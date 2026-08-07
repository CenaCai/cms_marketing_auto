<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 分群（Segment）模型
 *
 * @property int    $id
 * @property string $name
 * @property string $alias
 * @property array  $filters  (DC2Type:array) 以 JSON 存储
 * @property bool   $is_global
 * @property bool   $is_preference_center
 * @property \app\model\Lead[] $leads
 */
class LeadList extends Model
{
    protected $table = 'lead_lists';

    /**
     * filters 为 array 类型，新库以 JSON 文本存储。
     * ⚠️ think-orm v4 用 $type 声明，模型级 $json 属性已失效。
     */
    protected $type = [
        'filters' => 'array',
    ];

    protected $createTime = 'date_added';

    protected $updateTime = 'date_modified';

    /** 分群下的联系人（通过 lead_lists_leads 中间表） */
    public function leads(): \think\model\relation\BelongsToMany
    {
        return $this->belongsToMany(Lead::class, 'lead_lists_leads', 'lead_id', 'leadlist_id');
    }
}
