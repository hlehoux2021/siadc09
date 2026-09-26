"""SIA DC-09 Protocol Error Handler — Centralized Error Classification & Notification Contexts

This module defines the canonical 3-tier error classification model for the daemon and PHP plugin.

**PURPOSE:**
This module is a pure Python foundation layer that defines error classification, notification context
dataclasses, and the contract between daemon and PHP via four callback types. It has zero Jeedom/asyncio
dependencies and is fully unit-testable in isolation.

**3-TIER ERROR MODEL:**

**Tier 1 (Auto-heal):**
Transient errors that recover automatically. Examples: supervision timeouts, NAK on invalid timestamp.
Action: Log to message center only. User sees strike counter in UI.

**Tier 2 (User-actionable):**
Configuration or CSR issues requiring user intervention. Example: malformed CSR response.
Action: Log to message center AND fire configured notification command (SMS, push, etc.).

**Tier 3 (Critical):**
Infrastructure failures. Examples: 3 missed supervision cycles, permanent transport failure.
Action: Log to message center, fire notification command, prefix with "CRITIQUE —".
Policy: Every undelivered alarm must trigger critical notification.

**API SURFACE (Story 3.1) — Error Classification:**
- ErrorTier enum with T1, T2, T3 levels
- ErrorCode enum with 6 canonical error codes (SUPERVISION_TIMEOUT, SUPERVISION_NAK, BAD_CSR_RESPONSE,
  SUPERVISION_DISCONNECTED, EVENT_FAILED, TRANSPORT_PERMANENT)
- ERROR_TIERS immutable mapping (ErrorCode → ErrorTier)
- classify_error() helper function
- T3_PREFIX constant for critical message prefixing ("CRITIQUE — ")

**API SURFACE (Story 3.2) — Notification Contexts:**
- 6 context dataclasses (frozen, immutable):
  - SM1TimeoutCtx: SUPERVISION_TIMEOUT (T1)
  - SM1NakCtx: SUPERVISION_NAK (T1)
  - SM1DisconnectedCtx: SUPERVISION_DISCONNECTED (T3)
  - BadCSRResponseCtx: BAD_CSR_RESPONSE (T2)
  - TransportPermanentCtx: TRANSPORT_PERMANENT (T3)
  - EventFailedCtx: EVENT_FAILED (T3)
- NotificationContext union type
- _notify() interface signature
- _validate_context() helper for testing

**API SURFACE (Story 3.3) — Callback Types & Dispatch Contract:**

This story defines the **daemon-PHP IPC boundary contract** via four callback types. Each callback
carries a JSON-serializable payload that describes the error and how PHP should respond.

**Callback 1: `message_center`**
- Fired for: ALL error codes (T1, T2, T3)
- Payload: {type, tier, logical_id, title, message, timestamp, context}
- Timing: Synchronous (immediate when _notify() called)
- Purpose: Log error to Jeedom message center with deduplication via logical_id

**Callback 2: `notify`**
- Fired for: T2 and T3 errors ONLY (not T1)
- Payload: {type, tier, title, message, critical, timestamp}
- Timing: Synchronous (immediate when _notify() called)
- Purpose: Fire configured user notification (SMS, push, etc.) via Jeedom notification queue

**Callback 3: `error_update`**
- Fired for: T2 and T3 errors ONLY (not T1)
- Payload: {type, action (add|update|resolve), error {code, tier, timestamp, message, context, count}}
- Timing: Synchronous (immediate when _notify() called)
- Purpose: Update sia_last_errors config key (max 10 entries, manual clear only)

**Callback 4: `message_trace`**
- Fired for: ALL error codes (T1, T2, T3) + routine supervision messages
- Payload: {type, entry {timestamp, level (DEBUG|INFO|WARNING|ERROR), message, code, context_json}}
- Timing: Asynchronous (enqueue to ring buffer task, do not block _notify())
- Purpose: Append to sia_last_messages ring buffer (max 50 entries) for protocol inspector debugging

**Dispatch Logic (Story 3.3 Stub):**
The _notify(code, ctx) function is the daemon's central error dispatch point. It internally calls
_dispatch_notify(code, ctx), which fires the appropriate callbacks based on error tier:

- **T1 (auto-heal)**: message_center + message_trace (NO notify or error_update)
- **T2 (user-actionable)**: message_center + notify + error_update + message_trace
- **T3 (critical)**: message_center + notify + error_update + message_trace + T3_PREFIX prefix
  + critical=true flag + then call daemon.stop() (for TRANSPORT_PERMANENT)

Full implementation of _dispatch_notify() is deferred to Epic 6 (Error Handler Implementation).
This story defines the callback contract only.

**USAGE GUIDE — When and How to Call _notify():**

1. **SM1 Supervision — SUPERVISION_TIMEOUT (T1, auto-heal)**
   - **When:** Supervision NULL message times out waiting for ACK (transient network loss)
   - **Code:** `_notify(ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(elapsed_ms=5000.0, strike_count=1, supervision_interval_s=60.0))`
   - **Recovery:** Automatic on next successful ACK; strike counter resets

2. **SM1 Supervision — SUPERVISION_NAK (T1, auto-heal, v1.1)**
   - **When:** CSR responds with NAK to supervision NULL (invalid timestamp)
   - **Code:** `_notify(ErrorCode.SUPERVISION_NAK, SM1NakCtx(raw_nak_frame=frame, nak_timestamp=parse_or_none(frame), account_number='000001'))`
   - **Note:** v1.0 always NAKs (static timestamp). v1.1 adds dynamic timestamp parsing for real auto-heal.

3. **SM1 Supervision — SUPERVISION_DISCONNECTED (T3, critical)**
   - **When:** 3 consecutive supervision NULLs timeout without ACK (connection loss, CSR unreachable)
   - **Code:** `_notify(ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx(strike_count=3, last_ack_time_utc=last_ack, time_since_last_ack_s=elapsed, supervision_interval_s=60.0))`
   - **Action:** User notification, daemon termination, Jeedom watchdog restarts

4. **Transport — BAD_CSR_RESPONSE (T2, user-actionable)**
   - **When:** CSR sends unparseable response (not ACK/NAK). Indicates misconfiguration.
   - **Code:** `_notify(ErrorCode.BAD_CSR_RESPONSE, BadCSRResponseCtx(raw_frame=frame, parse_error=str(e), csr_host='192.168.1.1', csr_port=5000, transport='tcp'))`
   - **User Action:** Check CSR IP, port, account number configuration

5. **Transport — TRANSPORT_PERMANENT (T3, critical)**
   - **When:** TCP max reconnect attempts exceeded OR UDP permanently unreachable
   - **Code:** `_notify(ErrorCode.TRANSPORT_PERMANENT, TransportPermanentCtx(reason='tcp_max_retries_exceeded', transport='tcp', error_details='Connection refused', retry_count=3))`
   - **Action:** User notification, daemon termination, Jeedom watchdog restarts

6. **SM2 Event — EVENT_FAILED (T3, critical)**
   - **When:** Alarm delivery fails after max retry attempts. **MANDATORY per NFR1: Zero Silent Failures**
   - **Code:** `_notify(ErrorCode.EVENT_FAILED, EventFailedCtx(sia_code='BA', sia_seq=42, zone_name='Living Room', max_retries=3, attempts_made=3, last_error='timeout'))`
   - **User Action:** Manual verification of alarm delivery (SMS, call, etc.)

**Dependencies:** Python stdlib only — no asyncio, no Jeedom, no sia_protocol.
This module is a foundation layer imported by all higher layers. Zero circular dependencies.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Literal, TypedDict


# T3_PREFIX constant — prepended to all critical-tier notification messages
T3_PREFIX: Final[str] = "CRITIQUE — "


class ErrorTier(Enum):
    """Error classification tier for notification policy.

    Tier values (1, 2, 3) are used by message center deduplication logic.
    """

    T1 = 1  # Auto-heal — transient, message center only
    T2 = 2  # User-actionable — configuration issue, message center + command
    T3 = 3  # Critical — infrastructure failure, message center + command + "CRITIQUE —" prefix


class ErrorCode(Enum):
    """Canonical set of 6 error codes used across daemon and PHP plugin.

    Each code is mapped to an ErrorTier via ERROR_TIERS.
    No additions without design review and backlog prioritization.
    """

    # Tier 1 — Auto-heal
    SUPERVISION_TIMEOUT = "supervision_timeout"
    SUPERVISION_NAK = "supervision_nak"

    # Tier 2 — User-actionable
    BAD_CSR_RESPONSE = "bad_csr_response"

    # Tier 3 — Critical
    SUPERVISION_DISCONNECTED = "supervision_disconnected"
    EVENT_FAILED = "event_failed"
    TRANSPORT_PERMANENT = "transport_permanent"


# Immutable mapping: ErrorCode → ErrorTier (frozen via MappingProxyType)
ERROR_TIERS: MappingProxyType[ErrorCode, ErrorTier] = MappingProxyType({
    ErrorCode.SUPERVISION_TIMEOUT: ErrorTier.T1,
    ErrorCode.SUPERVISION_NAK: ErrorTier.T1,
    ErrorCode.BAD_CSR_RESPONSE: ErrorTier.T2,
    ErrorCode.SUPERVISION_DISCONNECTED: ErrorTier.T3,
    ErrorCode.EVENT_FAILED: ErrorTier.T3,
    ErrorCode.TRANSPORT_PERMANENT: ErrorTier.T3,
})


def classify_error(code: ErrorCode) -> ErrorTier:
    """Return the tier (T1, T2, or T3) for a given error code.

    Args:
        code: An ErrorCode enum value

    Returns:
        ErrorTier enum value (T1, T2, or T3)

    Raises:
        KeyError: If code is not in ERROR_TIERS (should not happen with proper enum usage)
    """
    return ERROR_TIERS[code]


# ============================================================================
# NOTIFICATION CONTEXTS (Story 3.2)
# ============================================================================


@dataclass(frozen=True)
class SM1TimeoutCtx:
    """Context for SUPERVISION_TIMEOUT (T1 auto-heal) errors.

    Raised when supervision NULL message times out waiting for ACK.
    Normal during transient network issues. Recovers on next successful ACK.

    Example:
        ctx = SM1TimeoutCtx(
            elapsed_ms=5000.0,
            strike_count=1,
            supervision_interval_s=60.0
        )
        _notify(ErrorCode.SUPERVISION_TIMEOUT, ctx)
    """

    elapsed_ms: float
    strike_count: int
    supervision_interval_s: float


@dataclass(frozen=True)
class SM1NakCtx:
    """Context for SUPERVISION_NAK (T1 auto-heal) errors.

    Raised when CSR responds with NAK to supervision NULL (invalid timestamp).
    In v1.0 with static timestamps, NAKs always occur. v1.1 will add dynamic
    timestamp parsing for actual auto-heal recovery.

    Example:
        ctx = SM1NakCtx(
            raw_nak_frame=b'\\x0a\\x00\\x00\\x00\\x0d',
            nak_timestamp=None,
            account_number='000001'
        )
        _notify(ErrorCode.SUPERVISION_NAK, ctx)
    """

    raw_nak_frame: bytes
    nak_timestamp: str | None
    account_number: str


@dataclass(frozen=True)
class SM1DisconnectedCtx:
    """Context for SUPERVISION_DISCONNECTED (T3 critical) errors.

    Raised when 3 consecutive supervision NULL messages timeout without ACK.
    Indicates connection loss or CSR unreachability.

    Example:
        ctx = SM1DisconnectedCtx(
            strike_count=3,
            last_ack_time_utc=datetime(2026, 4, 9, 14, 23, 45, tzinfo=timezone.utc),
            time_since_last_ack_s=180.0,
            supervision_interval_s=60.0
        )
        _notify(ErrorCode.SUPERVISION_DISCONNECTED, ctx)
    """

    strike_count: int
    last_ack_time_utc: datetime | None
    time_since_last_ack_s: float | None
    supervision_interval_s: float


@dataclass(frozen=True)
class BadCSRResponseCtx:
    """Context for BAD_CSR_RESPONSE (T2 user-actionable) errors.

    Raised when CSR sends a response that cannot be parsed as ACK or NAK.
    Indicates misconfiguration (wrong IP, port, account) or protocol mismatch.

    Example:
        ctx = BadCSRResponseCtx(
            raw_frame=b'\\x0aGARBLED\\x0d',
            parse_error='Expected frame to start with LF, got G',
            csr_host='192.168.1.100',
            csr_port=5000,
            transport='udp'
        )
        _notify(ErrorCode.BAD_CSR_RESPONSE, ctx)
    """

    raw_frame: bytes
    parse_error: str
    csr_host: str
    csr_port: int
    transport: Literal["udp", "tcp"]


@dataclass(frozen=True)
class TransportPermanentCtx:
    """Context for TRANSPORT_PERMANENT (T3 critical) errors.

    Raised when TCP max reconnect attempts exceeded or UDP permanently unreachable.
    Terminal condition — daemon stops and Jeedom watchdog restarts it.

    Example:
        ctx = TransportPermanentCtx(
            reason='tcp_max_retries_exceeded',
            transport='tcp',
            error_details='Connection refused',
            retry_count=3
        )
        _notify(ErrorCode.TRANSPORT_PERMANENT, ctx)
    """

    reason: str
    transport: Literal["udp", "tcp"]
    error_details: str | None
    retry_count: int | None


@dataclass(frozen=True)
class EventFailedCtx:
    """Context for EVENT_FAILED (T3 critical) errors.

    Raised when alarm delivery fails after max retry attempts.
    Every undelivered alarm must trigger this critical notification (NFR1: Zero Silent Failures).

    Example:
        ctx = EventFailedCtx(
            sia_code='BA',
            sia_seq=42,
            zone_name='Living Room',
            max_retries=3,
            attempts_made=3,
            last_error='timeout'
        )
        _notify(ErrorCode.EVENT_FAILED, ctx)
    """

    sia_code: Literal["BA", "FA", "PA", "BC", "OP", "CL"]
    sia_seq: int
    zone_name: str | None
    max_retries: int
    attempts_made: int
    last_error: str
    # Stories 13-1/13-4 (ADR-18): address field for BC/OP/CL — user-addressed, not
    # zone-addressed. Optional/defaulted so existing BA/FA/PA call sites are unaffected.
    user_number: int | None = None


# Union type for all notification context dataclasses
NotificationContext = (
    SM1TimeoutCtx
    | SM1NakCtx
    | SM1DisconnectedCtx
    | BadCSRResponseCtx
    | TransportPermanentCtx
    | EventFailedCtx
)


class NotificationPayload(TypedDict):
    """Typed return value of build_notification()."""
    tier: Literal[1, 2, 3]
    logical_id: str
    title: str
    message: str


def event_type_fr(event_type: str) -> str:
    """Convert SIA alarm command name to French label.

    Args:
        event_type: PHP command or SIA code — "burglarAlarm"/"BA", "fireAlarm"/"FA",
            "panicAlarm"/"PA", "burglaryCancel"/"BC" (legacy alias, never sent by the
            current disarm/alarmReset commands, kept for backward compatibility), or
            the SIA codes "BC" (cancel) / "OP" (disarm, story 13-1, ADR-18) / "CL"
            (arm, story 13-4, ADR-18)

    Returns:
        French label string
    """
    mapping = {
        "burglarAlarm": "intrusion",
        "BA": "intrusion",
        "fireAlarm": "incendie",
        "FA": "incendie",
        "panicAlarm": "panique",
        "PA": "panique",
        "burglaryCancel": "annulation",
        "BC": "annulation",
        "OP": "désarmement",
        "CL": "armement",
    }
    return mapping.get(event_type, event_type)


def build_notification(code: ErrorCode, context: dict[str, Any]) -> NotificationPayload:
    """Build notification payload for a given error code and runtime context.

    All context fields accessed via .get('field', '<inconnu>') for missing-field resilience.
    A degraded message is always preferable to a KeyError in a safety-critical context.

    Args:
        code: ErrorCode enum value
        context: Runtime dict with fields: csr_address, transport, strike_count, etc.

    Returns:
        NotificationPayload TypedDict with tier, logical_id, title, message.
    """
    tier_map: dict[ErrorCode, Literal[1, 2, 3]] = {
        ErrorCode.SUPERVISION_TIMEOUT: 1,
        ErrorCode.SUPERVISION_NAK: 1,
        ErrorCode.BAD_CSR_RESPONSE: 2,
        ErrorCode.SUPERVISION_DISCONNECTED: 3,
        ErrorCode.EVENT_FAILED: 3,
        ErrorCode.TRANSPORT_PERMANENT: 3,
    }

    # Story 13-1 (finding #4) / Story 13-4: EVENT_FAILED must name the failed event
    # precisely — BC/OP/CL are a cancel/disarm/arm, not a generic "alarme" — and address it
    # by configured user number, not zone (DC-03 addresses BC/OP/CL by user — ADR-18). BA/
    # FA/PA keep their original zone-addressed wording unchanged.
    _event_sia_code = str(context.get("sia_code", context.get("event_type", "<inconnu>")))
    if _event_sia_code == "BC":
        _event_title_subject = "Annulation"
        _event_subject, _event_object, _event_gender_e = "L'annulation", "l'annulation", "e"
    elif _event_sia_code == "OP":
        _event_title_subject = "Désarmement"
        _event_subject, _event_object, _event_gender_e = "Le désarmement", "le désarmement", ""
    elif _event_sia_code == "CL":
        _event_title_subject = "Armement"
        _event_subject, _event_object, _event_gender_e = "L'armement", "l'armement", ""
    else:
        _event_title_subject = "Alarme"
        _event_subject = "L'alarme " + event_type_fr(_event_sia_code)
        _event_object, _event_gender_e = "l'alarme", "e"

    if _event_sia_code in ("BC", "OP", "CL"):
        _event_address_clause = f"(utilisateur: {context.get('user_number', '<inconnu>')})"
    else:
        _event_address_clause = (
            "(zone: " + str(context.get("zone_name", context.get("zone", "<inconnu>"))) + ")"
        )

    title_map: dict[ErrorCode, str] = {
        ErrorCode.SUPERVISION_TIMEOUT: "siaDC09 — Timeout supervision (auto-résolu)",
        ErrorCode.SUPERVISION_NAK: "siaDC09 — NAK supervision (horodatage rejeté — auto-résolu)",
        ErrorCode.BAD_CSR_RESPONSE: "siaDC09 — Réponse incompréhensible de la centrale",
        ErrorCode.SUPERVISION_DISCONNECTED: "siaDC09 — Supervision perdue",
        ErrorCode.EVENT_FAILED: f"siaDC09 — {_event_title_subject} non transmis{_event_gender_e}",
        ErrorCode.TRANSPORT_PERMANENT: (
            f"siaDC09 — Connexion {context.get('transport', '<inconnu>')} impossible"
        ),
    }

    csr_address = context.get("csr_address", "<inconnu>")
    transport = context.get("transport", "<inconnu>").upper()
    strike_count = context.get("strike_count", "?")

    message_map: dict[ErrorCode, str] = {
        ErrorCode.SUPERVISION_TIMEOUT: (
            f"Timeout supervision auto-résolu (strike {strike_count}/3).\n"
            f"Centrale: {csr_address} ({transport})."
        ),
        ErrorCode.SUPERVISION_NAK: (
            f"NAK supervision (strike {strike_count}/3) — la centrale a rejeté "
            f"l'horodatage du message.\nCentrale: {csr_address} ({transport})."
        ),
        ErrorCode.BAD_CSR_RESPONSE: (
            "La centrale a renvoyé une réponse que le plugin ne peut pas interpréter.\n"
            "Cela peut indiquer un problème de version de protocole ou de configuration réseau.\n"
            "Contactez le support siaDC09 si le problème persiste.\n"
            f"Centrale: {csr_address} ({transport})."
        ),
        ErrorCode.SUPERVISION_DISCONNECTED: (
            T3_PREFIX
            + "La supervision vers la centrale est perdue\n"
            "(3 tentatives sans réponse). La centrale de télésurveillance ne reçoit plus\n"
            "les signaux de vie. Vérifiez votre connexion réseau et le service IMA Protect.\n"
            f"Centrale: {csr_address} ({transport})."
        ),
        ErrorCode.EVENT_FAILED: (
            T3_PREFIX
            + _event_subject
            + " "
            + _event_address_clause
            + " n'a pas pu être transmis" + _event_gender_e + "\nà la centrale après "
            + str(context.get("attempts_made", context.get("retry_count", "?")))
            + " tentative(s). La centrale de\ntélésurveillance n'a PAS reçu "
            + _event_object + ".\n"
            "Vérifiez votre connexion réseau et le service IMA Protect.\n"
            f"Centrale: {csr_address} ({transport})."
        ),
        ErrorCode.TRANSPORT_PERMANENT: (
            T3_PREFIX
            + f"Impossible de rétablir la connexion {context.get('transport', '<inconnu>')} "
            "avec la centrale\naprès "
            + str(context.get("retry_count", "?"))
            + " tentative(s). La supervision et la transmission d'alarmes\n"
            "sont interrompues. Vérifiez votre réseau.\n"
            f"Centrale: {csr_address} ({transport})."
        ),
    }

    tier: Literal[1, 2, 3] = tier_map.get(code, 1)  # type: ignore[assignment]
    title = title_map.get(code, f"siaDC09 — Erreur {code.name}")
    message = message_map.get(code, f"Erreur inconnue: {code.name}")
    logical_id = code.value  # e.g. "supervision_timeout"

    return NotificationPayload(tier=tier, logical_id=logical_id, title=title, message=message)


def _notify(code: ErrorCode, ctx: NotificationContext) -> None:
    """Notify PHP and user of an error via message center and/or notification command.

    This is the daemon's central error dispatch point. Called by SM1, SM2, and transport
    code whenever an error occurs. The context object carries all diagnostic data needed
    for logging, message center entries, and user notifications.

    Full implementation dispatches to message center, notification commands, and ring buffer
    logging per tier (T1/T2/T3). See Story 3.3 for dispatcher details.

    Args:
        code: ErrorCode enum value identifying the error type
        ctx: NotificationContext object with diagnostic data (SM1TimeoutCtx, etc.)

    Raises:
        ValueError: If code is not a known ErrorCode
        TypeError: If ctx is not a valid NotificationContext subtype matching the error code
        NotImplementedError: Full _dispatch_notify() stub (implementation deferred to Epic 6)

    Example:
        _notify(ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(
            elapsed_ms=5000.0,
            strike_count=1,
            supervision_interval_s=60.0
        ))

    [Source: error-handler-design.md § Notification Dispatch Contract]
    [Source: Story 3.3 — Full dispatcher implementation]
    """
    # Validate context type matches error code
    _validate_context(code, ctx)
    # Dispatch to PHP via four callback types (implementation in _dispatch_notify)
    _dispatch_notify(code, ctx)


def _dispatch_notify(code: ErrorCode, ctx: NotificationContext) -> None:
    """Dispatch error notification to PHP via four callback types (stub).

    This is the daemon's error dispatch point. Called by _notify() to fire up to four
    callbacks (message_center, notify, error_update, message_trace) based on error tier.

    DISPATCH LOGIC (full implementation deferred to Epic 6):

    **Tier 1 (Auto-heal — message_center + message_trace only):**
      - SUPERVISION_TIMEOUT: fire message_center callback, append to message_trace ring buffer
      - SUPERVISION_NAK: fire message_center callback, append to message_trace ring buffer
      - Do NOT fire notify callback (no user notification for auto-heal errors)
      - Do NOT fire error_update callback (no persistence for T1)
      - Strike counter managed by SM1 (1–3); recovery on next successful ACK

    **Tier 2 (User-actionable — message_center + notify + error_update + message_trace):**
      - BAD_CSR_RESPONSE: fire all four callbacks
      - Fire notify callback (triggers configured notification command via queue plugin)
      - Fire error_update callback with action='add' or 'update' (increment count if duplicate)
      - Persist to sia_last_errors config key (max 10 entries, manual clear only)
      - Append to message_trace ring buffer

    **Tier 3 (Critical — all four callbacks + special handling):**
      - SUPERVISION_DISCONNECTED: fire all four callbacks, call daemon.stop()
      - EVENT_FAILED: fire all four callbacks, call daemon.stop()
      - TRANSPORT_PERMANENT: fire all four callbacks, call daemon.stop()
      - Message prefixed with T3_PREFIX ("CRITIQUE — ") in notify and message_center payloads
      - notify callback with critical=true (queue plugin marks as high-priority)
      - error_update action='add' or 'update', persist to sia_last_errors
      - Append to message_trace with level='ERROR' (not DEBUG/INFO)

    **Callback Firing Contract (Guarantees):**
      - message_center: fires for ALL error codes (T1/T2/T3)
      - notify: fires ONLY for T2/T3 (not T1), omitted for T1 auto-heal
      - error_update: fires ONLY for T2/T3 (not T1), action is 'add' or 'update'
      - message_trace: fires for all codes + routine supervision NULL→ACK messages

    **Callback Timing Guarantees:**
      - message_center: synchronous (immediate dispatch, returns before next line executes)
      - notify: synchronous (immediate dispatch)
      - error_update: synchronous (immediate dispatch)
      - message_trace: asynchronous (enqueue to ring buffer task, do not block caller)

    **Deduplication Strategy:**
      - message_center: Jeedom occurrence counter via logical_id field (automatic)
      - notify: Jeedom notification queue plugin deduplicates via title field
      - error_update: compare code + logical_id in sia_last_errors; update count if match
      - message_trace: append all entries (routine supervision throttled at ring buffer layer)

    **Payload Schemas (JSON-serializable for PHP transmission):**

    message_center: {type, tier, logical_id, title, message, timestamp, context}
    notify: {type, tier, title, message, critical, timestamp}
    error_update: {type, action, error {code, tier, timestamp, message, context, count}}
    message_trace: {type, entry {timestamp, level, message, code, context_json}}

    Args:
        code: ErrorCode enum value identifying the error type
        ctx: NotificationContext object with diagnostic data

    Raises:
        NotImplementedError: This is a stub; full implementation is in Epic 6

    [Source: error-handler-design.md § Tier 1/2/3 Dispatch Logic]
    [Source: daemon-design.md § Error Handler Integration]
    [Source: php-core-design.md § Daemon-PHP IPC Protocol]
    """
    # Module-level stub — actual dispatch implemented in SIADaemon._dispatch_notify()
    # This function documents the callback contract (see Story 3.3 docstring).
    pass


def _validate_context(code: ErrorCode, ctx: NotificationContext) -> bool:
    """Validate that context type matches error code (for testing and debugging).

    Args:
        code: ErrorCode enum value
        ctx: NotificationContext instance to validate

    Returns:
        True if valid

    Raises:
        ValueError: If code is unknown
        TypeError: If ctx type doesn't match expected type for code
    """
    expected_contexts: dict[ErrorCode, type] = {
        ErrorCode.SUPERVISION_TIMEOUT: SM1TimeoutCtx,
        ErrorCode.SUPERVISION_NAK: SM1NakCtx,
        ErrorCode.SUPERVISION_DISCONNECTED: SM1DisconnectedCtx,
        ErrorCode.BAD_CSR_RESPONSE: BadCSRResponseCtx,
        ErrorCode.TRANSPORT_PERMANENT: TransportPermanentCtx,
        ErrorCode.EVENT_FAILED: EventFailedCtx,
    }
    expected_type = expected_contexts.get(code)
    if expected_type is None:
        raise ValueError(f"Unknown error code: {code}")
    if not isinstance(ctx, expected_type):
        raise TypeError(
            f"Invalid context type for {code.name}: "
            f"expected {expected_type.__name__}, got {type(ctx).__name__}"
        )
    return True


def _context_to_dict(ctx: NotificationContext | None) -> dict | None:
    """Convert context dataclass to JSON-serializable dict for callback payloads.

    Handles serialization of special types:
    - bytes → hex string (human-readable for debugging)
    - datetime → ISO 8601 UTC format (e.g., "2026-04-10T14:35:22+00:00")
    - Optional[T] → value or null (JSON null, not "null" string)

    Privacy Rules:
    - Encryption key values are NEVER included in output
    - If encryption key length is needed, use "key_length_bytes" field instead

    Args:
        ctx: NotificationContext instance (one of six context dataclass types), or None

    Returns:
        dict with serializable fields; all values are JSON-safe (str, int, float, bool, null, dict, list),
        or None if ctx is None

    Raises:
        TypeError: If ctx is not a valid NotificationContext subtype or None

    Example:
        ctx = SM1TimeoutCtx(elapsed_ms=5000.0, strike_count=1, supervision_interval_s=60.0)
        payload = _context_to_dict(ctx)
        # Returns: {"elapsed_ms": 5000.0, "strike_count": 1, "supervision_interval_s": 60.0}

        payload = _context_to_dict(None)
        # Returns: None

    [Source: error-handler-design.md § Privacy Rules]
    [Source: Story 3.3 — Error Context Serialization]
    """
    if ctx is None:
        return None

    # SM1TimeoutCtx: elapsed time and strike counter
    if isinstance(ctx, SM1TimeoutCtx):
        return {
            "elapsed_ms": ctx.elapsed_ms,
            "strike_count": ctx.strike_count,
            "supervision_interval_s": ctx.supervision_interval_s,
        }

    # SM1NakCtx: NAK frame and timestamp parsing result
    if isinstance(ctx, SM1NakCtx):
        return {
            "raw_nak_frame_hex": ctx.raw_nak_frame.hex(),
            "nak_timestamp": ctx.nak_timestamp,
            "account_number": ctx.account_number,
        }

    # SM1DisconnectedCtx: disconnection and recovery timing
    if isinstance(ctx, SM1DisconnectedCtx):
        return {
            "strike_count": ctx.strike_count,
            "last_ack_time_utc": (
                ctx.last_ack_time_utc.isoformat() if ctx.last_ack_time_utc else None
            ),
            "time_since_last_ack_s": ctx.time_since_last_ack_s,
            "supervision_interval_s": ctx.supervision_interval_s,
        }

    # BadCSRResponseCtx: unparseable response from CSR
    if isinstance(ctx, BadCSRResponseCtx):
        return {
            "raw_frame_hex": ctx.raw_frame.hex(),
            "parse_error": ctx.parse_error,
            "csr_host": ctx.csr_host,
            "csr_port": ctx.csr_port,
            "transport": ctx.transport,
        }

    # TransportPermanentCtx: permanent network failure
    if isinstance(ctx, TransportPermanentCtx):
        return {
            "reason": ctx.reason,
            "transport": ctx.transport,
            "error_details": ctx.error_details,
            "retry_count": ctx.retry_count,
        }

    # EventFailedCtx: alarm delivery failure
    if isinstance(ctx, EventFailedCtx):
        return {
            "sia_code": ctx.sia_code,
            "sia_seq": ctx.sia_seq,
            "zone_name": ctx.zone_name,
            "max_retries": ctx.max_retries,
            "attempts_made": ctx.attempts_made,
            "last_error": ctx.last_error,
            "user_number": ctx.user_number,
        }

    # Unknown context type
    raise TypeError(f"Unknown context type: {type(ctx).__name__}")


__all__ = [
    "ErrorCode",
    "ErrorTier",
    "ERROR_TIERS",
    "T3_PREFIX",
    "classify_error",
    "SM1TimeoutCtx",
    "SM1NakCtx",
    "SM1DisconnectedCtx",
    "BadCSRResponseCtx",
    "TransportPermanentCtx",
    "EventFailedCtx",
    "NotificationContext",
    "NotificationPayload",
    "build_notification",
    "event_type_fr",
    "_notify",
    "_dispatch_notify",
    "_validate_context",
    "_context_to_dict",
]
