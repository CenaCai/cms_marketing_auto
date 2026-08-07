<?php

declare(strict_types=1);

namespace app\controller\api\v1;

use app\controller\api\BaseApiController;
use app\service\FieldService;
use app\validate\FieldValidate;
use think\App;
use think\Response;

/**
 * 自定义字段 API  /api/v1/fields
 */
class FieldController extends BaseApiController
{
    private const WRITABLE = [
        'label', 'alias', 'type', 'field_group', 'default_value', 'field_order',
        'properties', 'is_published', 'is_required', 'is_visible', 'is_listable',
        'is_publicly_updatable', 'object',
    ];

    public function __construct(App $app, private readonly FieldService $service)
    {
        parent::__construct($app);
    }

    public function index(): Response
    {
        [$page, $pageSize] = $this->pageParams();
        $filters = $this->only(['keyword', 'field_group', 'type', 'is_published', 'order_by', 'order_dir']);

        return $this->paged($this->service->paginate($filters, $page, $pageSize));
    }

    public function read(int $id): Response
    {
        return $this->ok($this->service->detail($id)->toArray());
    }

    public function save(): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(FieldValidate::class)->scene('create')->check($data);

        return $this->ok($this->service->create($data)->toArray(), '创建成功');
    }

    public function update(int $id): Response
    {
        $data = $this->only(self::WRITABLE);
        validate(FieldValidate::class)->scene('update')->check($data);

        return $this->ok($this->service->update($id, $data)->toArray(), '更新成功');
    }

    public function delete(int $id): Response
    {
        $this->service->delete($id);

        return $this->ok(null, '删除成功');
    }

    /**
     * GET /api/v1/fields/grouped
     * 按 field_group 分组返回，前端联系人表单直接消费
     * （复刻现有 form.html.twig 的「手填块 / auto 系统自动块」分组约定）
     */
    public function grouped(): Response
    {
        $onlyPublished = (bool) $this->request->param('only_published', true);
        $grouped       = $this->service->listGrouped($onlyPublished);

        $out = [];
        foreach ($grouped as $group => $fields) {
            $out[] = [
                'group'     => $group,
                'is_auto'   => $group === 'auto',
                'read_only' => $group === 'auto',
                'fields'    => array_map(
                    static fn ($f): array => [
                        'id'            => (int) $f->id,
                        'label'         => $f->label,
                        'alias'         => $f->alias,
                        'type'          => $f->type,
                        'default_value' => $f->default_value,
                        'is_required'   => (bool) $f->is_required,
                        'properties'    => $f->properties,
                    ],
                    $fields
                ),
            ];
        }

        return $this->ok($out);
    }
}
