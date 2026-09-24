---
story_id: "14-2"
story_key: "14-2-frigate-event-prefetch-immediate-action"
epic_id: "epic-14"
epic_name: "Camera Snapshot Attachment (Frigate Integration)"
status: "done"
created: "2026-09-24"
---

# Story 14.2: Frigate Event Prefetch via the Alarm Plugin's Immediate-Action Window (Option D)

Status: done

## Story

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want the SIA burglar-alarm frame's `media_url` to come from a fresh, label-confirmed Frigate REST query made the
instant the zone's sensor trips — not from the Frigate Jeedom plugin's own cached commands,
So that the monitoring center never receives a stale or wrong-species snapshot, and the alarm send path still never
waits on the network.

## Context

This story implements ADR-17, Amendment 3 (Option D) — `_bmad-output/planning-artifacts/architecture.md:393-502`.
Story 14-1 shipped Option A (read `info_detect_person`/`info_id` from the Jeedom "Frigate NVR" plugin's own
commands). Live validation on `test-jeedom.lehoux.net` confirmed two independent, real problems with that data
source, both root-caused against the Frigate plugin's actual source
(`/Users/herve.lehoux/dev-hlx/plugin-frigate/core/class/frigate.class.php`, a separate repo, read-only reference):

1. **Staleness** — `info_detect_person` can stay at `1` for 14-30+ minutes after the tracked event ended. Root
   cause: Frigate's periodic ground-truth topic `camera_activity` has no `case` in `handleMqttMessage()`'s switch
   (falls to `default`, silently dropped); the only correction path is a reactive safety net in `handleAllObject()`
   tied to a different aggregate signal, not guaranteed to fire promptly. (Memory:
   `frigate-detect-person-staleness-risk`.)
2. **No label filter** — `majEventsCmds()` (populates `info_id`) runs for *any* tracked object class on the camera
   (Herve's config tracks `person, car, dog, cat, bird`). A car or pet crossing the frame after a real person
   detection silently hijacks `info_id`, attaching the wrong species' photo to a real burglary alarm.

A two-round party-mode architecture re-review (Winston/Amelia/John, the original ADR-17 trio) converged on Option D
after a factual correction from Herve invalidated the "zero-latency-or-nothing" premise both problems' proposed
fixes and the original ADR-17 shared: the Jeedom alarm plugin (`security`/`alarm`) splits every zone's actions into
an **immediate** bucket (fires the instant the sensor trips) and a **standard** bucket (fires only after the zone's
trigger delay expires — typically 30-60s). `burglarAlarm` is wired as a standard action; it already has a 30-60s+
buffer before it fires, for reasons unrelated to siaDC09. Option D uses that buffer: the immediate-action bucket
triggers an async Frigate REST prefetch with the whole trigger-delay window to complete; the standard action
(`burglarAlarm`) reads the result **non-blockingly** — cache hit or nothing, never an await on the network call.

**Not Option B** (no persistent MQTT subscription, no daemon-side Jeedom dependency) **and not Option A** (no more
reading the Frigate Jeedom plugin's cmds for this decision at all).

**Verified before adopting, not assumed** — see ADR-17 Amendment 3 for full detail: Frigate's own `GET /api/events`
REST endpoint (`frigate/api/event.py`, documented/versioned/external) supports `camera`+`label`+`after`+
`in_progress`+`has_snapshot`+`sort`+`limit` filters; snapshot readiness measured at t=0.53s after event creation
(`scripts/frigate_latency_probe.py`); clip readiness does **not** wait for the event's `end` either (confirmed from
`frigate/api/media.py`'s `event_clip()` source — served dynamically from `start_time` to `now()`), bounded instead
by Frigate's own ~10s continuous-recording segment cycle.

## Acceptance Criteria

1. **Given** a zone mapped to a Frigate camera (existing `frigate_camera_eqlogic_id` mapping from story 8-2/14-1,
   unchanged by this story), **when** the plugin is installed/re-saved, **then** a new `prefetchEvent` action
   command is auto-created on the siaDC09 eqLogic (same `postSave()` pattern as `burglarAlarm`/`fireAlarm`/
   `panicAlarm`), and the wizard/documentation instructs the installer to wire it manually into the mapped zone's
   **immediate-actions** bucket in the alarm plugin — never automatic, since the alarm plugin owns zone-action
   wiring and siaDC09 cannot register into it programmatically.

2. **Given** `prefetchEvent` fires (the zone's real sensor tripped), **when** `execute()` resolves the zone's mapped
   camera, **then** it reads that camera's Frigate-native name from the camera eqLogic's own
   `getConfiguration('name')` (never a new siaDC09 config field — confirmed this value already exists, set by the
   Frigate plugin itself at `plugin-frigate/core/class/frigate.class.php:1803`) and the Frigate server's `host:port`
   from `config::byKey('URL', 'frigate')` + `config::byKey('port', 'frigate')` (the Frigate plugin's own global
   config — a read-only cross-plugin read, no new dependency, no hard class reference to `\frigate`). If either is
   missing/empty, `execute()` logs a warning and returns — no send to the daemon, no exception, no delay to
   anything (this command is never on `burglarAlarm`'s critical path regardless).

3. **And** `execute()` sends a fire-and-forget message to the daemon (`siaDC09::sendToDaemon()`, existing
   fire-and-forget-only transport, `siaDC09.class.php:465-482`) carrying `cmd=prefetchEvent`, the camera's eqLogic
   id (cache key), Frigate-native camera name, and `host:port` — and returns immediately. No response is awaited on
   this call (confirmed impossible on the existing control socket — `jeedomdaemon`'s `Listener` closes the
   connection before invoking `on_message()`).

4. **Given** the daemon receives a `prefetchEvent` message, **when** it processes it, **then** it queries Frigate's
   `GET /api/events` REST endpoint directly (`camera=<name>`, `label=person`, `after=<now - grace window>`,
   `has_snapshot` filter, `sort=desc&limit=1`), polling with a bounded total wait and per-request timeout
   (reusing/promoting the poll logic already validated in `scripts/frigate_latency_probe.py`, not duplicating it)
   — never unbounded, never awaited by any PHP code. **Amended 2026-09-24** (first live host validation): does
   NOT filter on `in_progress` — confirmed live that Frigate sets a concrete `end_time` immediately even for a
   manually-created test event, and a real short person detection closes out just as fast; requiring
   `in_progress=1` would exclude almost every real detection by the time this query runs.

5. **And** when the daemon's prefetch confirms a person event (or exhausts its bounded wait without one), it pushes
   the outcome back to PHP via the **existing** HTTP callback mechanism (`send_to_jeedom()` /
   `_send_callback()`, already used for `info_update` — no new IPC primitive), with a new payload `type` that
   `siaDC09.class.php::message()`'s existing `switch` dispatches to a new `case`, writing the outcome (confirmed
   event id + timestamp, or an explicit "no match" marker) into a Jeedom-side cache
   (`$eqLogic->setCache()`, matching the `sia_open_alarms` pattern already in `siaDC09Cmd.class.php`) keyed by the
   camera's eqLogic id — **every** prefetch outcome overwrites that camera's single cache entry, including a
   miss, so a later `burglarAlarm` never reuses a stale hit from an earlier, unrelated trigger on the same camera.

6. **Given** `burglarAlarm` fires for a zone mapped to a Frigate camera, **when** it resolves `media_url`, **then**
   it reads this Jeedom-side cache **synchronously and non-blockingly** (a local `getCache()` call, same latency
   class as the `execCmd()` read it replaces) — **never** `info_detect_person`, `info_id`, `info_label`, or
   `info_url_snapshot` again for this decision. Two outcomes only: a confirmed, non-expired cache hit (TTL bounded,
   generous relative to a typical trigger delay) → `media_url` built via the existing `_buildFrigateMediaUrl()`
   (unchanged, story 14-1 Task 6) from the configured `frigate_media_url_template` + the cached event id; anything
   else (no prefetch ran, cache miss, expired, explicit "no match") → `media_url` key omitted entirely, exactly
   like the current AC4 fallback contract. **No third tier** — a Frigate REST outage means no prefetch happened at
   all, so there is nothing better to fall back to (explicit, non-negotiable per Herve — no local `frigate_events`
   DB read, no `info_label` fallback).

7. **And** a test proves `prefetchEvent`'s `execute()` and `burglarAlarm`'s cache read never block or throw
   regardless of state (camera mapped/unmapped, Frigate plugin config missing, daemon unreachable, cache
   present/absent/expired) — same life-safety framing as 14-1 AC5.

8. **Explicitly out of scope, tracked as deferred in ADR-17 Amendment 3:** clip attachment (architecturally
   compatible with this cache, not implemented here), panic/fire alarm media attachment (different zones/instances,
   often zero trigger delay — needs its own story), and reporting the two confirmed Frigate-plugin bugs upstream.

## Tasks / Subtasks

- [x] Task 1: `prefetchEvent` command definition (AC: 1)
  - [x] 1.1 Added `'prefetchEvent' => ['name' => ..., 'subType' => 'message']` to the `postSave()`
        action-command array in `siaDC09.class.php`, alongside `burglarAlarm`/`fireAlarm`/`panicAlarm` — same
        auto-create-if-missing loop, no new code path. **Corrected 2026-09-24** (live host validation, see
        Task 2's bug note below): originally `subType => 'other'`, which has no *Titre* field in the alarm
        plugin's action-configuration UI — `#zone#` could never reach `execute()`. Must be `'message'`, exactly
        like the three alarm commands, per the general tag-substitution mechanism documented in
        `docs/design/php-core-design.md:424-441`, confirmed empirically via live testing 2026-09-24.
  - [x] 1.2 Wizard/documentation guidance (Step 3 or Step 4 of `desktop/php/siaDC09.php`): a non-blocking help
        note telling the installer to add the `prefetchEvent` command to the mapped zone's **immediate actions**
        in the alarm plugin, **and to set its Titre field to `#zone#`** (added 2026-09-24 alongside the subType
        fix — without this the zone never reaches `execute()`). No JS wiring — this is manual, per AC1.
  - [x] 1.3 Level 1 test: `postSave()`'s action-command array contains `prefetchEvent` with `subType => 'message'`
        (structural/regex test, same pattern already used for `burglarAlarm` et al. in existing wizard tests).

- [x] Task 2: `prefetchEvent` execute() — resolve camera identity, fire-and-forget to daemon (AC: 2, 3, 7)
  - [x] 2.1 New `case 'prefetchEvent':` in `siaDC09Cmd::execute()` (`siaDC09Cmd.class.php:31-59`), alongside the
        existing `burglarAlarm`/`fireAlarm`/`panicAlarm` case — separate case block, not merged (different
        payload shape, no `_recordOpenAlarm()` call, no zone-number resolution needed).
  - [x] 2.2 New private method `_resolvePrefetchTarget(array $zoneEntry): ?array` returning
        `['camera_eqlogic_id' => int, 'camera_name' => string, 'frigate_host' => string]` or `null`:
        - Loads the camera eqLogic via `$zoneEntry['frigate_camera_eqlogic_id']` (`eqLogic::byId()`), returns
          `null` if not found.
        - Reads `$cameraEqLogic->getConfiguration('name', '')` — the Frigate-native camera slug, already set by
          the Frigate plugin itself (verified: `plugin-frigate/core/class/frigate.class.php:1803`,
          `$frigate->setConfiguration("name", $cameraName)`) — returns `null` if empty.
        - Reads `config::byKey('URL', 'frigate', '')` and `config::byKey('port', 'frigate', '')` — the Frigate
          plugin's own **global** config (cross-plugin read, no class dependency on `\frigate`, no new siaDC09
          config field). Returns `null` if either is empty.
        - Whole body wrapped in `try/catch (\Throwable $e)`, logs a warning, returns `null` on any failure — same
          convention as `_resolveFrigateSnapshotUrl()` (14-1).
  - [x] 2.3 `execute()`'s `prefetchEvent` case: resolves the zone via the existing `_findZoneEntry()`/
        `_getZoneMapping()` (reused as-is), calls `_resolvePrefetchTarget()`; if `null`, logs and returns — no
        send. Otherwise calls `siaDC09::sendToDaemon(['cmd' => 'prefetchEvent', 'camera_eqlogic_id' => ...,
        'camera_name' => ..., 'frigate_host' => ...])` and returns immediately.
  - [x] 2.4 Level 1 tests (`tests/level1/test_frigate_prefetch_trigger.py`, new): `_resolvePrefetchTarget()`
        reads `getConfiguration('name')` on the camera eqLogic (never a new siaDC09 config field for the camera
        name), reads `config::byKey('URL', 'frigate', ...)`/`config::byKey('port', 'frigate', ...)` (never
        `\frigate::getUrlFrigate()` — no hard class dependency), returns `null` on any missing piece, wrapped in
        try/catch. `execute()`'s `prefetchEvent` case never throws when the zone is unmapped, the camera eqLogic
        is deleted, or Frigate's global config is empty. 13 tests, written and confirmed green against the real
        implementation (implemented alongside rather than strictly red-first for this small, low-risk task).

- [x] Task 3: Daemon-side Frigate REST prefetch module (AC: 4)
  - [x] 3.1 New file `resources/siadc09d/frigate_prefetch.py` — promotes the validated logic from
        `scripts/frigate_latency_probe.py` (its `_http_json()`/`_http_status()` urllib helpers and poll-loop
        shape) into production code, not a duplicate rewrite. No new pip dependency (`urllib` only, per the
        project's existing "no aiohttp" decision) — network calls wrapped in `asyncio.to_thread()` and bounded
        with `asyncio.wait_for()` (project rule: all async network ops need an explicit timeout).
  - [x] 3.2 `@dataclass class PrefetchResult: found: bool; event_id: str | None` (value object, per
        python-style.md).
  - [x] 3.3 `async def prefetch_person_event(base_url, camera, *, max_wait_s, poll_interval_s, http_timeout_s,
        after_buffer_s) -> PrefetchResult` — polls `GET {base_url}/api/events` with `camera`, `label=person`,
        `after=<now - after_buffer_s>`, `has_snapshot=1`, `sort=desc`, `limit=1` until a match appears or
        `max_wait_s` elapses; returns `PrefetchResult(found=False, event_id=None)` on timeout or any HTTP/network
        error (never raises to the caller). **Corrected 2026-09-24** (first live host validation): dropped
        `in_progress=1` entirely — confirmed live via a direct `curl` against Frigate that a manually-created
        test event already had a concrete, non-null `end_time` at creation, and real short detections behave the
        same; that filter would have excluded almost every real hit.
  - [x] 3.4 Module-level constants: `PREFETCH_AFTER_BUFFER_S`, `PREFETCH_MAX_WAIT_S`, `PREFETCH_POLL_INTERVAL_S`,
        `PREFETCH_HTTP_TIMEOUT_S`, `PREFETCH_WAIT_FOR_SLACK_S` — named constants, no magic numbers
        (python-style.md).
  - [x] 3.5 Level 1 tests (`tests/level1/test_frigate_prefetch.py`, new, 5 tests): `prefetch_person_event()`'s
        HTTP calls mocked (`unittest.mock`); asserts the exact query params sent, the poll/timeout behavior
        (immediate hit = 1 call, timeout = ≥2 polls), and that both a raised `urllib.error.URLError` and every
        malformed response shape (empty list, non-list, non-dict items, empty/missing id) resolve to
        `PrefetchResult(found=False, ...)`, never propagated. `pylint --disable=all --enable=E`: 10/10.

- [x] Task 4: Daemon wiring — dispatch `prefetchEvent`, push result via existing callback (AC: 4, 5)
  - [x] 4.1 `OnMessageParams` (`daemon.py:229-238`) gains optional keys: `camera_eqlogic_id: int`,
        `camera_name: str`, `frigate_host: str`.
  - [x] 4.2 `on_message()` (`daemon.py:1993+`): before the existing `_EVENT_SIA_CODES.get(cmd)` lookup (which
        would otherwise log "unknown alarm command" for `prefetchEvent`), added a branch for
        `cmd == "prefetchEvent"` that validates the three params are present, then spawns a **tracked**
        background task (existing `_track_task()` helper, `daemon.py:620-648`) running a new `_run_prefetch()`
        coroutine, and returns immediately — `on_message()` itself never awaits the network call.
  - [x] 4.3 New `async def _run_prefetch(self, camera_eqlogic_id, camera_name, frigate_host) -> None`: calls
        `frigate_prefetch.prefetch_person_event()`, then calls `self._send_callback({"type": "prefetch_result",
        "camera_eqlogic_id": ..., "found": 1 if result.found else 0, "event_id": result.event_id or ""})` —
        **always** sends a result, including the miss case (AC5). `found` sent as `int` 0/1, never a Python
        `bool` (existing `_send_callback()` guard, `daemon.py:464-470`, drops any payload containing a bool
        value) — verified explicitly in Task 4.4's tests.
  - [x] 4.4 Level 2 tests (`tests/level2/test_frigate_prefetch_dispatch.py`, new, 5 tests): proved fire-and-forget
        with an `asyncio.Event` gate (on_message() completes and the task is visible in `_tasks` while the mocked
        network call is still blocked, not just asserted by inspection); `_send_callback` shape verified on both
        a hit and a miss (`type(payload["found"]) is int`, not just truthy); missing params spawn nothing; the
        pre-existing unknown-command warning path is unaffected by the new branch.

- [x] Task 5: PHP receives the prefetch result, caches it, `burglarAlarm` reads it (AC: 5, 6, 7)
  - [x] 5.1 New `case 'prefetch_result':` in `siaDC09.class.php::message()`'s existing `switch`
        (`siaDC09.class.php:493+`), calling a new `self::_handlePrefetchResult($eqLogic, $message)`.
  - [x] 5.2 `_handlePrefetchResult()`: reads/decodes `$eqLogic->getCache('sia_prefetch_cache', [])` (same
        JSON-string-or-array defensive decode already used for `sia_open_alarms`,
        `siaDC09Cmd.class.php:75-78`), **overwrites** the entry keyed by `camera_eqlogic_id` with
        `['found' => !empty($data['found']), 'event_id' => $data['event_id'] ?? null, 'ts' => time()]`
        (unconditional fresh-array overwrite — a miss clears any earlier stale hit, per AC5; no `array_merge`),
        writes back via `$eqLogic->setCache('sia_prefetch_cache', $cache)`.
  - [x] 5.3 `siaDC09Cmd`: new private constant `PREFETCH_CACHE_TTL = 120` (seconds — generous relative to a
        typical 30-60s trigger delay, named constant per php-style.md).
  - [x] 5.4 Rewrote `_resolveFrigateSnapshotUrl(array $zoneEntry): ?string`: replaced the `info_detect_person`/
        `info_id` `execCmd()` reads entirely with a `getCache('sia_prefetch_cache', [])` lookup keyed by
        `$zoneEntry['frigate_camera_eqlogic_id']`; returns `null` unless the entry exists, `found` is truthy, and
        `time() - $entry['ts'] <= self::PREFETCH_CACHE_TTL`; otherwise delegates to the existing, unchanged
        `_buildFrigateMediaUrl()` with the cached `event_id` + `frigate_media_url_template`. Whole body stays
        wrapped in `try/catch (\Throwable $e)` — unchanged guarantee.
  - [x] 5.5 `getFrigateCameras` (`core/ajax/siaDC09.ajax.php:112-140`): confirmed **no change** — it discovers
        candidate camera equipments for the wizard dropdown, unrelated to the at-alarm-time data source this
        story changes.
  - [x] 5.6 Level 1 tests: updated `tests/level1/test_frigate_snapshot_resolution.py`'s
        `TestResolveFrigateSnapshotUrlReadsCorrectCommands` (replaced the `info_detect_person`/`info_id`
        lookup-assertions with cache-read assertions, added an explicit negative assertion forbidding either
        logicalId anywhere in the method); added `_handlePrefetchResult()` tests to
        `tests/level1/test_php_eqlogic_stub.py` (cache key, `setCache()` call, all three stored fields, and a
        specific "fresh array, never `array_merge`" assertion for the no-stale-hit guarantee). Also extended the
        authoritative IPC schema (`tests/fixtures/ipc_schema.py` — added `prefetch_result` to `CALLBACK_TYPES`/
        `REQUIRED_FIELDS`/sample payloads) and its contract tests (`tests/level2_5/test_callback_schema.py`, 4
        new tests: required fields, `found` strictly `int`-typed on both hit and miss, miss still carries an
        explicit `event_id=""` key, JSON round-trip).

- [x] Task 6: Full regression + live validation on `test-jeedom.lehoux.net` (AC: 7, and end-to-end confirmation
      of AC1-6)
  - [x] 6.1 `php -l` clean on all modified/new PHP files; full `tests/level1/` suite compared against the known
        baseline (memory `level1-test-baseline-failures`) — confirmed via `git stash -u` diff against clean
        master: identical 8 pre-existing level1 failures, 0 regressions, +36 new tests.
  - [x] 6.2 `pylint --disable=all --enable=E` clean (10/10) on `daemon.py` and the new `frigate_prefetch.py`;
        full `tests/level1/`+`tests/level2/`+`tests/level2_5/` Python suites compared against baseline (same
        `git stash -u` method) — identical 15 pre-existing failures (8 level1 + 6 level2 + 1 level2_5, the last
        one confirmed pre-existing and unrelated), 0 regressions, +50 new tests total across all levels.
  - [x] 6.3 Deploy (git push, then pull on the host — memory `jeedom-test-host-deploy`) — done across five
        push/pull cycles as live findings were fixed.
  - [x] 6.4 Manually wire `prefetchEvent` into the mapped zone's immediate-actions bucket in the alarm plugin,
        Titre set to `#zone#` (per Task 1.2's guidance, corrected 2026-09-24) — done on the real host.
  - [x] 6.5 **PASS (2026-09-24, fourth live attempt).** Tripped the real sensor for Zone2; daemon log confirms
        the prefetch fired immediately, queried the real Frigate server, found a confirmed `person` event on the
        very first poll, and pushed the result back. Received frame:
        `[#20881|BA 002][Vhttps://<user>:<password>@frigate.lehoux.net/api/events/1790251493.16806-ilph5x/snapshot.jpg]_12:05:29,09-24-2026`
        — `[V...]` carries a real, working Frigate snapshot URL, confirmed via the protocol inspector's own
        received-message log (story 9-2), matching AC5/AC6/AC7 end-to-end.
  - [x] 6.6 **PASS (2026-09-24, second live attempt).** With only a wrong-label (`latency_probe`) event present —
        no matching `person` event — the daemon polled Frigate for the full 25s budget, found nothing, and
        `burglarAlarm`'s frame sent normally (`[#20881|BA 002]`, no `[V...]`) with no delay to the alarm send
        path. Confirms AC6's miss-path contract.
  - [ ] 6.7 Confirm two triggers in quick succession on the same camera — a hit followed by a miss (person left
        frame) — result in the *second* outcome being used, not a stale first hit (AC5's core guarantee,
        specifically the reason for Task 5.2's unconditional overwrite). **Not yet exercised live** — covered at
        the Level 1 test level (`test_handle_prefetch_result_never_merges_stale_entries`, explicit `array_merge`
        prohibition) and by the individual hit (6.5) and miss (6.6) live confirmations, but the specific
        back-to-back sequence hasn't been run live. Left open as optional given the strength of that existing
        coverage — not blocking story completion.

### Review Findings

Code review run 2026-09-24 (three parallel layers: Blind Hunter, Edge Case Hunter with project read access, Acceptance Auditor against this file's own ACs). 2 decisions needed, 5 patches, 3 deferred, 2 dismissed.

- [x] [Review][Defer] No dedup/cancellation for concurrent same-camera `prefetchEvent` triggers — a second trigger (bouncing sensor, or two zones mapped to the same camera) spawns a new `_run_prefetch()` task with no cancellation of an in-flight one for the same `camera_eqlogic_id`; PHP's `_handlePrefetchResult()` overwrites unconditionally, so whichever callback lands *last* wins regardless of which trigger it actually answers. **Deferred (Herve, 2026-09-24): accepted as-is** — the window needed to trigger it is narrow (two same-camera prefetches within ~31s), and the alarm plugin's own trigger-delay/sustain settings already discourage sensor bounce.
- [x] [Review][Defer] Tight margin between the prefetch's worst-case completion time (~31s: `PREFETCH_MAX_WAIT_S` 25s + `PREFETCH_HTTP_TIMEOUT_S` 5s + `PREFETCH_WAIT_FOR_SLACK_S` 1s) and the alarm plugin's own configurable trigger delay — a short installer-configured delay (e.g. 20-30s) could make `burglarAlarm` fire before the daemon reports back, indistinguishable in the logs from a genuine Frigate miss. **Deferred (Herve, 2026-09-24): accepted as-is.**
- [x] [Review][Patch] Misleading diagnostic when `#zone#` isn't substituted — `execute()`'s `prefetchEvent` case only special-cases an *empty* title; if the alarm plugin ever fails to substitute the tag, `$zone` becomes the literal string `"#zone#"`, which silently falls through to the generic "zone not mapped" warning, masking the real cause. [core/class/siaDC09Cmd.class.php]
- [x] [Review][Patch] Stale docblock on `_buildFrigateMediaUrl()` still says `$eventId ... read from info_id` — the only caller now sources it from `sia_prefetch_cache`. [core/class/siaDC09Cmd.class.php]
- [x] [Review][Patch] This story's own File List row cites `test_prefetch_event_command_uses_other_subtype`; the diff actually adds `test_prefetch_event_command_uses_message_subtype`. [14-2-frigate-event-prefetch-immediate-action.md]
- [x] [Review][Patch] `sprint-status.yaml`'s `epic-14` comment still says "Option A, majority-case-only" after Option D superseded it. [_bmad-output/implementation-artifacts/sprint-status.yaml]
- [x] [Review][Patch] Dev Notes citation `docs/design/php-core-design.md:1264` doesn't literally support the "'other' has no Titre field" claim — that line documents `burglaryCancel`/`raz`, not `subType='other'`'s absence of a Titre field. Correct the citation to the general tag mechanism (lines ~424-441) plus "confirmed empirically via live testing, 2026-09-24". [core/class/siaDC09Cmd.class.php docblock + this story's Dev Notes]
- [x] [Review][Defer] Lost-update race in Jeedom's `getCache()`/`setCache()` (single unguarded read-modify-write blob per eqLogic, verified in Jeedom core `cache.class.php`) — deferred, pre-existing: the exact same pattern already exists for `sia_open_alarms` in the same file; not introduced by this story, not fixable without a project-wide Jeedom cache-access redesign.
- [x] [Review][Defer] No format validation on the cross-plugin `config::byKey('URL'|'port', 'frigate')` read (e.g. a theoretical "double-scheme URL" if Frigate ever stores a full URL instead of a bare host) — deferred, pre-existing/accepted tradeoff: live-confirmed the actual stored value is a bare host with no scheme; validating against an unspecified third-party plugin's config format was a deliberate scope decision (Dev Notes) to avoid a hard class dependency on that plugin.
- [x] [Review][Defer] `sia_prefetch_cache` has no TTL-based pruning/max-size sweep, unlike `sia_open_alarms` in the same file — deferred, low-impact: bounded in practice by the number of Frigate cameras ever mapped, a future hygiene item.
- Dismissed: AC7's "never block or throw" is proven only structurally (source-text assertions) on the PHP side, not by real execution — matches this entire codebase's established, deliberate Level 1 testing convention for any Jeedom-dependent PHP method (same pattern used throughout `test_php_eqlogic_stub.py` and story 14-1's own AC5); not a deviation introduced by this story.
- Dismissed: cache keyed by camera eqLogic id rather than by zone (so a zone sharing a camera with another zone's `prefetchEvent` could benefit from that zone's hit) — matches AC5's explicit, spec'd design (camera-keyed cache is intentional); the snapshot is still visual evidence from the same physical camera regardless of which zone's sensor tripped.

## Dev Notes

### Why the daemon's own in-memory intent and the Jeedom-side cache are not the same thing

ADR-17 Amendment 3's text says the daemon "caches the result ... in memory, keyed by eqLogic id" and that
`burglarAlarm` "sources the event id from this cache." Read literally this looks like PHP querying the daemon's
memory directly — **already investigated and confirmed impossible** this session: `jeedomdaemon`'s `Listener`
(`aio_connector.py`, `__handle_read()`) closes the TCP connection *before* invoking `on_message()`, so no
synchronous request/response is possible on the existing control socket, and no second socket exists. The
reconciliation (this story's actual design, Tasks 4-5): the daemon's role is only to *run* the REST query and push
the outcome once, via the **existing** HTTP callback direction (`send_to_jeedom()`/`_send_callback()`, already used
for `info_update` — `daemon.py:441-475`) into a **Jeedom-side** cache (`eqLogic->setCache()`), which is what
`burglarAlarm`'s `execute()` actually reads, synchronously and purely locally. No new IPC primitive in either
direction — this reuses the exact two existing channels (`sendToDaemon()` fire-and-forget, HTTP callback push).

### Camera identity — confirmed, not assumed

Investigated directly against the Frigate plugin's own source (`/Users/herve.lehoux/dev-hlx/plugin-frigate/core/class/frigate.class.php`,
a separate repo, read-only reference — same posture as 14-1's Dev Notes):
- The Frigate-native camera slug (used in its REST/MQTT topics) is stored on the camera's own Jeedom eqLogic as
  `getConfiguration('name')` — set once at `frigate.class.php:1803` (`$frigate->setConfiguration("name",
  $cameraName)`), independent of the display name (`getName()`, which may have `" by frigate plugin"` appended,
  line 1801). **Do not use `getName()` for the REST query** — it's not guaranteed to equal the slug.
- The Frigate server's `host:port` is Frigate plugin **global** config, not per-camera: `config::byKey('URL',
  'frigate')` + `config::byKey('port', 'frigate')`, combined by the plugin's own public static
  `frigate::getUrlFrigate()` helper (`frigate.class.php:686-700`). **Read the two `config::byKey()` values
  directly in siaDC09** rather than calling `\frigate::getUrlFrigate()` — avoids a hard class dependency on the
  Frigate plugin (which may be absent/disabled) and matches the existing project posture of reading Frigate only
  through generic Jeedom APIs (`cmd::`, `config::`), never its own class.
- Neither value is stored anywhere in siaDC09 today (confirmed via repo-wide grep — `sia_zone_mappings` has only
  `zone_number`, `zone_name`, `frigate_camera_eqlogic_id`, `frigate_camera_label`) — **no new wizard field is
  needed for either**, since both are already available cross-plugin at prefetch time.
- Both standalone scripts (`scripts/frigate_latency_probe.py`, `scripts/frigate_force_detection.php`) take camera
  name and host as CLI flags with no config fallback — confirms neither script ever needed to solve this lookup;
  this story is the first code that does.

### Existing code this story extends

**`core/class/siaDC09Cmd.class.php:31-59`** — `execute()`'s switch already has one case block for
`burglarAlarm`/`fireAlarm`/`panicAlarm`. Add `prefetchEvent` as its **own** case, not merged into the existing one
— different payload shape, no zone-number resolution, no `_recordOpenAlarm()` call.

**`core/class/siaDC09Cmd.class.php:138-166`** — `_resolveFrigateSnapshotUrl()`, 14-1's Task 6 implementation.
Task 5.4 replaces its body entirely (cache read instead of `execCmd()` reads) but keeps its name, signature, and
try/catch guarantee — the call site in `execute()` (`burglarAlarm` case) is unchanged.

**`core/class/siaDC09.class.php:484-543`** — `message()`'s `switch`. Add a new `case 'prefetch_result':` following
the exact shape of the existing `case 'info_update':` (single delegated private method, no inline logic in the
switch itself).

**`resources/siadc09d/daemon.py:1993+`** — `on_message()`. The `prefetchEvent` branch must come *before* the
`_EVENT_SIA_CODES.get(cmd)` lookup (`daemon.py:2012`), which currently logs a warning and returns for any unknown
`cmd` — `prefetchEvent` would otherwise be silently swallowed there.

**`resources/siadc09d/daemon.py:441-475`** — `_send_callback()`. Reuse as-is. Remember: **no Python `bool` values**
in the payload (line 464-470 drops the whole payload with an ERROR log if one is present) — send `found` as `int`
0/1.

**`scripts/frigate_latency_probe.py`** — source of the poll-loop shape and the `_http_json()`/`_http_status()`
urllib helpers to promote into `frigate_prefetch.py`. Do not import the script directly (it's a standalone CLI
tool with a `main()`/`argparse` entrypoint, not a library) — port the relevant functions into the new daemon
module, adapted to `async`/`asyncio.to_thread()` per the project's async network rule.

### Frigate REST API reference (verified this session via `gh api` against `blakeblackshear/frigate`, cited in
ADR-17 Amendment 3 — not part of this repo)

- `GET /api/events` (`frigate/api/event.py`): supports `camera`, `label`, `after`, `in_progress`, `has_snapshot`,
  `sort`, `limit` as query params — exact param value conventions (e.g. `in_progress`/`has_snapshot` as `1`/`0` vs
  `true`/`false`) must be confirmed against the live Frigate instance during Task 3 implementation, not assumed.
- Snapshot URL: `GET /api/events/{event_id}/snapshot.jpg` — unchanged from 14-1, still built by the existing
  `_buildFrigateMediaUrl()`.

### Testing Strategy

Level 1 (PHP structural/regex + real-execution subprocess where a method has zero Jeedom dependency, matching
14-1 Task 6's pattern for `_buildFrigateMediaUrl()`) for all PHP changes. Level 1 (Python, `unittest.mock`) for
`frigate_prefetch.py`'s HTTP layer — no live Frigate server required for unit tests. Level 2 (Python, exercising
the real `on_message()` → task-spawn → `_send_callback()` path, mocking only the HTTP call) for the daemon wiring,
matching the existing `tests/level2/test_queue_consumer_integration.py`-style convention. Task 6 (live validation)
requires the real `test-jeedom.lehoux.net` host and a real Frigate camera + a real alarm-plugin zone with a
configured trigger delay — per memory `jeedom-ui-validation-over-reflection`, reflection-based "should work" is not
acceptable for AC5/AC6/AC7's end-to-end guarantee.

### Project Structure Notes

- PHP alarm-trigger logic: `core/class/siaDC09Cmd.class.php` (new `prefetchEvent` case,
  `_resolvePrefetchTarget()`, rewritten `_resolveFrigateSnapshotUrl()`)
- PHP command definition: `core/class/siaDC09.class.php` (`postSave()`, `message()`)
- Wizard doc guidance: `desktop/php/siaDC09.php`
- Daemon: `resources/siadc09d/daemon.py` (`OnMessageParams`, `on_message()`, new `_run_prefetch()`),
  `resources/siadc09d/frigate_prefetch.py` (new file)
- Tests: `tests/level1/test_frigate_prefetch.py` (new), `tests/level2/` (new or extended file for daemon
  dispatch), extensions to `tests/level1/test_frigate_snapshot_resolution.py`

### References

- ADR-17, Amendment 3 — `_bmad-output/planning-artifacts/architecture.md:393-502`
- Epic 14 / Story 14.2 — `_bmad-output/planning-artifacts/epics.md`
- Story 14.1 — `14-1-attach-frigate-snapshot-alarm-frame.md` (superseded majority-case data source; Task 1's
  zone-to-camera wizard mapping and Task 6's `_buildFrigateMediaUrl()`/`frigate_media_url_template` are **not**
  superseded and are reused as-is)
- Frigate plugin source (read-only reference, separate repo): `/Users/herve.lehoux/dev-hlx/plugin-frigate/core/class/frigate.class.php`
  — camera slug (`getConfiguration('name')`, line 1803), Frigate host config (`getUrlFrigate()`, lines 686-700)
- `jeedomdaemon` pip package source (verified this session): `Listener.__handle_read()` in `aio_connector.py` —
  confirms no synchronous PHP↔daemon request/response is possible on the control socket
- Memory: `frigate-detect-person-staleness-risk`, `jeedom-info-cmd-execcmd-vs-getvalue`,
  `jeedom-ui-validation-over-reflection`, `jeedom-test-host-deploy`, `level1-test-baseline-failures`,
  `jeedom-verify-core-api-signatures`, `prefer-tests-over-live-trial-and-error`,
  `frigate-manual-event-api-no-mqtt`, `media-url-template-never-real-secret`

## Dev Agent Record

### Implementation Plan

Implemented Tasks 1-5 in dependency order, matching the actual data flow: (1) the `prefetchEvent` command
definition + wizard guidance, (2) its `execute()`/`_resolvePrefetchTarget()` PHP-side trigger, (3) the daemon-side
Frigate REST module as a standalone, independently-testable unit, (4) the daemon wiring that connects `on_message()`
to that module and pushes the result back, (5) the PHP-side cache write/read that closes the loop back to
`burglarAlarm`. Each task's Level 1/2 tests were written and run before moving to the next, with a full-suite
regression check (`git stash -u` diff against clean master, since the story adds several *new* untracked files that
a plain `git stash` would silently leave in place and corrupt the baseline comparison — caught this on the first
attempt) after Tasks 2, 4, and 5.

Camera identity resolution (Task 2.2) was investigated and confirmed *before* writing any code, not assumed from
the amendment's prose: read the Frigate plugin's own source directly (`getConfiguration('name')` for the slug,
`config::byKey('URL'|'port', 'frigate')` for the host) rather than guessing at a new siaDC09 config field, and
deliberately avoided calling `\frigate::getUrlFrigate()` to keep siaDC09 free of a hard class dependency on a
plugin that may be absent or disabled — it reads the same two global config keys that helper reads internally.

Reconciled an apparent contradiction between ADR-17 Amendment 3's prose ("the daemon caches the result... in
memory... `burglarAlarm` sources the event id from this cache") and the already-confirmed fact that no synchronous
PHP↔daemon request/response is possible on the control socket: the daemon's role in this implementation is only to
*run* the REST query and push the outcome exactly once via the existing HTTP callback (`_send_callback()`, already
used for `info_update`) into a Jeedom-side cache (`eqLogic->setCache('sia_prefetch_cache', ...)`), which is the
cache `burglarAlarm`'s `execute()` actually reads, synchronously and purely locally. No new IPC primitive was added
in either direction.

`_handlePrefetchResult()` and `_resolveFrigateSnapshotUrl()`'s rewrite both deliberately overwrite/require a fresh
per-camera entry rather than merging fields — a miss must be able to erase an earlier hit outright (AC5); this was
called out explicitly as its own Level 1 assertion (`array_merge` forbidden) rather than left to reviewer's
inference, since a merge-based "fix" would silently reintroduce the exact stale-hit failure mode this story exists
to close.

### Completion Notes

- Tasks 1-5 complete: `prefetchEvent` command auto-created, wizard carries manual-wiring guidance, its `execute()`
  resolves the mapped camera's Frigate-native identity and fires a bounded async REST prefetch on the daemon side,
  the daemon pushes the outcome back over the existing HTTP callback, and `burglarAlarm`'s `_resolveFrigateSnapshotUrl()`
  now reads that outcome from a local, TTL-bounded cache instead of `info_detect_person`/`info_id` — closing both
  problems (staleness, no label filter) that made story 14-1's Option A untenable, by removing the data source they
  both lived in rather than patching around it.
- `php -l` clean on `core/class/siaDC09.class.php`, `core/class/siaDC09Cmd.class.php`, `desktop/php/siaDC09.php`.
  `pylint --disable=all --enable=E`: 10/10 on `resources/siadc09d/daemon.py` and the new
  `resources/siadc09d/frigate_prefetch.py`.
- Full regression, confirmed via `git stash -u` (plain `git stash` misses this story's own new untracked files and
  gives a false baseline — caught and corrected): `tests/level1/` 8 pre-existing failures (unchanged), `tests/level2/`
  6 pre-existing failures (unchanged), `tests/level2_5/` 1 pre-existing failure (unchanged, confirmed unrelated —
  a stale `event_state`/`event_label` assertion in `test_ipc_integration.py` that fails identically on clean
  master). 0 regressions from this story across all three levels; combined pass count 1472+72=1544 →
  1578 (level1+level2+level2_5), i.e. ~34 net new passing tests once the 2 superseded 14-1 assertions
  (`test_looks_up_info_detect_person_by_logical_id`, `test_looks_up_info_id_by_logical_id`) are accounted for.
- **Task 6 (live validation on `test-jeedom.lehoux.net`) is DONE, hit and miss paths both confirmed.** Four live
  attempts were needed, each surfacing a real, distinct bug or environment gap — all fixed, all re-confirmed by
  regression before the next attempt:
  1. **`prefetchEvent` never fired at all** — `subType` was `'other'`, which has no *Titre* field in the alarm
     plugin's action UI for `#zone#` to be typed into, so the zone never reached `execute()`. Fixed: `subType`
     corrected to `'message'`; wizard guidance updated to tell the installer to set Titre to `#zone#`.
  2. **Prefetch ran but always missed** — the `in_progress=1` REST filter excluded a manually-created test event
     because Frigate sets a concrete `end_time` immediately at creation; confirmed the same holds for a real
     detection (`end_time` set within ~5s of `start_time`) via a genuine historical event. Fixed: dropped
     `in_progress` from the query. The `after` buffer was also widened (15s→60s) then narrowed back (60s→30s)
     once Herve clarified the deployment principle (one camera per zone, narrow FOV, ~10s max real detection
     duration) — a tight buffer is correct here, not just safe, since an old/unrelated frame is itself
     undesirable to hand the monitoring center.
  3. **Confirmed hit, but `media_url` still missing** — `_resolveFrigateSnapshotUrl()` had no logging on its own
     null-return branches (unlike `_resolvePrefetchTarget()`), so this took a manual `_buildFrigateMediaUrl()`
     verification (via the real-execution `php` harness, against the actual live event id — no bug found) before
     Herve confirmed the actual cause: the "URL media Frigate" template field was simply empty on the host.
     Added the missing logging regardless, so this class of gap can't recur silently.
  4. **PASS** — with the template configured, received `[#20881|BA 002][Vhttps://<user>:<password>@frigate.lehoux.net/api/events/1790251493.16806-ilph5x/snapshot.jpg]` — a real snapshot URL on a real BA frame. Combined
     with an earlier clean miss-path confirmation (wrong-label event correctly excluded, no delay), AC5/AC6/AC7
     are confirmed end-to-end.
  Task 6.7 (a specific hit-then-miss-in-quick-succession live sequence) was not separately exercised live — left
  open as optional, given it's already covered by an explicit Level 1 test forbidding stale-entry merging
  (`test_handle_prefetch_result_never_merges_stale_entries`) plus the two individual hit/miss live confirmations
  above. Status moved `in-progress → review`.

### File List

| File | Change |
|------|--------|
| `core/class/siaDC09.class.php` | Added `prefetchEvent` to `postSave()`'s action-command array (`subType => 'message'`, corrected 2026-09-24 from `'other'`); added `case 'prefetch_result':` to `message()`'s switch and the new `_handlePrefetchResult()` handler (now with debug logging of the received payload and the resulting cache entry). |
| `core/class/siaDC09Cmd.class.php` | Added `case 'prefetchEvent':` to `execute()` and the new `_resolvePrefetchTarget()` helper; added `PREFETCH_CACHE_TTL` constant; rewrote `_resolveFrigateSnapshotUrl()` to read the `sia_prefetch_cache` cache instead of `info_detect_person`/`info_id`. 2026-09-24: added debug logging throughout the `prefetchEvent` case and `_resolvePrefetchTarget()` (raw title, zone mapping, resolved zone entry, resolved target, and a specific reason at every null-return branch) plus explicit warnings for an empty zone or an unresolvable target — the live host validation attempt had produced no diagnosable trace at all. |
| `desktop/php/siaDC09.php` | Step 3: added a non-blocking help note instructing the installer to wire `prefetchEvent` into the mapped zone's immediate actions in the alarm plugin. |
| `resources/siadc09d/frigate_prefetch.py` | New — `PrefetchResult` dataclass, `prefetch_person_event()` (bounded poll loop against Frigate's `GET /api/events`), promoting `scripts/frigate_latency_probe.py`'s validated HTTP/poll logic into production daemon code. 2026-09-24: added a module logger and debug logging of each query URL/response, the poll start/timeout/miss, and the confirmed event id. 2026-09-24 (second live validation): dropped the `in_progress=1` filter (excluded already-closed real detections) and widened `PREFETCH_AFTER_BUFFER_S` from 15.0 to 60.0 (real scenario needs more margin between camera detection and sensor trip than a fast manual test does). |
| `resources/siadc09d/daemon.py` | `OnMessageParams` gained `camera_eqlogic_id`/`camera_name`/`frigate_host`; `on_message()` gained a `prefetchEvent` branch (spawns a tracked `_run_prefetch()` task, before the `_EVENT_SIA_CODES` lookup); new `_run_prefetch()` method pushes the outcome via the existing `_send_callback()`. 2026-09-24: added debug logging of the raw dispatch params, the spawned task's target, the Frigate query being started, and the resolved `PrefetchResult`. |
| `tests/level1/test_frigate_prefetch_trigger.py` | New — 13 tests for `execute()`'s `prefetchEvent` case and `_resolvePrefetchTarget()`. |
| `tests/level1/test_frigate_prefetch.py` | New — 5 tests for `frigate_prefetch.py`'s query params, poll/timeout behavior, and error handling. |
| `tests/level1/test_frigate_snapshot_resolution.py` | `TestResolveFrigateSnapshotUrlReadsCorrectCommands`: replaced the `info_detect_person`/`info_id` lookup assertions with cache-read assertions (`sia_prefetch_cache`, `found`, `PREFETCH_CACHE_TTL`) plus a negative assertion forbidding either logicalId. |
| `tests/level1/test_php_eqlogic_stub.py` | Added `test_prefetch_event_command_uses_message_subtype`; renamed `test_message_dispatches_all_five_types` → `test_message_dispatches_all_callback_types` (now 6 types); added 4 new tests for `_handlePrefetchResult()` (cache key, `setCache()` call, stored fields, unconditional-overwrite/no-`array_merge` guarantee). |
| `tests/level1/test_wizard_php_structure.py` | Added `test_step3_prefetch_event_wiring_guidance_present`. |
| `tests/level2/test_frigate_prefetch_dispatch.py` | New — 5 tests for `on_message()`'s `prefetchEvent` dispatch: fire-and-forget proof via an `asyncio.Event` gate, exact `_send_callback` shape on hit/miss (`found` strictly `int`), missing-params rejection, unknown-command path unaffected. |
| `tests/fixtures/ipc_schema.py` | Added `prefetch_result` to `CALLBACK_TYPES`/`REQUIRED_FIELDS`; added `SAMPLE_PREFETCH_RESULT_HIT`/`SAMPLE_PREFETCH_RESULT_MISS`. |
| `tests/level2_5/test_callback_schema.py` | Added the two new samples to `ALL_SAMPLES`; added 4 tests for the `prefetch_result` schema (required fields, `found` strictly `int`, miss still carries `event_id=""`, JSON round-trip). |

## Change Log

| Date | Change |
|------|--------|
| 2026-09-24 | Story created from ADR-17 Amendment 3 (Option D), following a two-round party-mode architecture re-review (Winston/Amelia/John) triggered by two confirmed problems with story 14-1's Option A (`info_detect_person` staleness, `info_id` label-mismatch). Camera identity (Frigate-native slug + host:port) resolved via direct source investigation of the Frigate plugin's own code — confirmed no new siaDC09 config field is needed for either. |
| 2026-09-24 | Tasks 1-5 implemented via TDD across PHP (command definition, trigger-side `execute()`, cache write/read) and the Python daemon (new `frigate_prefetch.py` module, `on_message()` wiring, `_send_callback()` push). Full regression (`git stash -u` diff against clean master): 0 regressions across `tests/level1/`+`tests/level2/`+`tests/level2_5/` (14 known pre-existing failures unchanged, +1 already-pre-existing-and-unrelated in level2_5), ~34 net new passing tests. Status stays `in-progress` — Task 6 (live validation on `test-jeedom.lehoux.net`) requires the real host and a real alarm-plugin zone with a configured trigger delay, not yet run. |
| 2026-09-24 | First live validation attempt (Herve): wired `prefetchEvent` into a zone's immediate actions between two "avant/après prefetch" marker messages, both of which logged — proving the command *was* invoked — but no `sendToDaemon` line for it ever appeared, and `burglarAlarm`'s frame carried no `media_url`. Root cause found by re-reading `docs/design/php-core-design.md:1264`: `prefetchEvent`'s `subType` was `'other'`, which has no *Titre* field in the alarm plugin's action-configuration UI — `#zone#` had nowhere to be typed, so `$_options['title']` was always empty and `_resolvePrefetchTarget()` silently returned null on every invocation, with **no log line at all**, since only exception paths were logged. Fixed both problems: (1) `subType` corrected to `'message'` (Task 1.1/1.3, tests updated), wizard guidance updated to also instruct the installer to set Titre to `#zone#` (Task 1.2); (2) added debug-level logging at every decision point across both PHP (`execute()`'s `prefetchEvent` case, `_resolvePrefetchTarget()`, `_handlePrefetchResult()`) and the daemon (`on_message()`'s dispatch, `_run_prefetch()`, `frigate_prefetch.py`'s query/poll loop), plus explicit warnings for an empty zone or an unresolvable target — so any future misconfiguration is diagnosable from the logs alone, without needing to re-read this story's source. Full regression re-confirmed: identical 15 known pre-existing failures, 0 regressions. Pushed; awaiting a second live attempt with the corrected wiring. |
| 2026-09-24 | Second live validation attempt (Herve, corrected wiring — Titre set to `#zone#`): the full pipeline now ran end-to-end with no PHP/daemon bug — dispatch, REST polling, callback push, caching, and `burglarAlarm`'s non-blocking cache read all worked exactly as designed — but resolved to a miss even against a manually-created `label=person` event created ~6s before the trigger. Diagnosed via a direct `curl` against Frigate's own `GET /api/events`: the event's real `start_time` was backdated by the full `--duration` from creation (a probe-script artifact), landing just outside the 15s `after` buffer, and — more importantly — its `end_time` was already concrete (non-null) at creation, meaning the daemon's `in_progress=1` filter would have excluded it (and would exclude almost any real short detection just as fast, for the same reason). Fixed: dropped `in_progress` from the query entirely, widened `PREFETCH_AFTER_BUFFER_S` from 15.0 to 60.0 seconds for realistic margin between camera detection and sensor trip. Task 3.3/AC4 updated to reflect the corrected filter set. Full regression re-confirmed: identical 15 known pre-existing failures, 0 regressions. Pushed; awaiting a third live attempt. |
| 2026-09-24 | Herve pulled a real historical Frigate event (`curl` on a genuine tracked detection, not a manual test) confirming `end_time` is set within ~5s of `start_time` for a real person too — independently validating the `in_progress` fix against real data, not just the synthetic test event. On the 60s buffer: Herve clarified the intended deployment principle — one camera per protected zone with a narrow field of view on that zone's own entry, not a wide shot of the whole garden — under which his own measured maximum detection duration is ~10s. Narrowed `PREFETCH_AFTER_BUFFER_S` back down from 60.0 to **30.0**: not just a safety-margin choice, but because attaching an old/unrelated frame to the monitoring center is itself undesirable (ADR-17's own "no photo is fine, wrong photo never is" principle), so the buffer should stay tight around the real expected detection-to-trigger gap rather than generous. Full regression re-confirmed: identical 15 known pre-existing failures, 0 regressions. |
| 2026-09-24 | Third live validation attempt (Herve, with the 30s buffer): prefetch found a real, correctly-labeled, correctly-timed `person` event on the very first poll (`found=1`) and the daemon pushed/PHP cached it — but `burglarAlarm`'s frame still carried no `media_url`. Added missing debug logging to `_resolveFrigateSnapshotUrl()` itself (every null-return branch plus a success log — this method had none before, unlike `_resolvePrefetchTarget()`) to close the same diagnosability gap for the read side. Verified `_buildFrigateMediaUrl()` directly against the real event id (`1790247176.261449-fnjyy5`) via the real-execution `php` subprocess harness, both template forms — correct output, no bug there. Root cause confirmed by Herve: the "URL media Frigate" field (Step 3) was empty on this test host during the run — `_resolveFrigateSnapshotUrl()` correctly returned `null` at that exact check, before `_buildFrigateMediaUrl()` was ever called. **Not a code defect** — the prefetch/cache pipeline (dispatch → REST hit → callback → cache write → non-blocking cache read) is now confirmed fully working end-to-end; AC6's "template not configured → media_url omitted" contract behaved exactly as designed. Awaiting a fourth attempt with the template configured, to confirm AC7's full `[V...]` snapshot URL end-to-end. |
| 2026-09-24 | **Fourth live validation attempt — PASS.** With the media URL template configured, received frame `[#20881\|BA 002][Vhttps://<user>:<password>@frigate.lehoux.net/api/events/1790251493.16806-ilph5x/snapshot.jpg]_12:05:29,09-24-2026` — a real Frigate snapshot URL correctly attached to a real BA frame, confirming AC5/AC6/AC7 end-to-end. Combined with the earlier confirmed miss-path run (6.6, wrong-label event correctly excluded, no delay), Task 6 is complete except 6.7 (a specific hit-then-miss-in-quick-succession live sequence), left open as optional given it's already covered by an explicit Level 1 test forbidding stale-entry merging plus the two individual live confirmations. Status `in-progress → review`. |
| 2026-09-24 | Code review (`/bmad-code-review`, three parallel layers — Blind Hunter, Edge Case Hunter, Acceptance Auditor): 2 decisions, 5 patches, 3 deferred, 2 dismissed. Both decisions deferred by Herve as-is (same-camera prefetch task race; tight margin between prefetch worst-case latency and a short installer-configured trigger delay) — recorded as D-52/D-53 in `deferred-work.md`. All 5 patches applied: an explicit diagnostic for an unsubstituted `#zone#` tag (with a new Level 1 test), a stale `_buildFrigateMediaUrl()` docblock, a corrected Dev Notes/code-comment citation (the original `php-core-design.md:1264` reference didn't literally support the claim — pointed at the general tag mechanism instead), and two doc-only corrections (this story's own File List test name, `sprint-status.yaml`'s stale `epic-14` comment). Full regression re-confirmed: identical 15 known pre-existing failures, 0 regressions (+1 new test). |
