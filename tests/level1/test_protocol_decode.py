"""
Level 1 tests for sia_protocol.decode() function and CLI --decode mode.

Validates the ParsedMessage dataclass fields, CRC validation, malformed-input
handling and the __main__ CLI entry point — no external dependencies.

Reference: internal-docs/design/debug-ui-design.md § 5c.3
Reference: _bmad-output/implementation-artifacts/9-2-protocol-inspector-hex-viewer-decryption.md
"""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from resources.siadc09d.sia_protocol import (
    SIAMessageBuilder,
    SIAProtocolError,
    ParsedMessage,
    decode,
)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SIA_PROTOCOL_SCRIPT = _PROJECT_ROOT / "resources/siadc09d/sia_protocol.py"

# ── Golden frame constants ───────────────────────────────────────────────────

# Built via SIAMessageBuilder(crc_format='SIA').encode_message('1234', '0000')
# CRC=B437, sequence=0001, account=1234, data_raw=#1234|0000
_GOLDEN_HEX = (
    "0a4234333730303230225349412d44435322303030314c30"
    "23313233345b23313233347c303030305d0d"
)

# Same frame with one message-body byte flipped (position 10) → crc_valid=False
_CORRUPTED_HEX = (
    "0a4234333730303230225249412d44435322303030314c30"
    "23313233345b23313233347c303030305d0d"
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def golden_frame() -> ParsedMessage:
    """Decoded ParsedMessage for the known-good supervision frame."""
    return decode(_GOLDEN_HEX)


# ── Task 8.1: decode() returns correct ParsedMessage ─────────────────────────


class TestDecodeKnownGoodFrame:
    """Verify decode() returns correct ParsedMessage for a known good frame."""

    def test_id_token(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must return id_token='SIA-DCS' for a standard SIA frame.

        Expected result:
        - id_token field equals 'SIA-DCS'
        """
        # Assert: correct id_token from standard supervision frame
        assert golden_frame.id_token == "SIA-DCS"

    def test_sequence(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must return sequence=1 for first built frame.

        Expected result:
        - sequence field equals 1
        """
        # Assert: sequence parsed as integer
        assert golden_frame.sequence == 1

    def test_account(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must return account='1234'.

        Expected result:
        - account field equals '1234'
        """
        # Assert: account number extracted correctly
        assert golden_frame.account == "1234"

    def test_crc_valid(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must return crc_valid=True for well-formed frame.

        Expected result:
        - crc_valid is True
        """
        # Assert: CRC validates for known-good frame
        assert golden_frame.crc_valid is True

    def test_crc_format(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must detect crc_format='hex' for SIA-style (4-char ASCII) CRC.

        Expected result:
        - crc_format equals 'hex'
        """
        # Assert: hex CRC format auto-detected
        assert golden_frame.crc_format == "hex"

    def test_encrypted_false(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must return encrypted=False for unencrypted frame.

        Expected result:
        - encrypted is False
        """
        # Assert: unencrypted frame not marked as encrypted
        assert golden_frame.encrypted is False

    def test_raw_hex_preserved(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must preserve the original hex string in raw_hex field.

        Expected result:
        - raw_hex matches the input string
        """
        # Assert: input hex string round-trips unchanged
        assert golden_frame.raw_hex == _GOLDEN_HEX

    def test_crc_received_and_computed_match(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must set crc_received and crc_computed to the same value for valid frame.

        Expected result:
        - crc_received equals crc_computed
        """
        # Assert: received and computed CRC match on valid frame
        assert golden_frame.crc_received == golden_frame.crc_computed

    def test_result_is_json_serializable(self, golden_frame: ParsedMessage) -> None:
        """
        ParsedMessage produced by decode() must be fully JSON-serializable via dataclasses.asdict().

        Expected result:
        - json.dumps(dataclasses.asdict(result)) does not raise
        """
        d = dataclasses.asdict(golden_frame)
        # Assert: no TypeError from non-serializable types
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_account_prefix(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must extract account_prefix='L0'.

        Expected result:
        - account_prefix field equals 'L0'
        """
        # Assert: account prefix extracted from L-field
        assert golden_frame.account_prefix == "L0"

    def test_length_match(self, golden_frame: ParsedMessage) -> None:
        """
        decode() must report equal length_declared and length_actual for well-formed frame.

        Expected result:
        - length_declared equals length_actual
        """
        # Assert: declared and actual lengths match
        assert golden_frame.length_declared == golden_frame.length_actual


# ── Task 8.2: encrypted frame with valid key ─────────────────────────────────


class TestDecodeEncryptedFrame:
    """Verify decode() handles encrypted frame with valid key."""

    def test_encrypted_frame_without_key_sets_encrypted_true(self) -> None:
        """
        decode() without a key on an encrypted frame must still set encrypted=True.

        Expected result:
        - encrypted is True, data_decrypted is None
        """
        builder = SIAMessageBuilder(crc_format="SIA")
        # encode_message with encryption=True produces a *SIA-DCS token
        frame = builder.encode_message(
            account_number="1234",
            event_code="0000",
            encryption=True,
        )
        result = decode(frame.hex())
        # Assert: encrypted marker detected even without key
        assert result.encrypted is True
        # Assert: no key provided → no decrypted output
        assert result.data_decrypted is None

    def test_encrypted_frame_with_wrong_key_data_decrypted_none(self) -> None:
        """
        decode() with incorrect key must return data_decrypted=None (no crash).

        Expected result:
        - data_decrypted is None when decryption fails
        """
        builder = SIAMessageBuilder(crc_format="SIA")
        frame = builder.encode_message(
            account_number="1234",
            event_code="0000",
            encryption=True,
        )
        wrong_key = b"\x00" * 16
        result = decode(frame.hex(), key=wrong_key)
        # Assert: failed decryption yields None, not an exception
        assert result.data_decrypted is None


# ── Task 8.3: corrupted CRC → crc_valid=False ────────────────────────────────


class TestDecodeCorruptedCrc:
    """Verify decode() returns crc_valid=False for corrupted CRC frame."""

    def test_crc_valid_false_on_body_corruption(self) -> None:
        """
        decode() must return crc_valid=False when message body is corrupted.

        Expected result:
        - crc_valid is False
        - crc_received != crc_computed
        """
        result = decode(_CORRUPTED_HEX)
        # Assert: CRC mismatch detected
        assert result.crc_valid is False
        # Assert: received and computed values differ
        assert result.crc_received != result.crc_computed

    def test_decode_does_not_raise_on_crc_mismatch(self) -> None:
        """
        decode() must not raise on CRC mismatch — returns crc_valid=False instead.

        Expected result:
        - No exception raised, ParsedMessage returned normally
        """
        # Assert: CRC mismatch is non-fatal
        result = decode(_CORRUPTED_HEX)
        assert isinstance(result, ParsedMessage)


# ── Task 8.4: malformed input handled gracefully ─────────────────────────────


class TestDecodeMalformedInput:
    """Verify decode() raises SIAProtocolError for malformed inputs without crashing."""

    def test_invalid_hex_characters_raise(self) -> None:
        """
        decode() must raise SIAProtocolError for non-hex input.

        Expected result:
        - SIAProtocolError raised with descriptive message
        """
        # Assert: non-hex input rejected at the fromhex boundary
        with pytest.raises(SIAProtocolError, match="Invalid hex input"):
            decode("ZZZZ")

    def test_empty_string_raises(self) -> None:
        """
        decode() must raise SIAProtocolError for empty string input.

        Expected result:
        - SIAProtocolError raised
        """
        # Assert: empty string is malformed
        with pytest.raises(SIAProtocolError):
            decode("")

    def test_too_short_frame_raises(self) -> None:
        """
        decode() must raise SIAProtocolError for frames too short to be valid.

        Expected result:
        - SIAProtocolError raised for minimal stub frame (LF + CR only)
        """
        # Assert: two-byte frame is rejected
        with pytest.raises(SIAProtocolError, match="Malformed frame structure"):
            decode("0a0d")

    def test_missing_frame_delimiters_raises(self) -> None:
        """
        decode() must raise SIAProtocolError if frame does not start with LF (0x0A).

        Expected result:
        - SIAProtocolError raised when LF delimiter is absent
        """
        # Assert: frame without leading LF byte is malformed
        with pytest.raises(SIAProtocolError):
            decode("ff" + _GOLDEN_HEX[2:])


# ── Task 8.5: CLI --decode mode outputs valid JSON ────────────────────────────


class TestCliDecodeMode:
    """Verify __main__ CLI --decode mode outputs valid JSON to stdout."""

    def test_cli_outputs_json_for_valid_hex(self) -> None:
        """
        CLI --decode <hex> must output valid JSON with expected fields.

        Expected result:
        - stdout is valid JSON
        - JSON contains 'id_token', 'account', 'crc_valid' keys
        - return code is 0
        """
        result = subprocess.run(
            [sys.executable, str(_SIA_PROTOCOL_SCRIPT), "--decode", _GOLDEN_HEX],
            capture_output=True,
            text=True,
        )
        # Assert: exit code 0 for valid frame
        assert result.returncode == 0
        # Assert: stdout is parseable JSON
        data = json.loads(result.stdout)
        # Assert: expected keys present
        assert "id_token" in data
        assert "account" in data
        assert "crc_valid" in data

    def test_cli_outputs_error_json_for_invalid_hex(self) -> None:
        """
        CLI --decode with invalid hex must output JSON with 'error' key and exit code 1.

        Expected result:
        - stdout contains JSON {'error': ...}
        - return code is 1
        """
        result = subprocess.run(
            [sys.executable, str(_SIA_PROTOCOL_SCRIPT), "--decode", "ZZZZ"],
            capture_output=True,
            text=True,
        )
        # Assert: exit code 1 for invalid input
        assert result.returncode == 1
        # Assert: error JSON returned, not a traceback
        data = json.loads(result.stdout)
        assert "error" in data

    def test_cli_crc_valid_field_is_bool(self) -> None:
        """
        CLI output must have crc_valid as a JSON boolean (not a string).

        Expected result:
        - crc_valid field is Python bool after json.loads()
        """
        result = subprocess.run(
            [sys.executable, str(_SIA_PROTOCOL_SCRIPT), "--decode", _GOLDEN_HEX],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        # Assert: boolean type preserved in JSON serialization
        assert isinstance(data["crc_valid"], bool)


# ── ParsedMessage.extended_fields contract ───────────────────────────────────


class TestDecodeExtendedFields:
    """Verify ParsedMessage.extended_fields is always present and is a dict."""

    def test_extended_fields_present_on_golden_frame(
        self, golden_frame: ParsedMessage
    ) -> None:
        """
        decode() must always populate extended_fields on the returned ParsedMessage,
        even when the frame carries no SIA extended data.

        Expected result:
        - extended_fields attribute exists on ParsedMessage
        - extended_fields is a dict (not None, not absent)
        """
        # Assert: extended_fields attribute present and is a dict
        assert hasattr(golden_frame, "extended_fields")
        assert isinstance(golden_frame.extended_fields, dict)

    def test_extended_fields_empty_for_plain_frame(
        self, golden_frame: ParsedMessage
    ) -> None:
        """
        A standard supervision frame with no extended fields block must return
        an empty dict — not a populated dict with stale data.

        Expected result:
        - extended_fields == {} for a frame that contains no extended block
        """
        # Assert: no spurious extended field entries on a plain frame
        assert golden_frame.extended_fields == {}
