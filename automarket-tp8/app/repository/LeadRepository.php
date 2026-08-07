<?php

declare(strict_types=1);

namespace app\repository;

use app\model\Lead;
use app\repository\contracts\LeadRepositoryInterface;
use think\facade\Db;

final class LeadRepository extends BaseRepository implements LeadRepositoryInterface
{
    private const ORDERABLE = [
        'id', 'points', 'date_added', 'date_modified', 'last_active',
        'email', 'lastname', 'order_count', 'total_spent',
    ];

    public function findById(int $id): ?Lead
    {
        return Lead::with(['stage', 'owner', 'tags'])->find($id);
    }

    public function create(array $data): Lead
    {
        $lead = new Lead();
        $lead->save($data);

        return $lead;
    }

    public function update(int $id, array $data): bool
    {
        $lead = Lead::find($id);
        if ($lead === null) {
            return false;
        }

        return (bool) $lead->save($data);
    }

    public function delete(int $id): bool
    {
        // 中间表已配置 ON DELETE CASCADE，无需手动清理
        return (bool) Lead::destroy($id);
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        [$orderField, $orderDir] = $this->resolveOrder($filters, self::ORDERABLE);

        $builder = function () use ($filters, $orderField, $orderDir) {
            $query = Lead::with(['stage', 'tags']);

            if ($this->present($filters, 'keyword')) {
                $kw = '%' . str_replace(['%', '_'], ['\%', '\_'], (string) $filters['keyword']) . '%';
                $query->where(function ($q) use ($kw) {
                    $q->whereLike('email', $kw)
                        ->whereOr('firstname', 'like', $kw)
                        ->whereOr('lastname', 'like', $kw)
                        ->whereOr('company', 'like', $kw)
                        ->whereOr('mobile', 'like', $kw);
                });
            }

            if ($this->present($filters, 'stage_id')) {
                $query->where('stage_id', (int) $filters['stage_id']);
            }

            if ($this->present($filters, 'owner_id')) {
                $query->where('owner_id', (int) $filters['owner_id']);
            }

            if ($this->present($filters, 'country')) {
                $query->where('country', (string) $filters['country']);
            }

            if ($this->present($filters, 'source_primary')) {
                $query->where('source_primary', (string) $filters['source_primary']);
            }

            if ($this->present($filters, 'reply_intent')) {
                $query->where('reply_intent', (string) $filters['reply_intent']);
            }

            if (isset($filters['is_published']) && $filters['is_published'] !== '') {
                $query->where('is_published', (int) (bool) $filters['is_published']);
            }

            if ($this->present($filters, 'points_min')) {
                $query->where('points', '>=', (int) $filters['points_min']);
            }

            if ($this->present($filters, 'points_max')) {
                $query->where('points', '<=', (int) $filters['points_max']);
            }

            if ($this->present($filters, 'date_from')) {
                $query->where('date_added', '>=', (string) $filters['date_from']);
            }

            if ($this->present($filters, 'date_to')) {
                $query->where('date_added', '<=', (string) $filters['date_to']);
            }

            // 标签筛选（多选，AND 关系由调用方保证；此处为 OR-in）
            if (!empty($filters['tag_ids']) && is_array($filters['tag_ids'])) {
                $tagIds = array_values(array_filter(array_map('intval', $filters['tag_ids'])));
                if ($tagIds !== []) {
                    $leadIds = Db::name('lead_tags_xref')
                        ->whereIn('tag_id', $tagIds)
                        ->group('lead_id')
                        ->column('lead_id');
                    $query->whereIn('id', $leadIds ?: [0]);
                }
            }

            // 分群筛选
            if ($this->present($filters, 'segment_id')) {
                $leadIds = Db::name('lead_lists_leads')
                    ->where('leadlist_id', (int) $filters['segment_id'])
                    ->where('manually_removed', 0)
                    ->column('lead_id');
                $query->whereIn('id', $leadIds ?: [0]);
            }

            return $query->order($orderField, $orderDir);
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }

    public function syncTags(int $leadId, array $tagIds): void
    {
        $tagIds = array_values(array_unique(array_filter(array_map('intval', $tagIds))));

        Db::name('lead_tags_xref')->where('lead_id', $leadId)->delete();

        if ($tagIds === []) {
            return;
        }

        $rows = array_map(
            static fn (int $tagId): array => ['lead_id' => $leadId, 'tag_id' => $tagId],
            $tagIds
        );

        Db::name('lead_tags_xref')->insertAll($rows);
    }
}
