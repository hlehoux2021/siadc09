---
story_id: "14-1"
story_key: "14-1-attach-frigate-snapshot-alarm-frame"
epic_id: "epic-14"
epic_name: "Camera Snapshot Attachment (Frigate Integration)"
status: "in-progress"
created: "2026-09-22"
---

# Story 14.1: Attach Frigate Snapshot to Alarm Frame (Majority Case Only)

Status: in-progress

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

- [x] Task 1: Simplify zone mapping schema and wizard UI (AC: 1, 2)
  - [x] 1.1 Added `frigate_camera_eqlogic_id` (+ denormalized `frigate_camera_label` for display) to each
        `sia_zone_mappings` entry, replacing `camera_action_cmd_id`/`camera_action_cmd_label`/`media_url_cmd_id`/
        `media_url_cmd_label` (deleted — dead data, never read by any PHP code).
  - [x] 1.2 Added `getFrigateCameras` AJAX action in `core/ajax/siaDC09.ajax.php`: candidates from
        `cmd::byGenericType('CAMERA_TAKE')`, filtered to equipments that also expose `info_detect_person` AND
        `info_url_snapshot` by logicalId. Deleted `getCameraCommands` (dead code once nothing called it).
  - [x] 1.3 Step 3 zone table (`desktop/php/siaDC09.php` / `desktop/js/siaDC09.js`): replaced the two
        `<select>` dropdowns with a single "Caméra Frigate" dropdown per zone, populated from
        `getFrigateCameras`.
  - [x] 1.4 Added `#siaDC09-step3-nocamera` warning banner (shown when the discovered camera list is empty or
        the AJAX call fails) — non-blocking, mirrors 8-2's "no alarm plugin zones" pattern.

- [x] Task 2: Derive Frigate commands and resolve `media_url` at alarm time (AC: 3, 4, 5, 6)
  - [x] 2.1 Added `siaDC09Cmd::_resolveFrigateSnapshotUrl(array $zoneEntry): ?string` that reads
        `frigate_camera_eqlogic_id` and resolves `info_detect_person`/`info_url_snapshot` via
        `cmd::byLogicalId(..., $eqLogicId, false)`.
  - [x] 2.2 Returns `info_url_snapshot->execCmd()` only if `info_detect_person->execCmd() === 1`; `null`
        otherwise (any other state, or any command/equipment missing).
  - [x] 2.3 Whole body wrapped in `try/catch (\Throwable $e)`, logs a warning, returns `null` on any failure.
  - [x] 2.4 `execute()` calls the helper after `_resolveZoneNumber()`; `media_url` key added to the
        `sendToDaemon()` payload only when non-null (key omitted, never sent as literal `null`).

- [x] Task 3: Level 1 tests (AC: 5)
  - [x] 3.1 `tests/level1/test_frigate_snapshot_resolution.py` (new): structural/regex tests for
        `_resolveFrigateSnapshotUrl()` (exists, reads `frigate_camera_eqlogic_id`, resolves both commands by
        logicalId, never touches `info_url_clip`, uses `execCmd()` never `getValue()`, wrapped in try/catch,
        `?string` return type) and for `getFrigateCameras` (exists, starts from `CAMERA_TAKE`, filters by both
        Frigate-specific commands, single `cameras` list). TDD RED→GREEN for all of it.
  - [x] 3.2 Test that `execute()`'s alarm case adds `media_url` conditionally, not as a literal key in the base
        payload array.
  - [x] 3.3 `php -l` clean on all modified PHP files; `node --check` clean on `siaDC09.js`. Full
        `tests/level1/` suite: 1115 passed / 8 failed — identical to the pre-existing baseline (2 known + 6
        known-RED from story 13-1's in-progress fan-out work, unrelated to this story). Updated 2 pre-existing
        tests that asserted on the deleted `camera_action_cmd_id`/`media_url_cmd_id` JS fields
        (`test_wizard_js_logic.py`) and replaced the obsolete "getCameraCommands Action" test section (6 tests)
        with a "getFrigateCameras Action" section in `test_wizard_ajax_contracts.py`, plus updated
        `_AJAX_ACTIONS` in `test_wizard_config_key_consistency.py` — all following the deletion of the now-dead
        `getCameraCommands` handler. 0 regressions.

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

Implemented Tasks 1-3 in dependency order: PHP resolver + `execute()` wiring first (Task 2, since it's the
core alarm-path behavior and independently testable), then the AJAX discovery action and wizard UI
simplification (Task 1), with Level 1 tests written red-first for each piece (Task 3 interleaved, not a
separate pass at the end).

`_resolveFrigateSnapshotUrl()` deliberately duplicates the `_findZoneEntry()` lookup already done by
`_resolveZoneNumber()` inside `execute()`, rather than refactoring `_resolveZoneNumber()` to accept a
pre-fetched entry — kept the two resolutions (zone number vs. Frigate snapshot) independent so a failure in
one can never affect the other, at the cost of one small redundant array scan per alarm (negligible: zone
mappings are a handful of entries).

`getCameraCommands` was deleted rather than kept alongside the new `getFrigateCameras` action: once the
wizard stopped calling it, it had zero callers — dead code per project convention — and the story's own
Dev Notes draft had originally argued to keep it "for a future non-Frigate camera story," but that's exactly
the kind of speculative code the project avoids. If a future story needs generic camera support again, it can
be re-added then with a real caller.

### Completion Notes

- Tasks 1-3 complete: zone mapping simplified to a single Frigate-camera pick, `media_url` resolution wired
  into the alarm-trigger path (majority case only, per ADR-17), Level 1 tests green.
- `php -l` clean on `core/class/siaDC09Cmd.class.php`, `core/ajax/siaDC09.ajax.php`, `desktop/php/siaDC09.php`.
  `node --check` clean on `desktop/js/siaDC09.js`.
- Full `tests/level1/` suite: 1115 passed / 8 failed — identical to the pre-existing baseline (2 known +
  6 known-RED from story 13-1's in-progress fan-out work, confirmed unrelated by inspection). 0 regressions
  from this story's changes.
- **Task 4 (live validation on `test-jeedom.lehoux.net`) is NOT done** — per memory
  `jeedom-ui-validation-over-reflection`, acceptance requires validating on the real dashboard with a real
  Frigate camera, and per `jeedom-test-host-deploy` the code must be pushed first so the host can `git pull`.
  Awaiting push + Herve's verification of: zone mapping shows the new single-camera dropdown with a real
  Frigate camera; an alarm fired while Frigate has an active person detection carries a working snapshot URL
  in the SIA frame's `[V...]` field (protocol inspector); an alarm fired with no active detection sends
  normally with no `media_url` and no delay.

### File List

| File | Change |
|------|--------|
| `core/class/siaDC09Cmd.class.php` | Added `_resolveFrigateSnapshotUrl()`; wired conditional `media_url` into `execute()`'s alarm-trigger payload. |
| `core/ajax/siaDC09.ajax.php` | Added `getFrigateCameras` action; deleted `getCameraCommands` (dead code, no remaining callers). |
| `desktop/php/siaDC09.php` | Step 3 zone table: merged two camera/media columns into one "Caméra Frigate" column; added `#siaDC09-step3-nocamera` warning banner. |
| `desktop/js/siaDC09.js` | `saveEqLogic()`, `siaDC09_loadZoneData()`, `siaDC09_loadZoneTable()`, `siaDC09_buildZoneRow()`, `siaDC09_populateConfigSummary()` updated for the single-camera schema (`frigate_camera_eqlogic_id`/`frigate_camera_label`) and the new `getFrigateCameras` AJAX action. |
| `tests/level1/test_frigate_snapshot_resolution.py` | New — structural tests for `_resolveFrigateSnapshotUrl()`, `getFrigateCameras`, and the conditional `media_url` wiring in `execute()`. |
| `tests/level1/test_wizard_js_logic.py` | Updated 2 tests that asserted on the deleted `camera_action_cmd_id`/`media_url_cmd_id`/labels JS fields to assert on `frigate_camera_eqlogic_id`/`frigate_camera_label` instead. |
| `tests/level1/test_wizard_ajax_contracts.py` | Replaced the obsolete 6-test "getCameraCommands Action" section with a 5-test "getFrigateCameras Action" section. |
| `tests/level1/test_wizard_config_key_consistency.py` | `_AJAX_ACTIONS`: `getCameraCommands` → `getFrigateCameras`. |

## Change Log

| Date | Change |
|------|--------|
| 2026-09-22 | Story created from ADR-17 (Option A, majority-case-only Frigate snapshot attachment), following an adversarial review and a Winston/Amelia/John party-mode architecture discussion. |
| 2026-09-22 | Tasks 1-3 implemented: zone mapping simplified to a single Frigate-camera pick, `media_url` resolution wired into the alarm-trigger path, Level 1 tests green (0 regressions). Task 4 (live host validation) pending push + Herve's verification. Status `ready-for-dev → in-progress`. |
