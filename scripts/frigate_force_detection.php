#!/usr/bin/env php
<?php
/**
 * Standalone test utility for story 14-1 (see ADR-17, _bmad-output/planning-artifacts/architecture.md).
 * Not part of the shipped siaDC09 plugin — run manually on the Jeedom host, over SSH, when
 * physical access to the camera to trigger a real Frigate detection isn't available.
 *
 * Frigate's manual event API (/api/events/{camera}/{label}/create and /events/{event_id}/end)
 * never publishes to its own MQTT events/reviews topics (confirmed against Frigate's source:
 * frigate/api/event.py's create_event docstring, and frigate/events/maintainer.py's
 * handle_external_detection(), which never calls event_end_publisher unlike the real
 * tracked-object path) — so info_detect_person and info_url_snapshot can never be reached
 * through Frigate's API alone. This script sets them directly, using the same
 * cmd::event()/save() calls the Frigate plugin's own handleObject()/majEventsCmds() use
 * internally, so the Jeedom-side resolver in core/class/siaDC09Cmd.class.php sees exactly
 * the state it would see from a real detection.
 *
 * Usage:
 *   php scripts/frigate_force_detection.php --eqlogic-id=4 --event-id=1790143151.820367-ww7fi0 \
 *       --frigate-host=192.168.100.18:5000 [--detect=1]
 *
 * --detect=1 (default): forces info_detect_person=1 and info_url_snapshot to the guessable
 *   snapshot URL for --event-id (majority case, AC3/AC7).
 * --detect=0: forces info_detect_person=0 only, to test the fallback path (AC4) — event-id
 *   and frigate-host are still required but unused in this mode.
 */

require_once '/var/www/html/core/php/core.inc.php';

$options = getopt('', ['eqlogic-id:', 'event-id:', 'frigate-host:', 'detect::']);

foreach (['eqlogic-id', 'event-id', 'frigate-host'] as $required) {
    if (!isset($options[$required]) || $options[$required] === '') {
        fwrite(STDERR, "Usage: php " . __FILE__ . " --eqlogic-id=<id> --event-id=<id> --frigate-host=<host:port> [--detect=1]\n");
        exit(1);
    }
}

$eqLogicId = (int) $options['eqlogic-id'];
$eventId = $options['event-id'];
$frigateHost = $options['frigate-host'];
$detectValue = isset($options['detect']) ? (int) $options['detect'] : 1;

$detectCmd = cmd::byEqLogicIdAndLogicalId($eqLogicId, 'info_detect_person');
if (!is_object($detectCmd)) {
    fwrite(STDERR, "info_detect_person introuvable sur l'eqLogic {$eqLogicId}\n");
    exit(1);
}
$detectCmd->event($detectValue);
$detectCmd->save();
echo "info_detect_person = {$detectValue} sur eqLogic {$eqLogicId}\n";

if ($detectValue === 1) {
    $snapshotCmd = cmd::byEqLogicIdAndLogicalId($eqLogicId, 'info_url_snapshot');
    if (!is_object($snapshotCmd)) {
        fwrite(STDERR, "info_url_snapshot introuvable sur l'eqLogic {$eqLogicId}\n");
        exit(1);
    }
    $snapshotUrl = "http://{$frigateHost}/api/events/{$eventId}/snapshot.jpg";
    $snapshotCmd->event($snapshotUrl);
    $snapshotCmd->save();
    echo "info_url_snapshot = {$snapshotUrl} sur eqLogic {$eqLogicId}\n";
}
