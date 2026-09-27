# Story 14.4: Best-Effort Alarm Media — Any-Label Ranking + Forced Frigate Capture

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want every intrusion (BA) frame to carry the best available image and clip of the zone taken while the alarm is
happening, even when Frigate detected no person,
so that the operator always sees something useful ("an animal", "nobody visible", "an intruder") without the frame
ever being delayed.

**Sources:** ADR-17 Amendment 4 (`_bmad-output/planning-artifacts/architecture.md`, "ADR-17, Amendment 4
(2026-09-26)"), requirements `_bmad-output/planning-artifacts/requirements-14-4-frigate-forced-capture-2026-09-26.md`
(FR1–FR6, NFR1–NFR4, §8 AC seeds), epics.md Story 14.4. Builds on 14-2 (prefetch/cache) and 14-3 (`[V snapshot clip]`).

## Acceptance Criteria

1. **Forced capture first.** When the daemon receives `prefetchEvent`, the first Frigate call of the run is
   `POST {base_url}/api/events/{camera}/alarm/create` with JSON body `{"duration": 30, "include_recording": true}`,
   before any `GET /api/events` poll. The label is the constant `"alarm"`.
2. **Early push (rank 3).** As soon as the create call returns a non-empty `event_id`, the daemon sends a
   `prefetch_result` callback with `found=1`, `event_id=<manual id>`, `clip_found=1` (per-source rule, AC7), `rank=3`
   and the run's `run_id`. It's sent before the first poll, not at the end of the run.
3. **Any-label search.** In the same run, the daemon polls `GET /api/events` with `camera`, `after = t0 − 30 s`,
   `has_snapshot=1`, `sort=date_desc` and a `limit` > 1 (named constant). There's **no** `label` filter, every 2 s,
   within the unchanged 25 s budget measured from t0. Client-side it drops every row whose `label == "alarm"`
   **or** whose `data.type == "api"`, and every row without a truthy `has_snapshot`.
4. **Ranking.** Rank 1 is the most recent `person` row. Rank 2 is the most recent row with any other label. Rank 3 is
   the manual event, and rank 4 is nothing. Within a run, the daemon switches to another event **only on a strict rank
   improvement**. A same-rank event seen in a later poll never replaces the one already chosen, which keeps it
   consistent with the PHP rule in AC6. On rank 1 with the clip ready, the run stops. On rank 2 it keeps polling for a
   person until the budget runs out.
5. **One callback per improvement.** A callback is sent each time the rank improves (with `clip_found` decided by
   AC7), and once more when the chosen rank-1/2 event's clip becomes ready (same rank, `clip_found` 0→1). No other
   callbacks are sent, except the final rank-4 miss described in AC9.
6. **PHP monotonic cache rule** (`siaDC09::_handlePrefetchResult`). An incoming result replaces the stored entry for
   its camera only if one of these holds:
   (a) its `run_id` is numerically greater than the stored one, or there's no usable stored `run_id`;
   (b) it has the same `run_id` and a smaller `rank`;
   (c) it has the same `run_id` and the same `rank`, the stored `clip_found` is false and the incoming one is true.

   In every other case it's ignored, with a `debug` log line. The stored entry gains the `run_id` and `rank` fields.
   `found`, `event_id`, `clip_found` and `ts` keep their exact 14-3 shape and meaning, so the snapshot and clip
   resolvers are unchanged. A late callback from an older run never overwrites a newer run's entry (requirements
   §8.7).
7. **Per-source clip rule, in the daemon only.** Rank 3 sends `clip_found=1` immediately. Ranks 1 and 2 send
   `clip_found=1` only once `_check_clip_ready()` has confirmed `has_clip`. PHP never branches on the source
   beyond `rank`.
8. **`run_id` owned by PHP.** The `prefetchEvent` case in `siaDC09Cmd::execute()` generates
   `run_id = (string) microtime(true)`. It writes a **placeholder** cache entry for that camera
   (`found=false, event_id=null, clip_found=false, rank=4, run_id, ts=time()`) **before** calling `sendToDaemon`,
   then passes `run_id` in the payload. The daemon echoes it verbatim on every callback of that run. A stale hit from
   an earlier run can then never be attached, even if the create call fails and no callback ever arrives. This
   replaces 14-2 AC5's "the miss callback clears the entry".
9. **Failure never crashes, never delays.** If the create call gets HTTP 401/403/404/5xx, times out, or finds Frigate
   down, the daemon logs **one** `warning` for the run (with the status when there is one), skips the rank-3 push and
   carries on with the rank 1/2 search. If polling finds nothing either, it sends exactly one final rank-4 miss
   (`found=0, event_id="", clip_found=0, rank=4`), which PHP ignores under rule AC6, the placeholder already being
   rank 4. Nothing raises past `frigate_prefetch`, and `burglarAlarm` is never blocked or delayed.
10. **Never delete.** No code path calls Frigate's `DELETE`, `/end`, `/retain` or any other mutating endpoint besides
    `create`. A test asserts this on the module source.
11. **Send path unchanged.** `burglarAlarm`/`fireAlarm`/`panicAlarm`'s single shared `_readPrefetchCacheEntry()` read
    (14-3 TOCTOU fix), `_resolveFrigateSnapshotUrl`/`_resolveFrigateClipUrl`, `PREFETCH_CACHE_TTL = 120` and the
    space-joined `media_url` stay as they are. There's no new network call on the send path. The 14-3 execute
    harness tests still pass with entries that carry the new `run_id`/`rank` fields, and with legacy entries that
    don't.
12. **Tests before live** (memory `prefer-tests-over-live-trial-and-error`). Level-1/level-2 tests cover: create-first
    ordering, the rank-3 early push, the exclusion (label and type backstop, including a leftover `alarm` event from
    an earlier trip), the ranking and most-recent tie-break, no same-rank switching, clip upgrade, the create-failure
    fallback, the final rank-4 miss, and the PHP no-downgrade/stale-run rule. The IPC schema fixture is updated.
    Regression runs are compared against the known baseline (level1 2, level2 6, level2_5 1), not 0.
13. **Live validation** on `test-jeedom.lehoux.net` (push first; code arrives by `git pull`), against the real receiver
    `192.168.100.15:10002`, account `001234`, checked through the real Jeedom UI/API and Frigate, not by
    reflection:
    - (a) no Frigate event → the BA frame carries `[V …/{alarm-id}/snapshot.jpg …/{alarm-id}/clip.mp4]`, and Frigate
      shows an `alarm` event with a clip;
    - (b) person in view → the frame carries the person event's media, and the `alarm` event still exists;
    - (c) (if an animal can be staged or found) another label → that event's media;
    - (d) disarm during the entry delay → no BA frame, and the `alarm` event stays.

    Record what the receiver shows for the forced clip URL while it's still partial (Amendment 4 R5).

## Tasks / Subtasks

- [x] **Task 1 — Tests first: daemon prefetch module** (AC: 1, 2, 3, 4, 5, 7, 9, 10, 12)
  - [x] 1.1 In `tests/level1/test_frigate_prefetch.py`, add `_post_json` tests: 200 + JSON → dict; `HTTPError` 401/403
        → `None` with status surfaced (see Task 2.1 return shape); URLError/timeout/malformed JSON → never raises.
  - [x] 1.2 `_create_manual_event` tests: URL is `/api/events/{camera}/alarm/create` with the camera URL-quoted, and
        the body is exactly `{"duration": 30, "include_recording": true}`. It returns the `event_id` on
        `success: true`, and `None` on `success: false`, an empty id, or any error.
  - [x] 1.3 `_query_candidate_events` / ranking tests with fake `/api/events` rows:
        - the exclusion: `label=="alarm"`; `label!="alarm"` but `data.type=="api"`; a row with no `data`; a row
          without a snapshot;
        - person beats a more recent cat;
        - the most recent of two cats wins;
        - no `label` query parameter is sent, `sort=date_desc` is sent, and `limit` equals the constant.
  - [x] 1.4 `prefetch_alarm_media` orchestration tests (patch the helpers and collect the `on_result` calls):
        - create is called before the first query;
        - rank 3 is pushed with `clip_found=True`;
        - 3 → 2 (`clip_found=False`) → 2 (`clip_found=True`) → 1;
        - a later same-rank event is ignored;
        - the run stops on rank 1 with the clip ready;
        - it keeps polling on rank 2;
        - a create failure means no rank-3 push, and the search still runs;
        - with nothing found and a failed create, exactly one final rank-4 miss;
        - with nothing found but a successful create, no final miss;
        - the budget is respected, with a deadline from t0 and create time included;
        - an `on_result` that raises doesn't kill the run.
  - [x] 1.5 A source-scan test: `frigate_prefetch.py` contains no `DELETE` method, `/end`, `/retain`, or
        `method="PUT"`, and only one `POST` (the create).
- [x] **Task 2 — Implement `resources/siadc09d/frigate_prefetch.py`** (AC: 1–5, 7, 9, 10)
  - [x] 2.1 `_post_json(url: str, body: dict[str, object], timeout: float) -> tuple[int | None, object | None]`:
        - `urllib.request.Request(..., method="POST")` with `Content-Type: application/json`;
        - never raises; returns `(status, decoded)`, or `(e.code, None)` on `HTTPError` (catch it **before**
          `URLError`, since it's a subclass), or `(None, None)` on a network or JSON error;
        - mirror `_get_json`'s except tuple. Keep `_get_json` as is.
  - [x] 2.2 `_create_manual_event(base_url, camera, timeout) -> tuple[str | None, int | None]`, returning
        `(event_id, http_status)`. Add the constants `MANUAL_EVENT_LABEL: Final[str] = "alarm"`,
        `MANUAL_EVENT_DURATION_S: Final[int] = 30` and `MANUAL_EVENT_API_TYPE: Final[str] = "api"`.
  - [x] 2.3 Add `_query_candidate_events(base_url, camera, after_ts, timeout) -> list[dict[str, object]]`, which
        returns filtered rows, plus a pure `_best_candidate(rows) -> tuple[int, str] | None` that returns
        `(rank, event_id)`. Remove `_query_latest_person_event` and `_PERSON_LABEL` only if nothing else uses them
        (check with grep, including `tests/` and `scripts/`). Otherwise keep them.
  - [x] 2.4 Extend `PrefetchResult` with `rank: int = RANK_NONE` (constants `RANK_PERSON=1`, `RANK_OTHER=2`,
        `RANK_MANUAL=3`, `RANK_NONE=4`; an `IntEnum` is fine too, but its value must go over IPC as a plain int).
        The existing positional construction `PrefetchResult(found, event_id, clip_found)` must keep working, since
        the level-2 tests import it.
  - [x] 2.5 `async def prefetch_alarm_media(base_url, camera, on_result: Callable[[PrefetchResult], Awaitable[None]],
        *, same keyword budget params) -> PrefetchResult`:
        - compute `after_ts` and `deadline` at entry (t0);
        - create the manual event via `asyncio.wait_for(asyncio.to_thread(...), http_timeout_s + SLACK)`;
        - push rank 3;
        - loop: query, rank, push on a strict improvement; while a rank-1/2 event is held without its clip, call
          `_check_clip_ready` once per iteration (don't use the blocking `_poll_clip_ready`, which would stop the
          person search); stop on rank 1 with the clip;
        - cap each sleep at the time left (the 14-3 deadline-overrun fix);
        - wrap each `on_result` await in `try/except Exception` with a warning log, so one callback failure doesn't
          end the run;
        - return the final best result.

        Keep `prefetch_person_event` only if something else still calls it. Otherwise remove it and its now-dead
        tests, and say so in the Completion Notes.
  - [x] 2.6 Update the module docstring (Amendment 4 reference; "never deletes manual events") and the
        `PREFETCH_AFTER_BUFFER_S` comment (the principle is now "stale or not this alarm's").
- [x] **Task 3 — Tests first, then implement: daemon wiring** (AC: 2, 5, 8, 9, 12)
  - [x] 3.1 In `tests/level2/test_frigate_prefetch_dispatch.py`:
        - `run_id` is required: a missing or non-string value is ignored with a warning, the way a missing
          `camera_name` is today;
        - `_run_prefetch` forwards `run_id` and `rank` on every callback;
        - the payload uses only ints 0/1 for flags (`_send_callback` drops bools) and `rank` as an int;
        - one run with three improvements → three `_send_callback` calls, in order.

        The existing tests patch `resources.siadc09d.daemon.prefetch_person_event` by name (lines 76, 99, 133, 165,
        193). Retarget them to `prefetch_alarm_media`, using a fake that awaits `on_result(...)` to drive the
        callbacks, and keep their intent: fire-and-forget, never awaited in `on_message`, and a miss still reaching
        PHP.
  - [x] 3.2 `resources/siadc09d/daemon.py`:
        - `prefetchEvent` branch (~2124-2155): read and validate `run_id`, then pass it to
          `_run_prefetch(cam_id, camera_name, frigate_host, run_id)`;
        - `_run_prefetch` (~2222): call `prefetch_alarm_media` with a closure `on_result` that builds
          `{"type": "prefetch_result", "camera_eqlogic_id", "found", "event_id", "clip_found", "rank", "run_id"}`
          and awaits `_send_callback`;
        - update the import at line 63, the `Params` TypedDict (~line 246-262: add `run_id: str`), and the
          on_message docstring (~2119).
  - [x] 3.3 In `tests/fixtures/ipc_schema.py`, add `rank` and `run_id` to `REQUIRED_FIELDS["prefetch_result"]`, and
        update `SAMPLE_PREFETCH_RESULT_HIT`/`_MISS` plus the comment. Adjust `tests/level2_5/test_callback_schema.py`
        (add: `rank` is an int, never a bool; `run_id` is a non-empty str).
- [x] **Task 4 — Tests first, then implement: PHP** (AC: 6, 8, 11, 12)
  - [x] 4.1 Add a new PHP real-execution harness for `siaDC09::_handlePrefetchResult`, following
        `_run_execute_burglar_alarm`'s pattern in `tests/level1/test_frigate_snapshot_resolution.py` (strip
        `<?php`/`require_once`, stub `log`, and a `FakeEqLogic` with `getCache`/`setCache`). Invoke the private
        static method via `ReflectionMethod::setAccessible(true)`, or through the `case 'prefetch_result'` dispatch
        if that's easier to reach. Cover this matrix:
        - newer run replaces;
        - older run is ignored;
        - same run, better rank replaces;
        - same run, worse rank is ignored;
        - same run and rank, clip 0→1 replaces;
        - same run and rank, clip 1→0 is ignored;
        - a missing stored `run_id` (legacy 14-3 entry) is replaced;
        - an entry for another camera is left untouched.
  - [x] 4.2 Extend the `prefetchEvent` tests, either with a real-execution harness in
        `tests/level1/test_frigate_prefetch_trigger.py` or source-level like that file's current tests (prefer real
        execution). Check that:
        - `sendToDaemon` receives a numeric-string `run_id`;
        - the placeholder is written to `sia_prefetch_cache[camId]` **before** `sendToDaemon`;
        - nothing is written on the early-return paths (empty zone, literal `#zone#`, unresolved target).
  - [x] 4.3 `core/class/siaDC09.class.php` `_handlePrefetchResult` (596-623):
        - apply rule AC6, comparing `run_id` as `(float)`;
        - store `run_id` (string) and `rank` (int, default 4 when absent);
        - keep the try/catch and the debug logs, and add an "ignored (…)" debug line;
        - update the docblock ("unconditionally overwrites" is no longer true);
        - when it replaces, keep writing a **fresh array literal** at `$cache[(int) $camId] = [ ... ]` with
          `'clip_found' => !empty($data['clip_found'])`, and never `array_merge` with the old entry. The existing
          source-reflection tests in `tests/level1/test_php_eqlogic_stub.py:896-980` pin exactly that and must keep
          passing. Update the docstring of `test_handle_prefetch_result_never_merges_stale_entries` from 14-2 AC5's
          "unconditionally overwrite" to Amendment 4's "replace only per the run_id/rank rule, and never merge".
  - [x] 4.4 `core/class/siaDC09Cmd.class.php` `prefetchEvent` case (38-79): after a successful
        `_resolvePrefetchTarget`, generate `run_id` and write the placeholder with the same read-modify-write shape as
        `_handlePrefetchResult` (factor a small private helper only if it stays readable). Wrap it in its own
        `try/catch (\Throwable)` with a warning. A failed placeholder write must never block `sendToDaemon`. Then
        add `'run_id' => $runId` to the payload.
  - [x] 4.5 Check that the existing 14-3 `TestExecuteBurglarAlarmMediaUrlJoin` still passes, and add one case whose
        entry carries `run_id`/`rank` (AC11).
- [x] **Task 5 — Regression + lint** (AC: 12)
  - [x] 5.1 `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/`. Compare against the baseline (level1 2,
        level2 6, level2_5 1) and name any new failure.
  - [x] 5.2 `python3 -m pylint resources/siadc09d/`; `php -l core/class/siaDC09.class.php core/class/siaDC09Cmd.class.php`.
- [ ] **Task 6 — Live validation** (AC: 13) — deployed and validated 2026-09-27 on `test-jeedom.lehoux.net`
      against the real receiver (account `20881` — the siaDC09 eqLogic's currently-configured account on this
      test instance, also the live account seen in 12-5/14-2's sessions; AC13's literal `001234` reflects the
      reference config at the time the AC was written, not a requirement on this exact account number). Herve
      did the `git pull` + daemon restart manually (this
      session still has no SSH to the host). Cases (a), (b), (d) confirmed; case (c) and the clip-URL timing
      sub-check (6.4) are open by Herve's explicit call — see 6.3/6.4 below. Left unchecked at the Task level
      per the 14-3 Task 6 precedent (subtask-level [x] marks "addressed/decided", not "every sub-case
      reproduced").
  - [x] 6.1 Deployed via `git pull` (commit `e9d5332`) + manual daemon restart on `test-jeedom.lehoux.net`
        (Herve). Confirmed running by the daemon log activity below, not by supervision_state alone (memory
        `jeedom-daemon-down-looks-like-frozen-label`).
  - [x] 6.2 Confirmed via evidence, not directly queried: every `_create_manual_event` POST returned
        `status=200`/`success:true` (e.g. `event_id='1790502478.691199-tqjx6p'`), which requires the admin
        role (Amendment 4 R1) — so port 5000 is in effect. Case (a)'s degrade-to-plain-BA path was never
        exercised.
  - [x] 6.3 Cases (a), (b), (d) confirmed live; case (c) explicitly **not staged** by Herve's call —
        `scripts/frigate_latency_probe.py`'s `create_event()` uses the same manual-create endpoint as the
        forced capture, so any event it creates would carry `data.type=="api"` and be excluded by AC3's own
        rule regardless of `--label`; it can't exercise the rank-2 path, only a real Frigate object detection
        can, and none was available this session.
        - **(a) no person, run_id `1790502478.677253-aae37e`:** create → `event_id='...tqjx6p'` → rank-3 push
          (`clip_found=1`) before the first poll → 12 polls (09:47:58–09:48:22) see only the manual event,
          correctly excluded internally, no real candidate ever appears → no final miss sent (rank 3 already
          held) → `burglarAlarm` at 09:48:28 resolves `media_url` to the rank-3 event
          (`_resolveFrigateSnapshotUrl`/`_resolveFrigateClipUrl` PHP log confirms it), TCP frame sent, CRC
          valid, declared/actual length 242/242 (independent proof the `[V...]` block is genuinely on the
          wire even though the protocol inspector's decoder can't display it — see D-80). Frigate event list:
          one `alarm`/`api` event, `has_snapshot`/`has_clip` both true.
        - **(b) person in view, run_id `1790503982.078326-548fc1`:** create → rank-3 push, then a real `person`
          event (`...12iu2a`, created 10:13:12 per its own event id) is first seen in the 10:13:14 poll,
          alongside the still-present manual event → `_best_candidate`
          picks the person row → rank-1 push (`clip_found=0`) → immediate `_check_clip_ready` finds
          `has_clip=true` → second push (rank 1, `clip_found=1`) → run stops (rank 1 + clip ready, AC4).
          `burglarAlarm` at 10:13:32 resolves `media_url` to the **person event's id**
          (`1790503992.45437-12iu2a`), confirmed via the PHP log — AC11 holds. Both `person` and `alarm`
          Frigate events still present afterward (AC10).
        - **(d) disarm during entry delay, run_id `1790504332.695482-9d7f5c`:** `arm`(CL) at 10:18:48 →
          `prefetchEvent` at 10:18:52 (create + rank-3 push, polling starts) → `disarm`(OP) arrives at
          10:19:07 mid-poll → **no `burglarAlarm` ever fires**, exactly as AC13(d) expects; the background
          prefetch task's eventual result is simply never consumed. Confirmed by Herve: the manual `alarm`
          event created for this run still exists in Frigate afterward (AC10) — never deleted despite the
          disarm.
  - [x] 6.4 **Not captured this session, by Herve's explicit call** (same treatment as 14-3's Task 6.6) — the
        clip URL's HTTP 400 → partial → full transition over ~45s was not timed/recorded. Case (a)'s frame
        delivery, CRC/length integrity, and Frigate-side clip readiness (`has_clip=true`) are otherwise
        confirmed by 6.3 above; only the specific partial-clip-window observation is missing.

### Review Findings

Reviewed diff: `66efeec..HEAD` (commits `e9d5332`, `4a7ea4f`). Layers: Blind Hunter (diff-only),
Edge Case Hunter (diff + project access), Acceptance Auditor (diff + this story + ADR-17 Amendment 4).
Acceptance Auditor: **no AC violations found** across AC1-AC12 (AC13/Task 6 correctly excluded as an
honestly-disclosed blocker).

- [x] [Review][Defer] Double-failure gap: a failed `_writePrefetchPlaceholder()` write combined with a
  failed daemon create (no callback ever sent for the run) leaves a stale hit from an earlier, unrelated
  trigger sitting in the cache indefinitely — exactly the class of bug AC8's placeholder was built to close.
  `core/class/siaDC09Cmd.class.php`, `_writePrefetchPlaceholder()`. Deferred (Herve's call, 2026-09-27): needs
  two independent failures at once; same acceptance pattern as D-77 (single shared cache key).
- [x] [Review][Patch] `run_id` generated via bare `(string) microtime(true))` risks precision-truncation
  collisions under PHP's default `precision` ini (14 significant figures can truncate below microsecond
  resolution) — two near-simultaneous same-camera triggers could get an identical/misordered `run_id`.
  `core/class/siaDC09Cmd.class.php`, `prefetchEvent` case.
- [x] [Review][Patch] `siaDC09::_handlePrefetchResult()`'s incoming `rank` isn't validated/clamped — a
  malformed non-numeric `rank` casts to `0` via `(int)`, which beats every real rank (1-4) and would always
  win the replace check regardless of actual priority. `core/class/siaDC09.class.php:_handlePrefetchResult`.
- [x] [Review][Patch] `_create_forced_capture()`'s create-call timeout isn't capped to the remaining budget
  before `deadline`, unlike every other call in the any-label search loop (which uses
  `min(http_timeout_s, remaining)`) — inconsistent, and a latent NFR1 risk if the constants are ever tuned
  such that `http_timeout_s` exceeds the remaining budget. `resources/siadc09d/frigate_prefetch.py:_create_forced_capture`.
- [x] [Review][Patch] `_post_json()`'s generic exception handler conflates "200 response with malformed JSON"
  with "total network failure" — both return `(None, None)`, losing the real HTTP status and weakening AC9's
  "warning with the status when there is one" diagnostic. `resources/siadc09d/frigate_prefetch.py:_post_json`.
- [x] [Review][Patch] `architecture.md`'s Amendment 4 Trade-offs table states "there is always media while
  Frigate is up" as a Pro of the chosen design, but AC9/R1 explicitly allow a rank-4 (no media) outcome even
  while Frigate is fully up, whenever the configured port lacks the admin role and no real event is found —
  internally inconsistent with the risk analysis two sections later in the same doc.
- [x] [Review][Patch] The three independent `PREFETCH_RANK_NONE`/`RANK_NONE` = 4 constants
  (`frigate_prefetch.py`, `siaDC09.class.php`, `siaDC09Cmd.class.php`) have no test asserting they agree —
  a future rank-scheme change in one file could silently desync the others.
- [x] [Review][Defer] `EVENTS_QUERY_LIMIT = 20` with no server-side label filter could theoretically let a
  saturation of manual "alarm" events (many trips within the 30s window) crowd a real detection out of the
  fetched page before client-side filtering ever sees it — deferred, low-likelihood edge case, no test
  exercises it. `resources/siadc09d/frigate_prefetch.py:_query_candidate_events`.

**Second review pass (2026-09-27), scoped to Task 6's live-validation evidence.** Reviewed diff: uncommitted
changes to this story file, `deferred-work.md`, `sprint-status.yaml` only (doc/tracking, no application
code). Layers: Blind Hunter (diff-only), Edge Case Hunter (diff + project access), Acceptance Auditor (diff +
this story file). Edge Case Hunter: all 6 checked technical claims (decoder line numbers, `encode_message()`
V-block concatenation, port-5000 admin-role inference, `frigate_latency_probe.py` exclusion behavior, D-80
cross-file consistency, sprint-status.yaml summary arithmetic) confirmed accurate against source — 0
findings. Acceptance Auditor: no fabricated evidence, cases (a)/(b)/(d) internally consistent with AC2/AC4/
AC9/AC10/AC11, case (c)'s exclusion well-reasoned against AC3, the two honest gaps (case (c), AC13's R5
clip-timing note) correctly flagged rather than glossed over, and the Task-6-header-unchecked/subtasks-checked
pattern verified against the 14-3 precedent (not invented for this story).

- [x] [Review][Patch] Debug Log List credits the `[V ...]` block solely to "story 14-1", while the new D-80
  entry in `deferred-work.md` (written in the same session) correctly credits "14-1/14-3" (14-1 added the
  block, 14-3 extended it to the space-separated dual-URL format) — an internal attribution inconsistency
  between the two files for the same fact. `14-4-...md` Debug Log List. **Fixed**: Debug Log List reworded to
  "14-1/14-3".
- [x] [Review][Patch] Task 6's Case (a)/(b)/(d) preamble validates against account `20881` with no reconciling
  note against AC13's own literal text, which still names the reference account `001234` — the diff discloses
  the substitution but doesn't explain it, leaving a future reader to reconcile "what AC13 says" against "what
  Task 6 did" unaided. `14-4-...md`, Task 6 preamble and AC13. **Fixed**: Task 6 preamble now clarifies `20881`
  is the eqLogic's currently-configured account on this test instance (also seen live in 12-5/14-2), and that
  AC13's `001234` reflects the reference config at write-time, not a hard requirement.
- [x] [Review][Patch] Case (b)'s narrative states the person event "appears" at 10:13:14, but the event's own
  id (`1790503992.45437-...`) decodes to 10:13:12 — a 2s gap between the event's creation timestamp and its
  first-observed-in-poll timestamp (consistent with the 2s poll interval, not an error), stated in a way that
  reads as more tightly reconstructed than it is. `14-4-...md`, Task 6.3 case (b). **Fixed**: reworded to
  distinguish "created 10:13:12 per its own event id" from "first seen in the 10:13:14 poll".
- [x] [Review][Patch] The pre-existing "### Review Findings" preamble ("Acceptance Auditor: no AC violations
  found across AC1-AC12, AC13/Task 6 correctly excluded as an honestly-disclosed blocker") pre-dates this
  session's Task 6 live-validation work and doesn't reflect that Task 6's own evidence has now been through an
  adversarial pass — addressed by this second-pass preamble above, but noting it here so the two passes read
  as sequential rather than the first one looking silently stale.

## Dev Notes

### What changes, file by file (current state → change → preserve)

**`resources/siadc09d/frigate_prefetch.py`**
- *Today:*
  - `_get_json` (GET, never raises);
  - `_query_latest_person_event` (`label=person`, `has_snapshot=1`, `sort=desc`, `limit=1`; no `in_progress`
    filter, on purpose);
  - `_check_clip_ready` (`has_clip` on the event row);
  - `_poll_clip_ready` (blocking until the deadline);
  - `prefetch_person_event` → one `PrefetchResult(found, event_id, clip_found)`. Constants: after buffer 30 s, max
    wait 25 s, poll 2 s, HTTP timeout 5 s, `wait_for` slack 1 s.
- *Change:* add a POST helper, create, any-label query plus ranking, and an orchestrator with an `on_result` callback
  (Tasks 2.1-2.5).
- *Preserve:*
  - no Jeedom dependency (NFR2, the Amendment 3 boundary);
  - blocking urllib only via `asyncio.to_thread` inside `asyncio.wait_for`;
  - never raises;
  - no `in_progress` filter (memory `frigate-rest-in-progress-filter-unreliable`);
  - the 14-3 deadline-cap fix;
  - all existing constants and values.

**`resources/siadc09d/daemon.py`**
- *Today:*
  - on_message `prefetchEvent` validates `camera_eqlogic_id`, `camera_name` and `frigate_host`, then
    `_track_task(self._run_prefetch(...), name=f"frigate-prefetch-{cam_id}")`;
  - `_run_prefetch` sends **one** callback at the end.
- *Change:* add `run_id`, and send incremental callbacks through the `on_result` closure.
- *Preserve:*
  - fire-and-forget, with a tracked task (no untracked tasks);
  - `_send_callback`'s bool rejection (send ints);
  - base URL `http://{frigate_host}`.
- *Hot-spot:* daemon.py is the file several parallel agents merge into (memory `parallel-agents-daemon-conflict`).
  Pull and rebase before editing, and keep the diff confined to the prefetch section.

**`core/class/siaDC09.class.php`**
- *Today:* the `case 'prefetch_result'` dispatch is at ~498, and `_handlePrefetchResult` (596-623) unconditionally
  overwrites `$cache[(int)$camId]`.
- *Change:* apply the AC6 rule and store `run_id`/`rank`.
- *Preserve:* the try/catch (never throws into the callback endpoint), and the `is_string` → `json_decode` tolerance.

**`core/class/siaDC09Cmd.class.php`**
- *Today:*
  - the `prefetchEvent` case (38-79) guards against an empty zone or a literal `#zone#`, then
    `_findZoneEntry` → `_resolvePrefetchTarget` → `sendToDaemon`;
  - the send case (81-114) does one `_readPrefetchCacheEntry` read and resolves snapshot then clip;
  - `PREFETCH_CACHE_TTL = 120` (line 27).
- *Change:* the prefetchEvent case only (run_id, placeholder, payload field).
- *Preserve:* the whole send path, byte-for-byte in behaviour (AC11); the resolvers; `_buildFrigateMediaUrl`; the
  warning texts in French.

### Why a placeholder write (AC8), and why a single cache key stays

- The placeholder is needed because, without it, a failed create plus a miss would leave the previous run's hit in
  the cache until the ~25 s final callback. That's the exact stale-media case Amendment 4 still calls "wrong".
  Writing it in the PHP process that owns `run_id` closes that gap at t0.
- Verified in Jeedom core (`core/class/eqLogic.class.php:2040-2047`, cloned 2026-09-26):
  - `getCache`/`setCache` store **all** of an eqLogic's cache keys in one `cache::` blob, `eqLogicCacheAttr{id}`;
  - `setCache` is itself a read-modify-write of that blob.
- So splitting `sia_prefetch_cache` into per-camera keys would narrow but not remove the lost-update window between
  concurrent writers. Those writers are the placeholder (alarm-plugin PHP process) and callbacks for another camera
  (callback endpoint process). They're only concurrent when two cameras trip within milliseconds.
- Within one run, the daemon's callbacks are serialized (each `await _send_callback`).
- **Decision for this story:** keep the single `sia_prefetch_cache` key (the 14-3 tests and the reader are
  unchanged), keep each read-modify-write tight (no logic between `getCache` and `setCache` beyond the rule), and
  record the residual race in the Completion Notes as a new deferred item.

### Frigate 0.17.2 contract (verified in source, `/tmp/frigate-src` tag v0.17.2)

**Create** (`frigate/api/event.py:1737-1798`)
- Validates only the camera (404 if unknown) and a non-empty label. It requires the admin role.
- Returns `{"success": true, "message": "Successfully created event.", "event_id": "<ts>.<us>-<6 chars>"}`
  synchronously. The insert and the snapshot are asynchronous, and the snapshot has been measured ready at 0.53 s.

**Port 5000 is admin** (`api/auth.py:577-579`). The deployed `frigate_host` is `192.168.100.18:5000`.

**`GET /api/events`** (`event.py:98-370`)
- The selected columns include `label`, `start_time`, `has_clip`, `has_snapshot` and `data`, and `data.type` is
  `"api"` for manual events and `"object"` for real ones.
- `sort` accepts `date_desc`/`date_asc`/`score_*`/`speed_*`. **Any other value, including 14-2's `desc`, falls back
  to `start_time DESC`**, so use `date_desc` explicitly.
- The default `limit` is 100. Pick a small named constant (e.g. 20), since manual events now take slots in the list.

**Manual events**
- `end_time = t0 + duration` (`track/object_processing.py:524`).
- `clip.mp4` serves the segments already on disk: HTTP 400 until the first flush (~10 s), then a partial clip, then
  the full clip from about t0 + 40 s.
- Always alert review segments, so they follow `record.alerts.retain`. Snapshots use `snapshots.retain.objects.alarm`
  or `default`.
- **Never add `alarm` to `objects.track`**; it's dropped with a warning.
- Manual events never publish to MQTT `events` (memory `frigate-manual-event-api-no-mqtt`), which doesn't matter
  because nothing reads MQTT here.

**Event id format.** Manual ids have the same `<ts>.<us>-<rand>` shape as real ids, so `_buildFrigateMediaUrl`
needs no change.

### Guardrails

- **Media URLs:** siaDC09 stores only the literal placeholder template, never a real secret, and adds no Frigate
  credentials (memory `media-url-template-never-real-secret`).
- **Scope:** BA is the product scope. Media resolution stays shared by BA/FA/PA as it has been since 14-1/14-2 (14-3
  review decision), so don't add or remove a gate. `prefetchEvent` is only wired to intrusion zones anyway.
- **IPC:** flags are int 0/1 and `rank` is an int; `run_id` is a string echoed verbatim. Never send Python bools.
- **Python style:** full typing (`X | Y`), `Final` constants, no magic numbers or strings, Google docstrings,
  specific exceptions, `asyncio.wait_for` around every network op, `Callable`/`Awaitable` from `collections.abc`.
- **PHP style:** PHP 8 types on new methods, `??`, and log messages in French like the surrounding ones.
- **Never delete** manual events (AC10); Herve's explicit decision.
- **Budget:** the 25 s window is measured from t0 and includes the create call (worst case 6 s if the create hangs).
  Don't extend `PREFETCH_MAX_WAIT_S`.

### Cross-story impact

- **14-2 AC5** ("always send a result so a stale hit is cleared"): now covered by the PHP placeholder (AC8), plus the
  final rank-4 miss when nothing else was sent (AC9).
- **14-2 / Amendment 3 two-outcome contract and `label=person`:** superseded by Amendment 4. Update the docstrings
  that still say "no third tier".
- **Deferred items:**
  - D-52 (concurrent same-camera triggers): resolved by `run_id`, since the newer run owns the cache. Mark it
    resolved in `deferred-work.md` with a pointer to 14-4.
  - D-53 (tight margin with a short entry delay): largely mitigated, because a rank-3 entry lands about 1 s after t0.
    Note that in `deferred-work.md`.
  - D-54 (no trigger-time correlation): still applies, now to any label, and the ranking accepts it (most recent in
    the window). Leave it open and add a one-line note.
  - D-59 (clip ready just after the deadline): unchanged for ranks 1/2.
- **Known accepted cost** (Amendment 4, "one entry = one event"): a rank-2 event can replace the manual event's
  snapshot+clip with a snapshot alone if its clip isn't ready by BA time.

### Previous-story intelligence (14-3, 14-2)

- 14-3 review fixes to keep: `_poll_clip_ready`'s remaining-time cap (apply the same cap to every sleep in the new
  loop), and the single shared cache read in `execute()`.
- 14-2 live lessons:
  - `prefetchEvent` must stay `subType='message'` (for the `#zone#` Titre field; memory
    `alarm-plugin-subtype-message-for-titre-tag`);
  - the `in_progress` filter was dropped on purpose;
  - after-buffer 30 s (Herve's deployment assumption: one narrow camera per zone).
- Test patterns:
  - pytest-asyncio with `patch.object(frigate_prefetch, "<helper>")` and `sys.path` insert of `resources/siadc09d`
    (`tests/level1/test_frigate_prefetch.py`);
  - the `mock_daemon` fixture with `_send_callback = AsyncMock()` (`tests/level2/test_frigate_prefetch_dispatch.py`);
  - the PHP real-execution harness with Jeedom stubs (`tests/level1/test_frigate_snapshot_resolution.py:603-722`,
    skipped when `php` is missing). D-61 notes that the harness only asserts `returncode`; in the new harness also
    assert that `stderr` is empty on the happy path.
- Recent commits (`4fd41dc` 14-3 review, `736de3a`/`d2921ba` 14-1) touched the same PHP files. Rebase and don't
  revert them.

### Project Structure Notes

- No new files outside `tests/`. All REST code stays in `resources/siadc09d/frigate_prefetch.py`.
- No wizard/UI or `plugin_info` change. No new config key. `frigate_media_url_template` is unchanged.
- Recommendation for Herve's Frigate config (not code, not in this story's diff): add `alarm: 15` under
  `snapshots.retain.objects` in `pailly-proxified/etc/frigate/config.yml`.

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#ADR-17, Amendment 4 (2026-09-26)]
- [Source: _bmad-output/planning-artifacts/requirements-14-4-frigate-forced-capture-2026-09-26.md]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 14.4]
- [Source: _bmad-output/implementation-artifacts/14-3-attach-frigate-clip-alongside-snapshot.md]
- [Source: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — D-51..D-54, D-57..D-61]
- [Source: resources/siadc09d/frigate_prefetch.py; resources/siadc09d/daemon.py (~2124-2239, 503-535, 246-262)]
- [Source: core/class/siaDC09.class.php (~498, 596-623); core/class/siaDC09Cmd.class.php (27, 38-114, 307-529)]
- [Source: tests/fixtures/ipc_schema.py; tests/level2_5/test_callback_schema.py:489-560]
- [Source: Frigate v0.17.2 — frigate/api/event.py, api/auth.py, track/object_processing.py, review/maintainer.py]
- [Source: Jeedom core — core/class/eqLogic.class.php:2040-2047 (getCache/setCache)]
- [Source: scripts/frigate_latency_probe.py — `_http_json` POST pattern already proven against the deployed Frigate]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (eu.anthropic.claude-sonnet-5)

### Debug Log References

- Code review (2026-09-27, 3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor): 1
  decision-needed (double-failure gap in `_writePrefetchPlaceholder()` — deferred as D-79, Herve's call), 6
  patches applied and tested (`run_id` precision-truncation collision risk; `rank` clamping against a
  malformed non-numeric value; `_create_forced_capture()`'s create-call timeout not capped to the remaining
  budget; `_post_json()` losing the HTTP status on a malformed-but-successful body; `architecture.md`'s
  overclaiming Trade-offs wording; a cross-file consistency test for the `RANK_NONE`/`PREFETCH_RANK_NONE`
  constants), 1 deferred (D-78, `EVENTS_QUERY_LIMIT` saturation edge case), 6 dismissed as noise (verified
  against the code: a style nit matching an existing convention, a negligible budget micro-optimization, the
  already-disclosed D-77 race, the already-accepted never-delete design, the already-disclosed Task 6 blocker,
  and a general non-actionable observation). Post-review regression: 1710 passed, 9 failed (same baseline),
  `pylint` 8.90/10 (was 8.89/10 pre-review), `php -l` clean.
- Full regression run (2026-09-27, pre-review): `tests/level1/ tests/level2/ tests/level2_5/` → 1705 passed, 9 failed —
  identical to the known pre-existing baseline (memory `level1-test-baseline-failures`: level1 2, level2 6,
  level2_5 1). 40 new tests added, 0 regressions.
- `python3 -m pylint resources/siadc09d/` → 8.89/10 (baseline before this story: 8.85/10 — no new findings;
  `frigate_prefetch.py` alone: 9.61/10 after refactor, remaining findings are the codebase's existing
  f-string-logging/broad-except conventions).
- `php -l` clean on `core/class/siaDC09.class.php`, `core/class/siaDC09Cmd.class.php`, and every PHP file under
  `core/`/`desktop/`.
- Live validation (Task 6) attempted 2026-09-27: `ssh test-jeedom.lehoux.net` times out (port 22) from this
  session; `curl https://test-jeedom.lehoux.net/` returns 200/302, so the Jeedom UI itself is reachable but
  `git pull` on the host is not possible from here. Commit `e9d5332` pushed to `origin/master` regardless, ready
  for a session with SSH access to deploy and validate.
- Live validation (Task 6) completed 2026-09-27, second half of the session: Herve deployed manually (`git pull`
  + daemon restart on `test-jeedom.lehoux.net`, this session still had no SSH). Cases (a)/(b)/(d) driven live
  against the real receiver (account `20881`) and confirmed via daemon logs, PHP `_resolveFrigateSnapshotUrl`/
  `_resolveFrigateClipUrl`/`sendToDaemon` logs, the protocol inspector's captured frame (case a: CRC valid,
  declared/actual length 242/242), and direct Frigate observation (event lists, AC10 persistence after
  disarm). Case (c) not staged (no real object detection available; the obvious substitute,
  `scripts/frigate_latency_probe.py`, would only produce another `data.type=="api"` event, which AC3 excludes
  regardless of label — it can't exercise the rank-2 path). Task 6.4's clip-URL 400→partial→full timing was
  not captured — accepted as an open gap by Herve's explicit call, same treatment as 14-3's Task 6.6.
  Discovered live in case (a): the protocol inspector's raw-frame decoder only captures the first `[...]`
  bracket and never parses a second one, so it can't display the `[V...]` block even though it's genuinely on
  the wire (confirmed via CRC/length) — logged as new deferred item D-80, not a 14-4 regression (the decoder,
  story 9-2, was never updated when `encode_message()` gained V-block support in story 14-1/14-3).

### Completion Notes List

- Tasks 1-5 implemented via TDD (red-green-refactor per task), fully tested, 0 regressions. Task 6 (live
  validation) is BLOCKED on network access — see Debug Log References — not skipped, not fabricated as a pass.
- `frigate_prefetch.py`: `prefetch_person_event()`/`_query_latest_person_event()`/`_poll_clip_ready()` removed
  (superseded by `prefetch_alarm_media()`/`_query_candidate_events()`/`_best_candidate()`, with the clip-upgrade
  check now interleaved per-poll-iteration inside the orchestrator itself, since a blocking clip-only poll would
  have stopped the any-label search from ever noticing a person event appearing later). `_check_clip_ready()` is
  unchanged and still used. The orchestrator was refactored into `_create_forced_capture()`,
  `_maybe_upgrade_clip()`, and a small generic `_run_with_deadline_timeout()` helper to keep pylint's
  branches/statements/locals thresholds — confirmed no test coverage was lost, still 32/32 green after the split.
- `siaDC09::_handlePrefetchResult()` now applies the AC6 run_id/rank monotonic rule via a new
  `_prefetchResultShouldReplace()` helper, but still writes a fresh array literal on replace (never `array_merge`),
  keeping the 14-2-era source-reflection test (`test_handle_prefetch_result_never_merges_stale_entries`) green —
  only its docstring needed updating, not its assertions.
- `siaDC09Cmd::execute()`'s `prefetchEvent` case now generates `run_id` and calls a new
  `_writePrefetchPlaceholder()` before `sendToDaemon()`, per AC8. Kept the single shared `sia_prefetch_cache` key
  (Dev Notes' "why a placeholder write, and why a single cache key stays") — recorded the residual
  concurrent-writer race as a new deferred item, D-77, rather than refactoring to a per-camera key in this story.
- Deferred-work.md updated: D-52 marked RESOLVED (the run_id/rank rule removes the "last callback wins" race
  regardless of arrival order), D-53 marked "largely mitigated" (the manual event reaches the cache ~1s after t0
  instead of ~25-31s), D-54 got a one-line note (the same-recency limitation now applies to any label, accepted
  explicitly by Amendment 4), D-77 opened (single shared cache-key concurrency, accepted trade-off).
- No new dependencies, no new config fields, no wizard/UI changes.
- One new test file (`test_frigate_prefetch_cache_replace.py`) added for the AC6 replace-rule matrix via real PHP
  execution (`ReflectionMethod`, no `setAccessible()` call needed — a no-op since PHP 8.1, deprecated in 8.5).
- Sprint-status.yaml: `epic-14` reopened `done` → `in-progress` for this story (registered before this dev
  session); left as `in-progress` here since Task 6 is still open. `14-4-...` stays `in-progress`, not moved to
  `review`.
- Task 6 live validation (2026-09-27, same day, later session): cases (a)/(b)/(d) confirmed on
  `test-jeedom.lehoux.net` against the real receiver. Case (c) not staged (no real object detection available;
  the manual-create endpoint can't produce one — see Debug Log). Task 6.4's clip-URL timing check not
  captured — accepted as an open gap, Herve's explicit call. New deferred item D-77...D-80: D-80 opened for a
  pre-existing protocol-inspector decoder gap discovered during validation (single-bracket-only parsing, never
  populates `extended_fields`) — not a 14-4 regression, the wire frame is correct (CRC/length confirm the
  `[V...]` block is genuinely sent). `in-progress` → `review`.
- Code review (2026-09-27): 6 patches applied — `run_id` now `sprintf('%.6f', microtime(true)) . '-' .
  bin2hex(random_bytes(3))` (a bare `(string) microtime(true)` cast is truncated by PHP's `precision` ini to
  ~0.1ms resolution, not true microsecond resolution); `_handlePrefetchResult()`'s incoming `rank` clamped to
  `[PREFETCH_RANK_PERSON, PREFETCH_RANK_NONE]`; `_create_forced_capture()`'s create-call timeout now capped to
  the remaining budget like every other call in the loop; `_post_json()` now preserves the HTTP status on a
  malformed-but-successful (200) body instead of losing it to `None`; `architecture.md`'s Trade-offs table
  wording corrected; a new cross-file test asserts `RANK_NONE`/`PREFETCH_RANK_NONE` stay in sync across the
  three files. 1 decision (double-failure placeholder gap) deferred as D-79. 1 new deferred item (D-78,
  `EVENTS_QUERY_LIMIT` saturation edge case). Regression: 1710 passed (was 1705), same 9 pre-existing failures.

### File List

- `resources/siadc09d/frigate_prefetch.py` (rewritten: forced capture, any-label ranking, orchestration; code
  review: `_post_json()` status-preservation fix, `_create_forced_capture()` timeout capped to remaining budget)
- `resources/siadc09d/daemon.py` (`_run_prefetch()` incremental callbacks; `Params` TypedDict `run_id`;
  `on_message()` validates/forwards `run_id`)
- `core/class/siaDC09.class.php` (`_handlePrefetchResult()` monotonic replace rule; new
  `_prefetchResultShouldReplace()`; new `PREFETCH_RANK_NONE`/`PREFETCH_RANK_PERSON` constants; code review:
  incoming `rank` clamped to a valid range)
- `core/class/siaDC09Cmd.class.php` (`prefetchEvent` case generates `run_id` and writes the placeholder; new
  `_writePrefetchPlaceholder()`; new `PREFETCH_RANK_NONE` constant; code review: `run_id` generation hardened
  against PHP `precision`-ini truncation)
- `_bmad-output/planning-artifacts/architecture.md` (code review: corrected the Amendment 4 Trade-offs table's
  overclaiming "always media" wording; corrected the `run_id` generation description)
- `tests/level1/test_frigate_prefetch.py` (rewritten for `prefetch_alarm_media()` and its helpers; code review:
  4 new regression tests — timeout-cap, malformed-200-body, cross-file rank-constant consistency)
- `tests/level1/test_frigate_prefetch_trigger.py` (extended: `run_id`/placeholder source-shape + new real-execution
  class `TestExecutePrefetchEventRealRun`)
- `tests/level1/test_frigate_prefetch_cache_replace.py` (new: AC6 replace-rule matrix, real PHP execution)
- `tests/level1/test_frigate_snapshot_resolution.py` (added AC11 regression case: entry carrying `run_id`/`rank`)
- `tests/level1/test_php_eqlogic_stub.py` (docstring update on the "never merges" test — assertions unchanged)
- `tests/level2/test_frigate_prefetch_dispatch.py` (rewritten for `prefetch_alarm_media()`/`run_id`/`rank`)
- `tests/level2_5/test_callback_schema.py` (new `rank`/`run_id` field tests)
- `tests/fixtures/ipc_schema.py` (`prefetch_result` schema extended with `rank`/`run_id`)
- `_bmad-output/implementation-artifacts/deferred-work.md` (D-52 resolved, D-53/D-54 annotated, D-77/D-78/D-79
  opened during code review; D-80 opened during Task 6 live validation — protocol-inspector decoder gap)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (14-4 registered/in-progress; epic-14 reopened;
  in-progress → review after Task 6 live validation)
- `_bmad-output/implementation-artifacts/14-4-best-effort-alarm-media-forced-capture.md` (this story file)

## Change Log

| Date | Change |
|------|--------|
| 2026-09-27 | Dev session (TDD, red-green-refactor per task): Tasks 1-5 implemented and fully tested (AC1-12). 40 new tests, 0 regressions against the known baseline. Task 6 (live validation) BLOCKED — no SSH access to `test-jeedom.lehoux.net` from this sandboxed session; deferred, not skipped. Status stays `in-progress`. |
| 2026-09-27 | Code review (3-layer adversarial): 6 patches applied and tested (`run_id` precision-truncation fix, `rank` clamping, create-call timeout cap, `_post_json` status-loss fix, architecture.md wording, rank-constant cross-file consistency test), 1 decision deferred (D-79), 1 new deferred item (D-78), 6 dismissed as noise. Regression: 1710 passed, same 9 pre-existing baseline failures. Status stays `in-progress` — Task 6 still open. |
| 2026-09-27 | Task 6 live validation, same day: Herve deployed manually (`git pull` + daemon restart, this session still had no SSH). Cases (a) no-person, (b) person-in-view, (d) disarm-during-entry-delay confirmed live against the real receiver via daemon/PHP logs, the protocol inspector, and direct Frigate observation. Case (c) not staged (no real object detection available). Task 6.4's clip-URL timing check not captured — accepted as an open gap, Herve's explicit call, same precedent as 14-3's Task 6.6. Discovered and logged D-80 (protocol-inspector raw-frame decoder only parses the first `[...]` bracket, can't display `[V...]`) — confirmed a pre-existing gap, not a 14-4 regression, since the frame's CRC/length prove the V-block is genuinely on the wire. `in-progress` → `review`. |
