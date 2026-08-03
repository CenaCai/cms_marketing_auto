<?php
/**
 * 幂等补丁：把 sourcemarketing.guard（去重/冻结/主题冻结/强度降级/渠道拉黑）
 * 真正挂进已建好的活动画布。
 *
 * 挂载点（对齐 PRD「去重-冻结-降级」阶梯）：
 *   1. 7 条 SM-{source}-二次   : D换视角沉默分支末端 -> 强度降级 -> 主题冻结60天
 *   2. SM-沉睡唤醒            : 永久沉睡之后        -> 通信冻结365天
 *   3. SM-复购内容流          : 私域邀请分支末端    -> 强度降级
 *
 * 用法: php zz_patch_guard_nodes.php
 */
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';

$kernel = new AppKernel('prod', false);
$kernel->boot();
$container = $kernel->getContainer();

/** @var \Mautic\CampaignBundle\Model\CampaignModel $campaignModel */
$campaignModel = $container->get('mautic.campaign.model.campaign');
$repo          = $campaignModel->getRepository();

/**
 * 在已有活动上追加一个节点（按 tempId 幂等）。
 */
function appendNode(
    $campaign,
    string $tempId,
    string $name,
    string $type,
    string $eventType,
    array $props,
    string $parentTempId
): string {
    // 索引现有节点
    $byTemp = [];
    foreach ($campaign->getEvents() as $ev) {
        if ($ev->getTempId()) {
            $byTemp[$ev->getTempId()] = $ev;
        }
    }

    if (isset($byTemp[$tempId])) {
        return "SKIP  {$campaign->getName()} / {$tempId} 已存在";
    }
    if (!isset($byTemp[$parentTempId])) {
        return "WARN  {$campaign->getName()} / 找不到父节点 {$parentTempId}，跳过 {$tempId}";
    }

    $parent = $byTemp[$parentTempId];

    $e = new \Mautic\CampaignBundle\Entity\Event();
    $e->setName($name);
    $e->setType($type);
    $e->setEventType($eventType);
    $e->setProperties($props);
    $e->setCampaign($campaign);
    $e->setTempId($tempId);
    $e->setParent($parent);
    $e->setChannel('sourcemarketing');
    $e->setOrder(count($byTemp) + 1);
    $campaign->addEvent($tempId, $e);

    // 画布：连线只由 canvas_settings 驱动，必须同步写入
    $canvas = $campaign->getCanvasSettings();
    if (!is_array($canvas) || !isset($canvas['nodes'])) {
        $canvas = ['nodes' => [], 'connections' => []];
    }
    $order            = count($canvas['nodes']) + 1;
    $canvas['nodes'][] = [
        'id' => $tempId,
        'x'  => ($order * 90) % 540,
        'y'  => intval($order / 5) * 140,
    ];
    $canvas['connections'][] = [
        'sourceId'     => $parentTempId,
        'targetId'     => $tempId,
        'sourceAnchor' => 'bottom',
        'targetAnchor' => 'top',
    ];
    $campaign->setCanvasSettings($canvas);

    return "ADD   {$campaign->getName()} / {$tempId} {$name}";
}

$SOURCES = ['ctl', 'csts', 'crawler', 'adform', 'webform', 'tplus', 'spots'];
$touched = [];

// ---------------------------------------------------------- 1. 二次: 沉默分支降级
foreach ($SOURCES as $s) {
    $c = $repo->findOneBy(['name' => "SM-{$s}-二次"]);
    if (!$c) {
        echo "MISS  SM-{$s}-二次\n";
        continue;
    }
    echo appendNode(
        $c, 'b17', '强度降级', 'sourcemarketing.guard', 'action',
        ['action' => 'downgrade'], 'b12'
    )."\n";
    echo appendNode(
        $c, 'b18', '主题冻结60天', 'sourcemarketing.guard', 'action',
        ['action' => 'topic_freeze', 'topic' => $s, 'days' => 60], 'b17'
    )."\n";
    $touched[] = $c;
}

// ---------------------------------------------------------- 2. 沉睡唤醒: 永久沉睡后冻结
$cs = $repo->findOneBy(['name' => 'SM-沉睡唤醒']);
if ($cs) {
    echo appendNode(
        $cs, 'w10', '通信冻结365天', 'sourcemarketing.guard', 'action',
        ['action' => 'freeze', 'days' => 365], 'w9'
    )."\n";
    $touched[] = $cs;
}

// ---------------------------------------------------------- 3. 复购: 私域分支降级
$cr = $repo->findOneBy(['name' => 'SM-复购内容流']);
if ($cr) {
    // 找到私域分支最后一个节点作为父
    $parentTemp = null;
    foreach ($cr->getEvents() as $ev) {
        if (str_contains((string) $ev->getName(), '私域')) {
            $parentTemp = $ev->getTempId();
        }
    }
    if ($parentTemp) {
        echo appendNode(
            $cr, 'r99', '强度降级', 'sourcemarketing.guard', 'action',
            ['action' => 'downgrade'], $parentTemp
        )."\n";
        $touched[] = $cr;
    } else {
        echo "WARN  SM-复购内容流 未找到私域分支节点\n";
    }
}

foreach ($touched as $c) {
    $campaignModel->saveEntity($c);
}

echo "\nDONE 已保存 ".count($touched)." 条活动\n";
