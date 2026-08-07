<?php

declare(strict_types=1);

/**
 * 测试引导。
 *
 * PHPUnit 本体由 phpunit.phar 提供（自包含，含全部依赖），此处只需加载
 * composer 生成的自动加载器以解析 app\ / think\ / psr\ 等本项目类与框架类。
 */

$baseDir = dirname(__DIR__);
require $baseDir . '/vendor/autoload.php';
