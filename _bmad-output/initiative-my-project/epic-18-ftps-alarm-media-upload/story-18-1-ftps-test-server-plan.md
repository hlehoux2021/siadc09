---
title: 'FTPS test server on Synology'
type: 'chore'
ticket: '1'
created: '2026-11-09'
status: done
baseline_revision: 'bca9d302c08c51d252906d3c2a5cedf21b6cfb1f'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 18 uploads alarm media to an FTPS server, but none exists to develop and validate against (E18-R1). Nothing in the repo describes one or can check one.

**Approach:** The user enables the FTPS service on their Synology (a human step). The repo gets a short setup note recording the settled mode and certificate choice, and a stdlib probe script that connects, uploads a file, lists it, deletes it, and reports each step. 18.2 reuses the probe's connection logic as its test fixture seed.

## Decisions (user, 2026-11-09)

- TLS mode: explicit (FTPES) on port 21, as DSM offers.
- Certificate: DSM's self-signed certificate first; the CA-signed case is tested later (18.9).
- Server: Synology at 192.168.100.9 (`starfire-internal.lehoux.net`), shared folder `ftp-server`; a dedicated test account, no password in the repo.

</frozen-after-approval>

## Code Map

- No daemon or plugin code is touched. Nothing in the repo mentions FTPS yet.
- `scripts/` -- holds standalone probes (`sia_csr_probe.py`, `frigate_latency_probe.py`); the new probe sits beside them.
- `internal-docs/` -- the setup note goes here; the epic names `daemon-design.md` for later updates, not for this entry.
- `tests/requirements-dev.txt` -- unchanged; the probe uses `ftplib` only.

## Tasks & Acceptance

**Execution:**
- [ ] `scripts/ftps_probe.py` -- connect with `ftplib.FTP_TLS` (explicit), login, `PROT P`, upload a small file, list, download-compare, delete; print one PASS/FAIL line per step and the certificate SHA-256 fingerprint; take host, port, user, folder as arguments and the password from an environment variable; offer `--insecure` and `--fingerprint` for the self-signed case -- gives the repo a way to check any FTPS server, the user's now and the fixture later
- [ ] `internal-docs/ftps-test-server.md` -- Synology steps (enable FTP SSL/TLS, account, folder permissions, port forwarding not needed on LAN), settled mode and certificate choice, how to run the probe -- so the setup survives the session
- [ ] Human (hitl) -- enable the service, create the account, run the probe from the machine hosting test-jeedom

**Acceptance Criteria:**
- Given the Synology FTPS service is enabled, when `scripts/ftps_probe.py` runs from test-jeedom's network with the account, then every step prints PASS and the file is gone from the server afterwards.
- Given a wrong password or an unreachable host, when the probe runs, then it exits non-zero with a FAIL line naming the step and never prints the password.
- Given a self-signed certificate, when the probe runs without `--insecure` or `--fingerprint`, then it fails on certificate verification; with the right `--fingerprint` it passes.

## Implementation Notes

Oneshot: a small script and a note; no existing code involved.

## Plan Change Log

- 2026-11-09, user: the Synology is unreachable from the test VLAN (.40.x) and the firewall stays; the test server becomes vsftpd on test-jeedom (account `siaftps`, folder `upload`). Decisions on explicit TLS on port 21 and a self-signed certificate first are unchanged. `internal-docs/ftps-test-server.md` is rewritten for vsftpd; the probe script is unchanged.

## Review Triage Log

- medium, patched: cleanup in `finally` could replace the real failing step with `delete` -- `_delete` now never raises; the delete error is raised only when nothing else failed.
- medium, patched: `EOFError` escaped as a traceback -- all steps catch `ftplib.all_errors`.
- low, patched: malformed `--fingerprint` only failed after connecting -- validated by argparse.
- low, patched: doc listed a `fingerprint` PASS step for all modes -- doc corrected.
- low, patched: duplicated basename literal, hex-digit literal named.
- low, rejected: one-second remote-name resolution (sequential use only); missing Args/Returns docstring sections (one-line summaries suffice for a script); import order (isort-compatible); no re-list after delete (the server's 250 answer is the evidence).

## Verification

**Commands:**
- `python3 -m pylint scripts/ftps_probe.py` -- expected: no errors
- `python3 scripts/ftps_probe.py --help` -- expected: usage printed, exit 0

**Manual checks (if no CLI):**
- Probe against the Synology: all steps PASS, remote folder left empty. Done by the user.
