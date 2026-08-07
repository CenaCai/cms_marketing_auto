<?php

declare(strict_types=1);

namespace app\validate;

use think\Validate;

class ContactValidate extends Validate
{
    protected $rule = [
        'email'        => 'email|max:191',
        'firstname'    => 'max:191',
        'lastname'     => 'max:191',
        'company'      => 'max:191',
        'mobile'       => 'max:191',
        'phone'        => 'max:191',
        'country'      => 'max:191',
        'city'         => 'max:191',
        'stage_id'     => 'integer|egt:0',
        'owner_id'     => 'integer|egt:0',
        'points'       => 'integer',
        'order_count'  => 'float|egt:0',
        'total_spent'  => 'float|egt:0',
        'is_published' => 'in:0,1,true,false',
        'tags'         => 'array',
    ];

    protected $message = [
        'email.email'      => '邮箱格式不正确',
        'email.max'        => '邮箱长度不能超过 191 字符',
        'stage_id.integer' => '阶段 ID 必须为整数',
        'points.integer'   => '积分必须为整数',
        'tags.array'       => '标签必须为数组',
    ];

    protected $scene = [
        'create' => ['email', 'firstname', 'lastname', 'company', 'mobile', 'phone',
                     'country', 'city', 'stage_id', 'owner_id', 'points',
                     'order_count', 'total_spent', 'is_published', 'tags'],
        'update' => ['email', 'firstname', 'lastname', 'company', 'mobile', 'phone',
                     'country', 'city', 'stage_id', 'owner_id', 'points',
                     'order_count', 'total_spent', 'is_published', 'tags'],
    ];
}
