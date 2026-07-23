<?php

declare(strict_types=1);

return [
    'name'        => 'AI Email Builder',
    'description' => 'Generate email MJML/HTML from natural-language intent using Gemini.',
    'version'     => '1.0.0',
    'author'      => 'Mautic Community',
    'routes'      => [
        'main'   => [
            'ai_email_builder_generate' => [
                'path'       => '/ai-email-builder/generate',
                'controller' => 'MauticPlugin\AiEmailBuilderBundle\Controller\AiEmailBuilderController::generateAction',
                'methods'    => ['POST'],
            ],
            'ai_email_builder_config'   => [
                'path'       => '/ai-email-builder/config',
                'controller' => 'MauticPlugin\AiEmailBuilderBundle\Controller\AiEmailBuilderController::configAction',
                'methods'    => ['GET'],
            ],
        ],
        'public' => [],
        'api'    => [],
    ],
    'menu'        => [],
    'services'    => [],
    'parameters'  => [
        'gemini_api_key'  => '',
        'gemini_model'    => 'gemini-1.5-flash',
        'gemini_endpoint' => 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        'gemini_proxy'    => '',
    ],
];
