"""Story 5-3: PriorityQueue Task Coordination — Consumer Integration Tests (TC12–TC20).

Tests cover:
- Consumer happy path: EVENT dequeued → _send_with_retry() called
- Consumer task_done() after dispatch
- Logging of dequeue operations
- SM1 TCP_RECONNECTING: items held in queue (gate on _sm1_state_changed), dispatched after recovery
- Backpressure: multiple items processed in priority order without deadlock

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-3-priorityqueue-task-coordination.md Task 10
"""

import asyncio
import pytest
from resources.siadc09d.sia_transport import SIATransportResult
from tests.conftest import make_daemon_preset
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from resources.siadc09d.daemon import (
    SIADaemon,
    SM1State,
    SM2State,
    QUEUE_PRIORITY_EVENT,
    QUEUE_PRIORITY_SUPERVISION,
    QUEUE_TYPE_EVENT,
    QUEUE_TYPE_SUPERVISION,
    MAX_RETRY_DEFAULT,
)
from resources.siadc09d.error_handler import ErrorCode


# ===== FIXTURES =====

@pytest.fixture
def mock_daemon():
    """Create a SIADaemon instance with mocked transport and callbacks."""
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=make_daemon_preset())

    daemon._logger = MagicMock()
    daemon._preset = MagicMock(
        crc_format='SIA',
        supervision_interval_s=10,
        encryption_enabled=False,
        max_retries=3,
    )
    daemon._account = '001234'
    daemon._receiver_prefix = None
    daemon._account_prefix = 'L0'
    daemon._sia_seq = 0
    daemon._notify = MagicMock()
    daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))
    daemon._update_info_commands = AsyncMock()
    daemon._encryption_key = b''
    daemon._transport = 'UDP'

    # SM states
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sm2_state = SM2State.IDLE
    daemon._strike_counter = 0
    daemon._sm1_t3_fired = False
    daemon._last_supervision_ack = None

    return daemon


# ===== TC12–TC14: Consumer happy path =====

class TestConsumerHappyPath:
    """TC12–TC14: Queue consumer routes EVENT to _send_with_retry correctly."""

    @pytest.mark.asyncio
    async def test_tc12_event_dequeued_routes_to_send_with_retry(self, mock_daemon):
        """Enqueue EVENT → consumer dequeues → _send_with_retry() is called.

        Expected result:
        - EVENT enqueued via _enqueue_event()
        - _queue_consumer() dequeues it
        - _send_with_retry() is called with an EventItem having correct sia_code and zone
        - Queue is empty after processing
        """
        # Arrange: Spy on _send_with_retry
        original_send = mock_daemon._send_with_retry
        send_calls = []

        async def spy_send_with_retry(event_item, max_retries=3):
            send_calls.append((event_item.sia_code, event_item.zone))
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = spy_send_with_retry

        # Act: Enqueue one event and run consumer for one cycle
        await mock_daemon._enqueue_event("BA", "Salon", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())
        # Wait for queue to drain
        await mock_daemon._queue.join()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: _send_with_retry was called once with correct args
        assert len(send_calls) == 1, f"Expected 1 call, got {len(send_calls)}"
        assert send_calls[0] == ("BA", "Salon")

        # Assert: Queue is empty after processing
        assert mock_daemon._queue.empty()

    @pytest.mark.asyncio
    async def test_tc13_consumer_logs_dequeue_with_counter(self, mock_daemon):
        """Consumer logs dequeue with item_type and counter value.

        Expected result:
        - After dequeuing, logger.debug is called with item_type and counter info
        - Log message includes "Dequeued" keyword and QUEUE_TYPE_EVENT
        """
        # Arrange: Mock _send_with_retry to prevent actual network call
        mock_daemon._send_with_retry = AsyncMock(return_value=SM2State.CONFIRMED)

        # Act: Enqueue one event and run consumer
        await mock_daemon._enqueue_event("FA", "Cuisine", None, 3)
        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())
        await mock_daemon._queue.join()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: Debug was called with dequeue info
        debug_calls = [str(c) for c in mock_daemon._logger.debug.call_args_list]
        dequeue_logged = any("Dequeued" in msg and "EVENT" in msg for msg in debug_calls)
        assert dequeue_logged, (
            f"Expected debug log with 'Dequeued EVENT', got calls: {debug_calls}"
        )

    @pytest.mark.asyncio
    async def test_tc14_consumer_calls_task_done_after_dispatch(self, mock_daemon):
        """Consumer calls queue.task_done() after every dispatch cycle.

        Expected result:
        - After processing one EVENT, queue.join() completes (task_done was called)
        - queue.join() would block indefinitely if task_done() is never called
        - queue.join() completes within timeout → confirms task_done() was called
        """
        # Arrange
        mock_daemon._send_with_retry = AsyncMock(return_value=SM2State.CONFIRMED)

        # Act: Enqueue one event
        await mock_daemon._enqueue_event("PA", "Garage", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Assert: queue.join() completes — only possible if task_done() was called
        # If task_done() is missing, this will timeout and fail
        try:
            await asyncio.wait_for(mock_daemon._queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail(
                "queue.join() timed out — task_done() was NOT called after dispatch"
            )
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass


# ===== TC15–TC17: SM1 TCP_RECONNECTING handling =====

class TestTcpReconnectingBehavior:
    """TC15–TC17: Consumer handles TCP_RECONNECTING state correctly."""

    @pytest.mark.asyncio
    async def test_tc15_event_held_in_queue_during_tcp_reconnecting(self, mock_daemon):
        """EVENT stays in the queue (not dequeued) while SM1 is TCP_RECONNECTING.

        Expected result:
        - SM1 starts TCP_RECONNECTING; consumer waits on _sm1_state_changed gate
        - _send_with_retry is NOT called while TCP_RECONNECTING
        - After SM1 recovers (HEALTHY via _set_sm1_state), consumer unblocks,
          dequeues the held EVENT, and calls _send_with_retry exactly once
        - Queue empty after processing

        Strategy: Flip SM1 to HEALTHY and fire _sm1_state_changed after a brief yield,
        then wait for queue.join(). No spy_put, no re-enqueue involved.
        """
        # Arrange: collect _send_with_retry calls
        sent_events: list = []

        async def capture_and_recover(event_item, max_retries=3):
            sent_events.append((event_item.sia_code, max_retries))
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = capture_and_recover
        mock_daemon._sm1_state = SM1State.TCP_RECONNECTING

        # Act: Enqueue event and start consumer
        await mock_daemon._enqueue_event("BA", "Salon", None, 3)
        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Allow consumer to enter the gate (one event loop iteration)
        await asyncio.sleep(0)

        # Assert: _send_with_retry not yet called (consumer is still waiting)
        assert len(sent_events) == 0, "_send_with_retry should not have been called yet"

        # Recover SM1: set state and fire event (as _set_sm1_state() does)
        mock_daemon._sm1_state = SM1State.HEALTHY
        mock_daemon._sm1_state_changed.set()

        # Wait for queue to drain (consumer now dequeues and sends the held EVENT)
        await asyncio.wait_for(mock_daemon._queue.join(), timeout=3.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: _send_with_retry called after SM1 recovered
        assert len(sent_events) == 1, f"Expected 1 send, got {len(sent_events)}"
        assert sent_events[0][0] == "BA"

        # Assert: Queue drained
        assert mock_daemon._queue.empty()

    @pytest.mark.asyncio
    async def test_tc16_held_event_uses_original_retry_budget(self, mock_daemon):
        """EVENT held in queue during TCP_RECONNECTING retains its original retry budget.

        Expected result:
        - EVENT enqueued with retries_left=1 (near exhaustion)
        - Consumer gates on TCP_RECONNECTING, does NOT dequeue the item
        - After SM1 recovers, consumer dequeues the item and passes its retries_left=1
          as max_retries to _send_with_retry (no budget reset — item was never touched)
        Note: SIA DC-09 § 5.5.1.5 specifies sequence number handling for retries; the gate
        approach preserves the original payload (counter + retries_left) unchanged since
        the item is never dequeued during TCP_RECONNECTING — it simply waits in the queue.
        """
        # Arrange: capture max_retries from _send_with_retry call
        captured_max_retries: list = []

        async def capture_send(event_item, max_retries=3):
            captured_max_retries.append(max_retries)
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = capture_send
        mock_daemon._sm1_state = SM1State.TCP_RECONNECTING

        # Act: Enqueue event with near-exhausted retry budget
        await mock_daemon._enqueue_event("BA", "Hall", None, retries_left=1)
        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Allow consumer to enter the gate
        await asyncio.sleep(0)

        # Assert: not yet sent
        assert len(captured_max_retries) == 0

        # Recover SM1
        mock_daemon._sm1_state = SM1State.HEALTHY
        mock_daemon._sm1_state_changed.set()

        # Wait for queue to drain
        await asyncio.wait_for(mock_daemon._queue.join(), timeout=3.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: _send_with_retry called with the original retries_left=1 from the payload
        assert captured_max_retries, "_send_with_retry was never called"
        assert captured_max_retries[0] == 1, (
            f"Expected max_retries=1 (original payload retained), got {captured_max_retries[0]}"
        )

    @pytest.mark.asyncio
    async def test_tc17_supervision_held_in_queue_during_tcp_reconnecting(self, mock_daemon):
        """SUPERVISION stays in queue (not dequeued) while SM1 is TCP_RECONNECTING.

        Expected result:
        - SM1 state = TCP_RECONNECTING; consumer waits on _sm1_state_changed gate
        - _send_supervision is NOT called while TCP_RECONNECTING
        - After SM1 recovers (HEALTHY), consumer unblocks, dequeues, and calls _send_supervision
        - Queue empty after processing
        - Debug log contains "waiting for state change"
        """
        # Arrange: SM1 in TCP_RECONNECTING
        mock_daemon._sm1_state = SM1State.TCP_RECONNECTING
        supervision_called = asyncio.Event()

        async def spy_send_supervision():
            supervision_called.set()

        mock_daemon._send_supervision = spy_send_supervision

        # Act: Enqueue supervision and start consumer
        await mock_daemon._enqueue_supervision()
        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Allow consumer to enter the gate
        await asyncio.sleep(0)

        # Assert: _send_supervision was NOT called yet (item still in queue)
        assert not supervision_called.is_set(), "_send_supervision should not be called yet"
        assert mock_daemon._queue.qsize() == 1, "Item should still be in queue"

        # Recover SM1: fire state change event
        mock_daemon._sm1_state = SM1State.HEALTHY
        mock_daemon._sm1_state_changed.set()

        # Wait for supervision to be dispatched
        await asyncio.wait_for(mock_daemon._queue.join(), timeout=2.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: _send_supervision was eventually called after recovery
        assert supervision_called.is_set(), "_send_supervision was never called after SM1 recovery"

        # Assert: Queue is empty
        assert mock_daemon._queue.empty()

        # Assert: Debug log contains gate wait message
        debug_calls = [str(c) for c in mock_daemon._logger.debug.call_args_list]
        gate_logged = any(
            "TCP_RECONNECTING" in msg and "waiting for state change" in msg
            for msg in debug_calls
        )
        assert gate_logged, (
            f"Expected 'TCP_RECONNECTING: queue consumer waiting' debug log, got: {debug_calls}"
        )


# ===== TC18–TC20: Backpressure and ordering =====

class TestBackpressureAndOrdering:
    """TC18–TC20: Consumer handles multiple items correctly without deadlock."""

    @pytest.mark.asyncio
    async def test_tc18_backpressure_multiple_events_processed_in_order(self, mock_daemon):
        """Multiple EVENTs queued and processed in FIFO order without deadlock.

        Expected result:
        - 3 alarm events enqueued with zones Zone1, Zone2, Zone3
        - Consumer processes all 3 in FIFO order (counter 0→1→2)
        - _send_with_retry called 3 times, with zones in original order
        - No deadlock; queue.join() completes
        """
        # Arrange: Capture send_with_retry calls
        send_calls = []

        async def spy_send(event_item, max_retries=3):
            send_calls.append(event_item.zone)
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = spy_send

        # Act: Enqueue 3 events
        zones = ["Zone1", "Zone2", "Zone3"]
        for i, zone in enumerate(zones):
            await mock_daemon._enqueue_event("BA", zone, None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())
        await asyncio.wait_for(mock_daemon._queue.join(), timeout=3.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: All 3 events processed in FIFO order
        assert send_calls == zones, f"Expected {zones}, got {send_calls}"

    @pytest.mark.asyncio
    async def test_tc19_event_wins_over_supervision_under_load(self, mock_daemon):
        """EVENTs are always processed before SUPERVISION items.

        Expected result:
        - 2 EVENTs and 1 SUPERVISION enqueued (supervision enqueued first)
        - Consumer processes both EVENTs before the SUPERVISION
        - Order: EVENT→EVENT→SUPERVISION (priority 0→0→1)
        """
        # Arrange
        processed_types = []

        async def spy_send(event_item, max_retries=3):
            processed_types.append("EVENT")
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = spy_send
        mock_daemon._send_supervision = AsyncMock(
            side_effect=lambda: processed_types.append("SUPERVISION") or None
        )

        # Act: Enqueue supervision first (lower priority), then 2 events
        await mock_daemon._enqueue_supervision()
        await mock_daemon._enqueue_event("BA", "Zone1", None, 3)
        await mock_daemon._enqueue_event("FA", "Zone2", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())
        await asyncio.wait_for(mock_daemon._queue.join(), timeout=3.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: Both EVENTs processed before SUPERVISION
        assert processed_types == ["EVENT", "EVENT", "SUPERVISION"], (
            f"Expected EVENT→EVENT→SUPERVISION, got {processed_types}"
        )

    @pytest.mark.asyncio
    async def test_tc20_no_deadlock_with_slow_sender(self, mock_daemon):
        """Consumer processes items without deadlock even with slow sender.

        Expected result:
        - _send_with_retry introduces a short delay (mocked with asyncio.sleep)
        - 2 EVENTs still processed within timeout
        - No deadlock; queue.join() completes before timeout
        """
        # Arrange: Slow sender (100ms per call)
        async def slow_send(event_item, max_retries=3):
            await asyncio.sleep(0.05)
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = slow_send

        # Act: Enqueue 2 events
        await mock_daemon._enqueue_event("BA", "Zone1", None, 3)
        await mock_daemon._enqueue_event("FA", "Zone2", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Assert: No deadlock — completes within 2 seconds
        try:
            await asyncio.wait_for(mock_daemon._queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Deadlock detected: queue.join() timed out after 2s")
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass


# ===== TC-NEW-A: NO_NETWORK state drops all items =====

class TestNoNetworkBehavior:
    """TC-NEW-A: Consumer drops all items silently when SM1=NO_NETWORK."""

    @pytest.mark.asyncio
    async def test_no_network_drops_supervision_and_fails_event(self, mock_daemon):
        """SUPERVISION dropped and EVENT failed with notification when SM1=NO_NETWORK.

        Expected result:
        - SM1 state = NO_NETWORK (terminal — daemon stopping)
        - Consumer dequeues SUPERVISION → does NOT call _send_supervision()
        - Consumer dequeues EVENT → does NOT call _send_with_retry()
        - EVENT fires _notify(EVENT_FAILED) and sets SM2=FAILED (ADR-04: zero silent failures)
        - Queue empty after processing both items
        - task_done() called for each item (queue.join() completes)

        Covers AC8: NO_NETWORK (terminal) — supervision dropped, events failed with notification.
        """
        # Arrange: SM1 in NO_NETWORK (terminal state)
        mock_daemon._sm1_state = SM1State.NO_NETWORK
        mock_daemon._send_supervision = AsyncMock()
        mock_daemon._send_with_retry = AsyncMock()

        # Act: Enqueue one of each type
        await mock_daemon._enqueue_supervision()
        await mock_daemon._enqueue_event("BA", "Salon", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Assert: queue drains (task_done called for both items)
        try:
            await asyncio.wait_for(mock_daemon._queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("queue.join() timed out — task_done() not called for NO_NETWORK items")
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

        # Assert: neither send handler was called
        mock_daemon._send_supervision.assert_not_called()
        mock_daemon._send_with_retry.assert_not_called()

        # Assert: queue is empty (items not re-enqueued)
        assert mock_daemon._queue.empty()

        # Assert: supervision drop logged
        debug_calls = [str(c) for c in mock_daemon._logger.debug.call_args_list]
        assert any(
            "NO_NETWORK" in m and "SUPERVISION dropped" in m for m in debug_calls
        ), f"Expected 'NO_NETWORK: SUPERVISION dropped' in debug log, got: {debug_calls}"

        # Assert: event failed with notification (ADR-04: zero silent failures)
        assert any(
            "NO_NETWORK" in m and "EVENT failed" in m for m in debug_calls
        ), f"Expected 'NO_NETWORK: EVENT failed' in debug log, got: {debug_calls}"

        # Assert: SM2 set to FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED

        # Assert: _notify called with EVENT_FAILED
        mock_daemon._notify.assert_called_once()
        call_args = mock_daemon._notify.call_args[0]
        assert call_args[0] == ErrorCode.EVENT_FAILED
        assert call_args[1].last_error == "no_network"


# ===== TC-NEW-B: Consumer exception resilience =====

class TestConsumerExceptionResilience:
    """TC-NEW-B: Consumer survives unhandled exception in dispatch and continues running."""

    @pytest.mark.asyncio
    async def test_consumer_survives_exception_in_send_with_retry(self, mock_daemon):
        """Consumer continues running after _send_with_retry() raises an exception.

        Expected result:
        - First EVENT causes _send_with_retry to raise RuntimeError
        - Consumer logs the error (ERROR level) but does NOT exit
        - task_done() is called for the failed item (finally block)
        - Second EVENT is processed successfully by the same consumer
        - Both items dequeued, queue empty after processing

        This validates Task 4.5: consumer must not exit on transient errors.
        Covers the try/except Exception added to _queue_consumer() after party-mode review.
        """
        # Arrange: first call raises, second succeeds
        call_count = 0

        async def flaky_send(event_item: object, max_retries: int = 3) -> SM2State:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated transient dispatch failure")
            return SM2State.CONFIRMED

        mock_daemon._send_with_retry = flaky_send

        # Act: Enqueue two events
        await mock_daemon._enqueue_event("BA", "Zone1", None, 3)
        await mock_daemon._enqueue_event("FA", "Zone2", None, 3)

        consumer_task = asyncio.create_task(mock_daemon._queue_consumer())

        # Assert: both items processed (queue drains fully)
        try:
            await asyncio.wait_for(mock_daemon._queue.join(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail(
                "queue.join() timed out — consumer likely exited after first exception"
            )
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

        # Assert: _send_with_retry called twice (consumer survived the first failure)
        assert call_count == 2, (
            f"Expected 2 dispatch calls (consumer survived exception), got {call_count}"
        )

        # Assert: error was logged (consumer reported the failure)
        error_calls = [str(c) for c in mock_daemon._logger.error.call_args_list]
        assert any("unhandled exception" in m.lower() for m in error_calls), (
            f"Expected error log for dispatch exception, got: {error_calls}"
        )

        # Assert: queue is empty
        assert mock_daemon._queue.empty()
