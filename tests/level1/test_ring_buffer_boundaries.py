"""
Ring buffer boundary and edge case tests (QA hardening).

Tests capacity boundaries (0, 1, 49, 50, 51), throttle timing edge cases,
from_json corruption scenarios, and context type preservation. Fills gaps
identified in the quality audit.

Reference: tests/level1/test_ring_buffer.py (originals)
"""

import json
import time

import pytest
from resources.siadc09d.ring_buffer import (
    MAX_BUFFER_ENTRIES,
    ROUTINE_SUPERVISION_THROTTLE_MINUTES,
    RingBuffer,
    make_message_entry,
)


# ===== Capacity boundary tests =====


def test_buffer_exactly_at_capacity():
    """
    Buffer with exactly MAX_BUFFER_ENTRIES entries — no discard should occur.

    Expected result:
    - Push exactly 50 entries
    - All 50 are present (none discarded)
    - len(buffer) == 50
    """
    buffer = RingBuffer()
    for i in range(MAX_BUFFER_ENTRIES):
        buffer.push("info", f"Entry {i}", {"i": i})

    # Assert: exactly at capacity, none lost
    assert len(buffer) == MAX_BUFFER_ENTRIES
    entries = json.loads(buffer.to_json())
    assert entries[0]["message"] == f"Entry {MAX_BUFFER_ENTRIES - 1}"
    assert entries[-1]["message"] == "Entry 0"


def test_buffer_one_over_capacity():
    """
    Buffer with 51 entries — exactly one oldest entry discarded.

    Expected result:
    - Entry 0 is gone, entries 1-50 remain
    - len == 50
    """
    buffer = RingBuffer()
    for i in range(MAX_BUFFER_ENTRIES + 1):
        buffer.push("info", f"Entry {i}", {})

    # Assert: oldest (Entry 0) discarded
    assert len(buffer) == MAX_BUFFER_ENTRIES
    entries = json.loads(buffer.to_json())
    messages = {e["message"] for e in entries}
    assert "Entry 0" not in messages
    assert f"Entry {MAX_BUFFER_ENTRIES}" in messages


def test_buffer_single_entry():
    """
    Buffer with exactly 1 entry.

    Expected result:
    - len == 1
    - JSON array has exactly one element
    - That element has all 4 required keys
    """
    buffer = RingBuffer()
    buffer.push("debug", "Solo", {"only": True})

    assert len(buffer) == 1
    entries = json.loads(buffer.to_json())
    # Assert: single entry present with all keys
    assert len(entries) == 1
    assert entries[0]["message"] == "Solo"
    assert set(entries[0].keys()) == {"timestamp", "level", "message", "context"}


def test_buffer_at_capacity_minus_one():
    """
    Buffer with 49 entries — just under capacity, no discard.

    Expected result:
    - len == 49
    - All entries present
    """
    buffer = RingBuffer()
    for i in range(MAX_BUFFER_ENTRIES - 1):
        buffer.push("info", f"E{i}", {})

    # Assert: all present, no discard
    assert len(buffer) == MAX_BUFFER_ENTRIES - 1


# ===== Throttle timing edge cases =====


def test_throttle_resets_after_clear():
    """
    clear() resets throttle state — next routine entry should log.

    Expected result:
    - Push routine entry (logs)
    - Push routine entry (throttled)
    - clear()
    - Push routine entry (logs again — throttle reset)
    """
    buffer = RingBuffer()

    logged1 = buffer.push_supervision_entry("debug", "R1", {}, is_routine=True)
    assert logged1 is True

    logged2 = buffer.push_supervision_entry("debug", "R2", {}, is_routine=True)
    assert logged2 is False

    buffer.clear()

    logged3 = buffer.push_supervision_entry("debug", "R3", {}, is_routine=True)
    # Assert: after clear, throttle is reset
    assert logged3 is True
    assert len(buffer) == 1


def test_throttle_exact_boundary(monkeypatch):
    """
    Routine entry exactly at the throttle boundary (10 minutes) should log.

    Expected result:
    - First entry logs (no prior)
    - Entry at exactly 10*60 seconds later also logs
    """
    buffer = RingBuffer()
    fake_time = [0.0]

    monkeypatch.setattr(RingBuffer, '_get_monotonic_time', staticmethod(lambda: fake_time[0]))

    fake_time[0] = 1000.0
    logged1 = buffer.push_supervision_entry("debug", "First", {}, is_routine=True)
    assert logged1 is True

    # Exactly at throttle boundary
    fake_time[0] = 1000.0 + ROUTINE_SUPERVISION_THROTTLE_MINUTES * 60
    logged2 = buffer.push_supervision_entry("debug", "AtBoundary", {}, is_routine=True)
    # Assert: exactly at boundary logs
    assert logged2 is True


def test_throttle_one_second_before_boundary(monkeypatch):
    """
    Routine entry 1 second before throttle boundary is still throttled.

    Expected result:
    - Entry at (10*60 - 1) seconds is throttled
    """
    buffer = RingBuffer()
    fake_time = [0.0]

    monkeypatch.setattr(RingBuffer, '_get_monotonic_time', staticmethod(lambda: fake_time[0]))

    fake_time[0] = 1000.0
    buffer.push_supervision_entry("debug", "First", {}, is_routine=True)

    fake_time[0] = 1000.0 + ROUTINE_SUPERVISION_THROTTLE_MINUTES * 60 - 1
    logged = buffer.push_supervision_entry("debug", "TooEarly", {}, is_routine=True)
    # Assert: 1 second before boundary → still throttled
    assert logged is False


def test_non_routine_does_not_reset_throttle_timer(monkeypatch):
    """
    Non-routine entries don't reset the routine throttle timer.

    Expected result:
    - Routine at t=0 (logs)
    - Non-routine at t=1 (logs, but doesn't affect throttle)
    - Routine at t=2 (still throttled — timer started at t=0)
    """
    buffer = RingBuffer()
    fake_time = [0.0]

    monkeypatch.setattr(RingBuffer, '_get_monotonic_time', staticmethod(lambda: fake_time[0]))

    fake_time[0] = 0.0
    buffer.push_supervision_entry("debug", "Routine1", {}, is_routine=True)

    fake_time[0] = 1.0
    buffer.push_supervision_entry("warning", "Strike", {}, is_routine=False)

    fake_time[0] = 2.0
    logged = buffer.push_supervision_entry("debug", "Routine2", {}, is_routine=True)
    # Assert: non-routine didn't reset throttle, still throttled
    assert logged is False


# ===== from_json corruption scenarios =====


@pytest.mark.parametrize("bad_json", [
    '{}',
    '42',
    '"just a string"',
    'null',
    'true',
])
def test_from_json_non_array_types(bad_json):
    """
    from_json with valid JSON but wrong type (not array) starts empty.

    Expected result:
    - Buffer remains empty (no crash)
    - Subsequent push works normally
    """
    buffer = RingBuffer()
    buffer.from_json(bad_json)

    # Assert: non-array JSON leaves buffer empty
    assert len(buffer) == 0
    buffer.push("info", "After bad load", {})
    assert len(buffer) == 1


def test_from_json_array_with_missing_keys():
    """
    from_json with array of objects missing required keys skips invalid entries.

    Expected result:
    - Valid entries loaded, invalid entries skipped
    """
    data = json.dumps([
        {"timestamp": "t1", "level": "info", "message": "Good", "context": {}},
        {"timestamp": "t2", "level": "info"},
        {"bad": "entry"},
        {"timestamp": "t3", "level": "debug", "message": "Also good", "context": {}},
    ])
    buffer = RingBuffer()
    buffer.from_json(data)

    # Assert: only 2 valid entries loaded
    assert len(buffer) == 2


def test_from_json_truncates_to_max():
    """
    from_json with >50 entries truncates to MAX_BUFFER_ENTRIES.

    Expected result:
    - Only the last 50 entries are kept
    """
    entries = [
        {"timestamp": f"t{i}", "level": "info", "message": f"E{i}", "context": {}}
        for i in range(80)
    ]
    buffer = RingBuffer()
    buffer.from_json(json.dumps(entries))

    # Assert: truncated to max
    assert len(buffer) == MAX_BUFFER_ENTRIES


def test_from_json_replaces_existing_content():
    """
    from_json replaces any existing buffer content.

    Expected result:
    - Buffer with 5 entries → from_json with 2 entries → buffer has 2
    """
    buffer = RingBuffer()
    for i in range(5):
        buffer.push("info", f"Old {i}", {})
    assert len(buffer) == 5

    new_data = json.dumps([
        {"timestamp": "t1", "level": "info", "message": "New 1", "context": {}},
        {"timestamp": "t2", "level": "info", "message": "New 2", "context": {}},
    ])
    buffer.from_json(new_data)

    # Assert: old content replaced
    assert len(buffer) == 2
    entries = json.loads(buffer.to_json())
    messages = {e["message"] for e in entries}
    assert "Old 0" not in messages
    assert "New 1" in messages


# ===== make_message_entry edge cases =====


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
def test_make_entry_all_valid_levels(level):
    """
    make_message_entry accepts all four valid levels.

    Expected result:
    - No exception raised for any valid level
    - Returned dict has correct level field
    """
    entry = make_message_entry(level, "Test", {})
    # Assert: level matches input
    assert entry["level"] == level
    # Assert: all 4 required keys present
    assert set(entry.keys()) == {"timestamp", "level", "message", "context"}


@pytest.mark.parametrize("bad_level", [
    "DEBUG", "INFO", "WARNING", "ERROR",
    "critical", "fatal", "trace", "verbose",
    "", " ", "inf0",
])
def test_make_entry_rejects_bad_levels(bad_level):
    """
    make_message_entry rejects anything not in (debug, info, warning, error).

    Expected result:
    - ValueError raised for each invalid level
    """
    with pytest.raises(ValueError):
        make_message_entry(bad_level, "Test", {})


def test_make_entry_context_with_nested_structures():
    """
    make_message_entry preserves nested dicts and lists in context.

    Expected result:
    - Nested structures round-trip through JSON correctly
    """
    context = {
        "nested": {"a": 1, "b": [2, 3]},
        "list": [{"x": "y"}, {"z": 99}],
    }
    entry = make_message_entry("info", "Nested context", context)
    # Assert: context preserved
    assert entry["context"]["nested"]["b"] == [2, 3]
    assert entry["context"]["list"][1]["z"] == 99

    # Assert: survives JSON round-trip
    json_str = json.dumps(entry)
    restored = json.loads(json_str)
    assert restored["context"] == context
