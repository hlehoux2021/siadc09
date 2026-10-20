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
require_once __DIR__ . '/siaDC09Cmd.class.php';

class siaDC09 extends eqLogic {

    /** Notification target kinds, stored in `sia_notify_kind` at wizard step 4. */
    const NOTIFY_KIND_CMD = 'cmd';
    const NOTIFY_KIND_INTERNAL = 'internal';

    /** AES-128/192/256 key lengths in hex digits (DC-09 § 5.4). */
    const ENCRYPTION_KEY_HEX_LENGTHS = [32, 48, 64];

    /**
     * Periodic-frame settings (ADR-22, Story 17.1). Mirrored from
     * resources/siadc09d/presets.py (SupervisionFormat, RP_INTERVAL_MIN_S/MAX_S) —
     * deamon_info() Guard 3e and CSRPreset.__post_init__ must refuse the same
     * combinations, or Jeedom's auto-restart loops on a daemon that exits at start.
     */
    const SUPERVISION_FORMATS = ['none', 'sia-dcs', 'null'];
    const SUPERVISION_FORMAT_DEFAULT = 'sia-dcs';
    const RP_INTERVAL_MIN_S = 60;
    const RP_INTERVAL_MAX_S = 86400;
    const RP_INTERVAL_DEFAULT_S = 60;

    /** Sender-side CRC formats: 'bin' removed on 2026-10-17 (Story 17.1, ADR-06 note). */
    const SENDER_CRC_FORMATS = ['hex'];

    /** CSR profile file (ADR-22) — read PHP-side only, never by the daemon. */
    const CSR_PROFILES_FILE = __DIR__ . '/../config/csr_presets.json';
    const CSR_PROFILES_SCHEMA_VERSION = 1;

    /**
     * Jeedom internal actions the plugin knows how to run as a critical alert, stored in
     * `sia_notify_internal`. Adding one means: an <option> at step 4, a case in
     * _runNotifyInternal() and, if it needs a target, a config key + a check in
     * _hasNotifyTarget().
     */
    const NOTIFY_INTERNAL_MESSAGE = 'message';
    const NOTIFY_INTERNAL_SCENARIO = 'scenario';

    /**
     * ADR-17 Amendment 4 (Story 14-4): the "nothing found" rank a prefetch_result
     * callback's 'rank' field defaults to when absent (a pre-14-4 payload shape, or a
     * malformed one) — mirrors resources/siadc09d/frigate_prefetch.py's RANK_NONE.
     */
    private const PREFETCH_RANK_NONE = 4;

    // Best possible rank (a confirmed person event) — the lower clamp bound for an
    // incoming 'rank' field (code review 2026-09-27: a non-numeric rank casts to 0 via
    // (int), which would otherwise always win the replace check regardless of priority).
    private const PREFETCH_RANK_PERSON = 1;

    private static function getPython3(): string {
        if (method_exists('system', 'getCmdPython3')) {
            return system::getCmdPython3(__CLASS__);
        }
        return 'python3 ';
    }

    private static function _getAutoEquipmentSafe(): ?self {
        $eqLogics = eqLogic::byType(__CLASS__);
        if (!is_array($eqLogics) || count($eqLogics) === 0) {
            return null;
        }
        if (count($eqLogics) > 1) {
            log::add(__CLASS__, 'error', __('Plusieurs équipements détectés — un seul attendu', __FILE__));
        }
        return $eqLogics[0];
    }

    private static function _getAutoEquipment(): self {
        $eqLogics = eqLogic::byType(__CLASS__);
        if (is_array($eqLogics) && count($eqLogics) > 0) {
            if (count($eqLogics) > 1) {
                log::add(__CLASS__, 'error', __('Plusieurs équipements détectés — un seul attendu', __FILE__));
            }
            return $eqLogics[0];
        }
        log::add(__CLASS__, 'warning', __('Équipement absent — création automatique', __FILE__));
        $eq = new self();
        $eq->setName('Télésurveillance');
        $eq->setEqType_name(__CLASS__);
        $eq->setIsEnable(1);
        $eq->setIsVisible(1);
        $eq->setObject_id(null);
        $eq->save();
        return $eq;
    }

    /**
     * Bootstrap entry point for the equipment page — creates the auto-equipment
     * on first access so the wizard is reachable with the daemon stopped.
     * deamon_start() cannot be relied on: it throws while launchable = 'nok'
     * (wizard incomplete), which would leave the equipment forever uncreated.
     */
    public static function ensureAutoEquipment(): self {
        return self::_getAutoEquipment();
    }

    public static function deamon_info(): array {
        $return = [
            'log' => __CLASS__ . '_daemon',
            'state' => 'nok',
            'launchable' => 'ok',
            'auto' => config::byKey('autoStartDeamon', __CLASS__, 1),
        ];

        $pidFile = jeedom::getTmpFolder(__CLASS__) . '/daemon.pid';
        if (file_exists($pidFile)) {
            $pid = intval(trim(file_get_contents($pidFile)));
            if ($pid > 0 && @posix_getsid($pid)) {
                $return['state'] = 'ok';
            } else {
                shell_exec(system::getCmdSudo() . 'rm -rf ' . $pidFile . ' 2>&1 > /dev/null');
            }
        }

        // Guard 1 — equipment exists
        $eqLogic = self::_getAutoEquipmentSafe();
        if (!$eqLogic) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __("L'équipement n'existe pas — activez le plugin.", __FILE__);
            return $return;
        }

        // Guard 2 — wizard complete
        if ((int) $eqLogic->getConfiguration('sia_wizard_step', 0) < 4) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "L'assistant de configuration n'est pas terminé — complétez les 4 étapes.", __FILE__
            );
            return $return;
        }

        // Guard 3 — CSR IP
        $csrIp = $eqLogic->getConfiguration('csr_ip');
        if (empty($csrIp) || $csrIp === 'TBD') {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Adresse IP de la centrale non configurée (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }

        // Guard 3b — CSR port
        if ((int) $eqLogic->getConfiguration('csr_port', 0) <= 0) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Port de la centrale non configuré (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }

        // Guard 3c — transport protocol
        if (!in_array($eqLogic->getConfiguration('transport', ''), ['udp', 'tcp'], true)) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Protocole de transport non configuré (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }

        // Guard 3c' — sender-side CRC format (Story 17.1): only 'hex' since 'bin' was
        // removed. The wizard has no crc_format field, so a different value can only
        // come from a manual DB edit; refusing it here keeps the daemon's own
        // refusal from triggering Jeedom's restart loop.
        if (!in_array($eqLogic->getConfiguration('crc_format', 'hex'), self::SENDER_CRC_FORMATS, true)) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Format CRC non pris en charge (seul « hex » est accepté) — réenregistrez l'équipement.", __FILE__
            );
            return $return;
        }

        $supervisionFormat = $eqLogic->getConfiguration('supervision_format', self::SUPERVISION_FORMAT_DEFAULT);

        // Guard 3d — supervision interval must be positive. Default 60 matches the
        // system-wide default (deamon_start(), siadc09d.py's --supervision-interval),
        // so leaving the wizard field blank (trusting its "60" placeholder, which sets
        // no actual value) does not incorrectly block the daemon from launching.
        // Irrelevant when supervision_format is 'none' (no supervision frame sent).
        if ($supervisionFormat !== 'none'
            && (int) $eqLogic->getConfiguration('supervision_interval', 60) <= 0) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Intervalle de supervision invalide (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }

        // Guard 3e — periodic-frame combination (Story 17.1, ADR-22). Same three rules
        // and bounds as CSRPreset.__post_init__ (resources/siadc09d/presets.py). The RP
        // range is checked only when RP is enabled: a stored but unused rp_interval
        // must not block the daemon.
        $periodicFrameError = self::periodicFrameConfigError(
            (string) $supervisionFormat,
            (bool) $eqLogic->getConfiguration('rp_enabled', 0),
            (int) $eqLogic->getConfiguration('rp_interval', self::RP_INTERVAL_DEFAULT_S)
        );
        if ($periodicFrameError !== null) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = $periodicFrameError;
            return $return;
        }

        // Guard 4 — account number format (3–16 hex chars per SIA DC-09 § 5.5.1.3)
        $account = $eqLogic->getConfiguration('account_number');
        if (empty($account)) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Numéro de compte non configuré (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }
        if (!preg_match('/^[0-9A-Fa-f]{3,16}$/', $account)) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Numéro de compte invalide — doit contenir 3 à 16 caractères hexadécimaux (étape 1 de l'assistant).", __FILE__
            );
            return $return;
        }

        // Guard 5 — encryption key when encryption enabled: present and 32/48/64 hex digits
        // (story 1-5 AC5). The message never echoes the key.
        if ($eqLogic->getConfiguration('encryption_enabled')) {
            $encKey = trim((string) $eqLogic->getConfiguration('encryption_key', ''));
            if ($encKey === '') {
                $return['launchable'] = 'nok';
                $return['launchable_message'] = __(
                    "Clé de chiffrement manquante (étape 1 de l'assistant).", __FILE__
                );
                return $return;
            }
            if (!self::isValidEncryptionKey($encKey)) {
                $return['launchable'] = 'nok';
                $return['launchable_message'] = __(
                    "Clé de chiffrement invalide — 32, 48 ou 64 caractères hexadécimaux attendus (étape 1 de l'assistant).",
                    __FILE__
                );
                return $return;
            }
        }

        // Guard 6 — notification target (equipment command or Jeedom internal action)
        if (!self::_hasNotifyTarget($eqLogic)) {
            $return['launchable'] = 'nok';
            $return['launchable_message'] = __(
                "Notification critique non configurée (étape 4 de l'assistant).", __FILE__
            );
            return $return;
        }

        return $return;
    }

    public static function deamon_start(): bool {
        self::deamon_stop();
        $deamonInfo = self::deamon_info();
        if ($deamonInfo['launchable'] !== 'ok') {
            throw new Exception(__('Veuillez vérifier la configuration', __FILE__));
        }

        $eqLogic = self::_getAutoEquipment();

        $path = realpath(dirname(__FILE__) . '/../../resources/siadc09d');
        $socketport = (int) config::byKey('socketport', __CLASS__, 55009);

        $cmd = self::getPython3() . $path . '/siadc09d.py';
        $cmd .= ' --loglevel ' . log::convertLogLevel(log::getLogLevel(__CLASS__));
        $cmd .= ' --socketport ' . $socketport;
        $cmd .= ' --callback ' . network::getNetworkAccess('internal', 'http:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php';
        $cmd .= ' --apikey ' . jeedom::getApiKey(__CLASS__);
        $cmd .= ' --pid ' . jeedom::getTmpFolder(__CLASS__) . '/daemon.pid';

        $cmd .= ' --host ' . escapeshellarg($eqLogic->getConfiguration('csr_ip', ''));
        $cmd .= ' --port ' . (int) $eqLogic->getConfiguration('csr_port', 0);
        $cmd .= ' --transport ' . escapeshellarg($eqLogic->getConfiguration('transport', 'udp'));
        $cmd .= ' --account ' . escapeshellarg($eqLogic->getConfiguration('account_number', ''));
        $cmd .= ' --crc-format ' . escapeshellarg($eqLogic->getConfiguration('crc_format', 'hex'));

        $receiverPrefix = $eqLogic->getConfiguration('receiver_prefix', '');
        if ($receiverPrefix !== '') {
            $cmd .= ' --receiver-prefix ' . escapeshellarg($receiverPrefix);
        }

        $accountPrefix = $eqLogic->getConfiguration('account_prefix', '');
        if ($accountPrefix !== '') {
            $cmd .= ' --account-prefix ' . escapeshellarg($accountPrefix);
        }

        if ((bool) $eqLogic->getConfiguration('encryption_enabled', false)) {
            $encKey = $eqLogic->getConfiguration('encryption_key', '');
            $cmd .= ' --encryption-enabled';
            if ($encKey !== '') {
                $cmd .= ' --encryption-key ' . escapeshellarg($encKey);
            }
        }

        $supervisionInterval = (int) $eqLogic->getConfiguration('supervision_interval', 60);
        if ($supervisionInterval > 0) {
            $cmd .= ' --supervision-interval ' . $supervisionInterval;
        }

        // Story 17.1 (ADR-22): resolved periodic-frame values only — never a profile name.
        $cmd .= ' --supervision-format ' . escapeshellarg(
            (string) $eqLogic->getConfiguration('supervision_format', self::SUPERVISION_FORMAT_DEFAULT)
        );
        if ((bool) $eqLogic->getConfiguration('rp_enabled', 0)) {
            $cmd .= ' --rp-enabled';
            $cmd .= ' --rp-interval ' . (int) $eqLogic->getConfiguration('rp_interval', self::RP_INTERVAL_DEFAULT_S);
        }

        $retryCount = (int) $eqLogic->getConfiguration('retry_count', 6);
        $cmd .= ' --retry-count ' . $retryCount;

        $reconnectDelay = (int) $eqLogic->getConfiguration('reconnect_delay', 30);
        $cmd .= ' --reconnect-delay ' . $reconnectDelay;

        $notifyCmdId = (int) $eqLogic->getConfiguration('sia_notify_cmd_id', 0);
        if ($notifyCmdId > 0) {
            $cmd .= ' --notify-cmd-id ' . $notifyCmdId;
        }

        $cmdLog = preg_replace('/--encryption-key\s+\S+/', '--encryption-key [REDACTED]', $cmd);
        log::add(__CLASS__, 'info', __('Lancement démon', __FILE__) . ': ' . $cmdLog);
        exec($cmd . ' >> ' . log::getPathToLog(__CLASS__ . '_daemon') . ' 2>&1 &');

        $i = 0;
        while ($i < 10) {
            $deamonInfo = self::deamon_info();
            if ($deamonInfo['state'] === 'ok') {
                break;
            }
            sleep(1);
            $i++;
        }
        if ($i >= 10) {
            log::add(__CLASS__, 'error', __('Impossible de lancer le démon', __FILE__), 'unableStartDeamon');
            return false;
        }
        message::removeAll(__CLASS__, 'unableStartDeamon');
        return true;
    }

    public static function deamon_stop(): void {
        $pidFile = jeedom::getTmpFolder(__CLASS__) . '/daemon.pid';
        if (file_exists($pidFile)) {
            $pid = intval(trim(file_get_contents($pidFile)));
            system::kill($pid);
        }
        sleep(1);
        system::kill('siadc09d.py');
        sleep(1);
    }

    public static function cron5(): void {
        $eqLogic = self::_getAutoEquipmentSafe();

        if (!$eqLogic || !$eqLogic->getIsEnable()) {
            return;
        }

        if (self::deamon_info()['state'] === 'ok') {
            self::_checkSupervisionFreshness($eqLogic);
        }
    }

    private static function _checkSupervisionFreshness($eqLogic): void {
        $staleThreshold = self::_shortestPeriodicIntervalOf($eqLogic) * 3;
        $alertRateLimit = 30 * 60;

        $stateCmd = $eqLogic->getCmd('info', 'supervision_state');
        if (!$stateCmd) {
            return;
        }

        $collectDate = $stateCmd->getCollectDate();
        if (empty($collectDate)) {
            return;
        }

        $ts = strtotime($collectDate);
        if ($ts === false) {
            return;
        }

        $staleSince = time() - $ts;

        if ($staleSince <= $staleThreshold) {
            if (config::byKey('_freshness_alert_ts', __CLASS__, 0)) {
                config::save('_freshness_alert_ts', 0, __CLASS__);
            }
            return;
        }

        $lastAlertTs = (int) config::byKey('_freshness_alert_ts', __CLASS__, 0);
        if ((time() - $lastAlertTs) < $alertRateLimit) {
            return;
        }

        $msg = sprintf(
            'ALERTE siaDC09 : Le démon est actif mais ne répond plus depuis %ds. '
            . 'La supervision vers la centrale est interrompue. '
            . 'Le système de télésurveillance est potentiellement compromis.',
            $staleSince
        );

        log::add(__CLASS__, 'error', $msg);
        message::add(__CLASS__, $msg);

        // messageCenterDone: the line above already posted $msg, so the `message` internal
        // action must not post it a second time.
        self::_runNotifyTarget($eqLogic, 'siaDC09 — Démon bloqué', $msg, true);

        config::save('_freshness_alert_ts', time(), __CLASS__);
    }

    /**
     * True when $key is an AES key the daemon accepts: 32, 48 or 64 hex digits once trimmed
     * (story 1-5 AC5). Same rule as the wizard (desktop/js/siaDC09.js) and parse_hex_key().
     */
    public static function isValidEncryptionKey(?string $key): bool {
        $key = trim($key ?? '');
        return ctype_xdigit($key) && in_array(strlen($key), self::ENCRYPTION_KEY_HEX_LENGTHS, true);
    }

    /**
     * Shortest active periodic interval in seconds (Story 17.3, ADR-08 amended).
     *
     * Staleness is 3 x this value. Supervision counts only when its format is not 'none';
     * RP counts only when enabled. Falls back to 60 when neither is active (cannot happen
     * for a launchable daemon, Guard 3e).
     */
    public static function shortestPeriodicInterval(string $format, int $supervisionInterval, bool $rpEnabled, int $rpInterval): int {
        $intervals = [];
        if ($format !== 'none' && $supervisionInterval > 0) {
            $intervals[] = $supervisionInterval;
        }
        if ($rpEnabled && $rpInterval > 0) {
            $intervals[] = $rpInterval;
        }
        return $intervals ? min($intervals) : 60;
    }

    private static function _shortestPeriodicIntervalOf($eqLogic): int {
        return self::shortestPeriodicInterval(
            (string) $eqLogic->getConfiguration('supervision_format', self::SUPERVISION_FORMAT_DEFAULT),
            (int) $eqLogic->getConfiguration('supervision_interval', 60),
            (bool) $eqLogic->getConfiguration('rp_enabled', 0),
            (int) $eqLogic->getConfiguration('rp_interval', self::RP_INTERVAL_DEFAULT_S)
        );
    }

    /**
     * deamon_info() Guard 3e (Story 17.1, ADR-22): why a periodic-frame combination is
     * refused, or null when it is valid. Same three rules and bounds as
     * CSRPreset.__post_init__ in resources/siadc09d/presets.py:
     * - an unknown supervision format;
     * - supervision 'none' with RP off (no periodic frame at all);
     * - RP on with an interval outside RP_INTERVAL_MIN_S..RP_INTERVAL_MAX_S (inclusive).
     * The RP range is not checked when RP is off: a stored but unused rp_interval must not
     * block the daemon.
     */
    public static function periodicFrameConfigError(string $format, bool $rpEnabled, int $rpInterval): ?string {
        if (!in_array($format, self::SUPERVISION_FORMATS, true)) {
            return __("Format de supervision inconnu (étape 1 de l'assistant, Options avancées).", __FILE__);
        }
        if ($format === 'none' && !$rpEnabled) {
            return __(
                "Aucune trame périodique active : supervision « none » et test cyclique RP désactivé (étape 1 de l'assistant, Options avancées).",
                __FILE__
            );
        }
        if ($rpEnabled && ($rpInterval < self::RP_INTERVAL_MIN_S || $rpInterval > self::RP_INTERVAL_MAX_S)) {
            return __(
                "Intervalle du test cyclique RP invalide — entre 60 et 86400 secondes (étape 1 de l'assistant, Options avancées).",
                __FILE__
            );
        }
        return null;
    }

    /**
     * CSR behaviour profiles from core/config/csr_presets.json (ADR-22, Story 17.1).
     *
     * Each profile maps a name to a French `label` plus the equipment config keys it sets
     * (supervision_format, supervision_interval, rp_enabled, rp_interval). The file is read
     * PHP-side only: the daemon receives resolved values, never a profile name.
     *
     * Callers: the wizard step 1 profile selector (desktop/php/siaDC09.php), which also hands the
     * profiles to JS (Story 17.4). A preset may omit a key (e.g. supervision_interval); the wizard
     * then leaves that field untouched.
     *
     * @return array<string, array<string, mixed>> The `profiles` object, or [] when the file
     *         is missing, unreadable, not valid JSON or not schema_version 1 (logged at
     *         `error`; never throws).
     */
    public static function getCsrProfiles(): array {
        $path = self::CSR_PROFILES_FILE;
        $raw = is_readable($path) ? @file_get_contents($path) : false;
        if ($raw === false) {
            log::add(__CLASS__, 'error', __('Fichier des profils de télésurveillance illisible', __FILE__) . ' : ' . $path);
            return [];
        }
        $data = json_decode($raw, true);
        if (!is_array($data)
            || ($data['schema_version'] ?? null) !== self::CSR_PROFILES_SCHEMA_VERSION
            || !is_array($data['profiles'] ?? null)) {
            log::add(__CLASS__, 'error', __('Fichier des profils de télésurveillance invalide (JSON ou schema_version)', __FILE__) . ' : ' . $path);
            return [];
        }
        return $data['profiles'];
    }

    /**
     * Notification target kind chosen at wizard step 4 (self::NOTIFY_KIND_*). Installations
     * configured before the internal-action option existed carry no `sia_notify_kind`, so an
     * empty value means "an equipment command" and their `sia_notify_cmd_id` keeps working.
     */
    private static function _notifyKind(self $eqLogic): string {
        return $eqLogic->getConfiguration('sia_notify_kind', '') === self::NOTIFY_KIND_INTERNAL
            ? self::NOTIFY_KIND_INTERNAL
            : self::NOTIFY_KIND_CMD;
    }

    /**
     * True when step 4 left behind something able to raise a critical alert. Guards the daemon
     * start: an installation with no reachable target would fail silently on the first alarm.
     */
    private static function _hasNotifyTarget(self $eqLogic): bool {
        if (self::_notifyKind($eqLogic) === self::NOTIFY_KIND_CMD) {
            return ((int) $eqLogic->getConfiguration('sia_notify_cmd_id', 0)) > 0;
        }

        switch ($eqLogic->getConfiguration('sia_notify_internal', '')) {
            case self::NOTIFY_INTERNAL_MESSAGE:
                // The message centre is always available — nothing else to configure.
                return true;
            case self::NOTIFY_INTERNAL_SCENARIO:
                return ((int) $eqLogic->getConfiguration('sia_notify_scenario_id', 0)) > 0;
            default:
                return false;
        }
    }

    /**
     * Single entry point for every critical notification: routes to the equipment command or to
     * the Jeedom internal action selected at step 4. Never throws — a notification that fails
     * must not abort its caller (supervision check, daemon message handler).
     *
     * @param bool $messageCenterDone the caller already posted $message to the message centre,
     *                                so the `message` internal action would only duplicate it.
     */
    private static function _runNotifyTarget(
        self $eqLogic, string $title, string $message, bool $messageCenterDone = false
    ): void {
        if (self::_notifyKind($eqLogic) === self::NOTIFY_KIND_INTERNAL) {
            self::_runNotifyInternal($eqLogic, $title, $message, $messageCenterDone);
            return;
        }

        $notifyCmdId = (int) $eqLogic->getConfiguration('sia_notify_cmd_id', 0);
        $notifyCmd = $notifyCmdId > 0 ? cmd::byId($notifyCmdId) : null;
        if (!is_object($notifyCmd)) {
            log::add(__CLASS__, 'warning',
                __('Commande notification non configurée — alerte ignorée', __FILE__)
            );
            return;
        }

        try {
            $notifyCmd->execCmd(['title' => $title, 'message' => $message]);
        } catch (Exception $e) {
            log::add(__CLASS__, 'error',
                __('Impossible d\'envoyer la notification : ', __FILE__) . $e->getMessage()
            );
        }
    }

    /**
     * Runs the Jeedom internal action selected at step 4. A keyword such as `message` or
     * `scenario` is a scenario-expression action, not a cmd id, so cmd::byId() cannot execute
     * it — each keyword is dispatched to its own core API.
     */
    private static function _runNotifyInternal(
        self $eqLogic, string $title, string $message, bool $messageCenterDone
    ): void {
        $internal = (string) $eqLogic->getConfiguration('sia_notify_internal', '');
        $text = $title . ' : ' . $message;

        try {
            switch ($internal) {
                case self::NOTIFY_INTERNAL_MESSAGE:
                    if (!$messageCenterDone) {
                        message::add(__CLASS__, $text);
                    }
                    break;

                case self::NOTIFY_INTERNAL_SCENARIO:
                    $scenarioId = (int) $eqLogic->getConfiguration('sia_notify_scenario_id', 0);
                    $scenario = $scenarioId > 0 ? scenario::byId($scenarioId) : null;
                    if (!is_object($scenario)) {
                        log::add(__CLASS__, 'warning',
                            __('Scénario de notification introuvable — alerte ignorée', __FILE__)
                        );
                        break;
                    }
                    $scenario->launch(__CLASS__, $text);
                    break;

                default:
                    log::add(__CLASS__, 'warning',
                        __('Action interne de notification inconnue — alerte ignorée : ', __FILE__) . $internal
                    );
            }
        } catch (Exception $e) {
            log::add(__CLASS__, 'error',
                __('Impossible d\'exécuter l\'action interne de notification : ', __FILE__) . $e->getMessage()
            );
        }
    }

    public static function isConnect(): bool {
        $info = self::deamon_info();
        return ($info['launchable'] ?? 'nok') === 'ok'
            && ($info['state'] ?? 'nok') === 'ok';
    }

    public static function sendToDaemon(array $params): void {
        $socketport = (int) config::byKey('socketport', __CLASS__, 55009);
        log::add(__CLASS__, 'debug', 'sendToDaemon: ' . json_encode($params));
        $params['apikey'] = jeedom::getApiKey(__CLASS__);
        $payLoad = json_encode($params);
        $socket = @socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
        if ($socket === false) {
            log::add(__CLASS__, 'error', 'sendToDaemon: socket_create failed');
            return;
        }
        if (@socket_connect($socket, '127.0.0.1', $socketport) === false) {
            log::add(__CLASS__, 'error', 'sendToDaemon: connexion au démon impossible (port ' . $socketport . ')');
            @socket_close($socket);
            return;
        }
        @socket_write($socket, $payLoad, strlen($payLoad));
        @socket_close($socket);
    }

    public static function message($message): void {
        $eqLogic = self::_getAutoEquipmentSafe();
        if (!$eqLogic) {
            log::add(__CLASS__, 'warning',
                __('Message daemon reçu mais équipement absent — ignoré jusqu\'à réactivation du plugin.', __FILE__)
            );
            return;
        }

        switch ($message['type'] ?? '') {
            case 'info_update':
                self::_handleInfoUpdate($eqLogic, $message);
                break;

            case 'prefetch_result':
                self::_handlePrefetchResult($eqLogic, $message);
                break;

            case 'message_center':
                // No null guard — daemon is sole caller, always sends well-formed payloads
                message::add(
                    __CLASS__,
                    $message['message'],
                    '',
                    $message['logical_id']
                );
                break;

            case 'notify':
                self::_runNotifyTarget($eqLogic, $message['title'], $message['message']);
                break;

            case 'error_update':
                // Fix #8: config::byKey() may return array (Jeedom auto-decodes JSON)
                $raw = config::byKey('sia_last_errors', __CLASS__, '[]');
                $errors = is_array($raw) ? $raw : (json_decode($raw, true) ?: []);
                if (!empty($message['resolve_t1'])) {
                    $errors = array_values(array_filter($errors, fn($e) =>
                        !in_array(strtolower($e['code'] ?? ''), ['supervision_timeout', 'supervision_nak'])
                    ));
                } elseif (isset($message['code'])) {
                    array_unshift($errors, [
                        'code'      => $message['code'],
                        'message'   => $message['message'],
                        'timestamp' => $message['timestamp'],
                        'context'   => $message['context'] ?? null,
                        'count'     => $message['count'] ?? 1,
                    ]);
                }
                $errors = array_slice($errors, 0, 10);
                config::save('sia_last_errors', json_encode($errors), __CLASS__);
                break;

            case 'message_trace':
                // Fix #8: config::byKey() may return array (Jeedom auto-decodes JSON)
                $raw = config::byKey('sia_last_messages', __CLASS__, '[]');
                $messages = is_array($raw) ? $raw : (json_decode($raw, true) ?: []);
                $dialog = $message['dialog'] ?? null;
                if (!is_array($dialog)) {
                    break;
                }
                if (($dialog['dialog_type'] ?? '') === 'supervision' && !empty($dialog['routine'])) {
                    $idx = null;
                    foreach ($messages as $i => $entry) {
                        if (!empty($entry['routine'])) {
                            $idx = $i;
                            break;
                        }
                    }
                    if ($idx !== null) {
                        $messages[$idx] = $dialog;
                    } else {
                        array_unshift($messages, $dialog);
                        $messages = array_slice($messages, 0, 50);
                    }
                } else {
                    array_unshift($messages, $dialog);
                    $messages = array_slice($messages, 0, 50);
                }
                config::save('sia_last_messages', json_encode($messages), __CLASS__);
                break;

            default:
                log::add(__CLASS__, 'warning',
                    'Message daemon de type inconnu ignoré : ' . ($message['type'] ?? '<null>')
                );
                break;
        }
    }

    private static function _handleInfoUpdate($eqLogic, array $data): void {
        $map = [
            'supervision_state' => 'supervision_state',
            'supervision_label' => 'supervision_label',
            'event_state'       => 'event_state',
            'event_label'       => 'event_label',
        ];
        foreach ($map as $key => $logicalId) {
            if (isset($data[$key])) {
                $eqLogic->checkAndUpdateCmd($logicalId, $data[$key]);
            }
        }
    }

    /**
     * ADR-17 Amendment 3 (Option D), extended by Amendment 4 (Story 14-4): stores the
     * daemon's Frigate REST prefetch outcome into a per-camera cache entry, keyed by
     * camera_eqlogic_id, that burglarAlarm's execute() reads synchronously and locally
     * (siaDC09Cmd::_resolveFrigateSnapshotUrl()/_resolveFrigateClipUrl()). Replaces the
     * existing entry only per _prefetchResultShouldReplace()'s run_id/rank monotonic rule
     * — never merges with a previous entry (still a fresh array literal), but no longer
     * unconditionally overwrites on every message (superseded 14-2 AC5: a stale hit is
     * now cleared by the placeholder entry siaDC09Cmd::execute()'s prefetchEvent case
     * writes before triggering the run, not by "every callback always wins").
     */
    private static function _handlePrefetchResult($eqLogic, array $data): void {
        try {
            log::add(__CLASS__, 'debug', '_handlePrefetchResult: reçu ' . json_encode($data));
            $cameraEqLogicId = $data['camera_eqlogic_id'] ?? null;
            if ($cameraEqLogicId === null) {
                log::add(__CLASS__, 'warning', '_handlePrefetchResult: camera_eqlogic_id absent — message ignoré');
                return;
            }
            $camKey = (int) $cameraEqLogicId;

            $raw = $eqLogic->getCache('sia_prefetch_cache', []);
            $cache = is_string($raw) ? json_decode($raw, true) : $raw;
            if (!is_array($cache)) {
                $cache = [];
            }

            $incomingRunId = (string) ($data['run_id'] ?? '');
            // Clamped to the valid [PREFETCH_RANK_PERSON, PREFETCH_RANK_NONE] range (code
            // review 2026-09-27): a malformed, non-numeric 'rank' would otherwise cast to 0
            // via (int), beating every real rank and always winning the replace check below.
            $incomingRank = max(
                self::PREFETCH_RANK_PERSON,
                min(self::PREFETCH_RANK_NONE, (int) ($data['rank'] ?? self::PREFETCH_RANK_NONE))
            );
            $incomingClipFound = !empty($data['clip_found']);

            $existing = $cache[$camKey] ?? null;
            if (is_array($existing)
                && !self::_prefetchResultShouldReplace($existing, $incomingRunId, $incomingRank, $incomingClipFound)
            ) {
                log::add(__CLASS__, 'debug', '_handlePrefetchResult: résultat ignoré (ni plus récent, ni meilleur) '
                    . 'pour eqLogicId=' . $camKey . ' -> ' . json_encode($data));
                return;
            }

            $cache[$camKey] = [
                'found'      => !empty($data['found']),
                'event_id'   => $data['event_id'] ?? null,
                'clip_found' => !empty($data['clip_found']),
                'rank'       => $incomingRank,
                'run_id'     => $incomingRunId,
                'ts'         => time(),
            ];
            log::add(__CLASS__, 'debug', '_handlePrefetchResult: sia_prefetch_cache mis à jour pour eqLogicId='
                . $camKey . ' -> ' . json_encode($cache[$camKey]));

            $eqLogic->setCache('sia_prefetch_cache', $cache);
        } catch (\Throwable $e) {
            log::add(__CLASS__, 'warning', 'Traitement du résultat de prefetch Frigate échoué : ' . $e->getMessage());
        }
    }

    /**
     * ADR-17 Amendment 4, Decision 5 — the monotonic cache-replace rule:
     * - a numerically greater run_id than the one stored (or no usable stored run_id —
     *   a legacy pre-14-4 entry) always replaces, whatever the rank;
     * - the same run_id with a smaller (better) rank replaces;
     * - the same run_id and rank, with the stored clip_found false and the incoming one
     *   true, replaces (the clip-ready upgrade);
     * - anything else (an older run, a same-run worse rank, a same-run/rank/clip-state
     *   duplicate) is ignored.
     */
    private static function _prefetchResultShouldReplace(
        array $existing, string $incomingRunId, int $incomingRank, bool $incomingClipFound
    ): bool {
        $storedRunId = isset($existing['run_id']) ? (string) $existing['run_id'] : '';
        if ($storedRunId === '') {
            return true;
        }
        if ((float) $incomingRunId !== (float) $storedRunId) {
            return (float) $incomingRunId > (float) $storedRunId;
        }

        $storedRank = isset($existing['rank']) ? (int) $existing['rank'] : self::PREFETCH_RANK_NONE;
        if ($incomingRank !== $storedRank) {
            return $incomingRank < $storedRank;
        }

        return $incomingClipFound && empty($existing['clip_found']);
    }

    public function toHtml($_version = 'dashboard') {
        $replace = $this->preToHtml($_version);
        if (!is_array($replace)) {
            return $replace;
        }
        $_version = jeedom::versionAlias($_version);

        $supervisionStateCmd = $this->getCmd('info', 'supervision_state');
        $supervisionLabelCmd = $this->getCmd('info', 'supervision_label');
        $eventLabelCmd       = $this->getCmd('info', 'event_label');

        // Read via execCmd(), NOT getValue(): for non-historized 'info' cmds, cmd::event()
        // (invoked by the daemon's checkAndUpdateCmd on every push) only writes to the cmd
        // cache (setCache()) — it never touches the cmd table's own 'value' column that
        // getValue() reads, which stays frozen at whatever it held at cmd creation.
        // execCmd() reads the cache that event() actually updates, i.e. the live value.
        // 10-3 Task 3/AC4 reverted this to getValue() on the (incorrect) assumption that
        // getValue() reflects what checkAndUpdateCmd wrote — verified against Jeedom core
        // (cmd.class.php) that it does not, for this cmd type; reverted back to execCmd().
        $stateRaw   = ($supervisionStateCmd !== null) ? $supervisionStateCmd->execCmd() : null;
        $stateValue = ($stateRaw === null || $stateRaw === '') ? null : intval($stateRaw);
        $labelValue = ($supervisionLabelCmd !== null) ? $supervisionLabelCmd->execCmd() : '';
        $eventValue = ($eventLabelCmd !== null)       ? $eventLabelCmd->execCmd()       : '';

        // Command ids for the client-side live-refresh callbacks in the template.
        // The tile overrides toHtml() and so bypasses the stock per-command widgets;
        // its inline script registers jeedom.cmd.addUpdateFunction(<id>, ...) for each
        // of these, so Jeedom's poll loop (cmd::update -> refreshValue) drives live
        // updates without a page reload (story 10.3).
        $replace['#supervision_state_id#'] = ($supervisionStateCmd !== null) ? $supervisionStateCmd->getId() : '';
        $replace['#supervision_label_id#'] = ($supervisionLabelCmd !== null) ? $supervisionLabelCmd->getId() : '';
        $replace['#event_label_id#']       = ($eventLabelCmd !== null)       ? $eventLabelCmd->getId()       : '';

        if ($stateValue === null) {
            $replace['#badge_class#']       = 'text-muted';
            $replace['#supervision_label#'] = htmlspecialchars('—');
        } elseif ($stateValue === 2) {
            $replace['#badge_class#']       = 'text-success';
            $replace['#supervision_label#'] = htmlspecialchars($labelValue ?: '—');
        } elseif ($stateValue === 1) {
            $replace['#badge_class#']       = 'text-warning';
            $replace['#supervision_label#'] = htmlspecialchars($labelValue ?: '—');
        } else {
            $replace['#badge_class#']       = 'text-danger';
            $replace['#supervision_label#'] = htmlspecialchars($labelValue ?: '—');
        }

        $replace['#event_label#'] = htmlspecialchars(
            $eventValue ?: __('Aucun événement depuis le démarrage', __FILE__)
        );

        // Shortest active periodic interval; the templates multiply it by 3 (ADR-08).
        $replace['#supervision_interval#']    = self::_shortestPeriodicIntervalOf($this);
        $replace['#stale_label#']             = trim(json_encode(__('Données non disponibles', __FILE__)), '"');
        $replace['#stale_tooltip_prefix#']    = trim(json_encode(__('Dernière mise à jour il y a', __FILE__)), '"');
        $replace['#calledFrom#']              = 'eqLogic';

        return $this->postToHtml(
            $_version,
            template_replace($replace, getTemplate('core', $_version, 'siaDC09', 'siaDC09'))
        );
    }

    public function postSave(): void {
        $actionCmds = [
            'burglarAlarm'  => ['name' => __('Alarme intrusion', __FILE__), 'subType' => 'message'],
            'fireAlarm'     => ['name' => __('Alarme incendie', __FILE__), 'subType' => 'message'],
            'panicAlarm'    => ['name' => __('Alarme panique', __FILE__),  'subType' => 'message'],
            // Story 13-1 — DC-03 addresses BC/OP by user number, never by zone (ADR-18): no
            // #zone# tag is needed, so subType 'other' is used — neither command needs a Titre.
            'disarm'         => ['name' => __('Désarmement', __FILE__),            'subType' => 'other'],
            'alarmReset'     => ['name' => __('Réinitialisation alarme', __FILE__), 'subType' => 'other'],
            // Story 13-4 — DC-03 addresses CL by user number too (ADR-18): no #zone# tag
            // needed, same subType 'other' as disarm/alarmReset.
            'arm'            => ['name' => __('Armement', __FILE__),               'subType' => 'other'],
            // ADR-17 Amendment 3 (Option D): wired manually by the installer into the alarm
            // plugin's zone IMMEDIATE-actions bucket (not standard/after-delay) — fires as soon
            // as the sensor triggers, well before the BA's own trigger-delay actions fire.
            // subType MUST be 'message', not 'other': the alarm plugin only exposes a *Titre*
            // field (where #zone# gets substituted into $_options['title']) for 'message'-subtype
            // action commands, per the general tag mechanism described in
            // internal-docs/design/php-core-design.md:424-441 — 'other' has no options field at all, so
            // the zone would never reach execute(). Confirmed empirically via live testing,
            // 2026-09-24 (prefetchEvent fired but $_options['title'] was always empty).
            'prefetchEvent' => ['name' => __('Prefetch événement Frigate', __FILE__), 'subType' => 'message'],
        ];
        foreach ($actionCmds as $logicalId => $spec) {
            $cmd = $this->getCmd('action', $logicalId);
            if (!is_object($cmd)) {
                $cmd = new siaDC09Cmd();
                $cmd->setLogicalId($logicalId);
                $cmd->setEqLogic_id($this->getId());
                $cmd->setName($spec['name']);
                $cmd->setType('action');
                $cmd->setSubType($spec['subType']);
                $cmd->setIsVisible(0);
                $cmd->setConfiguration('returnStateTime', 30);
                $cmd->setConfiguration('returnStateValue', 0);
                $cmd->save();
            }
        }

        $infoCmds = [
            'supervision_state' => ['name' => __('État supervision', __FILE__), 'subType' => 'numeric', 'default' => 1],
            'supervision_label' => ['name' => __('Supervision', __FILE__),      'subType' => 'string',  'default' => 'DÉMARRAGE…'],
            'event_state'       => ['name' => __('État alarme', __FILE__),      'subType' => 'numeric', 'default' => 0],
            'event_label'       => ['name' => __('Alarme', __FILE__),           'subType' => 'string',  'default' => 'Inactif'],
        ];
        foreach ($infoCmds as $logicalId => $spec) {
            $cmd = $this->getCmd('info', $logicalId);
            if (!is_object($cmd)) {
                $cmd = new siaDC09Cmd();
                $cmd->setLogicalId($logicalId);
                $cmd->setEqLogic_id($this->getId());
                $cmd->setName($spec['name']);
                $cmd->setType('info');
                $cmd->setSubType($spec['subType']);
                $cmd->setIsVisible(0);
                $cmd->save();
                $this->checkAndUpdateCmd($logicalId, $spec['default']);
            }
        }

        // Every supervision / RP ACK re-pushes the same state. With the core default
        // ('never') checkAndUpdateCmd() only refreshes the cached collectDate and the
        // browser hears nothing; 'always' makes each ACK a cmd::update event, so the
        // widget's "last supervision" time moves live (no polling needed). Same for
        // event_label, whose text is identical on consecutive RP results.
        foreach (['supervision_state', 'event_label'] as $repeatLogicalId) {
            $repeatCmd = $this->getCmd('info', $repeatLogicalId);
            if (is_object($repeatCmd) && $repeatCmd->getConfiguration('repeatEventManagement') !== 'always') {
                $repeatCmd->setConfiguration('repeatEventManagement', 'always');
                $repeatCmd->save();
            }
        }
    }

    public function preRemove(): void {
        self::deamon_stop();
        config::save('sia_last_errors', '[]', __CLASS__);
        config::save('sia_last_messages', '[]', __CLASS__);
    }
}
