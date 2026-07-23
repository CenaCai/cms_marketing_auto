<?php

declare(strict_types=1);

namespace MauticPlugin\TravelPointsBundle\Controller;

use Mautic\CoreBundle\Factory\ModelFactory;
use Mautic\CoreBundle\Helper\CoreParametersHelper;
use Mautic\LeadBundle\Entity\Lead;
use Mautic\LeadBundle\Model\LeadModel;
use Mautic\PointBundle\Model\PointModel;
use Psr\Log\LoggerInterface;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * Public, unauthenticated endpoint that lets an external app (website / mobile backend)
 * attribute travel behaviours to a Mautic contact and award the configured points.
 *
 *   POST/GET /travelpoints/fire
 *     ?event=travel.search
 *     &email=user@example.com      (or &contact_id=123)
 *     &token=SHARED_SECRET
 */
class PublicController
{
    /**
     * Must match the point-action types seeded by TravelPointsBundle's PointSubscriber.
     * Anything else is rejected to prevent arbitrary point injection.
     */
    private const ALLOWED_EVENTS = [
        'travel.message_open',
        'travel.view_guide',
        'travel.search',
        'travel.view_price',
        'travel.add_to_cart',
        'travel.payment_success',
        'travel.share_review',
        'travel.inactive_14d',
        'travel.inactive_30d',
        'travel.cancel_order',
    ];

    // Fallback token used only when travelpoints_token is not configured in local.php.
    // Set a real secret in app/config/local.php as soon as possible.
    private const DEFAULT_TOKEN = 'travelpoints-dev-secret';

    public function __construct(
        private ModelFactory $modelFactory,
        private CoreParametersHelper $coreParametersHelper,
        private LoggerInterface $logger,
    ) {
    }

    public function fireAction(Request $request): JsonResponse
    {
        // 1) Auth — shared secret via ?token= or X-Travel-Token header.
        $token    = $request->query->get('token') ?? $request->headers->get('X-Travel-Token');
        $expected = (string) $this->coreParametersHelper->get('travelpoints_token', self::DEFAULT_TOKEN);

        if (null === $token || !hash_equals($expected, (string) $token)) {
            return new JsonResponse(['ok' => false, 'error' => 'invalid_token'], 403);
        }
        $usingDefaultToken = ($expected === self::DEFAULT_TOKEN);

        // 2) Event type — must be a registered travel.* behaviour.
        $event = (string) $request->query->get('event', '');
        if (!in_array($event, self::ALLOWED_EVENTS, true)) {
            return new JsonResponse(
                ['ok' => false, 'error' => 'unknown_event', 'allowed' => self::ALLOWED_EVENTS],
                400
            );
        }

        // 3) Identity — resolve the Mautic contact by contact_id or email.
        $contactId = $request->query->get('contact_id');
        $email     = trim((string) $request->query->get('email', ''));

        /** @var LeadModel $leadModel */
        $leadModel = $this->modelFactory->getModel('lead');
        $lead      = null;

        if ($contactId) {
            $lead = $leadModel->getEntity((int) $contactId);
        } elseif ('' !== $email) {
            $found = $leadModel->getRepository()->getLeadByEmail($email);
            if (!empty($found)) {
                $lead = $leadModel->getEntity((int) $found[0]['id']);
            }
        }

        // Create the contact on the fly when only an email was supplied.
        if ((!$lead || !$lead->getId()) && '' !== $email) {
            $lead = new Lead();
            $lead->setEmail($email);
            $leadModel->saveEntity($lead);
        }

        if (!$lead || !$lead->getId()) {
            return new JsonResponse(['ok' => false, 'error' => 'identity_required'], 400);
        }

        // 4) Fire the configured point action for this contact.
        /** @var PointModel $pointModel */
        $pointModel = $this->modelFactory->getModel('point');

        try {
            // $allowUserRequest = true: the caller is an anonymous public request,
            // but we explicitly allow the trigger regardless of Mautic session state.
            $pointModel->triggerAction($event, null, null, $lead, true);
        } catch (\Throwable $e) {
            $this->logger->error(
                sprintf('travelpoints fire failed: %s', $e->getMessage()),
                ['event' => $event, 'lead_id' => $lead->getId()]
            );

            return new JsonResponse(
                ['ok' => false, 'error' => 'trigger_failed', 'message' => $e->getMessage()],
                500
            );
        }

        // 5) Track order stats + last activity for S4/S5/S6 stage automation.
        $amount = (float) $request->query->get('amount', 0);
        $today  = (new \DateTime())->format('Y-m-d');

        // Every travel behaviour counts as "active" -> refresh last_activity_date
        // so the dormant (S6) segment can detect 90+ day silence reliably.
        $lead->addUpdatedField('last_activity_date', $today);

        if ('travel.payment_success' === $event) {
            $curOrders = (int) ($lead->getFieldValue('order_count') ?? 0);
            $lead->addUpdatedField('order_count', $curOrders + 1);

            $curSpent = (float) ($lead->getFieldValue('total_spent') ?? 0);
            $lead->addUpdatedField('total_spent', $curSpent + $amount);

            $lead->addUpdatedField('last_order_date', $today);
        }

        $leadModel->saveEntity($lead);

        return new JsonResponse([
            'ok'                  => true,
            'event'               => $event,
            'lead_id'             => $lead->getId(),
            'points'              => $lead->getPoints(),
            'order_count'         => $lead->getFieldValue('order_count'),
            'total_spent'         => $lead->getFieldValue('total_spent'),
            'using_default_token' => $usingDefaultToken,
        ]);
    }
}
