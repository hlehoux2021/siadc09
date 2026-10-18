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

Reference: internal-docs/design/daemon-design.md Component 1
Reference: internal-docs/design/supervision-design.md ADR-11 SM1 State Machine
Reference: internal-docs/design/error-handler-design.md T1/T2/T3 error tiers
"""

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Coroutine, Final, Iterator, Literal, TypedDict, cast

from jeedomdaemon import BaseDaemon, BaseConfig

from .error_handler import (
    BadCSRResponseCtx,
    EVENT_FAILED_ENCRYPTION_KEY,
    ErrorCode,
    EventFailedCtx,
    NotificationContext,
    SM1DisconnectedCtx,
    SM1NakCtx,
    SM1TimeoutCtx,
    TransportPermanentCtx,
    USER_ADDRESSED_SIA_CODES,
    event_type_fr,
)
from . import DAEMON_VERSION
from .messages import (
    DAEMON_VERSION_INFO,
    ENCRYPTION_KEY_INVALID,
    ENCRYPTION_KEY_INVALID_TITLE,
    SM1_DEGRADED_1_2_FR,
    SM1_DEGRADED_3_FR,
    SM1_HEALTHY_FR,
    SM1_INITIALIZING_FR,
    SM1_TCP_RECONNECTING_FR,
    SM1_NO_NETWORK_FR,
    SM1_CONFIG_ERROR_FR,
)
from .frigate_prefetch import PrefetchResult, prefetch_alarm_media
from .ring_buffer import RingBuffer, make_message_entry
from .sia_protocol import (
    NULL_TOKEN,
    RP_SIA_CODE,
    SIA_DCS_TOKEN,
    SIAMessageBuilder,
    SIAProtocolError,
    SIATransportError,
    TIMESTAMP_FORMAT,
    parse_frame_header,
    parse_nak_timestamp,
)
from .sia_crypto import AESEncryptionError, AESKeyError, parse_hex_key
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
    CONFIG_ERROR = "CONFIG_ERROR"    # Encryption on, key invalid: nothing is sent (story 1-5 AC3)


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


# SIA event codes: Burglary, Fire, Panic alarms + Burglary Cancel + Opening/disarm (story 13-1)
# + Closing/arm (story 13-4). BC/OP/CL address by user number (ADR-18), unlike BA/FA/PA which
# address by zone — see EventItem.user_number and _build_event_frame().
SiaEventCode = Literal['BA', 'FA', 'PA', 'BC', 'OP', 'CL']


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
        sia_code: Event SIA code (BA=burglary, FA=fire, PA=panic, BC=cancel, OP=disarm)
        zone: Zone name from alarm command #zone# tag (None if not specified)
        timestamp: Event timestamp from make_timestamp()
        zone_number: Zone order number resolved by PHP against the zone table (None when the
                     label matched no entry). Address source for BA/FA/PA only (story 13-1,
                     ADR-18) — ignored by _build_event_frame() for BC/OP/CL.
        user_number: Configured SIA user number (wizard step 3, `sia_user_number`) for
                     BC/OP/CL — DC-03 addresses these by user, never by zone (stories
                     13-1/13-4, ADR-18).
        media_url: Optional camera/media URL for the SIA [V...] extended field, or None
                   (story 14-1) — reaches the frame via _build_event_frame()'s extended_data
        callback: Optional callback function called when event completes (signature: callback(success: bool))
    """
    sia_code: SiaEventCode
    zone: str | None  # Zone name or None — logs, notifications, inspector
    timestamp: str  # SIA protocol timestamp HH:MM:SS,MM-DD-YYYY
    zone_number: int | None = None  # Reaches the SIA frame as the Annex B zone digits (BA/FA/PA)
    user_number: int | None = None  # Reaches the SIA frame as the address digits (BC/OP/CL)
    media_url: str | None = None  # Reaches the SIA frame as the [V...] extended-data block
    callback: Any | None = None  # Callback function(success: bool) when send completes


# ===== CONSTANTS =====

SUPERVISION_INTERVAL_S = 60  # Default supervision interval (seconds)
RECONNECT_BACKOFF_FACTORS: Final[tuple[float, ...]] = (1.0, 2.0, 4.0, 10.0, 10.0, 10.0)
RECONNECT_BACKOFF_CAP_S: Final[float] = 300.0  # Ceiling for any single reconnect attempt's delay
STRIKE_CAP = 3  # Strike counter capped at 3
SIA_SEQ_MAX: Final[int] = 10000  # Sequence wraps 9999 → 0000 (SIA DC-09 § 5.5.1.5)
# Story 1-5 AC4 (§ 5.6.1.2): immediate re-sends of a NAKed supervision frame before a strike.
SUPERVISION_NAK_RESENDS: Final[int] = 2
# A NAK timestamp further than this from local UTC is ignored (unauthenticated, § 5.5.3.2).
NAK_TIMESTAMP_SANITY: Final[timedelta] = timedelta(hours=24)
# message_center logical_id of the invalid-key notification (story 1-5 AC3).
ENCRYPTION_KEY_LOGICAL_ID: Final[str] = "encryption_key"


def _reconnect_backoff_delay_s(base_delay_s: float, attempt_index: int) -> float:
    """Compute the TCP reconnect delay for a given attempt (story 7-2 AC19).

    Growing backoff schedule: delay = base_delay_s * RECONNECT_BACKOFF_FACTORS[attempt_index],
    capped at RECONNECT_BACKOFF_CAP_S. Attempts beyond the factor table (a --retry-count larger
    than len(RECONNECT_BACKOFF_FACTORS)) reuse the cap.

    Args:
        base_delay_s: CSRPreset.reconnect_delay_s — the schedule's base (first-attempt) delay.
        attempt_index: 0-based attempt number.

    Returns:
        Delay in seconds to wait before this attempt's probe.
    """
    if attempt_index < len(RECONNECT_BACKOFF_FACTORS):
        return min(base_delay_s * RECONNECT_BACKOFF_FACTORS[attempt_index], RECONNECT_BACKOFF_CAP_S)
    return RECONNECT_BACKOFF_CAP_S


# ===== TASK 1 (Story 5-3): PRIORITY QUEUE CONSTANTS AND TYPES =====

# Priority values for asyncio.PriorityQueue (min-heap: lower number = higher priority).
# EVENT (alarms) always win — alarm delivery is safety-critical (daemon-design.md line 503).
QUEUE_PRIORITY_EVENT: Final[int] = 0        # Alarms dequeued first
QUEUE_PRIORITY_SUPERVISION: Final[int] = 1  # Supervision dequeued second

# Queue item type string identifiers (narrowed to Literal so the PriorityQueue
# type annotation tuple[int, int, QueueItemType, QueuePayload] is satisfied).
QUEUE_TYPE_EVENT: Final[Literal["EVENT"]] = "EVENT"
QUEUE_TYPE_SUPERVISION: Final[Literal["SUPERVISION"]] = "SUPERVISION"
# Story 17-3: RP cyclic test (own type: the loop needs an exchange-done event, an EVENT
# item has none). Shares the supervision priority; ties fall back to the counter.
QUEUE_TYPE_RP: Final[Literal["RP"]] = "RP"
QUEUE_PRIORITY_RP: Final[int] = QUEUE_PRIORITY_SUPERVISION

# Type alias for the item_type field (Literal for static analysis)
QueueItemType = Literal["EVENT", "SUPERVISION", "RP"]

# Default retry budget when enqueuing a new alarm event
MAX_RETRY_DEFAULT: Final[int] = 3
# Wait for the CSR's answer to one RP frame (story 17-3); a miss is one SM1 strike.
RP_SEND_TIMEOUT_S: Final[float] = 10.0


class OnMessageParams(TypedDict, total=False):
    """Parameters passed to on_message() from PHP sendToDaemon().

    All keys are optional — zone, zone_number and media_url may be absent for simple
    alarm commands. zone is the label (#zone# tag), zone_number the order number PHP
    resolved against sia_zone_mappings.

    camera_eqlogic_id/camera_name/frigate_host (Story 14-2, ADR-17 Amendment 3): present
    only for the "prefetchEvent" command, sent by siaDC09Cmd::_resolvePrefetchTarget().
    run_id (Story 14-4, ADR-17 Amendment 4): present only for "prefetchEvent" — a numeric
    string PHP generates (microtime(true)) and owns; echoed back verbatim on every
    "prefetch_result" callback of the run, so PHP's cache can tell a newer run from an
    older, stale one (siaDC09::_handlePrefetchResult()'s monotonic replace rule).

    sia_code (Story 13-1, ADR-18): present only for "disarm"/"alarmReset" — these two commands
    carry their own sia_code per sendToDaemon() call (BC and/or OP), rather than a single
    fixed code per command name, so on_message() reads sia_code from the payload instead of
    the static _EVENT_SIA_CODES mapping used by burglarAlarm/fireAlarm/panicAlarm/arm.
    user_number (Story 13-1/13-4, ADR-18) is the configured SIA user (wizard step 3) — the
    address field for BC/OP/CL. Present for "disarm"/"alarmReset" and "arm" alike; "arm"
    never sends sia_code (its code, CL, is fixed).
    """
    zone: str
    zone_number: int | None
    media_url: str
    camera_eqlogic_id: int
    camera_name: str
    frigate_host: str
    run_id: str
    sia_code: str
    user_number: int | None


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
    user_number: int | None  # Configured SIA user, address field for BC/OP/CL (13-1/13-4)
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
# Story 13-1: "disarm"/"alarmReset" are deliberately absent — see
# _VARIABLE_SIA_CODE_COMMANDS below. burglaryCancel (13-1's superseded per-zone fan-out
# design) is removed; it was never shipped.
# Story 13-4: "arm" is a fixed mapping (always CL, unconditionally) — unlike disarm/
# alarmReset, it never varies its code, so it belongs here, not in
# _VARIABLE_SIA_CODE_COMMANDS.
_EVENT_SIA_CODES: Final[dict[str, SiaEventCode]] = {
    "burglarAlarm": "BA",
    "fireAlarm": "FA",
    "panicAlarm": "PA",
    "arm": "CL",
}

# Story 13-1 (ADR-18): disarm/alarmReset each make one sendToDaemon() call per frame, with
# its own "sia_code" key (BC and/or OP) — PHP decides per-frame, not a fixed 1-code-per-cmd
# mapping like _EVENT_SIA_CODES above. on_message() reads params["sia_code"] for these two
# commands instead of a static lookup. Documented deviation from daemon-design.md's original
# "_EVENT_SIA_CODES gains entries for disarm/alarmReset" phrasing — a fixed mapping cannot
# express "BC then OP from the same command name" (see php-core-design.md, "disarm — wired on
# release").
_VARIABLE_SIA_CODE_COMMANDS: Final[frozenset[str]] = frozenset({"disarm", "alarmReset"})

# The only codes disarm/alarmReset are allowed to declare via params["sia_code"] (story 13-1).
# Deliberately narrower than _USER_ADDRESSED_SIA_CODES: CL (story 13-4) is user-addressed too,
# but only ever reaches the queue via the fixed "arm" → CL mapping — a disarm/alarmReset
# payload declaring CL is rejected, never framed as an arm report.
_VARIABLE_ALLOWED_SIA_CODES: Final[frozenset[str]] = frozenset({"BC", "OP"})

# User-addressed SIA codes (ADR-18): address by configured sia_user_number, never a zone —
# BC/OP/CL. Framing only (_build_event_frame(), _event_context_prefix()); defined once in
# error_handler.py, which also uses it for the EVENT_FAILED address clause.
_USER_ADDRESSED_SIA_CODES: Final[frozenset[str]] = USER_ADDRESSED_SIA_CODES

# DC-03 area (partition) carried as "ri" in every event's data block → [#acct|Nri1/CL001].
# Fixed: the plugin has a single siaDC09 equipment, so a single area. Ajax hubs send ri1 for
# alarm events and Scutum shows CL/OP as "CODE INCONNU" without it (internal-docs/ajax.md).
SIA_AREA_NUMBER: Final[int] = 1


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
            _event_sia_code: Latest event SIA code (BA=burglary, FA=fire, PA=panic, BC=cancel,
                             OP=disarm, CL=arm)
            _event_zone: Latest zone name from alarm command #zone# tag
            _event_user_number: Latest configured SIA user number (BC/OP/CL address field,
                             stories 13-1/13-4, ADR-18)
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
        self._event_sia_code: SiaEventCode | None = None  # Latest code (BA|FA|PA|BC|OP|CL)
        self._event_zone: str | None = None  # Latest zone from command #zone# tag
        self._event_user_number: int | None = None  # Latest user number (BC/OP/CL)
        self._event_attempt_count: int = 0  # Track send attempts for current event
        # Why FAILED was reached, for _event_label_from_sm2()'s wording split:
        # 'nak' = the CSR explicitly rejected the event; 'no_response' = no answer at
        # all (timeout/transport/protocol error/loop exhaustion) despite retries.
        # 'config' = never sent: encryption is on but the key is invalid (story 1-5 AC3).
        self._event_failure_reason: Literal["nak", "no_response", "config"] | None = None

        # Configuration — populated from preset and CLI config
        # Fix #5: account must come from preset (was empty string, causing frame build failures)
        self._account: str = preset.account_number
        self._receiver_prefix: str = getattr(config, "receiver_prefix", "") or ""
        # Fix #6: empty prefix fails SIA validation; "L0" is the protocol default
        self._account_prefix: str = getattr(config, "account_prefix", "") or "L0"
        # Story 1-5 AC3: the key is 32/48/64 hex digits, decoded once. An invalid
        # key leaves b"" — with encryption on, _encryption_config_error() then
        # blocks every send (never a plaintext fallback). The key is never logged.
        _enc_key_str: str = getattr(config, "encryption_key", "") or ""
        self._encryption_key: bytes = b""
        _enc_key_error: str | None = None
        try:
            self._encryption_key = parse_hex_key(_enc_key_str)
        except AESKeyError as e:
            _enc_key_error = str(e)  # parse_hex_key messages never contain the key
        # Set once the CONFIG_ERROR notification went out (sent once per daemon run).
        self._encryption_config_notified: bool = False
        self._sia_transport: SIABaseTransport | None = None  # Active transport; None before on_start()

        # State & data
        self._sia_seq: int = 0
        # Story 17.1: CSRPreset accepts only crc_format="hex" → always the SIA hex CRC builder.
        self._sia_builder: SIAMessageBuilder = SIAMessageBuilder(crc_format="SIA")
        self._ring_buffer: RingBuffer = RingBuffer()
        self._tasks: set[asyncio.Task] = set()
        self._logger = logging.getLogger(__name__)
        if preset.encryption_enabled and _enc_key_error is not None:
            self._logger.error(f"Encryption enabled but key rejected: {_enc_key_error} — nothing will be sent")

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
        # Story 17-2: set when no supervision exchange is outstanding (initially set);
        # cleared on enqueue, set by the queue consumer once the item is fully handled.
        self._supervision_exchange_done: asyncio.Event = asyncio.Event()
        self._supervision_exchange_done.set()
        # Story 17-3: released by the consumer's finally for each RP item (like supervision).
        self._rp_exchange_done: asyncio.Event = asyncio.Event()
        self._rp_exchange_done.set()

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
        """Build the "{Type} (zone {zone})" / "{Type} (utilisateur {n})" prefix for active
        SM2 labels.

        The alarm type is derived from the latest SIA code via event_type_fr()
        and capitalised for display (e.g. "intrusion" → "Intrusion"). BC/OP/CL (stories
        13-1, 13-4, ADR-18) address by configured user number, never by zone — DC-03 p.4 —
        so they use _event_user_number instead of _event_zone. BA/FA/PA keep the zone clause.

        Returns:
            str: e.g. "Intrusion (zone 3)" or "Annulation (utilisateur 1)". Falls back to
                 "Alarme" if the type is unknown, and omits the clause if no zone/user is
                 recorded.
        """
        if self._event_sia_code:
            type_fr = event_type_fr(self._event_sia_code)
            type_label = type_fr[:1].upper() + type_fr[1:]
        else:
            type_label = "Alarme"
        if self._event_sia_code in _USER_ADDRESSED_SIA_CODES:
            if self._event_user_number is not None:
                return f"{type_label} (utilisateur {self._event_user_number})"
            return type_label
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
            - FAILED, reason='nak' → "{Type} (zone {zone}) : Refusé par la centrale"
            - FAILED, reason='config' → "{Type} (zone {zone}) : Non transmise — clé de
              chiffrement invalide" (story 1-5 AC3: nothing was sent)
            - FAILED, reason='no_response' (or unset) → "{Type} (zone {zone}) : Sans
              réponse de la centrale"

        The type/zone prefix (built by _event_context_prefix) names the alarm in
        progress so the widget shows which event is being transmitted, not just a
        bare status word. IDLE has no active event, so it stays "Inactif". FAILED
        splits on _event_failure_reason: an explicit CSR NAK ("Refusé") and a plain
        timeout/transport/protocol failure with no reply at all ("Sans réponse") are
        operationally different facts and must not be conflated in the label.

        Reference: daemon-design.md SM2 state → INFO command mapping
        """
        if self._sm2_state == SM2State.IDLE:
            return "Inactif"
        elif self._sm2_state == SM2State.PENDING:
            return f"{self._event_context_prefix()} : En cours"
        elif self._sm2_state == SM2State.CONFIRMED:
            return f"{self._event_context_prefix()} : Confirmée par la centrale"
        elif self._sm2_state == SM2State.FAILED:
            if self._event_failure_reason == "nak":
                return f"{self._event_context_prefix()} : Refusé par la centrale"
            if self._event_failure_reason == "config":
                return f"{self._event_context_prefix()} : Non transmise — clé de chiffrement invalide"
            return f"{self._event_context_prefix()} : Sans réponse de la centrale"
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
            - CONFIG_ERROR → 0 (invalid encryption key, nothing sent)

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
            # TCP_RECONNECTING, NO_NETWORK, CONFIG_ERROR → 0 (problem)
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
            - CONFIG_ERROR → "Clé de chiffrement invalide" (story 1-5 AC3)

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
        elif self._sm1_state == SM1State.CONFIG_ERROR:
            return SM1_CONFIG_ERROR_FR  # "Clé de chiffrement invalide"
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

    def _encryption_config_error(self) -> bool:
        """Return True when encryption is enabled but no valid key was configured.

        Story 1-5 AC3: in that state nothing is sent — never a plaintext fallback.
        """
        return bool(self._preset.encryption_enabled) and not self._encryption_key

    async def _enter_encryption_config_error(self) -> None:
        """Set SM1 CONFIG_ERROR and notify the user once per daemon run.

        ErrorCode admits no new code without design review, so the T2-style
        message_center + notify callbacks are sent directly. The key never appears.

        Reference: story 1-5 AC3
        """
        self._set_sm1_state(SM1State.CONFIG_ERROR)
        if self._encryption_config_notified:
            return
        self._encryption_config_notified = True
        self._logger.error(ENCRYPTION_KEY_INVALID)
        self._ring_buffer.push_supervision_entry(
            level="error",
            message=ENCRYPTION_KEY_INVALID,
            context={"account": self._account},
            is_routine=False,
        )
        try:
            await self._send_callback({
                "type": "message_center",
                "message": ENCRYPTION_KEY_INVALID,
                "logical_id": ENCRYPTION_KEY_LOGICAL_ID,
            })
            await self._send_callback({
                "type": "notify",
                "title": ENCRYPTION_KEY_INVALID_TITLE,
                "message": ENCRYPTION_KEY_INVALID,
            })
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error(f"Encryption key notification failed: {e!r}")

    def _nak_offset(self, raw_nak: bytes | None) -> timedelta:
        """Return the clock offset to apply on a NAK re-send (story 1-5 AC4 / D3).

        The NAK is unauthenticated and never encrypted (§ 5.5.3.2), so its
        timestamp is only trusted within NAK_TIMESTAMP_SANITY of local UTC.
        Otherwise the current UTC time is used (offset 0) and a WARN is logged.

        Args:
            raw_nak: Raw NAK frame bytes, or None.

        Returns:
            ``nak_ts - now`` when sane, else ``timedelta(0)``.
        """
        now = datetime.now(timezone.utc)
        try:
            nak_ts = parse_nak_timestamp(raw_nak or b"")
        except ValueError:
            self._logger.warning("NAK without a usable timestamp — re-send with the current UTC time")
            return timedelta(0)
        offset = nak_ts - now
        if abs(offset) > NAK_TIMESTAMP_SANITY:
            self._logger.warning(
                f"NAK timestamp {nak_ts.isoformat()} is more than 24 h from local UTC — "
                f"ignored, re-send with the current UTC time"
            )
            return timedelta(0)
        return offset

    def _trace_header(self, default_token: str, default_seq: int | str) -> dict[str, str]:
        """Return the ID token and sequence of the frame actually sent (story 1-5 AC7).

        Falls back to the given defaults when no frame was sent or it cannot
        be parsed, so a trace entry is never lost. ``sequence`` is always a
        string, on both paths (review finding 2026-09-28: the fallback used
        to leak the caller's `int` default, an inconsistent type for callers
        of the JSON trace/notification payload).

        Args:
            default_token: ID token to report when the frame is unavailable.
            default_seq: Sequence to report when the frame is unavailable.

        Returns:
            ``{"id_token": ..., "sequence": ...}`` — e.g. ``{"id_token": "*NULL", "sequence": "0000"}``.
        """
        id_token, seq = default_token, default_seq
        if self._last_sent_frame:
            try:
                id_token, seq = parse_frame_header(self._last_sent_frame)
            except SIAProtocolError:
                pass  # keep the defaults
        return {"id_token": id_token, "sequence": str(seq)}

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

        NAK retry (story 1-5 AC4, DC-09 § 5.6.1.2): a NAK is answered by up to
        SUPERVISION_NAK_RESENDS immediate re-sends with an updated timestamp. Only
        when every attempt is NAKed does the NAK reach _handle_supervision_nak()
        (one strike).

        Reference: daemon-design.md Component 1, supervision-design.md ADR-11, Task B.2
        """
        if self._encryption_config_error():
            await self._enter_encryption_config_error()
            await self._update_info_commands()
            return

        nak_offset: timedelta | None = None
        wire_seq: str | None = None  # re-sends keep the first attempt's seq (§ 5.5.1.5)
        for attempt in range(SUPERVISION_NAK_RESENDS + 1):
            # Create SIA NULL supervision frame
            try:
                frame = self._sia_builder.make_supervision_message(
                    account_number=self._account,
                    account_prefix=self._account_prefix,
                    receiver_number=self._receiver_prefix if self._receiver_prefix else None,
                    encryption=self._preset.encryption_enabled,
                    encryption_key=self._encryption_key or None,
                    timestamp=None if nak_offset is None else datetime.now(timezone.utc) + nak_offset,
                    seq=wire_seq,
                    supervision_format=self._preset.supervision_format,
                )
                wire_seq = parse_frame_header(frame)[1]
            except (SIAProtocolError, AESEncryptionError, AESKeyError) as e:
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
            if result['status'] != "nak" or attempt == SUPERVISION_NAK_RESENDS:
                break
            nak_offset = self._nak_offset(result['raw_nak'])
            self._logger.info(
                f"NAK supervision — renvoi immédiat avec horodatage mis à jour "
                f"({attempt + 1}/{SUPERVISION_NAK_RESENDS})"
            )

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

    async def _refresh_sm1_on_ack(self) -> int:
        """Refresh SM1 after a CSR ACK to a periodic frame (supervision or RP, story 17-3).

        Strike counter 0, T3 flag cleared, HEALTHY, last-ACK timestamp, and the
        resolve_t1 callbacks when recovering. Does not touch ``_sia_seq`` nor write any
        supervision trace entry; the caller pushes ``supervision_state``.

        Returns:
            The strike counter value before the reset.
        """
        prev_strike = self._strike_counter
        self._strike_counter = 0
        self._sm1_t3_fired = False
        self._set_sm1_state(SM1State.HEALTHY)
        self._last_supervision_ack = datetime.now(timezone.utc)

        # Emit resolve_t1 when recovering from degraded state (clears T1 errors on PHP side).
        # Both codes resolved unconditionally — PHP handler is idempotent (no-op if code not in last_errors).
        if prev_strike > 0:
            await self._send_callback({"type": "error_update", "resolve_t1": 1, "code": ErrorCode.SUPERVISION_TIMEOUT.value})
            await self._send_callback({"type": "error_update", "resolve_t1": 1, "code": ErrorCode.SUPERVISION_NAK.value})
        return prev_strike

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
        # Increment sequence (only on ACK, never on timeout/NAK)
        self._sia_seq = (self._sia_seq + 1) % SIA_SEQ_MAX

        prev_strike = await self._refresh_sm1_on_ack()

        # Create logging context
        ctx: SM1AckLogCtx = {
            "seq": self._sia_seq - 1,  # Was the sequence sent
            "elapsed_ms": elapsed_ms,
            "crc_format": self._preset.crc_format,
            "raw_hex": result['raw_response'].hex() if result.get('raw_response') else None,
            "prev_strike": prev_strike,
        }

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
            - Probe: asyncio.wait_for(asyncio.open_connection(...), _preset.connect_timeout_s)
            - Reconnect interval: growing backoff (_reconnect_backoff_delay_s()), base
              _preset.reconnect_delay_s (default 30s), capped at RECONNECT_BACKOFF_CAP_S (300s)
            - Max attempts: _preset.reconnect_max_attempts (default 6)
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

        max_attempts = self._preset.reconnect_max_attempts
        attempt = 0

        while attempt < max_attempts:
            delay = _reconnect_backoff_delay_s(self._preset.reconnect_delay_s, attempt)
            attempt += 1
            self._logger.debug(
                f"TCP reconnect attempt {attempt}/{max_attempts}, "
                f"waiting {delay}s before probe"
            )

            await asyncio.sleep(delay)

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
                    f"({self._preset.connect_timeout_s}s)"
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

        Reference: internal-docs/design/logging-design.md § SM1 Supervision Table (ADR-16)
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
                        **self._trace_header(NULL_TOKEN, ack_ctx["seq"]),
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
                        **self._trace_header(NULL_TOKEN, t_ctx["seq"]),
                        "account": self._account,
                        "request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
                    },
                })

            elif event == "nak_timestamp":
                n_ctx = cast(SM1NakLogCtx, ctx)
                strike = n_ctx["strike"]
                elapsed_s = n_ctx["elapsed_ms"] / 1000
                info_msg = f"NAK supervision (strike {strike}/3) — trame refusée par la centrale"
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
                        **self._trace_header(NULL_TOKEN, n_ctx["seq"]),
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
                        **self._trace_header(NULL_TOKEN, n_ctx["seq"]),
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
        """Send alarm event with retry logic until ACK or the retry budget is used up.

        Implements retry loop with exponential backoff for alarm event delivery.
        Updates SM2 state and notifies on final failure.

        Story 1-5 AC4: NAK and timeout attempts share the max_retries budget. A NAK
        is re-sent immediately with an updated timestamp (§ 5.6.1.2); a timeout
        after a 1 s backoff. Every attempt reuses the first attempt's wire seq
        (§ 5.5.1.5). T2 BAD_CSR_RESPONSE fires once, only when the final attempt
        is NAKed. With encryption on and an invalid key nothing is sent (AC3).

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
        self._event_user_number = event_item.user_number
        self._event_attempt_count = 0

        if self._encryption_config_error():
            return await self._fail_event_config(event_item, max_retries)

        # SIA DC-09 § 5.5.1.5: "The PE shall NOT increment the sequence number
        # when repeating a message due to a communication failure or no response
        # from a CSR." The first attempt draws the seq from the builder's tracker;
        # every retry re-sends that same wire seq (story 1-5 AC4, D-85).
        wire_seq: str | None = None
        # § 5.6.1.2: a NAK is repeated immediately with an updated timestamp. The
        # offset learnt from the NAK applies to every later attempt of this event.
        nak_offset: timedelta | None = None

        for attempt in range(max_retries + 1):
            self._event_attempt_count = attempt + 1

            try:
                # Build SIA-DCS message frame and send with timeout
                frame = self._build_event_frame(event_item, seq=wire_seq, nak_offset=nak_offset)
                if wire_seq is None:
                    wire_seq = parse_frame_header(frame)[1]
                    self._sia_seq = int(wire_seq)  # traces/notifications = wire seq (AC4)
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
                    _nak_hex = result['raw_response'].hex() if result.get('raw_response') else None
                    if attempt < max_retries:
                        # § 5.6.1.2: repeat immediately (no backoff sleep) with an
                        # updated timestamp, within the shared max_retries budget.
                        nak_offset = self._nak_offset(result['raw_nak'])
                        await self._log_sm2_event(
                            "nak_retry",
                            SM2LogCtx(
                                zone=event_item.zone,
                                sia_code=event_item.sia_code,
                                attempt=self._event_attempt_count,
                                elapsed=0.0,
                                state_change=False
                            ),
                            response_hex=_nak_hex,
                        )
                        continue

                    # Budget used up on a NAK: T2 notification fires once, here only
                    # (no parseable/undecodable split for SM2).
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
                    self._event_failure_reason = "nak"
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
                        self._event_failure_reason = "no_response"
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
                                user_number=event_item.user_number,
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
                    self._event_failure_reason = "no_response"
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
                            user_number=event_item.user_number,
                        )
                    )
                    await self._update_info_commands({
                        'event_state': self._event_state_from_sm2(),
                        'event_label': self._event_label_from_sm2()
                    })
                    return SM2State.FAILED

            except (SIAProtocolError, AESEncryptionError, AESKeyError) as e:
                self._logger.error(f"Protocol/transport error in _send_with_retry: {e}")
                self._sm2_state = SM2State.FAILED
                self._event_failure_reason = "no_response"
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
                        user_number=event_item.user_number,
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
        self._event_failure_reason = "no_response"
        self._notify(
            ErrorCode.EVENT_FAILED,
            EventFailedCtx(
                sia_code=event_item.sia_code,
                sia_seq=self._sia_seq,
                zone_name=event_item.zone,
                max_retries=max_retries,
                attempts_made=self._event_attempt_count,
                last_error='loop_exhausted',
                user_number=event_item.user_number,
            )
        )
        await self._update_info_commands({
            'event_state': self._event_state_from_sm2(),
            'event_label': self._event_label_from_sm2()
        })
        return SM2State.FAILED

    async def _fail_event_config(self, event_item: EventItem, max_retries: int) -> SM2State:
        """Fail an event that cannot be sent: encryption on, key invalid (story 1-5 AC3).

        Nothing is built or sent — never a plaintext fallback. SM2 goes to FAILED
        with reason 'config', and EVENT_FAILED carries last_error='encryption_key'.

        Args:
            event_item: The event that is not transmitted.
            max_retries: The event's retry budget (reported in the notification).

        Returns:
            SM2State.FAILED
        """
        await self._enter_encryption_config_error()
        self._sm2_state = SM2State.FAILED
        self._event_failure_reason = "config"
        await self._log_sm2_event(
            "failed_config",
            SM2LogCtx(
                zone=event_item.zone,
                sia_code=event_item.sia_code,
                attempt=0,
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
                attempts_made=0,
                last_error=EVENT_FAILED_ENCRYPTION_KEY,
                user_number=event_item.user_number,
            )
        )
        await self._update_info_commands({
            'event_state': self._event_state_from_sm2(),
            'event_label': self._event_label_from_sm2()
        })
        return SM2State.FAILED

    def _build_event_frame(
        self,
        event_item: EventItem,
        *,
        seq: str | None = None,
        nak_offset: timedelta | None = None,
    ) -> bytes:
        """Build SIA-DCS frame for alarm event (Task 3.2.2b).

        Constructs complete SIA protocol frame for alarm event delivery with:
        - Account number and CRC format from preset (synced at call time)
        - Sequence number: drawn from the builder's tracker on the first attempt,
          the explicit ``seq`` on retries (SIA DC-09 § 5.5.1.5, story 1-5 AC4)
        - Zone order number in extended data, zero-padded to 3 digits (never the label)
        - media_url in extended data as a Verification [V...] block, when present (story 14-1)
        - Timestamp: see below
        - Encryption per preset, with the configured key (§ 5.4, story 1-5 AC3)

        Timestamp (story 1-5 AC3/AC4):
        - Encrypted: always UTC now (+ nak_offset), so each attempt fits the CSR
          window (§ 5.5.1.9); the event's own time stays in the SM2/inspector records.
        - Unencrypted, first attempt: event_item.timestamp (current UTC if unparseable).
        - Unencrypted NAK re-send (nak_offset set): UTC now + nak_offset.

        Args:
            event_item: EventItem with sia_code, zone, zone_number, media_url, timestamp
            seq: Explicit 4-digit wire seq for a retry; None draws a new one.
            nak_offset: Clock offset learnt from a NAK in this send; None = no NAK yet.

        Returns:
            Complete SIA frame as bytes: LF + CRC + Length + Message + CR

        Reference: story 5-2 Task 3.2.2b, sia_protocol.py encode_message()
        """
        try:
            # Build extended data with the address field.
            # BA/FA/PA address by zone ORDER NUMBER, never the label; BC/OP/CL address by the
            # configured SIA user number instead — DC-03 p.4, stories 13-1/13-4, ADR-18.
            # Either way SIA DC-09 Annex B formats it as 3 zero-padded digits →
            # [#001234|Nri1/BA001] or [#001234|Nri1/BC001]. Padding happens here and only here. When
            # the source value is None the frame carries no address field at all.
            # Note: _sia_seq is incremented once by _send_with_retry before the loop.
            # Every event also carries the area, SIA_AREA_NUMBER (the "ri1/" part).
            extended_data = {'area': str(SIA_AREA_NUMBER)}
            if event_item.sia_code in _USER_ADDRESSED_SIA_CODES:
                # Defense in depth (code review 2026-09-26): on_message() already rejects a
                # missing user_number for these codes, but a value outside the DC-03 Annex B
                # 3-digit range (e.g. a saved config value that bypassed PHP's own clamp)
                # must never reach f"{n:03d}" unchecked — a negative number or 4+ digits would
                # silently break the fixed-width address-field contract.
                if event_item.user_number is not None and 0 <= event_item.user_number <= 999:
                    extended_data['zone'] = f"{event_item.user_number:03d}"
            elif event_item.zone_number is not None:
                extended_data['zone'] = f"{event_item.zone_number:03d}"
            if event_item.media_url:
                extended_data['media_url'] = event_item.media_url

            # Parse event timestamp for the SIA frame (M1).
            # event_item.timestamp is a string "HH:MM:SS,MM-DD-YYYY"; pass None on parse failure
            # to let encode_message use current UTC time.
            encrypted = bool(self._preset.encryption_enabled)
            event_ts: datetime | None = None
            if encrypted or nak_offset is not None:
                event_ts = datetime.now(timezone.utc) + (nak_offset or timedelta(0))
            elif event_item.timestamp:
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
                encryption=encrypted,
                encryption_key=self._encryption_key or None,
                seq=seq,
            )

            return frame

        except SIAProtocolError:
            raise
        except (ValueError, AttributeError, AESEncryptionError, AESKeyError) as e:
            self._logger.error(f"Error building event frame: {e!r}")
            raise SIAProtocolError(f"Frame build failed: {e}") from e

    def _build_rp_frame(
        self,
        *,
        seq: str | None = None,
        nak_offset: timedelta | None = None,
    ) -> bytes:
        """Build the RP cyclic-test frame (story 17-3).

        ``"SIA-DCS"<seq>L0#acct[#acct|Nri0/RP0000]_ts``: area 0, zone 0000, never
        SIA_AREA_NUMBER. The seq comes from the shared tracker on the first attempt,
        the explicit ``seq`` on re-sends. Always timestamped (UTC now + nak_offset);
        encrypted as for events.

        Raises:
            SIAProtocolError: frame build failed (bad key, ...).
        """
        try:
            return self._sia_builder.make_rp_message(
                account_number=self._account,
                account_prefix=self._account_prefix or "L0",
                receiver_number=self._receiver_prefix,
                timestamp=datetime.now(timezone.utc) + (nak_offset or timedelta(0)),
                encryption=bool(self._preset.encryption_enabled),
                encryption_key=self._encryption_key or None,
                seq=seq,
            )
        except SIAProtocolError:
            raise
        except (ValueError, AttributeError, AESEncryptionError, AESKeyError) as e:
            self._logger.error(f"Error building RP frame: {e!r}")
            raise SIAProtocolError(f"RP frame build failed: {e}") from e

    async def _send_rp(self) -> None:
        """Send one RP cyclic test and route the result through SM1 (story 17-3, D-1b).

        Same failure model as ``_send_supervision``: one attempt per cycle (the next
        cycle is the retry), an immediate NAK re-send with updated timestamp
        (§ 5.6.1.2, same wire seq § 5.5.1.5), and the SM1 handlers for the outcome. A
        missed RP is a strike, so with supervision format ``none`` it is the RP that
        drives DEGRADED, T3 and the TCP reconnect. The user-facing event state (SM2,
        event_state, event_label, _event_sia_code/_zone/_user_number) is never touched.

        - ACK: SM1 refreshed (HEALTHY, strike 0) and ``supervision_state`` pushed.
        - NAK on every re-send: ``_handle_supervision_nak`` (one strike).
        - Timeout / transport error: ``_handle_supervision_timeout`` (one strike).
        - TCP drop: ``_handle_supervision_tcp_drop`` (reconnect, no strike).
        - Encryption key invalid: nothing sent, EVENT_FAILED (encryption_key), once per run.
        """
        if self._encryption_config_error():
            first_entry = not self._encryption_config_notified
            await self._enter_encryption_config_error()
            if first_entry:  # notify once per run, like the supervision loop
                self._notify(
                    ErrorCode.EVENT_FAILED,
                    EventFailedCtx(
                        sia_code=RP_SIA_CODE,
                        sia_seq=self._sia_seq,
                        zone_name=None,
                        max_retries=0,
                        attempts_made=0,
                        last_error=EVENT_FAILED_ENCRYPTION_KEY,
                    )
                )
            return

        wire_seq: str | None = None
        nak_offset: timedelta | None = None
        for attempt in range(SUPERVISION_NAK_RESENDS + 1):
            try:
                frame = self._build_rp_frame(seq=wire_seq, nak_offset=nak_offset)
                if wire_seq is None:
                    wire_seq = parse_frame_header(frame)[1]
            except (SIAProtocolError, AESEncryptionError, AESKeyError) as e:
                self._logger.error(f"Failed to encode RP frame: {e}")
                return

            send_start = time.monotonic()
            try:
                result = await asyncio.wait_for(self._send_raw(frame), timeout=RP_SEND_TIMEOUT_S)
            except asyncio.CancelledError:
                raise  # never swallow cancellation (daemon-design.md § CancelledError safety rule)
            except (asyncio.TimeoutError, SIATransportError) as e:
                self._logger.error(f"Transport error sending RP: {e!r}")
                await self._handle_supervision_timeout((time.monotonic() - send_start) * 1000)
                await self._update_info_commands()
                return

            elapsed_ms = (time.monotonic() - send_start) * 1000
            if result['status'] != "nak" or attempt == SUPERVISION_NAK_RESENDS:
                break
            nak_offset = self._nak_offset(result['raw_nak'])

        status = result['status']
        if status == "ack":
            await self._refresh_sm1_on_ack()
            self._logger.debug(f"RP ACKed (seq={wire_seq})")
            await self._update_info_commands({
                'supervision_state': self._supervision_value(),
                'supervision_label': self._supervision_label(),
            })
            return
        if status == "nak":
            await self._handle_supervision_nak(result, elapsed_ms)
        elif status == "timeout":
            await self._handle_supervision_timeout(elapsed_ms)
        elif status == "tcp_drop":
            await self._handle_supervision_tcp_drop()
        await self._update_info_commands()

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
            elif transition == "nak_retry":
                info_msg = messages.SM2_NAK_RETRY.format(
                    attempt=ctx['attempt'],
                    max=MAX_RETRY_DEFAULT
                )
            elif transition == "failed_config":
                info_msg = messages.SM2_FAILED_CONFIG.format(
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
                **self._trace_header(SIA_DCS_TOKEN, self._sia_seq),
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
        user_number: int | None = None,
    ) -> None:
        """Enqueue an alarm event for SM2 processing at EVENT priority.

        Places a 4-tuple into the priority queue with QUEUE_PRIORITY_EVENT (0).
        The queue consumer dequeues this and dispatches to _send_with_retry().
        The enqueue is fire-and-forget: on_message() returns immediately after calling this.

        Args:
            sia_code: SIA event code — "BA" (burglary), "FA" (fire), "PA" (panic),
                "BC" (burglary cancel), "OP" (disarm)
            zone: Zone name from PHP #zone# tag, or None if not specified
            media_url: Optional camera/media URL for SIA [V...] extended field, or None
            retries_left: Retry budget (default MAX_RETRY_DEFAULT=3). Reset to full
                          when re-enqueuing after TCP_RECONNECTING.
            zone_number: Zone order number resolved by PHP, or None when the label
                         matched no entry of the zone table (frame sent without zone).
            user_number: Configured SIA user number (story 13-1) — the address field for
                         BC/OP, or None for BA/FA/PA which use zone_number instead.

        Reference: daemon-design.md Component 1 — Task 1.6 on_message()
        """
        counter: int = next(self._queue_counter)
        payload: EventQueuePayload = {
            "sia_code": sia_code,
            "zone": zone,
            "zone_number": zone_number,
            "user_number": user_number,
            "media_url": media_url,
            "retries_left": retries_left,
        }
        await self._queue.put((QUEUE_PRIORITY_EVENT, counter, QUEUE_TYPE_EVENT, payload))
        self._logger.debug(
            f"EVENT enqueued: sia_code={sia_code}, zone={zone}, "
            f"zone_number={zone_number}, user_number={user_number}, counter={counter}"
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
        self._supervision_exchange_done.clear()
        await self._queue.put((QUEUE_PRIORITY_SUPERVISION, counter, QUEUE_TYPE_SUPERVISION, {}))
        self._logger.debug(f"SUPERVISION enqueued (counter={counter})")

    async def _enqueue_rp(self) -> None:
        """Enqueue an RP cyclic-test item at the supervision priority (story 17-3)."""
        counter: int = next(self._queue_counter)
        self._rp_exchange_done.clear()
        await self._queue.put((QUEUE_PRIORITY_RP, counter, QUEUE_TYPE_RP, {}))
        self._logger.debug(f"RP enqueued (counter={counter})")

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

                elif item_type == QUEUE_TYPE_RP:
                    if self._sm1_state == SM1State.NO_NETWORK:
                        # Daemon stopping: drop silently, like SUPERVISION
                        self._logger.debug(
                            f"SM1 NO_NETWORK: RP dropped (daemon stopping, counter={counter})"
                        )
                    else:
                        await self._send_rp()

                elif item_type == QUEUE_TYPE_EVENT:
                    event_payload: EventQueuePayload = payload  # type: ignore[assignment]

                    if self._sm1_state == SM1State.NO_NETWORK:
                        self._sm2_state = SM2State.FAILED
                        self._event_failure_reason = "no_response"
                        self._event_sia_code = event_payload["sia_code"]
                        self._event_zone = event_payload.get("zone")
                        self._event_user_number = event_payload.get("user_number")
                        self._notify(
                            ErrorCode.EVENT_FAILED,
                            EventFailedCtx(
                                sia_code=event_payload["sia_code"],
                                sia_seq=self._sia_seq,
                                zone_name=event_payload.get("zone"),
                                max_retries=0,
                                attempts_made=0,
                                last_error="no_network",
                                user_number=event_payload.get("user_number"),
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
                            user_number=event_payload.get("user_number"),
                            media_url=event_payload.get("media_url"),
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
                if item_type == QUEUE_TYPE_SUPERVISION:
                    # Releases _supervision_loop on ACK, NAK, timeout, drop or NO_NETWORK drop
                    self._supervision_exchange_done.set()
                elif item_type == QUEUE_TYPE_RP:
                    # Releases _rp_loop on ACK, NAK, timeout, drop, cancel or NO_NETWORK drop
                    self._rp_exchange_done.set()
                self._queue.task_done()

    # ===== TASK 5/6 (Story 5-3): SUPERVISION LOOP =====

    async def _supervision_loop(self) -> None:
        """Periodically enqueue supervision frames for SM1 keep-alive (story 17-2).

        The first frame is enqueued at task start (once per task, never on an
        INITIALIZING transition). The loop then waits for the consumer to finish
        the exchange (ACK, NAK, timeout, drop) and only then sleeps
        supervision_interval_s, so each period counts from the end of the previous
        exchange. The frame form (sia-dcs / null) is chosen in _send_supervision();
        format "none" never starts this task (see on_start).

        An alarm queued meanwhile still wins (EVENT priority=0 over SUPERVISION).

        Reference: daemon-design.md Component 1 — _supervision_loop() / Task B.3
        Reference: SIA DC-09-2021 § 5.5.2 Supervision Message
        """
        interval: float = float(getattr(self._preset, 'supervision_interval_s', SUPERVISION_INTERVAL_S))
        while True:
            self._logger.debug("Enqueueing supervision frame")
            await self._enqueue_supervision()
            await self._supervision_exchange_done.wait()
            await asyncio.sleep(interval)

    async def _rp_loop(self) -> None:
        """Periodically enqueue the RP cyclic test (story 17-3).

        The first RP is enqueued at task start, before the first sleep. The loop
        then waits for the consumer to finish the exchange and only then sleeps
        rp_interval_s, so each period counts from the end of the previous exchange
        and events in between do not shift it. Only started when rp_enabled.
        """
        interval: float = float(self._preset.rp_interval_s)
        while True:
            self._logger.debug("Enqueueing RP cyclic test")
            await self._enqueue_rp()
            try:
                await self._rp_exchange_done.wait()
            except asyncio.CancelledError:
                self._rp_exchange_done.set()
                raise
            await asyncio.sleep(interval)

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

    async def on_message(  # pylint: disable=too-many-locals
        self, cmd: str, params: OnMessageParams
    ) -> None:
        """Receive alarm command from PHP and enqueue for SM2 processing.

        Called by _on_message_dispatch() after apikey/cmd extraction.
        Extracts alarm type, zone, and media_url from params and enqueues
        an EVENT item into the priority queue. Returns immediately (fire-and-forget):
        the actual send happens asynchronously in _queue_consumer() → _send_with_retry().

        Args:
            cmd: Command name from PHP — "burglarAlarm", "fireAlarm", "panicAlarm",
                "arm" (Story 13-4 — fixed mapping to CL via _EVENT_SIA_CODES),
                "disarm"/"alarmReset" (Story 13-1 — sia_code comes from params, not a
                fixed mapping; see _VARIABLE_SIA_CODE_COMMANDS), or
                "prefetchEvent" (Story 14-2, ADR-17 Amendment 3)
            params: PHP payload dict with optional keys:
                - "zone": str — zone name from #zone# tag (None if absent)
                - "zone_number": int — zone order number PHP resolved against the zone
                  table (None when the label matched no entry: frame sent without zone)
                - "sia_code": str — required for "disarm"/"alarmReset" only: "BC" or "OP"
                - "user_number": int — configured SIA user (stories 13-1/13-4), address
                  field for "disarm"/"alarmReset"/"arm" frames
                - "media_url": str — camera/media URL (None if absent)
                - "camera_eqlogic_id"/"camera_name"/"frigate_host"/"run_id" — prefetchEvent
                  only (Story 14-4, ADR-17 Amendment 4)

        Reference: daemon-design.md Component 1 — Task 1.6 on_message()
        Reference: daemon-design.md — "Forbidden char policy" for media_url
        """
        if cmd == "prefetchEvent":
            # ADR-17 Amendment 3/4 (Option D): fire-and-forget dispatch to a tracked
            # background task — on_message() itself never awaits the Frigate REST
            # call, matching the fire-and-forget contract PHP's execute() relies on.
            self._logger.debug(f"on_message: prefetchEvent received, raw params={params!r}")
            camera_eqlogic_id = params.get("camera_eqlogic_id")
            camera_name = params.get("camera_name")
            frigate_host = params.get("frigate_host")
            run_id = params.get("run_id")
            if camera_eqlogic_id is None or not camera_name or not frigate_host or not run_id:
                self._logger.warning(
                    "on_message: prefetchEvent missing required params — ignored "
                    f"(camera_eqlogic_id={camera_eqlogic_id!r}, camera_name={camera_name!r}, "
                    f"frigate_host={frigate_host!r}, run_id={run_id!r})"
                )
                return
            try:
                cam_id = int(camera_eqlogic_id)
            except (TypeError, ValueError):
                self._logger.warning(
                    f"on_message: unusable camera_eqlogic_id {camera_eqlogic_id!r} — "
                    "prefetchEvent ignored"
                )
                return
            self._logger.debug(
                f"on_message: prefetchEvent spawning tracked task for camera_eqlogic_id="
                f"{cam_id}, camera_name={camera_name!r}, frigate_host={frigate_host!r}, "
                f"run_id={run_id!r}"
            )
            self._track_task(
                self._run_prefetch(cam_id, camera_name, frigate_host, str(run_id)),
                name=f"frigate-prefetch-{cam_id}",
            )
            return

        sia_code: SiaEventCode | None
        if cmd in _VARIABLE_SIA_CODE_COMMANDS:
            # Story 13-1 (ADR-18): disarm/alarmReset carry their own sia_code per call —
            # one sendToDaemon() per frame — rather than a fixed cmd→code mapping.
            raw_sia_code = params.get("sia_code")
            if raw_sia_code not in _VARIABLE_ALLOWED_SIA_CODES:
                self._logger.warning(
                    f"on_message: {cmd} missing/invalid sia_code {raw_sia_code!r} — ignored"
                )
                return
            sia_code = cast(SiaEventCode, raw_sia_code)
        else:
            sia_code = _EVENT_SIA_CODES.get(cmd)
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

        # Stories 13-1/13-4: user_number is the address field for BC/OP/CL (ADR-18) — same defensive
        # int coercion as zone_number, so a JSON string never breaks the f"{n:03d}" format.
        raw_user_number = params.get("user_number")
        user_number: int | None = None
        if raw_user_number is not None:
            try:
                user_number = int(raw_user_number)
            except (TypeError, ValueError):
                self._logger.warning(f"on_message: unusable user_number {raw_user_number!r}")

        # Unlike zone_number (BA/FA/PA: a missing zone is a normal, allowed outcome), the AC
        # for BC/OP/CL is that the address field is NEVER empty (code review 2026-09-26) — a
        # user-addressed code with no resolvable user_number is rejected outright, same as an
        # invalid sia_code above, rather than silently sent with no address field at all.
        if sia_code in _USER_ADDRESSED_SIA_CODES and user_number is None:
            self._logger.warning(
                f"on_message: {cmd} ({sia_code}) missing/invalid user_number "
                f"{raw_user_number!r} — ignored, address field must never be empty"
            )
            return

        self._logger.debug(
            f"on_message: cmd={cmd} → sia_code={sia_code}, zone={zone}, "
            f"zone_number={zone_number}, user_number={user_number}, "
            f"media_url={'<set>' if media_url else None}"
        )
        await self._enqueue_event(
            sia_code, zone, media_url, zone_number=zone_number, user_number=user_number
        )

    # ===== STORY 14-2/14-4 (ADR-17 Amendment 3/4): FRIGATE EVENT PREFETCH =====

    async def _run_prefetch(
        self, camera_eqlogic_id: int, camera_name: str, frigate_host: str, run_id: str
    ) -> None:
        """Run the best-effort alarm-media prefetch, pushing each improvement back to PHP.

        Runs as a tracked background task spawned by on_message()'s "prefetchEvent"
        branch — entirely inside the alarm zone's immediate-action window. Story 14-4
        (ADR-17 Amendment 4) sends one callback per rank improvement (forced-capture
        manual event first, then any-label real events ranked person > other label),
        plus a clip-ready upgrade, instead of 14-2's single end-of-run callback. `run_id`
        is echoed back on every callback unchanged, so PHP's monotonic cache rule
        (siaDC09::_handlePrefetchResult()) can never let a late callback from an older
        run overwrite a newer one — this replaces 14-2 AC5's "always send a result"
        contract (superseded by the placeholder cache entry PHP writes before triggering
        this run).

        Args:
            camera_eqlogic_id: siaDC09-side cache key (the camera's Jeedom eqLogic id)
            camera_name: Frigate-native camera name (getConfiguration('name') on the
                camera eqLogic)
            frigate_host: Frigate server host:port, e.g. "192.168.100.18:5000"
            run_id: Numeric string PHP generated and owns (siaDC09Cmd::execute()'s
                "prefetchEvent" case) — echoed back verbatim on every callback.

        Reference: ADR-17, Amendment 3/4 — _bmad-output/planning-artifacts/architecture.md
        Reference: 14-4 Task 3.2
        """
        base_url = f"http://{frigate_host}"
        self._logger.debug(
            f"_run_prefetch: querying {base_url} camera={camera_name!r} "
            f"(camera_eqlogic_id={camera_eqlogic_id}, run_id={run_id!r})"
        )

        async def _on_result(result: PrefetchResult) -> None:
            self._logger.debug(f"_run_prefetch: result={result!r} (run_id={run_id!r})")
            await self._send_callback({
                "type": "prefetch_result",
                "camera_eqlogic_id": camera_eqlogic_id,
                "found": 1 if result.found else 0,
                "event_id": result.event_id or "",
                "clip_found": 1 if result.clip_found else 0,
                "rank": result.rank,
                "run_id": run_id,
            })

        await prefetch_alarm_media(base_url, camera_name, _on_result)

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
        self._logger.info(DAEMON_VERSION_INFO.format(version=DAEMON_VERSION))
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
        if self._preset.supervision_format != "none":
            self._track_task(self._supervision_loop(), name="supervision_loop")
        else:
            self._logger.info("supervision_format=none: no supervision task")
        if self._preset.rp_enabled:
            self._track_task(self._rp_loop(), name="rp_loop")

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

        # Step 3 — Cancel all tracked tasks EXCEPT the current one.
        # on_stop() may itself run as a tracked task (the watchdog schedules self.stop()
        # as 'transport_permanent_stop', see _tcp_reconnect_loop). Cancelling/awaiting the
        # running task would self-cancel and surface a stray CancelledError at Exit 0, so we
        # exclude asyncio.current_task() — mirroring BaseDaemon.stop()'s own guard.
        current = asyncio.current_task()
        other_tasks = [task for task in self._tasks if task is not current]
        for task in other_tasks:
            task.cancel()

        # Step 4 — Await task completion with hard timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*other_tasks, return_exceptions=True),
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
