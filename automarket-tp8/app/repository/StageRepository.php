<?php

declare(strict_types=1);

namespace app\repository;

use app\model\Stage;
use app\repository\contracts\StageRepositoryInterface;
use think\Collection;
use think\facade\Db;

final class StageRepository extends BaseRepository implements StageRepositoryInterface
{
    private const ORDERABLE = ['id', 'weight', 'name', 'date_added'];

    public function findById(int $id): ?Stage
    {
        return Stage::find($id);
    }

    public function create(array $data): Stage
    {
        $model = new Stage();
        $model->save($data);

        return $model;
    }

    public function update(int $id, array $data): bool
    {
        $model = Stage::find($id);
        if ($model === null) {
            return false;
        }

        return (bool) $model->save($data);
    }

    public function delete(int $id): bool
    {
        // leads.stage_id 外键为 SET NULL，直接删除即可
        return (bool) Stage::destroy($id);
    }

    public function listAll(bool $onlyPublished = true): Collection
    {
        $query = Stage::newQuery();
        if ($onlyPublished) {
            $query->where('is_published', 1);
        }

        return $query->order('weight', 'asc')->order('id', 'asc')->select();
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        [$orderField, $orderDir] = $this->resolveOrder($filters, self::ORDERABLE, 'weight', 'asc');

        $builder = function () use ($filters, $orderField, $orderDir) {
            $query = Stage::newQuery();

            if ($this->present($filters, 'keyword')) {
                $kw = '%' . str_replace(['%', '_'], ['\%', '\_'], (string) $filters['keyword']) . '%';
                $query->whereLike('name', $kw);
            }

            if (isset($filters['is_published']) && $filters['is_published'] !== '') {
                $query->where('is_published', (int) (bool) $filters['is_published']);
            }

            return $query->order($orderField, $orderDir);
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }

    public function leadCountByStage(): array
    {
        $rows = Db::name('leads')
            ->field('stage_id, COUNT(*) AS cnt')
            ->whereNotNull('stage_id')
            ->group('stage_id')
            ->select()
            ->toArray();

        $result = [];
        foreach ($rows as $row) {
            $result[(int) $row['stage_id']] = (int) $row['cnt'];
        }

        return $result;
    }
}
