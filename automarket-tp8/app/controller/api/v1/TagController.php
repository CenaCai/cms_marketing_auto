<?php

declare(strict_types=1);

namespace app\controller\api\v1;

use app\controller\api\BaseApiController;
use app\service\TagService;
use app\validate\TagValidate;
use think\App;
use think\Response;

/**
 * 标签 API  /api/v1/tags
 */
class TagController extends BaseApiController
{
    public function __construct(App $app, private readonly TagService $service)
    {
        parent::__construct($app);
    }

    public function index(): Response
    {
        [$page, $pageSize] = $this->pageParams();
        $filters = $this->only(['keyword', 'order_by', 'order_dir']);

        return $this->paged($this->service->paginate($filters, $page, $pageSize));
    }

    public function read(int $id): Response
    {
        $tag = $this->service->detail($id);

        return $this->ok($tag->toArray() + ['lead_count' => $this->service->countLeads($id)]);
    }

    public function save(): Response
    {
        $data = $this->only(['tag', 'description']);
        validate(TagValidate::class)->scene('create')->check($data);

        return $this->ok($this->service->create($data)->toArray(), '创建成功');
    }

    public function update(int $id): Response
    {
        $data = $this->only(['tag', 'description']);
        validate(TagValidate::class)->scene('update')->check($data);

        return $this->ok($this->service->update($id, $data)->toArray(), '更新成功');
    }

    public function delete(int $id): Response
    {
        $this->service->delete($id);

        return $this->ok(null, '删除成功');
    }
}
