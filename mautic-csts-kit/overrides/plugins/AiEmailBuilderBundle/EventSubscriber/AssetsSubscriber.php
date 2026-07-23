<?php

declare(strict_types=1);

namespace MauticPlugin\AiEmailBuilderBundle\EventSubscriber;

use Mautic\CoreBundle\CoreEvents;
use Mautic\CoreBundle\Event\CustomAssetsEvent;
use Mautic\InstallBundle\Install\InstallService;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\HttpFoundation\RequestStack;

class AssetsSubscriber implements EventSubscriberInterface
{
    public function __construct(
        private InstallService $installer,
        private RequestStack $requestStack,
    ) {
    }

    public static function getSubscribedEvents(): array
    {
        return [
            CoreEvents::VIEW_INJECT_CUSTOM_ASSETS => ['injectAssets', 0],
        ];
    }

    public function injectAssets(CustomAssetsEvent $assetsEvent): void
    {
        if (!$this->installer->checkIfInstalled() || !$this->isMauticAdministrationPage()) {
            return;
        }

        $assetsEvent->addScript('plugins/AiEmailBuilderBundle/Assets/js/ai-email-builder.js');
    }

    private function isMauticAdministrationPage(): bool
    {
        return preg_match('/^\/s\//', $this->requestStack->getCurrentRequest()->getPathInfo()) >= 1;
    }
}
