<?php

declare(strict_types=1);

namespace app\controller\api\v1;

use app\controller\api\BaseApiController;
use app\resources\LeadResource;
use app\service\ContactService;
use app\validate\ContactValidate;
use think\App;
use think\Response;

/**
 * 联系人 API  /api/v1/contacts
 */
class ContactController extends BaseApiController
{
    private const WRITABLE = [
        'email', 'firstname', 'lastname', 'company', 'position', 'title',
        'phone', 'mobile', 'address1', 'address2', 'city', 'state', 'zipcode',
        'country', 'timezone', 'preferred_locale', 'website',
        'stage_id', 'owner_id', 'points', 'is_published', 'tags',
        'order_count', 'total_spent', 'order_status', 'departure_date',
        'behavior_type', 'form_type', 'consult_type', 'source_detail',
        'source_primary', 'reply_intent', 'reply_summary',
    ];

    public function __construct(App $app, private readonly ContactService $service)
    {
        parent::__construct($app);
    }

    /** GET /api/v1/contacts */
    public function index(): Response
    {
        [$page, $pageSize] = $this->pageParams();

        $filters = $this->only([
            'keyword', 'stage_id', 'owner_id', 'country', 'source_primary',
            'reply_intent', 'is_published', 'points_min', 'points_max',
            'date_from', 'date_to', 'tag_ids', 'segment_id', 'order_by', 'order_dir',
        ]);

        return $this->paged(
            $this->service->paginate($filters, $page, $pageSize),
            [LeadResource::class, 'brief']
        );
    }

    /** GET /api/v1/contacts/:id */
    public function read(int $id): Response
    {
        return $this->ok(LeadResource::detail($this->service->detail($id)));
    }

    /** POST /api/v1/contacts */
    public function save(): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(ContactValidate::class)->scene('create')->check($data);

        return $this->ok(LeadResource::detail($this->service->create($data)), '创建成功');
    }

    /** PUT /api/v1/contacts/:id */
    public function update(int $id): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(ContactValidate::class)->scene('update')->check($data);

        return $this->ok(LeadResource::detail($this->service->update($id, $data)), '更新成功');
    }

    /** DELETE /api/v1/contacts/:id */
    public function delete(int $id): Response
    {
        $this->service->delete($id);

        return $this->ok(null, '删除成功');
    }

    /** PATCH /api/v1/contacts/:id/stage */
    public function changeStage(int $id): Response
    {
        $stageId = $this->request->param('stage_id');
        $stageId = ($stageId === null || $stageId === '') ? null : (int) $stageId;

        return $this->ok(LeadResource::detail($this->service->changeStage($id, $stageId)), '阶段已更新');
    }

    /** PATCH /api/v1/contacts/:id/points  body: {delta: 10} */
    public function adjustPoints(int $id): Response
    {
        $delta = (int) $this->request->param('delta', 0);

        return $this->ok(LeadResource::detail($this->service->adjustPoints($id, $delta)), '积分已更新');
    }

    /** PUT /api/v1/contacts/:id/tags  body: {tags: ["a","b"]} */
    public function setTags(int $id): Response
    {
        $tags = $this->request->param('tags', []);
        $tags = is_array($tags) ? $tags : array_map('trim', explode(',', (string) $tags));

        return $this->ok(LeadResource::detail($this->service->setTags($id, $tags)), '标签已更新');
    }
}
