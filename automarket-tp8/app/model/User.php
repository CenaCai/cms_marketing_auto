<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 用户模型（最小版，支撑 leads.owner_id 外键）
 */
class User extends Model
{
    protected $table = 'users';

    protected $autoWriteTimestamp = false;

    /** 密码等敏感字段不对外暴露 */
    protected $hidden = ['password'];
}
