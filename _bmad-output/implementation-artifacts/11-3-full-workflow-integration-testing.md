---
story_id: "11-3"
story_key: "11-3-full-workflow-integration-testing"
epic_id: "epic-11"
epic_name: "End-to-End Testing & Market Preparation"
status: "ready-for-dev"
created: "2026-05-21"
analysis_completed: "2026-05-21"
---

# Story 11.3: Full Workflow Integration Testing

Status: ready-for-dev

## Story

As a plugin maintainer,
I want complete end-to-end testing of real user scenarios,
So that the plugin is production-ready.

## Acceptance Criteria

1. **Given** plugin fully implemented (Epic 1-10), **When** running full user workflow on real Jeedom, **Then** complete scenario verified: user installs → completes wizard → daemon starts → supervision loop healthy → alarm triggers → CSR ACK → `event_state=CONFIRMED`.

2. **And** test scenario "Happy path": supervision + alarm delivery → full success, event_state transitions IDLE → PENDING → CONFIRMED within 30s.

3. **And** test scenario "Network recovery": supervision timeout → strike escalation (1→2→3) → simulator restored → ACK → recovery to HEALTHY, strike reset to 0.

4. **And** test scenario "Daemon restart": kill daemon process → Jeedom `cron5()` detects → restarts daemon → supervision resumes → HEALTHY within 2 supervision intervals.

5. **And** test scenario "Alarm during network loss": alarm triggers while SM1=DEGRADED → alarm queued in PriorityQueue → network restored → alarm delivered → CONFIRMED.

6. **And** test scenario "CSR error": simulator patched to NAK → BAD_CSR_RESPONSE (T2) notification dispatched → error visible in `last_errors` config key → user notification fired.

7. **And** resource testing: daemon CPU < 5% and RSS < 50 MB under sustained supervision (30+ min run), database write frequency matches 10-min throttle specification, no memory leaks or orphaned asyncio tasks.

8. **And** each scenario runs for at least 5 supervision cycles (configurable interval, recommend 10s for tests).

9. **And** all tests use CSR Simulator on localhost (validated trustworthy in prior epics).

## Tasks / Subtasks

- [ ] Task 1: Test infrastructure and fixtures (AC: 1, 8, 9)
  - [ ] 1.1 Create `tests/level3/test_full_workflow_e2e.py` with `@pytest.mark.level3` marker
  - [ ] 1.2 Create `jeedom_e2e_daemon` fixture: real daemon with real transport, CSR Simulator on ephemeral ports, `send_to_jeedom` as AsyncMock (consistent with existing `tests/level3/conftest.py` pattern)
  - [ ] 1.3 Set `supervision_interval_s=2.0` for fast iteration (5 cycles = 10s); provide `E2E_SCENARIO_TIMEOUT = 30.0` constant
  - [ ] 1.4 Reuse `_wait_for()` from `tests/level3/conftest.py` for all state assertions

- [ ] Task 2: Happy path scenario (AC: 1, 2)
  - [ ] 2.1 `test_happy_path_supervision_then_alarm`: start daemon → wait SM1=HEALTHY → inject `on_message("burglarAlarm", {"zone": "salon"})` → wait SM2=CONFIRMED
  - [ ] 2.2 Assert: supervision_state callbacks include 1 (INITIALIZING) then 2 (HEALTHY)
  - [ ] 2.3 Assert: event_state callbacks include 3 (in-progress) then 1 (confirmed)
  - [ ] 2.4 Assert: ring buffer contains supervision entry + alarm dialog entry
  - [ ] 2.5 Assert: message_trace callback emitted with alarm dialog

- [ ] Task 3: Network recovery scenario (AC: 3)
  - [ ] 3.1 `test_network_recovery_strike_escalation`: daemon HEALTHY → stop simulator → wait strike=3 → restart simulator → wait HEALTHY
  - [ ] 3.2 Assert: SUPERVISION_TIMEOUT dispatched at strike=1, SUPERVISION_DISCONNECTED at strike=3
  - [ ] 3.3 Assert: after recovery, strike=0, `_sm1_t3_fired=False`
  - [ ] 3.4 Assert: supervision_state transitions include 2→1→0→2 (HEALTHY→impaired→critical→HEALTHY)

- [ ] Task 4: Daemon restart scenario (AC: 4)
  - [ ] 4.1 `test_daemon_restart_recovery`: start daemon → HEALTHY → call `on_stop()` → verify STOPPED push → re-create daemon → `on_start()` → wait HEALTHY
  - [ ] 4.2 Assert: first daemon emits supervision_state=0 on stop (ARRÊTÉ label)
  - [ ] 4.3 Assert: second daemon reaches HEALTHY within 2× supervision_interval timeout
  - [ ] 4.4 Assert: SM1 starts at INITIALIZING, progresses to HEALTHY (clean state, no carryover)

- [ ] Task 5: Alarm during network loss scenario (AC: 5)
  - [ ] 5.1 `test_alarm_during_network_loss`: daemon HEALTHY → stop simulator → wait DEGRADED → inject alarm → restart simulator → wait SM2=CONFIRMED
  - [ ] 5.2 Assert: alarm stays queued during DEGRADED (SM2=PENDING persists while no transport)
  - [ ] 5.3 Assert: after recovery, alarm delivered and SM2=CONFIRMED
  - [ ] 5.4 Assert: event_state callback with state=1 (confirmed) arrives after network recovery

- [ ] Task 6: CSR error scenario (AC: 6)
  - [ ] 6.1 `test_csr_error_nak_notification`: patch `sim._decide_response = lambda *_: "NAK"` → daemon starts → wait strike≥1
  - [ ] 6.2 Assert: BAD_CSR_RESPONSE (T2) in dispatched notifications
  - [ ] 6.3 Assert: error_update callback emitted with code=BAD_CSR_RESPONSE
  - [ ] 6.4 Assert: ring buffer entry with `is_routine=False`

- [ ] Task 7: Resource testing (AC: 7)
  - [ ] 7.1 `test_resource_usage_sustained_supervision`: run daemon for 60 supervision cycles (supervision_interval_s=0.5 → 30s total)
  - [ ] 7.2 Assert: no orphaned tasks — `len(daemon._tasks)` stable (tasks created = tasks completed)
  - [ ] 7.3 Assert: ring buffer size never exceeds configured cap (50 entries)
  - [ ] 7.4 Assert: routine entries throttled — count routine ring buffer entries over 30s run, verify ≤ ceil(30s / 600s) + 1 = 1 routine entry (10-min throttle)
  - [ ] 7.5 Optional: measure RSS via `resource.getrusage()` before/after; log warning if delta > 10 MB (informational, not hard-fail)

- [ ] Task 8: Multi-alarm sequence test (AC: 2, 5)
  - [ ] 8.1 `test_multi_alarm_sequential`: inject burglarAlarm → wait CONFIRMED → inject fireAlarm → wait CONFIRMED → inject panicAlarm → wait CONFIRMED
  - [ ] 8.2 Assert: SM2 transitions CONFIRMED→PENDING→CONFIRMED for each subsequent alarm (not IDLE→PENDING)
  - [ ] 8.3 Assert: each alarm produces distinct event callbacks with correct SIA event codes

- [ ] Task 9: Run full test suite and verify no regressions (AC: all)
  - [ ] 9.1 Run `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/ -v` — all pass
  - [ ] 9.2 Run `python3 -m pytest tests/level3/ -v` — all pass (including new tests)
  - [ ] 9.3 Run `find core/ desktop/ -name "*.php" | xargs -n1 php -l` — all pass

## Dev Notes

### Existing Level 3 Test Infrastructure (REUSE)

The test infrastructure is already built in `tests/level3/conftest.py`:

| Asset | What it provides |
|-------|-----------------|
| `_wait_for(predicate, timeout, poll_interval)` | CI-safe async state assertion |
| `_find_free_udp_port()` / `_find_free_tcp_port()` | Ephemeral port allocation |
| `csr_sim` fixture | CSRSimulator lifecycle (start+UDP task, teardown) |
| `make_e2e_daemon(transport, udp_port, tcp_port, ...)` | Pre-wired SIADaemon with mocked `send_to_jeedom` |
| `E2E_ACCOUNT` / `E2E_ENCRYPTION_KEY` | Shared test constants |

**Critical:** `make_e2e_daemon` wires `send_to_jeedom = AsyncMock()` — no PHP/Jeedom required for these tests. These are "Level 3" in the sense of full daemon+transport+simulator stack, not Jeedom-required. Mark `@pytest.mark.level3` and `@pytest.mark.asyncio`.

### Key Daemon APIs for Test Assertions

```python
daemon._sm1_state          # SM1State enum: INITIALIZING, HEALTHY, DEGRADED, TCP_RECONNECTING, NO_NETWORK
daemon._sm2_state          # SM2State enum: IDLE, PENDING, CONFIRMED, FAILED
daemon._strike_counter     # int 0–3
daemon._sm1_t3_fired       # bool — T3 notification sent once at strike=3
daemon._ring_buffer        # RingBuffer instance (._buffer is the internal deque)
daemon._tasks              # set[asyncio.Task] — tracked background tasks
daemon.send_to_jeedom      # AsyncMock — inspect .call_args_list for IPC assertions
daemon.on_message(cmd, params)  # Inject alarm: on_message("burglarAlarm", {"zone": "salon"})
daemon.on_start()          # Start daemon (supervision loop begins)
daemon.on_stop()           # Stop daemon (emits STOPPED push, cancels tasks)
```

### IPC Callback Assertion Pattern (from existing tests)

```python
calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
sup_states = [c.get("supervision_state") for c in calls if "supervision_state" in c]
event_states = [c.get("event_state") for c in calls if "event_state" in c]
error_updates = [c for c in calls if c.get("type") == "error_update"]
```

### SM2 State Transitions (alarm lifecycle)

- First alarm: IDLE → PENDING → CONFIRMED (or FAILED)
- Subsequent alarms: CONFIRMED/FAILED → PENDING → CONFIRMED (SM2 never re-enters IDLE after first alarm)
- Alarm injection: `await daemon.on_message("burglarAlarm", {"zone": "salon"})`
- Valid alarm commands: `"burglarAlarm"`, `"fireAlarm"`, `"panicAlarm"`

### Notification Capture Pattern (from test_supervision_e2e.py)

```python
from resources.siadc09d.error_handler import ErrorCode

dispatched: list[ErrorCode] = []
original_dispatch = daemon._dispatch_notify

async def _capture_dispatch(code, ctx):
    dispatched.append(code)
    await original_dispatch(code, ctx)

daemon._dispatch_notify = _capture_dispatch
```

### Teardown Pattern (CRITICAL)

Always wrap daemon lifecycle in try/finally:
```python
try:
    await daemon.on_start()
    # ... test logic ...
finally:
    with suppress(Exception):
        await daemon.on_stop()
```

For scenarios that restart the simulator:
```python
sim2 = CSRSimulator(udp_port=udp_port, tcp_port=tcp_port, preset=sim_preset)
await sim2.start()
udp_task2 = asyncio.create_task(sim2._handle_udp(), name="sim2_udp_recv")
# ... assertions ...
# Cleanup:
udp_task2.cancel()
with suppress(asyncio.CancelledError):
    await udp_task2
await sim2.stop()
```

### Resource Testing Approach

No external profiling tools needed. Use daemon internal state:
- `len(daemon._tasks)` — should remain bounded (tasks complete and remove themselves via done callbacks)
- `len(daemon._ring_buffer._buffer)` — capped at 50 by `RingBuffer` implementation
- Routine throttle: `RingBuffer` only stores 1 routine entry per 10 minutes; in a 30s test, expect ≤1 routine entry
- Optional RSS: `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` (macOS: bytes, Linux: KB)

### File Structure

```
tests/level3/
├── conftest.py                    # EXISTING — reuse fixtures
├── test_supervision_e2e.py        # EXISTING — story 7.3 tests (reference patterns)
└── test_full_workflow_e2e.py      # NEW — this story's tests
```

### What NOT To Do

- Do NOT create Jeedom API client fixtures (`jeedom_client`) — these tests mock `send_to_jeedom`, no real Jeedom needed
- Do NOT use `asyncio.sleep()` for timing — use `_wait_for()` exclusively
- Do NOT test wizard PHP flow — that's Level 4 manual acceptance (architecture.md line 432)
- Do NOT import or call actual PHP — daemon tests are pure Python
- Do NOT use `subprocess` to start the daemon — use `SIADaemon` directly with `on_start()`/`on_stop()`
- Do NOT add new dependencies — all tools are already available

### Previous Story Intelligence (10-2)

- Inline script approach works for client-side detection (not relevant here)
- All 1006+ Python tests passing before this story
- PHP syntax checks pass across all files
- Pattern: keep tasks focused, use existing test infrastructure

### References

- [Source: tests/level3/conftest.py] — E2E daemon factory, fixtures, helpers
- [Source: tests/level3/test_supervision_e2e.py] — Complete E2E test patterns (12 tests covering SM1 lifecycle)
- [Source: docs/design/supervision-design.md] — SM1 state machine spec
- [Source: docs/design/daemon-design.md] — SM2 alarm lifecycle
- [Source: _bmad-output/planning-artifacts/architecture.md#L366-443] — Testing strategy pyramid
- [Source: resources/siadc09d/daemon.py] — SIADaemon class, SM1State/SM2State enums

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
