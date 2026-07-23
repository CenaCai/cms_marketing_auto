<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$listModel = $c->get('mautic.lead.model.list');
$campaignModel = $c->get('mautic.campaign.model.campaign');

// ---------- 分群: 潜客入口 (新潜客, 无 潜在客户 标签) ----------
$qiankeFilters = [
    ['object'=>'lead','glue'=>'and','field'=>'tags','type'=>'lead','filter'=>[2],'operator'=>'!in','display'=>'不含标签 潜在客户'],
];
$qSeg = $listModel->getRepository()->findOneBy(['name'=>'潜客入口']);
if (!$qSeg) {
    $qSeg = $listModel->getEntity();
    $qSeg->setName('潜客入口');
    $qSeg->setPublicName('潜客入口');
    $qSeg->setFilters($qiankeFilters);
    $qSeg->setIsPublished(true);
    $listModel->saveEntity($qSeg);
    echo "SEG 潜客入口 已创建 #".$qSeg->getId()."\n";
} else { echo "SEG 潜客入口 已存在 #".$qSeg->getId()."\n"; }
$qSegId = $qSeg->getId();

// ---------- 分群: 意向客 (stage = 2) ----------
$yxFilters = [
    ['object'=>'lead','glue'=>'and','field'=>'stage','type'=>'stage','filter'=>'2','operator'=>'=','display'=>'阶段 = 意向客'],
];
$ySeg = $listModel->getRepository()->findOneBy(['name'=>'意向客']);
if (!$ySeg) {
    $ySeg = $listModel->getEntity();
    $ySeg->setName('意向客');
    $ySeg->setPublicName('意向客');
    $ySeg->setFilters($yxFilters);
    $ySeg->setIsPublished(true);
    $listModel->saveEntity($ySeg);
    echo "SEG 意向客 已创建 #".$ySeg->getId()."\n";
} else { echo "SEG 意向客 已存在 #".$ySeg->getId()."\n"; }
$ySegId = $ySeg->getId();

$events = [];
$canvas = ['nodes'=>[], 'connections'=>[]];

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
    $canvas['nodes'][] = ['id'=>$tempId, 'x'=>($order*90)%540, 'y'=>intval($order/5)*140];
    if ($parentTempId) { $canvas['connections'][] = ['sourceId'=>$parentTempId, 'targetId'=>$tempId, 'sourceAnchor'=>'b', 'targetAnchor'=>'t']; }
    return $e;
}

// ================= 战役1: 潜客工作流 =================
$c1 = $campaignModel->getRepository()->findOneBy(['name'=>'潜客工作流']);
if (!$c1) {
    $c1 = $campaignModel->getEntity();
    $c1->setName('潜客工作流');
    $c1->setIsPublished(true);
    $c1->addList($qSeg);
    $events = []; $canvas = ['nodes'=>[], 'connections'=>[]];
    mkEvent($c1, 'a1', '打潜在客户标签', 'lead.changetags', 'action', ['add_tags'=>['潜在客户'],'remove_tags'=>[]], null, null, 'lead', null, 1, $events, $canvas);
    mkEvent($c1, 'a2', '发潜客邮件', 'email.send', 'action', ['email'=>7], 'a1', null, 'email', 7, 2, $events, $canvas);
    mkEvent($c1, 'd1', '点击官网链接?', 'email.click', 'decision', ['urls'=>['https://www.connexustravel.com.cn/']], 'a2', null, 'email', 7, 3, $events, $canvas);
    mkEvent($c1, 'a3', '升意向客(打标签)', 'lead.changetags', 'action', ['add_tags'=>['S2-意向客'],'remove_tags'=>['潜在客户']], 'd1', 'yes', 'lead', null, 4, $events, $canvas);
    mkEvent($c1, 'a4', '升意向客(阶段S2)', 'stage.change', 'action', ['stage'=>2], 'a3', null, 'stage', 2, 5, $events, $canvas);
    mkEvent($c1, 'd2', '提交退订表单?', 'form.submit', 'decision', ['forms'=>[4]], 'a2', null, 'form', 4, 6, $events, $canvas);
    mkEvent($c1, 'a5', '退订处理', 'lead.changetags', 'action', ['add_tags'=>['退订'],'remove_tags'=>['潜在客户']], 'd2', 'yes', 'lead', null, 7, $events, $canvas);
    $c1->setCanvasSettings($canvas);
    $campaignModel->saveEntity($c1);
    echo "CAMPAIGN 潜客工作流 已创建 #".$c1->getId()."\n";
} else { echo "CAMPAIGN 潜客工作流 已存在 #".$c1->getId()."\n"; }

// ================= 战役2: 意向客转化 + 每周邮件 =================
$c2 = $campaignModel->getRepository()->findOneBy(['name'=>'意向客转化']);
if (!$c2) {
    $c2 = $campaignModel->getEntity();
    $c2->setName('意向客转化');
    $c2->setIsPublished(true);
    $c2->addList($ySeg);
    $events = []; $canvas = ['nodes'=>[], 'connections'=>[]];
    mkEvent($c2, 'b1', '发本周活动推荐', 'email.send', 'action', ['email'=>8], null, null, 'email', 8, 1, $events, $canvas);
    mkEvent($c2, 'b2', '访问下单确认页?', 'page.pagehit', 'decision', ['pages'=>[3]], 'b1', null, 'page', 3, 2, $events, $canvas);
    mkEvent($c2, 'b3', '升高意向(打标签)', 'lead.changetags', 'action', ['add_tags'=>['S3-高意向','意图-迪士尼亲子','上海','一线城市（北上广深）'],'remove_tags'=>['S2-意向客']], 'b2', 'yes', 'lead', null, 3, $events, $canvas);
    mkEvent($c2, 'b4', '升高意向(阶段S3)', 'stage.change', 'action', ['stage'=>3], 'b3', null, 'stage', 3, 4, $events, $canvas);
    $c2->setCanvasSettings($canvas);
    $campaignModel->saveEntity($c2);
    echo "CAMPAIGN 意向客转化 已创建 #".$c2->getId()."\n";
} else { echo "CAMPAIGN 意向客转化 已存在 #".$c2->getId()."\n"; }

echo "SUMMARY: 潜客入口Seg#$qSegId 意向客Seg#$ySegId\n";
echo "DONE\n";
