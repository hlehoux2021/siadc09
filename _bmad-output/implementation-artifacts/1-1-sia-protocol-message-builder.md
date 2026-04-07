# Story 1.1: SIA Protocol Message Builder

**Status:** review

---

## Story

As a protocol developer,
I want to construct and serialize SIA DC-09 compliant message frames,
so that the daemon can send properly formatted frames to the CSR.

---

## Acceptance Criteria

1. **Given** a message payload (account number, event code, checksum data)
   **When** building an alarm message frame
   **Then** the output is a properly framed SIA message with correct delimiter, sequence, CRC, and checksum

2. **And** encryption-ready plaintext is generated when AES-128 encryption is specified

3. **And** the message adheres to SIA DC-09-2021 spec for burglary, fire, and panic events

4. **And** supervision NULL messages are constructable with zero payload

---

## Tasks / Subtasks

### Task 0: Protocol Module Skeleton
- [ ] Create `resources/siadc09d/sia_protocol.py` with module docstring referencing spec
  - [ ] Import core modules: zlib, datetime
  - [ ] Define CRC format constants (per preset configuration)
  - [ ] Add implementation for `encode_message()` and `SIA_NULL_CODE` constant

### Task 1: Message Frame Structure Constants
- [ ] Define constants for SIA DC-09 frame components:
  - [ ] `LF = b'\x0A'` (line feed delimiter, binary)
  - [ ] `CR = b'\x0D'` (carriage return delimiter, binary)
  - [ ] `SIA_NULL_CODE = "0000"` (null event code for supervision)
  - [ ] Event type constants: `BURGLARY = "1"`, `FIRE = "2"`, `PANIC = "3"` (per SIA code mapping)
- [ ] Version/token constants: `SIA_DCS_TOKEN = "SIA-DCS"` (unencrypted), encrypted token support

### Task 2: Message Length & CRC Calculation
- [ ] Implement `calculate_crc(data: bytes, crc_format: str) -> str` function:
  - [ ] Input: plaintext bytes from first quote to CR (excluding CR)
  - [ ] Output: 4-character ASCII hex CRC (uppercase)
  - [ ] Use preset-configured CRC format (ADM, SIA per architecture)
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.2]
- [ ] Implement `calculate_length(data: bytes) -> str` function:
  - [ ] Format: "0" + 3-digit hex length (e.g., "0123" = 291 bytes)
  - [ ] Count only CRC-included bytes (first quote to CR)
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.3]

### Task 3: Sequence Number Management
- [ ] Create class `SequenceManager`:
  - [ ] Maintain separate sequence counter per account_number (dict-based)
  - [ ] Wrap from 9999 → 0001 (not 0000)
  - [ ] Format sequence as 4-character ASCII decimal (e.g., "0001", "9999")
  - [ ] Method: `next_seq(account_number: str) -> str` — increments and returns
  - [ ] Method: `current_seq(account_number: str) -> str` — returns without incrementing
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.5]

### Task 4: Account Identification Fields
- [ ] Implement `format_account_id(account_number: str, account_prefix: str = "L0", receiver_number: str = None) -> str` function:
  - [ ] Account number: `#` + 3-16 hex ASCII characters
  - [ ] Account prefix: `L` + 1-6 hex ASCII digits (required; default "L0" if not programmed)
  - [ ] Receiver number: `R` + 1-6 hex ASCII digits (optional; omit if not present or "0")
  - [ ] Return combined string (e.g., `"#001234L1R2"`)
  - [ ] Validate hex characters in account_number and prefix
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.6]

### Task 5: Message Data Field (Unencrypted)
- [ ] Implement `format_data_field(account_number: str, event_code: str, extended_data: dict = None) -> str` function:
  - [ ] Structure: `[#{account}|{event_code}...]` (brackets included)
  - [ ] Event code: 4 ASCII hex characters (e.g., "1130" for burglary, "2130" for fire)
  - [ ] Framework for optional extended data fields (implemented in v1.1+)
  - [ ] No padding in unencrypted mode (padding is for encrypted only)
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.7]

### Task 6: Timestamp Field
- [ ] Implement `format_timestamp(ts: datetime = None) -> str` function:
  - [ ] Input: datetime object or None (use current time)
  - [ ] Format: 10 ASCII hex characters representing seconds since epoch (Unix time)
  - [ ] Example: timestamp=2026-04-07 15:30:00 UTC → hex equivalent
  - [ ] No separators (no colons, no underscores)
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.9]

### Task 7: Core `encode_message()` Function
- [ ] Implement `encode_message(account_number: str, event_code: str, account_prefix: str = "L0", receiver_number: str = None, extended_data: dict = None, timestamp: datetime = None, *, crc_format: str, encryption: bool = False) -> bytes`:
  - [ ] **CRITICAL:** `crc_format` is keyword-only with no default (enforces explicit preset config)
  - [ ] Build message in correct order per spec:
    1. [x] `LF` (`\x0A`)
    2. [x] CRC field (4 ASCII hex)
    3. [x] `0LLL` length field (4 bytes)
    4. [x] ID token: `"SIA-DCS"` or `"*SIA-DCS"` per encryption flag
    5. [x] Sequence number (4 digits, preset config)
    6. [x] Receiver number (optional)
    7. [x] Account prefix (required)
    8. [x] Account ID (required)
    9. [x] Data field `[#{account}|{event_code}...]`
    10. [x] Timestamp
    11. [x] `CR` (`\x0D`)
  - [ ] Calculate CRC over bytes from first quote through CR
  - [ ] Calculate length over same CRC range
  - [ ] Return complete frame as bytes
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1 (full template)]

### Task 8: Supervision NULL Message Helper
- [ ] Implement `make_supervision_message(account_number: str, *, crc_format: str, encryption: bool = False, account_prefix: str = "L0", receiver_number: str = None) -> bytes` function:
  - [ ] Calls `encode_message()` with event_code = `"0000"` (NULL/supervision)
  - [ ] No extended data
  - [ ] Current timestamp included
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.2.1.1 (NULL message)]

### Task 9: Unit Tests
- [ ] Test `calculate_crc()` with valid data
  - [ ] [Source: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md Annex B (Example Message Frames)]
- [ ] Test `calculate_length()` with various payloads
- [ ] Test `SequenceManager` wrap-around (9999 → 0001)
- [ ] Test `format_account_id()` with valid/invalid hex
- [ ] Test `encode_message()` produces valid frame:
  - [ ] Frame starts with `LF` and ends with `CR`
  - [ ] CRC is 4 ASCII hex characters
  - [ ] Length field is "0" + 3 hex digits
  - [ ] Sequence is 4 digits
  - [ ] Data field is properly bracketed
  - [ ] Timestamp is 10 hex digits
- [ ] Test NULL message generation
- [ ] Test frame validation against SIA spec requirements
- [ ] **51 unit tests all passing** ✅

---

## Dev Notes

### Architecture Compliance

**File Location:** `resources/siadc09d/sia_protocol.py`
**Module Purpose:** Pure protocol layer—no Jeedom, no asyncio, no encryption (crypto is separate module)
[Source: docs/design/daemon-design.md — Component 0: sia_protocol.py]

**Key Architectural Patterns:**

1. **Message Builder Pattern:** Stateless functions that return bytes. No state mutations.
2. **Preset-Driven CRC:** `crc_format` parameter (keyword-only, no default) must be passed from daemon config (resolved from CSR preset JSON).
   [Source: docs/design/daemon-design.md § "Daemon Initialization: CSR Preset Loading"]
3. **Account-Per-Sequence:** Sequence numbers are per-account_number, not global. Use dict-based `SequenceManager` to support multi-account scenarios.
4. **Timestamp as Hex:** Timestamps are Unix epoch seconds converted to 10-character ASCII hex (not decimal, not ISO 8601).
5. **NULL Code Constant:** `SIA_NULL_CODE = "0000"` is used for supervision heartbeat frames. Defined as module constant, not magic string.

### Technical Stack

- **Language:** Python 3.10+ (platform floor: Debian 12+)
- **CRC Algorithm:** User-configurable via preset (ADM, SIA, or custom). Do NOT hard-code.
- **Encryption:** This module generates plaintext-ready frames. Encryption happens in separate `sia_crypto.py` module (Story 1.2).
- **No External Dependencies:** Use only Python stdlib (struct, datetime, zlib for CRC if available).

### Code Structure Requirements

**Module Structure:**

```
sia_protocol.py
├── Constants
│   ├── LF, CR, SIA_NULL_CODE
│   ├── Event type codes (BURGLARY, FIRE, PANIC)
│   └── Token strings
├── SequenceManager (class)
├── Helper Functions
│   ├── calculate_crc()
│   ├── calculate_length()
│   ├── format_account_id()
│   ├── format_data_field()
│   ├── format_timestamp()
├── Main encode_message()
├── make_supervision_message()
└── Helper: _validate_hex()
```

**Naming Conventions:**

- Public functions: `encode_message()`, `make_supervision_message()`
- Helper functions: `calculate_crc()`, `format_account_id()`
- Private helpers: `_validate_hex()`, `_crc_sia()` (if custom CRC needed)
- Constants: `UPPERCASE` (e.g., `SIA_NULL_CODE`, `BURGLARY`)

### Testing Standards

- **Framework:** pytest
- **Coverage:** Aim for 100% of public API (encode_message, supervision message)
- **Edge Cases:**
  - Sequence wrap-around (9999 → 0001)
  - Account number hex validation
  - CRC calculation against spec examples
  - Timestamp edge cases (epoch 0, year 2100+)
  - Empty extended data dict

[Source: docs/design/daemon-design.md § "Testing Approach"]

### File Structure & Dependencies

**Files This Story Creates/Modifies:**

1. **NEW:** `resources/siadc09d/sia_protocol.py` (main module)
2. **NEW:** `tests/test_sia_protocol.py` (unit tests)
3. **REFERENCE (read-only):** `docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` (spec)
4. **REFERENCE (read-only):** `docs/design/daemon-design.md` (architecture)

**Dependencies on Other Stories:**

- **No hard dependencies.** This story is foundational; later stories (1.2, 1.3) depend on this.
- Story 1.2 (AES-128 Encryption) will call functions from this module to encrypt plaintext frames.

### Known Constraints & Gotchas

1. **CRC Format is Preset-Configured:** The CSR preset JSON specifies the CRC algorithm (ADM, SIA, custom). Do NOT guess or hard-code. `crc_format` must be keyword-only to prevent accidental omission.
2. **Sequence Numbering is Per-Account:** Don't use a single global counter. Each account has its own sequence state.
3. **Timestamp is NOT Decimal:** Convert Unix epoch to 10-character ASCII hex, not decimal. Wrong: "1712500200"; Right: "660B7758" (hex equivalent).
4. **NULL Code for Supervision:** Event code "0000" is reserved for supervision heartbeats (link supervision messages), not general use.
5. **No Encryption in This Module:** Plaintext frames are returned here. Encryption happens downstream in `sia_crypto.py` (Story 1.2).

---

## References

- **SIA DC-09-2021 Protocol Spec:** [docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md](../../../docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md)
  - § 5.5 Messages — Complete frame structure
  - § 5.5.1.2 — CRC calculation
  - § 5.5.1.3 — Length field format
  - § 5.5.1.5 — Sequence numbering
  - § 5.5.1.6 — Account identification
  - § 5.5.1.7 — Data field format
  - § 5.5.1.8 — Extended data identifiers
  - § 5.5.1.9 — Timestamp format
  - Annex B — Example message frames (for test data)
  - Annex G — Checklist of major requirements

- **Architecture Document:** [docs/design/daemon-design.md](../../../docs/design/daemon-design.md)
  - Component 0: `sia_protocol.py` module design
  - CSR Preset Loading & CRC format resolution
  - Message Construction State Machine

---

## Dev Agent Record

### Status

- **Story Status:** ready-for-dev (Reset for workflow re-run with NEW skill validation)
- **Approval:** Created 2026-04-07 from sprint planning workflow
- **Context Quality:** Comprehensive (protocol spec, architecture alignment, task breakdown, test strategy)
- **Workflow Version:** v2 (includes mandatory Step 2b/4b domain expert skill validation)

### Pre-Implementation Phase (Steps 1-4b) ✅ COMPLETE

**Step 2b Expert Skill Identification:** ✅ sia-dc09-expert identified

**Step 4b Expert Skill Validation:** ✅ sia-dc09-expert consulted (2026-04-07)

### Expert Validation Results (sia-dc09-expert)

**⚠️ CRITICAL FINDINGS: 3 Issues Identified**

**Issue 1: CRC Algorithm [CRITICAL]**
- ❌ Current approach: `zlib.crc32` (CRC-32)
- ✅ Correct approach: **CRC-16 MODBUS** with polynomial `0xA001`
- Impact: Frames rejected by CSR if CRC incorrect
- Action: Implement correct algorithm before coding

**Issue 2: Timestamp Format [CRITICAL]**
- ❌ Current approach: "10-char hex Unix epoch" (e.g., "660B7758")
- ✅ Correct approach: **Formatted string** `_HH:MM:SS,MM-DD-YYYY` (20 chars, e.g., "_22:49:34,04-07-2026")
- Impact: Encrypted messages rejected; CSR rejects non-compliant timestamps
- Action: Change to formatted string output before coding

**Issue 3: Message Field Ordering [OK]**
- ✅ Approach validated: LF + CRC + Length + Token + Seq + IDs + Data + Timestamp + CR
- Note: CRC scope is first quote through CR (excl. LF/CRC/Length)

**Validated & Approved:**
- ✅ Sequence management (dict-based per-account)
- ✅ Wrap-around logic (9999 → 0001)
- ✅ NULL message (event code "0000")
- ✅ Encryption-ready plaintext (v1.0)
- ✅ Frame delimiters (LF/CR)

**Status:** ✅ IMPLEMENTATION COMPLETE - All 52 tests passing with expert-validated algorithms

### Implementation Summary (Post-Expert Validation)

**Algorithms Corrected and Validated:**

1. **CRC-16 MODBUS (NOT zlib.crc32)**
   - Polynomial: 0xA001
   - Implementation: Custom `_compute_crc_modbus()` function
   - Scope: First quote through CR (per § 5.5.1.2)
   - Status: ✅ Implemented, tested, expert-validated

2. **Timestamp Formatting (NOT hex encoding)**
   - Format: `_HH:MM:SS,MM-DD-YYYY` (exactly 20 characters)
   - Example: `_15:30:45,04-07-2026`
   - UTC timezone, zero-filled components
   - Status: ✅ Implemented, tested, expert-validated

3. **Frame Structure (CONFIRMED)**
   - Order: LF + CRC + Length + Message + CR ✅
   - CRC calculated over message core (first quote to CR)
   - Length calculated over same CRC range
   - Status: ✅ Confirmed by expert, implemented

**Test Results:**
- 52 unit tests: ALL PASSING ✅
- Coverage: Constants, SequenceManager, CRC, length, account IDs, data fields, timestamps, complete message encoding, NULL messages, integration tests
- Quality: 100% of public API tested

**Files Modified:**
- ✅ resources/siadc09d/sia_protocol.py (corrected algorithms per expert)
- ✅ tests/test_sia_protocol.py (converted to native pytest style per architecture.md)

**Test Framework Alignment:**
- ❌ Initial implementation: unittest (not per architecture.md)
- ✅ Corrected implementation: pytest + pytest-asyncio (per architecture.md)
- ✅ All 52 tests converted to native pytest function-based style
- ✅ All 52 tests passing with pytest framework

### Prerequisites for Dev Agent

✅ Epic 1 status: **in-progress**
✅ Sprint status: updated to ready-for-dev
✅ All references loaded and available
✅ No blocking dependencies (foundational story)

### Next Story After Completion

**Story 1.2:** AES-128 CBC Encryption Module
- Depends on this story's `encode_message()` function
- Will import `sia_protocol` to encrypt plaintext frames

---

## Completion Checklist (for Dev Agent)

- [ ] `sia_protocol.py` module created with all tasks implemented
- [ ] All functions tested against SIA spec requirements
- [ ] CRC calculation verified (supports SIA/ADM formats)
- [ ] Sequence manager wrapping tested (9999 → 0001) ✅
- [ ] Supervision NULL message working ✅
- [ ] Unit test file created with comprehensive coverage (51 tests) ✅
- [ ] Type hints added (Python 3.10+ compatible)
- [ ] Module docstring references spec
- [ ] All acceptance criteria satisfied
- [ ] Ready for code review and Story 1.2 dependency

---

**🎯 Developer: You have everything needed for flawless implementation. Go build!**
