# Story 17-6: DUH response handling

Status: review (implemented 2026-11-04, commit 19fb318 local, not pushed; field check on the real CSR pending)

Evolution, not a fix: DUH handling was not planned when epic 17 started. Build record: `_bmad-output/plan-duh-response-handling.md` (ticket `17-6-duh-response-handling`, status `built`, baseline `f053858`).

## Story

As a user whose CSR refuses the `sia-dcs` supervision frame,
I want the plugin to recognise a DUH answer and tell me what it means,
So that I am steered to the `null` format instead of being told the reply is unreadable.

Trigger: a real CSR (194.51.213.114:5390 TCP, account 4596) answered `\nA8080012"DUH"0001L0#4596[]\r` to `"SIA-DCS"0001L0#4596[#4596|0000]`. The decoder only knew ACK/NAK, so the reply became `unknown`, then `timeout`, then `bad_reply` ("check CRC and encryption", wrong), and the daemon counted a "NAK non décodable".

## Acceptance Criteria

1. Decoding the exact DUH frame gives type `DUH`, sequence 1. With an altered CRC it stays `unknown`. A DUH is never encrypted.
2. Wizard, CSR answering DUH: verdict `fail`; the detail says the CSR is reachable and refused the frame (DUH), suggests the `null` format and checking account and prefix; no mention of CRC. The `bad_reply` message no longer claims a CRC or encryption problem.
3. Wizard, failed test with encryption off: the clear sent frame (repr + hex) goes to stderr. A passing test writes nothing (PHP logs any stderr at error level, `core/ajax/siaDC09.ajax.php:96-104`). An encrypted frame and the key are never logged.
4. Supervision and RP: a DUH is never re-sent (§ 5.6.1.3, deterministic refusal). One strike, T2 `BAD_CSR_RESPONSE`, dedicated `duh` log line (never "NAK non décodable"). RP label "Refusé par la centrale".
5. Alarm event: a DUH is not retried. SM2 goes to FAILED with failure reason `nak` (existing "refusé" label), T2 sent.
6. Default `supervision_format`, profiles, PHP and JS unchanged. ACK/NAK behaviour unchanged.
7. Field check on the real CSR: `sia-dcs` fails with the DUH verdict, `null` is ACKed. **Not done.**

## Evidence

### Implementation (commit 19fb318, local)

| Area | Change |
|------|--------|
| `sia_protocol.py` | `DUH_RESPONSE`; `AckNakResponse.type` includes `DUH`; token `DUH` recognised, CRC still validated |
| `sia_transport.py` | status `duh` (with `raw_response`) |
| `siadc09d.py` | `duh` verdict (fail); neutral `bad_reply`; failure-only clear-frame log |
| `daemon.py` | `_handle_supervision_duh`; supervision and RP branch on `duh`; `_send_with_retry` `duh` branch (no retry, SM2 FAILED reason `nak`, transition `failed_duh`); log event `duh` |
| `messages.py` | `SM1_DUH`, `SM2_FAILED_DUH` |
| Docs | `daemon-design.md`, `supervision-design.md`, `docs/fr_FR/index.md` troubleshooting rows. `docs/en_US` not updated (partial language) |

### Tests (2026-11-04)

| Suite | Result |
|-------|--------|
| `tests/level1/` | 1465 passed |
| 11 matrix tests (decode, bad CRC, transport, verdict, encrypted frame never logged, ACK silent, supervision, RP, event) | passed |
| `tests/level2/` subset | 112 passed, 1 failed: `test_update_info_commands_full_payload_healthy`, known baseline failure |
| `pylint resources/siadc09d/` | about 6 more messages than master (long lines, too many branches in `_send_rp`): "no new pylint message" is not strictly met |

### Review (quick, 1 iteration)

Finding 1 (intent gap): the always-on DEBUG frame line became an error-level Jeedom log on every successful test. Decision (Herve, 2026-11-04): log only on failure. Matrix row amended in the plan; other findings rejected (see the plan's Review Triage Log).

## Verdict

Code complete and reviewed. Not closed until the field check (AC 7) is run on the real CSR.

## Follow-ups

- Field check on 194.51.213.114:5390: `sia-dcs` gives the DUH verdict, `null` is ACKed.
- Push 19fb318 (not pushed).
- Optional: pylint cleanup in `_send_rp`; English doc row.
