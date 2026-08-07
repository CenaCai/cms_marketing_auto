<?php

declare(strict_types=1);

use app\ExceptionHandle;
use app\repository\contracts\FieldRepositoryInterface;
use app\repository\contracts\LeadRepositoryInterface;
use app\repository\contracts\SegmentRepositoryInterface;
use app\repository\contracts\StageRepositoryInterface;
use app\repository\contracts\TagRepositoryInterface;
use app\repository\FieldRepository;
use app\repository\LeadRepository;
use app\repository\SegmentRepository;
use app\repository\StageRepository;
use app\repository\TagRepository;
use app\Request;

// 容器 Provider 定义文件：接口 -> 实现（依赖倒置绑定点）
return [
    'think\Request'          => Request::class,
    'think\exception\Handle' => ExceptionHandle::class,

    // ---- Repository 绑定 ----
    LeadRepositoryInterface::class    => LeadRepository::class,
    TagRepositoryInterface::class     => TagRepository::class,
    SegmentRepositoryInterface::class => SegmentRepository::class,
    StageRepositoryInterface::class   => StageRepository::class,
    FieldRepositoryInterface::class   => FieldRepository::class,
];
