<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase as BaseTestCase;
use think\App;
use think\Container;

/**
 * 测试基类：启动 ThinkPHP 容器，使 app()/Db 门面与 provider 绑定在测试中可用。
 *
 * 默认数据库连接为 automarket_tp8（已通过 ETL 灌入生产数据），故本套测试直接对
 * 真实数据进行断言（读多写少，写操作在测试内自行清理）。
 */
abstract class TestCase extends BaseTestCase
{
    protected App $app;

    protected function setUp(): void
    {
        parent::setUp();

        $rootPath = dirname(__DIR__);
        $this->app = new App($rootPath);
        $this->app->initialize();
        Container::setInstance($this->app);
    }

    protected function tearDown(): void
    {
        Container::setInstance(null);
        parent::tearDown();
    }

    /** @template T */
    protected function make(string $abstract): mixed
    {
        return $this->app->make($abstract);
    }
}
