<?php
/**
 * zz_setup_source_marketing.php
 * ----------------------------------------------------------------------------
 * Scaffolds the full PRD source-driven marketing layer in Mautic:
 *   - custom fields (source_primary, anchor, freeze, intensity, source attrs…)
 *   - 7 source tags + 7 "首触" segments + 7 "二次" segments
 *   - 7 "首触" campaigns  (arbitrate -> frequency_gate -> send -> log -> mark contacted)
 *   - 7 "二次" campaigns  (frequency_gate -> 四分支: 点击/转化/未点击/沉默)
 *   - 沉睡唤醒 campaign  (沉默 90d -> 换 IP 两轮 -> 永久沉睡)
 *   - 复购内容流 campaign (已交易/VIP + 30-180d 无单 -> 同IP/跨IP/VIP/私域)
 *   - frequency + event log tables for the cross-channel gate
 *   - native frequency config -> 3/WEEK (closest single-channel floor to PRD)
 *
 * Re-runnable (idempotent). Requires SourceMarketingBundle enabled (it is, by AppKernel scan).
 */

require 'vendor/autoload.php';
require_once 'app/AppKernel.php';

$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$listModel   = $c->get('mautic.lead.model.list');
$fieldModel  = $c->get('mautic.lead.model.field');
$emailModel  = $c->get('mautic.email.model.email');
$campaignModel = $c->get('mautic.campaign.model.campaign');
$em          = $c->get('doctrine.orm.entity_manager');
$conn        = $em->getConnection();

$SOURCES = [
    'ctl'     => 'CTL 现有用户',
    'csts'    => 'CSTS 现有用户',
    'crawler' => '爬虫/合作名单',
    'adform'  => 'Google/FB/LinkedIn 广告表单',
    'webform' => '官网咨询表单',
    'tplus'   => 'TPlus 注册用户',
    'spots'   => 'Spots 学员',
];

// ---------------------------------------------------------------- helpers
function makeField($fieldModel, $repo, $label, $alias, $type) {
    $existing = $repo->findOneBy(['alias' => $alias]);
    if ($existing) { echo "SKIP field {$alias}\n"; return $existing; }
    $f = new \Mautic\LeadBundle\Entity\LeadField();
    $f->setLabel($label); $f->setAlias($alias); $f->setType($type);
    $f->setObject('lead'); $f->setGroup('core'); $f->setIsPublished(true); $f->setIsRequired(false);
    if (method_exists($f, 'setOrder')) { $f->setOrder(0); }
    $fieldModel->saveEntity($f);
    echo "CREATED field {$alias} (id={$f->getId()})\n";
    return $f;
}
function makeTag($conn, $tag) {
    $cnt = $conn->fetchOne('SELECT COUNT(*) FROM lead_tags WHERE tag = ?', [$tag]);
    if ($cnt) { echo "SKIP tag {$tag}\n"; return; }
    $conn->executeStatement('INSERT INTO lead_tags (tag) VALUES (?)', [$tag]);
    echo "CREATED tag {$tag}\n";
}
function makeSegment($listModel, $name, $filters) {
    $seg = $listModel->getRepository()->findOneBy(['name' => $name]);
    if ($seg) { echo "SKIP segment {$name}\n"; return $seg; }
    $seg = $listModel->getEntity();
    $seg->setName($name); $seg->setPublicName($name); $seg->setFilters($filters); $seg->setIsPublished(true);
    $listModel->saveEntity($seg);
    echo "CREATED segment {$name} (#{$seg->getId()})\n";
    return $seg;
}
function makeEmail($emailModel, $repo, $name, $subject) {
    $e = $repo->findOneBy(['name' => $name]);
    if ($e) { echo "SKIP email {$name}\n"; return $e; }
    $e = $emailModel->getEntity();
    $e->setName($name);
    $e->setSubject($subject);
    $e->setCustomHtml('<html><body style="font-family:Arial,sans-serif;padding:24px"><h2>'.$subject.'</h2><p>[占位内容 - 请在 Mautic 邮件编辑器中替换为正式文案与素材]</p><p><a href="|URL|">查看详情</a></p></body></html>');
    $e->setEmailType('template');
    $e->setIsPublished(true);
    $emailModel->saveEntity($e);
    echo "CREATED email {$name} (#{$e->getId()})\n";
    return $e;
}
function mkEvent($campaign, $tempId, $name, $type, $eventType, $props, $parentTempId, $decisionPath, $channel, $channelId, $order, &$events, &$canvas) {
    $e = new \Mautic\CampaignBundle\Entity\Event();
    $e->setName($name); $e->setType($type); $e->setEventType($eventType); $e->setProperties($props);
    $e->setCampaign($campaign); $e->setTempId($tempId);
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

// ---------------------------------------------------------------- 1. tables
$conn->executeStatement("CREATE TABLE IF NOT EXISTS sourcemarketing_channel_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT NOT NULL,
    channel VARCHAR(32) NOT NULL,
    asset_id INT NULL,
    sent_at DATETIME NOT NULL,
    INDEX idx_lead_channel (lead_id, channel),
    INDEX idx_lead (lead_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
$conn->executeStatement("CREATE TABLE IF NOT EXISTS sourcemarketing_event_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT NOT NULL,
    source VARCHAR(32) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    INDEX idx_dedup (lead_id, source, event_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
echo "TABLES ready (channel_log / event_log)\n";

// ---------------------------------------------------------------- 2. fields
$frepo = $fieldModel->getRepository();
makeField($fieldModel, $frepo, '首选来源', 'source_primary', 'text');
makeField($fieldModel, $frepo, '最后来源事件', 'last_source_event', 'text');
makeField($fieldModel, $frepo, '时间锚点', 'last_anchor_time', 'datetime');
makeField($fieldModel, $frepo, '锚点来源', 'last_anchor_source', 'text');
makeField($fieldModel, $frepo, '当前生效旅程', 'active_journey', 'text');
makeField($fieldModel, $frepo, '沟通冻结至', 'comm_freeze_until', 'date');
makeField($fieldModel, $frepo, '主题冻结至', 'topic_freeze_until', 'date');
makeField($fieldModel, $frepo, '主题冻结列表', 'topic_frozen_list', 'text');
makeField($fieldModel, $frepo, '触达强度', 'intensity_level', 'text');
makeField($fieldModel, $frepo, '订单状态', 'order_status', 'text');
makeField($fieldModel, $frepo, '出发日期', 'departure_date', 'date');
makeField($fieldModel, $frepo, '行为类型', 'behavior_type', 'text');
makeField($fieldModel, $frepo, '表单类型', 'form_type', 'text');
makeField($fieldModel, $frepo, '咨询类型', 'consult_type', 'text');
makeField($fieldModel, $frepo, '开营日期', 'camp_start_date', 'date');
makeField($fieldModel, $frepo, '结营日期', 'camp_end_date', 'date');
makeField($fieldModel, $frepo, '来源明细', 'source_detail', 'text');

// ---------------------------------------------------------------- 3. tags + segments
foreach ($SOURCES as $s => $label) {
    makeTag($conn, "src_{$s}");
    makeTag($conn, "src_{$s}_contacted");
}
makeTag($conn, 'comm_frozen');
makeTag($conn, 'permanent_sleep');
makeTag($conn, 'reactivated');

foreach ($SOURCES as $s => $label) {
    makeSegment($listModel, "SM-{$s}-首触", [
        ['object' => 'lead', 'glue' => 'and', 'field' => 'tags', 'type' => 'lead', 'filter' => ["src_{$s}"], 'operator' => 'in', 'display' => "标签 含 src_{$s}"],
        ['object' => 'lead', 'glue' => 'and', 'field' => 'tags', 'type' => 'lead', 'filter' => ["src_{$s}_contacted"], 'operator' => '!in', 'display' => "标签 不含 src_{$s}_contacted"],
    ]);
    makeSegment($listModel, "SM-{$s}-二次", [
        ['object' => 'lead', 'glue' => 'and', 'field' => 'tags', 'type' => 'lead', 'filter' => ["src_{$s}_contacted"], 'operator' => 'in', 'display' => "标签 含 src_{$s}_contacted"],
    ]);
}
makeSegment($listModel, 'SM-沉睡', [
    ['object' => 'lead', 'glue' => 'and', 'field' => 'last_activity_date', 'type' => 'datetime', 'filter' => '-90', 'operator' => 'lt', 'display' => '最近活跃 < 90天前'],
    ['object' => 'lead', 'glue' => 'and', 'field' => 'tags', 'type' => 'lead', 'filter' => ['permanent_sleep'], 'operator' => '!in', 'display' => '非永久沉睡'],
]);
makeSegment($listModel, 'SM-复购', [
    ['object' => 'lead', 'glue' => 'and', 'field' => 'order_count', 'type' => 'number', 'filter' => '1', 'operator' => 'gte', 'display' => '订单数 >= 1'],
    ['object' => 'lead', 'glue' => 'and', 'field' => 'last_order_date', 'type' => 'date', 'filter' => '-180', 'operator' => 'gt', 'display' => '近180天内下过单'],
    ['object' => 'lead', 'glue' => 'and', 'field' => 'last_order_date', 'type' => 'date', 'filter' => '-30', 'operator' => 'lt', 'display' => '30天以上无新单'],
]);

// ---------------------------------------------------------------- 4. emails
$erepo = $emailModel->getRepository();
$srcEmail = []; // $srcEmail[$s][role] = emailId
foreach ($SOURCES as $s => $label) {
    $srcEmail[$s]['first'] = makeEmail($emailModel, $erepo, "SM-{$s}-首触", "[{$label}] 首触欢迎")->getId();
    $srcEmail[$s]['A']     = makeEmail($emailModel, $erepo, "SM-{$s}-A升级", "[{$label}] 升级内容")->getId();
    $srcEmail[$s]['B']     = makeEmail($emailModel, $erepo, "SM-{$s}-B转化", "[{$label}] 转化引导/感谢")->getId();
    $srcEmail[$s]['C']     = makeEmail($emailModel, $erepo, "SM-{$s}-C提醒", "[{$label}] 温馨提醒")->getId();
    $srcEmail[$s]['D']     = makeEmail($emailModel, $erepo, "SM-{$s}-D换视角", "[{$label}] 换视角(不复用素材)")->getId();
}
$wakeA = makeEmail($emailModel, $erepo, 'SM-沉睡-唤醒A', '我们想你了 · 年度大事记')->getId();
$wakeB = makeEmail($emailModel, $erepo, 'SM-沉睡-唤醒B', '换个城市，重新开始')->getId();
$repA  = makeEmail($emailModel, $erepo, 'SM-复购-同IP', '同款回归 · 老客专享')->getId();
$repB  = makeEmail($emailModel, $erepo, 'SM-复购-跨IP', '你可能也会喜欢')->getId();
$repC  = makeEmail($emailModel, $erepo, 'SM-复购-VIP', 'VIP 专属折扣')->getId();
$repD  = makeEmail($emailModel, $erepo, 'SM-复购-私域', '邀请加入私域社群')->getId();

// ---------------------------------------------------------------- 5. campaigns: 7 sources (首触 + 二次)
foreach ($SOURCES as $s => $label) {
    // ---- 首触 campaign
    $name = "SM-{$s}-首触";
    $c1 = $campaignModel->getRepository()->findOneBy(['name' => $name]);
    if (!$c1) {
        $c1 = $campaignModel->getEntity();
        $c1->setName($name); $c1->setIsPublished(true);
        $c1->addList($listModel->getRepository()->findOneBy(['name' => "SM-{$s}-首触"]));
        $events = []; $canvas = ['nodes' => [], 'connections' => []];
        mkEvent($c1, 'a1', '锚点仲裁', 'sourcemarketing.arbitrate', 'action', ['source' => $s], null, null, 'sourcemarketing', null, 1, $events, $canvas);
        mkEvent($c1, 'a2', '频次闸门', 'sourcemarketing.frequency_gate', 'decision', ['source' => $s, 'channel' => 'email'], 'a1', null, 'sourcemarketing', null, 2, $events, $canvas);
        mkEvent($c1, 'a3', '发首触邮件', 'email.send', 'action', ['email' => $srcEmail[$s]['first']], 'a2', 'yes', 'email', $srcEmail[$s]['first'], 3, $events, $canvas);
        mkEvent($c1, 'a4', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'a3', null, 'sourcemarketing', null, 4, $events, $canvas);
        mkEvent($c1, 'a5', '标记已联系', 'lead.changetags', 'action', ['add_tags' => ["src_{$s}_contacted"], 'remove_tags' => []], 'a4', null, 'lead', null, 5, $events, $canvas);
        mkEvent($c1, 'a6', '超频挂起', 'lead.changetags', 'action', ['add_tags' => ['freq_held'], 'remove_tags' => []], 'a2', 'no', 'lead', null, 6, $events, $canvas);
        $c1->setCanvasSettings($canvas);
        $campaignModel->saveEntity($c1);
        echo "CREATED campaign {$name} (#{$c1->getId()})\n";
    } else { echo "SKIP campaign {$name}\n"; }

    // ---- 二次 campaign (四分支: 点击/转化/未点击/沉默)
    $name = "SM-{$s}-二次";
    $c2 = $campaignModel->getRepository()->findOneBy(['name' => $name]);
    if (!$c2) {
        $c2 = $campaignModel->getEntity();
        $c2->setName($name); $c2->setIsPublished(true);
        $c2->addList($listModel->getRepository()->findOneBy(['name' => "SM-{$s}-二次"]));
        $events = []; $canvas = ['nodes' => [], 'connections' => []];
        // entry gate
        mkEvent($c2, 'b1', '频次闸门', 'sourcemarketing.frequency_gate', 'decision', ['source' => $s, 'channel' => 'email'], null, null, 'sourcemarketing', null, 1, $events, $canvas);
        // 分支A 点击升级
        mkEvent($c2, 'b2', '发升级内容A', 'email.send', 'action', ['email' => $srcEmail[$s]['A']], 'b1', 'yes', 'email', $srcEmail[$s]['A'], 2, $events, $canvas);
        mkEvent($c2, 'b3', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'b2', null, 'sourcemarketing', null, 3, $events, $canvas);
        mkEvent($c2, 'b4', '是否点击A?', 'email.click', 'decision', ['urls' => []], 'b2', null, 'email', $srcEmail[$s]['A'], 4, $events, $canvas);
        mkEvent($c2, 'b5', '发转化引导B', 'email.send', 'action', ['email' => $srcEmail[$s]['B']], 'b4', 'yes', 'email', $srcEmail[$s]['B'], 5, $events, $canvas);
        mkEvent($c2, 'b6', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'b5', null, 'sourcemarketing', null, 6, $events, $canvas);
        // 分支C 未点击 -> 提醒
        mkEvent($c2, 'b7', '发提醒C', 'email.send', 'action', ['email' => $srcEmail[$s]['C']], 'b4', 'no', 'email', $srcEmail[$s]['C'], 7, $events, $canvas);
        mkEvent($c2, 'b8', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'b7', null, 'sourcemarketing', null, 8, $events, $canvas);
        mkEvent($c2, 'b9', '点击C?', 'email.click', 'decision', ['urls' => []], 'b7', null, 'email', $srcEmail[$s]['C'], 9, $events, $canvas);
        mkEvent($c2, 'b10', '发转化引导B', 'email.send', 'action', ['email' => $srcEmail[$s]['B']], 'b9', 'yes', 'email', $srcEmail[$s]['B'], 10, $events, $canvas);
        // 分支D 沉默 -> 换视角(不复用素材)
        mkEvent($c2, 'b11', '发换视角D', 'email.send', 'action', ['email' => $srcEmail[$s]['D']], 'b9', 'no', 'email', $srcEmail[$s]['D'], 11, $events, $canvas);
        mkEvent($c2, 'b12', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'b11', null, 'sourcemarketing', null, 12, $events, $canvas);
        // 分支B' 转化(下单确认页) 独立入口
        mkEvent($c2, 'b13', '是否到下单页?', 'page.pagehit', 'decision', ['pages' => [3]], null, null, 'page', 3, 13, $events, $canvas);
        mkEvent($c2, 'b14', '发转化感谢B', 'email.send', 'action', ['email' => $srcEmail[$s]['B']], 'b13', 'yes', 'email', $srcEmail[$s]['B'], 14, $events, $canvas);
        mkEvent($c2, 'b15', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'b14', null, 'sourcemarketing', null, 15, $events, $canvas);
        // 超频挂起
        mkEvent($c2, 'b16', '超频挂起', 'lead.changetags', 'action', ['add_tags' => ['freq_held'], 'remove_tags' => []], 'b1', 'no', 'lead', null, 16, $events, $canvas);
        $c2->setCanvasSettings($canvas);
        $campaignModel->saveEntity($c2);
        echo "CREATED campaign {$name} (#{$c2->getId()})\n";
    } else { echo "SKIP campaign {$name}\n"; }
}

// ---------------------------------------------------------------- 6. 沉睡唤醒
if (!$campaignModel->getRepository()->findOneBy(['name' => 'SM-沉睡唤醒'])) {
    $cs = $campaignModel->getEntity();
    $cs->setName('SM-沉睡唤醒'); $cs->setIsPublished(true);
    $cs->addList($listModel->getRepository()->findOneBy(['name' => 'SM-沉睡']));
    $events = []; $canvas = ['nodes' => [], 'connections' => []];
    mkEvent($cs, 'w1', '频次闸门', 'sourcemarketing.frequency_gate', 'decision', ['source' => 'sleep', 'channel' => 'email'], null, null, 'sourcemarketing', null, 1, $events, $canvas);
    mkEvent($cs, 'w2', '发唤醒A(年度大事记)', 'email.send', 'action', ['email' => $wakeA], 'w1', 'yes', 'email', $wakeA, 2, $events, $canvas);
    mkEvent($cs, 'w3', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'w2', null, 'sourcemarketing', null, 3, $events, $canvas);
    mkEvent($cs, 'w4', '30天内有打开?', 'email.open', 'decision', [], 'w2', null, 'email', $wakeA, 4, $events, $canvas);
    mkEvent($cs, 'w5', '标记已唤醒', 'lead.changetags', 'action', ['add_tags' => ['reactivated'], 'remove_tags' => []], 'w4', 'yes', 'lead', null, 5, $events, $canvas);
    mkEvent($cs, 'w6', '发唤醒B(换IP)', 'email.send', 'action', ['email' => $wakeB], 'w4', 'no', 'email', $wakeB, 6, $events, $canvas);
    mkEvent($cs, 'w7', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'w6', null, 'sourcemarketing', null, 7, $events, $canvas);
    mkEvent($cs, 'w8', '再30天无响应?', 'email.open', 'decision', [], 'w6', null, 'email', $wakeB, 8, $events, $canvas);
    mkEvent($cs, 'w9', '永久沉睡', 'lead.changetags', 'action', ['add_tags' => ['permanent_sleep'], 'remove_tags' => []], 'w8', 'no', 'lead', null, 9, $events, $canvas);
    $cs->setCanvasSettings($canvas);
    $campaignModel->saveEntity($cs);
    echo "CREATED campaign SM-沉睡唤醒 (#{$cs->getId()})\n";
} else { echo "SKIP campaign SM-沉睡唤醒\n"; }

// ---------------------------------------------------------------- 7. 复购内容流
if (!$campaignModel->getRepository()->findOneBy(['name' => 'SM-复购内容流'])) {
    $cr = $campaignModel->getEntity();
    $cr->setName('SM-复购内容流'); $cr->setIsPublished(true);
    $cr->addList($listModel->getRepository()->findOneBy(['name' => 'SM-复购']));
    $events = []; $canvas = ['nodes' => [], 'connections' => []];
    mkEvent($cr, 'r1', '频次闸门', 'sourcemarketing.frequency_gate', 'decision', ['source' => 'repurchase', 'channel' => 'email'], null, null, 'sourcemarketing', null, 1, $events, $canvas);
    mkEvent($cr, 'r2', '发同IP复购A', 'email.send', 'action', ['email' => $repA], 'r1', 'yes', 'email', $repA, 2, $events, $canvas);
    mkEvent($cr, 'r3', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'r2', null, 'sourcemarketing', null, 3, $events, $canvas);
    mkEvent($cr, 'r4', '是否点击?', 'email.click', 'decision', ['urls' => []], 'r2', null, 'email', $repA, 4, $events, $canvas);
    mkEvent($cr, 'r5', '发跨IP推荐B', 'email.send', 'action', ['email' => $repB], 'r4', 'yes', 'email', $repB, 5, $events, $canvas);
    mkEvent($cr, 'r6', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'r5', null, 'sourcemarketing', null, 6, $events, $canvas);
    mkEvent($cr, 'r7', 'VIP折扣C', 'email.send', 'action', ['email' => $repC], 'r4', 'no', 'email', $repC, 7, $events, $canvas);
    mkEvent($cr, 'r8', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'r7', null, 'sourcemarketing', null, 8, $events, $canvas);
    // 私域分支(独立入口: 已加企微/社群标签)
    mkEvent($cr, 'r9', '是否私域标签?', 'lead.changetags', 'decision', [], null, null, 'lead', null, 9, $events, $canvas);
    mkEvent($cr, 'r10', '发私域邀请D', 'email.send', 'action', ['email' => $repD], 'r9', 'yes', 'email', $repD, 10, $events, $canvas);
    mkEvent($cr, 'r11', '记录渠道发送', 'sourcemarketing.log_channel', 'action', ['channel' => 'email'], 'r10', null, 'sourcemarketing', null, 11, $events, $canvas);
    $cr->setCanvasSettings($canvas);
    $campaignModel->saveEntity($cr);
    echo "CREATED campaign SM-复购内容流 (#{$cr->getId()})\n";
} else { echo "SKIP campaign SM-复购内容流\n"; }

// ---------------------------------------------------------------- 8. native frequency floor -> 3/WEEK
$local = 'config/local.php';
$orig = file_get_contents($local);
if (!preg_match("/'email_frequency_number'\s*=>\s*3\b/", $orig)) {
    copy($local, $local.'.bak-'.date('YmdHis'));
    $new = preg_replace("/'email_frequency_number'\s*=>\s*[^,]+,/", "'email_frequency_number' => 3,", $orig);
    $new = preg_replace("/'email_frequency_time'\s*=>\s*'[^']*'/", "'email_frequency_time' => 'WEEK'", $new);
    if (!preg_match("/'sourcemarketing_token'/", $new)) {
        $new = preg_replace("/(\$configuration\s*=\s*array\(|\$parameters\s*=\s*array\()/", "$1\n    'sourcemarketing_token' => 'sourcemarketing-dev-secret',", $new, 1);
    }
    file_put_contents($local, $new);
    echo "NATIVE frequency set to 3/WEEK (PRD single-channel floor). Backup: {$local}.bak-*\n";
} else {
    echo "NATIVE frequency already 3/WEEK\n";
}

echo "DONE\n";
