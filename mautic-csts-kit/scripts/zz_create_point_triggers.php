<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';

$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$pdo = new PDO('mysql:host=localhost;port=3306;dbname=mautic;charset=utf8mb4', 'mautic', 'mautic');

// 1) 阶段标签（幂等）
function ensureTag($pdo, $name, $desc) {
    $s = $pdo->prepare('SELECT id FROM lead_tags WHERE tag = ?');
    $s->execute([$name]);
    $id = $s->fetchColumn();
    if ($id) { echo "SKIP tag (exists): $name id=$id\n"; return (int)$id; }
    $pdo->prepare('INSERT INTO lead_tags (tag, description, uuid) VALUES (?, ?, UUID())')->execute([$name, $desc]);
    $id = (int)$pdo->lastInsertId();
    echo "CREATED tag: $name id=$id\n";
    return $id;
}
$tagS2 = ensureTag($pdo, 'S2-意向客', '阶段标签：意向客。积分达 20 分时由积分触发器自动打标，对应 S2 阶段。');
$tagS3 = ensureTag($pdo, 'S3-高意向', '阶段标签：高意向。积分达 50 分时由积分触发器自动打标，对应 S3 阶段。');

// 2) 营销邮件（幂等，按 name 查找）
$emailModel = $c->get('mautic.email.model.email');

function ensureEmail($emailModel, $name, $subject, $html) {
    $existing = $emailModel->getRepository()->findOneBy(['name' => $name]);
    if ($existing) { echo "SKIP email (exists): $name id=".$existing->getId()."\n"; return $existing; }
    $email = new \Mautic\EmailBundle\Entity\Email();
    $email->setName($name);
    $email->setSubject($subject);
    $email->setTemplate('blank');          // 与现有营销邮件一致的主题
    $email->setCustomHtml($html);          // 正文 HTML
    $email->setEmailType('template');      // 营销邮件（可被触发器发送）
    $email->setIsPublished(true);
    $emailModel->saveEntity($email);
    echo "CREATED email: $name id=".$email->getId()."\n";
    return $email;
}

$s2Html = <<<HTML
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">
  <div style="background:linear-gradient(135deg,#0ea5e9,#6366f1);padding:32px 24px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;">🎒 您的专属旅行优惠已就位</h1>
    <p style="color:#e0f2fe;margin:8px 0 0;font-size:14px;">再不下手，心仪的旅程就要被别人锁定啦</p>
  </div>
  <div style="background:#fff;padding:28px 24px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;">
    <p style="font-size:15px;line-height:1.7;">亲爱的旅行者，感谢您一路的探索与热情（已累计 <strong>20 积分</strong>，进入 <strong>意向客</strong> 阶段）。我们为您准备了三重专属福利：</p>
    <ul style="font-size:15px;line-height:1.9;padding-left:20px;">
      <li><strong>降价提醒</strong>：您关注的热门线路近期限时降价，第一时间通知您。</li>
      <li><strong>限时特惠</strong>：本周内下单，立享会员专属折扣。</li>
      <li><strong>攻略推送</strong>：附上精选目的地出行攻略，帮您少走弯路。</li>
    </ul>
    <div style="text-align:center;margin:28px 0 8px;">
      <a href="#" style="background:#6366f1;color:#fff;text-decoration:none;padding:13px 30px;border-radius:8px;font-size:15px;font-weight:600;">立即查看专属优惠 →</a>
    </div>
    <p style="font-size:12px;color:#9ca3af;margin-top:24px;border-top:1px solid #f3f4f6;padding-top:16px;">本邮件由 CSTS 旅行会员系统自动发送，基于您的积分阶段触发。</p>
  </div>
</div>
HTML;

$s3Html = <<<HTML
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">
  <div style="background:linear-gradient(135deg,#f59e0b,#ef4444);padding:32px 24px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;">🚀 限量加急券 + 专属行程顾问</h1>
    <p style="color:#fef3c7;margin:8px 0 0;font-size:14px;">为您锁定心仪的旅程</p>
  </div>
  <div style="background:#fff;padding:28px 24px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;">
    <p style="font-size:15px;line-height:1.7;">尊敬的贵宾，您已累计 <strong>50 积分</strong>，进入 <strong>高意向</strong> 阶段——这是我们最看重的一类旅行者。为您保留以下专属权益：</p>
    <ul style="font-size:15px;line-height:1.9;padding-left:20px;">
      <li><strong>限量加急券</strong>：优先锁定热门档期与稀缺房源。</li>
      <li><strong>一对一行程顾问</strong>：资深旅行顾问 1v1 为您定制路线。</li>
      <li><strong>久未出行召回</strong>：这封邮件为您保留专属权益，随时可唤醒旅程。</li>
    </ul>
    <div style="text-align:center;margin:28px 0 8px;">
      <a href="#" style="background:#ef4444;color:#fff;text-decoration:none;padding:13px 30px;border-radius:8px;font-size:15px;font-weight:600;">预约专属行程顾问 →</a>
    </div>
    <p style="font-size:12px;color:#9ca3af;margin-top:24px;border-top:1px solid #f3f4f6;padding-top:16px;">本邮件由 CSTS 旅行会员系统自动发送，基于您的积分阶段触发。</p>
  </div>
</div>
HTML;

$emailS2 = ensureEmail($emailModel, 'S2-意向客·旅行优惠与攻略推送', '🎒 您的专属旅行优惠已就位，再不下手就错过啦', $s2Html);
$emailS3 = ensureEmail($emailModel, 'S3-高意向·加急券与行程顾问', '🚀 限量加急券 + 专属行程顾问，为您锁定心仪旅程', $s3Html);

// 3) 积分触发器：确保每个触发器含「打标签 + 发营销邮件」两个事件（幂等升级）
$triggerModel = $c->get('mautic.point.model.trigger');

function ensureTrigger($triggerModel, $name, $points, $tagName, $email, $desc) {
    $existing = $triggerModel->getRepository()->findOneBy(['name' => $name]);
    $isNew = false;
    if (!$existing) {
        $existing = new \Mautic\PointBundle\Entity\Trigger();
        $existing->setName($name);
        $existing->setDescription($desc);
        $existing->setPoints($points);
        $isNew = true;
    }
    $existing->setIsPublished(true);
    $existing->setTriggerExistingLeads(false); // 存量联系人由下方回填处理，避免保存期重处理

    // 收集已有事件类型
    $have = [];
    foreach ($existing->getEvents() as $ev) { $have[$ev->getType()] = true; }

    // 事件1：打阶段标签
    if (!isset($have['lead.changetags'])) {
        $ev = new \Mautic\PointBundle\Entity\TriggerEvent();
        $ev->setName('自动打阶段标签');
        $ev->setType('lead.changetags');
        $ev->setProperties(['add_tags' => [$tagName], 'remove_tags' => []]);
        $ev->setOrder(1);
        $ev->setTrigger($existing);
        $existing->addTriggerEvent('tag_event', $ev);
        echo "  + added event lead.changetags (tag=$tagName)\n";
    }

    // 事件2：发营销邮件
    if (!isset($have['email.send'])) {
        $ev = new \Mautic\PointBundle\Entity\TriggerEvent();
        $ev->setName('发送营销邮件');
        $ev->setType('email.send');
        $ev->setProperties(['email' => (int)$email->getId()]);
        $ev->setOrder(2);
        $ev->setTrigger($existing);
        $existing->addTriggerEvent('email_event', $ev);
        echo "  + added event email.send (email#".$email->getId().")\n";
    }

    $triggerModel->saveEntity($existing);
    echo ($isNew ? "CREATED" : "UPDATED")." trigger: $name id=".$existing->getId()." (points>=$points)\n";
    return $existing;
}
ensureTrigger($triggerModel, '积分达20分→S2标签', 20, 'S2-意向客', $emailS2, '积分达 20 分：自动打 S2-意向客 标签，并发送旅行优惠/攻略营销邮件。');
ensureTrigger($triggerModel, '积分达50分→S3标签', 50, 'S3-高意向', $emailS3, '积分达 50 分：自动打 S3-高意向 标签，并发送加急券/行程顾问营销邮件。');

// 4) 存量回填：当前积分已达标者直接打标（lead_tags_xref，幂等）
function backfill($pdo, $minPoints, $tagId, $label) {
    $ins = $pdo->prepare(
        'INSERT INTO lead_tags_xref (lead_id, tag_id)
         SELECT l.id, ? FROM leads l
         WHERE l.points >= ?
           AND NOT EXISTS (SELECT 1 FROM lead_tags_xref x WHERE x.lead_id=l.id AND x.tag_id=?)'
    );
    $ins->execute([$tagId, $minPoints, $tagId]);
    echo "backfilled $label (points>=$minPoints): ".$ins->rowCount()." leads tagged\n";
}
backfill($pdo, 20, $tagS2, 'S2-意向客');
backfill($pdo, 50, $tagS3, 'S3-高意向');

echo "DONE\n";
