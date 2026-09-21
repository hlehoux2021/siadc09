"""SIA DC-09-2021.17 Protocol Daemon — SM1 Connection/Supervision State Machine.

v1.0: Daemon core with dual state machines (SM1 supervision, SM2 alarm events).
This module implements SM1 (Connection/Supervision State Machine) tracking CSR availability.

SM1 States (ref: supervision-design.md ADR-11):
- INITIALIZING: Daemon starting, initial NULL frame sent, awaiting CSR ACK
- HEALTHY: CSR responding with ACK, supervision normal (strike=0)
- DEGRADED: Timeouts or NAKs received (strike=1-2 impaired, strike=3 critical)
- TCP_RECONNECTING: TCP half-open stall detected at strike=3, reconnect loop active
- NO_NETWORK: Permanent TCP failure after 3+ reconnect attempts (terminal)

Strike counter (capped at 3):
- 0: HEALTHY or INITIALIZING
- 1-2: DEGRADED impaired, user-actionable via T1 (SUPERVISION_TIMEOUT, SUPERVISION_NAK)
- 3: DEGRADED critical, fires T3 (SUPERVISION_DISCONNECTED) once via _sm1_t3_fired flag

Module design:
- SIADaemon class: extends BaseDaemon from jeedomdaemon
- SM1 state machine: transitions driven by ACK/NAK/timeout/tcp_drop responses
- Single-consumer pattern: PriorityQueue ensures one _send_supervision() in flight (no race on strike)
- Task tracking: all async background tasks tracked in _tasks set with done callbacks
- Logging: dual-line pattern (French INFO + English DEBUG)
- Ring buffer: routine ACKs throttled 10-min, strikes/transitions immediate
- Type safety: SM1State enum, TypedDict contexts for logging

Reference: docs/design/daemon-design.md Component 1
Reference: docs/design/supervision-design.md ADR-11 SM1 State Machine
Reference: docs/design/error-handler-design.md T1/T2/T3 error tiers
"""

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Coroutine, Final, Iterator, Literal, TypedDict, cast

from jeedomdaemon import BaseDaemon, BaseConfig

from .error_handler import (
    BadCSRResponseCtx,
    ErrorCode,
    EventFailedCtx,
    NotificationContext,
    SM1DisconnectedCtx,
    SM1NakCtx,
    SM1TimeoutCtx,
    TransportPermanentCtx,
    event_type_fr,
)
from .messages import (
    SM1_DEGRADED_1_2_FR,
    SM1_DEGRADED_3_FR,
    SM1_HEALTHY_FR,
    SM1_INITIALIZING_FR,
    SM1_TCP_RECONNECTING_FR,
    SM1_NO_NETWORK_FR,
)
from .ring_buffer import RingBuffer, make_message_entry
from .sia_protocol import (
    ENCRYPTED_MARKER,
    NULL_TOKEN,
    SIA_DCS_TOKEN,
    SIAMessageBuilder,
    SIAProtocolError,
    SIATransportError,
    TIMESTAMP_FORMAT,
    parse_nak_timestamp,
)
from .sia_crypto import AESEncryptionError
from .presets import CSRPreset
from .sia_transport import (
    CrcFormat, SIABaseTransport, SIAUDPTransport, SIATCPTransport,
    SIATransportResult, TransportType, ON_STOP_TASK_TIMEOUT_S,
)


# ===== TASK 1: SM1 STATE MACHINE CLASS STRUCTURE =====

class SM1State(Enum):
    """SM1 state machine states (ref: supervision-design.md ADR-11)."""
    INITIALIZING = "INITIALIZING"  # Daemon starting, awaiting first ACK
    HEALTHY = "HEALTHY"              # CSR responding normally (strike=0)
    DEGRADED = "DEGRADED"            # Timeouts/NAKs received (strike=1-3)
    TCP_RECONNECTING = "TCP_RECONNECTING"  # TCP half-open stall, reconnect loop active
    NO_NETWORK = "NO_NETWORK"        # Permanent TCP failure (terminal)


class SM1AckLogCtx(TypedDict):
    """Logging context for ACK response."""
    seq: int  # Sequence number sent
    elapsed_ms: float  # Time from send to ACK
    crc_format: CrcFormat  # CRC encoding format ('hex' or 'bin') from CSR preset
    raw_hex: str | None  # Raw ACK hex (optional)
    prev_strike: int  # Strike counter before this ACK


class SM1TimeoutLogCtx(TypedDict):
    """Logging context for timeout."""
    seq: int  # Sequence number that timed out
    elapsed_ms: float  # Time elapsed since send
    strike: int  # Strike counter after increment
    prev_state: SM1State  # State before timeout
    t3_just_fired: bool  # True if T3 (SUPERVISION_DISCONNECTED) just fired


class SM1NakLogCtx(TypedDict):
    """Logging context for NAK response."""
    seq: int  # Sequence number NAK'd
    elapsed_ms: float  # Time from send to NAK
    strike: int  # Strike counter after increment
    raw_hex: str  # Raw NAK hex
    csr_time: datetime | None  # Parsed CSR timestamp (if parseable)
    t3_just_fired: bool  # True if T3 just fired


# ===== TASK 1: SM2 STATE MACHINE CLASS STRUCTURE =====

class SM2State(Enum):
    """SM2 state machine states (ref: daemon-design.md ADR-14 & story 5-2).

    State transitions:
    - IDLE: Startup-only state, entered once at daemon init
    - PENDING: Alarm event in progress, awaiting CSR ACK/NAK
    - CONFIRMED: Event confirmed by CSR (ACK received)
    - FAILED: Event failed (NAK, timeout, NO_NETWORK, or max retries exhausted)

    Transition rules:
    - IDLE → PENDING: First alarm dequeued from PriorityQueue
    - PENDING → CONFIRMED: ACK received from CSR
    - PENDING → FAILED: NAK, timeout, NO_NETWORK, or max retries
    - CONFIRMED → PENDING: Next alarm dequeued (direct, no IDLE)
    - FAILED → PENDING: Next alarm dequeued (direct, no IDLE)
    - **CRITICAL:** IDLE never re-entered after first alarm
    """
    IDLE = "IDLE"              # Startup-only (no alarm since daemon start)
    PENDING = "PENDING"        # Alarm send in progress
    CONFIRMED = "CONFIRMED"    # CSR confirmed alarm reception (ACK)
    FAILED = "FAILED"          # Event failed (NAK/timeout/NO_NETWORK/max retries)


SiaEventCode = Literal['BA', 'FA', 'PA']  # SIA alarm event codes: Burglary, Fire, Panic


class SM2LogCtx(TypedDict):
    """Logging context for SM2 state transitions.

    Used by _log_sm2_event() to provide structured logging context.
    """
    zone: str | None  # Zone name from alarm command #zone# tag (None if not specified)
    sia_code: SiaEventCode
    attempt: int  # Current attempt number (1, 2, 3, ...)
    elapsed: float  # Elapsed time in seconds since state entry
    state_change: bool  # True if this is a transition, False if retried state


@dataclass
class EventItem:
    """Queue item for alarm event delivery (SM2 processing).

    Attributes:
        sia_code: Event SIA code (BA=burglary, FA=fire, PA=panic)
        zone: Zone name from alarm command #zone# tag (None if not specified)
        timestamp: Event timestamp from make_timestamp()
        zone_number: Zone order number resolved by PHP against the zone table
                     (None when the label matched no entry — the frame then carries no zone)
        callback: Optional callback function called when event completes (signature: callback(success: bool))
    """
    sia_code: SiaEventCode
    zone: str | None  # Zone name or None — logs, notifications, inspector
    timestamp: str  # SIA protocol timestamp HH:MM:SS,MM-DD-YYYY
    zone_number: int | None = None  # Only field that reaches the SIA frame
    callback: Any | None = None  # Callback function(success: bool) when send completes


# ===== CONSTANTS =====

SUPERVISION_INTERVAL_S = 60  # Default supervision interval (seconds)
TCP_RECONNECT_DELAY_S = 5  # Default TCP reconnect backoff (seconds)
TCP_RECONNECT_MAX_ATTEMPTS = 3  # Max reconnect attempts before NO_NETWORK
TCP_CONNECT_TIMEOUT_S = 10  # Timeout for asyncio.wait_for() on TCP connect
STRIKE_CAP = 3  # Strike counter capped at 3
SIA_SEQ_MAX: Final[int] = 10000  # Sequence wraps 9999 → 0000 (SIA DC-09 § 5.5.1.5)


# ===== TASK 1 (Story 5-3): PRIORITY QUEUE CONSTANTS AND TYPES =====

# Priority values for asyncio.PriorityQueue (min-heap: lower number = higher priority).
# EVENT (alarms) always win — alarm delivery is safety-critical (daemon-design.md line 503).
QUEUE_PRIORITY_EVENT: Final[int] = 0        # Alarms dequeued first
QUEUE_PRIORITY_SUPERVISION: Final[int] = 1  # Supervision dequeued second

# Queue item type string identifiers (narrowed to Literal so the PriorityQueue
# type annotation tuple[int, int, QueueItemType, QueuePayload] is satisfied).
QUEUE_TYPE_EVENT: Final[Literal["EVENT"]] = "EVENT"
QUEUE_TYPE_SUPERVISION: Final[Literal["SUPERVISION"]] = "SUPERVISION"

# Type alias for the item_type field (Literal for static analysis)
QueueItemType = Literal["EVENT", "SUPERVISION"]

# Default retry budget when enqueuing a new alarm event
MAX_RETRY_DEFAULT: Final[int] = 3


class OnMessageParams(TypedDict, total=False):
    """Parameters passed to on_message() from PHP sendToDaemon().

    All keys are optional — zone, zone_number and media_url may be absent for simple
    alarm commands. zone is the label (#zone# tag), zone_number the order number PHP
    resolved against sia_zone_mappings.
    """
    zone: str
    zone_number: int | None
    media_url: str


class InfoCommandsPayload(TypedDict, total=False):
    """Partial payload for PHP INFO command updates.

    All fields are optional — callers pass only what changed.
    None-valued call (no-arg) triggers a full refresh on the PHP side.
    """
    event_state: int
    event_label: str
    supervision_state: int
    supervision_label: str


class EventQueuePayload(TypedDict):
    """Payload for EVENT items in the priority queue.

    Carried from on_message() → _queue_consumer() → _send_with_retry().
    """
    sia_code: SiaEventCode
    zone: str | None      # Zone name from PHP #zone# tag, or None
    zone_number: int | None  # Zone order number for the SIA frame, or None
    media_url: str | None # Verification media URL for SIA [V...] field, or None
    retries_left: int        # Retry budget; reset to MAX_RETRY_DEFAULT on TCP reconnect


class SupervisionQueuePayload(TypedDict):
    """Payload for SUPERVISION items in the priority queue (empty in v1.0).

    Reserved for future extended supervision data (v1.1: supervision category, etc.).
    """
    pass  # No payload needed for v1.0 NULL supervision frames


# Union of all queue payload types (AC1: 4-tuple type safety).
QueuePayload = EventQueuePayload | SupervisionQueuePayload

# Map PHP alarm command names → SIA event codes (M2: no magic strings).
# Used by on_message() to convert PHP sendToDaemon() commands to SIA codes.
_EVENT_SIA_CODES: Final[dict[str, SiaEventCode]] = {
    "burglarAlarm": "BA",
    "fireAlarm": "FA",
    "panicAlarm": "PA",
}


# ===== TASK 2: STRIKE COUNTER AND SM1 STATE MANAGEMENT =====

class SIADaemon(BaseDaemon):
    """SIA DC-09 Daemon with SM1 Connection/Supervision State Machine.

    Inherits from BaseDaemon (jeedomdaemon framework) and implements:
    - SM1 state machine tracking CSR connection health
    - Strike counter (0-3) for supervision robustness
    - T3 deduplication via _sm1_t3_fired flag
    - TCP half-open stall detection and recovery
    - Logging to ring buffer and Jeedom PHP plugin
    """

    def __init__(self, preset: CSRPreset, config: BaseConfig | None = None) -> None:
        """Initialize SIA Daemon with all instance variables.

        Args:
            preset: CSRPreset with all CSR connection parameters. Required — the daemon
                    cannot operate without a valid preset. Strongly typed; no duck-typing.
            config: Optional BaseConfig from jeedomdaemon. If None, uses default.

        Instance Variables (SM1 state machine):
            _sm1_state: Current SM1 state (INITIALIZING, HEALTHY, DEGRADED, etc.)
            _strike_counter: Strikes (timeouts/NAKs) since last ACK (0-3)
            _sm1_t3_fired: T3 deduplication flag (prevents duplicate SUPERVISION_DISCONNECTED)
            _last_supervision_ack: Datetime of last successful ACK (for timestamp tracking)

        Instance Variables (SM2 state machine - alarm events):
            _sm2_state: Current SM2 state (IDLE, PENDING, CONFIRMED, FAILED)
            _event_sia_code: Latest event SIA code (BA=burglary, FA=fire, PA=panic)
            _event_zone: Latest zone name from alarm command #zone# tag
            _event_attempt_count: Current send attempt count for in-flight event
            Note: event_state/event_label are derived via _event_state_from_sm2() /
                  _event_label_from_sm2() helpers — not stored as separate instance vars

        Instance Variables (Configuration):
            _preset: CSRPreset (host, port, encryption_enabled, crc_format, transport, etc.)
            _account: Account number (3-16 hex chars)
            _receiver_prefix: Receiver prefix (optional)
            _account_prefix: Account prefix (optional)
            _encryption_key: Encryption key bytes (empty if disabled)

        Instance Variables (State & Data):
            _sia_seq: Current SIA sequence number (0-9999)
            _sia_builder: SIAMessageBuilder for encoding frames
            _ring_buffer: RingBuffer for message history
            _tasks: Set of tracked asyncio.Task objects
            _logger: Module logger

        Instance Variables (Queue coordination — Story 5-3):
            _queue: asyncio.PriorityQueue of 4-tuples (priority, counter, item_type, payload).
                    EVENT priority=0 (dequeued first); SUPERVISION priority=1.
            _queue_counter: Monotonic int iterator (itertools.count) — tie-breaker within
                    same priority; prevents TypeError on heapq dict comparison.
            _sm1_state_changed: asyncio.Event set on every SM1 state transition via
                    _set_sm1_state(). Consumer waits on this before dequeuing while
                    SM1=TCP_RECONNECTING — items stay in queue (no spin, no re-enqueue).

        Instance Variables (Transport):
            _sia_transport: Active SIABaseTransport instance (SIAUDPTransport
                    or SIATCPTransport); None before on_start()

        Note: _notify() is a synchronous class method (def, not async def) —
              dispatches via _track_task(_dispatch_notify(...)).
        Note: _track_task() and _log_sm1_supervision() are class methods defined
              directly on SIADaemon — not stubs or subclass-injected.
        """
        super().__init__(
            config=config or BaseConfig(),
            on_start_cb=self.on_start,
            on_message_cb=self._on_message_dispatch,
            on_stop_cb=self.on_stop,
        )
        self._preset: CSRPreset = preset

        # SM1 state machine
        self._sm1_state: SM1State = SM1State.INITIALIZING
        self._strike_counter: int = 0
        self._sm1_t3_fired: bool = False
        self._last_supervision_ack: datetime | None = None

        # SM2 state machine (alarm event delivery)
        self._sm2_state: SM2State = SM2State.IDLE  # Startup-only state
        self._event_sia_code: SiaEventCode | None = None  # Latest event code (BA|FA|PA)
        self._event_zone: str | None = None  # Latest zone from command #zone# tag
        self._event_attempt_count: int = 0  # Track send attempts for current event

        # Configuration — populated from preset and CLI config
        # Fix #5: account must come from preset (was empty string, causing frame build failures)
        self._account: str = preset.account_number
        self._receiver_prefix: str = getattr(config, "receiver_prefix", "") or ""
        # Fix #6: empty prefix fails SIA validation; "L0" is the protocol default
        self._account_prefix: str = getattr(config, "account_prefix", "") or "L0"
        _enc_key_str: str = getattr(config, "encryption_key", "") or ""
        self._encryption_key: bytes = _enc_key_str.encode() if _enc_key_str else b""
        self._sia_transport: SIABaseTransport | None = None  # Active transport; None before on_start()

        # State & data
        self._sia_seq: int = 0
        # Fix #7: preset.crc_format is "hex"/"bin" but SIAMessageBuilder expects "SIA"/"ADM"
        _builder_crc = "SIA" if preset.crc_format == "hex" else "ADM"
        self._sia_builder: SIAMessageBuilder = SIAMessageBuilder(crc_format=_builder_crc)
        self._ring_buffer: RingBuffer = RingBuffer()
        self._tasks: set[asyncio.Task] = set()
        self._logger = logging.getLogger(__name__)

        # Queue coordination (Story 5-3): PriorityQueue + monotonic counter.
        # 4-tuple items: (priority: int, counter: int, item_type: QueueItemType, payload: QueuePayload)
        # priority=0 (EVENT) dequeued before priority=1 (SUPERVISION) — min-heap semantics.
        # counter from itertools.count() guarantees FIFO within same priority and
        # prevents TypeError when heapq would otherwise compare payload dicts.
        self._queue: asyncio.PriorityQueue[tuple[int, int, QueueItemType, QueuePayload]] = asyncio.PriorityQueue()
        self._queue_counter: Iterator[int] = itertools.count()

        # SM1 state change notification event (Story 5-3 H1 fix).
        # Set by _set_sm1_state() on every SM1 state transition.
        # _queue_consumer awaits this before each dequeue when SM1=TCP_RECONNECTING:
        # items stay in the queue (no re-enqueue) and the consumer wakes naturally.
        self._sm1_state_changed: asyncio.Event = asyncio.Event()

        # Last sent frame bytes — stored in _send_raw() for message_trace callbacks.
        self._last_sent_frame: bytes = b""


    def _notify(self, error_code: ErrorCode, context: NotificationContext) -> None:
        """Dispatch error notification as a non-blocking background task.

        Synchronous wrapper — never blocks the caller. Schedules _dispatch_notify()
        as a tracked task so exceptions are logged and the task is GC-safe.

        Args:
            error_code: ErrorCode enum value identifying the error tier
            context: Typed context dataclass (SM1TimeoutCtx, EventFailedCtx, etc.)

        Reference: error-handler-design.md — T1/T2/T3 dispatch contract
        Reference: daemon-design.md Component 1 — _notify() synchronous wrapper
        """
        self._track_task(
            self._dispatch_notify(error_code, context),
            name=f"notify_{error_code.name}",
        )

    async def _send_raw(self, frame: bytes) -> SIATransportResult:
        """Send one SIA frame via the active transport. Only _queue_consumer() may call this.

        Returns:
            SIATransportResult with status 'ack'|'nak'|'timeout'|'tcp_drop'

        Raises:
            SIATransportError: if transport not initialized or network failure
        """
        self._last_sent_frame = frame  # Store for message_trace callbacks
        if self._sia_transport is None:
            raise SIATransportError("Transport not initialized — on_start() not called")
        return await self._sia_transport.send_frame(frame)

    async def _send_callback(self, payload: dict[str, Any]) -> None:
        """Send callback payload to PHP via send_to_jeedom() — defensive wrapper.

        Validates payload structure before sending:
        - 'type' field must be present
        - No Python bool values (use int 0/1 per IPC contract)

        Catches ALL exceptions, logs ERROR, returns — never re-raises.
        Failure to deliver a callback is non-fatal to daemon operation.

        Args:
            payload: JSON-serializable dict with 'type' field at top level.

        Reference: architecture.md § Communication Patterns — IPC payload rules
        Reference: story 6-6 AC3
        """
        # Validate 'type' field present
        if "type" not in payload:
            self._logger.error(
                f"_send_callback: payload missing 'type' field — dropped: {payload!r}"
            )
            return

        # Validate no bool values (IPC contract: use int 0/1)
        for key, value in payload.items():
            if isinstance(value, bool):
                self._logger.error(
                    f"_send_callback: payload contains bool value at key '{key}' — dropped"
                )
                return

        try:
            await self.send_to_jeedom(payload)
        except Exception as e:
            self._logger.error(f"_send_callback: send_to_jeedom failed: {e!r}")

    async def _update_info_commands(self, data: InfoCommandsPayload | None = None) -> None:
        """Send PHP INFO command update via _send_callback().

        If data is None, builds full payload from current SM1/SM2 state.
        If data is provided, uses it directly (partial update path).

        Args:
            data: Optional partial payload. None triggers full state refresh.

        Reference: story 6-6 AC1/AC5, daemon-design.md Component 1
        """
        if data is None:
            payload: dict[str, Any] = {
                "type": "info_update",
                "supervision_state": self._supervision_value(),
                "supervision_label": self._supervision_label(),
            }
            # event_state/event_label excluded when SM2 is IDLE (startup-only state).
            # IDLE means no event has occurred since daemon start — persisted cmd values
            # from the previous run are intentionally left untouched.
            if self._sm2_state != SM2State.IDLE:
                payload["event_state"] = self._event_state_from_sm2()
                payload["event_label"] = self._event_label_from_sm2()
        else:
            payload = {k: v for k, v in data.items() if v is not None}
            payload["type"] = "info_update"
        await self._send_callback(payload)

    @staticmethod
    def _error_tier(code: ErrorCode) -> Literal[1, 2, 3]:
        """Return tier number (1, 2, or 3) for a given ErrorCode.

        Args:
            code: ErrorCode enum value

        Returns:
            1 for T1 (auto-heal), 2 for T2 (user-actionable), 3 for T3 (critical)
        """
        from .error_handler import ErrorTier, classify_error
        tier = classify_error(code)
        if tier == ErrorTier.T1:
            return 1
        elif tier == ErrorTier.T2:
            return 2
        else:
            return 3

    async def _dispatch_notify(self, code: ErrorCode, ctx: NotificationContext) -> None:
        """Dispatch error to PHP via tier-appropriate callbacks.

        Tier → callback mapping:
          T1: message_center only
          T2: message_center + notify + error_update
          T3: message_center + notify (CRITIQUE prefix) + error_update

        Each channel is wrapped in its own try/except — failure of one never
        prevents the others.

        Args:
            code: ErrorCode enum value
            ctx: Typed notification context dataclass

        Reference: story 6-6 AC2/AC7, error-handler-design.md § Tier dispatch
        """
        from .error_handler import build_notification, T3_PREFIX, _context_to_dict
        import dataclasses

        tier = self._error_tier(code)
        ctx_dict = _context_to_dict(ctx)

        # Build base context for build_notification (design doc contract)
        transport_str = "tcp" if self._preset.transport is TransportType.TCP else "udp"
        csr_address = f"{self._preset.host}:{self._preset.port}"
        build_ctx: dict[str, Any] = {
            "csr_address": csr_address,
            "transport": transport_str,
            "strike_count": self._strike_counter,
        }
        if ctx_dict:
            build_ctx.update(ctx_dict)

        notification = build_notification(code, build_ctx)
        title: str = notification["title"]
        message: str = notification["message"]
        logical_id: str = notification["logical_id"]
        timestamp = datetime.now(timezone.utc).isoformat()

        # Channel 1: message_center (all tiers)
        try:
            await self._send_callback({
                "type": "message_center",
                "message": message,
                "logical_id": logical_id,
            })
        except Exception as e:
            self._logger.error(f"_dispatch_notify: message_center failed: {e!r}")

        # Channel 2+3: notify + error_update (T2 and T3 only)
        if tier >= 2:
            notify_title = title if tier < 3 else title if title.startswith(T3_PREFIX) else T3_PREFIX + title

            try:
                await self._send_callback({
                    "type": "notify",
                    "title": notify_title,
                    "message": message,
                })
            except Exception as e:
                self._logger.error(f"_dispatch_notify: notify failed: {e!r}")

            try:
                await self._send_callback({
                    "type": "error_update",
                    "code": code.name,
                    "message": message,
                    "timestamp": timestamp,
                    "context": ctx_dict,
                    "count": 1,
                })
            except Exception as e:
                self._logger.error(f"_dispatch_notify: error_update failed: {e!r}")

    def _set_sm1_state(self, new_state: SM1State) -> None:
        """Set SM1 state and notify the queue consumer via _sm1_state_changed event.

        All SM1 state transitions MUST go through this method so that
        _queue_consumer() wakes up when it is waiting on _sm1_state_changed
        (i.e., while SM1=TCP_RECONNECTING, items stay in the queue without
        spinning — the consumer only dequeues once SM1 has transitioned).

        The consumer's gate loop clears the event before re-checking state,
        so we only call set() here — never clear(). This way, if multiple
        transitions happen while the consumer is dispatching, the event stays
        set and the consumer can re-evaluate on its next gate pass.

        Args:
            new_state: The new SM1State to transition to.

        Reference: daemon-design.md Component 1 — queue consumer gate (H1 fix)
        """
        self._sm1_state = new_state
        self._sm1_state_changed.set()

    def _track_task(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
        """Create a tracked asyncio.Task from a coroutine.

        Wraps asyncio.create_task() to ensure all tasks are tracked in _tasks and
        any unhandled exceptions are logged via _logger.error() on completion.

        Args:
            coro: Coroutine to schedule as a task
            name: Descriptive name (visible in tracebacks and logs). Required —
                  asyncio's default Task-N names are useless in error logs.

        Returns:
            The created asyncio.Task (already scheduled)

        Reference: daemon-design.md Component 1 — task tracking pattern (Story 5-5 refines)
        """
        task: asyncio.Task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        def _done_cb(t: asyncio.Task) -> None:
            """Remove completed task from set; log exceptions."""
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                self._logger.error(
                    f"Unhandled exception in tracked task '{t.get_name()}': {t.exception()}"
                )

        task.add_done_callback(_done_cb)
        return task

    # ===== SM2 STATE HELPER METHODS =====

    def _event_state_from_sm2(self) -> Literal[0, 1, 2, 3]:
        """Return numeric value for event_state INFO command based on SM2 state.

        Returns:
            int: 0 (no alarm), 1 (confirmed), 2 (failed), or 3 (pending)

        Logic:
            - IDLE → 0 (no alarm since daemon start)
            - PENDING → 3 (alarm send in progress)
            - CONFIRMED → 1 (CSR acknowledged alarm)
            - FAILED → 2 (event failed after retries)

        Reference: daemon-design.md SM2 state → INFO command mapping
        """
        if self._sm2_state == SM2State.IDLE:
            return 0
        elif self._sm2_state == SM2State.PENDING:
            return 3
        elif self._sm2_state == SM2State.CONFIRMED:
            return 1
        elif self._sm2_state == SM2State.FAILED:
            return 2
        else:
            # Defensive: should not reach here
            return 0

    def _event_context_prefix(self) -> str:
        """Build the "{Type} (zone {zone})" prefix for active SM2 labels.

        The alarm type is derived from the latest SIA code via event_type_fr()
        and capitalised for display (e.g. "intrusion" → "Intrusion"). The zone
        comes from the alarm command #zone# tag stored at PENDING entry.

        Returns:
            str: e.g. "Intrusion (zone 3)". Falls back to "Alarme" if the type
                 is unknown and omits the zone clause if no zone is recorded.
        """
        if self._event_sia_code:
            type_fr = event_type_fr(self._event_sia_code)
            type_label = type_fr[:1].upper() + type_fr[1:]
        else:
            type_label = "Alarme"
        if self._event_zone:
            return f"{type_label} (zone {self._event_zone})"
        return type_label

    def _event_label_from_sm2(self) -> str:
        """Return French label for event_label INFO command based on SM2 state.

        Returns:
            str: French-language state label for display

        Logic:
            - IDLE → "Inactif" (no alarm received)
            - PENDING → "{Type} (zone {zone}) : En cours"
            - CONFIRMED → "{Type} (zone {zone}) : Confirmée par la centrale"
            - FAILED → "{Type} (zone {zone}) : Refusé par la centrale"

        The type/zone prefix (built by _event_context_prefix) names the alarm in
        progress so the widget shows which event is being transmitted, not just a
        bare status word. IDLE has no active event, so it stays "Inactif".

        Reference: daemon-design.md SM2 state → INFO command mapping
        """
        if self._sm2_state == SM2State.IDLE:
            return "Inactif"
        elif self._sm2_state == SM2State.PENDING:
            return f"{self._event_context_prefix()} : En cours"
        elif self._sm2_state == SM2State.CONFIRMED:
            return f"{self._event_context_prefix()} : Confirmée par la centrale"
        elif self._sm2_state == SM2State.FAILED:
            return f"{self._event_context_prefix()} : Refusé par la centrale"
        else:
            # Defensive: should not reach here
            return "Inactif"

    def _supervision_value(self) -> Literal[0, 1, 2]:
        """Return numeric value for supervision_state INFO command.

        Returns:
            int: 0 (problem), 1 (impaired), or 2 (healthy)

        Logic:
            - INITIALIZING → 1 (daemon starting, supervision not yet confirmed)
            - HEALTHY → 2 (normal operation)
            - DEGRADED(strike 1-2) → 1 (impaired but recoverable)
            - DEGRADED(strike 3) → 0 (critical, requires attention)
            - TCP_RECONNECTING → 0 (connection broken)
            - NO_NETWORK → 0 (permanent failure, terminal)

        Reference: supervision-design.md SM1 state → INFO command mapping
        """
        if self._sm1_state == SM1State.INITIALIZING:
            return 1
        elif self._sm1_state == SM1State.HEALTHY:
            return 2
        elif self._sm1_state == SM1State.DEGRADED:
            # DEGRADED with strike=3 is critical (0), strike 1-2 is impaired (1)
            return 0 if self._strike_counter >= 3 else 1
        else:
            # TCP_RECONNECTING, NO_NETWORK → 0 (problem)
            return 0

    def _supervision_label(self) -> str:
        """Return French-language string for supervision_label INFO command.

        Returns:
            str: Localized French label describing SM1 state

        Labels:
            - INITIALIZING → "Connexion en cours d'initialisation" (daemon starting)
            - HEALTHY → "Connexion OK" (static, no timestamp embedded)
            - DEGRADED(strike 1-2) → "Connexion dégradée (N/3)" (N = current strike)
            - DEGRADED(strike 3) → "Connexion perdue" (lost)
            - TCP_RECONNECTING → "Tentative de reconnexion en cours" (reconnecting)
            - NO_NETWORK → "Hors Réseau" (network unavailable, terminal)

        Note: HEALTHY label is static "Connexion OK" (not time-varying) to avoid DB writes on every ACK.
        The last-ACK timestamp is available via supervision_state.collectDate for display.

        Reference: supervision-design.md SM1 state → INFO command mapping
        """
        if self._sm1_state == SM1State.INITIALIZING:
            return SM1_INITIALIZING_FR  # "Connexion en cours d'initialisation"
        elif self._sm1_state == SM1State.HEALTHY:
            return SM1_HEALTHY_FR  # "Connexion OK"
        elif self._sm1_state == SM1State.DEGRADED:
            if self._strike_counter >= 3:
                return SM1_DEGRADED_3_FR  # "Connexion perdue"
            else:
                # "Connexion dégradée (N/3)" — replace N with current strike
                return SM1_DEGRADED_1_2_FR.format(self._strike_counter)
        elif self._sm1_state == SM1State.TCP_RECONNECTING:
            return SM1_TCP_RECONNECTING_FR  # "Tentative de reconnexion en cours"
        else:  # NO_NETWORK
            return SM1_NO_NETWORK_FR  # "Hors Réseau"

    async def _update_sm1_from_strike(self) -> bool:
        """Centralized strike → state transition helper.

        Called AFTER strike counter is incremented (never increments itself).
        Handles state changes and notifications based on strike level.

        Returns:
            bool: True if T3 (SUPERVISION_DISCONNECTED) just fired, False otherwise

        Logic:
            - On any call (strike >= 1): set state to DEGRADED
            - If strike=3 and TCP: force socket close, transition to TCP_RECONNECTING
            - If strike=3 and UDP: stay DEGRADED (no TCP_RECONNECTING state)
            - If strike=3 and not _sm1_t3_fired: fire T3 and set flag to True
            - UDP never enters TCP_RECONNECTING or NO_NETWORK states

        Note: This method is async because it may schedule TCP reconnect task.
        Must be awaited, never called without await.

        Reference: supervision-design.md ADR-11, daemon-design.md Component 1
        """
        # Any strike level >= 1 transitions to DEGRADED
        self._set_sm1_state(SM1State.DEGRADED)

        t3_just_fired = False

        # Strike=3 handling
        if self._strike_counter >= 3:
            if self._preset.transport is TransportType.TCP:
                # Force socket close to escape half-open stall
                # (TCP connection may be in half-open state, blocking indefinitely)
                # Transition to TCP_RECONNECTING and start reconnect loop (D-3 guard:
                # only spawn if no loop already running — prevents dual-task race).
                self._set_sm1_state(SM1State.TCP_RECONNECTING)
                if not any(t.get_name() == "tcp_reconnect_loop" for t in self._tasks):
                    self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")

            # Fire T3 notification (once only, via _sm1_t3_fired deduplication)
            if not self._sm1_t3_fired:
                self._sm1_t3_fired = True
                t3_just_fired = True
                time_since = (
                    (datetime.now(timezone.utc) - self._last_supervision_ack).total_seconds()
                    if self._last_supervision_ack else None
                )
                self._notify(ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx(
                    strike_count=self._strike_counter,
                    last_ack_time_utc=self._last_supervision_ack,
                    time_since_last_ack_s=time_since,
                    supervision_interval_s=self._preset.supervision_interval_s,
                ))

        return t3_just_fired

    async def _send_supervision(self) -> None:
        """Send supervision NULL frame and handle ACK/NAK/timeout/tcp_drop response.

        This is the core supervision loop logic. Called repeatedly at supervision_interval.
        Handles:
        - Creating and sending SIA NULL frame
        - Processing ACK response (reset strike, set HEALTHY)
        - Processing NAK response (increment strike, dispatch T1/T2)
        - Processing timeout (increment strike, dispatch T1/T3)
        - Processing TCP drop (transition to TCP_RECONNECTING)

        Sequence flow:
            1. Increment sequence number (unless resetting from ACK)
            2. Create SIA NULL frame with current sequence
            3. Send frame via _send_raw()
            4. Parse response status
            5. Route to ACK/NAK/timeout/tcp_drop handler
            6. Update INFO commands via _update_info_commands()
            7. Push to ring buffer via _log_sm1_supervision()

        Error handling:
            - SIATransportError (from _send_raw) treated as timeout (strike++)
            - NAK with unparseable timestamp routed to BAD_CSR_RESPONSE (T2)
            - All strikes capped at 3 (never exceeds)

        Reference: daemon-design.md Component 1, supervision-design.md ADR-11, Task B.2
        """
        # Create SIA NULL supervision frame
        try:
            frame = self._sia_builder.make_supervision_message(
                account_number=self._account,
                account_prefix=self._account_prefix,
                receiver_number=self._receiver_prefix if self._receiver_prefix else None,
                encryption=self._preset.encryption_enabled,
            )
        except (SIAProtocolError, AESEncryptionError) as e:
            self._logger.error(f"Failed to encode supervision NULL frame: {e}")
            return

        # Send frame and measure elapsed time
        send_start = time.monotonic()
        try:
            result: SIATransportResult = await self._send_raw(frame)
        except asyncio.CancelledError:
            raise  # never swallow cancellation (daemon-design.md § CancelledError safety rule)
        except SIATransportError as e:
            self._logger.error(f"Transport error sending supervision: {e!r}")
            await self._handle_supervision_timeout((time.monotonic() - send_start) * 1000)
            await self._update_info_commands()
            return

        elapsed_ms = (time.monotonic() - send_start) * 1000

        # Route response to appropriate handler
        status: Literal['ack', 'nak', 'timeout', 'tcp_drop'] = result['status']

        if status == "ack":
            # ACK path
            await self._handle_supervision_ack(result, elapsed_ms)
        elif status == "nak":
            # NAK path
            await self._handle_supervision_nak(result, elapsed_ms)
        elif status == "timeout":
            # Timeout path
            await self._handle_supervision_timeout(elapsed_ms)
        elif status == "tcp_drop":
            # TCP drop path (rare, OS-level connection reset)
            await self._handle_supervision_tcp_drop()

        # Update INFO commands
        await self._update_info_commands()

    async def _handle_supervision_ack(self, result: SIATransportResult, elapsed_ms: float) -> None:
        """Handle ACK response: reset strike, set HEALTHY, increment sequence.

        Args:
            result: SIATransportResult from _send_raw()
            elapsed_ms: Time elapsed from send to ACK receipt

        Actions:
            - Increment sequence: _sia_seq = (_sia_seq + 1) % 10000
            - Reset strike: _strike_counter = 0
            - Reset T3 flag: _sm1_t3_fired = False
            - Set state: _sm1_state = HEALTHY
            - Update timestamp: _last_supervision_ack = now
            - Log via _log_sm1_supervision('ack', ...) ← routine, may be throttled
            - Push to ring buffer (throttled 10-min for routine ACKs)

        Reference: daemon-design.md Task 3 (ACK path), supervision-design.md
        """
        prev_strike = self._strike_counter

        # Increment sequence (only on ACK, never on timeout/NAK)
        self._sia_seq = (self._sia_seq + 1) % SIA_SEQ_MAX

        # Reset strike and T3 dedup flag
        self._strike_counter = 0
        self._sm1_t3_fired = False

        # Set state to HEALTHY
        self._set_sm1_state(SM1State.HEALTHY)

        # Update last ACK timestamp
        self._last_supervision_ack = datetime.now(timezone.utc)

        # Create logging context
        ctx: SM1AckLogCtx = {
            "seq": self._sia_seq - 1,  # Was the sequence sent
            "elapsed_ms": elapsed_ms,
            "crc_format": self._preset.crc_format,
            "raw_hex": result['raw_response'].hex() if result.get('raw_response') else None,
            "prev_strike": prev_strike,
        }

        # Emit resolve_t1 when recovering from degraded state (clears T1 errors on PHP side).
        # Both codes resolved unconditionally — PHP handler is idempotent (no-op if code not in last_errors).
        if prev_strike > 0:
            await self._send_callback({"type": "error_update", "resolve_t1": 1, "code": ErrorCode.SUPERVISION_TIMEOUT.value})
            await self._send_callback({"type": "error_update", "resolve_t1": 1, "code": ErrorCode.SUPERVISION_NAK.value})

        # Log supervision event (may be throttled for routine ACKs)
        await self._log_sm1_supervision("ack", ctx)

    async def _handle_supervision_nak(self, result: SIATransportResult, elapsed_ms: float) -> None:
        """Handle NAK response: increment strike, dispatch T1/T2, log.

        Args:
            result: SIATransportResult from _send_raw()
            elapsed_ms: Time elapsed from send to NAK receipt

        Actions:
            - Increment strike: _strike_counter = min(_strike_counter + 1, 3)
            - Call _update_sm1_from_strike() to handle strike→state transition
            - If strike < 3: fire T1 (SUPERVISION_NAK) notification
            - Attempt to parse NAK timestamp via sia_protocol.parse_nak_timestamp()
            - If unparseable (ValueError): fire T2 (BAD_CSR_RESPONSE) instead
            - Log via _log_sm1_supervision('nak_timestamp' or 'nak_bad', ...)
            - Push to ring buffer (immediate, not throttled)

        Reference: daemon-design.md Task 3 (NAK path), supervision-design.md ADR-11
        """
        # Increment strike
        self._strike_counter = min(self._strike_counter + 1, STRIKE_CAP)
        prev_strike = self._strike_counter - 1

        # Update SM1 state based on strike
        t3_just_fired = await self._update_sm1_from_strike()

        # Parse NAK timestamp first — needed for T1 context and T2 routing
        nak_data: bytes = result['raw_nak'] or b""
        csr_time: datetime | None = None
        is_parseable = False

        try:
            csr_time = parse_nak_timestamp(nak_data)
            is_parseable = True
        except ValueError:
            # Unparseable NAK → fire T2 (BAD_CSR_RESPONSE)
            self._notify(ErrorCode.BAD_CSR_RESPONSE, BadCSRResponseCtx(
                raw_frame=nak_data,
                parse_error="NAK timestamp unparseable",
                csr_host=self._preset.host,
                csr_port=self._preset.port,
                transport="tcp" if self._preset.transport is TransportType.TCP else "udp",
            ))

        # Fire T1 only at strike < 3 and only when NAK was parseable (unparseable → T2 already fired)
        if self._strike_counter < 3 and is_parseable:
            self._notify(ErrorCode.SUPERVISION_NAK, SM1NakCtx(
                raw_nak_frame=nak_data,
                nak_timestamp=csr_time.isoformat() if csr_time else None,
                account_number=self._account,
            ))

        # Create logging context
        ctx: SM1NakLogCtx = {
            "seq": self._sia_seq,
            "elapsed_ms": elapsed_ms,
            "strike": self._strike_counter,
            "raw_hex": nak_data.hex() if nak_data else "",
            "csr_time": csr_time,
            "t3_just_fired": t3_just_fired,
        }

        # Log supervision event (immediate, not throttled)
        event_type: Literal["nak_timestamp", "nak_bad"] = (
            "nak_timestamp" if is_parseable else "nak_bad"
        )
        await self._log_sm1_supervision(event_type, ctx)

    async def _handle_supervision_timeout(self, elapsed_ms: float) -> None:
        """Handle timeout: increment strike, dispatch T1/T3, log.

        Args:
            elapsed_ms: Time elapsed since send (reached supervision_interval timeout)

        Actions:
            - Increment strike: _strike_counter = min(_strike_counter + 1, 3)
            - Call _update_sm1_from_strike() to handle strike→state transition
            - If strike == 1: fire T1 (SUPERVISION_TIMEOUT) notification (once only, not repeated)
            - Log via _log_sm1_supervision('timeout', ...)
            - Push to ring buffer (immediate, not throttled)

        Reference: daemon-design.md Task 3 (Timeout path), supervision-design.md ADR-11
        """
        prev_state = self._sm1_state

        # Increment strike
        self._strike_counter = min(self._strike_counter + 1, STRIKE_CAP)

        # Update SM1 state based on strike
        t3_just_fired = await self._update_sm1_from_strike()

        # Fire T1 only at strike=1 (first timeout, user-actionable)
        # Don't repeat T1 at strike=2; strike=3 fires T3 instead
        if self._strike_counter == 1:
            self._notify(ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(
                elapsed_ms=elapsed_ms,
                strike_count=self._strike_counter,
                supervision_interval_s=self._preset.supervision_interval_s,
            ))

        # Create logging context
        ctx: SM1TimeoutLogCtx = {
            "seq": self._sia_seq,
            "elapsed_ms": elapsed_ms,
            "strike": self._strike_counter,
            "prev_state": prev_state,
            "t3_just_fired": t3_just_fired,
        }

        # Log supervision event (immediate, not throttled)
        await self._log_sm1_supervision("timeout", ctx)

    async def _handle_supervision_tcp_drop(self) -> None:
        """Handle TCP drop (OS-level connection reset).

        Rare event when OS forcibly closes TCP connection (e.g., connection refused, timeout at OS level).
        Different from timeout (which is supervisory timeout at app level).

        Actions:
            - Set state to TCP_RECONNECTING immediately (don't wait for 3 strikes)
            - Schedule _tcp_reconnect_loop() task
            - Do NOT increment strike (OS already broke connection)
            - Log via _logger.warning() with context

        Reference: daemon-design.md Task 3 (TCP drop path)
        """
        # State regression guard: late TCP drop callback must not regress terminal states.
        # TCP_RECONNECTING: reconnect already in progress — ignore duplicate.
        # NO_NETWORK: terminal state — ignore entirely (daemon stopped/watchdog handles).
        if self._sm1_state in (SM1State.TCP_RECONNECTING, SM1State.NO_NETWORK):
            self._logger.debug(
                f"TCP drop ignored: SM1 already {self._sm1_state.name}"
            )
            return
        self._set_sm1_state(SM1State.TCP_RECONNECTING)
        self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
        self._logger.warning("TCP connection dropped by OS, initiating reconnect")

    async def _tcp_reconnect_loop(self) -> None:
        """TCP reconnect loop with backoff and permanent failure detection.

        Only runs when _sm1_state == TCP_RECONNECTING.
        Probes CSR reachability by opening and immediately closing a TCP connection.
        Transitions to NO_NETWORK (terminal) after max failures.

        Behavior:
            - Only for TCP transport (UDP never enters this state)
            - Probe: asyncio.wait_for(asyncio.open_connection(...), TCP_CONNECT_TIMEOUT_S)
            - Reconnect interval: _preset.reconnect_delay_s (default 5s)
            - Max attempts: TCP_RECONNECT_MAX_ATTEMPTS (default 3)
            - On success: reset strike=0, t3_fired=False, set state=INITIALIZING
            - On permanent failure: set state=NO_NETWORK, fire T3 (TRANSPORT_PERMANENT)
            - Logged via _logger.debug() with per-attempt details

        Note: SIATCPTransport is per-frame (no persistent connection). This loop
              probes reachability directly via asyncio.open_connection(); success
              restores INITIALIZING so the supervision loop resumes normal sends.

        Reference: daemon-design.md Task 4 (TCP reconnect logic), supervision-design.md ADR-11
        """
        if self._preset.transport is not TransportType.TCP:
            return  # UDP never enters TCP_RECONNECTING

        max_attempts = TCP_RECONNECT_MAX_ATTEMPTS
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            self._logger.debug(
                f"TCP reconnect attempt {attempt}/{max_attempts}, "
                f"waiting {self._preset.reconnect_delay_s}s before probe"
            )

            await asyncio.sleep(self._preset.reconnect_delay_s)

            self._logger.debug(f"Probing TCP reachability {attempt}/{max_attempts}...")

            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._preset.host, self._preset.port),
                    timeout=self._preset.connect_timeout_s,
                )
                # Reachable — close probe connection immediately
                try:
                    writer.close()
                    await writer.wait_closed()
                except OSError:
                    pass  # already closed or reset — cleanup best-effort

                self._strike_counter = 0
                self._sm1_t3_fired = False
                self._set_sm1_state(SM1State.INITIALIZING)
                self._logger.info("TCP reconnect successful, returning to INITIALIZING")
                return

            except asyncio.CancelledError:
                raise  # propagate task cancellation (daemon-design.md § CancelledError safety rule)
            except asyncio.TimeoutError:
                self._logger.warning(
                    f"TCP reconnect probe {attempt}/{max_attempts} timed out "
                    f"({TCP_CONNECT_TIMEOUT_S}s)"
                )
            except OSError as e:
                self._logger.warning(
                    f"TCP reconnect probe {attempt}/{max_attempts} failed: {e!r}"
                )

        # Permanent failure after max attempts
        self._set_sm1_state(SM1State.NO_NETWORK)
        self._notify(ErrorCode.TRANSPORT_PERMANENT, TransportPermanentCtx(
            reason="tcp_max_retries_exceeded",
            transport="tcp",
            error_details=f"Max reconnect attempts ({max_attempts}) exceeded",
            retry_count=max_attempts,
        ))
        self._logger.error(
            f"TCP reconnect failed after {max_attempts} attempts, transitioning to NO_NETWORK"
        )

        # Option A: hand the process back to Jeedom's watchdog for a clean restart.
        # BaseDaemon.stop() cancels every task except the caller, then run()'s finally
        # block removes the PID file and sys.exit(0)s — the watchdog then re-launches us
        # (on_start → INITIALIZING → fresh reconnect). Schedule it (do NOT await): stop()
        # cancels _tasks including this loop, and awaiting inline would cancel ourselves
        # mid-call and drop the TRANSPORT_PERMANENT notify. Scheduling AFTER _notify()
        # guarantees the notify task is already in _tasks so on_stop() awaits it (AC16).
        # Ref: daemon-design.md:589/616/677/684, error-handler-design.md, story 3-3 stub docstring.
        self._track_task(self.stop(), name="transport_permanent_stop")

    async def _log_sm1_supervision(
        self,
        event: Literal["ack", "timeout", "nak_timestamp", "nak_bad"],
        ctx: SM1AckLogCtx | SM1TimeoutLogCtx | SM1NakLogCtx,
    ) -> None:
        """Log supervision event with dual-line pattern (French INFO + English DEBUG).

        Implements logging table from logging-design.md SM1 Supervision Table.
        Pushes to ring buffer with appropriate throttling:
        - Routine ACKs: throttled 10-minute interval (prevent INFO spam at normal operation)
        - Strikes, transitions, T1/T3: immediate (not throttled)

        Args:
            event: Event type ('ack', 'timeout', 'nak_timestamp', 'nak_bad')
            ctx: Logging context (SM1AckLogCtx, SM1TimeoutLogCtx, or SM1NakLogCtx)

        Logging behavior per event:
            - 'ack': DEBUG only, no INFO (routine, throttled)
            - 'timeout' @ strike=1: INFO (T1 fired) + DEBUG
            - 'timeout' @ strike=2: INFO (impaired) + DEBUG
            - 'timeout' @ strike=3: INFO (critical, T3 fired) + DEBUG
            - 'nak_timestamp': DEBUG only (like timeout, treats NAK as timeout)
            - 'nak_bad': DEBUG only (unparseable NAK)

        Reference: docs/design/logging-design.md § SM1 Supervision Table (ADR-16)
        """
        try:
            if event == "ack":
                ack_ctx = cast(SM1AckLogCtx, ctx)
                elapsed_s = ack_ctx["elapsed_ms"] / 1000
                self._logger.debug(
                    f"Supervision ACK received: account={self._account}, "
                    f"seq={ack_ctx['seq']}, elapsed={elapsed_s:.2f}s, "
                    f"crc_format={ack_ctx['crc_format']}"
                )
                self._ring_buffer.push_supervision_entry(
                    level="debug",
                    message=f"ACK: seq={ack_ctx['seq']}, elapsed={elapsed_s:.2f}s",
                    context={"account": self._account, "seq": ack_ctx["seq"]},
                    is_routine=True,
                )
                await self._send_callback({
                    "type": "message_trace",
                    "dialog": {
                        "dialog_type": "supervision",
                        "routine": 1,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elapsed_ms": int(ack_ctx["elapsed_ms"]),
                        "id_token": f"{ENCRYPTED_MARKER}{NULL_TOKEN}" if self._preset.encryption_enabled else NULL_TOKEN,
                        "sequence": ack_ctx["seq"],
                        "account": self._account,
                        "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
                        "response_hex": ack_ctx["raw_hex"] if ack_ctx["raw_hex"] else "",
                    },
                })

            elif event == "timeout":
                t_ctx = cast(SM1TimeoutLogCtx, ctx)
                strike = t_ctx["strike"]
                elapsed_s = t_ctx["elapsed_ms"] / 1000
                info_msg = (
                    f"Supervision dégradée — tentative {strike}/3"
                    if strike < 3
                    else "Supervision perdue — intervention requise"
                )
                self._logger.info(info_msg)
                self._logger.debug(
                    f"Supervision timeout: account={self._account}, "
                    f"seq={t_ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"prev_state={t_ctx['prev_state']}, "
                    f"t3_fired={t_ctx['t3_just_fired']}"
                )
                self._ring_buffer.push_supervision_entry(
                    level="warning" if strike == 3 else "info",
                    message=info_msg,
                    context={"account": self._account, "seq": t_ctx["seq"], "strike": strike},
                    is_routine=False,
                )
                await self._send_callback({
                    "type": "message_trace",
                    "dialog": {
                        "dialog_type": "supervision",
                        "routine": 0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elapsed_ms": int(t_ctx["elapsed_ms"]),
                        "id_token": f"{ENCRYPTED_MARKER}{NULL_TOKEN}" if self._preset.encryption_enabled else NULL_TOKEN,
                        "sequence": t_ctx["seq"],
                        "account": self._account,
                        "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
                    },
                })

            elif event == "nak_timestamp":
                n_ctx = cast(SM1NakLogCtx, ctx)
                strike = n_ctx["strike"]
                elapsed_s = n_ctx["elapsed_ms"] / 1000
                info_msg = f"NAK supervision (strike {strike}/3) — horodatage rejeté par la centrale"
                self._logger.info(info_msg)
                self._logger.debug(
                    f"Supervision NAK (parseable): account={self._account}, "
                    f"seq={n_ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"csr_time={n_ctx['csr_time']}, raw={n_ctx['raw_hex']}"
                )
                self._ring_buffer.push_supervision_entry(
                    level="warning",
                    message=info_msg,
                    context={"account": self._account, "seq": n_ctx["seq"], "strike": strike},
                    is_routine=False,
                )
                await self._send_callback({
                    "type": "message_trace",
                    "dialog": {
                        "dialog_type": "supervision",
                        "routine": 0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elapsed_ms": int(n_ctx["elapsed_ms"]),
                        "id_token": f"{ENCRYPTED_MARKER}{NULL_TOKEN}" if self._preset.encryption_enabled else NULL_TOKEN,
                        "sequence": n_ctx["seq"],
                        "account": self._account,
                        "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
                        "response_hex": n_ctx["raw_hex"],
                    },
                })

            elif event == "nak_bad":
                n_ctx = cast(SM1NakLogCtx, ctx)
                strike = n_ctx["strike"]
                elapsed_s = n_ctx["elapsed_ms"] / 1000
                info_msg = f"Réponse invalide de la centrale — NAK non décodable (strike {strike}/3)"
                self._logger.warning(info_msg)
                self._logger.debug(
                    f"Supervision NAK (unparseable): account={self._account}, "
                    f"seq={n_ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"raw={n_ctx['raw_hex']}"
                )
                self._ring_buffer.push_supervision_entry(
                    level="error",
                    message=info_msg,
                    context={"account": self._account, "seq": n_ctx["seq"], "strike": strike},
                    is_routine=False,
                )
                await self._send_callback({
                    "type": "message_trace",
                    "dialog": {
                        "dialog_type": "supervision",
                        "routine": 0,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elapsed_ms": int(n_ctx["elapsed_ms"]),
                        "id_token": f"{ENCRYPTED_MARKER}{NULL_TOKEN}" if self._preset.encryption_enabled else NULL_TOKEN,
                        "sequence": n_ctx["seq"],
                        "account": self._account,
                        "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
                        "response_hex": n_ctx["raw_hex"],
                    },
                })

        except Exception as e:
            self._logger.error(f"Error logging SM1 supervision event: {e}")


# ===== SM2 ALARM EVENT STATE MACHINE METHODS =====

    async def _send_with_retry(
        self,
        event_item: EventItem,
        max_retries: int = MAX_RETRY_DEFAULT
    ) -> SM2State:
        """Send alarm event with retry logic until ACK/NAK or max retries.

        Implements retry loop with exponential backoff for alarm event delivery.
        Updates SM2 state and notifies on final failure.

        Args:
            event_item: EventItem with sia_code, zone, timestamp
            max_retries: Maximum retry attempts (default 3)

        Returns:
            Final SM2 state: SM2State.CONFIRMED (ACK) or SM2State.FAILED (NAK/timeout/max retries)

        Raises:
            No exceptions raised - failures result in SM2State.FAILED with notifications.

        Reference: story 5-2 Task 3 - Send with Retry Logic
        """
        # Initialize retry state
        self._sm2_state = SM2State.PENDING
        self._event_sia_code = event_item.sia_code
        self._event_zone = event_item.zone
        self._event_attempt_count = 0

        # Increment sequence number ONCE before the loop.
        # SIA DC-09 § 5.5.1.5: "The PE shall NOT increment the sequence number
        # when repeating a message due to a communication failure or no response
        # from a CSR." All retry attempts reuse the same seq.
        self._sia_seq = (self._sia_seq + 1) % SIA_SEQ_MAX

        for attempt in range(max_retries + 1):
            self._event_attempt_count = attempt + 1

            try:
                # Build SIA-DCS message frame and send with timeout
                frame = self._build_event_frame(event_item)
                result = await asyncio.wait_for(
                    self._send_raw(frame),
                    timeout=10.0
                )

                # Handle response
                status: Literal['ack', 'nak', 'timeout', 'tcp_drop'] = result['status']

                if status == "ack":
                    # Task 3.2.2e: ACK received - event confirmed
                    self._sm2_state = SM2State.CONFIRMED
                    _ack_hex = result['raw_response'].hex() if result.get('raw_response') else None
                    await self._log_sm2_event(
                        "confirmed",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=True
                        ),
                        response_hex=_ack_hex,
                    )
                    await self._update_info_commands({
                        'event_state': self._event_state_from_sm2(),
                        'event_label': self._event_label_from_sm2()
                    })
                    return SM2State.CONFIRMED

                elif status == "nak":
                    # NAK received: per daemon-design.md any NAK in v1.0 →
                    # _notify(BAD_CSR_RESPONSE) → SM2 FAILED, stop retrying.
                    # Parse timestamp for diagnostic logging only; v1.1 will use it
                    # for auto-heal resync (SIA DC-09 § 5.5.3.2 / daemon-design.md line 724).
                    raw_nak = result['raw_nak']
                    try:
                        if raw_nak:
                            csr_timestamp = parse_nak_timestamp(raw_nak)
                            self._logger.debug(
                                f"Event NAK: parseable CSR timestamp {csr_timestamp} "
                                f"(v1.1 auto-heal candidate)"
                            )
                    except (ValueError, TypeError):
                        self._logger.debug("Event NAK: unparseable timestamp (protocol anomaly)")

                    # Always T2 notification on event NAK (no parseable/undecodable split for SM2)
                    self._notify(
                        ErrorCode.BAD_CSR_RESPONSE,
                        BadCSRResponseCtx(
                            raw_frame=result['raw_nak'] or b"",
                            parse_error=f"Event NAK for zone={event_item.zone} sia_code={event_item.sia_code}",
                            csr_host=self._preset.host,
                            csr_port=self._preset.port,
                            transport="tcp" if self._preset.transport is TransportType.TCP else "udp",
                        )
                    )
                    self._sm2_state = SM2State.FAILED
                    _nak_hex = result['raw_response'].hex() if result.get('raw_response') else None
                    await self._log_sm2_event(
                        "failed_nak",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=True
                        ),
                        response_hex=_nak_hex,
                    )
                    await self._update_info_commands({
                        'event_state': self._event_state_from_sm2(),
                        'event_label': self._event_label_from_sm2()
                    })
                    return SM2State.FAILED

                elif status == "timeout":
                    # Timeout - retry or fail
                    if attempt < max_retries:
                        # Task 3.2.2d: Backoff before retry (fixed 1s for v1.0)
                        await self._log_sm2_event(
                            "failed_timeout",
                            SM2LogCtx(
                                zone=event_item.zone,
                                sia_code=event_item.sia_code,
                                attempt=self._event_attempt_count,
                                elapsed=0.0,
                                state_change=False
                            )
                        )
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        # Task 3.3: Max retries exhausted - T3 notification
                        self._sm2_state = SM2State.FAILED
                        await self._log_sm2_event(
                            "failed_max_retries",
                            SM2LogCtx(
                                zone=event_item.zone,
                                sia_code=event_item.sia_code,
                                attempt=self._event_attempt_count,
                                elapsed=0.0,
                                state_change=True
                            )
                        )
                        self._notify(
                            ErrorCode.EVENT_FAILED,
                            EventFailedCtx(
                                sia_code=event_item.sia_code,
                                sia_seq=self._sia_seq,
                                zone_name=event_item.zone,
                                max_retries=max_retries,
                                attempts_made=self._event_attempt_count,
                                last_error='timeout',
                            )
                        )
                        await self._update_info_commands({
                            'event_state': self._event_state_from_sm2(),
                            'event_label': self._event_label_from_sm2()
                        })
                        return SM2State.FAILED

            except (asyncio.TimeoutError, SIATransportError):
                # Timeout (wait_for) or transport error (connection refused, socket error)
                # — retry up to max_retries then T3.
                if attempt < max_retries:
                    await self._log_sm2_event(
                        "failed_timeout",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=False
                        )
                    )
                    await asyncio.sleep(1.0)
                    continue
                else:
                    self._sm2_state = SM2State.FAILED
                    await self._log_sm2_event(
                        "failed_max_retries",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=True
                        )
                    )
                    self._notify(
                        ErrorCode.EVENT_FAILED,
                        EventFailedCtx(
                            sia_code=event_item.sia_code,
                            sia_seq=self._sia_seq,
                            zone_name=event_item.zone,
                            max_retries=max_retries,
                            attempts_made=self._event_attempt_count,
                            last_error='timeout',
                        )
                    )
                    await self._update_info_commands({
                        'event_state': self._event_state_from_sm2(),
                        'event_label': self._event_label_from_sm2()
                    })
                    return SM2State.FAILED

            except (SIAProtocolError, AESEncryptionError) as e:
                self._logger.error(f"Protocol/transport error in _send_with_retry: {e}")
                self._sm2_state = SM2State.FAILED
                await self._log_sm2_event(
                    "failed_max_retries",
                    SM2LogCtx(
                        zone=event_item.zone,
                        sia_code=event_item.sia_code,
                        attempt=self._event_attempt_count,
                        elapsed=0.0,
                        state_change=True
                    )
                )
                self._notify(
                    ErrorCode.EVENT_FAILED,
                    EventFailedCtx(
                        sia_code=event_item.sia_code,
                        sia_seq=self._sia_seq,
                        zone_name=event_item.zone,
                        max_retries=max_retries,
                        attempts_made=self._event_attempt_count,
                        last_error='protocol_error',
                    )
                )
                await self._update_info_commands({
                    'event_state': self._event_state_from_sm2(),
                    'event_label': self._event_label_from_sm2()
                })
                return SM2State.FAILED

        # Fallback: loop exhausted without explicit return (defensive — should not reach here
        # under normal flow; all paths above return explicitly)
        self._sm2_state = SM2State.FAILED
        self._notify(
            ErrorCode.EVENT_FAILED,
            EventFailedCtx(
                sia_code=event_item.sia_code,
                sia_seq=self._sia_seq,
                zone_name=event_item.zone,
                max_retries=max_retries,
                attempts_made=self._event_attempt_count,
                last_error='loop_exhausted',
            )
        )
        await self._update_info_commands({
            'event_state': self._event_state_from_sm2(),
            'event_label': self._event_label_from_sm2()
        })
        return SM2State.FAILED

    def _build_event_frame(self, event_item: EventItem) -> bytes:
        """Build SIA-DCS frame for alarm event (Task 3.2.2b).

        Constructs complete SIA protocol frame for alarm event delivery with:
        - Account number and CRC format from preset (synced at call time)
        - Current sequence number (incremented once per event by _send_with_retry,
          NOT here — SIA DC-09 § 5.5.1.5)
        - Zone order number in extended data, zero-padded to 3 digits (never the label)
        - UTC timestamp (from event_item.timestamp or current UTC if unparseable)

        Args:
            event_item: EventItem with sia_code, zone, zone_number, timestamp

        Returns:
            Complete SIA frame as bytes: LF + CRC + Length + Message + CR

        Reference: story 5-2 Task 3.2.2b, sia_protocol.py encode_message()
        """
        try:
            # Build extended data with zone information.
            # The CSR is given the zone ORDER NUMBER, never the label: SIA DC-09 Annex B
            # formats it as 3 zero-padded digits → [#001234|BA 001]. Padding happens here
            # and only here. When the label matched no entry of the zone table PHP sends
            # zone_number=None and the frame carries no zone field at all.
            # Note: _sia_seq is incremented once by _send_with_retry before the loop.
            extended_data = {}
            if event_item.zone_number is not None:
                extended_data['zone'] = f"{event_item.zone_number:03d}"

            # Parse event timestamp for the SIA frame (M1).
            # event_item.timestamp is a string "HH:MM:SS,MM-DD-YYYY"; pass None on parse failure
            # to let encode_message use current UTC time.
            event_ts: datetime | None = None
            if event_item.timestamp:
                try:
                    event_ts = datetime.strptime(event_item.timestamp, TIMESTAMP_FORMAT).replace(
                        tzinfo=timezone.utc
                    )
                except (ValueError, AttributeError):
                    pass  # Fall through: encode_message will stamp with current UTC

            frame = self._sia_builder.encode_message(
                account_number=self._account,
                event_code=event_item.sia_code,
                account_prefix=self._account_prefix or "L0",
                receiver_number=self._receiver_prefix,
                extended_data=extended_data if extended_data else None,
                timestamp=event_ts,
                encryption=False  # No encryption in v1.0
            )

            return frame

        except SIAProtocolError:
            raise
        except (ValueError, AttributeError, AESEncryptionError) as e:
            self._logger.error(f"Error building event frame: {e!r}")
            raise SIAProtocolError(f"Frame build failed: {e}") from e

    async def _log_sm2_event(
        self,
        transition: str,
        ctx: SM2LogCtx | None = None,
        response_hex: str | None = None,
    ) -> None:
        """Log SM2 state transitions with French INFO + English DEBUG lines (Task 7).

        Logs alarm event state transitions to both logger and ring buffer.
        Follows dual-line pattern: French user-facing (INFO) + English technical (DEBUG).

        Args:
            transition: State transition type (e.g., "event_received", "confirmed", "failed")
            ctx: Optional SM2LogCtx with zone, sia_code, attempt, elapsed, state_change
            response_hex: Optional hex string of the raw CSR response (ACK/NAK bytes).

        Reference: story 5-2 Task 7, logging-design.md SM2 transition table
        """
        try:
            from . import messages

            if not ctx:
                assert self._event_sia_code is not None  # invariant: set before SM2 enters PENDING
                ctx = SM2LogCtx(
                    zone=self._event_zone,
                    sia_code=self._event_sia_code,
                    attempt=self._event_attempt_count,
                    elapsed=0.0,
                    state_change=True
                )

            # French user-facing message (from messages.py)
            if transition == "event_received":
                info_msg = messages.SM2_EVENT_RECEIVED.format(
                    type=ctx['sia_code'],
                    zone=ctx['zone'] or "(pas de zone)"
                )
            elif transition == "confirmed":
                info_msg = messages.SM2_CONFIRMED.format(
                    type=ctx['sia_code'],
                    zone=ctx['zone'] or "(pas de zone)"
                )
            elif transition == "failed_timeout":
                info_msg = messages.SM2_RETRY.format(
                    attempt=ctx['attempt'],
                    max=MAX_RETRY_DEFAULT
                )
            elif transition == "failed_nak":
                info_msg = messages.SM2_FAILED_NAK.format(
                    type=ctx['sia_code'],
                    zone=ctx['zone'] or "(pas de zone)"
                )
            elif transition == "failed_no_network":
                info_msg = messages.SM2_FAILED_NO_NETWORK.format(
                    type=ctx['sia_code'],
                    zone=ctx['zone'] or "(pas de zone)"
                )
            elif transition == "failed_max_retries":
                info_msg = messages.SM2_FAILED.format(
                    type=ctx['sia_code'],
                    max=MAX_RETRY_DEFAULT,
                    zone=ctx['zone'] or "(pas de zone)"
                )
            else:
                info_msg = f"SM2 transition: {transition}"

            # English technical DEBUG line
            debug_msg = (
                f"SM2 {transition}: zone={ctx['zone']}, sia={ctx['sia_code']}, "
                f"attempt={ctx['attempt']}, elapsed={ctx['elapsed']:.2f}s"
            )

            # Log to logger
            self._logger.info(info_msg)
            self._logger.debug(debug_msg)

            # Log to ring buffer (_ring_buffer always initialized in __init__)
            self._ring_buffer.push_supervision_entry(
                level="info" if "failed" not in transition else "error",
                message=info_msg,
                context={
                    "account": self._account,
                    "zone": ctx['zone'],
                    "sia_code": ctx['sia_code'],
                    "attempt": ctx['attempt']
                },
                is_routine=False,
            )

            # Emit message_trace callback for protocol inspector
            dialog: dict = {
                "dialog_type": "alarm",
                "routine": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": int(ctx["elapsed"] * 1000),
                "id_token": f"{ENCRYPTED_MARKER}{SIA_DCS_TOKEN}" if self._preset.encryption_enabled else SIA_DCS_TOKEN,
                "sequence": self._sia_seq,
                "account": self._account,
                "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
            }
            if response_hex is not None:
                dialog["response_hex"] = response_hex
            await self._send_callback({"type": "message_trace", "dialog": dialog})

        except asyncio.CancelledError:
            raise  # propagate task cancellation (daemon-design.md § CancelledError safety rule)
        except (KeyError, AttributeError, TypeError) as e:
            self._logger.error(f"Error logging SM2 event: {e!r}")


    # ===== TASK 3 (Story 5-3): ENQUEUE HELPER METHODS =====

    # 6 params instead of the 5-param limit: the python-style rule would suggest a
    # dataclass, but the 4 leading params are the established positional signature of
    # ~20 level2 tests (`_enqueue_event("BA", "Salon", None, 3)`). zone_number is
    # keyword-only so the arity can only grow behind the `*`, never positionally.
    async def _enqueue_event(  # pylint: disable=too-many-arguments
        self,
        sia_code: SiaEventCode,
        zone: str | None,
        media_url: str | None,
        retries_left: int = MAX_RETRY_DEFAULT,
        *,
        zone_number: int | None = None,
    ) -> None:
        """Enqueue an alarm event for SM2 processing at EVENT priority.

        Places a 4-tuple into the priority queue with QUEUE_PRIORITY_EVENT (0).
        The queue consumer dequeues this and dispatches to _send_with_retry().
        The enqueue is fire-and-forget: on_message() returns immediately after calling this.

        Args:
            sia_code: SIA event code — "BA" (burglary), "FA" (fire), "PA" (panic)
            zone: Zone name from PHP #zone# tag, or None if not specified
            media_url: Optional camera/media URL for SIA [V...] extended field, or None
            retries_left: Retry budget (default MAX_RETRY_DEFAULT=3). Reset to full
                          when re-enqueuing after TCP_RECONNECTING.
            zone_number: Zone order number resolved by PHP, or None when the label
                         matched no entry of the zone table (frame sent without zone).

        Reference: daemon-design.md Component 1 — Task 1.6 on_message()
        """
        counter: int = next(self._queue_counter)
        payload: EventQueuePayload = {
            "sia_code": sia_code,
            "zone": zone,
            "zone_number": zone_number,
            "media_url": media_url,
            "retries_left": retries_left,
        }
        await self._queue.put((QUEUE_PRIORITY_EVENT, counter, QUEUE_TYPE_EVENT, payload))
        self._logger.debug(
            f"EVENT enqueued: sia_code={sia_code}, zone={zone}, "
            f"zone_number={zone_number}, counter={counter}"
        )

    async def _enqueue_supervision(self) -> None:
        """Enqueue a supervision NULL frame at SUPERVISION priority.

        Places a 4-tuple into the priority queue with QUEUE_PRIORITY_SUPERVISION (1).
        Because QUEUE_PRIORITY_SUPERVISION > QUEUE_PRIORITY_EVENT, any queued alarm
        will be dequeued and sent before the next supervision frame.
        The consumer calls _send_supervision() which handles the full ACK/NAK cycle.

        Reference: daemon-design.md Component 1 — _supervision_loop() / Task B.3
        Reference: SIA DC-09-2021 § 5.5.2 (Supervision Message)
        """
        counter: int = next(self._queue_counter)
        await self._queue.put((QUEUE_PRIORITY_SUPERVISION, counter, QUEUE_TYPE_SUPERVISION, {}))
        self._logger.debug(f"SUPERVISION enqueued (counter={counter})")

    # ===== TASK 4 (Story 5-3): QUEUE CONSUMER COROUTINE =====

    async def _queue_consumer(self) -> None:
        """Single-consumer coroutine: dequeue and dispatch SM1/SM2 tasks.

        Loops forever awaiting items from _queue. Routes:
        - SUPERVISION items → _send_supervision() (full ACK/NAK cycle, updates SM1)
        - EVENT items → _send_with_retry() (full retry cycle, updates SM2)

        SM1 state guards applied before dispatch:
        - TCP_RECONNECTING: consumer waits on _sm1_state_changed gate (items stay in queue,
          no dequeue, no re-enqueue, no spin). Resumes when SM1 transitions out.
        - NO_NETWORK + any: drop silently (daemon stopping, queue abandoned)

        One-at-a-time guarantee: consumer awaits each dispatch before dequeuing next.
        Satisfies SIA DC-09 § 5.3 "send one, wait for acknowledgement" per-account rule.

        TCP_RECONNECTING gate detail: before each queue.get(), the consumer checks SM1 state.
        While TCP_RECONNECTING it clears _sm1_state_changed and awaits it. When the reconnect
        loop calls _set_sm1_state() (→ INITIALIZING on success, → NO_NETWORK on failure),
        the event fires and the consumer re-evaluates and dequeues normally.

        Reference: daemon-design.md Component 1 — _queue_consumer() / Priority Queue coordination
        Reference: SIA DC-09-2021 § 5.3 Communication Sequence
        """
        while True:
            # Gate: wait for SM1 to leave TCP_RECONNECTING before dequeuing.
            # Items stay in the queue — no spin, no re-enqueue, no sleep.
            while self._sm1_state == SM1State.TCP_RECONNECTING:
                self._sm1_state_changed.clear()
                # Re-check after clear to avoid a missed-wakeup race (set() between
                # the while condition check and clear() would be lost without this).
                if self._sm1_state == SM1State.TCP_RECONNECTING:
                    self._logger.debug(
                        "SM1 TCP_RECONNECTING: queue consumer waiting for state change"
                    )
                    await self._sm1_state_changed.wait()

            priority, counter, item_type, payload = await self._queue.get()
            self._logger.debug(
                f"Dequeued {item_type} (priority={priority}, counter={counter})"
            )
            try:
                if item_type == QUEUE_TYPE_SUPERVISION:
                    if self._sm1_state == SM1State.NO_NETWORK:
                        # Daemon stopping: drop silently
                        self._logger.debug(
                            f"SM1 NO_NETWORK: SUPERVISION dropped (daemon stopping, "
                            f"counter={counter})"
                        )
                    else:
                        await self._send_supervision()

                elif item_type == QUEUE_TYPE_EVENT:
                    event_payload: EventQueuePayload = payload  # type: ignore[assignment]

                    if self._sm1_state == SM1State.NO_NETWORK:
                        self._sm2_state = SM2State.FAILED
                        self._event_sia_code = event_payload["sia_code"]
                        self._event_zone = event_payload.get("zone")
                        self._notify(
                            ErrorCode.EVENT_FAILED,
                            EventFailedCtx(
                                sia_code=event_payload["sia_code"],
                                sia_seq=self._sia_seq,
                                zone_name=event_payload.get("zone"),
                                max_retries=0,
                                attempts_made=0,
                                last_error="no_network",
                            ),
                        )
                        self._logger.debug(
                            f"SM1 NO_NETWORK: EVENT failed (counter={counter}, "
                            f"sia_code={event_payload['sia_code']})"
                        )

                    else:
                        # Normal send path (HEALTHY, INITIALIZING, DEGRADED):
                        # build EventItem and dispatch to SM2.
                        # Per SIA DC-09 § 5.5.1.5: fresh timestamp at actual send time.
                        timestamp_str = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
                        event_item = EventItem(
                            sia_code=event_payload["sia_code"],
                            zone=event_payload.get("zone"),
                            timestamp=timestamp_str,
                            zone_number=event_payload.get("zone_number"),
                        )
                        await self._send_with_retry(
                            event_item,
                            max_retries=event_payload.get("retries_left", MAX_RETRY_DEFAULT),
                        )

            except Exception as e:
                # Log and swallow: consumer must not exit on transient dispatch errors.
                # task_done() is guaranteed by the finally block below regardless.
                self._logger.error(
                    f"Queue consumer: unhandled exception dispatching {item_type} "
                    f"(counter={counter}): {e}"
                )
            finally:
                self._queue.task_done()

    # ===== TASK 5/6 (Story 5-3): SUPERVISION LOOP =====

    async def _supervision_loop(self) -> None:
        """Periodically enqueue supervision NULL frames for SM1 keep-alive.

        Sleeps for supervision_interval_s, then enqueues a SUPERVISION item.
        The queue consumer dequeues it and calls _send_supervision() for the full
        send/ACK/NAK cycle. If an alarm is queued, it will be processed first
        (EVENT priority=0 wins over SUPERVISION priority=1 — safety-critical).

        The timer is reset each cycle regardless of ACK/NAK result — the SM1 handler
        (_send_supervision) manages strike counter and state transitions independently.

        Reference: daemon-design.md Component 1 — _supervision_loop() / Task B.3
        Reference: SIA DC-09-2021 § 5.5.2 Supervision Message
        """
        interval: float = float(getattr(self._preset, 'supervision_interval_s', SUPERVISION_INTERVAL_S))
        while True:
            await asyncio.sleep(interval)
            self._logger.debug(
                f"Supervision interval fired ({interval}s), enqueueing NULL frame"
            )
            await self._enqueue_supervision()

    # ===== TASK 7 (Story 5-3): on_message — ALARM DISPATCH FROM PHP =====

    async def _on_message_dispatch(self, message: dict) -> None:
        """Framework callback adapter: normalize raw PHP message dict → on_message().

        The jeedomdaemon framework passes the full parsed JSON dict including 'apikey'.
        This adapter strips 'apikey', extracts 'cmd', and delegates to on_message().

        Args:
            message: Full parsed JSON dict from PHP sendToDaemon() socket.
                     Expected shape: {"cmd": "burglarAlarm", "zone": "...", "apikey": "..."}

        Reference: story 6-6 AC4, Dev Notes § on_message() framework contract
        """
        message.pop("apikey", None)
        cmd: str = message.pop("cmd", "")
        params: OnMessageParams = cast(OnMessageParams, message)
        await self.on_message(cmd, params)

    async def on_message(self, cmd: str, params: OnMessageParams) -> None:
        """Receive alarm command from PHP and enqueue for SM2 processing.

        Called by _on_message_dispatch() after apikey/cmd extraction.
        Extracts alarm type, zone, and media_url from params and enqueues
        an EVENT item into the priority queue. Returns immediately (fire-and-forget):
        the actual send happens asynchronously in _queue_consumer() → _send_with_retry().

        Args:
            cmd: Command name from PHP — "burglarAlarm", "fireAlarm", or "panicAlarm"
            params: PHP payload dict with optional keys:
                - "zone": str — zone name from #zone# tag (None if absent)
                - "zone_number": int — zone order number PHP resolved against the zone
                  table (None when the label matched no entry: frame sent without zone)
                - "media_url": str — camera/media URL (None if absent)

        Reference: daemon-design.md Component 1 — Task 1.6 on_message()
        Reference: daemon-design.md — "Forbidden char policy" for media_url
        """
        sia_code: SiaEventCode | None = _EVENT_SIA_CODES.get(cmd)
        if sia_code is None:
            self._logger.warning(f"on_message: unknown alarm command '{cmd}' — ignored")
            return

        zone: str | None = params.get("zone")
        media_url: str | None = params.get("media_url")

        # PHP sends null when the label matched no entry of the zone table. Coerce
        # defensively: a JSON string would otherwise break the f"{n:03d}" format later.
        raw_zone_number = params.get("zone_number")
        zone_number: int | None = None
        if raw_zone_number is not None:
            try:
                zone_number = int(raw_zone_number)
            except (TypeError, ValueError):
                self._logger.warning(
                    f"on_message: unusable zone_number {raw_zone_number!r} — "
                    "frame will be sent without zone"
                )

        self._logger.debug(
            f"on_message: cmd={cmd} → sia_code={sia_code}, zone={zone}, "
            f"zone_number={zone_number}, media_url={'<set>' if media_url else None}"
        )
        await self._enqueue_event(sia_code, zone, media_url, zone_number=zone_number)

    # ===== TASK 5 (Story 5-3): on_start — DAEMON STARTUP =====

    async def on_start(self) -> None:
        """Start daemon: initialize queue state and launch background tasks.

        Resets queue, counters, and SM states for a clean start (idempotent across restarts).
        Launches two background tasks tracked in _tasks:
        - queue_consumer: dequeues EVENT/SUPERVISION items and dispatches
        - supervision_loop: periodically enqueues supervision NULL frames

        Reference: daemon-design.md Component 1 — Daemon lifecycle / Task 1.1–1.7
        """
        # Cancel any previously running tasks before resetting (idempotent restart safety).
        # Prevents orphaned tasks if on_start() is called again without on_stop().
        if self._tasks:
            for task in list(self._tasks):
                task.cancel()
            # Await all tasks to completion (CancelledError swallowed via return_exceptions)
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # Reset queue state (fresh start on every on_start call)
        self._queue = asyncio.PriorityQueue()
        self._queue_counter = itertools.count()
        self._sm1_state_changed.clear()

        # Initialize SM states
        self._sm1_state = SM1State.INITIALIZING
        self._sm2_state = SM2State.IDLE
        self._strike_counter = 0
        self._sm1_t3_fired = False

        from . import messages
        self._logger.info(messages.SM1_STARTING)

        # Push INITIALIZING to PHP before any task starts — fail-fast if unreachable.
        # event_state/event_label intentionally NOT included (retained across restarts).
        await self.send_to_jeedom({
            "type": "info_update",
            "supervision_state": 1,
            "supervision_label": SM1_INITIALIZING_FR,
        })

        # Create and start transport before launching queue consumer
        if self._preset.transport is TransportType.UDP:
            t: SIABaseTransport = SIAUDPTransport(
                self._preset.host,
                self._preset.port,
                self._preset.receive_timeout_s,
                crc_format=self._preset.crc_format,
            )
        else:  # TransportType.TCP — exhaustive: TransportType only has UDP and TCP
            t = SIATCPTransport(
                self._preset.host,
                self._preset.port,
                self._preset.connect_timeout_s,
                self._preset.receive_timeout_s,
                crc_format=self._preset.crc_format,
            )
        await t.start()  # no-op for TCP; creates DatagramTransport for UDP
        self._sia_transport = t

        self._logger.debug("on_start: launching queue_consumer and supervision_loop")

        # Launch consumer and supervision loop — both tracked in _tasks
        self._track_task(self._queue_consumer(), name="queue_consumer")
        self._track_task(self._supervision_loop(), name="supervision_loop")

    # ===== TASK 7 (Story 5-4): on_stop — DAEMON SHUTDOWN =====

    async def on_stop(self) -> None:
        """Graceful shutdown: push final INFO, drain queue, cancel tasks, close transport.

        5-step sequence per daemon-design.md Task 1.11:
        1. Terminal INFO push (best-effort)
        2. Queue drain (discard pending items)
        3. Cancel all tracked tasks
        4. Await task completion with hard timeout
        5. Close transport (guaranteed None reset)

        Reference: daemon-design.md Task 1.11
        """
        # Step 1 — STOPPED push (best-effort, event_state/event_label retained across restarts)
        try:
            await self._send_callback({
                "type": "info_update",
                "supervision_state": 0,
                "supervision_label": "ARRÊTÉ",
            })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._logger.warning(f"on_stop: STOPPED push failed: {e!r}")

        # Step 2 — Queue drain (discard pending items, no callbacks)
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Step 3 — Cancel all tracked tasks
        for task in list(self._tasks):
            task.cancel()

        # Step 4 — Await task completion with hard timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=ON_STOP_TASK_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            self._logger.error(
                f"on_stop: tasks did not complete within {ON_STOP_TASK_TIMEOUT_S}s timeout"
            )

        # Step 5 — Close transport (guaranteed None reset via finally)
        if self._sia_transport is not None:
            try:
                await self._sia_transport.close()
            except OSError:
                self._logger.warning("on_stop: transport close raised OSError — ignoring")
            finally:
                self._sia_transport = None

        self._logger.info("Démon SIA DC-09 arrêté")


# ===== ENTRY POINT =====
# Production entry point wired in Epic 3 (PHP core): PHP builds CSRPreset from
# JSON config and passes it via CLI args → BaseDaemon → SIADaemon.__init__(preset).
# Direct `python3 daemon.py` execution is not supported without a preset.
