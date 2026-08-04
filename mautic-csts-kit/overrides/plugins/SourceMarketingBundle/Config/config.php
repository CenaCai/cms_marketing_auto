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
            'sm_country_policy' => [
                'path'       => '/sourcemarketing/country-policy',
                'controller' => 'MauticPlugin\SourceMarketingBundle\Controller\PublicController::countryPolicyAction',
                'methods'    => ['GET', 'POST'],
            ],
        ],
        'main' => [],
        'api'  => [],
    ],
    'menu'     => [],
    'services' => [],

    // Plugin-owned defaults. Declaring them here (rather than only in config/local.php)
    // means saving anything in Mautic's admin UI cannot silently drop them -- the admin
    // form rewrites local.php and discards parameters it does not know about.
    // Override any of these in config/local.php; that file always wins.
    'parameters' => [
        // Shared secret for the public /sourcemarketing/* endpoints. CHANGE IN PRODUCTION.
        'sourcemarketing_token' => 'sourcemarketing-dev-secret',

        // Country -> send policy. Send time is derived from the contact's `country`
        // field (see CountryPolicyService); this block only tunes the exceptions.
        'sourcemarketing_country_policy' => [
            // ISO-3166 alpha-2 codes that must never receive marketing email.
            'blocked' => [],

            // Turn on to require explicit opt-in (email_consent field == 1, or the
            // `consent_optin` tag) before emailing GDPR/EEA contacts.
            'consent_required_enabled' => false,
            // Empty = use the built-in EEA + UK + CH list.
            'consent_required'         => [],

            // Force a specific timezone for a country, e.g. ['US' => 'America/Los_Angeles'].
            'timezone' => [],

            // Per-country quiet hours [startInclusive, endExclusive], e.g. ['JP' => [21, 9]].
            'silence' => [],
        ],
    ],
];
