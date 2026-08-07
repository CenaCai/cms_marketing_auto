<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 标签模型
 *
 * @property int    $id
 * @property string $tag
 * @property string $description
 */
class LeadTag extends Model
{
    protected $table = 'lead_tags';

    protected $autoWriteTimestamp = false;
}
