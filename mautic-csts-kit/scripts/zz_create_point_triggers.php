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

// 2) 积分触发器（幂等）
$triggerModel = $c->get('mautic.point.model.trigger');

function makeTrigger($triggerModel, $name, $points, $tagName, $desc) {
    $existing = $triggerModel->getRepository()->findOneBy(['name' => $name]);
    if ($existing) { echo "SKIP trigger (exists): $name id=".$existing->getId()."\n"; return $existing; }

    $trigger = new \Mautic\PointBundle\Entity\Trigger();
    $trigger->setName($name);
    $trigger->setDescription($desc);
    $trigger->setPoints($points);
    $trigger->setIsPublished(true);
    $trigger->setTriggerExistingLeads(false); // 存量联系人由下方回填步骤处理，避免保存期重处理

    $event = new \Mautic\PointBundle\Entity\TriggerEvent();
    $event->setName('自动打阶段标签');
    $event->setType('lead.changetags');
    // lead.changetags 处理器把 add_tags 直接交给 modifyTags，期望【标签名字符串】而非 ID
    $event->setProperties(['add_tags' => [$tagName], 'remove_tags' => []]);
    $event->setOrder(1);
    $event->setTrigger($trigger);
    $trigger->addTriggerEvent('stage_tag', $event);

    $triggerModel->saveEntity($trigger);
    echo "CREATED trigger: $name id=".$trigger->getId()." (points>=$points -> tag '$tagName')\n";
    return $trigger;
}
makeTrigger($triggerModel, '积分达20分→S2标签', 20, 'S2-意向客', '联系人积分达到 20 分时，自动打上 S2-意向客 标签。');
makeTrigger($triggerModel, '积分达50分→S3标签', 50, 'S3-高意向', '联系人积分达到 50 分时，自动打上 S3-高意向 标签。');

// 3) 存量回填：当前积分已达标者直接打标（lead_tags_xref，幂等）
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
