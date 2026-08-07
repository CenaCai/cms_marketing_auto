<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\model\Lead;
use app\repository\contracts\LeadRepositoryInterface;
use app\repository\contracts\StageRepositoryInterface;
use app\repository\contracts\TagRepositoryInterface;
use think\facade\Db;

/**
 * 联系人业务服务（对应 Mautic LeadModel 的核心能力）
 */
final class ContactService
{
    public function __construct(
        private readonly LeadRepositoryInterface $leads,
        private readonly TagRepositoryInterface $tags,
        private readonly StageRepositoryInterface $stages,
    ) {
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        return $this->leads->paginate($filters, $page, $pageSize);
    }

    public function detail(int $id): Lead
    {
        $lead = $this->leads->findById($id);
        if ($lead === null) {
            throw BusinessException::of(ErrorCode::LEAD_NOT_FOUND);
        }

        return $lead;
    }

    /**
     * 创建联系人。$data['tags'] 支持标签名数组（不存在则自动创建，与 Mautic 行为一致）。
     */
    public function create(array $data): Lead
    {
        $tagNames = $this->pullTags($data);
        $email    = $this->normalizeEmail($data);

        if ($email !== null && $this->emailExists($email, null)) {
            throw BusinessException::of(ErrorCode::LEAD_EMAIL_EXISTS);
        }

        if (isset($data['stage_id']) && $data['stage_id'] !== null) {
            $this->assertStageExists((int) $data['stage_id']);
        }

        $data['points']       = (int) ($data['points'] ?? 0);
        $data['is_published'] = (int) (bool) ($data['is_published'] ?? true);

        return Db::transaction(function () use ($data, $tagNames): Lead {
            $lead = $this->leads->create($data);

            if ($tagNames !== null) {
                $this->leads->syncTags((int) $lead->id, $this->resolveTagIds($tagNames));
            }

            return $this->leads->findById((int) $lead->id) ?? $lead;
        });
    }

    public function update(int $id, array $data): Lead
    {
        $lead     = $this->detail($id);
        $tagNames = $this->pullTags($data);
        $email    = $this->normalizeEmail($data);

        if ($email !== null && $this->emailExists($email, $id)) {
            throw BusinessException::of(ErrorCode::LEAD_EMAIL_EXISTS);
        }

        if (array_key_exists('stage_id', $data) && $data['stage_id'] !== null) {
            $this->assertStageExists((int) $data['stage_id']);
        }

        // 生成列不可写
        unset($data['generated_email_domain'], $data['id']);

        return Db::transaction(function () use ($id, $data, $tagNames, $lead): Lead {
            if ($data !== []) {
                $this->leads->update($id, $data);
            }

            if ($tagNames !== null) {
                $this->leads->syncTags($id, $this->resolveTagIds($tagNames));
            }

            return $this->leads->findById($id) ?? $lead;
        });
    }

    public function delete(int $id): bool
    {
        $this->detail($id);

        return $this->leads->delete($id);
    }

    /** 变更阶段 */
    public function changeStage(int $id, ?int $stageId): Lead
    {
        $this->detail($id);

        if ($stageId !== null) {
            $this->assertStageExists($stageId);
        }

        $this->leads->update($id, [
            'stage_id'        => $stageId,
            'stage_date'      => date('Y-m-d H:i:s'),
            'date_modified'   => date('Y-m-d H:i:s'),
        ]);

        return $this->detail($id);
    }

    /** 积分增减（P2 将接入积分变更日志） */
    public function adjustPoints(int $id, int $delta): Lead
    {
        $lead = $this->detail($id);

        $points = max(0, (int) $lead->points + $delta);
        $this->leads->update($id, ['points' => $points, 'date_modified' => date('Y-m-d H:i:s')]);

        return $this->detail($id);
    }

    /** 覆盖式设置标签（传标签名数组） */
    public function setTags(int $id, array $tagNames): Lead
    {
        $this->detail($id);
        $this->leads->syncTags($id, $this->resolveTagIds($tagNames));

        return $this->detail($id);
    }

    // ------------------------------------------------------------------
    // 内部辅助
    // ------------------------------------------------------------------

    /** 从入参中摘出 tags，返回 null 表示"本次不动标签" */
    private function pullTags(array &$data): ?array
    {
        if (!array_key_exists('tags', $data)) {
            return null;
        }

        $tags = $data['tags'];
        unset($data['tags']);

        if ($tags === null || $tags === '') {
            return [];
        }

        return is_array($tags) ? $tags : array_map('trim', explode(',', (string) $tags));
    }

    private function normalizeEmail(array &$data): ?string
    {
        if (!array_key_exists('email', $data) || $data['email'] === null || $data['email'] === '') {
            return null;
        }

        $email         = strtolower(trim((string) $data['email']));
        $data['email'] = $email;

        return $email;
    }

    private function emailExists(string $email, ?int $exceptId): bool
    {
        $query = Lead::where('email', $email);
        if ($exceptId !== null) {
            $query->where('id', '<>', $exceptId);
        }

        return $query->count() > 0;
    }

    private function assertStageExists(int $stageId): void
    {
        if ($this->stages->findById($stageId) === null) {
            throw BusinessException::of(ErrorCode::STAGE_NOT_FOUND);
        }
    }

    /** 标签名 -> ID，缺失的自动创建（Mautic 语义） */
    private function resolveTagIds(array $tagNames): array
    {
        $names = array_values(array_unique(array_filter(
            array_map(static fn ($t) => trim((string) $t), $tagNames),
            static fn (string $t): bool => $t !== ''
        )));

        if ($names === []) {
            return [];
        }

        $existing = $this->tags->idsByTags($names);
        $ids      = array_values(array_map('intval', $existing));

        foreach (array_diff($names, array_keys($existing)) as $newName) {
            $ids[] = (int) $this->tags->create(['tag' => $newName])->id;
        }

        return $ids;
    }
}
