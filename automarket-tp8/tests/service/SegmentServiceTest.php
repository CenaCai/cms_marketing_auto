<?php

declare(strict_types=1);

require_once __DIR__ . '/../TestCase.php';

use app\exception\BusinessException;
use app\service\SegmentService;
use think\facade\Db;

/**
 * 分群服务测试：用真实生产分群验证 SegmentFilterCompiler。
 * - #3 积分≥20 -> 命中 4
 * - #12 SM-ctl-首触 (src_ctl AND NOT src_ctl_contacted) -> 命中 8
 * - #27 SM-复购 引用幽灵字段 last_order_date -> 显式抛错
 * - rebuild #3 幂等，写入 lead_lists_leads 且总数=4
 */
class SegmentServiceTest extends TestCase
{
    private function service(): SegmentService
    {
        return $this->make(SegmentService::class);
    }

    public function testPreviewPointsSegmentMatchesRaw(): void
    {
        $r = $this->service()->preview(3);
        $this->assertSame(4, $r['matched'], '#3 积分>=20 应命中 4（已用原始库校验）');
    }

    public function testPreviewSourceSegmentHandlesNotIn(): void
    {
        $r = $this->service()->preview(12);
        // src_ctl 标签共 8 人，且无一人同时带 src_ctl_contacted -> !in 正确排除 0
        $this->assertSame(8, $r['matched'], '#12 SM-ctl-首触 应命中 8');
    }

    public function testPreviewGhostFieldThrows(): void
    {
        $this->expectException(BusinessException::class);
        $this->expectExceptionMessage('last_order_date');
        $this->service()->preview(27);
    }

    public function testRebuildIsIdempotent(): void
    {
        $r = $this->service()->rebuild(3);
        $this->assertSame(4, $r['total'], 'rebuild 后成员总数应为 4');

        // 再 rebuild 一次应幂等（added=0, removed=0）
        $r2 = $this->service()->rebuild(3);
        $this->assertSame(0, $r2['added']);
        $this->assertSame(0, $r2['removed']);
        $this->assertSame(4, $r2['total']);

        // lead_lists_leads 实际写入行数
        $rows = (int) Db::table('lead_lists_leads')->where('leadlist_id', 3)->count();
        $this->assertSame(4, $rows);
    }
}
