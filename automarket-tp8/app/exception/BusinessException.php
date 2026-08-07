<?php

declare(strict_types=1);

namespace app\exception;

use app\enum\ErrorCode;
use RuntimeException;
use Throwable;

/**
 * 业务异常：由 Service 层抛出，统一由 ExceptionHandle 转成标准响应。
 */
class BusinessException extends RuntimeException
{
    public function __construct(
        public readonly ErrorCode $errorCode,
        string $message = '',
        public readonly array $data = [],
        ?Throwable $previous = null
    ) {
        parent::__construct($message !== '' ? $message : $errorCode->message(), $errorCode->value, $previous);
    }

    public static function of(ErrorCode $code, string $message = '', array $data = []): self
    {
        return new self($code, $message, $data);
    }

    public function httpStatus(): int
    {
        return $this->errorCode->httpStatus();
    }
}
