<?php
require 'vendor/autoload.php';
require_once 'app/AppKernel.php';

use Mautic\LeadBundle\Entity\LeadField;

$kernel = new AppKernel('prod', false);
$kernel->boot();
$container = $kernel->getContainer();

$fieldModel = $container->get('mautic.lead.model.field');
$repo       = $fieldModel->getRepository();

function makeField($fieldModel, $repo, $label, $alias, $type, $default)
{
    $existing = $repo->findOneBy(['alias' => $alias]);
    if ($existing) {
        echo "SKIP (exists): {$alias} (id={$existing->getId()})\n";
        return $existing;
    }
    $f = new LeadField();
    $f->setLabel($label);
    $f->setAlias($alias);
    $f->setType($type);
    $f->setObject('lead');
    $f->setGroup('core');
    $f->setDefaultValue($default);
    $f->setIsPublished(true);
    $f->setIsRequired(false);
    if (method_exists($f, 'setOrder')) {
        $f->setOrder(0);
    }
    $fieldModel->saveEntity($f);
    echo "CREATED: {$label} ({$alias}, type={$type}) id={$f->getId()}\n";
    return $f;
}

makeField($fieldModel, $repo, '订单数', 'order_count', 'number', 0);
makeField($fieldModel, $repo, '累计消费金额', 'total_spent', 'number', 0);
makeField($fieldModel, $repo, '最近活跃日期', 'last_activity_date', 'date', '');

echo "DONE\n";
