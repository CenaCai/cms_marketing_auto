<?php

declare(strict_types=1);

namespace app\repository\contracts;

use app\model\Stage;

interface StageRepositoryInterface
{
    public function findById(int $id): ?Stage;

    public function create(array $data): Stage;

    public function update(int $id, array $data): bool;

    public function delete(int $id): bool;

    /** 全部阶段（按 weight 升序），用于漏斗展示 */
    public function listAll(bool $onlyPublished = true): \think\Collection;

    /**
     * @return array{list: \think\Collection, total: int, page: int, page_size: int}
     */
    public function paginate(array $filters, int $page, int $pageSize): array;

    /** 各阶段联系人数量 [stage_id => count] */
    public function leadCountByStage(): array;
}
