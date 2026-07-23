<?php

use MauticPlugin\TravelPointsBundle\Controller\PublicController;
use MauticPlugin\TravelPointsBundle\EventListener\PointSubscriber;
use Symfony\Component\DependencyInjection\Loader\Configurator\ContainerConfigurator;

return static function (ContainerConfigurator $configurator): void {
    $services = $configurator->services();

    $services->defaults()
        ->autowire()
        ->autoconfigure()
        ->public();

    // Registers the custom travel point-action types so the Points UI / triggerAction
    // can award points for website-driven behaviours (search, add-to-cart, payment, ...).
    $services->set(PointSubscriber::class)
        ->tag('kernel.event_subscriber');

    // Public, unauthenticated endpoint that lets an external app attribute
    // travel behaviours to a Mautic contact and award the configured points.
    // autoconfigure() tags it with controller.service_arguments automatically.
    $services->set(PublicController::class);
};
