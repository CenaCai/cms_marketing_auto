<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\Service;

use Mautic\LeadBundle\Entity\Lead;
use Mautic\LeadBundle\Model\LeadModel;

/**
 * Time-anchor arbitration (PRD §时间锚点仲裁).
 *
 * When a contact qualifies for multiple source journeys at once, the journey whose
 * event carries the MOST RECENT time anchor wins ("最近者获胜"). We persist the winning
 * source in `active_journey`; the frequency-gate decision in each source campaign then
 * only allows sending when `active_journey == source`, so the losing journeys stay quiet.
 */
class ArbitrationService
{
    public function __construct(private LeadModel $leadModel)
    {
    }

    /**
     * @return array{awarded:bool,active_journey:string,anchor_time:string}
     */
    public function award(Lead $lead, string $source, ?\DateTime $anchor = null): array
    {
        $anchor    = $anchor ?? new \DateTime();
        $cur       = $lead->getFieldValue('last_anchor_time');
        $curSource = (string) $lead->getFieldValue('last_anchor_source');
        $newWins   = true;

        if ($cur) {
            try {
                $curDt = new \DateTime($cur);
            } catch (\Throwable $e) {
                $curDt = null;
            }
            // Existing anchor is more recent -> it keeps winning, new event is subordinate.
            if ($curDt && $curDt > $anchor) {
                $newWins = false;
            }
        }

        if ($newWins) {
            $lead->addUpdatedField('last_anchor_time', $anchor->format('Y-m-d H:i:s'));
            $lead->addUpdatedField('last_anchor_source', $source);
            $lead->addUpdatedField('active_journey', $source);
            $this->leadModel->saveEntity($lead);
        }

        return [
            'awarded'       => $newWins,
            'active_journey' => $newWins ? $source : $curSource,
            'anchor_time'    => $anchor->format('Y-m-d H:i:s'),
        ];
    }
}
