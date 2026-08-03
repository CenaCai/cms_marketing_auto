<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\Service;

use Doctrine\DBAL\Connection;
use Mautic\LeadBundle\Entity\Lead;
use Mautic\LeadBundle\Model\LeadModel;

/**
 * Contact guard rails (PRD §去重 / 冻结 / 降级 / 黑名单).
 *
 *  - dedup:    same (contact, source, event) within a short window is ignored.
 *  - freeze:   complaint / hard-unsub -> comm_freeze_until set, `comm_frozen` tag added.
 *  - topic:    "not interested" -> topic freeze 60 days.
 *  - downgrade:intensity escalates down high -> normal -> low -> sleep when frequency
 *              repeatedly hits or responses dry up.
 *  - blacklist:3 consecutive delivery failures -> `channel_blacklist` tag.
 *
 * Wired as the campaign action `sourcemarketing.guard` and exposed via
 * POST /sourcemarketing/guard for external orchestration.
 */
class ContactGuardService
{
    private const TABLE_EVENT_LOG = 'sourcemarketing_event_log';

    public function __construct(private LeadModel $leadModel, private Connection $conn)
    {
    }

    private function conn(): Connection
    {
        return $this->conn;
    }

    /**
     * Record an ingested event and report whether it is a duplicate within $windowHours.
     *
     * @return array{duplicate:bool,event_id:int|null}
     */
    public function logEvent(int $leadId, string $source, string $eventType, int $windowHours = 24): array
    {
        $dup = $this->isDuplicate($leadId, $source, $eventType, $windowHours);
        if ($dup) {
            return ['duplicate' => true, 'event_id' => null];
        }
        try {
            $this->conn()->executeStatement(
                'INSERT INTO '.self::TABLE_EVENT_LOG.' (lead_id, source, event_type, created_at) VALUES (?, ?, ?, ?)',
                [$leadId, $source, $eventType, (new \DateTime())->format('Y-m-d H:i:s')]
            );
            $id = (int) $this->conn()->lastInsertId();
        } catch (\Throwable $e) {
            $id = null;
        }

        return ['duplicate' => false, 'event_id' => $id];
    }

    public function isDuplicate(int $leadId, string $source, string $eventType, int $windowHours = 24): bool
    {
        try {
            $rows = $this->conn()->executeQuery(
                'SELECT COUNT(*) AS c FROM '.self::TABLE_EVENT_LOG
                .' WHERE lead_id=? AND source=? AND event_type=? AND created_at >= ?',
                [$leadId, $source, $eventType, (new \DateTime('-'.$windowHours.' hours'))->format('Y-m-d H:i:s')]
            )->fetchAllAssociative();

            return $rows ? (int) ($rows[0]['c'] ?? array_values($rows[0])[0]) > 0 : false;
        } catch (\Throwable $e) {
            return false;
        }
    }

    public function freeze(Lead $lead, int $days, string $reason = ''): void
    {
        $until = (new \DateTime('+'.$days.' days'))->format('Y-m-d');
        $lead->addUpdatedField('comm_freeze_until', $until);
        $this->leadModel->modifyTags($lead, ['comm_frozen'], []);
        $lead->addUpdatedField('comm_freeze_reason', $reason);
        $this->leadModel->saveEntity($lead);
    }

    /**
     * Freeze ONE topic for N days. Each topic carries its own expiry so freezing
     * `spots` never mutes `ctl`. Stored as `topic:YYYY-MM-DD, topic:YYYY-MM-DD`.
     */
    public function markTopicFreeze(Lead $lead, string $topic, int $days = 60): void
    {
        $topic = trim($topic);
        if ('' === $topic) {
            return;
        }

        $until = (new \DateTime('+'.$days.' days'))->format('Y-m-d');

        $map          = FrequencyGateService::parseFrozenTopics((string) $lead->getFieldValue('topic_frozen_list'));
        $map[$topic]  = $until;

        // Drop entries whose freeze already expired, keeps the field from growing forever.
        $todayStart = (new \DateTime())->setTime(0, 0)->getTimestamp();
        $pairs      = [];
        $latest     = $until;
        foreach ($map as $name => $exp) {
            if ('' !== $exp) {
                try {
                    if ((new \DateTime($exp))->getTimestamp() < $todayStart) {
                        continue;
                    }
                    if ($exp > $latest) {
                        $latest = $exp;
                    }
                } catch (\Exception $e) {
                    // keep malformed entries rather than silently unfreezing
                }
            }
            $pairs[] = '' !== $exp ? $name.':'.$exp : $name;
        }

        $lead->addUpdatedField('topic_frozen_list', implode(', ', $pairs));
        $lead->addUpdatedField('topic_freeze_until', $latest);
        $this->leadModel->saveEntity($lead);
    }

    /**
     * Intensity downgrade ladder: high -> normal -> low -> sleep.
     */
    public function downgradeIntensity(Lead $lead): string
    {
        $ladder = ['high' => 'normal', 'normal' => 'low', 'low' => 'sleep'];
        $cur    = (string) $lead->getFieldValue('intensity_level');
        if ('' === $cur) {
            $cur = 'high';
        }
        $next = $ladder[$cur] ?? 'sleep';
        $lead->addUpdatedField('intensity_level', $next);
        $this->leadModel->saveEntity($lead);

        return $next;
    }

    public function blacklistChannel(Lead $lead, string $channel): void
    {
        $this->leadModel->modifyTags($lead, ['channel_blacklist_'.$channel], []);
        $this->leadModel->saveEntity($lead);
    }

    /**
     * Generic entry point used by the campaign action `sourcemarketing.guard`.
     *
     * @param array{action?:string,source?:string,event?:string,window_hours?:int,days?:int,topic?:string,channel?:string} $config
     */
    public function enforce(Lead $lead, array $config): array
    {
        $action = $config['action'] ?? '';
        switch ($action) {
            case 'dedup':
                $dup = $this->logEvent(
                    (int) $lead->getId(),
                    (string) ($config['source'] ?? ''),
                    (string) ($config['event'] ?? 'touch'),
                    (int) ($config['window_hours'] ?? 24)
                );

                return ['action' => 'dedup', 'duplicate' => $dup['duplicate']];

            case 'freeze':
                $this->freeze($lead, (int) ($config['days'] ?? 365), (string) ($config['reason'] ?? ''));

                return ['action' => 'freeze'];

            case 'topic_freeze':
                $this->markTopicFreeze($lead, (string) ($config['topic'] ?? ''), (int) ($config['days'] ?? 60));

                return ['action' => 'topic_freeze'];

            case 'downgrade':
                return ['action' => 'downgrade', 'intensity' => $this->downgradeIntensity($lead)];

            case 'blacklist':
                $this->blacklistChannel($lead, (string) ($config['channel'] ?? 'email'));

                return ['action' => 'blacklist'];

            default:
                return ['action' => 'none'];
        }
    }
}
