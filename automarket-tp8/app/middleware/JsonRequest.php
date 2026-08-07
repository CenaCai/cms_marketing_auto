<?php

declare(strict_types=1);

namespace app\middleware;

use Closure;
use think\Request;
use think\Response;

/**
 * API 请求预处理：
 *  - 标记为 JSON 请求，使异常处理器返回统一 JSON 结构
 *  - 统一注入 CORS 与请求追踪 ID
 */
class JsonRequest
{
    public function handle(Request $request, Closure $next): Response
    {
        $traceId = $request->header('X-Request-Id') ?: bin2hex(random_bytes(8));
        $request->withMiddleware(['trace_id' => $traceId]);

        if ($request->method(true) === 'OPTIONS') {
            return $this->withCors(response('', 204), $request);
        }

        /** @var Response $response */
        $response = $next($request);

        return $this->withCors($response, $request)->header(['X-Request-Id' => $traceId]);
    }

    private function withCors(Response $response, Request $request): Response
    {
        return $response->header([
            'Access-Control-Allow-Origin'      => $request->header('Origin') ?: '*',
            'Access-Control-Allow-Methods'     => 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
            'Access-Control-Allow-Headers'     => 'Content-Type, Authorization, X-Request-Id, X-Requested-With',
            'Access-Control-Allow-Credentials' => 'true',
            'Access-Control-Max-Age'           => '86400',
        ]);
    }
}
