<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 分类模型（最小版，支撑 lead_lists / stages 外键）
 */
class Category extends Model
{
    protected $table = 'categories';

    protected $autoWriteTimestamp = false;
}
