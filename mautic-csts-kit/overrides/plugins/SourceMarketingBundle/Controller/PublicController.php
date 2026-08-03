<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\Controller;

use Mautic\CoreBundle\Factory\ModelFactory;
use Mautic\CoreBundle\Helper\CoreParametersHelper;
use Mautic\LeadBundle\Entity\Lead;
use Mautic\LeadBundle\Model\LeadModel;
use MauticPlugin\SourceMarketingBundle\Service\ArbitrationService;
use MauticPlugin\SourceMarketingBundle\Service\ContactGuardService;
use MauticPlugin\SourceMarketingBundle\Service\FrequencyGateService;
use Psr\Log\LoggerInterface;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * Public, unauthenticated webhook endpoints so the 7 business platforms can push
 * events into Mautic and query the frequency gate. Every write endpoint requires a
 * shared token (?token=… or X-SM-Token header). Set the real secret in
 * config/local.php as `sourcemarketing_token`.
 *
 *   POST /sourcemarketing/event        ?token=&source=&event=&email=|contact_id=…   ingest
 *   GET  /sourcemarketing/frequency/check?token=&email=&channel=                       query gate
 *   POST /sourcemarketing/channel-log  ?token=&email=&channel=&asset_id=              log external send
 *   POST /sourcemarketing/arbitrate    ?token=&email=&source=&anchor_time=            manual arbitration
 *   POST /sourcemarketing/guard        ?token=&email=&action=freeze|topic_freeze|downgrade|blacklist
 */
class PublicController
{
    private const ALLOWED_SOURCES = [
        'ctl', 'csts', 'crawler', 'adform', 'webform', 'tplus', 'spots',
    ];

    private const DEFAULT_TOKEN = 'sourcemarketing-dev-secret';

    /** @var array<string,mixed>|null Decoded JSON body cache, keyed per request. */
    private ?array $jsonCache = null;

    private ?string $jsonCacheKey = null;

    public function __construct(
        private ModelFactory $modelFactory,
        private CoreParametersHelper $coreParametersHelper,
        private LoggerInterface $logger,
        private FrequencyGateService $frequencyGate,
        private ArbitrationService $arbitration,
        private ContactGuardService $guard,
    ) {
    }

    /**
     * Decode a JSON request body once per request. Mautic core does NOT populate
     * $request->request for `Content-Type: application/json`, so we do it ourselves
     * instead of relying on implicit behaviour.
     *
     * @return array<string,mixed>
     */
    private function json(Request $request): array
    {
        $key = spl_object_hash($request);
        if ($this->jsonCacheKey === $key && null !== $this->jsonCache) {
            return $this->jsonCache;
        }

        $decoded = [];
        $content = (string) $request->getContent();
        if ('' !== $content && str_contains((string) $request->headers->get('Content-Type'), 'json')) {
            $parsed = json_decode($content, true);
            if (is_array($parsed)) {
                $decoded = $parsed;
            }
        }

        $this->jsonCacheKey = $key;
        $this->jsonCache    = $decoded;

        return $decoded;
    }

    /**
     * Read a parameter from query string, form body, or JSON body (in that order).
     */
    private function param(Request $request, string $key, mixed $default = null): mixed
    {
        $val = $request->query->get($key) ?? $request->request->get($key);
        if (null !== $val) {
            return $val;
        }

        return $this->json($request)[$key] ?? $default;
    }

    /**
     * @return array<string,mixed> every inbound parameter, JSON body included
     */
    private function allParams(Request $request): array
    {
        return array_merge($this->json($request), $request->query->all(), $request->request->all());
    }

    private function auth(Request $request): ?string
    {
        $token    = $this->param($request, 'token') ?? $request->headers->get('X-SM-Token');
        $expected = (string) $this->coreParametersHelper->get('sourcemarketing_token', self::DEFAULT_TOKEN);

        return (null !== $token && hash_equals($expected, (string) $token)) ? $expected : null;
    }

    private function resolveContact(Request $request): ?Lead
    {
        $contactId = $this->param($request, 'contact_id');
        $email     = trim((string) ($this->param($request, 'email') ?? ''));

        /** @var LeadModel $leadModel */
        $leadModel = $this->modelFactory->getModel('lead');

        if ($contactId) {
            $lead = $leadModel->getEntity((int) $contactId);
            if ($lead && $lead->getId()) {
                return $lead;
            }
        }

        if ('' !== $email) {
            // NOTE: getLeadByEmail($email) with $all=false returns a SINGLE assoc row
            // (['id' => 42]), not a list. Handle both shapes defensively.
            $found  = $leadModel->getRepository()->getLeadByEmail($email);
            $foundId = 0;
            if (is_array($found) && !empty($found)) {
                if (isset($found['id'])) {
                    $foundId = (int) $found['id'];
                } elseif (isset($found[0]['id'])) {
                    $foundId = (int) $found[0]['id'];
                }
            }

            if ($foundId > 0) {
                $lead = $leadModel->getEntity($foundId);
                if ($lead && $lead->getId()) {
                    return $lead;
                }
            }

            // Create on the fly (One-ID keyed by email, per PRD).
            $lead = new Lead();
            $lead->setEmail($email);
            $leadModel->saveEntity($lead);

            return $lead;
        }

        return null;
    }

    public function ingestEventAction(Request $request): JsonResponse
    {
        if (null === $this->auth($request)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }

        $source = strtolower((string) ($this->param($request, 'source') ?? ''));
        if (!in_array($source, self::ALLOWED_SOURCES, true)) {
            return new JsonResponse(
                ['ok' => false, 'error' => 'unknown_source', 'allowed' => self::ALLOWED_SOURCES],
                400
            );
        }

        $eventType = (string) $this->param($request, 'event', 'touch');
        $lead      = $this->resolveContact($request);
        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        $leadId = (int) $lead->getId();

        // Dedup at the ingest boundary. An external event_id makes it idempotent.
        $eventId = $this->param($request, 'event_id');
        $dupKey  = $eventId ? $eventType.'#'.$eventId : $eventType;
        $dup     = $this->guard->logEvent($leadId, $source, $dupKey);
        if ($dup['duplicate']) {
            return new JsonResponse(['ok' => true, 'duplicate' => true, 'lead_id' => $leadId, 'source' => $source]);
        }

        // Source attribution + first-source capture.
        if ('' === (string) $lead->getFieldValue('source_primary')) {
            $lead->addUpdatedField('source_primary', $source);
        }
        $lead->addUpdatedField('last_source_event', $eventType);

        // Source-specific attributes (PRD field mapping).
        foreach ([
            'order_status'   => 'order_status',
            'departure_date' => 'departure_date',
            'behavior_type'  => 'behavior_type',
            'form_type'      => 'form_type',
            'consult_type'   => 'consult_type',
            'source_detail'  => 'source_detail',
        ] as $param => $alias) {
            $val = $this->param($request, $param);
            if (null !== $val && '' !== (string) $val) {
                $lead->addUpdatedField($alias, (string) $val);
            }
        }

        /** @var LeadModel $leadModel */
        $leadModel = $this->modelFactory->getModel('lead');
        $leadModel->modifyTags($lead, ['src_'.$source], []);
        $leadModel->saveEntity($lead);

        // Time-anchor arbitration.
        $anchorParam = $this->param($request, 'anchor_time');
        try {
            $anchor = $anchorParam ? new \DateTime((string) $anchorParam) : new \DateTime();
        } catch (\Exception $e) {
            return new JsonResponse(['ok' => false, 'error' => 'bad_anchor_time', 'value' => $anchorParam], 400);
        }
        $arb = $this->arbitration->award($lead, $source, $anchor);

        return new JsonResponse([
            'ok'            => true,
            'lead_id'       => $leadId,
            'source'        => $source,
            'event'         => $eventType,
            'arbitration'   => $arb,
            'using_default_token' => ($this->coreParametersHelper->get('sourcemarketing_token', self::DEFAULT_TOKEN) === self::DEFAULT_TOKEN),
        ]);
    }

    public function frequencyCheckAction(Request $request): JsonResponse
    {
        if (null === $this->auth($request)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }

        $lead = $this->resolveContact($request);
        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        $channel = (string) $this->param($request, 'channel', 'email');
        $exempt  = filter_var($this->param($request, 'exempt', false), FILTER_VALIDATE_BOOLEAN);
        $topic   = $this->param($request, 'topic');
        $assetId = $this->param($request, 'asset_id');

        $res = $this->frequencyGate->isAllowed(
            $lead,
            $channel,
            $exempt,
            $topic ? (string) $topic : null,
            $assetId ? (int) $assetId : null
        );

        return new JsonResponse(array_merge(['ok' => true], $res));
    }

    public function channelLogAction(Request $request): JsonResponse
    {
        if (null === $this->auth($request)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }

        $lead = $this->resolveContact($request);
        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        $channel = (string) $this->param($request, 'channel', 'email');
        $assetId = $this->param($request, 'asset_id');

        $this->frequencyGate->logChannel((int) $lead->getId(), $channel, $assetId ? (int) $assetId : null);

        return new JsonResponse(['ok' => true, 'lead_id' => $lead->getId(), 'channel' => $channel]);
    }

    public function arbitrateAction(Request $request): JsonResponse
    {
        if (null === $this->auth($request)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }

        $source = strtolower((string) ($this->param($request, 'source') ?? ''));
        if (!in_array($source, self::ALLOWED_SOURCES, true)) {
            return new JsonResponse(['ok' => false, 'error' => 'unknown_source'], 400);
        }

        $lead = $this->resolveContact($request);
        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        $anchorParam = $this->param($request, 'anchor_time');
        try {
            $anchor = $anchorParam ? new \DateTime((string) $anchorParam) : new \DateTime();
        } catch (\Exception $e) {
            return new JsonResponse(['ok' => false, 'error' => 'bad_anchor_time', 'value' => $anchorParam], 400);
        }
        $arb = $this->arbitration->award($lead, $source, $anchor);

        return new JsonResponse(['ok' => true, 'arbitration' => $arb]);
    }

    public function guardAction(Request $request): JsonResponse
    {
        if (null === $this->auth($request)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }

        $lead = $this->resolveContact($request);
        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        $config = $this->allParams($request);
        $result = $this->guard->enforce($lead, $config);

        return new JsonResponse(['ok' => true, 'result' => $result]);
    }
}
