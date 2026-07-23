<?php
/**
 * 每周给「意向客」分群发送本周活动推荐邮件 (email#8)。
 * 由 Windows 任务计划程序每周一 09:00 调用。
 * 注意：本脚本仅负责"按周重发"，新意向客进入战役时已由 Campaign#9 ev#17 首发一次。
 */
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$emailModel = $c->get('mautic.email.model.email');
$listModel  = $c->get('mautic.lead.model.list');

$email = $emailModel->getEntity(8);   // 意向客每周活动推荐
$seg   = $listModel->getEntity(10);   // 意向客

if (!$email || !$seg) {
    fwrite(STDERR, "email#8 或 segment#10 不存在\n");
    exit(1);
}

// 发送邮件到分群（Mautic 会向分群内所有联系人发送）
$result = $emailModel->sendEmail($email, [$seg]);
echo sprintf(
    "[%s] 每周意向客邮件已触发: 成功=%d 失败=%d\n",
    date('Y-m-d H:i:s'),
    $result['sent'] ?? 0,
    $result['failed'] ?? 0
);
echo "DONE\n";
