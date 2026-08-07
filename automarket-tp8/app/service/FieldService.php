<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\model\LeadField;
use app\repository\contracts\FieldRepositoryInterface;

/**
 * 自定义字段业务服务（对应 Mautic FieldModel）
 *
 * ⚠️ 复刻 Mautic 的关键约束：select / multiselect 类型的 properties['list']
 *    必须是 [['label'=>..,'value'=>..], ...] 结构。旧版纯字符串数组会导致
 *    Mautic 端 validateSelectFields() 抛 TypeError，这里在写入时统一规整。
 */
final class FieldService
{
    private const CHOICE_TYPES = ['select', 'multiselect', 'boolean', 'radio', 'checkbox'];

    public function __construct(
        private readonly FieldRepositoryInterface $fields,
    ) {
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        return $this->fields->paginate($filters, $page, $pageSize);
    }

    public function detail(int $id): LeadField
    {
        $field = $this->fields->findById($id);
        if ($field === null) {
            throw BusinessException::of(ErrorCode::FIELD_NOT_FOUND);
        }

        return $field;
    }

    public function listGrouped(bool $onlyPublished = true): array
    {
        return $this->fields->listGrouped($onlyPublished);
    }

    public function create(array $data): LeadField
    {
        $alias = trim((string) ($data['alias'] ?? ''));
        if ($alias === '') {
            throw BusinessException::of(ErrorCode::PARAM_INVALID, '字段别名不能为空');
        }

        if ($this->fields->findByAlias($alias) !== null) {
            throw BusinessException::of(ErrorCode::FIELD_ALIAS_DUP);
        }

        $data['alias']      = $alias;
        $data['object']   ??= 'lead';
        $data['properties'] = $this->normalizeProperties($data);

        foreach (['is_published' => true, 'is_required' => false, 'is_fixed' => false,
                  'is_visible' => true, 'is_listable' => true, 'is_publicly_updatable' => false] as $key => $default) {
            $data[$key] = (int) (bool) ($data[$key] ?? $default);
        }

        return $this->fields->create($data);
    }

    public function update(int $id, array $data): LeadField
    {
        $field = $this->detail($id);

        if (isset($data['alias'])) {
            $alias    = trim((string) $data['alias']);
            $existing = $this->fields->findByAlias($alias);
            if ($existing !== null && (int) $existing->id !== $id) {
                throw BusinessException::of(ErrorCode::FIELD_ALIAS_DUP);
            }
            $data['alias'] = $alias;
        }

        if (array_key_exists('properties', $data)) {
            $data['properties'] = $this->normalizeProperties([
                'type'       => $data['type'] ?? $field->type,
                'properties' => $data['properties'],
            ]);
        }

        $this->fields->update($id, $data);

        return $this->detail($id);
    }

    public function delete(int $id): bool
    {
        $field = $this->detail($id);

        if ((bool) $field->is_fixed) {
            throw BusinessException::of(ErrorCode::FORBIDDEN, '系统固定字段不可删除');
        }

        return $this->fields->delete($id);
    }

    // ------------------------------------------------------------------

    /**
     * 规整 properties，重点是 select 系列的 list 结构。
     * 支持三种输入：
     *   ['a','b']                       -> [['label'=>'a','value'=>'a'], ...]
     *   ['a'=>'甲','b'=>'乙']            -> [['label'=>'甲','value'=>'a'], ...]
     *   [['label'=>'甲','value'=>'a']]   -> 原样保留
     */
    private function normalizeProperties(array $data): array
    {
        $props = $data['properties'] ?? [];
        if (is_string($props)) {
            $decoded = json_decode($props, true);
            $props   = is_array($decoded) ? $decoded : [];
        }
        if (!is_array($props)) {
            $props = [];
        }

        $type = (string) ($data['type'] ?? 'text');
        if (!in_array($type, self::CHOICE_TYPES, true) || !isset($props['list'])) {
            return $props;
        }

        $list = $props['list'];
        if (is_string($list)) {
            $list = array_map('trim', explode('|', $list));
        }
        if (!is_array($list)) {
            return $props;
        }

        $normalized = [];
        foreach ($list as $key => $item) {
            if (is_array($item) && array_key_exists('value', $item)) {
                $normalized[] = [
                    'label' => (string) ($item['label'] ?? $item['value']),
                    'value' => (string) $item['value'],
                ];
                continue;
            }

            // 关联数组：key 为 value，值为 label；纯数组：值同时作为 label/value
            $isAssoc = !is_int($key);
            $normalized[] = [
                'label' => (string) $item,
                'value' => $isAssoc ? (string) $key : (string) $item,
            ];
        }

        $props['list'] = $normalized;

        return $props;
    }
}
