<?php

declare(strict_types=1);

namespace app\repository;

use app\model\LeadTag;
use app\repository\contracts\TagRepositoryInterface;
use think\facade\Db;

final class TagRepository extends BaseRepository implements TagRepositoryInterface
{
    private const ORDERABLE = ['id', 'tag'];

    public function findById(int $id): ?LeadTag
    {
        return LeadTag::find($id);
    }

    public function findByTag(string $tag): ?LeadTag
    {
        return LeadTag::where('tag', $tag)->find();
    }

    public function create(array $data): LeadTag
    {
        $model = new LeadTag();
        $model->save($data);

        return $model;
    }

    public function update(int $id, array $data): bool
    {
        $model = LeadTag::find($id);
        if ($model === null) {
            return false;
        }

        return (bool) $model->save($data);
    }

    public function delete(int $id): bool
    {
        // lead_tags_xref 对 tag_id 无 CASCADE，需先解除关联
        Db::name('lead_tags_xref')->where('tag_id', $id)->delete();

        return (bool) LeadTag::destroy($id);
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        [$orderField, $orderDir] = $this->resolveOrder($filters, self::ORDERABLE, 'tag', 'asc');

        $builder = function () use ($filters, $orderField, $orderDir) {
            $query = LeadTag::newQuery();

            if ($this->present($filters, 'keyword')) {
                $kw = '%' . str_replace(['%', '_'], ['\%', '\_'], (string) $filters['keyword']) . '%';
                $query->whereLike('tag', $kw);
            }

            return $query->order($orderField, $orderDir);
        };

        return $this->paginateQuery($builder, $page, $pageSize);
    }

    public function idsByTags(array $tags): array
    {
        $tags = array_values(array_filter(array_map('strval', $tags), static fn ($t) => $t !== ''));
        if ($tags === []) {
            return [];
        }

        return LeadTag::whereIn('tag', $tags)->column('id', 'tag');
    }

    public function countLeads(int $id): int
    {
        return (int) Db::name('lead_tags_xref')->where('tag_id', $id)->count();
    }
}
