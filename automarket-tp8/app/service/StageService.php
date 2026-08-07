<?php

declare(strict_types=1);

namespace app\service;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\model\Stage;
use app\repository\contracts\StageRepositoryInterface;

/**
 * 阶段（漏斗）业务服务
 */
final class StageService
{
    public function __construct(
        private readonly StageRepositoryInterface $stages,
    ) {
    }

    public function paginate(array $filters, int $page, int $pageSize): array
    {
        return $this->stages->paginate($filters, $page, $pageSize);
    }

    public function detail(int $id): Stage
    {
        $stage = $this->stages->findById($id);
        if ($stage === null) {
            throw BusinessException::of(ErrorCode::STAGE_NOT_FOUND);
        }

        return $stage;
    }

    public function create(array $data): Stage
    {
        $data['is_published'] = (int) (bool) ($data['is_published'] ?? true);
        $data['weight']       = (int) ($data['weight'] ?? 0);

        return $this->stages->create($data);
    }

    public function update(int $id, array $data): Stage
    {
        $this->detail($id);
        $this->stages->update($id, $data);

        return $this->detail($id);
    }

    public function delete(int $id): bool
    {
        $this->detail($id);

        return $this->stages->delete($id);
    }

    /**
     * 漏斗视图：阶段列表 + 各阶段人数 + 相对转化率。
     *
     * @return array<int, array{id:int,name:string,weight:int,count:int,rate:float}>
     */
    public function funnel(): array
    {
        $stages = $this->stages->listAll();
        $counts = $this->stages->leadCountByStage();

        $funnel = [];
        $prev   = null;

        foreach ($stages as $stage) {
            $id    = (int) $stage->id;
            $count = $counts[$id] ?? 0;

            $funnel[] = [
                'id'     => $id,
                'name'   => (string) $stage->name,
                'weight' => (int) $stage->weight,
                'count'  => $count,
                // 相对上一阶段的转化率（首个阶段为 100%）
                'rate'   => $prev === null
                    ? 100.0
                    : ($prev > 0 ? round($count / $prev * 100, 2) : 0.0),
            ];

            $prev = $count;
        }

        return $funnel;
    }
}
