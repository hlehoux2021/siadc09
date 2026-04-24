"""Ring Buffer & Log Entry Factory — Message History and Throttling.

v1.0: Ring buffer for supervision and alarm event history with routine supervision throttling.

Module design:
- RingBuffer class: FIFO buffer with max 50 entries, JSON persistence
- Routine supervision throttling: entries logged only once per 10-minute interval
- State-changing events (strikes, transitions, alarms): logged immediately (bypass throttle)
- Entry format: {timestamp (ISO 8601), level (str), message (str), context (dict)}
- Factory function: make_message_entry() creates properly formatted entries
- JSON persistence: to_json() / from_json() for Jeedom config key storage

Privacy rules for log entries:
- account_number: Always included in context if present
- encryption_key: NEVER included (log key length instead)
- CSR IP:port: Always included if present
- Zone name: Always included if present
- Raw ciphertext: DEBUG level only (safe, key not shown)

Reference: docs/design/logging-design.md § Ring Buffer Structure (ADR-17)

Example usage:
    from resources.siadc09d.ring_buffer import RingBuffer, make_message_entry

    buffer = RingBuffer()

    # Routine supervision (throttled)
    logged = buffer.push_supervision_entry("debug", "NULL→ACK", {}, is_routine=True)
    if not logged:
        print("Entry was throttled")

    # State changes (always logged)
    buffer.push_supervision_entry("warning", "Strike escalation", {"strike": 1}, is_routine=False)

    # Manual entry creation and push
    entry = make_message_entry("info", "Alarm confirmed", {"zone": "Salon"})
    buffer.push(entry["level"], entry["message"], entry["context"])

    # Persistence
    json_str = buffer.to_json()  # Export for config storage
    buffer.from_json(json_str)   # Import from config
"""

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone


# Constants
MAX_BUFFER_ENTRIES = 50
ROUTINE_SUPERVISION_THROTTLE_MINUTES = 10

# Logger for this module
logger = logging.getLogger(__name__)


def make_message_entry(level: str, message: str, context: dict) -> dict:
    """Create a properly formatted log entry.

    Factory function for standardized log entry structure used by ring buffer
    and logging helpers. Validates input types and generates ISO 8601 timestamp.

    Args:
        level: Log level ("debug", "info", "warning", "error"). Must be one of these.
        message: Log message text. Must be non-empty string.
        context: Additional context data (dict). Can be empty {}.

    Returns:
        Dict with keys: timestamp (ISO 8601 str), level (str), message (str), context (dict)

    Raises:
        ValueError: If level not in ["debug", "info", "warning", "error"] or message empty
        TypeError: If context is not a dict

    Example:
        entry = make_message_entry("info", "Alarm received", {"zone": "Salon"})
        # Returns: {
        #   "timestamp": "2026-04-10T14:30:45.123456+00:00",
        #   "level": "info",
        #   "message": "Alarm received",
        #   "context": {"zone": "Salon"}
        # }
    """
    # Validate level
    valid_levels = ("debug", "info", "warning", "error")
    if level not in valid_levels:
        raise ValueError(f"level must be one of {valid_levels}, got {level!r}")

    # Validate message
    if not isinstance(message, str) or not message:
        raise ValueError(f"message must be non-empty string, got {message!r}")

    # Validate context
    if not isinstance(context, dict):
        raise TypeError(f"context must be dict, got {type(context).__name__}")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "context": context,
    }


class RingBuffer:
    """FIFO ring buffer for supervision and alarm event history.

    Stores max 50 entries (newest first) with JSON persistence to Jeedom config.
    Routine supervision entries (no state change) throttled to 10-minute interval.
    State-changing events (strikes, transitions) logged immediately.

    Attributes:
        _buffer: deque with maxlen=50 (FIFO, auto-discards oldest on overflow)
        _last_routine_supervision_time: Timestamp of last logged routine entry (for throttling)

    Example:
        buffer = RingBuffer()

        # Push normal entry
        buffer.push("info", "Supervision established", {})

        # Throttled routine entry
        buffer.push_supervision_entry("debug", "NULL→ACK", {}, is_routine=True)

        # Unthrottled state change
        buffer.push_supervision_entry("warning", "Strike 1", {"strike": 1}, is_routine=False)

        # Persistence
        json_str = buffer.to_json()
        buffer.from_json(json_str)
    """

    def __init__(self) -> None:
        """Initialize empty ring buffer with no throttle history."""
        self._buffer: deque[dict] = deque(maxlen=MAX_BUFFER_ENTRIES)
        self._last_routine_supervision_time: float | None = None

    def push(self, level: str, message: str, context: dict) -> None:
        """Push a log entry to the buffer.

        Entry is automatically formatted with ISO timestamp and added to buffer.
        If buffer is full (50 entries), oldest entry is automatically discarded.

        Args:
            level: Log level ("debug", "info", "warning", "error")
            message: Log message text
            context: Additional context dict

        Raises:
            ValueError: If level invalid or message empty
            TypeError: If context not a dict
        """
        entry = make_message_entry(level, message, context)
        self._buffer.appendleft(entry)  # Newest first (deque.appendleft)

    def push_supervision_entry(
        self, level: str, message: str, context: dict, is_routine: bool = False
    ) -> bool:
        """Push a supervision or alarm entry with throttling logic.

        Routine supervision entries (no state change) are throttled to once per 10 minutes.
        State-changing events (strikes, transitions, alarms) bypass throttle and log immediately.

        Args:
            level: Log level ("debug", "info", "warning", "error")
            message: Log message text
            context: Additional context dict
            is_routine: True if routine supervision ACK (throttled), False if state change (unthrottled)

        Returns:
            bool: True if entry was logged, False if throttled

        Example:
            # Routine entry (may be throttled)
            logged = buffer.push_supervision_entry("debug", "NULL→ACK", {}, is_routine=True)

            # State change (always logged)
            logged = buffer.push_supervision_entry("warning", "Strike 1", {}, is_routine=False)
        """
        if is_routine:
            # Check throttle for routine supervision
            if not self._should_log_routine_supervision():
                return False  # Throttled, not logged
            # Update throttle time
            self._last_routine_supervision_time = self._get_monotonic_time()

        # Log immediately (either non-routine or routine that passed throttle)
        self.push(level, message, context)
        return True

    def _should_log_routine_supervision(self) -> bool:
        """Check if routine supervision entry should be logged based on throttle interval.

        Returns True if:
        - No routine entry logged yet (_last_routine_supervision_time is None)
        - More than 10 minutes elapsed since last routine entry

        Returns False if throttle interval not exceeded.

        Returns:
            bool: True if should log, False if throttled
        """
        if self._last_routine_supervision_time is None:
            return True  # First routine entry

        elapsed_seconds = self._get_monotonic_time() - self._last_routine_supervision_time
        throttle_seconds = ROUTINE_SUPERVISION_THROTTLE_MINUTES * 60

        return elapsed_seconds >= throttle_seconds

    @staticmethod
    def _get_monotonic_time() -> float:
        """Get monotonic time (clock-skew safe, never goes backwards).

        Uses time.monotonic() instead of time.time() to prevent throttle bugs
        from system clock changes (e.g., NTP adjustments).

        Returns:
            float: Monotonic time in seconds since arbitrary start point
        """
        return time.monotonic()

    def clear(self) -> None:
        """Clear all entries from buffer and reset throttle state.

        Returns:
            None
        """
        self._buffer.clear()
        self._last_routine_supervision_time = None

    def __len__(self) -> int:
        """Return number of entries currently in buffer.

        Returns:
            int: Number of entries (0 to MAX_BUFFER_ENTRIES)
        """
        return len(self._buffer)

    def to_json(self) -> str:
        """Export buffer entries to JSON string (newest first).

        Serializes all entries to JSON array with newest entry first.
        Format: [newest, ..., oldest]

        Returns:
            str: Valid JSON string representing array of entries

        Example:
            >>> buffer = RingBuffer()
            >>> buffer.push("info", "Test", {})
            >>> json_str = buffer.to_json()
            >>> json_str
            '[{"timestamp": "...", "level": "info", "message": "Test", "context": {}}]'
        """
        # _buffer is stored newest-first (appendleft order), convert to list
        entries = list(self._buffer)
        return json.dumps(entries)

    def from_json(self, json_str: str) -> None:
        """Load buffer entries from JSON string.

        Parses JSON array and restores entries to buffer (max 50 entries).
        On parse error, logs warning and starts with empty buffer.

        Args:
            json_str: JSON string representing array of entry objects

        Returns:
            None

        Example:
            >>> json_str = '[{"timestamp": "...", "level": "info", ...}]'
            >>> buffer = RingBuffer()
            >>> buffer.from_json(json_str)
        """
        try:
            entries = json.loads(json_str)

            # Validate it's a list
            if not isinstance(entries, list):
                logger.warning("Ring buffer from_json: expected list, got %s", type(entries).__name__)
                return

            # Clear current buffer and reload (max 50 entries)
            self._buffer.clear()
            # JSON array is already in newest-first order, so append in reverse
            # to preserve the order when using appendleft (which reverses insertion)
            for entry in reversed(entries[-MAX_BUFFER_ENTRIES:]):
                if isinstance(entry, dict) and all(
                    k in entry for k in ("timestamp", "level", "message", "context")
                ):
                    self._buffer.appendleft(entry)  # Newest first

        except json.JSONDecodeError as e:
            logger.warning("Ring buffer from_json: JSON parse error: %s", e)
        except Exception as e:
            logger.warning("Ring buffer from_json: unexpected error: %s", e)
