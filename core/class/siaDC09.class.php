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

        $retryCount = (int) $eqLogic->getConfiguration('retry_count', 3);
        $cmd .= ' --retry-count ' . $retryCount;

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
                $notifyCmdId = (int) $eqLogic->getConfiguration('sia_notify_cmd_id', 0);
                if ($notifyCmdId <= 0) {
                    log::add(__CLASS__, 'warning',
                        __('Commande notification non configurée — alerte ignorée', __FILE__)
                    );
                    break;
                }
                $notifyCmd = cmd::byId($notifyCmdId);
                if (!is_object($notifyCmd)) {
                    log::add(__CLASS__, 'warning',
                        __('Commande notification non configurée — alerte ignorée', __FILE__)
                    );
                    break;
                }
                try {
                    $notifyCmd->execCmd([
                        'title'   => $message['title'],
                        'message' => $message['message'],
                    ]);
                } catch (Exception $e) {
                    log::add(__CLASS__, 'error',
                        __('Impossible d\'envoyer la notification : ', __FILE__) . $e->getMessage()
                    );
                }
                break;

            case 'error_update':
                $errors = json_decode(config::byKey('sia_last_errors', __CLASS__, '[]'), true) ?: [];
                if (!empty($message['resolve_t1'])) {
                    $errors = array_values(array_filter($errors, fn($e) =>
                        !in_array($e['code'] ?? '', ['SUPERVISION_TIMEOUT', 'SUPERVISION_NAK'])
                    ));
                }
                // No null guard on message/timestamp — daemon is sole caller, always sends all 5 fields
                if (isset($message['code'])) {
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
                $messages = json_decode(config::byKey('sia_last_messages', __CLASS__, '[]'), true) ?: [];
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
                $cmd->setConfiguration('returnStateTime', 30);
                $cmd->setConfiguration('returnStateValue', 0);
                $cmd->save();
                $this->checkAndUpdateCmd($logicalId, $spec['default']);
            }
        }
    }

    public function preRemove(): void {
        self::deamon_stop();
        config::save('sia_last_errors', '[]', __CLASS__);
        config::save('sia_last_messages', '[]', __CLASS__);
    }
}
