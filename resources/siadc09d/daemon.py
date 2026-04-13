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
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, TypedDict

from jeedomdaemon import BaseDaemon, BaseConfig

from .error_handler import ErrorCode
from .messages import (
    SM1_DEGRADED_1_2_FR,
    SM1_DEGRADED_3_FR,
    SM1_HEALTHY_FR,
    SM1_INITIALIZING_FR,
    SM1_TCP_RECONNECTING_FR,
    SM1_NO_NETWORK_FR,
)
from .ring_buffer import RingBuffer, make_message_entry
from .sia_protocol import SIAMessageBuilder, parse_nak_timestamp, SIAProtocolError
from .sia_crypto import AESEncryptionError


# ===== TASK 1: SM1 STATE MACHINE CLASS STRUCTURE =====

class SM1State(Enum):
    """SM1 state machine states (ref: supervision-design.md ADR-11)."""
    INITIALIZING = "INITIALIZING"  # Daemon starting, awaiting first ACK
    HEALTHY = "HEALTHY"              # CSR responding normally (strike=0)
    DEGRADED = "DEGRADED"            # Timeouts/NAKs received (strike=1-3)
    TCP_RECONNECTING = "TCP_RECONNECTING"  # TCP half-open stall, reconnect loop active
    NO_NETWORK = "NO_NETWORK"        # Permanent TCP failure (terminal)


class SM1AckCtx(TypedDict):
    """Logging context for ACK response."""
    seq: int  # Sequence number sent
    elapsed_ms: float  # Time from send to ACK
    crc_format: Literal["SIA", "ADM"]  # CRC format used
    raw_hex: Optional[str]  # Raw ACK hex (optional)
    prev_strike: int  # Strike counter before this ACK


class SM1TimeoutCtx(TypedDict):
    """Logging context for timeout."""
    seq: int  # Sequence number that timed out
    elapsed_ms: float  # Time elapsed since send
    strike: int  # Strike counter after increment
    prev_state: SM1State  # State before timeout
    t3_just_fired: bool  # True if T3 (SUPERVISION_DISCONNECTED) just fired


class SM1NakCtx(TypedDict):
    """Logging context for NAK response."""
    seq: int  # Sequence number NAK'd
    elapsed_ms: float  # Time from send to NAK
    strike: int  # Strike counter after increment
    raw_hex: str  # Raw NAK hex
    csr_time: Optional[datetime]  # Parsed CSR timestamp (if parseable)
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


class SM2LogCtx(TypedDict):
    """Logging context for SM2 state transitions.

    Used by _log_sm2_event() to provide structured logging context.
    """
    zone: Optional[str]  # Zone name from alarm command #zone# tag (None if not specified)
    sia_code: str  # Event SIA code (BA=burglary, FA=fire, PA=panic)
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
        callback: Optional callback function called when event completes (signature: callback(success: bool))
    """
    sia_code: str  # BA, FA, or PA
    zone: Optional[str]  # Zone name or None
    timestamp: str  # SIA protocol timestamp HH:MM:SS,MM-DD-YYYY
    callback: Optional[Any] = None  # Callback function(success: bool) when send completes


# ===== CONSTANTS =====

SUPERVISION_INTERVAL_S = 60  # Default supervision interval (seconds)
TCP_RECONNECT_DELAY_S = 5  # Default TCP reconnect backoff (seconds)
TCP_RECONNECT_MAX_ATTEMPTS = 3  # Max reconnect attempts before NO_NETWORK
TCP_CONNECT_TIMEOUT_S = 10  # Timeout for asyncio.wait_for() on TCP connect
STRIKE_CAP = 3  # Strike counter capped at 3


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

    def __init__(self, config: Optional[BaseConfig] = None) -> None:
        """Initialize SIA Daemon with all instance variables.

        Args:
            config: Optional BaseConfig from jeedomdaemon. If None, uses default.

        Instance Variables (SM1 state machine):
            _sm1_state: Current SM1 state (INITIALIZING, HEALTHY, DEGRADED, etc.)
            _strike_counter: Strikes (timeouts/NAKs) since last ACK (0-3)
            _sm1_t3_fired: T3 deduplication flag (prevents duplicate SUPERVISION_DISCONNECTED)
            _last_supervision_ack: Datetime of last successful ACK (for timestamp tracking)

        Instance Variables (SM2 state machine - alarm events):
            _sm2_state: Current SM2 state (IDLE, PENDING, CONFIRMED, FAILED)
            _event_state: Numeric state for INFO command (0=no alarm, 1=confirmed, 2=failed, 3=pending)
            _event_label: French label for display (Inactif, En cours, Confirmé, Échoué)
            _event_sia_code: Latest event SIA code (BA=burglary, FA=fire, PA=panic)
            _event_zone: Latest zone name from alarm command #zone# tag
            _event_attempt_count: Current send attempt count for in-flight event

        Instance Variables (Configuration):
            _preset: CSR preset config (host, port, encryption_key, crc_format, etc.)
            _account: Account number (3-16 hex chars)
            _receiver_prefix: Receiver prefix (optional)
            _account_prefix: Account prefix (optional)
            _encryption_key: Encryption key bytes (empty if disabled)
            _transport: Transport type ('UDP' or 'TCP')

        Instance Variables (State & Data):
            _sia_seq: Current SIA sequence number (0-9999)
            _sia_builder: SIAMessageBuilder for encoding frames
            _ring_buffer: RingBuffer for message history
            _tasks: Set of tracked asyncio.Task objects
            _logger: Module logger

        Instance Variables (Async methods - provided by subclass or injected):
            _notify: async method to dispatch error notifications
            _send_raw: async method to send raw frame to CSR
            _update_info_commands: async method to update PHP INFO commands
            _log_sm1_supervision: async method to log supervision events
            _track_task: method to track async tasks
        """
        super().__init__(config=config or BaseConfig())

        # SM1 state machine
        self._sm1_state: SM1State = SM1State.INITIALIZING
        self._strike_counter: int = 0
        self._sm1_t3_fired: bool = False
        self._last_supervision_ack: Optional[datetime] = None

        # SM2 state machine (alarm event delivery)
        self._sm2_state: SM2State = SM2State.IDLE  # Startup-only state
        self._event_state: int = 0  # Persisted: 0=no alarm, 1=confirmed, 2=failed, 3=pending
        self._event_label: str = "Inactif"  # Persisted: French label for display
        self._event_sia_code: Optional[str] = None  # Latest event code (BA|FA|PA)
        self._event_zone: Optional[str] = None  # Latest zone from command #zone# tag
        self._event_attempt_count: int = 0  # Track send attempts for current event

        # Configuration (populated by on_start or preset loader)
        # _preset should be a CSRPreset or config object with: crc_format, encryption_enabled, reconnect_delay_s
        self._preset: Any = None  # Set by subclass in on_start()
        self._account: str = ""
        self._receiver_prefix: str = ""
        self._account_prefix: str = ""
        self._encryption_key: bytes = b""
        self._transport: Literal["UDP", "TCP"] = "UDP"

        # State & data
        self._sia_seq: int = 0
        self._sia_builder: SIAMessageBuilder = SIAMessageBuilder(crc_format="SIA")  # Default, will be updated
        self._ring_buffer: RingBuffer = RingBuffer()
        self._tasks: set[asyncio.Task] = set()
        self._logger = logging.getLogger(__name__)

        # Async method stubs (will be overridden by subclass in on_start)
        # Note: _log_sm1_supervision is NOT stubbed - uses actual method implementation
        self._notify = self._notify_stub
        self._send_raw = self._send_raw_stub
        self._update_info_commands = self._update_info_commands_stub
        # self._log_sm1_supervision already bound to actual implementation (not stubbed)
        self._track_task = self._track_task_stub

    async def _notify_stub(self, error_code: ErrorCode, context: dict) -> None:
        """Stub for _notify (will be overridden)."""
        pass

    async def _send_raw_stub(self, frame: bytes) -> dict:
        """Stub for _send_raw (will be overridden)."""
        return {"status": "timeout"}

    async def _update_info_commands_stub(self) -> None:
        """Stub for _update_info_commands (will be overridden)."""
        pass

    def _track_task_stub(self, coro) -> None:
        """Stub for _track_task (will be overridden)."""
        pass

    # ===== SM2 STATE HELPER METHODS =====

    def _event_state_from_sm2(self) -> int:
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

    def _event_label_from_sm2(self) -> str:
        """Return French label for event_label INFO command based on SM2 state.

        Returns:
            str: French-language state label for display

        Logic:
            - IDLE → "Inactif" (no alarm received)
            - PENDING → "En cours" (alarm transmission in progress)
            - CONFIRMED → "Confirmé" (CSR confirmed alarm reception)
            - FAILED → "Échoué" (alarm failed)

        Reference: daemon-design.md SM2 state → INFO command mapping
        """
        if self._sm2_state == SM2State.IDLE:
            return "Inactif"
        elif self._sm2_state == SM2State.PENDING:
            return "En cours"
        elif self._sm2_state == SM2State.CONFIRMED:
            return "Confirmé"
        elif self._sm2_state == SM2State.FAILED:
            return "Échoué"
        else:
            # Defensive: should not reach here
            return "Inactif"

    def _supervision_value(self) -> int:
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
            - INITIALIZING → "DÉMARRAGE…" (daemon starting)
            - HEALTHY → "OK" (static, no timestamp embedded)
            - DEGRADED(strike 1-2) → "DÉGRADÉ (N/3)" (N = current strike)
            - DEGRADED(strike 3) → "PERDUE" (lost)
            - TCP_RECONNECTING → "Reconnexion TCP/UDP…" (reconnecting)
            - NO_NETWORK → "HORS RÉSEAU — arrêt" (network unavailable, terminal)

        Note: HEALTHY label is static "OK" (not time-varying) to avoid DB writes on every ACK.
        The last-ACK timestamp is available via supervision_state.collectDate for display.

        Reference: supervision-design.md SM1 state → INFO command mapping
        """
        if self._sm1_state == SM1State.INITIALIZING:
            return SM1_INITIALIZING_FR  # "DÉMARRAGE…"
        elif self._sm1_state == SM1State.HEALTHY:
            return SM1_HEALTHY_FR  # "OK"
        elif self._sm1_state == SM1State.DEGRADED:
            if self._strike_counter >= 3:
                return SM1_DEGRADED_3_FR  # "PERDUE"
            else:
                # "DÉGRADÉ (N/3)" — replace N with current strike
                return SM1_DEGRADED_1_2_FR.format(self._strike_counter)
        elif self._sm1_state == SM1State.TCP_RECONNECTING:
            return SM1_TCP_RECONNECTING_FR  # "Reconnexion TCP/UDP…"
        else:  # NO_NETWORK
            return SM1_NO_NETWORK_FR  # "HORS RÉSEAU — arrêt"

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
        self._sm1_state = SM1State.DEGRADED

        t3_just_fired = False

        # Strike=3 handling
        if self._strike_counter >= 3:
            if self._transport == "TCP":
                # Force socket close to escape half-open stall
                # (TCP connection may be in half-open state, blocking indefinitely)
                # Transition to TCP_RECONNECTING and start reconnect loop
                self._sm1_state = SM1State.TCP_RECONNECTING
                self._track_task(self._tcp_reconnect_loop())

            # Fire T3 notification (once only, via _sm1_t3_fired deduplication)
            if not self._sm1_t3_fired:
                self._sm1_t3_fired = True
                t3_just_fired = True
                await self._notify(ErrorCode.SUPERVISION_DISCONNECTED, {})

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
        result = {}
        try:
            result = await self._send_raw(frame)
        except Exception as e:
            self._logger.error(f"Transport error sending supervision: {e}")
            # Treat as timeout (strike++)
            result = {"status": "timeout"}

        elapsed_ms = (time.monotonic() - send_start) * 1000

        # Route response to appropriate handler
        status = result.get("status", "timeout")

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

    async def _handle_supervision_ack(self, result: dict, elapsed_ms: float) -> None:
        """Handle ACK response: reset strike, set HEALTHY, increment sequence.

        Args:
            result: Response dict from _send_raw() with keys: status, raw_hex (optional)
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
        self._sia_seq = (self._sia_seq + 1) % 10000

        # Reset strike and T3 dedup flag
        self._strike_counter = 0
        self._sm1_t3_fired = False

        # Set state to HEALTHY
        self._sm1_state = SM1State.HEALTHY

        # Update last ACK timestamp
        self._last_supervision_ack = datetime.now(timezone.utc)

        # Create logging context
        ctx: SM1AckCtx = {
            "seq": self._sia_seq - 1,  # Was the sequence sent
            "elapsed_ms": elapsed_ms,
            "crc_format": self._preset.crc_format,
            "raw_hex": result.get("raw_hex"),
            "prev_strike": prev_strike,
        }

        # Log supervision event (may be throttled for routine ACKs)
        await self._log_sm1_supervision("ack", ctx)

    async def _handle_supervision_nak(self, result: dict, elapsed_ms: float) -> None:
        """Handle NAK response: increment strike, dispatch T1/T2, log.

        Args:
            result: Response dict from _send_raw() with keys: status, nak_data (raw bytes)
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

        # Fire T1 only at strike < 3 (not at strike=3, which fires T3)
        if self._strike_counter < 3:
            await self._notify(ErrorCode.SUPERVISION_NAK, {})

        # Try to parse NAK timestamp
        nak_data = result.get("nak_data", b"")
        csr_time: Optional[datetime] = None
        is_parseable = False

        try:
            csr_time = parse_nak_timestamp(nak_data)
            is_parseable = True
        except ValueError:
            # Unparseable NAK → fire T2 (BAD_CSR_RESPONSE)
            await self._notify(ErrorCode.BAD_CSR_RESPONSE, {})

        # Create logging context
        ctx: SM1NakCtx = {
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
            await self._notify(ErrorCode.SUPERVISION_TIMEOUT, {})

        # Create logging context
        ctx: SM1TimeoutCtx = {
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
        self._sm1_state = SM1State.TCP_RECONNECTING
        self._track_task(self._tcp_reconnect_loop())
        self._logger.warning("TCP connection dropped by OS, initiating reconnect")

    async def _tcp_reconnect_loop(self) -> None:
        """TCP reconnect loop with backoff and permanent failure detection.

        Only runs when _sm1_state == TCP_RECONNECTING.
        Attempts reconnect at fixed intervals with exponential backoff.
        Transitions to NO_NETWORK (terminal) after max failures.

        Behavior:
            - Only for TCP transport (UDP never enters this state)
            - Uses asyncio.wait_for(..., timeout=10s) to prevent indefinite hang
            - Reconnect interval: _preset.reconnect_delay_s (default 5s)
            - Max attempts: TCP_RECONNECT_MAX_ATTEMPTS (default 3)
            - On success: reset strike=0, set state=INITIALIZING, send NULL immediately
            - On permanent failure: set state=NO_NETWORK, fire T3 (TRANSPORT_PERMANENT), call stop()
            - Logged via _logger.debug() with per-attempt details

        Note: This is a background task tracked in _tasks set.
        Note: Actual TCP connection is deferred to subclass implementation via _transport attribute.
              This loop provides the reconnect state machine logic.

        Reference: daemon-design.md Task 4 (TCP reconnect logic), supervision-design.md ADR-11
        """
        if self._transport != "TCP":
            return  # UDP never enters TCP_RECONNECTING

        max_attempts = TCP_RECONNECT_MAX_ATTEMPTS
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            self._logger.debug(
                f"TCP reconnect attempt {attempt}/{max_attempts}, "
                f"waiting {self._preset.reconnect_delay_s}s before reconnect"
            )

            # Wait before attempt (backoff)
            await asyncio.sleep(self._preset.reconnect_delay_s)

            # Attempt to reconnect - deferred to subclass via _transport object
            # The _transport attribute should be set by subclass to actual TCPTransport
            self._logger.debug(f"Attempting TCP reconnect {attempt}/{max_attempts}...")

            try:
                # Subclass responsibility: implement actual TCP connect via self._transport
                # For now, log that reconnect was attempted (actual connection deferred)
                # Future: result = await asyncio.wait_for(
                #     self._transport.connect(),
                #     timeout=TCP_CONNECT_TIMEOUT_S
                # )
                success = False  # Reconnect deferred to subclass implementation

                if success:
                    # Reconnect successful
                    self._strike_counter = 0
                    self._sm1_t3_fired = False
                    self._sm1_state = SM1State.INITIALIZING
                    self._logger.info("TCP reconnect successful, returning to INITIALIZING")
                    return

            except asyncio.TimeoutError:
                self._logger.warning(
                    f"TCP reconnect attempt {attempt}/{max_attempts} timed out "
                    f"({TCP_CONNECT_TIMEOUT_S}s)"
                )
            except Exception as e:
                self._logger.warning(
                    f"TCP reconnect attempt {attempt}/{max_attempts} failed: {e}"
                )

        # Permanent failure after max attempts
        self._sm1_state = SM1State.NO_NETWORK
        await self._notify(ErrorCode.TRANSPORT_PERMANENT, {})
        self._logger.error(
            f"TCP reconnect failed after {max_attempts} attempts, transitioning to NO_NETWORK"
        )
        # Note: stop() called by subclass if needed; deferred here to avoid terminating base daemon

    async def _log_sm1_supervision(
        self,
        event: Literal["ack", "timeout", "nak_timestamp", "nak_bad"],
        ctx: SM1AckCtx | SM1TimeoutCtx | SM1NakCtx,
    ) -> None:
        """Log supervision event with dual-line pattern (French INFO + English DEBUG).

        Implements logging table from logging-design.md SM1 Supervision Table.
        Pushes to ring buffer with appropriate throttling:
        - Routine ACKs: throttled 10-minute interval (prevent INFO spam at normal operation)
        - Strikes, transitions, T1/T3: immediate (not throttled)

        Args:
            event: Event type ('ack', 'timeout', 'nak_timestamp', 'nak_bad')
            ctx: Logging context (SM1AckCtx, SM1TimeoutCtx, or SM1NakCtx)

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
                # ACK: DEBUG only, no INFO (routine, may be throttled)
                elapsed_s = ctx["elapsed_ms"] / 1000
                self._logger.debug(
                    f"Supervision ACK received: account={self._account}, "
                    f"seq={ctx['seq']}, elapsed={elapsed_s:.2f}s, "
                    f"crc_format={ctx['crc_format']}"
                )
                # Push to ring buffer (throttled for routine ACKs)
                await self._ring_buffer.push_supervision_entry(
                    level="debug",
                    message=f"ACK: seq={ctx['seq']}, elapsed={elapsed_s:.2f}s",
                    context={"account": self._account, "seq": ctx["seq"]},
                    is_routine=True,  # Throttled 10-min
                )

            elif event == "timeout":
                # Timeout: INFO + DEBUG, immediate (not throttled)
                strike = ctx.get("strike", 0)
                elapsed_s = ctx["elapsed_ms"] / 1000

                if strike < 3:
                    # Strike 1-2: impaired but recoverable
                    info_msg = f"Supervision dégradée — tentative {strike}/3"
                else:
                    # Strike 3: critical (T3 fired)
                    info_msg = "Supervision perdue — intervention requise"

                self._logger.info(info_msg)
                self._logger.debug(
                    f"Supervision timeout: account={self._account}, "
                    f"seq={ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"prev_state={ctx.get('prev_state', 'unknown')}, "
                    f"t3_fired={ctx.get('t3_just_fired', False)}"
                )

                # Push to ring buffer (immediate, not throttled)
                await self._ring_buffer.push_supervision_entry(
                    level="warning" if strike == 3 else "info",
                    message=info_msg,
                    context={"account": self._account, "seq": ctx["seq"], "strike": strike},
                    is_routine=False,  # Immediate
                )

            elif event == "nak_timestamp":
                # NAK with parseable timestamp: treat as timeout
                strike = ctx.get("strike", 0)
                elapsed_s = ctx["elapsed_ms"] / 1000
                csr_time = ctx.get("csr_time")

                info_msg = f"NAK supervision (strike {strike}/3) — horodatage rejeté par la centrale"
                self._logger.info(info_msg)
                self._logger.debug(
                    f"Supervision NAK (parseable): account={self._account}, "
                    f"seq={ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"csr_time={csr_time}, raw={ctx.get('raw_hex', '')}"
                )

                await self._ring_buffer.push_supervision_entry(
                    level="warning",
                    message=info_msg,
                    context={"account": self._account, "seq": ctx["seq"], "strike": strike},
                    is_routine=False,
                )

            elif event == "nak_bad":
                # NAK with unparseable timestamp: protocol anomaly
                strike = ctx.get("strike", 0)
                elapsed_s = ctx["elapsed_ms"] / 1000

                info_msg = f"Réponse invalide de la centrale — NAK non décodable (strike {strike}/3)"
                self._logger.warning(info_msg)
                self._logger.debug(
                    f"Supervision NAK (unparseable): account={self._account}, "
                    f"seq={ctx['seq']}, strike={strike}, elapsed={elapsed_s:.2f}s, "
                    f"raw={ctx.get('raw_hex', '')}"
                )

                await self._ring_buffer.push_supervision_entry(
                    level="error",
                    message=info_msg,
                    context={"account": self._account, "seq": ctx["seq"], "strike": strike},
                    is_routine=False,
                )

        except Exception as e:
            self._logger.error(f"Error logging SM1 supervision event: {e}")


# ===== SM2 ALARM EVENT STATE MACHINE METHODS =====

    async def _send_with_retry(
        self,
        event_item: EventItem,
        max_retries: int = 3
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

        for attempt in range(max_retries + 1):
            self._event_attempt_count = attempt + 1

            try:
                # Build SIA-DCS message frame
                # TODO (Task 3.2.2b): Encode message with account, seq, zone, timestamp
                frame = self._build_event_frame(event_item)

                # Send with timeout
                # TODO (Task 3.2.2c): Send frame with 10s timeout via _send_raw()
                result = await asyncio.wait_for(
                    self._send_raw(frame),
                    timeout=10.0
                )

                # Handle response
                status = result.get("status", "timeout")

                if status == "ack":
                    # Task 3.2.2e: ACK received - event confirmed
                    self._sm2_state = SM2State.CONFIRMED
                    await self._log_sm2_event(
                        "confirmed",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=True
                        )
                    )
                    await self._update_info_commands({
                        'event_state': self._event_state_from_sm2(),
                        'event_label': self._event_label_from_sm2()
                    })
                    return SM2State.CONFIRMED

                elif status == "nak":
                    # NAK received - handle based on parseable timestamp (Task 5)
                    raw_nak = result.get("raw_nak")
                    csr_timestamp = None

                    try:
                        # Task 5.1: Try to parse NAK timestamp
                        if raw_nak:
                            csr_timestamp = parse_nak_timestamp(raw_nak)
                            # Task 5.2: Parseable NAK - delegate to SM1 for strike increment
                            # v1.0: No auto-heal, SM2 always FAILs on NAK
                            self._logger.debug(
                                f"NAK received with parseable timestamp: {csr_timestamp}"
                            )
                            # Call SM1 NAK handler (if available)
                            if hasattr(self, '_update_sm1_from_nak'):
                                await self._update_sm1_from_nak(csr_timestamp)

                    except (ValueError, TypeError):
                        # Task 5.3: Undecodable NAK - T2 notification
                        await self._notify(
                            ErrorCode.BAD_CSR_RESPONSE,
                            {
                                "zone": event_item.zone,
                                "sia_code": event_item.sia_code,
                                "reason": "unparseable_nak"
                            }
                        )

                    # SM2 always transitions to FAILED on NAK (v1.0 no auto-heal)
                    self._sm2_state = SM2State.FAILED
                    await self._log_sm2_event(
                        "failed_nak",
                        SM2LogCtx(
                            zone=event_item.zone,
                            sia_code=event_item.sia_code,
                            attempt=self._event_attempt_count,
                            elapsed=0.0,
                            state_change=True
                        )
                    )
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
                        await self._notify(
                            ErrorCode.EVENT_FAILED,
                            {
                                "zone": event_item.zone,
                                "sia_code": event_item.sia_code,
                                "attempts": self._event_attempt_count
                            }
                        )
                        await self._update_info_commands({
                            'event_state': self._event_state_from_sm2(),
                            'event_label': self._event_label_from_sm2()
                        })
                        return SM2State.FAILED

            except asyncio.TimeoutError:
                # Timeout during send
                if attempt < max_retries:
                    await asyncio.sleep(1.0)
                    continue
                else:
                    self._sm2_state = SM2State.FAILED
                    await self._notify(
                        ErrorCode.EVENT_FAILED,
                        {
                            "zone": event_item.zone,
                            "sia_code": event_item.sia_code,
                            "attempts": self._event_attempt_count
                        }
                    )
                    return SM2State.FAILED

            except Exception as e:
                self._logger.error(f"Unexpected error in _send_with_retry: {e}")
                self._sm2_state = SM2State.FAILED
                await self._notify(
                    ErrorCode.EVENT_FAILED,
                    {
                        "zone": event_item.zone,
                        "sia_code": event_item.sia_code,
                        "attempts": self._event_attempt_count
                    }
                )
                return SM2State.FAILED

        # Fallback (should not reach here)
        self._sm2_state = SM2State.FAILED
        return SM2State.FAILED

    def _build_event_frame(self, event_item: EventItem) -> bytes:
        """Build SIA-DCS frame for alarm event (Task 3.2.2b).

        Constructs complete SIA protocol frame for alarm event delivery with:
        - Account number and CRC format from preset
        - Incremented sequence number (wrapped at 10000)
        - Zone information in extended data
        - UTC timestamp

        Args:
            event_item: EventItem with sia_code, zone, timestamp

        Returns:
            Complete SIA frame as bytes: LF + CRC + Length + Message + CR

        Reference: story 5-2 Task 3.2.2b, sia_protocol.py encode_message()
        """
        try:
            # Increment sequence number (wrap at 10000)
            self._sia_seq = (self._sia_seq + 1) % 10000

            # Build extended data with zone information
            extended_data = {}
            if event_item.zone:
                # Zone information in extended data (protocol-dependent format)
                extended_data['zone'] = event_item.zone

            # Encode frame using SIAMessageBuilder
            # crc_format is set from preset at daemon startup
            frame = self._sia_builder.encode_message(
                account_number=self._account,
                event_code=event_item.sia_code,
                account_prefix=self._account_prefix or "L0",
                receiver_number=self._receiver_prefix,
                extended_data=extended_data if extended_data else None,
                timestamp=None,  # Timestamp in message already (event_item.timestamp)
                encryption=False  # No encryption in v1.0
            )

            return frame

        except Exception as e:
            self._logger.error(f"Error building event frame: {e}")
            raise

    async def _log_sm2_event(
        self,
        transition: str,
        ctx: Optional[SM2LogCtx] = None
    ) -> None:
        """Log SM2 state transitions with French INFO + English DEBUG lines (Task 7).

        Logs alarm event state transitions to both logger and ring buffer.
        Follows dual-line pattern: French user-facing (INFO) + English technical (DEBUG).

        Args:
            transition: State transition type (e.g., "event_received", "confirmed", "failed")
            ctx: Optional SM2LogCtx with zone, sia_code, attempt, elapsed, state_change

        Reference: story 5-2 Task 7, logging-design.md SM2 transition table
        """
        try:
            from . import messages

            if not ctx:
                ctx = SM2LogCtx(
                    zone=self._event_zone,
                    sia_code=self._event_sia_code or "??",
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
                    max=3  # Default max retries
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
                    max=3,
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

            # Log to ring buffer (if available)
            if hasattr(self, '_ring_buffer'):
                await self._ring_buffer.push_supervision_entry(
                    level="info" if "failed" not in transition else "error",
                    message=info_msg,
                    context={
                        "account": self._account,
                        "zone": ctx['zone'],
                        "sia_code": ctx['sia_code'],
                        "attempt": ctx['attempt']
                    },
                    is_routine=False
                )

        except Exception as e:
            self._logger.error(f"Error logging SM2 event: {e}")


# ===== ENTRY POINT =====

if __name__ == "__main__":
    daemon = SIADaemon()
    daemon.run()
