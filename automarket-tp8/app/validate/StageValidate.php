<?php

declare(strict_types=1);

namespace app\validate;

use think\Validate;

class StageValidate extends Validate
{
    protected $rule = [
        'name'         => 'require|max:191',
        'description'  => 'max:5000',
        'weight'       => 'integer',
        'category_id'  => 'integer|egt:0',
        'is_published' => 'in:0,1,true,false',
        'publish_up'   => 'date',
        'publish_down' => 'date',
    ];

    protected $message = [
        'name.require'    => '阶段名称不能为空',
        'weight.integer'  => '权重必须为整数',
    ];

    public function sceneCreate(): self
    {
        return $this->only(['name', 'description', 'weight', 'category_id',
                            'is_published', 'publish_up', 'publish_down']);
    }

    public function sceneUpdate(): self
    {
        return $this->only(['name', 'description', 'weight', 'category_id',
                            'is_published', 'publish_up', 'publish_down'])
            ->remove('name', 'require');
    }
}
