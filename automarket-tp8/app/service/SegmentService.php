<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\model\LeadList;
use app\repository\contracts\SegmentRepositoryInterface;
use think\facade\Db;

/**
 * 分群业务服务（对应 Mautic ListModel）
 */
final class SegmentService
{
    public function __construct(
        private readonly SegmentRepositoryInterface $segments,
        private readonly SegmentFilterCompiler $compiler,
    ) {
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        return $this->segments->paginate($filters, $page, $pageSize);
    }

    public function detail(int $id): LeadList
    {
        $segment = $this->segments->findById($id);
        if ($segment === null) {
            throw BusinessException::of(ErrorCode::SEGMENT_NOT_FOUND);
        }

        return $segment;
    }

    public function create(array $data): LeadList
    {
        $data['alias'] = $this->makeAlias($data, null);

        $data['filters']              = $this->normalizeFilters($data['filters'] ?? []);
        $data['public_name']        ??= (string) ($data['name'] ?? '');
        $data['is_published']         = (int) (bool) ($data['is_published'] ?? true);
        $data['is_global']            = (int) (bool) ($data['is_global'] ?? true);
        $data['is_preference_center'] = (int) (bool) ($data['is_preference_center'] ?? false);

        return $this->segments->create($data);
    }

    public function update(int $id, array $data): LeadList
    {
        $this->detail($id);

        if (isset($data['alias']) || isset($data['name'])) {
            $data['alias'] = $this->makeAlias($data, $id);
        }

        if (array_key_exists('filters', $data)) {
            $data['filters'] = $this->normalizeFilters($data['filters']);
        }

        $this->segments->update($id, $data);

        return $this->detail($id);
    }

    public function delete(int $id): bool
    {
        $this->detail($id);

        return $this->segments->delete($id);
    }

    public function members(int $id, int $page, int $pageSize): array
    {
        $this->detail($id);

        return $this->segments->paginateMembers($id, $page, $pageSize);
    }

    public function addMembers(int $id, array $leadIds): int
    {
        $this->detail($id);

        return $this->segments->addMembers($id, $leadIds);
    }

    public function removeMembers(int $id, array $leadIds): int
    {
        $this->detail($id);

        return $this->segments->removeMembers($id, $leadIds);
    }

    /**
     * 重建分群成员（对应 Mautic `mautic:segments:update`）。
     *
     * 规则与 Mautic 一致：
     *  - 命中过滤器且未被手动移除 -> 保留/新增
     *  - 未命中但为手动添加      -> 保留
     *  - 未命中且非手动添加      -> 移除
     *
     * @return array{matched:int,added:int,removed:int,total:int}
     */
    public function rebuild(int $id): array
    {
        $segment = $this->detail($id);
        $filters = $segment->filters ?: [];

        $matched = $filters === [] ? [] : $this->compiler->matchLeadIds($filters);

        $result = Db::transaction(function () use ($id, $matched): array {
            $existing = Db::name('lead_lists_leads')
                ->where('leadlist_id', $id)
                ->select()
                ->toArray();

            $existingMap = [];
            foreach ($existing as $row) {
                $existingMap[(int) $row['lead_id']] = $row;
            }

            $now   = date('Y-m-d H:i:s');
            $added = 0;

            // 1) 新增命中的联系人（跳过手动移除的）
            $toInsert = [];
            foreach ($matched as $leadId) {
                if (!isset($existingMap[$leadId])) {
                    $toInsert[] = [
                        'leadlist_id'      => $id,
                        'lead_id'          => $leadId,
                        'date_added'       => $now,
                        'manually_removed' => 0,
                        'manually_added'   => 0,
                    ];
                }
            }
            foreach (array_chunk($toInsert, 500) as $chunk) {
                $added += Db::name('lead_lists_leads')->insertAll($chunk);
            }

            // 2) 移除不再命中且非手动添加的联系人
            $matchedSet = array_flip($matched);
            $toRemove   = [];
            foreach ($existingMap as $leadId => $row) {
                if (!isset($matchedSet[$leadId]) && (int) $row['manually_added'] === 0) {
                    $toRemove[] = $leadId;
                }
            }

            $removed = 0;
            foreach (array_chunk($toRemove, 500) as $chunk) {
                $removed += Db::name('lead_lists_leads')
                    ->where('leadlist_id', $id)
                    ->whereIn('lead_id', $chunk)
                    ->delete();
            }

            return ['added' => $added, 'removed' => $removed];
        });

        $this->segments->update($id, [
            'last_built_date' => date('Y-m-d H:i:s'),
        ]);

        return [
            'matched' => count($matched),
            'added'   => $result['added'],
            'removed' => $result['removed'],
            'total'   => $this->segments->countMembers($id),
        ];
    }

    /** 干跑：只统计命中数量，不落库（用于后台预览） */
    public function preview(int $id): array
    {
        $segment = $this->detail($id);
        $filters = $segment->filters ?: [];
        $matched = $filters === [] ? [] : $this->compiler->matchLeadIds($filters);

        return [
            'matched' => count($matched),
            'current' => $this->segments->countMembers($id),
        ];
    }

    // ------------------------------------------------------------------

    private function normalizeFilters(mixed $filters): array
    {
        if (is_string($filters)) {
            $decoded = json_decode($filters, true);
            $filters = is_array($decoded) ? $decoded : [];
        }

        if (!is_array($filters)) {
            return [];
        }

        // 提前编译一次做语法校验，非法过滤器直接抛错
        $this->compiler->compile($filters);

        return array_values($filters);
    }

    private function makeAlias(array $data, ?int $exceptId): string
    {
        $alias = trim((string) ($data['alias'] ?? ''));
        if ($alias === '') {
            $alias = $this->slugify((string) ($data['name'] ?? ''));
        }

        if ($alias === '') {
            throw BusinessException::of(ErrorCode::PARAM_INVALID, '分群名称或别名不能为空');
        }

        $existing = $this->segments->findByAlias($alias);
        if ($existing !== null && (int) $existing->id !== $exceptId) {
            throw BusinessException::of(ErrorCode::SEGMENT_ALIAS_DUP);
        }

        return $alias;
    }

    private function slugify(string $text): string
    {
        $text = strtolower(trim($text));
        $text = preg_replace('/[^\p{L}\p{N}]+/u', '-', $text) ?? '';

        return trim($text, '-');
    }
}
