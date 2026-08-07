<?php

declare(strict_types=1);

use think\facade\Route;

/**
 * API v1 路由
 *
 * 统一响应结构：{ code, message, data, timestamp }
 * 静态路由必须声明在动态路由（:id）之前，否则会被 :id 抢先匹配。
 */
Route::group('api/v1', function () {

    // ---------------- 联系人 ----------------
    Route::group('contacts', function () {
        Route::get('',            'api.v1.Contact/index');
        Route::post('',           'api.v1.Contact/save');
        Route::get(':id',         'api.v1.Contact/read')->pattern(['id' => '\d+']);
        Route::put(':id',         'api.v1.Contact/update')->pattern(['id' => '\d+']);
        Route::delete(':id',      'api.v1.Contact/delete')->pattern(['id' => '\d+']);
        Route::patch(':id/stage', 'api.v1.Contact/changeStage')->pattern(['id' => '\d+']);
        Route::patch(':id/points', 'api.v1.Contact/adjustPoints')->pattern(['id' => '\d+']);
        Route::put(':id/tags',    'api.v1.Contact/setTags')->pattern(['id' => '\d+']);
    });

    // ---------------- 标签 ----------------
    Route::group('tags', function () {
        Route::get('',       'api.v1.Tag/index');
        Route::post('',      'api.v1.Tag/save');
        Route::get(':id',    'api.v1.Tag/read')->pattern(['id' => '\d+']);
        Route::put(':id',    'api.v1.Tag/update')->pattern(['id' => '\d+']);
        Route::delete(':id', 'api.v1.Tag/delete')->pattern(['id' => '\d+']);
    });

    // ---------------- 分群 ----------------
    Route::group('segments', function () {
        Route::get('',                'api.v1.Segment/index');
        Route::post('',               'api.v1.Segment/save');
        Route::get(':id/members',     'api.v1.Segment/members')->pattern(['id' => '\d+']);
        Route::post(':id/members',    'api.v1.Segment/addMembers')->pattern(['id' => '\d+']);
        Route::delete(':id/members',  'api.v1.Segment/removeMembers')->pattern(['id' => '\d+']);
        Route::post(':id/rebuild',    'api.v1.Segment/rebuild')->pattern(['id' => '\d+']);
        Route::get(':id/preview',     'api.v1.Segment/preview')->pattern(['id' => '\d+']);
        Route::get(':id',             'api.v1.Segment/read')->pattern(['id' => '\d+']);
        Route::put(':id',             'api.v1.Segment/update')->pattern(['id' => '\d+']);
        Route::delete(':id',          'api.v1.Segment/delete')->pattern(['id' => '\d+']);
    });

    // ---------------- 阶段 ----------------
    Route::group('stages', function () {
        Route::get('funnel', 'api.v1.Stage/funnel');
        Route::get('',       'api.v1.Stage/index');
        Route::post('',      'api.v1.Stage/save');
        Route::get(':id',    'api.v1.Stage/read')->pattern(['id' => '\d+']);
        Route::put(':id',    'api.v1.Stage/update')->pattern(['id' => '\d+']);
        Route::delete(':id', 'api.v1.Stage/delete')->pattern(['id' => '\d+']);
    });

    // ---------------- 自定义字段 ----------------
    Route::group('fields', function () {
        Route::get('grouped', 'api.v1.Field/grouped');
        Route::get('',        'api.v1.Field/index');
        Route::post('',       'api.v1.Field/save');
        Route::get(':id',     'api.v1.Field/read')->pattern(['id' => '\d+']);
        Route::put(':id',     'api.v1.Field/update')->pattern(['id' => '\d+']);
        Route::delete(':id',  'api.v1.Field/delete')->pattern(['id' => '\d+']);
    });

})->middleware([
    \app\middleware\JsonRequest::class,
]);

// 健康检查（不进 API 中间件）
Route::get('api/health', function () {
    return json([
        'code'      => 0,
        'message'   => 'ok',
        'data'      => ['service' => 'automarket-tp8', 'php' => PHP_VERSION],
        'timestamp' => time(),
    ]);
});
