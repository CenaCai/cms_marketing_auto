<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\model\LeadTag;
use app\repository\contracts\TagRepositoryInterface;

final class TagService
{
    public function __construct(
        private readonly TagRepositoryInterface $tags,
    ) {
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        return $this->tags->paginate($filters, $page, $pageSize);
    }

    public function detail(int $id): LeadTag
    {
        $tag = $this->tags->findById($id);
        if ($tag === null) {
            throw BusinessException::of(ErrorCode::TAG_NOT_FOUND);
        }

        return $tag;
    }

    public function create(array $data): LeadTag
    {
        $name = trim((string) ($data['tag'] ?? ''));
        if ($this->tags->findByTag($name) !== null) {
            throw BusinessException::of(ErrorCode::TAG_EXISTS);
        }

        $data['tag'] = $name;

        return $this->tags->create($data);
    }

    public function update(int $id, array $data): LeadTag
    {
        $this->detail($id);

        if (isset($data['tag'])) {
            $name     = trim((string) $data['tag']);
            $existing = $this->tags->findByTag($name);
            if ($existing !== null && (int) $existing->id !== $id) {
                throw BusinessException::of(ErrorCode::TAG_EXISTS);
            }
            $data['tag'] = $name;
        }

        $this->tags->update($id, $data);

        return $this->detail($id);
    }

    public function delete(int $id): bool
    {
        $this->detail($id);

        return $this->tags->delete($id);
    }

    public function countLeads(int $id): int
    {
        $this->detail($id);

        return $this->tags->countLeads($id);
    }
}
