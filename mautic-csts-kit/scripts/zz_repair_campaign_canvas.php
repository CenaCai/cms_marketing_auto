<?php
/**
 * 修复脚本 #8/#9（以及任何脚本创建的活动）的画布连线。
 *
 * 根因：Mautic 画布连线完全由 campaigns.canvas_settings（序列化 JSON）驱动，
 * 与 campaign_events.parent_id 无关。脚本建活动时写入的 canvas_settings 格式错误：
 *   - 节点用了临时 ID（b1..b4）而非真实事件 ID → jsPlumb 找不到 DOM(CampaignEvent_<id>)
 *   - 字段名用了 x/y 而非 positionX/positionY
 *   - anchors 用了扁平 sourceAnchor/targetAnchor 而非嵌套 anchors.source/target
 *   - 决策分支锚点应为 yes/no（按子事件 decision_path），却统一写成了 bottom
 *
 * 此脚本用真实事件数据重建 canvas_settings，格式对齐 Mautic 自带 DataFixture。
 * 幂等：每次重跑都以当前 campaign_events 为准重建。
 */

declare(strict_types=1);

require_once __DIR__ . '/vendor/autoload.php';
require_once __DIR__ . '/app/AppKernel.php';

$kernel = new \AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

use Mautic\CampaignBundle\Entity\Campaign;

$em   = $c->get('doctrine.orm.entity_manager');
$repo = $em->getRepository(Campaign::class);

$campaignIds = [8, 9];

foreach ($campaignIds as $cid) {
    /** @var Campaign|null $campaign */
    $campaign = $repo->find($cid);
    if (!$campaign) {
        echo "Cmp#$cid: NOT FOUND, skip\n";
        continue;
    }

    $conn   = $em->getConnection();
    $events = $conn->fetchAllAssociative(
        'SELECT id, type, event_type, decision_path, parent_id
         FROM campaign_events
         WHERE campaign_id = ?
         ORDER BY event_order, id',
        [$cid]
    );

    if (empty($events)) {
        echo "Cmp#$cid: no events, skip\n";
        continue;
    }

    $byId = [];
    foreach ($events as $e) {
        $byId[(int) $e['id']] = $e;
    }

    $nodes       = [];
    $connections = [];

    // 源节点（分群/细分来源）——Mautic UI 默认在顶部画一个 leadsource 气泡
    $nodes['lists'] = ['id' => 'lists', 'positionX' => 300, 'positionY' => 520];

    // 事件节点：无碰撞的纵向+横向错开布局
    $x = 300;
    $y = 360;
    foreach ($events as $e) {
        $id = (int) $e['id'];
        $nodes[(string) $id] = [
            'id'         => (string) $id,
            'positionX'  => $x,
            'positionY'  => $y,
        ];
        $y -= 130;
        if ($y < 40) {
            $y = 360;
            $x += 320;
        }
    }

    foreach ($events as $e) {
        $id     = (int) $e['id'];
        $parent = ($e['parent_id'] !== null) ? $byId[(int) $e['parent_id']] : null;

        if ($parent === null) {
            // 根事件：从 lists 源节点拉一条线下来
            $connections[] = [
                'sourceId' => 'lists',
                'targetId' => (string) $id,
                'anchors'  => ['source' => 'leadsource', 'target' => 'top'],
            ];
            continue;
        }

        // 父是决策事件 → 按子事件 decision_path 选 yes/no 锚点；否则统一 bottom
        $sourceAnchor = 'bottom';
        if ($parent['event_type'] === 'decision') {
            $sourceAnchor = ($e['decision_path'] === 'no') ? 'no' : 'yes';
        }

        $connections[] = [
            'sourceId' => (string) (int) $parent['id'],
            'targetId' => (string) $id,
            'anchors'  => ['source' => $sourceAnchor, 'target' => 'top'],
        ];
    }

    $campaign->setCanvasSettings(['nodes' => $nodes, 'connections' => $connections]);
    $em->persist($campaign);
    $em->flush();

    echo sprintf(
        "Cmp#%d: %d nodes, %d connections (rebuilt from %d events)\n",
        $cid,
        count($nodes),
        count($connections),
        count($events)
    );
}

echo "ALL DONE\n";
