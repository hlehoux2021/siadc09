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
        $envPrefix = 'SIA_ENCRYPTION_KEY=' . escapeshellarg($encKey) . ' ';

        set_time_limit(30);
        exec($envPrefix . $cmd . ' 2>/dev/null', $output, $retCode);

        $jsonOutput = implode('', $output);
        $result = json_decode($jsonOutput, true);
        if (!is_array($result)) {
            ajax::success([
                'status' => 'error',
                'detail' => __('Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés', __FILE__),
            ]);
            return;
        }
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

    if (init('action') == 'getCameraCommands') {
        $format = function ($cmd) {
            $eqLogic = $cmd->getEqLogic();
            if (!is_object($eqLogic)) {
                return null;
            }
            return [
                'id'    => (int) $cmd->getId(),
                'label' => $eqLogic->getName() . ' > ' . $cmd->getName(),
            ];
        };
        ajax::success([
            'camera_take' => array_values(array_filter(array_map($format, cmd::byGenericType('CAMERA_TAKE') ?? []))),
            'camera_url'  => array_values(array_filter(array_map($format, cmd::byGenericType('CAMERA_URL') ?? []))),
        ]);
    }

    throw new Exception(__('Aucune méthode correspondante à', __FILE__) . ' : ' . init('action'));
} catch (Exception $e) {
    ajax::error(displayException($e), $e->getCode());
}
