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

    // ADR-17 Amendment 4 (Story 14-4): the placeholder rank written at prefetchEvent time,
    // before the daemon has reported anything back — mirrors
    // resources/siadc09d/frigate_prefetch.py's RANK_NONE (worse than any real rank, so the
    // first genuine callback of the run always replaces it per _prefetchResultShouldReplace()).
    private const PREFETCH_RANK_NONE = 4;

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
                log::add('siaDC09', 'debug', 'prefetchEvent: execute() invoked, raw title='
                    . json_encode($_options['title'] ?? null));
                $zone = trim($_options['title'] ?? '');
                if ($zone === '') {
                    log::add('siaDC09', 'warning', 'prefetchEvent déclenché sans zone — '
                        . 'le champ Titre de cette action doit contenir #zone# (voir le guide de '
                        . 'l\'assistant, étape 3)');
                    break;
                }
                if ($zone === '#zone#') {
                    log::add('siaDC09', 'warning', 'prefetchEvent : le champ Titre contient encore le texte '
                        . 'littéral "#zone#" — le plugin Alarme n\'a pas substitué la balise (vérifiez que '
                        . 'l\'action est bien de type "message" et déclenchée par le plugin Alarme)');
                    break;
                }
                $zoneMapping = $this->_getZoneMapping();
                log::add('siaDC09', 'debug', 'prefetchEvent: zone=' . json_encode($zone)
                    . ' zoneMapping=' . json_encode($zoneMapping));
                $zoneEntry = $this->_findZoneEntry($zone, $zoneMapping) ?? [];
                log::add('siaDC09', 'debug', 'prefetchEvent: resolved zoneEntry='
                    . json_encode($zoneEntry));
                $target = $this->_resolvePrefetchTarget($zoneEntry);
                if ($target === null) {
                    log::add('siaDC09', 'warning', 'prefetchEvent : impossible de résoudre la '
                        . 'caméra Frigate pour la zone "' . $zone . '" — zone non mappée à une '
                        . 'caméra, caméra supprimée, ou configuration Frigate (URL/port) absente');
                    break;
                }
                log::add('siaDC09', 'debug', 'prefetchEvent: resolved target=' . json_encode($target));
                // ADR-17 Amendment 4 (Story 14-4, R2): run_id is generated and owned here,
                // by the process that owns the cache — no clock-sync question with the
                // daemon. The placeholder is written BEFORE sendToDaemon(), so a create
                // call that fails on the daemon side (Frigate refused/unreachable, no
                // callback ever sent for this run) still can't leave a stale hit from an
                // earlier, unrelated trigger sitting in the cache.
                // Code review (2026-09-27): a bare (string) microtime(true) is truncated
                // by PHP's `precision` ini (default 14 significant figures) to roughly
                // 0.1ms resolution, not true microsecond resolution — two triggers close
                // enough together (e.g. two zones mapped to the same camera) could collide
                // on an identical run_id. sprintf('%.6f', ...) forces full microsecond
                // digits regardless of `precision`, and the random suffix guarantees
                // uniqueness even within the same microsecond; (float) casts of the result
                // still parse only the leading numeric part, so the run_id/rank ordering
                // rule in siaDC09::_prefetchResultShouldReplace() is unaffected.
                $runId = sprintf('%.6f', microtime(true)) . '-' . bin2hex(random_bytes(3));
                $this->_writePrefetchPlaceholder((int) $target['camera_eqlogic_id'], $runId);
                siaDC09::sendToDaemon([
                    'cmd'               => 'prefetchEvent',
                    'camera_eqlogic_id' => $target['camera_eqlogic_id'],
                    'camera_name'       => $target['camera_name'],
                    'frigate_host'      => $target['frigate_host'],
                    'run_id'            => $runId,
                ]);
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
                // Single shared cache read passed to both resolvers (code review 2026-09-26):
                // closes a TOCTOU where two independent getCache() reads could straddle a
                // concurrent _handlePrefetchResult() callback and join a snapshot URL from one
                // event with a clip URL from a different, later one.
                $cacheEntry = $this->_readPrefetchCacheEntry($zoneEntry);
                $snapshotUrl = $this->_resolveFrigateSnapshotUrl($zoneEntry, $cacheEntry);
                $clipUrl = $this->_resolveFrigateClipUrl($zoneEntry, $cacheEntry);
                // Story 14-3: join both media (space-separated, one [V...] block) when both
                // resolve; fall back to whichever one resolves alone; omit entirely when
                // neither does — same fallback contract as 14-1/14-2, just for two URLs.
                $mediaParts = array_filter([$snapshotUrl, $clipUrl], fn($u) => $u !== null);
                if (!empty($mediaParts)) {
                    $payload['media_url'] = implode(' ', $mediaParts);
                }
                siaDC09::sendToDaemon($payload);
                $this->_recordOpenAlarm($logicalId, $zone !== '' ? $zone : null, $zoneNumber);
                break;

            case 'disarm':
                // Story 13.1 — wired on the alarm plugin's `release` ("Désactivation OK").
                // BC/OP address by user number, never by zone (DC-03 p.4) — ADR-18.
                $userNumber = $this->_resolveSiaUserNumber();
                if ($this->_hasOpenAlarm('BA')) {
                    siaDC09::sendToDaemon(['cmd' => 'disarm', 'user_number' => $userNumber, 'sia_code' => 'BC']);
                    siaDC09::sendToDaemon(['cmd' => 'disarm', 'user_number' => $userNumber, 'sia_code' => 'OP']);
                    $this->_purgeOpenAlarms('BA');
                } else {
                    // Story 13-4 — no BA was open: this is a normal disarm, outside any
                    // alarm context. Sends the Opening Report alone. `released` has no
                    // already-disarmed guard (alarm.class.php:700-703, unlike `armed`), so a
                    // repeated "Désactiver" sends another OP — accepted: OP is idempotent
                    // for the CSR (review 13-4, D1).
                    siaDC09::sendToDaemon(['cmd' => 'disarm', 'user_number' => $userNumber, 'sia_code' => 'OP']);
                }
                break;

            case 'arm':
                // Story 13-4 — wired on the alarm plugin's `activationImmediateOk`, which
                // fires on every successful arm (unlike `activationOk`, which never fires
                // after `activationKo`). Always sends exactly one CL: unlike disarm/
                // alarmReset, this command never varies its code, so — like burglarAlarm/
                // fireAlarm/panicAlarm — the mapping lives in the daemon's fixed
                // _EVENT_SIA_CODES, not in the payload.
                siaDC09::sendToDaemon([
                    'cmd'         => 'arm',
                    'user_number' => $this->_resolveSiaUserNumber(),
                ]);
                break;

            case 'alarmReset':
                // Story 13.1 — wired on the alarm plugin's `raz` ("Réinitialisation"). Sees the
                // mode-change reset that `release` never runs for (system stays armed).
                $userNumber = $this->_resolveSiaUserNumber();
                if ($this->_hasOpenAlarm('BA')) {
                    siaDC09::sendToDaemon(['cmd' => 'alarmReset', 'user_number' => $userNumber, 'sia_code' => 'BC']);
                    $this->_purgeOpenAlarms('BA');
                } else {
                    log::add('siaDC09', 'debug',
                        'alarmReset : aucune alarme intrusion ouverte — soit `disarm` l\'a déjà '
                        . 'purgée (désactivation normale), soit rien n\'était à réinitialiser');
                }
                break;
        }
    }

    /**
     * The configured SIA user number (wizard step 3, `sia_user_number`, default 1) — the
     * address field for every DC-03 user-addressed code (BC, OP, CL). The alarm plugin never
     * forwards the Jeedom user to its actions, so this is a configured value, not read data.
     */
    private function _resolveSiaUserNumber(): int {
        $eqLogic = $this->getEqLogic();
        if ($eqLogic === null) {
            return 1;
        }
        // Wizard input has min="1" max="999" (DC-03 Annex B: 3 zero-padded digits), but that
        // is HTML-only — nothing enforced the range server-side (code review 2026-09-26). A
        // saved 0/negative/>999 value would otherwise reach f"{n:03d}" on the daemon side
        // unclamped, breaking the fixed-width address-field contract.
        $n = (int) $eqLogic->getConfiguration('sia_user_number', 1);
        return ($n >= 1 && $n <= 999) ? $n : 1;
    }

    /**
     * True when sia_open_alarms still holds a non-expired entry for $siaCode — the "is a BA
     * still open?" oracle both disarm and alarmReset rely on (story 13-1, ADR-18). There is at
     * most one open burglary alarm to close by construction of the alarm plugin (one equipment,
     * one armed/disarmed state), so a boolean is enough — no more per-zone fan-out.
     */
    private function _hasOpenAlarm(string $siaCode): bool {
        $eqLogic = $this->getEqLogic();
        if ($eqLogic === null) {
            return false;
        }
        foreach ($this->_loadOpenAlarms($eqLogic) as $entry) {
            if (($entry['sia_code'] ?? null) === $siaCode) {
                return true;
            }
        }
        return false;
    }

    /**
     * Removes every open $siaCode entry on a BC (story 13-1): whichever of disarm/alarmReset
     * runs first purges the matching entries, so the alarm plugin's release-before-raz ordering
     * (alarm.class.php:703-712, ADR-18) guarantees the second command finds none left — never a
     * duplicate BC. Scoped to $siaCode (always 'BA' today) so a concurrent FA/PA — unrelated to
     * this burglary disarm — survives for the future story 13-3, per the design's own intent.
     */
    private function _purgeOpenAlarms(string $siaCode): void {
        $eqLogic = $this->getEqLogic();
        if ($eqLogic === null) {
            return;
        }
        $openAlarms = $this->_loadOpenAlarms($eqLogic);
        foreach ($openAlarms as $key => $entry) {
            if (($entry['sia_code'] ?? null) === $siaCode) {
                unset($openAlarms[$key]);
            }
        }
        $eqLogic->setCache('sia_open_alarms', $openAlarms);
    }

    /**
     * sia_open_alarms as an array, TTL-expired and malformed entries already dropped — the
     * cache may hand the table back JSON-encoded.
     */
    private function _loadOpenAlarms($eqLogic): array {
        $openAlarms = $eqLogic->getCache('sia_open_alarms', []);
        if (is_string($openAlarms)) {
            $openAlarms = json_decode($openAlarms, true);
        }
        if (!is_array($openAlarms)) {
            return [];
        }

        $now = time();
        foreach ($openAlarms as $key => $entry) {
            if (!is_array($entry) || !isset($entry['ts']) || ($now - (int) $entry['ts']) > self::OPEN_ALARMS_TTL) {
                unset($openAlarms[$key]);
            }
        }
        return $openAlarms;
    }

    /**
     * Dedups repeated alarms on one zone, and collapses every unresolved zone onto a single
     * 'account' entry — two unknown labels would otherwise yield two zoneless BC.
     */
    private static function _openAlarmKey(string $siaCode, ?int $zoneNumber): string {
        return $siaCode . '|' . ($zoneNumber !== null ? $zoneNumber : 'account');
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

        $openAlarms = $this->_loadOpenAlarms($eqLogic);
        $openAlarms[self::_openAlarmKey($siaCode, $zoneNumber)] = [
            'sia_code'    => $siaCode,
            'zone'        => $zone,
            'zone_number' => $zoneNumber,
            'ts'          => time(),
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
                log::add('siaDC09', 'debug',
                    '_resolvePrefetchTarget: frigate_camera_eqlogic_id absent de zoneEntry');
                return null;
            }
            $cameraEqLogic = eqLogic::byId((int) $eqLogicId);
            if (!is_object($cameraEqLogic)) {
                log::add('siaDC09', 'debug',
                    "_resolvePrefetchTarget: eqLogic::byId($eqLogicId) introuvable");
                return null;
            }
            $cameraName = $cameraEqLogic->getConfiguration('name', '');
            log::add('siaDC09', 'debug',
                "_resolvePrefetchTarget: eqLogicId=$eqLogicId cameraName=" . json_encode($cameraName));
            if (!is_string($cameraName) || $cameraName === '') {
                log::add('siaDC09', 'debug',
                    "_resolvePrefetchTarget: getConfiguration('name') vide pour l'eqLogic $eqLogicId "
                    . '— l\'équipement caméra a-t-il bien été créé par le plugin Frigate ?');
                return null;
            }
            $frigateUrl = config::byKey('URL', 'frigate', '');
            $frigatePort = config::byKey('port', 'frigate', '');
            log::add('siaDC09', 'debug',
                "_resolvePrefetchTarget: config::byKey('URL','frigate')=" . json_encode($frigateUrl)
                . " config::byKey('port','frigate')=" . json_encode($frigatePort));
            if (!is_string($frigateUrl) || $frigateUrl === '' || (string) $frigatePort === '') {
                log::add('siaDC09', 'debug',
                    '_resolvePrefetchTarget: configuration globale du plugin Frigate (URL/port) absente');
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
     * Single read of `sia_prefetch_cache`, keyed by the zone's mapped camera eqLogic id —
     * shared by execute() between _resolveFrigateSnapshotUrl() and _resolveFrigateClipUrl()
     * (code review 2026-09-26) so both see the exact same entry, closing a TOCTOU where two
     * independent reads could straddle a concurrent _handlePrefetchResult() callback. Returns
     * the raw entry array (still subject to each resolver's own found/clip_found/TTL/event_id
     * checks), or null if unavailable for any reason. Never throws.
     */
    private function _readPrefetchCacheEntry(array $zoneEntry): ?array {
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
            return is_array($entry) ? $entry : null;
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Lecture du cache de prefetch Frigate échouée : ' . $e->getMessage());
            return null;
        }
    }

    /**
     * ADR-17 Amendment 4 (Story 14-4, R2): writes a rank-PREFETCH_RANK_NONE placeholder
     * entry for `$cameraEqLogicId`, tagged with the new run's `$runId`, BEFORE
     * sendToDaemon() is called. Without this, a create call that fails on the daemon side
     * (Frigate refused/unreachable — no callback ever sent for this run) would leave
     * whatever entry an earlier, unrelated trigger on the same camera left behind sitting
     * in the cache indefinitely, which is exactly the "stale/not this alarm's" case
     * Amendment 4 still calls wrong. Once this placeholder is in place, the very first
     * genuine `prefetch_result` callback of this run always replaces it — its `run_id` is
     * numerically greater than any prior stored one (`_prefetchResultShouldReplace()`).
     * Same read-modify-write shape and never-throws contract as `_handlePrefetchResult()`.
     * A failed write here never blocks `sendToDaemon()`.
     */
    private function _writePrefetchPlaceholder(int $cameraEqLogicId, string $runId): void {
        try {
            $eqLogic = $this->getEqLogic();
            if ($eqLogic === null) {
                return;
            }
            $raw = $eqLogic->getCache('sia_prefetch_cache', []);
            $cache = is_string($raw) ? json_decode($raw, true) : $raw;
            if (!is_array($cache)) {
                $cache = [];
            }
            $cache[$cameraEqLogicId] = [
                'found'      => false,
                'event_id'   => null,
                'clip_found' => false,
                'rank'       => self::PREFETCH_RANK_NONE,
                'run_id'     => $runId,
                'ts'         => time(),
            ];
            $eqLogic->setCache('sia_prefetch_cache', $cache);
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Écriture du placeholder de cache prefetch Frigate échouée : '
                . $e->getMessage());
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
     * Never throws. Accepts an optional pre-read `$cacheEntry` (execute()'s single shared read)
     * to avoid a second independent cache read for the same zone/camera.
     */
    private function _resolveFrigateSnapshotUrl(array $zoneEntry, ?array $cacheEntry = null): ?string {
        try {
            $eqLogicId = $zoneEntry['frigate_camera_eqlogic_id'] ?? null;
            if (empty($eqLogicId)) {
                log::add('siaDC09', 'debug',
                    '_resolveFrigateSnapshotUrl: frigate_camera_eqlogic_id absent de zoneEntry');
                return null;
            }
            $eqLogic = $this->getEqLogic();
            if ($eqLogic === null) {
                log::add('siaDC09', 'debug', '_resolveFrigateSnapshotUrl: getEqLogic() a retourné null');
                return null;
            }
            // $cacheEntry, when provided by the caller (execute()'s single shared read — code
            // review 2026-09-26, closes a TOCTOU between this and _resolveFrigateClipUrl()'s
            // own read), is used as-is; otherwise this method reads the cache itself, same as
            // before (standalone/test callers).
            if ($cacheEntry !== null) {
                $entry = $cacheEntry;
            } else {
                $raw = $eqLogic->getCache('sia_prefetch_cache', []);
                log::add('siaDC09', 'debug', '_resolveFrigateSnapshotUrl: getCache(sia_prefetch_cache) brut='
                    . json_encode($raw));
                $cache = is_string($raw) ? json_decode($raw, true) : $raw;
                if (!is_array($cache)) {
                    log::add('siaDC09', 'debug', '_resolveFrigateSnapshotUrl: cache décodé non-array');
                    return null;
                }
                $entry = $cache[(int) $eqLogicId] ?? null;
            }
            log::add('siaDC09', 'debug', "_resolveFrigateSnapshotUrl: eqLogicId=$eqLogicId entry="
                . json_encode($entry));
            if (!is_array($entry) || empty($entry['found'])) {
                log::add('siaDC09', 'debug',
                    "_resolveFrigateSnapshotUrl: pas d'entrée trouvée ou found=false pour eqLogicId=$eqLogicId");
                return null;
            }
            $age = time() - (int) ($entry['ts'] ?? 0);
            if ($age > self::PREFETCH_CACHE_TTL) {
                log::add('siaDC09', 'debug',
                    "_resolveFrigateSnapshotUrl: entrée expirée (age={$age}s > " . self::PREFETCH_CACHE_TTL . 's)');
                return null;
            }
            $eventId = $entry['event_id'] ?? null;
            if (!is_string($eventId) || $eventId === '') {
                log::add('siaDC09', 'debug', '_resolveFrigateSnapshotUrl: event_id absent ou vide dans l\'entrée');
                return null;
            }
            $template = $eqLogic->getConfiguration('frigate_media_url_template', '');
            if (!is_string($template) || $template === '') {
                log::add('siaDC09', 'debug',
                    '_resolveFrigateSnapshotUrl: frigate_media_url_template non configuré');
                return null;
            }
            $mediaUrl = self::_buildFrigateMediaUrl($template, $eventId);
            log::add('siaDC09', 'debug', '_resolveFrigateSnapshotUrl: résolu media_url=' . json_encode($mediaUrl));
            return $mediaUrl;
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Résolution du snapshot Frigate échouée : ' . $e->getMessage());
            return null;
        }
    }

    /**
     * Story 14-3 sibling of _resolveFrigateSnapshotUrl(): same cache entry, same TTL/expiry
     * rule, same template-configured check — gates on the cache entry's 'clip_found' key
     * instead of 'found', and appends 'clip.mp4' instead of 'snapshot.jpg'. There is no
     * independent clip TTL: both outcomes are written by the same single prefetch_result
     * callback at the same moment (siaDC09::_handlePrefetchResult()), so they share one 'ts'.
     * A cache entry with 'clip_found' absent entirely (a stale pre-14-3 entry, or a
     * partially-written one) resolves to null via the same !empty() defensive read as
     * 'found' — never a crash. Never throws.
     */
    private function _resolveFrigateClipUrl(array $zoneEntry, ?array $cacheEntry = null): ?string {
        try {
            $eqLogicId = $zoneEntry['frigate_camera_eqlogic_id'] ?? null;
            if (empty($eqLogicId)) {
                log::add('siaDC09', 'debug',
                    '_resolveFrigateClipUrl: frigate_camera_eqlogic_id absent de zoneEntry');
                return null;
            }
            $eqLogic = $this->getEqLogic();
            if ($eqLogic === null) {
                log::add('siaDC09', 'debug', '_resolveFrigateClipUrl: getEqLogic() a retourné null');
                return null;
            }
            // $cacheEntry, when provided by the caller (execute()'s single shared read — code
            // review 2026-09-26, closes a TOCTOU between this and _resolveFrigateSnapshotUrl()'s
            // own read), is used as-is; otherwise this method reads the cache itself, same as
            // before (standalone/test callers).
            if ($cacheEntry !== null) {
                $entry = $cacheEntry;
            } else {
                $raw = $eqLogic->getCache('sia_prefetch_cache', []);
                log::add('siaDC09', 'debug', '_resolveFrigateClipUrl: getCache(sia_prefetch_cache) brut='
                    . json_encode($raw));
                $cache = is_string($raw) ? json_decode($raw, true) : $raw;
                if (!is_array($cache)) {
                    log::add('siaDC09', 'debug', '_resolveFrigateClipUrl: cache décodé non-array');
                    return null;
                }
                $entry = $cache[(int) $eqLogicId] ?? null;
            }
            log::add('siaDC09', 'debug', "_resolveFrigateClipUrl: eqLogicId=$eqLogicId entry="
                . json_encode($entry));
            if (!is_array($entry) || empty($entry['clip_found'])) {
                log::add('siaDC09', 'debug',
                    "_resolveFrigateClipUrl: pas d'entrée trouvée ou clip_found=false pour eqLogicId=$eqLogicId");
                return null;
            }
            $age = time() - (int) ($entry['ts'] ?? 0);
            if ($age > self::PREFETCH_CACHE_TTL) {
                log::add('siaDC09', 'debug',
                    "_resolveFrigateClipUrl: entrée expirée (age={$age}s > " . self::PREFETCH_CACHE_TTL . 's)');
                return null;
            }
            $eventId = $entry['event_id'] ?? null;
            if (!is_string($eventId) || $eventId === '') {
                log::add('siaDC09', 'debug', '_resolveFrigateClipUrl: event_id absent ou vide dans l\'entrée');
                return null;
            }
            $template = $eqLogic->getConfiguration('frigate_media_url_template', '');
            if (!is_string($template) || $template === '') {
                log::add('siaDC09', 'debug',
                    '_resolveFrigateClipUrl: frigate_media_url_template non configuré');
                return null;
            }
            $mediaUrl = self::_buildFrigateMediaUrl($template, $eventId, 'clip.mp4');
            log::add('siaDC09', 'debug', '_resolveFrigateClipUrl: résolu media_url=' . json_encode($mediaUrl));
            return $mediaUrl;
        } catch (\Throwable $e) {
            log::add('siaDC09', 'warning', 'Résolution du clip Frigate échouée : ' . $e->getMessage());
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
     * @param string $eventId Frigate event id, read from the sia_prefetch_cache entry (see
     *                        _resolveFrigateSnapshotUrl())
     * @param string $mediaFile Trailing path segment appended after the event id — defaults
     *                        to 'snapshot.jpg' so every pre-14-3 caller's behavior is unchanged;
     *                        Story 14-3's _resolveFrigateClipUrl() passes 'clip.mp4' instead.
     * @return string|null null when the template has no scheme or host — never throws
     */
    private static function _buildFrigateMediaUrl(
        string $template,
        string $eventId,
        string $mediaFile = 'snapshot.jpg'
    ): ?string {
        $parts = parse_url($template);
        if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
            return null;
        }

        $path = rtrim($parts['path'] ?? '', '/') . '/api/events/' . rawurlencode($eventId) . '/' . $mediaFile;

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
