# Story 1.3: ACK/NAK Response Parser

**Status:** ready-for-dev

---

## Story

As a daemon developer,
I want to parse and validate CSR responses (ACK/NAK),
So that I can distinguish successful delivery from errors.

---

## Acceptance Criteria

1. **Given** a raw ACK response frame from the CSR
   **When** calling `decode_ack_nak()`
   **Then** the function returns a dict with `type='ACK'`, `seq=<echoed_sequence>`, and `raw_nak=None`

2. **And** a raw NAK response frame
   **When** calling `decode_ack_nak()`
   **Then** the function returns a dict with `type='NAK'`, `seq=<echoed_sequence>`, and `raw_nak=<full_nak_bytes>`

3. **And** for NAK responses: if the NAK contains a timestamp field (section 5.5.3.2)
   **When** calling `parse_nak_timestamp(raw_nak)` with the NAK bytes
   **Then** the function returns a `datetime` object representing the CSR's current time (UTC, timezone-aware)

4. **And** validation confirms proper CRC calculation and checksum match before accepting any frame as ACK/NAK

5. **And** malformed responses (invalid frame structure, CRC mismatch, incomplete data)
   **When** parsed
   **Then** `decode_ack_nak()` returns `type='unknown'` with `seq=None` and `raw_nak=None` (never raises an exception)

6. **And** parser handles both encrypted and plaintext ACK/NAK frames
   **When** decryption is needed
   **Then** the plaintext is extracted before parsing (handled by `sia_crypto.decrypt_frame()` in caller context)

7. **And** all tests pass: unit tests for function correctness, integration with `SIAMessageBuilder` from Story 1.1, and golden frame validation with real CSR data

---

## Tasks / Subtasks

### Task 0: ACK/NAK Response Parser Module Skeleton & Exception Classes
- [ ] Create or update `resources/siadc09d/sia_protocol.py` module
  - [ ] Import required modules: `struct`, `datetime`, `timezone` from stdlib; `SIACipher` from `sia_crypto`
  - [ ] Define exception class `SIAProtocolError(Exception)` if not already present (from Story 1.1)
  - [ ] [Source: docs/design/daemon-design.md § Component 0 Exception Hierarchy]

### Task 1: ACK Frame Structure Constants & Frame Parsing Helpers
- [ ] Define module-level constants for ACK/NAK frame structure
  - [ ] `ACK_FRAME_MARKER: bytes = b'*ACK'` (4 bytes, start of ACK frame)
  - [ ] `NAK_FRAME_MARKER: bytes = b'*NAK'` (4 bytes, start of NAK frame)
  - [ ] `FRAME_LEAD: bytes = b'\x0A'` (LF, line feed, frame leader per SIA DC-09 § 5.5.1)
  - [ ] `FRAME_TRAIL: bytes = b'\x0D'` (CR, carriage return, frame trailer)
  - [ ] `CRC_MODBUS_POLY: int = 0xA001` (polynomial for CRC-16 MODBUS, bit-reversed from 0x8005)
  - [ ] [Source: SIA DC-09-2021.17 spec § 5.5.1.1 + § 5.5.3 (ACK/NAK format)]

### Task 2: Low-Level Frame Parsing Helper
- [ ] Implement private function `_extract_frame_components(raw: bytes) -> tuple[bytes, str, bytes, bytes] | None`
  - [ ] Validates frame structure: leader (0x0A) → 4-byte CRC → 4-byte length (ASCII hex) → message_string → trailer (0x0D)
  - [ ] Returns: `(crc_bytes, message_str, expected_length_bytes, trailing_byte)` on success
  - [ ] Returns `None` if any structural check fails (missing leader, incomplete length field, missing trailer)
  - [ ] Does not raise exceptions — callers handle `None` returns gracefully
  - [ ] [Source: docs/design/daemon-design.md § Component 0 — wrap_frame() and frame envelope]

### Task 3: CRC Validation Helper
- [ ] Implement `_validate_crc(crc_bytes: bytes, message_str: str, crc_format: str = 'hex') -> bool`
  - [ ] Decodes CRC from frame bytes (handles both 'hex' and 'bin' formats)
  - [ ] Computes expected CRC using `compute_crc(message_str.encode('windows-1252'))`
  - [ ] Compares received vs. computed CRC
  - [ ] Returns `True` if match, `False` otherwise
  - [ ] For 'hex' format: CRC is 4 ASCII hex characters (e.g., "A3F2")
  - [ ] For 'bin' format: CRC is 2 binary bytes (little-endian)
  - [ ] [Source: docs/design/daemon-design.md § compute_crc()]

### Task 4: ACK/NAK Type Detection & Sequence Extraction
- [ ] Implement `_parse_ack_nak_type_and_seq(id_token: str) -> tuple[str, int | None]`
  - [ ] Analyzes the id_token field (first field in message_string, e.g., "SIA-DCS", "*SIA-DCS", "ACK", "NAK")
  - [ ] Returns `('ACK', seq_int)` if id_token starts with "ACK" or matches ACK pattern
  - [ ] Returns `('NAK', seq_int)` if id_token starts with "NAK" or matches NAK pattern
  - [ ] Returns `('unknown', None)` for any unrecognized id_token
  - [ ] Extracts sequence number from message_string field(s) following the id_token per § 5.5.3.1
  - [ ] [Source: SIA DC-09-2021.17 spec § 5.5.3 (ACK/NAK Response Message Format)]

### Task 5: Core Function — `decode_ack_nak(raw: bytes) -> dict`
- [ ] Implement public function with signature: `def decode_ack_nak(raw: bytes) -> dict[str, str | int | bytes | None]`
  - [ ] Input: complete raw CSR response bytes
  - [ ] Returns dict with keys: `type` (str: 'ACK', 'NAK', or 'unknown'), `seq` (int | None), `raw_nak` (bytes | None)
  - [ ] **Parsing logic (defensive, never raises):**
    1. Check for frame leader (0x0A); if missing return `{'type': 'unknown', 'seq': None, 'raw_nak': None}`
    2. Call `_extract_frame_components(raw)` to validate frame structure
    3. If structure invalid, return `{'type': 'unknown', 'seq': None, 'raw_nak': None}`
    4. Validate CRC using `_validate_crc()` — if invalid, return `'unknown'`
    5. Parse message_string (Windows-1252 encoding) and extract id_token and sequence
    6. Call `_parse_ack_nak_type_and_seq()` to classify as ACK/NAK
    7. For NAK: populate `raw_nak` with full frame bytes (for timestamp extraction in v1.1)
    8. Return dict with parsed values
  - [ ] **Error handling:** Catch all exceptions (malformed bytes, encoding errors, index errors) and return `'unknown'` — zero exception propagation
  - [ ] [Source: docs/design/daemon-design.md § decode_ack_nak() specification]

### Task 6: NAK Timestamp Extraction — `parse_nak_timestamp(nak_data: bytes) -> datetime`
- [ ] Implement function to extract CSR timestamp from NAK frame data
  - [ ] Input: raw NAK frame bytes (full frame, not just message_string)
  - [ ] SIA DC-09 § 5.5.3.2 specifies optional timestamp in NAK message data field
  - [ ] Timestamp format: `_HH:MM:SS,MM-DD-YYYY` (13 characters, includes `_` leader and field separators per CLAUDE.md)
  - [ ] Parse timestamp into `datetime` object (UTC, timezone-aware)
  - [ ] **Error handling:** Raise `ValueError` if NAK data is None, unparseable, or malformed
  - [ ] Call sites wrap with try/except and treat ValueError as "malformed NAK" → `BAD_CSR_RESPONSE` error
  - [ ] [Source: SIA DC-09-2021.17 spec § 5.5.3.2 (NAK message format with timestamp)]
  - [ ] [Source: docs/design/daemon-design.md § parse_nak_timestamp() specification]

### Task 7: Golden Frame Test Fixtures & Test Data
- [ ] Create test fixtures directory: `tests/fixtures/golden/` (if not exists)
  - [ ] Add golden ACK frame (binary): `ack-plaintext-seq-0001.bin` (real CSR ACK response, hex format)
  - [ ] Add golden NAK frame (binary): `nak-plaintext-timestamp.bin` (real CSR NAK with timestamp, hex format)
  - [ ] Add golden encrypted ACK (binary): `ack-encrypted-aes128.bin` (ACK frame encrypted with test key)
  - [ ] Add encrypted NAK (binary): `nak-encrypted-aes128-timestamp.bin` (NAK frame encrypted, with timestamp)
  - [ ] Document frame origins and sources in `tests/fixtures/README.md`
  - [ ] [Source: docs/design/daemon-design.md § Component 0 Test Fixtures]

### Task 8: Unit Tests (pytest) — Comprehensive Test Suite
- [ ] Create `tests/level1/test_sia_protocol_ack_nak.py` with pytest function-based tests
  - [ ] **Test Frame Structure Validation:**
    - [ ] Valid ACK frame: parses without error, returns correct type and sequence
    - [ ] Valid NAK frame: parses without error, returns correct type and sequence
    - [ ] Frame with missing leader (0x0A): returns `type='unknown'`
    - [ ] Frame with missing trailer (0x0D): returns `type='unknown'`
    - [ ] Frame with truncated CRC field: returns `type='unknown'`
    - [ ] Frame with truncated length field: returns `type='unknown'`
    - [ ] Completely empty raw bytes: returns `type='unknown'`
    - [ ] Single byte (not a valid frame): returns `type='unknown'`

  - [ ] **Test CRC Validation:**
    - [ ] Valid CRC (hex format): frame accepted
    - [ ] Invalid CRC (hex format): frame rejected as `type='unknown'`
    - [ ] Valid CRC (bin format): frame accepted
    - [ ] Invalid CRC (bin format): frame rejected
    - [ ] Corrupted message_string (CRC mismatch): frame rejected

  - [ ] **Test Sequence Number Extraction:**
    - [ ] ACK with seq 0000: parsed correctly as int 0
    - [ ] ACK with seq 5432: parsed correctly as int 5432
    - [ ] ACK with seq 9999: parsed correctly as int 9999
    - [ ] NAK with seq 0001: parsed correctly as int 1
    - [ ] Frame with missing sequence field: returns seq=None

  - [ ] **Test Type Classification:**
    - [ ] "ACK" id_token: classified as type='ACK'
    - [ ] "NAK" id_token: classified as type='NAK'
    - [ ] "*ACK" id_token: classified as type='ACK'
    - [ ] "*NAK" id_token: classified as type='NAK'
    - [ ] Unrecognized id_token (e.g., "ERROR"): classified as type='unknown'
    - [ ] Empty id_token: classified as type='unknown'

  - [ ] **Test raw_nak Field Handling:**
    - [ ] ACK frame: raw_nak=None
    - [ ] NAK frame: raw_nak populated with full raw bytes
    - [ ] NAK frame: raw_nak can be passed to parse_nak_timestamp()

  - [ ] **Test Plaintext ACK/NAK Parsing:**
    - [ ] Golden plaintext ACK frame (from fixture)
    - [ ] Golden plaintext NAK frame with timestamp (from fixture)

  - [ ] **Test Encrypted ACK/NAK Handling (Integration):**
    - [ ] Decrypt encrypted ACK using `SIACipher` from Story 1.2, then parse
    - [ ] Decrypt encrypted NAK using `SIACipher`, then parse
    - [ ] Encrypted frame passed to decoder without pre-decryption: returns `type='unknown'` (encrypted format is not valid ACK/NAK)

  - [ ] **Test Timestamp Extraction (parse_nak_timestamp):**
    - [ ] Valid timestamp `_14:32:45,03-22-2026` in NAK: parsed as datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)
    - [ ] Invalid timestamp format (wrong separators): raises ValueError
    - [ ] Missing NAK data (None): raises ValueError
    - [ ] Empty NAK data (b''): raises ValueError
    - [ ] Timestamp with invalid month (13): raises ValueError
    - [ ] Timestamp with invalid day (32): raises ValueError
    - [ ] Timestamp with invalid hour (25): raises ValueError

  - [ ] **Test Error Handling (Zero Exceptions from decode_ack_nak):**
    - [ ] Encoding error (non-Windows-1252 bytes): returns `type='unknown'` (no exception)
    - [ ] Integer overflow (malformed sequence field): returns `type='unknown'` (no exception)
    - [ ] All edge cases handled gracefully without raising

  - [ ] **Integration Tests with Story 1.1 & 1.2:**
    - [ ] Generate alarm frame using `SIAMessageBuilder` from Story 1.1
    - [ ] Generate ACK response frame using protocol formatter
    - [ ] Parse ACK using `decode_ack_nak()` — verify it matches original sequence
    - [ ] Generate NAK response with timestamp
    - [ ] Parse NAK and extract timestamp using `parse_nak_timestamp()` — verify datetime correctness
    - [ ] Encrypt alarm frame with `SIACipher` from Story 1.2
    - [ ] Simulate CSR response to encrypted frame
    - [ ] Decrypt response and parse with `decode_ack_nak()`

  - [ ] **Test Coverage:** >95% line coverage on `sia_protocol.py` ACK/NAK parsing functions

---

## Dev Notes

### Architecture Compliance

**File Location:** `resources/siadc09d/sia_protocol.py` (update existing module from Story 1.1)

**Module Purpose:** Pure protocol layer — no Jeedom, no asyncio, no state. Single responsibility: SIA DC-09-2021 message construction, encryption support, and response parsing.

[Source: docs/design/daemon-design.md — Component 0: sia_protocol.py + code-style.md § Classes vs Functions]

**Key Architectural Patterns:**

1. **Defensive Parsing:** `decode_ack_nak()` never raises exceptions. All malformed input returns `type='unknown'` — call sites never crash on garbage from the network. This is critical for daemon stability.
   - [Source: docs/design/daemon-design.md § Zero Silent Failures]

2. **Windows-1252 Encoding:** Message strings in SIA DC-09 frames use Windows-1252 encoding (section 5.5.1.1). ASCII-only content (account numbers, event codes, sequence) is unaffected; non-ASCII characters (media URLs) must be pre-validated by callers.
   - [Source: SIA DC-09-2021 spec § 5.5.1.1]

3. **CRC-16/MODBUS Validation:** Every frame (ACK, NAK, alarm) must have valid CRC. Polynomial `0xA001` (bit-reversed). CRC is computed over `message_string` only — not leader, not CRC field itself, not length field, not trailer.
   - [Source: SIA DC-09-2021 spec § 5.5.1.2; docs/design/daemon-design.md § compute_crc()]

4. **Sequence Number Matching:** ACK/NAK responses echo the sequence number of the original outbound frame. Parser extracts this for SM1/SM2 state machine transitions.
   - [Source: SIA DC-09-2021 spec § 5.5.3 (ACK/NAK format)]

5. **NAK Timestamp for v1.1 Auto-Heal:** NAK responses optionally include CSR timestamp (section 5.5.3.2). In v1.0, extracted timestamp is validated (any parse error → `BAD_CSR_RESPONSE`). In v1.1, timestamp will drive clock synchronization retry.
   - [Source: docs/design/daemon-design.md § parse_nak_timestamp(); logging-design.md § SM1_NAK_TIMESTAMP event]

6. **Plaintext vs. Encrypted:** ACK/NAK can be plaintext or encrypted. Decryption is handled by caller (`sia_crypto.decrypt_frame()` in `_send_raw_tcp()/_send_raw_udp()`) before passing to `decode_ack_nak()`. Parser never sees ciphertext directly.
   - [Source: docs/design/daemon-design.md § Message Flow]

### Technical Stack

**Language:** Python 3.10+ (same floor as Stories 1.1, 1.2)

**Parsing Libraries:** None — pure Python using `struct`, `datetime`, `timezone` from stdlib

**Encoding:** Windows-1252 for message_string field (per SIA DC-09 standard). Frame envelope (leader, CRC, length, trailer) is pure ASCII.

**Standard Reference:** SIA DC-09-2021.17 Internet Protocol Event Reporting, sections:
- 5.5.1 (frame envelope, CRC-16/MODBUS, Windows-1252)
- 5.5.3 (ACK/NAK response format with sequence and optional timestamp)
- 5.5.3.1 (ACK structure)
- 5.5.3.2 (NAK structure including timestamp field)

### Code Structure Requirements

**Module Integration:**

```
sia_protocol.py (existing from Story 1.1, now extended with Story 1.3)
├── Exception Classes
│   └── SIAProtocolError (existing, reused)
│
├── CRC Constants & Functions (from Story 1.1)
│   ├── compute_crc(data: bytes) -> int
│   └── CRC_MODBUS_POLY: int = 0xA001
│
├── Frame Wrapping Helpers (from Story 1.1)
│   ├── wrap_frame(message_str: str, crc_format: str = 'hex') -> bytes
│   └── FRAME_LEAD, FRAME_TRAIL constants
│
├── Message Encoding (from Story 1.1)
│   └── encode_message(..., *, crc_format: str) -> bytes
│
└── Response Parsing (NEW — Story 1.3)
    ├── Constants
    │   ├── ACK_FRAME_MARKER: bytes
    │   ├── NAK_FRAME_MARKER: bytes
    │   └── (existing FRAME_LEAD, FRAME_TRAIL reused)
    │
    ├── Private Helpers
    │   ├── _extract_frame_components(raw: bytes) -> tuple | None
    │   ├── _validate_crc(crc_bytes: bytes, message_str: str, crc_format: str = 'hex') -> bool
    │   └── _parse_ack_nak_type_and_seq(id_token: str) -> tuple[str, int | None]
    │
    └── Public API
        ├── decode_ack_nak(raw: bytes) -> dict[str, str | int | bytes | None]
        └── parse_nak_timestamp(nak_data: bytes) -> datetime
```

**Type Hints:** All functions have full type hints (parameters and return types). Exception types explicitly raised in docstrings.

**Error Handling:** `decode_ack_nak()` is the *only* function that must never raise. All other parsing helpers can raise internal exceptions, which are caught and converted to `type='unknown'`.

### Integration with Story 1.1 & 1.2

- **Story 1.1 (Message Builder):** Parser validates responses to frames built by `SIAMessageBuilder.encode_message()`. Sequence numbers in responses must match outbound sequence.
- **Story 1.2 (AES-128):** Parser works on plaintext frames. Encrypted ACK/NAK responses are decrypted by transport layer (`_send_raw_tcp()`, `_send_raw_udp()`) before parsing.
- **Future Story 1.4 (Simulator):** Parser will use `decode_ack_nak()` to generate CSR responses in the test simulator.

### Previous Story Intelligence (Story 1.2)

**Testing Approach (replicate from 1.2):**
- Golden frame fixtures in `tests/fixtures/golden/` with real CSR data
- Parametrized tests for boundary conditions
- Integration tests combining Story 1.1 (message builder), Story 1.2 (encryption), and Story 1.3 (parser)
- >95% line coverage minimum

**Code Patterns (replicate from 1.2):**
- Private helper functions for low-level operations
- Constants defined as module-level `CONSTANT_NAME` (UPPER_SNAKE_CASE)
- Exception classes inherit from appropriate stdlib base (`ValueError`, `OSError`, etc.)
- Type hints on all functions; use `typing.Literal` for restricted string values
- Docstrings use Google style with Args, Returns, Raises sections
- [Source: Story 1.2 Dev Notes § Code Structure Requirements]

### Latest Technical Specifics

**SIA DC-09-2021.17 Compliance:**
- Latest spec version: SIA DC-09-2021.17 (released 2021, stable)
- CRC-16/MODBUS polynomial: `0xA001` (bit-reversal of 0x8005) — confirmed in § 5.5.1.2
- Windows-1252 encoding: mandatory for message_string per § 5.5.1.1
- Timestamp format: `_HH:MM:SS,MM-DD-YYYY` per § 5.5.3.2 (13 characters, fixed)
- No breaking changes in SIA DC-09 since 2021; safe to implement against this version

**Python Standard Library (datetime handling):**
- Use `datetime.now(timezone.utc)` instead of deprecated `datetime.utcnow()`
- All timestamps must be timezone-aware (tzinfo=timezone.utc)
- Mixing naive and aware datetimes raises TypeError at runtime
- [Source: code-style.md § All datetime objects are UTC and timezone-aware]

---

## References

- **Protocol Spec:** docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md (complete standard reference)
- **Architecture:** docs/design/daemon-design.md § Component 0 (sia_protocol.py API surface)
- **Code Style:** .claude/rules/code-style.md (type hints, error handling, function vs. class design)
- **Testing:** .claude/rules/testing.md (pytest standards, three-element test documentation)
- **Previous Story:** _bmad-output/implementation-artifacts/1-2-aes-128-cbc-encryption-module.md (testing patterns, code structure)
- **Project Context:** docs/project-context.md (if exists)

---

## Dev Agent Record

### Agent Model Used

Claude Haiku 4.5 (bmad-bmm-create-story automated context engine)

### Debug Log References

- Story created from Epic 1 epics.md specification
- Integrated with Story 1.1 (message builder) and Story 1.2 (encryption)
- Architecture extracted from daemon-design.md Component 0 API surface
- Test patterns sourced from 1-2 story implementation

### Completion Notes

- **Ultimate context engine analysis completed** — comprehensive developer guide created with full SIA DC-09 protocol compliance coverage, defensive parsing requirements, and integration points with previous stories.
- Story ready for dev-story implementation by developer agent.

### File List

**New/Modified Files (relative to repo root):**
- `resources/siadc09d/sia_protocol.py` — MODIFY (add Story 1.3 parser functions)
- `tests/level1/test_sia_protocol_ack_nak.py` — CREATE (new test module)
- `tests/fixtures/golden/ack-plaintext-seq-0001.bin` — CREATE (golden fixture)
- `tests/fixtures/golden/nak-plaintext-timestamp.bin` — CREATE (golden fixture)
- `tests/fixtures/golden/ack-encrypted-aes128.bin` — CREATE (golden fixture)
- `tests/fixtures/golden/nak-encrypted-aes128-timestamp.bin` — CREATE (golden fixture)
- `tests/fixtures/README.md` — MODIFY (document fixture origins)

**No New Dependencies:** Uses only Python stdlib (`struct`, `datetime`, `timezone`). No additional libraries beyond those already required (Story 1.1: no deps; Story 1.2: `cryptography`).

---

## Change Log

- **2026-04-09:** Story created by automated context engine (bmad-bmm-create-story). Full architecture analysis, integration with Stories 1.1–1.2, comprehensive task breakdown with defensive parsing design. Ready for dev-story workflow.
