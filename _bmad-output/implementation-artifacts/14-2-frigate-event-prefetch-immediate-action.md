---
story_id: "14-2"
story_key: "14-2-frigate-event-prefetch-immediate-action"
epic_id: "epic-14"
epic_name: "Camera Snapshot Attachment (Frigate Integration)"
status: "in-progress"
created: "2026-09-24"
---

# Story 14.2: Frigate Event Prefetch via the Alarm Plugin's Immediate-Action Window (Option D)

Status: in-progress

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
   `in_progress`/`has_snapshot` filters, `sort=desc&limit=1`), polling with a bounded total wait and per-request
   timeout (reusing/promoting the poll logic already validated in `scripts/frigate_latency_probe.py`, not
   duplicating it) — never unbounded, never awaited by any PHP code.

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
  - [x] 1.1 Added `'prefetchEvent' => ['name' => ..., 'subType' => 'other']` to the `postSave()` action-command
        array in `siaDC09.class.php:648-653`, alongside `burglarAlarm`/`fireAlarm`/`panicAlarm` — same
        auto-create-if-missing loop, no new code path.
  - [x] 1.2 Wizard/documentation guidance (Step 3 or Step 4 of `desktop/php/siaDC09.php`): a non-blocking help
        note telling the installer to add the `prefetchEvent` command to the mapped zone's **immediate actions**
        in the alarm plugin. No JS wiring — this is manual, per AC1.
  - [x] 1.3 Level 1 test: `postSave()`'s action-command array contains `prefetchEvent` with `subType => 'other'`
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
        `after=<now - after_buffer_s>`, `in_progress=1`, `has_snapshot=1`, `sort=desc`, `limit=1` until a match
        appears or `max_wait_s` elapses; returns `PrefetchResult(found=False, event_id=None)` on timeout or any
        HTTP/network error (never raises to the caller).
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

- [ ] Task 6: Full regression + live validation on `test-jeedom.lehoux.net` (AC: 7, and end-to-end confirmation
      of AC1-6)
  - [x] 6.1 `php -l` clean on all modified/new PHP files; full `tests/level1/` suite compared against the known
        baseline (memory `level1-test-baseline-failures`) — confirmed via `git stash -u` diff against clean
        master: identical 8 pre-existing level1 failures, 0 regressions, +36 new tests.
  - [x] 6.2 `pylint --disable=all --enable=E` clean (10/10) on `daemon.py` and the new `frigate_prefetch.py`;
        full `tests/level1/`+`tests/level2/`+`tests/level2_5/` Python suites compared against baseline (same
        `git stash -u` method) — identical 15 pre-existing failures (8 level1 + 6 level2 + 1 level2_5, the last
        one confirmed pre-existing and unrelated), 0 regressions, +50 new tests total across all levels.
  - [ ] 6.3 Deploy (git push, then pull on the host — memory `jeedom-test-host-deploy`).
  - [ ] 6.4 Manually wire `prefetchEvent` into the mapped zone's immediate-actions bucket in the alarm plugin
        (per Task 1.2's guidance) on the real host.
  - [ ] 6.5 Trip the real sensor for that zone; confirm in the daemon/plugin logs that the prefetch fires
        immediately, the REST query reaches the real Frigate server, and the SIA frame (sent after the zone's
        real trigger delay) carries the correct person snapshot in its `[V...]` field — validated via the
        protocol inspector (story 9-2), per memory `jeedom-ui-validation-over-reflection`.
  - [ ] 6.6 Trip the sensor with no person actually present on camera (or force a miss); confirm the frame sends
        normally with no `media_url` and no delay to the alarm send path.
  - [ ] 6.7 Confirm two triggers in quick succession on the same camera — a hit followed by a miss (person left
        frame) — result in the *second* outcome being used, not a stale first hit (AC5's core guarantee,
        specifically the reason for Task 5.2's unconditional overwrite).

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
- **Task 6 (live validation on `test-jeedom.lehoux.net`) is NOT done** — per memory
  `jeedom-ui-validation-over-reflection`, this requires the real host, a real Frigate camera, and a real
  alarm-plugin zone with a configured trigger delay (to actually exercise the immediate-vs-standard timing this
  story's whole design depends on). Code is implemented and fully regression-tested but not yet pushed/deployed.
  Awaiting: push to the host, manual wiring of the `prefetchEvent` command into the mapped zone's immediate actions
  (per the new Step 3 wizard guidance), then a real sensor trip to confirm AC5/AC6/AC7 end-to-end — including the
  specific two-triggers-in-a-row scenario (Task 6.7) that is the concrete reason `_handlePrefetchResult()` was
  written as an unconditional overwrite rather than a merge.

### File List

| File | Change |
|------|--------|
| `core/class/siaDC09.class.php` | Added `prefetchEvent` to `postSave()`'s action-command array (`subType => 'other'`); added `case 'prefetch_result':` to `message()`'s switch and the new `_handlePrefetchResult()` handler. |
| `core/class/siaDC09Cmd.class.php` | Added `case 'prefetchEvent':` to `execute()` and the new `_resolvePrefetchTarget()` helper; added `PREFETCH_CACHE_TTL` constant; rewrote `_resolveFrigateSnapshotUrl()` to read the `sia_prefetch_cache` cache instead of `info_detect_person`/`info_id`. |
| `desktop/php/siaDC09.php` | Step 3: added a non-blocking help note instructing the installer to wire `prefetchEvent` into the mapped zone's immediate actions in the alarm plugin. |
| `resources/siadc09d/frigate_prefetch.py` | New — `PrefetchResult` dataclass, `prefetch_person_event()` (bounded poll loop against Frigate's `GET /api/events`), promoting `scripts/frigate_latency_probe.py`'s validated HTTP/poll logic into production daemon code. |
| `resources/siadc09d/daemon.py` | `OnMessageParams` gained `camera_eqlogic_id`/`camera_name`/`frigate_host`; `on_message()` gained a `prefetchEvent` branch (spawns a tracked `_run_prefetch()` task, before the `_EVENT_SIA_CODES` lookup); new `_run_prefetch()` method pushes the outcome via the existing `_send_callback()`. |
| `tests/level1/test_frigate_prefetch_trigger.py` | New — 13 tests for `execute()`'s `prefetchEvent` case and `_resolvePrefetchTarget()`. |
| `tests/level1/test_frigate_prefetch.py` | New — 5 tests for `frigate_prefetch.py`'s query params, poll/timeout behavior, and error handling. |
| `tests/level1/test_frigate_snapshot_resolution.py` | `TestResolveFrigateSnapshotUrlReadsCorrectCommands`: replaced the `info_detect_person`/`info_id` lookup assertions with cache-read assertions (`sia_prefetch_cache`, `found`, `PREFETCH_CACHE_TTL`) plus a negative assertion forbidding either logicalId. |
| `tests/level1/test_php_eqlogic_stub.py` | Added `test_prefetch_event_command_uses_other_subtype`; renamed `test_message_dispatches_all_five_types` → `test_message_dispatches_all_callback_types` (now 6 types); added 4 new tests for `_handlePrefetchResult()` (cache key, `setCache()` call, stored fields, unconditional-overwrite/no-`array_merge` guarantee). |
| `tests/level1/test_wizard_php_structure.py` | Added `test_step3_prefetch_event_wiring_guidance_present`. |
| `tests/level2/test_frigate_prefetch_dispatch.py` | New — 5 tests for `on_message()`'s `prefetchEvent` dispatch: fire-and-forget proof via an `asyncio.Event` gate, exact `_send_callback` shape on hit/miss (`found` strictly `int`), missing-params rejection, unknown-command path unaffected. |
| `tests/fixtures/ipc_schema.py` | Added `prefetch_result` to `CALLBACK_TYPES`/`REQUIRED_FIELDS`; added `SAMPLE_PREFETCH_RESULT_HIT`/`SAMPLE_PREFETCH_RESULT_MISS`. |
| `tests/level2_5/test_callback_schema.py` | Added the two new samples to `ALL_SAMPLES`; added 4 tests for the `prefetch_result` schema (required fields, `found` strictly `int`, miss still carries `event_id=""`, JSON round-trip). |

## Change Log

| Date | Change |
|------|--------|
| 2026-09-24 | Story created from ADR-17 Amendment 3 (Option D), following a two-round party-mode architecture re-review (Winston/Amelia/John) triggered by two confirmed problems with story 14-1's Option A (`info_detect_person` staleness, `info_id` label-mismatch). Camera identity (Frigate-native slug + host:port) resolved via direct source investigation of the Frigate plugin's own code — confirmed no new siaDC09 config field is needed for either. |
| 2026-09-24 | Tasks 1-5 implemented via TDD across PHP (command definition, trigger-side `execute()`, cache write/read) and the Python daemon (new `frigate_prefetch.py` module, `on_message()` wiring, `_send_callback()` push). Full regression (`git stash -u` diff against clean master): 0 regressions across `tests/level1/`+`tests/level2/`+`tests/level2_5/` (14 known pre-existing failures unchanged, +1 already-pre-existing-and-unrelated in level2_5), ~34 net new passing tests. Status stays `in-progress` — Task 6 (live validation on `test-jeedom.lehoux.net`) requires the real host and a real alarm-plugin zone with a configured trigger delay, not yet run. |
