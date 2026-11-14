---
title: '18.15 — Photo burst by FTP and FTPS'
type: 'feature'
ticket: '15'
created: '2026-11-13'
status: 'built'
baseline_revision: '3d427e62fc65a46a872b14e160ca9c2c09789a91'
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

**Problem:** The series built first (5 then 30 `latest.jpg` frames grabbed at the prefetch) photographs the camera after the event and needs memory state, a 120 s timer and a `burst` flag. The receiver wants the frames of the event itself, from its start.

**Approach:** At the BA alarm the daemon reads the Frigate event (camera, `start_time`), cuts 30 frames from its recordings (3 per second, 10 s, from `start_time`) and uploads them over one connection, all named with the event `start_time` epoch and image 0001.... No frame: the single event snapshot is sent alone, as before the series.

## Boundaries & Constraints

**Always:** FTP/FTPS only, only when the photo is wanted; nothing captured at the prefetch and nothing held between prefetch and alarm; frame `GET /api/<camera>/recordings/<ts>/snapshot.jpg`, `ts` = `start_time` + n/3 s, n = 0..29; a failed frame is retried once at `ts` + 0.2 s then skipped, image numbers consecutive over the frames obtained; the series stops after 3 consecutive frames that failed twice; the clip keeps the alarm-handling epoch (18.13); the SIA frame never waits; one notification for a partial failure ("N photos sur M"); password never logged; no event snapshot sent with a series; one WARNING when the series falls back to the snapshot.

**Never:** a `latest.jpg` capture, in parallel or as a fallback; equipment setting or wizard field for count or rate; changing the SIA URL transport and its `[V...]` tag; writing photos to disk; one connection per photo; changing the clip, or `prefetch_alarm_media`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Full series | event with recordings, BA alarm | 30 files `<acct>_<zone>_<start_time>_0001..0030.jpg`, one login | none |
| One frame refused | one frame 404 twice | skipped; 29 files, numbers 0001..0029 | one DEBUG line per refusal |
| Frame refused once | 404 then 200 at +0.2 s | frame kept in its place | none |
| Recording ends early | 3 frames in a row fail twice | series stops with the frames held | none |
| No frame at all | no recording, Frigate down | single event snapshot sent alone (18.13 name, alarm epoch) | one WARNING |
| Partial upload failure | connection drops after 3 | one notification "3 photos sur 30" | ERROR log, no retry |
| No Frigate event | no `event_id` | nothing sent (as before 18.15) | one WARNING (PHP) |
| Cancelled in delay | no BA alarm | nothing fetched, nothing uploaded | none |
| Clip wanted too | series + clip | clip named with the alarm epoch, series with `start_time` | independent |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/frigate_prefetch.py` -- remove `fetch_latest_jpeg`, `BurstPhoto`, `capture_burst`, `BURST_*`, `_LATEST_QUERY`; add `fetch_event_info(host, event_id)` (camera + `start_time` from `GET /api/events/<id>`), `fetch_recording_frame(host, camera, ts)` and `fetch_event_frames(host, event_id)` with retry and the 3-failure stop; reuse `_get_json`, `_get_bytes`, `_run_with_deadline_timeout`.
- `resources/siadc09d/daemon.py` -- `_run_ftps_upload`, `_upload_series` (takes frames + `start_time`), `_upload_snapshot` (unchanged, is the fallback); remove `_BurstSeries`, `_burst_series`, `_start_burst`, `_drop_burst`, `_expire_burst`, `_take_burst`, `BURST_TTL_S`, the `burst` branch of the prefetchEvent handler, `FtpsAlarmMedia.run_id` and the `run_id` read of `ftps_upload`; `has_source` back to host + event id. Keep `FTPS_SERIES_PER_FILE_S`.
- `resources/siadc09d/ftps_upload.py` -- `remote_location(..., image=)` and `upload_many` stay as they are.
- `core/class/siaDC09Cmd.class.php` -- drop `burst` from the prefetchEvent payload and `run_id` from `ftps_upload`; `_resolveFtpsUpload` returns null with its warning when there is no event id.
- `tests/level2/test_ftps_photo_burst_dispatch.py`, `tests/level1/test_ftps_photo_burst.py` -- rewrite for the matrix (frames faked at `_get_bytes`/`_get_json`).
- Docs: `docs/fr_FR/media-ftps.md`, `docs/fr_FR/changelog.md`, `internal-docs/ftps-test-server.md`, `internal-docs/design/daemon-design.md`; `core/i18n` and `desktop/js` label stay "Rafale de photos".
- Probe: `scripts/frigate_recordings_snapshot_probe.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/frigate_prefetch.py` -- event info, frame fetch with retry, series fetch; remove the `latest.jpg` capture -- new photo source
- [ ] `resources/siadc09d/daemon.py` -- series at the alarm with `start_time` epoch, snapshot fallback with one WARNING; remove burst state and `run_id` -- no prefetch-time state
- [ ] `core/class/siaDC09Cmd.class.php` -- remove `burst` and `run_id`; null without event -- payloads match the daemon
- [ ] `tests/level1`, `tests/level2` -- every matrix row
- [ ] docs listed in the Code Map -- 30 photos, event recordings, `start_time` epoch, no 120 s memory

**Acceptance Criteria:**
- Given an event with recordings and FTPS with photo on, when the BA alarm fires, then 30 files ...0001.jpg to ...0030.jpg reach the server over one connection, all with the event `start_time` epoch.
- Given an event with no recording, when the BA alarm fires, then one photo (the event snapshot) is sent and one WARNING is logged.
- Given the prefetch, when it runs, then no frame is requested from Frigate and no timer is armed.

## Implementation Notes

House rules (read before coding): `.claude/rules/python-style.md`, `.claude/rules/testing.md`, the php-style rule, and `CLAUDE.md`. Bash: no `cd`, no heredocs, no redirections, no `python3 -c`; temp files in `$TMPDIR`; macOS `sed -i ''`; use Read/Grep tools to read files. Do not commit, do not push. Read the ticket `story-18-15-photo-burst-by-ftp-and-ftps.md` (Notes, Evidence) for verified Frigate API facts.

## Plan Change Log

- 2026-11-14 (user renegotiated the intent): source changed from `latest.jpg` captured at the prefetch to the event recordings fetched at the alarm; epoch changed to the event `start_time`; fallback changed to the single event snapshot; memory, timer and `burst` flag removed. KEEP: `upload_many` (one login), `remote_location(image=)`, the partial-failure notification, `FTPS_SERIES_PER_FILE_S = 2`, the 30-photo count, the "Rafale de photos" label, the docs structure.

## Review Triage Log

Second build (2026-11-15, recordings version), quick lens:

| # | Finding (quick) | Verdict | Route |
|---|---|---|---|
| 1 | +0.2 s retry not checked on a real Frigate (probe not run) | maybe-false, medium if the retry does nothing: harmless extra request per refused frame; settle by running the probe on test-frigate | defer |
| 2 | Two DEBUG lines for a frame refused twice | false: two refusals, two lines | reject |
| 3 | No overall time bound on the frame fetch | low: Frigate down stops at once (event row), a hung Frigate stops after 3 failures; fix adds a deadline | reject |
| 4 | i18n keys moved to the `siaDC09.js` section | false: the label is used by that file and the i18n tests require it | reject |
| 5 | Docs do not say recordings are needed | low | patch (done, one sentence in media-ftps.md) |

First build (2026-11-13/14, `latest.jpg` version), kept as the record:

| # | Finding (quick) | Verdict | Route |
|---|---|---|---|
| 1 | `latest.jpg` never called on a real Frigate | settled by curl on test-frigate | defer, then settled |
| 2 | AC2 test calls `_expire_burst` by hand | false | reject |
| 3 | Two WARNINGs for one missing event | low | patch |
| 4 | PHP warning claims a series may be sent when only the clip is wanted | low | patch |
| 5 | With a series, a missing event snapshot only a WARNING | medium | patch |
| 6 | Outer timeout notification gives no count | low | reject |
| 7 | Expiry timers not cancelled in `on_stop` | false | reject |
| 8 | daemon-design.md lacked the not-checked caveat | low | patch |

## Design Notes

The recordings fetch needs the camera name and the start time; both come from one `GET /api/events/<id>` at the alarm, so the `ftps_upload` payload keeps `frigate_host` and `event_id` only. Evidence on test-frigate (2026-11-14): 29 of 30 frames in 3.8 s from `start_time`, about 47 KB each; one 404 "Unable to parse frame" per series, seen 0.05 to 0.1 s before a segment end (cause not verified). The retry at +0.2 s is kept only if the build shows it recovers the frame (probe script).

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failure versus the baseline
- `python3 -m pylint resources/siadc09d/` -- expected: no new message
- `php -l core/class/siaDC09Cmd.class.php` -- expected: no syntax error
- `python3 -I scripts/frigate_recordings_snapshot_probe.py 192.168.40.18:5000 - 0 <event id>` -- expected: about 30 frames in under 5 s on an event with recordings

**Manual checks (if no CLI):**
- On test-jeedom, cancel an alarm during its delay: nothing on the FTPS server and no request to Frigate recordings.
