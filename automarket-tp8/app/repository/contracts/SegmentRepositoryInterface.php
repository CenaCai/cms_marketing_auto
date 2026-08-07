<?php

declare(strict_types=1);

namespace app\repository\contracts;

use app\model\LeadList;

interface SegmentRepositoryInterface
{
    public function findById(int $id): ?LeadList;

    public function findByAlias(string $alias): ?LeadList;

    public function create(array $data): LeadList;

    public function update(int $id, array $data): bool;

    public function delete(int $id): bool;

    /**
     * @return array{list: \think\Collection, total: int, page: int, page_size: int}
     */
    public function paginate(array $filters, int $page, int $pageSize): array;

    /**
     * 分群成员分页
     *
     * @return array{list: \think\Collection, total: int, page: int, page_size: int}
     */
    public function paginateMembers(int $segmentId, int $page, int $pageSize): array;

    /** 手动加入分群（manually_added=1） */
    public function addMembers(int $segmentId, array $leadIds): int;

    /** 手动移出分群（manually_removed=1） */
    public function removeMembers(int $segmentId, array $leadIds): int;

    public function countMembers(int $segmentId): int;
}
