<?php

declare(strict_types=1);

namespace MauticPlugin\SourceMarketingBundle\Service;

use Mautic\CoreBundle\Helper\CoreParametersHelper;
use Symfony\Component\Intl\Countries;

/**
 * Country -> (timezone | send policy | silence window) resolver.
 *
 * Mautic stores `leads.country` as the ENGLISH country name (Symfony\Intl\Countries::getNames('en')),
 * e.g. "Philippines", "United States". This service maps that value to:
 *   1. an IANA timezone   -> drives the 22:00-08:00 silence window in the contact's local time
 *   2. an email policy    -> allow / block / consent-required
 *   3. an optional per-country silence window override
 *
 * Resolution is automatic for all ~250 ISO countries via PHP's built-in
 * DateTimeZone::listIdentifiers(PER_COUNTRY), so no hand-maintained table is needed.
 * Only multi-timezone countries need an explicit primary timezone (see TZ_PRIMARY).
 *
 * Everything is overridable at runtime from config/local.php:
 *
 *   'sourcemarketing_country_policy' => [
 *       'blocked'                  => ['KP'],                  // never email these
 *       'consent_required_enabled' => false,                   // turn on GDPR/EEA opt-in gate
 *       'consent_required'         => [],                      // [] = use built-in EEA list
 *       'timezone'                 => ['PH' => 'Asia/Manila'], // override resolved timezone
 *       'silence'                  => ['JP' => [21, 9]],       // per-country quiet hours
 *   ],
 */
class CountryPolicyService
{
    public const DEFAULT_SILENCE_START = 22; // inclusive
    public const DEFAULT_SILENCE_END   = 8;  // exclusive

    public const POLICY_ALLOW   = 'allow';
    public const POLICY_BLOCK   = 'block';
    public const POLICY_CONSENT = 'consent_required';

    /**
     * Primary timezone for countries spanning several zones.
     * Without this, listIdentifiers() returns the alphabetically-first zone, which is
     * usually a remote outpost (US -> America/Adak, ES -> Africa/Ceuta ...).
     */
    private const TZ_PRIMARY = [
        'CN' => 'Asia/Shanghai',
        'US' => 'America/New_York',
        'CA' => 'America/Toronto',
        'RU' => 'Europe/Moscow',
        'AU' => 'Australia/Sydney',
        'BR' => 'America/Sao_Paulo',
        'MX' => 'America/Mexico_City',
        'ID' => 'Asia/Jakarta',
        'IN' => 'Asia/Kolkata',
        'KZ' => 'Asia/Almaty',
        'MN' => 'Asia/Ulaanbaatar',
        'MY' => 'Asia/Kuala_Lumpur',
        'ES' => 'Europe/Madrid',
        'PT' => 'Europe/Lisbon',
        'FR' => 'Europe/Paris',
        'NL' => 'Europe/Amsterdam',
        'GB' => 'Europe/London',
        'DK' => 'Europe/Copenhagen',
        'AR' => 'America/Argentina/Buenos_Aires',
        'CL' => 'America/Santiago',
        'EC' => 'America/Guayaquil',
        'CD' => 'Africa/Kinshasa',
        'NZ' => 'Pacific/Auckland',
        'PG' => 'Pacific/Port_Moresby',
        'KI' => 'Pacific/Tarawa',
        'FM' => 'Pacific/Pohnpei',
        'PF' => 'Pacific/Tahiti',
        'GL' => 'America/Nuuk',
        'UA' => 'Europe/Kyiv',
        'PS' => 'Asia/Hebron',
        'CY' => 'Asia/Nicosia',
    ];

    /**
     * Aliases the CRM / platform feeds may send instead of the canonical English name:
     * Chinese names, ISO3 codes, and common short forms. Keys are lowercase.
     */
    private const ALIASES = [
        // Greater China (always use the full official form)
        '中国' => 'CN', '中国大陆' => 'CN', '中国内地' => 'CN', '中华人民共和国' => 'CN',
        'china' => 'CN', 'p.r. china' => 'CN', 'prc' => 'CN', 'mainland china' => 'CN',
        '中国香港' => 'HK', '香港' => 'HK', 'hong kong' => 'HK', 'hong kong, china' => 'HK', 'hongkong' => 'HK', 'hk sar' => 'HK',
        '中国澳门' => 'MO', '澳门' => 'MO', 'macao' => 'MO', 'macau' => 'MO', 'macao, china' => 'MO',
        '中国台湾' => 'TW', '台湾' => 'TW', 'taiwan' => 'TW', 'taiwan, china' => 'TW', 'chinese taipei' => 'TW',
        // Asia-Pacific source markets
        '日本' => 'JP', 'japan' => 'JP',
        '韩国' => 'KR', '南韩' => 'KR', '大韩民国' => 'KR', 'south korea' => 'KR', 'korea' => 'KR', 'republic of korea' => 'KR',
        '新加坡' => 'SG', 'singapore' => 'SG',
        '马来西亚' => 'MY', 'malaysia' => 'MY',
        '泰国' => 'TH', 'thailand' => 'TH',
        '越南' => 'VN', 'vietnam' => 'VN', 'viet nam' => 'VN',
        '菲律宾' => 'PH', 'philippines' => 'PH',
        '印尼' => 'ID', '印度尼西亚' => 'ID', 'indonesia' => 'ID',
        '印度' => 'IN', 'india' => 'IN',
        '澳大利亚' => 'AU', '澳洲' => 'AU', 'australia' => 'AU',
        '新西兰' => 'NZ', 'new zealand' => 'NZ',
        // Long-haul
        '美国' => 'US', 'usa' => 'US', 'u.s.' => 'US', 'u.s.a.' => 'US', 'america' => 'US', 'united states of america' => 'US',
        '加拿大' => 'CA', 'canada' => 'CA',
        '英国' => 'GB', 'uk' => 'GB', 'u.k.' => 'GB', 'england' => 'GB', 'great britain' => 'GB', 'britain' => 'GB',
        '法国' => 'FR', 'france' => 'FR',
        '德国' => 'DE', 'germany' => 'DE',
        '意大利' => 'IT', 'italy' => 'IT',
        '西班牙' => 'ES', 'spain' => 'ES',
        '俄罗斯' => 'RU', 'russia' => 'RU',
        '阿联酋' => 'AE', '迪拜' => 'AE', 'uae' => 'AE', 'dubai' => 'AE',
        '沙特' => 'SA', 'saudi arabia' => 'SA',
        '土耳其' => 'TR', 'turkey' => 'TR', 'turkiye' => 'TR',
        '瑞士' => 'CH', '荷兰' => 'NL', '比利时' => 'BE', '瑞典' => 'SE', '挪威' => 'NO',
        '丹麦' => 'DK', '芬兰' => 'FI', '奥地利' => 'AT', '希腊' => 'GR', '葡萄牙' => 'PT',
        '波兰' => 'PL', '捷克' => 'CZ', '匈牙利' => 'HU', '爱尔兰' => 'IE',
        '巴西' => 'BR', '墨西哥' => 'MX', '阿根廷' => 'AR', '南非' => 'ZA', '埃及' => 'EG',
    ];

    /**
     * EEA + UK + Switzerland: GDPR / ePrivacy require prior opt-in for marketing email.
     * Only enforced when `consent_required_enabled` is turned on in config.
     */
    private const EEA_CONSENT = [
        'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
        'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
        'IS', 'LI', 'NO', 'GB', 'CH',
    ];

    /** @var array<string,string|null> */
    private array $tzCache = [];

    /** @var array<string,string>|null lowercase english name => alpha2 */
    private static ?array $nameIndex = null;

    public function __construct(private CoreParametersHelper $coreParametersHelper)
    {
    }

    /**
     * @return array<string,mixed>
     */
    private function config(): array
    {
        $cfg = $this->coreParametersHelper->get('sourcemarketing_country_policy', []);

        return is_array($cfg) ? $cfg : [];
    }

    /**
     * Normalise whatever the platform sent into an ISO 3166-1 alpha-2 code.
     * Accepts: canonical English name, Chinese name, alias, alpha-2, alpha-3.
     */
    public function toAlpha2(?string $country): ?string
    {
        $raw = trim((string) $country);
        if ('' === $raw) {
            return null;
        }

        $key = mb_strtolower($raw);

        if (isset(self::ALIASES[$key])) {
            return self::ALIASES[$key];
        }

        // Direct alpha-2 / alpha-3
        $upper = strtoupper($raw);
        if (2 === strlen($upper) && Countries::exists($upper)) {
            return $upper;
        }
        if (3 === strlen($upper) && Countries::alpha3CodeExists($upper)) {
            return Countries::getAlpha2Code($upper);
        }

        // Canonical English name lookup (case-insensitive)
        if (null === self::$nameIndex) {
            self::$nameIndex = [];
            foreach (Countries::getNames('en') as $code => $name) {
                self::$nameIndex[mb_strtolower($name)] = $code;
            }
        }
        if (isset(self::$nameIndex[$key])) {
            return self::$nameIndex[$key];
        }

        // Tolerate "Taiwan, Province of China" / "Korea, Republic of" style variants
        foreach (self::$nameIndex as $name => $code) {
            if (str_starts_with($name, $key.',') || str_starts_with($key, $name.',')) {
                return $code;
            }
        }

        return null;
    }

    /**
     * The "server clock" used when a contact has neither a timezone nor a resolvable
     * country. Reads Mautic's own General Settings -> Default timezone first, so the
     * fallback can be steered from the admin UI instead of the PHP ini.
     */
    public function serverTimezone(): string
    {
        $configured = trim((string) $this->coreParametersHelper->get('default_timezone', ''));
        if ('' !== $configured) {
            try {
                new \DateTimeZone($configured);

                return $configured;
            } catch (\Throwable $e) {
                // fall through to the PHP default
            }
        }

        return date_default_timezone_get() ?: 'UTC';
    }

    /**
     * Canonical English country name as used by Mautic's country picker.
     * Falls back to the raw input when the value cannot be resolved, so we never
     * silently drop data the platform sent.
     */
    public function normalizeName(string $country): string
    {
        $alpha2 = $this->toAlpha2($country);

        return $alpha2 ? Countries::getName($alpha2, 'en') : trim($country);
    }

    /**
     * Resolve the IANA timezone for a country value. NULL when unresolvable
     * (caller then falls back to the server clock).
     */
    public function resolveTimezone(?string $country): ?string
    {
        $alpha2 = $this->toAlpha2($country);
        if (null === $alpha2) {
            return null;
        }

        if (array_key_exists($alpha2, $this->tzCache)) {
            return $this->tzCache[$alpha2];
        }

        $overrides = $this->config()['timezone'] ?? [];
        if (is_array($overrides) && !empty($overrides[$alpha2])) {
            return $this->tzCache[$alpha2] = (string) $overrides[$alpha2];
        }

        if (isset(self::TZ_PRIMARY[$alpha2])) {
            return $this->tzCache[$alpha2] = self::TZ_PRIMARY[$alpha2];
        }

        $zones = \DateTimeZone::listIdentifiers(\DateTimeZone::PER_COUNTRY, $alpha2);

        return $this->tzCache[$alpha2] = $zones[0] ?? null;
    }

    /**
     * Quiet hours for a country (defaults to 22:00-08:00).
     *
     * @return array{0:int,1:int} [startHourInclusive, endHourExclusive]
     */
    public function silenceWindow(?string $country): array
    {
        $alpha2 = $this->toAlpha2($country);
        $map    = $this->config()['silence'] ?? [];

        if ($alpha2 && is_array($map) && isset($map[$alpha2]) && is_array($map[$alpha2]) && 2 === count($map[$alpha2])) {
            return [(int) $map[$alpha2][0], (int) $map[$alpha2][1]];
        }

        return [self::DEFAULT_SILENCE_START, self::DEFAULT_SILENCE_END];
    }

    /**
     * Whether email may be sent to this country.
     *
     * @return array{policy:string,allowed:bool,needs_consent:bool,alpha2:?string}
     */
    public function emailPolicy(?string $country): array
    {
        $alpha2 = $this->toAlpha2($country);
        $cfg    = $this->config();

        $blocked = $cfg['blocked'] ?? [];
        $blocked = is_array($blocked) ? array_map('strtoupper', $blocked) : [];
        if ($alpha2 && in_array($alpha2, $blocked, true)) {
            return ['policy' => self::POLICY_BLOCK, 'allowed' => false, 'needs_consent' => false, 'alpha2' => $alpha2];
        }

        if (!empty($cfg['consent_required_enabled'])) {
            $list = $cfg['consent_required'] ?? [];
            $list = (is_array($list) && $list) ? array_map('strtoupper', $list) : self::EEA_CONSENT;
            if ($alpha2 && in_array($alpha2, $list, true)) {
                return ['policy' => self::POLICY_CONSENT, 'allowed' => true, 'needs_consent' => true, 'alpha2' => $alpha2];
            }
        }

        return ['policy' => self::POLICY_ALLOW, 'allowed' => true, 'needs_consent' => false, 'alpha2' => $alpha2];
    }

    /**
     * Full debug view — powers GET /sourcemarketing/country-policy.
     *
     * @return array<string,mixed>
     */
    public function describe(?string $country): array
    {
        $alpha2   = $this->toAlpha2($country);
        $tz       = $this->resolveTimezone($country);
        $policy   = $this->emailPolicy($country);
        [$s, $e]  = $this->silenceWindow($country);
        $localNow = null;

        if ($tz) {
            try {
                $localNow = (new \DateTime('now', new \DateTimeZone($tz)))->format('Y-m-d H:i');
            } catch (\Throwable $ex) {
                $tz = null;
            }
        }

        return [
            'input'          => $country,
            'alpha2'         => $alpha2,
            'country_name'   => $alpha2 ? Countries::getName($alpha2, 'en') : null,
            'resolved'       => null !== $alpha2,
            'timezone'       => $tz,
            'local_time'     => $localNow,
            'silence_window' => sprintf('%02d:00-%02d:00', $s, $e),
            'in_silence'     => $localNow ? $this->hourInWindow((int) (new \DateTime('now', new \DateTimeZone($tz)))->format('G'), $s, $e) : null,
            'email_policy'   => $policy['policy'],
            'email_allowed'  => $policy['allowed'],
            'needs_consent'  => $policy['needs_consent'],
        ];
    }

    public function hourInWindow(int $hour, int $start, int $end): bool
    {
        // Window wraps midnight (22 -> 8) or is a plain daytime range.
        return $start > $end ? ($hour >= $start || $hour < $end) : ($hour >= $start && $hour < $end);
    }
}
