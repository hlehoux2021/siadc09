---
title: '18.14 - Optional plain FTP, without TLS'
type: 'feature'
ticket: '14'
created: '2026-11-13'
status: 'built'
baseline_revision: '1a89bb79b032c22d92056b78d0de7e95ca7a3190'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/.claude/rules/python-style.md'
  - '{project-root}/.claude/rules/php-style.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A server with no FTPS (it answers `530 Please login with USER and PASS` to AUTH TLS) fails at the step « sécurité TLS ». The user cannot enable FTPS on it.

**Approach:** A per-equipment setting « FTP sans TLS », off by default, always shown in the step 2 advanced options with a text warning. When on, upload and connection test use plain FTP: no AUTH TLS, no certificate or fingerprint check, no data protection. FTPS stays the default.

## Boundaries & Constraints

**Always:** Default off means today's FTPS behaviour, unchanged. The password stays out of logs, arguments and answers. Every plain upload and every plain test logs that the link is not encrypted. The setting is never a profile field and never locked (ADR-22). Warning wording in `fr_FR.json`.

**Never:** Silent fallback from FTPS to plain after a TLS failure. A mockup. Changing the SIA frame, the file names (18.13) or the Frigate fetch. Pinning a fingerprint in plain mode.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default | `ftps_plain` unset | `FTP_TLS` path as today | None |
| Upload, plain on | Server without FTPS | Connect, login, cwd, STOR with no TLS step; log "sans TLS" | Failure names its step |
| Test, plain on | Same server | `ok`, detail says the link is not encrypted | Bad login gives the login failure |
| Plain on, server has FTPS | Any | Still plain FTP, no TLS attempted | None |
| Plain off, server without FTPS | Today's case | Fails at « sécurité TLS » | Unchanged message |
| Plain on, fingerprint saved | Old value | Fingerprint ignored and not sent | None |
| Wizard, box ticked | Step 2 | Certificate radios and fingerprint hidden; fingerprint not required; warning shown | None |
| Completeness | Plain on, host/user/password set | No FTPS error | Missing field still refused |

</frozen-after-approval>

## Code Map

- `core/class/siaDC09.class.php` l.563-585 -- start command; add `--ftps-plain` when `ftps_plain` is on, skip the fingerprint then
- `core/ajax/siaDC09.ajax.php` `testFtps` l.54-140 -- read `ftps_plain`, pass it in the `--config` JSON
- `resources/siadc09d/siadc09d.py` l.564-571 (CLI args), l.448-500 (`run_ftps_probe`, `--test-ftps`) -- add the flag and the `plain` config key
- `resources/siadc09d/ftps_upload.py` -- `FtpsSettings` (add `plain`), `_upload_stream` l.304 (use `ftplib.FTP`, skip tls/fingerprint/data-protection), `probe_connection` l.464 (connect + login only), `_probe_failure` texts; reuse `_mask`
- `resources/siadc09d/daemon.py` `_read_ftps_settings` l.597 -- read `ftps_plain`, warn once at start
- `desktop/php/siaDC09.php` l.304-344 -- add the checkbox and the warning in the FTPS card
- `desktop/js/siaDC09.js` l.444-515 (card, radios, `siaDC09_ftpsConfigErrors`), l.921 (`siaDC09_renderFtpsResult`), summaries l.743-771 -- hide certificate parts, skip the fingerprint check, show the plain result
- `core/i18n/fr_FR.json` -- new strings; `en_US.json` has no FTPS strings, leave it
- Tests to extend: `tests/level1/test_php_ftps_keys.py`, `test_ftps_upload.py`, `test_ftps_probe.py`, wizard JS DOM tests (`test_wizard_step1_js_dom.py` and fixtures)
- Docs: `internal-docs/ftps-test-server.md`, `internal-docs/design/wizard-design.md` (read ADR-22 and its step 2 section first), `daemon-design.md`
- Do not touch: `scripts/ftps_probe.py`, the clip and snapshot fetch

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/ftps_upload.py`, `siadc09d.py`, `daemon.py` -- `plain` setting, plain upload and plain probe, logs -- the server without FTPS works
- [ ] `core/class/siaDC09.class.php`, `core/ajax/siaDC09.ajax.php` -- hand the setting to the daemon and the test -- same path as the other keys
- [ ] `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js`, `core/i18n/fr_FR.json` -- checkbox, warning, validation, result text -- user-visible mode
- [ ] Tests for every matrix row, including the JS DOM tests -- proves the matrix
- [ ] The three docs -- mode, warning, off by default -- documented

**Acceptance Criteria:**
- Given a server with no FTPS and the setting on, when the user tests and an alarm fires, then both succeed and the logs say the link is not encrypted.
- Given the setting off, when the same server is tested, then it fails at « sécurité TLS » as today.
- Given the setting on, when the password is logged anywhere, then it never appears.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Quick lens, 8 findings.

| # | Finding | Verdict | Action |
|---|---------|---------|--------|
| F1 | Plain connect failure said "service FTPS" | patch | Wording follows the mode; asserted in the CLI test |
| F7 | CLI test for the plain flag was weak | patch | Now asserts the step and the "service FTP" wording |
| F2-F6, F8 | Not defects in the code as built (checked against the code and tests) | rejected | None |

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the 5 known baseline failures
- `python3 -m pylint resources/siadc09d/ftps_upload.py resources/siadc09d/daemon.py resources/siadc09d/siadc09d.py` -- expected: no new messages
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax error

**Manual checks (if no CLI):**
- On test-jeedom: tick the box in step 2 advanced options, the warning shows, the test succeeds against the user's server, and an alarm uploads. Untick: the TLS failure returns.
