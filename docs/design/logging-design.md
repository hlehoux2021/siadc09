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
DEBUG:   SM1: HEALTHY→DEGRADED | seq=012 strike=1 elapsed=45000ms | no response
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
[← CSR] timeout | seq={n} elapsed={t}ms
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
| | | `DEBUG` | `SM1: INIT→DEGRADED \| seq={n} strike=1 elapsed={t}ms \| no response` |
| `HEALTHY → DEGRADED` | Timeout (strike=1) | `WARNING` | `Timeout supervision (strike 1/3) — nouvelle tentative` |
| | | `DEBUG` | `SM1: HEALTHY→DEGRADED \| seq={n} strike=1 elapsed={t}ms \| no response` |
| `HEALTHY → DEGRADED` | Parseable NAK (strike=1) | `WARNING` | `NAK supervision (strike 1/3) — horodatage rejeté par la centrale` |
| | | `DEBUG` | `SM1: HEALTHY→DEGRADED \| seq={n} strike=1 cause=nak_timestamp \| NAK: raw={hex}` |
| `DEGRADED → DEGRADED` | Timeout (strike=2) | `WARNING` | `Timeout supervision (strike 2/3) — nouvelle tentative` |
| | | `DEBUG` | `SM1: DEGRADED→DEGRADED \| seq={n} strike=2 elapsed={t}ms \| no response` |
| `DEGRADED → DEGRADED` | Parseable NAK (strike=2) | `WARNING` | `NAK supervision (strike 2/3) — horodatage rejeté par la centrale` |
| | | `DEBUG` | `SM1: DEGRADED→DEGRADED \| seq={n} strike=2 cause=nak_timestamp \| NAK: raw={hex}` |
| `DEGRADED → DEGRADED` | Timeout (strike=3, T3 fires) | `ERROR` | `Supervision perdue — 3 tentatives sans réponse (T3 notification envoyée)` |
| | | `DEBUG` | `SM1: DEGRADED→DEGRADED \| seq={n} strike=3 elapsed={t}ms \| no response \| T3 fired` |
| `DEGRADED → DEGRADED` | Timeout (strike already 3, subsequent) | `WARNING` | `Supervision toujours absente — en attente de rétablissement` |
| | | `DEBUG` | `SM1: DEGRADED(3) \| seq={n} elapsed={t}ms \| no response \| T3 already fired` |
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
| | | `DEBUG` | `SM2: PENDING→PENDING \| seq={n} retries_left={r} elapsed={e}ms \| no response` |
| `PENDING → PENDING` | NAK timestamp_old, auto-heal | `WARNING` | `Horodatage refusé — correction automatique et renvoi` _(v1.1 only — not present in v1.0)_ |
| | | `DEBUG` | `SM2: PENDING→PENDING \| cause=nak_timestamp_old seq={n} old_ts={ts} new_ts={ts} \| NAK: raw={hex}` _(v1.1)_ |
| `PENDING → CONFIRMED` | ACK received | `INFO` | `Centrale confirmée — alarme {type} transmise (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→CONFIRMED \| seq={n} elapsed={t}ms \| ACK: crc_format={hex\|bin} raw={hex}` |
| `PENDING → FAILED` | Retries exhausted | `ERROR` | `Alarme {type} non transmise après {max} tentatives (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| seq={n} retries_exhausted={max} \| last attempt: no response elapsed={t}ms` |
| `PENDING → FAILED` | NAK received | `ERROR` | `Réponse inattendue de la centrale — alarme {type} non transmise (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| seq={n} cause=nak_received \| NAK: raw={hex}` |
| `PENDING → FAILED` | SM1 → NO_NETWORK (event in queue, daemon stopping) | `ERROR` | `Alarme {type} non transmise — réseau inaccessible (zone: {zone})` |
| | | `DEBUG` | `SM2: PENDING→FAILED \| cause=no_network \| event dropped, daemon stopping` |
| `CONFIRMED → PENDING` | Next event dequeued | _(same as `IDLE → PENDING`)_ | See 'received' trigger in helper below |
| `FAILED → PENDING` | Next event dequeued | _(same as `IDLE → PENDING`)_ | See 'received' trigger in helper below |

> **Note:** `IDLE` is a startup-only state. After the first alarm event completes
> (CONFIRMED or FAILED), the consumer dequeues the next event directly into PENDING —
> no intermediate IDLE. There is no "back to IDLE" log line in normal operation.

---

### Logging helper methods

**Architectural rule:** All INFO/WARNING/ERROR log lines for SM1 supervision events and
SM2 alarm events are emitted exclusively through `_log_sm1_supervision()` and
`_log_sm2_event()`. Component 4 (supervision) code only constructs context objects and
calls these helpers — it does **not** call `self._logger` directly for state-machine events.
Technical DEBUG lines (raw frames, timing details) are also emitted inside the helpers.

#### Context dataclasses

```python
# resources/siadc09d/siadc09d.py

from dataclasses import dataclass, field
from typing import Literal

# --- SM1 trigger type ---
SM1Trigger = Literal['ack', 'timeout', 'nak_timestamp', 'nak_bad']

# --- SM2 trigger type ---
SM2Trigger = Literal['idle', 'received', 'retry', 'confirmed',
                     'failed_timeout', 'failed_nak', 'failed_no_network']

# --- SM1 logging contexts ---

@dataclass
class SM1AckCtx:
    seq:         int
    elapsed_ms:  int
    crc_format:  str
    raw_hex:     str
    prev_strike: int   # 0 = was already HEALTHY (routine); >0 = DEGRADED→HEALTHY recovery

@dataclass
class SM1TimeoutCtx:
    seq:           int
    elapsed_ms:    int
    strike:        int       # current strike after increment (already capped at 3)
    prev_state:    SM1State  # INITIALIZING | HEALTHY | DEGRADED — drives message choice
    t3_just_fired: bool      # True = first time strike reaches 3 this session

@dataclass
class SM1NakCtx:
    seq:           int
    elapsed_ms:    int
    strike:        int
    raw_hex:       str
    csr_time:      str | None  # ISO string if NAK timestamp was parseable; None = undecodable
    t3_just_fired: bool = False

SM1LogCtx = SM1AckCtx | SM1TimeoutCtx | SM1NakCtx

# --- SM2 logging contexts ---

@dataclass
class SM2LogCtx:
    event_type:    str          # 'burglarAlarm' | 'fireAlarm' | 'panicAlarm'
    zone:          str
    seq:           int
    attempt:       int   = 1
    max_attempts:  int   = 5
    retries_left:  int   = -1  # sentinel; caller must set for 'received', 'retry', and 'failed_*' triggers
    elapsed_ms:    int   = 0
    raw_hex:       str   = ''
    crc_format:    str   = ''
```

#### `_log_sm1_supervision(trigger, ctx)`

```python
def _log_sm1_supervision(self, trigger: SM1Trigger, ctx: SM1LogCtx) -> None:
    """Emit the dual-line log (INFO/WARNING/ERROR + DEBUG) for SM1 supervision events.

    trigger values:
      'ack'           — ACK received
      'timeout'       — no response within deadline
      'nak_timestamp' — parseable NAK (standard timestamp validation failure)
      'nak_bad'       — undecodable NAK (protocol anomaly → T2 BAD_CSR_RESPONSE)

    Owns all SM1 supervision log lines — supervision code must not call self._logger
    directly for these events.
    """
    if trigger == 'ack':
        if ctx.prev_strike == 0:
            # Routine healthy cycle — DEBUG only to prevent log flood
            self._logger.debug(
                f'[← CSR] ACK | seq={ctx.seq:04d} crc_format={ctx.crc_format} '
                f'elapsed={ctx.elapsed_ms}ms | raw={ctx.raw_hex}'
            )
        else:
            self._logger.info(SM1_RECOVERED.format(prev_strike=ctx.prev_strike))
            self._logger.debug(
                f'SM1: DEGRADED→HEALTHY | seq={ctx.seq:04d} prev_strike={ctx.prev_strike} '
                f'strike=0 | ACK: crc_format={ctx.crc_format} raw={ctx.raw_hex}'
            )

    elif trigger == 'timeout':
        if ctx.t3_just_fired:
            self._logger.error(SM1_LOST)
            self._logger.debug(
                f'SM1: DEGRADED→DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
                f'elapsed={ctx.elapsed_ms}ms | no response | T3 fired'
            )
        elif ctx.strike >= 3:
            # T3 already fired in a previous cycle — warn without re-firing
            self._logger.warning(SM1_STILL_ABSENT)
            self._logger.debug(
                f'SM1: DEGRADED(3) | seq={ctx.seq:04d} elapsed={ctx.elapsed_ms}ms '
                f'| no response | T3 already fired'
            )
        elif ctx.prev_state == SM1State.INITIALIZING:
            self._logger.warning(SM1_TIMEOUT_STARTUP)
            self._logger.debug(
                f'SM1: INIT→DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
                f'elapsed={ctx.elapsed_ms}ms | no response'
            )
        else:
            self._logger.warning(SM1_TIMEOUT_WARNING.format(strike=ctx.strike))
            prev = 'HEALTHY' if ctx.prev_state == SM1State.HEALTHY else 'DEGRADED'
            self._logger.debug(
                f'SM1: {prev}→DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
                f'elapsed={ctx.elapsed_ms}ms | no response'
            )

    elif trigger == 'nak_timestamp':
        if ctx.t3_just_fired:
            self._logger.error(SM1_LOST)
            self._logger.debug(
                f'SM1: DEGRADED→DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
                f'cause=nak_timestamp csr_time={ctx.csr_time} | NAK: raw={ctx.raw_hex} | T3 fired'
            )
        elif ctx.strike >= 3:
            # T3 already fired in a previous cycle — warn without re-stating strike
            self._logger.warning(SM1_STILL_ABSENT)
            self._logger.debug(
                f'SM1: DEGRADED(3) | seq={ctx.seq:04d} elapsed={ctx.elapsed_ms}ms '
                f'cause=nak_timestamp csr_time={ctx.csr_time} | NAK: raw={ctx.raw_hex} | T3 already fired'
            )
        else:
            self._logger.warning(SM1_NAK_TIMESTAMP.format(strike=ctx.strike))
            prev = 'HEALTHY' if ctx.strike == 1 else 'DEGRADED'
            self._logger.debug(
                f'SM1: {prev}→DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
                f'cause=nak_timestamp csr_time={ctx.csr_time} | NAK: raw={ctx.raw_hex}'
            )

    elif trigger == 'nak_bad':
        # T2 event — use ERROR (user-actionable: possible CSR firmware bug)
        self._logger.error(SM1_NAK_BAD.format(strike=ctx.strike))
        self._logger.debug(
            f'SM1: →DEGRADED | seq={ctx.seq:04d} strike={ctx.strike} '
            f'cause=nak_undecodable | NAK: raw={ctx.raw_hex}'
        )
```

#### `_log_sm2_event(trigger, ctx)`

```python
def _log_sm2_event(self, trigger: SM2Trigger, ctx: SM2LogCtx) -> None:
    """Emit the dual-line log for SM2 alarm event transitions.

    trigger values:
      'idle'              — daemon start, no events in queue
      'received'          — alarm event dequeued (from any state: IDLE, CONFIRMED, FAILED)
      'retry'             — timeout on current attempt, retrying
      'confirmed'         — ACK received
      'failed_timeout'    — retries exhausted
      'failed_nak'        — unexpected NAK from CSR
      'failed_no_network' — SM1 → NO_NETWORK while event in flight
    """
    fr  = error_handler.event_type_fr(ctx.event_type)  # canonical French label from error_handler.py

    if trigger == 'idle':
        self._logger.info(SM2_IDLE)
        self._logger.debug('SM2: →IDLE | queue=empty')

    elif trigger == 'received':
        sia = _EVENT_SIA_CODES[ctx.event_type]          # SIA protocol code — see daemon-design.md Task 1.1
        self._logger.info(SM2_EVENT_RECEIVED.format(type=fr, zone=ctx.zone))
        self._logger.debug(
            f'SM2: →PENDING | event={sia} zone={ctx.zone} seq={ctx.seq:04d} '
            f'retries_left={ctx.retries_left}'
        )

    elif trigger == 'retry':
        self._logger.warning(SM2_RETRY.format(attempt=ctx.attempt, max=ctx.max_attempts))
        self._logger.debug(
            f'SM2: PENDING→PENDING | seq={ctx.seq:04d} retries_left={ctx.retries_left} '
            f'elapsed={ctx.elapsed_ms}ms | no response'
        )

    elif trigger == 'confirmed':
        self._logger.info(SM2_CONFIRMED.format(type=fr, zone=ctx.zone))
        self._logger.debug(
            f'SM2: PENDING→CONFIRMED | seq={ctx.seq:04d} elapsed={ctx.elapsed_ms}ms '
            f'| ACK: crc_format={ctx.crc_format} raw={ctx.raw_hex}'
        )

    elif trigger == 'failed_timeout':
        self._logger.error(SM2_FAILED.format(type=fr, max=ctx.max_attempts, zone=ctx.zone))
        self._logger.debug(
            f'SM2: PENDING→FAILED | seq={ctx.seq:04d} retries_exhausted={ctx.max_attempts} '
            f'| last attempt: no response elapsed={ctx.elapsed_ms}ms'
        )

    elif trigger == 'failed_nak':
        self._logger.error(SM2_FAILED_NAK.format(type=fr, zone=ctx.zone))
        self._logger.debug(
            f'SM2: PENDING→FAILED | seq={ctx.seq:04d} cause=nak_received | NAK: raw={ctx.raw_hex}'
        )

    elif trigger == 'failed_no_network':
        self._logger.error(SM2_FAILED_NO_NETWORK.format(type=fr, zone=ctx.zone))
        self._logger.debug(
            f'SM2: PENDING→FAILED | seq={ctx.seq:04d} cause=no_network '
            f'| event dropped, daemon stopping'
        )
```

> **`_EVENT_SIA_CODES`:** Module-level dict constant defined in `siadc09d.py` (daemon-design.md Task 1.1).
> French label mapping (`intrusion`, `incendie`, `panique`) is provided by
> `error_handler.event_type_fr()` — separate concern, separate owner.

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

**Push to PHP:** on dialog completion (after response received or timeout),
via `send_to_jeedom({'type': 'message_trace', 'dialog': {...}})`.

**Routine supervision push throttle:** routine dialogs (`routine=True`) are pushed to PHP
at most once every **600 seconds (10 minutes)**, not on every cycle.

> **Rationale:** Every `message_trace` push triggers a `config::save('last_messages', ...)`
> DB write (read-modify-write of a 5–15 KB JSON blob). At the default `supervision_interval=60s`,
> pushing every routine ACK produces **1,440 DB writes/day** — significant I/O on
> Raspberry Pi or NAS SD cards, and a source of DB lock contention on busy Jeedom instances.
>
> Skipping routine pushes entirely was considered but rejected: the debug inspector would
> show an empty list during healthy operation (no routine entry visible), making it appear
> the daemon is idle — a confusing UX regression for a diagnostic tool.
>
> Throttling to 10-minute intervals keeps the inspector useful (the routine entry shows
> "last healthy supervision ≤10 min ago"), while reducing routine DB writes from
> 1,440/day to ~144/day (10× reduction). Non-routine events (timeout, NAK, alarm) are
> always pushed immediately — no throttle.

**Daemon implementation:** `SIADaemon` tracks `_last_routine_trace_ts: float` (epoch,
init `0.0` in `on_start()`). Before pushing a routine dialog:
```python
if dialog['routine']:
    now = time.monotonic()
    if now - self._last_routine_trace_ts < 600:
        return   # throttled — skip this push
    self._last_routine_trace_ts = now
await self.send_to_jeedom({'type': 'message_trace', 'dialog': dialog})
```
Non-routine dialogs bypass the throttle entirely.

### New PHP callback type: `message_trace`

```php
case 'message_trace':
    $messages = json_decode(config::byKey('sia_last_messages', __CLASS__, '[]'), true) ?: [];
    $dialog   = $result['dialog'];

    if ($dialog['dialog_type'] === 'supervision' && $dialog['routine']) {
        // Replace existing routine entry, or prepend if none exists.
        // Routine dialogs are throttled to one push per 10 min by the daemon —
        // this branch fires at most ~144 times/day (not 1440).
        $idx = array_search(true, array_column($messages, 'routine'));
        if ($idx !== false) {
            $messages[$idx] = $dialog;
        } else {
            array_unshift($messages, $dialog);
            $messages = array_slice($messages, 0, 50);    // enforce cap on first-ever routine entry
        }
    } else {
        array_unshift($messages, $dialog);            // newest first
        $messages = array_slice($messages, 0, 50);    // enforce cap
    }

    // Stored at plugin level (config::save) — NOT on eqLogic — to avoid triggering
    // postSave() on every write.
    config::save('sia_last_messages', json_encode($messages), __CLASS__);
    break;
```

### `make_message_entry()` factory

**Canonical construction path** for message buffer entries — defined in daemon module:

```python
def make_message_entry(type: str, timestamp: str, sia_code: str, zone: str | None, attempt: int | None, result: str) -> dict:
    """Factory for last_messages entries. All 6 fields mandatory."""
    return {
        "type":      type,              # "alarm" | "supervision"
        "timestamp": timestamp,         # ISO 8601, timezone-aware
        "sia_code":  sia_code,          # event code string
        "zone":      zone,              # alarm only; None for supervision
        "attempt":   attempt,           # alarm only; None for supervision
        "result":    result,            # "ack" | "nak" | "timeout"
    }
```

All 6 fields mandatory. Use `None` for absent optional fields — do not omit keys. `sia_last_messages` stores max 50 entries, newest first.

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
# TODO v1.1: replace with gettext loader
from typing import Final

T3_PREFIX: Final[str] = "CRITIQUE — "
# Level 1 test: assert every T3 message starts with T3_PREFIX.

SIA_NULL_CODE: Final[str] = "NULL"
# Used for supervision NULL frames only. NOT in _EVENT_SIA_CODES.
# Level 1 test: assert SIA_NULL_CODE not in _EVENT_SIA_CODES.

# --- SM1 transitions ---
SM1_STARTING              = "Démarrage — connexion à la centrale en cours"
SM1_CONNECTED             = "Connexion à la centrale établie"
SM1_RECOVERED             = "Supervision rétablie après {prev_strike} timeout(s)"
SM1_TCP_RECONNECTED       = "Connexion TCP rétablie — vérification supervision en cours"
SM1_TIMEOUT_STARTUP       = "Timeout supervision au démarrage (strike 1/3) — nouvelle tentative"
SM1_TIMEOUT_WARNING       = "Timeout supervision (strike {strike}/3) — nouvelle tentative"
SM1_STILL_ABSENT          = "Supervision toujours absente — en attente de rétablissement"
SM1_TCP_DROP              = "Connexion TCP perdue — tentative de reconnexion (depuis état {prev_state})"
SM1_NAK_TIMESTAMP         = "NAK supervision (strike {strike}/3) — horodatage rejeté par la centrale"
SM1_NAK_BAD               = "Réponse invalide de la centrale — NAK non décodable (strike {strike}/3)"
SM1_LOST                  = "Supervision perdue — 3 tentatives sans réponse (T3 notification envoyée)"
SM1_TCP_RECONNECT_FAIL_1  = "Reconnexion TCP échouée — centrale injoignable"
SM1_NO_NETWORK            = "Réseau injoignable après {n} tentatives — arrêt du daemon"

# --- SM2 transitions ---
SM2_IDLE                  = "En attente d'événements alarme"
SM2_EVENT_RECEIVED        = "Alarme {type} reçue (zone: {zone}) — transmission en cours"
SM2_CONFIRMED             = "Centrale confirmée — alarme {type} transmise (zone: {zone})"
SM2_RETRY                 = "Pas de réponse de la centrale — tentative {attempt}/{max}"
SM2_TIMESTAMP_HEAL        = "Horodatage refusé — correction automatique et renvoi"  # v1.1 — not used in v1.0
SM2_FAILED                = "Alarme {type} non transmise après {max} tentatives (zone: {zone})"
SM2_FAILED_NAK            = "Réponse inattendue de la centrale — alarme {type} non transmise (zone: {zone})"
SM2_FAILED_NO_NETWORK     = "Alarme {type} non transmise — réseau inaccessible (zone: {zone})"

# --- Error notifications (T1 / T2 / T3) ---
# T3 messages must prepend T3_PREFIX — enforced by Level 1 test.
# (Notification message templates are constructed in error_handler.py using these constants.)

# --- Preset validation ---
# Human-readable French error messages for missing/invalid preset fields.

# --- Wizard UI ---
# UI-facing strings for wizard steps (French only, v1.0).
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
| `message_trace` | `sia_last_messages` (JSON, max 50) | Protocol dialog for inspector panel (5c) |

> Combined with Component 5a's `message_center`, `notify`, `error_update` — four callback
> types total added across 5a and 5b.

---

## Module: `messages.py`

**Location:** `resources/siadc09d/messages.py`

**Dependencies:** `typing.Final` only (stdlib). **Zero other imports** — `messages.py` is always
the first module in the creation/import chain; no circular dependency risk.
Level 1 test: `assert messages.py` has no imports other than `typing.Final`.

**Used by:** `siadc09d.py` (imports named constants, formats with `.format()`).

**`T3_PREFIX` constant:**
```python
T3_PREFIX: Final[str] = "CRITIQUE — "
```
All T3-tier notification messages prepend this constant (not the raw string).
Level 1 test: assert every T3 message starts with `T3_PREFIX`.

**`SIA_NULL_CODE` constant:**
```python
SIA_NULL_CODE: Final[str] = "NULL"
```
Used for supervision NULL frames only. `SIA_NULL_CODE` is **not** in `_EVENT_SIA_CODES`.
Level 1 test: `assert SIA_NULL_CODE not in _EVENT_SIA_CODES`.

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
