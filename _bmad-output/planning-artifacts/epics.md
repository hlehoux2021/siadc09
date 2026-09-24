---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - '_bmad-output/planning-artifacts/prd.md'
  - '_bmad-output/planning-artifacts/architecture.md'
validationStatus: 'COMPLETE'
validationDate: '2026-04-07'
---

# my-project - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for my-project, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Protocol Message Builder — SIA DC-09-2021 compliant message construction with proper framing
FR2: AES-128 CBC Encryption/Decryption — Secure encryption and decryption of CSR communications
FR3: ACK/NAK Parser — Parse and interpret CSR responses and handle acknowledgments/negative acknowledgments
FR4: UDP Transport — Datagram-based communication with CSR for firewall-friendly deployment
FR5: TCP Transport — Stream-based communication with CSR and automatic reconnection on failure
FR6: SM1 State Machine — Manage connection/supervision states (INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING → NO_NETWORK)
FR7: SM2 State Machine — Manage alarm event states (IDLE → PENDING → CONFIRMED/FAILED)
FR8: Burglar Alarm Event — Send burglar alarm events to CSR with proper SIA encoding
FR9: Fire Alarm Event — Send fire alarm events to CSR with proper SIA encoding
FR10: Panic Alarm Event — Send panic alarm events to CSR with proper SIA encoding
FR11: IMA Protect CSR Preset — Configure single CSR endpoint for v1.0 without failover
FR12: 4-Step Configuration Wizard — Zero-jargon domain-language setup in French (preset selection, connection test, zone mapping, notifications)
FR13: Zone Mapping Table — Map zone names to optional camera actions and optional media URLs
FR14: Supervision Health Widget — Display connection state on Jeedom dashboard and mobile
FR15: 3-Tier Error Handler — Auto-heal notifications (T1), user-actionable notifications (T2), critical infrastructure notifications (T3)

### NonFunctional Requirements

NFR1: Zero Silent Failures — Every undelivered alarm must trigger a critical notification within the ACK timeout window
NFR2: Supervision State Lag ≤ 1 Interval — INFO commands updated immediately after state transitions
NFR3: Non-Technical Usability — Configuration wizard uses domain language only; no protocol jargon exposed
NFR4: Full SIA DC-09-2021 Compliance — Encryption, timestamp handling, supervision NULL keep-alive, ACK/NAK dialog
NFR5: Python 3.10+ / Debian 12+ Platform Floor — Declared in info.json; no legacy compatibility required
NFR6: Encryption Key Security — Key scrubbed from PHP scope after exec(); debug UI shows length-only
NFR7: CSR Extensibility — JSON preset architecture allows community-contributed CSR support without modifying core
NFR8: Clean Installation — Jeedom dependency manager handles all setup; no manual steps required

### Additional Requirements

- **Starter Template**: Jeedom Plugin Template (`/Users/herve.lehoux/Dev/plugin-template`)
- **Daemon Framework**: `jeedomdaemon` pip package (asyncio base class)
- **PHP/Python IPC**: JSON callback protocol for daemon → PHP state updates
- **SM1 ↔ SM2 Coordination**: SM1 triggers SM2 re-queue on TCP_RECONNECTING only
- **PriorityQueue Implementation**: 4-tuple tie-breaking with `itertools.count()`
- **Structured Logging**: French user-facing strings in `messages.py`, English debug inline
- **Async Task Lifecycle**: All tasks via `_track_task()` with done-callbacks
- **CRC Format**: Loaded from CSR preset at startup (no runtime detection)
- **TCP Connect Timeout**: 10-second fallback with `asyncio.wait_for()`
- **Ring Buffer Throttle**: Routine supervision writes throttled to 10-minute intervals
- **testConnection Isolation**: Standalone subprocess (`test_connection.py`), no daemon dependency
- **SM1 Strike Counter**: Single DEGRADED state with `_strike` (1–3, capped); reset on ACK or TCP reconnect
- **SM2 Startup Role**: IDLE entered once at init only; transitions CONFIRMED/FAILED → PENDING on next alarm
- **Info Commands**: `supervision_state`, `supervision_label`, `event_state`, `event_label` persist across restarts
- **Preset Architecture**: JSON files in `resources/siadc09d/presets/`; schema validation at startup

### FR Coverage Map

**FR1** (Message Builder) → Epic 1
**FR2** (AES-128) → Epic 1
**FR3** (ACK/NAK Parser) → Epic 1
**FR4** (UDP Transport) → Epic 2
**FR5** (TCP Transport) → Epic 2
**FR6** (SM1 State Machine) → Epic 2, 4
**FR7** (SM2 State Machine) → Epic 2
**FR8** (Burglar Alarm) → Epic 2
**FR9** (Fire Alarm) → Epic 2
**FR10** (Panic Alarm) → Epic 2
**FR11** (IMA Protect Preset) → Epic 5
**FR12** (4-Step Wizard) → Epic 5
**FR13** (Zone Mapping) → Epic 5
**FR14** (Widget) → Epic 9
**FR15** (3-Tier Error Handler) → Epic 6

## Epic List

### Epic 1: SIA DC-09 Protocol Engine
Build core protocol layer with AES-128 encryption, message construction, ACK/NAK parsing.
**Dependencies:** None
**FRs covered:** FR1, FR2, FR3
**Testing:** Unit tests (standalone, no daemon required)

### Epic 2: CSR Simulator (Standalone Tool)
Build a standalone CSR simulator that responds to SIA DC-09 protocol frames, usable for testing daemon implementations and other alarm systems without a real CSR.
**Note:** Internal Testing Infrastructure (not user-facing v1.0 feature); can be deferred if v1.0 uses mock responses
**Dependencies:** Story 1.1 (Message Builder) + Story 1.2 (AES-128 Encryption)
**Testing:** Unit tests for simulator ACK/NAK generation, encryption, UDP/TCP modes; hex frame replay; PCAP extraction

### Epic 3: Error Handler (Contract & Boilerplate)
Define error handling interfaces, ErrorCode enum, notification context types, and dispatcher contract that all daemon and PHP components depend on.
**Dependencies:** None (foundation)
**FRs covered:** FR15, NFR1 (zero silent failures)
**Testing:** Type/interface validation only

### Epic 4: Logging & Observability (Contract & Boilerplate)
Define logging infrastructure, French user-facing message strings, ring buffer structure, and log output format for consistent observability across all components.
**Dependencies:** None (foundation)
**FRs covered:** (cross-cutting infrastructure)
**Testing:** Message constants validation, logger setup

### Epic 5: Daemon Core & Dual State Machines
Build asyncio daemon with SM1 (connection/supervision) and SM2 (alarm events) state machines, PriorityQueue coordination, UDP/TCP transport, and async task lifecycle. Integration tests with CSR simulator.
**Dependencies:** Epic 1, Epic 3, Epic 4
**FRs covered:** FR4, FR5, FR6, FR7, FR8, FR9, FR10
**Testing:** State transition integration tests with csr_simulator (no PHP/supervision loop required)

### Epic 6: PHP Plugin Core & Jeedom IPC
Build PHP eqLogic/cmd classes, auto-equipment creation, JSON callback IPC protocol, and INFO command persistence.
**Dependencies:** Epic 1, 5, Epic 3, Epic 4
**FRs covered:** (infrastructure, enables others)
**Testing:** PHP/daemon callback integration tests

### Epic 7: Supervision Health Monitoring
Implement continuous supervision loop with 3-strike connection state, real-time INFO updates, and TCP stall detection.
**Dependencies:** Epic 5, 6, Epic 3, Epic 4
**FRs covered:** FR6 (supervision state persistence)
**Testing:** E2E supervision loop tests (strikes, ACK recovery, TCP reconnect)

### Epic 8: Configuration Wizard & CSR Presets
Build 4-step zero-jargon wizard for non-technical users to configure CSR connection, test it, map zones, and configure notifications.
**Dependencies:** Epic 1, 5, 6, 7, Epic 3, Epic 4
**FRs covered:** FR11, FR12, FR13
**Testing:** Wizard flow tests, connection test validation, zone mapping logic

### Epic 9: Debug UI & Diagnostics Panel
Implement diagnostic tab with status badge, error panel, protocol inspector (hex viewer, decryption, field breakdown), and manual refresh buttons.
**Dependencies:** Epic 1-8
**FRs covered:** (infrastructure for troubleshooting)
**Testing:** UI component tests, inspector decrypt validation

### Epic 10: Dashboard Widget
Build supervision health widget for dashboard and mobile with color-coded state, staleness detection, and Bootstrap 3 styling.
**Dependencies:** Epic 7, 4
**FRs covered:** FR14
**Testing:** Widget rendering, staleness detection, responsive design

### Epic 11: End-to-End Testing & Market Preparation
Full integration testing with real Ajax alarm system, CSR Simulator validation against real IMA Protect, documentation, and Jeedom Market submission.
**Dependencies:** Epic 1-10 (all features complete)
**FRs covered:** (all features)
**Testing:** Full end-to-end protocol conformance, integration with real CSR, Jeedom Market readiness

### Epic 12: Jeedom VM Integration Testing
Validate the complete plugin on a real Jeedom instance (Debian 12 VM) — installation, wizard, daemon lifecycle, supervision, alarm delivery, UI rendering, error handling, and Market packaging.
**Dependencies:** Epic 1-10 (all features complete)
**Infrastructure:** Debian 12 VM (VMware Fusion), CSR simulator on same VM, shared folder symlink
**FRs covered:** (validates all FRs on real infrastructure)
**Testing:** Real Jeedom UI, real daemon process, real alarm plugin, real notification commands

---

## Epic 1: SIA DC-09 Protocol Engine

Build core protocol layer with AES-128 encryption, message construction, ACK/NAK parsing.

### Story 1.1: SIA Protocol Message Builder

As a protocol developer,
I want to construct and serialize SIA DC-09 compliant message frames,
So that the daemon can send properly formatted frames to the CSR.

**Acceptance Criteria:**

**Given** a message payload (account number, event code, checksum data)
**When** building an alarm message frame
**Then** the output is a properly framed SIA message with correct delimiter, sequence, CRC, and checksum

**And** encryption-ready plaintext is generated when AES-128 encryption is specified

**And** the message adheres to SIA DC-09-2021 spec for burglary, fire, and panic events

**And** supervision NULL messages are constructable with zero payload

---

### Story 1.2: AES-128 CBC Encryption Module

As a security engineer,
I want to encrypt and decrypt SIA messages using AES-128 CBC,
So that communication with the CSR is secure.

**Acceptance Criteria:**

**Given** a plaintext SIA message and an encryption key
**When** encrypting
**Then** output is AES-128 CBC ciphertext with random IV prepended

**And** decryption of the ciphertext returns the original plaintext

**And** key length validation (128-bit) is enforced

**And** IV is generated fresh for each encryption

**And** padding follows PKCS#7 standard

---

### Story 1.3: ACK/NAK Response Parser

As a daemon developer,
I want to parse and validate CSR responses (ACK/NAK),
So that I can distinguish successful delivery from errors.

**Acceptance Criteria:**

**Given** a raw ACK or NAK response from the CSR
**When** parsing
**Then** the message type (ACK/NAK) is correctly identified

**And** for NAK: timestamp (if present) is extracted for clock drift detection

**And** validation confirms proper CRC and checksum

**And** malformed responses raise specific exceptions with diagnostic data

**And** parser handles both encrypted and plaintext ACK/NAK frames

---

## Epic 2: CSR Simulator (Standalone Tool)

**⚠️ SCOPE CLARIFICATION (2026-04-07):** This is **Internal Testing Infrastructure**, not a v1.0 user-facing epic. It provides developer and QA tools for protocol validation. Can be implemented in parallel with or after Epic 1 based on resource availability. Core v1.0 implementation (Epics 1, 5-10) can proceed with mock CSR responses if simulator is deferred.

Build a standalone CSR simulator that responds to SIA DC-09 protocol frames, usable for testing daemon implementations and other alarm systems without a real CSR.

**Dependencies:** Story 1.1 (Message Builder) + Story 1.2 (AES-128 Encryption)

**Scope Classification:** Developer/Testing Infrastructure (not user-facing v1.0 feature)

**Optionality:** Can be deferred to v1.1+ if v1.0 implementation uses mock responses instead

### Story 2.1: Simulator Framework & UDP/TCP Listen

As a tester/developer,
I want to run a local CSR simulator that accepts UDP/TCP connections,
So that I can test alarm system integrations without connecting to a real CSR.

**Acceptance Criteria:**

**Given** the simulator is started with configured UDP and TCP ports
**When** a frame arrives from a daemon or test tool
**Then** the simulator listens on both UDP and TCP simultaneously

**And** incoming frames are parsed using protocol engine (stories 1.1/1.2)

**And** encrypted frames are decrypted using AES-128 (story 1.2)

**And** frame structure and CRC are validated

**And** all received frames are logged with timestamp for debugging

---

### Story 2.2: Generate CSR Responses (ACK/NAK/NULL)

As a simulator operator,
I want the simulator to respond appropriately to incoming frames,
So that the daemon receives realistic CSR behavior.

**Acceptance Criteria:**

**Given** a valid alarm message (burglary, fire, panic)
**When** simulator receives it
**Then** simulator responds with ACK encoded properly

**And** for supervision NULL messages: responds with ACK

**And** for malformed frames: responds with NAK

**And** responses use correct SIA encoding with encryption if required by preset

**And** simulator supports configurable response delay to simulate network latency

**And** responses are logged with matching request for audit trail

---

### Story 2.3: CLI Tool for Hex Dump Frame Replay

As a developer/tester,
I want to replay SIA frames from a hex dump file against the simulator,
So that I can test protocol compliance with predefined frame sequences.

**Acceptance Criteria:**

**Given** a hex dump file with one frame per line (space/comma separated)
**When** running `./simulate-frames.py --input frames.hex --port 10001 --protocol udp`
**Then** each frame is sent to the simulator in sequence

**And** simulator response (ACK/NAK) is displayed with timing

**And** hex file supports comments (lines starting with #)

**And** tool works with both UDP and TCP modes

**And** example files are provided (e.g., `frames_ajax_burglary.hex`)

---

### Story 2.4: PCAP Frame Extractor Tool (Wireshark Dumps)

As a tester,
I want to extract SIA DC-09 frames from Wireshark pcap captures of real CSR traffic,
So that I can replay authentic protocol sequences for testing.

**Acceptance Criteria:**

**Given** a `.pcap` or `.pcapng` file from Wireshark sniffing real CSR traffic
**When** running `extract-frames-from-pcap.py capture.pcapng --output frames.hex`
**Then** output is a hex dump file compatible with Story 2.3

**And** frames are filtered by configured SIA UDP/TCP ports

**And** tool supports `--direction` flag (client→server, server→client, or both)

**And** timestamps are included in comments for reference

**And** example pcap files and extracted frames are provided

---

### Story 2.5: Test Harness & Standalone Documentation

As a maintainer/ecosystem user,
I want clear documentation and examples for using the simulator and tools standalone,
So that other alarm systems can adopt them for their own testing.

**Acceptance Criteria:**

**Given** a developer new to the simulator
**When** reading the README
**Then** setup, configuration, and CLI usage are clear with examples

**And** unit tests cover simulator ACK/NAK generation, encryption, UDP/TCP modes

**And** examples include "Testing against Ajax alarm panel with Wireshark captures"

**And** simulator and tools can be installed and run standalone (not Jeedom-dependent)

**And** example pcap files and extracted frame files are included

---

## Epic 3: Error Handler (Contract & Boilerplate)

Define error handling interfaces, ErrorCode enum, notification context types, and dispatcher contract that all daemon and PHP components depend on.

**Dependencies:** None (foundation)

### Story 3.1: ErrorCode Enum & Error Classification

As a daemon developer,
I want a centralized ErrorCode enum and tier classification,
So that error handling is consistent across all components.

**Acceptance Criteria:**

**Test Strategy Reference:** error-handler-design.md "ErrorCode Classification Table" + ADR-04 (zero silent failures, notification tiers)

**ErrorCode Enum Definition (ref: error-handler-design.md FINAL):**

```python
from enum import Enum, auto

class ErrorCode(Enum):
    SUPERVISION_TIMEOUT = auto()      # T1: timeout waiting for supervision ACK
    SUPERVISION_NAK = auto()            # T1: CSR responded with NAK to supervision NULL (timestamp invalid)
    BAD_CSR_RESPONSE = auto()           # T2: malformed/undecodable response from CSR
    SUPERVISION_DISCONNECTED = auto()   # T3: 3 missed supervision cycles, connection lost
    EVENT_FAILED = auto()               # T3: alarm delivery failed after retries
    TRANSPORT_PERMANENT = auto()        # T3: permanent transport failure (TCP permanent, UDP unreachable)
```

**Error Classification (ref: error-handler-design.md tier logic):**

| ErrorCode | Tier | Trigger | Action | Notification |
|-----------|------|---------|--------|--------------|
| SUPERVISION_TIMEOUT | T1 | Strike=1 on supervision NULL timeout | Auto-heal: wait for next ACK | Message center only, no command |
| SUPERVISION_NAK | T1 | CSR NAK on supervision NULL (invalid timestamp) | Auto-heal: daemon adjusts timestamp (v1.1), retry next cycle | Message center only |
| BAD_CSR_RESPONSE | T2 | Undecodable/malformed CSR response | User-actionable: check CSR config, network | Message center + notify command |
| SUPERVISION_DISCONNECTED | T3 | Strike=3 (3 consecutive missed ACKs) | Critical: manual intervention needed | Message center + notify command + "CRITIQUE —" prefix |
| EVENT_FAILED | T3 | Alarm delivery fails after max retries | Critical: alarm did not reach CSR | Message center + notify command + "CRITIQUE —" prefix |
| TRANSPORT_PERMANENT | T3 | TCP reconnect fails 3+ times, or UDP permanent error | Critical: daemon stops, Jeedom restarts it | Message center + notify command + "CRITIQUE —" prefix |

**Tier Definitions (ref: error-handler-design.md):**

- **T1 (Auto-heal)**: Expected transient errors, auto-recover; message center log only, deduped by Jeedom occurrence counter
- **T2 (User-actionable)**: Configuration/CSR issues requiring user action; message center + user-configured notification command; deduped by Jeedom
- **T3 (Critical)**: Infrastructure failures, zero silent failures; message center + notification + "CRITIQUE —" prefix; deduped by notification queue plugin

**Rationale for Each Code (ref: error-handler-design.md reasoning):**

1. **SUPERVISION_TIMEOUT** (T1): Normal during transient network hiccups, recovers on next ACK. No notification; user sees strike counter.
2. **SUPERVISION_NAK** (T1): CSR rejected timestamp (v1.0 static timestamps, v1.1 dynamic). Will auto-heal in v1.1; for now, log as debug.
3. **BAD_CSR_RESPONSE** (T2): Indicates CSR misconfiguration or protocol mismatch. User must check CSR IP/port/account number.
4. **SUPERVISION_DISCONNECTED** (T3): 3 missed cycles = definite connection loss. User must investigate network, firewall, CSR availability.
5. **EVENT_FAILED** (T3): Alarm did NOT reach CSR. Zero-silent-failures rule: user must be notified immediately.
6. **TRANSPORT_PERMANENT** (T3): TCP cannot reconnect or UDP permanently unreachable. Daemon terminates; Jeedom watchdog restarts.

**Helper Function: classify_error(code)**

```python
def classify_error(code: ErrorCode) -> Literal['T1', 'T2', 'T3']:
    """Return tier for error code."""
    tier_map = {
        ErrorCode.SUPERVISION_TIMEOUT: 'T1',
        ErrorCode.SUPERVISION_NAK: 'T1',
        ErrorCode.BAD_CSR_RESPONSE: 'T2',
        ErrorCode.SUPERVISION_DISCONNECTED: 'T3',
        ErrorCode.EVENT_FAILED: 'T3',
        ErrorCode.TRANSPORT_PERMANENT: 'T3',
    }
    return tier_map[code]
```

**Test Validation (ref: error-handler-design.md):**

Test Cases:
1. All 6 ErrorCode values defined ✓
2. Each code has a unique value (no collisions) ✓
3. Tier assignment matches table above ✓
4. classify_error() returns correct tier for each code ✓
5. All codes are used in daemon/error handler (grep for usage) ✓
6. No undefined error codes in daemon ✓
7. Tier definitions documented in module docstring ✓

**Usage Contract (ref: error-handler-design.md, ADR-04):**

- SM1 uses: SUPERVISION_TIMEOUT, SUPERVISION_NAK, SUPERVISION_DISCONNECTED, TRANSPORT_PERMANENT
- SM2 uses: EVENT_FAILED (alarm delivery failure)
- Transport uses: BAD_CSR_RESPONSE, TRANSPORT_PERMANENT
- All errors dispatched via `_notify(code, ctx)` (story 3.2)

---

### Story 3.2: Notification Context Types & _notify() Interface

As a daemon developer,
I want typed context objects for notifications,
So that error handling is type-safe and carries complete diagnostic data.

**Acceptance Criteria:**

**Given** the _notify() interface
**When** calling from SM1/SM2 code
**Then** the signature is: `_notify(code: ErrorCode, ctx: NotificationContext)`

**And** context types are defined as TypedDict/dataclass: EventFailedCtx, TransportPermanentCtx, SM1TimeoutCtx, SM1NakCtx

**And** each context includes required fields (elapsed_ms, zone, raw_response, etc.) with type hints

**And** context types are documented with examples for each error code

**And** type validation is enforced (no untyped contexts)

---

### Story 3.3: Error Handler Module Structure & Callback Types

As a plugin architect,
I want clear callback contracts between daemon and PHP,
So that error dispatch integration is unambiguous.

**Acceptance Criteria:**

**Given** the error_handler.py module in resources/siadc09d/
**When** daemon needs to notify PHP of an error
**Then** four callback types are defined with full signatures: `message_center`, `notify`, `error_update`, `message_trace`

**And** each callback payload format is documented (JSON schema)

**And** callback timing guarantees are documented (synchronous vs async dispatch)

**And** stub _dispatch_notify() exists with clear comments on T1/T2/T3 dispatch logic (full implementation deferred to Epic 6)

**And** module docstring documents the error handling architecture and integration points

---

## Epic 4: Logging & Observability (Contract & Boilerplate)

Define logging infrastructure, French user-facing message strings, ring buffer structure, and log output format for consistent observability across all components.

**Dependencies:** None (foundation)

### Story 4.1: messages.py Structure & French String Constants

As a daemon developer,
I want all French user strings in one place,
So that translations are centralized and maintenance is easy.

**Acceptance Criteria:**

**Given** messages.py module in resources/siadc09d/
**When** accessing user-facing strings
**Then** all French strings are defined as module-level constants: SM1 states, SM2 states, error messages, wizard prompts, etc.

**And** strings are organized by category with comments: `# SM1 States`, `# Error Messages`, `# Wizard Steps`

**And** each string includes a placeholder for v1.1 gettext migration (`# TODO v1.1: gettext`)

**And** example strings provided for all error codes and state transitions

**And** string format matches logging requirements (no protocol jargon)

**Test Strategy Reference:** logging-design.md "User-Facing String Externalization (ADR-15)" + logging-design.md SM1/SM2 logging tables

**Module Structure (ref: logging-design.md):**

File: `resources/siadc09d/messages.py`

```python
# SIA DC-09 Plugin - French User-Facing Messages
# v1.0: Static strings (French only)
# TODO v1.1: Migrate to gettext for multi-language support

# SM1 (Supervision) States
SM1_INITIALIZING = "Initialisation de la supervision..."
SM1_HEALTHY = "Sain"
SM1_DEGRADED_1 = "Supervision dégradée — tentative 1/3"
SM1_DEGRADED_2 = "Supervision dégradée — tentative 2/3"
SM1_DEGRADED_3 = "Supervision perdue — intervention requise"
SM1_TCP_RECONNECTING = "Reconnexion en cours..."
SM1_NO_NETWORK = "Surveillance perdue — redémarrage requis"
SM1_ESTABLISHED = "Connexion supervisée établie"
SM1_RECOVERED = "Connexion supervisée rétablie"

# SM2 (Alarm) States
SM2_IDLE = "Inactif"
SM2_PENDING = "En cours"
SM2_CONFIRMED = "Confirmé"
SM2_FAILED = "Échoué"
SM2_ALARM_DETECTED = "Alarme détectée: %s"  # %s = event type
SM2_ALARM_CONFIRMED = "Alarme confirmée par la centrale"
SM2_ALARM_REJECTED = "Alarme rejetée par la centrale"

# Error Messages (T1 - Auto-heal)
ERR_SUPERVISION_TIMEOUT_T1 = "Supervision momentanément indisponible — tentative de rétablissement"
ERR_SUPERVISION_NAK_T1 = "Horodatage invalide — synchronisation en cours"

# Error Messages (T2 - User-Actionable)
ERR_BAD_CSR_RESPONSE_T2 = "Réponse invalide du serveur — vérifiez la configuration CSR"

# Error Messages (T3 - Critical)
ERR_SUPERVISION_DISCONNECTED_T3 = "CRITIQUE — Surveillance perdue. Intervention immédiate requise"
ERR_EVENT_FAILED_T3 = "CRITIQUE — Alarme non confirmée par la centrale"
ERR_TRANSPORT_PERMANENT_T3 = "CRITIQUE — Perte de connexion permanente"

# Wizard & Configuration
WIZARD_STEP_1_TITLE = "Sélectionner la centrale (CSR)"
WIZARD_STEP_2_TITLE = "Tester la connexion"
WIZARD_STEP_3_TITLE = "Configurer les zones"
WIZARD_STEP_4_TITLE = "Configurer les notifications"
WIZARD_TEST_SUCCESS = "✓ Connexion établie"
WIZARD_TEST_FAILED = "✗ Connexion échouée: %s"
```

**String Coverage (ref: logging-design.md SM1/SM2 tables + error-handler-design.md):**

From logging tables: all state transitions must have messages ✓
From error codes (story 3.1): all T1/T2/T3 errors have messages ✓
From wizard (story 8): all steps have messages ✓

**Test Validation:**

1. All messages defined with correct French ✓
2. No French strings elsewhere in daemon (grep verify) ✓
3. All state transitions from logging tables have messages ✓
4. All error codes (story 3.1) have T1/T2/T3 messages ✓
5. `%s` placeholders for dynamic values ✓
6. Module docstring documents v1.1 migration ✓

---

### Story 4.2: Logging Infrastructure Setup & Logger Configuration

As a daemon developer,
I want consistent logging setup across all modules,
So that all components log with the same format and level.

**Acceptance Criteria:**

**Given** the logging infrastructure in resources/siadc09d/
**When** a module does `logger = logging.getLogger(__name__)`
**Then** logger is configured with correct handlers and formatters

**And** Python CRITICAL level is mapped to ERROR for Jeedom (Jeedom has no CRITICAL display level)

**And** dual-line log pattern is defined: `INFO/WARNING/ERROR` (French) + `DEBUG` (English)

**And** log format includes timestamp, level, module name, message

**And** helper function `_get_logger(name)` exists for consistent setup

**And** logging configuration is documented for new developers

---

### Story 4.3: Ring Buffer Structure & Log Entry Factory

As a daemon developer,
I want a ring buffer for supervision and alarm event history,
So that users can see recent activity and diagnose issues.

**Acceptance Criteria:**

**Given** the ring buffer structure
**When** logging a supervision ACK or alarm event
**Then** max 50 entries are stored (FIFO, oldest discarded)

**And** routine supervision NULLs are throttled: only one entry per 10-minute interval (not every ACK)

**And** state-changing events (strikes, transitions, failures) write immediately

**And** each entry format is: `{timestamp, level, message, context_dict}`

**And** factory function `make_message_entry(level, message, context)` creates properly formatted entries

**And** ring buffer persists to `last_messages` config key (JSON, max 50 entries)

**And** ring buffer behavior is documented with examples

---

## Epic 5: Daemon Core & Dual State Machines

Build asyncio daemon with SM1 (connection/supervision) and SM2 (alarm events) state machines, PriorityQueue coordination, UDP/TCP transport, and async task lifecycle. Integration tests with CSR simulator.

**Dependencies:** Epic 1 (protocol), Stories 1.1 & 1.2, Epic 3, Epic 4

### Story 5.1: SM1 Connection/Supervision State Machine

As a daemon architect,
I want SM1 to track connection and supervision health,
So that the daemon knows when the CSR is available and healthy.

**Acceptance Criteria:**

**Test Strategy Reference:** daemon-design.md "SM1 State Machine Pseudocode" + supervision-design.md "SM1 State Transition Table"

**State Machine (ref: daemon-design.md fig. SM1):**

States: INITIALIZING → HEALTHY → DEGRADED → [TCP_RECONNECTING] → [NO_NETWORK]

| State | Entry Condition | Exit Condition | Info Command (supervision_state) |
|-------|-----------------|----------------|----------------------------------|
| INITIALIZING | daemon on_start() | ACK received | 1 (impaired) |
| HEALTHY | ACK to first NULL or strike→0 on ACK | Timeout, strike=1 | 2 (healthy) |
| DEGRADED | Strike ≥1 | ACK received (reset), TCP reconnect success, or strike=3→NO_NETWORK | 1 or 0 (see below) |
| TCP_RECONNECTING | Strike=3 + TCP + socket force-close | Reconnect success or permanent failure | 1 (impaired) |
| NO_NETWORK | TCP permanent failure (3+ reconnect attempts) | (terminal) stop() called | 0 (problem) |

**Strike Counter Logic (ref: supervision-design.md ADR-11):**

- `_strike_counter: int` initialized to 0 in on_start()
- Each supervision timeout (NULL frame no ACK): increment by 1 (cap at 3)
- Each ACK received: reset to 0 AND reset `_sm1_t3_fired` flag to False
- TCP reconnect success (TCP_RECONNECTING → INITIALIZING): reset both to 0, False

**Notification Dispatch (ref: error-handler-design.md + supervision-design.md):**

| Strike | State | Action |
|--------|-------|--------|
| 0 | HEALTHY | No action |
| 1 | DEGRADED | `_notify(SUPERVISION_TIMEOUT, SM1TimeoutCtx{elapsed_ms, strike=1})` (T1 auto-heal) |
| 2 | DEGRADED | No new notification (already notified at strike=1) |
| 3 | DEGRADED | `_notify(SUPERVISION_DISCONNECTED, TransportPermanentCtx{...})` (T3 critical) — **only once** (tracked by `_sm1_t3_fired` flag) |
| ACK after strike>0 | HEALTHY | Strike resets, `_sm1_t3_fired` → False, no new notification |
| TCP strike=3 | TCP_RECONNECTING | Force socket close immediately |
| TCP reconnect fail | NO_NETWORK | `_notify(TRANSPORT_PERMANENT, ...)` (T3), call self.stop() |

**Logging Output (ref: logging-design.md SM1 Table):**

| Transition | INFO (French) | DEBUG (English) |
|------------|---------------|-----------------|
| INITIALIZING (first) | (none, startup) | "SM1 initialized, awaiting first supervision ACK" |
| → HEALTHY (ACK) | "Connexion supervisée établie" | "SM1 HEALTHY: ACK received to initial NULL" |
| → DEGRADED (strike 1) | "Supervision dégradée — tentative 1/3" | "SM1 DEGRADED(strike=1): timeout on supervision NULL, T1 fired" |
| → DEGRADED (strike 2) | "Supervision dégradée — tentative 2/3" | "SM1 DEGRADED(strike=2): 2nd consecutive timeout" |
| → DEGRADED (strike 3) | "Supervision perdue — intervention requise" | "SM1 DEGRADED(strike=3): T3 fired, daemon in critical state" |
| → HEALTHY (recovery) | "Connexion supervisée rétablie" | "SM1 HEALTHY: recovered from DEGRADED via ACK" |
| → TCP_RECONNECTING (TCP only) | "Reconnexion en cours..." | "SM1 TCP_RECONNECTING: forcing socket close, attempting reconnect" |
| → NO_NETWORK (TCP fail) | "Surveillance perdue — redémarrage requis" | "SM1 NO_NETWORK: permanent TCP failure, calling daemon.stop()" |

**Test Data & Fixtures (ref: daemon-design.md test scenarios):**

File: `test_data/sm1_state_transitions.yaml`

Test Cases (run with csr_simulator):
1. **Initial ACK**: daemon start → INITIALIZING → supervision NULL → CSR ACK → HEALTHY ✓
2. **Strike Escalation**: HEALTHY → timeout (strike=1) → DEGRADED → timeout (strike=2) → timeout (strike=3) → T3 ✓
3. **Strike Recovery**: DEGRADED(strike=2) → ACK → strike reset, T3 flag reset → HEALTHY ✓
4. **TCP Stall (strike=3)**: TCP + strike=3 → socket force-close → TCP_RECONNECTING ✓
5. **TCP Reconnect Success**: TCP_RECONNECTING + successful connect → INITIALIZING ✓
6. **TCP Permanent Failure**: TCP_RECONNECTING + 3 failed reconnect attempts → NO_NETWORK → daemon.stop() ✓
7. **UDP No Reconnect**: UDP + strike=3 → stays DEGRADED (no TCP_RECONNECTING, no NO_NETWORK) ✓

**Supervision Interval:** Configurable per equipment (default 30s for tests, typical 60-120s production). Use `supervision_interval` from preset config.

**Test Harness:** Use csr_simulator with `--response-delay N` to inject timeout scenarios. Measure strike escalation timing (should occur at supervision_interval × strike count).

---

### Story 5.2: SM2 Alarm Event State Machine

As a daemon architect,
I want SM2 to track alarm event delivery status,
So that the daemon and PHP know whether alarms reached the CSR.

**Acceptance Criteria:**

**Test Strategy Reference:** daemon-design.md "SM2 State Machine" (IDLE role, CONFIRMED/FAILED transitions) + error-handler-design.md "SM2 owns zero-silent-failures invariant"

**State Machine (ref: daemon-design.md fig. SM2, ADR-14):**

States: IDLE (startup-only) → PENDING → [CONFIRMED | FAILED] → PENDING → ...

| State | Entry Condition | Exit Condition | event_state | event_label (French) |
|-------|-----------------|----------------|-------------|----------------------|
| IDLE | daemon on_start() only | Alarm trigger | 0 | "Inactif" |
| PENDING | Alarm event (burglary/fire/panic) triggered | ACK or NAK received | 3 | "En cours" |
| CONFIRMED | CSR ACK received to alarm frame | Next alarm (→PENDING) | 1 | "Confirmé" |
| FAILED | CSR NAK received to alarm frame | Next alarm (→PENDING) | 2 | "Échoué" |

**Critical Rule (ADR-14 - IDLE is Startup-Only):**

- IDLE entered only once, at daemon initialization
- After IDLE, on any alarm: SM2 → PENDING
- On CONFIRMED or FAILED: do NOT transition back to IDLE
- On next alarm (whether after CONFIRMED or FAILED): directly → PENDING
- `event_state` never resets to 0 after daemon start (persists across restarts as "never alarm since start")

**Alarm Event Extraction (ref: daemon-design.md alarm payload):**

Alarm triggered by action command with zone name:
- Zone name comes from alarm plugin action `#zone#` tag (user-configured in alarm plugin)
- Payload sent to daemon: `{event_type: "burglar|fire|panic", zone: "zone_name"}`
- Daemon includes zone in SIA frame (if required by CSR format)

**Error Handling / Zero Silent Failures (ref: error-handler-design.md ADR-04):**

| Scenario | Action | Notification |
|----------|--------|---------------|
| Alarm triggered, CSR ACK received | SM2 PENDING → CONFIRMED, event_state=1 | No notification (success) |
| Alarm triggered, CSR NAK received | SM2 PENDING → FAILED, event_state=2 | `_notify(SUPERVISION_NAK, SM2NakCtx{...})` (T1) |
| Alarm triggered, timeout (no ACK/NAK) | SM2 stays PENDING (retry logic at story 5.6) | `_notify(EVENT_FAILED, EventFailedCtx{...})` after max retries (T3) |
| Alarm triggered, SM1 in NO_NETWORK | Queue alarm in PriorityQueue, attempt when SM1 recovers | None (waiting state) |

**Persistence Across Restarts (ref: ADR-14, php-core-design.md):**

- `event_state` and `event_label` stored in INFO command values (Jeedom config)
- On daemon restart: read from command.execAttr, restore to `_event_state`, `_event_label`
- Do NOT reset to IDLE or event_state=0 on daemon stop/start
- Example: if last event was CONFIRMED, restart → event_state=1, event_label="Confirmé"

**Logging Output (ref: logging-design.md SM2 Table):**

| Transition | INFO (French) | DEBUG (English) |
|------------|---------------|-----------------|
| IDLE (start) | (none) | "SM2 initialized: IDLE state, event_state=0 (no alarm since start)" |
| → PENDING (alarm) | "Alarme détectée: [burglar\|fire\|panic]" | "SM2 PENDING: alarm triggered for zone=[zone], sent to CSR" |
| → CONFIRMED (ACK) | "Alarme confirmée par la centrale" | "SM2 CONFIRMED: ACK received for alarm, event_state=1" |
| → FAILED (NAK) | "Alarme rejetée par la centrale" | "SM2 FAILED: NAK received, event_state=2, T1 notification dispatched" |
| PENDING → PENDING | "Nouvelle alarme détectée" | "SM2: alarm triggered while PENDING, queueing new event" |

**Test Data & Fixtures (ref: daemon-design.md test scenarios):**

File: `test_data/sm2_alarm_scenarios.yaml`

Test Cases (run with csr_simulator):
1. **Happy Path**: Alarm trigger → SM2 PENDING → CSR ACK → CONFIRMED, event_state=1 ✓
2. **NAK Path**: Alarm trigger → PENDING → CSR NAK → FAILED, event_state=2, T1 notification ✓
3. **Persistence**: Trigger alarm → CONFIRMED, event_state=1 → stop daemon → restart → event_state=1 (not reset) ✓
4. **Multiple Alarms**: Alarm (zone=A) → CONFIRMED → Alarm (zone=B) → PENDING → ACK → CONFIRMED ✓
5. **No IDLE Re-entry**: CONFIRMED → next alarm goes to PENDING (not back to IDLE) ✓
6. **Timeout Scenario**: Alarm → PENDING → no ACK within timeout → retry → max retries → T3 notification ✓
7. **Zone Extraction**: Action command with `#zone#` → zone extracted → included in SIA frame ✓

**Supervision Resilience:** SM2 continues queuing alarms in PriorityQueue even when SM1 is DEGRADED. Alarms are sent when SM1 recovers (story 5.3).

---

### Story 5.3: PriorityQueue Task Coordination

As a daemon architect,
I want SM1 and SM2 tasks coordinated in a priority queue,
So that supervision keep-alives take priority over alarm retries.

**Acceptance Criteria:**

**Given** PriorityQueue initialized with 4-tuple tie-breaking: `(priority, counter, timestamp, item)`

**When** enqueueing SM1 tasks (supervision)
**Then** priority=10 (highest)

**And** SM2 tasks (alarms) get priority=5 (lower)

**And** counter uses `itertools.count()` for FIFO ordering within same priority

**And** timestamp uses `time.monotonic()` for diagnostic purposes

**And** dequeue always returns highest-priority item first

**And** tie-breaking prevents TypeError on equal-priority items

---

### Story 5.4: UDP & TCP Transport Layer

As a daemon architect,
I want to send and receive SIA frames over UDP and TCP,
So that the daemon can communicate with the CSR.

**Acceptance Criteria:**

**Given** transport configuration (UDP or TCP, CSR IP:port)
**When** sending an alarm or supervision message
**Then** frame is serialized and sent via configured transport

**And** for UDP: datagram sent, no connection state maintained

**And** for TCP: connection established, frame sent, connection optionally kept open

**And** on TCP send: `asyncio.wait_for(open_connection(...), timeout=10s)` prevents indefinite hang

**And** on TCP timeout: socket closed, error logged, strike triggered

**And** received frames parsed and validated (CRC check)

**And** socket resources cleaned up on error

**And** both transports support encrypted and plaintext frames

---

### Story 5.5: Async Task Lifecycle Management

As a daemon architect,
I want all background tasks tracked and cleanly cancelled,
So that no tasks are orphaned or lost on shutdown.

**Acceptance Criteria:**

**Given** daemon initialization
**When** creating background tasks
**Then** all tasks created via `_track_task(coro, name)` method

**And** `_tasks: set[asyncio.Task]` initialized in `on_start()` (not `__init__`)

**And** each task added to set and given descriptive name (not Task-1, Task-2)

**And** done callback logs exceptions via logger.error()

**And** on `on_stop()`: all tasks in _tasks are cancelled and awaited

**And** no bare `asyncio.create_task()` calls in codebase

**And** `_notify()` is a synchronous wrapper that internally calls `_track_task()`

---

### Story 5.6: Daemon Core Integration & State Transition Tests

As a daemon architect,
I want the daemon to bootstrap, manage state transitions, and integrate with error handler/logging,
So that all components work together.

**Acceptance Criteria:**

**Given** daemon `on_start()` method
**When** daemon starts
**Then** configuration loaded from plugin config

**And** CSR preset loaded and validated (fail-fast on missing/invalid)

**And** encryption key scrubbed from PHP scope after exec()

**And** logger configured using logging boilerplate (Epic 4)

**And** _tasks set initialized, ready for background tasks

**And** `isConnect()` returns true only if config valid and daemon ready

**And** on `on_stop()`: all tasks cancelled, resources cleaned up, state cleared

**And** integration tests with csr_simulator verify:
- SM1 state transitions (INITIALIZING → HEALTHY, strikes → DEGRADED, ACK recovery)
- SM2 state transitions (PENDING → CONFIRMED/FAILED)
- Task priority ordering
- Error handler callbacks triggered at correct times

**And** state transitions logged with French user messages (from messages.py)

---

## Epic 6: PHP Plugin Core & Jeedom IPC

Build PHP eqLogic/cmd classes, auto-equipment creation, JSON callback IPC protocol, and INFO command persistence.

**Dependencies:** Epic 1, 5, Epic 3, Epic 4

### Story 6.1: PHP eqLogic & cmd Classes

As a Jeedom plugin developer,
I want eqLogic and cmd classes that extend Jeedom framework,
So that the plugin integrates properly with Jeedom architecture.

**Acceptance Criteria:**

**Given** PHP core classes in core/class/
**When** plugin is enabled
**Then** eqLogic class extends Jeedom eqLogic with:
- Equipment name (set from CSR preset)
- Icon and category (security)
- Health check via isConnect() method
- Pre/post-save hooks for lifecycle

**And** cmd class defines two command types:
- **Action commands** (not visible in UI): burglarAlarm, fireAlarm, panicAlarm
  - Accept the zone **label** in the `#zone#` tag placed in the action's *Titre* field
  - Resolve that label against `sia_zone_mappings` to obtain `zone_number` (amended 2026-09-17, Story 8.2 AC13)
  - Payload sent to daemon via sendToDaemon(): `{cmd, zone: label, zone_number: int|null, media_url}` — only `zone_number` reaches the SIA frame

- **INFO commands** (not visible in UI): supervision_state, supervision_label, event_state, event_label
  - Updated by daemon callbacks
  - Numeric state + human-readable labels

**And** all commands have proper subtype, type, logicalId

---

### Story 6.2: Auto-Equipment Creation

As a Jeedom user,
I want the plugin to automatically create equipment,
So that I don't need to manually add it.

**Acceptance Criteria:**

**Given** plugin installed and enabled
**When** daemon starts
**Then** equipment is automatically created once

**And** equipment name is "SIA DC-09 - [CSR Preset Name]" (e.g., "SIA DC-09 - IMA Protect")

**And** equipment is associated with plugin eqLogic

**And** all action and INFO commands are created and assigned to equipment

**And** equipment is not recreated if it already exists

**And** equipment remains even if daemon is temporarily stopped

---

### Story 6.3: JSON Callback IPC Protocol

As a daemon architect,
I want daemon to push state updates to PHP via JSON callbacks,
So that PHP always has current daemon state without polling.

**Acceptance Criteria:**

**Given** daemon needs to notify PHP
**When** daemon emits callback
**Then** HTTP POST to configured callback URL with JSON payload

**And** callback payload includes:
- type: "message_center" | "notify" | "error_update" | "message_trace"
- data: {message, level, timestamp, context...}

**And** PHP AJAX handler routes callbacks to appropriate handler

**And** isConnect('admin') AJAX guard validates admin access

**And** callback is idempotent (duplicate callbacks don't corrupt state)

**And** failed callbacks are logged but don't block daemon

---

### Story 6.4: INFO Command Persistence & Real-time Updates

As a Jeedom user,
I want to see supervision and alarm state in real-time,
So that I know the monitoring connection health and last event status.

**Acceptance Criteria:**

**Given** daemon sends callback with supervision state update
**When** PHP receives callback
**Then** supervision_state (numeric) is updated: 0=problem, 1=impaired, 2=healthy

**And** supervision_label (string) is updated with French label: "Sain", "Dégradé", "Problème"

**And** event_state (numeric) is updated: 0=no alarm, 1=confirmed, 2=failed, 3=in progress

**And** event_label (string) is updated: "Inactif", "Confirmé", "Échoué", "En cours"

**And** collectDate is updated automatically (Jeedom feature)

**And** state persists across daemon restarts (commands keep last values)

**And** INFO commands are hidden from UI (isVisible=0)

---

### Story 6.5: Jeedom Dependency Manager & Installation

As a plugin maintainer,
I want clean installation and dependency management,
So that users can install via Jeedom Market without manual steps.

**Acceptance Criteria:**

**Given** packages.json in plugin_info/
**When** Jeedom dependency manager runs
**Then** all Python packages installed: jeedomdaemon, aiofiles, pycryptodome, etc.

**And** install.php creates Python venv in resources/venv/

**And** venv-aware pip used (F3/R3 deferred to implementation phase)

**And** preRemove() hooks clean up venv and running daemon

**And** postSave() validates configuration without restarting daemon

**And** plugin requires Jeedom 4.5+, PHP 8.x (set in info.json)

**And** os.min declared as 12 (Debian 12+) for Python 3.10+

---

### Story 6.6: PHP Core Integration & IPC Tests

As a plugin architect,
I want daemon and PHP to communicate reliably,
So that state updates flow seamlessly.

**Acceptance Criteria:**

**Given** plugin installed with equipment created
**When** daemon starts
**Then** daemon loads plugin config (CSR preset, encryption key, etc.)

**And** sendToDaemon() method sends action commands to daemon via IPC

**And** daemon responds with callbacks to configured callback URL

**And** PHP handlers dispatch callbacks to equipment commands

**And** equipment state (INFO commands) updates in real-time

**And** integration tests verify:
- Equipment auto-creation works
- Callbacks update state correctly
- Daemon stop/start preserves state
- Multiple action commands work independently

**And** end-to-end test: trigger alarm → daemon receives → CSR ACK → event_state=1

---

## Epic 7: Supervision Health Monitoring

Implement continuous supervision loop with 3-strike connection state, real-time INFO updates, and TCP stall detection.

**Dependencies:** Epic 5, 6, 3, 4

### Story 7.1: Supervision Loop with Strike Management & INFO Updates

As a daemon architect,
I want continuous supervision polling with strike escalation,
So that connection degradation is detected within 3 supervision cycles.

**Acceptance Criteria:**

**Test Strategy Reference:** supervision-design.md "Supervision Loop Timing" (ADR-08) + logging-design.md "Supervision Logging Table" + daemon-design.md "SM1 Strike Logic"

**Supervision Loop Execution (ref: supervision-design.md):**

Loop runs every `supervision_interval` seconds (configurable per preset, typically 30-120s):

```
While daemon.running:
  Send SIA NULL supervision frame (zero payload, encrypted per preset)
  Start timeout timer (supervision_interval seconds)

  on ACK received:
    _strike_counter = 0
    _sm1_t3_fired = False
    SM1 state = HEALTHY
    supervision_state = 2
    log INFO "Connexion supervisée établie"
    Ring buffer: log entry (throttled 10-min routine)

  on Timeout:
    _strike_counter = min(_strike_counter + 1, 3)
    if _strike_counter == 1:
      SM1 state = DEGRADED
      supervision_state = 1
      _notify(SUPERVISION_TIMEOUT, SM1TimeoutCtx{...}) [T1]
      log INFO "Supervision dégradée — tentative 1/3"
      Ring buffer: log entry (immediate)
    elif _strike_counter == 3:
      supervision_state = 0
      if not _sm1_t3_fired:
        _notify(SUPERVISION_DISCONNECTED, ...) [T3]
        _sm1_t3_fired = True
      log ERROR "Supervision perdue — intervention requise"
      Ring buffer: log entry (immediate)

      If TCP:
        force socket.close()
        SM1 state = TCP_RECONNECTING
        [Story 7.2 handles reconnect]
      If UDP:
        SM1 stays DEGRADED (no reconnect, waiting for next ACK)
```

**INFO Command Updates (ref: php-core-design.md supervision INFO commands):**

After each supervision cycle, callback to PHP with:
```json
{
  "callback_type": "error_update",
  "data": {
    "supervision_state": 0|1|2,
    "supervision_label": "Sain" | "Dégradé" | "Problème"
  }
}
```

| supervision_state | Meaning | supervision_label | Condition |
|-------------------|---------|-------------------|-----------|
| 2 | Healthy | "Sain" | HEALTHY, strike=0 |
| 1 | Impaired | "Dégradé" | DEGRADED, strike 1-2 |
| 0 | Problem | "Problème" | DEGRADED (strike=3), TCP_RECONNECTING, NO_NETWORK |

**Ring Buffer Logging (ref: logging-design.md ADR-08, supervision throttle):**

Ring buffer (max 50 entries):
- **Routine ACKs**: logged once per 10-minute interval (throttled, not every ACK)
  - Entry: `{timestamp, ROUTINE_ACK, "ACK reçu de [CSR IP]", {strike_count: 0}}`
- **Strike escalations**: logged immediately (1st timeout, 2nd timeout, 3rd timeout)
  - Entry: `{timestamp, STRIKE_ESCALATION, "Tentative 1/3", {strike: 1, elapsed_ms: 30000}}`
- **State transitions**: logged immediately (HEALTHY→DEGRADED, strike 3, TCP_RECONNECTING, etc.)
  - Entry: `{timestamp, STATE_TRANSITION, "SM1 DEGRADED(strike=3)", {from: HEALTHY, to: DEGRADED}}`
- **T1/T3 dispatches**: logged immediately
  - Entry: `{timestamp, T1_FIRED, "SUPERVISION_TIMEOUT", {...}}`

First-ever routine entry: write immediately, then apply 10-min throttle thereafter.

**Logging Output (ref: logging-design.md SM1 Supervision Table):**

| Event | INFO (French) | DEBUG (English) | Log Level |
|-------|---------------|-----------------|-----------|
| ACK received (routine) | (none, routine) | "Supervision ACK: account=XXXXX, time_skew=+/-N ms" | DEBUG |
| Strike 1 timeout | "Supervision dégradée — tentative 1/3" | "Strike 1: timeout on NULL after 30s, T1 SUPERVISION_TIMEOUT fired" | WARNING |
| Strike 2 timeout | "Supervision dégradée — tentative 2/3" | "Strike 2: no ACK for 60s cumulative" | WARNING |
| Strike 3 timeout | "Supervision perdue — intervention requise" | "Strike 3: 3 missed cycles, T3 SUPERVISION_DISCONNECTED fired" | ERROR |
| ACK recovery | "Connexion supervisée rétablie" | "Strike reset: ACK received, returning to HEALTHY" | INFO |

**Test Data & Fixtures:**

File: `test_data/supervision_loop_scenarios.yaml`

Test Cases (run with csr_simulator, supervision_interval=10s for fast testing):
1. **Healthy Loop**: Send NULL → ACK (every 10s for 60s) → strike=0, no escalation ✓
2. **Strike 1**: ACK fails at cycle 1 → strike=1, T1 fired, supervision_state=1 ✓
3. **Strike 2**: ACK fails at cycles 2 → strike=2, no new notification ✓
4. **Strike 3**: ACK fails at cycle 3 → strike=3, T3 fired (once), supervision_state=0 ✓
5. **Recovery**: Strike 3 → ACK at next cycle → strike=0, T3 flag reset, HEALTHY ✓
6. **TCP Stall**: TCP + strike 3 → socket close → TCP_RECONNECTING ✓
7. **Ring Buffer Throttle**: Run 120s (12 cycles) → see 1 routine ACK entry (10-min), 3 strike entries, 1 recovery entry ✓

**Configuration:**
- `supervision_interval` from preset (IMA Protect: 60s default)
- Timeout = supervision_interval (same value)
- TCP connect timeout (story 5.4): 10s default, preset-configurable
- Ring buffer: 10-min routine throttle, immediate state-change entries

---

### Story 7.2: TCP Stall Detection, Reconnect & Ring Buffer Logging

As a daemon architect,
I want to detect TCP connection failures and automatically recover,
So that transient network issues don't require manual restart.

**Acceptance Criteria:**

**Given** TCP transport in use
**When** sending supervision NULL message
**Then** if socket is half-open (no response, no error): force socket.close() after strike timeout

**And** at strike=3 for TCP only: force close → SM1 transitions to TCP_RECONNECTING

**And** TCP_RECONNECTING state: daemon attempts reconnect at configured backoff (exponential or fixed interval)

**And** on reconnect success: → INITIALIZING, strike counter and T3 flag reset

**And** on permanent reconnect failure: → NO_NETWORK, T3 notification sent (TRANSPORT_PERMANENT), daemon stops

**And** ring buffer logging:
- Routine supervision ACKs: logged once per 10-minute interval (throttled, not every ACK)
- Strike escalations (1→2, 2→3): logged immediately
- State transitions (HEALTHY→DEGRADED, TCP_RECONNECTING→INITIALIZING, etc.): logged immediately
- Each log entry includes timestamp, level, message (French), context

**And** ring buffer capped at 50 entries, FIFO oldest-discarded

---

### Story 7.3: Supervision Integration & Testing

As a daemon architect,
I want supervision fully integrated with SM1 and error handler,
So that all components work together reliably.

**Acceptance Criteria:**

**Given** supervision loop, SM1 state machine, error handler, logging all complete
**When** integration tests run with csr_simulator
**Then** SM1 state transitions match supervision strikes: INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING → NO_NETWORK

**And** error handler notifications fire at correct times:
- Strike=1: _notify(SUPERVISION_TIMEOUT, ctx) - T1
- Strike=3: _notify(SUPERVISION_DISCONNECTED, ctx) - T3 (once per escalation)
- TCP_RECONNECTING → NO_NETWORK: _notify(TRANSPORT_PERMANENT, ctx) - T3

**And** logging matches logging-design.md specification:
- INFO lines: French user-facing messages
- DEBUG lines: technical English messages
- All logged via _log_sm1_supervision() helper

**And** tests verify:
- Strike escalation over multiple supervision cycles
- ACK recovery resets strike counter and T3 flag
- TCP stall detection and reconnect
- Callbacks to PHP update supervision_state/label in real-time
- Ring buffer entries appear at correct times (throttled vs immediate)

**And** end-to-end test: simulate network loss → strike escalation → T1/T3 notifications → network recovery → ACK → back to HEALTHY

---

## Epic 8: Configuration Wizard & CSR Presets

Build 4-step zero-jargon wizard for non-technical users to configure CSR connection, test it, map zones, and configure notifications.

**Dependencies:** Epic 1, 5, 6, 7, 3, 4

### Story 8.1: Wizard Steps 1-2 & CSR Preset Selection

As a non-technical Jeedom user,
I want a simple wizard to select my CSR and test the connection,
So that I can set up monitoring without understanding SIA protocol.

**Acceptance Criteria:**

**Given** plugin configuration page loads with wizard mode (step < 4)
**When** user reaches Step 1
**Then** two preset cards displayed: "IMA Protect" and "Personnalisé"

**And** selecting "IMA Protect" auto-fills CSR preset values (host, port, transport, encryption_enabled, supervision_interval, retry_count) — account number and encryption key remain editable (subscriber-specific, not in preset)

**And** "Personnalisé" allows manual entry of CSR parameters

**And** Step 2 displays connection test UI with "Suivant" (Next) and "Ignorer" (Skip) buttons

**And** clicking "Suivant" triggers testConnection subprocess:
- Calls `siadc09d.py --test-only` with configured CSR params (no separate test script)
- 30-second timeout via set_time_limit()
- Displays result (✓ Success or ✗ Error with French error message)

**And** if daemon is running, wizard warns user and requests confirmation before daemon_stop()

**And** connection fields remain populated throughout wizard (no data loss)

**And** "Relancer le test" (Retry) button available for failed tests

**And** Step 2 advances to Step 3 only on successful test or user skip

---

### Story 8.2: Wizard Steps 3-4 & Zone Mapping

As a Jeedom user with an alarm plugin,
I want to map my alarm zones to camera actions and select notifications,
So that alarms trigger cameras and I get notified on failures.

**Acceptance Criteria:**

**Given** wizard Step 3 displayed
**When** page loads
**Then** zone mapping table shows all zones from Jeedom alarm plugin

**And** each row has: N° | Zone Name | Camera Action Selector | Media URL Input

**And** camera selector is a Jeedom.cmd.getSelectModal() popup (Jeedom 4.5+ API)

**And** media URL is optional (for future Frigate integration)

**And** zone names are extracted from alarm plugin action `#zone#` tag (user-configured in alarm plugin)

**And** mapping is saved to equipment config

**Amendment 2026-09-17 — zone order number (AC11–AC15)** — *validated 2026-09-17 on the real receiver `192.168.100.15:10002`, frame `D741003A"SIA-DCS"0010L0#001234[#001234|BA 001]_22:01:49,09-17-2026` (AC15 PASS)*:

**And** each row displays a zone order number (1-based, from the alarm plugin zone order), carried on the row as `data-zone-number` and persisted in `sia_zone_mappings` as `zone_number`

**And** the number is stable: never recomputed at send time; a new zone gets `max(existing) + 1`; legacy entries without `zone_number` are renumbered by table position on the first Step 3 save

**Given** an alarm fires with `#zone#` = a label present in `sia_zone_mappings`
**Then** the SIA frame carries the **zone order number**, zero-padded to 3 digits — `[#001234|BA 001]` — and never the label

**Given** an alarm fires with a label absent from `sia_zone_mappings`
**Then** the frame carries **no zone field at all** — `[#001234|BA]` — a WARNING naming the label is logged, and the alarm is still sent

**And** the IPC payload keeps both fields on purpose: `zone` = label (logs, notifications, ring buffer, protocol inspector), `zone_number` = the only zone identity that reaches the frame

**And** Step 4 displays mandatory notification command selector
- Opens Jeedom.cmd.getSelectModal() to select a notification command
- Displays human-readable command name next to selector
- Step 4 cannot proceed without notification command selected

**And** wizard completion saves all config and starts daemon

---

### Story 8.3: Wizard Integration & Testing

As a plugin maintainer,
I want the wizard to be robust and testable,
So that users can recover from errors and re-configure easily.

**Acceptance Criteria:**

**Given** wizard in any step
**When** user clicks "Relancer l'assistant" (Restart Wizard)
**Then** wizard saves wizard_step=0 before daemon_stop() to prevent race condition

**And** daemon stops, wizard restarts from Step 1

**And** existing config is preserved (fields pre-populate from last save)

**And** wizard validates config at each step before advancing

**And** error messages in French from messages.py

**And** integration tests verify:
- Step 1-4 flow with IMA Protect preset
- Step 2 connection test with csr_simulator
- Zone mapping with mock alarm plugin
- Notification command selection
- Daemon startup after Step 4 completion
- Restart wizard functionality

**And** end-to-end test: complete wizard → daemon starts → supervision connection healthy

---

## Epic 9: Debug UI & Diagnostics Panel

Implement diagnostic tab with status badge, error panel, protocol inspector (hex viewer, decryption, field breakdown), and manual refresh buttons.

**Dependencies:** Epic 1-8

### Story 9.1: Status Badge & Error Panel

As a Jeedom user troubleshooting a connection issue,
I want to see the current connection status and recent errors,
So that I can understand what went wrong.

**Acceptance Criteria:**

**Given** diagnostic tab opened (Step 4 config page)
**When** page loads
**Then** status badge displayed with color coding:
- Green: supervision_state=2 (HEALTHY)
- Orange: supervision_state=1 (DEGRADED/INITIALIZING)
- Red: supervision_state=0 (NO_NETWORK/STOPPED)

**And** badge shows human-readable label next to color (e.g., "Sain", "Dégradé", "Problème")

**And** error panel shows 10 most recent errors, newest first

**And** each error displays: timestamp, error code, description (French), resolution hint

**And** manual "Actualiser" button refreshes both badge and error panel (no auto-refresh)

**And** manual "Vider" button clears error panel (clears config key only, not daemon log)

**And** layout is responsive for mobile and desktop

---

### Story 9.2: Protocol Inspector with Hex Viewer & Decryption

As a developer debugging protocol issues,
I want to inspect raw protocol frames and decrypt encrypted messages,
So that I can understand what was sent and received.

**Acceptance Criteria:**

**Given** protocol inspector panel
**When** page loads
**Then** collapsed list displays recent frames from ring buffer

**And** each frame shows: timestamp, direction (send/receive), length, CRC status

**And** clicking frame expands inline to show full details:
- Raw hex (with copy-to-clipboard button, not inline copy)
- Decrypted plaintext (if encrypted)
- Field-by-field breakdown: delimiter, account_number, event_code, checksum, CRC

**And** decryption uses configured encryption key from plugin config

**And** if decryption fails: displays error (bad key or corrupted frame)

**And** CRC validation shown: ✓ Valid or ✗ Invalid

**And** timestamp displayed in local user timezone

**And** manual "Actualiser" button refreshes frame list

**And** manual "Vider" button clears inspector (clears last_messages config key)

---

### Story 9.3: Diagnostic Tab Integration & Testing

As a plugin architect,
I want the diagnostic tab properly integrated and tested,
So that it's reliable for user troubleshooting.

**Acceptance Criteria:**

**Given** diagnostic tab in equipment configuration page
**When** user is in Step 4 (wizard complete, daemon running)
**Then** diagnostic tab is visible and populated

**And** all panels (badge, error, inspector) are visible simultaneously

**And** all refresh buttons are manual only (no auto-refresh)

**And** separate "Vider" button for each panel (error panel, inspector)

**And** layout uses Bootstrap 3 panel styling consistent with Jeedom

**And** responsive design works on mobile and desktop

**And** integration tests verify:
- Status badge updates on supervision state change
- Error panel populated with errors from error_handler
- Protocol inspector displays frames from ring buffer
- All refresh buttons work correctly
- Clear buttons wipe correct data without affecting daemon

**And** end-to-end test: trigger error → error appears in panel → clear → panel empty

---

## Epic 10: Dashboard Widget

Build supervision health widget for dashboard and mobile with color-coded state, staleness detection, and Bootstrap 3 styling.

**Dependencies:** Epic 7, 4

### Story 10.1: Widget Rendering & Bootstrap Panel

As a Jeedom user,
I want to see my monitoring connection status on the dashboard,
So that I can verify monitoring is active at a glance.

**Acceptance Criteria:**

**Given** equipment added to dashboard
**When** dashboard loads
**Then** widget displays Bootstrap 3 panel with supervision status

**And** panel header shows color-coded badge:
- Green circle: supervision_state=2 (HEALTHY, "Sain")
- Orange circle: supervision_state=1 (DEGRADED, "Dégradé")
- Red circle: supervision_state=0 (PROBLEM, "Problème")

**And** human-readable label displayed next to badge

**And** last update timestamp shown (collectDate formatted in local timezone)

**And** widget HTML template is identical for desktop and mobile rendering

**And** widget refreshes on standard Jeedom dashboard reload (no custom JS required)

**And** Bootstrap 3 styling consistent with Jeedom UI

---

### Story 10.2: Widget Staleness Detection & Testing

As a Jeedom user,
I want to know if my widget data is stale,
So that I don't rely on outdated information.

**Acceptance Criteria:**

**Given** widget displayed on dashboard
**When** collectDate is older than 3× supervision_interval
**Then** badge color changes to grey

**And** label changes to "Données non disponibles" (French)

**And** tooltip explains why (e.g., "Last update: 2 hours ago")

**And** staleness check happens on each dashboard view (client-side, no server call)

**And** staleness threshold (3×) is consistent with SM1 strike logic

**And** mobile widget displays identically to desktop widget

**And** integration tests verify:
- Widget displays correct color based on supervision_state
- Staleness detection triggers at 3× supervision_interval
- Widget updates when daemon sends callback
- Mobile and desktop rendering are identical

**And** end-to-end test: supervision HEALTHY → green badge, DEGRADED → orange, NO_NETWORK → red

---

## Epic 11: End-to-End Testing & Market Preparation

Full integration testing with real Ajax alarm system, CSR Simulator validation against real IMA Protect, documentation, and Jeedom Market submission.

**Dependencies:** Epic 1-10 (all features complete)

### Story 11.1: Protocol Conformance — Capture & Compare Ajax Frames

As a protocol engineer,
I want to verify our daemon generates frames identical to Ajax,
So that both systems interoperate with CSRs identically.

**Acceptance Criteria:**

**Given** Ajax alarm system configured to send to CSR Simulator
**When** capturing Wireshark traffic
**Then** extract SIA frames using PCAP extraction tool (Epic 2.4)

**And** save frames to: `test_data/ajax_burglary.hex`, `ajax_fire.hex`, `ajax_panic.hex`, `ajax_supervision.hex`

**And** trigger same scenarios in our plugin (burglary, fire, panic, supervision)
- Our daemon generates frames for same events
- Capture our frames

**And** frame comparison:
- Message length, delimiter, account number, event code, sequence, CRC all match
- Encryption (if enabled) produces structurally identical frames
- Both Ajax and our frames accepted by CSR Simulator with identical ACK response

**And** frame differences documented (e.g., timestamp precision, if any)

**And** test harness: `compare_frames.py ajax_frame our_frame → match|mismatch`

**And** test data stored in `test_data/protocol_conformance/`

---

### Story 11.2: CSR Response Validation — Real IMA vs Simulator

As a plugin architect,
I want to verify CSR Simulator responds identically to real IMA Protect,
So that our simulator is trustworthy for development and testing.

**Acceptance Criteria:**

**Test Strategy Reference:** daemon-design.md "CSR Simulator" validation protocol + architecture.md "Starter Template Evaluation" (CSR specifications)

**Test Setup (ref: architecture doc, ADR-03 Preset Architecture):**

Capture real CSR behavior with Wireshark:
1. Ajax alarm system configured to send to **real IMA Protect** (live CSR, production or test)
2. Sniff traffic with Wireshark (tcpdump or Wireshark UI)
3. Extract frames using Story 2.4 (PCAP extractor tool)
4. Save to: `test_data/ima_protect_capture.pcapng` and extracted `test_data/ima_protect_frames.hex`

Capture IMA Protect responses:
5. Parse CSR responses from pcap (ACKs, NAKs, timestamps)
6. Extract response format: frame structure, timestamp format, CRC algorithm
7. Save response samples to: `test_data/ima_protect_responses.yaml`

**Response Format Specification (ref: daemon-design.md protocol spec section):**

CSR responses expected:
- **ACK**: Fixed format per SIA DC-09-2021 (see protocol spec)
  - Structure: delimiter + sequence + code + CRC + checksum
  - Timestamp: optional, format HHMMSSMMDDYY (when present)
  - CRC format: hex or binary (per preset)
- **NAK**: NAK code + optional timestamp
  - Indicates rejection (timestamp invalid, bad account, etc.)

**Comparison Matrix (ref: daemon-design.md testing section):**

| Scenario | Input Frame | Expected IMA Response | CSR Simulator Response | Match | Status |
|----------|-------------|-----------------------|------------------------|-------|--------|
| Valid alarm (burglary) | SIA encoded burglary frame | ACK, no timestamp | ACK, no timestamp | ✓/✗ | — |
| Valid alarm (fire) | SIA encoded fire frame | ACK | ACK | ✓/✗ | — |
| Valid alarm (panic) | SIA encoded panic frame | ACK | ACK | ✓/✗ | — |
| Supervision NULL | SIA NULL (zero payload) | ACK with timestamp | ACK with timestamp | ✓/✗ | — |
| Invalid timestamp | Alarm with bad timestamp | NAK (timestamp error) | NAK (timestamp error) | ✓/✗ | — |
| Malformed CRC | Frame with bad CRC | NAK or no response | NAK or no response | ✓/✗ | — |
| Encryption mismatch | Wrong key used | No response / timeout | No response / timeout | ✓/✗ | — |

**Test Execution:**

For each test case:
1. Send frame from our daemon to **real IMA Protect** → capture response
2. Send same frame to **CSR Simulator** → capture response
3. Compare byte-by-byte:
   - Frame structure identical
   - Timestamp values within acceptable skew (e.g., ±5 seconds)
   - CRC/checksum algorithms match
   - NAK codes identical

**Validation Thresholds:**

| Aspect | Criterion | Pass |
|--------|-----------|------|
| Frame structure | ACK/NAK format matches | Byte-for-byte identical (excluding timestamps) |
| Timestamp | Time skew | ±5 seconds or less |
| Error responses | NAK codes | Same NAK code for same error condition |
| Response timing | ACK delay | Within 1 second (both <500ms) |
| Encryption | Encrypted frame handling | Both accept or both reject |

**Test Report (ref: daemon-design.md validation output):**

File: `test_data/csr_simulator_validation_report.md`

Document findings:
- **Validation Status**: ✅ PASS (simulator matches IMA within thresholds) or ⚠️ PARTIAL (known differences documented)
- **Differences Found**: If any, describe and document impact on development
- **Confidence Level**: Can development proceed with simulator? YES / NO / WITH_CAVEATS
- **Test Data**: List of captured frames, response samples, test matrix results
- **Next Steps**: If validation fails, action items to fix simulator or update test data

**Test Automation (ref: daemon-design.md):**

Python script: `test_data/validate_csr_simulator.py`
```bash
python validate_csr_simulator.py \
  --ima-responses test_data/ima_protect_responses.yaml \
  --simulator-responses test_data/sim_protect_responses.yaml \
  --report test_data/csr_simulator_validation_report.md
```

Output: comparison table + PASS/FAIL verdict

**Acceptance:**

✅ All test cases pass (responses match within thresholds)
✅ Validation report generated
✅ CSR Simulator confidence level: VALIDATED
✅ Simulator approved for development use

---

### Story 11.3: Full Workflow Integration Testing

As a plugin maintainer,
I want complete end-to-end testing of real user scenarios,
So that the plugin is production-ready.

**Acceptance Criteria:**

**Given** plugin fully implemented (Epic 1-10)
**When** running full user workflow
**Then** complete scenario: user installs → completes wizard → daemon starts → supervision loop healthy → alarm triggers → CSR ACK → event_state=CONFIRMED

**And** test scenarios:
1. **Happy path**: Supervision + Alarm delivery → full success
2. **Network recovery**: Supervision timeout → strike escalation → recovery via ACK
3. **Daemon restart**: Kill daemon → supervision detects → restart daemon → recovery
4. **Alarm during network loss**: Alarm triggers while degraded → buffered → delivered when recovered
5. **CSR error**: CSR rejects frame (NAK) → error notification to user

**And** resource testing:
- Daemon CPU/memory usage under sustained supervision (30+ min)
- Database write frequency matches specification (10-min throttle for routine)
- No memory leaks or orphaned tasks

**And** test duration: each scenario 30+ minutes

**And** test with CSR Simulator (validated in 11.2)

---

### Story 11.4: Documentation, i18n & Market Submission

As a plugin maintainer,
I want complete documentation and market readiness,
So that the plugin can be published and supported.

**Acceptance Criteria:**

**Given** all code complete and tested
**When** preparing for release
**Then** documentation includes:
- **User guide** (French): setup wizard, troubleshooting, understanding status indicators
- **Admin guide**: configuration, backup/restore, upgrade path
- **Developer guide**: code overview, API contracts, extending with new CSR presets

**And** i18n structure:
- All French user strings in `messages.py` (v1.0)
- gettext migration path documented (`# TODO v1.1: gettext`)
- English debug strings inline in code

**And** Jeedom Market submission:
- `info.json` complete (name, description, version, icon, dependencies, min_version)
- `packages.json` lists all Python dependencies with versions
- `plugin_info/icon.png` included (80×80 px)
- Changelog documented (fr_FR and en_US)
- Installation and upgrade tested via Jeedom dependency manager

**And** plugin submission to Jeedom Market official process followed

**And** release notes (French + English) published on GitHub

---

## Epic 12: Jeedom VM Integration Testing

Validate the complete plugin on a real Jeedom instance (Debian 12, VMware Fusion) — from manual installation through daily operation — proving production-readiness on real infrastructure before Market packaging.

**Dependencies:** Epic 1-10 (all features complete)
**Infrastructure:** Debian 12 VM (VMware Fusion on macOS), CSR simulator on same VM, plugin files via shared folder symlink
**FRs covered:** (validates all FRs end-to-end on real Jeedom)
**Testing:** Real Jeedom UI, real daemon process, real alarm plugin, real notification commands

### Story 12.1: Manual Plugin Installation & Dependency Setup

As a plugin developer,
I want to install the plugin manually via shared folder symlink and verify dependencies install cleanly,
So that I have a working dev environment for all subsequent integration tests.

**Acceptance Criteria:**

**Given** VMware shared folder mounted at `/mnt/hgfs` with project files
**When** creating symlink to Jeedom plugins directory
**Then** `ln -s /mnt/hgfs /var/www/html/plugins/siaDC09` makes plugin visible in Jeedom UI

**And** plugin appears in Jeedom → Plugins → Plugin Management with correct name, icon, and description

**And** clicking "Install dependencies" in plugin config triggers packages.json processing:
- Python venv created in `resources/venv/`
- All pip packages installed (jeedomdaemon, pycryptodome, aiofiles, etc.)
- No errors in Jeedom dependency install log

**And** dependency status shows green checkmark in Jeedom UI

**And** `info.json` values are correctly read: plugin name, version, description, minJeedomVersion, os.min

**And** plugin activation (enable toggle) succeeds without PHP errors

**And** Jeedom log (`siaDC09` log) shows no errors after activation

**And** daemon binary path resolves correctly from shared folder structure

**Validation checklist:**
- [ ] Symlink created, plugin visible in Jeedom
- [ ] Dependencies install without errors
- [ ] Dependency status green
- [ ] Plugin activates cleanly
- [ ] No PHP syntax errors in Jeedom log

---

### Story 12.2: Wizard Flow & Connection Test

As a Jeedom user,
I want to complete the 4-step configuration wizard on a real Jeedom instance,
So that the plugin is configured and ready to monitor.

**Acceptance Criteria:**

**Prerequisites:** Story 12.1 complete, CSR simulator running on same VM (`python3 -m tests.simulator --udp-port 10001`)

**Given** plugin enabled and equipment page opened
**When** wizard starts (step < 4)
**Then** Step 1 displays IMA Protect and Personnalisé preset cards

**And** selecting "IMA Protect" auto-fills CSR parameters (host=127.0.0.1 for local simulator, port=10001, transport=udp)

**And** account number and encryption key fields are editable

**And** Step 2 "Suivant" button triggers connection test:
- `test_connection.py` subprocess runs with configured params
- Sends supervision NULL to local CSR simulator
- Receives ACK → displays "✓ Connexion établie"
- Times out or error → displays French error message with "Relancer le test" button

**And** Step 3 displays zone mapping table:
- Zones loaded from alarm plugin (if installed)
- Camera action selector works (jeedom.cmd.getSelectModal)
- Media URL field editable (optional)

**And** Step 4 notification command selector:
- Modal opens, user selects a notification command
- Human-readable name displayed next to selector
- Cannot proceed without selection

**And** wizard completion saves all config to equipment

**And** after Step 4: daemon starts automatically, supervision loop begins

**Validation checklist:**
- [ ] Step 1: preset selection works
- [ ] Step 2: connection test passes against local simulator
- [ ] Step 3: zone mapping table renders (alarm plugin zones if available)
- [ ] Step 4: notification command selection works
- [ ] Wizard completion starts daemon
- [ ] "Relancer l'assistant" restarts wizard cleanly

---

### Story 12.3: Daemon Lifecycle & Jeedom Controls

As a Jeedom administrator,
I want the daemon to start, stop, and restart reliably via Jeedom UI,
So that I can manage the monitoring service without SSH access.

**Acceptance Criteria:**

**Prerequisites:** Story 12.2 complete (wizard done, daemon running)

**Given** daemon is running (green status in Jeedom)
**When** clicking "Stop" in daemon management panel
**Then** daemon process terminates cleanly (no orphan processes)

**And** supervision_state updates to 0 ("Problème") in Jeedom

**And** clicking "Start" relaunches daemon:
- Process visible in `ps aux | grep siadc09`
- Supervision loop begins immediately
- supervision_state → 2 ("Sain") after first ACK

**And** clicking "Restart" performs stop + start atomically

**And** Jeedom watchdog recovery:
- Kill daemon process with `kill -9 <pid>`
- Jeedom detects daemon death within watchdog interval
- Jeedom automatically restarts daemon
- supervision_state recovers to 2 after restart

**And** config change behavior:
- Change a config value (e.g., supervision interval)
- Save equipment → daemon restarts with new config
- Verify new config is active (e.g., changed interval visible in logs)

**And** daemon log accessible via Jeedom UI (Analyse → Logs → siaDC09_daemon)

**And** no zombie processes after repeated start/stop cycles (10+ cycles)

**Validation checklist:**
- [ ] Start/stop/restart via UI works
- [ ] Watchdog recovers from kill -9
- [ ] Config change triggers proper restart
- [ ] No zombie processes after 10 cycles
- [ ] Daemon log accessible in Jeedom

---

### Story 12.4: Supervision Loop & Strike Recovery

As a plugin user,
I want continuous supervision to detect and recover from CSR connection issues,
So that I'm always aware of my monitoring connection health.

**Acceptance Criteria:**

**Prerequisites:** Story 12.3 complete (daemon lifecycle validated)

**Given** daemon running with CSR simulator on same VM
**When** running sustained supervision for 30+ minutes
**Then** supervision_state remains 2 ("Sain") throughout

**And** ring buffer shows routine ACK entries (throttled to 1 per 10 min)

**And** Jeedom log shows DEBUG entries for each supervision cycle

**Strike escalation test:**

**Given** CSR simulator configured to drop ACKs (e.g., `--drop-ack-count 3`)
**When** 3 consecutive supervision NULLs receive no ACK
**Then** strike counter escalates: 1 → 2 → 3

**And** supervision_state transitions: 2 → 1 (strike 1-2) → 0 (strike 3)

**And** supervision_label updates in real-time: "Sain" → "Dégradé" → "Problème"

**And** T1 notification fires at strike=1 (message center entry visible in Jeedom)

**And** T3 notification fires at strike=3 (message center + notification command triggered)

**And** T3 fires only ONCE (not repeated on subsequent timeouts)

**Recovery test:**

**Given** daemon in DEGRADED state (strike=3)
**When** CSR simulator resumes sending ACKs
**Then** strike resets to 0, supervision_state → 2, label → "Sain"

**And** Jeedom log shows INFO "Connexion supervisée rétablie"

**And** T3 flag resets (next disconnection will fire T3 again)

**Duration test:**
- Run 30+ minutes with stable supervision → no memory growth, no orphan tasks
- Check daemon RSS memory at start and end (should be stable ±10%)

**Validation checklist:**
- [ ] 30-min stable supervision passes
- [ ] Strike escalation 1→2→3 visible in Jeedom
- [ ] T1 at strike=1 appears in message center
- [ ] T3 at strike=3 triggers notification command
- [ ] Recovery after simulator resumes ACKs
- [ ] No memory leak over 30 min

---

### Story 12.5: Alarm Delivery End-to-End

As a Jeedom user with an alarm system,
I want alarm events delivered to the CSR and confirmed,
So that my home is protected by professional monitoring.

**Acceptance Criteria:**

**Prerequisites:** Story 12.3 complete, daemon running with healthy supervision

**Happy path (ACK):**

**Given** alarm plugin configured with zones, daemon in HEALTHY state
**When** triggering burglarAlarm action command with zone="Salon"
**Then** daemon receives action via sendToDaemon()

**And** SIA frame constructed with correct event code (BA for burglar)

**And** frame sent to CSR simulator via configured transport

**And** CSR simulator responds with ACK

**And** event_state updates to 1 ("Confirmé") in Jeedom

**And** event_label shows "Confirmé"

**And** ring buffer shows alarm dialog entry (request + response)

**NAK path (rejection):**

**Given** CSR simulator configured to NAK alarm frames
**When** triggering fireAlarm action command
**Then** event_state updates to 2 ("Échoué")

**And** T3 EVENT_FAILED notification fires after max retries

**And** notification command triggered with "CRITIQUE" prefix

**And** Jeedom message center shows critical error entry

**All event types:**
- [ ] burglarAlarm → BA code → ACK → CONFIRMED
- [ ] fireAlarm → FA code → ACK → CONFIRMED
- [ ] panicAlarm → PA code → ACK → CONFIRMED

**Zone handling** (amended 2026-09-17 — see Story 8.2 AC11–AC15):
- Trigger alarm with a zone name present in the zone table → the SIA frame carries the zone **order number**, 3-digit zero-padded (`[#001234|BA 001]`), never the label (protocol inspector)
- Trigger alarm with a zone name absent from the zone table → the frame carries **no zone field** (`[#001234|BA]`) + WARNING, alarm still sent
- Trigger alarm without zone → same as unresolved, frame still valid, no crash

**Validation checklist:**
- [ ] Burglar alarm ACK path works end-to-end
- [ ] Fire alarm ACK path works
- [ ] Panic alarm ACK path works
- [ ] NAK path → FAILED + T3 notification
- [ ] Zone **order number** included in SIA frame (never the zone label)
- [ ] Ring buffer shows alarm dialog

---

### Story 12.6: Widget & Debug UI Rendering

As a Jeedom user,
I want the dashboard widget and diagnostic panel to display accurate real-time information,
So that I can monitor status at a glance and troubleshoot issues.

**Acceptance Criteria:**

**Prerequisites:** Story 12.4 complete (supervision states validated)

**Dashboard widget:**

**Given** equipment added to Jeedom dashboard
**When** dashboard loads
**Then** widget renders Bootstrap 3 panel with correct color badge:
- Green when supervision_state=2
- Orange when supervision_state=1
- Red when supervision_state=0

**And** widget shows human-readable label and last update timestamp

**And** widget renders identically on mobile view (responsive)

**And** staleness detection: if collectDate > 3× supervision_interval → grey badge + "Données non disponibles"

**Diagnostic tab (Step 4 config page):**

**Given** equipment config page opened at Step 4
**When** diagnostic tab selected
**Then** status badge shows current supervision state with correct color

**And** error panel shows recent errors (if any) with French descriptions

**And** "Actualiser" button refreshes badge + error panel

**And** "Vider" button clears error panel without affecting daemon

**Protocol inspector:**

**Given** daemon has been running (ring buffer populated)
**When** opening protocol inspector panel
**Then** collapsed frame list shows recent frames with timestamp, direction, length

**And** expanding a frame shows field-by-field breakdown (delimiter, account, event code, CRC)

**And** encrypted frames show decrypted plaintext (using configured key)

**And** copy-to-clipboard button works for raw hex

**And** "Actualiser" refreshes frame list, "Vider" clears inspector

**Validation checklist:**
- [ ] Widget green/orange/red matches supervision state
- [ ] Widget renders on mobile
- [ ] Staleness detection works
- [ ] Diagnostic badge + error panel populate
- [ ] Protocol inspector shows frame details
- [ ] Encrypted frames decrypted correctly
- [ ] All refresh/clear buttons work

---

### Story 12.7: Error Handling & Notification Delivery

As a Jeedom user,
I want errors properly classified and notifications delivered through Jeedom's systems,
So that I'm informed of issues proportional to their severity.

**Acceptance Criteria:**

**Prerequisites:** Stories 12.4 and 12.5 complete (supervision + alarm paths validated)

**T1 (Auto-heal) — Message center only:**

**Given** supervision timeout occurs (strike=1)
**When** T1 SUPERVISION_TIMEOUT fires
**Then** Jeedom message center shows entry (Analyse → Messages)

**And** no notification command is triggered

**And** occurrence counter increments on repeat (Jeedom dedup)

**T2 (User-actionable) — Message center + notification:**

**Given** CSR simulator sends malformed response
**When** T2 BAD_CSR_RESPONSE fires
**Then** Jeedom message center shows entry with French description

**And** configured notification command IS triggered

**And** notification text explains user action needed

**T3 (Critical) — Message center + notification + CRITIQUE prefix:**

**Given** 3 consecutive supervision timeouts (strike=3)
**When** T3 SUPERVISION_DISCONNECTED fires
**Then** Jeedom message center shows entry with "CRITIQUE —" prefix

**And** configured notification command triggered with "CRITIQUE" prefix

**And** T3 fires only ONCE per escalation (not repeated)

**Given** alarm delivery fails after retries
**When** T3 EVENT_FAILED fires
**Then** same behavior: message center + notification + "CRITIQUE" prefix

**Deduplication:**
- Trigger same T1 error 5 times → message center shows 1 entry with occurrence=5 (not 5 entries)
- Verify notification command not spammed on repeated T2/T3

**Validation checklist:**
- [ ] T1 → message center only, no notification cmd
- [ ] T2 → message center + notification cmd fired
- [ ] T3 → message center + notification cmd + "CRITIQUE" prefix
- [ ] T3 fires only once per escalation
- [ ] Deduplication works (occurrence counter)
- [ ] All error messages in French

---

### Story 12.8: Market Package Install & Uninstall

As a plugin maintainer,
I want the plugin to install cleanly from a packaged .zip (Market-style) and uninstall without orphans,
So that the plugin is ready for Jeedom Market submission.

**Acceptance Criteria:**

**Prerequisites:** Stories 12.1–12.7 complete (all features validated via manual install)

**Setup:** Remove the symlink installation first:
```bash
sudo rm /var/www/html/plugins/siaDC09
# Verify plugin no longer visible in Jeedom
```

**Package creation:**

**Given** project source on macOS
**When** packaging plugin as .zip (excluding .git, _bmad-output, tests, docs)
**Then** .zip contains only Market-required files: core/, desktop/, resources/, plugin_info/, docs/ (user docs only)

**And** .zip structure matches Jeedom Market conventions

**Fresh install from .zip:**

**Given** clean Jeedom (no previous siaDC09 installation)
**When** uploading .zip via Jeedom → Plugins → Plugin Management → "Ajouter depuis une autre source"
**Then** plugin installs without errors

**And** dependency install creates venv + installs all packages

**And** plugin activates cleanly (no PHP errors)

**And** wizard flow works (same validation as Story 12.2)

**And** daemon starts and supervision works

**Uninstall:**

**Given** plugin installed and daemon running
**When** removing plugin via Jeedom UI
**Then** preRemove() stops daemon

**And** venv directory removed (`resources/venv/`)

**And** no orphan files left in plugins directory

**And** no orphan cron entries in Jeedom

**And** equipment removed from Jeedom

**And** Jeedom logs show clean removal

**Upgrade path:**

**Given** plugin installed from .zip (version 1.0.0)
**When** uploading newer .zip (version 1.0.1)
**Then** files updated in place

**And** equipment and config preserved (no data loss)

**And** dependency install re-runs (handles new packages if any)

**And** daemon restarts with new code

**Validation checklist:**
- [ ] .zip package created with correct structure
- [ ] Fresh install from .zip succeeds
- [ ] Dependencies install from packaged plugin
- [ ] Full wizard + supervision works from packaged install
- [ ] Uninstall leaves no orphans
- [ ] Upgrade preserves config and equipment

---

## Epic 13: Alarm Event Vocabulary Extension (v1.1)

Report the *end* of an alarm, not only its start: Burglary Restore (BR) when a zone returns to normal, Burglary Cancel (BC) when the user cancels from the abort window. v1.0 emits BA/FA/PA only, so a CSR keeps an incident open until an operator calls back.

**Dependencies:** Epic 12 (v1.0 validated on real Jeedom), plus the zone-number resolution added to Story 8.2 — a restoral must carry the same zone number as the alarm it closes.
**FRs covered:** new (post-MVP, PRD Growth v1.1+)
**Testing:** level 1 frame building, level 2 SM2 correlation, real Jeedom UI on `test-jeedom.lehoux.net` against the internal receiver `192.168.100.15:10002`

### Story 13.1: Burglary Restore (BR) & Burglary Cancel (BC) Events

As a monitored Jeedom user,
I want the plugin to report the end of an intrusion event — zone back to normal (BR) and alarm cancelled by the user (BC),
So that the CSR closes the incident instead of keeping an open alarm.

This story carries three **blocking design questions** that must be answered in the design docs before code (full analysis with code references in `_bmad-output/implementation-artifacts/13-1-burglary-restore-cancel-events.md`):

1. **Zone correlation** — SM2 keeps a single current event (`daemon.py:339-340`: `_event_sia_code` / `_event_zone`), so after `BA Salon` then `BA Cuisine` it cannot tell which alarm `BR Salon` closes. Per-zone active-alarm map, or unconditional BR with correlation left to the CSR?
2. **`event_state` vocabulary** — the numeric info command (`siaDC09.class.php:647`) has 0 inactive / 1 confirmed / 2 failed / 3 in progress, none of which means "returned to normal" or "cancelled"; reusing 0 conflates "restored" with "nothing ever happened". New states (widget + labels + diagnostic tab), or expose the restoral elsewhere?
3. **Commands and alarm-plugin wiring** — which Jeedom action commands to expose, and where their zone comes from: the alarm plugin's natural restore triggers (`release`, `raz`, `razImmediate`) pass **only** `#mode#`, never `#zone#` (`alarm.class.php:703-712`, `:743`), so the zone of a BR cannot come from the alarm plugin at all.

**Acceptance criteria:**

**Given** the three design questions above
**When** implementation starts
**Then** each one is answered in `daemon-design.md`, `widget-design.md` and `php-core-design.md` first

**And** `SiaEventCode`, `_EVENT_SIA_CODES` and `error_handler.py`'s code/label maps (`:328`, `:366`) accept BR and BC

**And** a BR frame is `[#{account}|BR {zone_number}]` — the resolved number from the zone table, never the zone label

**And** an unresolved zone yields `[#{account}|BR]` with a warning, consistent with Story 8.2

**And** BR for a zone that never alarmed, and a duplicate BR, both have a test proving the chosen behaviour

**And** the whole flow is validated through the real Jeedom UI on `test-jeedom.lehoux.net`, alarm triggered *and* ended, both frames read in the protocol inspector

---

## Epic 14: Camera Snapshot Attachment (Frigate Integration)

Attach a camera snapshot URL to the SIA frame's `[V...]` Verification field when a zone's alarm fires, so the receiving operator has a visual on the alarm. Scoped per ADR-17 (`architecture.md`) to the majority case only — a person Frigate's AI already detected *before* the alarm fired — using the existing Jeedom "Frigate NVR" plugin's own commands. The fallback case (camera hasn't detected anyone yet) is explicitly deferred: no create-event call, no wait/poll logic, no `media_url` in that branch this version.

**Dependencies:** Epic 8 (zone mapping, 8-2) for the zone → camera association pattern being adapted; the user's Jeedom instance must have the Frigate NVR plugin installed and configured with MQTT (via `mqtt2`) for `info_detect_person`/`info_url_snapshot` to be real-time.
**FRs covered:** new (post-MVP, adjacent to PRD Vision v1.5+ "Frigate NVR integration," implemented here in a deliberately narrower majority-case-only form — see ADR-17 rationale for why the full v1.5 vision (clip attachment, fallback-case event creation) is not in scope)
**Testing:** level 1 PHP structure tests (zone mapping schema, camera-derivation logic) with mocked `cmd::execCmd()`; level 3 manual validation on `test-jeedom.lehoux.net` against a real Frigate camera

### Story 14.1: Attach Frigate Snapshot to Alarm Frame (Majority Case Only)

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want the SIA alarm frame to carry a snapshot URL when Frigate already caught the person before the alarm fired,
So that the monitoring center has a visual without me building or waiting on anything that could delay the alarm itself.

**Acceptance criteria:**

**Given** a zone mapped to a Frigate camera equipment,
**When** the zone mapping is saved,
**Then** only the camera equipment is selected — `info_detect_person` and `info_url_snapshot` command IDs are derived by `logicalId` lookup on that same equipment, not stored as separate config fields

**And** if the selected camera equipment doesn't expose both `info_detect_person` and `info_url_snapshot` (plugin absent, wrong version, or command missing), saving the mapping warns the user but does not block save — same "never crash on unmapped/misconfigured camera" principle as 8-2's zone mapping

**Given** an alarm fires for a zone mapped to a Frigate camera,
**When** `info_detect_person` reads `1` (person already detected — the expected majority case),
**Then** `info_url_snapshot`'s current value is read via `execCmd()` (live cache read, per the execCmd-vs-getValue project finding — never `getValue()`, which is frozen for these info cmds) with zero wait, and attached as `media_url` in the SIA frame

**And** when `info_detect_person` reads `0` (fallback case) or the camera/plugin/commands are unavailable for any reason, the frame is sent with `media_url` omitted — no create-event call, no wait, no exception, no delay to the alarm send path

**And** a test proves the alarm-send path never blocks or throws regardless of camera/plugin state (mapped-and-detected, mapped-and-not-detected, camera deleted, plugin absent) — promoted from a review finding to a hard AC given the life-safety framing of this path

**And** `media_url` never maps to a clip/video URL in this story — snapshot only, matching ADR-17

**And** the whole flow is validated through the real Jeedom UI on `test-jeedom.lehoux.net` against a real Frigate camera: trigger an alarm while Frigate has an active person detection, confirm the SIA frame's `[V...]` field carries a working snapshot URL in the protocol inspector

**Explicitly out of scope (deferred, tracked in ADR-17):** the fallback case (create-event call for when the camera missed the person), clip/video attachment, and the independent MQTT/REST Frigate integration (Option B) — revisit only if production telemetry shows the fallback case is common enough to justify the added complexity.

### Story 14.2: Frigate Event Prefetch via the Alarm Plugin's Immediate-Action Window (Option D)

Supersedes 14.1's at-alarm-time data source per ADR-17 Amendment 3 (`architecture.md`). Live validation of 14.1
surfaced two confirmed problems with reading the Frigate plugin's own commands directly: `info_detect_person` can
stay stuck at `1` for 14-30+ minutes after the person left (a missing MQTT case in the Frigate plugin itself), and
`info_id` has no label filter at all — any tracked object class (person, car, dog, cat, bird in the real
deployment) can silently overwrite it, so a pet or a passing car can end up presented as evidence of a burglary.
A party-mode architecture review (Winston/Amelia/John) converged, after a correction from Herve about the alarm
plugin's own timing model, on Option D: the Jeedom alarm plugin fires each zone's actions in two buckets —
immediate (instant, ignores the trigger delay) and standard (fires only after the trigger delay, typically 30-60s,
the entry-delay window that lets a legitimate user disarm). `burglarAlarm` is a standard action; a new immediate
action can therefore kick off an async Frigate REST lookup with the whole trigger-delay window to complete, well
before the frame is built.

As a monitored Jeedom user with a Frigate camera covering an alarm zone,
I want the SIA alarm frame's snapshot to always be of the actual detected person, never a stale or wrong-species one,
So that the monitoring center can trust the photo it's looking at, not just receive one.

**Acceptance criteria:**

**Given** a zone mapped to a Frigate camera (14.1's existing wizard mapping, unchanged),
**When** the zone's own sensor trips (the alarm plugin's immediate action, never Frigate's own detection state),
**Then** a new `prefetchEvent` action command fires immediately and asks the daemon, asynchronously, whether
Frigate currently has a `person`-labeled event active or very recent for that camera — via Frigate's own
documented `GET /api/events` REST endpoint, never the Jeedom Frigate plugin's cmds or its internal DB table

**And** the daemon's REST call runs entirely inside this immediate-action window, with a bounded timeout; on a
confirmed match it pushes the result (event id, snapshot availability) back to PHP via the existing HTTP callback
channel, cached on the SIA eqLogic keyed by camera — no new synchronous IPC primitive, no blocking read anywhere

**Given** the zone's trigger delay later expires and `burglarAlarm` (the standard action) fires,
**When** it builds the SIA frame,
**Then** it reads the cached prefetch result **locally, synchronously, non-blockingly** (same latency class as the
`execCmd()` read it replaces) and attaches `media_url` only on a confirmed, unexpired, correctly-labeled hit

**And** on any miss — no prefetch ran, timed out, expired, or found no `person` event — `media_url` is omitted,
exactly like 14.1's existing AC4 fallback: never a wrong photo, never a delay, "no photo" is an acceptable outcome
and "wrong photo" never is

**And** `info_detect_person`, `info_id`, `info_label`, and `info_url_snapshot` are no longer read anywhere in this
path — closing both confirmed problems by removing the data source they lived in, not by patching around them

**And** scope stays `burglarAlarm` only — panic/fire alarms are triggered through different zones/instances with
independently-configured (often zero) trigger delays and are explicitly deferred to a future story

**And** the whole flow is validated on `test-jeedom.lehoux.net` against a real Frigate camera and a real alarm
zone with a configured entry delay: trigger the sensor, confirm the prefetch fires immediately, confirm the SIA
frame sent after the delay carries the correct `[V...]` snapshot URL

**Explicitly out of scope (deferred, tracked in ADR-17 Amendment 3):** clip attachment (architecturally compatible,
confirmed no rework needed, but not implemented here); PA/FA media attachment for zero-delay zones; reporting the
two confirmed Frigate-plugin bugs upstream.
