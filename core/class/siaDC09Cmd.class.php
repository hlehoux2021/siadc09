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

    public function execute($_options = array()): void {
        $logicalId = $this->getLogicalId();
        switch ($logicalId) {
            case 'burglarAlarm':
            case 'fireAlarm':
            case 'panicAlarm':
                // The alarm plugin's #zone# tag substitutes the zone LABEL — its zone model has
                // no identifier. The label stays in the payload for the logs, the notification
                // context and the inspector; only zone_number reaches the SIA frame.
                $zone = trim($_options['title'] ?? '');
                siaDC09::sendToDaemon([
                    'cmd'         => $logicalId,
                    'zone'        => $zone !== '' ? $zone : null,
                    'zone_number' => $this->_resolveZoneNumber($zone),
                ]);
                break;
        }
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
