<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\repository\contracts\TagRepositoryInterface;
use think\facade\Db;

/**
 * 分群过滤器编译器：把 Mautic 的 filters DSL 编译成 SQL 条件。
 *
 * 单条过滤器结构（与 Mautic 完全一致）：
 *   ['object'=>'lead','glue'=>'and|or','field'=>'points','type'=>'number',
 *    'filter'=>'20','operator'=>'gte','display'=>'...']
 *
 * 相对 Mautic 的两点修正：
 *  1. tags 过滤器同时接受「标签 ID」与「标签名」（Mautic 只认 ID，传名字会静默匹配 0 人）；
 *  2. 引用不存在的字段时显式抛错，而不是静默返回空集。
 */
final class SegmentFilterCompiler
{
    /** 虚拟字段 -> leads 实际列 */
    private const FIELD_ALIAS = [
        'stage'      => 'stage_id',
        'owner'      => 'owner_id',
        'date_added' => 'date_added',
    ];

    /** leads 表真实列缓存 */
    private ?array $columns = null;

    public function __construct(
        private readonly TagRepositoryInterface $tags,
    ) {
    }

    /**
     * 编译过滤器为 SQL 片段。
     *
     * @return array{0: string, 1: array} [whereSql, binds]；无过滤器时返回 ['', []]
     */
    public function compile(array $filters): array
    {
        $parts = [];
        $binds = [];

        foreach (array_values($filters) as $index => $filter) {
            if (!is_array($filter) || !isset($filter['field'])) {
                continue;
            }

            [$sql, $bind] = $this->compileOne($filter);
            if ($sql === '') {
                continue;
            }

            $glue = strtolower((string) ($filter['glue'] ?? 'and'));
            $glue = $glue === 'or' ? 'OR' : 'AND';

            $parts[] = ($parts === [] ? '' : $glue . ' ') . $sql;
            $binds   = array_merge($binds, $bind);

            unset($index);
        }

        return [implode(' ', $parts), $binds];
    }

    /** 返回命中该分群的联系人 ID 列表 */
    public function matchLeadIds(array $filters): array
    {
        [$sql, $binds] = $this->compile($filters);

        $query = Db::name('leads')->alias('l');
        if ($sql !== '') {
            $query->whereRaw($sql, $binds);
        }

        return array_map('intval', $query->column('l.id'));
    }

    // ------------------------------------------------------------------

    /** @return array{0: string, 1: array} */
    private function compileOne(array $filter): array
    {
        $field    = (string) $filter['field'];
        $operator = strtolower((string) ($filter['operator'] ?? '='));
        $value    = $filter['filter'] ?? null;
        $type     = strtolower((string) ($filter['type'] ?? 'text'));

        if ($field === 'tags') {
            return $this->compileTags($operator, $value);
        }

        $column = self::FIELD_ALIAS[$field] ?? $field;
        $this->assertColumn($column, $field);

        $col = 'l.`' . $column . '`';

        return match ($operator) {
            'empty'          => ["($col IS NULL OR $col = '')", []],
            '!empty', 'not_empty' => ["($col IS NOT NULL AND $col <> '')", []],
            'in'             => $this->compileIn($col, $value, false),
            '!in', 'not_in'  => $this->compileIn($col, $value, true),
            'like'           => ["$col LIKE ?", ['%' . $value . '%']],
            '!like', 'not_like' => ["($col IS NULL OR $col NOT LIKE ?)", ['%' . $value . '%']],
            'startswith'     => ["$col LIKE ?", [$value . '%']],
            'endswith'       => ["$col LIKE ?", ['%' . $value]],
            'between'        => $this->compileBetween($col, $value, false),
            '!between'       => $this->compileBetween($col, $value, true),
            'gt'             => ["$col > ?",  [$this->castValue($value, $type)]],
            'gte', '>='      => ["$col >= ?", [$this->castValue($value, $type)]],
            'lt'             => ["$col < ?",  [$this->castValue($value, $type)]],
            'lte', '<='      => ["$col <= ?", [$this->castValue($value, $type)]],
            'neq', '!='      => ["($col IS NULL OR $col <> ?)", [$this->castValue($value, $type)]],
            'eq', '='        => ["$col = ?",  [$this->castValue($value, $type)]],
            default          => throw BusinessException::of(
                ErrorCode::PARAM_INVALID,
                "分群过滤器不支持的操作符：{$operator}（字段 {$field}）"
            ),
        };
    }

    /** tags 过滤：EXISTS / NOT EXISTS 子查询 */
    private function compileTags(string $operator, mixed $value): array
    {
        $tagIds = $this->resolveTagIds((array) $value);

        if ($tagIds === []) {
            // 空标签集：in 恒假、!in 恒真
            return in_array($operator, ['!in', 'not_in'], true) ? ['1 = 1', []] : ['1 = 0', []];
        }

        $placeholders = implode(',', array_fill(0, count($tagIds), '?'));
        $sub          = "SELECT 1 FROM `lead_tags_xref` x WHERE x.lead_id = l.id AND x.tag_id IN ($placeholders)";

        return match ($operator) {
            'in', '='            => ["EXISTS ($sub)", $tagIds],
            '!in', 'not_in', '!=' => ["NOT EXISTS ($sub)", $tagIds],
            default              => throw BusinessException::of(
                ErrorCode::PARAM_INVALID,
                "tags 过滤器不支持的操作符：{$operator}"
            ),
        };
    }

    /** 标签值兼容 ID 与名称两种写法 */
    private function resolveTagIds(array $values): array
    {
        $ids   = [];
        $names = [];

        foreach ($values as $v) {
            if (is_int($v) || (is_string($v) && ctype_digit($v))) {
                $ids[] = (int) $v;
            } elseif (is_string($v) && trim($v) !== '') {
                $names[] = trim($v);
            }
        }

        if ($names !== []) {
            foreach ($this->tags->idsByTags($names) as $id) {
                $ids[] = (int) $id;
            }
        }

        return array_values(array_unique($ids));
    }

    private function compileIn(string $col, mixed $value, bool $negate): array
    {
        $values = array_values(array_filter((array) $value, static fn ($v): bool => $v !== '' && $v !== null));
        if ($values === []) {
            return [$negate ? '1 = 1' : '1 = 0', []];
        }

        $placeholders = implode(',', array_fill(0, count($values), '?'));

        return $negate
            ? ["($col IS NULL OR $col NOT IN ($placeholders))", $values]
            : ["$col IN ($placeholders)", $values];
    }

    private function compileBetween(string $col, mixed $value, bool $negate): array
    {
        $values = array_values((array) $value);
        if (count($values) < 2) {
            throw BusinessException::of(ErrorCode::PARAM_INVALID, 'between 过滤器需要两个值');
        }

        return [$negate ? "$col NOT BETWEEN ? AND ?" : "$col BETWEEN ? AND ?", [$values[0], $values[1]]];
    }

    /**
     * 值转换。日期类型支持 Mautic 的相对写法：
     *   '-90 days' / '-90'（等价 -90 天）/ 'today' / '2026-01-01'
     */
    private function castValue(mixed $value, string $type): mixed
    {
        if (!in_array($type, ['date', 'datetime'], true)) {
            return is_bool($value) ? (int) $value : $value;
        }

        $raw = trim((string) $value);
        if ($raw === '') {
            return $raw;
        }

        // 纯数字（含负号）视为「N 天」
        if (preg_match('/^-?\d+$/', $raw) === 1) {
            $raw .= ' days';
        }

        $ts = strtotime($raw);
        if ($ts === false) {
            throw BusinessException::of(ErrorCode::PARAM_INVALID, "无法解析日期过滤值：{$value}");
        }

        return $type === 'date' ? date('Y-m-d', $ts) : date('Y-m-d H:i:s', $ts);
    }

    private function assertColumn(string $column, string $originalField): void
    {
        $this->columns ??= array_map(
            static fn (array $c): string => $c['Field'],
            Db::query('SHOW COLUMNS FROM `leads`')
        );

        if (!in_array($column, $this->columns, true)) {
            throw BusinessException::of(
                ErrorCode::PARAM_INVALID,
                "分群过滤器引用了不存在的字段：{$originalField}"
            );
        }
    }
}
