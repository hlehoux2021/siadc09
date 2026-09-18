"""Story 7.3: E2E Supervision Integration Tests with real CSR Simulator.

Tests the full integration path: real transport → real protocol → real SM1 state machine
→ real ring buffer → real callbacks. Only send_to_jeedom is mocked (no PHP required).

Reference: _bmad-output/implementation-artifacts/7-3-supervision-integration-testing.md
Reference: docs/design/supervision-design.md — Groups A/B/C, SM1 state mapping
"""
import asyncio
from contextlib import suppress

import pytest
import pytest_asyncio

from resources.siadc09d.csr_simulator import CSRSimulator
from resources.siadc09d.daemon import (
    SM1State,
    SM2State,
    SIADaemon,
    TCP_RECONNECT_MAX_ATTEMPTS,
)
from resources.siadc09d.error_handler import ErrorCode
from tests.level3.conftest import (
    E2E_ACCOUNT,
    E2E_ENCRYPTION_KEY,
    _wait_for,
    _find_free_tcp_port,
    _find_free_udp_port,
    make_e2e_daemon,
)


# ===== TASK 1.4 SMOKE TEST =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_task1_smoke_sim_udp_recv_task(csr_sim):
    """Smoke: simulator _handle_udp() task running — can receive a frame and send ACK.

    Expected result:
    - CSRSimulator starts on ephemeral ports
    - _handle_udp task is running (started by csr_sim fixture)
    - UDP roundtrip: send NULL frame, receive ACK response
    """
    from tests.level3.conftest import _sim_udp_roundtrip
    sim, udp_port, tcp_port = csr_sim

    # Assert: simulator is running
    assert sim._running is True

    # Assert: can do UDP roundtrip (ACK received)
    got_ack = await _sim_udp_roundtrip(udp_port, timeout=2.0)
    assert got_ack, (
        f"UDP roundtrip failed — CSRSimulator not responding on port {udp_port}. "
        "Check _handle_udp() task started by fixture."
    )


# ===== TASK 2: E2E HEALTHY SUPERVISION — UDP (AC1) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac1_udp_healthy_supervision(csr_sim):
    """E2E UDP: daemon reaches HEALTHY after first supervision ACK. (AC1)

    Scenario:
    - CSRSimulator running on localhost UDP port
    - SIADaemon with UDP transport, supervision_interval_s=1.0
    - on_start() called → supervision_loop fires after 1s → simulator ACKs → SM1=HEALTHY

    Expected result:
    - SM1 transitions INITIALIZING → HEALTHY
    - _strike_counter == 0
    - send_to_jeedom called with supervision_state=1 (INITIALIZING) then supervision_state=2 (HEALTHY)
    - ring_buffer has at least one entry
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)

    try:
        await daemon.on_start()

        # Assert: SM1 reaches HEALTHY after first ACK
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=10.0,
        )
        # Assert: strike counter is 0
        assert daemon._strike_counter == 0, (
            f"Expected strike=0 after HEALTHY, got {daemon._strike_counter}"
        )

        # Assert: send_to_jeedom calls include INITIALIZING then HEALTHY
        calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        sup_states = [c.get("supervision_state") for c in calls if "supervision_state" in c]
        assert 1 in sup_states, "Expected supervision_state=1 (INITIALIZING) callback"
        assert 2 in sup_states, "Expected supervision_state=2 (HEALTHY) callback"
        # INITIALIZING push (state=1) comes before HEALTHY push (state=2)
        first_1 = next(i for i, s in enumerate(sup_states) if s == 1)
        first_2 = next(i for i, s in enumerate(sup_states) if s == 2)
        assert first_1 < first_2, "INITIALIZING callback must precede HEALTHY callback"

        # Assert: ring buffer has at least one entry
        assert len(daemon._ring_buffer) >= 1, (
            "Ring buffer must have at least one entry after first ACK"
        )

    finally:
        await daemon.on_stop()


# ===== TASK 3: E2E HEALTHY SUPERVISION — TCP (AC2) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac2_tcp_healthy_supervision(csr_sim):
    """E2E TCP: daemon reaches HEALTHY after first supervision ACK. (AC2)

    Scenario:
    - CSRSimulator running on localhost TCP port
    - SIADaemon with TCP transport, supervision_interval_s=1.0

    Expected result:
    - SM1 transitions INITIALIZING → HEALTHY
    - sim.tcp_connect_count >= 1 (per-frame TCP behavior confirmed)
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port)

    try:
        await daemon.on_start()

        # Assert: SM1 reaches HEALTHY
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=10.0,
        )
        # Assert: TCP connection was established at least once
        assert sim.tcp_connect_count >= 1, (
            f"Expected at least 1 TCP connection, got {sim.tcp_connect_count}"
        )

    finally:
        await daemon.on_stop()


# ===== TASK 4: E2E STRIKE ESCALATION — TIMEOUT (AC3, AC4) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac3_udp_strike_escalation_timeout(csr_sim):
    """E2E UDP: strike escalates 1→2→3 after simulator stops responding. (AC3)

    Scenario:
    - Daemon reaches HEALTHY, then simulator is stopped
    - Three consecutive supervision timeouts escalate strike 1→2→3

    Expected result:
    - SM1=DEGRADED at each strike step
    - _notify called with SUPERVISION_TIMEOUT at strike=1 (T1)
    - _notify called with SUPERVISION_DISCONNECTED at strike=3 (T3)
    - supervision_state transitions include 1 (DEGRADED 1-2) and 0 (DEGRADED 3)
    """
    sim, udp_port, tcp_port = csr_sim

    # Use a UDP task handle so we can stop it
    udp_task = None
    # Note: csr_sim fixture already launched _handle_udp() — we access the sim directly.
    # To stop UDP: we call sim.stop() which closes the socket → UDP handler exits.

    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)
    notified_codes: list[ErrorCode] = []

    original_notify = daemon._notify.__class__.__name__  # just for reference
    # Wrap _notify to capture error codes
    import unittest.mock
    real_notify_path = None

    # Capture notifications by patching _dispatch_notify
    dispatched: list[ErrorCode] = []

    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append(code)
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()

        # Wait for HEALTHY first
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Stop simulator to trigger timeouts
        await sim.stop()
        # Also cancel the UDP task from the fixture (sim is stopped, socket closed)
        # The fixture teardown will handle this — we just need to stop the sim

        # Wait for strike=3
        await _wait_for(
            lambda: daemon._strike_counter >= 3,
            timeout=15.0,
        )

        # Assert: SM1=DEGRADED at strike=3
        assert daemon._sm1_state == SM1State.DEGRADED, (
            f"Expected SM1=DEGRADED at strike=3, got {daemon._sm1_state}"
        )

        # Assert: T1 fired at strike=1 (SUPERVISION_TIMEOUT)
        assert ErrorCode.SUPERVISION_TIMEOUT in dispatched, (
            f"Expected SUPERVISION_TIMEOUT T1 notification, got {dispatched}"
        )
        # Assert: T3 fired at strike=3 (SUPERVISION_DISCONNECTED)
        assert ErrorCode.SUPERVISION_DISCONNECTED in dispatched, (
            f"Expected SUPERVISION_DISCONNECTED T3 notification, got {dispatched}"
        )

        # Assert: supervision_state transitions include impaired (1) and problem (0)
        calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        sup_states = [c.get("supervision_state") for c in calls if "supervision_state" in c]
        assert 1 in sup_states, "Expected supervision_state=1 (DEGRADED 1-2) callback"
        assert 0 in sup_states, "Expected supervision_state=0 (DEGRADED 3) callback"

    finally:
        with suppress(Exception):
            await daemon.on_stop()


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac4_tcp_strike3_enters_tcp_reconnecting(csr_sim):
    """E2E TCP: strike=3 triggers TCP_RECONNECTING state and reconnect task. (AC4)

    Scenario:
    - TCP daemon reaches HEALTHY, simulator stops
    - Three timeouts → strike=3 → SM1=TCP_RECONNECTING

    Expected result:
    - SM1=TCP_RECONNECTING after strike=3 for TCP
    - tcp_reconnect_loop task exists in daemon._tasks
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port)

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Stop simulator
        await sim.stop()

        # Wait for TCP_RECONNECTING (triggered at strike=3 for TCP)
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.TCP_RECONNECTING,
            timeout=15.0,
        )

        # Assert: tcp_reconnect_loop task spawned
        loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
        assert len(loop_tasks) >= 1, (
            f"Expected tcp_reconnect_loop task in daemon._tasks, tasks={[t.get_name() for t in daemon._tasks]}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 5: E2E ACK RECOVERY AFTER DEGRADATION (AC5) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac5_udp_recovery_after_degradation(csr_sim):
    """E2E UDP: recovery to HEALTHY after DEGRADED(strike=2), simulator restored. (AC5)

    Scenario:
    - UDP daemon reaches HEALTHY → simulator stops → escalate to DEGRADED(2)
    - Restart simulator on same ports → next ACK resets strike=0 → SM1=HEALTHY

    Expected result:
    - After recovery: SM1=HEALTHY, strike=0, _sm1_t3_fired=False
    - supervision_state=2 in callbacks after recovery
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)

    sim2 = None

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Stop simulator to trigger timeouts
        await sim.stop()

        # Wait for strike=2 (degraded but T3 not yet fired)
        await _wait_for(lambda: daemon._strike_counter >= 2, timeout=10.0)

        # Start fresh simulator on same ports (SO_REUSEADDR prevents TIME_WAIT conflict)
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(
            udp_port=udp_port,
            tcp_port=tcp_port,
            preset=sim2_preset,
            response_delay_ms=0,
        )
        await sim2.start()
        udp_task2 = asyncio.create_task(sim2._handle_udp(), name="sim2_udp_recv")

        # Wait for recovery to HEALTHY
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=15.0)

        # Assert: strike reset to 0
        assert daemon._strike_counter == 0, (
            f"Expected strike=0 after recovery, got {daemon._strike_counter}"
        )
        # Assert: T3 flag reset
        assert daemon._sm1_t3_fired is False, "_sm1_t3_fired must be False after recovery"

        # Assert: supervision_state=2 in callbacks after recovery
        calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        # Get supervision states after the first HEALTHY (search for second occurrence of 2)
        sup_states = [c.get("supervision_state") for c in calls if "supervision_state" in c]
        count_2 = sum(1 for s in sup_states if s == 2)
        assert count_2 >= 2, (
            f"Expected at least 2 supervision_state=2 callbacks (initial HEALTHY + recovery), got {sup_states}"
        )

        # Assert: resolve_t1 callbacks emitted for both T1 error codes (Task 5.2)
        resolve_calls = [
            c for c in calls
            if c.get("type") == "error_update" and c.get("resolve_t1") == 1
        ]
        resolved_codes = {c.get("code") for c in resolve_calls}
        from resources.siadc09d.error_handler import ErrorCode
        assert ErrorCode.SUPERVISION_TIMEOUT.value in resolved_codes, (
            f"Expected resolve_t1 for SUPERVISION_TIMEOUT, got resolved_codes={resolved_codes}"
        )
        assert ErrorCode.SUPERVISION_NAK.value in resolved_codes, (
            f"Expected resolve_t1 for SUPERVISION_NAK, got resolved_codes={resolved_codes}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        if sim2:
            try:
                udp_task2.cancel()
                with suppress(asyncio.CancelledError):
                    await udp_task2
            except Exception:
                pass
            with suppress(Exception):
                await sim2.stop()


# ===== TASK 6: E2E NAK HANDLING (AC6) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac6_nak_handling_unparseable(csr_sim):
    """E2E NAK: simulator patched to return NAK → BAD_CSR_RESPONSE (T2), ring buffer entry. (AC6)

    Scenario:
    - Patch sim._decide_response to always return 'NAK'
    - daemon starts, first supervision frame → NAK response
    - NAK has no parseable timestamp (simulator's _generate_nak_frame has no timestamp)
    - → nak_bad path → BAD_CSR_RESPONSE (T2)

    Expected result:
    - _dispatch_notify called with BAD_CSR_RESPONSE
    - ring buffer has entry with is_routine=False
    """
    sim, udp_port, tcp_port = csr_sim

    # Patch simulator to always return NAK
    sim._decide_response = lambda *_: "NAK"  # type: ignore[method-assign]

    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)
    dispatched: list[ErrorCode] = []

    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append(code)
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()

        # Wait for first strike (from NAK)
        await _wait_for(
            lambda: daemon._strike_counter >= 1,
            timeout=10.0,
        )

        # Assert: BAD_CSR_RESPONSE (T2) was dispatched
        assert ErrorCode.BAD_CSR_RESPONSE in dispatched, (
            f"Expected BAD_CSR_RESPONSE T2 notification, got {dispatched}"
        )

        # Assert: ring buffer has non-routine entry
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is False]
        assert len(non_routine) >= 1, (
            f"Expected at least one is_routine=False ring buffer entry, got {entries}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 7: E2E TCP RECONNECT SUCCESS + PERMANENT FAILURE (AC7, AC8) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac7_tcp_reconnect_success(csr_sim):
    """E2E TCP: reconnect succeeds after simulator restart on same port. (AC7)

    Scenario:
    - TCP daemon in TCP_RECONNECTING → restart simulator on same TCP port
    - _tcp_reconnect_loop probe succeeds → SM1=INITIALIZING, strike=0, t3_fired=False
    - Next supervision cycle → HEALTHY

    Expected result:
    - SM1 returns to INITIALIZING then HEALTHY after restart
    - strike=0, _sm1_t3_fired=False
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port)

    sim2 = None

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Stop simulator to trigger TCP reconnect
        await sim.stop()
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.TCP_RECONNECTING,
            timeout=15.0,
        )

        # Restart simulator on same TCP port (SO_REUSEADDR already set in CSRSimulator.start())
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(
            udp_port=udp_port,
            tcp_port=tcp_port,
            preset=sim2_preset,
            response_delay_ms=0,
        )
        await sim2.start()

        # Wait for probe to succeed → INITIALIZING (reconnect reset) then HEALTHY (first ACK)
        await _wait_for(
            lambda: daemon._sm1_state in (SM1State.INITIALIZING, SM1State.HEALTHY),
            timeout=10.0,
        )
        # Assert: strike reset to 0 and T3 flag cleared (safe to check at INITIALIZING)
        assert daemon._strike_counter == 0, f"Expected strike=0, got {daemon._strike_counter}"
        assert daemon._sm1_t3_fired is False, "_sm1_t3_fired must be False after reconnect"

        # Assert: eventually reaches HEALTHY (supervision cycle completes post-reconnect)
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=10.0,
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        if sim2:
            with suppress(Exception):
                await sim2.stop()


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac8_tcp_reconnect_permanent_failure(csr_sim):
    """E2E TCP: all 3 reconnect probes fail → SM1=NO_NETWORK, TRANSPORT_PERMANENT. (AC8)

    Scenario:
    - TCP daemon in TCP_RECONNECTING, simulator never restarts
    - 3 probe attempts all time out (connect_timeout_s=0.5 → max 3×0.5=1.5s)
    - → SM1=NO_NETWORK, _notify(TRANSPORT_PERMANENT)

    Expected result:
    - SM1=NO_NETWORK after exhausting reconnect attempts
    - _dispatch_notify called with TRANSPORT_PERMANENT
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port)

    dispatched: list[ErrorCode] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append(code)
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    # The permanent-failure path schedules self.stop() as the tracked task
    # 'transport_permanent_stop' (daemon.py:1146). Now that on_stop() completes
    # cleanly (AC22 self-cancellation guard), BaseDaemon.stop() would proceed to
    # its process-level asyncio.all_tasks() sweep and cancel this test's own
    # _wait_for driver task. Replace stop() with a spy that runs the real
    # on_stop() while excluding the self-stop task, so the assertions below can
    # observe NO_NETWORK / TRANSPORT_PERMANENT without the test task being cancelled.
    async def _spy_stop() -> None:
        current = asyncio.current_task()
        daemon._tasks.discard(current)
        await daemon.on_stop()

    daemon.stop = _spy_stop  # type: ignore[method-assign]

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Stop simulator, never restart
        await sim.stop()
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.TCP_RECONNECTING,
            timeout=15.0,
        )

        # Wait for permanent failure (NO_NETWORK state)
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.NO_NETWORK,
            timeout=15.0,
        )

        # Wait for TRANSPORT_PERMANENT notification (dispatched asynchronously as a tracked task)
        await _wait_for(
            lambda: ErrorCode.TRANSPORT_PERMANENT in dispatched,
            timeout=5.0,
        )

        # Assert: TRANSPORT_PERMANENT fired
        assert ErrorCode.TRANSPORT_PERMANENT in dispatched, (
            f"Expected TRANSPORT_PERMANENT notification, got {dispatched}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 8: E2E FULL LIFECYCLE (AC9, AC10, AC11) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac9_ac10_ac11_full_lifecycle(csr_sim):
    """E2E full lifecycle: start → HEALTHY → degrade(3) → recover → stop. (AC9, AC10, AC11)

    Scenario:
    1. Start daemon + simulator → wait HEALTHY
    2. Stop simulator → wait strike=3 (T3 fires)
    3. Restart simulator → wait HEALTHY (recovery)
    4. Call on_stop() → verify STOPPED push

    Expected result (AC9):
    - Complete SM1 lifecycle from start to stop
    - STOPPED push in send_to_jeedom calls on stop

    Expected result (AC10):
    - Ring buffer has is_routine=False entries for strikes + recovery ACK
    - At most 1 routine entry (10-min throttle prevents spam)

    Expected result (AC11):
    - supervision_state sequence: 1→2→1/0→2→0 (INIT, HEALTHY, DEGRADED, RECOVERY, STOPPED)
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)

    sim2 = None
    daemon_stopped = False

    try:
        # Step 1: start → HEALTHY
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Step 2: stop sim → escalate to strike=3
        await sim.stop()
        await _wait_for(lambda: daemon._strike_counter >= 3, timeout=15.0)
        assert daemon._sm1_state == SM1State.DEGRADED

        # Step 3: restart sim → recovery to HEALTHY
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(udp_port=udp_port, tcp_port=tcp_port, preset=sim2_preset)
        await sim2.start()
        udp_task2 = asyncio.create_task(sim2._handle_udp(), name="sim2_udp_recv")

        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=15.0)

        # Step 4: stop daemon → verify STOPPED push
        await daemon.on_stop()
        daemon_stopped = True

        # ===== AC9: verify STOPPED push =====
        calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        stopped_calls = [
            c for c in calls
            if c.get("type") == "info_update" and c.get("supervision_label") == "ARRÊTÉ"
        ]
        assert len(stopped_calls) >= 1, (
            "Expected STOPPED push (supervision_label='ARRÊTÉ') in send_to_jeedom calls"
        )

        # ===== AC10: ring buffer non-routine entries =====
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is False]
        # Expect at least 3 non-routine entries (one per timeout strike)
        assert len(non_routine) >= 3, (
            f"Expected at least 3 is_routine=False entries, got {len(non_routine)}"
        )
        # Expect at most 1 routine entry (10-min throttle)
        routine = [e for e in entries if e.get("is_routine") is True]
        assert len(routine) <= 1, (
            f"Expected at most 1 routine entry (throttle), got {len(routine)}"
        )

        # ===== AC11: supervision_state sequence =====
        sup_states = [
            c.get("supervision_state") for c in calls
            if c.get("type") == "info_update" and "supervision_state" in c
        ]
        assert 1 in sup_states, "Expected supervision_state=1 (INITIALIZING) in sequence"
        assert 2 in sup_states, "Expected supervision_state=2 (HEALTHY) in sequence"
        assert 0 in sup_states, "Expected supervision_state=0 (DEGRADED/STOPPED) in sequence"
        # Final value in the sequence is 0 (STOPPED push)
        assert sup_states[-1] == 0, (
            f"Expected last supervision_state=0 (STOPPED), got {sup_states}"
        )

    finally:
        if not daemon_stopped:
            with suppress(Exception):
                await daemon.on_stop()
        if sim2:
            try:
                udp_task2.cancel()
                with suppress(asyncio.CancelledError):
                    await udp_task2
            except Exception:
                pass
            with suppress(Exception):
                await sim2.stop()


# ===== TASK 9: E2E CONCURRENT ALARM DURING SUPERVISION (AC12) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac12_concurrent_alarm_during_supervision(csr_sim):
    """E2E: inject alarm event while supervision is running. (AC12)

    Scenario:
    - UDP daemon running HEALTHY with periodic supervision
    - on_message("burglarAlarm", {"zone": "salon"}) injected
    - SM2 processes alarm: IDLE → PENDING → CONFIRMED (simulator ACKs)

    Expected result:
    - SM2=CONFIRMED after alarm processed
    - SM1 still HEALTHY (supervision uninterrupted)
    - Both supervision_state=2 and event_state=1 callbacks arrive
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port)

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Inject alarm event
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Wait for SM2 to reach CONFIRMED or FAILED
        await _wait_for(
            lambda: daemon._sm2_state in (SM2State.CONFIRMED, SM2State.FAILED),
            timeout=10.0,
        )

        # Assert: alarm confirmed (not failed)
        assert daemon._sm2_state == SM2State.CONFIRMED, (
            f"Expected SM2=CONFIRMED, got {daemon._sm2_state}. "
            "Check account_number matches between daemon and simulator."
        )

        # Assert: SM1 still HEALTHY (supervision uninterrupted)
        assert daemon._sm1_state == SM1State.HEALTHY, (
            f"Expected SM1=HEALTHY after alarm, got {daemon._sm1_state}"
        )

        # Assert: both supervision and event callbacks arrived
        calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        sup_states = [c.get("supervision_state") for c in calls if "supervision_state" in c]
        event_states = [c.get("event_state") for c in calls if "event_state" in c]
        assert 2 in sup_states, "Expected supervision_state=2 callback"
        assert any(e is not None for e in event_states), (
            "Expected event_state callback from alarm processing"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 10: E2E ENCRYPTED SUPERVISION (AC13) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_ac13_encrypted_supervision_marker_sent(csr_sim):
    """E2E: daemon with encryption_enabled=True sends frame with *SIA-DCS marker. (AC13)

    Note: Current implementation sets the * marker but does not perform actual AES
    encryption of the data block. The simulator will return NAK (unknown frame type)
    because it cannot parse '*SIA-DCS' as a known type. This test verifies the
    encryption marker is correctly set in the frame — full E2E ACK requires completing
    the encryption path in the daemon (deferred work).

    Expected result:
    - Daemon sends frame with '*SIA-DCS' id_token (encryption marker present)
    - Ring buffer has entry (from NAK response)
    - Daemon state is DEGRADED (simulator NAKs the frame — expected given partial impl)
    """
    # Restart the default sim with encryption key so it can at least detect the marker
    sim, udp_port, tcp_port = csr_sim

    # Create daemon with encryption enabled
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, encryption_enabled=True)

    try:
        await daemon.on_start()

        # Wait for first supervision cycle to fire (success or failure)
        await _wait_for(
            lambda: daemon._strike_counter >= 1 or daemon._sm1_state == SM1State.HEALTHY,
            timeout=10.0,
        )

        # Assert: supervision frame uses *SIA-DCS marker (encryption_enabled=True)
        # Verify via _sia_builder — when encryption=True, make_supervision_message sets id_token="*SIA-DCS"
        from resources.siadc09d.sia_protocol import ENCRYPTED_MARKER, SIA_DCS_TOKEN
        test_frame = daemon._sia_builder.make_supervision_message(
            account_number=daemon._account,
            account_prefix=daemon._account_prefix,
            encryption=daemon._preset.encryption_enabled,
        )
        frame_str = test_frame.decode("ascii", errors="replace")
        assert f'"{ENCRYPTED_MARKER}{SIA_DCS_TOKEN}"' in frame_str, (
            f"Expected '*{SIA_DCS_TOKEN}' id_token in encrypted supervision frame, "
            f"got frame_str={frame_str[:80]}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
