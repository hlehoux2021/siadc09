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

    if (!isConnect('admin')) {
        throw new Exception(__('401 - Accès non autorisé', __FILE__));
    }

    ajax::init();

    if (init('action') == 'testConnection') {
        $eqLogics = eqLogic::byType('siaDC09');
        if (!is_array($eqLogics) || count($eqLogics) === 0) {
            ajax::success(['status' => 'error', 'detail' => __("Équipement introuvable — activez le plugin.", __FILE__)]);
            return;
        }
        $eqLogic = $eqLogics[0];

        $configData = $eqLogic->getConfiguration();
        $encKey = $configData['encryption_key'] ?? '';
        unset($configData['encryption_key']);

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
        if ($stderr !== '') {
            log::add('siaDC09', 'error', 'Test connexion — erreur Python : ' . $stderr);
        }

        $result = json_decode($jsonOutput, true);
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
        $eqLogics = eqLogic::byType('siaDC09');
        if (!is_array($eqLogics) || count($eqLogics) === 0) {
            ajax::success([
                'supervision_state' => 1,
                'supervision_label' => '',
                'event_state' => 0,
                'event_label' => '',
                'errors' => [],
                'messages' => [],
            ]);
            return;
        }
        $eqLogic = $eqLogics[0];

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

        $eqLogics = eqLogic::byType('siaDC09');
        if (empty($eqLogics)) {
            ajax::error(__('Aucun équipement siaDC09 trouvé', __FILE__));
            return;
        }
        $eqLogic = $eqLogics[0];

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
