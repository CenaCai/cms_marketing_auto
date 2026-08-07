<?php

declare(strict_types=1);

namespace app\controller\api;

use app\BaseController;
use app\enum\ErrorCode;
use app\exception\BusinessException;
use app\support\ApiResponse;
use think\Response;

/**
 * API 控制器基类：只负责入参收敛与响应包装，不写业务逻辑。
 */
abstract class BaseApiController extends BaseController
{
    protected const DEFAULT_PAGE_SIZE = 20;

    /** @return array{0:int,1:int} [page, pageSize] */
    protected function pageParams(): array
    {
        $page     = (int) $this->request->param('page', 1);
        $pageSize = (int) $this->request->param('page_size', self::DEFAULT_PAGE_SIZE);

        return [max(1, $page), min(200, max(1, $pageSize))];
    }

    /** 只取白名单内且实际传了的字段，避免脏字段写库 */
    protected function only(array $keys): array
    {
        $all  = $this->request->param();
        $data = [];

        foreach ($keys as $key) {
            if (array_key_exists($key, $all)) {
                $data[$key] = $all[$key];
            }
        }

        return $data;
    }

    /** 取 ID 数组参数（支持 [1,2] 或 "1,2"） */
    protected function idsParam(string $key = 'ids'): array
    {
        $raw = $this->request->param($key);

        if (is_string($raw)) {
            $raw = explode(',', $raw);
        }

        $ids = array_values(array_unique(array_filter(array_map('intval', (array) $raw))));

        if ($ids === []) {
            throw BusinessException::of(ErrorCode::PARAM_INVALID, "参数 {$key} 不能为空");
        }

        return $ids;
    }

    protected function ok(mixed $data = null, string $message = 'ok'): Response
    {
        return ApiResponse::success($data, $message);
    }

    protected function paged(array $paginated, ?callable $transformer = null): Response
    {
        return ApiResponse::paginated($paginated, $transformer);
    }
}
