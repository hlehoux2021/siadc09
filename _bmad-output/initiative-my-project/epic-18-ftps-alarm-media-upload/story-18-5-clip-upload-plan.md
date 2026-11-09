---
title: '18.5 - Clip upload'
type: 'feature'
ticket: '18.5'
created: '2026-11-09'
status: 'built'
baseline_revision: '8cb69b00f6938a755f177b30b407186bb6e5e6e1'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/internal-docs/ftps-test-server.md'
  - '{project-root}/.claude/rules/python-style.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Since 18.2 only the snapshot of a BA alarm reaches the FTPS server; the receiver cannot see the clip (E18-R2).

**Approach:** PHP tells the daemon which media the equipment wants (snapshot and/or clip, from the existing switches). After the snapshot, the daemon reads the event row from the Frigate API, waits only for what the event still lacks (a clip, or the end of the event), derived from the row's own times, then downloads the clip into a size-capped temporary file and uploads it with the same FTPS logic. In practice the BA fires after the alarm plugin's trigger delay, long after the immediate-action prefetch created the event, so the wait is usually zero. The frame and the snapshot never wait for the clip.

## Boundaries & Constraints

**Always:** The frame is sent as today and never waits. The clip is read in chunks into a size-capped temporary file, never fully in memory, and the file is deleted after the attempt. A clip failure is an ERROR reported to the user like a snapshot failure, with its own wording (video). Snapshot and clip are independent: one failing does not skip the other. The password stays out of logs and callbacks.

**Time limits follow the clip, not fixed numbers.** The wait for the clip is `end_time - now + CLIP_END_MARGIN_S` read from the event row (zero when the event already ended), capped by `CLIP_MAX_WAIT_S`; when `end_time` is missing or beyond the cap the daemon downloads what exists. The download deadline is `CLIP_DOWNLOAD_BASE_S` plus the clip duration (`end_time - start_time`), and the FTPS upload deadline is computed the same way.

**Never:** Waiting indefinitely for the event end; final naming/layout (18.8); wizard (18.4); the overall upload deadline and certificate hardening (18.6); a clip for non-BA events; reading the Frigate plugin's stored files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Both switches on | BA, ftps | Snapshot then clip uploaded; frame untouched | No error expected |
| Clip only | snapshot switch off, clip on | Only the clip is uploaded | None |
| Snapshot only | clip switch off | Behaviour of 18.2 | None |
| BA after the trigger delay | Event ended, clip complete | Downloaded and uploaded at once, no wait | None |
| Event still running | `end_time` in the near future | Waits until `end_time` plus margin (capped), then downloads the full clip | None |
| Clip not ready | Frigate answers 4xx or has no clip | Retried every `CLIP_POLL_INTERVAL_S` within the computed wait | After the wait: ERROR + notification (video not transmitted); snapshot unaffected |
| Clip too large | Body above `CLIP_MAX_BYTES` | Download stopped, nothing uploaded | ERROR + notification naming the cap |
| Snapshot fails, clip ok | FTPS refuses the first upload | Clip still attempted | One notification per failed media |

</frozen-after-approval>

## Code Map

- `core/class/siaDC09Cmd.class.php:160-175,246` -- `execute()` resolves `ftps_upload` only when the snapshot switch is on; resolve it when the snapshot or the clip switch is on and add `snapshot`/`clip` booleans to the payload; `_resolveFtpsUpload()` already checks the cache entry (`clip_found` is in it)
- `resources/siadc09d/daemon.py:~590-660` -- `_run_ftps_upload()`: read the booleans, snapshot first, then the clip; `_report_ftps_failure()` takes a media label; `FTPS_UPLOAD_DEADLINE_S` (:275) bounds the snapshot, add a clip deadline
- `resources/siadc09d/frigate_prefetch.py:~125,300+` -- `_get_bytes`/`fetch_event_snapshot` pattern and `_check_clip_ready()` (`has_clip`); add a chunked clip download to a temp file with the byte cap
- `resources/siadc09d/ftps_upload.py:~121` -- `upload_bytes()` takes bytes; add a file-based variant (`storbinary` from the open file) sharing the same connect/TLS/fingerprint steps and error wording
- `resources/siadc09d/messages.py` -- failure wording: add a video variant of `FTPS_UPLOAD_FAILED`
- Do not change: frame building, snapshot behaviour, the prefetch ranking logic
- Tests to imitate: `tests/level2/test_ftps_upload_dispatch.py`, `tests/level1/test_ftps_upload.py`

## Tasks & Acceptance

**Execution:**
- [ ] `core/class/siaDC09Cmd.class.php` -- `ftps_upload` carries `snapshot` and `clip` flags from the switches -- E18-R2
- [ ] `resources/siadc09d/frigate_prefetch.py` -- `fetch_event_clip()` polls then streams to a size-capped temp file -- bounded, no full clip in memory
- [ ] `resources/siadc09d/ftps_upload.py` -- upload from a file path, same steps and traces -- one FTPS code path
- [ ] `resources/siadc09d/daemon.py`, `messages.py` -- sequence snapshot then clip, independent failures, video wording, temp file cleanup -- matrix
- [ ] `tests/level1/`, `tests/level2/` -- one test per matrix row (mocked Frigate and ftplib) plus temp-file deletion and the cap -- proves the matrix
- [ ] `internal-docs/design/daemon-design.md` -- clip path paragraph -- design stays current

**Acceptance Criteria:**
- Given both switches on and the 18.1 server, when a BA alarm fires, then the snapshot and a playable `.mp4` are in the remote folder (field check).
- Given the clip is never ready, when the maximum wait passes, then the snapshot is already uploaded, the frame was never delayed, and the user is notified that the video was not transmitted.
- Given any run, when it ends, then no temporary clip file remains.

## Implementation Notes

## Plan Change Log

## Review Triage Log

- medium, patched: the clip retry window was measured from the start of the call, so a long event-end wait (up to 60 s) left no retry -- now measured after the wait; test added.
- medium, patched: a failure to create the temporary file ended the task with an unhandled exception, no ERROR and no notification -- now a ClipFetchError; test added.
- low, patched: a local write error (disk full, permission) was reported as "clip not available on Frigate" -- now named as a disk error; test added.
- low, patched: the PHP log said "pas d'envoi de photo" in a clip-only configuration -- now "photo ni de vidéo".
- low, patched: duplicated magic strings in `frigate_prefetch.py` named.
- low, rejected: six-parameter `_run_ftps_upload` (the fix is a payload value object, more than a correction); real sleeps with shrunk constants and a cross-module test helper import (tests pass, no flake seen); assert comments shared by two asserts; no PHP behavioural test (the PHP tests are source checks by design here).
- Note: the retry window after the event-end wait is `CLIP_MAX_WAIT_S` (60 s); the plan's "within the computed wait" read literally would be zero for an ended event, which cannot absorb the HTTP 400 Frigate gives a fresh clip.

## Design Notes

Timing (user, 2026-11-09): the prefetch runs on the alarm plugin's immediate trigger action; the BA is generated after the trigger's own delay. The event row gives `start_time`/`end_time` (a manual event ends at start + 30 s duration + 5 s, as seen in the logs), so every limit is derived from it instead of fixed. Constraint to know: `PREFETCH_CACHE_TTL` (120 s) still bounds how long after the prefetch a BA may come; a longer trigger delay finds no cached event and uploads nothing (logged).

Frigate facts (checked on 0.17.2, see the Frigate manual-event memory): `clip.mp4` of a manual event answers HTTP 400 until the first segments are flushed, then serves a partial clip that grows. The remote name is `<account>-<event id>-clip.mp4` until 18.8.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the recorded baseline (5 level2)
- `python3 -m pylint resources/siadc09d/` -- expected: no new messages
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom with both switches on: BA alarm leaves the snapshot and a playable clip in `upload/`; with the server stopped, an ERROR and a notification appear.
