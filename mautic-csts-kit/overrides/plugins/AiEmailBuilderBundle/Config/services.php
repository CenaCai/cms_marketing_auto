<?php

declare(strict_types=1);

use Mautic\CoreBundle\DependencyInjection\MauticCoreExtension;
use MauticPlugin\AiEmailBuilderBundle\EventSubscriber\AssetsSubscriber;
use Symfony\Component\DependencyInjection\Loader\Configurator\ContainerConfigurator;

return static function (ContainerConfigurator $configurator): void {
    $services = $configurator->services();

    $services->defaults()
        ->autowire()
        ->autoconfigure()
        ->public();

    // Auto-register controllers, event subscribers and helpers in this bundle.
    $services->load('MauticPlugin\\AiEmailBuilderBundle\\', '../')
        ->exclude('../{'.implode(',', array_merge(MauticCoreExtension::DEFAULT_EXCLUDES, ['node_modules', 'vendor'])).'}');

    // Injects the AI assistant UI script on Mautic admin pages.
    $services->set(AssetsSubscriber::class)
        ->tag('kernel.event_subscriber');
};
