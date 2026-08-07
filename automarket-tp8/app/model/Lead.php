<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 联系人（Lead）模型 —— 对应 Mautic leads 表（1:1 字段映射）
 *
 * @property int         $id
 * @property int|null    $owner_id
 * @property int|null    $stage_id
 * @property bool        $is_published
 * @property int         $points
 * @property string|null $email
 * @property string|null $firstname
 * @property string|null $lastname
 * @property string|null $company
 * @property string|null $mobile
 * @property string|null $country
 * @property array|null   $internal      (DC2Type:array) JSON
 * @property array|null   $social_cache  (DC2Type:array) JSON
 * @property float|null   $order_count
 * @property float|null   $total_spent
 * @property string|null  $source_primary
 * @property string|null  $reply_intent
 * @property string|null  $reply_summary
 * @property string|null  $reply_raw
 * @property \app\model\Stage $stage
 * @property \app\model\User  $owner
 * @property \app\model\LeadTag[] $tags
 */
class Lead extends Model
{
    protected $table = 'leads';

    /**
     * array 类型字段，新库以 JSON 文本存储。
     * ⚠️ think-orm v4 已移除模型级 $json 属性，必须用 $type 声明，否则写入时报
     *    "Array to string conversion"。
     */
    protected $type = [
        'internal'     => 'array',
        'social_cache' => 'array',
    ];

    /** generated_email_domain 为生成列，禁止写入 */
    protected $readonly = ['generated_email_domain'];

    protected $createTime = 'date_added';

    protected $updateTime = 'date_modified';

    /** 阶段 */
    public function stage(): \think\model\relation\BelongsTo
    {
        return $this->belongsTo(Stage::class, 'stage_id', 'id');
    }

    /** 负责人 */
    public function owner(): \think\model\relation\BelongsTo
    {
        return $this->belongsTo(User::class, 'owner_id', 'id');
    }

    /** 标签（多对多，通过 lead_tags_xref） */
    public function tags(): \think\model\relation\BelongsToMany
    {
        return $this->belongsToMany(LeadTag::class, 'lead_tags_xref', 'tag_id', 'lead_id');
    }
}
