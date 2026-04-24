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

    public static function dependancy_info(): array {
        $installOk = dirname(__FILE__) . '/../../resources/siadc09d/.install_ok';
        return [
            'state' => file_exists($installOk) ? 'ok' : 'nok',
            'nb_try' => 0,
        ];
    }

    public static function deamon_info(): array {
        $return = [
            'log' => __CLASS__ . '_daemon',
            'launchable' => 'nok',
            'state' => 'nok',
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

        $eqLogic = self::_getAutoEquipmentSafe();
        if ($eqLogic === null) {
            $return['launchable_message'] = __('Aucun équipement configuré', __FILE__);
            return $return;
        }

        $csrIp = $eqLogic->getConfiguration('csr_ip', '');
        $csrPort = (int) $eqLogic->getConfiguration('csr_port', 0);
        $transport = $eqLogic->getConfiguration('transport', '');

        if ($csrIp !== '' && $csrPort > 0 && $transport !== '') {
            $return['launchable'] = 'ok';
        } else {
            $return['launchable_message'] = __('Veuillez vérifier la configuration', __FILE__);
        }

        return $return;
    }

    public static function deamon_start(): bool {
        self::deamon_stop();
        $deamonInfo = self::deamon_info();
        if ($deamonInfo['launchable'] !== 'ok') {
            throw new Exception(__('Veuillez vérifier la configuration', __FILE__));
        }

        // launchable=='ok' guarantees equipment exists with valid config
        $eqLogic = self::_getAutoEquipmentSafe();

        $path = realpath(dirname(__FILE__) . '/../../resources/siadc09d');
        $socketport = (int) config::byKey('socketport', __CLASS__, 55009);

        $cmd = self::getPython3() . $path . '/siadc09d.py';
        $cmd .= ' --loglevel ' . log::convertLogLevel(log::getLogLevel(__CLASS__));
        $cmd .= ' --socketport ' . $socketport;
        $cmd .= ' --callback ' . network::getNetworkAccess('internal', 'proto:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php';
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

        $retryCount = (int) $eqLogic->getConfiguration('retry_count', 3);
        $cmd .= ' --retry-count ' . $retryCount;

        $notifyCmdId = (int) $eqLogic->getConfiguration('sia_notify_cmd_id', 0);
        if ($notifyCmdId > 0) {
            $cmd .= ' --notify-cmd-id ' . $notifyCmdId;
        }

        $cmdLog = preg_replace('/--encryption-key\s+\S+/', '--encryption-key [REDACTED]', $cmd);
        log::add(__CLASS__, 'info', __('Lancement démon', __FILE__) . ': ' . $cmdLog);
        $result = exec($cmd . ' >> ' . log::getPathToLog(__CLASS__ . '_daemon') . ' 2>&1 &');

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

    public function postSave(): void {
        $actionCmds = [
            'burglarAlarm' => ['name' => __('Alarme intrusion', __FILE__), 'subType' => 'message'],
            'fireAlarm'    => ['name' => __('Alarme incendie', __FILE__), 'subType' => 'message'],
            'panicAlarm'   => ['name' => __('Alarme panique', __FILE__),  'subType' => 'message'],
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
    }

    public function preRemove(): void {
        self::deamon_stop();
    }
}
