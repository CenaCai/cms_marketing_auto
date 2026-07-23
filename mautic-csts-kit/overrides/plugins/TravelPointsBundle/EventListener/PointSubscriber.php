<?php

declare(strict_types=1);

namespace MauticPlugin\TravelPointsBundle\EventListener;

use Mautic\PointBundle\Event\PointBuilderEvent;
use Mautic\PointBundle\PointEvents;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

/**
 * Registers the custom point-action event types required by the travel/marketing
 * scoring model. Each type is fired by the website (via PointModel::triggerAction)
 * when a contact performs the corresponding behaviour.
 */
class PointSubscriber implements EventSubscriberInterface
{
    /**
     * @var array<string,string>  event type => translation key
     */
    private const TYPES = [
        'travel.message_open'    => 'mautic.travelpoints.type.message_open',
        'travel.view_guide'       => 'mautic.travelpoints.type.view_guide',
        'travel.search'           => 'mautic.travelpoints.type.search',
        'travel.view_price'       => 'mautic.travelpoints.type.view_price',
        'travel.add_to_cart'      => 'mautic.travelpoints.type.add_to_cart',
        'travel.payment_success'  => 'mautic.travelpoints.type.payment_success',
        'travel.share_review'     => 'mautic.travelpoints.type.share_review',
        'travel.inactive_14d'     => 'mautic.travelpoints.type.inactive_14d',
        'travel.inactive_30d'     => 'mautic.travelpoints.type.inactive_30d',
        'travel.cancel_order'     => 'mautic.travelpoints.type.cancel_order',
    ];

    public static function getSubscribedEvents(): array
    {
        return [
            PointEvents::POINT_ON_BUILD => ['onPointBuild', 0],
        ];
    }

    public function onPointBuild(PointBuilderEvent $event): void
    {
        foreach (self::TYPES as $key => $label) {
            $event->addAction($key, [
                'group' => 'mautic.travelpoints.group',
                'label' => $label,
            ]);
        }
    }
}
