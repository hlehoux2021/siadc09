---
title: '17-2 Configurable supervision frame (sia-dcs / null / none)'
type: 'feature'
ticket: ''
created: '2026-10-17'
status: 'built'
baseline_revision: 'faafddba7ad54655b9e58ab5298b22427bd8ae9f'
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

**Problem:** Story 17.1 carries `supervision_format` into `CSRPreset`, but the daemon always sends the `sia-dcs` frame, and the first frame waits one full interval (D-42). A CSR that expects a true Null Message cannot be served.

**Approach:** Make `_supervision_loop` act on `supervision_format` (`sia-dcs` | `null` | `none`). It sends its first frame at daemon start and counts each period from the end of the previous supervision exchange. Add a clear `"NULL"0000L0#acct[]_ts` builder path (§ 5.5.2.1). No wizard, no RP, no PHP change.

## Boundaries & Constraints

**Always:** `sia-dcs` frame bytes stay as today (D-86), encrypted or not. Decision (Herve, 2026-10-17): with encryption on, format `null` sends the real `*NULL` and format `sia-dcs` keeps the encrypted `*SIA-DCS` `0000` fallback, so the format picks the token. A receiver such as ioBroker.sia, which does not answer `*NULL`, is simply not configured with `null`. `null` uses seq `0000` and never draws from the sequence tracker. An ACK refreshes SM1 through the existing `_send_supervision` path. The first frame leaves once per task start, never on an INITIALIZING transition. A queued event still wins over supervision (priority).

**Never:** Touch PHP, including `_checkSupervisionFreshness`. Send RP (17.3). Add wizard fields (17.4). Change the value of `ENCRYPTED_SUPERVISION_TOKEN` (a level-1 test pins it to `SIA-DCS`) or the encrypted `*SIA-DCS` frame used by format `sia-dcs`. Edit the existing `sia-dcs` frame-shape tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| sia-dcs, clear | format `sia-dcs` | `"SIA-DCS"<seq>…[#acct\|0000]`, seq from tracker | No error expected |
| null, clear | format `null`, no encryption | `"NULL"0000L0#acct[]_ts`, tracker seq not consumed | No error expected |
| null, NAK re-send | CSR NAKs the null frame | Re-sent with seq `0000` and a fresh timestamp | Existing `SUPERVISION_NAK_RESENDS` limit |
| null, encrypted | format `null`, encryption on | `"*NULL"0000L0#acct[<cipher>`, tracker seq not consumed | AESKeyError on a bad key, as today |
| sia-dcs, encrypted | format `sia-dcs`, encryption on | Encrypted `*SIA-DCS` `0000` fallback, unchanged | No error expected |
| none | format `none` | No supervision task, no frame | No error expected |
| First frame | daemon start | Enqueued before the first sleep | No error expected |
| Reconnect | INITIALIZING re-entered | No extra supervision enqueue | No error expected |
| Slow exchange | exchange takes T s | Next sleep starts after the exchange ends | Wait released on ACK, NAK, timeout, drop or cancel |
| NO_NETWORK drop | consumer drops the item | Loop wait is released, no deadlock | Release in `finally` |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/daemon.py:2303-2323` `_supervision_loop` -- sleeps first, reads only `supervision_interval_s`; rework for first-frame-at-start and end-of-exchange timing.
- `resources/siadc09d/daemon.py:2179-2191` `_enqueue_supervision` -- queue payload stays `{}`; do not change the 4-tuple shape (tests inspect it).
- `resources/siadc09d/daemon.py:2225-2300` `_queue_consumer` -- single consumer; set a "supervision exchange done" event in its `finally` for SUPERVISION items, including the NO_NETWORK drop.
- `resources/siadc09d/daemon.py:1054-1148` `_send_supervision` -- builder call at ~1096-1105; pass the format; `wire_seq` parsing already handles `0000`.
- `resources/siadc09d/daemon.py:2584-2588` `on_start` -- skip creating the supervision task when format is `none`. Task count stays 2 for the default preset (test at `test_supervision_loop_integration.py:948`).
- `resources/siadc09d/sia_protocol.py:309-364` `make_supervision_message` -- add the clear `"NULL"` path, reusing `_format_account_id`, `_format_timestamp`, `_frame` and `NULL_MESSAGE_SEQ`.
- Decoder and `csr_simulator.py:581-586` already accept clear `NULL`; add a pinning test only.
- `core/class/siaDC09.class.php` -- do not change.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/sia_protocol.py` -- clear `NULL` builder path plus a `null`-format parameter that selects the real `*NULL` branch when encrypted; keep `ENCRYPTED_SUPERVISION_TOKEN` as the `sia-dcs` default -- spec § 5.5.2.1
- [ ] `resources/siadc09d/daemon.py` -- `_send_supervision` passes the format; `_supervision_loop` enqueues first, then waits for the exchange-done event, then sleeps; `on_start` skips the task for `none`; `_queue_consumer` sets the event in `finally`
- [ ] `tests/level1/` -- golden frames for `null` (clear and encrypted `*NULL`), tracker seq not consumed, decoder and simulator accept it
- [ ] `tests/level2/test_supervision_default_preset.py` -- update the cadence test for first-frame-at-start only (same file, minimal edit); add cases for `none`, `null`, end-of-exchange timing, reconnect no-double-send

**Acceptance Criteria:**
- Given `supervision_format = sia-dcs`, when the daemon runs, then frames are byte-identical to today and the first leaves at start.
- Given `null` in clear, when a period elapses, then the frame is `"NULL"0000L0#acct[]_ts` and the tracker is unchanged.
- Given `null` with encryption on, when a period elapses, then the frame is the real `*NULL` and `sia-dcs` stays on the `*SIA-DCS` fallback.
- Given `none`, when the daemon runs, then no supervision task exists and no frame is sent.
- Given an exchange that outlasts the interval, when it ends, then the next period starts from that end.
- Given INITIALIZING is re-entered, then no extra supervision frame is enqueued.

## Implementation Notes

## Plan Change Log

## Review Triage Log

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | First frame sent while SM1 is INITIALIZING | false | rejected | Intended by the frozen intent (first frame at start); the consumer already sends in INITIALIZING, as the delayed frame did before. |
| 2 | Loop waits on the exchange event with no timeout | false | rejected | Every consumer path sets the event in `finally`; the TCP_RECONNECTING gate is existing design and wakes on SM1 change. |
| 3 | `test_ipc_daemon_wiring.py` edited outside the plan | low | rejected | The start-of-run frame broke that test; the fix is a one-line preset change, and the only remedy is a plan edit. |
| 4 | Slow-exchange test uses a spy, ACK/NAK/timeout release paths not tested via the consumer | low | rejected | The release is one `finally` line shared by all paths; the NO_NETWORK drop test runs the real consumer. Fix would add test machinery. |
| 5 | Reconnect test checks only `_set_sm1_state` has no enqueue | low | rejected | The loop has no SM1 hook; enqueue sites are only the loop and tests. |
| 6 | `test_unknown_format_rejected` passes `none` | low | rejected | Cosmetic naming; `none` never reaches the builder (`on_start` skips the task). |
| 7 | `null` encrypted without key untested | low | rejected | Same `_make_cipher` path as before, already covered by the existing encryption tests. |
| 8 | Tests clean up only on success path | low | rejected | Matches the pattern in neighbouring tests; no orphaned-task failure shown. |

## Design Notes

End-of-exchange wait: the loop awaits an `asyncio.Event` that the consumer sets in the `finally` around a SUPERVISION item, so ACK, NAK, timeout, TCP drop and the NO_NETWORK drop all release it. Clear the event before each enqueue. Keep the payload `{}`.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/ -q` -- expected: only the baseline failures (level2 5, level2_5 1)
- `python3 -m pylint resources/siadc09d/` -- expected: no new messages beyond existing ones
