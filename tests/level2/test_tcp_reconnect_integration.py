"""Story 7.2: TCP Stall Detection, Reconnect & Ring Buffer Logging — Integration Tests.

Tests for _tcp_reconnect_loop(), D-3 dual-task race guard, state regression guard,
nominal TCP drop path, ring buffer logging, INFO command values, and queue consumer gate.

Reference: _bmad-output/implementation-artifacts/7-2-tcp-stall-detection-reconnect-ring-buffer-logging.md
"""
import asyncio
import dataclasses
from contextlib import suppress
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import (
    QUEUE_PRIORITY_SUPERVISION,
    QUEUE_TYPE_SUPERVISION,
    SIADaemon,
    SM1State,
    TCP_CONNECT_TIMEOUT_S,
    TCP_RECONNECT_MAX_ATTEMPTS,
)
from resources.siadc09d.error_handler import (
    ErrorCode,
    EventFailedCtx,
    SM1DisconnectedCtx,
)
from resources.siadc09d.messages import (
    SM1_INITIALIZING_FR,
    SM1_NO_NETWORK_FR,
)
from resources.siadc09d.ring_buffer import RingBuffer
from tests.conftest import make_daemon_preset


# ===== FIXTURES =====


def _make_tcp_daemon(connect_timeout_s: float = 10.0) -> SIADaemon:
    """Create a TCP SIADaemon with mocked callbacks for reconnect tests.

    Expected result:
    - TCP preset (reconnect_delay_s=0.01 already set in conftest.make_daemon_preset)
    - _notify, _update_info_commands, _log_sm1_supervision mocked
    - SM1 in INITIALIZING state, strike=0, _account set to valid value
    """
    preset = make_daemon_preset(transport="TCP")
    if connect_timeout_s != 10.0:
        preset = dataclasses.replace(preset, connect_timeout_s=connect_timeout_s)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = "001234"
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()

    mock_t = MagicMock()
    mock_t.start = AsyncMock()
    mock_t.close = AsyncMock()
    mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = mock_t
    return daemon


def _make_udp_daemon() -> SIADaemon:
    """Create a UDP SIADaemon for UDP-specific tests.

    Expected result:
    - UDP preset, _notify mocked, SM1 in INITIALIZING state, _account set
    """
    preset = make_daemon_preset(transport="UDP")
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = "001234"
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()

    mock_t = MagicMock()
    mock_t.start = AsyncMock()
    mock_t.close = AsyncMock()
    mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = mock_t
    return daemon


def _install_stop_spy(daemon: SIADaemon) -> list[int]:
    """Replace daemon.stop() with a spy that faithfully mirrors BaseDaemon.stop().

    BaseDaemon.stop() (base_daemon.py:133-149) calls on_stop() then cancels every
    task EXCEPT the current one. Our self-stop is scheduled as the tracked task
    'transport_permanent_stop', so when it runs, IT is the current task — the spy
    must discard itself from _tasks before delegating to on_stop(), otherwise
    on_stop()'s gather would await the running task on itself and deadlock/self-cancel.

    Expected result:
    - Returns a list whose length equals the number of stop() invocations
    - Each invocation runs the real on_stop() (transport close + task cancellation)
    """
    calls: list[int] = []

    async def _spy_stop() -> None:
        calls.append(1)
        # Mirror BaseDaemon.stop(): exclude the current (self-stop) task from _tasks
        # so on_stop()'s gather does not await this coroutine on itself.
        current = asyncio.current_task()
        daemon._tasks.discard(current)
        await daemon.on_stop()

    daemon.stop = _spy_stop  # type: ignore[method-assign]
    return calls


def _make_writer_mock() -> MagicMock:
    """Create a mock asyncio StreamWriter for open_connection return value.

    Expected result:
    - close() is a regular MagicMock (sync)
    - wait_closed() is an AsyncMock (awaitable, no-op)
    """
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()
    return mock_writer


# ===== TASK 2: _tcp_reconnect_loop() INTEGRATION TESTS =====


@pytest.mark.asyncio
async def test_reconnect_success_first_attempt():
    """Reconnect success on first attempt → SM1=INITIALIZING, strike=0, t3_fired=False.

    Expected result:
    - asyncio.open_connection succeeds on first call
    - SM1 transitions to INITIALIZING
    - _strike_counter == 0
    - _sm1_t3_fired == False
    - _sm1_state_changed event is set
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    daemon._sm1_t3_fired = True

    mock_writer = _make_writer_mock()

    daemon._sm1_state_changed.clear()
    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        await daemon._tcp_reconnect_loop()

    # Assert: SM1 transitions to INITIALIZING on success
    assert daemon._sm1_state == SM1State.INITIALIZING
    # Assert: strike counter reset to 0
    assert daemon._strike_counter == 0
    # Assert: T3 re-arm flag reset
    assert daemon._sm1_t3_fired is False
    # Assert: state_changed event woke queue consumer
    assert daemon._sm1_state_changed.is_set()


@pytest.mark.asyncio
async def test_reconnect_permanent_failure_all_attempts_timeout():
    """All 3 reconnect attempts fail with TimeoutError → SM1=NO_NETWORK, TRANSPORT_PERMANENT fired once.

    Expected result:
    - All TCP_RECONNECT_MAX_ATTEMPTS calls to open_connection raise TimeoutError
    - SM1 transitions to NO_NETWORK
    - _notify called exactly once with ErrorCode.TRANSPORT_PERMANENT
    - _sm1_state_changed event is set
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3

    daemon._sm1_state_changed.clear()
    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._tcp_reconnect_loop()

    # Assert: permanent failure state
    assert daemon._sm1_state == SM1State.NO_NETWORK
    # Assert: TRANSPORT_PERMANENT fired exactly once
    daemon._notify.assert_called_once()
    assert daemon._notify.call_args[0][0] == ErrorCode.TRANSPORT_PERMANENT
    # Assert: state_changed event woke queue consumer
    assert daemon._sm1_state_changed.is_set()
    # Assert: all 3 attempts exhausted
    assert mock_open.call_count == TCP_RECONNECT_MAX_ATTEMPTS

    # Cleanup: cancel the scheduled watchdog hand-off (real self.stop() not under test here;
    # the dedicated AC15 test exercises it — see test_reconnect_permanent_failure_schedules_self_stop)
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_permanent_failure_all_attempts_oserror():
    """All 3 reconnect attempts fail with OSError → SM1=NO_NETWORK, TRANSPORT_PERMANENT fired.

    Expected result:
    - All attempts raise OSError (connection refused)
    - SM1=NO_NETWORK after exhausting max attempts
    - _notify called once with TRANSPORT_PERMANENT
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = OSError("Connection refused")
        await daemon._tcp_reconnect_loop()

    # Assert: terminal state reached
    assert daemon._sm1_state == SM1State.NO_NETWORK
    # Assert: T3 TRANSPORT_PERMANENT fired
    assert daemon._notify.call_args[0][0] == ErrorCode.TRANSPORT_PERMANENT

    # Cleanup: cancel the scheduled watchdog hand-off (real self.stop() not under test here)
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_partial_failure_then_success():
    """First 2 attempts fail (OSError), 3rd succeeds → SM1=INITIALIZING, no TRANSPORT_PERMANENT.

    Expected result:
    - Attempts 1 and 2: OSError raised
    - Attempt 3: connection succeeds
    - SM1=INITIALIZING, strike=0, t3_fired=False
    - _notify NOT called with TRANSPORT_PERMANENT
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    daemon._sm1_t3_fired = True

    mock_writer = _make_writer_mock()

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = [
            OSError("refused"),
            OSError("refused"),
            (MagicMock(), mock_writer),
        ]
        await daemon._tcp_reconnect_loop()

    # Assert: recovery after partial failure
    assert daemon._sm1_state == SM1State.INITIALIZING
    assert daemon._strike_counter == 0
    assert daemon._sm1_t3_fired is False
    # Assert: no TRANSPORT_PERMANENT notification
    calls = [c.args[0] for c in daemon._notify.call_args_list]
    assert ErrorCode.TRANSPORT_PERMANENT not in calls
    # Assert: exactly 3 attempts made
    assert mock_open.call_count == 3


# ===== TASK 8 (AC15–AC17): SELF-STOP ON TRANSPORT_PERMANENT (Option A) =====


@pytest.mark.asyncio
async def test_reconnect_permanent_failure_schedules_self_stop():
    """Permanent TCP failure schedules a 'transport_permanent_stop' task that runs stop() once (AC15).

    Scenario:
    - All TCP_RECONNECT_MAX_ATTEMPTS reconnect probes raise TimeoutError.
    - After NO_NETWORK + TRANSPORT_PERMANENT notify, the loop must hand the
      process back to Jeedom's watchdog by SCHEDULING self.stop() (not awaiting it).

    Expected result:
    - A tracked task named 'transport_permanent_stop' is scheduled by the loop.
    - Draining _tasks runs that task, which invokes stop() exactly once.
    - stop() delegates to on_stop(): the transport is closed and reset to None.
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    stop_calls = _install_stop_spy(daemon)
    mock_transport = daemon._sia_transport  # captured before on_stop() resets it to None

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._tcp_reconnect_loop()

    # Assert: the loop scheduled the watchdog hand-off task by name (AC15 step d)
    scheduled_names = {t.get_name() for t in daemon._tasks}
    assert "transport_permanent_stop" in scheduled_names
    # Assert: NO_NETWORK reached before the hand-off
    assert daemon._sm1_state == SM1State.NO_NETWORK

    # Drain tracked tasks so the scheduled self-stop actually runs
    await asyncio.gather(*daemon._tasks, return_exceptions=True)

    # Assert: stop() ran exactly once (single clean hand-off, not per-attempt)
    assert len(stop_calls) == 1
    # Assert: stop() → on_stop() closed the transport
    mock_transport.close.assert_awaited_once()
    # Assert: on_stop() reset the transport handle to None
    assert daemon._sia_transport is None


@pytest.mark.asyncio
async def test_transport_permanent_notify_survives_self_stop():
    """The TRANSPORT_PERMANENT notify is fully dispatched before shutdown completes (AC16).

    Scenario:
    - Real _notify/_dispatch_notify (only _send_callback is mocked).
    - Permanent TCP failure fires TRANSPORT_PERMANENT, then schedules self.stop().
    - Because the notify task is scheduled BEFORE the stop task and the mocked
      _send_callback never yields, the notify runs to completion before on_stop()
      cancels tasks — so all three T3 channels reach PHP.

    Expected result:
    - message_center, notify, and error_update payloads are all sent.
    - The notify payload carries the TRANSPORT_PERMANENT error code.
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    del daemon._notify  # restore the real _notify (fixture had mocked it)
    sent: list[dict] = []

    async def _record(payload: dict) -> None:
        sent.append(payload)

    daemon._send_callback = _record  # type: ignore[method-assign]
    _install_stop_spy(daemon)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._tcp_reconnect_loop()

    # Drain tracked tasks: notify task (scheduled first) then self-stop task
    await asyncio.gather(*daemon._tasks, return_exceptions=True)

    sent_types = [p.get("type") for p in sent]
    # Assert: T3 message_center channel delivered
    assert "message_center" in sent_types
    # Assert: T3 notify channel delivered (survived the shutdown)
    assert "notify" in sent_types
    # Assert: T3 error_update channel delivered
    assert "error_update" in sent_types
    # Assert: the error_update carries the TRANSPORT_PERMANENT code
    error_update = next(p for p in sent if p.get("type") == "error_update")
    assert error_update["code"] == ErrorCode.TRANSPORT_PERMANENT.name


@pytest.mark.asyncio
async def test_other_t3_notifications_do_not_self_stop():
    """SUPERVISION_DISCONNECTED and EVENT_FAILED are T3 but never trigger self-stop (AC17).

    Scenario:
    - Real _notify/_dispatch_notify (only _send_callback is mocked).
    - Fire the two other T3 error codes directly via _notify.
    - Only TRANSPORT_PERMANENT owns the watchdog hand-off; these must not.

    Expected result:
    - No 'transport_permanent_stop' task is ever scheduled.
    - stop() is never invoked.
    """
    daemon = _make_tcp_daemon()
    del daemon._notify  # restore the real _notify (fixture had mocked it)
    daemon._send_callback = AsyncMock()
    stop_calls = _install_stop_spy(daemon)

    # Fire both other T3 error codes through the real dispatch path
    daemon._notify(ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx(
        strike_count=3,
        last_ack_time_utc=None,
        time_since_last_ack_s=None,
        supervision_interval_s=90.0,
    ))
    daemon._notify(ErrorCode.EVENT_FAILED, EventFailedCtx(
        sia_code="BA",
        sia_seq=1,
        zone_name="Zone 1",
        max_retries=3,
        attempts_made=3,
        last_error="timeout",
    ))

    # Assert: neither dispatch scheduled a self-stop task
    scheduled_names = {t.get_name() for t in daemon._tasks}
    assert "transport_permanent_stop" not in scheduled_names

    # Drain the dispatch tasks
    await asyncio.gather(*daemon._tasks, return_exceptions=True)

    # Assert: stop() was never called for non-TRANSPORT_PERMANENT T3 errors
    assert len(stop_calls) == 0


@pytest.mark.asyncio
async def test_reconnect_cancelled_error_propagates():
    """CancelledError during open_connection propagates cleanly; SM1 stays TCP_RECONNECTING.

    Expected result:
    - open_connection raises asyncio.CancelledError
    - CancelledError propagates out of _tcp_reconnect_loop (not swallowed)
    - SM1 remains TCP_RECONNECTING (zombie state acknowledged — watchdog handles)
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await daemon._tcp_reconnect_loop()

    # Assert: SM1 remains TCP_RECONNECTING (no transition on cancellation)
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING


@pytest.mark.asyncio
async def test_reconnect_loop_skips_for_udp():
    """_tcp_reconnect_loop() called on UDP daemon returns immediately without probing.

    Expected result:
    - UDP transport: method returns without calling asyncio.open_connection
    - SM1 state unchanged
    - No TRANSPORT_PERMANENT fired
    """
    daemon = _make_udp_daemon()
    daemon._sm1_state = SM1State.INITIALIZING

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        await daemon._tcp_reconnect_loop()

    # Assert: open_connection never called for UDP
    mock_open.assert_not_called()
    # Assert: no notification fired
    daemon._notify.assert_not_called()
    # Assert: SM1 state unchanged
    assert daemon._sm1_state == SM1State.INITIALIZING


# ===== TASK 3: D-3 DUAL-TASK GUARD + STATE REGRESSION TESTS =====


@pytest.mark.asyncio
async def test_d3_guard_second_tcp_drop_no_duplicate_task():
    """Second TCP drop while _tcp_reconnect_loop already running → no duplicate task spawned.

    Expected result:
    - First call to _handle_supervision_tcp_drop: SM1=TCP_RECONNECTING, task spawned
    - Second call while task still running: state regression guard fires, returns immediately
    - _tasks contains exactly one tcp_reconnect_loop entry
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    # Spy on stop() so the Option A self-stop scheduled once the drained loop reaches permanent
    # failure doesn't reach the real BaseDaemon.stop() and leak to teardown.
    _install_stop_spy(daemon)

    # Slow the reconnect loop: all attempts timeout (fast 0.01s delay)
    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()

        # First TCP drop: spawns task, transitions to TCP_RECONNECTING
        await daemon._handle_supervision_tcp_drop()
        assert daemon._sm1_state == SM1State.TCP_RECONNECTING

        task_count_after_first = sum(
            1 for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"
        )
        assert task_count_after_first == 1, "First drop should spawn exactly one task"

        # Second TCP drop: state regression guard fires (already TCP_RECONNECTING)
        await daemon._handle_supervision_tcp_drop()

        # Assert: still exactly one tcp_reconnect_loop task
        task_count_after_second = sum(
            1 for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"
        )
        assert task_count_after_second == 1, "Second drop must not spawn a duplicate task"

        # Drain the loop to avoid ResourceWarning. The loop reaches permanent failure and
        # schedules the (spied) self-stop task, which the first gather's snapshot misses — a
        # second gather drains that follow-up task.
        await asyncio.gather(*daemon._tasks, return_exceptions=True)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_d3_guard_strike3_while_loop_running_no_duplicate():
    """Strike=3 while _tcp_reconnect_loop already running → no duplicate task spawned.

    Expected result:
    - A tcp_reconnect_loop task already in _tasks (seeded manually)
    - _update_sm1_from_strike at strike=3: sets TCP_RECONNECTING but skips _track_task
    - _tasks still contains exactly one tcp_reconnect_loop after the call
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 3

    # Use a blocking event to keep the reconnect loop alive during the test
    blocker: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _slow_open(*args, **kwargs):
        await blocker

    with patch("asyncio.open_connection", new=_slow_open):
        # Manually seed a running tcp_reconnect_loop task
        _task = daemon._track_task(daemon._tcp_reconnect_loop(), name="tcp_reconnect_loop")
        await asyncio.sleep(0)  # let the task start and reach open_connection

        task_count_before = sum(
            1 for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"
        )
        assert task_count_before == 1, "One loop task must exist before second strike"

        # Second strike=3 via _update_sm1_from_strike — must NOT spawn duplicate
        await daemon._update_sm1_from_strike()

        task_count_after = sum(
            1 for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"
        )
        assert task_count_after == 1, "D-3 guard must prevent second task"

        # Unblock and drain
        blocker.cancel()
        await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_d3_guard_allows_fresh_loop_after_completion():
    """After reconnect loop completes, a new TCP drop CAN spawn a fresh loop.

    Expected result:
    - First loop runs and completes (success → INITIALIZING)
    - After completion, TCP_RECONNECTING guard does NOT apply (SM1 is now HEALTHY)
    - Second TCP drop spawns a new loop
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.HEALTHY

    mock_writer = _make_writer_mock()

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        # First loop: succeeds immediately
        mock_open.return_value = (MagicMock(), mock_writer)

        await daemon._handle_supervision_tcp_drop()
        # Join the first loop so it completes
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

        # First loop completed; SM1 is now INITIALIZING
        assert daemon._sm1_state == SM1State.INITIALIZING

        # Simulate a new TCP drop from INITIALIZING (e.g., on reconnect)
        daemon._sm1_state = SM1State.HEALTHY
        mock_open.return_value = (MagicMock(), mock_writer)

        await daemon._handle_supervision_tcp_drop()

        # Assert: a new tcp_reconnect_loop task was spawned
        active_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
        assert len(active_tasks) >= 1, "Fresh TCP drop must spawn a new reconnect loop"

        await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_state_regression_guard_no_network():
    """_handle_supervision_tcp_drop() when SM1==NO_NETWORK → returns immediately, no change.

    Expected result:
    - SM1 is NO_NETWORK (terminal state)
    - Method returns without changing state or spawning task
    - _tasks count unchanged
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.NO_NETWORK

    task_count_before = len(daemon._tasks)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        await daemon._handle_supervision_tcp_drop()
        # Assert: open_connection never called (guard fired early)
        mock_open.assert_not_called()

    # Assert: SM1 state unchanged (still NO_NETWORK)
    assert daemon._sm1_state == SM1State.NO_NETWORK
    # Assert: no new tasks spawned
    assert len(daemon._tasks) == task_count_before


@pytest.mark.asyncio
async def test_state_regression_guard_already_tcp_reconnecting():
    """_handle_supervision_tcp_drop() when SM1==TCP_RECONNECTING (no task) → returns immediately.

    Expected result:
    - SM1 is already TCP_RECONNECTING (set directly, no running task)
    - Method returns without spawning a task (pure state guard check)
    - No tcp_reconnect_loop task in _tasks after the call
    """
    daemon = _make_tcp_daemon()
    # Set state directly without spawning a task (tests the state-only guard path)
    daemon._sm1_state = SM1State.TCP_RECONNECTING

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        await daemon._handle_supervision_tcp_drop()
        mock_open.assert_not_called()

    # Assert: no tcp_reconnect_loop task was spawned
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 0, "State guard must prevent task spawn when TCP_RECONNECTING"


# ===== TASK 4: NOMINAL TCP DROP PATH + TCP STALL DETECTION =====


@pytest.mark.asyncio
async def test_nominal_tcp_drop_from_healthy():
    """_handle_supervision_tcp_drop() when SM1==HEALTHY → TCP_RECONNECTING, task spawned.

    Expected result:
    - SM1 starts HEALTHY
    - After call: SM1==TCP_RECONNECTING
    - tcp_reconnect_loop task appears in _tasks
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.HEALTHY

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._handle_supervision_tcp_drop()

    # Assert: transitioned to TCP_RECONNECTING
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    # Assert: reconnect task was spawned
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 1, "tcp_reconnect_loop must be in _tasks"

    # Cleanup: cancel the spawned loop rather than run it to permanent failure — this test
    # only asserts the loop was spawned. Running it would schedule the real Option A self.stop()
    # (exercised by test_reconnect_permanent_failure_schedules_self_stop) and leak it to teardown.
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_nominal_tcp_drop_from_degraded():
    """_handle_supervision_tcp_drop() when SM1==DEGRADED → same transition as from HEALTHY.

    Expected result:
    - SM1 starts DEGRADED
    - After call: SM1==TCP_RECONNECTING
    - tcp_reconnect_loop task appears in _tasks
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._handle_supervision_tcp_drop()

    # Assert: transitioned to TCP_RECONNECTING from DEGRADED
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    # Assert: task spawned
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 1

    # Cleanup: cancel the spawned loop rather than run it to permanent failure (see
    # test_reconnect_permanent_failure_schedules_self_stop for the Option A self.stop() path).
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_tcp_stall_detection_timeout_path():
    """_send_supervision() at strike=2→3 on TCP → SM1=TCP_RECONNECTING, task spawned.

    Expected result:
    - TCP daemon at DEGRADED(strike=2)
    - Timeout response triggers strike=3 via _send_supervision():
      SM1==TCP_RECONNECTING after the call
      tcp_reconnect_loop task present in _tasks
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    mock_t = daemon._sia_transport
    mock_t.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._send_supervision()

    # Assert: TCP stall detection triggered at strike=3
    assert daemon._strike_counter == 3
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    # Assert: reconnect task spawned via _update_sm1_from_strike
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 1

    # Cleanup: cancel the spawned loop rather than run it to permanent failure (see
    # test_reconnect_permanent_failure_schedules_self_stop for the Option A self.stop() path).
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_tcp_stall_detection_nak_path():
    """_send_supervision() NAK at strike=2→3 on TCP → SM1=TCP_RECONNECTING, task spawned.

    Expected result:
    - TCP daemon at DEGRADED(strike=2)
    - NAK response triggers strike=3 via _send_supervision():
      SM1==TCP_RECONNECTING after the call
      tcp_reconnect_loop task present in _tasks
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    mock_t = daemon._sia_transport
    mock_t.send_frame = AsyncMock(return_value={
        "status": "nak",
        "raw_nak": b"\x0c\x1e\x0f\x13\x05\x0a",
    })

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
            mock_parse.return_value = datetime.now(timezone.utc)
            await daemon._send_supervision()

    # Assert: NAK path also triggers TCP stall detection
    assert daemon._strike_counter == 3
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 1

    # Cleanup: cancel the spawned loop rather than run it to permanent failure (see
    # test_reconnect_permanent_failure_schedules_self_stop for the Option A self.stop() path).
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_udp_strike3_no_reconnect_task():
    """UDP at strike=3 → stays DEGRADED, no tcp_reconnect_loop task, supervision_value==0.

    Expected result:
    - UDP daemon at DEGRADED(strike=2)
    - Timeout at strike=3: SM1 stays DEGRADED (not TCP_RECONNECTING)
    - No tcp_reconnect_loop task in _tasks
    - _supervision_value() == 0
    """
    daemon = _make_udp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    mock_t = daemon._sia_transport
    mock_t.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})

    await daemon._send_supervision()

    # Assert: UDP stays DEGRADED at strike=3
    assert daemon._strike_counter == 3
    assert daemon._sm1_state == SM1State.DEGRADED
    # Assert: no tcp_reconnect_loop for UDP
    loop_tasks = [t for t in daemon._tasks if t.get_name() == "tcp_reconnect_loop"]
    assert len(loop_tasks) == 0
    # Assert: supervision_value is 0 at DEGRADED(3)
    assert daemon._supervision_value() == 0


# ===== TASK 5: RING BUFFER AND INFO COMMANDS AROUND TCP =====


@pytest.mark.asyncio
async def test_info_commands_after_reconnect_success():
    """After successful reconnect (SM1=INITIALIZING), supervision_value==1 and correct label.

    Expected result:
    - _tcp_reconnect_loop() transitions SM1 to INITIALIZING on success
    - _supervision_value() returns 1 (impaired: INITIALIZING)
    - _supervision_label() returns SM1_INITIALIZING_FR ("DÉMARRAGE…")
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    daemon._sm1_t3_fired = True

    mock_writer = _make_writer_mock()

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.return_value = (MagicMock(), mock_writer)
        await daemon._tcp_reconnect_loop()

    # Assert: state is INITIALIZING after successful reconnect
    assert daemon._sm1_state == SM1State.INITIALIZING
    # Assert: supervision_value == 1 (impaired) for INITIALIZING
    assert daemon._supervision_value() == 1
    # Assert: label is INITIALIZING string
    assert daemon._supervision_label() == SM1_INITIALIZING_FR


@pytest.mark.asyncio
async def test_info_commands_after_permanent_failure():
    """After permanent failure (SM1=NO_NETWORK), supervision_value==0 and correct label.

    Expected result:
    - _tcp_reconnect_loop() all attempts fail → SM1=NO_NETWORK
    - _supervision_value() returns 0 (problem)
    - _supervision_label() returns SM1_NO_NETWORK_FR ("HORS RÉSEAU — arrêt")
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    # Spy on stop() so the Option A self-stop scheduled at permanent failure doesn't reach the
    # real BaseDaemon.stop() and leak to teardown (dedicated test covers the self-stop wiring).
    _install_stop_spy(daemon)

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._tcp_reconnect_loop()

    # Assert: NO_NETWORK after permanent failure
    assert daemon._sm1_state == SM1State.NO_NETWORK
    # Assert: supervision_value == 0 (problem)
    assert daemon._supervision_value() == 0
    # Assert: label is NO_NETWORK string
    assert daemon._supervision_label() == SM1_NO_NETWORK_FR

    # Cleanup: drain the scheduled self-stop task
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_ring_buffer_timeout_at_strike3_is_not_routine():
    """Timeout event at strike=3 pushes ring buffer entry with is_routine=False.

    Uses the real _log_sm1_supervision (not mocked) with a real RingBuffer instance.

    Expected result:
    - Ring buffer has at least one entry after timeout at strike=3
    - The entry has level == "warning" (timeout at strike=3 uses warning level)
    - Entry context contains strike == 3 (state-changing event)
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2
    # Spy on stop() so the Option A self-stop scheduled once the spawned loop reaches permanent
    # failure doesn't reach the real BaseDaemon.stop() and leak to teardown.
    _install_stop_spy(daemon)

    # Use real ring buffer and real _log_sm1_supervision — do NOT mock them
    daemon._ring_buffer = RingBuffer()
    # Restore real method (overrides the AsyncMock set in _make_tcp_daemon)
    del daemon.__dict__["_log_sm1_supervision"]  # remove instance-level mock
    daemon._send_callback = AsyncMock()  # required by real _log_sm1_supervision

    mock_t = daemon._sia_transport
    mock_t.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})

    with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = asyncio.TimeoutError()
        await daemon._send_supervision()
        # Drain the spawned reconnect loop (then its scheduled self-stop) while open_connection
        # is still patched — otherwise the loop runs the real network path after the patch exits.
        await asyncio.gather(*daemon._tasks, return_exceptions=True)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

    # Assert: ring buffer has entries after timeout at strike=3
    buffer_entries = list(daemon._ring_buffer._buffer)
    assert len(buffer_entries) > 0, "Ring buffer must have at least one entry after timeout"
    # Assert: entry has warning level (strike=3 timeout is logged as warning)
    warning_entries = [e for e in buffer_entries if e["level"] == "warning"]
    assert len(warning_entries) > 0, "Strike=3 timeout must push a warning entry"
    # Assert: entry context has strike=3 (non-routine state change)
    strike3_entries = [e for e in warning_entries if e.get("context", {}).get("strike") == 3]
    assert len(strike3_entries) > 0, "Entry context must include strike=3"
    # Assert: is_routine=False (AC10 explicit requirement)
    non_routine_entries = [e for e in strike3_entries if e.get("is_routine") is False]
    assert len(non_routine_entries) > 0, "Strike=3 timeout entry must have is_routine=False"


# ===== TASK 6: QUEUE CONSUMER GATE TESTS =====


@pytest.mark.asyncio
async def test_queue_consumer_gate_blocks_during_tcp_reconnecting():
    """Queue consumer does not consume items while SM1==TCP_RECONNECTING.

    Expected result:
    - Consumer task started, supervision item enqueued
    - SM1 set to TCP_RECONNECTING
    - After 3 event-loop yields: item still in queue (not consumed)
    - SM1 set to INITIALIZING via _set_sm1_state
    - After multiple event-loop yields: item consumed (queue empty)
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.HEALTHY

    # Replace _send_supervision with a no-op to avoid transport calls
    daemon._send_supervision = AsyncMock()

    consumer_task = asyncio.create_task(daemon._queue_consumer())
    try:
        # Set SM1=TCP_RECONNECTING BEFORE enqueuing (consumer sees it immediately)
        daemon._set_sm1_state(SM1State.TCP_RECONNECTING)

        # Enqueue a supervision item
        counter = next(daemon._queue_counter)
        await daemon._queue.put(
            (QUEUE_PRIORITY_SUPERVISION, counter, QUEUE_TYPE_SUPERVISION, {})
        )

        # Yield control multiple times: item must stay in queue
        for _ in range(3):
            await asyncio.sleep(0)

        # Assert: item not consumed (still in queue)
        assert not daemon._queue.empty(), (
            "Queue consumer must NOT consume items while SM1==TCP_RECONNECTING"
        )

        # Transition SM1 to INITIALIZING — consumer should wake and consume
        daemon._set_sm1_state(SM1State.INITIALIZING)

        # Yield control multiple times: consumer should now process the item
        for _ in range(5):
            await asyncio.sleep(0)

        # Assert: item consumed
        assert daemon._queue.empty(), (
            "Queue consumer must consume items after SM1 leaves TCP_RECONNECTING"
        )
        daemon._send_supervision.assert_called_once()

    finally:
        consumer_task.cancel()
        with suppress(asyncio.CancelledError):
            await consumer_task


@pytest.mark.asyncio
async def test_queue_consumer_gate_multiple_items_all_consumed_after_recovery():
    """3 supervision items accumulate while TCP_RECONNECTING; all consumed after recovery.

    Expected result:
    - 3 SUPERVISION items enqueued while SM1==TCP_RECONNECTING
    - After SM1 → INITIALIZING: all 3 items consumed sequentially (no loss)
    - _send_supervision called exactly 3 times
    """
    daemon = _make_tcp_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING

    # Replace _send_supervision with a no-op to avoid transport calls
    daemon._send_supervision = AsyncMock()

    consumer_task = asyncio.create_task(daemon._queue_consumer())
    try:
        # Enqueue 3 supervision items while TCP_RECONNECTING
        for _ in range(3):
            counter = next(daemon._queue_counter)
            await daemon._queue.put(
                (QUEUE_PRIORITY_SUPERVISION, counter, QUEUE_TYPE_SUPERVISION, {})
            )

        # Yield: items must stay in queue while TCP_RECONNECTING
        for _ in range(3):
            await asyncio.sleep(0)

        # Assert: nothing consumed yet
        assert daemon._queue.qsize() == 3, (
            "All 3 items must accumulate while TCP_RECONNECTING"
        )

        # Recovery: transition to INITIALIZING
        daemon._set_sm1_state(SM1State.INITIALIZING)

        # Yield enough times for all 3 items to be processed (each is an AsyncMock no-op)
        for _ in range(15):
            await asyncio.sleep(0)

        # Assert: all 3 items consumed
        assert daemon._queue.empty(), "All 3 items must be consumed after recovery"
        assert daemon._send_supervision.call_count == 3, (
            f"Expected 3 _send_supervision calls, got {daemon._send_supervision.call_count}"
        )

    finally:
        consumer_task.cancel()
        with suppress(asyncio.CancelledError):
            await consumer_task


# ===== TASK 0.3 (Story 7.3): CONNECT_TIMEOUT_S REGRESSION TEST =====


@pytest.mark.asyncio
async def test_reconnect_uses_preset_connect_timeout_not_hardcoded_constant():
    """_tcp_reconnect_loop() passes preset.connect_timeout_s to asyncio.wait_for, not hardcoded 10s.

    Regression guard: before fix, TCP_CONNECT_TIMEOUT_S (10s) was hardcoded in the wait_for
    call. This verifies the fix (self._preset.connect_timeout_s) is correct and that the old
    constant is NOT used.

    Expected result:
    - Preset has connect_timeout_s=0.5 (deliberately != TCP_CONNECT_TIMEOUT_S=10s)
    - asyncio.wait_for is called with timeout=0.5 on every reconnect attempt
    - timeout=TCP_CONNECT_TIMEOUT_S (10s) is never passed to wait_for
    """
    preset_timeout = 0.5
    assert preset_timeout != TCP_CONNECT_TIMEOUT_S, (
        "Test requires preset_timeout != hardcoded constant to detect regression"
    )

    daemon = _make_tcp_daemon(connect_timeout_s=preset_timeout)
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 3
    # Spy on stop() so the Option A self-stop scheduled at permanent failure doesn't reach the
    # real BaseDaemon.stop() and leak to teardown (dedicated test covers the self-stop wiring).
    _install_stop_spy(daemon)

    captured_timeouts: list[float] = []

    async def _spy_wait_for(coro, *, timeout, **kwargs):
        captured_timeouts.append(timeout)
        raise asyncio.TimeoutError()

    # Patch in daemon's own asyncio namespace so the spy intercepts the wait_for call
    with patch("resources.siadc09d.daemon.asyncio.wait_for", side_effect=_spy_wait_for):
        await daemon._tcp_reconnect_loop()

    # Assert: wait_for was called for each reconnect attempt
    assert len(captured_timeouts) == TCP_RECONNECT_MAX_ATTEMPTS, (
        f"Expected {TCP_RECONNECT_MAX_ATTEMPTS} wait_for calls, got {len(captured_timeouts)}"
    )
    # Assert: preset value used (not hardcoded constant)
    for t in captured_timeouts:
        assert t == preset_timeout, (
            f"wait_for called with timeout={t}, expected preset.connect_timeout_s={preset_timeout}"
        )
    # Assert: hardcoded constant was never used
    assert TCP_CONNECT_TIMEOUT_S not in captured_timeouts, (
        f"Old hardcoded constant {TCP_CONNECT_TIMEOUT_S}s must not be passed to wait_for"
    )

    # Cleanup: drain the scheduled self-stop task
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== AC22: on_stop() SELF-CANCELLATION GUARD =====


@pytest.mark.asyncio
async def test_on_stop_does_not_self_cancel_when_run_as_tracked_task():
    """on_stop() run AS the tracked self-stop task must not cancel itself (AC22).

    Reproduces the real shutdown path: the watchdog schedules self.stop() as the tracked
    task 'transport_permanent_stop' (daemon.py:1146), and BaseDaemon.stop() then calls
    on_stop(). When on_stop() executes, the CURRENT task IS that tracked task, so it is a
    member of self._tasks. on_stop() step-3 (cancel loop) and step-4 (gather) must exclude
    asyncio.current_task(), mirroring BaseDaemon.stop()'s own guard (base_daemon.py:142) —
    otherwise on_stop() cancels/awaits itself and surfaces a stray 'CancelledError' at Exit 0.

    Unlike _install_stop_spy() (which discards the current task before delegating, as a
    workaround), this test drives on_stop() directly as a tracked task to exercise the guard
    in production code.

    Expected result:
    - The tracked task running on_stop() completes without being cancelled (no self-cancel)
    - on_stop() still cancels the OTHER tracked tasks (shutdown remains effective)
    - Step-5 is reached: the transport is closed and reset to None
    """
    daemon = _make_tcp_daemon()
    daemon._send_callback = AsyncMock()  # isolate step-1 IPC push from real transport

    # A long-lived "other" task that on_stop() is expected to cancel during shutdown
    async def _other() -> None:
        await asyncio.Event().wait()

    other = asyncio.ensure_future(_other())
    daemon._tasks.add(other)
    other.add_done_callback(daemon._tasks.discard)

    # Run on_stop() AS a tracked task, exactly like the scheduled 'transport_permanent_stop'
    stop_task = asyncio.ensure_future(daemon.on_stop())
    daemon._tasks.add(stop_task)
    stop_task.add_done_callback(daemon._tasks.discard)

    # Bound the await: a self-cancel guard bug makes on_stop() gather on itself (step-4),
    # which deadlocks. Treat a timeout as the defect signal so the test fails fast, not hangs.
    try:
        await asyncio.wait_for(asyncio.shield(stop_task), timeout=2.0)
    except asyncio.TimeoutError:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        pytest.fail(
            "on_stop() deadlocked awaiting itself — step-4 gather must exclude "
            "asyncio.current_task()"
        )

    # Assert: the self-stop task must NOT have cancelled itself
    assert not stop_task.cancelled(), (
        "on_stop() self-cancelled the running 'transport_permanent_stop' task — "
        "step-3/step-4 must exclude asyncio.current_task()"
    )
    # Assert: on_stop() completed without raising (CancelledError would surface at Exit 0)
    assert stop_task.exception() is None
    # Assert: the OTHER task was still cancelled — shutdown stays effective
    assert other.cancelled()
    # Assert: step-5 reached — transport closed and handle reset to None
    assert daemon._sia_transport is None

    # Cleanup: ensure the other task is fully drained
    await asyncio.gather(other, return_exceptions=True)
