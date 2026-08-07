<?php

declare(strict_types=1);

namespace app\repository\contracts;

use app\model\LeadField;

interface FieldRepositoryInterface
{
    public function findById(int $id): ?LeadField;

    public function findByAlias(string $alias): ?LeadField;

    public function create(array $data): LeadField;

    public function update(int $id, array $data): bool;

    public function delete(int $id): bool;

    /** 全部字段定义（按 field_order 升序） */
    public function listAll(bool $onlyPublished = true): \think\Collection;

    /** 按分组返回字段定义，key 为 field_group */
    public function listGrouped(bool $onlyPublished = true): array;

    /**
     * @return array{list: \think\Collection, total: int, page: int, page_size: int}
     */
    public function paginate(array $filters, int $page, int $pageSize): array;
}
