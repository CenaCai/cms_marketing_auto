<?php

declare(strict_types=1);

namespace app\repository;

use app\model\LeadField;
use app\repository\contracts\FieldRepositoryInterface;
use think\Collection;

final class FieldRepository extends BaseRepository implements FieldRepositoryInterface
{
    private const ORDERABLE = ['id', 'field_order', 'label', 'alias', 'field_group', 'type'];

    public function findById(int $id): ?LeadField
    {
        return LeadField::find($id);
    }

    public function findByAlias(string $alias): ?LeadField
    {
        return LeadField::where('alias', $alias)->find();
    }

    public function create(array $data): LeadField
    {
        $model = new LeadField();
        $model->save($data);

        return $model;
    }

    public function update(int $id, array $data): bool
    {
        $model = LeadField::find($id);
        if ($model === null) {
            return false;
        }

        return (bool) $model->save($data);
    }

    public function delete(int $id): bool
    {
        return (bool) LeadField::destroy($id);
    }

    public function listAll(bool $onlyPublished = true): Collection
    {
        $query = LeadField::newQuery();
        if ($onlyPublished) {
            $query->where('is_published', 1);
        }

        return $query->order('field_order', 'asc')->order('id', 'asc')->select();
    }

    public function listGrouped(bool $onlyPublished = true): array
    {
        $grouped = [];
        foreach ($this->listAll($onlyPublished) as $field) {
            $grouped[(string) ($field->field_group ?? 'core')][] = $field;
        }

        return $grouped;
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        [$orderField, $orderDir] = $this->resolveOrder($filters, self::ORDERABLE, 'field_order', 'asc');

        $builder = function () use ($filters, $orderField, $orderDir) {
            $query = LeadField::newQuery();

            if ($this->present($filters, 'keyword')) {
                $kw = '%' . str_replace(['%', '_'], ['\%', '\_'], (string) $filters['keyword']) . '%';
                $query->where(function ($q) use ($kw) {
                    $q->whereLike('label', $kw)->whereOr('alias', 'like', $kw);
                });
            }

            if ($this->present($filters, 'field_group')) {
                $query->where('field_group', (string) $filters['field_group']);
            }

            if ($this->present($filters, 'type')) {
                $query->where('type', (string) $filters['type']);
            }

            if (isset($filters['is_published']) && $filters['is_published'] !== '') {
                $query->where('is_published', (int) (bool) $filters['is_published']);
            }

            return $query->order($orderField, $orderDir);
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }
}
