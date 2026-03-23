# Logging & Observability Design — Jeedom siaDC09 Plugin

**Version:** 0.1
**Date:** 2026-03-06
**Status:** Draft — all Component 5b decisions confirmed

---

## Overview

Component 5b defines what the daemon and PHP core log, at what level, and establishes
the protocol inspector ring buffer that feeds the Debug UI (Component 5c).

**Boundaries:**
- 5a handles `_notify()`, message center writes, and `error_update` callbacks — not redefined here
- 5c will consume `last_messages` (ring buffer defined here) and `last_errors` (defined in 5a)
- jeedom-daemon-py handles `--loglevel` → `basicConfig()` — 5b layers on top

---

## Task 5b.1 — Logger architecture

**Decision: single root logger (Option A).**

Every module uses `logging.getLogger(__name__)`. All loggers inherit the root level set by
jeedom-daemon-py's `Utils.init_logger()` via `--loglevel`. No per-module logger names,
no independent filtering by module — sufficient for v1.0.

`asyncio` logger is already pinned to WARNING by the framework.

---

## Task 5b.2 — Log level mapping and protocol message trace format

### Level mapping

Jeedom's log system has four visible levels. Python's `CRITICAL` maps to the same display
as `ERROR` in Jeedom — **use `ERROR` for all T3 events, not `CRITICAL`.**

| Python level | Jeedom display | Used for |
|---|---|---|
| `DEBUG` | debug | Routine supervision cycles, raw hex frames, SIA field details, state machine internal data |
| `INFO` | info | Significant operational events in user-friendly French |
| `WARNING` | warning | T1 auto-heal events, supervision timeouts (strike < 3), retry attempts |
| `ERROR` | error | T2 user-actionable events (NAK config errors), T3 infrastructure events (supervision lost, alarm not transmitted, NO_NETWORK) |

### Dual-line pattern

Every significant event produces **two log entries**: one INFO/WARNING/ERROR with a
user-friendly French message, and one DEBUG with full technical detail.
Technical DEBUG lines are always in English and follow a structured `KEY: field=val` format.

```
INFO:  Connexion à la centrale établie
DEBUG: SM1: INIT→HEALTHY | seq=001 strike=0 | ACK: seq=001 crc_format=hex raw=0a303030390030303222...

INFO:  Alarme intrusion envoyée vers la centrale (zone: Salon)
DEBUG: [→ CSR] SIA-DCS | acct=ABC123 seq=007 event=BA zone=Salon ts_sia=14:32:11,03-06-2026 | raw=0a30...

WARNING: Timeout supervision (strike 1/3) — nouvelle tentative
DEBUG:   SM1: HEALTHY→DEGRADED | seq=012 strike=1 elapsed=45s | no response
```

### Protocol message trace format

Used in DEBUG companion lines for send/receive events.

**Send format:**
```
[→ CSR] {type} | acct={account} seq={n} event={code} zone={zone} ts_sia={ts} | raw={hex}
```

**Receive format:**
```
[← CSR] ACK | seq={n} crc_format={hex|bin} elapsed={t}ms | raw={hex}
[← CSR] NAK | seq={n} elapsed={t}ms | raw={hex}
[← CSR] timeout | seq={n} elapsed={t}s
```

### Privacy rules for logs

| Field | Rule |
|---|---|
| `account_number` | Always shown — actionable |
| `encryption_key` | **Never** — not even key length in logs |
| Raw ciphertext bytes | DEBUG only (safe — unusable without key) |
| CSR IP:port | Always shown |
| Zone name | Always shown |

---

## Task 5b.3 — State machine event logging

### SM1 — all transitions

Every transition produces an INFO/WARNING/ERROR line (human-friendly) and a DEBUG line
(technical: state names, counters, elapsed time, frame data).

| Transition | Trigger | Level | Log lines |
|---|---|---|---|
| `[*] → INITIALIZING` | Daemon start | `INFO` | `Démarrage — connexion à la centrale en cours` |
| | | `DEBUG` | `SM1: →INIT \| csr={ip}:{port} transport={tcp\|udp} supervision_interval={n}s` |
| `INITIALIZING → HEALTHY` | First supervision ACK | `INFO` | `Connexion à la centrale établie` |
| | | `DEBUG` | `SM1: INIT→HEALTHY \| seq={n} strike=0 \| ACK: crc_format={hex\|bin} raw={hex}` |
| `INITIALIZING → DEGRADED` | First timeout (strike=1) | `WARNING` | `Timeout supervision au démarrage (strike 1/3) — nouvelle tentative` |
| | | `DEBUG` | `SM1: INIT→DEGRADED \| seq={n} strike=1 elapsed={t}s \| no response` |
| `HEALTHY → DEGRADED` | Timeout (strike=1) | `WARNING` | `Timeout supervision (strike 1/3) — nouvelle tentative` |
| | | `DEBUG` | `SM1: HEALTHY→DEGRADED \| seq={n} strike=1 elapsed={t}s \| no response` |
| `DEGRADED → DEGRADED` | Timeout (strike=2) | `WARNING` | `Timeout supervision (strike 2/3) — nouvelle tentative` |
| | | `DEBUG` | `SM1: DEGRADED→DEGRADED \| seq={n} strike=2 elapsed={t}s \| no response` |
| `DEGRADED → DEGRADED` | Timeout (strike=3, T3 fires) | `ERROR` | `Supervision perdue — 3 tentatives sans réponse (T3 notification envoyée)` |
| | | `DEBUG` | `SM1: DEGRADED→DEGRADED \| seq={n} strike=3 elapsed={t}s \| no response \| T3 fired` |
| `DEGRADED → DEGRADED` | Timeout (strike already 3, subsequent) | `WARNING` | `Supervision toujours absente — en attente de rétablissement` |
| | | `DEBUG` | `SM1: DEGRADED(3) \| seq={n} elapsed={t}s \| no response \| T3 already fired` |
| `DEGRADED → HEALTHY` | ACK, strike reset | `INFO` | `Supervision rétablie après {prev_strike} timeout(s)` |
| | | `DEBUG` | `SM1: DEGRADED→HEALTHY \| seq={n} prev_strike={n} strike=0 \| ACK: crc_format={hex\|bin} raw={hex}` |
| `{any} → TCP_RECONNECTING` | TCP drop | `WARNING` | `Connexion TCP perdue — tentative de reconnexion (depuis état {prev_state})` |
| | | `DEBUG` | `SM1: {prev}→TCP_RECONNECTING \| errno={e} csr={ip}:{port}` |
| `TCP_RECONNECTING → TCP_RECONNECTING` | Attempt failed (first) | `ERROR` | `Reconnexion TCP échouée — centrale injoignable` |
| | | `DEBUG` | `SM1: TCP_RECONNECTING \| attempt=1 errno={e} csr={ip}:{port}` |
| `TCP_RECONNECTING → TCP_RECONNECTING` | Attempt failed (subsequent) | `DEBUG` | `SM1: TCP_RECONNECTING \| attempt={n} errno={e} csr={ip}:{port}` |
| `TCP_RECONNECTING → INITIALIZING` | Reconnect succeeded | `INFO` | `Connexion TCP rétablie — vérification supervision en cours` |
| | | `DEBUG` | `SM1: TCP_RECONNECTING→INIT \| attempt={n} csr={ip}:{port}` |
| `TCP_RECONNECTING → NO_NETWORK` | All attempts exhausted | `ERROR` | `Réseau injoignable après {n} tentatives — arrêt du daemon` |
| | | `DEBUG` | `SM1: TCP_RECONNECTING→NO_NETWORK \| total_attempts={n} csr={ip}:{port}` |

> **Note:** Routine supervision ACK cycles (SM1=HEALTHY, no state change) are logged at
> DEBUG only — no INFO line. This prevents flooding the log at normal operation.
> Only the DEBUG companion line is emitted: `[→ CSR] NULL | ...` then `[← CSR] ACK | ...`.

### SM2 — all transitions

| Transition | Trigger | Level | Log lines |
|---|---|---|---|
| `[*] → IDLE` | Daemon start | `INFO` | `En attente d'événements alarme` |
| | | `DEBUG` | `SM2: →IDLE \| queue=empty` |
| `IDLE → PENDING` | Alarm from PHP | `INFO` | `Alarme {type} reçue (zone: {zone}) — transmission en cours` |
| | | `DEBUG` | `SM2: IDLE→PENDING \| event={sia_code} zone={zone} seq={n} retries_left={max}` |
| `PENDING → PENDING` | Timeout, retry | `WARNING` | `Pas de réponse de la centrale — tentative {attempt}/{max}` |
| | | `DEBUG` | `SM2: PENDING→PENDING \| seq={n} retries_left={r} timeout={t}s elapsed={e}s \| no response` |
| `PENDING → PENDING` | NAK timestamp_old, auto-heal | `WARNING` | `Horodatage refusé — correction automatique et renvoi` _(v1.1 only — not present in v1.0)_ |
| | | `DEBUG` | `SM2: PENDING→PENDING \| cause=nak_timestamp_old seq={n} old_ts={ts} new_ts={ts} \| NAK: raw={hex}` _(v1.1)_ |
| `PENDING → CONFIRMED` | ACK received | `INFO` | `Centrale confirmée — alarme {type} transmise (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→CONFIRMED \| seq={n} elapsed={t}ms \| ACK: crc_format={hex\|bin} raw={hex}` |
| `PENDING → FAILED` | Retries exhausted | `ERROR` | `Alarme {type} non transmise après {max} tentatives (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| seq={n} retries_exhausted={max} \| last attempt: no response elapsed={t}s` |
| `PENDING → FAILED` | NAK received | `ERROR` | `Réponse inattendue de la centrale — alarme {type} non transmise (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| seq={n} cause=nak_received \| NAK: raw={hex}` |
| `PENDING → FAILED` | SM1 → NO_NETWORK (event in queue, daemon stopping) | `ERROR` | `Alarme {type} non transmise — réseau inaccessible (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| cause=no_network \| event dropped, daemon stopping` |
| `CONFIRMED → IDLE` | Housekeeping | `DEBUG` | `SM2: CONFIRMED→IDLE` |
| `FAILED → IDLE` | After notification | `DEBUG` | `SM2: FAILED→IDLE` |

---

## Task 5b.4 — PHP-side logging policy

All PHP log messages use the standard Jeedom i18n wrapper:

```php
log::add(__CLASS__, 'info', __('Message en français', __FILE__));
```

Translation strings are registered in `core/i18n/{locale}.json` and picked up automatically
by Jeedom's community translation workflow.

The `message_center` callback type (`message::add()`) produces **no PHP log entry** —
the message center write is itself the trace.

| Event | Level | Message |
|---|---|---|
| Daemon start triggered | `info` | `Démarrage du daemon demandé` |
| Daemon stop triggered | `info` | `Arrêt du daemon demandé` |
| Daemon already running on start attempt | `warning` | `Tentative de démarrage alors que le daemon est déjà actif` |
| eqLogic save | `info` | `Configuration sauvegardée` |
| Callback received from daemon | `debug` | `Callback reçu: type={type}` |
| Unknown callback type | `warning` | `Callback de type inconnu: {type}` |
| `notify` callback — command not configured | `warning` | `Notification demandée mais aucune commande configurée` |
| `notify` callback — execCmd exception | `error` | `Impossible d'envoyer la notification: {msg}` |
| `error_update` — eqLogic not found | `warning` | `error_update reçu mais équipement introuvable` |
| Wizard step completed | `info` | `Assistant — étape {n} validée` |
| Connection test result | `info` | `Test de connexion: {succès|échec} — {detail}` |

---

## Task 5b.5 — Protocol inspector ring buffer

### Purpose

A bounded in-memory store of recent SIA protocol exchanges, pushed to PHP and persisted
as `last_messages` in equipment config. Read by Component 5c to render the protocol
inspector panel.

### Unit of storage: the dialog

The fundamental unit is a **dialog** — a complete request + response pair (or all retry
attempts for an alarm event). Individual send/receive events are not stored separately.

### Alarm event dialog structure

One entry per alarm event, regardless of retry count. All attempts are nested.

```python
{
    'dialog_type':  'alarm_event',
    'ts_local':     str,           # HH:MM:SS when first attempt sent
    'sm1_state':    str,           # SM1 state at start of first attempt
    'account':      str,
    'event_code':   str,           # 'BA' | 'FA' | 'PA'
    'zone':         str,
    'final_result': str,           # 'confirmed' | 'failed'
    'attempts': [
        {
            'attempt':     int,    # 1-based
            'seq':         int,
            'ts_sia':      str,    # timestamp embedded in SIA frame
            'ts_local':    str,    # wall-clock when this attempt was sent
            'raw_hex_req': str,    # sent frame as hex string
            'response': {
                'type':       str,           # 'ACK' | 'NAK' | 'timeout'
                'nak_raw':    str | None,    # hex string of raw NAK frame bytes; None on ACK/timeout
                'elapsed_ms': int,
                'raw_hex':    str | None,    # None on timeout
            },
        },
        # ... additional attempts if retried
    ],
}
```

### Supervision dialog structure

One entry per supervision cycle.

```python
{
    'dialog_type': 'supervision',
    'ts_local':    str,
    'sm1_state':   str,
    'routine':     bool,           # True = NULL→ACK with SM1=HEALTHY, no state change
    'request': {
        'seq':     int,
        'account': str,
        'ts_sia':  str,
        'raw_hex': str,
    },
    'response': {
        'type':       str,         # 'ACK' | 'NAK' | 'timeout'
        'nak_raw':    str | None,  # hex string of raw NAK frame bytes; None on ACK/timeout
        'elapsed_ms': int,
        'raw_hex':    str | None,
    },
}
```

### Ring buffer management

**Capacity:** 50 entries max.

**Routine supervision** (`routine=True`): only the latest is kept. When a new routine
supervision dialog is added, the previous routine entry is replaced in-place (not appended).
All routine cycles are still logged at DEBUG (5b.2) — only the ring buffer is deduplicated.

**Non-routine supervision** (timeout, NAK, state change → `routine=False`): always appended.

**Alarm event dialogs**: always appended.

**Push to PHP:** immediately on dialog completion (after response received or timeout),
via `send_to_jeedom({'type': 'message_trace', 'dialog': {...}})`.

### New PHP callback type: `message_trace`

```php
case 'message_trace':
    $messages = json_decode(config::byKey('last_messages', __CLASS__, '[]'), true) ?: [];
    $dialog   = $result['dialog'];

    if ($dialog['dialog_type'] === 'supervision' && $dialog['routine']) {
        // Replace existing routine entry, or prepend if none exists
        $idx = array_search(true, array_column($messages, 'routine'));
        if ($idx !== false) {
            $messages[$idx] = $dialog;
        } else {
            array_unshift($messages, $dialog);
        }
    } else {
        array_unshift($messages, $dialog);            // newest first
        $messages = array_slice($messages, 0, 50);    // enforce cap
    }

    // Stored at plugin level (config::save) — NOT on eqLogic — to avoid triggering
    // postSave() on every supervision cycle (1440×/day at default 60s interval).
    config::save('last_messages', json_encode($messages), __CLASS__);
    break;
```

---

## Task 5b.6 — Message externalization (`messages.py`)

All user-facing Python log strings (INFO/WARNING/ERROR level) are externalized to
`resources/siadc09d/messages.py`. Technical DEBUG lines stay inline in code — they are
developer-facing and not translated.

**Rationale:** Jeedom's `__()` i18n system is PHP-only and does not reach into daemon
output. Python logs are read in Jeedom's log panel as plain text. Externalizing to
`messages.py` makes all user-visible strings reviewable in one place and provides a
clean foundation if locale support is added in a future version (gettext loader swap).

**v1.0:** French-only. Gettext deferred.

```python
# resources/siadc09d/messages.py
# User-facing log message strings — INFO/WARNING/ERROR only.
# Technical DEBUG lines are NOT here; they stay inline in code.
# All strings are French (v1.0). Gettext deferred to future version.

# SM1 — lifecycle
SM1_STARTING              = "Démarrage — connexion à la centrale en cours"
SM1_CONNECTED             = "Connexion à la centrale établie"
SM1_RECOVERED             = "Supervision rétablie après {prev_strike} timeout(s)"
SM1_TCP_RECONNECTED       = "Connexion TCP rétablie — vérification supervision en cours"

# SM1 — degraded / warning
SM1_TIMEOUT_STARTUP       = "Timeout supervision au démarrage (strike 1/3) — nouvelle tentative"
SM1_TIMEOUT_WARNING       = "Timeout supervision (strike {strike}/3) — nouvelle tentative"
SM1_STILL_ABSENT          = "Supervision toujours absente — en attente de rétablissement"
SM1_TCP_DROP              = "Connexion TCP perdue — tentative de reconnexion (depuis état {prev_state})"

# SM1 — error
SM1_LOST                  = "Supervision perdue — 3 tentatives sans réponse (T3 notification envoyée)"
SM1_TCP_RECONNECT_FAIL_1  = "Reconnexion TCP échouée — centrale injoignable"
SM1_NO_NETWORK            = "Réseau injoignable après {n} tentatives — arrêt du daemon"

# SM2 — lifecycle
SM2_IDLE                  = "En attente d'événements alarme"
SM2_EVENT_RECEIVED        = "Alarme {type} reçue (zone: {zone}) — transmission en cours"
SM2_CONFIRMED             = "Centrale confirmée — alarme {type} transmise (zone: {zone})"

# SM2 — warning
SM2_RETRY                 = "Pas de réponse de la centrale — tentative {attempt}/{max}"
SM2_TIMESTAMP_HEAL        = "Horodatage refusé — correction automatique et renvoi"  # v1.1 — not used in v1.0

# SM2 — error
SM2_FAILED                = "Alarme {type} non transmise après {max} tentatives (zone: {zone})"
SM2_FAILED_NAK            = "Réponse inattendue de la centrale — alarme {type} non transmise (zone: {zone})"
SM2_FAILED_NO_NETWORK     = "Alarme {type} non transmise — réseau inaccessible (zone: {zone})"
```

**Usage in `siadc09d.py`:**

```python
from messages import SM1_LOST, SM2_CONFIRMED, ...

logging.warning(SM1_TIMEOUT_WARNING.format(strike=self._strike))
logging.error(SM1_LOST)
logging.info(SM2_CONFIRMED.format(type=event_type_fr(evt), zone=zone))
```

---

## Design decisions summary

| Decision | Choice | Rationale |
|---|---|---|
| Logger architecture | Single root logger (`logging.getLogger(__name__)`) | Sufficient for v1.0; consistent with jeedom-daemon-py pattern |
| Python CRITICAL level | Use `ERROR` instead | Jeedom log system has no CRITICAL display — both map to "error" |
| Log line pattern | Dual: INFO/WARNING/ERROR (human-friendly) + DEBUG (technical) | Users see clean messages; developers get full detail at debug level |
| Routine supervision in logs | DEBUG only — no INFO line | Prevents flooding at production log level (one NULL every 60s) |
| Technical DEBUG lines | Inline in code, not in `messages.py` | Developer-only traces — no i18n needed |
| User-facing strings | Externalized to `messages.py` | Single reviewable location; clean foundation for future gettext |
| i18n — Python | French-only for v1.0, gettext deferred | Jeedom `__()` system is PHP-only; Python logs are plain text in log panel |
| i18n — PHP | `__('msg', __FILE__)` on all log calls | Standard Jeedom approach; plugs into community translation workflow |
| PHP `message_center` callback | Silent (no PHP log entry) | Message center write is itself the trace |
| Ring buffer unit | Dialog (request + response) | Matches protocol structure; readable in debug panel |
| Alarm event retries | One dialog entry, attempts nested | Compact; one event = one row in 5c panel |
| Routine supervision in ring buffer | Latest one only (replaced, not appended) | Ring buffer stays useful; routine cycles don't push alarm entries out |
| Ring buffer capacity | 50 entries | Sufficient for debug session; bounded config key size |
| Ring buffer push | Immediate on dialog completion | Real-time protocol inspector |
| Privacy in ring buffer | Encryption key never stored; raw bytes OK | Raw bytes are ciphertext — unusable without key |

---

## New PHP callback types (Component 5b)

| Type | Storage | Description |
|---|---|---|
| `message_trace` | `last_messages` (JSON, max 50) | Protocol dialog for inspector panel (5c) |

> Combined with Component 5a's `message_center`, `notify`, `error_update` — four callback
> types total added across 5a and 5b.

---

## Module: `messages.py`

**Location:** `resources/siadc09d/messages.py`

**Dependencies:** None — pure string constants.

**Used by:** `siadc09d.py` (imports named constants, formats with `.format()`).

---

## Testing strategy for Component 5b

| Test | How |
|---|---|
| Dual log lines — INFO event | Send alarm, confirm ACK → verify INFO line present + DEBUG line with seq/raw_hex |
| Dual log lines — WARNING | Trigger supervision timeout strike=1 → verify WARNING + DEBUG with elapsed |
| No INFO for routine supervision | Run 3 supervision cycles (ACK) → verify no INFO lines, only DEBUG |
| ERROR at strike=3 | 3 supervision timeouts → verify ERROR logged once, not at strike=4 |
| T3 not repeated | 5 supervision timeouts → verify ERROR line appears at strike=3 only |
| TCP_RECONNECTING first failure | Drop TCP, reconnect fails once → verify ERROR logged once |
| TCP_RECONNECTING subsequent failures | Drop TCP, 3 failed attempts → verify ERROR at attempt=1, DEBUG at 2 and 3 |
| messages.py coverage | All INFO/WARNING/ERROR log calls in siadc09d.py reference a messages.py constant — no inline user-facing string |
| Ring buffer — routine supervision | 5 routine cycles → verify `last_messages` contains exactly 1 routine entry (latest) |
| Ring buffer — non-routine supervision | 1 timeout → verify appended to ring buffer, not replacing routine slot |
| Ring buffer — alarm event with retry | 2 timeouts then ACK → verify 1 dialog entry with 3 attempts nested |
| Ring buffer — cap | 55 non-routine entries → verify max 50 kept |
| Ring buffer — push timing | Verify `message_trace` callback sent immediately after dialog completion |
| PHP `__()` coverage | All PHP log strings use `__()` wrapper |
| PHP message_center silent | Trigger message_center callback → verify no PHP log entry produced |
