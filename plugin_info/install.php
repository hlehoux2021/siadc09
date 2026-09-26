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

require_once dirname(__FILE__) . '/../../../core/php/core.inc.php';

function siaDC09_install(): void {
}

function siaDC09_update(): void {
    // Story 13-1 (finding #2): postSave() only runs on save (fresh install, manual re-save).
    // On upgrade, Jeedom calls this hook, not postSave() — an existing install that never
    // re-saves its equipment would otherwise never get the new disarm/alarmReset commands.
    // Each eqLogic is isolated (code review 2026-09-26): one misbehaving equipment must not
    // abort migration for every other siaDC09 eqLogic on the same instance.
    foreach (eqLogic::byType('siaDC09') as $eqLogic) {
        try {
            $eqLogic->postSave();
        } catch (\Throwable $e) {
            log::add('siaDC09', 'error', 'siaDC09_update: postSave() a échoué pour l\'équipement '
                . $eqLogic->getId() . ' : ' . $e->getMessage());
        }
    }
}

function siaDC09_remove(): void {
    $pidFile = jeedom::getTmpFolder('siaDC09') . '/daemon.pid';
    if (file_exists($pidFile)) {
        $pid = intval(trim(file_get_contents($pidFile)));
        if ($pid > 0) {
            system::kill($pid);
        }
    }
    system::kill('siadc09d.py');
    @log::add('siaDC09', 'info', __('Suppression du plugin — démon arrêté', __FILE__));
}
