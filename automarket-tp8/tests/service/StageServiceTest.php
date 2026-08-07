<?php

declare(strict_types=1);

require_once __DIR__ . '/../TestCase.php';

use app\service\StageService;
use think\facade\Db;

/**
 * 阶段服务测试：漏斗结构、详情、分页，计数与真实库一致。
 */
class StageServiceTest extends TestCase
{
    private function service(): StageService
    {
        return $this->make(StageService::class);
    }

    public function testFunnelStructureAndCounts(): void
    {
        $funnel = $this->service()->funnel();

        $this->assertCount(7, $funnel, '应有 7 个阶段（S0-S6）');

        $expected = Db::table('stages')
            ->field('id, name, weight')
            ->order('weight', 'asc')
            ->select()
            ->toArray();

        $byId = [];
        foreach ($expected as $s) {
            $byId[(int) $s['id']] = (int) $s['weight'];
        }

        foreach ($funnel as $row) {
            $this->assertArrayHasKey('id', $row);
            $this->assertArrayHasKey('name', $row);
            $this->assertArrayHasKey('weight', $row);
            $this->assertArrayHasKey('count', $row);
            $this->assertArrayHasKey('rate', $row);
            $this->assertIsInt($row['count']);

            // count 必须等于真实库该阶段联系人数量
            $real = (int) Db::table('leads')->where('stage_id', $row['id'])->count();
            $this->assertSame($real, $row['count'], "阶段 {$row['name']} 计数应与库一致");
            $this->assertSame($byId[$row['id']] ?? null, $row['weight'], 'weight 应与阶段配置一致');
        }
    }

    public function testDetailReturnsStage(): void
    {
        $stage = $this->service()->detail(2);
        $this->assertSame(2, (int) $stage->id);
        $this->assertNotEmpty($stage->name);
    }

    public function testPaginateReturnsShape(): void
    {
        $r = $this->service()->paginate([], 1, 10);
        $this->assertArrayHasKey('list', $r);
        $this->assertArrayHasKey('total', $r);
        $this->assertLessThanOrEqual(10, count($r['list']));
    }
}
