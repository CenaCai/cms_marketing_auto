<?php

declare(strict_types=1);

namespace app\enum;

/**
 * 业务错误码。
 * 0        成功
 * 1xxxx    通用/系统
 * 2xxxx    联系人域
 * 3xxxx    标签/分群/阶段/字段
 */
enum ErrorCode: int
{
    case SUCCESS = 0;

    // 通用
    case PARAM_INVALID     = 10001;
    case UNAUTHORIZED      = 10002;
    case FORBIDDEN         = 10003;
    case NOT_FOUND         = 10004;
    case RATE_LIMITED      = 10005;
    case SERVER_ERROR      = 10500;

    // 联系人
    case LEAD_NOT_FOUND    = 20001;
    case LEAD_EMAIL_EXISTS = 20002;

    // 标签 / 分群 / 阶段 / 字段
    case TAG_NOT_FOUND     = 30001;
    case TAG_EXISTS        = 30002;
    case SEGMENT_NOT_FOUND = 30011;
    case SEGMENT_ALIAS_DUP = 30012;
    case STAGE_NOT_FOUND   = 30021;
    case FIELD_NOT_FOUND   = 30031;
    case FIELD_ALIAS_DUP   = 30032;

    public function message(): string
    {
        return match ($this) {
            self::SUCCESS           => 'ok',
            self::PARAM_INVALID     => '参数校验失败',
            self::UNAUTHORIZED      => '未认证或登录已过期',
            self::FORBIDDEN         => '无权限访问',
            self::NOT_FOUND         => '资源不存在',
            self::RATE_LIMITED      => '请求过于频繁，请稍后再试',
            self::SERVER_ERROR      => '服务器内部错误',
            self::LEAD_NOT_FOUND    => '联系人不存在',
            self::LEAD_EMAIL_EXISTS => '该邮箱已存在联系人',
            self::TAG_NOT_FOUND     => '标签不存在',
            self::TAG_EXISTS        => '标签已存在',
            self::SEGMENT_NOT_FOUND => '分群不存在',
            self::SEGMENT_ALIAS_DUP => '分群别名已被占用',
            self::STAGE_NOT_FOUND   => '阶段不存在',
            self::FIELD_NOT_FOUND   => '字段不存在',
            self::FIELD_ALIAS_DUP   => '字段别名已被占用',
        };
    }

    /** 对应的 HTTP 状态码 */
    public function httpStatus(): int
    {
        return match ($this) {
            self::SUCCESS       => 200,
            self::PARAM_INVALID => 422,
            self::UNAUTHORIZED  => 401,
            self::FORBIDDEN     => 403,
            self::NOT_FOUND,
            self::LEAD_NOT_FOUND,
            self::TAG_NOT_FOUND,
            self::SEGMENT_NOT_FOUND,
            self::STAGE_NOT_FOUND,
            self::FIELD_NOT_FOUND => 404,
            self::RATE_LIMITED  => 429,
            self::SERVER_ERROR  => 500,
            default             => 400,
        };
    }
}
