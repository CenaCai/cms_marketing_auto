<?php

declare(strict_types=1);

namespace app\repository\contracts;

use app\model\LeadTag;

interface TagRepositoryInterface
{
    public function findById(int $id): ?LeadTag;

    public function findByTag(string $tag): ?LeadTag;

    public function create(array $data): LeadTag;

    public function update(int $id, array $data): bool;

    public function delete(int $id): bool;

    /**
     * @return array{list: \think\Collection, total: int, page: int, page_size: int}
     */
    public function paginate(array $filters, int $page, int $pageSize): array;

    /** 批量按名称取标签 ID（不存在的返回空缺） */
    public function idsByTags(array $tags): array;

    /** 统计标签下联系人数量 */
    public function countLeads(int $id): int;
}
