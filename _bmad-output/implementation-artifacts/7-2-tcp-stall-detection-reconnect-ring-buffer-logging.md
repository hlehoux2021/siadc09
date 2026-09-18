# Story 7.2: TCP Stall Detection, Reconnect & Ring Buffer Logging

Status: review

> **Amendment 2026-09-17 — daemon self-stop on `TRANSPORT_PERMANENT` (AC15–AC17, Task 8).**
> The original scope shipped and was validated, but it froze the WRONG recovery model. AC2 and the
> Dev Notes ("NO_NETWORK is terminal — daemon never recovers", lines below) documented that the daemon
> keeps running after the TCP reconnect loop exhausts its attempts. The frozen design says the opposite
> in four places: `daemon-design.md:589` (`NO_NETWORK --> [*] : _notify() + self.stop()`), `:616`
> (`TCP reconnect exhausted → NO_NETWORK → _notify(TRANSPORT_PERMANENT) + self.stop()`), `:677`, `:684`,
> and story 3-3's `_dispatch_notify` stub docstring ("TRANSPORT_PERMANENT: fire all callbacks, then call
> daemon.stop()"). Field evidence on host SM1: the daemon sits in `NO_NETWORK` forever, logging
> `NO_NETWORK: SUPERVISION dropped (daemon stopping, counter=N)` every minute without ever stopping, so
> the Jeedom watchdog restart (`on_start()` → `INITIALIZING` → fresh reconnect) never fires. This is a
> confirmed bug, which authorises the daemon.py edit under 12-7's anti-pattern escape clause ("unless a
> bug is found"). Option A (chosen): wire `self.stop()` on the `TRANSPORT_PERMANENT` transition so the
> watchdog restarts the daemon. Status reopened to `in-progress` for AC15–AC17 only; AC1–AC14 stay done.
> Validation is owned by 12-7 AC11 / Task 10 (already asserts self-stop — no change there).

## Story

As a daemon architect,
I want proper integration tests for TCP stall detection, reconnect recovery, and ring buffer logging,
So that the already-implemented TCP reconnect flow is verified to work correctly end-to-end and the dual-task race condition (D-3) is fixed.

## Acceptance Criteria

1. **TCP reconnect loop success path** — `_tcp_reconnect_loop()` called with mocked `asyncio.open_connection` succeeding on first attempt → SM1 transitions to INITIALIZING, `_strike_counter=0`, `_sm1_t3_fired=False`, `_sm1_state_changed` event is set. Test runs the real method (not manually setting state).

2. **TCP reconnect loop permanent failure** — `_tcp_reconnect_loop()` with all 3 `asyncio.open_connection` attempts failing (TimeoutError/OSError) → SM1 transitions to NO_NETWORK, `_notify(TRANSPORT_PERMANENT, TransportPermanentCtx{...})` fired exactly once, `_sm1_state_changed` event is set. *(Extended by AC15 — the loop also schedules `self.stop()` after the notify; see Amendment 2026-09-17.)*

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

### Amendment 2026-09-17 — daemon self-stop on `TRANSPORT_PERMANENT` (Option A)

15. **`_tcp_reconnect_loop()` schedules a clean shutdown after permanent failure** — After all `max_attempts`
    fail, the loop MUST, in order: (a) `_set_sm1_state(SM1State.NO_NETWORK)`, (b) `_notify(ErrorCode.TRANSPORT_PERMANENT, ...)`,
    (c) log the "transitioning to NO_NETWORK" error, then (d) schedule `self.stop()` as a tracked task
    (`self._track_task(self.stop(), name="transport_permanent_stop")`). The loop must NOT `await self.stop()`
    inline — `BaseDaemon.stop()` cancels *all* tasks including the current one (`asyncio.all_tasks()` minus
    `current_task()` — see framework note), and `on_stop()` step 3 also cancels `_tasks`; scheduling avoids the
    reconnect-loop task cancelling itself mid-shutdown and losing the ordered `_notify` dispatch. Ordering is
    critical: the `TRANSPORT_PERMANENT` notify is fire-and-forget via `_track_task`, so `self.stop()` must be
    scheduled *after* `_notify` returns to guarantee the notify task exists in `_tasks` before `on_stop()`
    gathers/awaits them (see AC16).

16. **The `TRANSPORT_PERMANENT` notification survives the shutdown it triggers** — When `self.stop()` runs,
    `on_stop()` step 4 awaits all tracked tasks with `ON_STOP_TASK_TIMEOUT_S`. The `notify_TRANSPORT_PERMANENT`
    dispatch task (message_center + notify + error_update, T3) MUST complete before the process exits, so the
    operator receives the `CRITIQUE — Connexion tcp impossible` alert. Test asserts all three callback payloads
    (`message_center`, `notify`, `error_update`) were sent before `on_stop()` returns.

17. **Self-stop is scoped to `TRANSPORT_PERMANENT` only** — No other T3 code path gains a `self.stop()`.
    `SUPERVISION_DISCONNECTED` and `EVENT_FAILED` are T3 but the daemon keeps running (they are recoverable —
    supervision can resume, later events can succeed). The `self.stop()` call lives in `_tcp_reconnect_loop()`
    at the `NO_NETWORK` transition, NOT in `_dispatch_notify()` (which must stay tier-generic — it dispatches
    callbacks for all codes and has no business terminating the process). Test: firing `_notify(SUPERVISION_DISCONNECTED)`
    or `_notify(EVENT_FAILED)` directly does NOT schedule a `transport_permanent_stop` task.

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

### Task 8: Daemon self-stop on `TRANSPORT_PERMANENT` — amendment 2026-09-17 (AC15–AC17)

- [x] **8.1** `resources/siadc09d/daemon.py` `_tcp_reconnect_loop()` (permanent-failure tail, currently
  lines ~1126–1136): after the existing three statements (`_set_sm1_state(NO_NETWORK)`,
  `_notify(TRANSPORT_PERMANENT, ...)`, `_logger.error(...)`), add:
  ```python
  # Option A: hand the process back to Jeedom's watchdog for a clean restart.
  # BaseDaemon.stop() cancels every task except the caller, then run()'s finally
  # block removes the PID file and sys.exit(0)s — the watchdog then re-launches us
  # (on_start → INITIALIZING → fresh reconnect). Schedule it (do NOT await): stop()
  # cancels _tasks including this loop, and awaiting inline would cancel ourselves
  # mid-call and drop the TRANSPORT_PERMANENT notify. Scheduling AFTER _notify()
  # guarantees the notify task is already in _tasks so on_stop() awaits it (AC16).
  # Ref: daemon-design.md:589/616/677/684, error-handler-design.md, story 3-3 stub docstring.
  self._track_task(self.stop(), name="transport_permanent_stop")
  ```
- [x] **8.2** Verify no `self.stop()` is added to `_dispatch_notify()` — it stays tier-generic (AC17).
  The termination decision belongs to the state-machine transition, not the notification dispatcher.
- [x] **8.3** `tests/level2/test_tcp_reconnect_integration.py` — extend the permanent-failure test (AC2's
  `test_...permanent_failure`): after all 3 `open_connection` calls raise, assert a task named
  `transport_permanent_stop` is scheduled AND that `daemon.stop` (patched/spied) is invoked exactly once.
  Gather `daemon._tasks` to let it run; assert `on_stop()` ran (transport closed, tasks cancelled).
- [x] **8.4** Test AC16: with real `_dispatch_notify` (mock only `_send_callback`), drive the loop to
  permanent failure and assert all three payloads (`message_center`, `notify`, `error_update`) were sent
  to `_send_callback` before `stop()`/`on_stop()` completes — the notify is not lost to shutdown.
- [x] **8.5** Test AC17: call `_notify(SUPERVISION_DISCONNECTED)` and `_notify(EVENT_FAILED)` directly →
  assert NO `transport_permanent_stop` task is ever scheduled (self-stop is TRANSPORT_PERMANENT-scoped).
- [x] **8.6** Reverse the now-false Dev Notes: update the "NO_NETWORK is terminal — daemon never recovers"
  paragraph and AC8's "zombie state" note to state the daemon self-stops so the watchdog restarts it.
  Keep the CancelledError-during-shutdown note (that path is genuine shutdown, unchanged).
- [x] **8.7** Run `python3 -m pytest tests/ -q --tb=short` — full suite green (baseline: 1 pre-existing
  failure `test_tc13`). Then `python3 -m pylint resources/siadc09d/daemon.py`.
- [ ] **8.8** VM validation is 12-7 AC11 / Task 10 (already written, `ready-for-dev`) — do NOT duplicate it
  here. Once code lands, 12-7 Task 10.5/10.6 (`pgrep -f siadc09d` → no output, watchdog restart) is the
  end-to-end gate. Re-run against SM1.

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
> **Amendment 2026-09-17:** Note that the permanent-failure path now schedules `self.stop()` (AC15),
> so the loop's *own* task will be cancelled by `on_stop()` step 3 shortly after it schedules the stop.
> That cancellation lands AFTER the loop has returned (it schedules and falls off the end), so it is a
> no-op, not a lost transition. The genuine "cancelled mid-`open_connection`" shutdown case above is
> unchanged.

**`_tcp_reconnect_loop()` probes via `asyncio.open_connection()` with `wait_for` timeout:**
Not via `SIATCPTransport` — it bypasses the transport layer to directly probe reachability. On success, it closes the probe connection immediately (writer.close() + wait_closed()).

**`_tcp_reconnect_loop()` on success resets _sm1_t3_fired:**
Line 1069: `self._sm1_t3_fired = False`. This is critical — allows T3 to fire again on the next escalation cycle.

**Fixed delay, NOT exponential backoff:**
`self._preset.reconnect_delay_s` is constant (default 5s). Exponential backoff is an anti-pattern here — a CSR restart completes in seconds.

**NO_NETWORK triggers a clean self-stop → watchdog restart (amended 2026-09-17):**
~~After `_tcp_reconnect_loop()` exhausts attempts, `_set_sm1_state(SM1State.NO_NETWORK)` is set and `_notify(TRANSPORT_PERMANENT, ...)` fires. The daemon continues running (no `self.stop()`) — Jeedom's watchdog will notice `supervision_state` going stale and the next cron5 freshness check will fire an alert. The daemon does NOT self-terminate.~~
**Superseded (this note froze the wrong model and produced the SM1 dead-end).** After `_tcp_reconnect_loop()`
exhausts attempts it sets `NO_NETWORK`, fires `_notify(TRANSPORT_PERMANENT, ...)`, then **schedules
`self.stop()`** (AC15). `BaseDaemon.stop()` runs `on_stop()` (final STOPPED INFO push, queue drain, cancel
tasks) and `run()`'s `finally` removes the PID file and `sys.exit(0)`. Jeedom's runtime watchdog (auto=1,
every minute) then relaunches the process, re-entering `on_start()` → `INITIALIZING` → a fresh reconnect
cycle. This is the recovery model the design always specified (`daemon-design.md:589/616/677/684`); the
daemon does NOT sit in `NO_NETWORK` indefinitely. The old "counter=N, daemon stopping" log line that never
led to a stop was the symptom of this missing call.

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

Amendment 2026-09-17 (AC15–AC17, Task 8):
  resources/siadc09d/daemon.py                     ← schedule self.stop() in _tcp_reconnect_loop() permanent-failure tail (~line 1136)
  tests/level2/test_tcp_reconnect_integration.py   ← extend permanent-failure test + AC16/AC17 tests
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
- [Amendment 2026-09-17] [Source: docs/design/daemon-design.md:589,616,677,684 — `NO_NETWORK --> [*] : _notify() + self.stop()`; the authoritative recovery model this story now aligns to]
- [Amendment 2026-09-17] [Source: docs/design/supervision-design.md:92 — `on_stop()` Push STOPPED before process exits; :641 — watchdog auto-restarts within ~1 min]
- [Amendment 2026-09-17] [Source: _bmad-output/implementation-artifacts/3-3-error-handler-module-structure-callback-types.md — stub docstring: "TRANSPORT_PERMANENT: fire all callbacks, then call daemon.stop()" (contract, deferred to Epic 6, never wired)]
- [Amendment 2026-09-17] [Source: _bmad-output/implementation-artifacts/12-7-error-handling-notification-delivery.md — AC11 / Task 10.5–10.6: VM validation that the daemon exits and the watchdog restarts it]
- [Amendment 2026-09-17] [Source: jeedomdaemon.BaseDaemon.stop() — cancels `asyncio.all_tasks()` minus current, then run()'s finally removes PID + sys.exit(0); this is why self.stop() must be scheduled, not awaited]

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
- **Task 8 (self-stop on `TRANSPORT_PERMANENT`, AC15–AC17):** Added `self._track_task(self.stop(), name="transport_permanent_stop")` to the `_tcp_reconnect_loop()` permanent-failure tail (daemon.py ~1146), scheduled AFTER `_notify(TRANSPORT_PERMANENT)` so the notify task is already in `_tasks` when `on_stop()` gathers (AC16). Scheduled, not awaited — awaiting inline would cancel the loop mid-call via `BaseDaemon.stop()` and drop the notify. Self-stop is scoped to this one path; `_dispatch_notify()` stays tier-generic so other T3 codes (`SUPERVISION_DISCONNECTED`, `EVENT_FAILED`) do NOT self-stop (AC17). Added `_install_stop_spy()` test helper (level2 + level3) that discards `asyncio.current_task()` from `_tasks` then awaits the real `on_stop()`, letting the scheduled stop run non-recursively — this also fixed the RecursionError/hang the naive real-`stop()` path caused at level3 event-loop teardown. Tests: level2 TCP suite 25 passed (AC15 `test_reconnect_permanent_failure_schedules_self_stop`, AC16 `test_transport_permanent_notify_survives_self_stop`, AC17 `test_other_t3_notifications_do_not_self_stop`); level3 `test_tcp_no_network_daemon_self_stop` passes at 8.22s (no hang). Reversed the two now-false Dev Notes paragraphs (8.6). **Validation gate (8.7):** full suite 11 failed / 1492 passed — all 11 failures proven pre-existing via git-stash baseline comparison (0 regressions from this change); `pylint resources/siadc09d/daemon.py` exit 0 (the 8.53/10 delta is stale-cache style warnings outside the edited region 1138–1146, not new findings). **VM validation (8.8) deferred to story 12-7 AC11 / Task 10 — NOT executed here (no duplication).**

### Change Log

- 2026-05-04: Fixed D-3 dual-task race condition in `_update_sm1_from_strike()` + state regression guard in `_handle_supervision_tcp_drop()`. Created `tests/level2/test_tcp_reconnect_integration.py` with 21 integration tests covering all ACs.
- 2026-09-17: **Testing feedback recorded (TF-1…TF-4)** from 12-4 VM supervision-loss test — see "Testing Feedback — 2026-09-17" section. Proposed AC18 (push NO_NETWORK label before self-stop, fold into AC15), AC19 (reconnect backoff schedule + total budget), AC20 (wire `--retry-count` + add `--reconnect-delay` through CSRPreset), AC21 (fix stale `TCP_CONNECT_TIMEOUT_S` log/docstring). Analysis only — awaiting go-ahead to implement.
- 2026-09-17: **Amendment — daemon self-stop on `TRANSPORT_PERMANENT` (Option A, AC15–AC17, Task 8).** Reopened `done → in-progress`. Root cause: the reconnect loop set `NO_NETWORK` and fired `_notify(TRANSPORT_PERMANENT)` but never called `self.stop()`, so host SM1 sat in `NO_NETWORK` forever (log: `NO_NETWORK: SUPERVISION dropped (daemon stopping, counter=N)` every minute) and the Jeedom watchdog restart never triggered. AC2 + Dev Notes had frozen this "no self.stop()" behavior, contradicting `daemon-design.md:589/616/677/684` and the story 3-3 `_dispatch_notify` stub contract. Fix scopes `self._track_task(self.stop(), name="transport_permanent_stop")` to the `_tcp_reconnect_loop()` permanent-failure tail only (NOT `_dispatch_notify`). Reversed the two now-false Dev Notes paragraphs. VM validation stays owned by 12-7 AC11 / Task 10 (unchanged). Design docs were already correct — no design-first pass needed.
- 2026-09-18: **Amendment implemented (Task 8 complete, AC15–AC17).** Wired the scheduled self-stop in `_tcp_reconnect_loop()` (daemon.py ~1146); added `_install_stop_spy()` + AC15/AC16/AC17 tests in `tests/level2/test_tcp_reconnect_integration.py` (25 passed) and wired the spy into `tests/level3/test_full_workflow_e2e.py::test_tcp_no_network_daemon_self_stop` (fixes RecursionError at teardown, passes 8.22s). Validation gate: full suite 11 failed / 1492 passed — all 11 pre-existing (proven via stash baseline), 0 regressions; pylint exit 0. VM validation (8.8) deferred to 12-7 AC11/Task 10. Status `in-progress → review`. TF-1…TF-4 (proposed AC18–AC21) remain out of scope for this story.

### File List

- `resources/siadc09d/daemon.py` — modified: state regression guard + D-3 guard
- `tests/level2/test_tcp_reconnect_integration.py` — created: 21 integration tests

**Amendment 2026-09-17 (implemented — Task 8, AC15–AC17):**
- `resources/siadc09d/daemon.py` — modified: schedule `self._track_task(self.stop(), name="transport_permanent_stop")` in `_tcp_reconnect_loop()` permanent-failure tail (line ~1146), after `_notify(TRANSPORT_PERMANENT)`. Self-stop scoped to this path only — `_dispatch_notify()` stays tier-generic (AC17).
- `tests/level2/test_tcp_reconnect_integration.py` — modified: added `_install_stop_spy()` helper; extended permanent-failure test into `test_reconnect_permanent_failure_schedules_self_stop` (AC15), added `test_transport_permanent_notify_survives_self_stop` (AC16) + `test_other_t3_notifications_do_not_self_stop` (AC17).
- `tests/level3/test_full_workflow_e2e.py` — modified: added `_install_stop_spy()` and wired it into `test_tcp_no_network_daemon_self_stop` so the scheduled real `self.stop()` drains non-recursively (prevents RecursionError at event-loop teardown).

### Review Findings

- [x] [Review][Decision] AC6: D-3 task-name guard missing from `_handle_supervision_tcp_drop()` — DISMISSED: state regression guard (TCP_RECONNECTING | NO_NETWORK) covers AC6's intent; task-name guard is redundant here. Spec bullet was over-specified.
- [x] [Review][Patch] T3_PREFIX substring `in` check is weaker than `startswith` — can skip prefix for titles that contain T3_PREFIX as a substring but not at position 0 [daemon.py:525]
- [x] [Review][Patch] `_sm1_state_changed` event not cleared before reconnect loop assertions — test may pass vacuously if event is already set from earlier fixture state [test_tcp_reconnect_integration.py:133]
- [x] [Review][Patch] AC10: `is_routine=False` not asserted in ring buffer test — test checks `level=="warning"` and `context.strike==3` but never checks `entry.get("is_routine") is False` [test_tcp_reconnect_integration.py:669-677]
- [x] [Review][Defer] Queue consumer gate tests use `asyncio.sleep(0)` instead of `asyncio.gather()` — violates testing.md rule but structurally necessary (consumer loop cannot be joined mid-run) [test_tcp_reconnect_integration.py:715,765] — deferred, structural constraint
- [x] [Review][Defer] Asymmetric guard strategies: `_handle_supervision_tcp_drop` guards on SM1 state while `_update_sm1_from_strike` guards on task name — edge case where the two disagree is theoretically possible [daemon.py:1019,742] — deferred, pre-existing design trade-off

## Testing Feedback — 2026-09-17 (supervision-loss field test, Herve)

Surfaced during 12-4 VM testing after a real connectivity loss to the CSR (`192.168.100.15:10002`, account `001234`). Log excerpt `0700–0717`. Four findings, all in the `_tcp_reconnect_loop()` path this story owns. **Recorded for analysis — not yet implemented.**

### TF-1 — Widget label stuck at "Reconnexion TCP/UDP…" after reconnect fails
- **Observed:** on permanent failure (`log 0717`, transition to NO_NETWORK), the widget `supervision_label` stays at `Reconnexion TCP/UDP…` indefinitely.
- **Root cause:** `_set_sm1_state()` [daemon.py:577-596] only mutates `_sm1_state` + sets `_sm1_state_changed` — it never pushes an `info_update`. The last label pushed was `SM1_TCP_RECONNECTING_FR` [messages.py:41] when entering TCP_RECONNECTING (`log 0705`). The NO_NETWORK transition [daemon.py:1127] fires no `_update_info_commands()` → the widget is never told. Confirms the tested build predates the pending AC15 self-stop amendment: `on_stop()` would have pushed `"ARRÊTÉ"` [daemon.py:2059], and no such push appears in the log.
- **Recommended fix:** fold into the open AC15 amendment (same code tail). Push an explicit `_update_info_commands()` with `SM1_NO_NETWORK_FR` ("HORS RÉSEAU — arrêt") [messages.py:42] at daemon.py:1127 **before** scheduling `self.stop()`. **Design point — RESOLVED (Herve, 2026-09-17):** the widget must read **"HORS RÉSEAU — arrêt"** during the down/restart window, so `on_stop()` must carry the terminal reason instead of the generic `"ARRÊTÉ"` [daemon.py:2059]. Implementation: pass the terminal label into `on_stop()` (or set an instance field the STOPPED push reads) so the NO_NETWORK reason survives shutdown; the label then clears to `DÉMARRAGE…` when the watchdog restarts. Proposed new **AC18**.

### TF-2 — Reconnect sequence too aggressive (starts fast, probes too close, gives up in ~30s)
- **Observed:** whole 3-attempt sequence completes in ~30s (`log 0703→0717`) then declares NO_NETWORK. Herve: too fast after the loss and too tightly spaced — give connectivity time to recover.
- **Root cause:** fixed non-growing delay `_preset.reconnect_delay_s` = 5.0 [presets.py:43] at daemon.py:1092, and `TCP_RECONNECT_MAX_ATTEMPTS` = 3 [daemon.py:182] at daemon.py:1082. No exponential/linear backoff; total reconnect budget ≈ 3 × (5s delay + ~5s probe) ≈ 30s. A router reboot / ISP blip / IMA Protect restart routinely exceeds that.
- **Recommended fix:** replace fixed delay with a growing backoff and raise the attempt budget so the daemon tries for ~15 min before NO_NETWORK. **Schedule — RESOLVED (Herve, 2026-09-17):** **6 attempts, delays 30 / 60 / 120 / 300 / 300 / 300s** (cap 300s), ≈ 15 min total budget before declaring NO_NETWORK. Implement as a delay-sequence helper (per-attempt lookup with cap), not a single constant. Note the interaction with the AC15 self-stop: after NO_NETWORK the watchdog restarts in ~1 min → INITIALIZING → 3 strikes over ~3 min → reconnect again, so the *outer* recovery loop already re-tries; the inner loop just needed to stop declaring defeat in 30s. Proposed new **AC19**.

### TF-3 — `--retry-count` parsed but never used; `reconnect_delay_s` never wired
- **Root cause:** `--retry-count` [siadc09d.py:382] is parsed but the loop reads the hardcoded `TCP_RECONNECT_MAX_ATTEMPTS` [daemon.py:1082]; `CSRPreset(...)` construction [siadc09d.py:389-402] omits `reconnect_delay_s`, leaving the dataclass default 5.0 [presets.py:43], and there is no `--reconnect-delay` arg at all. Neither attempt count nor delay is operator-tunable.
- **Recommended fix:** make `TCP_RECONNECT_MAX_ATTEMPTS` a `CSRPreset` field fed by `--retry-count`; add a `--reconnect-delay` CLI arg → `reconnect_delay_s`. Full chain to expose to operators: wizard field → PHP daemon-launch args → CLI → CSRPreset → loop (touches epic 6 PHP + epic 8 wizard). **Interaction with AC19:** the new default attempt count must become **6** (was 3) to match the resolved backoff schedule, and `--retry-count` then caps how far into the 30/60/120/300… sequence the loop walks (extra attempts reuse the 300s cap). Decide whether `--reconnect-delay` overrides the *base* of the sequence or is retired in favor of a fixed schedule — recommend keeping it as the base (first) delay so operators can still widen/tighten. Proposed new **AC20**.

### TF-4 — Probe-timeout log/docstring lie about the real timeout (found while tracing TF-2)
- **Observed:** `log 0709→0710` shows the probe times out **5s** after "Probing…", but the message reads `timed out (10s)`.
- **Root cause:** the probe actually uses `self._preset.connect_timeout_s` = 5.0 [siadc09d.py:399 → daemon.py:1099], but the warning f-string [daemon.py:1119] and the docstring [daemon.py:1066] both interpolate the stale constant `TCP_CONNECT_TIMEOUT_S` = 10 [daemon.py:183], which is no longer the value in effect. `TCP_CONNECT_TIMEOUT_S` is now a dead/misleading constant.
- **Recommended fix:** log the real `self._preset.connect_timeout_s`; delete or repurpose `TCP_CONNECT_TIMEOUT_S`; correct the docstring. Low-risk, bundle with TF-3. Proposed new **AC21**.
