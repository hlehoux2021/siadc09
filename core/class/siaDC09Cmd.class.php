<?php
/* This file is part of Jeedom.
 *
 * Jeedom is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * Jeedom is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with Jeedom. If not, see <http://www.gnu.org/licenses/>.
 */

require_once __DIR__ . '/../../../../core/php/core.inc.php';

class siaDC09Cmd extends cmd {

    private const OPEN_ALARMS_MAX = 90;
    private const OPEN_ALARMS_TTL = 86400;

    // ADR-17 Amendment 3 (Option D): generous relative to a typical 30-60s alarm-plugin
    // trigger delay — a confirmed prefetch hit older than this is treated as expired.
    private const PREFETCH_CACHE_TTL = 120;

    private const OPEN_ALARMS_SIA_CODES = [
        'burglarAlarm' => 'BA',
        'fireAlarm'    => 'FA',
        'panicAlarm'   => 'PA',
    ];

    public function execute($_options = array()): void {
        $logicalId = $this->getLogicalId();
        switch ($logicalId) {
            case 'prefetchEvent':
                // ADR-17 Amendment 3 (Option D): wired by the installer into the mapped zone's
                // IMMEDIATE actions — fires the instant the real sensor trips, well before
                // burglarAlarm's own standard-action send. Fire-and-forget: no response is
                // awaited (impossible on the existing control socket — jeedomdaemon's Listener
                // closes the connection before invoking on_message()).
                $zone = trim($_options['title'] ?? '');
                $zoneEntry = $this->_findZoneEntry($zone, $this->_getZoneMapping()) ?? [];
                $target = $this->_resolvePrefetchTarget($zoneEntry);
                if ($target !== null) {
                    siaDC09::sendToDaemon([
                        'cmd'               => 'prefetchEvent',
                        'camera_eqlogic_id' => $target['camera_eqlogic_id'],
                        'camera_name'       => $target['camera_name'],
                        'frigate_host'      => $target['frigate_host'],
                    ]);
                }
                break;

            case 'burglarAlarm':
            case 'fireAlarm':
            case 'panicAlarm':
                // The alarm plugin's #zone# tag substitutes the zone LABEL — its zone model has
                // no identifier. The label stays in the payload for the logs, the notification
                // context and the inspector; only zone_number reaches the SIA frame.
                $zone = trim($_options['title'] ?? '');
                $zoneNumber = $this->_resolveZoneNumber($zone);
                $payload = [
                    'cmd'         => $logicalId,
                    'zone'        => $zone !== '' ? $zone : null,
                    'zone_number' => $zoneNumber,
                ];
                // ADR-17: majority case only — a person already detected by Frigate before the
                // alarm fired. Key is omitted entirely (not set to null) when unavailable, so a
                // missing camera/plugin never changes the payload shape sent to the daemon.
                $zoneEntry = $this->_findZoneEntry($zone, $this->_getZoneMapping()) ?? [];
                $snapshotUrl = $this->_resolveFrigateSnapshotUrl($zoneEntry);
                if ($snapshotUrl !== null) {
                    $payload['media_url'] = $snapshotUrl;
                }
                siaDC09::sendToDaemon($payload);
                $this->_recordOpenAlarm($logicalId, $zone !== '' ? $zone : null, $zoneNumber);
                break;
        }
    }

    /**
     * Persists this emission into sia_open_alarms so a later burglaryCancel can fan out one BC
     * per zone still open (story 13-1, A-PHP). Written at emission time, not at ACK — the
     * plugin's policy is to never drop a frame, and a spurious BC is harmless while a missing
     * one is not.
     */
    private function _recordOpenAlarm(string $logicalId, ?string $zone, ?int $zoneNumber): void {
        $eqLogic = $this->getEqLogic();
        $siaCode = self::OPEN_ALARMS_SIA_CODES[$logicalId] ?? null;
        if ($eqLogic === null || $siaCode === null) {
            return;
        }

        $now = time();
        $openAlarms = $eqLogic->getCache('sia_open_alarms', []);
        if (is_string($openAlarms)) {
            $openAlarms = json_decode($openAlarms, true);
        }
        if (!is_array($openAlarms)) {
            $openAlarms = [];
        }

        foreach ($openAlarms as $key => $entry) {
            if (!is_array($entry) || !isset($entry['ts']) || ($now - (int) $entry['ts']) > self::OPEN_ALARMS_TTL) {
                unset($openAlarms[$key]);
            }
        }

        $key = $siaCode . '|' . ($zoneNumber !== null ? $zoneNumber : 'account');
        $openAlarms[$key] = [
            'sia_code'    => $siaCode,
            'zone'        => $zone,
            'zone_number' => $zoneNumber,
            'ts'          => $now,
        ];

        if (count($openAlarms) > self::OPEN_ALARMS_MAX) {
            uasort($openAlarms, function (array $a, array $b): int {
                return ($a['ts'] ?? 0) <=> ($b['ts'] ?? 0);
            });
            while (count($openAlarms) > self::OPEN_ALARMS_MAX) {
                unset($openAlarms[array_key_first($openAlarms)]);
            }
        }

        $eqLogic->setCache('sia_open_alarms', $openAlarms);
    }

    /**
     * Order number declared to the CSR for this zone, or null when the label matches no entry
     * of sia_zone_mappings — the daemon then emits a frame with no zone field at all rather
     * than transmitting a free-text label. The alarm is never dropped.
     */
    private function _resolveZoneNumber(string $zone): ?int {
        if ($zone === '') {
            return null;
        }
        $entry = $this->_findZoneEntry($zone, $this->_getZoneMapping());
        if ($entry !== null && !empty($entry['zone_number'])) {
            return (int) $entry['zone_number'];
        }
        log::add('siaDC09', 'warning', 'Zone "' . $zone . '" '
            . __('absente de la table des zones — trame envoyée sans numéro de zone', __FILE__));
        return null;
    }

    /**
     * ADR-17 Amendment 3 (Option D): resolves what the daemon needs to run a Frigate REST
     * prefetch for this zone's mapped camera — the camera's own Frigate-native name
     * (`getConfiguration('name')`, set by the Frigate plugin itself at camera-creation time,
     * never a siaDC09 config field — confirmed by reading the Frigate plugin's own source) and
     * the Frigate server's `host:port` (the Frigate plugin's own **global** config,
     * `config::byKey('URL'|'port', 'frigate')` — a read-only cross-plugin read, deliberately not
     * a call to `\frigate::getUrlFrigate()`, to avoid a hard class dependency on a plugin that
     * may be absent or disabled). Returns null on any missing piece; never throws.
     */
    private function _resolvePrefetchTarget(array $zoneEntry): ?array {
        try {
            $eqLogicId = $zoneEntry['frigate_camera_eqlogic_id'] ?? null;
            if (empty($eqLogicId)) {
                return null;
            }
            $cameraEqLogic = eqLogic::byId((int) $eqLogicId);
            if (!is_object($cameraEqLogic)) {
                return null;
            }
            $cameraName = $cameraEqLogic->getConfiguration('name', '');
            if (!is_string($cameraName) || $cameraName === '') {
                return null;
            }
            $frigateUrl = config::byKey('URL', 'frigate', '');
            $frigatePort = config::byKey('port', 'frigate', '');
            if (!is_string($frigateUrl) || $frigateUrl === '' || (string) $frigatePort === '') {
                return null;
            }
            return [
                'camera_eqlogic_id' => (int) $eqLogicId,
                'camera_name'       => $cameraName,
                'frigate_host'      => $frigateUrl . ':' . $frigatePort,
            ];
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Résolution de la cible Frigate prefetch échouée : ' . $e->getMessage());
            return null;
        }
    }

    /**
     * ADR-17 Amendment 3 (Option D): reads the daemon's Frigate REST prefetch outcome from the
     * Jeedom-side cache (`sia_prefetch_cache`, written by `siaDC09::_handlePrefetchResult()` in
     * response to the immediate-action `prefetchEvent` trigger) — a synchronous, local,
     * non-blocking read, same latency class as the `execCmd()` reads it replaces. Returns null
     * unless the cache holds a confirmed, non-expired hit for this zone's mapped camera: no
     * entry (prefetchEvent never fired, or hasn't reported back yet), an explicit miss, or an
     * entry older than `PREFETCH_CACHE_TTL` all resolve to null — the same two-outcome contract
     * as before (AC6: no third fallback tier). Never reads `info_detect_person`, `info_id`,
     * `info_label`, or `info_url_snapshot` again for this decision (superseded by Amendment 3).
     * Never throws.
     */
    private function _resolveFrigateSnapshotUrl(array $zoneEntry): ?string {
        try {
            $eqLogicId = $zoneEntry['frigate_camera_eqlogic_id'] ?? null;
            if (empty($eqLogicId)) {
                return null;
            }
            $eqLogic = $this->getEqLogic();
            if ($eqLogic === null) {
                return null;
            }
            $raw = $eqLogic->getCache('sia_prefetch_cache', []);
            $cache = is_string($raw) ? json_decode($raw, true) : $raw;
            if (!is_array($cache)) {
                return null;
            }
            $entry = $cache[(int) $eqLogicId] ?? null;
            if (!is_array($entry) || empty($entry['found'])) {
                return null;
            }
            if (time() - (int) ($entry['ts'] ?? 0) > self::PREFETCH_CACHE_TTL) {
                return null;
            }
            $eventId = $entry['event_id'] ?? null;
            if (!is_string($eventId) || $eventId === '') {
                return null;
            }
            $template = $eqLogic->getConfiguration('frigate_media_url_template', '');
            if (!is_string($template) || $template === '') {
                return null;
            }
            return self::_buildFrigateMediaUrl($template, $eventId);
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Résolution du snapshot Frigate échouée : ' . $e->getMessage());
            return null;
        }
    }

    /**
     * Builds an absolute media URL from a configurable template containing literal placeholder
     * credentials (e.g. `<user>`, `<pass>`, `<token>`) plus the Frigate event id — siaDC09 never
     * stores or transmits a real secret; the CSR substitutes the placeholder itself, out-of-band
     * (ADR-17 amendment, 2026-09-23). Inserts `api/events/{eventId}/snapshot.jpg` into the
     * template's path component, before any existing query string, so a query-string credential
     * form (`?accesstoken=<token>`) still ends up at the very end of the final URL rather than
     * stranded before the inserted path by naive string concatenation.
     *
     * @param string $template e.g. "https://<user>:<pass>@host/" or "https://host/?accesstoken=<token>"
     * @param string $eventId Frigate event id, read from info_id
     * @return string|null null when the template has no scheme or host — never throws
     */
    private static function _buildFrigateMediaUrl(string $template, string $eventId): ?string {
        $parts = parse_url($template);
        if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
            return null;
        }

        $path = rtrim($parts['path'] ?? '', '/') . '/api/events/' . rawurlencode($eventId) . '/snapshot.jpg';

        $userinfo = '';
        if (isset($parts['user']) && $parts['user'] !== '') {
            $userinfo = $parts['user'];
            if (isset($parts['pass']) && $parts['pass'] !== '') {
                $userinfo .= ':' . $parts['pass'];
            }
            $userinfo .= '@';
        }

        $port = isset($parts['port']) ? ':' . $parts['port'] : '';

        $url = $parts['scheme'] . '://' . $userinfo . $parts['host'] . $port . $path;

        if (isset($parts['query']) && $parts['query'] !== '') {
            $url .= '?' . $parts['query'];
        }
        if (isset($parts['fragment']) && $parts['fragment'] !== '') {
            $url .= '#' . $parts['fragment'];
        }

        return $url;
    }

    private function _getZoneMapping(): array {
        $eqLogic = $this->getEqLogic();
        if ($eqLogic === null) {
            return [];
        }
        $mapping = $eqLogic->getConfiguration('sia_zone_mappings', []);
        if (is_string($mapping)) {
            $mapping = json_decode($mapping, true);
        }
        return is_array($mapping) ? $mapping : [];
    }

    /**
     * Case-insensitive and whitespace-tolerant: the label reaches us through a user-typed
     * action title, the table through the alarm plugin.
     */
    private function _findZoneEntry(string $zone, array $zoneMapping): ?array {
        $needle = mb_strtolower(trim($zone));
        foreach ($zoneMapping as $entry) {
            if (!is_array($entry)) {
                continue;
            }
            if (mb_strtolower(trim($entry['zone_name'] ?? '')) === $needle) {
                return $entry;
            }
        }
        return null;
    }
}
