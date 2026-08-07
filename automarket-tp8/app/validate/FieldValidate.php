<?php

declare(strict_types=1);

namespace app\validate;

use think\Validate;

class FieldValidate extends Validate
{
    /** 与 Mautic 一致的字段类型白名单 */
    private const TYPES = 'text,textarea,email,number,tel,url,select,multiselect,boolean,'
        . 'date,datetime,time,lookup,country,region,timezone,locale,html';

    protected $rule = [
        'label'         => 'require|max:191',
        'alias'         => 'require|max:191|regex:/^[a-z][a-z0-9_]*$/',
        'type'          => 'require|in:' . self::TYPES,
        'field_group'   => 'max:191',
        'default_value' => 'max:191',
        'field_order'   => 'integer',
        'properties'    => 'array',
        'is_published'  => 'in:0,1,true,false',
        'is_required'   => 'in:0,1,true,false',
        'is_visible'    => 'in:0,1,true,false',
        'is_listable'   => 'in:0,1,true,false',
    ];

    protected $message = [
        'label.require' => '字段标签不能为空',
        'alias.require' => '字段别名不能为空',
        'alias.regex'   => '别名必须以小写字母开头，且只能包含小写字母、数字、下划线',
        'type.require'  => '字段类型不能为空',
        'type.in'       => '不支持的字段类型',
    ];

    public function sceneCreate(): self
    {
        return $this->only(['label', 'alias', 'type', 'field_group', 'default_value',
                            'field_order', 'properties', 'is_published', 'is_required',
                            'is_visible', 'is_listable']);
    }

    public function sceneUpdate(): self
    {
        return $this->only(['label', 'alias', 'type', 'field_group', 'default_value',
                            'field_order', 'properties', 'is_published', 'is_required',
                            'is_visible', 'is_listable'])
            ->remove('label', 'require')
            ->remove('alias', 'require')
            ->remove('type', 'require');
    }
}
