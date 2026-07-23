<?php

declare(strict_types=1);

namespace MauticPlugin\AiEmailBuilderBundle\Controller;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use Mautic\CoreBundle\Controller\CommonController;
use Mautic\CoreBundle\Helper\CoreParametersHelper;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

class AiEmailBuilderController extends CommonController
{
    private const DEFAULT_SYSTEM_PROMPT_MJML = <<<'PROMPT'
You are an expert email template developer. The user will describe an email in natural language.
Generate a complete, valid MJML email template that matches the intent.
Use only standard MJML tags such as <mjml>, <mj-head>, <mj-body>, <mj-section>, <mj-column>, <mj-text>, <mj-button>, <mj-image>, <mj-divider>, <mj-spacer>, <mj-attributes>, <mj-style>.
Keep styles inline-friendly and email-client compatible.
Do not output markdown, explanations, or code fences. Output ONLY the raw MJML XML.
PROMPT;

    private const DEFAULT_SYSTEM_PROMPT_HTML = <<<'PROMPT'
You are an expert email template developer. The user will describe an email in natural language.
Generate a complete, email-client compatible HTML fragment (tables-based layout, inline styles).
Do not output markdown, explanations, or code fences. Output ONLY the raw HTML.
PROMPT;

    public function generateAction(
        Request $request,
        CoreParametersHelper $coreParametersHelper,
        Client $httpClient,
    ): JsonResponse {
        $prompt = trim((string) $request->request->get('prompt'));
        $mode   = in_array($request->request->get('mode'), ['mjml', 'html'], true)
            ? $request->request->get('mode')
            : 'mjml';

        if ('' === $prompt) {
            return new JsonResponse(['error' => 'Prompt is required.'], 400);
        }

        $apiKey = trim((string) $coreParametersHelper->get('gemini_api_key'));
        if ('' === $apiKey) {
            return new JsonResponse(['error' => 'Gemini API key is not configured.'], 500);
        }

        // Optional outbound proxy (useful behind GFW / corporate networks).
        // e.g. gemini_proxy => 'http://127.0.0.1:7890' (Clash / V2Ray local HTTP proxy).
        $proxy  = trim((string) $coreParametersHelper->get('gemini_proxy', ''));
        $client = '' !== $proxy
            ? new Client(['proxy' => $proxy, 'timeout' => 60, 'connect_timeout' => 15])
            : $httpClient;

        $model    = (string) $coreParametersHelper->get('gemini_model', 'gemini-1.5-flash');
        $endpoint = (string) $coreParametersHelper->get(
            'gemini_endpoint',
            'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        );
        $endpoint = str_replace('{model}', $model, $endpoint);
        $endpoint .= (str_contains($endpoint, '?') ? '&' : '?').'key='.urlencode($apiKey);

        $systemPrompt = 'mjml' === $mode ? self::DEFAULT_SYSTEM_PROMPT_MJML : self::DEFAULT_SYSTEM_PROMPT_HTML;

        $payload = [
            'systemInstruction' => [
                'parts' => [['text' => $systemPrompt]],
            ],
            'contents' => [
                [
                    'role'  => 'user',
                    'parts' => [['text' => $prompt]],
                ],
            ],
            'generationConfig' => [
                'temperature' => 0.2,
            ],
        ];

        try {
            $response = $client->post($endpoint, [
                'headers' => ['Content-Type' => 'application/json'],
                'body'    => json_encode($payload, JSON_THROW_ON_ERROR),
                'timeout' => 60,
            ]);
            $status = $response->getStatusCode();
            $body   = (string) $response->getBody();

            if ($status < 200 || $status >= 300) {
                return new JsonResponse(['error' => 'Gemini API returned HTTP '.$status, 'details' => $body], 502);
            }

            $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
            $text = $data['candidates'][0]['content']['parts'][0]['text'] ?? '';
            $text = $this->stripCodeFences($text);

            return new JsonResponse([
                'ok'   => true,
                'mode' => $mode,
                'html' => 'html' === $mode ? $text : '',
                'mjml' => 'mjml' === $mode ? $text : '',
            ]);
        } catch (GuzzleException $e) {
            $msg = $e->getMessage();
            // Surface a friendly hint for the common GFW / no-outbound case.
            if (preg_match('/Failed to connect|Could not connect|cURL error 28|timed out/i', $msg)) {
                $hint = '' !== $proxy
                    ? 'Proxy is set but unreachable — check the gemini_proxy address/port and that the proxy is running.'
                    : 'The server cannot reach Google. Behind the GFW or without outbound access, set a gemini_proxy (e.g. http://127.0.0.1:7890) in config/local.php, or run a global VPN (TUN mode) on this machine.';
                $msg .= ' [Network] '.$hint;
            }

            return new JsonResponse(['error' => 'Gemini request failed: '.$msg], 502);
        } catch (\Throwable $e) {
            return new JsonResponse(['error' => $e->getMessage()], 502);
        }
    }

    /**
     * Returns the configured Gemini key/endpoint to the admin browser client.
     * The actual Gemini call is made client-side (browser -> Google) because
     * the Mautic server (sandboxed) has no outbound internet.
     */
    public function configAction(CoreParametersHelper $coreParametersHelper): JsonResponse
    {
        $apiKey   = trim((string) $coreParametersHelper->get('gemini_api_key'));
        $model    = (string) $coreParametersHelper->get('gemini_model', 'gemini-1.5-flash');
        $endpoint = (string) $coreParametersHelper->get(
            'gemini_endpoint',
            'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        );
        $endpoint = str_replace('{model}', $model, $endpoint);

        return new JsonResponse([
            'apiKey'   => $apiKey,
            'endpoint' => $endpoint,
            'model'    => $model,
        ]);
    }

    private function stripCodeFences(string $text): string
    {
        $text = trim($text);
        // Remove markdown code fences (```xml, ```html, ```)
        if (preg_match('/^```[a-z]*\s*(.*?)\s*```$/s', $text, $matches)) {
            return trim($matches[1]);
        }

        return $text;
    }
}
