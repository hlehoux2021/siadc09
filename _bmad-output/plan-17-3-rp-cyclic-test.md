---
title: '17-3 RP cyclic test'
type: 'feature'
ticket: ''
created: '2026-10-18'
status: 'built'
baseline_revision: 'b61fc517aaea7594936b9f3702e48703b574f489'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 17.1 carries `rp_enabled` / `rp_interval_s` into `CSRPreset`, but the daemon never sends an RP. A CSR that supervises on-demand transmitters by their cyclic test (Ajax, Scutum) shows a link alarm.

**Approach:** Add an RP loop that sends `"SIA-DCS"<seq>L0#acct[#acct|Nri0/RP0000]_ts` at daemon start, then every `rp_interval_s` counted from the end of the previous RP exchange. It goes through the normal send path (ACK/NAK/retries). An RP ACK refreshes SM1, and staleness becomes 3 × the shortest active periodic interval (ADR-08).

## Boundaries & Constraints

**Always:** RP uses area `0` and zone `0000`, never `SIA_AREA_NUMBER`. It draws its seq from the shared tracker. With `rp_enabled = false` no RP task exists and no RP is sent. An alarm event queued meanwhile still wins over RP. Encryption applies as for events. A missing ACK is reported through the existing `EVENT_FAILED` path only: decision (Herve, 2026-10-18), no SM2 change, no event label change and no SM1 strike for a missed RP.

**Never:** Change supervision frames or the 17-2 loop. Add wizard fields (17.4). Let an RP failure or ACK touch the user-facing event state (`event_state`, `event_label`, `_event_sia_code`, `_event_zone`). Hardcode the staleness threshold.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| RP clear | `rp_enabled`, no encryption | `"SIA-DCS"<seq>L0#acct[#acct\|Nri0/RP0000]_ts`, seq from tracker | No error expected |
| RP encrypted | encryption on | `*SIA-DCS` frame with the same data block, encrypted | AESKeyError as for events |
| First frame | daemon start | Enqueued before the first sleep | No error expected |
| Period | exchange takes T s | Next sleep starts after the exchange ends; an event in between does not shift it | Wait released on ACK, NAK, timeout, drop, cancel |
| RP ACK | CSR ACKs | SM1 HEALTHY, strike counter 0, `supervision_state` pushed | No error expected |
| RP not ACKed | timeout or NAK on every re-send | One SM1 strike (T1, T3 at 3); event state and label untouched (amended 2026-10-18, see Plan Change Log) | No in-cycle retry |
| NO_NETWORK | consumer drops RP | Loop wait released, no deadlock | Release in `finally` |
| rp off | `rp_enabled = false` | No RP task, no frame | No error expected |
| Staleness | supervision 60 s + RP 120 s | Threshold 180 s | `none` ignores the supervision interval; RP off ignores RP |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/sia_protocol.py:505` `_format_data_field` -- `extended_data={"area":"0","zone":"0000"}` with code `RP` already gives `[#acct|Nri0/RP0000]`; no builder change needed.
- `resources/siadc09d/daemon.py:1922` `_build_event_frame` -- hardcodes area `SIA_AREA_NUMBER`; leave unchanged (RP gets `_build_rp_frame`).
- `resources/siadc09d/daemon.py:242-259` queue constants -- add `QUEUE_TYPE_RP` (priority = supervision's); `:2186` `_enqueue_supervision` and `:2312` `_supervision_loop` are the templates for `_enqueue_rp` / `_rp_loop` with a `_rp_exchange_done` event.
- `resources/siadc09d/daemon.py:2202-2305` `_queue_consumer` -- RP branch calling `_send_rp`; the `finally` (2305) also sets `_rp_exchange_done` for RP items; the NO_NETWORK branch drops RP silently like SUPERVISION.
- `resources/siadc09d/daemon.py:1594` `_send_with_retry` -- writes SM2 state, `event_state`/`event_label`, `_event_sia_code/_zone/_user_number` at many sites (1627-1677, 1700-1704, 1779, 1827-1830, `_fail_event_config` 1878). A skip flag is fragile: write a dedicated `_send_rp` that reuses the wire/ACK/NAK/timeout mechanics but touches none of that state. On retries exhausted by timeout it calls `_notify(EVENT_FAILED, ...)`; NAK exhaustion keeps its existing `BAD_CSR_RESPONSE`.
- `resources/siadc09d/daemon.py:1156` `_handle_supervision_ack` -- also advances `_sia_seq` and logs a supervision trace, so do not call it for RP. Factor a refresh-only helper (strike 0, `_sm1_t3_fired=False`, HEALTHY, `_last_supervision_ack`, `resolve_t1` callbacks 1189-1194, `supervision_state` push) and call it from both.
- `resources/siadc09d/daemon.py:246,493` `QueueItemType` Literal and the queue annotation -- add `"RP"`. RP shares the supervision priority; ties fall back to the counter.
- `resources/siadc09d/daemon.py:2532` `on_start` -- start `rp_loop` when `rp_enabled`. Build the RP frame in a separate `_build_rp_frame` (area "0", zone "0000"), not in `_build_event_frame` (1922).
- `resources/siadc09d/error_handler.py:432-472` -- `EVENT_FAILED` renders "CRITIQUE — Alarme ... non transmise (zone: None)". Add an RP branch giving a cyclic-test wording (French), with a level-1 test (`tests/level1/test_error_handler*.py`). Check in `_dispatch_notify` that T3 EVENT_FAILED does not stop the daemon (docstring line 594 says it may); if it does for EVENT_FAILED, RP must not.
- `core/class/siaDC09.class.php:385` and `:884` -- helper reads `supervision_format`, `supervision_interval` (ignored for `none`), `rp_enabled` (default 0), `rp_interval` (default `RP_INTERVAL_DEFAULT_S`). `#supervision_interval#` must carry the shortest interval itself: the templates (`core/template/dashboard|mobile/siaDC09.html:36-38`) already multiply by 3, so PHP must not. Follow the source/regex test pattern of `tests/level1/test_php_periodic_frame_guard.py`.
- `resources/siadc09d/csr_simulator.py:565-633` -- RP is neither alarm nor NULL. Classify it as ALARM in both parsers (plain parser currently calls it NULL via `0000` in the block); update the simulator tests that move.
- `tests/level2/test_ipc_daemon_wiring.py:182` -- uses `none` + `rp_enabled=True` with `on_start()`; it now starts an RP. Minimal edit: stub `_enqueue_rp` there, or move to a format that keeps the test focused.
- `tests/level2/test_supervision_default_preset.py:205` -- `none` + RP now expects tasks `{"queue_consumer","rp_loop"}` and one RP frame. Task-count tests with the default preset (`test_supervision_loop_integration.py:966`, `level3/test_full_workflow_e2e.py:551`) stay valid; do not edit them.
- Golden frames: `tests/level1/_dc09_crypto_oracle.py:128` is the decrypted plaintext of the Ajax encrypted vector (use for the encrypted row only); write a new clear golden for `[#acct|Nri0/RP0000]`.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/daemon.py` -- RP queue type, `_enqueue_rp`, `_rp_loop`, consumer branch, RP frame, shared SM1 ACK refresh, `on_start` -- spec 17.3
- [ ] `core/class/siaDC09.class.php` -- shortest-active-interval helper used by the freshness check and the widget tag -- ADR-08
- [ ] `resources/siadc09d/error_handler.py` -- RP wording for EVENT_FAILED -- the failure must not read as a failed alarm
- [ ] `resources/siadc09d/csr_simulator.py` -- RP classified as ALARM in both parsers -- test fidelity
- [ ] `tests/level1/`, `tests/level2/`, PHP level-1 test -- golden frame, matrix rows, staleness helper; update the `none` task test minimally

**Acceptance Criteria:**
- Given `rp_enabled` and `rp_interval_s = 60`, when the daemon runs, then the first RP leaves at start and each next one 60 s after the previous exchange ended.
- Given an event sent between two RPs, when the period elapses, then the RP timing is unchanged.
- Given supervision 60 s and RP 120 s, when staleness is computed, then it is 180 s; given `none` and RP 60 s, then 180 s.

## Implementation Notes

## Plan Change Log

- **2026-10-18 (Herve, after /bmad-review of 17-1..17-4):** the intent above is renegotiated on failure handling.
  - Before: a missed RP gave `EVENT_FAILED` only, no SM1 strike, with a 4-attempt retry loop (up to about 43 s per
    cycle). Two problems: with supervision `none` (Ajax, Scutum) nothing drove SM1, so a dead CSR never reached T3 or
    the TCP reconnect; and the retry loop held the queue, delaying alarms (ADR: events win).
  - After: `_send_rp` makes one attempt per cycle and uses the SM1 handlers of supervision (timeout and NAK are one
    strike, TCP drop starts the reconnect). The NAK re-send is kept, limited to `SUPERVISION_NAK_RESENDS`. T3 now needs
    3 missed cycles. `_notify_rp_failed`, `RP_MAX_RETRIES` and the once-per-outage flag are removed; EVENT_FAILED for RP
    remains only for the invalid encryption key (once per run).
  - Not changed: the 10 s in-flight wait (accepted, same as supervision).
  - Matrix row "RP not ACKed" now reads: timeout, one SM1 strike (T1 / T3), event state and label untouched.

## Review Triage Log

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | Invalid AES key: `_send_rp` re-notifies EVENT_FAILED (T3) every RP cycle | medium | patch (fixed) | Dedupe on `_encryption_config_notified`; test `test_rp_bad_key_notifies_once_across_cycles` added. |
| 2 | Sets SM1 CONFIG_ERROR on bad key, not listed in plan | low | rejected | Same as events and supervision; shared helper, no new behaviour. |
| 3 | No test that an event between RPs does not shift timing | low | rejected | True by construction: the sleep starts after the RP exchange only; fix is test machinery. |
| 4 | No tests for NAK exhaustion, `resolve_t1` on RP ACK | low | rejected | Mechanics shared with the event path, already covered there. |

## Design Notes

RP is its own queue type rather than an EVENT item: the loop needs an exchange-done event, exactly as in 17-2, and an EVENT item has none.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/ -q` -- expected: only the baseline failures (level2 5, level2_5 1)
- `python3 -m pylint resources/siadc09d/` -- expected: no new messages
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors
