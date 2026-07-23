<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();

$emailModel = $c->get('mautic.email.model.email');
$pageModel  = $c->get('mautic.page.model.page');

function mkEmail($model, $name, $alias, $subject, $html) {
    $ex = $model->getRepository()->findOneBy(['name' => $name]);
    if ($ex) { echo "EMAIL [$name] 已存在 #".$ex->getId()."\n"; return $ex; }
    $e = $model->getEntity();
    $e->setName($name);
    $e->setSubject($subject);
    $e->setTemplate('blank');
    $e->setCustomHtml($html);
    $e->setEmailType('template');
    $e->setIsPublished(true);
    $model->saveEntity($e);
    echo "EMAIL [$name] 已创建 #".$e->getId()."\n";
    return $e;
}
function mkPage($model, $title, $alias, $html) {
    $ex = $model->getRepository()->findOneBy(['alias' => $alias]);
    if ($ex) { echo "PAGE [$alias] 已存在 #".$ex->getId()."\n"; return $ex; }
    $p = $model->getEntity();
    $p->setTitle($title);
    $p->setAlias($alias);
    $p->setTemplate('blank');
    $p->setCustomHtml($html);
    $p->setIsPublished(true);
    $p->setLanguage('zh');
    $model->saveEntity($p);
    echo "PAGE [$alias] 已创建 #".$p->getId()."\n";
    return $p;
}

// ---------- 下单确认落地页 (先建, 拿 ID 供迪士尼页引用) ----------
$orderConfirm = mkPage($pageModel, '下单确认', 'order_confirm', <<<HTML
<div style="max-width:560px;margin:48px auto;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;color:#1f2937;text-align:center;">
  <div style="font-size:48px;">🎉</div>
  <h1 style="font-size:26px;margin:12px 0;">已收到您的下单意向</h1>
  <p style="color:#6b7280;line-height:1.8;">我们的行程顾问将在 24 小时内与您联系，为您锁定上海迪士尼亲子专属权益。</p>
  <p style="margin-top:24px;"><a href="https://www.connexustravel.com.cn/" style="display:inline-block;padding:12px 28px;background:#2563eb;color:#fff;border-radius:999px;text-decoration:none;font-weight:600;">返回官网查看更多</a></p>
</div>
HTML
);
$orderConfirmId = $orderConfirm->getId();

// ---------- 上海迪士尼介绍落地页 (我要下单 -> 下单确认页) ----------
$shDisney = mkPage($pageModel, '上海迪士尼介绍', 'sh_disney', <<<HTML
<div style="max-width:720px;margin:40px auto;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;color:#1f2937;">
  <h1 style="font-size:30px;margin-bottom:8px;">上海迪士尼 · 亲子奇遇之旅</h1>
  <p style="color:#6b7280;line-height:1.8;">从奇幻童话城堡到创极速光轮，一场专属于家庭的魔法时光。我们为您打包了门票 + 快速通行证 + 周边酒店的一站式方案。</p>
  <div style="margin:28px 0;padding:24px;background:linear-gradient(135deg,#eff6ff,#faf5ff);border-radius:16px;">
    <h2 style="font-size:20px;margin:0 0 8px;">套餐亮点</h2>
    <ul style="line-height:2;color:#374151;">
      <li>🎟️ 1~2 日门票，儿童/成人同价优惠</li>
      <li>⚡ 创极速光轮优先通道</li>
      <li>🏨 迪士尼主题酒店或周边精选住宿</li>
      <li>👨‍👩‍👧 专属亲子行程顾问 1v1</li>
    </ul>
  </div>
  <p style="text-align:center;">
    <a href="{pagelink=$orderConfirmId}" style="display:inline-block;padding:14px 36px;background:#d97706;color:#fff;border-radius:999px;text-decoration:none;font-weight:700;font-size:16px;">我要下单</a>
  </p>
  <p style="margin-top:20px;font-size:12px;color:#9ca3af;text-align:center;">Connexus Travel · 让每一次出发都值得期待</p>
</div>
HTML
);
$shDisneyId = $shDisney->getId();

// ---------- 潜客邮件 (链接到官网 + 退订页#2) ----------
$qianke = mkEmail($emailModel, '潜客欢迎邮件', 'qianke_email', '欢迎来到 Connexus Travel｜开启您的专属旅程', <<<HTML
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;color:#1f2937;">
  <h1 style="font-size:24px;">您好，欢迎加入 Connexus Travel 👋</h1>
  <p style="line-height:1.8;color:#374151;">感谢您的关注。我们专注于为家庭与旅行者打造值得期待的旅程——从主题乐园到深度定制，总有一款适合您。</p>
  <p style="text-align:center;margin:28px 0;">
    <a href="https://www.connexustravel.com.cn/" style="display:inline-block;padding:14px 34px;background:#2563eb;color:#fff;border-radius:999px;text-decoration:none;font-weight:700;">浏览官网 · 发现旅程</a>
  </p>
  <p style="font-size:12px;color:#9ca3af;">如果您不希望再收到此类邮件，<a href="{pagelink=2}">点击此处退订并告诉我们原因</a>。</p>
</div>
HTML
);

// ---------- 意向客每周活动推荐邮件 (CTA -> 上海迪士尼页) ----------
$weekly = mkEmail($emailModel, '意向客每周活动推荐', 'yixiang_weekly', '本周精选 · 上海迪士尼亲子之旅等您开启', <<<HTML
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;color:#1f2937;">
  <h1 style="font-size:24px;">本周为您精选 ✨</h1>
  <p style="line-height:1.8;color:#374151;">根据您的兴趣，我们准备了上海迪士尼亲子奇遇之旅——门票、快速通道与酒店一站式打包。</p>
  <p style="text-align:center;margin:28px 0;">
    <a href="{pagelink=$shDisneyId}" style="display:inline-block;padding:14px 34px;background:#d97706;color:#fff;border-radius:999px;text-decoration:none;font-weight:700;">查看上海迪士尼介绍</a>
  </p>
  <p style="font-size:12px;color:#9ca3af;"><a href="{unsubscribe_url}">退订邮件</a></p>
</div>
HTML
);

echo "SUMMARY: orderConfirm=#$orderConfirmId shDisney=#$shDisneyId qiankeEmail=#".$qianke->getId()." weeklyEmail=#".$weekly->getId()."\n";
echo "DONE\n";
