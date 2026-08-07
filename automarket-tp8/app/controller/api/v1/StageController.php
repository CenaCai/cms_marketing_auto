<?php

declare(strict_types=1);

namespace app\controller\api\v1;

use app\controller\api\BaseApiController;
use app\service\StageService;
use app\validate\StageValidate;
use think\App;
use think\Response;

/**
 * 阶段 API  /api/v1/stages
 */
class StageController extends BaseApiController
{
    public function __construct(App $app, private readonly StageService $service)
    {
        parent::__construct($app);
    }

    public function index(): Response
    {
        [$page, $pageSize] = $this->pageParams();
        $filters = $this->only(['keyword', 'is_published', 'order_by', 'order_dir']);

        return $this->paged($this->service->paginate($filters, $page, $pageSize));
    }

    public function read(int $id): Response
    {
        return $this->ok($this->service->detail($id)->toArray());
    }

    public function save(): Response
    {
        $data = $this->only(['name', 'description', 'weight', 'category_id',
                             'is_published', 'publish_up', 'publish_down']);
        validate(StageValidate::class)->scene('create')->check($data);

        return $this->ok($this->service->create($data)->toArray(), '创建成功');
    }

    public function update(int $id): Response
    {
        $data = $this->only(['name', 'description', 'weight', 'category_id',
                             'is_published', 'publish_up', 'publish_down']);
        validate(StageValidate::class)->scene('update')->check($data);

        return $this->ok($this->service->update($id, $data)->toArray(), '更新成功');
    }

    public function delete(int $id): Response
    {
        $this->service->delete($id);

        return $this->ok(null, '删除成功');
    }

    /** GET /api/v1/stages/funnel —— 漏斗视图（S0~S6 人数与转化率） */
    public function funnel(): Response
    {
        return $this->ok($this->service->funnel());
    }
}
