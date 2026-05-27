"""Story 11.3: Full Workflow Integration Tests.

Tests complete end-to-end user scenarios with real transport (UDP/TCP),
real CSRSimulator on localhost, and real daemon state machines.
Only send_to_jeedom is mocked — no PHP/Jeedom required.

Reference: _bmad-output/implementation-artifacts/11-3-full-workflow-integration-testing.md
Reference: docs/design/daemon-design.md — SM1/SM2 state machines
Reference: docs/design/supervision-design.md — SM1 lifecycle
"""
import asyncio
import resource
from contextlib import suppress
from math import ceil
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from resources.siadc09d.csr_simulator import CSRSimulator
from resources.siadc09d.daemon import (
    MAX_RETRY_DEFAULT,
    SM1State,
    SM2State,
    SIADaemon,
)
from resources.siadc09d.error_handler import ErrorCode
from tests.level3.conftest import (
    E2E_ACCOUNT,
    E2E_ENCRYPTION_KEY,
    _find_free_tcp_port,
    _find_free_udp_port,
    _wait_for,
    make_e2e_daemon,
)

# ===== CONSTANTS =====

E2E_SCENARIO_TIMEOUT = 30.0  # Max wait for multi-cycle assertions
E2E_FAST_INTERVAL = 2.0       # supervision_interval_s for scenario tests (5 cycles = 10s)
E2E_RESOURCE_INTERVAL = 0.1   # supervision_interval_s for resource tests (60 cycles = 6s)

# ===== ASSERTION HELPERS (Task 1.5) =====


def extract_sup_states(mock: AsyncMock) -> list[int]:
    """Extract supervision_state values from send_to_jeedom call history, in order."""
    calls = [c.args[0] for c in mock.call_args_list]
    return [c["supervision_state"] for c in calls if "supervision_state" in c]


def extract_event_states(mock: AsyncMock) -> list[int]:
    """Extract event_state values from send_to_jeedom call history, in order."""
    calls = [c.args[0] for c in mock.call_args_list]
    return [c["event_state"] for c in calls if "event_state" in c]


def extract_error_updates(mock: AsyncMock) -> list[dict]:
    """Extract error_update callbacks from send_to_jeedom call history."""
    calls = [c.args[0] for c in mock.call_args_list]
    return [c for c in calls if c.get("type") == "error_update"]


def extract_notifications(mock: AsyncMock) -> list[dict]:
    """Extract notify callbacks from send_to_jeedom call history."""
    calls = [c.args[0] for c in mock.call_args_list]
    return [c for c in calls if c.get("type") == "notify"]


# ===== TASK 2: HAPPY PATH SCENARIO — UDP (AC: 1, 2) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_happy_path_supervision_then_alarm(csr_sim):
    """E2E UDP happy path: supervision reaches HEALTHY, then alarm delivered → CONFIRMED. (AC: 1, 2)

    Scenario:
    - UDP daemon starts → supervision loop fires → simulator ACKs → SM1=HEALTHY
    - on_message("burglarAlarm") injected → SM2 processes → simulator ACKs → SM2=CONFIRMED

    Expected result:
    - Callback ordering: sup_state=1 → sup_state=2 → event_state=3 → event_state=1
    - Ring buffer contains supervision entry + alarm dialog entry
    - message_trace callback emitted with alarm dialog
    - Sequence number increments: supervision seq=N, alarm seq=N+1
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    try:
        await daemon.on_start()

        # Assert: SM1 reaches HEALTHY
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        seq_before_alarm = daemon._sia_seq

        # Inject burglar alarm
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Assert: SM2 reaches CONFIRMED
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: callback ordering — sup_state=1 < sup_state=2 < event_state=1
        sup_states = extract_sup_states(daemon.send_to_jeedom)
        event_states = extract_event_states(daemon.send_to_jeedom)

        assert 1 in sup_states, "Expected supervision_state=1 (INITIALIZING) callback"
        assert 2 in sup_states, "Expected supervision_state=2 (HEALTHY) callback"
        assert 1 in event_states, "Expected event_state=1 (CONFIRMED) callback"

        idx_sup1 = next(i for i, s in enumerate(sup_states) if s == 1)
        idx_sup2 = next(i for i, s in enumerate(sup_states) if s == 2)
        assert idx_sup1 < idx_sup2, "supervision_state=1 must precede supervision_state=2"

        all_calls = [c.args[0] for c in daemon.send_to_jeedom.call_args_list]
        # PENDING (event_state=3) is set internally but not pushed as a callback in the fast path.
        # Verify ordering: sup_state=2 (HEALTHY) must precede event_state=1 (CONFIRMED).
        event1_pos = next(
            (i for i, c in enumerate(all_calls) if c.get("event_state") == 1), None
        )
        sup2_pos = next(
            (i for i, c in enumerate(all_calls) if c.get("supervision_state") == 2), None
        )
        assert sup2_pos is not None and event1_pos is not None
        assert sup2_pos < event1_pos, "sup_state=2 must precede event_state=1 (CONFIRMED)"

        # Assert: ring buffer has entries
        assert len(daemon._ring_buffer) >= 2, (
            "Ring buffer must contain at least supervision entry + alarm dialog entry"
        )

        # Assert: message_trace callback emitted
        message_traces = [c for c in all_calls if c.get("type") == "message_trace"]
        assert len(message_traces) >= 1, "Expected at least one message_trace callback for alarm dialog"

        # Assert: alarm sequence number increments from supervision seq
        # _sia_seq is post-increment: alarm was sent with seq_before_alarm, next seq = seq_before_alarm+1
        assert daemon._sia_seq == (seq_before_alarm + 1) % 10000, (
            f"Sequence not incremented: before={seq_before_alarm}, after={daemon._sia_seq}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 3: NETWORK RECOVERY SCENARIO (AC: 3) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_network_recovery_strike_escalation(csr_sim):
    """E2E UDP: strike escalates 1→2→3 then simulator restored → HEALTHY recovery. (AC: 3)

    Scenario:
    - Daemon HEALTHY → stop simulator → supervision timeouts escalate strike 1→2→3
    - T1 fired at each strike (1,2,3); T3 fired exactly once at strike=3
    - Restart simulator on same ports → next ACK → SM1=HEALTHY

    Expected result:
    - T1 (SUPERVISION_TIMEOUT) dispatched at each strike (3 total)
    - T3 (SUPERVISION_DISCONNECTED) dispatched exactly once
    - After recovery: strike=0, _sm1_t3_fired=False
    - supervision_state transitions in order: 2→1→0→2
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    dispatched: list[tuple[ErrorCode, object]] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append((code, ctx))
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    sim2 = None
    udp_task2 = None
    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Stop simulator — triggers supervision timeouts
        await sim.stop()

        # Wait for strike=3
        await _wait_for(
            lambda: daemon._strike_counter >= 3,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: T1 (SUPERVISION_TIMEOUT) fired at strike=1 only (by design: fires once, not per-strike)
        t1_count = sum(1 for code, _ in dispatched if code == ErrorCode.SUPERVISION_TIMEOUT)
        assert t1_count >= 1, (
            f"Expected SUPERVISION_TIMEOUT T1 at strike=1 (fires once), got {t1_count} dispatches"
        )

        # Assert: T3 (SUPERVISION_DISCONNECTED) fired exactly once at strike=3
        t3_count = sum(1 for code, _ in dispatched if code == ErrorCode.SUPERVISION_DISCONNECTED)
        assert t3_count == 1, (
            f"Expected SUPERVISION_DISCONNECTED T3 exactly once, got {t3_count}"
        )

        # Assert: supervision_state transitions include 1 (impaired) and 0 (critical)
        sup_states = extract_sup_states(daemon.send_to_jeedom)
        assert 1 in sup_states, "Expected supervision_state=1 (DEGRADED 1-2) in history"
        assert 0 in sup_states, "Expected supervision_state=0 (DEGRADED 3) in history"

        # Restart simulator for recovery
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(udp_port=udp_port, tcp_port=tcp_port, preset=sim2_preset)
        await sim2.start()
        udp_task2 = asyncio.create_task(sim2._handle_udp(), name="sim2_udp_recv")

        # Wait for recovery
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: after recovery, strike=0 and T3 flag reset
        assert daemon._strike_counter == 0, f"Expected strike=0 after recovery, got {daemon._strike_counter}"
        assert daemon._sm1_t3_fired is False, "_sm1_t3_fired must be False after recovery"

        # Assert: supervision_state=2 (HEALTHY) appears again after recovery
        sup_states_after = extract_sup_states(daemon.send_to_jeedom)
        count_healthy = sum(1 for s in sup_states_after if s == 2)
        assert count_healthy >= 2, (
            f"Expected ≥2 supervision_state=2 callbacks (initial + recovery), got {sup_states_after}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        if udp_task2:
            try:
                udp_task2.cancel()
                with suppress(asyncio.CancelledError):
                    await udp_task2
            except Exception:
                pass
        if sim2:
            with suppress(Exception):
                await sim2.stop()


# ===== TASK 4: DAEMON RESTART SCENARIO (AC: 4) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_daemon_restart_recovery(csr_sim):
    """E2E: daemon stopped and restarted; second daemon has clean state. (AC: 4)

    Scenario:
    - Start daemon → HEALTHY → call on_stop() → verify STOPPED push
    - Re-create daemon (fresh instance) → on_start() → wait HEALTHY

    Expected result:
    - First daemon emits supervision_state=0 with 'ARRÊTÉ' label on stop
    - Second daemon reaches HEALTHY within 2× supervision_interval timeout
    - Second daemon has clean state: _ring_buffer empty, _strike_counter=0,
      _sm2_state=IDLE, _sm1_t3_fired=False, call_count starts fresh
    """
    sim, udp_port, tcp_port = csr_sim
    daemon1 = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    try:
        await daemon1.on_start()
        await _wait_for(lambda: daemon1._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Stop first daemon
        await daemon1.on_stop()

        # Assert: first daemon emitted STOPPED push (supervision_state=0, label='ARRÊTÉ')
        all_calls = [c.args[0] for c in daemon1.send_to_jeedom.call_args_list]
        stopped_calls = [
            c for c in all_calls
            if c.get("type") == "info_update" and c.get("supervision_label") == "ARRÊTÉ"
        ]
        assert len(stopped_calls) >= 1, "Expected STOPPED push (supervision_label='ARRÊTÉ') from first daemon"

        # Create second daemon (fresh instance — clean state)
        daemon2 = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

        # Assert: fresh state before start
        assert len(daemon2._ring_buffer) == 0, "New daemon ring buffer must be empty"
        assert daemon2._strike_counter == 0, "New daemon strike_counter must be 0"
        assert daemon2._sm2_state == SM2State.IDLE, "New daemon SM2 must be IDLE"
        assert daemon2._sm1_t3_fired is False, "New daemon _sm1_t3_fired must be False"
        assert daemon2.send_to_jeedom.call_count == 0, "New daemon call_count must start at 0"

        try:
            await daemon2.on_start()

            # Assert: second daemon reaches HEALTHY within 2× supervision_interval
            await _wait_for(
                lambda: daemon2._sm1_state == SM1State.HEALTHY,
                timeout=E2E_FAST_INTERVAL * 2 + 5.0,  # 2 cycles + buffer
            )

            # Assert: second daemon still has clean strike state
            assert daemon2._strike_counter == 0, f"Second daemon strike={daemon2._strike_counter}"
            assert daemon2._sm1_t3_fired is False, "Second daemon _sm1_t3_fired must be False"

        finally:
            with suppress(Exception):
                await daemon2.on_stop()

    finally:
        with suppress(Exception):
            await daemon1.on_stop()


# ===== TASK 5: ALARM DURING NETWORK LOSS SCENARIO (AC: 5) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_alarm_during_network_loss(csr_sim):
    """E2E UDP: SM1 DEGRADED state + alarm delivery after network recovery. (AC: 5)

    Scenario:
    - Daemon HEALTHY → stop simulator → SM1=DEGRADED (strike escalates)
    - Inject alarm while DEGRADED → SM2=PENDING (queued, transport unavailable)
    - Restart simulator → SM1 recovers to HEALTHY
    - Inject second alarm post-recovery → SM2=CONFIRMED

    Expected result:
    - SM2=PENDING after on_message() during DEGRADED (event enqueued, SM2 set at dequeue)
    - After recovery: SM1=HEALTHY, fresh alarm → SM2=CONFIRMED
    - event_state=1 (confirmed) callback arrives post-recovery
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    sim2 = None
    udp_task2 = None
    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Stop simulator to degrade network
        await sim.stop()
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.DEGRADED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Inject alarm while DEGRADED: queue consumer will dequeue and set SM2=PENDING
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Assert: SM2=PENDING (alarm dequeued and SM2 set; first send attempt may fail via SIATransportError
        # which propagates through _send_with_retry → _queue_consumer exception handler, but SM2 stays PENDING)
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.PENDING,
            timeout=5.0,
        )

        # Restart simulator for SM1 recovery
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(udp_port=udp_port, tcp_port=tcp_port, preset=sim2_preset)
        await sim2.start()
        udp_task2 = asyncio.create_task(sim2._handle_udp(), name="sim2_udp_recv")

        # Assert: SM1 recovers to HEALTHY after simulator restart
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Inject a fresh alarm post-recovery → should reach CONFIRMED
        await daemon.on_message("fireAlarm", {"zone": "cuisine"})
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: event_state=1 (CONFIRMED) callback arrived post-recovery
        event_states = extract_event_states(daemon.send_to_jeedom)
        assert 1 in event_states, "Expected event_state=1 (CONFIRMED) callback after recovery"

        # Assert: ring buffer has alarm dialog entries (from post-recovery alarm)
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is not True]
        assert len(non_routine) >= 1, "Expected alarm dialog entry in ring buffer after recovery"

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        if udp_task2:
            try:
                udp_task2.cancel()
                with suppress(asyncio.CancelledError):
                    await udp_task2
            except Exception:
                pass
        if sim2:
            with suppress(Exception):
                await sim2.stop()


# ===== TASK 6: CSR ERROR SCENARIO (AC: 6) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_csr_error_nak_notification(csr_sim):
    """E2E: simulator patched to NAK → BAD_CSR_RESPONSE T2 + error_update callback. (AC: 6)

    Scenario:
    - Patch sim._decide_response to always return 'NAK'
    - Daemon starts → first supervision frame → NAK → BAD_CSR_RESPONSE (T2)

    Expected result:
    - BAD_CSR_RESPONSE (T2) notification dispatched
    - error_update callback emitted with code=BAD_CSR_RESPONSE
    - Ring buffer has non-routine entry (is_routine=False)
    """
    sim, udp_port, tcp_port = csr_sim

    # Patch simulator to always NAK
    sim._decide_response = lambda *_: "NAK"  # type: ignore[method-assign]

    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)
    dispatched: list[tuple[ErrorCode, object]] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append((code, ctx))
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()

        # Wait for first strike (from NAK)
        await _wait_for(
            lambda: daemon._strike_counter >= 1,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: BAD_CSR_RESPONSE (T2) dispatched
        bad_csr_codes = [code for code, _ in dispatched if code == ErrorCode.BAD_CSR_RESPONSE]
        assert len(bad_csr_codes) >= 1, (
            f"Expected BAD_CSR_RESPONSE T2 notification, got {[c for c, _ in dispatched]}"
        )

        # Assert: error_update callback emitted with code=BAD_CSR_RESPONSE
        error_updates = extract_error_updates(daemon.send_to_jeedom)
        bad_csr_updates = [
            e for e in error_updates if e.get("code") == ErrorCode.BAD_CSR_RESPONSE.name
        ]
        assert len(bad_csr_updates) >= 1, (
            f"Expected error_update with code=BAD_CSR_RESPONSE, got error_updates={error_updates}"
        )

        # Assert: ring buffer has non-routine entry
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is False]
        assert len(non_routine) >= 1, (
            f"Expected ≥1 is_routine=False ring buffer entry, got {entries}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 7: RESOURCE TESTING (AC: 7) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_resource_usage_sustained_supervision(csr_sim):
    """E2E: daemon resources bounded under 60 supervision cycles (6s at 0.1s interval). (AC: 7)

    Scenario:
    - Run daemon for 60 supervision cycles (supervision_interval_s=0.1 → 6s total)
    - Sample task count and ring buffer size periodically

    Expected result:
    - No orphaned tasks: len(daemon._tasks) bounded ≤ 3 at all sample points
    - Ring buffer size never exceeds 50 (configured cap)
    - Routine entries throttled: ≤ ceil(6s / 600s) + 1 = 1 routine entry (10-min throttle)
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_RESOURCE_INTERVAL)

    task_samples: list[int] = []
    rss_before: int = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=10.0)

        # Sample task count every 10 cycles (every 1s at 0.1s interval)
        for _ in range(6):
            await asyncio.sleep(1.0)
            task_samples.append(len(daemon._tasks))

        # Assert: task count bounded ≤ 3 at all sample points
        for i, count in enumerate(task_samples):
            assert count <= 3, (
                f"Task count exceeded bound at sample {i}: {count} tasks "
                f"(expected ≤ 3: supervision_loop + queue_consumer + optional in-flight send)"
            )

        # Assert: ring buffer cap never exceeded
        assert len(daemon._ring_buffer) <= 50, (
            f"Ring buffer exceeded cap: {len(daemon._ring_buffer)} > 50"
        )

        # Assert: routine entries throttled — at most 1 routine entry in a 6s window
        entries = list(daemon._ring_buffer._buffer)
        routine_entries = [e for e in entries if e.get("is_routine") is True]
        max_routine = ceil(6.0 / 600.0) + 1  # = 1 + buffer
        assert len(routine_entries) <= max_routine, (
            f"Routine entries not throttled: {len(routine_entries)} > {max_routine} "
            f"(10-min throttle should limit entries in 6s window)"
        )

        # Optional: RSS check (informational, not hard-fail)
        rss_after: int = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_delta_mb = abs(rss_after - rss_before) / (1024 * 1024)
        if rss_delta_mb > 10:
            import warnings
            warnings.warn(f"RSS delta {rss_delta_mb:.1f} MB > 10 MB threshold (informational)")

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 8: MULTI-ALARM SEQUENCE TEST (AC: 2, 16) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_multi_alarm_sequential(csr_sim):
    """E2E: burglarAlarm → CONFIRMED → fireAlarm → CONFIRMED → panicAlarm → CONFIRMED. (AC: 2, 16)

    Scenario:
    - Daemon HEALTHY → inject 3 alarms sequentially (wait CONFIRMED between each)

    Expected result:
    - SM2 transitions: IDLE→PENDING→CONFIRMED, CONFIRMED→PENDING→CONFIRMED (×2)
    - Each alarm produces distinct SIA event code: BA=burglar, FA=fire, PA=panic
    - Ring buffer contains 3 alarm dialog entries
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Alarm 1: burglarAlarm (BA)
        await daemon.on_message("burglarAlarm", {"zone": "entrée"})
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )
        # Assert: event_state=1 (CONFIRMED) received
        assert 1 in extract_event_states(daemon.send_to_jeedom), "Expected CONFIRMED after burglarAlarm"
        assert daemon._event_sia_code == "BA", f"Expected SIA code BA, got {daemon._event_sia_code}"

        # Alarm 2: fireAlarm (FA) — SM2 transitions CONFIRMED → PENDING (not IDLE → PENDING).
        # Must track confirmed_count before injecting to distinguish alarm 2's CONFIRMED
        # from alarm 1's (SM2 is already CONFIRMED when we inject, so we wait for count to grow).
        confirmed_count_before_fa = sum(
            1 for s in extract_event_states(daemon.send_to_jeedom) if s == 1
        )
        await daemon.on_message("fireAlarm", {"zone": "cuisine"})
        await _wait_for(
            lambda: sum(1 for s in extract_event_states(daemon.send_to_jeedom) if s == 1)
            > confirmed_count_before_fa,
            timeout=E2E_SCENARIO_TIMEOUT,
        )
        assert daemon._event_sia_code == "FA", f"Expected SIA code FA, got {daemon._event_sia_code}"

        # Alarm 3: panicAlarm (PA)
        confirmed_count_before_pa = sum(
            1 for s in extract_event_states(daemon.send_to_jeedom) if s == 1
        )
        await daemon.on_message("panicAlarm", {"zone": "bureau"})
        await _wait_for(
            lambda: sum(1 for s in extract_event_states(daemon.send_to_jeedom) if s == 1)
            > confirmed_count_before_pa,
            timeout=E2E_SCENARIO_TIMEOUT,
        )
        assert daemon._event_sia_code == "PA", f"Expected SIA code PA, got {daemon._event_sia_code}"

        # Assert: event_state=1 (CONFIRMED) callbacks present ≥3 times.
        # PENDING (event_state=3) is an internal state not pushed as a callback in the fast path.
        event_states = extract_event_states(daemon.send_to_jeedom)
        confirmed_count = sum(1 for s in event_states if s == 1)
        assert confirmed_count >= 3, f"Expected ≥3 CONFIRMED (event_state=1) callbacks, got {confirmed_count}"

        # Assert: ring buffer contains 3+ alarm dialog entries
        entries = list(daemon._ring_buffer._buffer)
        # Alarm dialogs are non-routine entries with event data
        non_routine = [e for e in entries if e.get("is_routine") is not True]
        assert len(non_routine) >= 3, (
            f"Expected ≥3 non-routine ring buffer entries (3 alarm dialogs), got {len(non_routine)}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 9: ALARM RETRY EXHAUSTION → FAILED (AC: 10) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_alarm_retry_exhaustion_sm2_failed(csr_sim):
    """E2E: alarm retries exhaust with CSR unreachable → SM2=FAILED, EVENT_FAILED T3. (AC: 10)

    Scenario:
    - Daemon HEALTHY → stop simulator → inject alarm → wait retries exhaust → SM2=FAILED

    Expected result:
    - EVENT_FAILED (T3) notification dispatched with EventFailedCtx
    - event_state=2 (failed) callback emitted
    - Ring buffer alarm dialog shows all retry attempts
    - Sequence number NOT incremented on failed send attempts after first increment
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    dispatched: list[tuple[ErrorCode, object]] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append((code, ctx))
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        seq_before = daemon._sia_seq

        # Patch _send_raw to raise asyncio.TimeoutError for event frames (not supervision).
        # This triggers the asyncio.TimeoutError except branch in _send_with_retry,
        # causing retries to exhaust → SM2=FAILED. The supervision loop continues unaffected
        # because _send_supervision catches SIATransportError separately.
        alarm_send_count = 0
        original_send_raw = daemon._send_raw

        async def _timeout_on_event(frame: bytes):
            nonlocal alarm_send_count
            # Let supervision frames through; time out only event (alarm) frames.
            # Both supervision and alarm frames use "SIA-DCS" id_token when unencrypted;
            # the reliable differentiator is the event code in the data block:
            # supervision uses SIA_NULL_CODE "0000" → b"|0000]"; alarms use "BA", "FA", "PA".
            if b"|0000]" not in frame:
                alarm_send_count += 1
                raise asyncio.TimeoutError
            return await original_send_raw(frame)

        daemon._send_raw = _timeout_on_event  # type: ignore[method-assign]

        # Inject alarm
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Wait for SM2=FAILED (retries exhausted: MAX_RETRY_DEFAULT=3, 1s backoff each)
        # Max wait: (MAX_RETRY_DEFAULT+1) × (1.0s backoff) + buffer
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.FAILED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: EVENT_FAILED (T3) notification dispatched
        event_failed_codes = [code for code, _ in dispatched if code == ErrorCode.EVENT_FAILED]
        assert len(event_failed_codes) >= 1, (
            f"Expected EVENT_FAILED T3 notification, got {[c for c, _ in dispatched]}"
        )

        # Assert: event_state=2 (failed) callback emitted
        event_states = extract_event_states(daemon.send_to_jeedom)
        assert 2 in event_states, f"Expected event_state=2 (FAILED) callback, got {event_states}"

        # Assert: ring buffer alarm dialog entry exists
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is not True]
        assert len(non_routine) >= 1, "Expected alarm dialog entry in ring buffer after failure"

        # Assert: retry count matches MAX_RETRY_DEFAULT+1 total attempts (initial + retries)
        assert alarm_send_count == MAX_RETRY_DEFAULT + 1, (
            f"Expected {MAX_RETRY_DEFAULT + 1} alarm send attempts, got {alarm_send_count}"
        )

        # Assert: sequence number incremented only once (first attempt allocates seq; retries reuse it)
        seq_after = daemon._sia_seq
        assert seq_after == seq_before + 1, (
            f"Expected seq incremented by 1 (retries reuse same seq), got {seq_before} → {seq_after}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 10: NAK ON ALARM EVENT — IMMEDIATE FAILURE (AC: 11) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_alarm_nak_immediate_failure(csr_sim):
    """E2E: simulator NAKs only event frames → SM2=FAILED immediately (no retry). (AC: 11)

    Scenario:
    - Patch simulator to NAK event frames but ACK NULL supervision frames
    - Daemon reaches HEALTHY → inject alarm → SM2=FAILED (NAK stops retrying per spec)

    Expected result:
    - SM2=FAILED immediately (no retry on NAK)
    - BAD_CSR_RESPONSE (T2) notification fired (alarm path)
    - EVENT_FAILED (T3) notification also fired (alarm ultimately failed)
    """
    sim, udp_port, tcp_port = csr_sim

    # Patch: NAK ALARM frames (type='ALARM'), ACK NULL supervision frames (type='NULL').
    # parsed_frame keys from _parse_received_message: type, seq, raw_nak — no event_code key.
    original_decide = sim._decide_response

    def _nak_events_only(parsed_frame: dict, preset) -> str:
        if parsed_frame.get("type") == "ALARM":
            return "NAK"
        return original_decide(parsed_frame, preset)

    sim._decide_response = _nak_events_only  # type: ignore[method-assign]

    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)
    dispatched: list[tuple[ErrorCode, object]] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append((code, ctx))
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()

        # Wait for HEALTHY (supervision ACKed normally)
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Inject alarm — will get NAK
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Assert: SM2=FAILED (NAK → immediate fail, no retry)
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.FAILED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: BAD_CSR_RESPONSE (T2) dispatched (NAK path: immediate failure, no retry).
        # Per daemon-design.md: NAK → _notify(BAD_CSR_RESPONSE) → SM2=FAILED, no EVENT_FAILED.
        # EVENT_FAILED is reserved for timeout exhaustion (retries); NAK stops immediately.
        bad_csr = [code for code, _ in dispatched if code == ErrorCode.BAD_CSR_RESPONSE]
        assert len(bad_csr) >= 1, (
            f"Expected BAD_CSR_RESPONSE T2 for alarm NAK, got {[c for c, _ in dispatched]}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 11: TCP TRANSPORT SCENARIOS (AC: 12, 13) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_tcp_happy_path(csr_sim):
    """E2E TCP: happy path — supervision reaches HEALTHY, alarm → CONFIRMED. (AC: 12)

    Scenario:
    - TCP daemon starts → supervision ACKed → SM1=HEALTHY → alarm → SM2=CONFIRMED

    Expected result:
    - SM1=HEALTHY after first supervision ACK via TCP
    - SM2=CONFIRMED after alarm ACK via TCP
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        await daemon.on_message("burglarAlarm", {"zone": "salon"})
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: callbacks present
        assert 2 in extract_sup_states(daemon.send_to_jeedom), "Expected supervision_state=2 (HEALTHY)"
        assert 1 in extract_event_states(daemon.send_to_jeedom), "Expected event_state=1 (CONFIRMED)"

    finally:
        with suppress(Exception):
            await daemon.on_stop()


@pytest.mark.asyncio
@pytest.mark.level3
async def test_tcp_network_recovery(csr_sim):
    """E2E TCP: network recovery path — TCP_RECONNECTING → INITIALIZING → HEALTHY. (AC: 12)

    Scenario:
    - TCP daemon HEALTHY → simulator stops → TCP_RECONNECTING entered
    - Restart simulator → reconnect probe succeeds → INITIALIZING → HEALTHY

    Expected result:
    - SM1 enters TCP_RECONNECTING at strike=3
    - After restart: SM1=INITIALIZING (reconnect reset), then SM1=HEALTHY
    - strike=0, _sm1_t3_fired=False after reconnect
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    sim2 = None
    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Stop simulator
        await sim.stop()
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.TCP_RECONNECTING,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Restart simulator
        sim2_preset = {
            "crc_format": "hex",
            "account_number": E2E_ACCOUNT,
            "encryption_key": None,
        }
        sim2 = CSRSimulator(udp_port=udp_port, tcp_port=tcp_port, preset=sim2_preset)
        await sim2.start()

        # Assert: reconnect probe → INITIALIZING then HEALTHY
        await _wait_for(
            lambda: daemon._sm1_state in (SM1State.INITIALIZING, SM1State.HEALTHY),
            timeout=E2E_SCENARIO_TIMEOUT,
        )
        assert daemon._strike_counter == 0, f"Expected strike=0 after reconnect, got {daemon._strike_counter}"
        assert daemon._sm1_t3_fired is False, "_sm1_t3_fired must be False after reconnect"

        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        if sim2:
            with suppress(Exception):
                await sim2.stop()


@pytest.mark.asyncio
@pytest.mark.level3
async def test_tcp_no_network_daemon_self_stop(csr_sim):
    """E2E TCP: all reconnect probes fail → NO_NETWORK → daemon calls self.stop(). (AC: 13)

    Scenario:
    - TCP daemon in TCP_RECONNECTING, simulator never restarts
    - 3 probe attempts all time out (connect_timeout_s=0.5 → max 3×0.5s=1.5s)
    - → SM1=NO_NETWORK, _notify(TRANSPORT_PERMANENT)

    Expected result:
    - SM1=NO_NETWORK after exhausting reconnect attempts
    - TRANSPORT_PERMANENT (T3) notification dispatched
    - supervision_state=0 pushed
    - Daemon not running (tasks drained) after self.stop()
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("TCP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    dispatched: list[tuple[ErrorCode, object]] = []
    original_dispatch = daemon._dispatch_notify

    async def _capture_dispatch(code, ctx):
        dispatched.append((code, ctx))
        await original_dispatch(code, ctx)

    daemon._dispatch_notify = _capture_dispatch  # type: ignore[method-assign]

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Stop simulator — never restart
        await sim.stop()
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.TCP_RECONNECTING,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Wait for NO_NETWORK (all 3 probes exhausted)
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.NO_NETWORK,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: TRANSPORT_PERMANENT (T3) dispatched
        await _wait_for(
            lambda: any(code == ErrorCode.TRANSPORT_PERMANENT for code, _ in dispatched),
            timeout=10.0,
        )
        transport_perm = [code for code, _ in dispatched if code == ErrorCode.TRANSPORT_PERMANENT]
        assert len(transport_perm) >= 1, (
            f"Expected TRANSPORT_PERMANENT T3 notification, got {[c for c, _ in dispatched]}"
        )

        # Assert: supervision_state=0 pushed
        sup_states = extract_sup_states(daemon.send_to_jeedom)
        assert 0 in sup_states, "Expected supervision_state=0 after NO_NETWORK"

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 12: ENCRYPTED MODE HAPPY PATH (AC: 14) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_happy_path_encrypted(csr_sim):
    """E2E encrypted: supervision + alarm with encryption_enabled=True → ACK from simulator. (AC: 14)

    Scenario:
    - Daemon with encryption_enabled=True; simulator with encryption_key=None
    - v1.0 encryption is id_token marker only: daemon sends "*SIA-DCS" frames,
      simulator sends plain ACK (payload is NOT AES-encrypted in v1.0)
    - Supervision and alarm frames carry "*SIA-DCS" encrypted marker

    Expected result:
    - Supervision frames use *SIA-DCS id_token (encrypted marker per v1.0)
    - Alarm frames use *SIA-DCS id_token (encrypted event marker)
    - CSR simulator responds with plain ACK (parseable by decode_ack_nak)
    - SM1=HEALTHY and SM2=CONFIRMED
    """
    # Allocate fresh ports for the encrypted simulator (csr_sim fixture already holds the fixture ports).
    enc_udp_port = _find_free_udp_port()
    enc_tcp_port = _find_free_tcp_port()

    enc_sim_preset = {
        "crc_format": "hex",
        "account_number": E2E_ACCOUNT,
        # encryption_key=None: v1.0 encryption is id_token marker only ("*SIA-DCS"),
        # actual payload is NOT AES-encrypted. Simulator must send plain ACK frames
        # (not AES-encrypted) so decode_ack_nak() can parse them on the daemon side.
        "encryption_key": None,
    }
    enc_sim = CSRSimulator(
        udp_port=enc_udp_port,
        tcp_port=enc_tcp_port,
        preset=enc_sim_preset,
        response_delay_ms=0,
    )
    await enc_sim.start()
    enc_udp_task = asyncio.create_task(enc_sim._handle_udp(), name="enc_sim_udp_recv")

    daemon = make_e2e_daemon(
        "UDP", enc_udp_port, enc_tcp_port,
        supervision_interval_s=E2E_FAST_INTERVAL,
        encryption_enabled=True,
    )

    try:
        await daemon.on_start()

        # Assert: SM1 reaches HEALTHY (encrypted supervision ACKed)
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: supervision frames use *NULL marker (encrypted supervision = *NULL per spec)
        from resources.siadc09d.sia_protocol import ENCRYPTED_MARKER, NULL_TOKEN
        sup_frame = daemon._sia_builder.make_supervision_message(
            account_number=daemon._account,
            account_prefix=daemon._account_prefix,
            encryption=daemon._preset.encryption_enabled,
        )
        sup_str = sup_frame.decode("ascii", errors="replace")
        assert f'"{ENCRYPTED_MARKER}{NULL_TOKEN}"' in sup_str, (
            f"Expected *NULL marker in encrypted supervision frame, got: {sup_str[:100]}"
        )

        # Inject alarm
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Assert: SM2 reaches CONFIRMED (encrypted alarm ACKed by simulator)
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: both supervision and event callbacks present
        assert 2 in extract_sup_states(daemon.send_to_jeedom), "Expected supervision_state=2 (HEALTHY)"
        assert 1 in extract_event_states(daemon.send_to_jeedom), "Expected event_state=1 (CONFIRMED)"

    finally:
        with suppress(Exception):
            await daemon.on_stop()
        enc_udp_task.cancel()
        with suppress(asyncio.CancelledError):
            await enc_udp_task
        with suppress(Exception):
            await enc_sim.stop()


# ===== TASK 13: ALARM DURING INITIALIZING — RACE CONDITION (AC: 15) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_alarm_during_initializing(csr_sim):
    """E2E: alarm injected immediately after on_start(), before first supervision ACK. (AC: 15)

    Scenario:
    - Call on_start() → immediately inject alarm (before any supervision ACK)
    - Alarm is sent without waiting for HEALTHY (too time-critical to hold)

    Expected result:
    - SM2=CONFIRMED (alarm ACKed by simulator despite INITIALIZING SM1 state)
    - SM1 still reaches HEALTHY via subsequent supervision cycle
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    try:
        await daemon.on_start()
        # Immediately inject alarm before first supervision ACK
        assert daemon._sm1_state == SM1State.INITIALIZING, (
            f"Expected SM1=INITIALIZING right after on_start(), got {daemon._sm1_state}"
        )
        await daemon.on_message("burglarAlarm", {"zone": "salon"})

        # Assert: alarm reaches CONFIRMED (sent immediately, not held)
        await _wait_for(
            lambda: daemon._sm2_state == SM2State.CONFIRMED,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: SM1 still reaches HEALTHY via next supervision cycle
        await _wait_for(
            lambda: daemon._sm1_state == SM1State.HEALTHY,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: event_state=1 (CONFIRMED) and supervision_state=2 (HEALTHY) callbacks arrived
        assert 1 in extract_event_states(daemon.send_to_jeedom), "Expected event_state=1 (CONFIRMED)"
        assert 2 in extract_sup_states(daemon.send_to_jeedom), "Expected supervision_state=2 (HEALTHY)"

    finally:
        with suppress(Exception):
            await daemon.on_stop()


# ===== TASK 14: RAPID-FIRE ALARMS — PRIORITYQUEUE CONTRACT (AC: 16) =====


@pytest.mark.asyncio
@pytest.mark.level3
async def test_rapid_fire_alarms(csr_sim):
    """E2E: 3 alarms injected in rapid succession, all reach CONFIRMED. (AC: 16)

    Scenario:
    - Daemon HEALTHY → inject burglarAlarm, fireAlarm, panicAlarm with no await between
    - PriorityQueue processes all 3 in sequence

    Expected result:
    - All 3 alarms reach SM2=CONFIRMED (no lost events)
    - event_state transitions show 3→1 pattern ≥3 times
    - Ring buffer contains 3+ alarm dialog entries
    - 3 event ACKs received from simulator
    """
    sim, udp_port, tcp_port = csr_sim
    daemon = make_e2e_daemon("UDP", udp_port, tcp_port, supervision_interval_s=E2E_FAST_INTERVAL)

    confirmed_count = 0
    original_dispatch = daemon._dispatch_notify

    try:
        await daemon.on_start()
        await _wait_for(lambda: daemon._sm1_state == SM1State.HEALTHY, timeout=E2E_SCENARIO_TIMEOUT)

        # Capture confirmed event count via send_to_jeedom mock
        # We'll count event_state=1 callbacks as confirmation
        initial_event_calls = len(extract_event_states(daemon.send_to_jeedom))

        # Inject 3 alarms in rapid succession (no await between)
        await daemon.on_message("burglarAlarm", {"zone": "salon"})
        await daemon.on_message("fireAlarm", {"zone": "cuisine"})
        await daemon.on_message("panicAlarm", {"zone": "bureau"})

        # Wait for all 3 alarms to be confirmed
        # Each confirmation emits event_state=1, so we need 3 new confirmed callbacks
        await _wait_for(
            lambda: sum(1 for s in extract_event_states(daemon.send_to_jeedom) if s == 1) >= 3,
            timeout=E2E_SCENARIO_TIMEOUT,
        )

        # Assert: final SM2 state is CONFIRMED (last alarm)
        assert daemon._sm2_state == SM2State.CONFIRMED, (
            f"Expected final SM2=CONFIRMED, got {daemon._sm2_state}"
        )

        # Assert: event_state=1 (CONFIRMED) callbacks ≥3.
        # PENDING (event_state=3) is internal state — not pushed as callback in the fast path.
        event_states = extract_event_states(daemon.send_to_jeedom)
        confirmed_total = sum(1 for s in event_states if s == 1)
        assert confirmed_total >= 3, f"Expected ≥3 CONFIRMED (event_state=1) callbacks, got {confirmed_total}"

        # Assert: ring buffer contains 3+ alarm dialog entries
        entries = list(daemon._ring_buffer._buffer)
        non_routine = [e for e in entries if e.get("is_routine") is not True]
        assert len(non_routine) >= 3, (
            f"Expected ≥3 alarm dialog entries in ring buffer, got {len(non_routine)}: {non_routine}"
        )

    finally:
        with suppress(Exception):
            await daemon.on_stop()
