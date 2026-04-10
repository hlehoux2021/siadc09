# Story 1.4 CSR Simulator Framework — QA Review Report

**Status:** ready-for-dev (Pre-Implementation QA Analysis)

**Review Date:** 2026-04-09

**Reviewer:** QA/Testing Specialist

**Scope:** Test specifications in Story 1.4 (Task 7: Unit Tests) — Gap analysis, specification completeness, protocol compliance, integration testing readiness.

---

## Executive Summary

**Overall Assessment:** The test specification is **structurally sound but has 14 identified issues** spanning acceptance criteria mapping, fixture definitions, protocol compliance validation, and integration testing clarity. These range from **Critical** (2) to **Minor** (8), with most being **ambiguities or gaps** rather than incorrect content.

**Recommendation:** Address all **Critical** and **Major** items before development begins. **Minor** items can be addressed during implementation with developer discretion.

**Estimated Impact:** Low-to-medium. None of the issues prevent implementation, but clarifications will improve test quality and reduce rework.

---

## 1. Acceptance Criteria Alignment

### Assessment

Story 1.4 defines 8 acceptance criteria (ACs). The test specification covers most but has **incomplete mapping** for AC #6 (logging) and **vague coverage** for AC #7 (configurable delay).

| AC # | Text | Test Mapping | Coverage Status | Issue |
|------|------|-------------|-----------------|-------|
| 1 | UDP/TCP listen simultaneously | "Server starts on configured ports" | ✅ Direct | None |
| 2 | Parse & decrypt using Stories 1.1-1.3 | "Encryption," "Integration" tests | ⚠️ Partial | See Issue #1 |
| 3 | Valid alarm → ACK with encryption if needed | "ACK Generation," "Encryption" tests | ✅ Direct | None |
| 4 | Supervision NULL → ACK | "NULL supervision frame → ACK" | ✅ Direct | None |
| 5 | Malformed frame → NAK | "NAK Generation" tests | ✅ Direct | None |
| 6 | Frame logging with timestamps | `_log_frame_exchange()` task defined | ❌ Not tested | **Issue #2** |
| 7 | Configurable response delay | "Latency Simulation" test | ⚠️ Vague | **Issue #3** |
| 8 | Unit tests cover specified scenarios | "Test Coverage >95%" | ✅ Present | None |

### Issues Found

#### Issue #1: Integration with Stories 1.1-1.2 Tests Are Vague

**Category:** Gap / Ambiguity

**Affected Test:** "Integration with Story 1.1 & 1.2" (line 207-211)

**Problem:** The test description says:
```
- Generate valid alarm using SIAMessageBuilder
- Send to simulator
- Verify ACK response parsed by Story 1.3 decode_ack_nak()
- Encrypt outbound, decrypt inbound using Story 1.2 cipher
```

This is **not specific enough for implementation**. It reads like a checklist, not a test case. Questions:
- Does "generate valid alarm" mean test calls `SIAMessageBuilder(crc_format="SIA").encode_message("001234", "1130")`?
- Does "send to simulator" mean send via UDP or TCP socket?
- Should there be **separate tests** for:
  - Story 1.1 integration (message builder + simulator ACK parsing)?
  - Story 1.2 integration (encrypt outbound plaintext, decrypt inbound ACK)?
  - Or is one combined integration test sufficient?
- Should the encryption test validate that **encrypted inbound frame gets encrypted ACK**, not plaintext?

**Recommendation:**
- Break into **3 specific integration tests**:
  1. `test_integration_story_1_1_unencrypted_alarm()` — Build alarm with SIAMessageBuilder, send, verify ACK structure using decode_ack_nak()
  2. `test_integration_story_1_2_encrypted_round_trip()` — Build plaintext alarm, encrypt with SIACipher, send to simulator, receive encrypted ACK, decrypt, verify structure
  3. `test_integration_all_stories_full_flow()` — Full end-to-end: build (1.1) → encrypt (1.2) → send/receive → decrypt → parse (1.3)

**Severity:** Major

---

#### Issue #2: Acceptance Criterion #6 (Logging) Not Tested

**Category:** Gap

**Affected Test:** AC #6 "all received frames are logged with timestamp for debugging"

**Problem:** Task 6 defines `_log_frame_exchange()` function with specific format:
```python
[RX] ACK seq=0001 (plaintext) 2026-04-09 14:32:45.123456
```

But **no test verifies this output exists**. The test spec mentions Task 7 "all received and transmitted frames logged" but doesn't specify:
- How to capture logs (pytest `caplog` fixture)?
- What to assert (exact format? substring?)?
- Should there be separate tests for each direction (RX/TX)?

**Recommendation:**
- Add **2 logging assertion tests** using `caplog`:
  1. `test_logging_frame_received()` — Send frame, assert `caplog.text` contains `"[RX]"` + timestamp
  2. `test_logging_frame_transmitted()` — Receive frame, send response, assert `caplog.text` contains `"[TX]"` + seq number
- Clarify format: Is `2026-04-09 14:32:45.123456` exact, or can it be ISO 8601 like `2026-04-09T14:32:45.123456Z`?

**Severity:** Major

---

#### Issue #3: Latency Simulation Test Is Vague

**Category:** Ambiguity

**Affected Test:** "Test Latency Simulation" (line 192-194)

**Problem:** Test spec says:
```
- Response delay honored (measure elapsed time)
- Zero delay (default) responds immediately
```

This is **not measurable without implementation details**:
- Should the test measure wall-clock time? (fragile, system-dependent)
- How much tolerance? (±10ms? ±50ms? ±100ms?)
- Does "zero delay (default)" mean `response_delay_ms=0` or absence of parameter?
- Should the test verify that with `response_delay_ms=100`, the response takes **at least** 100ms to arrive?

**Recommendation:**
- Define test more precisely:
  ```python
  test_response_delay_simulation():
      """
      Verify that configured response_delay_ms is honored.
      
      Expected result:
      - With response_delay_ms=50, response time is >= 50ms (with 10ms tolerance)
      - With response_delay_ms=0, response time is < 10ms
      """
      simulator = CSRSimulator(..., response_delay_ms=50)
      start = time.perf_counter()
      send_frame(...)
      response = receive_response(...)
      elapsed_ms = (time.perf_counter() - start) * 1000
      
      # Assert: response arrived at least 40ms later (50 - 10ms tolerance)
      assert elapsed_ms >= 40, f"Response too fast: {elapsed_ms}ms"
      # Assert: response arrived within reasonable bounds (50 + 50ms max jitter)
      assert elapsed_ms < 100, f"Response too slow: {elapsed_ms}ms"
  ```
- Add separate test for zero delay (no delay configured).

**Severity:** Minor (but important for reliability)

---

### Summary: Acceptance Criteria Coverage

| AC | Coverage | Issue? | Severity |
|----|----------|--------|----------|
| 1 | ✅ Complete | None | — |
| 2 | ⚠️ Partial | Issue #1 | Major |
| 3 | ✅ Complete | None | — |
| 4 | ✅ Complete | None | — |
| 5 | ✅ Complete | None | — |
| 6 | ❌ Not tested | Issue #2 | Major |
| 7 | ⚠️ Vague | Issue #3 | Minor |
| 8 | ✅ Complete | None | — |

---

## 2. Test Specification Completeness

### 2.1 Test Name Clarity

**Assessment:** Test names are **clear and specific** at the category level but lack **concrete test names** for individual assertions.

**Findings:**

| Test Category | # of Tests | Named? | Issue |
|---------------|-----------|--------|-------|
| UDP/TCP Server Startup | 3 | ❌ Generic | Issue #4 |
| ACK Generation | 4 | ❌ Generic | Issue #4 |
| NAK Generation | 3 | ❌ Generic | Issue #4 |
| Frame Parsing | 3 | ❌ Generic | Issue #4 |
| Encryption | 3 | ⚠️ Partial | Issue #5 |
| Latency Simulation | 2 | ⚠️ Vague | Issue #3 (noted) |
| UDP/TCP Symmetry | 4 | ❌ Generic | Issue #4 |
| Error Handling | 3 | ❌ Generic | Issue #4 |
| Integration | 3 | ⚠️ Vague | Issue #1 (noted) |
| **Total** | **~28 tests** | **12/28 named** | — |

#### Issue #4: Test Names Are Bullet Points, Not Function Names

**Category:** Ambiguity

**Affected Tests:** Lines 167-205 (most tests)

**Problem:** The spec lists test scenarios as bullet points:
```
- Server starts on configured ports without error
- Both UDP and TCP listeners active simultaneously
- Server stops cleanly without hanging
```

But **does not provide function names** like `test_server_starts_on_configured_ports()`. This creates ambiguity:
- Are these 3 separate `test_*()` functions, or assertions within one `test_server_startup()`?
- How specific should each test be? (One assertion per test, or multiple?)

**Recommendation:**
- Provide explicit pytest function names in the spec:
  ```
  - test_server_starts_on_configured_ports()
  - test_both_udp_tcp_active_simultaneously()
  - test_server_stops_without_hanging()
  - test_ack_response_for_valid_alarm()
  - test_ack_matches_received_sequence()
  - test_plaintext_inbound_generates_plaintext_ack()
  - test_encrypted_inbound_generates_encrypted_ack()
  - (... etc for all ~28 tests)
  ```

**Severity:** Minor (developer can infer, but wastes implementation time)

---

#### Issue #5: Encryption Tests Don't Specify Both Directions

**Category:** Ambiguity

**Affected Tests:** Lines 187-190 ("Test Encryption")

**Problem:** Test spec says:
```
- Encrypted inbound decrypted before parsing
- Response encrypted if inbound was encrypted
- Invalid key or malformed ciphertext handled gracefully (NAK response)
```

The first two bullets are **asymmetric**:
- "Encrypted **inbound** decrypted before **parsing**" — This is inbound handling
- "Response **encrypted** if inbound was encrypted" — This is outbound handling

But test descriptions don't clarify:
- Is there a **single test** that covers both (send encrypted, receive encrypted ACK)?
- Or **two tests** (one for inbound decryption, one for outbound encryption)?
- What if inbound is encrypted but `encryption_key` is missing from preset? (NAK is correct, but test says "invalid key or malformed ciphertext" — should this be separate?)

**Recommendation:**
- Split into clearer tests:
  1. `test_encrypted_inbound_decrypted_for_parsing()` — Send encrypted frame, simulator decrypts and parses correctly
  2. `test_encrypted_inbound_produces_encrypted_ack()` — Send encrypted frame, receive encrypted ACK response
  3. `test_encrypted_inbound_without_key_produces_nak()` — Send encrypted frame, but preset has no key → NAK response
  4. `test_malformed_ciphertext_produces_nak()` — Send corrupted/truncated encrypted data → NAK response

**Severity:** Major

---

### 2.2 Expected Results Documentation

**Assessment:** Expected results are **documented in Task descriptions** but **not in test scenarios themselves**.

**Example Issues:**

1. **"Valid alarm frame → ACK response with matching sequence" (line 171)**
   - What does "matching sequence" mean exactly? Echo the inbound sequence?
   - Should the test assert that ACK message contains `seq=<inbound_seq>`?
   - Or should it parse the ACK with `decode_ack_nak()` and assert the returned `seq` field?

2. **"Truncated frame → NAK response" (line 178)**
   - What is "truncated"? (Missing CR? CRC field incomplete? Message cut off?)
   - Should there be **multiple truncation scenarios**?
   - See Issue #7.

3. **"TCP client disconnect doesn't crash server" (line 199)**
   - How does the test verify this? (Assert server still running? Accept new connection?)
   - What if the disconnect happens mid-frame? (Partial read, then close)

**Recommendation:**
- For each test, add explicit **expected result assertion**:
  ```python
  # Instead of:
  - Valid alarm frame → ACK response with matching sequence
  
  # Write:
  - test_ack_echoes_inbound_sequence()
    Expected result:
    - ACK response is generated (not NAK or unknown)
    - parse_ack_nak(response)['seq'] equals inbound sequence
    - ACK message_string contains echoed sequence in correct field
  ```

**Severity:** Minor (but improves test clarity)

---

### 2.3 Edge Cases & Boundary Conditions

**Assessment:** Test spec covers **some edge cases** but **misses several protocol-critical boundaries**.

#### Issue #6: Missing Edge Cases for CRC Format (hex vs bin)

**Category:** Gap

**Problem:** Test spec says "Test ACK Generation" but doesn't explicitly test:
- ACK with `crc_format='hex'` (4 ASCII hex chars)
- ACK with `crc_format='bin'` (2 binary bytes, little-endian)

This is **critical** because Task 4 says:
```
- If 'hex': CRC as 4 ASCII hex chars (e.g., "A3F2"), length as 4 ASCII hex
- If 'bin': CRC as 2 little-endian bytes, length as 4 ASCII hex
```

The two formats have **different byte structures** — a test must verify both paths.

**Recommendation:**
- Add **2 parametrized tests**:
  1. `test_ack_crc_hex_format()` — Send frame with preset `crc_format='hex'`, verify ACK CRC is 4 ASCII hex chars
  2. `test_ack_crc_bin_format()` — Send frame with preset `crc_format='bin'`, verify ACK CRC is 2 binary bytes
- Use pytest `@pytest.mark.parametrize()` to test both formats for each response type (ACK, NAK).

**Severity:** Critical

---

#### Issue #7: NAK Generation Tests Lack Specificity on "Truncated Frame"

**Category:** Ambiguity / Gap

**Affected Test:** "Truncated frame → NAK response" (line 178)

**Problem:** "Truncated" is undefined:
- Missing trailer (CR)? (Frame incomplete)
- Message field cut off mid-message?
- CRC field incomplete (only 2 hex chars instead of 4)?
- Length field incomplete?

Each scenario may require **different handling**:
- Incomplete read on TCP → wait for more data, then process OR timeout then NAK?
- Malformed CRC field → NAK via `_validate_crc()` failure?
- Missing CR → reject as invalid frame structure?

**Recommendation:**
- Define **specific truncation test cases**:
  1. `test_nak_for_frame_missing_trailer()` — Send frame without CR, expect NAK
  2. `test_nak_for_incomplete_crc_field()` — Send frame with only 2 hex CRC chars (should be 4), expect NAK
  3. `test_nak_for_message_cut_mid_field()` — Send frame with message data truncated, expect NAK
  4. `test_nak_for_oversized_length_field()` — Send frame where stated length exceeds actual message, expect NAK

**Severity:** Major

---

#### Issue #8: CRC Mismatch Test Doesn't Specify Calculation

**Category:** Ambiguity

**Affected Test:** "CRC mismatch → NAK response" (line 179)

**Problem:** Test says verify NAK is generated, but doesn't clarify:
- How is CRC mismatch created? (Flip a bit in the CRC field? Modify message after CRC?)
- Should the test validate that `_validate_crc()` is called and returns False?
- Or just verify NAK output (black-box)?

**Recommendation:**
- Clarify: "Generate a valid frame, then flip one bit in the CRC field, send to simulator, expect NAK"
- Test implementation can be:
  ```python
  test_nak_for_invalid_crc():
      """Generate valid alarm, corrupt CRC field, send, verify NAK."""
      frame = build_alarm_frame(seq="0001")
      corrupted = frame[:5] + bytes([frame[5] ^ 0x01]) + frame[6:]  # Flip bit in CRC
      response = simulator.process_frame(corrupted)
      assert decode_ack_nak(response)['type'] == 'NAK'
  ```

**Severity:** Minor

---

### 2.4 Test Independence

**Assessment:** Tests **appear independent** (no ordering dependencies mentioned) but **fixture scope assumptions** need clarification.

#### Issue #9: Fixture Scope & Simulator State Between Tests

**Category:** Ambiguity

**Affected Fixtures:** Lines 157-164

**Problem:** Fixture definitions say `scope="function"` (correct), but don't clarify:
- Is `simulator` fixture **started fresh for each test** or reused?
- Does `simulator` keep state between tests (e.g., sequence counter, received frames)?
- Should cleanup happen automatically (e.g., `await simulator.stop()`)?

**Recommendation:**
- Clarify fixture docstrings:
  ```python
  @pytest.fixture(scope="function")
  def simulator(csr_preset, simulator_udp_port, simulator_tcp_port):
      """
      Create, start, and auto-cleanup simulator instance.
      
      - Each test gets a fresh simulator instance
      - Simulator is started before test and stopped after
      - Port numbers are ephemeral (OS-assigned)
      - Fixture cleanup: close both UDP/TCP sockets and release ports
      """
      sim = CSRSimulator(
          udp_port=simulator_udp_port,
          tcp_port=simulator_tcp_port,
          preset=csr_preset,
          response_delay_ms=0
      )
      # Start simulator
      loop = asyncio.new_event_loop()
      loop.run_until_complete(sim.start())
      
      yield sim
      
      # Cleanup
      loop.run_until_complete(sim.stop())
      loop.close()
  ```

**Severity:** Minor

---

### 2.5 Test Complexity (Lines of Code)

**Assessment:** Test complexity **not specified**. Most tests should be <50 lines but some integration tests might exceed.

**Recommendation:**
- For integration tests (Issues #1), assume ~60-80 lines:
  - Import statements
  - Fixture initialization
  - Build frame
  - Send via socket
  - Receive response
  - Parse response
  - Multiple assertions
- For simple unit tests (ACK/NAK generation), assume <30 lines.
- No test should exceed 100 lines; if it does, split into smaller tests.

**Severity:** Minor

---

## 3. Protocol Compliance

### 3.1 ACK Frame Structure Validation

**Assessment:** Task 4 specifies ACK generation in detail, but tests don't validate all fields.

#### Issue #10: ACK Message String Field Validation Not Tested

**Category:** Gap

**Problem:** Task 4 says ACK message format is:
```
"ACK"<seq_4digit>R0L0#<account>[]
```

But test spec doesn't verify:
- Sequence is exactly 4 digits (zero-padded)?
- Flags are exactly "R0L0"?
- Account number is correct (from preset or default "000001")?
- Data field `[]` is empty (no extended data)?

**Recommendation:**
- Add **parsing tests** that use `decode_ack_nak()` to parse simulator-generated ACK and verify all fields:
  ```python
  test_ack_message_string_format():
      """Verify ACK message contains required fields in correct format."""
      # Send alarm frame
      response = simulator.process_frame(alarm_frame)
      parsed = decode_ack_nak(response)
      
      assert parsed['type'] == 'ACK'
      assert parsed['seq'] == 1  # Received seq=1
      
      # Parse message_string from response (need helper to extract)
      msg = extract_message_string(response)
      assert msg.startswith('ACK')
      assert 'R0L0' in msg  # Flags present
      assert '#000001' in msg or '#001234' in msg  # Account present
  ```

**Severity:** Major

---

#### Issue #11: Encryption Marker (`*ACK` vs `ACK`) Not Fully Tested

**Category:** Gap

**Problem:** Task 4 says:
```
- "ACK" if plaintext inbound, "*ACK" if encrypted inbound (matching inbound encryption state)
```

But test spec only mentions:
```
- Plaintext frame → plaintext ACK
- Encrypted frame (with key) → encrypted ACK
```

This **doesn't explicitly test** that the message_string contains `*ACK` (not just `ACK`).

**Recommendation:**
- Add **explicit marker tests**:
  1. `test_plaintext_inbound_produces_ack_without_marker()` — Send plaintext, verify ACK message_string starts with "ACK" (not "*ACK")
  2. `test_encrypted_inbound_produces_ack_with_encryption_marker()` — Send encrypted, verify decrypted ACK message_string starts with "*ACK"

**Severity:** Major

---

### 3.2 NAK Frame Structure

**Assessment:** NAK generation is specified but test doesn't validate structure details.

#### Issue #12: NAK Format Validation Test Missing

**Category:** Gap

**Problem:** Task 4 specifies NAK format:
```
"NAK"0000R0L0A0[]
```

But no test validates that generated NAK has this exact format. Tests only verify "NAK is generated" but not:
- Sequence is always 0000 (not echoed)?
- Flags are "R0L0A0" (not "R0L0")?
- Data field is empty `[]`?

**Recommendation:**
- Add test:
  ```python
  test_nak_message_format():
      """Verify NAK message structure matches SIA DC-09 spec."""
      response = simulator.process_frame(malformed_frame)
      parsed = decode_ack_nak(response)
      
      assert parsed['type'] == 'NAK'
      assert parsed['seq'] == 0  # NAK always has seq=0000
      
      msg = extract_message_string(response)
      assert msg.startswith('NAK0000')  # NAK marker + zero sequence
      assert 'R0L0A0' in msg  # Exact flags
      assert msg.endswith('[]')  # Empty data field
  ```

**Severity:** Major

---

### 3.3 Windows-1252 Encoding

**Assessment:** Not tested.

#### Issue #13: Windows-1252 Encoding Not Validated

**Category:** Gap

**Problem:** Spec says frames use Windows-1252 encoding but test spec doesn't verify:
- Message string is encoded/decoded as Windows-1252 (not UTF-8)?
- Non-ASCII characters (if any) are handled correctly?

**Recommendation:**
- Add test (if applicable for v1.0):
  ```python
  test_windows_1252_encoding():
      """Verify message_string uses Windows-1252 encoding."""
      # Build frame with Windows-1252 message
      msg = "ACK0001R0L0#000001[]"
      frame = build_frame_with_encoding(msg, encoding='windows-1252')
      response = simulator.process_frame(frame)
      
      # Verify simulator returned frame also uses Windows-1252
      assert response_message_uses_encoding(response, 'windows-1252')
  ```
- Or defer to integration test with Story 1.1 (which already validates encoding).

**Severity:** Minor (encoding likely validated by SIAMessageBuilder)

---

## 4. Integration Testing Gaps

### Assessment

Story 1.4 lists 3 integration test scenarios (lines 207-211) but they are vague. See **Issue #1** above.

Additionally:

#### Issue #14: Missing Integration Scenarios

**Category:** Gap

**Problem:** Tests don't specify integration with:
- **Full daemon flow** (not in scope for Story 1.4, but should note it)
- **UDP vs TCP parity** — Test that same alarm frame sent via UDP and TCP produces identical ACK responses

**Recommendation:**
- Add test:
  ```python
  test_udp_tcp_response_parity():
      """Verify UDP and TCP produce identical responses to same input."""
      # Send alarm via UDP
      udp_response = send_via_udp(alarm_frame, simulator)
      
      # Send same alarm via TCP
      tcp_response = send_via_tcp(alarm_frame, simulator)
      
      # Responses should be identical (same ACK content, same CRC)
      assert udp_response == tcp_response
      assert decode_ack_nak(udp_response) == decode_ack_nak(tcp_response)
  ```

**Severity:** Minor

---

## 5. Fixture Validation

### Assessment

Fixtures are **well-defined** but have **gap** in coverage.

| Fixture | Defined? | Sufficient? | Issue |
|---------|----------|-----------|-------|
| `csr_preset` | ✅ | ✅ | None |
| `csr_preset_encrypted` | ✅ | ✅ | None |
| `simulator_udp_port` | ✅ | ✅ | None |
| `simulator_tcp_port` | ✅ | ✅ | None |
| `simulator` | ✅ | ⚠️ | Issue #9 |
| `sample_alarm_frame` | ✅ | ⚠️ | Issue #15 |
| `sample_null_frame` | ✅ | ⚠️ | Issue #15 |

#### Issue #15: Sample Frame Fixtures Don't Cover All Scenarios

**Category:** Gap

**Problem:** Only 2 sample frames defined (alarm, NULL). But tests need:
- Encrypted alarm frame
- Malformed frame (for NAK tests)
- Truncated frames
- Frame with CRC mismatch
- Frame with oversized message

Building these manually in each test is tedious and error-prone.

**Recommendation:**
- Add fixture helper:
  ```python
  @pytest.fixture(scope="function")
  def malformed_frames():
      """Return dict of various malformed frames for NAK testing."""
      return {
          'truncated_no_trailer': FRAME_LEAD + crc + length + message,  # Missing CR
          'crc_mismatch': FRAME_LEAD + corrupted_crc + length + message + FRAME_TRAIL,
          'invalid_id_token': FRAME_LEAD + crc + length + 'GARBAGE' + FRAME_TRAIL,
          'oversized_length': FRAME_LEAD + crc + b'FFFF' + short_message + FRAME_TRAIL,
      }
  ```
- Or add factory fixture:
  ```python
  @pytest.fixture(scope="function")
  def frame_builder():
      """Return factory to build frames with specific corruption."""
      def build(template, corruption_fn):
          frame = template
          return corruption_fn(frame)
      return build
  ```

**Severity:** Minor (improves test maintainability)

---

## 6. Coverage Target (>95%)

### Assessment

Test spec targets >95% line coverage. Risk areas:

| Code Path | At Risk? | Test Coverage |
|-----------|----------|---------------|
| `_validate_preset()` | ✅ | None? (See Issue #16) |
| `_decrypt_if_needed()` | ⚠️ | "Encryption" tests (vague) |
| `_parse_received_message()` | ✅ | "Frame Parsing" tests |
| `_generate_ack_frame()` | ✅ | "ACK Generation" tests |
| `_generate_nak_frame()` | ✅ | "NAK Generation" tests |
| `_detect_encryption_from_frame()` | ⚠️ | Not mentioned |
| `_log_frame_exchange()` | ✅ | Issue #2 (no test) |
| `start()` / `stop()` | ✅ | "Server startup/shutdown" tests |
| UDP handler | ✅ | "UDP/TCP" tests |
| TCP handler | ⚠️ | "TCP error cases" tests (vague) |
| Error handling | ⚠️ | "Error Handling" tests (vague) |

#### Issue #16: `_validate_preset()` Has No Test Coverage

**Category:** Gap

**Problem:** Task 0b defines `_validate_preset()` but test spec doesn't include tests for:
- Valid preset accepted
- Missing `crc_format` raises CSRSimulatorError
- Invalid `crc_format` (not 'hex' or 'bin') raises error
- Missing `account_number` uses default "000001"
- Invalid account_number (non-hex, <3 chars) raises error
- Invalid `encryption_key` (not bytes, wrong length) raises error

**Recommendation:**
- Add test class:
  ```python
  def test_validate_preset_valid():
      """Valid preset with all required fields."""
      preset = {'crc_format': 'hex', 'account_number': '000001', 'encryption_key': None}
      _validate_preset(preset)  # Should not raise

  def test_validate_preset_missing_crc_format():
      """Missing crc_format raises error."""
      preset = {'account_number': '000001'}
      with pytest.raises(CSRSimulatorError):
          _validate_preset(preset)

  def test_validate_preset_invalid_crc_format():
      """Invalid crc_format value raises error."""
      preset = {'crc_format': 'invalid', 'account_number': '000001'}
      with pytest.raises(CSRSimulatorError):
          _validate_preset(preset)

  def test_validate_preset_invalid_account_number():
      """Account number with non-hex chars raises error."""
      preset = {'crc_format': 'hex', 'account_number': 'XYZ'}
      with pytest.raises(CSRSimulatorError):
          _validate_preset(preset)

  def test_validate_preset_encryption_key_wrong_length():
      """AES key not exactly 16 bytes raises error."""
      preset = {'crc_format': 'hex', 'account_number': '000001', 'encryption_key': b'short'}
      with pytest.raises(CSRSimulatorError):
          _validate_preset(preset)
  ```

**Severity:** Critical

---

#### Issue #17: `_detect_encryption_from_frame()` Not Mentioned in Tests

**Category:** Gap

**Problem:** Task 4 defines `_detect_encryption_from_frame()` helper, but test spec doesn't verify it works:
- Plaintext frame returns False
- Encrypted frame (with `*` marker) returns True
- Malformed frame returns False (safe fallback)

**Recommendation:**
- Add tests:
  ```python
  def test_detect_encryption_plaintext_frame():
      """Plaintext frame detected correctly."""
      frame = build_frame(message="ACK0001R0L0#000001[]")  # No * marker
      assert _detect_encryption_from_frame(frame) == False

  def test_detect_encryption_encrypted_frame():
      """Encrypted frame detected correctly."""
      frame = build_frame(message="*ACK0001R0L0#000001[]")  # With * marker
      assert _detect_encryption_from_frame(frame) == True

  def test_detect_encryption_malformed_returns_false():
      """Malformed frame returns False (safe fallback)."""
      frame = b'\x0A\x0D'  # Just leader and trailer
      assert _detect_encryption_from_frame(frame) == False
  ```

**Severity:** Major

---

## Summary of All Issues

| # | Category | Severity | Fixture/Test | Issue | Recommendation |
|---|----------|----------|--------------|-------|-----------------|
| 1 | Gap | Major | Integration tests | Vague scenarios | Split into 3 specific tests |
| 2 | Gap | Major | Logging test | Not tested | Add caplog assertions (2 tests) |
| 3 | Ambiguity | Minor | Latency test | Vague timing | Define tolerance ±10ms with assertions |
| 4 | Ambiguity | Minor | Most tests | Generic names | Provide explicit pytest function names |
| 5 | Ambiguity | Major | Encryption tests | Asymmetric | Split into 4 specific tests |
| 6 | Gap | Critical | ACK/NAK tests | No hex vs bin CRC format test | Add parametrized CRC format tests |
| 7 | Ambiguity | Major | NAK truncation | "Truncated" undefined | Define 4 specific truncation scenarios |
| 8 | Ambiguity | Minor | CRC mismatch | How to create mismatch? | Clarify: flip bit in CRC field |
| 9 | Ambiguity | Minor | Fixtures | State between tests? | Clarify scope and cleanup |
| 10 | Gap | Major | ACK validation | Message format not tested | Parse ACK and validate all fields |
| 11 | Gap | Major | Encryption marker | `*ACK` not validated | Test marker presence |
| 12 | Gap | Major | NAK format | Structure not validated | Test exact format match |
| 13 | Gap | Minor | Encoding | Windows-1252 not tested | Add encoding test or defer to Story 1.1 |
| 14 | Gap | Minor | Integration | Missing UDP/TCP parity | Add response parity test |
| 15 | Gap | Minor | Fixtures | Limited sample frames | Add malformed frame fixtures/factory |
| 16 | Gap | Critical | Preset validation | No test for `_validate_preset()` | Add 5 validation tests |
| 17 | Gap | Major | Encryption detection | `_detect_encryption_from_frame()` untested | Add 3 detection tests |

---

## Severity Breakdown

- **Critical (3):** Issues #6, #16 — Must fix before dev
- **Major (8):** Issues #1, #2, #5, #7, #10, #11, #12, #17 — Should fix before dev
- **Minor (6):** Issues #3, #4, #8, #9, #13, #14, #15 — Can address during dev with guidance

---

## Specific Answers to User's Questions

### 1. Is the test for "Encrypted frame (with key) → encrypted ACK" sufficient?

**Answer: No.** The test description is **vague and incomplete**. Currently it says:
- "Encrypted inbound decrypted before parsing"
- "Response encrypted if inbound was encrypted"
- "Invalid key or malformed ciphertext handled gracefully"

But doesn't specify:
- Whether it's **one test or three separate tests**
- How to verify encryption (parse the response? inspect bytes?)
- Whether to test the `*` marker in the decrypted ACK message

**Recommendation:** Split into 4 tests (see Issue #5):
1. Encrypted inbound decrypted correctly
2. Encrypted inbound produces encrypted ACK
3. Encrypted inbound without key → NAK
4. Malformed ciphertext → NAK

---

### 2. Should there be separate tests for hex vs bin CRC format responses?

**Answer: Yes, absolutely.** This is **Critical (Issue #6)**. The two formats have **different byte structures**:
- `'hex'`: CRC as 4 ASCII hex chars (e.g., `b'A3F2'`)
- `'bin'`: CRC as 2 binary bytes, little-endian

A single test cannot adequately cover both. Recommend:
- `test_ack_crc_hex_format()` — Assert CRC is 4 ASCII hex chars
- `test_ack_crc_bin_format()` — Assert CRC is 2 binary bytes
- Use parametrized test for both formats on ACK and NAK

---

### 3. Are there any tests for the `_validate_preset()` function from Task 0b?

**Answer: No.** This is **Critical (Issue #16)**. The test spec completely omits tests for preset validation. Missing tests for:
- Valid preset accepted
- Missing/invalid `crc_format` raises error
- Missing/invalid `account_number` raises error
- Missing/invalid `encryption_key` raises error

Recommend: Add 5+ validation tests before dev.

---

### 4. The NAK generation test mentions "Truncated frame → NAK" but doesn't specify what "truncated" means. Is this clear enough?

**Answer: No.** This is **Major (Issue #7)**. "Truncated" is ambiguous and could mean:
- Missing trailer (CR)
- CRC field incomplete (2 chars instead of 4)
- Message data cut off mid-field
- Length field incomplete

Recommend: Define 4 specific truncation test cases with exact descriptions.

---

### 5. Should tests verify log output using `caplog` fixture?

**Answer: Yes, they should.** This is **Major (Issue #2)**. Acceptance Criterion #6 requires logging, but no tests verify it. 

Task 6 defines `_log_frame_exchange()` with format: `[RX] ACK seq=0001 (plaintext) 2026-04-09 14:32:45.123456`

But test spec doesn't specify how to verify this appears in logs. Recommend:
- `test_logging_frame_received()` — Assert `"[RX]"` in `caplog.text`
- `test_logging_frame_transmitted()` — Assert `"[TX]"` in `caplog.text`
- Optionally verify timestamp format in log

---

## Recommendations Before Development

### Must Address (Blocking)

1. **Issue #6** — Add parametrized CRC format tests (hex vs bin)
2. **Issue #16** — Add `_validate_preset()` tests (5+ cases)
3. **Issue #2** — Add logging assertion tests with `caplog`

### Should Address (High Value)

4. **Issue #1** — Clarify integration test scenarios (3 specific tests)
5. **Issue #5** — Split encryption tests (4 specific tests)
6. **Issue #7** — Define truncation test cases (4 scenarios)
7. **Issue #10** — Add ACK message format validation tests
8. **Issue #11** — Add encryption marker (`*ACK`) validation tests
9. **Issue #12** — Add NAK format validation tests
10. **Issue #17** — Add `_detect_encryption_from_frame()` tests

### Nice to Have (During Dev)

11. **Issue #3** — Clarify latency timing tolerance
12. **Issue #4** — Provide explicit pytest function names
13. **Issue #9** — Clarify fixture scope and cleanup
14. **Issue #13** — Add Windows-1252 encoding test (or defer)
15. **Issue #14** — Add UDP/TCP response parity test
16. **Issue #15** — Add malformed frame fixtures

---

## Conclusion

**The test specification is structurally sound but requires clarification and expansion** before implementation. The primary issues are:
- **Vague integration test scenarios** that need breaking into specific test cases
- **Missing tests for critical functions** like `_validate_preset()` and logging
- **Protocol compliance gaps** (CRC format, encryption marker, message format validation)
- **Ambiguous test descriptions** that don't specify exact assertions

Addressing the **Critical** and **Major** items will result in a robust, comprehensive test suite that provides >95% coverage and validates full SIA DC-09 protocol compliance.

