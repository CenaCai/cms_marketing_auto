<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 联系人自定义字段模型
 *
 * @property int    $id
 * @property string $label
 * @property string $alias
 * @property string $type
 * @property string $field_group
 * @property array  $properties  (DC2Type:array) 以 JSON 存储
 */
class LeadField extends Model
{
    protected $table = 'lead_fields';

    /**
     * properties 为 array 类型，新库以 JSON 文本存储。
     * ⚠️ 注意：本表恰好有一列也叫 `type`，但模型的 $type 是「字段类型转换表」，
     *    二者不冲突——列值通过 __get 从 data 读取，不会命中这个 protected 属性。
     */
    protected $type = [
        'properties' => 'array',
    ];

    protected $createTime = 'date_added';

    protected $updateTime = 'date_modified';
}
