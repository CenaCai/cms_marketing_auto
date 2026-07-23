<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';

$kernel = new AppKernel('prod', false);
$kernel->boot();
$container = $kernel->getContainer();

$listModel     = $container->get('mautic.lead.model.list');
$campaignModel = $container->get('mautic.campaign.model.campaign');
$userModel     = $container->get('mautic.user.model.user');

$admin = $userModel->getEntity(1);

function makeSegment($listModel, $name, $alias, $filters, $admin)
{
    $existing = $listModel->getRepository()->findOneBy(['alias' => $alias]);
    if ($existing) {
        echo "SKIP segment (exists): {$alias} id={$existing->getId()}\n";
        return $existing;
    }
    $l = new \Mautic\LeadBundle\Entity\LeadList();
    $l->setName($name);
    $l->setAlias($alias);
    $l->setFilters($filters);
    $l->setIsPublished(true);
    $l->setCreatedBy($admin);
    $l->setDateAdded(new \DateTime());
    $listModel->saveEntity($l);
    echo "CREATED segment: {$name} ({$alias}) id={$l->getId()}\n";
    return $l;
}

function makeCampaign($campaignModel, $name, $segment, $stageId, $admin)
{
    $existing = $campaignModel->getRepository()->findOneBy(['name' => $name]);
    if ($existing) {
        echo "SKIP campaign (exists): {$name} id={$existing->getId()}\n";
        return $existing;
    }
    $c = new \Mautic\CampaignBundle\Entity\Campaign();
    $c->setName($name);
    $c->setIsPublished(true);
    $c->setCreatedBy($admin);
    $c->setDateAdded(new \DateTime());
    $c->setCanvasSettings(['nodes' => [], 'connections' => []]);
    $c->addList($segment);
    $campaignModel->saveEntity($c); // flush to obtain id

    $e = new \Mautic\CampaignBundle\Entity\Event();
    $e->setName('自动升 S' . $stageId);
    $e->setType('stage.change');
    $e->setEventType('action');
    $e->setOrder(1);
    $e->setProperties(['stage' => $stageId]);
    $e->setCampaign($c);
    $e->setTempId('stage_' . $stageId);
    $c->addEvent('stage_' . $stageId, $e);
    $campaignModel->saveEntity($c);
    echo "CREATED campaign: {$name} id={$c->getId()} -> stage.change S{$stageId}\n";
    return $c;
}

// S4: first paid order (order_count >= 1)
$segS4 = makeSegment($listModel, '积分段外-首单支付（自动升S4）', 'stage-auto-s4',
    [['object' => 'lead', 'glue' => 'and', 'field' => 'order_count', 'type' => 'number', 'filter' => '1', 'operator' => 'gte', 'display' => null]],
    $admin);
makeCampaign($campaignModel, '订单驱动-首单自动升S4', $segS4, 4, $admin);

// S5: >=3 orders OR total spent >= threshold (default 1000)
$segS5 = makeSegment($listModel, '复购忠诚（自动升S5）', 'stage-auto-s5',
    [
        ['object' => 'lead', 'glue' => 'and', 'field' => 'order_count', 'type' => 'number', 'filter' => '3', 'operator' => 'gte', 'display' => null],
        ['object' => 'lead', 'glue' => 'or', 'field' => 'total_spent', 'type' => 'number', 'filter' => '1000', 'operator' => 'gte', 'display' => null],
    ],
    $admin);
makeCampaign($campaignModel, '复购忠诚自动升S5', $segS5, 5, $admin);

// S6: dormant 90+ days (last_activity_date <= 90 days ago)
$segS6 = makeSegment($listModel, '沉睡流失（自动升S6）', 'stage-auto-s6',
    [['object' => 'lead', 'glue' => 'and', 'field' => 'last_activity_date', 'type' => 'date', 'filter' => '-90 days', 'operator' => 'lte', 'display' => null]],
    $admin);
makeCampaign($campaignModel, '沉睡自动升S6', $segS6, 6, $admin);

echo "DONE\n";
