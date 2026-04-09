# Story 2.1: Simulator Framework & UDP/TCP Listen

**Status:** ready-for-dev

---

## Story

As a tester/developer,
I want to run a local CSR simulator that accepts UDP/TCP connections,
So that I can test alarm system integrations without connecting to a real CSR.

---

## Acceptance Criteria

1. **Given** the simulator is started with configured UDP and TCP ports
   **When** a frame arrives from a daemon or test tool
   **Then** the simulator listens on both UDP and TCP simultaneously

2. **And** incoming frames are parsed using protocol engine (stories 1.1/1.2)

3. **And** encrypted frames are decrypted using AES-128 (story 1.2)

4. **And** frame structure and CRC are validated

5. **And** all received frames are logged with timestamp for debugging

---

## Tasks / Subtasks

### Task 0: CSR Simulator Module Skeleton
- [ ] Create `tests/simulator/csr_simulator.py` with module docstring
  - [ ] Document purpose: standalone CSR simulator for protocol testing (not deployed to Jeedom)
  - [ ] Import core modules: asyncio, struct, logging, datetime
  - [ ] Import from sia_protocol: `encode_ack()`, `encode_nak()`, `decode_message()`, `validate_timestamp()`, `SIAProtocolError`, `SIATransportError`
  - [ ] Import from sia_crypto: `decrypt_message()` for encrypted frame handling
  - [ ] Define simulator configuration constants: `DEFAULT_UDP_PORT`, `DEFAULT_TCP_PORT`, `DEFAULT_LISTEN_HOST`
  - [ ] Define simulator version/identifier string

### Task 1: Frame Parsing & Validation
- [ ] Implement `_parse_frame(raw: bytes) -> dict` method
  - [ ] Validate frame structure: starts with `0x0A` (LF), ends with `0x0D` (CR)
  - [ ] Extract CRC field (4 ASCII hex bytes after LF)
  - [ ] Validate CRC matches computed value
  - [ ] Raise `SIAProtocolError` for malformed frames (invalid CRC, missing delimiters)
  - [ ] Return parsed dict with: `id_type`, `seq`, `account`, `zone`, `timestamp`, `encrypted`, `raw_nak`
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1 (frame structure)]

### Task 2: UDP Socket Binding & Listen Loop
- [ ] Implement `_setup_udp_listener()` async method
  - [ ] Create UDP socket on `listen_host:udp_port` (default 10001)
  - [ ] Bind socket with `SO_REUSEADDR` flag (allow rapid restart)
  - [ ] Configure socket to non-blocking mode via asyncio
  - [ ] Log: `"UDP listener started on {host}:{port}"`
  - [ ] Return bound socket object
  - [ ] Raise `SIATransportError` if bind fails (port in use, permission denied)
  - [ ] Handle address family (IPv4 by default; IPv6 optional for v1.1)

### Task 3: TCP Socket Binding & Listen Loop
- [ ] Implement `_setup_tcp_listener()` async method
  - [ ] Create TCP server via `asyncio.start_server()` on `listen_host:tcp_port` (default 5000)
  - [ ] Log: `"TCP listener started on {host}:{port}"`
  - [ ] Register new connection callback: `_handle_tcp_connection(reader, writer)`
  - [ ] Return server object for lifecycle management (close on shutdown)
  - [ ] Raise `SIATransportError` if bind fails

### Task 4: UDP Receive Handler
- [ ] Implement `_handle_udp_frame(data: bytes, addr: tuple)` async method
  - [ ] Log received frame: `"UDP frame from {addr}: {len(data)} bytes"`
  - [ ] Call `_parse_frame(data)` to extract message details
  - [ ] On parse error: log warning, do NOT respond (let timeout occur on sender)
  - [ ] On success: store frame metadata (src_addr, timestamp, raw bytes)
  - [ ] For inspection/debugging: add to ring buffer (Task 6)
  - [ ] Pass to scenario handler for response decision (Task 5)

### Task 5: TCP Connection Handler
- [ ] Implement `_handle_tcp_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter)` async method
  - [ ] Log: `"TCP connection from {peer_addr}"`
  - [ ] Loop to receive frames until connection closes:
    - [ ] Read frame bytes with timeout (5 seconds)
    - [ ] On timeout: log warning, close connection
    - [ ] On `ConnectionResetError`/`BrokenPipeError`: log and exit loop
    - [ ] Call `_parse_frame(data)` to validate
    - [ ] On parse error: log warning, close connection
    - [ ] On success: pass to scenario handler for response (Task 5)
  - [ ] Cleanup: close writer via `writer.close()` + `await writer.wait_closed()`
  - [ ] [Source: daemon-design.md § "Component 0 — Transport Layer"]

### Task 6: Scenario Handler (Response Decision)
- [ ] Implement `_get_response(frame_dict: dict) -> bytes | None` method
  - [ ] Input: parsed frame dict (id_type, seq, account, timestamp, etc.)
  - [ ] Decision logic:
    - [ ] If `id_type == "NULL"` (supervision): respond with `encode_ack(seq, account)`
    - [ ] If `id_type == "SIA-DCS"` (alarm): respond with `encode_ack(seq, account)` (default)
    - [ ] If `id_type == "*NULL"` (encrypted supervision): decrypt, validate timestamp, respond with encrypted ACK
    - [ ] If `id_type == "*SIA-DCS"` (encrypted alarm): decrypt, validate event, respond with ACK
    - [ ] If timestamp invalid: respond with `encode_nak(seq, account, reason='TIMESTAMP')`
    - [ ] Return bytes (ACK/NAK frame) or `None` for no response (scenario: simulate timeout)
  - [ ] [Source: epics.md Story 2.2 "Generate CSR Responses"]

### Task 7: Encryption Support (Decryption)
- [ ] Implement `_decrypt_if_needed(frame_dict: dict, encryption_key: bytes) -> dict` method
  - [ ] Check if `frame_dict['encrypted'] == True`
  - [ ] If encrypted: call `sia_crypto.decrypt_message(frame_dict['raw_nak'], encryption_key)`
  - [ ] If decryption fails: log error, set flag `decryption_failed: True` in dict
  - [ ] If plaintext: return dict unchanged
  - [ ] Update frame_dict with decrypted content (account, zone, timestamp)
  - [ ] [Source: daemon-design.md § "Component 0 — sia_crypto.py integration"]

### Task 8: Ring Buffer for Frame Logging
- [ ] Implement `_add_to_ring_buffer(frame_entry: dict)` method
  - [ ] Create class attribute: `_frame_buffer: deque[dict]` with maxlen=100
  - [ ] Store: timestamp, source (UDP/TCP), src_addr, raw_hex, parsed dict, response sent
  - [ ] Timestamp: `datetime.now(timezone.utc)` (timezone-aware UTC)
  - [ ] Max 100 entries; oldest automatically discarded on overflow
  - [ ] [Source: logging-design.md § "Ring Buffer Structure"]

### Task 9: Main Simulator Lifecycle
- [ ] Create `CSRSimulator` class with async lifecycle:
  - [ ] `__init__(config: dict)` — initialize with listen_host, udp_port, tcp_port, encryption_key (optional)
    - [ ] All attributes documented in docstring with Instance Variables section
    - [ ] `_udp_socket`, `_tcp_server`, `_tasks`, `_frame_buffer`, `_logger`, `_encryption_key`
    - [ ] Instance Variables section in docstring (required per code-style.md)
  - [ ] `async def start()` — start both UDP and TCP listeners:
    - [ ] Call `_setup_udp_listener()` and `_setup_tcp_listener()`
    - [ ] Create task for UDP recv loop: `asyncio.create_task(self._udp_loop())`
    - [ ] Store task refs in `_tasks` set
    - [ ] Log: `"CSR Simulator started on UDP {udp_port} and TCP {tcp_port}"`
    - [ ] Track task completion with done callback
  - [ ] `async def stop()` — graceful shutdown:
    - [ ] Cancel all tasks in `_tasks`
    - [ ] Close UDP socket
    - [ ] Close TCP server
    - [ ] Await task cancellation
    - [ ] Log: `"CSR Simulator stopped"`
  - [ ] `async def _udp_loop()` — receive frames on UDP until cancelled:
    - [ ] Create UDP socket and bind via `_setup_udp_listener()`
    - [ ] Loop: `recvfrom()` frame, call `_handle_udp_frame(data, addr)`
    - [ ] On `asyncio.CancelledError`: exit cleanly

### Task 10: Logging & Debugging Output
- [ ] Implement logging for all major events:
  - [ ] `logging.getLogger(__name__)` at module level (not global)
  - [ ] Log format: `"[SIMULATOR] {level}: {message}"` (consistent with daemon)
  - [ ] DEBUG: frame arrival, parsing, response decision
  - [ ] INFO: listener startup, frame counts
  - [ ] WARNING: malformed frame, timestamp invalid, decryption error
  - [ ] ERROR: socket bind failure, shutdown errors
  - [ ] All timestamps in UTC timezone-aware format
  - [ ] [Source: logging-design.md § "Logging Infrastructure"]

### Task 11: Unit Tests (pytest)
- [ ] Create `tests/level1/test_csr_simulator.py` with pytest fixtures
  - [ ] Fixture: `simulator_config()` — test config dict with ports 10001/5000
  - [ ] Fixture: `simulator_instance()` — instantiated CSRSimulator
  - [ ] Fixture: `udp_client_socket()` — UDP socket for sending test frames
  - [ ] Fixture: `tcp_client_connection()` — TCP connection for sending test frames
- [ ] Test UDP listening:
  - [ ] Simulator accepts UDP frames without error
  - [ ] Received frame is parsed and logged
  - [ ] Multiple frames in sequence are handled
- [ ] Test TCP listening:
  - [ ] Simulator accepts TCP connections
  - [ ] Frames sent via TCP are received and parsed
  - [ ] Connection closed gracefully after frame
- [ ] Test frame parsing:
  - [ ] Valid SIA-DCS frame is parsed correctly
  - [ ] Valid NULL supervision frame is parsed
  - [ ] Malformed frame raises `SIAProtocolError`
  - [ ] Invalid CRC triggers error (no response sent)
- [ ] Test response generation:
  - [ ] NULL message → ACK response
  - [ ] SIA-DCS message → ACK response
  - [ ] Invalid timestamp → NAK response
- [ ] Test ring buffer:
  - [ ] Frames added in order
  - [ ] Buffer does not exceed 100 entries
  - [ ] Oldest entries discarded on overflow
- [ ] Test lifecycle:
  - [ ] Start/stop sequence works
  - [ ] Tasks properly tracked and cancelled on stop
  - [ ] No orphaned sockets after stop
- [ ] Test encrypted frame handling (with mocked decryption):
  - [ ] Encrypted frame flagged correctly
  - [ ] Decryption called with correct key
  - [ ] Decryption error handled gracefully
- [ ] **Coverage goal:** >90% of simulator code (excluding CLI tool—Story 2.3)

---

## Dev Notes

### Architecture Compliance

**File Location:** `tests/simulator/csr_simulator.py`
**Purpose:** Standalone testing tool—NOT part of production daemon, NOT imported by Jeedom plugin
[Source: daemon-design.md — Component 0: csr_simulator.py (development tool)]

**Dependency Rules:**
- Imports only from `sia_protocol.py` (no Jeedom, no asyncio in sia_protocol)
- Imports `sia_crypto.py` for decryption only
- Zero production daemon dependencies
- Can be run standalone: `python -m tests.simulator.csr_simulator --udp-port 10001 --tcp-port 5000`
[Source: daemon-design.md § "Dependency Rules"]

**Key Architectural Patterns:**

1. **Asyncio-Based Concurrency:** CSR simulator uses Python asyncio for simultaneous UDP and TCP listening. Both listeners are independent coroutines with separate socket lifecycle.
2. **Frame Parsing Contract:** Frame validation delegates to `sia_protocol.decode_message()` (Story 1.3) and `validate_timestamp()`. Simulator is NOT responsible for re-implementing protocol validation.
3. **Scenario-Driven Response:** Response decision is separated from socket handling. `_get_response()` encapsulates decision logic for ACK/NAK/timeout selection—easily extended for Story 2.2 (configurable responses) and Story 2.3 (scenario scripting).
4. **Ring Buffer for Observability:** All frames logged to in-memory ring buffer (max 100 entries) for debugging. Oldest entries discarded on overflow—prevents unbounded memory growth.
5. **Exception Hierarchy:** Uses `SIATransportError` (socket failures) and `SIAProtocolError` (frame parse failures) from sia_protocol.py. Never catches `asyncio.CancelledError` implicitly.

### Technical Stack

- **Language:** Python 3.10+ (asyncio native support)
- **Protocol Parsing:** Delegates to `sia_protocol.py` (Story 1.1)
- **Encryption Decryption:** Delegates to `sia_crypto.py` (Story 1.2)
- **Frame Validation:** Uses `decode_message()` + `validate_timestamp()` from sia_protocol.py
- **Networking:** Python asyncio (no third-party networking libraries)
- **Logging:** Python `logging` module (consistent with daemon)

### Code Structure Requirements

**Module Structure:**

```
csr_simulator.py
├── Module docstring (purpose: development testing tool)
├── Constants
│   ├── DEFAULT_UDP_PORT = 10001
│   ├── DEFAULT_TCP_PORT = 5000
│   ├── DEFAULT_LISTEN_HOST = '127.0.0.1' (localhost only)
│   ├── FRAME_BUFFER_SIZE = 100
│   ├── TCP_READ_TIMEOUT = 5.0
│   └── SIMULATOR_VERSION = "0.1"
│
├── Exception classes (import from sia_protocol)
│   ├── SIATransportError
│   └── SIAProtocolError
│
└── CSRSimulator (class)
    ├── __init__(config: dict) → None
    │   └── Instance Variables (documented in docstring)
    │       ├── _listen_host: str
    │       ├── _udp_port: int
    │       ├── _tcp_port: int
    │       ├── _encryption_key: Optional[bytes]
    │       ├── _udp_socket: Optional[socket.socket]
    │       ├── _tcp_server: Optional[asyncio.Server]
    │       ├── _tasks: set[asyncio.Task]
    │       ├── _frame_buffer: deque[dict] (maxlen=100)
    │       ├── _logger: logging.Logger
    │       └── _running: bool
    │
    ├── async def start() → None
    ├── async def stop() → None
    ├── async def get_frame_history() → list[dict]
    │
    ├── Private methods:
    │   ├── async def _udp_loop() → None
    │   ├── async def _setup_udp_listener() → socket.socket
    │   ├── async def _setup_tcp_listener() → asyncio.Server
    │   ├── async def _handle_tcp_connection(reader, writer) → None
    │   ├── async def _handle_udp_frame(data, addr) → None
    │   ├── def _parse_frame(raw: bytes) → dict
    │   ├── def _get_response(frame_dict: dict) → bytes | None
    │   ├── def _decrypt_if_needed(frame_dict: dict, key: bytes) → dict
    │   └── def _add_to_ring_buffer(frame_entry: dict) → None
```

**Naming Conventions:**

- Public class: `CSRSimulator`
- Public methods: `start()`, `stop()`, `get_frame_history()`
- Private methods: `_setup_udp_listener()`, `_handle_udp_frame()`, `_parse_frame()`, etc.
- Constants: `UPPERCASE` (e.g., `DEFAULT_UDP_PORT`, `FRAME_BUFFER_SIZE`)
- Instance attributes: `_snake_case` with leading underscore (private)

### Testing Standards

- **Framework:** pytest
- **Test Location:** `tests/level1/test_csr_simulator.py` (synchronous unit tests)
- **Fixtures:** simulator instance, UDP/TCP client sockets for integration
- **Coverage:** >90% of simulator code (focus on critical paths: frame parsing, response logic, lifecycle)
- **Async Testing:** Use `pytest-asyncio` for async fixture and test functions
  - Never use bare `await asyncio.sleep()` for synchronization—use `await asyncio.gather(*tasks)`
  - Join daemon tasks after state changes: `await asyncio.gather(*simulator._tasks)`
- **Test Categories:**
  1. **Frame Parsing:** Valid/invalid frame structures, CRC validation, delimiter detection
  2. **UDP Reception:** Single frame, multiple frames, burst reception
  3. **TCP Reception:** Connection acceptance, frame parsing, graceful close
  4. **Response Generation:** ACK/NAK decision, encryption handling
  5. **Lifecycle:** Start, stop, task cleanup, socket resource cleanup
  6. **Ring Buffer:** Entry insertion, overflow behavior, max capacity

[Source: testing.md — "Test Writing Standards" + "Async Testing Rules"]

### File Structure & Dependencies

**Files This Story Creates/Modifies:**

1. **CREATED:** `tests/simulator/csr_simulator.py` (main simulator with `CSRSimulator` class)
2. **CREATED:** `tests/level1/test_csr_simulator.py` (pytest unit tests)
3. **REFERENCE (read-only):** `resources/siadc09d/sia_protocol.py` (protocol parsing, validation)
4. **REFERENCE (read-only):** `resources/siadc09d/sia_crypto.py` (decryption for encrypted frames)
5. **REFERENCE (read-only):** `docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` (spec)
6. **REFERENCE (read-only):** `docs/design/daemon-design.md` (architecture patterns)

**Dependencies on Other Stories:**

- **HARD DEPENDENCY:** Story 1.1 (SIA Protocol Message Builder) — uses `sia_protocol.py`
- **SOFT DEPENDENCY:** Story 1.2 (AES-128 Encryption) — optional encryption handling
- **No reverse dependencies:** This is a testing tool only; no production code depends on it

### API Usage Patterns

**Basic Simulator Usage:**
```python
import asyncio
from tests.simulator.csr_simulator import CSRSimulator

# Create simulator with default config
config = {
    'listen_host': '127.0.0.1',
    'udp_port': 10001,
    'tcp_port': 5000,
    'encryption_key': None  # Or bytes if testing encrypted frames
}

simulator = CSRSimulator(config)

# Start listening
await simulator.start()

# Simulator is now accepting connections on both UDP and TCP
# (sending frames from another process will be received and logged)

# Stop when done
await simulator.stop()
```

**Inspecting Received Frames:**
```python
# Get all frames received since simulator started
history = await simulator.get_frame_history()
for entry in history:
    print(f"Received {entry['protocol']} from {entry['src_addr']}")
    print(f"  Frame: {entry['raw_hex']}")
    print(f"  Parsed: {entry['parsed']}")
```

**Testing Against Simulator:**
```python
# Send a NULL supervision message via UDP
import socket
from tests.simulator.csr_simulator import DEFAULT_UDP_PORT
from resources.siadc09d.sia_protocol import SIAMessageBuilder

builder = SIAMessageBuilder(crc_format="SIA")
frame = builder.make_supervision_message(account_number="001234")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(frame, ('127.0.0.1', DEFAULT_UDP_PORT))
```

---

## Dev Agent Record

### Agent Model Used

Claude Haiku 4.5 (claude-haiku-4-5-20251001)

### Debug Log References

- Loaded sprint-status.yaml to identify first backlog story: `2-1-simulator-framework-udp-tcp-listen`
- Analyzed Epic 2 context from epics.md (CSR Simulator scope, dependencies, rationale)
- Cross-referenced daemon-design.md Component 0 for simulator architecture patterns
- Validated task breakdown against sia_protocol.py API surface (Stories 1.1, 1.2)

### Completion Notes

Story file created following established pattern from Story 1.1. Comprehensive task breakdown with acceptance criteria mapping. All tasks specify file locations, source references (spec § section numbers), and architecture compliance notes.

### File List

- `/Users/herve.lehoux/Dev/my-project/_bmad-output/implementation-artifacts/2-1-simulator-framework-udp-tcp-listen.md` (this story file)
- Will create: `tests/simulator/csr_simulator.py`
- Will create: `tests/level1/test_csr_simulator.py`
