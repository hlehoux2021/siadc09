# Protocol Error Handler Design — Jeedom siaDC09 Plugin

**Version:** 0.1
**Date:** 2026-03-05
**Status:** Draft — all Component 5a decisions confirmed

---

## Overview

Components 1 and 4 already handle protocol errors inline — NAK dispatch in
`_send_with_retry()`, `_handle_supervision_nak()`, and a local `_nak_to_user_message()`
in the daemon. Component 5a:

1. Extracts all error classification and message generation into a **centralized
   `error_handler.py`** module (pure Python, zero Jeedom/asyncio dependencies)
2. Defines the **canonical 3-tier model** that was implicit across Components 1 and 4
3. Standardizes the **`_notify()` method** with a consistent dual-channel policy
4. Adds **structured error payloads** to PHP for the future debug inspector (Component 5c)

No new protocol behavior is introduced. This is a consolidation and completion pass.

---

## Transport support

Both **TCP and UDP** are supported in v1.0. The transport depends on the CSR provider
(defined in the preset file or manual config). The CSR simulator tests both transports.
A `transport` config key is stored in equipment configuration. Error messages reference
`{transport}` rather than hardcoding any specific transport.

---

## 3-Tier error model — canonical definition

### Tier 1 — Auto-heal (warning)

Errors that recover automatically without user action. Written to the Jeedom message
center at warning level (logically — Jeedom's `message::add()` has no severity
parameter; T1 messages use neutral language). **No configured notification command
fired.**

Jeedom's occurrence counter (via `logicalId`) handles deduplication — a network
outage generating 10 consecutive supervision timeouts produces **one message center
entry** with occurrence count 10, not 10 separate entries.

| Code | Event | Trigger |
|------|-------|---------|
| `supervision_timeout` | Single supervision timeout | SM1 strike++ (strike < 3) |
| `supervision_nak` | CSR rejected frame timestamp (parseable NAK) | SM1 strike++ (strike < 3) |

### Tier 2 — User-actionable (error)

Errors that require user intervention (configuration fix or support contact). Written
to the Jeedom message center at error level **and** the configured notification command
is fired (SMS, push, etc. via notification queue plugin).

| Code | Event |
|------|-------|
| `bad_csr_response` | CSR returned an unexpected or undecodable response |

**Protocol note:** per SIA DC-09 section 5.5.3.2, the CSR sends a NAK only when a
message fails the timestamp validation test. The NAK data field contains the CSR's
current GMT time (for PE clock correction). There are **no standard NAK sub-codes**
(no `bad_acct`, `bad_encryption`, etc. in the protocol). Any NAK received, or any
undecodable CSR response, is classified as `bad_csr_response` (T2). The v1.1
timestamp auto-heal will parse the CSR timestamp from NAK data for clock resync;
in v1.0 all NAKs immediately stop retrying.

**First-occurrence policy:** alert on the first `bad_csr_response` — do not wait.
For a safety system, one unexpected CSR response is actionable.

**Recovery:** `bad_csr_response` entries in `last_errors` are not auto-resolved.
They remain visible in the debug panel until the user explicitly clears them via the
"Vider" button (Component 5c). No daemon flag is needed.

### Tier 3 — Infrastructure (critical)

Errors where the CSR or network is unreachable — beyond user configuration. Written to
the Jeedom message center at critical level **and** the configured notification command
is fired.

| Code | Event |
|------|-------|
| `supervision_disconnected` | SM1 DEGRADED(strike=3) — 3 consecutive supervision timeouts |
| `event_failed` | SM2 → FAILED (all event retries exhausted) |
| `transport_permanent` | TCP/UDP reconnection exhausted all attempts |

---

## Module: `error_handler.py`

**Location:** `resources/siadc09d/error_handler.py`

**Dependencies:** Python stdlib only — no Jeedom, no asyncio, no `sia_protocol`.
Pure classification and message factory functions. Fully unit-testable in isolation.

### API surface

```python
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final, TypedDict

T3_PREFIX: Final[str] = "CRITIQUE — "
# All T3-tier notification messages prepend this constant (not the raw string).
# Level 1 test: assert every T3 message starts with T3_PREFIX.

class ErrorTier(Enum):
    T1 = 1   # Auto-heal — warning, message center only
    T2 = 2   # User-actionable — error, message center + command
    T3 = 3   # Infrastructure — critical, message center + command


class ErrorCode(Enum):
    # Tier 1
    SUPERVISION_TIMEOUT      = 'supervision_timeout'
    SUPERVISION_NAK          = 'supervision_nak'

    # Tier 2
    BAD_CSR_RESPONSE         = 'bad_csr_response'

    # Tier 3
    SUPERVISION_DISCONNECTED = 'supervision_disconnected'
    EVENT_FAILED             = 'event_failed'
    TRANSPORT_PERMANENT      = 'transport_permanent'


ERROR_TIERS: dict[ErrorCode, ErrorTier] = {
    ErrorCode.SUPERVISION_TIMEOUT:    ErrorTier.T1,
    ErrorCode.SUPERVISION_NAK:        ErrorTier.T1,
    ErrorCode.BAD_CSR_RESPONSE:       ErrorTier.T2,
    ErrorCode.SUPERVISION_DISCONNECTED: ErrorTier.T3,
    ErrorCode.EVENT_FAILED:           ErrorTier.T3,
    ErrorCode.TRANSPORT_PERMANENT:    ErrorTier.T3,
}


# --- Typed context dataclasses for _notify() call sites ---
# Defined here (alongside ErrorCode) so call sites import from one place.
# All context dataclasses are frozen (immutable) and use __slots__ for
# memory efficiency. Use dataclasses.replace(ctx, field=val) for derived copies.

@dataclass(frozen=True, slots=True)
class SM1TimeoutCtx:
    """Extra context for ErrorCode.SUPERVISION_TIMEOUT."""
    strike:     int    # current strike after increment (1–3, capped)
    interval_s: float  # supervision interval in seconds

@dataclass(frozen=True, slots=True)
class SM1NakCtx:
    """Extra context for ErrorCode.SUPERVISION_NAK and ErrorCode.BAD_CSR_RESPONSE."""
    strike:    int            # current strike after increment (1–3, capped)
    raw_nak:   bytes          # raw NAK frame bytes
    parsed_ts: datetime | None  # parsed CSR timestamp from NAK data; None if undecodable

@dataclass(frozen=True, slots=True)
class EventFailedCtx:
    """Extra context for ErrorCode.EVENT_FAILED."""
    zone:     str | None  # zone name from alarm event; None if unset
    sia_code: str         # SIA event code ('BA' | 'FA' | 'PA')
    attempts: int         # total number of send attempts made

@dataclass(frozen=True, slots=True)
class TransportPermanentCtx:
    """Extra context for ErrorCode.TRANSPORT_PERMANENT."""
    transport:  str        # "tcp" | "udp"
    last_error: str | None # last OS/network error message; None if unavailable

# Type alias for _notify() ctx argument (Python 3.10+ | syntax).
# Use ErrorContext everywhere — never re-expand the union inline.
ErrorContext = SM1TimeoutCtx | SM1NakCtx | EventFailedCtx | TransportPermanentCtx | None


class NotificationPayload(TypedDict):
    """Typed return value of build_notification(). Keys verified by mypy at all call sites."""
    tier:       ErrorTier
    logical_id: str   # for Jeedom message center dedup
    title:      str   # for notification queue dedup
    message:    str   # full user-facing message


def make_error_entry(code: str, message: str, timestamp: str,
                     context: dict | None, count: int) -> dict:
    """
    Factory — the only valid construction path for `sia_last_errors` entries.
    All 5 fields are mandatory; `context` may be None; `count` starts at 1.

    Returns: {"code": str, "message": str, "timestamp": str,  # ISO 8601
              "context": dict | None, "count": int}

    Level 1 test: Each ErrorCode → make_error_entry() → valid JSON with all 5 keys.
    """
    ...


def build_notification(code: ErrorCode, context: dict[str, Any]) -> NotificationPayload:
    """
    Build notification payload for a given error code + runtime context.

    Returns a NotificationPayload TypedDict — all keys are always present.

    Missing-field policy: all context fields are accessed via context.get('field', '<inconnu>').
    A missing field produces a degraded but deliverable message (e.g. "Centrale: <inconnu>")
    rather than a KeyError. A degraded message is always preferable to a silent notification
    failure in a safety-critical context.
    Call sites are still expected to pass all required fields — .get() with default is a
    safety net, not a licence to omit fields.
    """
    ...


def event_type_fr(event_type: str) -> str:
    """
    Convert internal event type to French label for user messages.
    burglarAlarm → 'intrusion'
    fireAlarm    → 'incendie'
    panicAlarm   → 'panique'
    """
    ...
```

---

## Context data — what gets embedded in messages

The `context` dict passed to `build_notification()` carries runtime values used to
make messages actionable.

### Privacy rules

| Field | Rule | Example |
|-------|------|---------|
| `account_number` | Show full value | `"Compte: ABC123"` |
| `encryption_key` | **Never show** — length only | `"Clé: 32 caractères"` |
| `csr_address` | Show as `IP:port` | `"Centrale: 192.168.1.100:12000"` |
| `transport` | Show | `"TCP"` or `"UDP"` |
| `zone` | Show full name (from event payload) | `"Salon"` |
| `event_type` | French label via `event_type_fr()` | `"intrusion"` |
| `retry_count` | Show | `"3"` |

### Context fields by error code

| Error code | Required context fields |
|------------|------------------------|
| `supervision_timeout` | `csr_address`, `strike_count`, `transport` |
| `supervision_nak` | `csr_address`, `strike_count`, `transport` |
| `bad_csr_response` | `csr_address`, `transport` |
| `supervision_disconnected` | `csr_address`, `transport` |
| `event_failed` | `event_type`, `zone`, `csr_address`, `transport`, `retry_count` |
| `transport_permanent` | `csr_address`, `transport`, `retry_count` |

---

## Message catalog

### logicalId table

One stable `logicalId` per error code. Jeedom deduplicates `(plugin, logicalId)` pairs —
repeated occurrences increment the occurrence counter rather than creating new entries.

| Code | logicalId |
|------|-----------|
| `supervision_timeout` | `supervision_timeout` |
| `supervision_nak` | `supervision_nak` |
| `bad_csr_response` | `bad_csr_response` |
| `supervision_disconnected` | `supervision_disconnected` |
| `event_failed` | `event_failed` |
| `transport_permanent` | `transport_permanent` |

> **`event_failed` zone exclusion rationale:** including the zone name in the logicalId
> would create a separate message center entry per zone, defeating deduplication.
> Zone information is embedded in the `message` body instead.

### Title table

Titles serve as the deduplication key for the **notification queue plugin**. Titles must
be consistent per error type (same error = same title) and distinct across types
(different errors = different titles).

| Code | Title |
|------|-------|
| `supervision_timeout` | `siaDC09 — Timeout supervision (auto-résolu)` |
| `supervision_nak` | `siaDC09 — NAK supervision (horodatage rejeté — auto-résolu)` |
| `bad_csr_response` | `siaDC09 — Réponse incompréhensible de la centrale` |
| `supervision_disconnected` | `siaDC09 — ` + T3_PREFIX + `Supervision perdue` |
| `event_failed` | `siaDC09 — ` + T3_PREFIX + `Alarme non transmise` |
| `transport_permanent` | `siaDC09 — ` + T3_PREFIX + `Connexion {transport} impossible` |

### Full message templates

**Tier 1:**

```
supervision_timeout:
  "Timeout supervision auto-résolu (strike {strike_count}/3).
   Centrale: {csr_address} ({transport})."

supervision_nak:
  "NAK supervision (strike {strike_count}/3) — la centrale a rejeté l'horodatage du message.
   Centrale: {csr_address} ({transport})."
```

**Tier 2:**

```
bad_csr_response:
  "La centrale a renvoyé une réponse que le plugin ne peut pas interpréter.
   Cela peut indiquer un problème de version de protocole ou de configuration réseau.
   Contactez le support siaDC09 si le problème persiste.
   Centrale: {csr_address} ({transport})."
```

**Tier 3:**

All T3 messages prepend `T3_PREFIX` (defined as the `"CRITIQUE — "` constant in
`error_handler.py` and re-exported from `messages.py`). Never hardcode the prefix
string at call sites. Level 1 test: assert every T3 message starts with `T3_PREFIX`.

```
supervision_disconnected:
  T3_PREFIX + "La supervision vers la centrale est perdue
   (3 tentatives sans réponse). La centrale de télésurveillance ne reçoit plus
   les signaux de vie. Vérifiez votre connexion réseau et le service IMA Protect.
   Centrale: {csr_address} ({transport})."

event_failed:
  T3_PREFIX + "L'alarme {event_type} (zone: {zone}) n'a pas pu être transmise
   à la centrale après {retry_count} tentative(s). La centrale de
   télésurveillance n'a PAS reçu l'alarme.
   Vérifiez votre connexion réseau et le service IMA Protect.
   Centrale: {csr_address} ({transport})."

transport_permanent:
  T3_PREFIX + "Impossible de rétablir la connexion {transport} avec la centrale
   après {retry_count} tentative(s). La supervision et la transmission d'alarmes
   sont interrompues. Vérifiez votre réseau.
   Centrale: {csr_address} ({transport})."
```

---

## `_notify()` — standardized dual-channel dispatch

Replaces the existing `_notify_critical()` in `siadc09d.py`.

```python
def _notify(self, code: ErrorCode, ctx: ErrorContext = None) -> None:
    """
    Synchronous entry point for all notification dispatch.

    Fires _dispatch_notify() as a tracked background task — GC-safe,
    exception-logged, cleanly cancelled on daemon stop. Call sites use
    plain self._notify(code, ctx) with no await and no _track_task().
    """
    self._track_task(self._dispatch_notify(code, ctx), f"notify_{code.name}")

async def _dispatch_notify(self, code: ErrorCode, ctx: ErrorContext = None) -> None:
    """
    Actual dual-channel dispatch. Called only via _notify().

    T1 → Jeedom message center only (via PHP callback)
    T2 → Jeedom message center + configured notification command
    T3 → Jeedom message center + configured notification command

    Both channels are independent — each wrapped in its own try/except.
    Failure of one channel never prevents the other.

    Base context (csr_address, transport, strike_count) is always injected
    from self. Callers only pass event-specific extras via a typed ctx dataclass:
      - SM1TimeoutCtx         for ErrorCode.SUPERVISION_TIMEOUT
      - SM1NakCtx             for ErrorCode.SUPERVISION_NAK
      - SM1NakCtx             for ErrorCode.BAD_CSR_RESPONSE
      - None                  for ErrorCode.SUPERVISION_DISCONNECTED
      - EventFailedCtx        for ErrorCode.EVENT_FAILED
      - TransportPermanentCtx for ErrorCode.TRANSPORT_PERMANENT
    Use ErrorContext type alias — never re-expand the union inline.
    """
    # Base context — always available from self, no need to repeat at call sites
    context = {
        'csr_address':  f'{self._csr_ip}:{self._csr_port}',
        'transport':    self._transport,
        'strike_count': self._strike_counter,
    }
    # Merge event-specific extras from typed ctx dataclass
    if ctx is not None:
        context.update(dataclasses.asdict(ctx))

    notification = error_handler.build_notification(code, context)
    tier = notification['tier']

    # --- Channel 1: Jeedom message center (always) ---
    # PHP callback calls message::add(__CLASS__, message, '', logicalId)
    # Jeedom deduplicates same logicalId → occurrence counter, not new entries
    # Wrapped in its own try/except — failure never prevents Channel 2.
    try:
        await self.send_to_jeedom({
            'type':       'message_center',
            'logical_id': notification['logical_id'],
            'message':    notification['message'],
        })
    except Exception:
        self._logger.error('message_center callback failed')

    # --- Channel 2: configured notification command (T2 + T3 only) ---
    # The notification queue plugin deduplicates based on title and/or message.
    # Deduplication and spam control are the notification plugin's responsibility.
    # We call unconditionally — the plugin handles whether to actually deliver.
    # Wrapped in its own try/except — independent of Channel 1.
    if tier in (ErrorTier.T2, ErrorTier.T3):
        try:
            await self.send_to_jeedom({
                'type':    'notify',
                'title':   notification['title'],
                'message': notification['message'],
            })
        except Exception:
            self._logger.error('notify callback failed')

    # --- Structured error payload for debug panel (Component 5c) ---
    # Only T2 and T3 are stored in last_errors — T1 events are auto-healed
    # and do not require user attention in the debug panel.
    if tier in (ErrorTier.T2, ErrorTier.T3):
        await self.send_to_jeedom({
            'type':     'error_update',
            'tier':     tier.value,
            'code':     code.value,
            'context':  context,
            'message':  notification['message'],
            'ts':       datetime.now(timezone.utc).strftime('%H:%M:%S'),
        })
```

### Error Context Schema — per-ErrorCode requirements

| ErrorCode | Dataclass | Required fields | Optional fields |
|-----------|-----------|-----------------|-----------------|
| `SUPERVISION_TIMEOUT` | `SM1TimeoutCtx` | `strike: int`, `interval_s: float` | — |
| `SUPERVISION_NAK` | `SM1NakCtx` | `strike: int`, `raw_nak: bytes` | `parsed_ts: datetime \| None` |
| `BAD_CSR_RESPONSE` | `SM1NakCtx` | `strike: int`, `raw_nak: bytes` | `parsed_ts: datetime \| None` |
| `SUPERVISION_DISCONNECTED` | `None` | — | — |
| `EVENT_FAILED` | `EventFailedCtx` | `zone: str \| None`, `sia_code: str`, `attempts: int` | — |
| `TRANSPORT_PERMANENT` | `TransportPermanentCtx` | `transport: str` | `last_error: str \| None` |

`ErrorContext = SM1TimeoutCtx | SM1NakCtx | EventFailedCtx | TransportPermanentCtx | None`

`_notify()` signature: `def _notify(self, code: ErrorCode, ctx: ErrorContext = None) -> None`

All context dataclasses are `@dataclass(frozen=True, slots=True)`. Defined in `error_handler.py`;
imported from there everywhere. Use `ErrorContext` type alias — never re-expand the union inline.
Use `dataclasses.replace(ctx, field=new_val)` for derived contexts.

### T1 auto-resolve on HEALTHY transition

When SM1 transitions to `HEALTHY` (ACK received after DEGRADED), T1 errors
(`SUPERVISION_TIMEOUT`, `SUPERVISION_NAK`) are auto-resolved from `sia_last_errors`:
remove all T1-tier entries from the list before pushing the updated `error_update` callback.

### `sia_last_errors` persistence

`sia_last_errors` persists across daemon restarts — PHP reads it at page load. On daemon
start, `sia_last_errors` is **NOT cleared**. Cleared only in `preRemove()`.

---

**No episode tracking in the daemon.** Deduplication responsibilities:
- **Message center:** Jeedom occurrence counter via `logicalId`
- **Notification command:** notification queue plugin, keyed on `title` / `message`

---

## PHP callback — new payload types

Three new `type` values are added to `siaDC09::message()` in `core/class/siaDC09.class.php`
(Task 2.6 in php-core-design.md). `core/php/jeesiaDC09.php` is a thin routing shim that
verifies the API key and calls `siaDC09::message($payload)` — it is not modified by Component 5a.

### `message_center` — write to Jeedom message center

```php
case 'message_center':
    message::add(
        __CLASS__,
        $result['message'],
        '',                      // action — unused
        $result['logical_id']    // dedup key — same logicalId → occurrence++
    );
    break;
```

### `notify` — execute configured notification command

```php
case 'notify':
    $eqLogic = siaDC09::_getAutoEquipmentSafe();
    if (!$eqLogic) { break; }
    $notifyCmdId = (int) $eqLogic->getConfiguration('sia_notify_cmd_id');
    if ($notifyCmdId <= 0) { break; }
    $notifyCmd = cmd::byId($notifyCmdId);
    if (!$notifyCmd) { break; }
    try {
        $notifyCmd->execCmd([
            'title'   => $result['title'],
            'message' => $result['message'],
        ]);
    } catch (Exception $e) {
        log::add(__CLASS__, 'error',
            'Impossible d\'envoyer la notification : ' . $e->getMessage()
        );
    }
    break;
```

### `error_update` — persist structured error for debug panel

```php
case 'error_update':
    $errors = json_decode(config::byKey('sia_last_errors', __CLASS__, '[]'), true) ?: [];

    // Auto-resolve T1 entries before prepending (T1 = supervision_timeout, supervision_nak).
    // When SM1 recovers (ACK after DEGRADED), all T1-tier entries are removed.
    // The daemon sends error_update with a flag or the updated list directly.

    // Prepend new entry (newest first), keep max 10.
    // T2/T3 entries remain until the user clears them via the "Vider" button (5c).
    // All 5 fields are mandatory (make_error_entry() factory in error_handler.py ensures this).
    array_unshift($errors, [
        'code'      => $result['code'],      // ErrorCode string value
        'message'   => $result['message'],   // full user-facing message
        'timestamp' => $result['timestamp'], // ISO 8601 string
        'context'   => $result['context'],   // dict | null
        'count'     => $result['count'],     // int, starts at 1
    ]);
    $errors = array_slice($errors, 0, 10);

    config::save('sia_last_errors', json_encode($errors), __CLASS__);
    break;
```

**Persistence:** plugin-level config key `sia_last_errors` (via `config::byKey/__CLASS__`, JSON,
array of up to 10 entries, newest first). Stored at plugin level — NOT on eqLogic — to
avoid triggering `postSave()` on every error event. Read by Component 5c debug inspector.
Cleared by the "Vider" button via `config::save('sia_last_errors', '[]', __CLASS__)`.

Persists across daemon restarts — **NOT cleared on daemon start**. Cleared only in `preRemove()`.

---

## Refactoring of Components 1 and 4

Component 5a introduces `error_handler.py` — Components 1 and 4 must be updated to use it.

### Changes to `siadc09d.py`

| Old | New |
|-----|-----|
| `_notify_critical(message: str)` | `_notify(code: ErrorCode, context: dict)` |
| `_nak_to_user_message(nak_code: str) -> str` | Removed — replaced by `error_handler.build_notification()` |
| Inline NAK dispatch in `_handle_supervision_nak()` | Any NAK → `_notify(ErrorCode.BAD_CSR_RESPONSE, {…})` |
| Inline NAK dispatch in `_send_with_retry()` | Any NAK → `_notify(ErrorCode.BAD_CSR_RESPONSE, {…})` |
| `_notify_critical("Supervision perdue…")` in `_update_sm1_from_strike()` | `self._notify(ErrorCode.SUPERVISION_DISCONNECTED)` |
| `_notify_critical("Reconnexion TCP échouée")` in `_connect()` | `self._notify(ErrorCode.TRANSPORT_PERMANENT, {…})` in `_tcp_reconnect_loop()` |

> **Protocol note:** per SIA DC-09 section 5.5.3.2, a NAK carries no sub-code — only
> the CSR's current GMT time for clock correction. There is no standard mechanism for
> the CSR to signal "bad account", "bad encryption key", or "bad message format".
> Any NAK (timestamp NAK or otherwise) in v1.0 triggers `BAD_CSR_RESPONSE` (T2).
> The v1.1 timestamp auto-heal feature will handle the standard timestamp NAK gracefully.

### Changes to PHP callback (`core/php/jeeXxx.php`)

Add dispatch for three new `type` values (`message_center`, `notify`, `error_update`)
as shown above. Existing `info_update` dispatch is unchanged.

---

## Task breakdown — Component 5a

### Task 5a.1 — `error_handler.py` skeleton

Create `resources/siadc09d/error_handler.py`. Define `ErrorTier`, `ErrorCode`,
`ERROR_TIERS` dict. Implement `event_type_fr(event_type)`.

No message generation yet — just the classification layer. No `classify_nak()` is
needed: any CSR NAK maps unconditionally to `ErrorCode.BAD_CSR_RESPONSE`.

---

### Task 5a.2 — Tier 1 catalog + T1 message factory

Verify that T1 cases are fully covered by Components 1/4. Document Tier 1 in
`error_handler.py` inline comments.

Implement `build_notification()` for the T1 code (`supervision_timeout`). Include context embedding per the privacy rules table.

---

### Task 5a.3 — Tier 2 message factory

Implement `build_notification()` for the T2 code (`bad_csr_response`). The message:
- Includes CSR address and transport
- Notes that the response could not be interpreted and suggests contacting support
- Uses a single context-agnostic template for both supervision and event send contexts
  (the operator contacts support either way — no `send_context` field is needed)

---

### Task 5a.4 — Tier 3 message factory

Implement `build_notification()` for all T3 codes. Each message:
- Uses "CRITIQUE —" prefix in the message body
- Includes CSR address + transport
- For `event_failed`: includes event type (French) + zone name + retry count

---

### Task 5a.5 — `_notify()` and `_dispatch_notify()` in `siadc09d.py`

Replace `_notify_critical()` with two methods:
- `def _notify(self, code: ErrorCode, ctx: ErrorContext = None)` — synchronous wrapper; calls `_track_task(self._dispatch_notify(code, ctx), f"notify_{code.name}")`
- `async def _dispatch_notify(self, code: ErrorCode, ctx: ErrorContext = None)` — actual dual-channel dispatch (message_center always, notify for T2+T3, error_update for T2+T3); each channel in its own `try/except` — failure of one never prevents the other

All call sites use `self._notify(code, ctx)` — no `await`, no `_track_task()` at the call site.

Update all call sites in Components 1 and 4:
- `_update_sm1_from_strike()` → `self._notify(ErrorCode.SUPERVISION_DISCONNECTED, {...})`
- `_send_with_retry()` NAK received → `self._notify(ErrorCode.BAD_CSR_RESPONSE, {...})` directly.
  No `classify_nak()` — per SIA DC-09 section 5.5.3.2 there are no NAK sub-codes; any NAK
  maps unconditionally to BAD_CSR_RESPONSE.
- `_handle_supervision_nak()` undecodable NAK → `self._notify(ErrorCode.BAD_CSR_RESPONSE, {...})`
  Parseable timestamp NAK (v1.0) → treated as timeout, no notify.
- `_tcp_reconnect_loop()` reconnect failure → `self._notify(ErrorCode.TRANSPORT_PERMANENT, {...})`
- `_send_raw()` OS exception (EAGAIN/ECONNRESET/EPIPE) → logged at WARNING, returned as `{status: 'timeout'}` — no notification fired; absorbed by caller's retry mechanism
- `_send_with_retry()` all retries exhausted → `self._notify(ErrorCode.EVENT_FAILED, {...})`
- `_queue_consumer()` SM1=NO_NETWORK at event dequeue → `self._notify(ErrorCode.EVENT_FAILED, {...})` (event never sent; fired by consumer directly, not by `_send_with_retry()`)

---

### Task 5a.6 — PHP callback error dispatch

Add three new `type` cases to `jeeXxx.php`: `message_center`, `notify`, `error_update`.
Implement `last_errors` persistence (10 entries, remove on resolved).

---

## Design decisions summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| `error_handler.py` placement | `resources/siadc09d/` | Alongside other daemon modules; pure Python, no deps |
| T1 message center write | Yes, via `message::add()` with logicalId | Visibility into auto-healed events; Jeedom dedup prevents spam |
| T1 configured command | No | Auto-healed events do not require user action |
| T2/T3 configured command | Yes (unconditional call) | Deduplication is the notification plugin's responsibility |
| Episode tracking in daemon | None | Fully delegated: logicalId dedup for message center, notification queue for command |
| logicalId per error code | One per ErrorCode (5 total) | Each distinct failure mode has its own dedup key |
| Zone name in logicalId | No — in message body only | Deduplication should aggregate all zone failures under one entry |
| Privacy: account number | Show full value | Not sensitive, directly actionable |
| Privacy: encryption key | Show length only | Never expose key material in any log or notification |
| Garbled CSR response tier | T2, first occurrence | Unknown response = potential protocol mismatch, not transient |
| Transport support | TCP + UDP both in v1.0 | IMA Protect = TCP; simulator tests both; error messages reference `{transport}` |
| `sia_last_errors` depth | 10 entries, newest first | Sufficient for debug panel; bounded size |
| `sia_last_errors` cleared by | User via "Vider" button only (preRemove() resets on plugin removal) | T2/T3 errors require explicit user acknowledgement; persists across restarts |
| T1 auto-resolve | Remove all T1-tier entries on SM1→HEALTHY | T1 errors are self-healing; stale T1 entries in the panel would be misleading |
| `_notify_critical()` | Removed — replaced by `_notify(code, ErrorContext)` | Single entry point, consistent dispatch with typed context |
| Dual-channel independence | Each channel in its own `try/except` | Failure of message center never prevents notification command (and vice versa) |

---

## Testing strategy for Component 5a

| Test | How |
|------|-----|
| T1 supervision_timeout | Single timeout → verify: message center entry logicalId=supervision_timeout, no command called, occurrence increments on second timeout |
| T2 bad_csr_response — supervision | Simulator sends NAK during supervision → verify: logicalId=bad_csr_response, title="siaDC09 — Réponse incompréhensible de la centrale", command called |
| T2 bad_csr_response — event | Simulator sends NAK during alarm event → verify same logicalId, T2 escalation on first occurrence |
| T2 bad_csr_response — garbled | Simulator sends undecodable bytes → verify same T2 path |
| T3 supervision_disconnected | 3 consecutive timeouts → verify: logicalId=supervision_disconnected, title contains "CRITIQUE", command called |
| T3 event_failed | 3 event timeouts → verify: zone + event_type_fr + retry_count in message, command called |
| T3 transport_permanent | Exhaust TCP reconnect attempts → verify T3 payload with transport="TCP" |
| build_notification unit test | All ErrorCodes with full context → verify title/logicalId/message strings |
| last_errors persistence | 12 error_updates → verify max 10 kept, newest first |
| last_errors cleared by user | Click "Vider" in debug panel → verify list empty |
| UDP transport reference | Set transport=UDP → verify all T3 messages say "UDP" not "TCP" |
