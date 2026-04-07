# Claude Testing Rules

## Test Implementation Workflow

1. **Always invoke domain expert skills first**
   - Before writing tests, identify if a domain expert skill applies (e.g., `sia-dc09-expert` for protocol work)
   - Validate implementation approach with the skill before writing code
   - This catches critical algorithm and specification errors early

2. **Use bmad-bmm-dev-story workflow for story-level testing**
   - Follow the workflow steps including Step 2b (expert skill identification) and Step 4b (expert validation)
   - Run tests after implementation to verify correctness

3. **Test Framework: pytest only**
   - Use pytest function-based tests (`def test_*():`), not unittest.TestCase
   - Use `pytest.fixture` for reusable setup, not setUp methods
   - Use simple `assert` statements, not `self.assert*` methods

## Test Writing Standards

Every test method must include three documented elements (per `tests/README.md`):

1. **Test Description** (in docstring)
   - Human-readable explanation of the scenario being tested
   - 1-3 sentences, non-technical language
   ```python
   def test_crc_returns_4_hex_chars():
       """Test that CRC calculation produces a valid 4-character hexadecimal string."""
   ```

2. **Expected Result Documentation** (in docstring)
   - Clearly state what the function should return or produce
   - Bullet points listing observable outcomes
   ```python
   def test_crc_returns_4_hex_chars():
       """
       Test that CRC calculation produces a valid 4-character hexadecimal string.

       Expected result:
       - calculate_crc() returns a string exactly 4 characters long
       - All characters are valid hex digits (0-9, A-F)
       """
   ```

3. **Assert Documentation** (inline comments)
   - One comment per assert explaining what is being validated
   - Reference the expected result from the docstring
   ```python
   # Assert: CRC result is exactly 4 characters (required by SIA protocol)
   assert len(crc) == 4

   # Assert: All characters are valid hex (0-9, A-F uppercase)
   assert all(c in '0123456789ABCDEF' for c in crc)
   ```

## Test Organization

- **Level 1:** Unit tests in `tests/level1/` — sync, no async, no external deps
- **Level 2:** Daemon integration in `tests/level2/` — async, state machine tests
- **Level 2.5:** IPC contract in `tests/level2_5/` — callback schema validation
- **Level 3:** Jeedom integration in `tests/level3/` — live Jeedom instance required

## Async Testing Rules (Level 2+)

1. **Join daemon tasks after state transitions**
   ```python
   await asyncio.gather(*daemon._tasks)  # Always use this
   ```
   Never use `await asyncio.sleep(0)` — it doesn't guarantee task completion.

2. **Use time_mock fixture for time-dependent tests**
   - Do not hardcode `asyncio.sleep()` in tests
   - Do not rely on real clock timing

3. **Log assertions use caplog**
   ```python
   assert "expected string" in caplog.text
   ```
   Never mock the logger directly — use pytest's built-in `caplog` fixture.

## Protocol/Algorithm Testing

When implementing protocol features (e.g., CRC, encryption, message encoding):

1. **Validate against spec reference document**
   - CRC-16 MODBUS with polynomial 0xA001 (SIA DC-09 § 5.5.1.2)
   - Timestamp format: _HH:MM:SS,MM-DD-YYYY (§ 5.5.1.9)
   - Include spec section references in docstrings

2. **Test with golden frames (real data)**
   - For CSR protocol work, create tests marked `@pytest.mark.golden_frames`
   - Store real frame data as `.bin` files in `tests/fixtures/golden/`
   - Document origin in `tests/fixtures/README.md`

3. **Expert validation**
   - Protocol tests are reviewed by domain expert skill before merging
   - Critical algorithm errors caught: CRC, encryption, timestamp format, sequence management

## Test Execution

1. **Run tests locally after writing**
   - Verify all tests pass before marking story as "review"
   - Use `pytest tests/level1/` for unit tests
   - Use `pytest -m "not requires_jeedom"` to skip slow tests in development

2. **Check test coverage**
   - Aim for >95% line coverage on core protocol modules
   - Use `pytest --cov` to measure coverage

3. **Async fixtures cleanup**
   - Async fixtures must yield and clean up resources
   - No orphaned tasks or unclosed sockets after test completes

## No Deviations Without Reason

- Do not use unittest.TestCase (pytest is the standard)
- Do not skip the three-element documentation (description + expected result + assert comment)
- Do not write tests without a clear expected result in the docstring
- Do not use bare `asyncio.sleep()` for synchronization — use task gathering
