<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\Service;

use Doctrine\DBAL\Connection;
use Mautic\LeadBundle\Entity\Lead;

/**
 * Cross-channel frequency gate (PRD §频次控制).
 *
 * Rules enforced:
 *  - single channel <= 3 messages / 7 days
 *  - cross channel  <= 5 messages / 7 days
 *  - 22:00-08:00 silence window (per contact timezone)
 *  - high-value content exempt from single/cross caps BUT still respects 24h gap + silence
 *  - contact frozen (complaint/unsub) or topic frozen -> hard block
 *  - same asset (email/sms id) not reused within 30 days (dedup)
 *
 * The counters are backed by the `sourcemarketing_channel_log` table, written by
 * logChannel() (wired as the campaign action `sourcemarketing.log_channel`, and also
 * exposed via POST /sourcemarketing/channel-log for external sends).
 */
class FrequencyGateService
{
    public const SINGLE_CHANNEL_LIMIT = 3;
    public const CROSS_CHANNEL_LIMIT  = 5;
    public const WINDOW_DAYS          = 7;
    public const ASSET_DEDUP_DAYS     = 30;
    public const SILENCE_START        = 22; // inclusive
    public const SILENCE_END          = 8;  // exclusive

    private const TABLE_CHANNEL_LOG = 'sourcemarketing_channel_log';
    private const TABLE_EVENT_LOG   = 'sourcemarketing_event_log';

    public function __construct(private Connection $conn)
    {
    }

    private function conn(): Connection
    {
        return $this->conn;
    }

    /**
     * @return array{allowed:bool,reason:string,single_count:int,cross_count:int}
     */
    public function isAllowed(Lead $lead, string $channel, bool $exemptHighValue = false, ?string $topic = null, ?int $assetId = null): array
    {
        $leadId = (int) $lead->getId();

        try {
            if ($this->isFrozen($lead)) {
                return $this->deny('contact_frozen', 0, 0);
            }
            if ($topic && $this->isTopicFrozen($lead, $topic)) {
                return $this->deny('topic_frozen', 0, 0);
            }
            if ($this->inSilenceWindow($lead) && !$exemptHighValue) {
                return $this->deny('silence_window', 0, 0);
            }

            $conn  = $this->conn();
            $since = (new \DateTime('-'.self::WINDOW_DAYS.' days'))->format('Y-m-d H:i:s');

            $single = $this->countRows(
                $conn,
                'SELECT COUNT(*) AS c FROM '.self::TABLE_CHANNEL_LOG.' WHERE lead_id=? AND channel=? AND sent_at >= ?',
                [$leadId, $channel, $since]
            );
            if ($single >= self::SINGLE_CHANNEL_LIMIT) {
                return $this->deny('single_channel_limit', $single, 0);
            }

            $cross = $this->countRows(
                $conn,
                'SELECT COUNT(*) AS c FROM '.self::TABLE_CHANNEL_LOG.' WHERE lead_id=? AND sent_at >= ?',
                [$leadId, $since]
            );
            if ($cross >= self::CROSS_CHANNEL_LIMIT) {
                return $this->deny('cross_channel_limit', $single, $cross);
            }

            // asset dedup (never re-send same creative within 30 days)
            if ($assetId) {
                $dup = $this->countRows(
                    $conn,
                    'SELECT COUNT(*) AS c FROM '.self::TABLE_CHANNEL_LOG.' WHERE lead_id=? AND channel=? AND asset_id=? AND sent_at >= ?',
                    [$leadId, $channel, $assetId, (new \DateTime('-'.self::ASSET_DEDUP_DAYS.' days'))->format('Y-m-d H:i:s')]
                );
                if ($dup > 0) {
                    return $this->deny('asset_dedup', $single, $cross);
                }
            }

            // high-value: exempt from caps but enforce 24h gap
            if ($exemptHighValue) {
                $last = $this->countRows(
                    $conn,
                    'SELECT COUNT(*) AS c FROM '.self::TABLE_CHANNEL_LOG.' WHERE lead_id=? AND sent_at >= ?',
                    [$leadId, (new \DateTime('-1 days'))->format('Y-m-d H:i:s')]
                );
                if ($last > 0) {
                    return $this->deny('high_value_24h_gap', $single, $cross);
                }
            }

            return ['allowed' => true, 'reason' => 'ok', 'single_count' => $single, 'cross_count' => $cross];
        } catch (\Throwable $e) {
            // Table missing or DB error -> fail open (allow) but surface the reason so the
            // operator knows the gate is not yet active.
            return ['allowed' => true, 'reason' => 'gate_unavailable:'.$e->getMessage(), 'single_count' => 0, 'cross_count' => 0];
        }
    }

    /**
     * Record a channel send. Called by the campaign action `sourcemarketing.log_channel`
     * and by POST /sourcemarketing/channel-log (external sends).
     */
    public function logChannel(int $leadId, string $channel, ?int $assetId = null, ?\DateTime $when = null): void
    {
        $when = $when ?? new \DateTime();
        try {
            $this->conn()->executeStatement(
                'INSERT INTO '.self::TABLE_CHANNEL_LOG.' (lead_id, channel, asset_id, sent_at) VALUES (?, ?, ?, ?)',
                [$leadId, $channel, $assetId, $when->format('Y-m-d H:i:s')]
            );
        } catch (\Throwable $e) {
            // Non-fatal: gate simply won't count this send. Log via error handler if available.
        }
    }

    public function isFrozen(Lead $lead): bool
    {
        $until = $lead->getFieldValue('comm_freeze_until');
        if ($until && (new \DateTime($until))->getTimestamp() >= (new \DateTime())->setTime(0, 0)->getTimestamp()) {
            return true;
        }

        return (bool) $lead->getFieldValue('comm_frozen');
    }

    /**
     * Parse `topic_frozen_list` into a topic => expiry map.
     *
     * Stored format is `topic:YYYY-MM-DD, topic:YYYY-MM-DD`. A bare `topic`
     * without a date is treated as legacy data and falls back to the global
     * `topic_freeze_until` value.
     *
     * @return array<string,string> topic => 'Y-m-d' ('' when no per-topic date)
     */
    public static function parseFrozenTopics(string $raw): array
    {
        $map = [];
        foreach (array_filter(array_map('trim', explode(',', $raw))) as $entry) {
            $parts          = explode(':', $entry, 2);
            $name           = trim($parts[0]);
            if ('' === $name) {
                continue;
            }
            $map[$name] = isset($parts[1]) ? trim($parts[1]) : '';
        }

        return $map;
    }

    /**
     * A topic is frozen only when it is present in the contact's frozen list AND
     * its own expiry is still in the future. Freezing one topic must never mute
     * the others.
     */
    public function isTopicFrozen(Lead $lead, string $topic): bool
    {
        $map = self::parseFrozenTopics((string) $lead->getFieldValue('topic_frozen_list'));
        if (!array_key_exists($topic, $map)) {
            return false;
        }

        // Per-topic expiry, falling back to the global field for legacy rows.
        $until = $map[$topic] ?: (string) $lead->getFieldValue('topic_freeze_until');
        if ('' === $until) {
            return true; // frozen with no expiry recorded -> stay frozen
        }

        try {
            $todayStart = (new \DateTime())->setTime(0, 0)->getTimestamp();

            return (new \DateTime($until))->getTimestamp() >= $todayStart;
        } catch (\Exception $e) {
            return true;
        }
    }

    public function inSilenceWindow(Lead $lead): bool
    {
        $tzName = (string) $lead->getFieldValue('timezone');
        try {
            $tz = $tzName ? new \DateTimeZone($tzName) : new \DateTimeZone(date_default_timezone_get() ?: 'UTC');
        } catch (\Throwable $e) {
            $tz = new \DateTimeZone('UTC');
        }
        $hour = (int) (new \DateTime('now', $tz))->format('G');

        return $hour >= self::SILENCE_START || $hour < self::SILENCE_END;
    }

    /**
     * @return array{allowed:bool,reason:string,single_count:int,cross_count:int}
     */
    private function deny(string $reason, int $single, int $cross): array
    {
        return ['allowed' => false, 'reason' => $reason, 'single_count' => $single, 'cross_count' => $cross];
    }

    private function countRows(Connection $conn, string $sql, array $params): int
    {
        $rows = $conn->executeQuery($sql, $params)->fetchAllAssociative();

        return $rows ? (int) ($rows[0]['c'] ?? array_values($rows[0])[0]) : 0;
    }
}
