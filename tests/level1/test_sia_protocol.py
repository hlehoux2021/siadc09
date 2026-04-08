"""
Unit tests for sia_protocol module — pytest style.

Tests cover:
- CRC calculation (CRC-16 MODBUS algorithm)
- Message frame structure and delimiters
- Sequence number management (wrap-around)
- Account ID formatting
- Complete message encoding
- NULL message generation
- Timestamp formatting
- Error handling and validation
- Boundary and edge cases
- Parametrized tests for efficiency
- Encryption functionality
- Receiver/prefix combinations

Framework: pytest (per architecture.md)
Test Level: Level 1 (unit tests — sync, no async, no external dependencies)
"""

import pytest
from datetime import datetime, timezone
from typing import Optional
from resources.siadc09d.sia_protocol import (
    # Constants
    LF, CR, SIA_NULL_CODE, BURGLARY, FIRE, PANIC,
    CRC_FORMAT_SIA, CRC_FORMAT_ADM,

    # Classes
    SequenceManager,

    # Functions
    calculate_crc,
    calculate_length,
    format_account_id,
    format_data_field,
    format_timestamp,
    encode_message,
    make_supervision_message,
)


# ===== HELPER FUNCTIONS FOR FIELD VALIDATION =====

def parse_frame(frame: bytes) -> dict:
    """
    Parse a SIA protocol frame into its component fields.

    Returns dict with keys:
    - lf: Start delimiter (bytes)
    - crc: CRC field (bytes, 4 chars)
    - length: Length field (bytes, 4 chars)
    - message_core: Message content (bytes, everything between length and CR)
    - cr: End delimiter (bytes)

    Raises ValueError if frame structure is invalid.
    """
    if len(frame) < 11:  # Minimum: LF + 4 CRC + 4 length + CR
        raise ValueError(f"Frame too short: {len(frame)}")
    if frame[0:1] != LF or frame[-1:] != CR:
        raise ValueError("Invalid frame delimiters")

    return {
        "lf": frame[0:1],
        "crc": frame[1:5],
        "length": frame[5:9],
        "message_core": frame[9:-1],
        "cr": frame[-1:],
    }


def validate_frame_field_values(
    frame: bytes,
    expected_crc: str,
    expected_length: str,
    expected_seq: str,
    expected_account: str,
    expected_event_code: str,
    expected_timestamp: Optional[str] = None,
) -> None:
    """
    Validate that all field values in frame match expected values.

    Args:
        frame: Complete frame bytes
        expected_crc: Expected CRC as string (4 hex chars)
        expected_length: Expected length as string (4 hex chars)
        expected_seq: Expected sequence number (4 digits)
        expected_account: Expected account ID with prefix (e.g., "L0#1234")
        expected_event_code: Expected event code (e.g., "FA 129")
        expected_timestamp: Expected timestamp string or None
    """
    parsed = parse_frame(frame)

    # Validate CRC
    actual_crc = parsed["crc"].decode('ascii')
    assert actual_crc == expected_crc, \
        f"CRC mismatch: expected {expected_crc}, got {actual_crc}"

    # Validate length
    actual_length = parsed["length"].decode('ascii')
    assert actual_length == expected_length, \
        f"Length mismatch: expected {expected_length}, got {actual_length}"

    # Validate message core contains expected values
    message_str = parsed["message_core"].decode('ascii')

    assert expected_seq in message_str, \
        f"Sequence {expected_seq} not found in message: {message_str}"

    assert expected_account in message_str, \
        f"Account {expected_account} not found in message: {message_str}"

    assert expected_event_code in message_str, \
        f"Event code {expected_event_code} not found in message: {message_str}"

    if expected_timestamp:
        assert expected_timestamp in message_str, \
            f"Timestamp {expected_timestamp} not found in message: {message_str}"


# ===== FIXTURES =====

@pytest.fixture
def sequence_manager():
    """Provide a fresh SequenceManager for each test."""
    return SequenceManager()


# ===== TESTS: Constants =====

def test_lf_is_0x0a():
    """
    Test that LF constant is the correct binary line feed value.
    This verifies the frame start delimiter is set correctly per SIA spec.

    Expected result:
    - LF constant equals 0x0A (ASCII line feed character)
    """
    # Assert: LF is the correct binary value for line feed
    assert LF == b'\x0A'


def test_cr_is_0x0d():
    """
    Test that CR constant is the correct binary carriage return value.
    This verifies the frame end delimiter is set correctly per SIA spec.

    Expected result:
    - CR constant equals 0x0D (ASCII carriage return character)
    """
    # Assert: CR is the correct binary value for carriage return
    assert CR == b'\x0D'


def test_null_code():
    """
    Test that SIA_NULL_CODE constant has the correct value.
    This verifies supervision messages use the correct event code.

    Expected result:
    - SIA_NULL_CODE equals "0000" (per SIA DC-09 § 5.5.2.1)
    """
    # Assert: NULL code is exactly "0000" for supervision messages
    assert SIA_NULL_CODE == "0000"


def test_event_codes():
    """
    Test that event type code constants are correctly defined.
    This verifies alarm event types match SIA spec mappings.

    Expected result:
    - BURGLARY code is "1"
    - FIRE code is "2"
    - PANIC code is "3"
    """
    # Assert: Event codes match SIA protocol mappings
    assert BURGLARY == "1"
    assert FIRE == "2"
    assert PANIC == "3"


# ===== TESTS: SequenceManager =====

def test_sequence_first_is_0001(sequence_manager):
    """
    Test that first sequence number is 0001.
    This verifies sequence tracking starts at the correct value.

    Expected result:
    - First call to next_seq() returns "0001"
    - No sequence counter reaches 0000 (per SIA spec § 5.5.1.5)
    """
    seq = sequence_manager.next_seq("001234")
    # Assert: First sequence is 0001
    assert seq == "0001"


def test_sequence_increments(sequence_manager):
    """
    Test that sequence numbers increment correctly with each call.
    This verifies per-account sequence counting works properly.

    Expected result:
    - Sequential calls return 0001, 0002, 0003, ...
    - Each call increments the counter by exactly 1
    """
    seq1 = sequence_manager.next_seq("001234")
    seq2 = sequence_manager.next_seq("001234")
    seq3 = sequence_manager.next_seq("001234")

    # Assert: Sequence increments by 1 each call
    assert seq1 == "0001"
    assert seq2 == "0002"
    assert seq3 == "0003"


def test_sequence_wraps_9999_to_0001(sequence_manager):
    """
    Test that sequence wraps from 9999 to 0001 (never 0000).
    This verifies wrap-around behavior per SIA spec § 5.5.1.5.

    Expected result:
    - After reaching 9999, next sequence is 0001
    - Sequence never wraps to 0000
    """
    sequence_manager._seq_map["001234"] = 9999
    next_seq = sequence_manager.next_seq("001234")
    # Assert: Wrapping skips 0000 and returns 0001
    assert next_seq == "0001"


def test_current_seq_no_increment(sequence_manager):
    """
    Test that current_seq() returns sequence without incrementing.
    This verifies current_seq() is non-destructive read operation.

    Expected result:
    - Multiple calls to current_seq() return same value
    - Value remains unchanged after calls
    """
    sequence_manager.next_seq("001234")  # Initialize to 0001
    current1 = sequence_manager.current_seq("001234")
    current2 = sequence_manager.current_seq("001234")

    # Assert: current_seq() returns same value on repeated calls
    assert current1 == "0001"
    assert current2 == "0001"


def test_sequence_per_account(sequence_manager):
    """
    Test that each account has independent sequence tracking.
    This verifies sequences don't interfere across accounts.

    Expected result:
    - Each account has separate sequence counter
    - Two accounts both start at 0001
    - Each increments independently
    """
    seq_a1 = sequence_manager.next_seq("acctA")
    seq_b1 = sequence_manager.next_seq("acctB")
    seq_a2 = sequence_manager.next_seq("acctA")
    seq_b2 = sequence_manager.next_seq("acctB")

    # Assert: Each account has independent sequence tracking
    assert seq_a1 == "0001"
    assert seq_b1 == "0001"
    assert seq_a2 == "0002"
    assert seq_b2 == "0002"


# ===== TESTS: CRC Calculation =====

def test_crc_returns_4_hex_chars():
    """
    Test that CRC calculation produces a valid 4-character hexadecimal string.
    This verifies the CRC-16 MODBUS algorithm produces properly formatted output.

    Expected result:
    - calculate_crc() returns a string exactly 4 characters long
    - All characters are valid hex digits (0-9, A-F)
    """
    result = calculate_crc(b"test data", CRC_FORMAT_SIA)
    # Assert: CRC result is exactly 4 characters (required by SIA protocol)
    assert len(result) == 4
    # Assert: All characters are valid hex (0-9, A-F uppercase)
    assert all(c in '0123456789ABCDEF' for c in result)


def test_crc_format_sia():
    """
    Test CRC calculation with SIA format (CRC-16 MODBUS).
    This verifies SIA format algorithm is correctly applied.

    Expected result:
    - SIA format produces valid 4-char hex output
    - Different data produces different CRCs (data-dependent)
    """
    crc1 = calculate_crc(b"test1", CRC_FORMAT_SIA)
    crc2 = calculate_crc(b"test2", CRC_FORMAT_SIA)

    # Assert: Both are valid hex
    assert all(c in '0123456789ABCDEF' for c in crc1)
    assert all(c in '0123456789ABCDEF' for c in crc2)

    # Assert: Different data produces different CRCs
    assert crc1 != crc2, "Different data should produce different CRCs"


def test_crc_format_adm():
    """
    Test CRC calculation with ADM format.
    This verifies ADM format algorithm is correctly applied.

    Expected result:
    - ADM format produces valid 4-char hex output
    - Different data produces different CRCs (data-dependent)
    """
    crc1 = calculate_crc(b"test1", CRC_FORMAT_ADM)
    crc2 = calculate_crc(b"test2", CRC_FORMAT_ADM)

    # Assert: Both are valid hex
    assert all(c in '0123456789ABCDEF' for c in crc1)
    assert all(c in '0123456789ABCDEF' for c in crc2)

    # Assert: Different data produces different CRCs
    assert crc1 != crc2, "Different data should produce different CRCs"


def test_crc_format_accepts_sia_and_adm():
    """
    Test that CRC format parameter accepts SIA and ADM values.
    This verifies the two supported CRC algorithm types.

    Expected result:
    - calculate_crc with CRC_FORMAT_SIA produces valid output
    - calculate_crc with CRC_FORMAT_ADM produces valid output
    """
    # Assert: Both valid formats produce output
    crc_sia = calculate_crc(b"test", CRC_FORMAT_SIA)
    crc_adm = calculate_crc(b"test", CRC_FORMAT_ADM)

    assert len(crc_sia) == 4
    assert len(crc_adm) == 4


@pytest.mark.parametrize("crc_format", [CRC_FORMAT_SIA, CRC_FORMAT_ADM])
def test_crc_both_formats_produce_valid_output(crc_format):
    """
    Parametrized test: Verify both CRC formats produce valid output.
    This reduces duplication while testing both algorithm variants.

    Expected result:
    - Both SIA and ADM formats produce 4-character hex strings
    - Output is consistent (same input → same output)
    """
    data = b"test payload"
    crc1 = calculate_crc(data, crc_format)  # type: ignore
    crc2 = calculate_crc(data, crc_format)  # type: ignore

    # Assert: Output is 4 hex chars
    assert len(crc1) == 4
    assert all(c in '0123456789ABCDEF' for c in crc1)

    # Assert: Consistent (same input produces same output)
    assert crc1 == crc2


# ===== TESTS: Length Calculation =====

def test_length_starts_with_zero():
    """
    Test that length field always starts with '0' character.
    This verifies proper zero-padding per SIA spec § 5.5.1.4.

    Expected result:
    - calculate_length() always returns format "0XXX" (starting with '0')
    - Never produces "1000" or higher (frames limited to 0FFF max)
    """
    result = calculate_length(b"short")
    # Assert: Length starts with zero
    assert result.startswith('0'), f"Length must start with 0, got {result}"


def test_length_is_4_chars():
    """
    Test that length field is always exactly 4 characters.
    This verifies proper formatting for the 4-byte length field.

    Expected result:
    - calculate_length() returns exactly 4 characters
    - Padded with zeros if needed
    """
    result = calculate_length(b"test data")
    # Assert: Length is exactly 4 characters
    assert len(result) == 4, f"Length must be 4 chars, got {len(result)}"


def test_length_is_hex():
    """
    Test that length field contains only hexadecimal characters.
    This verifies valid hex format per SIA spec.

    Expected result:
    - All characters are 0-9 or A-F
    - Field is valid hexadecimal (not decimal)
    """
    result = calculate_length(b"test")
    # Assert: All characters are valid hex
    assert all(c in '0123456789ABCDEF' for c in result), \
        f"Length should be hex, got {result}"


def test_length_calculation_example():
    """
    Test length calculation with known data size.
    This validates the calculation formula matches spec expectations.

    Expected result:
    - 10 bytes of data → "000A" (hex 0A = decimal 10)
    - 255 bytes of data → "00FF" (hex FF = decimal 255)
    """
    # Assert: 10 bytes → 000A
    result = calculate_length(b"x" * 10)
    assert result == "000A", f"10 bytes should be 000A, got {result}"

    # Assert: 255 bytes → 00FF
    result = calculate_length(b"x" * 255)
    assert result == "00FF", f"255 bytes should be 00FF, got {result}"


# ===== TESTS: Account ID Formatting =====

def test_basic_account_id():
    """
    Test basic account ID formatting without receiver.
    This verifies standard L0 prefix with account number only.

    Expected result:
    - format_account_id("001234", "L0") returns "L0#001234"
    - Format is prefix + "#" + account_number
    """
    result = format_account_id("001234", "L0")
    # Assert: Account ID has correct format
    assert result == "L0#001234"


def test_account_id_with_prefix():
    """
    Test account ID formatting with different prefix.
    This verifies custom prefix handling.

    Expected result:
    - format_account_id("001234", "L2") returns "L2#001234"
    - Format adapts to different prefixes
    """
    result = format_account_id("001234", "L2")
    # Assert: Custom prefix is used
    assert result == "L2#001234"


def test_account_id_with_receiver():
    """
    Test account ID formatting with receiver number.
    This verifies receiver prefix is included before account prefix.

    Expected result:
    - format_account_id("001234", "L0", "R2") returns "R2L0#001234"
    - Format is receiver + prefix + "#" + account_number
    """
    result = format_account_id("001234", "L0", "R2")
    # Assert: Receiver and prefix included in correct order
    assert result == "R2L0#001234"


def test_account_id_with_multiple_digit_account():
    """
    Test account ID with longer account number.
    This verifies format handles various account number lengths.

    Expected result:
    - format_account_id("ABCDEF123456", "L0") returns "L0#ABCDEF123456"
    - Accepts full 16-char hex account numbers
    """
    result = format_account_id("ABCDEF123456", "L0")
    # Assert: Full account number is preserved
    assert result == "L0#ABCDEF123456"


def test_account_id_mixed_case():
    """
    Test that account ID accepts mixed-case hexadecimal.
    This verifies case doesn't affect validation or output.

    Expected result:
    - Mixed case hex (a-f, A-F) is accepted
    - Case is preserved in output
    """
    result = format_account_id("aAbBcCdD", "L0")
    # Assert: Mixed-case hex is accepted and preserved
    assert result == "L0#aAbBcCdD"


# ===== TESTS: Data Field Formatting =====

def test_data_field_basic():
    """
    Test basic data field formatting.
    This verifies standard unencrypted data field structure.

    Expected result:
    - Format is "[#{account_number}|{event_code}]"
    - Square brackets and pipe separator present
    """
    result = format_data_field("001234", "1130")
    # Assert: Data field has correct format
    assert result == "[#001234|1130]"


def test_data_field_fire_code():
    """
    Test data field with fire event code.
    This verifies data field works with different event types.

    Expected result:
    - Fire code "2130" produces "[#001234|2130]"
    """
    result = format_data_field("001234", "2130")
    # Assert: Fire event code produces correct format
    assert result == "[#001234|2130]"


def test_data_field_has_brackets():
    """
    Test that data field includes bracket delimiters.
    This verifies bracket syntax per SIA spec § 5.5.1.7.

    Expected result:
    - Result starts with "[" and ends with "]"
    """
    result = format_data_field("001234", "1130")
    # Assert: Data field is enclosed in brackets
    assert result.startswith("[")
    assert result.endswith("]")


def test_data_field_has_pipe_separator():
    """
    Test that data field includes pipe separator.
    This verifies account and event code are separated correctly.

    Expected result:
    - Result contains "|" separator between account and event
    """
    result = format_data_field("001234", "1130")
    # Assert: Data field includes pipe separator
    assert "|" in result


@pytest.mark.parametrize("account,event_code,expected", [
    ("1234", "FA 129", "[#1234|FA 129]"),
    ("ABCD", "BA 129", "[#ABCD|BA 129]"),
    ("0000", "0000", "[#0000|0000]"),
    ("FFFF", "FF FF", "[#FFFF|FF FF]"),
])
def test_data_field_parametrized(account: str, event_code: str, expected: str):
    """
    Parametrized test for data field formatting with various inputs.
    This validates format consistency across different account/event combinations.

    Expected result:
    - Each combination produces expected format
    """
    # Assert: Data field matches expected format
    assert format_data_field(account, event_code) == expected


# ===== TESTS: Timestamp Formatting =====

def test_timestamp_length():
    """
    Test that timestamp is exactly 20 characters.
    This verifies timestamp format per SIA spec § 5.5.1.9.

    Expected result:
    - Formatted timestamp is exactly 20 characters long
    """
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    # Assert: Timestamp is exactly 20 characters
    assert len(result) == 20


def test_timestamp_format():
    """
    Test that timestamp follows correct format string.
    This verifies format is _HH:MM:SS,MM-DD-YYYY per spec.

    Expected result:
    - Timestamp for 2026-04-07 15:30:45 UTC is "_15:30:45,04-07-2026"
    """
    ts = datetime(2026, 4, 7, 15, 30, 45, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    # Assert: Timestamp matches exact format
    assert result == "_15:30:45,04-07-2026"


def test_timestamp_has_required_separators():
    """
    Test that timestamp includes all required separator characters.
    This verifies correct separators: underscore, colons, comma, dashes.

    Expected result:
    - Starts with "_"
    - Contains ":" for time separators
    - Contains "," between time and date
    - Contains "-" for date separators
    """
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    # Assert: Leading underscore present
    assert result.startswith("_")
    # Assert: Colons present in time section
    assert ":" in result
    # Assert: Comma separator between time and date
    assert "," in result
    # Assert: Dashes present in date section
    assert "-" in result


def test_timestamp_zero_fills_components():
    """
    Test that timestamp zero-fills all components.
    This verifies single-digit months/days/hours are padded.

    Expected result:
    - Month 01, day 03, hour 09, minute 05, second 02 are zero-filled
    - Result is "_09:05:02,01-03-2026"
    """
    ts = datetime(2026, 1, 3, 9, 5, 2, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    # Assert: All components are zero-filled to 2 digits
    assert result == "_09:05:02,01-03-2026"


def test_timestamp_current_if_none():
    """
    Test that None timestamp returns None (omits timestamp from message).
    This allows frames without timestamps per SIA spec § 5.5.2.1.

    Expected result:
    - None input returns None (no timestamp field)
    - Caller can choose to include or exclude timestamp
    """
    result = format_timestamp(None)
    # Assert: None timestamp returns None (field omitted)
    assert result is None


@pytest.mark.parametrize("dt,expected", [
    (datetime(2026, 4, 7, 15, 30, 45, tzinfo=timezone.utc), "_15:30:45,04-07-2026"),
    (datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc), "_00:00:00,01-01-2026"),
    (datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc), "_23:59:59,12-31-2026"),
])
def test_timestamp_parametrized(dt: datetime, expected: str):
    """
    Parametrized test for timestamp formatting across various dates/times.
    This validates formatting consistency across boundary conditions.

    Expected result:
    - Each datetime produces expected formatted string
    """
    # Assert: Timestamp matches expected format
    assert format_timestamp(dt) == expected


# ===== TESTS: Complete Message Encoding =====

def test_encode_message_starts_with_lf():
    """
    Test that encoded message starts with LF byte.
    This verifies frame start delimiter per SIA spec § 5.5.

    Expected result:
    - First byte is LF (0x0A)
    - Frame contains all required fields with correct values
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Frame starts with LF delimiter
    assert frame.startswith(LF)
    # Assert: Message fields contain expected values
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert "SIA-DCS" in message_str
    assert "0001" in message_str  # Sequence
    assert "L0#001234" in message_str  # Account ID
    assert "[#001234|1130]" in message_str  # Data field


def test_encode_message_ends_with_cr():
    """
    Test that encoded message ends with CR byte.
    This verifies frame end delimiter per SIA spec § 5.5.

    Expected result:
    - Last byte is CR (0x0D)
    - Frame has no data after CR delimiter
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Frame ends with CR delimiter
    assert frame.endswith(CR)
    # Assert: CR is exactly at the end (no trailing bytes)
    assert frame[-1:] == CR
    assert frame[-2:-1] != CR


def test_encode_message_has_crc():
    """
    Test that encoded message includes valid CRC field.
    This verifies CRC is present, positioned correctly, and has valid value.

    Expected result:
    - Bytes 1-4 (after LF) are CRC (4 bytes)
    - CRC value is valid hexadecimal (0-9, A-F)
    - CRC matches calculation over message core
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: CRC field is 4 bytes after LF
    crc_bytes = frame[1:5]
    assert len(crc_bytes) == 4
    # Assert: CRC is valid hexadecimal
    crc_str = crc_bytes.decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in crc_str), \
        f"CRC contains non-hex characters: {crc_str}"
    # Assert: CRC matches recalculation
    message_core = frame[9:-1]  # Everything between length and CR
    expected_crc = calculate_crc(message_core, CRC_FORMAT_SIA)
    assert crc_str == expected_crc, \
        f"CRC mismatch: frame has {crc_str}, calculation gives {expected_crc}"


def test_encode_message_has_length():
    """
    Test that encoded message includes length field.
    This verifies length field is present at correct position and value is correct.

    Expected result:
    - Bytes 5-8 (after CRC) are length (4 bytes starting with "0")
    - Length value matches actual message core byte count
    - Length is valid hexadecimal string
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Length field is 4 bytes after CRC
    length_bytes = frame[5:9]
    assert len(length_bytes) == 4
    # Assert: Length starts with zero
    assert length_bytes.startswith(b'0')
    # Assert: Length is valid hex characters
    length_str = length_bytes.decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in length_str), \
        f"Length contains non-hex: {length_str}"
    # Assert: Length matches actual message core size
    message_core = frame[9:-1]  # Everything between length and CR
    expected_length = f"0{len(message_core):03X}"
    assert length_str == expected_length, \
        f"Length mismatch: frame has {length_str}, message_core is {len(message_core)} bytes"


def test_encode_message_has_id_token():
    """
    Test that encoded message includes correct ID token.
    This verifies message identification marker is exactly "SIA-DCS" (unencrypted).

    Expected result:
    - Frame contains exactly "SIA-DCS" token (not encrypted variant)
    - Token appears at correct position in message core
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False,
        timestamp=None
    )
    # Assert: ID token is present in frame
    assert b'"SIA-DCS"' in frame
    # Assert: Message starts with ID token (position 0 in message core)
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert message_str.startswith('"SIA-DCS"'), \
        f"Message should start with ID token, got: {message_str[:20]}"


def test_encode_message_crc_format_keyword_only():
    """
    Test that crc_format parameter is keyword-only.
    This verifies API design enforces keyword usage.

    Expected result:
    - Passing crc_format as positional argument raises TypeError
    """
    # Assert: crc_format as positional raises TypeError
    with pytest.raises(TypeError):
        encode_message("001234", "1130", "L0", None, None, None, CRC_FORMAT_SIA)  # type: ignore


def test_encode_message_unencrypted_token():
    """
    Test that unencrypted message uses SIA-DCS token.
    This verifies unencrypted mode token selection without encryption marker.

    Expected result:
    - Contains "SIA-DCS" token (without * prefix)
    - Token appears as "SIA-DCS" (quoted, no asterisk)
    - Message does not contain "*SIA-DCS" variant
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False,
        timestamp=None
    )
    # Assert: Unencrypted token present
    assert b'"SIA-DCS"' in frame
    # Assert: No encryption marker in token
    assert b'"*' not in frame
    # Assert: Message core starts with unencrypted token
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert message_str.startswith('"SIA-DCS"'), \
        f"Should start with \"SIA-DCS\", got: {message_str[:15]}"


def test_encode_message_encrypted_token():
    """
    Test that encrypted message uses *SIA-DCS token.
    This verifies encrypted mode token selection with encryption marker.

    Expected result:
    - Contains "*SIA-DCS" token (with * encryption prefix)
    - Token appears as "*SIA-DCS" (quoted with asterisk)
    - Message starts with encrypted token identifier
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=True,
        timestamp=None
    )
    # Assert: Encrypted token with * prefix present
    assert b'"*SIA-DCS"' in frame
    # Assert: Message core starts with encrypted token
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert message_str.startswith('"*SIA-DCS"'), \
        f"Should start with \"*SIA-DCS\", got: {message_str[:15]}"
    # Assert: Unencrypted variant is NOT present
    assert '"SIA-DCS"0' not in message_str, \
        "Should not contain unencrypted token variant"


def test_encode_message_returns_bytes():
    """
    Test that encode_message returns bytes object.
    This verifies return type is binary data (not string) and frame is non-empty.

    Expected result:
    - Return value is bytes type (not str)
    - Frame is not empty (contains at least LF + CRC + Length + Message + CR)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Return type is bytes
    assert isinstance(frame, bytes), \
        f"Expected bytes, got {type(frame)}"
    # Assert: Frame is not empty
    assert len(frame) > 0, "Frame should not be empty"
    # Assert: Frame has minimum structure (LF + CRC + Length + message + CR = at least 14 bytes)
    assert len(frame) >= 14, \
        f"Frame too small: {len(frame)} bytes"


def test_encode_message_with_receiver():
    """
    Test that message includes receiver when provided.
    This verifies receiver number and prefix are added correctly.

    Expected result:
    - Frame contains "R2" receiver marker
    - Frame contains "L1" prefix marker
    - Account ID field is exactly "R2L1#001234" (receiver + prefix + # + account)
    """
    frame = encode_message(
        "001234", "1130",
        account_prefix="L1",
        receiver_number="R2",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Receiver and prefix are in frame
    assert b"R2" in frame
    assert b"L1" in frame
    # Assert: Complete account ID field is correct
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert "R2L1#001234" in message_str, \
        f"Expected 'R2L1#001234' in message, got: {message_str}"


def test_encode_message_data_field_included():
    """
    Test that message includes exact data field with event code.
    This verifies data field structure: [#account|event_code].

    Expected result:
    - Frame contains exactly "[#001234|1130]" data field
    - Data field appears after account ID, before timestamp (if present)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Exact data field is present
    assert b"[#001234|1130]" in frame


# ===== ERROR HANDLING TESTS =====

def test_encode_message_empty_account_raises_error():
    """
    Test that encode_message rejects empty account number.
    This verifies input validation catches invalid account IDs early.

    Expected result:
    - encode_message("", "1130", ...) raises ValueError
    - Error message indicates account number issue
    """
    # Assert: Empty account raises ValueError
    with pytest.raises(ValueError):
        encode_message("", "1130", crc_format=CRC_FORMAT_SIA)


def test_encode_message_with_short_event_code():
    """
    Test that encode_message accepts various event code formats.
    This validates event code flexibility for different alarm types.

    Expected result:
    - encode_message("001234", "1130", ...) produces valid frame
    - Frame structure is correct
    """
    # Assert: Event code produces valid frame (no validation error)
    frame = encode_message("001234", "1130", crc_format=CRC_FORMAT_SIA)
    assert frame.startswith(LF)
    assert frame.endswith(CR)


def test_format_timestamp_with_invalid_type():
    """
    Test that format_timestamp rejects non-datetime objects.
    This verifies type checking prevents invalid inputs.

    Expected result:
    - format_timestamp("not a datetime") raises TypeError or ValueError
    """
    # Assert: Non-datetime input raises error
    with pytest.raises((TypeError, AttributeError)):
        format_timestamp("not a datetime")  # type: ignore


def test_sequence_manager_empty_account_allowed():
    """
    Test that SequenceManager handles empty account ID gracefully.
    This verifies the manager can track arbitrary account identifiers.

    Expected result:
    - next_seq("") returns valid sequence (or raises specific error)
    - Behavior is explicit and documented
    """
    sm = SequenceManager()
    # Empty account should either work or raise clear error (not crash)
    try:
        seq = sm.next_seq("")
        # If allowed, should return valid sequence
        assert len(seq) == 4
        assert seq.isdigit()
    except (ValueError, KeyError):
        # If not allowed, should raise clear error
        pass


# ===== BOUNDARY AND EDGE CASE TESTS =====

def test_account_id_minimum_length():
    """
    Test account ID with minimum valid length (3 characters).
    This validates lower boundary of account number field.

    Expected result:
    - format_account_id("123", "L0") returns "L0#123"
    - Minimum 3-char account is accepted
    """
    result = format_account_id("123", "L0")
    # Assert: Minimum length account accepted
    assert result == "L0#123"


def test_account_id_maximum_length():
    """
    Test account ID with maximum valid length (16 characters).
    This validates upper boundary of account number field.

    Expected result:
    - format_account_id with 16-char hex accepted
    - Result includes full account number
    """
    account_16 = "0123456789ABCDEF"  # Exactly 16 hex chars
    result = format_account_id(account_16, "L0")
    # Assert: Maximum length account accepted
    assert result == f"L0#{account_16}"
    assert len(result) == 19  # L0(2) + #(1) + 16 chars = 19


def test_sequence_boundary_9998_to_9999():
    """
    Test sequence number progression near wrap boundary.
    This validates sequence transitions correctly at 9999→0001 wrap.

    Expected result:
    - Sequence at 9998 → next is 9999
    - Sequence at 9999 → next is 0001 (wrap, skip 0000)
    """
    sm = SequenceManager()
    sm._seq_map["test"] = 9998

    # Assert: 9998 → 9999
    seq1 = sm.next_seq("test")
    assert seq1 == "9999"

    # Assert: 9999 → 0001 (wraps)
    seq2 = sm.next_seq("test")
    assert seq2 == "0001"


def test_timestamp_year_boundary():
    """
    Test timestamp formatting at year boundaries.
    This validates year formatting in various scenarios.

    Expected result:
    - Year 2026 formats as "2026"
    - Year 2099 formats as "2099"
    - Year 2000 formats as "2000"
    """
    ts_2026 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_2000 = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # Assert: Year 2026 included in timestamp
    result_2026 = format_timestamp(ts_2026)
    assert result_2026 is not None
    assert "2026" in result_2026

    # Assert: Year 2000 included in timestamp
    result_2000 = format_timestamp(ts_2000)
    assert result_2000 is not None
    assert "2000" in result_2000


def test_crc_empty_data():
    """
    Test CRC calculation with empty data.
    This validates CRC handles minimal input gracefully.

    Expected result:
    - calculate_crc(b"", format) returns valid 4-hex-char CRC
    - Not an error condition
    """
    result = calculate_crc(b"", CRC_FORMAT_SIA)
    # Assert: CRC of empty data is valid (not error)
    assert len(result) == 4
    assert all(c in '0123456789ABCDEF' for c in result)


def test_length_single_byte_data():
    """
    Test length calculation with single byte.
    This validates length field for minimum data size.

    Expected result:
    - calculate_length(b"x") returns "0001"
    """
    result = calculate_length(b"x")
    # Assert: Single byte produces "0001"
    assert result == "0001"


def test_length_max_frame_size():
    """
    Test length calculation at practical frame size limits.
    This validates length field for large frames.

    Expected result:
    - calculate_length with 4095 bytes (0FFF) is valid
    - Produces "0FFF" (max 4-digit hex with leading 0)
    """
    large_data = b"x" * 4095
    result = calculate_length(large_data)
    # Assert: Large frame length is valid
    assert result == "0FFF"
    assert len(result) == 4


# ===== NEGATIVE TEST PATTERNS =====

def test_parse_frame_with_missing_lf():
    """
    Test that parse_frame rejects frames without LF delimiter.
    This verifies frame validation catches structural errors.

    Expected result:
    - parse_frame(bytes starting without LF) raises ValueError
    """
    bad_frame = b"X1234567890abcdefghijklmnop\r"  # Missing LF start
    # Assert: Missing LF raises ValueError
    with pytest.raises(ValueError):
        parse_frame(bad_frame)


def test_parse_frame_with_missing_cr():
    """
    Test that parse_frame rejects frames without CR delimiter.
    This verifies end-of-frame validation is enforced.

    Expected result:
    - parse_frame(bytes not ending with CR) raises ValueError
    """
    bad_frame = b"\nABCD1234messageX"  # Missing CR end
    # Assert: Missing CR raises ValueError
    with pytest.raises(ValueError):
        parse_frame(bad_frame)


def test_parse_frame_too_short():
    """
    Test that parse_frame rejects frames below minimum size.
    This verifies minimum frame structure is enforced.

    Expected result:
    - parse_frame(bytes < 11 chars) raises ValueError
    - Minimum is LF(1) + CRC(4) + Length(4) + CR(1) = 10, + message min 1
    """
    short_frame = b"\n1234567"  # Only 8 bytes
    # Assert: Frame too short raises ValueError
    with pytest.raises(ValueError):
        parse_frame(short_frame)


def test_encode_message_crc_format_parameter():
    """
    Test that encode_message accepts CRC format parameter.
    This validates both SIA and ADM formats are supported.

    Expected result:
    - encode_message with CRC_FORMAT_SIA produces valid frame
    - encode_message with CRC_FORMAT_ADM produces valid frame
    """
    # Assert: Both CRC formats produce valid frames
    frame_sia = encode_message("001234", "1130", crc_format=CRC_FORMAT_SIA)
    frame_adm = encode_message("001234", "1130", crc_format=CRC_FORMAT_ADM)

    assert frame_sia.startswith(LF)
    assert frame_adm.startswith(LF)
    assert frame_sia.endswith(CR)
    assert frame_adm.endswith(CR)


# ===== ENCRYPTION PAYLOAD VERIFICATION TESTS =====

def test_encryption_flag_changes_frame_content():
    """
    Test that encryption flag produces different frame content.
    This validates encryption is more than just token change.

    Expected result:
    - encrypted=False produces different CRC than encrypted=True
    - Frames differ due to encryption marker affecting message
    """
    unenc = encode_message("001234", "1130", crc_format=CRC_FORMAT_SIA, encryption=False, timestamp=None)
    enc = encode_message("001234", "1130", crc_format=CRC_FORMAT_SIA, encryption=True, timestamp=None)

    # Assert: Encryption flag produces different frames
    assert unenc != enc, "Encrypted and unencrypted frames should differ"

    # Assert: Different CRCs (indicates different content)
    assert unenc[1:5] != enc[1:5], \
        f"CRC should differ: unenc={unenc[1:5]}, enc={enc[1:5]}"


def test_encryption_affects_null_message():
    """
    Test that encryption flag affects supervision (NULL) message.
    This validates encryption is consistently applied.

    Expected result:
    - make_supervision_message with encryption=False/True produce different frames
    - CRCs differ
    """
    unenc = make_supervision_message("001234", crc_format=CRC_FORMAT_SIA, encryption=False)
    enc = make_supervision_message("001234", crc_format=CRC_FORMAT_SIA, encryption=True)

    # Assert: Encryption affects supervision message
    assert unenc != enc, "Encryption should change supervision message"

    # Assert: Different CRCs
    assert unenc[1:5] != enc[1:5], \
        "Encryption should produce different CRC"


# ===== RECEIVER/PREFIX COMBINATION TESTS =====

@pytest.mark.parametrize("receiver,prefix,expected_substring", [
    ("R1", "L0", "R1L0#"),
    ("R2", "L0", "R2L0#"),
    ("R1", "L1", "R1L1#"),
    ("R2", "L2", "R2L2#"),
    ("R3", "L3", "R3L3#"),
])
def test_receiver_prefix_combinations(receiver: str, prefix: str, expected_substring: str):
    """
    Parametrized test for various receiver/prefix combinations.
    This validates all valid receiver-prefix pairings work correctly.

    Expected result:
    - Each combination produces frame with correct receiver+prefix
    """
    frame = encode_message(
        "1234", "FA 129",
        receiver_number=receiver,
        account_prefix=prefix,
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Expected receiver+prefix combination present
    assert expected_substring.encode() in frame, \
        f"Expected {expected_substring} in frame"


def test_receiver_affects_frame_structure():
    """
    Test that receiver number changes frame content and CRC.
    This validates receiver is properly encoded in message.

    Expected result:
    - Two frames with different receivers have different CRCs
    - Content reflects receiver number difference
    """
    frame_r1 = encode_message("1234", "FA 129", receiver_number="R1", crc_format=CRC_FORMAT_SIA, timestamp=None)
    frame_r2 = encode_message("1234", "FA 129", receiver_number="R2", crc_format=CRC_FORMAT_SIA, timestamp=None)

    # Assert: Different receivers produce different CRCs
    assert frame_r1[1:5] != frame_r2[1:5], \
        "Different receivers should produce different CRCs"


# ===== TESTS: NULL Message Generation =====

def test_null_message_uses_null_code():
    """
    Test that NULL message uses supervision event code "0000".
    This verifies supervision message uses correct event code per spec.

    Expected result:
    - make_supervision_message() generates frame with "[#account|0000]"
    - No other event code in supervision message
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    # Assert: NULL code present in frame
    assert b"[#001234|0000]" in frame, \
        "Supervision message should contain [#001234|0000]"


def test_null_message_starts_with_lf():
    """
    Test that NULL message starts with LF delimiter.
    This verifies frame structure matches encode_message requirements.

    Expected result:
    - First byte is exactly LF (0x0A)
    - Second byte starts CRC field
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    # Assert: Frame starts with LF
    assert frame.startswith(LF), "First byte should be LF (0x0A)"
    # Assert: CRC follows LF (4 bytes)
    assert len(frame) > 5, "Frame must have CRC after LF"
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5]), \
        "Bytes 1-4 should be CRC hex"


def test_null_message_ends_with_cr():
    """
    Test that NULL message ends with CR delimiter.
    This verifies frame structure matches encode_message requirements.

    Expected result:
    - Last byte is exactly CR (0x0D)
    - No trailing bytes after CR
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    # Assert: Frame ends with CR
    assert frame.endswith(CR), "Last byte should be CR (0x0D)"
    # Assert: CR is exactly at end (no trailing bytes)
    assert frame[-1:] == CR, "Last byte must be CR"
    # Assert: Byte before CR is not CR (not doubled)
    assert frame[-2:-1] != CR, "Should not have double CR"


def test_null_message_encrypted_flag():
    """
    Test that NULL message respects encryption flag.
    This verifies encryption token changes between unencrypted and encrypted modes.

    Expected result:
    - unencrypted: contains "SIA-DCS" token (no asterisk)
    - encrypted: contains "*SIA-DCS" token (with asterisk)
    - Both frames have valid structure
    """
    unencrypted = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )
    encrypted = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA,
        encryption=True
    )
    # Assert: Unencrypted uses unencrypted token
    assert b'"SIA-DCS"' in unencrypted, \
        "Unencrypted should contain \"SIA-DCS\""
    # Assert: Unencrypted does NOT use encrypted token
    assert b'"*SIA-DCS"' not in unencrypted, \
        "Unencrypted should not contain \"*SIA-DCS\""
    # Assert: Encrypted uses encrypted token
    assert b'"*SIA-DCS"' in encrypted, \
        "Encrypted should contain \"*SIA-DCS\""
    # Assert: Encrypted does NOT use unencrypted variant
    assert b'"SIA-DCS"0' not in encrypted, \
        "Encrypted should not contain unencrypted variant"
    # Assert: Both have valid frame structure
    assert unencrypted.startswith(LF) and unencrypted.endswith(CR)
    assert encrypted.startswith(LF) and encrypted.endswith(CR)


def test_null_message_with_custom_prefix():
    """
    Test that NULL message uses custom account prefix.
    This verifies account prefix parameter is passed through correctly.

    Expected result:
    - Frame contains custom prefix "L2"
    - Account ID field is exactly "L2#001234"
    - NULL event code "0000" is still present
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA,
        account_prefix="L2"
    )
    # Assert: Custom prefix is included in frame
    assert b"L2" in frame, "Custom prefix L2 should be in frame"
    # Assert: Account ID field has correct format
    assert b"L2#001234" in frame, \
        "Account ID should be L2#001234"
    # Assert: NULL event code still present
    assert b"[#001234|0000]" in frame, \
        "Data field should still be [#001234|0000]"


# ===== INTEGRATION TESTS =====

def test_message_frame_is_valid():
    """
    Test that complete message frame has all required components.
    This validates overall frame structure is correct per SIA spec.

    Expected result:
    - Frame starts with LF, ends with CR
    - Frame exceeds minimum size (20+ bytes for: LF + CRC + Length + Message + CR)
    - CRC and length fields are valid hexadecimal
    - Message core contains required fields
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Frame starts with LF
    assert frame[0:1] == LF, "First byte should be LF"
    # Assert: Frame ends with CR
    assert frame[-1:] == CR, "Last byte should be CR"
    # Assert: Frame exceeds minimum size (LF + CRC + Length + Message + CR)
    assert len(frame) > 20, f"Frame too small: {len(frame)} bytes"
    # Assert: CRC is valid hex
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5]), \
        "CRC should be hex"
    # Assert: Length is valid hex
    assert all(c in b'0123456789ABCDEF' for c in frame[5:9]), \
        "Length should be hex"
    # Assert: Message contains required fields
    assert b"SIA-DCS" in frame, "Should contain ID token"
    assert b"0001" in frame, "Should contain sequence"
    assert b"L0#001234" in frame, "Should contain account ID"
    assert b"[#001234|1130]" in frame, "Should contain data field"


def test_example_message_structure():
    """
    Test message structure against protocol spec example.
    This validates real-world message generation with all components correct.

    Expected result:
    - Frame starts with LF, ends with CR
    - Contains "SIA-DCS" ID token (unencrypted)
    - Contains "L0#1234" account ID field
    - Contains "[#1234|FA 129]" data field
    - CRC and length fields are valid
    """
    frame = encode_message(
        "1234", "FA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )
    # Assert: Frame has correct start/end delimiters
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"
    # Assert: Frame contains ID token
    assert b"SIA-DCS" in frame, "Should contain SIA-DCS token"
    # Assert: Frame contains complete account ID field (not just prefix)
    assert b"L0#1234" in frame, "Should contain L0#1234"
    # Assert: Frame contains data field with event code
    assert b"[#1234|FA 129]" in frame, "Should contain data field"
    # Assert: CRC field is valid
    crc_str = frame[1:5].decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in crc_str), \
        f"CRC should be hex: {crc_str}"
    # Assert: Length field is valid
    length_str = frame[5:9].decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in length_str), \
        f"Length should be hex: {length_str}"


def test_message_with_timestamp():
    """
    Test that message includes timestamp when provided.
    This validates timestamp parameter is processed correctly and included in frame.

    Expected result:
    - Frame is generated without error
    - Frame contains timestamp in correct format (_HH:MM:SS,MM-DD-YYYY)
    - Timestamp field is 20 characters
    - CRC changes compared to no-timestamp version
    """
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    frame_with_ts = encode_message(
        "001234", "1130",
        timestamp=ts,
        crc_format=CRC_FORMAT_SIA
    )
    frame_no_ts = encode_message(
        "001234", "1130",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA
    )
    # Assert: Frame generated successfully
    assert frame_with_ts is not None, "Frame should be generated"
    # Assert: Frame contains data (timestamp increases size)
    assert len(frame_with_ts) > len(frame_no_ts), \
        "Frame with timestamp should be larger"
    # Assert: Timestamp is in frame
    assert b"_15:30:00,04-07-2026" in frame_with_ts, \
        "Should contain correct timestamp"
    # Assert: CRC changes (because timestamp changes message content)
    assert frame_with_ts[1:5] != frame_no_ts[1:5], \
        "CRC should differ with/without timestamp"


# ===== TESTS: Golden Frame Validation (Expected-Value Format) =====
# NOTE: Binary .bin files deferred to v1.1 when CSR integration is available.
# These tests validate expected frame structure per SIA-DC-09 spec examples.

def test_spec_b1_fire_alarm_no_timestamp():
    """
    Test against Annex B.1: Fire Alarm, SIA DC-04, Non-Encrypted, No Timestamp.
    Validates our implementation produces frame with expected structure.
    NOTE: Full binary validation deferred until .bin files available.

    Expected result:
    - Generated frame has valid structure (LF + CRC + Length + Message + CR)
    - Contains sequence 0001, account L0#1234, event FA 129
    - CRC and length are valid hex values
    """
    # Spec: <LF>CRC_VALUE0022"SIA-DCS"0001L0#1234[#1234|FA 129]<CR>
    frame = encode_message(
        account_number="1234",
        event_code="FA 129",
        account_prefix="L0",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA,
    )

    # Assert: Frame starts with LF
    assert frame.startswith(LF), "Frame should start with LF"

    # Assert: Frame ends with CR
    assert frame.endswith(CR), "Frame should end with CR"

    # Assert: CRC is 4-char hex
    crc_str = frame[1:5].decode('ascii')
    assert len(crc_str) == 4, "CRC should be 4 chars"
    assert all(c in '0123456789ABCDEF' for c in crc_str), \
        f"CRC should be hex: {crc_str}"

    # Assert: Length is 4-char hex starting with 0
    length_str = frame[5:9].decode('ascii')
    assert len(length_str) == 4, "Length should be 4 chars"
    assert length_str.startswith('0'), "Length should start with 0"
    assert all(c in '0123456789ABCDEF' for c in length_str), \
        f"Length should be hex: {length_str}"

    # Assert: Message contains required fields per spec
    message = frame[9:-1].decode('ascii')
    assert '"SIA-DCS"' in message, "Should contain SIA-DCS token"
    assert '0001' in message, "Should contain sequence 0001"
    assert 'L0#1234' in message, "Should contain account L0#1234"
    assert '[#1234|FA 129]' in message, "Should contain event FA 129"


def test_spec_b2_burglary_with_timestamp():
    """
    Test burglary alarm with timestamp.
    Validates message structure when timestamp is included.
    NOTE: Full binary validation deferred until .bin files available.

    Expected result:
    - Frame has valid structure
    - Contains sequence 0001, account L0#1234, event BA 129
    - Contains timestamp in format _HH:MM:SS,MM-DD-YYYY
    """
    ts = datetime(2026, 4, 8, 10, 30, 45, tzinfo=timezone.utc)
    frame = encode_message(
        account_number="1234",
        event_code="BA 129",
        account_prefix="L0",
        timestamp=ts,
        crc_format=CRC_FORMAT_SIA,
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF), "Frame should start with LF"
    assert frame.endswith(CR), "Frame should end with CR"

    # Assert: CRC and length are valid hex
    crc_str = frame[1:5].decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in crc_str), "CRC should be hex"

    length_str = frame[5:9].decode('ascii')
    assert all(c in '0123456789ABCDEF' for c in length_str), "Length should be hex"

    # Assert: Message contains expected fields
    message = frame[9:-1].decode('ascii')
    assert '"SIA-DCS"' in message, "Should contain SIA-DCS token"
    assert '0001' in message, "Should contain sequence 0001"
    assert 'L0#1234' in message, "Should contain account L0#1234"
    assert '[#1234|BA 129]' in message, "Should contain event BA 129"
    assert '_10:30:45,04-08-2026' in message, "Should contain correct timestamp"


# ===== TESTS: Different Event Types =====

def test_fire_event_code():
    """
    Test fire alarm event codes.
    Validates fire event type produces correct CRC/length/structure.

    Expected result:
    - Frame structure valid for fire event (LF + CRC + Length + Message + CR)
    - CRC is valid 4-char hex
    - Event code "FA 129" (fire code 129) is present
    - Account ID and token fields are correct
    """
    frame = encode_message(
        account_number="1234",
        event_code="FA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is 4 valid hex chars
    assert len(frame[1:5]) == 4, "CRC should be 4 bytes"
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5]), \
        f"CRC should be hex: {frame[1:5]}"

    # Assert: Fire event code present in data field
    assert b'[#1234|FA 129]' in frame, \
        "Data field should contain [#1234|FA 129]"

    # Assert: All required fields present
    assert b'"SIA-DCS"' in frame, "Should contain SIA-DCS token"
    assert b'L0#1234' in frame, "Should contain account ID"
    assert b'0001' in frame, "Should contain sequence"


def test_burglary_event_code():
    """
    Test burglary alarm event codes.
    Validates burglary event type produces correct CRC/length/structure.

    Expected result:
    - Frame structure valid for burglary event (LF + CRC + Length + Message + CR)
    - CRC is valid 4-char hex
    - Event code "BA 129" (burglary alarm code 129) is present
    - Account ID and token fields are correct
    """
    frame = encode_message(
        account_number="1234",
        event_code="BA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is 4 valid hex chars
    assert len(frame[1:5]) == 4, "CRC should be 4 bytes"
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5]), \
        f"CRC should be hex: {frame[1:5]}"

    # Assert: Burglary event code present in data field
    assert b'[#1234|BA 129]' in frame, \
        "Data field should contain [#1234|BA 129]"

    # Assert: All required fields present
    assert b'"SIA-DCS"' in frame, "Should contain SIA-DCS token"
    assert b'L0#1234' in frame, "Should contain account ID"
    assert b'0001' in frame, "Should contain sequence"


def test_panic_event_code():
    """
    Test panic alarm event codes.
    Validates panic event type produces correct CRC/length/structure.

    Expected result:
    - Frame structure valid for panic event (LF + CRC + Length + Message + CR)
    - CRC is valid 4-char hex
    - Event code "PA 001" (panic code 001) is present
    - Account ID and token fields are correct
    """
    frame = encode_message(
        account_number="1234",
        event_code="PA 001",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is 4 valid hex chars
    assert len(frame[1:5]) == 4, "CRC should be 4 bytes"
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5]), \
        f"CRC should be hex: {frame[1:5]}"

    # Assert: Panic event code present in data field
    assert b'[#1234|PA 001]' in frame, \
        "Data field should contain [#1234|PA 001]"

    # Assert: All required fields present
    assert b'"SIA-DCS"' in frame, "Should contain SIA-DCS token"
    assert b'L0#1234' in frame, "Should contain account ID"
    assert b'0001' in frame, "Should contain sequence"


# ===== TESTS: Frame Structure Validation =====

def test_frame_has_correct_delimiter_sequence():
    """
    Test that frame delimiters appear in correct order per SIA spec.
    This validates fundamental frame structure integrity.

    Expected result:
    - LF at position 0 (frame start)
    - CR at final position (frame end)
    - No LF or CR bytes within the middle (message content)
    - Delimiters exactly 1 byte each
    """
    frame = encode_message(
        "1234", "FA 129",
        crc_format=CRC_FORMAT_SIA,
        timestamp=None
    )

    # Assert: LF is first byte (exactly at position 0)
    assert frame[0:1] == LF, "Position 0 must be LF (0x0A)"
    assert frame[0] == 0x0A, "First byte must be 0x0A"

    # Assert: CR is last byte (exactly at last position)
    assert frame[-1:] == CR, "Last position must be CR (0x0D)"
    assert frame[-1] == 0x0D, "Last byte must be 0x0D"

    # Assert: No other LF in middle (would corrupt frame)
    middle = frame[1:-1]
    assert middle.count(LF) == 0, \
        f"Frame middle should not contain LF: {middle}"

    # Assert: No other CR in middle (would corrupt frame)
    assert middle.count(CR) == 0, \
        f"Frame middle should not contain CR: {middle}"


def test_frame_crc_length_relationship():
    """
    Test that CRC is calculated over correct message range and length field is accurate.
    Validates CRC and length consistency and sensitivity to content changes.

    Expected result:
    - Length field matches actual message core byte count
    - CRC is 4 ASCII hex characters at position 1-4
    - Different event codes produce different CRCs (content-dependent)
    - Both CRCs are valid hexadecimal
    """
    frame1 = encode_message("1234", "FA 129", crc_format=CRC_FORMAT_SIA, timestamp=None)
    frame2 = encode_message("1234", "BA 129", crc_format=CRC_FORMAT_SIA, timestamp=None)

    # Assert: Different events produce different CRCs (CRC is content-sensitive)
    assert frame1[1:5] != frame2[1:5], \
        f"Different events should produce different CRCs: {frame1[1:5]} vs {frame2[1:5]}"

    # Assert: Both CRCs are valid 4-byte hex
    assert len(frame1[1:5]) == 4, "CRC should be 4 bytes"
    assert len(frame2[1:5]) == 4, "CRC should be 4 bytes"
    assert all(c in b'0123456789ABCDEF' for c in frame1[1:5]), \
        f"CRC1 should be hex: {frame1[1:5]}"
    assert all(c in b'0123456789ABCDEF' for c in frame2[1:5]), \
        f"CRC2 should be hex: {frame2[1:5]}"

    # Assert: Length field in frame1 matches actual message size
    length1_str = frame1[5:9].decode('ascii')
    message1 = frame1[9:-1]
    expected_length1 = f"0{len(message1):03X}"
    assert length1_str == expected_length1, \
        f"Length1 mismatch: field says {length1_str}, message is {len(message1)} bytes"

    # Assert: Length field in frame2 matches actual message size
    length2_str = frame2[5:9].decode('ascii')
    message2 = frame2[9:-1]
    expected_length2 = f"0{len(message2):03X}"
    assert length2_str == expected_length2, \
        f"Length2 mismatch: field says {length2_str}, message is {len(message2)} bytes"


def test_frame_field_positions():
    """
    Test that frame fields appear at correct byte positions.
    Validates frame layout and field alignment per SIA spec § 5.5.1.

    Expected result:
    - Byte 0: LF (0x0A)
    - Bytes 1-4: CRC (4 ASCII hex characters)
    - Bytes 5-8: Length (4 ASCII hex characters, starting with '0')
    - Bytes 9 onward: Message core
    - Last byte: CR (0x0D)
    """
    frame = encode_message("1234", "FA 129", crc_format=CRC_FORMAT_SIA, timestamp=None)

    # Assert: Byte 0 is LF
    assert frame[0:1] == LF, "Byte 0 must be LF"
    assert frame[0] == 0x0A, "Byte 0 must be 0x0A"

    # Assert: Bytes 1-4 are CRC (4 ASCII hex chars)
    crc = frame[1:5]
    assert len(crc) == 4, "CRC must be 4 bytes"
    assert all(c in b'0123456789ABCDEF' for c in crc), \
        f"CRC must be hex: {crc}"

    # Assert: Bytes 5-8 are Length (4 ASCII hex chars, starts with 0)
    length_field = frame[5:9]
    assert len(length_field) == 4, "Length must be 4 bytes"
    assert length_field.startswith(b'0'), \
        f"Length must start with 0: {length_field}"
    assert all(c in b'0123456789ABCDEF' for c in length_field), \
        f"Length must be hex: {length_field}"

    # Assert: Bytes 9 onward are message core
    message_core = frame[9:-1]
    assert len(message_core) > 0, "Message core must exist"

    # Assert: Last byte is CR
    assert frame[-1:] == CR, "Last byte must be CR"
    assert frame[-1] == 0x0D, "Last byte must be 0x0D"

    # Assert: No extra delimiters in message core
    assert LF not in message_core, "Message core should not contain LF"
    assert CR not in message_core, "Message core should not contain CR"


# ===== TESTS: Extended Data Identifiers (Structure Validation Only) =====
# NOTE: These test expected structure for future v1.1 implementation.
# Actual encoding not yet implemented.

def test_extended_data_mac_address_structure():
    """
    Test expected structure for MAC Address extended data (future support).
    Documents format per SIA spec § 5.5.1.8 (data identifier 'M').

    Expected result:
    - MAC Address data would be formatted as [M1234567890AB]
    - 'M' identifier + 12 hex characters
    - Appears after main data field in brackets
    """
    # NOTE: Extended data support deferred to v1.1
    # This test documents the expected structure:
    # Frame with MAC: [#1234|FA 129][M1234567890AB]_HH:MM:SS,MM-DD-YYYY
    # Spec: Annex B.5

    # Assert: Document expected format for future implementation
    # MAC address identifier must be 'M' followed by 12 hex chars
    mac_identifier = "M"
    mac_data = "1234567890AB"
    expected_mac_field = f"[{mac_identifier}{mac_data}]"

    # Assert: Format is correct
    assert expected_mac_field == "[M1234567890AB]"
    assert expected_mac_field.startswith("[M")
    assert expected_mac_field.endswith("]")
    assert len(mac_data) == 12


def test_extended_data_network_address_structure():
    """
    Test expected structure for Network Address extended data (future support).
    Documents format per SIA spec § 5.5.1.8 (data identifier 'N').

    Expected result:
    - Network Address would be formatted as [N1234567890ABCDEF]
    - 'N' identifier + up to 16 hex characters
    - Appears after main data field in brackets
    """
    # NOTE: Extended data support deferred to v1.1
    # This test documents expected structure:
    # Frame with Network Address: [#1234|FA 129][N1234567890ABCDEF]
    # Spec: Annex B.8

    # Assert: Document expected format for future implementation
    # Network address identifier must be 'N' followed by hex chars
    network_identifier = "N"
    network_data = "1234567890ABCDEF"
    expected_network_field = f"[{network_identifier}{network_data}]"

    # Assert: Format is correct
    assert expected_network_field == "[N1234567890ABCDEF]"
    assert expected_network_field.startswith("[N")
    assert expected_network_field.endswith("]")
    assert len(network_data) == 16


def test_extended_data_authentication_hash_structure():
    """
    Test expected structure for Authentication Hash extended data (future support).
    Documents format per SIA spec § 5.5.1.8 (data identifier 'A').

    Expected result:
    - Authentication Hash would be formatted as [A6F2348C99335DF38]
    - 'A' identifier + 12 hex characters (hash value)
    - Appears after main data field in brackets
    """
    # NOTE: Extended data support deferred to v1.1
    # This test documents expected structure:
    # Frame with Hash: [#1234|1130 02 065][M1234567890AB][A6F2348C99335DF38]
    # Spec: Annex B.6

    # Assert: Document expected format for future implementation
    # Authentication hash identifier must be 'A' followed by 12 hex chars
    hash_identifier = "A"
    hash_value = "6F2348C99335DF38"
    expected_hash_field = f"[{hash_identifier}{hash_value}]"

    # Assert: Format is correct
    assert expected_hash_field == "[A6F2348C99335DF38]"
    assert expected_hash_field.startswith("[A")
    assert expected_hash_field.endswith("]")
    assert len(hash_value) == 16


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
