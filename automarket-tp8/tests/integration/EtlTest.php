<?php

declare(strict_types=1);

require_once __DIR__ . '/../TestCase.php';

use think\facade\Db;

/**
 * ETL 后数据一致性校验（针对已灌入 automarket_tp8 的真实库）。
 * 验证：行数 1:1、原始 ID 保留、serialize 字段已转为合法 JSON。
 */
class EtlTest extends TestCase
{
    public function testRowCountsMatchSource(): void
    {
        $tables = ['categories', 'users', 'lead_fields', 'stages', 'lead_tags', 'leads', 'lead_tags_xref', 'lead_lists', 'lead_lists_leads'];

        foreach ($tables as $table) {
            $src  = (int) Db::connect('mautic')->table($table)->count();
            $dst  = (int) Db::table($table)->count();
            $this->assertSame($src, $dst, "表 {$table} 行数应与 Mautic 源库一致");
        }
    }

    public function testSerializedColumnsAreValidJson(): void
    {
        // leads.internal / social_cache 应为合法 JSON（空则为 []）
        $bad = (int) Db::table('leads')
            ->whereNotNull('internal')
            ->where('internal', '<>', '')
            ->whereRaw('JSON_VALID(internal) = 0')
            ->count();
        $this->assertSame(0, $bad, 'leads.internal 应全部为合法 JSON');

        // lead_lists.filters 必须全部为合法 JSON（原 Mautic 为 serialize）
        $badFilters = (int) Db::table('lead_lists')
            ->whereRaw('JSON_VALID(filters) = 0')
            ->count();
        $this->assertSame(0, $badFilters, 'lead_lists.filters 应全部为合法 JSON');

        // lead_fields.properties 必须全部为合法 JSON
        $badProps = (int) Db::table('lead_fields')
            ->whereRaw('JSON_VALID(properties) = 0')
            ->count();
        $this->assertSame(0, $badProps, 'lead_fields.properties 应全部为合法 JSON');
    }

    public function testOriginalIdsPreserved(): void
    {
        // 最小 id 应为 1（保留原始主键，而非从 1 重新自增覆盖）
        $minLead = (int) Db::table('leads')->min('id');
        $this->assertSame(1, $minLead, 'leads 最小 id 应保留为 1');

        // leads 数量应为 ETL 灌入的 26
        $this->assertSame(26, (int) Db::table('leads')->count());
    }
}
