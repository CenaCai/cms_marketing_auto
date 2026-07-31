<?php
// 幂等脚本：新增 S0 阶段 + 无阶段分群 + S0 入站分配活动
// 复用 zz_create_campaigns.php 的 mkEvent 模式
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$stageModel    = $c->get('mautic.stage.model.stage');
$listModel     = $c->get('mautic.lead.model.list');
$campaignModel = $c->get('mautic.campaign.model.campaign');

// ---------- S0 阶段 ----------
$s0Name = 'S0. 访客/未知 (Visitor/Unknown)';
$s0 = $stageModel->getRepository()->findOneBy(['name' => $s0Name]);
if (!$s0) {
    $s0 = $stageModel->getEntity();
    $s0->setName($s0Name);
    $s0->setWeight(5);           // 置于 S1(权重10) 之前，作为生命周期最底层入口
    $s0->setIsPublished(true);
    $stageModel->saveEntity($s0);
    echo "STAGE S0 已创建 #" . $s0->getId() . "\n";
} else {
    echo "STAGE S0 已存在 #" . $s0->getId() . "\n";
}
$s0Id = $s0->getId();

// ---------- 分群: 无阶段联系人 ----------
$segName = 'S0-无阶段联系人';
$seg = $listModel->getRepository()->findOneBy(['name' => $segName]);
if (!$seg) {
    $seg = $listModel->getEntity();
    $seg->setName($segName);
    $seg->setPublicName($segName);
    $seg->setFilters([
        ['object' => 'lead', 'glue' => 'and', 'field' => 'stage', 'type' => 'stage', 'filter' => '', 'operator' => 'empty', 'display' => '阶段 为空'],
    ]);
    $seg->setIsPublished(true);
    $listModel->saveEntity($seg);
    echo "SEG $segName 已创建 #" . $seg->getId() . "\n";
} else {
    echo "SEG $segName 已存在 #" . $seg->getId() . "\n";
}
$segId = $seg->getId();

// ---------- 活动: S0 入站分配 ----------
function mkEvent($campaign, $tempId, $name, $type, $eventType, $props, $parentTempId, $decisionPath, $channel, $channelId, $order, &$events, &$canvas) {
    $e = new \Mautic\CampaignBundle\Entity\Event();
    $e->setName($name);
    $e->setType($type);
    $e->setEventType($eventType);
    $e->setProperties($props);
    $e->setCampaign($campaign);
    $e->setTempId($tempId);
    if ($parentTempId) { $e->setParent($events[$parentTempId]); }
    if ($decisionPath) { $e->setDecisionPath($decisionPath); }
    if ($channel) { $e->setChannel($channel); }
    if ($channelId) { $e->setChannelId($channelId); }
    $e->setOrder($order);
    $campaign->addEvent($tempId, $e);
    $events[$tempId] = $e;
    $canvas['nodes'][] = ['id' => $tempId, 'x' => ($order * 90) % 540, 'y' => intval($order / 5) * 140];
    if ($parentTempId) { $canvas['connections'][] = ['sourceId' => $parentTempId, 'targetId' => $tempId, 'sourceAnchor' => 'b', 'targetAnchor' => 't']; }
    return $e;
}

$campName = 'S0 入站分配';
$camp = $campaignModel->getRepository()->findOneBy(['name' => $campName]);
if (!$camp) {
    $camp = $campaignModel->getEntity();
    $camp->setName($campName);
    $camp->setIsPublished(true);
    $camp->addList($seg);
    $events = []; $canvas = ['nodes' => [], 'connections' => []];
    mkEvent($camp, 's1', '设为 S0 访客/未知', 'stage.change', 'action', ['stage' => $s0Id], null, null, 'stage', $s0Id, 1, $events, $canvas);
    $camp->setCanvasSettings($canvas);
    $campaignModel->saveEntity($camp);
    echo "CAMPAIGN $campName 已创建 #" . $camp->getId() . "\n";
} else {
    echo "CAMPAIGN $campName 已存在 #" . $camp->getId() . "\n";
}

echo "SUMMARY: S0#$s0Id  Seg#$segId\n";
echo "DONE\n";
