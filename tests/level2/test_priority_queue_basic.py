"""Story 5-3: PriorityQueue Task Coordination — Unit Tests (TC1–TC11).

Tests cover:
- Queue initialization and counter behaviour
- Priority ordering (EVENT before SUPERVISION — safety-critical, min-heap)
- FIFO ordering within same priority via monotonic counter
- Tie-breaking: no TypeError when payloads contain dicts

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-3-priorityqueue-task-coordination.md Tasks 9, Design Decision Record
"""

import asyncio
import itertools
import pytest
from unittest.mock import patch

from resources.siadc09d.daemon import (
    SIADaemon,
    QUEUE_PRIORITY_EVENT,
    QUEUE_PRIORITY_SUPERVISION,
    QUEUE_TYPE_EVENT,
    QUEUE_TYPE_SUPERVISION,
    MAX_RETRY_DEFAULT,
    EventQueuePayload,
)


# ===== FIXTURES =====

@pytest.fixture
def daemon():
    """Create a fresh SIADaemon instance with fresh queue and counter."""
    with patch('sys.argv', ['test']):
        d = SIADaemon()
    from unittest.mock import MagicMock, AsyncMock
    d._logger = MagicMock()
    d._preset = MagicMock(
        crc_format='SIA',
        supervision_interval_s=10,
        encryption_enabled=False,
    )
    d._account = '001234'
    return d


# ===== TC1–TC3: Queue initialization and counter =====

class TestQueueInitialization:
    """TC1–TC3: PriorityQueue and counter initialize correctly."""

    def test_tc1_queue_is_priorityqueue(self, daemon):
        """PriorityQueue instance created during __init__.

        Expected result:
        - _queue is an asyncio.PriorityQueue instance
        - _queue is empty on creation
        - _queue_counter is a working Iterator
        """
        # Assert: _queue is the correct type
        assert isinstance(daemon._queue, asyncio.PriorityQueue)

        # Assert: Queue starts empty
        assert daemon._queue.empty()

    def test_tc2_counter_starts_at_zero(self, daemon):
        """Counter starts at 0 and increments monotonically.

        Expected result:
        - First next() call returns 0
        - Second next() returns 1
        - Third returns 2 (monotonically increasing)
        """
        # Assert: Counter starts at 0 (fresh itertools.count())
        assert next(daemon._queue_counter) == 0
        # Assert: Monotonically increasing
        assert next(daemon._queue_counter) == 1
        assert next(daemon._queue_counter) == 2

    def test_tc3_counter_is_independent_of_queue(self, daemon):
        """Counter increments independently of queue operations.

        Expected result:
        - Calling next() on counter doesn't add items to queue
        - Queue remains empty after counter increments
        """
        # Act: Increment counter several times without enqueuing
        for _ in range(5):
            next(daemon._queue_counter)

        # Assert: Queue is still empty (counter is independent)
        assert daemon._queue.empty()


# ===== TC4–TC6: Priority ordering =====

class TestPriorityOrdering:
    """TC4–TC6: EVENT dequeued before SUPERVISION (min-heap semantics)."""

    @pytest.mark.asyncio
    async def test_tc4_event_dequeued_before_supervision(self, daemon):
        """EVENT (priority=0) is dequeued before SUPERVISION (priority=1).

        Expected result:
        - When both EVENT and SUPERVISION are queued
        - EVENT is returned first (lower priority number = higher urgency)
        - Then SUPERVISION is returned
        - This matches alarm delivery safety-critical design decision
        """
        # Arrange: Enqueue SUPERVISION first, then EVENT
        counter_s = 0
        counter_e = 1
        await daemon._queue.put((QUEUE_PRIORITY_SUPERVISION, counter_s, QUEUE_TYPE_SUPERVISION, {}))
        await daemon._queue.put((
            QUEUE_PRIORITY_EVENT, counter_e, QUEUE_TYPE_EVENT,
            {"sia_code": "BA", "zone": "Salon", "media_url": None, "retries_left": 3}
        ))

        # Act: Dequeue first item
        first = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: EVENT dequeued first (priority=0 < 1)
        assert first[2] == QUEUE_TYPE_EVENT, f"Expected EVENT first, got {first[2]}"

        # Act: Dequeue second item
        second = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: SUPERVISION dequeued second
        assert second[2] == QUEUE_TYPE_SUPERVISION

    @pytest.mark.asyncio
    async def test_tc5_multiple_events_fifo_order(self, daemon):
        """Multiple EVENTs dequeued in FIFO (counter) order.

        Expected result:
        - Three alarm events queued in order (counter 0, 1, 2)
        - Dequeued in same FIFO order (counter 0 first, then 1, then 2)
        - SIA codes preserved correctly for each item
        """
        # Arrange: Enqueue 3 events in order
        events = [("BA", "Zone1"), ("FA", "Zone2"), ("PA", "Zone3")]
        for i, (sia_code, zone) in enumerate(events):
            await daemon._queue.put((
                QUEUE_PRIORITY_EVENT, i, QUEUE_TYPE_EVENT,
                {"sia_code": sia_code, "zone": zone, "media_url": None, "retries_left": 3}
            ))

        # Act + Assert: Dequeue all and verify FIFO order
        for expected_sia, expected_zone in events:
            pri, counter, item_type, payload = await daemon._queue.get()
            daemon._queue.task_done()

            # Assert: EVENT type preserved
            assert item_type == QUEUE_TYPE_EVENT

            # Assert: SIA code and zone match expected order
            assert payload["sia_code"] == expected_sia
            assert payload["zone"] == expected_zone

    @pytest.mark.asyncio
    async def test_tc6_multiple_supervisions_fifo_order(self, daemon):
        """Multiple SUPERVISION items dequeued in FIFO (counter) order.

        Expected result:
        - Three SUPERVISION items queued with consecutive counters
        - Dequeued in counter order (0, 1, 2)
        - All items are SUPERVISION type
        """
        # Arrange: Enqueue 3 supervision items
        for i in range(3):
            await daemon._queue.put((QUEUE_PRIORITY_SUPERVISION, i, QUEUE_TYPE_SUPERVISION, {}))

        # Act + Assert: Dequeue and verify counter order
        for expected_counter in range(3):
            pri, counter, item_type, payload = await daemon._queue.get()
            daemon._queue.task_done()

            # Assert: SUPERVISION type preserved
            assert item_type == QUEUE_TYPE_SUPERVISION

            # Assert: Counter follows FIFO order
            assert counter == expected_counter


# ===== TC7–TC8: Tie-breaking prevents TypeError =====

class TestTieBreaking:
    """TC7–TC8: Monotonic counter prevents TypeError on equal-priority items."""

    @pytest.mark.asyncio
    async def test_tc7_no_typeerror_two_events_different_payloads(self, daemon):
        """Two EVENTs with different dict payloads don't raise TypeError.

        Expected result:
        - Two EVENT items enqueued with same priority but unique counters
        - asyncio.PriorityQueue does NOT attempt to compare the dict payloads
        - No TypeError raised during enqueue or dequeue
        - Both items dequeued successfully
        """
        # Arrange: Two events with incomparable dict payloads
        payload1: EventQueuePayload = {
            "sia_code": "BA", "zone": "Zone A",
            "media_url": "http://cam1/snapshot", "retries_left": 3
        }
        payload2: EventQueuePayload = {
            "sia_code": "FA", "zone": "Zone B",
            "media_url": None, "retries_left": 2
        }

        # Act: Enqueue both — counter (0 vs 1) prevents heapq from comparing dicts
        try:
            await daemon._queue.put((QUEUE_PRIORITY_EVENT, 0, QUEUE_TYPE_EVENT, payload1))
            await daemon._queue.put((QUEUE_PRIORITY_EVENT, 1, QUEUE_TYPE_EVENT, payload2))
        except TypeError:
            pytest.fail("TypeError raised during enqueue — counter tie-breaking failed")

        # Act: Dequeue both — should not raise TypeError
        try:
            item1 = await daemon._queue.get()
            daemon._queue.task_done()
            item2 = await daemon._queue.get()
            daemon._queue.task_done()
        except TypeError:
            pytest.fail("TypeError raised during dequeue — counter tie-breaking failed")

        # Assert: Both items dequeued correctly
        assert item1[2] == QUEUE_TYPE_EVENT
        assert item2[2] == QUEUE_TYPE_EVENT

    @pytest.mark.asyncio
    async def test_tc8_counter_uniqueness_guarantees_no_dict_comparison(self, daemon):
        """counter=next(itertools.count()) always produces unique values per enqueue.

        Expected result:
        - Fresh itertools.count() starts at 0 and never repeats
        - 100 consecutive next() calls produce [0..99] with no duplicates
        - This guarantees heapq never needs to compare the payload dict
        """
        # Arrange: Fresh counter (same as daemon uses)
        counter = itertools.count()
        values = [next(counter) for _ in range(100)]

        # Assert: All unique (no duplicates)
        assert len(set(values)) == 100, "Counter produced duplicate values"

        # Assert: Monotonically increasing (no gaps)
        assert values == list(range(100)), "Counter not monotonically increasing"


# ===== TC9–TC11: Enqueue helper methods =====

class TestEnqueueMethods:
    """TC9–TC11: _enqueue_event() and _enqueue_supervision() helper methods."""

    @pytest.mark.asyncio
    async def test_tc9_enqueue_event_creates_correct_structure(self, daemon):
        """_enqueue_event() creates a correctly structured EVENT queue item.

        Expected result:
        - Queue item is 4-tuple: (priority, counter, item_type, payload)
        - priority == QUEUE_PRIORITY_EVENT (0)
        - item_type == QUEUE_TYPE_EVENT
        - payload contains sia_code, zone, media_url, retries_left
        """
        # Act: Enqueue an event
        await daemon._enqueue_event("BA", "Salon", "http://cam/snap", 3)

        # Assert: Queue has exactly one item
        assert daemon._queue.qsize() == 1

        # Act: Dequeue and inspect
        priority, counter, item_type, payload = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: Priority is EVENT (0 — highest)
        assert priority == QUEUE_PRIORITY_EVENT

        # Assert: item_type is EVENT
        assert item_type == QUEUE_TYPE_EVENT

        # Assert: Payload is correct
        assert payload["sia_code"] == "BA"
        assert payload["zone"] == "Salon"
        assert payload["media_url"] == "http://cam/snap"
        assert payload["retries_left"] == 3

    @pytest.mark.asyncio
    async def test_tc10_enqueue_supervision_creates_correct_structure(self, daemon):
        """_enqueue_supervision() creates a correctly structured SUPERVISION queue item.

        Expected result:
        - Queue item is 4-tuple: (priority, counter, item_type, payload)
        - priority == QUEUE_PRIORITY_SUPERVISION (1)
        - item_type == QUEUE_TYPE_SUPERVISION
        - payload is empty dict {}
        """
        # Act: Enqueue a supervision item
        await daemon._enqueue_supervision()

        # Assert: Queue has one item
        assert daemon._queue.qsize() == 1

        # Act: Dequeue and inspect
        priority, counter, item_type, payload = await daemon._queue.get()
        daemon._queue.task_done()

        # Assert: Priority is SUPERVISION (1 — lower than EVENT)
        assert priority == QUEUE_PRIORITY_SUPERVISION

        # Assert: item_type is SUPERVISION
        assert item_type == QUEUE_TYPE_SUPERVISION

        # Assert: Payload is empty
        assert payload == {}

    @pytest.mark.asyncio
    async def test_tc11_each_enqueue_increments_counter(self, daemon):
        """Counter increments on each call to _enqueue_event or _enqueue_supervision.

        Expected result:
        - Three consecutive enqueues produce items with counter=0, 1, 2 respectively
        - Counter monotonically increases regardless of item type
        """
        # Act: Mix of event and supervision enqueues
        await daemon._enqueue_event("BA", "Zone1", None, 3)     # counter=0
        await daemon._enqueue_supervision()                       # counter=1
        await daemon._enqueue_event("FA", "Zone2", None, 3)     # counter=2

        # Act: Dequeue all (in priority order: EVENT, EVENT, SUPERVISION)
        items = []
        for _ in range(3):
            item = await daemon._queue.get()
            daemon._queue.task_done()
            items.append(item)

        # Sort by counter to verify monotonic increment regardless of dequeue order
        counters = sorted(item[1] for item in items)

        # Assert: Counter values are 0, 1, 2 (monotonically increasing from 0)
        assert counters == [0, 1, 2], f"Expected [0,1,2] counters, got {counters}"
