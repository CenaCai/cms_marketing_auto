<?php

declare(strict_types=1);

namespace app\repository;

use app\model\Lead;
use app\model\LeadList;
use app\repository\contracts\SegmentRepositoryInterface;
use think\facade\Db;

final class SegmentRepository extends BaseRepository implements SegmentRepositoryInterface
{
    private const ORDERABLE = ['id', 'name', 'alias', 'date_added', 'last_built_date'];

    public function findById(int $id): ?LeadList
    {
        return LeadList::whereNull('deleted')->where('id', $id)->find();
    }

    public function findByAlias(string $alias): ?LeadList
    {
        return LeadList::whereNull('deleted')->where('alias', $alias)->find();
    }

    public function create(array $data): LeadList
    {
        $model = new LeadList();
        $model->save($data);

        return $model;
    }

    public function update(int $id, array $data): bool
    {
        $model = $this->findById($id);
        if ($model === null) {
            return false;
        }

        return (bool) $model->save($data);
    }

    /** Mautic 语义：分群为软删除（写 deleted 时间戳） */
    public function delete(int $id): bool
    {
        $model = $this->findById($id);
        if ($model === null) {
            return false;
        }

        return (bool) $model->save(['deleted' => date('Y-m-d H:i:s')]);
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        [$orderField, $orderDir] = $this->resolveOrder($filters, self::ORDERABLE);

        $builder = function () use ($filters, $orderField, $orderDir) {
            $query = LeadList::whereNull('deleted');

            if ($this->present($filters, 'keyword')) {
                $kw = '%' . str_replace(['%', '_'], ['\%', '\_'], (string) $filters['keyword']) . '%';
                $query->where(function ($q) use ($kw) {
                    $q->whereLike('name', $kw)->whereOr('alias', 'like', $kw);
                });
            }

            if (isset($filters['is_published']) && $filters['is_published'] !== '') {
                $query->where('is_published', (int) (bool) $filters['is_published']);
            }

            if (isset($filters['is_global']) && $filters['is_global'] !== '') {
                $query->where('is_global', (int) (bool) $filters['is_global']);
            }

            return $query->order($orderField, $orderDir);
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }

    public function paginateMembers(int $segmentId, int $page, int $pageSize): array
    {
        $builder = static function () use ($segmentId) {
            return Lead::with(['stage', 'tags'])
                ->alias('l')
                ->join('lead_lists_leads ll', 'll.lead_id = l.id')
                ->where('ll.leadlist_id', $segmentId)
                ->where('ll.manually_removed', 0)
                ->field('l.*')
                ->order('ll.date_added', 'desc');
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }

    public function addMembers(int $segmentId, array $leadIds): int
    {
        $leadIds = array_values(array_unique(array_filter(array_map('intval', $leadIds))));
        if ($leadIds === []) {
            return 0;
        }

        $exists = Db::name('lead_lists_leads')
            ->where('leadlist_id', $segmentId)
            ->whereIn('lead_id', $leadIds)
            ->column('lead_id');

        $now      = date('Y-m-d H:i:s');
        $affected = 0;

        // 已存在的：撤销手动移除标记
        if ($exists !== []) {
            $affected += Db::name('lead_lists_leads')
                ->where('leadlist_id', $segmentId)
                ->whereIn('lead_id', $exists)
                ->update(['manually_removed' => 0, 'manually_added' => 1]);
        }

        $new = array_values(array_diff($leadIds, array_map('intval', $exists)));
        if ($new !== []) {
            $rows = array_map(
                static fn (int $leadId): array => [
                    'leadlist_id'      => $segmentId,
                    'lead_id'          => $leadId,
                    'date_added'       => $now,
                    'manually_removed' => 0,
                    'manually_added'   => 1,
                ],
                $new
            );
            $affected += Db::name('lead_lists_leads')->insertAll($rows);
        }

        return $affected;
    }

    public function removeMembers(int $segmentId, array $leadIds): int
    {
        $leadIds = array_values(array_unique(array_filter(array_map('intval', $leadIds))));
        if ($leadIds === []) {
            return 0;
        }

        return Db::name('lead_lists_leads')
            ->where('leadlist_id', $segmentId)
            ->whereIn('lead_id', $leadIds)
            ->update(['manually_removed' => 1, 'manually_added' => 0]);
    }

    public function countMembers(int $segmentId): int
    {
        return (int) Db::name('lead_lists_leads')
            ->where('leadlist_id', $segmentId)
            ->where('manually_removed', 0)
            ->count();
    }
}
