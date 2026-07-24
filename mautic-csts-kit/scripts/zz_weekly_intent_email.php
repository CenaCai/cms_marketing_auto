<?php
/**
 * 每周给「意向客」分群发送本周活动推荐邮件 (email#8)。
 * 由 Windows 任务计划程序每周一 09:00 调用。
 * 注意：本脚本仅负责"按周重发"，新意向客进入战役时已由 Campaign#9 ev#17 首发一次。
 *
 * 修复说明（2026-07-24）：
 *   原脚本把"分群对象(LeadList)"直接当联系人传给 EmailModel::sendEmail()，
 *   触发 "Cannot use object of type Mautic\LeadBundle\Entity\LeadList as array"
 *   （sendEmail 内部用 $lead['id'] 遍历，对象不可数组访问）。
 *   且 email#8 是 template 型，不能走 sendEmailToLists（该方法要求 list 型）。
 *   正确做法：从 lead_lists_leads 取出分群内真实联系人(lead 数组)，再 sendEmail。
 *   另：sendEmail 多收件人时返回的是"失败联系人数组"而非 ['sent'/'failed']，
 *   故成功数 = 总数 - 失败数。
 */

require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$emailModel = $c->get('mautic.email.model.email');
$listModel  = $c->get('mautic.lead.model.list');
$leadModel  = $c->get('mautic.lead.model.lead');

$email = $emailModel->getEntity(8);   // 意向客每周活动推荐 (template 型)
$seg   = $listModel->getEntity(10);   // 意向客 分群

if (!$email || !$seg) {
    fwrite(STDERR, "email#8 或 segment#10 不存在\n");
    exit(1);
}

// 取分群 #10 内的联系人 ID（排除手动移除的）
$conn = $c->get('database_connection');
$rows = $conn->fetchAllAssociative(
    'SELECT lead_id FROM lead_lists_leads WHERE leadlist_id = ? AND manually_removed = 0',
    [$seg->getId()]
);
$ids = array_column($rows, 'lead_id');

if (empty($ids)) {
    echo sprintf("[%s] 分群 #10 内无联系人，跳过\n", date('Y-m-d H:i:s'));
    echo "DONE\n";
    exit(0);
}

// 构造 sendEmail 需要的联系人数组（含 id/email 等字段，供令牌渲染与收件人解析）
$leads = [];
foreach ($ids as $id) {
    $fields = $leadModel->getRepository()->getFieldValues((int) $id);
    $fields['id'] = (int) $id;   // 确保含 id，供 sendEmail 索引
    $leads[] = $fields;
}

$result = $emailModel->sendEmail($email, $leads);

// sendEmail 多收件人时返回"失败联系人数组"（空数组=全部成功）
$leadsCount  = count($leads);
$failedCount = is_array($result) ? count($result) : ($result ? 0 : $leadsCount);
$sentCount   = $leadsCount - $failedCount;

echo sprintf(
    "[%s] 每周意向客邮件已触发: 成功=%d 失败=%d\n",
    date('Y-m-d H:i:s'),
    $sentCount,
    $failedCount
);
echo "DONE\n";
