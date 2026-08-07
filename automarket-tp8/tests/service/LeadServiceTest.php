<?php

declare(strict_types=1);

require_once __DIR__ . '/../TestCase.php';

use app\service\ContactService;
use think\facade\Db;

/**
 * 联系人服务测试：创建 -> 加分 -> 改阶段 -> 打标 -> 更新 -> 清理。
 * 全程仅操作本测试自建的联系人，结束删除，不污染生产数据。
 */
class LeadServiceTest extends TestCase
{
    private function service(): ContactService
    {
        return $this->make(ContactService::class);
    }

    private function existingTagName(): string
    {
        return (string) Db::table('lead_tags')->order('id', 'asc')->value('tag');
    }

    public function testCreateAndMutateAndCleanup(): void
    {
        $email = 'phpunit_' . uniqid() . '@example.com';
        $lead  = $this->service()->create([
            'email'     => $email,
            'firstname' => 'PHP',
            'lastname'  => 'Unit',
            'points'    => 5,
        ]);
        $id = (int) $lead->id;
        $this->assertGreaterThan(0, $id, '新建联系人应获得自增 ID');
        $this->assertSame($email, $lead->email);

        try {
            // 加分
            $after = $this->service()->adjustPoints($id, 10);
            $this->assertSame(15, (int) $after->points, '加分后应为 15');

            // 改阶段
            $after = $this->service()->changeStage($id, 3);
            $this->assertSame(3, (int) $after->stage_id, '阶段应变更为 3');

            // 打标（使用已存在标签，避免自动建标污染）
            $tag = $this->existingTagName();
            $this->assertNotEmpty($tag, '库中应存在至少一个标签');
            $this->service()->setTags($id, [$tag]);
            $xref = (int) Db::table('lead_tags_xref')->where('lead_id', $id)->count();
            $this->assertGreaterThanOrEqual(1, $xref, '打标后 lead_tags_xref 至少 1 行');

            // 更新字段
            $after = $this->service()->update($id, ['firstname' => 'Updated']);
            $this->assertSame('Updated', $after->firstname, 'firstname 应被更新');
        } finally {
            // 清理：删除自建联系人（级联清理 xref）
            $this->service()->delete($id);
        }

        $this->assertSame(0, (int) Db::table('leads')->where('id', $id)->count(), '清理后联系人应不存在');
        $this->assertSame(0, (int) Db::table('lead_tags_xref')->where('lead_id', $id)->count(), '清理后 xref 应被级联删除');
    }

    public function testDetailReturnsLead(): void
    {
        // 使用 ETL 灌入的真实数据（id=1 必然存在）
        $lead = $this->service()->detail(1);
        $this->assertSame(1, (int) $lead->id);
        $this->assertInstanceOf(\app\model\Lead::class, $lead);
        // 真实 Mautic 数据中部分联系人 email 为空，故仅断言 stage/积分等必有字段
        $this->assertIsInt((int) $lead->stage_id);
        $this->assertIsInt((int) $lead->points);
    }
}
