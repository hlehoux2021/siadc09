---
title: '18.6 - Upload robustness: timeout, certificate, secret handling'
type: 'feature'
ticket: '6'
created: '2026-11-09'
status: done
baseline_revision: 'd74c378375b458ed5b21defb24b337b1f6746467'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/.claude/rules/python-style.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Since 18.2/18.5 the upload is best-effort, but its deadline is only a wait: a stalled or trickling server keeps a worker thread (and a clip file) alive past it, a burst of alarms has no cap, the TLS minimum is implicit, and the FTPS password is readable in `ps` (daemon command line) and in the test-connection call (E18-R3, E18-R4).

**Approach:** One real deadline enforced inside the blocking upload (per-block check plus a shrinking socket timeout); an explicit TLS 1.2 minimum; the FTPS password passed to the daemon by environment variable, never on a command line, and kept out of the test-connection call; the `apikey` also redacted from the launch log line.

## Boundaries & Constraints

**Always:** The SIA frame and the snapshot never wait for a clip or for another upload. Pinned mode still compares the fingerprint before the login. A deadline hit is an ERROR reported to the user like any upload failure. The password appears in no argument list, log, callback, exception or PHP payload.

**Never:** Making the timeouts user-configurable. Moving `encryption_key` or `apikey` off the command line (follow-up, recorded in `deferred-work.md`). A watchdog thread closing sockets. Any wizard change (18.11) or file naming (18.8).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stalled server | Accepts the data connection, never reads | Upload aborted at the deadline, the thread ends, the frame was ACKed on time | ERROR + notification naming the deadline |
| Trickling clip | Server accepts bytes slowly, total above the deadline | Aborted between two blocks | Same |
| Wrong certificate (CA mode) | Chain or host name invalid | Refused at the TLS step, nothing sent | Step "tls" named |
| Old TLS | Server offers below TLS 1.2 | Refused | Step "tls" named |
| Daemon start | Equipment with a password | Password absent from the argument list; reaches the daemon through `SIA_FTPS_PASSWORD` | None |
| Test connection | Equipment with an FTPS password | `ftps_password` absent from `--config` and from the logged command | None |
| Launch log line | Any equipment | `--apikey`, `--encryption-key`, `--ftps-*` secrets redacted | None |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/ftps_upload.py:~115-210` -- `upload_bytes`/`upload_file`/`_upload_stream`, `_build_context` (:104): add a `deadline` argument, a source wrapper whose `read()` raises `FtpsUploadError` once `time.monotonic()` passes it (block size 64 KiB via `storbinary(..., blocksize=)`), `ftp.sock.settimeout(min(FTPS_TIMEOUT_S, remaining))` before each control step, `context.minimum_version = TLSv1_2`
- `resources/siadc09d/daemon.py:~285,590-700` -- `FTPS_UPLOAD_DEADLINE_S`, `_run_ftps_upload`, `_upload_clip`: pass the deadline into the blocking call, keep `wait_for` as the outer bound; read the password from the environment
- `resources/siadc09d/siadc09d.py:~506` -- replace `--ftps-password` by `os.environ.get("SIA_FTPS_PASSWORD", "")`
- `core/class/siaDC09.class.php:362,377,413-418,419` -- `deamon_start`: prefix the command with `SIA_FTPS_PASSWORD=<escapeshellarg>` instead of the argument, extend the log redaction to `--apikey` and the env prefix
- `core/ajax/siaDC09.ajax.php:62-88` -- `testConnection`: unset `ftps_password` from the config JSON as `encryption_key` is, and do not log it
- Do not change: SIA send path, the snapshot/clip fetch limits, `encryption_key` and `apikey` transport
- Tests to imitate: `tests/level1/test_ftps_upload.py`, `tests/level2/test_ftps_upload_dispatch.py`, `tests/level1/test_php_ftps_keys.py`

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/ftps_upload.py` -- deadline inside the blocking call, TLS 1.2 minimum -- one hard bound
- [ ] `resources/siadc09d/daemon.py`, `siadc09d.py` -- deadline plumbing, password from the environment -- E18-R3, R4
- [ ] `core/class/siaDC09.class.php`, `core/ajax/siaDC09.ajax.php` -- env var launch, redaction, test-connection config -- no secret on a command line
- [ ] `tests/level1/`, `tests/level2/` -- one test per matrix row (mocked stalled/trickling server, bursts, TLS refusals, PHP source and `php` CLI redaction checks) -- proves the matrix
- [ ] `_bmad-output/initiative-my-project/deferred-work.md`, `internal-docs/design/daemon-design.md` -- record the AES-key/apikey follow-up and the new bounds -- design stays current

**Acceptance Criteria:**
- Given a stalled FTPS server, when a BA alarm fires, then the frame is ACKed on time, the upload thread is gone after the deadline, and the user is notified.
- Given the daemon running, when `ps` is read, then the FTPS password is nowhere in the arguments.
- Given the test-connection action, when it runs for an FTPS equipment, then the password is in neither its arguments nor its log line.

## Implementation Notes

Implemented by a subagent from this plan; the concurrency cap was dropped before approval (a burst of alarms is not a real case, user 2026-11-09). All execution tasks above are done.

## Plan Change Log

## Review Triage Log

- medium, patched: the data connection and the final server reply were not bounded -- `storbinary` replaced by an explicit `_store()` that re-arms the socket timeout before each block and before `voidresp()`; the outer `wait_for` is now deadline + `FTPS_TIMEOUT_S` + grace, so the inner abort reports first.
- medium, patched: the stall tests passed with the deadline code removed -- tests now run the real functions against a fake `FTP_TLS` built on real `socket.socketpair()` sockets (stalled data connection, missing 226) and assert the thread ends and the step is named.
- low, patched: the FTPS password stayed in the daemon environment -- read with `os.environ.pop`; `putenv`/exec wrapped in try/finally in `deamon_start`.
- low, rejected: a server dripping one byte every 9 s during the banner or TLS handshake, and DNS resolution without a timeout (not a realistic case here; noted in the design doc); the clip file unlinked while the thread still runs (POSIX keeps the open file, the thread now ends within the bound); the AES key still on the test-connection command line (existing, recorded in `deferred-work.md`); partial password scrubbing on module-own messages; source-text and attribute-only tests; an unset password variable giving an empty password (fails at login with the server's reply).
- Open for the user: the manual check on test-jeedom -- `ps aux | grep siadc09d` shows no `--ftps-password`, and a frozen vsftpd (`kill -STOP`) leaves the frame ACKed with an ERROR and a notification.

## Design Notes

A per-block check bounds a trickling transfer to one block's socket timeout (10 s) past the deadline; a single hung `send` is bounded by the shrinking socket timeout. A hard watchdog was rejected: a race on two sockets for a gain of a few seconds. No cap on concurrent uploads: a burst of alarms is not a real case here (user, 2026-11-09), each upload is bounded by its own deadline.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the baseline (5 level2)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom: `ps aux | grep siadc09d` shows no `--ftps-password`; with vsftpd stopped or frozen (`kill -STOP`), a BA alarm's frame is ACKed and an ERROR + notification appears.
