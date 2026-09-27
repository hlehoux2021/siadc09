---
story_id: "14-3"
story_key: "14-3-attach-frigate-clip-alongside-snapshot"
epic_id: "epic-14"
epic_name: "Camera Snapshot Attachment (Frigate Integration)"
status: "done"
created: "2026-09-26"
---

# Story 14.3: Attach Frigate Video Clip Alongside Snapshot in Alarm Frame

Status: done — Tasks 1-6 complete. Live-validated 2026-09-26 on test-jeedom.lehoux.net against the real
receiver 192.168.100.15:10002: dual-URL [V...] field confirmed end-to-end (Zone2/vigi_sud-est). Task 6.6
(snapshot-only live case) covered by unit tests only, live repro not attempted — see Dev Notes. Code review
2026-09-26: 1 decision resolved (doc correction, no code change), 2 patches applied and tested (clip-poll
deadline overrun fixed; cache-read TOCTOU closed), 6 items deferred (D-57..D-62), 5 dismissed as noise.

## Story

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want the SIA alarm frame to carry both a snapshot and a short video clip when Frigate has both ready,
So that the monitoring center gets the richest available evidence without ever waiting on it.

## Context

Extends story 14-2's Option D prefetch/cache mechanism (ADR-17 Amendment 3,
`_bmad-output/planning-artifacts/architecture.md:393-502`) to also carry a clip URL for the same
confirmed person event, attaching both media (snapshot + clip) in the SIA frame's single `[V...]`
extended-data field when both are available by `burglarAlarm`'s frame-build time.

**V-field format decision (2026-09-26, already made — do not revisit):** the SIA DC-09 `[V...]` field is
free-form (§5.5.1.8) and not reliably repeatable per-identifier across real CSR parsers, so this story
uses **one** `[V...]` block with both URLs **space-separated** when both are available (a well-formed URL
never contains a literal space), e.g. `[Vhttps://.../snapshot.jpg https://.../clip.mp4]`. No MIME/type tag
— the file extension (`.jpg` vs `.mp4`) is the only type indicator. When only one media is available, that
one alone is attached — unchanged from 14-2. When neither is available, `media_url` is omitted entirely —
unchanged from 14-1/14-2's fallback contract.

**Architecture correction made during story creation (read before implementing):** the epics.md AC text
says "the daemon also constructs a clip URL... reusing 14.1's existing `frigate_media_url_template`
placeholder-substitution mechanism." Taken literally this is wrong and must not be implemented as written:
`frigate_media_url_template` is a **Jeedom PHP eqLogic config value**, and the daemon has zero Jeedom
dependencies by design (ADR-17's own invariant, reaffirmed in 14-2's Dev Notes — the daemon never touches
Jeedom config/cmds, only the existing fire-and-forget/HTTP-callback IPC channels). The daemon **cannot**
read `frigate_media_url_template`. This is the same class of ADR-prose-vs-actual-architecture mismatch that
14-2's own Dev Notes already resolved once for the snapshot URL (see that story's "Why the daemon's own
in-memory intent and the Jeedom-side cache are not the same thing").

**Resolved design (what to actually build):**
- The **daemon's** job is only to *confirm clip readiness* — a bounded, independent HTTP check inside the
  same immediate-action prefetch window already used for the person-event query (never awaited by PHP,
  never a new synchronous call on `burglarAlarm`'s path). It reports back a boolean `clip_found`, alongside
  the existing `found`/`event_id`, via the **same** `prefetch_result` callback.
- The **PHP side** constructs the actual clip URL string, exactly the way `_resolveFrigateSnapshotUrl()` /
  `_buildFrigateMediaUrl()` already construct the snapshot URL today — same `frigate_media_url_template`,
  same cached `event_id`, just a different path suffix (`clip.mp4` instead of `snapshot.jpg`). This is
  genuinely "reusing 14.1's existing placeholder-substitution mechanism," just correctly located in PHP, not
  the daemon.
- This design is also the only way to satisfy the AC that requires the clip-readiness network call to be
  independently failable from the snapshot confirmation ("Frigate API unreachable for the clip call
  specifically while the snapshot call succeeded, and vice versa") — if PHP only ever did blind string
  templating for both media with no readiness check, there would be no such independent failure mode to
  test, and the ADR's own measured clip-latency data (0.53s–11.49s, bounded by Frigate's ~10s
  recording-segment flush, not by the tracked object's dwell time) would have nothing to be *for*.

## Acceptance Criteria

1. **Given** the same `prefetchEvent`/`_run_prefetch()` flow that already confirms a `person` event
   (14-2, unchanged), **when** a person event is confirmed (or exhausted without one), **then** the daemon
   also checks, within the same bounded prefetch window, whether a clip is ready for that event id — an
   independent HTTP check against Frigate's own guessable clip URL/event row (per the validated
   `scripts/frigate_latency_probe.py` methodology: `has_clip` on the event row, or a direct status check on
   `/api/events/{event_id}/clip.mp4`) — and includes the outcome as a new `clip_found` boolean in the
   existing `prefetch_result` callback payload (`found`/`event_id` unchanged). No new IPC primitive, no new
   command, no new PHP↔daemon channel.

2. **And** the clip-readiness check is its own network operation, separate from the person-event
   confirmation query — a Frigate outage or timeout affecting only the clip check (e.g. the event row query
   succeeds but the clip-file probe times out) resolves `clip_found=False` without affecting `found`/
   `event_id`, and vice versa (a clip probe that would have succeeded is never attempted if no person event
   was confirmed in the first place). Never raises to the caller; never blocks beyond the existing bounded
   `max_wait_s` budget already governing the whole prefetch.

3. **Given** the daemon's `prefetch_result` callback (now carrying `clip_found`), **when** PHP's
   `_handlePrefetchResult()` writes the per-camera `sia_prefetch_cache` entry, **then** it also stores
   `clip_found` (coerced to bool, same defensive pattern as the existing `found` field) — same unconditional
   fresh-entry overwrite as today (a miss on either field must be able to erase an earlier stale hit; no
   `array_merge`).

4. **Given** `burglarAlarm` fires for a zone mapped to a Frigate camera, **when** it resolves `media_url`,
   **then** it reads the cached per-camera entry once and resolves **both** a snapshot URL (existing
   `_resolveFrigateSnapshotUrl()`, unchanged: hit on `found` + non-expired + template configured) and a clip
   URL (new sibling method, same cache entry, same TTL/expiry rule, gated on `clip_found` instead of
   `found`) — both built via the same `frigate_media_url_template` + cached `event_id`, differing only in
   the path suffix appended (`snapshot.jpg` vs `clip.mp4`). When both resolve, `execute()` joins them with a
   single space into one `media_url` string; when exactly one resolves, that one alone is sent; when
   neither resolves, the `media_url` payload key is omitted entirely (unchanged AC4/AC6 fallback contract
   from 14-1/14-2). This read is local, synchronous, and non-blocking — no new network call happens on this
   path; the clip-readiness network call already happened during the immediate-action prefetch window.

5. **And** a test proves `execute()`'s `burglarAlarm` case never blocks or throws regardless of clip-cache
   state — clip ready, clip not ready, cache entry present with `clip_found` absent/malformed (pre-14-3
   cache entries, or a partially-written entry), snapshot resolved but clip not, clip resolved but snapshot
   not, both resolved, neither resolved — same life-safety framing as 14-1's AC5 / 14-2's AC7.

6. **And** the whole flow is validated live on `test-jeedom.lehoux.net` against a real Frigate camera and
   the real receiver: trigger a real alarm with both snapshot and clip available in time, confirm the SIA
   frame's `[V...]` field carries both URLs space-separated in the protocol inspector, and confirm — by
   direct observation, not inference — what the receiver at `192.168.100.15:10002` actually does with a
   dual-URL `[V...]` field (a generic receiver; this exact shape has not been sent to it before). Document
   the observed result even if the receiver only surfaces one URL or truncates the field.

**Note on scope (corrected 2026-09-26, code review):** media resolution (`_resolveFrigateSnapshotUrl`/
`_resolveFrigateClipUrl`) has never been gated to `burglarAlarm` — it has been shared across
`burglarAlarm`/`fireAlarm`/`panicAlarm` via the same `execute()` case fallthrough since 14-1/14-2, for
snapshot. This story's clip attachment simply follows that same existing, shared pattern; it does not newly
scope clip attachment to BA only. Herve's explicit call (code review 2026-09-26): leave the shared dispatch
as-is, correct this doc rather than add a new BA-only gate.

**Explicitly out of scope:** any new
wizard/config UI (reuses 14-1's existing camera mapping and `frigate_media_url_template` field verbatim);
a structured multi-media format (JSON, MIME tags) — space-separated free-form text is the chosen convention
per the V-field format decision above, revisit only if AC6's live receiver validation shows it doesn't work.

## Tasks / Subtasks

- [x] Task 1: Daemon-side clip-readiness check (AC: 1, 2)
  - [x] 1.1 In `resources/siadc09d/frigate_prefetch.py`: extend `PrefetchResult` (currently
        `found: bool; event_id: str | None`, lines 52-58) with `clip_found: bool = False`.
  - [x] 1.2 Add `_check_clip_ready(base_url: str, event_id: str, timeout: float) -> bool` — mirrors the
        existing `_get_json()`/`_query_latest_person_event()` pattern (lines 60-118): a single bounded HTTP
        check against `{base_url}/api/events/{event_id}` (read `has_clip` from the JSON body, matching
        `scripts/frigate_latency_probe.py`'s `poll()` — line 137, `row.get("has_clip")`) or directly against
        `{base_url}/api/events/{event_id}/clip.mp4` (status-code check, matching that same script's
        `_http_status()` helper, lines 83-92). Returns `False` on any HTTP/network error or malformed
        response — never raises, same contract as `_get_json()`.
  - [x] 1.3 In `prefetch_person_event()` (lines 121-168): after a person event is confirmed (`event_id`
        found), poll `_check_clip_ready()` — via `asyncio.to_thread()` + `asyncio.wait_for()`, same pattern
        as the existing poll loop — using the **remaining** time budget under `deadline` (do not add a
        second independent `max_wait_s`; the whole prefetch, snapshot-confirmation + clip-check combined,
        must stay bounded by the existing `PREFETCH_MAX_WAIT_S`). If the person-event confirmation itself
        times out (miss), skip the clip check entirely — `clip_found` stays `False`, `PrefetchResult(found=False, event_id=None, clip_found=False)`.
  - [x] 1.4 New named constants for any new timeout/poll values introduced (no magic numbers,
        `python-style.md`) — reuse `PREFETCH_POLL_INTERVAL_S`/`PREFETCH_HTTP_TIMEOUT_S` where the same
        cadence applies rather than inventing near-duplicates.
  - [x] 1.5 Level 1 tests, extending `tests/level1/test_frigate_prefetch.py`: clip check runs only after a
        confirmed person event (never when the person-event poll itself missed); clip check's own
        HTTP/network error resolves `clip_found=False` without affecting `found`/`event_id`; clip ready
        resolves `clip_found=True`; total elapsed time across both checks stays bounded by
        `PREFETCH_MAX_WAIT_S` (mock `time.monotonic()`/`asyncio.sleep()` as the existing tests already do
        for the timeout-poll assertions).

- [x] Task 2: Daemon wiring — include `clip_found` in the existing callback (AC: 1)
  - [x] 2.1 `daemon.py`'s `_run_prefetch()` (lines 2192-2221): change
        `"found": 1 if result.found else 0` line to also add `"clip_found": 1 if result.clip_found else 0`
        to the `_send_callback({"type": "prefetch_result", ...})` payload — same int-not-bool guard as
        `found` already respects (`_send_callback()` drops any payload containing a Python `bool`,
        `daemon.py:487-521`).
  - [x] 2.2 No changes needed to `OnMessageParams` (`daemon.py:237-260`) or `on_message()`'s `prefetchEvent`
        branch (lines 2102-2133) — `clip_found` is outbound-only (daemon → PHP), never a dispatch param.
  - [x] 2.3 Level 2 test, extending `tests/level2/test_frigate_prefetch_dispatch.py`: `_run_prefetch()`'s
        `_send_callback` payload includes `clip_found` strictly as `int` (not `bool`) on every combination
        (person hit + clip ready, person hit + clip not ready, person miss → `clip_found=0` always).

- [x] Task 3: IPC schema — extend `prefetch_result` contract (AC: 1, 3)
  - [x] 3.1 `tests/fixtures/ipc_schema.py`: add `"clip_found"` to `REQUIRED_FIELDS["prefetch_result"]`
        (currently `["type", "camera_eqlogic_id", "found", "event_id"]`, line 36); update
        `SAMPLE_PREFETCH_RESULT_HIT`/`SAMPLE_PREFETCH_RESULT_MISS` (lines 123-134) to include `clip_found`.
  - [x] 3.2 `tests/level2_5/test_callback_schema.py`: extend the existing `prefetch_result` schema tests —
        required fields now include `clip_found`, strictly `int`-typed (not `bool`) on both hit and miss,
        JSON round-trip.

- [x] Task 4: PHP — cache the clip outcome (AC: 3)
  - [x] 4.1 `core/class/siaDC09.class.php::_handlePrefetchResult()` (lines 596-620): add
        `'clip_found' => !empty($data['clip_found']),` to the cache-entry array literal (alongside the
        existing `'found'`/`'event_id'`/`'ts'` keys) — same unconditional fresh-array overwrite, no
        `array_merge`.
  - [x] 4.2 Level 1 test, extending `tests/level1/test_php_eqlogic_stub.py`'s existing
        `_handlePrefetchResult()` tests: the cached entry includes `clip_found` derived from the payload's
        `clip_found` key; a payload with `clip_found` absent/falsy stores `clip_found => false` (never
        crashes on a legacy/partial payload shape).

- [x] Task 5: PHP — resolve and attach the clip URL alongside the snapshot (AC: 4, 5)
  - [x] 5.1 `core/class/siaDC09Cmd.class.php::_buildFrigateMediaUrl()` (lines 406-435): add a third
        parameter `string $mediaFile = 'snapshot.jpg'` and replace the hardcoded
        `'/api/events/' . rawurlencode($eventId) . '/snapshot.jpg'` (line 412) with
        `'/api/events/' . rawurlencode($eventId) . '/' . $mediaFile`. Default preserves every existing
        caller's behavior unchanged (`_resolveFrigateSnapshotUrl()`'s call site needs no edit).
  - [x] 5.2 New private method `_resolveFrigateClipUrl(array $zoneEntry): ?string` — copy of
        `_resolveFrigateSnapshotUrl()`'s structure (lines 337-390: same cache lookup, same TTL/expiry rule,
        same template-configured check) but gates on `$entry['clip_found']` instead of `$entry['found']`,
        and calls `self::_buildFrigateMediaUrl($template, $eventId, 'clip.mp4')`. Same
        `try/catch (\Throwable $e)` guarantee, same debug logging convention at every null-return branch.
  - [x] 5.3 `execute()`'s `burglarAlarm`/`fireAlarm`/`panicAlarm` case (lines 81-104): after the existing
        `$snapshotUrl = $this->_resolveFrigateSnapshotUrl($zoneEntry);`, add
        `$clipUrl = $this->_resolveFrigateClipUrl($zoneEntry);`, then replace the current
        `if ($snapshotUrl !== null) { $payload['media_url'] = $snapshotUrl; }` with a join:
        `$mediaParts = array_filter([$snapshotUrl, $clipUrl], fn($u) => $u !== null); if (!empty($mediaParts)) { $payload['media_url'] = implode(' ', $mediaParts); }`
        — preserves the existing single-URL/omitted-key behavior exactly when only one or neither resolves.
  - [x] 5.4 Level 1 tests, extending `tests/level1/test_frigate_snapshot_resolution.py`: new test class for
        `_resolveFrigateClipUrl()` mirroring the existing snapshot-resolution test class (cache hit/miss/
        expired/template-missing → same null-return matrix, gated on `clip_found` not `found`); a test
        proving `_buildFrigateMediaUrl()`'s new `$mediaFile` param defaults to `'snapshot.jpg'` (no
        behavior change for existing callers) and correctly substitutes `'clip.mp4'` when passed; new tests
        on the `burglarAlarm` case in `execute()` (via the real-execution PHP harness already used for this
        file) covering all six AC5 cache-state combinations: both resolve → space-joined single string;
        snapshot only; clip only; neither → `media_url` key entirely absent from the payload; a cache entry
        with `clip_found` key missing entirely (simulating a stale pre-14-3 cache entry) → clip resolves to
        null, no crash.

- [ ] Task 6: Full regression + live validation on `test-jeedom.lehoux.net` (AC: 5, 6)
  - [x] 6.1 `php -l` clean on all modified PHP files; full `tests/level1/` suite compared against the known
        baseline (memory `level1-test-baseline-failures`) via `git stash -u` diff against clean master — 0
        regressions.
  - [x] 6.2 `pylint --disable=all --enable=E` clean on `resources/siadc09d/daemon.py` and
        `resources/siadc09d/frigate_prefetch.py`; full `tests/level1/`+`tests/level2/`+`tests/level2_5/`
        Python suites compared against baseline (same `git stash -u` method) — 0 regressions.
  - [x] 6.3 Deployed via `git push` (commit `eb4ac8f`) + `git pull` on `test-jeedom.lehoux.net` (Herve).
        Daemon required a manual restart post-deploy (was stopped — `supervision_label` read "ARRÊTÉ",
        matching memory `jeedom-daemon-down-looks-like-frozen-label`); confirmed running before proceeding.
  - [x] 6.4 Triggered via the Jeedom API (`prefetchEvent` id 282, then `burglarAlarm` id 279, both with
        `title=Zone2` — matching the real zone name, not a synthetic id; a first attempt using a
        synthetic unique title broke zone→camera resolution and is documented as a mistake below) with a
        real person in front of `vigi_sud-est` (Zone2, `frigate_camera_eqlogic_id=4`) at the moment of the
        `prefetchEvent` call. Daemon log confirms `{"found":1,"event_id":"1790433219.456768-lndwmp","clip_found":1}`.
        Received frame (`192.168.100.15:10002`, 2026-09-26 14:34:39 UTC):
        `[#001234|BA 002][Vhttps://<user>:<password>@frigate.lehoux.net/api/events/1790433219.456768-lndwmp/snapshot.jpg https://<user>:<password>@frigate.lehoux.net/api/events/1790433219.456768-lndwmp/clip.mp4]`
        — both URLs present, space-separated, `snapshot.jpg` before `clip.mp4`. AC5/AC6 confirmed live.
  - [x] 6.5 Confirmed by direct observation of the receiver's own log line above: the generic receiver at
        `192.168.100.15:10002` accepts and logs the full dual-URL `[V...]` field verbatim — no truncation,
        no rejection, no NAK. It does not itself interpret or render the two URLs (it is a generic
        line-logging receiver, not a monitoring-center client) — what a real operator console does with
        this exact shape remains unverified beyond "the receiver accepts the frame."
  - [x] 6.6 **Not live-reproduced, by Herve's explicit call** — in this deployment, `clip_found` is
        confirmed synchronously with person-event confirmation inside the same `prefetchEvent` REST
        round-trip (both live runs returned `found`/`clip_found` as the same value at the same timestamp,
        never one true and the other false), so a live snapshot-only race is not reliably producible on
        demand — forcing it would depend on Frigate's own recording-segment flush timing, not on anything
        this story's code controls. The snapshot-only code path (AC5's second bullet) is proven at the unit
        level by Task 5.4's cache-state test matrix (snapshot-only case passing, unchanged by this session's
        live work). Accepted as sufficient live-validation closure for this sub-case.

### Review Findings

Code review 2026-09-26 (`ed8af11..HEAD`, commits `eb4ac8f`+`6f64203`), three parallel adversarial layers
(Blind Hunter, Edge Case Hunter, Acceptance Auditor). All findings below verified against the actual code,
not taken at face value from the reviewers.

- [x] [Review][Decision] Clip attachment (like snapshot before it) reaches `fireAlarm`/`panicAlarm`
  frames, not just `burglarAlarm` — the story's own "Explicitly out of scope: PA/FA clip attachment
  (14-2's BA-only scope carries forward unchanged)" claim was factually inaccurate. Verified against
  `ed8af11` (pre-14-3): snapshot resolution was already shared across all three actions via the same
  `case 'burglarAlarm': case 'fireAlarm': case 'panicAlarm':` fallthrough (`siaDC09Cmd.class.php`) — there
  has never been a BA-only gate. **Resolved by Herve (2026-09-26): option 2 — corrected the doc, no code
  change.** Scope text in this story and in epics.md Story 14.3 updated to reflect the existing shared
  dispatch; no new BA-only gate added.

- [x] [Review][Patch] Clip-readiness poll can overrun the shared prefetch deadline [`resources/siadc09d/frigate_prefetch.py:174-186`] — `_poll_clip_ready()` fires its `_check_clip_ready` attempt unconditionally before checking `time.monotonic() >= deadline`, so an attempt starting near the deadline still consumes a full `http_timeout_s + PREFETCH_WAIT_FOR_SLACK_S` past it — stacking on top of the pre-existing person-event poll's identical shape and roughly doubling the worst-case overrun beyond `PREFETCH_MAX_WAIT_S`. Violates AC2 ("never blocks beyond the existing bounded `max_wait_s` budget"). The guard test (`test_total_elapsed_time_across_both_checks_stays_bounded_by_max_wait_s`, `tests/level1/test_frigate_prefetch.py:273-296`) mocks `_check_clip_ready` to return synchronously, so it never exercises the real `asyncio.wait_for(...)` timeout path and provides no actual protection against this. Flagged independently by all three review layers. **Fixed:** `_poll_clip_ready()` now computes `remaining = deadline - time.monotonic()` before every attempt, returns `False` immediately if exhausted, and caps the attempt's own timeout to `min(http_timeout_s, remaining)`. New regression test `test_clip_poll_attempt_timeout_bounded_by_remaining_deadline_not_full_http_timeout` (`tests/level1/test_frigate_prefetch.py`) actually exercises the real timeout path with a slow mock and would fail without the fix. 0 regressions (`tests/level1/` 1222 passed/2 failed, matching baseline exactly).

- [x] [Review][Patch] Cache read TOCTOU between snapshot and clip resolution [`core/class/siaDC09Cmd.class.php:98-99`] — `_resolveFrigateSnapshotUrl()` and `_resolveFrigateClipUrl()` each independently call `$eqLogic->getCache('sia_prefetch_cache', [])`, two separate reads of the same logical entry within one `execute()` call. A concurrent `_handlePrefetchResult()` callback landing between the two reads could join a snapshot URL from one event with a clip URL from a different, later event. Low practical likelihood (microsecond window, same PHP request) but the fix is trivial: decode the cache entry once and pass it to both resolvers. **Fixed:** new `_readPrefetchCacheEntry()` helper does the single read in `execute()`; both resolvers gained an optional `?array $cacheEntry = null` parameter — used as-is when provided (execute()'s call site), falling back to each method's own original internal read when not (preserves every existing static-analysis test's assumption that the read logic still lives inside each resolver's own body). `php -l` clean; `tests/level1/test_frigate_snapshot_resolution.py`/`test_php_eqlogic_stub.py` all green, 0 regressions.

- [x] [Review][Defer] No backoff/circuit-breaker on repeated `_check_clip_ready` HTTP polls if Frigate is slow/degraded [`resources/siadc09d/frigate_prefetch.py`] — deferred, pre-existing pattern (same shape as 14-2's person-event poll, not newly introduced by this story)
- [x] [Review][Defer] `_resolveFrigateClipUrl()` is a copy-paste of `_resolveFrigateSnapshotUrl()` rather than a shared parameterized helper [`core/class/siaDC09Cmd.class.php:420-468`] — deferred, real duplication-maintenance risk but low severity, a refactor not a defect
- [x] [Review][Defer] Evidence-permanently-understated risk: a clip that becomes ready just after the deadline is recorded `clip_found=false` forever for that alarm — deferred, already an accepted scope boundary of this design (same class of gap as the pre-existing miss-path contract), worth a doc note only
- [x] [Review][Defer] Bespoke space-separated dual-URL `[V...]` convention unverified against any real monitoring-center CSR parser — deferred, already transparently documented as an accepted risk in this story's own Task 6.5/6.6 notes
- [x] [Review][Defer] Test-quality gaps: `_run_execute_burglar_alarm` harness checks only `returncode==0` not `stderr` empty; stale-cache test only checks the fake `log` stub not real PHP stderr — deferred, matches this test suite's pre-existing harness pattern, not newly introduced by 14-3
- [x] [Review][Defer] sprint-status.yaml summary counter drift — deferred, matches known pre-existing project pattern (memory: sprint-status summary drift), not a 14-3-specific defect

Dismissed as noise (verified false against the actual code, not applied): `_buildFrigateMediaUrl` "empty-string join" edge case (method only ever returns `null` or a well-formed non-empty URL); `urllib.parse` "unconfirmed import" (it is imported at `frigate_prefetch.py:22`); `<user>:<password>` "looks like a leaked credential" (established placeholder-template convention, memory `media-url-template-never-real-secret`); duplicated AC text between epics.md and the story file (standard BMad convention, every story does this); Task 6.6 "declared sufficient by fiat" (already transparently documented as a deliberate call in this story, not a hidden gap).

## Dev Notes

### What already exists and must not be duplicated or broken (read before touching any file)

**`core/class/siaDC09Cmd.class.php`** (`/Users/herve.lehoux/dev-hlx/my-project/core/class/siaDC09Cmd.class.php`):
- `execute()` (lines 35-134): the `burglarAlarm`/`fireAlarm`/`panicAlarm` case (lines 81-104) is where
  `media_url` gets attached to the outbound daemon payload today. Lines 97-101 are the exact block Task 5.3
  replaces.
- `_resolveFrigateSnapshotUrl()` (lines 337-390): reads `getEqLogic()->getCache('sia_prefetch_cache', [])`,
  looks up the entry keyed by `frigate_camera_eqlogic_id`, checks `found` + TTL (`PREFETCH_CACHE_TTL = 120`,
  line 27) + `frigate_media_url_template` configured, then calls `_buildFrigateMediaUrl()`. This method
  itself is **unchanged** by this story — only its new sibling (`_resolveFrigateClipUrl()`) is added.
- `_buildFrigateMediaUrl()` (lines 406-435): builds an absolute URL from the template + event id, inserting
  `api/events/{eventId}/snapshot.jpg` into the template's path before any query string (critical for the
  query-token credential form). Task 5.1 parameterizes the trailing path segment; every existing behavior
  for the two-argument call form is preserved by the new parameter's default.
- The `sia_prefetch_cache` cache entry shape today (per `_handlePrefetchResult()` in `siaDC09.class.php`) is
  `['found' => bool, 'event_id' => ?string, 'ts' => int]` — Task 4.1 adds `'clip_found' => bool` as a fourth
  key, same entry, same cache, same TTL rule (both fields share one `ts`/expiry — there is no independent
  clip TTL, since both outcomes are written by the same single callback at the same moment).

**`core/class/siaDC09.class.php`**:
- `message()`'s `switch` (lines 484-572), `case 'prefetch_result':` (line 498) already dispatches to
  `_handlePrefetchResult()` (lines 596-620) — **no new case is needed**; Task 4.1 only extends the array
  literal at line 611-615.

**`resources/siadc09d/frigate_prefetch.py`**:
- `PrefetchResult` dataclass (lines 52-58), `_query_latest_person_event()` (lines 82-118, unchanged — still
  no `in_progress` filter, per 14-2's live-validated correction), `prefetch_person_event()` (lines 121-168,
  the poll loop Task 1.3 extends). The module's own constants (`PREFETCH_AFTER_BUFFER_S = 30.0`,
  `PREFETCH_MAX_WAIT_S = 25.0`, `PREFETCH_POLL_INTERVAL_S = 2.0`, `PREFETCH_HTTP_TIMEOUT_S = 5.0`,
  `PREFETCH_WAIT_FOR_SLACK_S = 1.0`) are tuned for the person-event query alone; Task 1.3 must fit the clip
  check inside the *same* `deadline`, not add a second budget on top — a longer total prefetch risks losing
  the race against a short installer-configured trigger delay (an already-deferred risk from 14-2,
  D-53/D-52 in `deferred-work.md` — this story must not make that margin worse without at least flagging
  it).

**`resources/siadc09d/daemon.py`**:
- `_run_prefetch()` (lines 2192-2221) is the only site that builds the `prefetch_result` callback payload —
  Task 2.1's one-line addition. `on_message()`'s `prefetchEvent` branch (lines 2102-2133) and
  `OnMessageParams` (lines 237-260) need **no changes** — `clip_found` never flows PHP→daemon, only
  daemon→PHP, and the existing `camera_eqlogic_id`/`camera_name`/`frigate_host` dispatch is unaffected.
- `_send_callback()` (lines 487-521): drops the **entire payload** if any value is a Python `bool` — confirm
  `clip_found` is sent as `1`/`0` int, exactly like the existing `found` field on the same line.

**`resources/siadc09d/sia_protocol.py`**: `_format_extended_data_field()` (lines 420-446) already treats
`media_url` as an opaque string and wraps it in a single `[V...]` block — **no change needed here at all**.
As long as PHP joins snapshot+clip with a single space before sending `media_url` in the daemon payload, the
daemon and `sia_protocol.py` need zero awareness that two URLs are inside that one string. This is the
reason the space-join happens PHP-side (Task 5.3), not daemon-side.

### Frigate REST reference for the clip check (verified in 14-2, reused here)

`scripts/frigate_latency_probe.py` (not part of the shipped plugin, a standalone investigation tool,
`main()`/`argparse` entrypoint — do not import it, port the relevant check): its `poll()` function (lines
114-161) already probes both the event row's `has_clip` boolean (line 137) and the guessable
`{base_url}/api/events/{event_id}/clip.mp4` URL's HTTP status directly (lines 140-143,
`_http_status()`). Either signal is a valid basis for Task 1.2's `_check_clip_ready()` — the event-row
`has_clip` field is one HTTP call cheaper (no need to also probe the URL itself) and is the more direct
signal Frigate itself exposes for readiness; prefer it unless the live host validation (Task 6) shows it
lags behind the guessable URL's own 200 status.

### Why this story needs no wizard/config changes

`frigate_media_url_template` (wizard step 3, story 14-1) already stores a URL template with literal
placeholder credentials, substituted into the path before any query string. The clip URL differs from the
snapshot URL only in the final path segment — reusing the exact same template field for both is why AC/Task
5.1 only needs a new *parameter*, not a new config field, matching the epics story's explicit "no new wizard
field" scope note.

### Testing Strategy

Level 1 (PHP structural/regex + real-execution subprocess for the pure functions, matching 14-1/14-2's
established pattern) for all `siaDC09Cmd.class.php`/`siaDC09.class.php` changes. Level 1 (Python,
`unittest.mock`) for `frigate_prefetch.py`'s new clip check — no live Frigate server required. Level 2
(Python, exercising `_run_prefetch()`'s real callback-payload construction, mocking only the HTTP calls) for
the daemon wiring. Level 2.5 for the IPC schema contract extension. Task 6 (live validation) requires the
real `test-jeedom.lehoux.net` host, a real Frigate camera, and the real receiver at
`192.168.100.15:10002` — per memory `jeedom-ui-validation-over-reflection`, AC6 in particular is a genuine
open question (this exact `[V...]` shape has never been sent to that receiver before) and must be answered
by direct observation, not inferred as a pass.

### Project Structure Notes

- PHP alarm-trigger logic: `core/class/siaDC09Cmd.class.php` (`_buildFrigateMediaUrl()` parameterized,
  new `_resolveFrigateClipUrl()`, `execute()`'s `burglarAlarm` case join logic)
- PHP callback handling: `core/class/siaDC09.class.php` (`_handlePrefetchResult()` extended, no new switch
  case)
- Daemon: `resources/siadc09d/frigate_prefetch.py` (`PrefetchResult` extended, new `_check_clip_ready()`,
  `prefetch_person_event()` extended), `resources/siadc09d/daemon.py` (`_run_prefetch()`'s callback payload
  extended — no new dispatch branch)
- No changes: `resources/siadc09d/sia_protocol.py`, `resources/siadc09d/daemon.py`'s `OnMessageParams`/
  `on_message()` dispatch, `desktop/php/siaDC09.php` (no new wizard field)
- Tests: `tests/level1/test_frigate_prefetch.py` (extended), `tests/level1/test_frigate_snapshot_resolution.py`
  (extended), `tests/level1/test_php_eqlogic_stub.py` (extended), `tests/level2/test_frigate_prefetch_dispatch.py`
  (extended), `tests/fixtures/ipc_schema.py` + `tests/level2_5/test_callback_schema.py` (extended)

## Previous Story Intelligence (from 14-2, `14-2-frigate-event-prefetch-immediate-action.md`)

- **The daemon-caches-in-memory prose in ADR-17 Amendment 3 is not literal** — already reconciled once
  before (14-2's Dev Notes, "Why the daemon's own in-memory intent and the Jeedom-side cache are not the
  same thing"): no synchronous PHP↔daemon request/response exists on the control socket
  (`jeedomdaemon`'s `Listener` closes the connection before `on_message()` runs). The daemon's only channel
  back to PHP is the existing `_send_callback()`/HTTP-callback push. This story hits the exact same class of
  mismatch for "the daemon constructs a clip URL" — resolved the same way (see Context section above): the
  daemon confirms readiness, PHP constructs the string.
- **Deploy via git push then pull on the host** (memory `jeedom-test-host-deploy`) — every live attempt in
  14-2 needed a fresh push/pull cycle; budget for several iterations during Task 6.
- **Debug logging at every null-return branch was a hard-won lesson** — 14-2's first live attempt produced
  no diagnosable trace at all because `_resolveFrigateSnapshotUrl()` initially had zero logging on its null
  branches (only exception paths were logged). `_resolveFrigateSnapshotUrl()` now has debug logging at
  every branch (lines 341-384) — `_resolveFrigateClipUrl()` (Task 5.2) must copy this logging density from
  the start, not add it reactively after a failed live run.
- **`array_merge` is explicitly forbidden** on the `sia_prefetch_cache` write — a miss must be able to erase
  an earlier hit outright. This extends unchanged to `clip_found`: the whole entry (including `clip_found`)
  is a fresh overwrite every callback, never a partial merge.
- **`_send_callback()` drops bools silently** (logs ERROR, drops the *entire* payload) — `found` is already
  sent as `int`; `clip_found` must follow the identical convention or the whole `prefetch_result` push is
  lost, silently, for both fields.
- **Deferred items D-52/D-53 (accepted as-is by Herve, 2026-09-24)**: no dedup/cancellation for concurrent
  same-camera `prefetchEvent` triggers, and a tight margin between the prefetch's worst-case completion time
  and a short installer-configured trigger delay. This story's Task 1.3 extends the same bounded window with
  a clip check — do not silently widen the worst-case completion time without at least noting the effect on
  that already-accepted margin.
- **Live validation needs multiple iterations, each surfacing a real bug** — 14-2 needed four live attempts,
  each fixing a distinct issue (wrong `subType`, wrong REST filter, missing logging, empty config field).
  Budget realistic time for Task 6, and add logging *before* the first live attempt, not after a failure.

## References

- ADR-17, Amendment 3 — `_bmad-output/planning-artifacts/architecture.md:393-502`
- Epic 14 / Story 14.3 — `_bmad-output/planning-artifacts/epics.md:2362-2418`
- Story 14.2 — `_bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md`
  (prefetch cache mechanism this story extends; daemon-caches-vs-Jeedom-cache reconciliation reused as-is)
- Story 14.1 — `_bmad-output/implementation-artifacts/14-1-attach-frigate-snapshot-alarm-frame.md`
  (`frigate_media_url_template` wizard field and `_buildFrigateMediaUrl()`'s original construction, reused
  as-is, only parameterized)
- `scripts/frigate_latency_probe.py` — clip-readiness probing methodology (`has_clip` field, guessable-URL
  status check) this story's Task 1.2 promotes into production code
- SIA DC-09 protocol spec — `internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` §5.5.1.8 (free-form
  Verification field)
- Memory: `frigate-detect-person-staleness-risk`, `jeedom-ui-validation-over-reflection`,
  `jeedom-test-host-deploy`, `sia-test-server-endpoint`, `level1-test-baseline-failures`,
  `media-url-template-never-real-secret`, `parallel-agents-daemon-conflict` (daemon.py is a merge hot-spot)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (eu.anthropic.claude-sonnet-5), via the bmad-dev-story workflow, 2026-09-26.

### Debug Log References

- Baseline established before any change (clean master): `tests/level1/` 2 failed/1188 passed,
  `tests/level2/` 6 failed/349 passed, `tests/level2_5/` 1 failed/76 passed — matches memory
  `level1-test-baseline-failures` exactly.
- `_check_clip_ready()`'s existing-test interaction: the pre-existing Task 1 tests in
  `tests/level1/test_frigate_prefetch.py` did not anticipate a second network call after a
  person-event hit. Running them unmodified caused `test_query_sends_expected_params` to fail
  (captured 7 requests instead of 1 — the shared `_get_json` mock was also being hit by the new
  clip-readiness poll loop) and made the whole file slow (~17s, real network attempts against an
  unreachable 192.168.100.18:5000). Fixed by patching `_check_clip_ready` directly (decoupled from
  `_get_json`) in the affected pre-existing tests and adding explicit `clip_found` assertions —
  legitimate, since Dev Notes/Task 1.5 explicitly scope this file for extension. Full file now runs
  in ~2.4s, 12/12 passing.
- Final full-suite run after all 5 code tasks: `tests/level1/` 2 failed/1214 passed (+26 net new
  passing tests), `tests/level2/` 6 failed/350 passed (+1), `tests/level2_5/` 1 failed/77 passed
  (+1) — same 9 pre-existing baseline failures, 0 regressions introduced.
- `php -l` clean on both modified PHP files; `pylint --disable=all --enable=E` on
  `resources/siadc09d/daemon.py` and `resources/siadc09d/frigate_prefetch.py` — 10.00/10, no errors.

### Completion Notes List

- **Tasks 1-5 (AC1-AC5) implemented via TDD, all green.** Daemon confirms clip readiness only
  after a person event is confirmed (`_check_clip_ready()` reads the event row's `has_clip`,
  polled via `_poll_clip_ready()` inside the same shared `deadline` as the person-event poll — no
  second `max_wait_s` budget added, per Dev Notes' explicit constraint about not widening the
  already-accepted D-52/D-53 margin). `PrefetchResult.clip_found` flows daemon → `_run_prefetch()`'s
  callback payload (`clip_found` as int 0/1, same `_send_callback()` bool-drop guard as `found`) →
  PHP's `_handlePrefetchResult()` cache write (fresh-array overwrite, no `array_merge`, same as
  `found`/`event_id`) → `siaDC09Cmd::_resolveFrigateClipUrl()` (new sibling of
  `_resolveFrigateSnapshotUrl()`, same cache/TTL, gated on `clip_found`) → `execute()`'s
  `burglarAlarm` case, which now resolves both URLs and space-joins them into one `media_url`
  when both are present, falls back to whichever resolves alone, omits the key entirely when
  neither does.
- `_buildFrigateMediaUrl()` gained a third parameter (`$mediaFile = 'snapshot.jpg'`) rather than a
  new method — every pre-14-3 caller keeps its exact behavior via the default; `clip.mp4` is only
  ever passed by the new `_resolveFrigateClipUrl()`.
- A stale/legacy cache entry missing the `clip_found` key entirely (any cache entry written before
  this story shipped) is handled the same defensive way as a false `found` always was — `!empty()`
  on a missing key is `false`, so the clip resolves to null and the snapshot alone is still
  attached; verified with a dedicated real-PHP-execution test
  (`test_stale_pre_14_3_cache_entry_missing_clip_found_key`).
- **AC6 (Task 6.4-6.6) and the deploy prerequisite (Task 6.3) are BLOCKED, not completed and not
  silently skipped.** This dev session has no network access to `test-jeedom.lehoux.net` or the
  real receiver at `192.168.100.15:10002`. Per project instructions, no live-validation pass is
  fabricated here — AC6 in particular is described in the story itself as "a genuine open
  question" that must be answered by direct observation. Story Status is left at `in-progress`
  (not `review`) because Task 6 is not fully checked off; sprint-status.yaml reflects the same.
  Whoever picks this up next needs real connectivity to the host and the receiver to close out
  Task 6.3-6.6 and only then can Status legitimately move to `review`.
- No changes were made to `resources/siadc09d/sia_protocol.py` — verified directly (not just taken
  on the story's own claim) that `_format_extended_data_field()` treats `media_url` as an opaque
  string it wraps in a single `[V...]` block, with no per-token parsing of its contents. The
  space-join happening PHP-side is therefore sufficient and correct as designed.

### File List

- `resources/siadc09d/frigate_prefetch.py` — extended `PrefetchResult` with `clip_found`; added
  `_check_clip_ready()` and `_poll_clip_ready()`; `prefetch_person_event()` now checks clip
  readiness (within the same shared deadline) after a confirmed person event.
- `resources/siadc09d/daemon.py` — `_run_prefetch()`'s `prefetch_result` callback payload now
  includes `clip_found` (int 0/1).
- `core/class/siaDC09.class.php` — `_handlePrefetchResult()`'s cache-entry array literal now
  includes `clip_found`.
- `core/class/siaDC09Cmd.class.php` — `_buildFrigateMediaUrl()` gained a `$mediaFile` parameter
  (default `'snapshot.jpg'`); new `_resolveFrigateClipUrl()` method; `execute()`'s
  `burglarAlarm`/`fireAlarm`/`panicAlarm` case now resolves and space-joins both snapshot and
  clip URLs into `media_url`.
- `tests/level1/test_frigate_prefetch.py` — extended/adjusted existing tests for the new clip
  check; added `_check_clip_ready()` unit tests and clip-poll integration tests (only-after-hit,
  independent-failure, elapsed-time-bounded).
- `tests/level2/test_frigate_prefetch_dispatch.py` — extended hit/miss callback-payload tests for
  `clip_found`; added a person-hit-but-clip-not-ready combination test.
- `tests/fixtures/ipc_schema.py` — `REQUIRED_FIELDS["prefetch_result"]` and both sample payloads
  now include `clip_found`.
- `tests/level2_5/test_callback_schema.py` — added `clip_found` int-not-bool schema test.
- `tests/level1/test_php_eqlogic_stub.py` — added `_handlePrefetchResult()` `clip_found` storage
  test.
- `tests/level1/test_frigate_snapshot_resolution.py` — added `_buildFrigateMediaUrl()`
  default/substitution tests; new `TestResolveFrigateClipUrlExists` class; new real-PHP-execution
  harness + `TestExecuteBurglarAlarmMediaUrlJoin` class covering all six AC5 cache-state
  combinations plus a stale-cache-shape and an expired-entry case.
- `_bmad-output/implementation-artifacts/14-3-attach-frigate-clip-alongside-snapshot.md` — this
  story file (Tasks/Subtasks, Dev Agent Record, Status).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `14-3-attach-frigate-clip-alongside-snapshot`
  status `ready-for-dev` → `in-progress`; summary counters updated.

## Change Log

| Date | Change |
|------|--------|
| 2026-09-26 | Story file created from epics.md Story 14.3, extending 14-2's prefetch/cache mechanism. Corrected the epics AC's "daemon constructs a clip URL via frigate_media_url_template" framing during story creation: the daemon has zero Jeedom dependencies by design and cannot read that config field — resolved design has the daemon only confirm clip readiness (new `clip_found` on the existing `prefetch_result` callback), with PHP constructing both URLs via the existing `_buildFrigateMediaUrl()` (parameterized for snapshot vs clip), matching 14-2's own precedent for the same class of ADR-prose-vs-architecture mismatch. |
| 2026-09-26 | Dev session (TDD, red-green-refactor per task): Tasks 1-5 implemented and fully tested (AC1-AC5). Daemon's `_check_clip_ready()`/`_poll_clip_ready()` added to `frigate_prefetch.py`, sharing the person-event poll's single `deadline`; `daemon.py`'s callback payload extended with `clip_found`; IPC schema (`ipc_schema.py`/`test_callback_schema.py`) extended; PHP `_handlePrefetchResult()` caches `clip_found`; PHP `_buildFrigateMediaUrl()` parameterized, new `_resolveFrigateClipUrl()` added, `execute()`'s `burglarAlarm` case space-joins both URLs. Full regression run: `tests/level1/` 1214 passed/2 failed, `tests/level2/` 350 passed/6 failed, `tests/level2_5/` 77 passed/1 failed — identical to the known pre-existing baseline (memory `level1-test-baseline-failures`), 0 regressions. `php -l` clean, `pylint --disable=all --enable=E` 10.00/10. Task 6.3-6.6 (deploy + live validation on test-jeedom.lehoux.net / real receiver) BLOCKED — no network access from this sandboxed session; deferred, not skipped, not fabricated as a pass. Status stays `in-progress`; sprint-status.yaml updated to match. |
| 2026-09-26 | Deployed (`git push` commit `eb4ac8f` + `git pull` on `test-jeedom.lehoux.net`) and live-validated via the Jeedom API against the real receiver `192.168.100.15:10002`. Daemon had to be restarted post-deploy (found stopped — memory `jeedom-daemon-down-looks-like-frozen-label`). First live attempt used a synthetic unique `title` param for `prefetchEvent`/`burglarAlarm`, which broke zone→camera resolution (title IS the zone name for mapping lookup) — corrected to the real zone name (`Zone2`). Second attempt (no person in frame at prefetch time) returned `found=0`/`clip_found=0`, confirming the "neither" fallback (no `[V...]` field at all) but not the dual-media case. Third attempt (person physically in front of `vigi_sud-est` at the exact `prefetchEvent` call) succeeded: daemon returned `found=1`/`clip_found=1`, PHP resolved and space-joined both URLs, and the real receiver logged the frame with `[Vsnapshot.jpg-url clip.mp4-url]` verbatim — AC5/AC6 confirmed end-to-end (Task 6.3/6.4/6.5). Task 6.6 (live snapshot-only case) not reproduced — Herve's call: `clip_found` resolves synchronously with person confirmation in this deployment (both live runs showed `found`/`clip_found` matching, never split), so the race is not reliably producible on demand; the snapshot-only path stays validated at the unit level only (Task 5.4). Status: in-progress → review. |
