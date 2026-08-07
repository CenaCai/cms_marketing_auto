<?php

declare(strict_types=1);

namespace app\repository\contracts;

use app\model\Lead;

interface LeadRepositoryInterface
{
    public function findById(int $id): ?Lead;

    public function create(array $data): Lead;

    public function update(int $id, array $data): bool;

    public function delete(int $id): bool;

    /**
     * @return array{list: \think\model\Collection, total: int, page: int, page_size: int}
     */
    public function paginate(array $filters, int $page, int $pageSize): array;

    /** 同步联系人标签（覆盖式） */
    public function syncTags(int $leadId, array $tagIds): void;
}
