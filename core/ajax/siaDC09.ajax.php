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

try {
    require_once dirname(__FILE__) . '/../../../../core/php/core.inc.php';
    include_file('core', 'authentification', 'php');

    // Widget poll: readable by any connected user (the dashboard tile is not admin-only).
    // Returns the collectDate of supervision_state / event_label. execCmd() fills it from
    // the cmd cache, which checkAndUpdateCmd() refreshes even when the value is unchanged
    // (an RP / supervision ACK that leaves the state at OK pushes no cmd::update event).
    if (init('action') == 'getWidgetDates') {
        if (!isConnect()) {
            throw new Exception(__('401 - Accès non autorisé', __FILE__));
        }
        ajax::init();
        $eqLogic = eqLogic::byId((int) init('id'));
        if (!is_object($eqLogic) || $eqLogic->getEqType_name() !== 'siaDC09') {
            throw new Exception(__('Équipement introuvable', __FILE__));
        }
        $dates = [];
        foreach (['state_date' => 'supervision_state', 'event_date' => 'event_label'] as $key => $logicalId) {
            $cmd = $eqLogic->getCmd('info', $logicalId);
            $dates[$key] = '';
            if (is_object($cmd)) {
                $cmd->execCmd();
                $dates[$key] = (string) $cmd->getCollectDate();
            }
        }
        ajax::success($dates);
        return;
    }

    if (!isConnect('admin')) {
        throw new Exception(__('401 - Accès non autorisé', __FILE__));
    }

    ajax::init();

    // Story 18.7: read-only FTPS probe (connect, TLS, certificate, login; nothing written).
    // Answer: {status: ok|untrusted|changed|error, step?, detail, fingerprint?}. The browser sends
    // no password: the saved configuration is read here and handed to a short-lived Python
    // subprocess, the password by environment only.
    if (init('action') == 'testFtps') {
        $eqLogic = siaDC09::getActiveEquipment();
        if ($eqLogic === null) {
            ajax::success(['status' => 'error', 'step' => 'connexion', 'detail' => __("Aucun équipement actif — activez un équipement.", __FILE__)]);
            return;
        }

        $ftpsConfig = [];
        foreach (['ftps_host', 'ftps_port', 'ftps_user', 'ftps_cert_fingerprint'] as $ftpsKey) {
            $ftpsConfig[$ftpsKey] = (string) $eqLogic->getConfiguration($ftpsKey, '');
        }
        if (trim($ftpsConfig['ftps_host']) === '' || trim($ftpsConfig['ftps_user']) === '') {
            // Nothing is contacted.
            ajax::success([
                'status' => 'error',
                'step' => 'connexion',
                'detail' => __("Réglages FTPS incomplets : renseignez le serveur et l'utilisateur dans les options avancées.", __FILE__),
            ]);
            return;
        }

        if (method_exists('system', 'getCmdPython3')) {
            $python3 = system::getCmdPython3('siaDC09');
        } else {
            $python3 = 'python3 ';
        }
        $script = realpath(__DIR__ . '/../../resources/siadc09d/siadc09d.py');
        if (!$script) {
            ajax::success(['status' => 'error', 'step' => 'connexion', 'detail' => __('Script de test non trouvé — réinstallez le plugin', __FILE__)]);
            return;
        }
        $encoded = json_encode($ftpsConfig);
        if ($encoded === false) {
            ajax::success(['status' => 'error', 'step' => 'connexion', 'detail' => __('Erreur lors du codage de la configuration', __FILE__)]);
            return;
        }

        $cmd = $python3 . escapeshellarg($script) . ' --test-ftps --config ' . escapeshellarg($encoded);
        log::add('siaDC09', 'debug', 'Test FTPS — commande : ' . $cmd);

        $stderrFile = tempnam(sys_get_temp_dir(), 'siaDC09_ftps_');
        $redirect = $stderrFile ? ' 2>' . escapeshellarg($stderrFile) : ' 2>/dev/null';

        // putenv(), not a "VAR=value " prefix: the password must not appear in a command line.
        $ftpsPassword = (string) $eqLogic->getConfiguration('ftps_password', '');
        putenv('SIA_FTPS_PASSWORD=' . $ftpsPassword);
        set_time_limit(30);
        try {
            exec($cmd . $redirect, $output, $retCode);
        } finally {
            putenv('SIA_FTPS_PASSWORD');
        }

        $stderr = $stderrFile ? trim((string) @file_get_contents($stderrFile)) : '';
        if ($stderrFile) {
            @unlink($stderrFile);
        }
        if ($stderr !== '') {
            // A traceback can echo a server reply: the password never reaches the log.
            if ($ftpsPassword !== '') {
                $stderr = str_replace($ftpsPassword, '***', $stderr);
            }
            log::add('siaDC09', 'debug', 'Test FTPS — détail technique : ' . $stderr);
        }

        $result = json_decode(implode('', $output), true);
        if (!is_array($result) || !in_array($result['status'] ?? '', ['ok', 'untrusted', 'changed', 'error'], true)) {
            log::add('siaDC09', 'error', 'Test FTPS — sortie illisible (code retour ' . $retCode . ')');
            ajax::success([
                'status' => 'error',
                'step' => 'connexion',
                'detail' => __('Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés', __FILE__),
            ]);
            return;
        }
        // Only the contract keys go back; the verdict is logged without any secret.
        $answer = array_intersect_key($result, array_flip(['status', 'step', 'detail', 'fingerprint']));
        log::add('siaDC09', 'info', 'Test FTPS — résultat : ' . $answer['status']
            . (isset($answer['step']) ? ' (étape ' . $answer['step'] . ')' : ''));
        ajax::success($answer);
        return;
    }

    if (init('action') == 'testConnection') {
        $eqLogic = siaDC09::getActiveEquipment();
        if ($eqLogic === null) {
            ajax::success(['status' => 'error', 'detail' => __("Aucun équipement actif — activez un équipement.", __FILE__)]);
            return;
        }

        $configData = $eqLogic->getConfiguration();
        $encKey = $configData['encryption_key'] ?? '';
        unset($configData['encryption_key'], $configData['ftps_password']);

        if (method_exists('system', 'getCmdPython3')) {
            $python3 = system::getCmdPython3('siaDC09');
        } else {
            $python3 = 'python3 ';
        }

        $script = realpath(__DIR__ . '/../../resources/siadc09d/siadc09d.py');
        if (!$script) {
            ajax::success(['status' => 'error', 'detail' => __('Script de test non trouvé — réinstallez le plugin', __FILE__)]);
            return;
        }

        $encoded = json_encode($configData);
        if ($encoded === false) {
            ajax::success(['status' => 'error', 'detail' => __('Erreur lors du codage de la configuration', __FILE__)]);
            return;
        }

        $cmd = $python3 . escapeshellarg($script)
            . ' --test-only --timeout 15 --config ' . escapeshellarg($encoded);
        // $envPrefix carries the AES key — never log it, only $cmd.
        $envPrefix = 'SIA_ENCRYPTION_KEY=' . escapeshellarg($encKey) . ' ';
        log::add('siaDC09', 'debug', 'Test connexion — commande : ' . $cmd);

        $stderrFile = tempnam(sys_get_temp_dir(), 'siaDC09_test_');
        $redirect = $stderrFile ? ' 2>' . escapeshellarg($stderrFile) : ' 2>/dev/null';

        set_time_limit(30);
        exec($envPrefix . $cmd . $redirect, $output, $retCode);

        $stderr = $stderrFile ? trim((string) @file_get_contents($stderrFile)) : '';
        if ($stderrFile) {
            @unlink($stderrFile);
        }

        $jsonOutput = implode('', $output);
        log::add('siaDC09', 'debug', 'Test connexion — code retour ' . $retCode . ', sortie : ' . $jsonOutput);
        $result = json_decode($jsonOutput, true);
        // Story 17.12: a DUH is an expected refusal of the test frame (wrong profile or account),
        // not a fault — WARNING here. The running daemon's SM1_DUH level is unrelated.
        // The technical detail (plaintext frame, hex) goes to the log at debug only: at error level
        // Jeedom copies it into the message center, where nobody can read it. The user-facing
        // failure is one readable line below (and the wizard banner).
        if ($stderr !== '') {
            log::add('siaDC09', 'debug', 'Test connexion — détail technique : ' . $stderr);
        }
        if (is_array($result) && !in_array($result['status'] ?? '', ['ok', 'nak'], true)) {
            $isDuh = ($result['outcome'] ?? '') === 'duh';
            log::add('siaDC09', $isDuh ? 'warning' : 'error',
                'Test de connexion échoué : ' . ($result['detail'] ?? ($result['status'] ?? '?')));
        }
        if (!is_array($result)) {
            log::add('siaDC09', 'error', 'Test connexion — sortie illisible (code retour ' . $retCode . ')');
            ajax::success([
                'status' => 'error',
                'detail' => __('Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés', __FILE__),
            ]);
            return;
        }
        log::add('siaDC09', 'info', 'Test connexion — résultat : ' . ($result['status'] ?? '?')
            . ' — ' . ($result['detail'] ?? ''));
        ajax::success($result);
    }

    if (init('action') == 'getZones') {
        $alarmEqLogics = eqLogic::byType('alarm');
        if (empty($alarmEqLogics)) {
            ajax::success(['error' => 'alarm_plugin_not_found']);
            return;
        }
        $zones = $alarmEqLogics[0]->getConfiguration('zones', []);
        if (!is_array($zones)) {
            $zones = [];
        }
        if (empty($zones)) {
            ajax::success(['error' => 'no_zones_configured']);
            return;
        }
        ajax::success(['zones' => array_column($zones, 'name')]);
    }

    if (init('action') == 'getFrigateCameras') {
        // ADR-17 simplification: a zone maps to one Frigate camera equipment — everything else
        // (info_detect_person, info_id) is derived by logicalId at alarm time, never stored
        // separately. CAMERA_TAKE is plugin-agnostic (any camera plugin can tag it), so
        // candidates are filtered to equipments that also expose both Frigate-specific commands.
        // info_id (Task 6 swap, away from the Jeedom-cached snapshot path): same
        // majEventsCmds() sweep, and this filter must stay consistent with what
        // _resolveFrigateSnapshotUrl() actually reads.
        $cameras = [];
        $seenEqLogicIds = [];
        foreach (cmd::byGenericType('CAMERA_TAKE') ?? [] as $takeCmd) {
            $eqLogic = $takeCmd->getEqLogic();
            if (!is_object($eqLogic)) {
                continue;
            }
            $eqLogicId = $eqLogic->getId();
            if (isset($seenEqLogicIds[$eqLogicId])) {
                continue;
            }
            $seenEqLogicIds[$eqLogicId] = true;
            $detectCmd = cmd::byEqLogicIdAndLogicalId((int) $eqLogicId, 'info_detect_person');
            $idCmd = cmd::byEqLogicIdAndLogicalId((int) $eqLogicId, 'info_id');
            if (!is_object($detectCmd) || !is_object($idCmd)) {
                continue;
            }
            $cameras[] = [
                'id'    => (int) $eqLogicId,
                'label' => $eqLogic->getName(),
            ];
        }
        ajax::success(['cameras' => $cameras]);
    }

    if (init('action') == 'getDiagnosticData') {
        $eqLogic = siaDC09::getActiveEquipment();
        if ($eqLogic === null) {
            ajax::success([
                'supervision_state' => 1,
                'supervision_label' => '',
                'event_state' => 0,
                'event_label' => '',
                'state_date' => '',
                'event_date' => '',
                'errors' => [],
                'messages' => [],
            ]);
            return;
        }

        // execCmd(), not getValue(): for non-historized 'info' cmds, cmd::event()
        // (called by the daemon's checkAndUpdateCmd on every push) only writes to
        // the cmd cache (setCache()) — it never touches the cmd table's own 'value'
        // column. getValue() reads that column directly and so stays frozen at
        // whatever it held at cmd creation; execCmd() reads the cache that event()
        // actually updates, which is the live value. Verified against Jeedom core
        // (cmd.class.php: event()/execCmd()/getCache()/getValue()).
        $stateCmd = $eqLogic->getCmd('info', 'supervision_state');
        $supervisionState = $stateCmd ? (int) $stateCmd->execCmd() : 1;

        $labelCmd = $eqLogic->getCmd('info', 'supervision_label');
        $supervisionLabel = $labelCmd ? (string) $labelCmd->execCmd() : '';

        $eventStateCmd = $eqLogic->getCmd('info', 'event_state');
        $eventState = $eventStateCmd ? (int) $eventStateCmd->execCmd() : 0;

        $eventLabelCmd = $eqLogic->getCmd('info', 'event_label');
        $eventLabel = $eventLabelCmd ? (string) $eventLabelCmd->execCmd() : '';

        $rawErrors = config::byKey('sia_last_errors', 'siaDC09', '[]');
        $errors = is_array($rawErrors) ? $rawErrors : (json_decode($rawErrors, true) ?: []);
        $errors = array_slice($errors, 0, 10);

        $rawMessages = config::byKey('sia_last_messages', 'siaDC09', '[]');
        $messages = is_array($rawMessages) ? $rawMessages : (json_decode($rawMessages, true) ?: []);

        ajax::success([
            'supervision_state' => $supervisionState,
            'supervision_label' => $supervisionLabel,
            'event_state' => $eventState,
            'event_label' => $eventLabel,
            // collectDate is filled by the execCmd() calls above (same source as getWidgetDates).
            'state_date' => $stateCmd ? (string) $stateCmd->getCollectDate() : '',
            'event_date' => $eventLabelCmd ? (string) $eventLabelCmd->getCollectDate() : '',
            'errors' => $errors,
            'messages' => $messages,
        ]);
    }

    if (init('action') == 'decodeFrame') {
        $hex = init('hex');
        if (empty($hex)) {
            ajax::error(__('Paramètre hex manquant', __FILE__));
            return;
        }
        if (strlen($hex) > 4096) {
            ajax::error(__('Trame trop longue (max 4096 caractères)', __FILE__));
            return;
        }
        if (!ctype_xdigit($hex)) {
            ajax::error(__('Format hexadécimal invalide', __FILE__));
            return;
        }
        if (strlen($hex) % 2 !== 0) {
            ajax::error(__('Longueur hexadécimale invalide (doit être paire)', __FILE__));
            return;
        }

        $eqLogic = siaDC09::getActiveEquipment();
        if ($eqLogic === null) {
            ajax::error(__('Aucun équipement siaDC09 actif trouvé', __FILE__));
            return;
        }

        $encKey = $eqLogic->getConfiguration('encryption_key', '');

        if (method_exists('system', 'getCmdPython3')) {
            $python3 = system::getCmdPython3('siaDC09');
        } else {
            $python3 = 'python3 ';
        }
        $pythonPath = realpath(__DIR__ . '/../../resources/siadc09d/sia_protocol.py');
        if (!$pythonPath) {
            ajax::error(__('Script de décodage non trouvé — réinstallez le plugin', __FILE__));
            return;
        }

        // Review finding 2026-09-28: a stored key that is non-empty but rejected must not
        // fall through to a silent unencrypted decode — that reads as an opaque decode
        // failure with no clue the key itself was the problem.
        if ($encKey !== '' && !siaDC09::isValidEncryptionKey($encKey)) {
            ajax::error(__('Clé de chiffrement stockée invalide — reconfigurez-la (étape 1)', __FILE__));
            return;
        }

        $cmd = $python3 . escapeshellarg($pythonPath) . ' --decode ' . escapeshellarg($hex);
        $envPrefix = '';
        // Story 1-5 AC5: only a key the daemon would accept is passed (no ASCII fallback).
        if (siaDC09::isValidEncryptionKey($encKey)) {
            $envPrefix = 'SIA_ENCRYPTION_KEY=' . escapeshellarg(trim($encKey)) . ' ';
        }

        set_time_limit(10);
        exec($envPrefix . $cmd . ' 2>/dev/null', $output, $retCode);
        $encKey = null;
        $envPrefix = null;

        if ($retCode !== 0 || empty($output)) {
            ajax::error(__('Erreur de décodage de la trame', __FILE__));
            return;
        }

        $decoded = json_decode(implode('', $output), true);
        if ($decoded === null) {
            ajax::error(__('Réponse invalide du décodeur', __FILE__));
            return;
        }
        if (isset($decoded['error'])) {
            ajax::error($decoded['error']);
            return;
        }
        ajax::success($decoded);
    }

    if (init('action') == 'clearDiagnosticData') {
        $target = init('target');
        if ($target === 'errors') {
            config::save('sia_last_errors', '[]', 'siaDC09');
        } elseif ($target === 'messages') {
            config::save('sia_last_messages', '[]', 'siaDC09');
        } else {
            ajax::error(__('Cible invalide', __FILE__));
            return;
        }
        ajax::success(['success' => true]);
    }

    throw new Exception(__('Aucune méthode correspondante à', __FILE__) . ' : ' . init('action'));
} catch (Exception $e) {
    ajax::error(displayException($e), $e->getCode());
}
