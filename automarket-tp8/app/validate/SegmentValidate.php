<?php

declare(strict_types=1);

namespace app\validate;

use think\Validate;

class SegmentValidate extends Validate
{
    protected $rule = [
        'name'                 => 'require|max:191',
        'alias'                => 'max:191|regex:/^[a-z0-9\-_]+$/i',
        'public_name'          => 'max:191',
        'description'          => 'max:5000',
        'filters'              => 'array',
        'is_published'         => 'in:0,1,true,false',
        'is_global'            => 'in:0,1,true,false',
        'is_preference_center' => 'in:0,1,true,false',
    ];

    protected $message = [
        'name.require' => '分群名称不能为空',
        'alias.regex'  => '别名只能包含字母、数字、下划线与短横线',
        'filters.array' => '过滤器必须为数组',
    ];

    public function sceneCreate(): self
    {
        return $this->only(['name', 'alias', 'public_name', 'description', 'filters',
                            'is_published', 'is_global', 'is_preference_center']);
    }

    public function sceneUpdate(): self
    {
        return $this->only(['name', 'alias', 'public_name', 'description', 'filters',
                            'is_published', 'is_global', 'is_preference_center'])
            ->remove('name', 'require');
    }
}
