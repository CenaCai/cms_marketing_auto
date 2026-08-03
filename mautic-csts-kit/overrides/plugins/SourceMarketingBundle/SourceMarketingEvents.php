<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle;

/**
 * Custom event constants for the SourceMarketingBundle campaign nodes.
 * These are dispatched by Mautic's campaign executioner and handled in
 * EventListener/CampaignSubscriber.php.
 */
final class SourceMarketingEvents
{
    /**
     * Dispatched when a campaign decision node "sourcemarketing.frequency_gate"
     * is evaluated. Handler returns a boolean result (pass/fail the gate).
     */
    public const ON_CAMPAIGN_TRIGGER_DECISION = 'mautic.sourcemarketing.on_campaign_trigger_decision';

    /**
     * Dispatched for the synchronous campaign actions:
     *  - sourcemarketing.log_channel  (record a channel send for the frequency gate)
     *  - sourcemarketing.arbitrate    (time-anchor arbitration / most-recent-wins)
     *  - sourcemarketing.guard       (dedup / freeze / downgrade)
     */
    public const ON_CAMPAIGN_TRIGGER_ACTION = 'mautic.sourcemarketing.on_campaign_trigger_action';
}
