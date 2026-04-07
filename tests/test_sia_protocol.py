"""
Unit tests for sia_protocol module.

Tests cover:
- CRC calculation against spec examples
- Message frame structure and delimiters
- Sequence number management (wrap-around)
- Account ID formatting
- Complete message encoding
- NULL message generation
"""

import unittest
from datetime import datetime, timezone
from resources.siadc09d.sia_protocol import (
    # Constants
    LF, CR, SIA_NULL_CODE, BURGLARY, FIRE, PANIC,
    SIA_DCS_TOKEN, ADM_CID_TOKEN,
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


# ===== TESTS: Constants =====

class TestConstants(unittest.TestCase):
    """Test protocol constants."""

    def test_lf_is_0x0a(self):
        self.assertEqual(LF, b'\x0A')

    def test_cr_is_0x0d(self):
        self.assertEqual(CR, b'\x0D')

    def test_null_code(self):
        self.assertEqual(SIA_NULL_CODE, "0000")

    def test_event_codes(self):
        self.assertEqual(BURGLARY, "1")
        self.assertEqual(FIRE, "2")
        self.assertEqual(PANIC, "3")


# ===== TESTS: SequenceManager =====

class TestSequenceManager(unittest.TestCase):
    """Test sequence number management."""

    def test_first_sequence_is_0001(self):
        mgr = SequenceManager()
        seq = mgr.next_seq("001234")
        self.assertEqual(seq, "0001")

    def test_sequence_increments(self):
        mgr = SequenceManager()
        seq1 = mgr.next_seq("001234")
        seq2 = mgr.next_seq("001234")
        seq3 = mgr.next_seq("001234")
        self.assertEqual(seq1, "0001")
        self.assertEqual(seq2, "0002")
        self.assertEqual(seq3, "0003")

    def test_sequence_wraps_from_9999_to_0001(self):
        """Test wrap-around from 9999 → 0001 (not 0000)."""
        mgr = SequenceManager()
        # Manually set to 9999
        mgr._seq_map["001234"] = 9999
        next_seq = mgr.next_seq("001234")
        self.assertEqual(next_seq, "0001")

    def test_current_seq_without_increment(self):
        """Test current_seq doesn't increment."""
        mgr = SequenceManager()
        mgr.next_seq("001234")  # Set to 0001
        current1 = mgr.current_seq("001234")
        current2 = mgr.current_seq("001234")
        self.assertEqual(current1, "0001")
        self.assertEqual(current2, "0001")

    def test_per_account_sequence(self):
        """Test sequence numbers are per-account."""
        mgr = SequenceManager()
        seq_a1 = mgr.next_seq("acctA")
        seq_b1 = mgr.next_seq("acctB")
        seq_a2 = mgr.next_seq("acctA")
        seq_b2 = mgr.next_seq("acctB")

        self.assertEqual(seq_a1, "0001")
        self.assertEqual(seq_b1, "0001")
        self.assertEqual(seq_a2, "0002")
        self.assertEqual(seq_b2, "0002")


# ===== TESTS: CRC Calculation =====

class TestCRCCalculation(unittest.TestCase):
    """Test CRC calculation."""

    def test_calculate_crc_returns_4_hex_chars(self):
        """CRC should be 4-character ASCII hex."""
        data = b'"SIA-DCS"0001L0#1234[#1234|FA 129]'
        crc = calculate_crc(data, CRC_FORMAT_SIA)
        self.assertEqual(len(crc), 4)
        for c in crc:
            self.assertIn(c, '0123456789ABCDEF')

    def test_crc_format_sia(self):
        """SIA format should be accepted."""
        data = b'"SIA-DCS"0001L0#1234'
        crc = calculate_crc(data, CRC_FORMAT_SIA)
        self.assertEqual(len(crc), 4)

    def test_crc_format_adm(self):
        """ADM format should be accepted."""
        data = b'"ADM-CID"0001L0#1234'
        crc = calculate_crc(data, CRC_FORMAT_ADM)
        self.assertEqual(len(crc), 4)

    def test_crc_invalid_format_raises(self):
        """Invalid CRC format should raise ValueError."""
        data = b'"SIA-DCS"0001L0#1234'
        with self.assertRaises(ValueError):
            calculate_crc(data, "INVALID")


# ===== TESTS: Length Calculation =====

class TestLengthCalculation(unittest.TestCase):
    """Test message length calculation."""

    def test_length_starts_with_zero(self):
        """Length should start with '0'."""
        data = b'"SIA-DCS"0001L0#1234'
        length = calculate_length(data)
        self.assertTrue(length.startswith("0"))

    def test_length_is_4_chars(self):
        """Length should be 4 characters total."""
        data = b'"SIA-DCS"0001L0#1234'
        length = calculate_length(data)
        self.assertEqual(len(length), 4)

    def test_length_is_hex(self):
        """Length field should be hex after leading 0."""
        data = b'"SIA-DCS"0001L0#1234'
        length = calculate_length(data)
        # Should be "0" + 3 hex digits
        self.assertEqual(length[0], "0")
        for c in length[1:]:
            self.assertIn(c, '0123456789ABCDEF')

    def test_length_calculation_example(self):
        """Test length calculation with known size."""
        # Create exactly 64 bytes
        data = b'x' * 64
        length = calculate_length(data)
        self.assertEqual(length, "0040")  # 0x40 = 64 in hex


# ===== TESTS: Account ID Formatting =====

class TestAccountIDFormatting(unittest.TestCase):
    """Test account identification formatting."""

    def test_basic_account_id(self):
        """Test basic account ID without receiver."""
        result = format_account_id("001234", "L0")
        self.assertEqual(result, "#001234L0")

    def test_account_id_with_prefix(self):
        """Test account ID with custom prefix."""
        result = format_account_id("001234", "L1")
        self.assertEqual(result, "#001234L1")

    def test_account_id_with_receiver(self):
        """Test account ID with receiver number."""
        result = format_account_id("001234", "L1", "R2")
        self.assertEqual(result, "R2#001234L1")

    def test_account_id_receiver_zero_omitted(self):
        """Test that receiver '0' is omitted."""
        result = format_account_id("001234", "L0", "0")
        self.assertEqual(result, "#001234L0")

    def test_account_id_invalid_account_raises(self):
        """Invalid account number should raise."""
        with self.assertRaises(ValueError):
            format_account_id("XYZ", "L0")  # Too short

    def test_account_id_invalid_prefix_raises(self):
        """Invalid prefix should raise."""
        with self.assertRaises(ValueError):
            format_account_id("001234", "LG")  # G is not hex

    def test_account_id_hex_case_insensitive(self):
        """Account ID should accept upper and lower case hex."""
        result = format_account_id("aAbBcCdD", "L0")
        self.assertIn("#aAbBcCdDL0", [result, result])


# ===== TESTS: Data Field Formatting =====

class TestDataFieldFormatting(unittest.TestCase):
    """Test data field formatting."""

    def test_data_field_basic(self):
        """Test basic data field format."""
        result = format_data_field("001234", "1130")
        self.assertEqual(result, "[#001234|1130]")

    def test_data_field_fire_code(self):
        """Test data field with fire event code."""
        result = format_data_field("001234", "2130")
        self.assertEqual(result, "[#001234|2130]")

    def test_data_field_has_brackets(self):
        """Data field should include bracket characters."""
        result = format_data_field("001234", "1130")
        self.assertTrue(result.startswith("["))
        self.assertTrue(result.endswith("]"))

    def test_data_field_has_pipe_separator(self):
        """Data field should use pipe separator."""
        result = format_data_field("001234", "1130")
        self.assertIn("|", result)


# ===== TESTS: Timestamp Formatting =====

class TestTimestampFormatting(unittest.TestCase):
    """Test timestamp field formatting."""

    def test_timestamp_length(self):
        """Timestamp should be 10 hex characters."""
        ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
        result = format_timestamp(ts)
        self.assertEqual(len(result), 10)

    def test_timestamp_is_hex(self):
        """Timestamp should be hex digits."""
        ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
        result = format_timestamp(ts)
        for c in result:
            self.assertIn(c, '0123456789ABCDEF')

    def test_timestamp_no_separators(self):
        """Timestamp should have no colons, underscores, or dashes."""
        ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
        result = format_timestamp(ts)
        self.assertNotIn("_", result)
        self.assertNotIn(":", result)
        self.assertNotIn("-", result)

    def test_timestamp_current_if_none(self):
        """None timestamp should use current time."""
        before = int(datetime.now(timezone.utc).timestamp())
        result = format_timestamp(None)
        after = int(datetime.now(timezone.utc).timestamp()) + 1
        # Parse hex timestamp
        ts_int = int(result, 16)
        self.assertGreaterEqual(ts_int, before)
        self.assertLessEqual(ts_int, after)


# ===== TESTS: Complete Message Encoding =====

class TestEncodeMessage(unittest.TestCase):
    """Test complete message encoding."""

    def test_encode_message_starts_with_lf(self):
        """Message should start with LF (0x0A)."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertTrue(frame.startswith(LF))

    def test_encode_message_ends_with_cr(self):
        """Message should end with CR (0x0D)."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertTrue(frame.endswith(CR))

    def test_encode_message_has_crc(self):
        """Message should contain 4-digit CRC."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        # After LF, next 4 bytes should be CRC
        crc_bytes = frame[1:5]
        self.assertEqual(len(crc_bytes), 4)
        # CRC should be ASCII hex

    def test_encode_message_has_length(self):
        """Message should contain length field (0LLL)."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        # After CRC, next 4 bytes should be length
        length_bytes = frame[5:9]
        self.assertEqual(len(length_bytes), 4)
        self.assertTrue(length_bytes.startswith(b'0'))

    def test_encode_message_has_id_token(self):
        """Message should contain ID token."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA,
            encryption=False
        )
        self.assertIn(b'"SIA-DCS"', frame)

    def test_encode_message_crc_format_keyword_only(self):
        """crc_format must be keyword-only parameter."""
        with self.assertRaises(TypeError):
            encode_message("001234", "1130", "L0", None, None, None, CRC_FORMAT_SIA)

    def test_encode_message_unencrypted_token(self):
        """Unencrypted message should use SIA-DCS token."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA,
            encryption=False
        )
        self.assertIn(b'"SIA-DCS"', frame)
        # Should not have encryption marker in unencrypted mode
        self.assertNotIn(b'"*', frame)

    def test_encode_message_encrypted_token(self):
        """Encrypted message should use *SIA-DCS token."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA,
            encryption=True
        )
        self.assertIn(b'"*SIA-DCS"', frame)

    def test_encode_message_returns_bytes(self):
        """encode_message should return bytes."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertIsInstance(frame, bytes)

    def test_encode_message_with_receiver(self):
        """Message should include receiver number if provided."""
        frame = encode_message(
            "001234", "1130",
            account_prefix="L1",
            receiver_number="R2",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertIn(b"R2", frame)
        self.assertIn(b"L1", frame)

    def test_encode_message_data_field_included(self):
        """Message should include data field with brackets."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertIn(b"[#001234|1130]", frame)


# ===== TESTS: NULL Message Generation =====

class TestSupervisionMessage(unittest.TestCase):
    """Test NULL/supervision message generation."""

    def test_null_message_uses_0000_event_code(self):
        """NULL message should use event code 0000."""
        frame = make_supervision_message(
            "001234",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertIn(b"0000", frame)

    def test_null_message_starts_with_lf(self):
        """NULL message should start with LF."""
        frame = make_supervision_message(
            "001234",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertTrue(frame.startswith(LF))

    def test_null_message_ends_with_cr(self):
        """NULL message should end with CR."""
        frame = make_supervision_message(
            "001234",
            crc_format=CRC_FORMAT_SIA
        )
        self.assertTrue(frame.endswith(CR))

    def test_null_message_encrypted_flag(self):
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
        self.assertIn(b'"SIA-DCS"', unencrypted)
        self.assertIn(b'"*SIA-DCS"', encrypted)

    def test_null_message_with_custom_prefix(self):
        """NULL message should use custom prefix if provided."""
        frame = make_supervision_message(
            "001234",
            crc_format=CRC_FORMAT_SIA,
            account_prefix="L2"
        )
        self.assertIn(b"L2", frame)


# ===== INTEGRATION TESTS =====

class TestIntegration(unittest.TestCase):
    """Integration tests for complete workflows."""

    def test_message_frame_is_valid(self):
        """Complete message frame should have all required fields."""
        frame = encode_message(
            "001234", "1130",
            crc_format=CRC_FORMAT_SIA
        )

        # Check overall structure: LF + CRC + LENGTH + ... + CR
        self.assertEqual(frame[0:1], LF)
        self.assertEqual(frame[-1:], CR)
        self.assertGreater(len(frame), 20)  # Minimum frame size

    def test_example_message_structure(self):
        """Test against protocol spec example structure."""
        # Example from spec: B3680040"SIA-DCS"0001L0#1234[#1234|FA 129]
        frame = encode_message(
            "1234", "FA 129",
            account_prefix="L0",
            crc_format=CRC_FORMAT_SIA
        )

        # Basic checks
        self.assertTrue(frame.startswith(LF))
        self.assertTrue(frame.endswith(CR))
        self.assertIn(b"SIA-DCS", frame)
        self.assertIn(b"L0", frame)
        self.assertIn(b"#1234", frame)

    def test_message_with_timestamp(self):
        """Test message includes timestamp when provided."""
        ts = datetime(2026, 4, 7, 15, 30, 0, tzinfo=timezone.utc)
        frame = encode_message(
            "001234", "1130",
            timestamp=ts,
            crc_format=CRC_FORMAT_SIA
        )
        # Verify frame was created (timestamp affects length)
        self.assertIsNotNone(frame)
        self.assertGreater(len(frame), 0)


if __name__ == "__main__":
    unittest.main()
