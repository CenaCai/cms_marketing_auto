<?php

declare(strict_types=1);

namespace app\validate;

use think\Validate;

class TagValidate extends Validate
{
    protected $rule = [
        'tag'         => 'require|max:191',
        'description' => 'max:5000',
    ];

    protected $message = [
        'tag.require' => '标签名不能为空',
        'tag.max'     => '标签名长度不能超过 191 字符',
    ];

    public function sceneCreate(): self
    {
        return $this->only(['tag', 'description']);
    }

    public function sceneUpdate(): self
    {
        return $this->only(['tag', 'description'])->remove('tag', 'require');
    }
}
