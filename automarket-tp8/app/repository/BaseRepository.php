<?php

declare(strict_types=1);

namespace app\repository;

use think\Collection;

/**
 * Repository 基类：仅提供分页包装与筛选辅助，不含业务判断。
 */
abstract class BaseRepository
{
    protected const MAX_PAGE_SIZE = 200;

    /**
     * 统一分页包装。
     *
     * @param callable():\think\db\Query $builder 每次调用返回一个全新的查询对象（避免 clone 语义问题）
     *
     * @return array{list: Collection, total: int, page: int, page_size: int}
     */
    protected function paginateQuery(callable $builder, int $page, int $pageSize): array
    {
        $page     = max(1, $page);
        $pageSize = min(self::MAX_PAGE_SIZE, max(1, $pageSize));

        $total = (int) $builder()->count();
        $list  = $total > 0
            ? $builder()->page($page, $pageSize)->select()
            : new Collection([]);

        return [
            'list'      => $list,
            'total'     => $total,
            'page'      => $page,
            'page_size' => $pageSize,
        ];
    }

    /**
     * 安全排序：仅允许白名单字段，防止 SQL 注入与全表扫描。
     *
     * @return array{0: string, 1: string} [field, direction]
     */
    protected function resolveOrder(array $filters, array $allowed, string $default = 'id', string $defaultDir = 'desc'): array
    {
        $field = (string) ($filters['order_by'] ?? $default);
        if (!in_array($field, $allowed, true)) {
            $field = $default;
        }

        $dir = strtolower((string) ($filters['order_dir'] ?? $defaultDir));

        return [$field, $dir === 'asc' ? 'asc' : 'desc'];
    }

    /** 过滤空值（保留 0 与 '0'） */
    protected function present(array $filters, string $key): bool
    {
        return isset($filters[$key]) && $filters[$key] !== '' && $filters[$key] !== null;
    }
}
