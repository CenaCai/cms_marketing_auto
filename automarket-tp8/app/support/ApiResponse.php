<?php

declare(strict_types=1);

namespace app\support;

use app\enum\ErrorCode;
use think\Response;

/**
 * 统一响应结构：{ code, message, data, timestamp }
 */
final class ApiResponse
{
    public static function success(mixed $data = null, string $message = 'ok'): Response
    {
        return self::make(ErrorCode::SUCCESS->value, $message, $data, 200);
    }

    public static function error(ErrorCode $code, string $message = '', mixed $data = null): Response
    {
        return self::make(
            $code->value,
            $message !== '' ? $message : $code->message(),
            $data,
            $code->httpStatus()
        );
    }

    /**
     * 分页响应：把 Repository 的 {list,total,page,page_size} 直接铺平进 data
     *
     * @param array{list: mixed, total: int, page: int, page_size: int} $paginated
     */
    public static function paginated(array $paginated, ?callable $transformer = null): Response
    {
        $list = $paginated['list'];
        if ($transformer !== null) {
            $items = is_array($list) ? $list : $list->toArray();
            $list  = array_map($transformer, $items);
        }

        return self::success([
            'list'      => $list,
            'total'     => $paginated['total'],
            'page'      => $paginated['page'],
            'page_size' => $paginated['page_size'],
            'pages'     => $paginated['page_size'] > 0
                ? (int) ceil($paginated['total'] / $paginated['page_size'])
                : 0,
        ]);
    }

    public static function make(int $code, string $message, mixed $data, int $httpStatus): Response
    {
        return json([
            'code'      => $code,
            'message'   => $message,
            'data'      => $data,
            'timestamp' => time(),
        ], $httpStatus);
    }
}
