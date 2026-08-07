<?php

declare(strict_types=1);

namespace app;

use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\support\ApiResponse;
use think\db\exception\DataNotFoundException;
use think\db\exception\ModelNotFoundException;
use think\exception\Handle;
use think\exception\HttpException;
use think\exception\HttpResponseException;
use think\exception\ValidateException;
use think\Response;
use Throwable;

/**
 * 全局异常处理：所有 /api 请求返回统一 JSON 结构。
 */
class ExceptionHandle extends Handle
{
    /** 不需要记录日志的异常类列表 */
    protected $ignoreReport = [
        HttpException::class,
        HttpResponseException::class,
        ModelNotFoundException::class,
        DataNotFoundException::class,
        ValidateException::class,
        BusinessException::class,
    ];

    public function report(Throwable $exception): void
    {
        parent::report($exception);
    }

    public function render($request, Throwable $e): Response
    {
        // 非 API 请求走框架默认渲染（便于本地调试页面）
        if (!$this->wantsJson($request)) {
            return parent::render($request, $e);
        }

        // 1. 业务异常
        if ($e instanceof BusinessException) {
            return ApiResponse::error($e->errorCode, $e->getMessage(), $e->data ?: null);
        }

        // 2. 参数校验异常
        if ($e instanceof ValidateException) {
            $error = $e->getError();

            return ApiResponse::error(
                ErrorCode::PARAM_INVALID,
                is_array($error) ? (string) reset($error) : (string) $error,
                is_array($error) ? $error : null
            );
        }

        // 3. 模型/数据未找到
        if ($e instanceof ModelNotFoundException || $e instanceof DataNotFoundException) {
            return ApiResponse::error(ErrorCode::NOT_FOUND);
        }

        // 4. HTTP 异常（404 / 405 等）
        if ($e instanceof HttpException) {
            $status = $e->getStatusCode();
            $code   = match ($status) {
                401     => ErrorCode::UNAUTHORIZED,
                403     => ErrorCode::FORBIDDEN,
                404     => ErrorCode::NOT_FOUND,
                429     => ErrorCode::RATE_LIMITED,
                default => ErrorCode::SERVER_ERROR,
            };

            return ApiResponse::error($code, $e->getMessage() ?: $code->message());
        }

        // 5. 兜底：未预期异常
        $debug = (bool) env('APP_DEBUG', false);

        return ApiResponse::error(
            ErrorCode::SERVER_ERROR,
            $debug ? $e->getMessage() : ErrorCode::SERVER_ERROR->message(),
            $debug ? [
                'exception' => $e::class,
                'file'      => $e->getFile(),
                'line'      => $e->getLine(),
                'trace'     => array_slice(explode("\n", $e->getTraceAsString()), 0, 10),
            ] : null
        );
    }

    private function wantsJson($request): bool
    {
        if (!$request instanceof \think\Request) {
            return false;
        }

        return $request->isJson()
            || $request->isAjax()
            || str_starts_with(ltrim($request->pathinfo(), '/'), 'api/');
    }
}
