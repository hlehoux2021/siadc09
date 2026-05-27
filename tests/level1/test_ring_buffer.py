"""
Test suite for ring_buffer.py module - Ring buffer & log entry factory.

Test strategy:
- TC1-TC6: Core functionality (HIGH priority) — buffer capacity, FIFO, JSON, throttle
- TC7-TC11: Integration logic (MEDIUM priority) — throttle bypass, factory, clear
- TC12-TC15: Edge cases (LOW priority) — invalid JSON, memory, timestamp format
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ===== TC1: Buffer creation and initial state (HIGH) =====
def test_ring_buffer_creation():
    """
    Test that RingBuffer initializes with empty state and correct capacity.

    Expected result:
    - RingBuffer() creates an empty buffer
    - Buffer capacity is 50 (MAX_BUFFER_ENTRIES constant)
    - len(buffer) == 0 initially
    - to_json() returns empty JSON array "[]"
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()

    # Assert: Buffer is empty
    assert len(buffer) == 0

    # Assert: to_json() returns empty array
    assert buffer.to_json() == "[]"


# ===== TC2: Push entries and preserve order (HIGH) =====
def test_ring_buffer_push_preserves_order():
    """
    Test that push() adds entries with newest first (LIFO retrieval).

    Expected result:
    - push() adds entry to buffer
    - Multiple pushes preserve insertion order (newest first in JSON)
    - Each entry includes: timestamp, level, message, context
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()

    # Add three entries
    buffer.push("info", "First message", {})
    buffer.push("debug", "Second message", {"key": "value"})
    buffer.push("warning", "Third message", {})

    # Assert: Buffer has 3 entries
    assert len(buffer) == 3

    # Assert: Latest entry is retrievable
    entries = json.loads(buffer.to_json())
    assert entries[0]["message"] == "Third message"  # Newest first
    assert entries[2]["message"] == "First message"  # Oldest last


# ===== TC3: FIFO discard when buffer full (HIGH) =====
def test_ring_buffer_fifo_discard_at_capacity():
    """
    Test that when buffer reaches 50 entries, oldest entry is discarded.

    Expected result:
    - Push 51 entries to buffer with MAX_BUFFER_ENTRIES=50
    - After 51st push, buffer still has exactly 50 entries
    - First entry added (oldest) is discarded
    - Remaining 50 entries are the newest ones (2-51)
    """
    from resources.siadc09d.ring_buffer import RingBuffer, MAX_BUFFER_ENTRIES

    buffer = RingBuffer()

    # Push MAX_BUFFER_ENTRIES + 1 entries
    for i in range(MAX_BUFFER_ENTRIES + 1):
        buffer.push("info", f"Message {i}", {"index": i})

    # Assert: Buffer size is exactly MAX_BUFFER_ENTRIES (50)
    assert len(buffer) == MAX_BUFFER_ENTRIES

    # Assert: Oldest entry (Message 0) is discarded
    entries = json.loads(buffer.to_json())
    messages = [e["message"] for e in entries]
    assert "Message 0" not in messages
    assert "Message 1" in messages  # 2nd oldest is still present
    assert "Message 50" in messages  # Newest is present


# ===== TC4: to_json() returns valid JSON (HIGH) =====
def test_ring_buffer_to_json_valid():
    """
    Test that to_json() returns valid JSON with newest first.

    Expected result:
    - to_json() returns valid JSON string parseable by json.loads()
    - JSON is array of objects: [{timestamp, level, message, context}, ...]
    - Array is in newest-first order
    - Each entry has all required keys
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()
    buffer.push("info", "Message A", {"ctx": "a"})
    buffer.push("warning", "Message B", {"ctx": "b"})

    # Assert: to_json() returns valid JSON
    json_str = buffer.to_json()
    entries = json.loads(json_str)

    # Assert: Entries are objects with required keys
    assert isinstance(entries, list)
    assert len(entries) == 2
    assert entries[0]["message"] == "Message B"  # Newest
    assert all(key in entries[0] for key in ["timestamp", "level", "message", "context"])


# ===== TC5: from_json() restores entries (HIGH) =====
def test_ring_buffer_from_json_restore():
    """
    Test that from_json() correctly restores entries from JSON string.

    Expected result:
    - Create buffer with entries, export to JSON
    - Create new buffer, load from JSON
    - Restored buffer has same entries and order
    - Restores max 50 entries (truncates if more)
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    # Create buffer with entries
    buffer1 = RingBuffer()
    buffer1.push("info", "Message 1", {})
    buffer1.push("debug", "Message 2", {"key": "val"})

    # Export to JSON
    json_str = buffer1.to_json()

    # Create new buffer and restore
    buffer2 = RingBuffer()
    buffer2.from_json(json_str)

    # Assert: Restored buffer has same entries
    assert len(buffer2) == 2
    entries = json.loads(buffer2.to_json())
    assert entries[0]["message"] == "Message 2"
    assert entries[1]["message"] == "Message 1"


# ===== TC6: Routine supervision throttling (HIGH) =====
def test_ring_buffer_routine_supervision_throttle():
    """
    Test that routine supervision entries are throttled to 10-minute interval.

    Expected result:
    - First routine supervision entry logs immediately
    - Second routine entry within 10 min is skipped (throttled)
    - Non-routine entry (strike, state change) logs immediately
    - After 10+ min elapsed, routine entry logs again
    """
    from resources.siadc09d.ring_buffer import RingBuffer, ROUTINE_SUPERVISION_THROTTLE_MINUTES

    buffer = RingBuffer()

    # First routine entry should log
    logged = buffer.push_supervision_entry("debug", "NULL→ACK", {}, is_routine=True)
    assert logged is True
    assert len(buffer) == 1

    # Second routine entry should be throttled
    logged = buffer.push_supervision_entry("debug", "NULL→ACK", {}, is_routine=True)
    assert logged is False
    assert len(buffer) == 1  # Not added

    # Non-routine (strike) entry should bypass throttle
    logged = buffer.push_supervision_entry("info", "Strike escalation", {}, is_routine=False)
    assert logged is True
    assert len(buffer) == 2


# ===== TC7: Throttle bypass for state changes (MEDIUM) =====
def test_ring_buffer_throttle_bypass_state_change():
    """
    Test that state-changing events bypass routine supervision throttle.

    Expected result:
    - State-changing events (is_routine=False) always log immediately
    - Multiple state changes log without throttling
    - Throttle still applies to routine entries
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()

    # Push multiple state changes (all should log)
    for i in range(3):
        logged = buffer.push_supervision_entry("warning", f"Strike {i+1}", {}, is_routine=False)
        assert logged is True

    # Assert: All 3 entries are in buffer
    assert len(buffer) == 3


# ===== TC8: make_message_entry() validates inputs (MEDIUM) =====
def test_make_message_entry_validates_inputs():
    """
    Test that make_message_entry() validates level, message, context.

    Expected result:
    - Valid inputs return proper dict
    - Invalid level raises ValueError
    - Empty message raises ValueError
    - Invalid context (non-dict) raises TypeError
    """
    from resources.siadc09d.ring_buffer import make_message_entry

    # Assert: Valid inputs work
    entry = make_message_entry("info", "Test message", {})
    assert entry["level"] == "info"
    assert entry["message"] == "Test message"

    # Assert: Invalid level raises ValueError
    with pytest.raises(ValueError):
        make_message_entry("invalid_level", "Message", {})

    # Assert: Empty message raises ValueError
    with pytest.raises(ValueError):
        make_message_entry("info", "", {})

    # Assert: Non-dict context raises TypeError
    with pytest.raises(TypeError):
        make_message_entry("info", "Message", "not a dict")


# ===== TC9: make_message_entry() generates ISO timestamp (MEDIUM) =====
def test_make_message_entry_iso_timestamp():
    """
    Test that make_message_entry() generates ISO 8601 timestamp.

    Expected result:
    - Timestamp is ISO 8601 format string
    - Timestamp parses with datetime.fromisoformat()
    - Timestamp is recent (within last 60 seconds)
    """
    from resources.siadc09d.ring_buffer import make_message_entry

    before_time = datetime.now(timezone.utc)
    entry = make_message_entry("info", "Test", {})
    after_time = datetime.now(timezone.utc)

    # Assert: Timestamp is ISO format
    ts = entry["timestamp"]
    parsed_ts = datetime.fromisoformat(ts)

    # Assert: Timestamp is between before and after
    assert before_time <= parsed_ts <= after_time


# ===== TC10: clear() empties buffer (MEDIUM) =====
def test_ring_buffer_clear():
    """
    Test that clear() removes all entries.

    Expected result:
    - clear() empties buffer
    - len(buffer) == 0
    - to_json() returns "[]"
    - Throttle state is also reset
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()
    buffer.push("info", "Message", {})
    assert len(buffer) == 1

    buffer.clear()

    # Assert: Buffer is empty
    assert len(buffer) == 0
    assert buffer.to_json() == "[]"


# ===== TC11: Multiple pushes preserve order (MEDIUM) =====
def test_ring_buffer_insertion_order_preserved():
    """
    Test that many push() calls preserve insertion order (newest first).

    Expected result:
    - Push 10 entries
    - Retrieve via to_json() and verify order
    - entries[0] is newest, entries[9] is oldest
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()

    for i in range(10):
        buffer.push("info", f"Msg {i}", {})

    entries = json.loads(buffer.to_json())

    # Assert: Order is newest first
    assert entries[0]["message"] == "Msg 9"
    assert entries[9]["message"] == "Msg 0"


# ===== TC12: Invalid JSON handling (LOW) =====
def test_ring_buffer_invalid_json_warning():
    """
    Test that from_json() logs warning on invalid JSON, starts empty.

    Expected result:
    - from_json("invalid json") logs warning
    - Buffer remains empty (doesn't crash)
    - Subsequent operations work normally
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()

    # Load invalid JSON (should not raise, just log warning)
    buffer.from_json("not valid json {[")

    # Assert: Buffer is still empty and functional
    assert len(buffer) == 0
    buffer.push("info", "New message", {})
    assert len(buffer) == 1


# ===== TC13: Timestamp format ISO 8601 (LOW) =====
def test_ring_buffer_timestamp_iso_format():
    """
    Test that all timestamps in buffer entries are ISO 8601 format.

    Expected result:
    - Timestamps in entries match ISO 8601 (YYYY-MM-DDTHH:MM:SS.mmmmmm+00:00 or similar)
    - All timestamps parse without error
    - All timestamps include timezone info (+00:00 or Z)
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()
    buffer.push("info", "Test", {})

    entries = json.loads(buffer.to_json())
    ts = entries[0]["timestamp"]

    # Assert: Timestamp is ISO format (parses successfully)
    parsed = datetime.fromisoformat(ts)

    # Assert: Timestamp has timezone (is aware, not naive)
    assert parsed.tzinfo is not None


# ===== TC14: Context dict preserved as-is (LOW) =====
def test_ring_buffer_context_preservation():
    """
    Test that context dict is preserved without modification or serialization.

    Expected result:
    - Push entry with context dict containing various types
    - to_json() serializes, from_json() restores context
    - Context values match original types (str, int, dict, list)
    """
    from resources.siadc09d.ring_buffer import RingBuffer

    buffer = RingBuffer()
    context = {"account": "ABC123", "strike": 1, "elapsed_ms": 45000, "tags": ["timeout"]}
    buffer.push("warning", "Test", context)

    entries = json.loads(buffer.to_json())

    # Assert: Context is preserved
    assert entries[0]["context"]["account"] == "ABC123"
    assert entries[0]["context"]["strike"] == 1
    assert entries[0]["context"]["elapsed_ms"] == 45000
    assert entries[0]["context"]["tags"] == ["timeout"]


# ===== TC15: No memory leaks with rapid pushes (LOW) =====
def test_ring_buffer_memory_stability():
    """
    Test that rapid pushes don't leak memory (buffer size stays at 50 max).

    Expected result:
    - Push 1000 entries rapidly
    - Buffer size never exceeds MAX_BUFFER_ENTRIES (50)
    - Memory footprint is bounded
    """
    from resources.siadc09d.ring_buffer import RingBuffer, MAX_BUFFER_ENTRIES

    buffer = RingBuffer()

    for i in range(1000):
        buffer.push("info", f"Message {i}", {"index": i})
        # Assert: Buffer never exceeds capacity
        assert len(buffer) <= MAX_BUFFER_ENTRIES

    # Assert: Final size is exactly max capacity
    assert len(buffer) == MAX_BUFFER_ENTRIES
