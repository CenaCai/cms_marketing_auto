<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\EventListener;

use Mautic\CampaignBundle\CampaignEvents;
use Mautic\CampaignBundle\Event\CampaignBuilderEvent;
use Mautic\CampaignBundle\Event\CampaignExecutionEvent;
use Mautic\LeadBundle\Model\LeadModel;
use MauticPlugin\SourceMarketingBundle\Service\ArbitrationService;
use MauticPlugin\SourceMarketingBundle\Service\ContactGuardService;
use MauticPlugin\SourceMarketingBundle\Service\FrequencyGateService;
use MauticPlugin\SourceMarketingBundle\SourceMarketingEvents;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

/**
 * Registers the custom campaign nodes and handles their execution:
 *
 *  Decision : sourcemarketing.frequency_gate  -> pass/fail the cross-channel gate +
 *             active_journey arbitration check.
 *  Action   : sourcemarketing.log_channel     -> record a channel send (feeds the gate).
 *  Action   : sourcemarketing.arbitrate       -> time-anchor arbitration (most-recent-wins).
 *  Action   : sourcemarketing.guard           -> dedup / freeze / topic-freeze / downgrade.
 */
class CampaignSubscriber implements EventSubscriberInterface
{
    public function __construct(
        private LeadModel $leadModel,
        private FrequencyGateService $frequencyGate,
        private ArbitrationService $arbitration,
        private ContactGuardService $guard,
    ) {
    }

    public static function getSubscribedEvents(): array
    {
        return [
            CampaignEvents::CAMPAIGN_ON_BUILD => ['onCampaignBuild', 0],
            SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_DECISION => ['onFrequencyDecision', 0],
            SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_ACTION => [
                ['onLogChannel', 0],
                ['onArbitrate', 1],
                ['onGuard', 2],
            ],
        ];
    }

    public function onCampaignBuild(CampaignBuilderEvent $event): void
    {
        $event->addDecision(
            'sourcemarketing.frequency_gate',
            [
                'label'       => 'mautic.sourcemarketing.decision.frequency_gate',
                'description' => 'mautic.sourcemarketing.decision.frequency_gate_descr',
                'eventName'   => SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_DECISION,
            ]
        );

        $event->addAction(
            'sourcemarketing.log_channel',
            [
                'label'       => 'mautic.sourcemarketing.action.log_channel',
                'description' => 'mautic.sourcemarketing.action.log_channel_descr',
                'eventName'   => SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_ACTION,
            ]
        );

        $event->addAction(
            'sourcemarketing.arbitrate',
            [
                'label'       => 'mautic.sourcemarketing.action.arbitrate',
                'description' => 'mautic.sourcemarketing.action.arbitrate_descr',
                'eventName'   => SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_ACTION,
            ]
        );

        $event->addAction(
            'sourcemarketing.guard',
            [
                'label'       => 'mautic.sourcemarketing.action.guard',
                'description' => 'mautic.sourcemarketing.action.guard_descr',
                'eventName'   => SourceMarketingEvents::ON_CAMPAIGN_TRIGGER_ACTION,
            ]
        );
    }

    public function onFrequencyDecision(CampaignExecutionEvent $event): CampaignExecutionEvent
    {
        if (!$event->checkContext('sourcemarketing.frequency_gate')) {
            return $event;
        }

        $lead   = $event->getLead();
        $config = $event->getConfig();
        if (!$lead || !$lead->getId()) {
            return $event->setResult(false);
        }

        $source  = (string) ($config['source'] ?? '');
        $channel = (string) ($config['channel'] ?? ($event->getEvent()['channel'] ?? 'email'));
        $exempt  = !empty($config['exempt']);
        $topic   = !empty($config['topic']) ? (string) $config['topic'] : null;
        $assetId = isset($config['asset_id']) ? (int) $config['asset_id'] : null;

        // Time-anchor arbitration: only the winning journey may send.
        $active = (string) $lead->getFieldValue('active_journey');
        if ($source && $active && $active !== $source) {
            return $event->setResult(false);
        }

        $res = $this->frequencyGate->isAllowed($lead, $channel, $exempt, $topic, $assetId);

        return $event->setResult($res['allowed']);
    }

    public function onLogChannel(CampaignExecutionEvent $event): void
    {
        if (!$event->checkContext('sourcemarketing.log_channel')) {
            return;
        }
        $lead = $event->getLead();
        if (!$lead || !$lead->getId()) {
            return;
        }
        $channel = (string) ($event->getConfig()['channel'] ?? ($event->getEvent()['channel'] ?? 'email'));
        $assetId = $event->getConfig()['asset_id'] ?? ($event->getEvent()['channelId'] ?? null);
        $this->frequencyGate->logChannel((int) $lead->getId(), $channel, $assetId ? (int) $assetId : null);
    }

    public function onArbitrate(CampaignExecutionEvent $event): void
    {
        if (!$event->checkContext('sourcemarketing.arbitrate')) {
            return;
        }
        $lead = $event->getLead();
        if (!$lead || !$lead->getId()) {
            return;
        }
        $config  = $event->getConfig();
        $source  = (string) ($config['source'] ?? '');
        if (!$source) {
            return;
        }
        $anchor = !empty($config['anchor_time']) ? new \DateTime((string) $config['anchor_time']) : new \DateTime();
        $this->arbitration->award($lead, $source, $anchor);
    }

    public function onGuard(CampaignExecutionEvent $event): void
    {
        if (!$event->checkContext('sourcemarketing.guard')) {
            return;
        }
        $lead = $event->getLead();
        if (!$lead || !$lead->getId()) {
            return;
        }
        $this->guard->enforce($lead, $event->getConfig());
    }
}
