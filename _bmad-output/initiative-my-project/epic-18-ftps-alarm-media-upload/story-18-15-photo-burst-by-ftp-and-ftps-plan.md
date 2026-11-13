---
title: '18.15 — Photo burst by FTP and FTPS'
type: 'feature'
ticket: '15'
created: '2026-11-13'
status: 'built'
baseline_revision: 'd3a6c2737f9e0237710390f947d1429d7406ba3e'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A BA alarm verified by FTP/FTPS uploads one snapshot; the receiver wants a series it can rebuild a video from.

**Approach:** On `prefetchEvent` the daemon starts a tracked task that grabs 5 photos (1 per second, `latest.jpg`) into memory, tied to the `run_id`. When the BA alarm arrives, the daemon uploads them as `{UID}_{zone}_{epoch of the photo}_0001..0005.jpg` over one connection; without a series it sends the single event snapshot as today.

## Boundaries & Constraints

**Always:** FTP/FTPS only, only when the photo is wanted; series in memory only, dropped after 120 s, never sent without a BA alarm; the SIA frame never waits; one notification for a partial failure; password never logged; no Frigate event snapshot with a series (amended 2026-11-14); each photo named with its own capture epoch second.

**Always (decisions, user 2026-11-13):** the 5 photos are taken right after the immediate action (the delay only lets a legitimate user cancel), not in a rolling buffer; send whatever can be obtained: series, event snapshot and clip are independent, and a missing Frigate event never blocks the series (nor the reverse). The PHP side builds `ftps_upload` when a `run_id` exists even with no event id.

**Never:** equipment setting or wizard field for count/interval; touching the SIA URL transport and its `[V...]` tag; writing photos to disk; one connection per photo.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Full series | 5 photos held, BA alarm | 5 files 0001..0005 on one login, then event snapshot | No error expected |
| Alarm early | 2 photos held | the 2 are sent | none |
| No series | none held / daemon restarted | single event snapshot as before (18.13 name) | none |
| Cancelled in delay | no BA alarm | nothing uploaded; series expires at 120 s | none |
| Partial failure | connection drops after 3 | one notification "3 photos sur 5" | logged ERROR, no retry |
| Camera offline | identical bytes | series sent, one WARNING | none |
| latest.jpg refused | HTTP error | no series, fallback single snapshot | one WARNING |
| No Frigate event | manual create refused, series held | series sent; no snapshot or clip | one WARNING for the missing event |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/frigate_prefetch.py` -- add `fetch_latest_jpeg(frigate_host, camera)` (reuse `_get_bytes` + `_run_with_deadline_timeout`) and the series capture coroutine; constants `BURST_COUNT=5`, `BURST_INTERVAL_S=1.0`.
- `resources/siadc09d/ftps_upload.py` -- `remote_location(..., image=1)` replaces `IMAGE_NUMBER`; split `_upload_stream` so one login STORs several files (`upload_many`); keep `upload_bytes`/`upload_file` signatures.
- `resources/siadc09d/daemon.py` -- `on_message` prefetchEvent branch (~2978) starts the burst task; `_burst_series` dict keyed by run_id with TTL; `FtpsAlarmMedia` (~199) gains `run_id`; `_run_ftps_upload` (~642) / `_upload_snapshot` (~702) send series, then snapshot; one failure notification via `_report_ftps_failure`.
- `core/class/siaDC09Cmd.class.php` -- prefetchEvent payload (~103) adds `burst` flag (ftps transport active and photo wanted); `ftps_upload` payload (~174) adds `run_id` from the cache entry; `_resolveFtpsUpload` (~250) must return a payload with an empty `event_id` when a `run_id` exists, instead of null. Daemon (~3098) then accepts `run_id` without `event_id`.
- `tests/level1/test_ftps_remote_layout.py`, `tests/level2/test_ftps_clip_dispatch.py` -- conventions to follow (daemon fixture with `_ftps`, `AsyncMock` callbacks).
- Do not change: `prefetch_alarm_media` logic, SIA frame building, URL transport.

## Tasks & Acceptance

**Execution:**
- [x] `internal-docs/ftps-test-server.md` -- check `GET /api/<camera>/latest.jpg?...` with curl on test-frigate (no login, query params), record the result -- the ticket's assumption (Herve ran it on the Frigate host 2026-11-14, camera `reolink`: `200 image/jpeg 29237`; result recorded in the doc)
- [x] `resources/siadc09d/ftps_upload.py` -- image number parameter, multi-file upload on one connection -- one login per series
- [x] `resources/siadc09d/frigate_prefetch.py` -- latest.jpg fetch and series capture, camera-offline duplicate warning -- photo source
- [x] `resources/siadc09d/daemon.py` -- series store with TTL, burst task, upload of series then snapshot, fallback, partial-failure notice
- [x] `core/class/siaDC09Cmd.class.php` -- burst flag and run_id in the payloads
- [x] `tests/level1`, `tests/level2` -- the I/O matrix rows
- [x] `internal-docs/ftps-test-server.md` (l.98), `internal-docs/design/daemon-design.md` -- document the series

**Acceptance Criteria:**
- Given a zone with a delay, FTPS and photo on, when the BA alarm fires, then five files ...0001.jpg to ...0005.jpg reach the server over one connection.
- Given an alarm cancelled during the delay, when 120 s pass, then nothing was uploaded and the series is gone.
- Given no series, when the BA alarm fires, then one photo is sent as before.

## Implementation Notes

- Event snapshot naming with a series: it takes the next image number (`0006` after 5 photos, `0003` after 2) and goes on the same login as the series. Without a series it keeps the 18.13 name `0001`.
- Partial-failure count: "N photos sur M" counts every photo of the batch, so with an event snapshot a full series is "x sur 6". The matrix row (no event) gives "3 photos sur 5".
- `IMAGE_NUMBER` replaced by `remote_location(..., image=1)` (keyword-only) and `FIRST_IMAGE`. `_upload_stream` takes a list of transfers plus one deadline; `upload_bytes`/`upload_file` signatures unchanged; new `upload_many(settings, [(name, bytes)], deadline)`. `FtpsUploadError.sent` counts files stored before the failure.
- Series store: `daemon._burst_series[run_id]` = photos list + tracked capture task + `loop.call_later(120 s)` expiry. BA alarm takes the photos and cancels a capture still running (early alarm). A series is also dropped when the BA wants the clip only.
- latest.jpg URL: `/api/<camera>/latest.jpg?timestamp=0&bbox=0&zones=0&mask=0&motion=0&regions=0`, from `helpers/plugin-frigate` (`frigate.class.php:1797`). Checked by Herve on test-frigate 2026-11-14 (camera `reolink`): `200 image/jpeg 29237`.
- PHP: with a recent run but no event, `_resolveFtpsUpload` logs one warning and returns `event_id = ''`; the daemon then sends the series alone (or nothing) with one WARNING.

## Plan Change Log

## Review Triage Log

| # | Finding (quick) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | `latest.jpg` never called on a real Frigate; AC1 shown with mocks only | maybe-false (medium if true) | URL shape copied from `frigate.class.php:1797`; settled only by the curl in `ftps-test-server.md` on test-frigate (192.168.100.18:5000 not reachable from the dev machine) | defer, then settled 2026-11-14: Herve's curl on test-frigate returned `200 image/jpeg` |
| 2 | AC2 test calls `_expire_burst` by hand, not via the timer | false | `_start_burst` wires `call_later(BURST_TTL_S, self._expire_burst, run_id)`: right callback, right arg; the test asserts the 120 s arming | reject |
| 3 | Two WARNINGs (PHP + daemon) for one missing event; matrix asks one | low | `_resolveFtpsUpload` new warning + `_run_ftps_upload` warning both fire on the same alarm; fix is a deletion | patch |
| 4 | PHP warning text claims a series may be sent when only the clip is wanted | low | `burst` is false with photo off, and the daemon drops the series when `snapshot` is false; same root cause as 3 (PHP warns about an outcome it cannot know) | patch (with 3) |
| 5 | With a series, a missing event snapshot is only a WARNING; user never told | medium | `_upload_snapshot` reports the same case through `_report_ftps_failure`; `_upload_series` only logs | patch |
| 6 | Outer timeout notification gives no "N sur M" count | low | Only reached when the inner deadline fails to fire; count would need plumbing out of the thread | reject |
| 7 | Expiry timers not cancelled in `on_stop` | false | `_expire_burst` only pops the dict and cancels; it uploads nothing, and handles die with the loop | reject |
| 8 | daemon-design.md presents `latest.jpg` as working, without the not-checked caveat | low | `ftps-test-server.md` carries the caveat, the design section does not; direct text edit | patch |

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failure versus the baseline
- `python3 -m pylint resources/siadc09d/` -- expected: no new message
- `php -l core/class/siaDC09Cmd.class.php` -- expected: no syntax error

**Manual checks (if no CLI):**
- On test-jeedom, cancel an alarm during its delay: nothing on the FTPS server.
