<?php
// +----------------------------------------------------------------------
// | 控制台配置
// +----------------------------------------------------------------------
return [
    // 指令定义
    'commands' => [
        'etl:mautic'      => \app\command\MigrateMauticData::class,
        'segments:update' => \app\command\SegmentsUpdate::class,
    ],
];
