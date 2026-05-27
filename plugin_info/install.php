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
