<?php

declare(strict_types=1);

return [
    'name'        => 'Travel Points',
    'description' => 'Custom travel point/behaviour tracking (search, add-to-cart, payment, ...)',
    'version'     => '1.0.0',
    'author'      => 'CSTS',
    'routes'      => [
        // Public, unauthenticated routes (no /s prefix, public firewall).
        'public' => [
            'travelpoints_fire' => [
                'path'       => '/travelpoints/fire',
                'controller' => 'MauticPlugin\TravelPointsBundle\Controller\PublicController::fireAction',
                'methods'    => ['GET', 'POST'],
            ],
        ],
        'main'   => [],
        'api'    => [],
    ],
    'menu'     => [],
    'services' => [],
];
