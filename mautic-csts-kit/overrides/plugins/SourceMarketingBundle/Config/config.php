<?php

declare(strict_types=1);

return [
    'name'        => 'Source Marketing',
    'description' => 'Source-driven marketing: 7-source first/second branching, cross-channel frequency gate, time-anchor arbitration, dedup/freeze/downgrade. Exposes ingestion + frequency APIs for platform integration.',
    'version'     => '1.0.0',
    'author'      => 'CSTS',
    'routes'      => [
        // Public, unauthenticated webhook endpoints (no /s prefix, public firewall).
        // All write endpoints require ?token= or X-SM-Token header.
        'public' => [
            'sm_ingest' => [
                'path'       => '/sourcemarketing/event',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::ingestEventAction',
                'methods'    => ['GET', 'POST'],
            ],
            'sm_frequency_check' => [
                'path'       => '/sourcemarketing/frequency/check',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::frequencyCheckAction',
                'methods'    => ['GET', 'POST'],
            ],
            'sm_channel_log' => [
                'path'       => '/sourcemarketing/channel-log',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::channelLogAction',
                'methods'    => ['GET', 'POST'],
            ],
            'sm_arbitrate' => [
                'path'       => '/sourcemarketing/arbitrate',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::arbitrateAction',
                'methods'    => ['GET', 'POST'],
            ],
            'sm_guard' => [
                'path'       => '/sourcemarketing/guard',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::guardAction',
                'methods'    => ['GET', 'POST'],
            ],
        ],
        'main' => [],
        'api'  => [],
    ],
    'menu'     => [],
    'services' => [],
];
