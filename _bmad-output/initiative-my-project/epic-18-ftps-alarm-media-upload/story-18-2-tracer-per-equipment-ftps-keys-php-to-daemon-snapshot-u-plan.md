---
title: 'Tracer: per-equipment FTPS keys, PHP to daemon, snapshot upload on BA alarm'
type: 'feature'
ticket: '18.2'
created: '2026-11-09'
status: 'built'
baseline_revision: '35119e6'
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

**Problem:** The daemon only puts a media URL in the BA frame; nothing pushes the snapshot to a server the receiver can read (E18-R1, R2, R7).

**Approach:** Add per-equipment keys (enable, transport, host, port, user, password, folder, optional certificate fingerprint), pass them to the daemon at start like `encryption_key`, and on a BA alarm have PHP pass the Frigate host and event id it already holds; the daemon downloads the snapshot straight from the Frigate API (`/api/events/{id}/snapshot.jpg`, as the prefetch already talks to it) and uploads it by explicit FTPS in a tracked background task. The `media_url` template is not fetched (it holds placeholder credentials the CSR substitutes) and the Frigate plugin's stored files are not read. No wizard yet; keys are set by hand.

## Boundaries & Constraints

**Always:** The frame is built and sent exactly as today and never waits for the upload. The password is a `type="password"` field, never logged, never in IPC status, the debug UI or the frame. The server certificate is verified by default; the optional SHA-256 fingerprint is the self-signed path. Upload uses stdlib `ftplib.FTP_TLS` (explicit TLS) with a fixed timeout constant.

**Never:** Clip upload (18.5), wizard fields (18.4), timeout/certificate/secret hardening beyond the above (18.6), test button (18.7), final naming/layout (18.8). No FTPS keys in CSR profiles (ADR-22). No upload for non-BA events. No SFTP.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| BA, transport ftps | burglarAlarm payload with Frigate host and event id | Frame sent with no U/V tag; snapshot uploaded to `ftps_folder` | No error expected |
| BA, transport url | Same, `media_transport` url (default) | Behavior unchanged, no upload | None |
| Non-BA (fire, panic, restore) | ftps chosen | No upload | None |
| Server down or slow | ftps chosen, connect refused or timeout | Frame ACKed in its usual time | Upload failure logged with host and reason, no password |
| Snapshot fetch fails | Frigate API unreachable or event has no snapshot | No upload | Logged; frame unaffected |
| Upload disabled or keys incomplete | `ftps_enabled` off or host/user empty | No upload | One warning at start if enabled but incomplete |

</frozen-after-approval>

## Code Map

- `core/class/siaDC09.class.php:48-61` -- media key constants/defaults; add `media_transport` (url|ftps, default url) and `ftps_*` keys here
- `core/class/siaDC09.class.php:308-378` -- `deamon_start()`: add `--ftps-*` args beside `--encryption-key` (:344-347); extend the redaction regex at :376 to the new password arg
- `core/class/siaDC09Cmd.class.php:110-153,205-219` -- `execute()` builds the `media` list for BA/fire/panic; with transport ftps, send `ftps_upload = {frigate_host, event_id}` (from `_resolvePrefetchTarget` :370 and the prefetch cache entry via `_readPrefetchCacheEntry` :422) and omit `media` (frame carries no tag)
- `desktop/php/siaDC09.php:190` -- `encryption_key` password input to copy for `ftps_password` (hand entry only; no wizard)
- `resources/siadc09d/siadc09d.py:487-549` -- argparse; add `--ftps-*` options next to `--encryption-key` (:500)
- `resources/siadc09d/daemon.py:495-499` -- `SIADaemon.__init__` stores the key; store an `FtpsSettings` dataclass the same way
- `resources/siadc09d/daemon.py:2831-2846` -- `on_message` media parsing and `_enqueue_event` (:2449); parse `ftps_upload` and, only when `sia_code == "BA"`, call `_track_task` (:754-775)
- `resources/siadc09d/frigate_prefetch.py:92-106` -- `_get_json` urllib pattern (unauthenticated port 5000); add a binary GET for `/api/events/{id}/snapshot.jpg` beside it, same timeout constant and `_run_with_deadline_timeout` (:302)
- New `resources/siadc09d/ftps_upload.py` -- `FtpsSettings`, `upload_bytes(settings, name, data)` (blocking, run via `asyncio.to_thread` under `asyncio.wait_for`)
- Do not change: frame building at `daemon.py:2141-2154`, `frigate_prefetch.py` logic, the `_EVENT_SIA_CODES` table
- Tests to imitate: `tests/level2/test_async_task_lifecycle.py`, `tests/level1/test_php_encryption_key_guard.py`, `tests/level1/test_frigate_prefetch.py`; `scripts/ftps_probe.py` shows the FTPS connect/fingerprint code to reuse

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/ftps_upload.py` -- `FtpsSettings` and `upload_bytes` (explicit TLS, fingerprint or CA verification, timeout, no password in exceptions) -- the one place that talks FTPS
- [ ] `resources/siadc09d/siadc09d.py`, `daemon.py` -- parse `--ftps-*`, store settings, handle `ftps_upload` for BA via a tracked task that fetches then uploads -- E18-R2, R7, frame independence
- [ ] `core/class/siaDC09.class.php`, `siaDC09Cmd.class.php`, `desktop/php/siaDC09.php` -- keys, `deamon_start` args and redaction, `ftps_upload` payload, hand-entry password field -- E18-R1
- [ ] `tests/level1/`, `tests/level2/` -- tests for the I/O matrix against a mocked `ftplib` (no new dependency): BA uploads, others do not, failure does not delay the frame, password absent from logs and `deamon_start` log line, PHP arg and redaction guard -- proves the matrix
- [ ] `internal-docs/design/daemon-design.md` -- short section on the upload path -- epic names it for update

**Acceptance Criteria:**
- Given ftps chosen and a BA alarm, when the SIA frame is built, then it carries no U/V tag and is sent within its usual time whatever the upload does.
- Given the keys set by hand on test-jeedom and the 18.1 server (vsftpd on test-jeedom, `upload/` folder), when a BA alarm fires, then the snapshot is in the remote folder (field check, after 18.1 passes).
- Given any log, status or debug output, when an upload runs, then the password never appears.

## Implementation Notes

Implemented by a subagent from this plan. Self-review before the quick lens found one defect, patched: the upload ignored the media master and snapshot switches (E18-R2); it now resolves `ftps_upload` only when both are on.

## Plan Change Log

## Review Triage Log

- medium, patched: `_get_bytes` let `ConnectionResetError`/`IncompleteRead` escape, ending the tracked task with an unhandled exception -- now catches `OSError` and `HTTPException`; two tests added.
- low, patched: unused `MEDIA_TRANSPORTS`, `MEDIA_TRANSPORT_KEY`, `MEDIA_TRANSPORT_DEFAULT` on `siaDC09` removed (the Cmd keeps its own copies because the PHP test harnesses stub `siaDC09`).
- low, patched: new level-1 PHP tests lacked the mandatory docstring and assert comments -- added.
- low, patched: design doc did not say a BA frame loses its U/V tag when ftps is chosen but the upload cannot run -- bullet added.
- low, rejected: that tag loss is the epic's decision (transports exclusive); each case is logged and the frame is never held back.
- low, rejected: Google-style Args/Returns on small private helpers; `fr_FR.json` key order (Jeedom reads it as a map, `Port` already exists).
- medium, deferred to 18.6: the upload thread outlives `FTPS_UPLOAD_DEADLINE_S` because `wait_for` cannot cancel a blocking thread; each socket step is bounded by `FTPS_TIMEOUT_S`.

## Design Notes

Media source (study 2026-11-09): the `media_url` template carries placeholder credentials the CSR substitutes, so it cannot be fetched; the Frigate plugin's stored files arrive late (MQTT, 0-10 s pause, clip only at end), never exist for the prefetch's manual events, and use a private layout. The Frigate API is already the prefetch's channel and has the event id in the cache. 18.5 reuses it for the clip (`has_clip` check, streamed read).

The tracer adds `media_transport` and the optional `ftps_cert_fingerprint` now, ahead of their wizard and hardening stories: without them the frame would still carry a tag and the self-signed test server could not be reached. The fixed remote name is `<account>-<event id>-snapshot.jpg` until 18.8.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the recorded baseline
- `python3 -m pylint resources/siadc09d/` -- expected: no new messages
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom with keys set by hand and 18.1 passing: BA alarm leaves the snapshot on the Synology and the CSR still ACKs the frame.
