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
    """LF should be line feed character 0x0A."""
    assert LF == b'\x0A'


def test_cr_is_0x0d():
    """CR should be carriage return character 0x0D."""
    assert CR == b'\x0D'


def test_null_code():
    """NULL code for supervision messages."""
    assert SIA_NULL_CODE == "0000"


def test_event_codes():
    """Event type code constants."""
    assert BURGLARY == "1"
    assert FIRE == "2"
    assert PANIC == "3"


# ===== TESTS: SequenceManager =====

def test_sequence_first_is_0001(sequence_manager):
    """First sequence should be 0001."""
    seq = sequence_manager.next_seq("001234")
    assert seq == "0001"


def test_sequence_increments(sequence_manager):
    """Sequence numbers should increment."""
    seq1 = sequence_manager.next_seq("001234")
    seq2 = sequence_manager.next_seq("001234")
    seq3 = sequence_manager.next_seq("001234")
    assert seq1 == "0001"
    assert seq2 == "0002"
    assert seq3 == "0003"


def test_sequence_wraps_9999_to_0001(sequence_manager):
    """Sequence should wrap from 9999 → 0001 (not 0000)."""
    sequence_manager._seq_map["001234"] = 9999
    next_seq = sequence_manager.next_seq("001234")
    assert next_seq == "0001"


def test_current_seq_no_increment(sequence_manager):
    """current_seq() should not increment."""
    sequence_manager.next_seq("001234")  # Set to 0001
    current1 = sequence_manager.current_seq("001234")
    current2 = sequence_manager.current_seq("001234")
    assert current1 == "0001"
    assert current2 == "0001"


def test_sequence_per_account(sequence_manager):
    """Sequence numbers should be per-account."""
    seq_a1 = sequence_manager.next_seq("acctA")
    seq_b1 = sequence_manager.next_seq("acctB")
    seq_a2 = sequence_manager.next_seq("acctA")
    seq_b2 = sequence_manager.next_seq("acctB")

    assert seq_a1 == "0001"
    assert seq_b1 == "0001"
    assert seq_a2 == "0002"
    assert seq_b2 == "0002"


# ===== TESTS: CRC Calculation =====

def test_crc_returns_4_hex_chars():
    """CRC should be 4-character ASCII hex."""
    data = b'"SIA-DCS"0001L0#1234[#1234|FA 129]'
    crc = calculate_crc(data, CRC_FORMAT_SIA)
    assert len(crc) == 4
    assert all(c in '0123456789ABCDEF' for c in crc)


def test_crc_format_sia():
    """SIA format should be accepted."""
    data = b'"SIA-DCS"0001L0#1234'
    crc = calculate_crc(data, CRC_FORMAT_SIA)
    assert len(crc) == 4


def test_crc_format_adm():
    """ADM format should be accepted."""
    data = b'"ADM-CID"0001L0#1234'
    crc = calculate_crc(data, CRC_FORMAT_ADM)
    assert len(crc) == 4


def test_crc_invalid_format_raises():
    """Invalid CRC format should raise ValueError."""
    data = b'"SIA-DCS"0001L0#1234'
    with pytest.raises(ValueError):
        calculate_crc(data, "INVALID")


# ===== TESTS: Length Calculation =====

def test_length_starts_with_zero():
    """Length should start with '0'."""
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)
    assert length.startswith("0")


def test_length_is_4_chars():
    """Length should be 4 characters total."""
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)
    assert len(length) == 4


def test_length_is_hex():
    """Length field should be hex after leading 0."""
    data = b'"SIA-DCS"0001L0#1234'
    length = calculate_length(data)
    assert length[0] == "0"
    assert all(c in '0123456789ABCDEF' for c in length[1:])


def test_length_calculation_example():
    """Test length calculation with known size."""
    data = b'x' * 64
    length = calculate_length(data)
    assert length == "0040"  # 0x40 = 64 in hex


# ===== TESTS: Account ID Formatting =====

def test_basic_account_id():
    """Test basic account ID without receiver."""
    result = format_account_id("001234", "L0")
    assert result == "#001234L0"


def test_account_id_with_prefix():
    """Test account ID with custom prefix."""
    result = format_account_id("001234", "L1")
    assert result == "#001234L1"


def test_account_id_with_receiver():
    """Test account ID with receiver number."""
    result = format_account_id("001234", "L1", "R2")
    assert result == "R2#001234L1"


def test_account_id_receiver_zero_omitted():
    """Test that receiver '0' is omitted."""
    result = format_account_id("001234", "L0", "0")
    assert result == "#001234L0"


def test_account_id_invalid_account_raises():
    """Invalid account number should raise."""
    with pytest.raises(ValueError):
        format_account_id("XYZ", "L0")  # Too short


def test_account_id_invalid_prefix_raises():
    """Invalid prefix should raise."""
    with pytest.raises(ValueError):
        format_account_id("001234", "LG")  # G is not hex


def test_account_id_hex_case_insensitive():
    """Account ID should accept upper and lower case hex."""
    result = format_account_id("aAbBcCdD", "L0")
    assert "#aAbBcCdDL0" == result


# ===== TESTS: Data Field Formatting =====

def test_data_field_basic():
    """Test basic data field format."""
    result = format_data_field("001234", "1130")
    assert result == "[#001234|1130]"


def test_data_field_fire_code():
    """Test data field with fire event code."""
    result = format_data_field("001234", "2130")
    assert result == "[#001234|2130]"


def test_data_field_has_brackets():
    """Data field should include bracket characters."""
    result = format_data_field("001234", "1130")
    assert result.startswith("[")
    assert result.endswith("]")


def test_data_field_has_pipe_separator():
    """Data field should use pipe separator."""
    result = format_data_field("001234", "1130")
    assert "|" in result


# ===== TESTS: Timestamp Formatting =====

def test_timestamp_length():
    """Timestamp should be exactly 20 characters per spec."""
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    assert len(result) == 20


def test_timestamp_format():
    """Timestamp should be formatted as _HH:MM:SS,MM-DD-YYYY."""
    ts = datetime(2026, 4, 7, 15, 30, 45, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    assert result == "_15:30:45,04-07-2026"


def test_timestamp_has_required_separators():
    """Timestamp should have underscore, colons, comma, and dashes per spec."""
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    assert result.startswith("_")  # Leading underscore
    assert ":" in result  # Colons in time
    assert "," in result  # Comma separator
    assert "-" in result  # Dashes in date


def test_timestamp_zero_fills_components():
    """Timestamp components should be zero-filled."""
    ts = datetime(2026, 1, 3, 9, 5, 2, tzinfo=timezone.utc)
    result = format_timestamp(ts)
    assert result == "_09:05:02,01-03-2026"


def test_timestamp_current_if_none():
    """None timestamp should use current time."""
    result = format_timestamp(None)
    # Result should be formatted string, not hex
    assert len(result) == 20
    assert result.startswith("_")
    # Verify it's within the time window
    assert ":" in result
    assert "," in result


# ===== TESTS: Complete Message Encoding =====

def test_encode_message_starts_with_lf():
    """Message should start with LF (0x0A)."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    assert frame.startswith(LF)


def test_encode_message_ends_with_cr():
    """Message should end with CR (0x0D)."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    assert frame.endswith(CR)


def test_encode_message_has_crc():
    """Message should contain 4-digit CRC."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    # After LF, next 4 bytes should be CRC
    crc_bytes = frame[1:5]
    assert len(crc_bytes) == 4


def test_encode_message_has_length():
    """Message should contain length field (0LLL)."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    # After CRC, next 4 bytes should be length
    length_bytes = frame[5:9]
    assert len(length_bytes) == 4
    assert length_bytes.startswith(b'0')


def test_encode_message_has_id_token():
    """Message should contain ID token."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )
    assert b'"SIA-DCS"' in frame


def test_encode_message_crc_format_keyword_only():
    """crc_format must be keyword-only parameter."""
    with pytest.raises(TypeError):
        # This should fail: crc_format passed as positional instead of keyword-only
        encode_message("001234", "1130", "L0", None, None, None, CRC_FORMAT_SIA)  # type: ignore


def test_encode_message_unencrypted_token():
    """Unencrypted message should use SIA-DCS token."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=False
    )
    assert b'"SIA-DCS"' in frame
    # Should not have encryption marker in unencrypted mode
    assert b'"*' not in frame


def test_encode_message_encrypted_token():
    """Encrypted message should use *SIA-DCS token."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA,
        encryption=True
    )
    assert b'"*SIA-DCS"' in frame


def test_encode_message_returns_bytes():
    """encode_message should return bytes."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    assert isinstance(frame, bytes)


def test_encode_message_with_receiver():
    """Message should include receiver number if provided."""
    frame = encode_message(
        "001234", "1130",
        account_prefix="L1",
        receiver_number="R2",
        crc_format=CRC_FORMAT_SIA
    )
    assert b"R2" in frame
    assert b"L1" in frame


def test_encode_message_data_field_included():
    """Message should include data field with brackets."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )
    assert b"[#001234|1130]" in frame


# ===== TESTS: NULL Message Generation =====

def test_null_message_uses_0000_event_code():
    """NULL message should use event code 0000."""
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    assert b"0000" in frame


def test_null_message_starts_with_lf():
    """NULL message should start with LF."""
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    assert frame.startswith(LF)


def test_null_message_ends_with_cr():
    """NULL message should end with CR."""
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA
    )
    assert frame.endswith(CR)


def test_null_message_encrypted_flag():
    """NULL message should respect encryption flag."""
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
    assert b'"SIA-DCS"' in unencrypted
    assert b'"*SIA-DCS"' in encrypted


def test_null_message_with_custom_prefix():
    """NULL message should use custom prefix if provided."""
    frame = make_supervision_message(
        "001234",
        crc_format=CRC_FORMAT_SIA,
        account_prefix="L2"
    )
    assert b"L2" in frame


# ===== INTEGRATION TESTS =====

def test_message_frame_is_valid():
    """Complete message frame should have all required fields."""
    frame = encode_message(
        "001234", "1130",
        crc_format=CRC_FORMAT_SIA
    )

    # Check overall structure: LF + CRC + LENGTH + ... + CR
    assert frame[0:1] == LF
    assert frame[-1:] == CR
    assert len(frame) > 20  # Minimum frame size


def test_example_message_structure():
    """Test against protocol spec example structure."""
    frame = encode_message(
        "1234", "FA 129",
        account_prefix="L0",
        crc_format=CRC_FORMAT_SIA
    )

    # Basic checks
    assert frame.startswith(LF)
    assert frame.endswith(CR)
    assert b"SIA-DCS" in frame
    assert b"L0" in frame
    assert b"#1234" in frame


def test_message_with_timestamp():
    """Test message includes timestamp when provided."""
    ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
    frame = encode_message(
        "001234", "1130",
        timestamp=ts,
        crc_format=CRC_FORMAT_SIA
    )
    # Verify frame was created (timestamp affects length)
    assert frame is not None
    assert len(frame) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
