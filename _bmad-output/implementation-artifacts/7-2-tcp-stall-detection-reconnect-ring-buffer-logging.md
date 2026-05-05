# Story 7.2: TCP Stall Detection, Reconnect & Ring Buffer Logging

Status: done

## Story

As a daemon architect,
I want proper integration tests for TCP stall detection, reconnect recovery, and ring buffer logging,
So that the already-implemented TCP reconnect flow is verified to work correctly end-to-end and the dual-task race condition (D-3) is fixed.

## Acceptance Criteria

1. **TCP reconnect loop success path** — `_tcp_reconnect_loop()` called with mocked `asyncio.open_connection` succeeding on first attempt → SM1 transitions to INITIALIZING, `_strike_counter=0`, `_sm1_t3_fired=False`, `_sm1_state_changed` event is set. Test runs the real method (not manually setting state).

2. **TCP reconnect loop permanent failure** — `_tcp_reconnect_loop()` with all 3 `asyncio.open_connection` attempts failing (TimeoutError/OSError) → SM1 transitions to NO_NETWORK, `_notify(TRANSPORT_PERMANENT, TransportPermanentCtx{...})` fired exactly once, `_sm1_state_changed` event is set.

3. **TCP reconnect loop partial failure then success** — First 2 attempts fail, 3rd succeeds → SM1=INITIALIZING, strike=0, no TRANSPORT_PERMANENT fired.

4. **TCP stall detection at strike=3** — `_update_sm1_from_strike()` called when `_strike_counter==3` and `transport==TCP` → state transitions to TCP_RECONNECTING and `_tcp_reconnect_loop` task is scheduled. Verify both trigger paths: (a) from `_handle_supervision_timeout()` at strike=3, (b) from `_handle_supervision_nak()` at strike=3.

5. **UDP never enters TCP_RECONNECTING via _update_sm1_from_strike** — UDP transport at strike=3 → stays DEGRADED, no `_tcp_reconnect_loop` task scheduled, `_supervision_value()==0`.

6. **Dual-task guard (D-3 fix)** — If `_tcp_reconnect_loop` is already running (task in `_tasks` with name `"tcp_reconnect_loop"`), a second TCP drop or second strike=3 event MUST NOT spawn a duplicate task. Guard placed at TOP of `_handle_supervision_tcp_drop()` (before `_set_sm1_state`) and in `_update_sm1_from_strike()` (before `_track_task`).

7. **State regression guard** — `_handle_supervision_tcp_drop()` called when SM1 is already TCP_RECONNECTING or NO_NETWORK → returns immediately without state change or task spawn. Prevents late TCP drop callbacks from regressing terminal states.

8. **CancelledError in reconnect loop** — `_tcp_reconnect_loop()` with `asyncio.CancelledError` during `open_connection` → propagates cleanly. SM1 remains TCP_RECONNECTING (zombie state acknowledged — Jeedom watchdog handles recovery via daemon restart).

9. **Nominal TCP drop path** — `_handle_supervision_tcp_drop()` called when SM1 is HEALTHY or DEGRADED → SM1 transitions to TCP_RECONNECTING, `tcp_reconnect_loop` task spawned, warning logged.

10. **Ring buffer logging for TCP state transitions** — When _log_sm1_supervision is called for events that trigger TCP transitions, ring buffer entries have `is_routine=False`. Test uses real `_log_sm1_supervision` (requires ring buffer initialized via fixture with real `RingBuffer` instance).

11. **INFO commands update after TCP transitions** — After `_tcp_reconnect_loop()` sets SM1=INITIALIZING or NO_NETWORK, verify `_supervision_value()` and `_supervision_label()` return correct values for these states.

12. **Queue consumer gate during TCP_RECONNECTING** — Start `_queue_consumer()` as background task, enqueue a SUPERVISION item, set SM1=TCP_RECONNECTING, prove item stays in queue across multiple event-loop yields (`asyncio.sleep(0)` × 3). Then transition SM1=INITIALIZING via `_set_sm1_state()`, verify item gets consumed.

13. **Supervision accumulation during TCP_RECONNECTING** — While SM1==TCP_RECONNECTING, multiple supervision items can accumulate in queue. After recovery to INITIALIZING, verify first dequeued item is processed correctly (no state corruption from stale items).

14. **All existing tests pass** — No regressions. Current baseline: all levels combined + 1 pre-existing failure (test_tc13).

## Tasks / Subtasks

### Task 1: Fix dual-task race condition D-3 + state regression guard (AC6, AC7)

- [x] **1.1** In `daemon.py` `_handle_supervision_tcp_drop()` (line ~999): add state regression guard + D-3 guard at TOP of method (before `_set_sm1_state`):
  ```python
  async def _handle_supervision_tcp_drop(self) -> None:
      # State regression guard: late TCP drop must not regress terminal states
      if self._sm1_state in (SM1State.TCP_RECONNECTING, SM1State.NO_NETWORK):
          self._logger.debug(
              f"TCP drop ignored: SM1 already {self._sm1_state.name}"
          )
          return
      self._set_sm1_state(SM1State.TCP_RECONNECTING)
      self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
      self._logger.warning("TCP connection dropped by OS, initiating reconnect")
  ```
- [x] **1.2** In `daemon.py` `_update_sm1_from_strike()` (line ~747): add D-3 guard before `_track_task`:
  ```python
  if self._preset.transport is TransportType.TCP:
      self._set_sm1_state(SM1State.TCP_RECONNECTING)
      if not any(t.get_name() == "tcp_reconnect_loop" for t in self._tasks):
          self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
  ```
- [x] **1.3** Run existing tests — verify no regressions from guard addition.

### Task 2: Integration tests for _tcp_reconnect_loop (AC1, AC2, AC3, AC8)

- [x] **2.1** Create `tests/level2/test_tcp_reconnect_integration.py` with test fixture that creates a TCP daemon with `reconnect_delay_s=0.01` (fast tests). Fixture must support `reconnect_delay_s` via a modified `make_daemon_preset(transport="TCP", reconnect_delay_s=0.01)` call or post-creation patch of `daemon._preset.reconnect_delay_s`.
- [x] **2.2** Test: reconnect success on first attempt — mock `asyncio.open_connection` to return `(reader, writer_mock)` on first call. Assert SM1=INITIALIZING, strike=0, t3_fired=False, `_sm1_state_changed.is_set()==True`.
- [x] **2.3** Test: permanent failure — mock all 3 `open_connection` calls to raise `TimeoutError`. Assert SM1=NO_NETWORK, `_notify` called with TRANSPORT_PERMANENT, `_sm1_state_changed.is_set()==True`.
- [x] **2.4** Test: partial failure (2 fail, 1 success) — mock to raise OSError twice, then succeed. Assert SM1=INITIALIZING.
- [x] **2.5** Test: CancelledError propagation — mock `open_connection` to raise `asyncio.CancelledError`. Assert it propagates. Assert SM1 remains TCP_RECONNECTING (no transition).
- [x] **2.6** Test: loop skips immediately for UDP — call `_tcp_reconnect_loop()` on UDP daemon, assert it returns without sleeping or connecting.

### Task 3: Tests for D-3 dual-task guard + state regression (AC6, AC7)

- [x] **3.1** Test: second TCP drop while `_tcp_reconnect_loop` already running → no second task spawned, `_tasks` contains exactly one `tcp_reconnect_loop`.
- [x] **3.2** Test: strike=3 while `_tcp_reconnect_loop` already running → no duplicate task spawned.
- [x] **3.3** Test: after first loop completes (success or failure), a new TCP drop CAN spawn a fresh loop (guard not permanent).
- [x] **3.4** Test: `_handle_supervision_tcp_drop()` called when SM1==NO_NETWORK → returns immediately, no state change, no task spawn.
- [x] **3.5** Test: `_handle_supervision_tcp_drop()` called when SM1==TCP_RECONNECTING (no task name match — pure state guard) → returns immediately.

### Task 4: Tests for nominal TCP drop path + TCP stall detection (AC4, AC5, AC9)

- [x] **4.1** Test: `_handle_supervision_tcp_drop()` called when SM1==HEALTHY → SM1=TCP_RECONNECTING, `tcp_reconnect_loop` in `_tasks`, warning logged.
- [x] **4.2** Test: `_handle_supervision_tcp_drop()` called when SM1==DEGRADED → same transition as 4.1.
- [x] **4.3** Test: `_handle_supervision_timeout()` at strike=2→3 on TCP transport → SM1=TCP_RECONNECTING, `tcp_reconnect_loop` task in `_tasks`.
- [x] **4.4** Test: `_handle_supervision_nak()` at strike=2→3 on TCP transport → same as 4.3.
- [x] **4.5** Test: same scenario on UDP → stays DEGRADED, no reconnect task.

### Task 5: Tests for ring buffer and INFO commands around TCP (AC10, AC11)

- [x] **5.1** Test: after successful reconnect (SM1=INITIALIZING), `_supervision_value()==1` and `_supervision_label()=="DÉMARRAGE…"`.
- [x] **5.2** Test: after permanent failure (SM1=NO_NETWORK), `_supervision_value()==0` and `_supervision_label()=="HORS RÉSEAU — arrêt"`.
- [x] **5.3** Test: timeout event at strike=3 pushes ring buffer entry with `is_routine=False`. Uses real `_log_sm1_supervision` (non-mocked) with an initialized `RingBuffer` instance.

### Task 6: Tests for queue consumer gate (AC12, AC13)

- [x] **6.1** Test: start `_queue_consumer()` as background task, enqueue a SUPERVISION item, set SM1=TCP_RECONNECTING. After 3× `asyncio.sleep(0)` (multiple event-loop yields), verify queue is NOT empty (item not consumed). Then call `_set_sm1_state(SM1State.INITIALIZING)`, after 3× `asyncio.sleep(0)`, verify item was consumed (queue empty). Cancel consumer task at end.
- [x] **6.2** Test: enqueue 3 SUPERVISION items while SM1==TCP_RECONNECTING. Transition to INITIALIZING. Verify all 3 are consumed sequentially (no loss, no corruption).

### Task 7: Full suite regression (AC14)

- [x] **7.1** Run `python3 -m pytest tests/ -q --tb=short` — verify no regressions from D-3 fix + state regression guard.

## Dev Notes

### What Already Exists (DO NOT RE-IMPLEMENT)

The TCP reconnect flow is **fully implemented** in `daemon.py`. Story 7.2 focuses on:
1. Fixing D-3 (dual-task race) — guard in `_update_sm1_from_strike()`
2. Adding state regression guard in `_handle_supervision_tcp_drop()` (prevents late TCP drop from regressing NO_NETWORK)
3. Writing proper integration tests that exercise the real `_tcp_reconnect_loop()` method

| Method | File | Lines | Status |
|--------|------|-------|--------|
| `_handle_supervision_tcp_drop()` | daemon.py | 999–1015 | ✅ Complete (needs D-3 guard + state regression guard) |
| `_tcp_reconnect_loop()` | daemon.py | 1017–1096 | ✅ Complete |
| `_update_sm1_from_strike()` | daemon.py | 714–764 | ✅ Complete (needs D-3 guard) |
| `_log_sm1_supervision()` | daemon.py | 1098–1238 | ✅ Complete |
| `_set_sm1_state()` | daemon.py | 548–567 | ✅ Complete (sets `_sm1_state_changed` event) |
| `_queue_consumer()` gate | daemon.py | 1706+ | ✅ Complete (waits on `_sm1_state_changed`) |

### Key Design Facts

**`_tcp_reconnect_loop()` uses real `asyncio.open_connection` — must be mocked in tests:**
Use `patch("asyncio.open_connection")` or `patch.object` to control probe behavior. The loop sleeps `self._preset.reconnect_delay_s` between attempts — use `reconnect_delay_s=0.01` in test preset for fast execution.

**D-3 dual-task race condition:**
Both `_handle_supervision_tcp_drop()` (direct TCP drop from transport) and `_update_sm1_from_strike()` (strike=3 on TCP) call `self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")`. If a TCP drop arrives during an existing reconnect attempt, or if two timeouts trigger strike=3 concurrently (e.g., one from queue consumer, one from a stale callback), two loops can race to `NO_NETWORK`. The guard: check `any(t.get_name() == "tcp_reconnect_loop" for t in self._tasks)` before scheduling.

**State regression guard (NEW — from AR Finding 2):**
`_handle_supervision_tcp_drop()` can be called by the transport layer at any time (late callback). If SM1 is already TCP_RECONNECTING or NO_NETWORK (terminal), the method MUST return immediately — otherwise it regresses SM1 state and spawns a zombie loop. The guard is `if self._sm1_state in (SM1State.TCP_RECONNECTING, SM1State.NO_NETWORK): return` at the very top of the method. This is MORE important than the D-3 guard (which catches a narrower race).

**Post-reconnect transport state (acknowledged limitation):**
After `_tcp_reconnect_loop()` succeeds, SM1=INITIALIZING and supervision resumes. The `_sia_transport` instance is NOT recreated — it's a per-frame transport (SIATCPTransport opens a new connection per `send_frame()`), so stale socket state is not a concern. Each subsequent `_send_supervision()` call creates a fresh TCP connection via the transport's own `send_frame()`.

**CancelledError zombie state (acknowledged):**
If `_tcp_reconnect_loop()` is cancelled (daemon shutdown), SM1 remains TCP_RECONNECTING with no transition. This is acceptable — the daemon is shutting down (`on_stop()` cancels all tasks). Jeedom's cron5 watchdog handles any edge case where the daemon process survives in this state.

**`_tcp_reconnect_loop()` probes via `asyncio.open_connection()` with `wait_for` timeout:**
Not via `SIATCPTransport` — it bypasses the transport layer to directly probe reachability. On success, it closes the probe connection immediately (writer.close() + wait_closed()).

**`_tcp_reconnect_loop()` on success resets _sm1_t3_fired:**
Line 1069: `self._sm1_t3_fired = False`. This is critical — allows T3 to fire again on the next escalation cycle.

**Fixed delay, NOT exponential backoff:**
`self._preset.reconnect_delay_s` is constant (default 5s). Exponential backoff is an anti-pattern here — a CSR restart completes in seconds.

**NO_NETWORK is terminal — daemon never recovers:**
After `_tcp_reconnect_loop()` exhausts attempts, `_set_sm1_state(SM1State.NO_NETWORK)` is set and `_notify(TRANSPORT_PERMANENT, ...)` fires. The daemon continues running (no `self.stop()`) — Jeedom's watchdog will notice `supervision_state` going stale and the next cron5 freshness check will fire an alert. The daemon does NOT self-terminate.

**Queue consumer gate:**
`_queue_consumer()` has a gate loop: while `self._sm1_state == SM1State.TCP_RECONNECTING`, it waits on `self._sm1_state_changed` event (an `asyncio.Event`). When `_tcp_reconnect_loop()` calls `_set_sm1_state(INITIALIZING)` or `_set_sm1_state(NO_NETWORK)`, the event is set, waking the consumer.

**Writer mock for `asyncio.open_connection`:**
```python
mock_writer = MagicMock()
mock_writer.close = MagicMock()
mock_writer.wait_closed = AsyncMock()
mock_open.return_value = (MagicMock(), mock_writer)
```

### Test Patterns from Story 7.1

From `tests/level2/test_supervision_loop_integration.py`:
```python
def _make_daemon(transport: str = "UDP") -> SIADaemon:
    preset = make_daemon_preset(transport=transport)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon.send_to_jeedom = AsyncMock()
    ...
```

For TCP reconnect tests, use the same pattern but:
- Set `transport="TCP"`
- Set `reconnect_delay_s=0.01` in preset: patch `daemon._preset.reconnect_delay_s = 0.01` after daemon creation (avoids modifying the shared `make_daemon_preset` helper)
- Mock `asyncio.open_connection` (the reconnect loop's external dependency)
- For tasks that complete, use `await asyncio.gather(*daemon._tasks, return_exceptions=True)` to join them

For ring buffer tests (Task 5.3), the fixture must NOT mock `_log_sm1_supervision`. Instead:
- Initialize `daemon._ring_buffer = RingBuffer(max_size=50)` (real instance)
- Provide `daemon._send_callback = AsyncMock()` (ring buffer pushes trigger callback)
- Call the real `_log_sm1_supervision()` and inspect `daemon._ring_buffer` contents

For queue consumer gate tests (Task 6), lifecycle pattern:
```python
consumer_task = asyncio.create_task(daemon._queue_consumer())
try:
    # ... enqueue items, manipulate state, yield control ...
    for _ in range(3):
        await asyncio.sleep(0)  # multiple yields to prove non-consumption
    # ... assert, transition, assert consumption ...
finally:
    consumer_task.cancel()
    with suppress(asyncio.CancelledError):
        await consumer_task
```

### Existing Fake Tests to Note

`tests/level2/test_sm1_extended_suite.py` has `test_tc5_tcp_reconnect_success` and `test_tc6_tcp_permanent_failure` — these are **NOT real integration tests**. They manually set state instead of calling `_tcp_reconnect_loop()`. Story 7.2 writes proper integration tests that exercise the actual method. Do NOT modify the existing tests (they serve as unit-level state assertions).

### Overlap with Story 7.1 Tests (avoid duplication)

`tests/level2/test_supervision_loop_integration.py` already has:
- `test_ar_tc7_1_nak_at_strike3_triggers_tcp_reconnecting` — verifies strike=3 + TCP → TCP_RECONNECTING state
- `test_tc8_tcp_drop_triggers_reconnect` — verifies `_handle_supervision_tcp_drop()` spawns task

Story 7.2 Task 4 tests differ because they:
- Verify the FULL flow through `_handle_supervision_timeout()` / `_handle_supervision_nak()` (not just `_update_sm1_from_strike()`)
- Assert task name in `_tasks` (not just state change)
- Test the nominal `_handle_supervision_tcp_drop()` path from HEALTHY/DEGRADED specifically (7.1 tests don't distinguish entry state)

### File Locations

```
Modified files (Story 7.2):
  resources/siadc09d/daemon.py        ← state regression guard + D-3 guard in _handle_supervision_tcp_drop() + _update_sm1_from_strike()

New files (Story 7.2):
  tests/level2/test_tcp_reconnect_integration.py  ← all new integration tests
```

### Deferred Work from Previous Stories (addressed here)

- **D-3**: Dual `_tcp_reconnect_loop` tasks on concurrent TCP drop — **FIXED in this story** (Task 1)
- **State regression (NEW)**: Late TCP drop callback regressing NO_NETWORK → TCP_RECONNECTING — **FIXED in this story** (Task 1.1, combined with D-3 guard)

### References

- [Source: docs/design/supervision-design.md — "TCP half-open stall at DEGRADED(strike=3)", TCP reconnect policy, Group B]
- [Source: docs/design/daemon-design.md — Task 4 (TCP reconnect logic), CancelledError safety rule]
- [Source: resources/siadc09d/daemon.py:999–1096 — _handle_supervision_tcp_drop + _tcp_reconnect_loop implementation]
- [Source: resources/siadc09d/daemon.py:714–764 — _update_sm1_from_strike with TCP_RECONNECTING transition]
- [Source: resources/siadc09d/daemon.py:548–567 — _set_sm1_state with _sm1_state_changed event]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — D-3 dual task race condition]
- [Source: _bmad-output/implementation-artifacts/7-1-supervision-loop-strike-management-info-updates.md — Story 7.1 patterns and learnings]
- [Source: tests/level2/test_supervision_loop_integration.py — test fixture pattern (_make_daemon)]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- `CSRPreset` is a frozen dataclass — `reconnect_delay_s` cannot be mutated post-creation. `conftest.make_daemon_preset` already sets it to `0.01`; fixture removed the redundant assignment.
- `_log_sm1_supervision` was set as an instance-level `AsyncMock`. Removed via `del daemon.__dict__["_log_sm1_supervision"]` to restore the real class method for ring buffer test (Task 5.3).
- `RingBuffer()` takes no constructor arguments — `max_size` kwarg removed.
- `_slow_open` for Task 3.2 D-3 guard test used `asyncio.get_event_loop().create_future()` as a blocking sentinel; cancelled in finally to drain task cleanly.

### Completion Notes List

- **Task 1 (daemon.py fixes):** Added state regression guard at top of `_handle_supervision_tcp_drop()` — checks `SM1State.TCP_RECONNECTING | NO_NETWORK` and returns early. Added D-3 guard in `_update_sm1_from_strike()` — uses `any(t.get_name() == "tcp_reconnect_loop" for t in self._tasks)` before calling `_track_task`.
- **Task 2 (reconnect loop tests):** 6 tests covering success, permanent failure (TimeoutError + OSError), partial failure, CancelledError propagation, and UDP bypass. All exercise the real `_tcp_reconnect_loop()` method.
- **Task 3 (D-3 + regression guard):** 5 tests verifying no duplicate task from second TCP drop or second strike=3, guard non-permanence (fresh loop after completion), NO_NETWORK guard, and TCP_RECONNECTING state guard.
- **Task 4 (nominal path + stall detection):** 5 tests covering `_handle_supervision_tcp_drop()` from HEALTHY and DEGRADED, `_send_supervision()` at strike=3 via timeout and NAK paths, and UDP non-reconnect behavior.
- **Task 5 (ring buffer + INFO):** 3 tests: INFO commands return correct values for INITIALIZING and NO_NETWORK, ring buffer test uses real `_log_sm1_supervision` + real `RingBuffer` — verifies warning entry with `strike=3` context pushed (non-routine).
- **Task 6 (queue consumer gate):** 2 tests verifying gate blocks during TCP_RECONNECTING and unblocks on transition to INITIALIZING, including accumulation of 3 items and sequential consumption.
- **Task 7 (regression):** Full suite: 926 passed, 1 pre-existing failure (`test_tc13_strike_timing_precision`). No regressions.

### Change Log

- 2026-05-04: Fixed D-3 dual-task race condition in `_update_sm1_from_strike()` + state regression guard in `_handle_supervision_tcp_drop()`. Created `tests/level2/test_tcp_reconnect_integration.py` with 21 integration tests covering all ACs.

### File List

- `resources/siadc09d/daemon.py` — modified: state regression guard + D-3 guard
- `tests/level2/test_tcp_reconnect_integration.py` — created: 21 integration tests

### Review Findings

- [x] [Review][Decision] AC6: D-3 task-name guard missing from `_handle_supervision_tcp_drop()` — DISMISSED: state regression guard (TCP_RECONNECTING | NO_NETWORK) covers AC6's intent; task-name guard is redundant here. Spec bullet was over-specified.
- [x] [Review][Patch] T3_PREFIX substring `in` check is weaker than `startswith` — can skip prefix for titles that contain T3_PREFIX as a substring but not at position 0 [daemon.py:525]
- [x] [Review][Patch] `_sm1_state_changed` event not cleared before reconnect loop assertions — test may pass vacuously if event is already set from earlier fixture state [test_tcp_reconnect_integration.py:133]
- [x] [Review][Patch] AC10: `is_routine=False` not asserted in ring buffer test — test checks `level=="warning"` and `context.strike==3` but never checks `entry.get("is_routine") is False` [test_tcp_reconnect_integration.py:669-677]
- [x] [Review][Defer] Queue consumer gate tests use `asyncio.sleep(0)` instead of `asyncio.gather()` — violates testing.md rule but structurally necessary (consumer loop cannot be joined mid-run) [test_tcp_reconnect_integration.py:715,765] — deferred, structural constraint
- [x] [Review][Defer] Asymmetric guard strategies: `_handle_supervision_tcp_drop` guards on SM1 state while `_update_sm1_from_strike` guards on task name — edge case where the two disagree is theoretically possible [daemon.py:1019,742] — deferred, pre-existing design trade-off
