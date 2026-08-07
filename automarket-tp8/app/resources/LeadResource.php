<?php

declare(strict_types=1);

namespace app\resources;

use app\model\Lead;

/**
 * 联系人输出转换：控制对外字段，避免直接吐 70 列裸数据。
 */
final class LeadResource
{
    /** 列表视图（精简） */
    public static function brief(Lead|array $lead): array
    {
        $d = $lead instanceof Lead ? $lead->toArray() : $lead;

        return [
            'id'           => (int) $d['id'],
            'email'        => $d['email'] ?? null,
            'firstname'    => $d['firstname'] ?? null,
            'lastname'     => $d['lastname'] ?? null,
            'company'      => $d['company'] ?? null,
            'mobile'       => $d['mobile'] ?? null,
            'country'      => $d['country'] ?? null,
            'points'       => (int) ($d['points'] ?? 0),
            'stage'        => isset($d['stage']) && $d['stage']
                ? ['id' => (int) $d['stage']['id'], 'name' => $d['stage']['name']]
                : null,
            'tags'         => array_map(
                static fn (array $t): array => ['id' => (int) $t['id'], 'tag' => $t['tag']],
                $d['tags'] ?? []
            ),
            'source_primary' => $d['source_primary'] ?? null,
            'reply_intent'   => $d['reply_intent'] ?? null,
            'last_active'    => $d['last_active'] ?? null,
            'date_added'     => $d['date_added'] ?? null,
        ];
    }

    /** 详情视图（含业务扩展字段） */
    public static function detail(Lead $lead): array
    {
        $d    = $lead->toArray();
        $base = self::brief($d);

        return $base + [
            'is_published'    => (bool) ($d['is_published'] ?? true),
            'title'           => $d['title'] ?? null,
            'position'        => $d['position'] ?? null,
            'phone'           => $d['phone'] ?? null,
            'address1'        => $d['address1'] ?? null,
            'address2'        => $d['address2'] ?? null,
            'city'            => $d['city'] ?? null,
            'state'           => $d['state'] ?? null,
            'zipcode'         => $d['zipcode'] ?? null,
            'timezone'        => $d['timezone'] ?? null,
            'preferred_locale' => $d['preferred_locale'] ?? null,
            'website'         => $d['website'] ?? null,
            'owner'           => isset($d['owner']) && $d['owner']
                ? ['id' => (int) $d['owner']['id'], 'username' => $d['owner']['username'] ?? null]
                : null,
            // 业务扩展（Mautic 自定义字段）
            'order_count'     => $d['order_count'] ?? null,
            'total_spent'     => $d['total_spent'] ?? null,
            'order_status'    => $d['order_status'] ?? null,
            'departure_date'  => $d['departure_date'] ?? null,
            'behavior_type'   => $d['behavior_type'] ?? null,
            'form_type'       => $d['form_type'] ?? null,
            'consult_type'    => $d['consult_type'] ?? null,
            'source_detail'   => $d['source_detail'] ?? null,
            'last_source_event' => $d['last_source_event'] ?? null,
            'last_anchor_time'  => $d['last_anchor_time'] ?? null,
            'active_journey'    => $d['active_journey'] ?? null,
            'comm_freeze_until' => $d['comm_freeze_until'] ?? null,
            'intensity_level'   => $d['intensity_level'] ?? null,
            'reply_summary'     => $d['reply_summary'] ?? null,
            'reply_classified_at' => $d['reply_classified_at'] ?? null,
            'last_activity_date'  => $d['last_activity_date'] ?? null,
            'date_modified'       => $d['date_modified'] ?? null,
        ];
    }
}
