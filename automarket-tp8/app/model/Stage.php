<?php

declare(strict_types=1);

namespace app\model;

use think\Model;

/**
 * 阶段（漏斗 S0–S6）模型
 *
 * @property int    $id
 * @property string $name
 * @property int    $weight
 * @property \app\model\Lead[] $leads
 */
class Stage extends Model
{
    protected $table = 'stages';

    protected $autoWriteTimestamp = false;

    protected $createTime = 'date_added';

    protected $updateTime = 'date_modified';

    /** 该阶段下的联系人 */
    public function leads(): \think\model\relation\HasMany
    {
        return $this->hasMany(Lead::class, 'stage_id', 'id');
    }
}
