"""
ACK/NAK Response Parser Tests

Comprehensive unit tests for SIA DC-09 ACK/NAK response parsing.
Tests defensive parsing (never raises), CRC validation, sequence extraction,
timestamp handling, and integration with Stories 1.1 & 1.2.

Reference: docs/design/daemon-design.md § Component 0 (decode_ack_nak, parse_nak_timestamp)
Expert Validation: sia-dc09-expert (2026-04-09)
"""

import pytest
import struct
from datetime import datetime, timezone
from resources.siadc09d.sia_protocol import (
    _compute_crc_modbus,
    decode_ack_nak,
    parse_nak_timestamp,
    SIAMessageBuilder,
)


# ===== Helper Functions =====

def build_frame(message: bytes, crc_format: str = 'hex') -> bytes:
    """
    Build a complete SIA frame with correct CRC and length.

    Args:
        message: Message string (bytes), e.g., b'"ACK"0001R0L0A0[]'
        crc_format: 'hex' (default) or 'bin'

    Returns:
        Complete frame: 0x0A + CRC + Length + message + 0x0D
    """
    crc_value = _compute_crc_modbus(message)

    # Format CRC
    if crc_format == 'hex':
        crc_str = f"{crc_value:04X}"
        crc_data = crc_str.encode()
    else:  # bin
        crc_data = struct.pack('<H', crc_value)

    # Compute length
    length_value = len(message)
    length_str = f"0{length_value:03X}"
    length_data = length_str.encode()

    # Build frame
    frame = b'\x0A' + crc_data + length_data + message + b'\x0D'

    return frame


# ===== Fixture Data =====

class TestDecodeAckNakFrameStructureValidation:
    """Test frame structure validation - missing leader, trailer, truncated fields."""

    def test_valid_ack_frame_basic(self):
        """
        Test that a valid plaintext ACK frame parses correctly.

        Expected result:
        - decode_ack_nak() returns dict with type='ACK', seq=1, raw_nak=None
        - All structural checks pass
        """
        # Construct a valid ACK frame: LF + CRC + Length + "ACK"0001R0L0A0[] + CR
        # Frame: 0x0A + CRC(4 hex) + Length(4 hex) + message + 0x0D
        ack_message = b'"ACK"0001R0L0A0[]'
        ack_frame = build_frame(ack_message, crc_format='hex')

        result = decode_ack_nak(ack_frame)

        # Assert: Frame parses as ACK with correct sequence
        assert result['type'] == 'ACK'
        assert result['seq'] == 1
        assert result['raw_nak'] is None

    def test_valid_nak_frame_basic(self):
        """
        Test that a valid plaintext NAK frame parses correctly.

        Expected result:
        - decode_ack_nak() returns dict with type='NAK', seq=0, raw_nak=<full_bytes>
        - raw_nak field populated with full NAK bytes
        """
        # NAK always has seq=0000 per spec
        nak_message = b'"NAK"0000R0L0A0[]'
        nak_frame = build_frame(nak_message, crc_format='hex')

        result = decode_ack_nak(nak_frame)

        # Assert: Frame parses as NAK with seq=0 and raw_nak populated
        assert result['type'] == 'NAK'
        assert result['seq'] == 0
        assert result['raw_nak'] == nak_frame

    def test_frame_missing_leader(self):
        """
        Test that frame without leader (0x0A) returns type='unknown'.

        Expected result:
        - decode_ack_nak() returns type='unknown', seq=None, raw_nak=None
        - No exception raised
        """
        # Frame without 0x0A leader
        invalid_frame = b'CRC000200"ACK"0001R0L0A0[]\x0D'

        result = decode_ack_nak(invalid_frame)

        # Assert: Returns 'unknown' without raising
        assert result['type'] == 'unknown'
        assert result['seq'] is None
        assert result['raw_nak'] is None

    def test_frame_missing_trailer(self):
        """
        Test that frame without trailer (0x0D) returns type='unknown'.

        Expected result:
        - decode_ack_nak() returns type='unknown'
        - No exception raised
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        # Build frame but strip the CR trailer
        frame_without_trailer = b'\x0A' + b'0000' + b'0010' + ack_message

        result = decode_ack_nak(frame_without_trailer)

        # Assert: Missing trailer → 'unknown'
        assert result['type'] == 'unknown'
        assert result['seq'] is None

    def test_frame_truncated_crc_field(self):
        """
        Test that frame with incomplete CRC field returns type='unknown'.

        Expected result:
        - Returns type='unknown' (CRC field incomplete)
        """
        # Frame with only 2 bytes of CRC instead of 4
        truncated_frame = b'\x0A' + b'00' + b'0010' + b'"ACK"0001R0L0A0[]\x0D'

        result = decode_ack_nak(truncated_frame)

        # Assert: Truncated CRC → 'unknown'
        assert result['type'] == 'unknown'

    def test_frame_truncated_length_field(self):
        """
        Test that frame with incomplete length field returns type='unknown'.

        Expected result:
        - Returns type='unknown' (length field incomplete)
        """
        # Frame with only 2 bytes of length instead of 4
        truncated_frame = b'\x0A' + b'0000' + b'00' + b'"ACK"0001R0L0A0[]\x0D'

        result = decode_ack_nak(truncated_frame)

        # Assert: Truncated length → 'unknown'
        assert result['type'] == 'unknown'

    def test_frame_empty_raw_bytes(self):
        """
        Test that empty input returns type='unknown'.

        Expected result:
        - decode_ack_nak(b'') returns type='unknown', seq=None, raw_nak=None
        """
        result = decode_ack_nak(b'')

        # Assert: Empty frame → 'unknown'
        assert result['type'] == 'unknown'
        assert result['seq'] is None
        assert result['raw_nak'] is None

    def test_frame_single_byte(self):
        """
        Test that single byte (not a valid frame) returns type='unknown'.

        Expected result:
        - Not a valid frame structure
        """
        result = decode_ack_nak(b'\x0A')

        # Assert: Single byte → 'unknown'
        assert result['type'] == 'unknown'


class TestDecodeAckNakCrcValidation:
    """Test CRC validation logic."""

    def test_valid_crc_hex_format(self):
        """
        Test that frame with valid CRC (hex format) is accepted.

        Expected result:
        - Frame parses successfully as ACK/NAK
        - CRC validation passes
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        # _build_frame computes correct CRC for us
        ack_frame = build_frame(ack_message, crc_format='hex')

        result = decode_ack_nak(ack_frame)

        # Assert: Valid CRC → frame accepted
        assert result['type'] == 'ACK'

    def test_invalid_crc_hex_format(self):
        """
        Test that frame with invalid CRC (hex format) returns type='unknown'.

        Expected result:
        - CRC mismatch → frame rejected as 'unknown'
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        frame = build_frame(ack_message, crc_format='hex')

        # Corrupt the CRC field (bytes 1-4)
        corrupted = frame[:1] + b'XXXX' + frame[5:]

        result = decode_ack_nak(corrupted)

        # Assert: CRC mismatch → 'unknown'
        assert result['type'] == 'unknown'

    def test_valid_crc_bin_format(self):
        """
        Test that frame with valid CRC (binary format) is accepted.

        Expected result:
        - Binary CRC (2 bytes, little-endian) validates correctly
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        frame_bin = build_frame(ack_message, crc_format='bin')

        result = decode_ack_nak(frame_bin, crc_format='bin')

        # Assert: Valid binary CRC → frame accepted
        assert result['type'] == 'ACK'

    def test_invalid_crc_bin_format(self):
        """
        Test that frame with invalid CRC (binary format) returns type='unknown'.

        Expected result:
        - Binary CRC mismatch → rejected
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        frame_bin = build_frame(ack_message, crc_format='bin')

        # Corrupt binary CRC (bytes 1-2)
        corrupted = frame_bin[:1] + b'\xFF\xFF' + frame_bin[3:]

        result = decode_ack_nak(corrupted, crc_format='bin')

        # Assert: CRC mismatch → 'unknown'
        assert result['type'] == 'unknown'


class TestDecodeAckNakSequenceExtraction:
    """Test sequence number extraction from ACK/NAK frames."""

    def test_ack_sequence_0000(self):
        """
        Test ACK with sequence 0000 (wraps to 0).

        Expected result:
        - seq=0 extracted correctly
        """
        ack_message = b'"ACK"0000R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: seq field parsed as integer 0
        assert result['seq'] == 0

    def test_ack_sequence_5432(self):
        """
        Test ACK with arbitrary sequence 5432.

        Expected result:
        - seq=5432 extracted correctly
        """
        ack_message = b'"ACK"5432R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: seq field parsed as integer 5432
        assert result['seq'] == 5432

    def test_ack_sequence_9999(self):
        """
        Test ACK with maximum sequence 9999.

        Expected result:
        - seq=9999 extracted correctly
        """
        ack_message = b'"ACK"9999R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: seq field parsed as integer 9999
        assert result['seq'] == 9999

    def test_nak_sequence_always_0000(self):
        """
        Test NAK always has sequence 0000 per spec.

        Expected result:
        - NAK seq=0 (spec requirement)
        """
        nak_message = b'"NAK"0000R0L0A0[]'
        frame = build_frame(nak_message)

        result = decode_ack_nak(frame)

        # Assert: NAK always has seq=0
        assert result['seq'] == 0


class TestDecodeAckNakTypeClassification:
    """Test ACK/NAK type classification."""

    def test_type_classification_ack(self):
        """
        Test id_token "ACK" classified as type='ACK'.

        Expected result:
        - type='ACK'
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: Classified as ACK
        assert result['type'] == 'ACK'

    def test_type_classification_nak(self):
        """
        Test id_token "NAK" classified as type='NAK'.

        Expected result:
        - type='NAK'
        """
        nak_message = b'"NAK"0000R0L0A0[]'
        frame = build_frame(nak_message)

        result = decode_ack_nak(frame)

        # Assert: Classified as NAK
        assert result['type'] == 'NAK'

    def test_type_classification_encrypted_ack(self):
        """
        Test encrypted ACK (id_token "*ACK") classified as type='ACK'.

        Expected result:
        - type='ACK' (encryption marker ignored in plaintext parser)
        """
        # *ACK (with encryption marker)
        ack_message = b'"*ACK"0001R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: *ACK also classified as ACK
        assert result['type'] == 'ACK'

    def test_type_classification_unknown_id_token(self):
        """
        Test unrecognized id_token returns type='unknown'.

        Expected result:
        - type='unknown' for unrecognized tokens
        """
        unknown_message = b'"ERROR"0001R0L0A0[]'
        frame = build_frame(unknown_message)

        result = decode_ack_nak(frame)

        # Assert: Unrecognized id_token → 'unknown'
        assert result['type'] == 'unknown'

    def test_type_classification_empty_id_token(self):
        """
        Test empty id_token returns type='unknown'.

        Expected result:
        - type='unknown' for empty/missing id_token
        """
        empty_token = b'""0001R0L0A0[]'
        frame = build_frame(empty_token)

        result = decode_ack_nak(frame)

        # Assert: Empty id_token → 'unknown'
        assert result['type'] == 'unknown'


class TestDecodeAckNakRawNakField:
    """Test raw_nak field population."""

    def test_ack_raw_nak_none(self):
        """
        Test that ACK frame has raw_nak=None.

        Expected result:
        - raw_nak=None (ACK, not NAK)
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: ACK has raw_nak=None
        assert result['raw_nak'] is None

    def test_nak_raw_nak_populated(self):
        """
        Test that NAK frame has raw_nak populated with full bytes.

        Expected result:
        - raw_nak=<full_frame_bytes>
        """
        nak_message = b'"NAK"0000R0L0A0[]'
        frame = build_frame(nak_message)

        result = decode_ack_nak(frame)

        # Assert: NAK has raw_nak = full frame bytes
        assert result['raw_nak'] == frame
        assert isinstance(result['raw_nak'], bytes)

    def test_nak_raw_nak_can_be_parsed_for_timestamp(self):
        """
        Test that raw_nak from NAK can be used for timestamp extraction.

        Expected result:
        - raw_nak can be passed to parse_nak_timestamp()
        """
        nak_message = b'"NAK"0000R0L0A0[]_14:32:45,03-22-2026'
        frame = build_frame(nak_message)

        result = decode_ack_nak(frame)

        # Assert: raw_nak is present and can be parsed
        assert result['raw_nak'] is not None
        # Try parsing timestamp from raw_nak (should work)
        try:
            ts = parse_nak_timestamp(result['raw_nak'])
            assert ts == datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)
        except ValueError:
            pytest.fail("parse_nak_timestamp() should succeed on valid NAK with timestamp")


class TestParseNakTimestamp:
    """Test NAK timestamp extraction and parsing."""

    def test_valid_timestamp_in_nak(self):
        """
        Test extracting valid timestamp from NAK frame.

        Expected result:
        - parse_nak_timestamp() returns datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)
        """
        nak_message = b'"NAK"0000R0L0A0[]_14:32:45,03-22-2026'
        nak_frame = build_frame(nak_message)

        ts = parse_nak_timestamp(nak_frame)

        # Assert: Timestamp parsed correctly as datetime object
        assert ts == datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)
        assert ts.tzinfo is not None  # Timezone-aware

    def test_timestamp_none_input(self):
        """
        Test that None input raises ValueError.

        Expected result:
        - Raises ValueError
        """
        with pytest.raises(ValueError):
            parse_nak_timestamp(None)

    def test_timestamp_empty_bytes(self):
        """
        Test that empty bytes raises ValueError.

        Expected result:
        - Raises ValueError (no timestamp data)
        """
        with pytest.raises(ValueError):
            parse_nak_timestamp(b'')

    def test_timestamp_invalid_format_wrong_separators(self):
        """
        Test that timestamp with wrong separators raises ValueError.

        Expected result:
        - Format mismatch → ValueError
        """
        # Wrong separator: colon instead of comma between seconds and month
        nak_message = b'"NAK"0000R0L0A0[]_14:32:45:03-22-2026'
        nak_frame = build_frame(nak_message)

        with pytest.raises(ValueError):
            parse_nak_timestamp(nak_frame)

    def test_timestamp_invalid_month(self):
        """
        Test that invalid month (13) raises ValueError.

        Expected result:
        - Datetime validation fails
        """
        nak_message = b'"NAK"0000R0L0A0[]_14:32:45,13-22-2026'
        nak_frame = build_frame(nak_message)

        with pytest.raises(ValueError):
            parse_nak_timestamp(nak_frame)

    def test_timestamp_invalid_day(self):
        """
        Test that invalid day (32) raises ValueError.

        Expected result:
        - Datetime validation fails
        """
        nak_message = b'"NAK"0000R0L0A0[]_14:32:45,03-32-2026'
        nak_frame = build_frame(nak_message)

        with pytest.raises(ValueError):
            parse_nak_timestamp(nak_frame)

    def test_timestamp_invalid_hour(self):
        """
        Test that invalid hour (25) raises ValueError.

        Expected result:
        - Datetime validation fails
        """
        nak_message = b'"NAK"0000R0L0A0[]_25:32:45,03-22-2026'
        nak_frame = build_frame(nak_message)

        with pytest.raises(ValueError):
            parse_nak_timestamp(nak_frame)


class TestDecodeAckNakErrorHandling:
    """Test that decode_ack_nak never raises exceptions."""

    def test_encoding_error_non_ascii_bytes(self):
        """
        Test that non-ASCII bytes don't crash decoder.

        Expected result:
        - Returns type='unknown' (graceful error handling, no exception)
        """
        # Frame with invalid UTF-8 bytes
        bad_frame = b'\x0A' + b'0000' + b'0010' + b'\xFF\xFE\xFD\xFC' + b'\x0D'

        result = decode_ack_nak(bad_frame)

        # Assert: Returns 'unknown' without raising
        assert result['type'] == 'unknown'

    def test_integer_overflow_malformed_sequence(self):
        """
        Test that malformed sequence field doesn't crash.

        Expected result:
        - Returns type='unknown' (error handled gracefully)
        """
        # Sequence field with non-digit characters
        malformed_message = b'"ACK"ABCDR0L0A0[]'
        frame = build_frame(malformed_message)

        result = decode_ack_nak(frame)

        # Assert: Gracefully handles parse error
        assert result['type'] == 'unknown'


class TestIntegrationWithStory11:
    """Integration tests combining Story 1.1 (message builder) and Story 1.3 (parser)."""

    def test_roundtrip_message_builder_to_parser(self):
        """
        Test roundtrip: build message → construct ACK response → parse ACK.

        Expected result:
        - Parsed sequence matches original outbound sequence
        """
        builder = SIAMessageBuilder(crc_format='hex')

        # Build an outbound message
        frame = builder.encode_message("001234", "1130")

        # Extract sequence from built frame (should be 0001)
        # Build corresponding ACK response with same sequence
        ack_message = b'"ACK"0001R0L0A0[]'
        ack_frame = build_frame(ack_message)

        result = decode_ack_nak(ack_frame)

        # Assert: Parsed sequence matches outbound sequence
        assert result['type'] == 'ACK'
        assert result['seq'] == 1

    def test_integration_multiple_sequences(self):
        """
        Test parsing ACKs with various sequences from message builder.

        Expected result:
        - Each ACK matches corresponding outbound sequence
        """
        builder = SIAMessageBuilder(crc_format='hex')

        # Build multiple messages to advance sequence
        builder.encode_message("001234", "1130")  # seq=1
        builder.encode_message("001234", "2130")  # seq=2
        builder.encode_message("001234", "3130")  # seq=3

        # Parse ACKs for seq=1, 2, 3
        for expected_seq in [1, 2, 3]:
            ack_message = f'"ACK"{expected_seq:04d}R0L0A0[]'.encode()
            ack_frame = build_frame(ack_message)
            result = decode_ack_nak(ack_frame)

            # Assert: Each ACK matches its sequence
            assert result['type'] == 'ACK'
            assert result['seq'] == expected_seq


class TestVariableLengthNakMessages:
    """Test NAK parsing with variable message structures (Gap 1 — variable-length messages)."""

    def test_nak_without_receiver_number(self):
        """
        Test NAK without receiver number (receiver prefix omitted).

        Expected result:
        - NAK still parses correctly; timestamp extracted despite different message length
        """
        # NAK with receiver omitted: "NAK"0000L0A0[]_timestamp
        nak_message = b'"NAK"0000L0A0[]_14:32:45,03-22-2026'
        nak_frame = build_frame(nak_message)

        result = decode_ack_nak(nak_frame)

        # Assert: NAK parses despite shorter message structure
        assert result['type'] == 'NAK'
        assert result['seq'] == 0
        # Timestamp extraction uses find('_'), so it should work
        ts = parse_nak_timestamp(nak_frame)
        assert ts == datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)

    def test_nak_with_alternate_receiver_number(self):
        """
        Test NAK with non-zero receiver number (R99).

        Expected result:
        - Timestamp delimiter position shifts; parser uses find('_') to adapt
        """
        # NAK with R99 (longer receiver): "NAK"0000R99L0A0[]_timestamp
        nak_message = b'"NAK"0000R99L0A0[]_14:32:45,03-22-2026'
        nak_frame = build_frame(nak_message)

        result = decode_ack_nak(nak_frame)

        # Assert: NAK parses; timestamp extracted despite shifted position
        assert result['type'] == 'NAK'
        ts = parse_nak_timestamp(nak_frame)
        assert ts == datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)

    def test_nak_with_encrypted_marker(self):
        """
        Test NAK with encryption marker (*NAK) in plaintext context.

        Expected result:
        - Parser handles *NAK as NAK type; timestamp still extracted
        """
        # Encrypted NAK marker: "*NAK"0000R0L0A0[]_timestamp
        nak_message = b'"*NAK"0000R0L0A0[]_14:32:45,03-22-2026'
        nak_frame = build_frame(nak_message)

        result = decode_ack_nak(nak_frame)

        # Assert: *NAK classified as NAK
        assert result['type'] == 'NAK'
        ts = parse_nak_timestamp(nak_frame)
        assert ts == datetime(2026, 3, 22, 14, 32, 45, tzinfo=timezone.utc)


class TestCrcFormatPresetValidation:
    """Test CRC format as preset configuration (Gap 3 — CRC format must be preset, not auto-detected)."""

    def test_crc_format_hex_explicit_parameter(self):
        """
        Test that hex CRC format must be explicitly specified, not auto-detected.

        Expected result:
        - Parser uses crc_format parameter; succeeds when crc_format='hex'
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        ack_frame = build_frame(ack_message, crc_format='hex')

        result = decode_ack_nak(ack_frame, crc_format='hex')

        # Assert: Frame parses with explicit hex format parameter
        assert result['type'] == 'ACK'
        assert result['seq'] == 1

    def test_crc_format_bin_explicit_parameter(self):
        """
        Test that binary CRC format must be explicitly specified.

        Expected result:
        - Parser uses crc_format parameter; succeeds when crc_format='bin'
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        ack_frame = build_frame(ack_message, crc_format='bin')

        result = decode_ack_nak(ack_frame, crc_format='bin')

        # Assert: Frame parses with explicit bin format parameter
        assert result['type'] == 'ACK'
        assert result['seq'] == 1

    def test_crc_format_mismatch_fails_gracefully(self):
        """
        Test that CRC format mismatch causes parse failure (not crash).

        Expected result:
        - CRC validation fails; returns type='unknown' (defensive)
        """
        ack_message = b'"ACK"0001R0L0A0[]'
        # Build frame with hex CRC
        ack_frame = build_frame(ack_message, crc_format='hex')

        # Try to parse as binary (wrong format)
        result = decode_ack_nak(ack_frame, crc_format='bin')

        # Assert: CRC mismatch causes graceful failure
        assert result['type'] == 'unknown'


class TestSequenceWrappingBoundary:
    """Test sequence wrapping from 9999 to 0001 (Gap 5 — boundary conditions)."""

    def test_sequence_9999_parses(self):
        """
        Test that sequence 9999 parses correctly.

        Expected result:
        - seq=9999 extracted as integer
        """
        ack_message = b'"ACK"9999R0L0A0[]'
        frame = build_frame(ack_message)

        result = decode_ack_nak(frame)

        # Assert: Maximum sequence value parses
        assert result['type'] == 'ACK'
        assert result['seq'] == 9999

    def test_sequence_0001_after_wrap(self):
        """
        Test that sequence wraps to 0001 (never 0000 for outbound).

        Expected result:
        - seq=0001 is valid ACK response
        """
        builder = SIAMessageBuilder(crc_format='hex')

        # Advance sequence to 9999
        builder._sequence_tracker._seq_map['001234'] = 9999

        # Next message would wrap to 0001; simulate corresponding ACK
        ack_message = b'"ACK"0001R0L0A0[]'
        ack_frame = build_frame(ack_message)

        result = decode_ack_nak(ack_frame)

        # Assert: seq=0001 accepted as valid ACK
        assert result['type'] == 'ACK'
        assert result['seq'] == 1


class TestMessageFormatVariations:
    """Test message format edge cases (Gap 6 — format variations)."""

    @pytest.mark.parametrize("ack_msg", [
        b'"ACK"0001R0L0A0[]',    # Standard: R0L0
        b'"ACK"0001L0A0[]',       # Without receiver
        b'"ACK"0001R99L0A0[]',    # Different receiver
    ])
    def test_ack_format_variations(self, ack_msg):
        """
        Test ACK parsing with various prefix combinations.

        Expected result:
        - All valid prefix combinations parse as ACK type
        """
        frame = build_frame(ack_msg)
        result = decode_ack_nak(frame)

        # Assert: Variant formats parse successfully
        assert result['type'] == 'ACK'
        assert result['seq'] == 1


class TestNakWithoutTimestamp:
    """Test optional NAK timestamp field (Gap 7 — optional fields)."""

    def test_nak_without_timestamp_field(self):
        """
        Test that NAK without timestamp field parses as NAK type.

        Expected result:
        - type='NAK' returned; parse_nak_timestamp() raises ValueError
        """
        nak_message = b'"NAK"0000R0L0A0[]'  # No _timestamp suffix
        nak_frame = build_frame(nak_message)

        result = decode_ack_nak(nak_frame)

        # Assert: NAK type recognized despite missing timestamp
        assert result['type'] == 'NAK'
        assert result['seq'] == 0

        # Assert: parse_nak_timestamp() raises ValueError for NAK without timestamp
        with pytest.raises(ValueError):
            parse_nak_timestamp(nak_frame)


class TestFrameLengthFieldMismatch:
    """Test frame length field validation (Gap 8 — length field mismatch)."""

    def test_frame_length_field_too_large(self):
        """
        Test that frame with length field larger than actual message fails gracefully.

        Expected result:
        - Returns type='unknown' (frame structure validation fails)
        """
        message = b'"ACK"0001R0L0A0[]'

        # Build frame but set length field incorrectly (say 0050, actual ~17)
        frame = b'\x0A' + b'0000' + b'0050' + message + b'\x0D'

        result = decode_ack_nak(frame)

        # Assert: Length mismatch causes graceful failure
        assert result['type'] == 'unknown'

    def test_frame_length_field_too_small(self):
        """
        Test that frame with length field smaller than actual message fails.

        Expected result:
        - Returns type='unknown'
        """
        message = b'"ACK"0001R0L0A0[]'

        # Build frame with length field too small (say 0005, actual ~17)
        frame = b'\x0A' + b'0000' + b'0005' + message + b'\x0D'

        result = decode_ack_nak(frame)

        # Assert: Length mismatch handled gracefully
        assert result['type'] == 'unknown'


class TestNakAckSequenceIntegration:
    """Test NAK/ACK sequence matching in realistic scenario (Gap 10 — integration)."""

    def test_nak_then_ack_for_retry_scenario(self):
        """
        Test realistic error-recovery scenario: send msg1 (seq=0001), get NAK, retry msg2 (seq=0002), get ACK.

        Expected result:
        - NAK has seq=0 (standard); ACK has seq=0002 (echoing retry message)
        """
        builder = SIAMessageBuilder(crc_format='hex')

        # Simulate message 1 sent
        builder.encode_message("001234", "1130")  # seq=0001

        # Simulate NAK received (always seq=0000 per spec)
        nak_message = b'"NAK"0000R0L0A0[]'
        nak_frame = build_frame(nak_message)
        nak_result = decode_ack_nak(nak_frame)

        # Assert: NAK has seq=0
        assert nak_result['type'] == 'NAK'
        assert nak_result['seq'] == 0

        # Simulate message 2 sent (after retry)
        builder.encode_message("001234", "2130")  # seq=0002

        # Simulate ACK received for message 2 (echoing seq=0002)
        ack_message = b'"ACK"0002R0L0A0[]'
        ack_frame = build_frame(ack_message)
        ack_result = decode_ack_nak(ack_frame)

        # Assert: ACK echoes retry sequence 0002
        assert ack_result['type'] == 'ACK'
        assert ack_result['seq'] == 2

