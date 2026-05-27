# Story 7.3: Supervision Integration Testing (End-to-End with CSR Simulator)

Status: done

## Story

As a daemon architect,
I want end-to-end supervision tests using the real CSR simulator subprocess,
So that SM1 state transitions, error notifications, and IPC callbacks are verified across the full stack (transport → protocol → state machine → callbacks).

## Acceptance Criteria

1. **E2E healthy supervision cycle (UDP)** — Start daemon with real `SIAUDPTransport` against a running `CSRSimulator` on localhost. After one supervision interval fires, SM1 transitions INITIALIZING → HEALTHY. Verify: `supervision_state=2` callback emitted, `_strike_counter==0`, ring buffer has at least one entry.

2. **E2E healthy supervision cycle (TCP)** — Same as AC1 but over TCP transport. Verify: SM1=HEALTHY after first ACK. Verify per-frame TCP behavior by asserting `sim.tcp_connect_count >= 1` (instrumented counter on simulator).

3. **E2E strike escalation via timeout (UDP)** — Start daemon against a running simulator, then stop the simulator. Three consecutive supervision timeouts → strike escalates 1→2→3. Verify: SM1=DEGRADED at each step, T1 fires at strike=1, T3 fires at strike=3, `supervision_state` transitions 1→1→0.

4. **E2E strike escalation via timeout (TCP)** — Same as AC3 but over TCP. After strike=3: verify TCP_RECONNECTING state entered and `_tcp_reconnect_loop` task spawned.

5. **E2E ACK recovery after degradation** — After reaching DEGRADED(strike=2), restore simulator reachability. Next supervision cycle ACKs → strike resets to 0, SM1=HEALTHY, `_sm1_t3_fired=False`, `supervision_state=2`. Verify T1 `resolve_t1` callback emitted.

6. **E2E NAK handling (unparseable)** — Patch simulator `_decide_response` to always return `'NAK'`. Verify: strike increments, `_notify(BAD_CSR_RESPONSE)` fires (T2), ring buffer entry with `is_routine=False`.

7. **E2E TCP reconnect success** — Daemon in TCP_RECONNECTING → restart simulator on same port (with `SO_REUSEADDR`). `_tcp_reconnect_loop()` probe succeeds → SM1=INITIALIZING, strike=0, `_sm1_t3_fired=False`. Next supervision cycle → HEALTHY.

8. **E2E TCP reconnect permanent failure** — Daemon in TCP_RECONNECTING, simulator never restarts. After `TCP_RECONNECT_MAX_ATTEMPTS` (3) probes time out → SM1=NO_NETWORK, `_notify(TRANSPORT_PERMANENT)` fired, daemon stops supervision.

9. **E2E full lifecycle** — Start daemon → wait for HEALTHY → stop simulator → escalate to DEGRADED(3)/T3 → restart simulator → recovery to HEALTHY → stop daemon → verify `on_stop()` STOPPED push. Complete E2E proving SM1 lifecycle from start to stop.

10. **E2E ring buffer correct over full lifecycle** — After AC9 scenario, inspect ring buffer: non-routine entries (timeout at strikes 1,2,3 and recovery ACK) all present as individual `is_routine=False` entries. Routine ACK entries throttled (at most 1 in first 10-min window).

11. **E2E INFO callbacks correct** — Capture all `send_to_jeedom` calls during AC9. Verify sequence: INITIALIZING push → supervision_state=2 (HEALTHY) → supervision_state=1/0 (degrading) → supervision_state=2 (recovery) → ARRÊTÉ (stop).

12. **E2E concurrent alarm during supervision** — While supervision is running (HEALTHY), inject an alarm event via `on_message()`. Verify: EVENT processed (SM2=PENDING→CONFIRMED via simulator ACK), supervision continues uninterrupted, both callbacks arrive.

13. **E2E encrypted supervision cycle** — Start daemon with `encryption_enabled=True` and matching key in both daemon preset and simulator preset. Verify: `*NULL` frame sent, simulator decrypts and ACKs, SM1=HEALTHY.

14. **All existing tests pass** — No regressions. Current baseline: all levels combined + 1 pre-existing failure (`tests/level2/test_sm1_extended_suite.py::test_tc13_strike_timing_precision`). If test_tc13 now passes, that's acceptable. Any NEW failures are regressions.

## Tasks / Subtasks

### Task 0: Fix two production bugs discovered during E2E design (prerequisite)

- [x] **0.1** In `daemon.py:1832`: change `interval: int = int(getattr(...))` to `interval: float = float(getattr(self._preset, 'supervision_interval_s', SUPERVISION_INTERVAL_S))`. The `int()` cast truncates sub-second intervals to 0, causing infinite spin. This is a trivial bug fix — `asyncio.sleep(0)` yields immediately without delay.
- [x] **0.2** In `daemon.py:1068`: replace hardcoded `TCP_CONNECT_TIMEOUT_S` in the `asyncio.wait_for()` call with `self._preset.connect_timeout_s`. The module-level constant (10s) makes TCP reconnect tests impractically slow. The preset already carries this value and `make_daemon_preset` sets it to `0.5` for tests.
- [x] **0.3** Add regression test in `tests/level2/test_tcp_reconnect_integration.py`: mock `asyncio.wait_for` (or inspect call args on `asyncio.open_connection` wrapper), call `_tcp_reconnect_loop()`, assert the timeout passed to `wait_for` equals `daemon._preset.connect_timeout_s` (0.5 in test preset), NOT the old hardcoded 10s constant.
- [x] **0.4** Run `python3 -m pytest tests/level1/ tests/level2/ -q --tb=short` to verify neither fix introduces regressions.

### Task 1: Create Level 3 test infrastructure (AC1–AC14 foundation)

- [x] **1.1** Create `tests/level3/` directory and `tests/level3/__init__.py`.
- [x] **1.2** Create `tests/level3/conftest.py` with:
  - Port-finding helpers:
    ```python
    def _find_free_udp_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def _find_free_tcp_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
    ```
  - `@pytest.fixture` `csr_sim` — allocates ephemeral UDP+TCP ports, creates `CSRSimulator`, starts it, launches `asyncio.create_task(sim._handle_udp())` as `_udp_task`, yields `(sim, udp_port, tcp_port)`, on teardown: cancels `_udp_task`, awaits it (suppress CancelledError), then calls `await sim.stop()`.
  - `@pytest.fixture` `make_e2e_daemon` — factory function that accepts `transport: str` and the simulator fixture. Constructs `SIADaemon` with `CSRPreset` pointing at simulator ports. Sets `supervision_interval_s=1.0`, `reconnect_delay_s=0.05`, `receive_timeout_s=0.5`, `connect_timeout_s=0.5`. Applies `daemon.send_to_jeedom = AsyncMock()`. On teardown (yield pattern): calls `await daemon.on_stop()` wrapped in `suppress(Exception)` to guarantee cleanup regardless of test outcome.
  - `_wait_for(predicate, timeout=5.0, poll_interval=0.02)` async helper for CI-safe polling:
    ```python
    async def _wait_for(predicate, *, timeout=5.0, poll_interval=0.02):
        deadline = asyncio.get_event_loop().time() + timeout
        while not predicate():
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"Condition not met within {timeout}s")
            await asyncio.sleep(poll_interval)
    ```
- [x] **1.3** Add pytest mark `@pytest.mark.level3` to all Level 3 tests. Register marker in `pytest.ini` or `pyproject.toml`.
- [x] **1.4** Smoke test: start simulator, verify it can receive a UDP datagram and send ACK back (send raw NULL frame manually via socket, check ACK received). This validates the `_handle_udp()` task lifecycle.
- [x] **1.5** Add `sim.tcp_connect_count = 0` instrumentation: patch `CSRSimulator._handle_tcp_client` in the fixture to increment a counter on entry (for AC2 verification).

### Task 2: E2E healthy supervision — UDP (AC1)

- [x] **2.1** Test: start simulator, create daemon with `transport="UDP"`, call `on_start()`, use `_wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=5.0)`. Verify: `_strike_counter==0`.
- [x] **2.2** Verify `send_to_jeedom` called with INITIALIZING push first (`supervision_state=1`), then `supervision_state=2` callback from `_send_callback` path.
- [x] **2.3** Verify ring buffer has at least one entry.

### Task 3: E2E healthy supervision — TCP (AC2)

- [x] **3.1** Same as Task 2 but with `transport="TCP"`. Use `_wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY)`.
- [x] **3.2** Verify `sim.tcp_connect_count >= 1` (per-frame TCP behavior confirmed).

### Task 4: E2E strike escalation — timeout (AC3, AC4)

- [x] **4.1** Test (UDP): start daemon with simulator running. Wait for HEALTHY. Stop simulator (`await sim.stop()` + cancel `_udp_task`). Use `_wait_for(lambda: daemon._strike_counter >= 3, timeout=10.0)`. Verify: SM1=DEGRADED, `_notify` called with SUPERVISION_TIMEOUT (strike=1) and SUPERVISION_DISCONNECTED (strike=3).
- [x] **4.2** Verify `supervision_state` callback sequence includes transitions 1→1→0.
- [x] **4.3** Test (TCP): same flow, but verify SM1=TCP_RECONNECTING after strike=3 and `any(t.get_name() == "tcp_reconnect_loop" for t in daemon._tasks)`.

### Task 5: E2E ACK recovery after degradation (AC5)

- [x] **5.1** Start daemon with simulator running. Wait for HEALTHY. Stop simulator. Use `_wait_for(lambda: daemon._strike_counter >= 2)`. Restart simulator (new instance on same ports with `SO_REUSEADDR`, launch `_handle_udp` task). Use `_wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY)`. Verify: strike=0, `supervision_state=2` in callbacks.
- [x] **5.2** Verify `resolve_t1` callback emitted (both SUPERVISION_TIMEOUT and SUPERVISION_NAK codes).
- [x] **5.3** Verify `_sm1_t3_fired==False`.

### Task 6: E2E NAK handling (AC6)

- [x] **6.1** Start simulator, patch `sim._decide_response = lambda *_: 'NAK'` to force all responses as NAK. Start daemon. Use `_wait_for(lambda: daemon._strike_counter >= 1)`. Verify: `_notify` called with `BAD_CSR_RESPONSE` (the simulator's `_generate_nak_frame` produces a NAK without parseable timestamp → T2 path).
- [x] **6.2** Verify ring buffer has entry with `is_routine=False`.

### Task 7: E2E TCP reconnect success + permanent failure (AC7, AC8)

- [x] **7.1** Test TCP reconnect success: start daemon on TCP with simulator. Wait for HEALTHY. Stop simulator. `_wait_for(SM1==TCP_RECONNECTING)`. Start new simulator on same TCP port (pass `reuse_address=True` to `asyncio.start_server` — add this via monkey-patch on `CSRSimulator.start` or pass as constructor param). `_wait_for(SM1==INITIALIZING or SM1==HEALTHY)`. Verify: strike=0, t3_fired=False.
- [x] **7.2** Test TCP permanent failure: same setup but never restart simulator. `_wait_for(SM1==NO_NETWORK, timeout=10.0)`. Verify `_notify` called with TRANSPORT_PERMANENT.

### Task 8: E2E full lifecycle test (AC9, AC10, AC11)

- [x] **8.1** Single test:
  1. Start simulator + daemon → `_wait_for(HEALTHY)`
  2. Stop simulator → `_wait_for(_strike_counter >= 3)` (T3 fires)
  3. Restart simulator → `_wait_for(HEALTHY)` (recovery)
  4. Call `on_stop()` → verify STOPPED push in `send_to_jeedom` calls
- [x] **8.2** Inspect ring buffer (AC10): count entries with `is_routine=False` — expect at least 3 (one per timeout strike) + 1 (recovery ACK). Verify routine entries are NOT one per supervision cycle.
- [x] **8.3** Inspect `send_to_jeedom.call_args_list` (AC11): extract `supervision_state` values, verify the ordered sequence includes `1` (INITIALIZING) → `2` (HEALTHY) → `1`/`0` (degrading) → `2` (recovery) → then final STOPPED push with `0`.

### Task 9: E2E concurrent alarm during supervision (AC12)

- [x] **9.1** Start daemon in HEALTHY state. Call `await daemon.on_message("burglarAlarm", {"zone": "salon"})`. `_wait_for(lambda: daemon._sm2_state == SM2State.CONFIRMED, timeout=5.0)`. Verify: SM1 still HEALTHY, supervision callbacks still flowing.
- [x] **9.2** Ensure daemon preset and simulator preset use the SAME `account_number` (e.g., `'001234'`). A mismatch causes simulator to NAK the alarm frame → SM2=FAILED instead of CONFIRMED.

### Task 10: E2E encrypted supervision (AC13)

- [x] **10.1** Create fixture variant with `encryption_enabled=True` and `encryption_key=bytes.fromhex('0123456789ABCDEF0123456789ABCDEF')` in both `CSRPreset` (daemon) and `CSRSimulatorPreset` (simulator). Start daemon. `_wait_for(HEALTHY)`. Verify: daemon sent `*NULL` frame type (check ring buffer or send_to_jeedom call content).

### Task 11: Full suite regression (AC14)

- [x] **11.1** Run `python3 -m pytest tests/ -q --tb=short` — verify no regressions from Task 0 fixes + new Level 3 tests.
- [x] **11.2** Verify Level 3 tests can be excluded via `pytest -m "not level3"` for fast CI.

## Dev Notes

### CRITICAL: Two Production Bug Fixes Required (Task 0)

**Bug 1: `_supervision_loop()` casts interval to `int` (daemon.py:1832):**
```python
interval: int = int(getattr(self._preset, 'supervision_interval_s', SUPERVISION_INTERVAL_S))
```
`int(0.5) == 0` → `asyncio.sleep(0)` → infinite spin. Fix: change to `float(...)`. This affects any preset with sub-second supervision intervals. For Level 3 tests with `supervision_interval_s=1.0` this wouldn't trigger, but it's still a latent bug that must be fixed (production presets could have fractional intervals).

**Bug 2: `_tcp_reconnect_loop()` uses hardcoded 10s timeout (daemon.py:1068):**
```python
await asyncio.wait_for(
    asyncio.open_connection(self._preset.host, self._preset.port),
    timeout=TCP_CONNECT_TIMEOUT_S,  # 10 seconds!
)
```
The `CSRPreset.connect_timeout_s` field exists for this purpose. Fix: replace `TCP_CONNECT_TIMEOUT_S` with `self._preset.connect_timeout_s`. Without this, TCP reconnect tests take 3×10s=30s instead of 3×0.5s=1.5s.

### CSRSimulator `_handle_udp()` — MANDATORY Task Lifecycle Management

`CSRSimulator.start()` binds sockets and starts TCP server but does **NOT** start the UDP recv loop. The fixture **MUST** explicitly:
1. `_udp_task = asyncio.create_task(sim._handle_udp())` after `await sim.start()`
2. On teardown: `_udp_task.cancel()` then `await _udp_task` (suppress CancelledError), THEN `await sim.stop()`

The `_handle_udp()` method uses `loop.run_in_executor(None, sock.recvfrom, 1024)` — blocking I/O in a thread. When `sim.stop()` closes the socket, the executor thread gets an OSError and the coroutine exits. Ordering matters: cancel the task FIRST (so it stops looping), then close the socket (which unblocks the executor thread).

### Timing Strategy — Poll-With-Timeout (NO Fixed Sleeps)

All state assertions MUST use the `_wait_for(predicate, timeout, poll_interval)` helper. Never use fixed `asyncio.sleep(N)` for "wait until state reached" — CI runners have variable scheduling latency.

With `supervision_interval_s=1.0` and `receive_timeout_s=0.5`:
- One supervision cycle: ~1.5s (1s interval + 0.5s timeout on failure, or ~1s on success)
- Full strike=3 escalation: ~4.5s (3 × 1.5s)
- TCP reconnect attempts: 3 × (0.05s delay + 0.5s timeout) = ~1.65s
- Full lifecycle test: ~15s with safety margins
- All timeouts in `_wait_for()`: use 10s minimum (5× expected) for CI safety

### Level 3 Test Classification

Project `.claude/rules/testing.md` defines Level 3 as "live Jeedom required." This story redefines Level 3 for this project as "E2E with real subprocess (CSR simulator) but no Jeedom." The `send_to_jeedom` callback remains mocked. Mark tests with `@pytest.mark.level3` so they can be excluded from fast CI via `pytest -m "not level3"`.

### Port Isolation

- Level 3 tests use `_find_free_udp_port()` and `_find_free_tcp_port()` for ephemeral port allocation (no hardcoded ports).
- Do NOT use the `csr_simulator_instance` fixture from `tests/conftest.py` — it uses hardcoded ports 10001/5000 which conflict with parallel execution.
- For simulator restart tests (AC5, AC7): create a NEW simulator instance on the same port. TCP `asyncio.start_server` needs `reuse_address=True` to avoid TIME_WAIT conflicts.

### Callback Capture Pattern

Use `daemon.send_to_jeedom = AsyncMock()` exclusively. Inspect `send_to_jeedom.call_args_list` for all assertions. Both `on_start()` direct calls and `_send_callback()` routed calls are captured by the same mock (since `_send_callback` calls `self.send_to_jeedom` internally).

### Timeout Simulation Strategy

For triggering supervision timeouts, **stop a running simulator** (not "point at unreachable port"):
- Stopping a previously-connected simulator guarantees true timeout behavior on all platforms
- Pointing at a never-bound port triggers platform-specific ICMP "port unreachable" on Linux (immediate error instead of timeout), causing rapid strike escalation with unpredictable timing
- For TCP: connection refused (from stopped sim) is caught as `SIATransportError` → treated as timeout

### NAK Testing Strategy

The simulator's `_generate_nak_frame()` produces a NAK without a parseable timestamp (no CSR time embedded). This means ALL NAKs from the simulator take the "unparseable" path → `BAD_CSR_RESPONSE` (T2). Testing the "parseable NAK with timestamp" path (SUPERVISION_NAK, T1) is not feasible with the current simulator without modification. AC6 tests only the unparseable NAK → T2 path. Parseable NAK testing is already covered at Level 2 (Story 7.1, test 7.9) where `parse_nak_timestamp()` is called with crafted bytes.

### Ring Buffer Assertion Strategy

With `supervision_interval_s=1.0`, the 10-minute throttle means at most 1 routine ACK entry appears per test run (the first-ever routine entry bypasses throttle). Focus ring buffer assertions on:
- Count of `is_routine=False` entries = expected strike/recovery events
- Absence of routine entry spam (at most 1 routine entry in buffer)

Access: `entries = list(daemon._ring_buffer._buffer)` (deque, newest first).

### Account Number Consistency

Both `CSRPreset` (daemon) and `CSRSimulatorPreset` (simulator) must use the SAME account_number. The daemon's `_account` is set from the preset. The simulator's `_parse_received_message` + `_decide_response` uses frame type (not account) for ACK/NAK routing, so a mismatch won't cause NAK. BUT for alarm frames, a mismatch in frame format could trigger NAK. Use `'001234'` consistently in both.

### What Already Exists (DO NOT RE-IMPLEMENT)

| Component | File | Status |
|-----------|------|--------|
| `CSRSimulator` | `resources/siadc09d/csr_simulator.py` | ✅ Complete (UDP+TCP, ACK/NAK) |
| `SIAUDPTransport` | `resources/siadc09d/sia_transport.py:173` | ✅ Complete |
| `SIATCPTransport` | `resources/siadc09d/sia_transport.py:282` | ✅ Complete |
| `SIADaemon.on_start()` | `resources/siadc09d/daemon.py:1910` | ✅ Complete |
| `SIADaemon.on_stop()` | `resources/siadc09d/daemon.py:1960` | ✅ Complete |
| `_send_supervision()` | `resources/siadc09d/daemon.py:768` | ✅ Complete |
| `_tcp_reconnect_loop()` | `resources/siadc09d/daemon.py:1028` | ✅ Complete |
| `_queue_consumer()` | `resources/siadc09d/daemon.py:1717` | ✅ Complete |
| `_log_sm1_supervision()` | `resources/siadc09d/daemon.py:1109` | ✅ Complete |
| Level 2 supervision | `tests/level2/test_supervision_loop_integration.py` | ✅ 11 tests |
| Level 2 TCP reconnect | `tests/level2/test_tcp_reconnect_integration.py` | ✅ 21 tests |

### Level 3 Difference from Level 2

Level 2 mocks `_notify`, `_update_info_commands`, `_log_sm1_supervision`, and the transport. Level 3 runs ALL internal methods for real — only `send_to_jeedom` is mocked (no PHP). This exercises the complete integration path: real frame construction → real UDP/TCP send → real simulator response → real ACK parsing → real state transition → real ring buffer push → real callback dispatch.

### Deferred Work (do NOT fix in 7.3)

- D-2: SM2 elapsed_ms always 0
- D-5: prev_strike misreputed at NAK cap
- D-6: _update_info_commands None-filter
- D-7: asyncio.sleep(0) in gate tests
- D-8: Asymmetric guard strategies

### File Locations

```
Modified files (Story 7.3 — Task 0 only):
  resources/siadc09d/daemon.py        ← int→float cast fix (line 1832) + TCP timeout fix (line 1068)

New files (Story 7.3):
  tests/level3/__init__.py                           ← package marker
  tests/level3/conftest.py                           ← CSR simulator fixtures + E2E daemon factory + _wait_for helper
  tests/level3/test_supervision_e2e.py               ← all E2E supervision integration tests (AC1-AC13)
```

### CSR Simulator Behavior Reference

| Daemon sends | Simulator receives | Simulator responds | Notes |
|---|---|---|---|
| NULL frame (plaintext) | Parses type="NULL" | ACK (echo seq) | Normal supervision |
| NULL frame (encrypted) | Decrypts → type="*NULL" | ACK (encrypted) | Encrypted supervision (AC13) |
| ALARM frame | Parses type="ALARM" | ACK (echo seq) | Alarm confirmation (AC12) |
| Any frame (patched `_decide_response`) | N/A | NAK | Forces NAK path (AC6) |
| Frame to stopped sim | No response | — (timeout) | Timeout path (AC3-5) |
| TCP to stopped sim | Connection refused | — (SIATransportError) | TCP drop/timeout (AC4, AC7-8) |

### Timing Budget for CI

| Scenario | Estimated time |
|---|---|
| Single healthy cycle (AC1/2/13) | ~2s |
| Full strike escalation (AC3/4) | ~6s |
| Recovery after degradation (AC5) | ~8s |
| TCP reconnect success (AC7) | ~8s |
| TCP permanent failure (AC8) | ~5s |
| Full lifecycle (AC9) | ~20s |
| Concurrent alarm (AC12) | ~3s |
| **Total Level 3 suite** | **~60s** |

### References

- [Source: docs/design/supervision-design.md — Groups A/B/C, SM1 state mapping, testing strategy table]
- [Source: docs/design/daemon-design.md — Task 1.1 (on_start), Task 1.11 (on_stop), Task 4 (TCP reconnect)]
- [Source: resources/siadc09d/csr_simulator.py — CSRSimulator class, _decide_response(), _handle_udp(), _handle_tcp_client()]
- [Source: resources/siadc09d/sia_transport.py — SIATransportResult TypedDict, SIAUDPTransport, SIATCPTransport]
- [Source: resources/siadc09d/daemon.py:768 — _send_supervision() full path]
- [Source: resources/siadc09d/daemon.py:1028 — _tcp_reconnect_loop() implementation]
- [Source: resources/siadc09d/daemon.py:1832 — _supervision_loop() interval cast BUG]
- [Source: resources/siadc09d/daemon.py:1068 — _tcp_reconnect_loop() timeout constant BUG]
- [Source: resources/siadc09d/daemon.py:1910 — on_start() with transport creation]
- [Source: tests/level2/test_supervision_loop_integration.py — Level 2 patterns (mocked transport)]
- [Source: tests/level2/test_tcp_reconnect_integration.py — Level 2 TCP patterns]
- [Source: tests/conftest.py — make_daemon_preset(), CSRSimulator fixtures (DO NOT USE for Level 3)]
- [Source: _bmad-output/implementation-artifacts/7-1-supervision-loop-strike-management-info-updates.md — Story 7.1 learnings]
- [Source: _bmad-output/implementation-artifacts/7-2-tcp-stall-detection-reconnect-ring-buffer-logging.md — Story 7.2 learnings]

### Review Findings

- [x] [Review][Decision] `on_stop()` not idempotent — resolved: Option A (test-only fix via `daemon_stopped` flag) [tests/level3/test_supervision_e2e.py]
- [x] [Review][Patch] `asyncio.get_event_loop()` deprecated — replaced with `asyncio.get_running_loop()` in `_wait_for` and `_sim_udp_roundtrip` [tests/level3/conftest.py]
- [x] [Review][Patch] AC5 missing `resolve_t1` assertion (Task 5.2) — added assertion for both SUPERVISION_TIMEOUT and SUPERVISION_NAK resolve codes [tests/level3/test_supervision_e2e.py]
- [x] [Review][Patch] AC9/AC10/AC11 double `on_stop()` in finally block — fixed with `daemon_stopped` flag [tests/level3/test_supervision_e2e.py]
- [x] [Review][Patch] AC7 missing final HEALTHY assertion — added second `_wait_for(HEALTHY)` after INITIALIZING [tests/level3/test_supervision_e2e.py]
- [x] [Review][Patch] `make_e2e_daemon` encryption: builder `crc_format` now uses `preset.crc_format` instead of hardcoded `"SIA"` [tests/level3/conftest.py]
- [x] [Review][Defer] AC3 no per-strike intermediate assertion [tests/level3/test_supervision_e2e.py:155] — deferred, pre-existing
- [x] [Review][Defer] AC13 sim missing encryption key — partial E2E, documented limitation [tests/level3/test_supervision_e2e.py:708] — deferred, pre-existing
- [x] [Review][Defer] PHP `cron5()` restart sequencing concern — pre-existing, not introduced by 7-3 [core/class/siaDC09.class.php] — deferred, pre-existing
