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
   (person already detected — the expected majority case), **Then** the Frigate event id is read from
   `info_id`'s current value via `execCmd()` (live cache read — never `getValue()`, which is frozen for these
   info cmds per project memory `jeedom-info-cmd-execcmd-vs-getvalue`) with zero wait, combined with the
   configured media URL template (AC8) into an absolute URL, and attached as `media_url` in the
   `sendToDaemon()` payload. **Amended 2026-09-23** — originally read `info_url_snapshot` directly; superseded
   because that command always holds a Jeedom-local cached-copy path, unusable by an external CSR (see ADR-17
   amendment and AC8). `info_url_snapshot` is no longer read by siaDC09 at all.

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

8. **Added 2026-09-23 (ADR-17 amendment).** `media_url` is built from a single configurable URL template
   string (one global eqLogic config field, not per-zone) containing **literal placeholder tokens** for
   whatever credential the operator's own reverse-proxy needs (e.g. `https://<user>:<pass>@host/` or
   `https://host/?accesstoken=<token>`) — siaDC09 never stores or transmits a real secret; the CSR substitutes
   the placeholder itself, out-of-band. Construction: parse the template, insert `api/events/{event_id}/snapshot.jpg`
   into its **path** component — before any existing query string, so the query-token form still ends up with
   the token at the very end of the URL rather than stranded before the inserted path — then reassemble. When
   the template is empty/unset or fails to parse (missing scheme or host), `media_url` is omitted exactly like
   any other resolution failure (AC4) — never a partial or malformed URL.

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
  - [x] 4.1 Deploy (git push then pull on the host — code arrives by git pull, per memory
        `jeedom-test-host-deploy`).
  - [ ] 4.2 Map a zone to a real Frigate camera via the updated wizard Step 3; confirm the warning path if a
        camera without `info_detect_person`/`info_url_snapshot` is selected.
  - [ ] 4.3 Trigger an alarm while Frigate has an active person detection on the mapped camera; confirm the SIA
        frame's `[V...]` field carries the snapshot URL, read via the protocol inspector (story 9-2).
  - [ ] 4.4 Trigger an alarm with no active detection; confirm the frame sends normally with no `media_url` and
        no delay.
  - [x] 4.5 **Bug found during 4.3** (Herve, 2026-09-23): first live alarm logged
        `Résolution du snapshot Frigate échouée : Call to a member function execCmd() on array` and sent with
        `media_url=None` even though the Frigate event had been created manually beforehand. Root cause: the
        Dev Notes' assumed signature `cmd::byLogicalId(string $logicalId, int|string $eqLogicId, bool $exception
        = false)` does not exist in Jeedom core. The real signature
        (`jeedom/core/core/class/cmd.class.php:214`) is `cmd::byLogicalId($_logical_id, $_type = null)` — no
        eqLogic scoping at all, and it returns an **array** of every matching cmd across every equipment (the
        second positional arg was silently being read as the `type` SQL filter, not an eqLogic scope). Fixed by
        switching both call sites to `cmd::byEqLogicIdAndLogicalId($eqLogicId, $logicalId)`
        (`cmd.class.php:385`), which returns a single object (or `false`) scoped to one equipment — the pattern
        already used internally by `eqLogic::getCmd()`. Fixed in `_resolveFrigateSnapshotUrl()`
        (`core/class/siaDC09Cmd.class.php`) and in `getFrigateCameras` (`core/ajax/siaDC09.ajax.php`), which had
        the identical bug (silently matched too broadly instead of throwing, since an empty array is not
        `null`). Level 1 tests updated to assert the correct API and to forbid the unscoped call
        (`tests/level1/test_frigate_snapshot_resolution.py`, `tests/level1/test_wizard_ajax_contracts.py`
        docstring). Re-validation of 4.2-4.4 against the real host still pending.
  - [x] 4.7 **Second live attempt (2026-09-23)**: PHP-side resolver worked correctly this time
        (`media_url=<set>` logged by the daemon, correct URL in `sendToDaemon()`), but the SIA frame received
        by the CSR simulator carried no `[V...]` field at all — `[#20881|BA 002]`, plain. Root cause is a
        second, larger gap: the daemon never encodes `media_url` into the wire frame at all, in any story.
        See Task 5 below — this is not fixable by re-running 4.3, it requires new daemon work.
  - [x] 4.8 Re-run 4.3/4.4 for real once Task 5 shipped, to confirm the `[V...]` field actually appears in the
        protocol inspector (story 9-2) end to end.
  - [x] 4.9 **Third live attempt (2026-09-23)**: `[V...]` appeared — Task 5 confirmed working — but carrying
        `/plugins/frigate/data/vigi_sud-est/<id>_snapshot.jpg`, a path relative to the Jeedom web server, useless
        to an external CSR. Root cause and fix: see Task 6 and the ADR-17 amendment (siaDC09 stops reading
        `info_url_snapshot` entirely, builds `media_url` from a configurable template + `info_id` instead).
  - [ ] 4.10 Re-run once more after Task 6 ships: configure `frigate_media_url_template` on
        `test-jeedom.lehoux.net`, trigger an alarm with an active detection, confirm the `[V...]` field now
        carries `https://.../api/events/{id}/snapshot.jpg` (with Herve's own placeholder form) instead of the
        old Jeedom-local path.

- [x] Task 5: Encode `media_url` into the SIA frame's `[V...]` extended-data field (AC: 7)
  - **Gap found during Task 4.7, not part of Tasks 1-3's scope** (those were PHP-only). `media_url` reaches
    `sendToDaemon()` (Task 2) and is correctly logged by `on_message()`/`_enqueue_event()`
    (`resources/siadc09d/daemon.py:1786-1824`, `EventQueuePayload` already has a `media_url` key,
    `daemon.py:258`) — but the pipeline dead-ends there. `EventItem` (`daemon.py:161-176`), the dataclass
    `_build_event_frame()` actually consumes, has **no `media_url` field** (its own docstring says "zone_number:
    Only field that reaches the SIA frame", `daemon.py:175`), and `_queue_consumer()`'s `EventItem(...)`
    construction (`daemon.py:1922-1927`) never reads `event_payload.get("media_url")`. Even if it did,
    `_format_data_field()` (`sia_protocol.py:391-414`) has no code path for it.
  - **Spec correction vs. the zone precedent**: `[V...]` is NOT embedded inside the same brackets as
    `[#account|code zone]` the way `zone` is. Per the protocol spec
    (`docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md:609-671`), `zone` lives in §5.5.1.7 [Data]
    (legacy DC-07 Annex B convention — account+eventcode+zone in one bracket), while `V` is one of the
    §5.5.1.8 "[x…data…] Optional Extended Data" identifiers (line 651: `[Vhttp://verify.com/34AC4DE3446]`) —
    its own separate `[V...]` bracket block. Message field order per §5.5.1 subsections is Data (5.5.1.7) →
    Extended Data (5.5.1.8) → Timestamp (5.5.1.9) → CR — so the new block must be inserted in
    `encode_message()`'s `message_core_str` (`sia_protocol.py:240-242`) between `data_field` and
    `timestamp_str`, not folded into `_format_data_field()`.
  - [x] 5.1 Added `media_url: str | None = None` to `EventItem` (`daemon.py:161-176`).
  - [x] 5.2 `_queue_consumer()`'s `EventItem(...)` construction (`daemon.py:1922-1927`) now passes
        `media_url=event_payload.get("media_url")`.
  - [x] 5.3 `_build_event_frame()` (`daemon.py:1614+`): added `event_item.media_url` to the existing
        `extended_data` dict under its own `"media_url"` key (kept `_format_data_field()`'s zone-only contract
        untouched — it silently ignores unknown keys).
  - [x] 5.4 `sia_protocol.py`: added `_format_extended_data_field()` producing `[V{media_url}]` or `""`;
        wired into `encode_message()`'s `message_core_str` between `data_field` and `timestamp_str`. `media_url`
        absent/`None` → `""`, byte-identical to pre-Task-5 frames (confirmed by regression test).
  - [x] 5.5 Level 1 tests added (`tests/level1/test_sia_protocol.py`, 6 new tests): `_format_extended_data_field()`
        renders `[Vhttp://...]`; absent for missing key, empty string, and `None`; `encode_message()` places the
        `[V...]` block contiguously between the data field and the timestamp; regression test confirms no `[V`
        substring at all when `media_url` is absent. Written red-first, confirmed failing before implementation.
  - [x] 5.6 Level 2 tests added (`tests/level2/test_sm2_frame_building.py`, 3 new tests): built real
        `EventItem(media_url=...)` through the actual `_send_with_retry()` → `_build_event_frame()` path (no
        mocked frame builder) and asserted the captured frame bytes contain `[V<url>]`; a `media_url=None`
        case asserts its absence; an ordering test asserts the block sits contiguously between the data field
        and the timestamp. Written red-first (`TypeError: unexpected keyword argument 'media_url'`), confirmed
        failing before implementation — this is exactly the scenario the two live host attempts could only
        catch by trial and error.
  - [x] 5.7 `php -l`/`node --check` not applicable (Python-only change). Full `tests/level1/` suite:
        1122 passed / 8 failed (same 8-failure baseline as before Task 5, confirmed via `git stash` diff —
        +6 new tests, 0 regressions). Full `tests/level2/` suite: 334 passed / 6 failed (same 6-failure
        baseline, confirmed the same way — +3 new tests, 0 regressions). `pylint --disable=all --enable=E`
        clean on both modified daemon files.

- [x] Task 6: Build `media_url` from a configurable template + Frigate `event_id`, stop reading
      `info_url_snapshot` (AC: 3, 8)
  - **Why (found during Task 4.7's second live attempt, 2026-09-23):** `info_url_snapshot` is always a
    Jeedom-local cached-copy path (`/plugins/frigate/data/<camera>/<id>_snapshot.jpg`) by the Frigate plugin's
    own design — confirmed dead-end for an external CSR, see ADR-17 amendment above. Herve: siaDC09 will not
    rely on the Frigate plugin's snapshot exposure/caching at all; construct the URL directly against Frigate's
    own API instead, and never store or transmit a real credential — the config field holds only literal
    placeholder tokens (e.g. `<user>`, `<pass>`, `<token>`) that the CSR substitutes itself, out-of-band.
    Investigated Herve's own `pailly-proxified` reverse-proxy setup (`etc/caddy/Caddyfile:450-523`,
    `cameras.lehoux.net` vhost) as the generalized reference: a dedicated, no-SSO vhost with IP allowlist +
    Basic Auth, GET/HEAD path allowlist already including `/api/events/*/snapshot.jpg`, proxied to Frigate's
    authenticated port. Generalizes to: a static, pre-shared credential embedded in the URL — siaDC09 only
    needs to know the template shape, never the real value.
  - [x] 6.1 New eqLogic config field `frigate_media_url_template` added to `desktop/php/siaDC09.php` Step 3,
        above the zone table — `<input type="password" class="eqLogicAttr" data-l1key="configuration"
        data-l2key="frigate_media_url_template">`, same convention as `encryption_key`. Help text states
        explicitly that only literal placeholder tokens go here, never a real credential. No JS wiring needed:
        `.eqLogicAttr` inputs save/load generically via Jeedom's `getValues('.eqLogicAttr')` (confirmed —
        `encryption_key` itself has zero custom JS); deliberately excluded from
        `siaDC09_populateConfigSummary()`, matching `encryption_key`'s own precedent of never displaying a
        secret-shaped field in the summary.
  - [x] 6.2 `siaDC09Cmd::_buildFrigateMediaUrl(string $template, string $eventId): ?string` implemented
        exactly as designed — `parse_url($template)`, `null` on missing scheme/host, path built with
        `rtrim(..., '/')` + `api/events/` + `rawurlencode($eventId)` + `/snapshot.jpg`, reassembled as
        scheme + userinfo + host + port + path + query + fragment (query/fragment copied verbatim, appended
        last). Made `private static` — pure function of its two args, no Jeedom dependency at all, which let
        Task 6.5's tests execute its real extracted source directly via `php` for genuine behavioral
        verification instead of source-text-shape regex alone.
  - [x] 6.3 `_resolveFrigateSnapshotUrl()` updated: swapped the `info_url_snapshot` read for `info_id`
        (same `cmd::byEqLogicIdAndLogicalId()` pattern, same per-camera equipment), reads
        `frigate_media_url_template` from `$this->getEqLogic()->getConfiguration(...)`, returns `null` early
        when either is empty/missing, otherwise delegates to `_buildFrigateMediaUrl()`. The
        `info_detect_person === 1` gate untouched.
  - [x] 6.4 `getFrigateCameras` (`core/ajax/siaDC09.ajax.php`) swapped its filter from
        `info_detect_person`/`info_url_snapshot` to `info_detect_person`/`info_id` — consistent with what the
        resolver now actually reads.
  - [x] 6.5 Level 1 tests added (`tests/level1/test_frigate_snapshot_resolution.py`, 15 new tests across
        `TestBuildFrigateMediaUrl` and updates to `TestResolveFrigateSnapshotUrlReadsCorrectCommands`/
        `TestGetFrigateCamerasAction`). Went beyond source-text regex for `_buildFrigateMediaUrl()`: because it
        has zero Jeedom dependency, its real extracted method body is executed directly via `php` (a small
        harness function, no `core.inc.php` bootstrap needed) — both AC8 template forms verified against exact
        expected output strings, including the path-before-query ordering guard, a malformed/empty-template
        `null` guard, and event-id URL-escaping. `_resolveFrigateSnapshotUrl()`/`getFrigateCameras` tests
        updated to assert `info_id` plus a negative assertion forbidding `info_url_snapshot` in either call
        site (also fixed one incidental regression in `tests/level1/test_wizard_ajax_contracts.py`, which
        substring-checked for `info_url_snapshot`). Written and confirmed red before implementation.
  - [x] 6.6 `php -l` clean on `core/class/siaDC09Cmd.class.php`, `core/ajax/siaDC09.ajax.php`,
        `desktop/php/siaDC09.php`. `siaDC09.js` unchanged (6.1 confirmed no JS wiring needed) — `node --check`
        not applicable. Full `tests/level1/` suite: 1135 passed / 8 failed — exact pre-existing baseline
        (confirmed matches the known 8), +13 new tests, 0 regressions.
  - [x] 6.7 Task 4 Dev Notes/Change Log updated (see below) — 4.8's live re-validation now checks for
        `https://.../api/events/{id}/snapshot.jpg` (operator's own placeholder form) in the `[V...]` field.

- [x] Task 7: Wizard UI fixes from Task 6's live testing (AC: 8)
  - **Three findings from Herve testing Task 6's wizard changes on `test-jeedom.lehoux.net` (2026-09-23):**
    1. The `frigate_media_url_template` field is masked (`type="password"`) — wrong, since (per Task 6's own
       design) it never holds a real secret, only literal placeholder tokens. Masking it is misleading UX,
       inherited by copying `encryption_key`'s convention without re-checking it applied here.
    2. Clicking "Terminer" at step 4 shows a browser-native "leave page, unsaved changes?" confirmation before
       the connection summary appears — unwanted. Traced to Jeedom core
       (`jeedom/core/desktop/common/js/utils.js:767-773`): the global `beforeunload` listener fires whenever
       `window.modifyWithoutSave`/`jeeFrontEnd.modifyWithoutSave` is `true` (set by
       `core/js/plugin.template.js` on any `.eqLogicAttr` field change). `bt_step4Finish`'s handler
       (`desktop/js/siaDC09.js:614-638`) saves via its own direct `jeedom.eqLogic.save()` call, then
       `window.location.reload()` — the save succeeds, but nothing resets the two dirty-flag globals first, so
       core still thinks the page has unsaved changes at reload time.
    3. The connection summary (`siaDC09_populateConfigSummary()`, `desktop/js/siaDC09.js:642+`) doesn't mention
       the media URL template entered in step 3 — a direct consequence of Task 6.1's own decision to exclude it
       from the summary "matching `encryption_key`'s precedent of never displaying a secret-shaped field" —
       which finding 1 shows was the wrong precedent to follow here, since this field isn't a secret.
  - [x] 7.1 `desktop/php/siaDC09.php`: `frigate_media_url_template` input changed from `type="password"` to
        `type="text"`.
  - [x] 7.2 `desktop/js/siaDC09.js`, `bt_step4Finish`'s `success` callback now sets
        `window.modifyWithoutSave = false` and `jeeFrontEnd.modifyWithoutSave = false` immediately before
        `window.location.reload()`.
  - [x] 7.3 `siaDC09_populateConfigSummary()`: added "URL media Frigate" to `#siaDC09-summary-connection`,
        alongside Opérateur/Centrale/Supervision/Chiffrement, with an italic muted "non configurée" fallback
        when empty — matching the zones/notification blocks' own empty-state style.
  - [x] 7.4 Level 1 tests added: `tests/level1/test_wizard_php_structure.py`
        (`test_step3_media_url_template_field_is_plain_text`), `tests/level1/test_wizard_js_logic.py`
        (`test_step4_finish_resets_modify_without_save_before_reload`,
        `test_config_summary_displays_media_url_template`) — all 3 written and confirmed red before
        implementation. `php -l`/`node --check` clean on both files. Full `tests/level1/` suite: 1138 passed /
        8 failed — exact pre-existing baseline, +3 new tests, 0 regressions.

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

**Corrected 2026-09-23 — the signature originally drafted here does not exist.** `cmd::byLogicalId($_logical_id,
$_type = null)` (Jeedom core `cmd.class.php:214`) has no eqLogic-scoping parameter at all and returns an **array**
of every matching cmd across every equipment — the assumed three-arg `(string $logicalId, int|string $eqLogicId,
bool $exception = false)` form was never real, and both original call sites silently misbehaved instead of
throwing (see Task 4.5). The correct API for "this command, on this one equipment" is
`cmd::byEqLogicIdAndLogicalId($_eqLogic_id, $_logicalId, $_multiple = false, $_type = null, $_eqLogic = null)`
(`cmd.class.php:385`) — with `$_multiple = false` (default) it returns a single cmd object, or `false` when not
found. This is the same lookup `eqLogic::getCmd($type, $logicalId)` uses internally. Null-check with
`!is_object($result)` (not `=== null` — a not-found result is `false`) — never let a missing command throw on
the alarm path (AC5).

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
  `level1-test-baseline-failures`, `jeedom-verify-core-api-signatures`, `prefer-tests-over-live-trial-and-error`,
  `frigate-manual-event-api-no-mqtt`
- Task 6's reverse-proxy reference pattern: `/Users/herve.lehoux/dev-hlx/pailly-proxified/etc/caddy/Caddyfile`
  (the `cameras.lehoux.net` vhost, lines ~450-523) — a separate repo, not part of this codebase

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

**Task 5** (added 2026-09-23, after two live validation attempts on Tasks 1-3/4 surfaced a second gap): strict
TDD, consulted `/sia-dc09-expert` against the spec text before touching code rather than trusting the
zone-in-`[Data]` precedent by analogy. Confirmed via the spec's own message template
(`docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md:538`,
`<"id"><seq><Rrcvr><Lpref><#acct>[<pad>|...data...][x…data…]<timestamp>`) that `[V...]` is its own bracket
block (§5.5.1.8), never merged into `[Data]` (§5.5.1.7) the way the existing `zone` handling does — a
pre-existing deferred test block in `test_sia_protocol.py` (`test_extended_data_mac_address_structure` et al.,
"documents expected structure for future v1.1 implementation") already encoded this same separate-bracket
convention for M/N/A identifiers, confirming the design independently. `_format_extended_data_field()` reads
the same `extended_data` dict `_format_data_field()` receives (just a different key, `"media_url"`) rather than
adding a new parameter to `encode_message()` — kept the existing dict-based extension point instead of growing
the function signature. Level 1 tests written first and confirmed RED (`AttributeError: no attribute
'_format_extended_data_field'`), then Level 2 tests written and confirmed RED
(`TypeError: EventItem.__init__() got an unexpected keyword argument 'media_url'`), before any implementation
code was touched.

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
  Awaiting Herve's verification of: zone mapping shows the new single-camera dropdown with a real Frigate
  camera; an alarm fired while Frigate has an active person detection carries a working snapshot URL in the
  SIA frame's `[V...]` field (protocol inspector); an alarm fired with no active detection sends normally with
  no `media_url` and no delay.
- **Live validation attempt #1 (2026-09-23) found a real bug — see Task 4.5.** `cmd::byLogicalId()` does not
  take an eqLogic-scoping argument in Jeedom core and returns an array, not a single cmd; both call sites
  (`_resolveFrigateSnapshotUrl()` and `getFrigateCameras`) were fixed to use
  `cmd::byEqLogicIdAndLogicalId($eqLogicId, $logicalId)` instead, confirmed against
  `jeedom/core/core/class/cmd.class.php` (`byLogicalId` at line 214, `byEqLogicIdAndLogicalId` at line 385) and
  the same pattern already used by `eqLogic::getCmd()`. Level 1 tests updated accordingly; full suite back to
  the 8-failure baseline (0 regressions). Re-push done; Task 4 re-validation still pending.
- **Task 5 complete (2026-09-23)**: the daemon never encoded `media_url` into the actual SIA wire frame, in
  any story — confirmed a second, larger gap on live attempt #2 (Task 4.7). `EventItem` gained a `media_url`
  field, `_queue_consumer()` now threads it from the queue payload, `_build_event_frame()` adds it to
  `extended_data`, and `sia_protocol.py` gained `_format_extended_data_field()` producing the `[V...]` block
  per SIA DC-09 §5.5.1.8, inserted between the data field and the timestamp. TDD red-first throughout (6 new
  Level 1 tests, 3 new Level 2 tests exercising the real `_build_event_frame()` path, not mocked). Full
  `tests/level1/`: 1122 passed / 8 failed (baseline, +6 new, 0 regressions — confirmed via `git stash` diff).
  Full `tests/level2/`: 334 passed / 6 failed (baseline, +3 new, 0 regressions — same method).
  `pylint --disable=all --enable=E` clean on `daemon.py` and `sia_protocol.py`. Task 4's remaining live
  re-validation (4.8) can now proceed — this is the first attempt where the `[V...]` field has any chance of
  actually appearing in the protocol inspector.
- **Live validation attempt #3 (2026-09-23) found a third gap — see Task 4.9.** `[V...]` appeared correctly
  (Task 5 confirmed working) but carried `/plugins/frigate/data/vigi_sud-est/<id>_snapshot.jpg` — a Jeedom-local
  path, useless to an external CSR. Investigated Herve's own `pailly-proxified` reverse-proxy setup as the
  generalized reference pattern (see ADR-17 amendment); Herve's explicit call: stop reading `info_url_snapshot`
  entirely, build `media_url` from a configurable template (literal placeholder credentials only, never a real
  secret) + the Frigate `event_id`.
- **Task 6 complete (2026-09-23)**: new `siaDC09Cmd::_buildFrigateMediaUrl()` (private static, pure
  `parse_url()`-based string logic, zero Jeedom dependency) inserts `api/events/{event_id}/snapshot.jpg` into
  the template's path, before any existing query string, then reassembles the full URL — verified against both
  of Herve's example forms (userinfo and query-token). `_resolveFrigateSnapshotUrl()` swapped its
  `info_url_snapshot` read for `info_id` + the new `frigate_media_url_template` eqLogic config; `getFrigateCameras`
  swapped its filter the same way. New wizard field in Step 3, same `<input type="password">` convention as
  `encryption_key` — no JS changes needed. TDD red-first: because `_buildFrigateMediaUrl()` has zero Jeedom
  dependency, its real extracted method body is executed directly via `php` in the tests (no `core.inc.php`
  bootstrap) for genuine behavioral verification of the tricky path-vs-query reassembly, not just source-text
  regex. Full `tests/level1/`: 1135 passed / 8 failed — exact baseline, +13 new tests, 0 regressions (one
  incidental pre-existing regression in `test_wizard_ajax_contracts.py`, caught and fixed in the same pass).
- **Task 7 complete (2026-09-23)** — three UI findings from Herve testing Task 6's wizard changes live: (1)
  `frigate_media_url_template` was `type="password"`, wrong since it never holds a real secret — changed to
  `type="text"`; (2) clicking "Terminer" triggered a spurious browser "unsaved changes" confirmation before
  the summary appeared — traced to Jeedom core's global `modifyWithoutSave` dirty-flag (set by
  `core/js/plugin.template.js` on any `.eqLogicAttr` change, never reset by `bt_step4Finish`'s own direct
  `jeedom.eqLogic.save()` call) — fixed by resetting both `window.modifyWithoutSave` and
  `jeeFrontEnd.modifyWithoutSave` before `reload()`, mirroring Jeedom core's own post-save reset pattern
  (`utils.js:103-104`/`221-222`); (3) the connection summary omitted the media URL template — added, with an
  empty-state fallback. 3 new Level 1 tests, written and confirmed red before implementation. Full
  `tests/level1/`: 1138 passed / 8 failed — exact baseline, +3 new tests, 0 regressions.

### File List

| File | Change |
|------|--------|
| `core/class/siaDC09Cmd.class.php` | Added `_resolveFrigateSnapshotUrl()`; wired conditional `media_url` into `execute()`'s alarm-trigger payload. Fixed (2026-09-23, live-validation bug): swapped the non-existent scoped `cmd::byLogicalId()` call for `cmd::byEqLogicIdAndLogicalId()`. Task 6 (2026-09-23): swapped the `info_url_snapshot` read for `info_id` + new `frigate_media_url_template` config; added `_buildFrigateMediaUrl()`. |
| `core/ajax/siaDC09.ajax.php` | Added `getFrigateCameras` action; deleted `getCameraCommands` (dead code, no remaining callers). Fixed (2026-09-23, same bug): swapped `cmd::byLogicalId()` for `cmd::byEqLogicIdAndLogicalId()`. Task 6 (2026-09-23): swapped its `info_url_snapshot` filter check for `info_id`. |
| `desktop/php/siaDC09.php` | Step 3 zone table: merged two camera/media columns into one "Caméra Frigate" column; added `#siaDC09-step3-nocamera` warning banner. Task 6 (2026-09-23): added the `frigate_media_url_template` field above the zone table. Task 7 (2026-09-23): that field changed from `type="password"` to `type="text"` (never holds a real secret). |
| `desktop/js/siaDC09.js` | `saveEqLogic()`, `siaDC09_loadZoneData()`, `siaDC09_loadZoneTable()`, `siaDC09_buildZoneRow()`, `siaDC09_populateConfigSummary()` updated for the single-camera schema (`frigate_camera_eqlogic_id`/`frigate_camera_label`) and the new `getFrigateCameras` AJAX action. Task 7 (2026-09-23): `bt_step4Finish`'s success callback resets `window.modifyWithoutSave`/`jeeFrontEnd.modifyWithoutSave` before `reload()`; `siaDC09_populateConfigSummary()` now displays `frigate_media_url_template`. |
| `tests/level1/test_frigate_snapshot_resolution.py` | New — structural tests for `_resolveFrigateSnapshotUrl()`, `getFrigateCameras`, and the conditional `media_url` wiring in `execute()`. Updated (2026-09-23) to assert `cmd::byEqLogicIdAndLogicalId()` instead of the non-existent scoped `byLogicalId()`, plus a new negative assertion forbidding `byLogicalId(` in both call sites. Task 6 (2026-09-23): 15 new tests — real-execution coverage of `_buildFrigateMediaUrl()` via a `php` subprocess harness, plus `info_id`/`frigate_media_url_template` assertions replacing `info_url_snapshot`. |
| `tests/level1/test_wizard_js_logic.py` | Updated 2 tests that asserted on the deleted `camera_action_cmd_id`/`media_url_cmd_id`/labels JS fields to assert on `frigate_camera_eqlogic_id`/`frigate_camera_label` instead. Task 7 (2026-09-23): 2 new tests for the `modifyWithoutSave` reset and the connection summary's media URL display. |
| `tests/level1/test_wizard_ajax_contracts.py` | Replaced the obsolete 6-test "getCameraCommands Action" section with a 5-test "getFrigateCameras Action" section. Docstring corrected (2026-09-23) to name `byEqLogicIdAndLogicalId`. Task 6 (2026-09-23): fixed the `info_url_snapshot`-substring assertion (incidental regression) to assert `info_id` plus a negative assertion. |
| `tests/level1/test_wizard_config_key_consistency.py` | `_AJAX_ACTIONS`: `getCameraCommands` → `getFrigateCameras`. |
| `resources/siadc09d/daemon.py` | Task 5 (2026-09-23): added `media_url` field to `EventItem`; `_queue_consumer()`'s `EventItem(...)` construction now passes `media_url=event_payload.get("media_url")`; `_build_event_frame()` adds `media_url` to `extended_data` when present. |
| `resources/siadc09d/sia_protocol.py` | Task 5 (2026-09-23): added `_format_extended_data_field()` (SIA DC-09 §5.5.1.8 Verification "V" block); wired into `encode_message()`'s `message_core_str` between `data_field` and `timestamp_str`. |
| `tests/level1/test_sia_protocol.py` | Task 5 (2026-09-23): 6 new tests for `_format_extended_data_field()` and `encode_message()`'s field ordering, written red-first. |
| `tests/level2/test_sm2_frame_building.py` | Task 5 (2026-09-23): 3 new tests exercising the real `_build_event_frame()` path with `EventItem(media_url=...)`, written red-first. |
| `scripts/frigate_force_detection.php` | New (2026-09-23, hors story/hors plugin livré — même statut que `frigate_latency_probe.py`): force `info_detect_person`/`info_url_snapshot` sur un eqLogic donné, pour valider 14-1 sans accès physique à la caméra (l'API manuelle Frigate ne publie jamais sur MQTT events/reviews). |
| `tests/level1/test_wizard_php_structure.py` | Task 7 (2026-09-23): new test asserting `frigate_media_url_template` is `type="text"`, never `type="password"`. |

## Change Log

| Date | Change |
|------|--------|
| 2026-09-22 | Story created from ADR-17 (Option A, majority-case-only Frigate snapshot attachment), following an adversarial review and a Winston/Amelia/John party-mode architecture discussion. |
| 2026-09-22 | Tasks 1-3 implemented: zone mapping simplified to a single Frigate-camera pick, `media_url` resolution wired into the alarm-trigger path, Level 1 tests green (0 regressions). Task 4 (live host validation) pending push + Herve's verification. Status `ready-for-dev → in-progress`. |
| 2026-09-23 | Live validation attempt #1 (Herve, real alarm on a manually-created Frigate event) found `cmd::byLogicalId()` misuse — the signature assumed in Dev Notes doesn't exist in Jeedom core, causing a fatal-avoided-by-catch "execCmd() on array" warning and silent `media_url` loss, plus an equivalent silent over-inclusion bug in `getFrigateCameras`. Fixed both call sites to `cmd::byEqLogicIdAndLogicalId()`; Level 1 tests updated; suite back to the 8-failure baseline. Task 4 re-validation (4.2-4.4) still pending. |
| 2026-09-23 | Live validation attempt #2 (Herve, using `scripts/frigate_force_detection.php` to force `info_detect_person`/`info_url_snapshot` — Frigate's manual event API confirmed, via its own source, to never trigger Frigate's MQTT events/reviews topics, so it can't drive Jeedom's real pipeline): PHP resolver worked, but the SIA frame received by the CSR held no `[V...]` field. Traced to a second gap, entirely in the Python daemon: `EventItem`/`_build_event_frame()`/`_format_data_field()` never carried or encoded `media_url` at all — this was never implemented, in any story, not a regression. Added Task 5 (daemon-side `[V...]` encoding, AC7) with Level 1 + Level 2 test tasks up front, per Herve's explicit direction to stop relying on live trial-and-error for this and cover it in automated tests before the next live attempt. Status stays `in-progress`; Task 4's remaining live re-validation (4.8) now depends on Task 5 shipping first. |
| 2026-09-23 | Task 5 implemented via `bmad-dev-story`, strict TDD (consulted `/sia-dc09-expert` against the spec text first): `EventItem` gained `media_url`, threaded through `_queue_consumer()` to `_build_event_frame()`, encoded by new `sia_protocol.py::_format_extended_data_field()` as a `[V...]` block per §5.5.1.8 — its own bracket, inserted between the data field and the timestamp, never merged into the zone-carrying `[Data]` block. 6 new Level 1 + 3 new Level 2 tests, all written and confirmed red before implementation. Full suites: 1122/8 (level1) and 334/6 (level2) — both exactly baseline+new, 0 regressions (confirmed via `git stash` diff). Task 4.8 (live re-validation) can now proceed. |
| 2026-09-23 | Live validation attempt #3 (Herve): `[V...]` appeared (Task 5 confirmed working) but carried a Jeedom-local cached path (`info_url_snapshot`'s own design), unusable by an external CSR. Investigated Herve's `pailly-proxified` Caddy setup (`cameras.lehoux.net` vhost) as the generalized reference pattern — a static, pre-shared credential embedded in the URL, never a per-event dynamic token. Herve's explicit call: siaDC09 never sees or transmits a real secret; it stores only a URL template with literal placeholder tokens, and builds `media_url` from that template + the Frigate `event_id` (`info_id`), never `info_url_snapshot` again. Documented in the ADR-17 amendment. Added Task 6, implemented via `bmad-dev-story`, strict TDD: new `_buildFrigateMediaUrl()` (pure `parse_url()` logic, zero Jeedom dependency — let its real extracted body run directly via `php` in tests for genuine behavioral verification of both template forms and the path-before-query ordering guard); `_resolveFrigateSnapshotUrl()`/`getFrigateCameras` swapped to `info_id`; new wizard field, no JS needed. Full `tests/level1/`: 1135/8 — exact baseline, +13 new, 0 regressions. Task 4.10 (live re-validation with the new URL shape) still pending. |
| 2026-09-23 | Herve tested Task 6's wizard changes live and reported 3 UI findings. Added Task 7, implemented via `bmad-dev-story`, TDD red-first: media URL template field un-masked (`type="text"`, never held a real secret); `bt_step4Finish` no longer triggers a spurious browser "unsaved changes" prompt on Terminer (Jeedom core's `modifyWithoutSave` dirty-flag now reset before `reload()`, traced to `jeedom/core/desktop/common/js/utils.js`/`plugin.template.js`); connection summary now displays the media URL template. 3 new Level 1 tests. Full `tests/level1/`: 1138/8 — exact baseline, +3 new, 0 regressions. |
