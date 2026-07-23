<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';
$kernel = new AppKernel('prod', false);
$kernel->boot();
$c = $kernel->getContainer();
$pdo = new PDO("mysql:host=localhost;port=3306;dbname=mautic;charset=utf8mb4","mautic","mautic");

// ---------- 0) 退订标签(缺失则建) ----------
$tagName = '退订';
$row = $pdo->query("SELECT id FROM lead_tags WHERE tag=".$pdo->quote($tagName))->fetch(PDO::FETCH_ASSOC);
if ($row) {
    $tagId = $row['id'];
    echo "TAG 退订 已存在 #$tagId\n";
} else {
    $pdo->exec("INSERT INTO lead_tags (tag) VALUES (".$pdo->quote($tagName).")");
    $tagId = $pdo->lastInsertId();
    echo "TAG 退订 已创建 #$tagId\n";
}

// ---------- 1) form#2 退订询问 ----------
$formModel = $c->get('mautic.form.model.form');
$alias = 'tuidin_wenxun';

// 幂等: 已存在则跳过
$existing = $formModel->getRepository()->findOneBy(['alias' => $alias]);
if ($existing) {
    $formId = $existing->getId();
    echo "FORM 退订询问 已存在 #$formId (alias=$alias)\n";
    $form = $existing;
} else {
    $form = $formModel->getEntity();
    $form->setName('退订询问');
    $form->setAlias($alias);
    $form->setDescription('潜客/意向客退订时收集退订原因');
    $form->setIsPublished(true);
    $form->setPostAction('message');
    $form->setPostActionProperty('已收到您的退订请求，感谢您之前的关注。');

    $fEmail = new \Mautic\FormBundle\Entity\Field();
    $fEmail->setLabel('邮箱');
    $fEmail->setType('email');
    $fEmail->setAlias('email');
    $fEmail->setLeadField('email');
    $fEmail->setIsRequired(false);
    $fEmail->setOrder(1);
    $fEmail->setForm($form);
    $form->addField($fEmail->getAlias(), $fEmail);

    $fReason = new \Mautic\FormBundle\Entity\Field();
    $fReason->setLabel('退订原因');
    $fReason->setType('textarea');
    $fReason->setAlias('tuiding_yuanyin');
    $fReason->setLeadField('tuiding_yuanyin');
    $fReason->setIsRequired(true);
    $fReason->setOrder(2);
    $fReason->setForm($form);
    $form->addField($fReason->getAlias(), $fReason);

    $fSubmit = new \Mautic\FormBundle\Entity\Field();
    $fSubmit->setLabel('提交退订');
    $fSubmit->setType('button');
    $fSubmit->setAlias('submit');
    $fSubmit->setOrder(3);
    $fSubmit->setForm($form);
    $form->addField($fSubmit->getAlias(), $fSubmit);

    $formModel->saveEntity($form);
    $formId = $form->getId();
    echo "FORM 退订询问 已创建 #$formId (alias=$alias)\n";
}

// ---------- 2) 退订落地页(嵌入 form#2) ----------
$pageModel = $c->get('mautic.page.model.page');
$pageAlias = 'tuidin_wenxun_page';
$exPage = $pageModel->getRepository()->findOneBy(['alias' => $pageAlias]);
if ($exPage) {
    echo "PAGE 退订询问页 已存在 #".$exPage->getId()."\n";
} else {
    $html = <<<HTML
<div style="max-width:560px;margin:48px auto;font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;color:#1f2937;">
  <h1 style="font-size:24px;margin-bottom:8px;">很遗憾看到您离开</h1>
  <p style="color:#6b7280;line-height:1.7;">我们理解每个人的需求都会变化。请告诉我们退订的原因，帮助我们做得更好。提交后您将不再收到我们的营销邮件。</p>
  <div style="margin-top:24px;padding:24px;background:#f9fafb;border-radius:14px;border:1px solid #e5e7eb;">
    {form=tuidin_wenxun}
  </div>
  <p style="margin-top:20px;font-size:12px;color:#9ca3af;">Connexus Travel · 让每一次出发都值得期待</p>
</div>
HTML;
    $page = $pageModel->getEntity();
    $page->setTitle('退订询问');
    $page->setAlias($pageAlias);
    $page->setTemplate('blank');
    $page->setCustomHtml($html);
    $page->setIsPublished(true);
    $page->setLanguage('zh');
    $pageModel->saveEntity($page);
    echo "PAGE 退订询问页 已创建 #".$page->getId()." (alias=$pageAlias)\n";
}

echo "DONE\n";
