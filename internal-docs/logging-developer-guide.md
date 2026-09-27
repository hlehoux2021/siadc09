# Logging Developer Guide — SIA DC-09 Daemon

**Version:** 1.0  
**Date:** 2026-04-10  
**Reference:** internal-docs/design/logging-design.md

---

## Quick Start

Every daemon module uses the same logger setup:

```python
from resources.siadc09d.logging_config import _get_logger

logger = _get_logger(__name__)

# Use it
logger.info("Connexion établie")  # User-friendly French
logger.debug("SM1 INIT→HEALTHY | seq=001 | ACK received")  # Technical English
```

---

## Logging Levels

| Level | Jeedom Display | When to Use |
|-------|---|---|
| **DEBUG** | debug | Routine supervision cycles, raw hex frames, technical details, state machine internals |
| **INFO** | info | Significant operational events in user-friendly French |
| **WARNING** | warning | T1 auto-heal events, supervision timeouts (strike < 3), retry attempts |
| **ERROR** | error | T2 user-actionable (config errors), T3 infrastructure events (supervision lost, alarm failed) |

**Note:** Python `logging.CRITICAL` maps to ERROR in Jeedom (no CRITICAL display level).

---

## Dual-Line Logging Pattern

Every significant event produces **TWO** log entries:

### Example: Supervision ACK

```python
# User-friendly INFO line (French, significant event)
logger.info("Connexion à la centrale établie")

# Technical DEBUG line (English, full context)
logger.debug("SM1: INIT→HEALTHY | seq=001 strike=0 | ACK: crc_format=hex raw=0a303030...")
```

### Example: Timeout (Strike)

```python
# User-facing WARNING (French, actionable)
logger.warning("Timeout supervision (strike 1/3) — nouvelle tentative")

# Technical DEBUG (English, structured detail)
logger.debug("SM1: HEALTHY→DEGRADED | seq=012 strike=1 elapsed=45000ms | no response")
```

### Example: Alarm Event

```python
# User-facing INFO (French)
logger.info("Alarme intrusion reçue (zone: Salon) — transmission en cours")

# Technical DEBUG (English, structured)
logger.debug("SM2: IDLE→PENDING | event=BA zone=Salon seq=007 retries_left=3")
```

---

## Dual-Line Format Guide

### INFO/WARNING/ERROR (User-Facing)
- **Language:** French only (v1.0 target audience)
- **Audience:** End users, Jeedom admin panel
- **Content:** High-level operational status
- **Examples:**
  - "Connexion à la centrale établie"
  - "Timeout supervision (strike 2/3) — nouvelle tentative"
  - "Alarme incendie non transmise après 3 tentatives"

### DEBUG (Technical)
- **Language:** English, structured format
- **Audience:** Developers, support engineers, protocol debugging
- **Content:** Full context: state names, counters, elapsed time, frame data
- **Format:** `SM1: STATE→STATE | field=value field=value | frame info`
- **Examples:**
  ```
  SM1: INIT→HEALTHY | seq=001 strike=0 | ACK: crc_format=hex raw=0a...
  SM2: PENDING→CONFIRMED | seq=007 elapsed=234ms | ACK: crc_format=bin raw=0a...
  SM1: HEALTHY→DEGRADED | seq=012 strike=1 cause=timeout elapsed=45000ms
  ```

---

## Routine Supervision (No INFO Spam)

Routine supervision ACK cycles (SM1=HEALTHY, no state change) use **DEBUG only**:

```python
# ✅ CORRECT: No INFO line for routine ACK
logger.debug("[→ CSR] NULL | seq=001 | raw=0a0031...")
logger.debug("[← CSR] ACK | seq=001 elapsed=234ms | raw=0a...")
```

**Why?** At normal operation, supervision cycles every 60-120 seconds. Without this rule, INFO logs would flood: dozens of "Connexion supervié" messages daily.

---

## State Machine Logging

SM1 (Connection/Supervision) and SM2 (Alarm Events) log all transitions via helper methods:

### SM1 Transitions

| Transition | Level | French Message | DEBUG Detail |
|---|---|---|---|
| INIT→HEALTHY (first ACK) | INFO | "Connexion à la centrale établie" | `SM1: INIT→HEALTHY \| seq=001 strike=0 \| ACK...` |
| HEALTHY→DEGRADED (strike 1) | WARNING | "Timeout supervision (strike 1/3) — nouvelle tentative" | `SM1: HEALTHY→DEGRADED \| seq=012 strike=1 elapsed=45s` |
| DEGRADED→HEALTHY (recovery) | INFO | "Supervision rétablie après 2 timeout(s)" | `SM1: DEGRADED→HEALTHY \| prev_strike=2 \| ACK...` |
| TCP drop → TCP_RECONNECTING | WARNING | "Connexion TCP perdue — tentative de reconnexion" | `SM1: →TCP_RECONNECTING \| errno=104 csr=192.168.1.1:5000` |
| NO_NETWORK (terminal) | ERROR | "Réseau injoignable après 3 tentatives — arrêt du daemon" | `SM1: →NO_NETWORK \| total_attempts=3 csr=192.168.1.1:5000` |

### SM2 Transitions

| Transition | Level | French Message | DEBUG Detail |
|---|---|---|---|
| IDLE→PENDING (alarm rcvd) | INFO | "Alarme intrusion reçue (zone: Salon) — transmission en cours" | `SM2: IDLE→PENDING \| event=BA zone=Salon seq=007 retries_left=3` |
| PENDING→CONFIRMED (ACK) | INFO | "Centrale confirmée — alarme intrusion transmise (zone: Salon)" | `SM2: PENDING→CONFIRMED \| seq=007 elapsed=456ms \| ACK...` |
| PENDING→FAILED (retries exhausted) | ERROR | "Alarme incendie non transmise après 3 tentatives (zone: Kitchen)" | `SM2: PENDING→FAILED \| seq=008 retries_exhausted=3` |

---

## Privacy Rules for Logs

| Field | Rule | Example |
|---|---|---|
| **account_number** | Always shown | "Comptes: ABC123DEF456" in DEBUG |
| **encryption_key** | NEVER show | Don't log key bytes or even key length |
| **CSR IP:port** | Always shown | "csr=192.168.1.100:5000" in DEBUG |
| **Zone name** | Always shown | "zone=Living Room" in both INFO and DEBUG |
| **Raw ciphertext** | DEBUG only | Never in user-facing INFO/WARNING/ERROR |

**Example:**

```python
# ✅ GOOD: Account shown, key not shown
logger.debug("SM1: INIT→HEALTHY | acct=ABC123 | raw=0a0031...")

# ❌ BAD: Don't log key
logger.debug("SM1: INIT→HEALTHY | acct=ABC123 key=16bytes raw=0a...")

# ✅ GOOD: Zone shown in user message
logger.info("Alarme intrusion reçue (zone: Salon)")
```

---

## Using T3_PREFIX for Critical Errors

All T3 (critical) error messages MUST use the `T3_PREFIX` constant from messages.py:

```python
from resources.siadc09d.messages import T3_PREFIX

# ✅ CORRECT: Use constant
logger.error(T3_PREFIX + "Supervision perdue — 3 tentatives sans réponse")

# ❌ WRONG: Hardcoded string
logger.error("CRITIQUE — Supervision perdue...")

# ✅ ALSO CORRECT: Messages already include T3_PREFIX
from resources.siadc09d.messages import SM1_LOST
logger.error(SM1_LOST)  # Already starts with "CRITIQUE — "
```

---

## Module Imports

### Correct

```python
from resources.siadc09d.logging_config import _get_logger
from resources.siadc09d.messages import SM1_CONNECTED, T3_PREFIX

logger = _get_logger(__name__)

# Use messages constants
logger.info(SM1_CONNECTED)
logger.error(T3_PREFIX + "Supervision perdue")
```

### Avoid Circular Dependencies

The `logging_config.py` module imports ONLY:
- `logging` (Python standard library)
- `typing` (Python standard library)

Never import daemon modules from `logging_config.py`. The module is foundational and must not create circular imports.

---

## Testing Logging Code

Use pytest with `caplog` fixture to capture log output:

```python
def test_supervisor_logs_on_timeout(caplog):
    """Verify timeout produces dual-line log."""
    import logging
    # Replace with actual module under test:
    from resources.siadc09d.siadc09d import SiaDC09Daemon
    
    caplog.set_level(logging.DEBUG)
    
    # Trigger timeout scenario (example — adapt to actual daemon API)
    daemon = SiaDC09Daemon(config)
    daemon.handle_supervision_timeout()
    
    # Assert: INFO line present (French)
    assert "Timeout supervision (strike 1/3)" in caplog.text
    
    # Assert: DEBUG line present (English, technical)
    assert "SM1: HEALTHY→DEGRADED" in caplog.text
    assert "strike=1" in caplog.text
```

Never mock the logger directly. Use `caplog` to verify actual logging behavior.

---

## Framework Integration

The logging infrastructure is set up by **jeedom-daemon-py** framework:

```python
# Framework does this (daemon startup):
Utils.init_logger(__name__, log_level=logging.DEBUG)  # Sets root logger

# Your code just uses it:
logger = _get_logger(__name__)  # Gets logger from root config
logger.info("Message")  # Framework's handlers handle output
```

**Do NOT override root logger configuration in daemon code.** The framework owns:
- Root logger level (`--loglevel` CLI parameter)
- Handlers (console, file, etc.)
- Formatters (timestamp, module name, etc.)

Your code just creates child loggers and logs messages.

---

## Common Mistakes

### ❌ Don't: Hardcode French in other modules

```python
# WRONG: French strings scattered in code
logger.warning("Timeout supervision — nouvelle tentative")
```

### ✅ Do: Use messages.py constants

```python
from resources.siadc09d.messages import SM1_TIMEOUT_WARNING
logger.warning(SM1_TIMEOUT_WARNING.format(strike=2))
```

---

### ❌ Don't: Create multiple DEBUG/INFO lines

```python
logger.debug("Strike = 1")
logger.debug("State = DEGRADED")
logger.debug("Elapsed = 45000ms")
```

### ✅ Do: Structured single DEBUG line

```python
logger.debug("SM1: HEALTHY→DEGRADED | strike=1 elapsed=45000ms")
```

---

### ❌ Don't: Log encryption keys

```python
logger.debug(f"Encrypting with key={self.encryption_key}")
```

### ✅ Do: Log only that encryption happened

```python
logger.debug("Frame encrypted with 128-bit key")
```

---

## Reference

- **Logging Design:** internal-docs/design/logging-design.md (Tasks 5b.1–5b.3)
- **Error Handler:** internal-docs/design/error-handler-design.md (T1/T2/T3 classification)
- **Messages:** resources/siadc09d/messages.py (All user-facing strings)
- **State Machines:** daemon-design.md (SM1 and SM2 logging tables)

---

## Questions?

If logging patterns aren't clear:
1. Check logging-design.md for architecture decisions
2. Review messages.py for user-facing string patterns
3. Look at existing daemon code for examples
4. Refer to SM1/SM2 logging tables in daemon-design.md
