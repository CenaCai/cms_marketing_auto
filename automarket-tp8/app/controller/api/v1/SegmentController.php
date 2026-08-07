<?php

declare(strict_types=1);

namespace app\controller\api\v1;

use app\controller\api\BaseApiController;
use app\resources\LeadResource;
use app\service\SegmentService;
use app\validate\SegmentValidate;
use think\App;
use think\Response;

/**
 * 分群 API  /api/v1/segments
 */
class SegmentController extends BaseApiController
{
    private const WRITABLE = [
        'name', 'alias', 'public_name', 'description', 'filters',
        'is_published', 'is_global', 'is_preference_center', 'category_id',
    ];

    public function __construct(App $app, private readonly SegmentService $service)
    {
        parent::__construct($app);
    }

    public function index(): Response
    {
        [$page, $pageSize] = $this->pageParams();
        $filters = $this->only(['keyword', 'is_published', 'is_global', 'order_by', 'order_dir']);

        return $this->paged($this->service->paginate($filters, $page, $pageSize));
    }

    public function read(int $id): Response
    {
        $segment = $this->service->detail($id);

        return $this->ok($segment->toArray() + $this->service->preview($id));
    }

    public function save(): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(SegmentValidate::class)->scene('create')->check($data);

        return $this->ok($this->service->create($data)->toArray(), '创建成功');
    }

    public function update(int $id): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(SegmentValidate::class)->scene('update')->check($data);

        return $this->ok($this->service->update($id, $data)->toArray(), '更新成功');
    }

    public function delete(int $id): Response
    {
        $this->service->delete($id);

        return $this->ok(null, '删除成功');
    }

    /** GET /api/v1/segments/:id/members */
    public function members(int $id): Response
    {
        [$page, $pageSize] = $this->pageParams();

        return $this->paged(
            $this->service->members($id, $page, $pageSize),
            [LeadResource::class, 'brief']
        );
    }

    /** POST /api/v1/segments/:id/members  body: {ids:[1,2]} */
    public function addMembers(int $id): Response
    {
        $count = $this->service->addMembers($id, $this->idsParam());

        return $this->ok(['affected' => $count], '已加入分群');
    }

    /** DELETE /api/v1/segments/:id/members  body: {ids:[1,2]} */
    public function removeMembers(int $id): Response
    {
        $count = $this->service->removeMembers($id, $this->idsParam());

        return $this->ok(['affected' => $count], '已移出分群');
    }

    /** POST /api/v1/segments/:id/rebuild —— 对应 mautic:segments:update */
    public function rebuild(int $id): Response
    {
        return $this->ok($this->service->rebuild($id), '分群已重建');
    }

    /** GET /api/v1/segments/:id/preview —— 干跑，只算命中数 */
    public function preview(int $id): Response
    {
        return $this->ok($this->service->preview($id));
    }
}
