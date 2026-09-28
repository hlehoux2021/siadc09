"""
Daemon core integration tests for Story 5.6.

Verifies SM1/SM2 state machines work together with transport, error handler,
and task lifecycle as an integrated system. Unlike unit tests (Stories 5-1
through 5-5) which mock individual components, these tests exercise multiple
components together to catch interaction bugs.

Reference: _bmad-output/implementation-artifacts/5-6-daemon-core-integration-state-transition-tests.md
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from resources.siadc09d.daemon import (
    SM1State,
    SM2State,
    SIADaemon,
    EventItem,
    STRIKE_CAP,
    SIA_SEQ_MAX,
)
from resources.siadc09d.error_handler import (
    BadCSRResponseCtx,
    ErrorCode,
    EventFailedCtx,
    SM1DisconnectedCtx,
    SM1TimeoutCtx,
    TransportPermanentCtx,
)
from resources.siadc09d.sia_protocol import parse_frame_header
from tests.conftest import make_daemon_preset


# ===== Shared helpers =====

def _make_daemon(transport: str = 'UDP') -> SIADaemon:
    """Create a SIADaemon with mocked transport, _notify, and logging.

    Expected result:
    - Daemon has all instance vars initialized but no background tasks
    - Transport, _notify, logging all mocked for deterministic testing
    - _log_sm1_supervision and _log_sm2_event mocked to avoid
      await-on-sync ring_buffer issue (pre-existing, not this story's scope)
    """
    preset = make_daemon_preset(transport=transport)
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = '001234'
    daemon._receiver_prefix = ''
    daemon._account_prefix = 'L0'

    mock_t = MagicMock()
    mock_t.start = AsyncMock()
    mock_t.close = AsyncMock()
    mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
    daemon._sia_transport = mock_t
    return daemon


def _install_stop_spy(daemon: SIADaemon) -> list[int]:
    """Replace daemon.stop() with a spy that faithfully mirrors BaseDaemon.stop().

    The permanent-failure path schedules self.stop() as the tracked task
    'transport_permanent_stop' (daemon.py:1146). Under the real
    BaseDaemon.stop() (base_daemon.py:133-149), on_stop() runs, then the loop
    cancels every task EXCEPT current_task() via asyncio.all_tasks() — which in
    a pytest event loop includes the TEST's own driver task, cancelling the
    awaiting `await asyncio.gather(*daemon._tasks)`. That process-level sweep is
    correct in production (run()'s finally then sys.exit(0)s for the watchdog)
    but cannot execute inside the test loop. The spy runs the real on_stop()
    while discarding the self-stop task from _tasks first, so on_stop()'s own
    gather does not await the running task on itself.

    Expected result:
    - Returns a list whose length equals the number of stop() invocations
    - Each invocation runs the real on_stop() (transport close + task cancellation)
    """
    calls: list[int] = []

    async def _spy_stop() -> None:
        calls.append(1)
        # Mirror BaseDaemon.stop(): exclude the current (self-stop) task from
        # _tasks so on_stop()'s gather does not await this coroutine on itself.
        current = asyncio.current_task()
        daemon._tasks.discard(current)
        await daemon.on_stop()

    daemon.stop = _spy_stop  # type: ignore[method-assign]
    return calls


async def _make_started_daemon(transport: str = 'UDP') -> tuple[SIADaemon, MagicMock]:
    """Create a SIADaemon with on_start() called (full lifecycle).

    Expected result:
    - Daemon has queue_consumer and supervision_loop running
    - _log_sm1_supervision and _log_sm2_event mocked to avoid await-on-sync
      ring_buffer issue (pre-existing, not this story's scope)
    - Returns (daemon, mock_transport) tuple for assertions
    """
    preset = make_daemon_preset(transport=transport)
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = '001234'
    daemon._receiver_prefix = ''
    daemon._account_prefix = 'L0'
    daemon.send_to_jeedom = AsyncMock()

    transport_cls = 'SIAUDPTransport' if transport == 'UDP' else 'SIATCPTransport'
    with patch(f'resources.siadc09d.daemon.{transport_cls}') as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        MockT.return_value = mock_t
        await daemon.on_start()
        daemon._sia_transport = mock_t
    return daemon, mock_t


@pytest.fixture
def daemon_no_start():
    """Create a SIADaemon without calling on_start() — for direct method tests.

    Expected result:
    - Daemon has all instance vars initialized but no tasks running
    - Transport, _notify, logging all mocked for deterministic testing
    """
    return _make_daemon()


# ===== TC1: SM1 full lifecycle (AC1) =====

@pytest.mark.asyncio
async def test_sm1_full_lifecycle_initializing_to_healthy_to_degraded_to_recovery(
    daemon_no_start,
):
    """
    SM1 completes full cycle: INITIALIZING → HEALTHY → DEGRADED(1→2→3) → HEALTHY.

    Expected result:
    - ACK transitions from INITIALIZING to HEALTHY with strike=0
    - Timeouts escalate strike 1→2→3 in DEGRADED
    - T3 fires once at strike=3 (SUPERVISION_DISCONNECTED)
    - Recovery ACK resets to HEALTHY, strike=0, _sm1_t3_fired=False
    """
    daemon = daemon_no_start
    mock_t = daemon._sia_transport

    # Assert: initial state is INITIALIZING
    assert daemon._sm1_state == SM1State.INITIALIZING
    assert daemon._strike_counter == 0

    # Phase 1: First ACK → HEALTHY
    mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
    await daemon._send_supervision()

    # Assert: transitioned to HEALTHY, strike reset
    assert daemon._sm1_state == SM1State.HEALTHY
    assert daemon._strike_counter == 0

    # Phase 2: Three timeouts → DEGRADED with escalating strikes
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})

    await daemon._send_supervision()
    # Assert: strike=1, DEGRADED
    assert daemon._sm1_state == SM1State.DEGRADED
    assert daemon._strike_counter == 1

    await daemon._send_supervision()
    # Assert: strike=2, still DEGRADED
    assert daemon._sm1_state == SM1State.DEGRADED
    assert daemon._strike_counter == 2

    await daemon._send_supervision()
    # Assert: strike=3, DEGRADED (UDP — no TCP_RECONNECTING)
    assert daemon._sm1_state == SM1State.DEGRADED
    assert daemon._strike_counter == 3

    # Assert: T3 fired exactly once (SUPERVISION_DISCONNECTED)
    t3_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED
    ]
    assert len(t3_calls) == 1
    assert daemon._sm1_t3_fired is True

    # Phase 3: Recovery ACK → back to HEALTHY
    mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
    await daemon._send_supervision()

    # Assert: full recovery — HEALTHY, strike=0, T3 flag reset
    assert daemon._sm1_state == SM1State.HEALTHY
    assert daemon._strike_counter == 0
    assert daemon._sm1_t3_fired is False


# ===== TC1-TCP: SM1 full lifecycle for TCP (AC1 + AC10) =====

@pytest.mark.asyncio
async def test_sm1_full_lifecycle_tcp():
    """
    SM1 lifecycle with TCP: INITIALIZING → HEALTHY → DEGRADED(3) → TCP_RECONNECTING.

    Expected result:
    - Same as UDP until strike=3
    - At strike=3 with TCP: transitions to TCP_RECONNECTING (not stays DEGRADED)
    - T3 fires at strike=3
    """
    daemon = _make_daemon(transport='TCP')
    mock_t = daemon._sia_transport

    # ACK → HEALTHY
    await daemon._send_supervision()
    assert daemon._sm1_state == SM1State.HEALTHY

    # Three timeouts → strike=3
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})
    await daemon._send_supervision()
    await daemon._send_supervision()
    await daemon._send_supervision()

    # Assert: TCP transitions to TCP_RECONNECTING at strike=3
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    assert daemon._strike_counter == 3

    # Assert: T3 fired
    t3_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED
    ]
    assert len(t3_calls) == 1

    # Cleanup: cancel _tcp_reconnect_loop task (it would block on open_connection)
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)
    daemon._tasks.clear()


# ===== TC2: SM2 alarm confirmed via ACK (AC2) =====

@pytest.mark.asyncio
async def test_sm2_alarm_confirmed_via_ack(daemon_no_start):
    """
    SM2 alarm event is confirmed when CSR returns ACK.

    Expected result:
    - SM2 transitions IDLE → PENDING → CONFIRMED
    - _event_state_from_sm2() returns 1 (confirmed)
    - Event SIA code and zone are recorded
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY

    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event)

    # Assert: SM2 confirmed
    assert result == SM2State.CONFIRMED
    assert daemon._sm2_state == SM2State.CONFIRMED
    # Assert: event_state numeric is 1 (confirmed)
    assert daemon._event_state_from_sm2() == 1
    # Assert: event metadata recorded
    assert daemon._event_sia_code == 'BA'
    assert daemon._event_zone == 'Salon'


# ===== TC3: SM2 alarm failed via NAK (AC2) =====

@pytest.mark.asyncio
async def test_sm2_alarm_failed_via_nak(daemon_no_start):
    """
    SM2 alarm event fails immediately on NAK with BAD_CSR_RESPONSE notification.

    Expected result:
    - SM2 transitions IDLE → PENDING → FAILED
    - _event_state_from_sm2() returns 2 (failed)
    - _notify called with ErrorCode.BAD_CSR_RESPONSE
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sia_transport.send_frame = AsyncMock(
        return_value={'status': 'nak', 'raw_nak': b'\x00\x01\x02'}
    )

    event = EventItem(sia_code='FA', zone='Cuisine', timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event)

    # Assert: SM2 failed
    assert result == SM2State.FAILED
    assert daemon._sm2_state == SM2State.FAILED
    # Assert: event_state numeric is 2 (failed)
    assert daemon._event_state_from_sm2() == 2
    # Assert: BAD_CSR_RESPONSE notification fired
    bad_csr_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.BAD_CSR_RESPONSE
    ]
    assert len(bad_csr_calls) >= 1


# ===== TC4: Event priority over supervision (AC3) =====

@pytest.mark.asyncio
async def test_event_priority_over_supervision():
    """
    EVENT items (priority=0) are dequeued before SUPERVISION (priority=1).

    Expected result:
    - When both EVENT and SUPERVISION are queued, EVENT is processed first
    - Verified by tracking send_frame call order
    - Uses queue.join() for deterministic drain (no asyncio.sleep)
    """
    daemon, mock_t = await _make_started_daemon()
    try:
        # Gate the consumer: TCP_RECONNECTING blocks dequeue without spinning
        daemon._set_sm1_state(SM1State.TCP_RECONNECTING)

        # Yield control so the consumer can enter its wait loop before we enqueue
        await asyncio.gather(*[t for t in daemon._tasks
                                if t.get_name() == 'queue_consumer'],
                              return_exceptions=True) if False else None
        # One event loop turn is sufficient — consumer is already awaiting
        await asyncio.sleep(0)

        # Enqueue SUPERVISION first, then EVENT — EVENT must still win
        await daemon._enqueue_supervision()
        await daemon._enqueue_event('BA', 'Salon', None)

        # Track call order via side_effect
        call_order: list[str] = []

        async def tracking_send_frame(frame: bytes) -> dict:
            frame_str = frame.decode('windows-1252', errors='replace')
            call_order.append('SUPERVISION' if 'NULL' in frame_str else 'EVENT')
            return {'status': 'ack', 'raw_nak': None}

        mock_t.send_frame = AsyncMock(side_effect=tracking_send_frame)

        # Ungate: consumer wakes, drains queue by priority
        daemon._set_sm1_state(SM1State.HEALTHY)

        # Deterministic drain: wait until all queued items are processed
        await daemon._queue.join()

        # Assert: EVENT processed before SUPERVISION
        assert len(call_order) >= 2, f"Expected 2+ calls, got {len(call_order)}: {call_order}"
        assert call_order[0] == 'EVENT', (
            f"EVENT should be processed first, got order: {call_order}"
        )
    finally:
        await daemon.on_stop()


# ===== TC5: Sequence number monotonicity (AC4) =====

@pytest.mark.asyncio
async def test_sequence_monotonic_across_supervision_and_alarm(daemon_no_start):
    """
    Sequence number increments on ACK only, shared across SM1 and SM2.

    Expected result:
    - _sia_seq increments by 1 on each ACK (supervision or alarm)
    - _sia_seq does NOT increment on timeout retry
    - Sequence is shared: supervision ACK + alarm ACK = contiguous increments

    Reference: SIA DC-09 § 5.5.1.5
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sia_seq = 0

    # Supervision ACK → seq increments to 1
    await daemon._send_supervision()
    seq_after_sup1 = daemon._sia_seq
    # Assert: sequence incremented after supervision ACK
    assert seq_after_sup1 == 1

    # Alarm ACK → seq increments (alarm calls seq++ before retry loop)
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event)
    seq_after_alarm = daemon._sia_seq
    # Assert: sequence incremented after alarm ACK (shared counter)
    assert seq_after_alarm == 2

    # Supervision timeout → seq should NOT increment
    daemon._sia_transport.send_frame = AsyncMock(
        return_value={'status': 'timeout', 'raw_nak': None}
    )
    await daemon._send_supervision()
    seq_after_timeout = daemon._sia_seq
    # Assert: sequence unchanged after timeout (§ 5.5.1.5)
    assert seq_after_timeout == 2

    # Next supervision ACK → seq increments again
    daemon._sia_transport.send_frame = AsyncMock(
        return_value={'status': 'ack', 'raw_nak': None}
    )
    await daemon._send_supervision()
    seq_final = daemon._sia_seq
    # Assert: back to incrementing after ACK
    assert seq_final == 3


# ===== TC6: TCP permanent failure path (AC5) =====

@pytest.mark.asyncio
async def test_tcp_strike3_to_no_network():
    """
    TCP strike=3 → TCP_RECONNECTING → NO_NETWORK after max reconnect attempts.

    Expected result:
    - Strike=3 with TCP transitions to TCP_RECONNECTING
    - _tcp_reconnect_loop probes via asyncio.open_connection; all attempts fail (OSError)
    - After max attempts → NO_NETWORK
    - _notify called with TRANSPORT_PERMANENT
    """
    daemon = _make_daemon(transport='TCP')
    mock_t = daemon._sia_transport
    daemon.send_to_jeedom = AsyncMock()  # on_stop() step-1 pushes STOPPED via _send_callback

    # The permanent-failure path schedules self.stop() as a tracked task. Replace
    # stop() with a spy so on_stop() runs faithfully WITHOUT BaseDaemon.stop()'s
    # process-level asyncio.all_tasks() sweep, which would cancel this test's own
    # driver task (see _install_stop_spy docstring).
    _install_stop_spy(daemon)

    # Get to HEALTHY first
    await daemon._send_supervision()
    assert daemon._sm1_state == SM1State.HEALTHY

    # Drive to strike=3 with timeouts → TCP_RECONNECTING spawned
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})

    # Patch asyncio.open_connection to fail so reconnect loop exhausts all attempts
    with patch('resources.siadc09d.daemon.asyncio.open_connection',
               side_effect=OSError("Connection refused")):
        await daemon._send_supervision()  # strike=1
        await daemon._send_supervision()  # strike=2
        await daemon._send_supervision()  # strike=3 → TCP_RECONNECTING + spawns loop

        # Assert: TCP_RECONNECTING entered
        assert daemon._sm1_state == SM1State.TCP_RECONNECTING

        # Drain reconnect loop — reconnect_delay_s=0.01 so completes quickly
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

    # Assert: final state is NO_NETWORK
    assert daemon._sm1_state == SM1State.NO_NETWORK

    # Assert: TRANSPORT_PERMANENT notification fired
    transport_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.TRANSPORT_PERMANENT
    ]
    assert len(transport_calls) == 1


# ===== TC7: SM2 during NO_NETWORK (AC6) =====

@pytest.mark.asyncio
async def test_sm2_fails_immediately_on_no_network():
    """
    Alarm event dequeued while SM1=NO_NETWORK fails immediately without send.

    Expected result:
    - SM2 transitions to FAILED
    - _notify called with EVENT_FAILED, last_error="no_network", attempts_made=0
    - No send_frame call made (alarm dropped, not sent)
    """
    daemon, mock_t = await _make_started_daemon()
    try:
        # Set NO_NETWORK directly
        daemon._set_sm1_state(SM1State.NO_NETWORK)

        # Reset send_frame call tracking
        mock_t.send_frame.reset_mock()

        # Enqueue alarm event
        await daemon._enqueue_event('BA', 'Salon', None)

        # Deterministic drain: wait until consumer calls task_done()
        await daemon._queue.join()

        # Assert: SM2 is FAILED
        assert daemon._sm2_state == SM2State.FAILED

        # Assert: EVENT_FAILED notification with no_network
        event_failed_calls = [
            c for c in daemon._notify.call_args_list
            if c[0][0] == ErrorCode.EVENT_FAILED
        ]
        assert len(event_failed_calls) >= 1
        ctx = event_failed_calls[-1][0][1]
        # Assert: context indicates no_network and zero attempts (dataclass attr access)
        assert ctx.last_error == 'no_network'
        assert ctx.attempts_made == 0

        # Assert: no send_frame call (alarm not sent)
        mock_t.send_frame.assert_not_called()
    finally:
        await daemon.on_stop()


# ===== TC8: on_stop() during SM2=PENDING (AC7) =====

@pytest.mark.asyncio
async def test_on_stop_during_alarm_send():
    """
    on_stop() during in-flight alarm cancels cleanly without crash.

    Expected result:
    - Transport send_frame blocks on a never-resolved Future
    - on_stop() cancels all tasks (including the blocked alarm send)
    - _tasks is empty after stop
    - Transport is closed
    """
    daemon, mock_t = await _make_started_daemon()

    # Make send_frame block indefinitely
    blocked_future: asyncio.Future = asyncio.Future()
    mock_t.send_frame = AsyncMock(side_effect=lambda _: blocked_future)

    # Enqueue alarm — consumer will try to send and block
    await daemon._enqueue_event('PA', 'Entrée', None)

    # Wait a bit for consumer to pick up the item and block
    await asyncio.sleep(0.1)

    # Call on_stop while alarm is in-flight
    await daemon.on_stop()

    # Assert: all tasks cancelled and cleaned up
    assert len(daemon._tasks) == 0

    # Assert: transport closed
    mock_t.close.assert_awaited()

    # Assert: transport reference cleared
    assert daemon._sia_transport is None


# ===== TC9: Error handler integration (AC8) =====

@pytest.mark.asyncio
async def test_error_handler_notifications_at_correct_trigger_points(daemon_no_start):
    """
    _notify() called with correct ErrorCode and context at each trigger point.

    Expected result:
    - SUPERVISION_TIMEOUT (T1) at strike=1
    - SUPERVISION_DISCONNECTED (T3) at strike=3
    - BAD_CSR_RESPONSE (T2) on NAK
    - EVENT_FAILED (T3) on max retries exhausted
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    mock_t = daemon._sia_transport

    # --- Trigger 1: Supervision timeout at strike=1 → SUPERVISION_TIMEOUT ---
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})
    await daemon._send_supervision()

    # Assert: T1 notification at strike=1
    t1_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.SUPERVISION_TIMEOUT
    ]
    assert len(t1_calls) == 1
    t1_ctx = t1_calls[0][0][1]
    # Assert: context is SM1TimeoutCtx with correct strike (dataclass attribute access)
    assert isinstance(t1_ctx, SM1TimeoutCtx)
    assert t1_ctx.strike_count == 1

    # --- Trigger 2: More timeouts to reach strike=3 → SUPERVISION_DISCONNECTED ---
    await daemon._send_supervision()  # strike=2
    await daemon._send_supervision()  # strike=3

    t3_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED
    ]
    # Assert: T3 fired once at strike=3
    assert len(t3_calls) == 1
    t3_ctx = t3_calls[0][0][1]
    assert isinstance(t3_ctx, SM1DisconnectedCtx)
    assert t3_ctx.strike_count == 3

    # Reset to HEALTHY for NAK test
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._sm1_t3_fired = False
    daemon._notify.reset_mock()

    # --- Trigger 3: NAK → BAD_CSR_RESPONSE ---
    mock_t.send_frame = AsyncMock(
        return_value={'status': 'nak', 'raw_nak': b'\xff\xff'}
    )
    await daemon._send_supervision()

    bad_csr_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.BAD_CSR_RESPONSE
    ]
    # Assert: BAD_CSR_RESPONSE fired (T2) for unparseable NAK
    assert len(bad_csr_calls) >= 1

    # Reset for SM2 test
    daemon._notify.reset_mock()
    daemon._sm1_state = SM1State.HEALTHY

    # --- Trigger 4: Alarm max retries exhausted → EVENT_FAILED ---
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})
    event = EventItem(sia_code='BA', zone='Garage', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    event_failed_calls = [
        c for c in daemon._notify.call_args_list
        if c[0][0] == ErrorCode.EVENT_FAILED
    ]
    # Assert: EVENT_FAILED fired
    assert len(event_failed_calls) >= 1
    ef_ctx = event_failed_calls[-1][0][1]
    assert isinstance(ef_ctx, EventFailedCtx)
    assert ef_ctx.sia_code == 'BA'


# ===== TC10: Logging integration (AC9) =====

@pytest.mark.asyncio
async def test_sm1_transitions_emit_french_info_and_english_debug(daemon_no_start, caplog):
    """
    SM1 transitions emit dual-line logging: French INFO + English DEBUG.

    Expected result:
    - French INFO lines present for state changes (e.g., "Supervision dégradée")
    - English DEBUG lines present (e.g., "Supervision timeout")
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY

    # Replace the mocked _log_sm1_supervision with the REAL method
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon, SIADaemon)
    # Mock ring_buffer.push_supervision_entry to avoid await-on-sync issue
    daemon._ring_buffer.push_supervision_entry = MagicMock(return_value=True)

    daemon._logger = logging.getLogger("test_logging_integration")
    daemon._sia_transport.send_frame = AsyncMock(
        return_value={'status': 'timeout', 'raw_nak': None}
    )

    with caplog.at_level(logging.DEBUG, logger="test_logging_integration"):
        await daemon._send_supervision()

    # Assert: French INFO line present
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("dégradée" in r.message.lower() or "supervision" in r.message.lower()
               for r in info_records), (
        f"Expected French INFO log about supervision, got: {[r.message for r in info_records]}"
    )

    # Assert: English DEBUG line present
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("supervision timeout" in r.message.lower() or "strike" in r.message.lower()
               for r in debug_records), (
        f"Expected English DEBUG log about timeout/strike, got: {[r.message for r in debug_records]}"
    )


@pytest.mark.asyncio
async def test_sm1_healthy_transition_logged(daemon_no_start, caplog):
    """
    SM1 transition to HEALTHY emits debug log with supervision ACK details.

    Expected result:
    - DEBUG line contains 'Supervision ACK' on ACK receipt
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.INITIALIZING

    # Use real _log_sm1_supervision
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon, SIADaemon)
    daemon._ring_buffer.push_supervision_entry = MagicMock(return_value=True)
    daemon._logger = logging.getLogger("test_healthy_log")

    with caplog.at_level(logging.DEBUG, logger="test_healthy_log"):
        await daemon._send_supervision()

    # Assert: ACK debug log present
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("ack" in r.message.lower() for r in debug_records), (
        f"Expected DEBUG log about ACK, got: {[r.message for r in debug_records]}"
    )


# ===== TC11: UDP/TCP parameterized SM1 lifecycle (AC10) =====

@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["UDP", "TCP"])
async def test_sm1_lifecycle_parameterized(transport):
    """
    SM1 lifecycle produces identical state outcomes for both UDP and TCP
    (until strike=3, where TCP diverges to TCP_RECONNECTING).

    Expected result:
    - ACK → HEALTHY for both transports
    - Timeout → DEGRADED(1) for both
    - Timeout → DEGRADED(2) for both
    - At strike=3: UDP stays DEGRADED, TCP goes TCP_RECONNECTING
    """
    daemon = _make_daemon(transport=transport)
    mock_t = daemon._sia_transport

    # ACK → HEALTHY (same for both)
    await daemon._send_supervision()
    assert daemon._sm1_state == SM1State.HEALTHY

    # Timeout → DEGRADED(1) (same for both)
    mock_t.send_frame = AsyncMock(return_value={'status': 'timeout', 'raw_nak': None})
    await daemon._send_supervision()
    assert daemon._sm1_state == SM1State.DEGRADED
    assert daemon._strike_counter == 1

    # Timeout → DEGRADED(2) (same for both)
    await daemon._send_supervision()
    assert daemon._sm1_state == SM1State.DEGRADED
    assert daemon._strike_counter == 2

    # Timeout → strike=3 (diverges)
    await daemon._send_supervision()
    assert daemon._strike_counter == 3

    if transport == "UDP":
        # Assert: UDP stays DEGRADED at strike=3 (no TCP states)
        assert daemon._sm1_state == SM1State.DEGRADED
    else:
        # Assert: TCP transitions to TCP_RECONNECTING
        assert daemon._sm1_state == SM1State.TCP_RECONNECTING

    # Cleanup: cancel TCP reconnect loop task to prevent it blocking on open_connection
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)
    daemon._tasks.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["UDP", "TCP"])
async def test_sm2_alarm_delivery_parameterized(transport):
    """
    SM2 alarm delivery produces identical outcomes for both UDP and TCP.

    Expected result:
    - ACK → SM2=CONFIRMED for both transports
    - Both transports produce event_state=1 (confirmed)
    """
    daemon = _make_daemon(transport=transport)
    daemon._sm1_state = SM1State.HEALTHY

    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event)

    # Assert: SM2 confirmed for both transports
    assert result == SM2State.CONFIRMED
    assert daemon._event_state_from_sm2() == 1


# ===== TC12: UDP never enters TCP states (AC10 constraint) =====

@pytest.mark.asyncio
async def test_udp_never_enters_tcp_states(daemon_no_start):
    """
    UDP transport never enters TCP_RECONNECTING or NO_NETWORK states.

    Expected result:
    - After 10 consecutive timeouts, UDP stays in DEGRADED with strike capped at 3
    - SM1 state never becomes TCP_RECONNECTING or NO_NETWORK
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sia_transport.send_frame = AsyncMock(
        return_value={'status': 'timeout', 'raw_nak': None}
    )

    states_seen: list[SM1State] = []
    for _ in range(10):
        await daemon._send_supervision()
        states_seen.append(daemon._sm1_state)

    # Assert: never entered TCP-specific states
    assert SM1State.TCP_RECONNECTING not in states_seen, (
        "UDP must never enter TCP_RECONNECTING"
    )
    assert SM1State.NO_NETWORK not in states_seen, (
        "UDP must never enter NO_NETWORK"
    )

    # Assert: strike capped at 3
    assert daemon._strike_counter == STRIKE_CAP


# ===== TC13: Sequence does NOT increment on SM2 retry (§ 5.5.1.5) =====

@pytest.mark.asyncio
async def test_sequence_not_incremented_on_sm2_retry(daemon_no_start):
    """
    Sequence number is NOT incremented when SM2 retries after timeout.

    Expected result:
    - The first attempt draws the wire seq; retries reuse it (story 1-5 AC4)
    - _sia_seq mirrors the wire seq
    - SIA DC-09 § 5.5.1.5: "PE shall not increment sequence on retry"
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sia_builder._sequence_tracker._seq_map[daemon._account] = 10

    # All attempts timeout, then ACK on final retry
    daemon._sia_transport.send_frame = AsyncMock(side_effect=[
        {'status': 'timeout', 'raw_nak': None},
        {'status': 'timeout', 'raw_nak': None},
        {'status': 'ack', 'raw_nak': None},
    ])

    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event, max_retries=2)

    seqs = [parse_frame_header(c.args[0])[1] for c in daemon._sia_transport.send_frame.call_args_list]
    # Assert: all three attempts carry the same wire seq (10 → 11 once)
    assert seqs == ["0011", "0011", "0011"]
    # Assert: _sia_seq mirrors the wire seq
    assert daemon._sia_seq == 11
    # Assert: final ACK confirms the event
    assert result == SM2State.CONFIRMED


# ===== TC14: Sequence wraps from 9999 to 0 =====

@pytest.mark.asyncio
async def test_sequence_wraps_at_boundary(daemon_no_start):
    """
    Sequence number wraps from 9999 → 0 per SIA DC-09 § 5.5.1.5.

    Expected result:
    - After ACK with seq=9999, next seq is 0 (modulo SIA_SEQ_MAX)
    """
    daemon = daemon_no_start
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sia_seq = 9999

    # Supervision ACK wraps seq
    await daemon._send_supervision()

    # Assert: seq wrapped to 0
    assert daemon._sia_seq == 0
