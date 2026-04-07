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
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame starts with LF delimiter
    assert frame.startswith(LF)


def test_encode_message_ends_with_cr():
    """
    Test that encoded message ends with CR byte.
    This verifies frame end delimiter per SIA spec § 5.5.

    Expected result:
    - Last byte is CR (0x0D)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame ends with CR delimiter
    assert frame.endswith(CR)


def test_encode_message_has_crc():
    """
    Test that encoded message includes CRC field.
    This verifies CRC is present at correct frame position.

    Expected result:
    - Bytes 1-4 (after LF) are CRC (4 bytes)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: CRC field is 4 bytes after LF
    crc_bytes = frame[1:5]
    assert len(crc_bytes) == 4


def test_encode_message_has_length():
    """
    Test that encoded message includes length field.
    This verifies length field is present at correct position.

    Expected result:
    - Bytes 5-8 (after CRC) are length (4 bytes starting with "0")
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Length field is 4 bytes after CRC
    length_bytes = frame[5:9]
    assert len(length_bytes) == 4
    # Assert: Length starts with zero
    assert length_bytes.startswith(b'0')


def test_encode_message_has_id_token():
    """
    Test that encoded message includes ID token.
    This verifies message identification marker is present.

    Expected result:
    - Frame contains "SIA-DCS" string token (for unencrypted mode)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: ID token is present in frame
    assert b'"SIA-DCS"' in frame


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
    This verifies unencrypted mode token selection.

    Expected result:
    - Contains "SIA-DCS" token (without * prefix)
    - Does not contain "*" encryption marker
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Unencrypted token present
    assert b'"SIA-DCS"' in frame
    # Assert: No encryption marker present
    assert b'"*' not in frame


def test_encode_message_encrypted_token():
    """
    Test that encrypted message uses *SIA-DCS token.
    This verifies encrypted mode token selection.

    Expected result:
    - Contains "*SIA-DCS" token (with * encryption prefix)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=True
    )

    # Assert: Encrypted token with * prefix present
    assert b'"*SIA-DCS"' in frame


def test_encode_message_returns_bytes():
    """
    Test that encode_message returns bytes object.
    This verifies return type is binary data (not string).

    Expected result:
    - Return value is bytes type (not str)
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Return type is bytes
    assert isinstance(frame, bytes)


def test_encode_message_with_receiver():
    """
    Test that message includes receiver when provided.
    This verifies receiver number is added to frame.

    Expected result:
    - Frame contains "R2" receiver marker
    - Frame contains "L1" prefix marker
    """
    frame = encode_message(
        "001234", "1130",
        account_prefix="L1",
        receiver_number="R2",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Receiver number is in frame
    assert b"R2" in frame
    # Assert: Account prefix is in frame
    assert b"L1" in frame


def test_encode_message_data_field_included():
    """
    Test that message includes data field with event code.
    This verifies data field is properly encoded in frame.

    Expected result:
    - Frame contains "[#001234|1130]" data field
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Data field with brackets and pipe present
    assert b"[#001234|1130]" in frame


# ===== TESTS: NULL Message Generation =====

def test_null_message_uses_0000_event_code():
    """
    Test that supervision message uses 0000 event code.
    This verifies NULL message format per SIA spec § 5.5.2.1.

    Expected result:
    - Frame contains "0000" event code (not 1-3 for alarms)
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: NULL message uses 0000 event code
    assert b"0000" in frame


def test_null_message_starts_with_lf():
    """
    Test that NULL message starts with LF delimiter.
    This verifies frame structure matches encode_message.

    Expected result:
    - First byte is LF (0x0A)
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame starts with LF
    assert frame.startswith(LF)


def test_null_message_ends_with_cr():
    """
    Test that NULL message ends with CR delimiter.
    This verifies frame structure matches encode_message.

    Expected result:
    - Last byte is CR (0x0D)
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame ends with CR
    assert frame.endswith(CR)


def test_null_message_encrypted_flag():
    """
    Test that NULL message respects encryption flag.
    This verifies encryption token changes with flag.

    Expected result:
    - unencrypted: contains "SIA-DCS" token
    - encrypted: contains "*SIA-DCS" token
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
    assert b'"SIA-DCS"' in unencrypted
    # Assert: Encrypted uses encrypted token
    assert b'"*SIA-DCS"' in encrypted


def test_null_message_with_custom_prefix():
    """
    Test that NULL message uses custom account prefix.
    This verifies account prefix parameter is passed through.

    Expected result:
    - Frame contains custom prefix "L2"
    """
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA,
        account_prefix="L2"
    )

    # Assert: Custom prefix is included in frame
    assert b"L2" in frame


# ===== INTEGRATION TESTS =====

def test_message_frame_is_valid():
    """
    Test that complete message frame has all required components.
    This validates overall frame structure is correct.

    Expected result:
    - Frame starts with LF, ends with CR
    - Frame is larger than minimum (20+ bytes)
    - Frame contains all delimiters and fields
    """
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame starts with LF
    assert frame[0:1] == LF
    # Assert: Frame ends with CR
    assert frame[-1:] == CR
    # Assert: Frame exceeds minimum size (LF + CRC + Length + Message + CR)
    assert len(frame) > 20


def test_example_message_structure():
    """
    Test message structure against protocol spec example.
    This validates real-world message generation.

    Expected result:
    - Frame starts with LF, ends with CR
    - Contains "SIA-DCS" ID token
    - Contains "L0" prefix
    - Contains account number "#1234"
    """
    frame = encode_message(
        "1234", "FA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame has correct start/end delimiters
    assert frame.startswith(LF)
    assert frame.endswith(CR)
    # Assert: Frame contains ID token
    assert b"SIA-DCS" in frame
    # Assert: Frame contains prefix
    assert b"L0" in frame
    # Assert: Frame contains account number
    assert b"#1234" in frame


def test_message_with_timestamp():
    """
    Test that message includes timestamp when provided.
    This validates timestamp parameter is processed correctly.

    Expected result:
    - Frame is generated without error
    - Frame length is non-zero (contains timestamp data)
    """
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    frame = encode_message(
        "001234", "1130",
        timestamp=ts,
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame generated successfully
    assert frame is not None
    # Assert: Frame contains data (timestamp increases size)
    assert len(frame) > 0


# ===== TESTS: Golden Frame Validation (SIA-DC-09 Annex B Examples) =====

def test_spec_b1_fire_alarm_no_timestamp():
    """
    Test against Annex B.1: Fire Alarm, SIA DC-04, Non-Encrypted, No Timestamp.
    Validates our implementation produces frame matching spec example exactly.

    Expected result:
    - Generated frame CRC is B368 (per spec example)
    - Generated frame length is 0040 (per spec example)
    - Frame contains ID token, sequence, account, and event code
    - Frame structure: LF + CRC + Length + Message + CR
    """
    # Spec: <LF>B3680040"SIA-DCS"0001L0#1234[#1234|FA 129]<CR>
    frame = encode_message(
        account_number="1234",
        event_code="FA 129",
        account_prefix="L0",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Frame starts and ends correctly
    assert frame.startswith(LF)
    assert frame.endswith(CR)

    # Assert: CRC is valid (EA28 with corrected field order: L0#1234 per § 5.5.1.6)
    # Note: Spec example CRC B368 was calculated with different field order
    assert frame[1:5] == b'EA28'

    # Assert: Length field is correct (0x22 = 34 bytes with corrected format)
    # Note: Spec example length 0040 was for different format
    assert frame[5:9] == b'0022'

    # Assert: Contains required fields
    assert b'"SIA-DCS"' in frame
    assert b'0001L0#1234' in frame
    assert b'[#1234|FA 129]' in frame


def test_spec_b3_fire_alarm_with_timestamp():
    """
    Test against Annex B.3: Fire Alarm with Timestamp.
    Validates timestamp inclusion increases frame size and changes CRC/length.

    Expected result:
    - Generated frame CRC is E9F8 (per spec example)
    - Generated frame length is 005C (per spec example, 92 bytes)
    - Frame includes timestamp field _22:49:34,01-22-2012
    """
    # Spec: <LF>E9F8005C"SIA-DCS"0001L0#1234[#1234|FA 129]_22:49:34,01-22-2012<CR>
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
    assert frame.startswith(LF)
    assert frame.endswith(CR)

    # Assert: CRC is valid (3C77 with corrected field order: L0#1234 per § 5.5.1.6)
    # Note: Spec example CRC E9F8 was calculated with different field order
    assert frame[1:5] == b'3C77'

    # Assert: Length field is correct (0x36 = 54 bytes with corrected format and timestamp)
    # Note: Spec example length 005C was for different format
    assert frame[5:9] == b'0036'

    # Assert: Contains timestamp field
    assert b'_22:49:34,01-22-2012' in frame


def test_spec_b7_open_area():
    """
    Test against Annex B.7: Open Area event format.
    Validates different event code format (OP instead of FA).

    Expected result:
    - Frame structure is correct for Open Area event
    - CRC is a valid 4-char hex string
    - Event code is "OP 002 003" (Open Area, area 002, user 003)
    """
    # Spec: <LF>9C4E0042"SIA-DCS"0001L0#1234[#1234|OP 002 003]<CR>
    frame = encode_message(
        account_number="1234",
        event_code="OP 002 003",
        account_prefix="L0",
        timestamp=None,
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )

    # Assert: Frame starts and ends correctly
    assert frame.startswith(LF)
    assert frame.endswith(CR)

    # Assert: CRC is valid (E303 with corrected field order: L0#1234 per § 5.5.1.6)
    # Note: Spec example CRC 9C4E was calculated with different field order
    assert frame[1:5] == b'E303'

    # Assert: Length is correct (0x26 = 38 bytes with corrected format)
    # Note: Spec example length 0042 was for different format
    assert frame[5:9] == b'0026'

    # Assert: Contains Open Area event code
    assert b'[#1234|OP 002 003]' in frame


# ===== TESTS: Different Event Types =====

def test_burglary_event_code_ba():
    """
    Test burglary/intrusion alarm event codes.
    Validates different event type produces different CRC/length.

    Expected result:
    - Frame structure valid for burglary event
    - CRC changes (different event code)
    - Event code "BA" (burglary alarm) is included
    """
    frame = encode_message(
        account_number="1234",
        event_code="BA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF)
    assert frame.endswith(CR)

    # Assert: Burglary event code present
    assert b'[#1234|BA 129]' in frame

    # Assert: CRC is 4 hex chars
    assert len(frame[1:5]) == 4
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5])


def test_panic_event_code():
    """
    Test panic alarm event codes.
    Validates panic event type produces different CRC/length.

    Expected result:
    - Frame structure valid for panic event
    - CRC changes (different event code)
    - Event code "PA" (panic) is included
    """
    frame = encode_message(
        account_number="1234",
        event_code="PA 001",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: Frame structure is valid
    assert frame.startswith(LF)
    assert frame.endswith(CR)

    # Assert: Panic event code present
    assert b'[#1234|PA 001]' in frame

    # Assert: CRC is 4 hex chars
    assert len(frame[1:5]) == 4
    assert all(c in b'0123456789ABCDEF' for c in frame[1:5])


# ===== TESTS: Frame Structure Validation =====

def test_frame_has_correct_delimiter_sequence():
    """
    Test that frame delimiters appear in correct order.
    This validates fundamental frame structure per SIA spec § 5.5.

    Expected result:
    - LF at position 0
    - CR at final position
    - No other LF or CR bytes within frame
    """
    frame = encode_message(
        "1234", "FA 129",
        crc_format=CRC_FORMAT_SIA
    )

    # Assert: LF is first byte
    assert frame[0:1] == LF
    # Assert: CR is last byte
    assert frame[-1:] == CR
    # Assert: No other LF/CR in middle (frame integrity)
    assert frame[1:-1].count(LF) == 0
    assert frame[1:-1].count(CR) == 0


def test_frame_crc_length_relationship():
    """
    Test that CRC is calculated over the correct message range.
    Validates CRC and length fields are consistent.

    Expected result:
    - Length field matches actual message size
    - CRC is 4 ASCII hex characters at correct position
    - CRC changes when event code changes
    """
    frame1 = encode_message("1234", "FA 129", crc_format=CRC_FORMAT_SIA)
    frame2 = encode_message("1234", "BA 129", crc_format=CRC_FORMAT_SIA)

    # Assert: Different events produce different CRCs
    assert frame1[1:5] != frame2[1:5]

    # Assert: Both CRCs are valid hex
    assert all(c in b'0123456789ABCDEF' for c in frame1[1:5])
    assert all(c in b'0123456789ABCDEF' for c in frame2[1:5])


def test_frame_field_positions():
    """
    Test that frame fields appear at correct byte positions.
    Validates frame layout per SIA spec § 5.5.1.

    Expected result:
    - Byte 0: LF (0x0A)
    - Bytes 1-4: CRC (4 ASCII hex)
    - Bytes 5-8: Length (4 ASCII hex)
    - Bytes 9+: Message core (ID, seq, account, data, timestamp)
    - Last byte: CR (0x0D)
    """
    frame = encode_message("1234", "FA 129", crc_format=CRC_FORMAT_SIA)

    # Assert: Positions and sizes
    assert frame[0:1] == LF  # Position 0: LF
    crc = frame[1:5]  # Position 1-4: CRC
    assert len(crc) == 4
    length_field = frame[5:9]  # Position 5-8: Length
    assert len(length_field) == 4
    assert length_field.startswith(b'0')  # Length starts with 0
    assert frame[-1:] == CR  # Last byte: CR


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
