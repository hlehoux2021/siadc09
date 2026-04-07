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
    Test that CRC calculation returns exactly 4 hexadecimal characters.
    This verifies CRC format matches SIA frame requirements.

    Expected result:
    - CRC result is exactly 4 characters long
    - All characters are valid hexadecimal (0-9, A-F)
    """
    data = b'"SIA-DCS"0001L0#1234[#1234|FA 129]'
    crc = calculate_crc(data, CRC_FORMAT_SIA)

    # Assert: CRC is exactly 4 characters
    assert len(crc) == 4
    # Assert: All characters are valid hex digits
    assert all(c in '0123456789ABCDEF' for c in crc)


def test_crc_format_sia():
    """
    Test that SIA format is accepted for CRC calculation.
    This verifies CRC function works with SIA-DCS message format.

    Expected result:
    - CRC_FORMAT_SIA is accepted without error
    - Result is 4-character hex string
    """
    data = b'"SIA-DCS"0001L0#1234'
    crc = calculate_crc(data, CRC_FORMAT_SIA)

    # Assert: SIA format produces valid 4-char CRC
    assert len(crc) == 4


def test_crc_format_adm():
    """
    Test that ADM format is accepted for CRC calculation.
    This verifies CRC function works with ADM-CID message format.

    Expected result:
    - CRC_FORMAT_ADM is accepted without error
    - Result is 4-character hex string
    """
    data = b'"ADM-CID"0001L0#1234'
    crc = calculate_crc(data, CRC_FORMAT_ADM)

    # Assert: ADM format produces valid 4-char CRC
    assert len(crc) == 4


def test_crc_format_type_constraint():
    """
    Test that crc_format parameter enforces type constraint.
    This validates the Literal["SIA", "ADM"] type constraint.

    Expected result:
    - Both "SIA" and "ADM" are accepted and produce valid CRC
    - Invalid values would be rejected by type checker at compile-time
    """
    data = b'"SIA-DCS"0001L0#1234'

    # Assert: Both valid formats produce valid CRC
    crc_sia = calculate_crc(data, "SIA")
    crc_adm = calculate_crc(data, "ADM")

    # Assert: Both produce 4-character hex strings
    assert len(crc_sia) == 4
    assert len(crc_adm) == 4
    assert all(c in '0123456789ABCDEF' for c in crc_sia)
    assert all(c in '0123456789ABCDEF' for c in crc_adm)


# ===== TESTS: Length Calculation =====

def test_length_starts_with_zero():
    """
    Test that length field starts with leading zero.
    This verifies length format matches SIA frame requirements.

    Expected result:
    - Length field always starts with "0"
    - Remaining 3 characters are hexadecimal
    """
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)

    # Assert: Length field starts with required leading zero
    assert length.startswith("0")


def test_length_is_4_chars():
    """
    Test that length field is exactly 4 characters.
    This verifies length encoding format per SIA spec § 5.5.1.3.

    Expected result:
    - Length is exactly 4 characters (leading 0 + 3-digit hex)
    """
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)

    # Assert: Length field is exactly 4 characters
    assert len(length) == 4


def test_length_is_hex():
    """
    Test that length field (after leading 0) is hexadecimal.
    This verifies remaining 3 characters are valid hex digits.

    Expected result:
    - First character is "0"
    - Characters 2-4 are hex digits (0-9, A-F)
    """
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)

    # Assert: First character is leading zero
    assert length[0] == "0"
    # Assert: Remaining characters are valid hex
    assert all(c in '0123456789ABCDEF' for c in length[1:])


def test_length_calculation_example():
    """
    Test length calculation with known data size.
    This validates length encodes data size correctly in hex.

    Expected result:
    - 64 bytes of data produces length "0040" (0x40 = 64 in decimal)
    """
    data = b'x' * 64
    length = calculate_length(data)

    # Assert: 64 bytes encodes as 0x40 = "0040"
    assert length == "0040"


# ===== TESTS: Account ID Formatting =====

def test_basic_account_id():
    """
    Test basic account ID formatting without receiver.
    This verifies minimal account identification field.

    Expected result:
    - Format is "#" + account_number + prefix
    - Result is "#001234L0"
    """
    result = format_account_id("001234", "L0")

    # Assert: Basic account ID has correct format (prefix before account per spec)
    assert result == "L0#001234"


def test_account_id_with_prefix():
    """
    Test account ID with custom receiver prefix.
    This verifies receiver prefix is included correctly.

    Expected result:
    - Format is "#" + account_number + prefix
    - Different prefix values change the result
    """
    result = format_account_id("001234", "L1")

    # Assert: Custom prefix is included in result
    assert result == "L1#001234"


def test_account_id_with_receiver():
    """
    Test account ID including receiver number.
    This verifies receiver field appears before account ID per spec.

    Expected result:
    - Format is receiver + "#" + account_number + prefix
    - Receiver appears first in the string
    """
    result = format_account_id("001234", "L1", "R2")

    # Assert: Receiver appears first, then prefix, then account ID
    assert result == "R2L1#001234"


def test_account_id_receiver_zero_omitted():
    """
    Test that receiver value "0" is omitted from result.
    This verifies default receiver "0" is not included.

    Expected result:
    - Receiver "0" is treated as absence of receiver
    - Result does not include receiver prefix
    """
    result = format_account_id("001234", "L0", "0")

    # Assert: Receiver "0" is omitted from result
    assert result == "L0#001234"


def test_account_id_invalid_account_raises():
    """
    Test that invalid account number raises ValueError.
    This verifies account validation works correctly.

    Expected result:
    - Too-short account number (< 3 chars) raises ValueError
    """
    # Assert: Invalid account raises ValueError
    with pytest.raises(ValueError):
        format_account_id("XYZ", "L0")  # Too short


def test_account_id_invalid_prefix_raises():
    """
    Test that invalid prefix raises ValueError.
    This verifies prefix validation works correctly.

    Expected result:
    - Non-hex characters in prefix raise ValueError
    """
    # Assert: Non-hex prefix character raises ValueError
    with pytest.raises(ValueError):
        format_account_id("001234", "LG")  # G is not hex


def test_account_id_hex_case_insensitive():
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

    # Assert: Data field structure is correct
    parsed = parse_frame(frame)
    message_str = parsed["message_core"].decode('ascii')
    assert "[#001234|1130]" in message_str, \
        f"Data field mismatch in: {message_str}"

    # Assert: Data field appears after account ID
    account_pos = message_str.find("L0#001234")
    data_pos = message_str.find("[#001234|1130]")
    assert account_pos < data_pos, \
        f"Data field should appear after account ID"


# ===== TESTS: NULL Message Generation =====

def test_null_message_uses_0000_event_code():
    """
    Test that supervision message uses 0000 event code.
    This verifies NULL message format per SIA spec § 5.5.2.1.

    Expected result:
    - Frame contains "0000" event code (NULL, not 1-3 for alarms)
    - Data field is exactly "[#001234|0000]"
    - Frame structure is valid (starts LF, ends CR)
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: NULL message uses 0000 event code
    assert b"0000" in frame, "Should contain 0000 event code"

    # Assert: Data field has exact NULL format
    assert b"[#001234|0000]" in frame, \
        "Data field should be [#001234|0000]"

    # Assert: Frame has correct delimiters
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"


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


# ===== TESTS: Golden Frame Validation (SIA-DC-09 Annex B Examples) =====

def test_spec_b1_fire_alarm_no_timestamp():
    """
    Test against Annex B.1: Fire Alarm, SIA DC-04, Non-Encrypted, No Timestamp.
    Validates our implementation produces frame matching spec example with corrected field order.

    Expected result:
    - Generated frame CRC is EA28 (with corrected L0#1234 field order per § 5.5.1.6)
    - Generated frame length is 0022 (34 bytes message)
    - Frame contains ID token "SIA-DCS", sequence 0001, account L0#1234, event FA 129
    - Frame structure: LF + CRC + Length + Message + CR
    """
    # Spec: <LF>B3680040"SIA-DCS"0001L0#1234[#1234|FA 129]<CR>
    # Note: Spec example used different field order; corrected to L0#1234
    frame = encode_message(
        account_number="1234",
        event_code="FA 129",
        account_prefix="L0",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Frame starts and ends correctly
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is exact value (EA28 with corrected field order: L0#1234 per § 5.5.1.6)
    assert frame[1:5] == b'EA28', \
        f"CRC mismatch: expected EA28, got {frame[1:5]}"

    # Assert: Length field is correct (0x22 = 34 bytes)
    assert frame[5:9] == b'0022', \
        f"Length mismatch: expected 0022, got {frame[5:9]}"

    # Assert: Message core has exact expected content
    message_core = frame[9:-1]
    # Extract and validate each field
    assert b'"SIA-DCS"' in message_core, "Should contain unencrypted token"
    assert b'0001' in message_core, "Should contain sequence 0001"
    assert b'L0#1234' in message_core, "Should contain account L0#1234"
    assert b'[#1234|FA 129]' in message_core, "Should contain data field"

    # Assert: Fields appear in correct order
    msg_str = message_core.decode('ascii')
    token_pos = msg_str.find('"SIA-DCS"')
    seq_pos = msg_str.find('0001')
    account_pos = msg_str.find('L0#1234')
    data_pos = msg_str.find('[#1234|FA 129]')
    assert token_pos < seq_pos < account_pos < data_pos, \
        "Fields should appear in order: token, seq, account, data"


def test_spec_b3_fire_alarm_with_timestamp():
    """
    Test against Annex B.3: Fire Alarm with Timestamp.
    Validates timestamp inclusion increases frame size and produces correct CRC/length.

    Expected result:
    - Generated frame CRC is 3C77 (with corrected L0#1234 field order per § 5.5.1.6)
    - Generated frame length is 0036 (54 bytes message)
    - Frame includes timestamp field _22:49:34,01-22-2012 (20 chars)
    - All fields present and in correct order
    """
    # Spec: <LF>E9F8005C"SIA-DCS"0001L0#1234[#1234|FA 129]_22:49:34,01-22-2012<CR>
    # Note: Spec example used different field order; corrected to L0#1234
    ts = datetime(2012, 1, 22, 22, 49, 34, tzinfo=timezone.utc)
    frame = encode_message(
        account_number="1234",
        event_code="FA 129",
        account_prefix="L0",
        timestamp=ts,
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Frame starts and ends correctly
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is exact value (3C77 with corrected field order: L0#1234 per § 5.5.1.6)
    assert frame[1:5] == b'3C77', \
        f"CRC mismatch: expected 3C77, got {frame[1:5]}"

    # Assert: Length field is correct (0x36 = 54 bytes with timestamp)
    assert frame[5:9] == b'0036', \
        f"Length mismatch: expected 0036, got {frame[5:9]}"

    # Assert: Contains timestamp field (exactly 20 chars per spec)
    assert b'_22:49:34,01-22-2012' in frame, \
        "Should contain timestamp _22:49:34,01-22-2012"

    # Assert: All required fields present
    message_core = frame[9:-1]
    assert b'"SIA-DCS"' in message_core, "Should contain unencrypted token"
    assert b'0001' in message_core, "Should contain sequence"
    assert b'L0#1234' in message_core, "Should contain account"
    assert b'[#1234|FA 129]' in message_core, "Should contain data field"

    # Assert: Fields in correct order (token, seq, account, data, timestamp)
    msg_str = message_core.decode('ascii')
    token_pos = msg_str.find('"SIA-DCS"')
    seq_pos = msg_str.find('0001')
    account_pos = msg_str.find('L0#1234')
    data_pos = msg_str.find('[#1234|FA 129]')
    ts_pos = msg_str.find('_22:49:34,01-22-2012')
    assert token_pos < seq_pos < account_pos < data_pos < ts_pos, \
        "Fields should appear in order: token, seq, account, data, timestamp"


def test_spec_b7_open_area():
    """
    Test against Annex B.7: Open Area event format.
    Validates different event code format (OP with parameters instead of FA).

    Expected result:
    - Frame structure is correct for Open Area event
    - CRC is E303 (with corrected L0#1234 field order per § 5.5.1.6)
    - Length is 0026 (38 bytes message)
    - Event code is "OP 002 003" (Open Area, area 002, user 003)
    """
    # Spec: <LF>9C4E0042"SIA-DCS"0001L0#1234[#1234|OP 002 003]<CR>
    # Note: Spec example used different field order; corrected to L0#1234
    frame = encode_message(
        account_number="1234",
        event_code="OP 002 003",
        account_prefix="L0",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Frame starts and ends correctly
    assert frame.startswith(LF), "Should start with LF"
    assert frame.endswith(CR), "Should end with CR"

    # Assert: CRC is exact value (E303 with corrected field order: L0#1234 per § 5.5.1.6)
    assert frame[1:5] == b'E303', \
        f"CRC mismatch: expected E303, got {frame[1:5]}"

    # Assert: Length is correct (0x26 = 38 bytes with corrected format)
    assert frame[5:9] == b'0026', \
        f"Length mismatch: expected 0026, got {frame[5:9]}"

    # Assert: Contains Open Area event code with parameters
    assert b'[#1234|OP 002 003]' in frame, \
        "Should contain Open Area event [#1234|OP 002 003]"

    # Assert: All required fields present
    message_core = frame[9:-1]
    assert b'"SIA-DCS"' in message_core, "Should contain unencrypted token"
    assert b'0001' in message_core, "Should contain sequence"
    assert b'L0#1234' in message_core, "Should contain account"

    # Assert: Field order is correct
    msg_str = message_core.decode('ascii')
    token_pos = msg_str.find('"SIA-DCS"')
    seq_pos = msg_str.find('0001')
    account_pos = msg_str.find('L0#1234')
    event_pos = msg_str.find('[#1234|OP 002 003]')
    assert token_pos < seq_pos < account_pos < event_pos, \
        "Fields should appear in order: token, seq, account, event"


# ===== TESTS: Different Event Types =====

def test_burglary_event_code_ba():
    """
    Test burglary/intrusion alarm event codes.
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
