<?php

use Doctrine\DBAL\Connection;
use MauticPlugin\SourceMarketingBundle\Controller\PublicController;
use MauticPlugin\SourceMarketingBundle\EventListener\CampaignSubscriber;
use MauticPlugin\SourceMarketingBundle\Service\ArbitrationService;
use MauticPlugin\SourceMarketingBundle\Service\ContactGuardService;
use MauticPlugin\SourceMarketingBundle\Service\FrequencyGateService;
use Symfony\Component\DependencyInjection\Loader\Configurator\ContainerConfigurator;
use function Symfony\Component\DependencyInjection\Loader\Configurator\service;

return static function (ContainerConfigurator $configurator): void {
    $services = $configurator->services();

    $services->defaults()
        ->autowire()
        ->autoconfigure()
        ->public()
        // Bind Doctrine DBAL Connection to the doctrine service id so the gate/guard
        // services can be autowired with a real connection.
        ->bind(Connection::class, service('database_connection'));

    $services->set(PublicController::class);
    $services->set(FrequencyGateService::class);
    $services->set(ArbitrationService::class);
    $services->set(ContactGuardService::class);

    // Registers the custom campaign decision + action nodes and their handlers.
    $services->set(CampaignSubscriber::class)
        ->tag('kernel.event_subscriber');
};
