---
story_id: "14-1"
story_key: "14-1-attach-frigate-snapshot-alarm-frame"
epic_id: "epic-14"
epic_name: "Camera Snapshot Attachment (Frigate Integration)"
status: "ready-for-dev"
created: "2026-09-22"
---

# Story 14.1: Attach Frigate Snapshot to Alarm Frame (Majority Case Only)

Status: ready-for-dev

## Story

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want the SIA alarm frame to carry a snapshot URL when Frigate already caught the person before the alarm fired,
So that the monitoring center has a visual without me building or waiting on anything that could delay the alarm itself.

## Context

This story implements ADR-17 (`_bmad-output/planning-artifacts/architecture.md`), reached after a collaborative
design session (adversarial review + a Winston/Amelia/John party-mode debate on Option A — depend on the Jeedom
"Frigate NVR" plugin's own commands — vs Option B — an independent MQTT/REST integration bypassing that plugin).
The decision: **Option A, majority case only.** The fallback case (camera hasn't detected the person yet when the
alarm fires) is explicitly deferred — no create-event call, no wait/poll logic, no `media_url` in that branch this
version. See ADR-17 for the full rationale and the three options table.

A standalone investigation script (`scripts/frigate_latency_probe.py`, not part of this story or the shipped plugin)
was written the same session to measure Frigate's own snapshot/clip URL guessability and timing, informing any
*future* fallback-case story — it has no bearing on this story's implementation.

## Acceptance Criteria

1. **Given** a zone mapped to a Frigate camera equipment, **When** the zone mapping is saved, **Then** only the
   camera equipment is selected — `info_detect_person` and `info_url_snapshot` command IDs are derived by
   `logicalId` lookup on that same equipment, not stored as separate config fields.

2. **And** if the selected camera equipment doesn't expose both `info_detect_person` and `info_url_snapshot`
   (Frigate plugin absent, wrong version, or command missing), saving the mapping warns the user but does not
   block save — same "never crash on unmapped/misconfigured camera" principle as story 8-2's zone mapping.

3. **Given** an alarm fires for a zone mapped to a Frigate camera, **When** `info_detect_person` reads `1`
   (person already detected — the expected majority case), **Then** `info_url_snapshot`'s current value is read
   via `execCmd()` (live cache read — never `getValue()`, which is frozen for these info cmds per project memory
   `jeedom-info-cmd-execcmd-vs-getvalue`) with zero wait, and attached as `media_url` in the `sendToDaemon()`
   payload.

4. **And** when `info_detect_person` reads `0` (fallback case) or the camera/plugin/commands are unavailable for
   any reason, the frame is sent with `media_url` omitted (key absent, not `null` — matches the current payload
   convention of `zone`/`zone_number`) — no create-event call, no wait, no exception, no delay to the alarm send
   path.

5. **And** a test proves the alarm-send path never blocks or throws regardless of camera/plugin state
   (mapped-and-detected, mapped-and-not-detected, camera deleted, plugin absent) — promoted from a design-review
   finding to a hard AC given the life-safety framing of this path.

6. **And** `media_url` never maps to a clip/video URL in this story — snapshot only, matching ADR-17.

7. **And** the whole flow is validated through the real Jeedom UI on `test-jeedom.lehoux.net` against a real
   Frigate camera: trigger an alarm while Frigate has an active person detection, confirm the SIA frame's `[V...]`
   field carries a working snapshot URL in the protocol inspector.

**Explicitly out of scope (deferred, tracked in ADR-17):** the fallback case (create-event call for when the
camera missed the person), clip/video attachment, and the independent MQTT/REST Frigate integration (Option B).

## Tasks / Subtasks

- [ ] Task 1: Simplify zone mapping schema and wizard UI (AC: 1, 2)
  - [ ] 1.1 Add a `frigate_camera_eqlogic_id` field to each `sia_zone_mappings` entry (replacing
        `camera_action_cmd_id`/`camera_action_cmd_label`/`media_url_cmd_id`/`media_url_cmd_label`, which are
        currently dead data — never read by any PHP code per this story's Dev Notes below).
  - [ ] 1.2 Add a new AJAX action (e.g. `getFrigateCameras`) in `core/ajax/siaDC09.ajax.php` that lists candidate
        camera equipments — discover via the equipment owning the command found by
        `cmd::byGenericType('CAMERA_TAKE')` filtered to those whose eqLogic also has an `info_detect_person`
        AND `info_url_snapshot` command by logicalId (see Dev Notes: this is stricter than the existing
        plugin-agnostic `getCameraCommands`, since it must resolve to a real Frigate camera, not any
        CAMERA_TAKE-tagged command).
  - [ ] 1.3 Update the Step 3 zone mapping table in `desktop/php/siaDC09.php` / `desktop/js/siaDC09.js`: replace
        the two `<select>` dropdowns (Action caméra / URL média) with a single "Caméra Frigate" dropdown per
        zone, populated from `getFrigateCameras`.
  - [ ] 1.4 On save, if a zone has no matching camera in the discovered list (plugin absent, wrong version), show
        a warning banner but do not block "Suivant"/save — matches 8-2's "no alarm plugin zones" warning pattern.

- [ ] Task 2: Derive Frigate commands and resolve `media_url` at alarm time (AC: 3, 4, 5, 6)
  - [ ] 2.1 Add a PHP helper (e.g. `siaDC09::_resolveFrigateSnapshot(string $zone): ?string`) that: looks up the
        zone's mapping entry (reuse `_findZoneEntry()` pattern from `siaDC09Cmd.class.php:105-145`), reads
        `frigate_camera_eqlogic_id`, and if present, resolves `info_detect_person` and `info_url_snapshot` via
        `cmd::byLogicalId('info_detect_person', $eqLogicId)` / `cmd::byLogicalId('info_url_snapshot', $eqLogicId)`.
  - [ ] 2.2 If `info_detect_person` exists and `execCmd()` returns `1`: read `info_url_snapshot->execCmd()` and
        return it. Otherwise (any other state, or any command/equipment missing) return `null` — no exception
        ever escapes this helper.
  - [ ] 2.3 Wrap the whole helper body in a broad `try/catch` that logs a warning and returns `null` on any
        failure — this is the AC5 guarantee; the alarm path must be unconditionally safe.
  - [ ] 2.4 In `siaDC09Cmd::execute()` (`core/class/siaDC09Cmd.class.php:31-50`), call the helper after
        `_resolveZoneNumber()` and, only if it returns non-null, add `'media_url' => $snapshotUrl` to the
        `sendToDaemon()` payload array (key omitted entirely when null — do not send `'media_url' => null`).

- [ ] Task 3: Level 1 tests (AC: 5)
  - [ ] 3.1 Test `_resolveFrigateSnapshot()` via PHP structure/regex tests (following the `test_php_eqlogic_stub.py`
        pattern already used in this repo) for: person detected → URL returned; not detected → null; camera
        eqLogic missing → null, no throw; `info_detect_person`/`info_url_snapshot` cmd missing on the equipment →
        null, no throw.
  - [ ] 3.2 Test that `sendToDaemon()`'s payload omits the `media_url` key entirely (not `null`) in the
        fallback/absent cases, and includes it only in the detected case.
  - [ ] 3.3 `php -l` on all modified PHP files; `python3 -m pytest tests/level1/` — compare against the known
        2-failure baseline (memory `level1-test-baseline-failures`).

- [ ] Task 4: Live validation on the Jeedom test host (AC: 2, 7)
  - [ ] 4.1 Deploy (git push then pull on the host — code arrives by git pull, per memory
        `jeedom-test-host-deploy`).
  - [ ] 4.2 Map a zone to a real Frigate camera via the updated wizard Step 3; confirm the warning path if a
        camera without `info_detect_person`/`info_url_snapshot` is selected.
  - [ ] 4.3 Trigger an alarm while Frigate has an active person detection on the mapped camera; confirm the SIA
        frame's `[V...]` field carries the snapshot URL, read via the protocol inspector (story 9-2).
  - [ ] 4.4 Trigger an alarm with no active detection; confirm the frame sends normally with no `media_url` and
        no delay.

## Dev Notes

### Existing code to extend — read before implementing

**`core/class/siaDC09Cmd.class.php:31-50`** — `execute()` for `burglarAlarm`/`fireAlarm`/`panicAlarm`. Currently:
```php
case 'burglarAlarm':
case 'fireAlarm':
case 'panicAlarm':
    $zone = trim($_options['title'] ?? '');
    $zoneNumber = $this->_resolveZoneNumber($zone);
    siaDC09::sendToDaemon([
        'cmd'         => $logicalId,
        'zone'        => $zone !== '' ? $zone : null,
        'zone_number' => $zoneNumber,
    ]);
    $this->_recordOpenAlarm($logicalId, $zone !== '' ? $zone : null, $zoneNumber);
    break;
```
**There is no `media_url` key at all today — not even hardcoded null.** This story adds it, conditionally.

**`core/class/siaDC09Cmd.class.php:105-145`** — `_resolveZoneNumber()` / `_getZoneMapping()` / `_findZoneEntry()`.
Reuse `_getZoneMapping()` + `_findZoneEntry()` as-is (they return the full matched mapping entry); add the new
Frigate-resolution helper alongside `_resolveZoneNumber()`, not inside it — keep the two resolutions independent
so a zone-number failure never affects snapshot resolution or vice versa.

**`sia_zone_mappings` entry shape today** (built in `desktop/js/siaDC09.js:53-60`, `saveEqLogic()`):
```js
{ zone_number, zone_name, camera_action_cmd_id, camera_action_cmd_label, media_url_cmd_id, media_url_cmd_label }
```
`camera_action_cmd_id`/`media_url_cmd_id` are **dead data** — saved and re-displayed in the config summary
(`desktop/js/siaDC09.js:682-709`) but never read by any PHP code (confirmed by repo-wide grep this session). This
story replaces those four fields with one: `frigate_camera_eqlogic_id`. Existing saved configs with the old
fields simply become stale until the user re-saves Step 3 through the updated wizard — no migration script needed
(the fields were never functionally load-bearing).

**`core/ajax/siaDC09.ajax.php:112-127`** — `getCameraCommands`, the existing plugin-agnostic discovery:
```php
if (init('action') == 'getCameraCommands') {
    $format = function ($cmd) {
        $eqLogic = $cmd->getEqLogic();
        if (!is_object($eqLogic)) { return null; }
        return ['id' => (int) $cmd->getId(), 'label' => $eqLogic->getName() . ' > ' . $cmd->getName()];
    };
    ajax::success([
        'camera_take' => array_values(array_filter(array_map($format, cmd::byGenericType('CAMERA_TAKE') ?? []))),
        'camera_url'  => array_values(array_filter(array_map($format, cmd::byGenericType('CAMERA_URL') ?? []))),
    ]);
}
```
Do not repurpose this action for Frigate discovery — it's intentionally plugin-agnostic (any camera plugin tagging
`CAMERA_TAKE`/`CAMERA_URL`) and 8-2's fallback case (a non-Frigate camera) may still want it later. Add a new,
separate `getFrigateCameras` action per Task 1.2.

**No `getZones`-equivalent save handler exists** — `sia_zone_mappings` is saved through Jeedom's generic
eqLogic-save mechanism (JS mutates `_eqLogic.configuration.sia_zone_mappings` in memory in `saveEqLogic()`, the
standard core save AJAX call persists the whole eqLogic). No new save handler is needed for this story either.

### Frigate plugin commands (read-only reference, no dependency on its code — this story only reads its Jeedom
commands via standard `cmd::` APIs)

Source: `/Users/herve.lehoux/dev-hlx/plugin-frigate/core/class/frigate.class.php` (verified this session, not
part of this repo):
- `info_detect_person` — binary INFO command, logicalId `info_detect_<label>` where label matches the camera's
  configured Frigate object-tracking class (confirmed by Herve as "person" for his cameras). Updated live via MQTT
  in `handleObject()` (~line 3352-3365) — real-time as long as the Jeedom `mqtt2` plugin is healthy (confirmed:
  Herve's instance has MQTT configured).
- `info_url_snapshot` — string INFO command, logicalId `info_url_snapshot`. Populated via `majEventsCmds()`
  (~line 2536-2558) from `$event->getSnapshot()`, itself fed by the async MQTT `reviews`-triggered pipeline. This
  value is what "already populated, real-time" means for AC3 — for the majority case (person already detected),
  this value was written before the alarm fired, so there is no wait involved in reading it.
- **Do not use `info_url_clip`** — confirmed unconditionally withheld until the Frigate event's type reaches
  `"end"` (10-30+ seconds), and has a confirmed silent-failure/no-retry bug on top. Out of scope per ADR-17.
- **`CAMERA_TAKE` generic type is on `action_make_api_event`** ("Créer un évènement"), not on the plain snapshot
  action — irrelevant to this story since it's deferred fallback-case machinery, but worth knowing so a future
  story doesn't rediscover this the hard way.

### Jeedom API reference for command lookup by logicalId

`cmd::byLogicalId(string $logicalId, int|string $eqLogicId, bool $exception = false)` — no existing precedent in
this repo for camera-command lookup (the only `byLogicalId` hit in the whole codebase is an unrelated demo-class
self-lookup in `core/class/aiodemo.class.php:97`). Use `$exception = false` (default) and null-check the result —
never let a missing command throw on the alarm path (AC5).

### Read pattern

**Always `execCmd()`, never `getValue()`**, for `info_detect_person` and `info_url_snapshot` — per project memory
`jeedom-info-cmd-execcmd-vs-getvalue`: `getValue()` is frozen forever for non-historized info cmds (verified
against Jeedom core source in a prior story; a same-day mistaken flip to `getValue()` froze the Diagnostic tab in
production). Do not re-litigate this — it is settled.

### Testing Strategy

Level 1 only for this story (no live Frigate/Jeedom required for the unit tests) — follow the PHP structure/regex
testing pattern in `tests/level1/test_php_eqlogic_stub.py`. Level 3/manual validation (Task 4) requires the real
`test-jeedom.lehoux.net` host and a real Frigate camera, per memory `jeedom-ui-validation-over-reflection` —
reflection-based "should work" is not acceptable for this AC.

### Project Structure Notes

- PHP alarm-trigger logic: `core/class/siaDC09Cmd.class.php` (execute(), new resolver helper)
- PHP AJAX: `core/ajax/siaDC09.ajax.php` (new `getFrigateCameras` action)
- Wizard UI: `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` (Step 3 zone mapping table)
- Tests: `tests/level1/test_frigate_snapshot_resolution.py` (new file)

### References

- ADR-17 — `_bmad-output/planning-artifacts/architecture.md`
- Epic 14 / Story 14.1 — `_bmad-output/planning-artifacts/epics.md`
- Prior art: story 8.2 (`8-2-wizard-steps-3-4-zone-mapping.md`) for the zone-mapping wizard pattern and the
  "never crash on unmapped/misconfigured camera" principle
- Memory: `jeedom-info-cmd-execcmd-vs-getvalue`, `jeedom-ui-validation-over-reflection`, `jeedom-test-host-deploy`,
  `level1-test-baseline-failures`

## Dev Agent Record

### Implementation Plan

_Not yet started._

### Completion Notes

_Not yet started._

### File List

_Not yet started._

## Change Log

| Date | Change |
|------|--------|
| 2026-09-22 | Story created from ADR-17 (Option A, majority-case-only Frigate snapshot attachment), following an adversarial review and a Winston/Amelia/John party-mode architecture discussion. |
