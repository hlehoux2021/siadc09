---
title: '18.7 - FTPS connection test action'
type: 'feature'
ticket: '7'
created: '2026-11-10'
status: done
baseline_revision: '256f2f9cce6c8f6f8eefb2355007f0a6af9d6250'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/EXPERIENCE.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The step 2 test button calls `testFtps`, which is a stub answering `unavailable` (18.12), so under FTPS no test can ever pass and the user cannot tell an unreachable host from a bad certificate or a bad login (E18-R5).

**Approach:** `testFtps` reads the saved configuration server-side and runs a read-only probe in a short-lived Python subprocess, as `testConnection` does: connect, TLS, certificate check, then login, nothing written and no folder change. Certificate problems stop before the password is sent and carry the fingerprint the server presents.

## Boundaries & Constraints

**Always:** The answer keeps the 18.12 contract `{status: ok|untrusted|changed|error, step?, detail, fingerprint?}`. `step` is one of « connexion », « sécurité TLS », « identifiants », « délai dépassé ». The password reaches the subprocess by `SIA_FTPS_PASSWORD` only (never an argument, never logged, never in the answer); the probe reuses `FtpsSettings`, `_build_context`, `_check_fingerprint` and the password masking of `ftps_upload.py`. Without a pinned fingerprint the chain and host name are verified. A failed verification triggers a second handshake with no verification, only to read the certificate's SHA-256, and no login on it. The probe applies one overall deadline of 15 s.

**Never:** Writing, listing or changing folder on the server (the folder is checked at the first alarm, as the success text says). Changing `daemon.py`, the upload path, the wizard JS or markup (18.12 already renders every status). File naming (18.8).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Correct setup, CA | Valid chain, good login | `ok` | None |
| Correct setup, pinned | Fingerprint matches, good login | `ok` | None |
| Host unreachable | Refused, unknown host | `error`, step « connexion » | Message names host:port |
| Timeout | No answer in time | `error`, step « délai dépassé » | None |
| Self-signed, no fingerprint | Chain verification fails | `untrusted` + presented fingerprint, no login | Password not sent |
| Fingerprint differs | Pinned value is not the server's | `changed` + presented fingerprint, no login | Password not sent |
| Bad login | Server answers 530 | `error`, step « identifiants » | Password masked in detail |
| TLS refused | Server has no TLS or too old | `error`, step « sécurité TLS » | None |
| Incomplete settings | No host or user saved | `error`, step « connexion » | Nothing contacted |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/ftps_upload.py:104-130,237-287` -- reuse `_build_context`, `_check_fingerprint`, `_arm`/`_remaining`, the connect/auth/login sequence and the `_FTP_ERRORS` masking; add `probe_connection(settings, deadline) -> dict` beside `_upload_stream` (no STOR)
- `resources/siadc09d/siadc09d.py:442-479` -- `--test-only` entry is the pattern; add a `--test-ftps` branch before it: `--config` JSON of the saved keys, password from `SIA_FTPS_PASSWORD`, one JSON line on stdout, traceback on stderr
- `core/ajax/siaDC09.ajax.php:54-63` -- replace the stub; copy the `testConnection` plumbing (python3, script path, env prefix, stderr file, `log::add`) with `ftps_*` keys instead of the encryption key
- `core/class/siaDC09.class.php:373-387` -- how settings are passed to the daemon (reference only; `ftps_cert_fingerprint` empty means CA verification)
- `internal-docs/design/wizard-design.md:258-270` -- `testFtps` contract: drop the stub paragraph
- Tests: `tests/level1/test_ftps_upload.py` (fake `FTP_TLS` pattern), `tests/level1/test_php_ftps_keys.py`, `test_i18n_roundtrip.py`; `scripts/ftps_probe.py` for the field check

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/ftps_upload.py` -- `probe_connection()` with the status and step mapping -- matrix
- [ ] `resources/siadc09d/siadc09d.py` -- `--test-ftps` entry, JSON out, password by environment -- subprocess boundary
- [ ] `core/ajax/siaDC09.ajax.php` -- real `testFtps`; log the verdict, never the password -- E18-R5
- [ ] `core/i18n/fr_FR.json` -- new PHP strings -- round trip
- [ ] `tests/level1/` -- one test per matrix row on a fake `FTP_TLS`; password absent from stdout, stderr and detail; PHP structure test -- proves the matrix
- [ ] `internal-docs/design/wizard-design.md` -- contract without the stub -- spec stays current

**Acceptance Criteria:**
- Given the test server on test-jeedom, when step 2 runs with a wrong host, a self-signed certificate without fingerprint, or a wrong password, then each shows its own message and no password reaches the server in the first two.
- Given a correct setup with the trusted fingerprint, when the test runs, then the FTPS zone reports success and Suivant shows.

## Implementation Notes

- The worktree branch predated the plan and 18.12; it was fast-forwarded to master (113a29b) before starting.
- `ftps_upload.probe_connection(settings, deadline)` (appended after `_upload_stream`, naming helpers untouched): connect, AUTH TLS, pinned fingerprint compare or CA verification, login. An `ssl.SSLCertVerificationError` in CA mode triggers `_read_presented_fingerprint()` (unverified second `FTP_TLS`, hello only) and answers `untrusted`; a pinned mismatch answers `changed`. Both never reach `login`. Step mapping by the step being run when the exception hits; timeouts and the deadline override to « délai dépassé ». `detail` is French user text built in Python; server messages are password-masked.
- `siadc09d.py --test-ftps --config <json>`: `run_ftps_probe()`, password from `SIA_FTPS_PASSWORD`, one JSON line; invalid saved port/fingerprint gives an `error` answer. 15 s deadline (`PROBE_DEADLINE_S`).
- `testFtps` (PHP): config JSON holds only host, port, user, fingerprint; password set with `putenv` around `exec` and cleared; only the contract keys are returned; verdict logged without any secret. Incomplete settings answer before any subprocess.
- Tests: `tests/level1/test_ftps_probe.py` (one per matrix row plus CLI subprocess against a closed local port); the 18.12 stub PHP structure test was replaced.
- Verification: new/affected tests pass. Full run: 107 failures, none from this change: 101 are the JS DOM harness (node module missing in this worktree), 1 is `test_plugin_css_is_included_and_has_the_mockup_rules` (hard-coded `#e9ecef` from 18.12 CSS, untouched here), 5 are the known level2. Pylint: no new warning in the new code. Field check on test-jeedom not run.

## Plan Change Log

## Review Triage Log

Pass 1 (quick): 0 high, 3 medium, 5 low, 1 false/none. Patches applied; the field check stays open.

| Verdict | Route | Finding and evidence |
|---|---|---|
| medium | patch | Port "0" or "70000" raised `OverflowError` in `connect()`, escaping to the generic "Erreur interne" with no step. `run_ftps_probe` now validates 1-65535 and answers an `error`, step "connexion"; test added. |
| medium | patch | A reset or EOF during login was reported as "Identifiant ou mot de passe refusé". Only an `ftplib.Error` (server reply) now maps to "identifiants"; test added. |
| medium | patch | stderr (traceback) was logged unmasked while the plan says the password is never logged. `siaDC09.ajax.php` masks it before `log::add`. |
| low | patch | The probe re-implemented the fingerprint hash and the password mask. Both come from `_peer_fingerprint()` and `_mask()` now, shared with `_check_fingerprint` and `_upload_stream`. |
| low | patch | Plain `dict[str, str]` for the answer: `_ProbeResult` is now a `TypedDict` with a `Literal` status. |
| low | patch | Missing assert comments in `test_ftps_probe.py`; added. |
| low | rejected | "connexion" detail says "connexion refusée" for DNS failures too. The exception type and message follow in parentheses; a per-cause wording needs new texts. |
| low | rejected | The two CLI tests spawn a subprocess in level 1. Closed local port, no external dependency, same pattern as the other probe tests. |
| false | rejected | Plan says "reuses `_check_fingerprint`" while the probe compares inline: it cannot raise there, since `changed` needs the fingerprint; fixed by sharing `_peer_fingerprint()` instead (see above). |
| n/a | open | Acceptance criteria need the field check on test-jeedom (wrong host, self-signed, wrong password, trusted setup). That is the human's step, noted in the plan. |

## Design Notes

A second, unverified handshake is the only way to learn the fingerprint of a certificate the first handshake rejected. It is safe because nothing but the TLS hello is sent on it. `unavailable` stays in the contract for the JS but the action no longer returns it.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the baseline (5 level2)
- `python3 -m pylint resources/siadc09d/` -- expected: no new warnings
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom against vsftpd: wrong host, self-signed without fingerprint, wrong password, then a trusted setup.
