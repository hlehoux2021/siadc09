"""Story 5-3: PriorityQueue Task Coordination — Supervision Loop Integration Tests (TC21–TC26).

Tests cover:
- Supervision timer fires → _enqueue_supervision() called
- SUPERVISION item enqueued with correct priority
- EVENT dequeued before SUPERVISION (priority 0 < 1)
- Supervision under SM1 DEGRADED (queue items still sent)
- on_message() enqueues alarms correctly via _enqueue_event()

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-3-priorityqueue-task-coordination.md Task 11
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from resources.siadc09d.daemon import (
    SIADaemon,
    SM1State,
    SM2State,
    QUEUE_PRIORITY_EVENT,
    QUEUE_PRIORITY_SUPERVISION,
    QUEUE_TYPE_EVENT,
    QUEUE_TYPE_SUPERVISION,
    SUPERVISION_INTERVAL_S,
)


# ===== FIXTURES =====

@pytest.fixture
def daemon():
    """SIADaemon with mocked preset and callbacks for supervision tests."""
    with patch('sys.argv', ['test']):
        d = SIADaemon()

    d._logger = MagicMock()
    d._preset = MagicMock(
        crc_format='SIA',
        supervision_interval_s=10,
        encryption_enabled=False,
        max_retries=3,
    )
    d._account = '001234'
    d._receiver_prefix = None
    d._account_prefix = 'L0'
    d._sia_seq = 0
    d._notify = AsyncMock()
    d._send_raw = AsyncMock(return_value={"status": "ack"})
    d._update_info_commands = AsyncMock()
    d._encryption_key = b''
    d._transport = 'UDP'

    d._sm1_state = SM1State.HEALTHY
    d._sm2_state = SM2State.IDLE
    d._strike_counter = 0
    d._sm1_t3_fired = False
    d._last_supervision_ack = None

    return d


# ===== TC21–TC22: Supervision enqueue =====

class TestSupervisionEnqueue:
    """TC21–TC22: _supervision_loop() calls _enqueue_supervision() on timer fire."""

    @pytest.mark.asyncio
    async def test_tc21_supervision_loop_calls_enqueue_on_interval(self, daemon):
        """Supervision timer fires → _enqueue_supervision() is called.

        Expected result:
        - _supervision_loop() calls _enqueue_supervision() after interval elapses
        - After one interval, SUPERVISION item is in the queue
        - Loop continues (fires again after another interval)

        Strategy: asyncio.Event set on 2nd enqueue call — no wall-clock sleep dependency.
        Per testing rules: never use asyncio.sleep() for synchronisation in tests.
        """
        # Arrange: Short interval and event-driven spy on _enqueue_supervision
        daemon._preset.supervision_interval_s = 0.05
        enqueue_calls: list = []
        two_cycles_done = asyncio.Event()

        async def spy_enqueue() -> None:
            enqueue_calls.append(1)
            if len(enqueue_calls) >= 2:
                two_cycles_done.set()

        daemon._enqueue_supervision = spy_enqueue

        # Act: Run supervision loop — cancelled as soon as 2 cycles confirmed
        loop_task = asyncio.create_task(daemon._supervision_loop())

        # Wait for event (event-driven, no wall-clock dependency)
        await asyncio.wait_for(two_cycles_done.wait(), timeout=1.0)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Assert: _enqueue_supervision called at least 2 times
        assert len(enqueue_calls) >= 2, (
            f"Expected ≥2 supervision enqueues, got {len(enqueue_calls)}"
        )

    @pytest.mark.asyncio
    async def test_tc22_supervision_item_has_correct_priority(self, daemon):
        """_enqueue_supervision() creates SUPERVISION item with priority=1.

        Expected result:
        - Queue item after _enqueue_supervision() has priority=QUEUE_PRIORITY_SUPERVISION (1)
        - item_type is QUEUE_TYPE_SUPERVISION
        - payload is empty {}
        """
        # Act: Directly call enqueue_supervision
        await daemon._enqueue_supervision()

        # Assert: Queue has one item
        assert daemon._queue.qsize() == 1

        # Act: Dequeue and inspect
        priority, counter, item_type, payload = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: Priority is SUPERVISION (1 — lower urgency than EVENT)
        assert priority == QUEUE_PRIORITY_SUPERVISION

        # Assert: item_type is correct
        assert item_type == QUEUE_TYPE_SUPERVISION

        # Assert: Empty payload for v1.0
        assert payload == {}


# ===== TC23–TC24: Priority ordering =====

class TestSupervisionPriorityOrdering:
    """TC23–TC24: EVENT always dequeued before SUPERVISION regardless of enqueue order."""

    @pytest.mark.asyncio
    async def test_tc23_event_dequeued_first_when_enqueued_after_supervision(self, daemon):
        """EVENT enqueued AFTER SUPERVISION is still dequeued first.

        Expected result:
        - SUPERVISION enqueued (counter=0, priority=1)
        - EVENT enqueued (counter=1, priority=0)
        - Consumer dequeues EVENT first (priority 0 < 1)
        - Then SUPERVISION is dequeued
        """
        # Arrange: enqueue supervision first, then event
        await daemon._enqueue_supervision()  # counter=0, priority=1
        await daemon._enqueue_event("BA", "Zone1", None, 3)  # counter=1, priority=0

        # Act + Assert: Dequeue in priority order
        first = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: EVENT dequeued first (priority 0 wins)
        assert first[2] == QUEUE_TYPE_EVENT, (
            f"Expected EVENT first, got {first[2]}"
        )

        second = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: SUPERVISION dequeued second
        assert second[2] == QUEUE_TYPE_SUPERVISION

    @pytest.mark.asyncio
    async def test_tc24_event_dequeued_first_when_enqueued_before_supervision(self, daemon):
        """EVENT enqueued BEFORE SUPERVISION is also dequeued first (same priority rule).

        Expected result:
        - EVENT enqueued first (counter=0, priority=0)
        - SUPERVISION enqueued second (counter=1, priority=1)
        - Consumer still dequeues EVENT first (priority 0 < 1)
        - Order is determined by priority, not enqueue order
        """
        # Act: Enqueue event first, then supervision
        await daemon._enqueue_event("FA", "Zone2", None, 3)  # counter=0, priority=0
        await daemon._enqueue_supervision()  # counter=1, priority=1

        # Act + Assert: First dequeue is EVENT
        first = await daemon._queue.get()
        daemon._queue.task_done()

        assert first[2] == QUEUE_TYPE_EVENT, (
            f"Expected EVENT first, got {first[2]}"
        )

        # Act + Assert: Second dequeue is SUPERVISION
        second = await daemon._queue.get()
        daemon._queue.task_done()

        assert second[2] == QUEUE_TYPE_SUPERVISION


# ===== TC25–TC26: Integration and resilience =====

class TestSupervisionResilience:
    """TC25–TC26: Supervision and event processing under DEGRADED SM1 and on_message."""

    @pytest.mark.asyncio
    async def test_tc25_supervision_and_event_sent_under_degraded(self, daemon):
        """Both SUPERVISION and EVENT queue items are sent when SM1 is DEGRADED.

        Expected result:
        - SM1 state = DEGRADED (strike=1 — not critical)
        - Consumer processes EVENT (calls _send_with_retry)
        - Consumer processes SUPERVISION (calls _send_supervision)
        - Both items complete without errors
        - Queue drains fully
        """
        # Arrange: SM1 DEGRADED (strike=1), not TCP_RECONNECTING
        daemon._sm1_state = SM1State.DEGRADED
        daemon._strike_counter = 1

        processed = []

        async def spy_send_with_retry(event_item, max_retries=3):
            processed.append("EVENT")
            return SM2State.CONFIRMED

        async def spy_send_supervision():
            processed.append("SUPERVISION")

        daemon._send_with_retry = spy_send_with_retry
        daemon._send_supervision = spy_send_supervision

        # Act: Enqueue supervision then event
        await daemon._enqueue_supervision()
        await daemon._enqueue_event("PA", "Garden", None, 3)

        consumer_task = asyncio.create_task(daemon._queue_consumer())
        await asyncio.wait_for(daemon._queue.join(), timeout=2.0)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Assert: Both items processed (EVENT first, then SUPERVISION)
        assert "EVENT" in processed, "EVENT was not processed under DEGRADED"
        assert "SUPERVISION" in processed, "SUPERVISION was not processed under DEGRADED"

        # Assert: EVENT processed before SUPERVISION (priority)
        event_idx = processed.index("EVENT")
        supervision_idx = processed.index("SUPERVISION")
        assert event_idx < supervision_idx, (
            f"EVENT should be processed before SUPERVISION, got order: {processed}"
        )

        # Assert: Queue drained
        assert daemon._queue.empty()

    @pytest.mark.asyncio
    async def test_tc26_on_message_enqueues_alarm_correctly(self, daemon):
        """on_message() maps PHP alarm commands to SIA codes and enqueues correctly.

        Expected result:
        - on_message("burglarAlarm", {zone: "Salon"}) → enqueues EVENT with sia_code="BA"
        - on_message("fireAlarm", {zone: "Cuisine"}) → sia_code="FA"
        - on_message("panicAlarm", {}) → sia_code="PA", zone=None
        - Unknown command → ignored (warning logged, no enqueue)
        - Queue has exactly 3 items after 3 valid commands
        """
        # Act: Send 3 valid alarm commands
        await daemon.on_message("burglarAlarm", {"zone": "Salon", "media_url": None})
        await daemon.on_message("fireAlarm", {"zone": "Cuisine", "media_url": None})
        await daemon.on_message("panicAlarm", {})

        # Assert: Queue has exactly 3 items
        assert daemon._queue.qsize() == 3

        # Act: Dequeue and verify each item
        items = []
        for _ in range(3):
            item = await daemon._queue.get()
            daemon._queue.task_done()
            items.append(item)

        # Extract sia_codes from payloads in counter order
        items_by_counter = sorted(items, key=lambda x: x[1])
        sia_codes = [item[3]["sia_code"] for item in items_by_counter]

        # Assert: Correct SIA code mapping
        assert sia_codes == ["BA", "FA", "PA"], (
            f"Expected ['BA', 'FA', 'PA'], got {sia_codes}"
        )

        # Assert: Zone extracted correctly
        assert items_by_counter[0][3]["zone"] == "Salon"
        assert items_by_counter[1][3]["zone"] == "Cuisine"
        assert items_by_counter[2][3]["zone"] is None

        # Act: Send unknown command
        await daemon.on_message("unknownCommand", {})

        # Assert: Unknown command was ignored (queue still empty after draining)
        assert daemon._queue.empty(), "Unknown command should not enqueue anything"

        # Assert: Warning was logged
        warning_calls = [str(c) for c in daemon._logger.warning.call_args_list]
        warned = any("unknownCommand" in msg for msg in warning_calls)
        assert warned, f"Expected warning for unknown command, got: {warning_calls}"
