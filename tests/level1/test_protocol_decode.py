"""
Level 1 tests for sia_protocol.decode() function and CLI --decode mode.

Validates the ParsedMessage dataclass fields, CRC validation, malformed-input
handling and the __main__ CLI entry point — no external dependencies.

Reference: internal-docs/design/debug-ui-design.md § 5c.3
Reference: _bmad-output/implementation-artifacts/9-2-protocol-inspector-hex-viewer-decryption.md
"""

import dataclasses
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from resources.siadc09d.sia_protocol import (
    SIAMessageBuilder,
    SIAProtocolError,
    ParsedMessage,
    decode,
)
from tests.level1._dc09_crypto_oracle import EXPECTED_CONTENT, crc16_arc, vector

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SIA_PROTOCOL_SCRIPT = _PROJECT_ROOT / "resources/siadc09d/sia_protocol.py"

_KEY_128 = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
_TS = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)

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
    """decode() on DC-09 encrypted frames (story 1-5 AC7, § 5.4.3)."""

    def test_encrypted_frame_without_key_sets_encrypted_true(self) -> None:
        """
        decode() without a key on an encrypted frame must still set encrypted=True.

        Expected result:
        - encrypted is True, data_decrypted is None, no decrypt_error
        - data_raw is the wire hex (no ']' after it)
        """
        frame = SIAMessageBuilder(crc_format="SIA").encode_message(
            account_number="1234", event_code="BA", encryption=True, encryption_key=_KEY_128)
        result = decode(frame.hex())
        # Assert: encrypted marker detected even without key
        assert result.encrypted is True
        # Assert: no key provided → no decrypted output and no error
        assert result.data_decrypted is None and result.decrypt_error is None
        # Assert: data_raw carries the ciphertext hex up to the end of the message
        assert re.fullmatch(r"[0-9A-F]+", result.data_raw) and len(result.data_raw) % 32 == 0

    def test_encrypted_frame_with_key_decrypts_region(self) -> None:
        """
        decode() with the key returns the region content and the plaintext timestamp.

        Expected result:
        - data_decrypted == '#1234|BA 001][Vhttp://c/s]_12:00:00,09-27-2026'
        - timestamp_str parsed from the plaintext
        - key and pad never appear in the result
        """
        builder = SIAMessageBuilder(crc_format="SIA", pad_source=lambda n: b"p" * n)
        frame = builder.encode_message(
            "1234", "BA", extended_data={"zone": "001", "media_url": "http://c/s"},
            timestamp=_TS, encryption=True, encryption_key=_KEY_128)
        result = decode(frame.hex(), key=_KEY_128)
        # Assert: decrypted region content, pad and '|' stripped
        assert result.data_decrypted == "#1234|BA 001][Vhttp://c/s]_12:00:00,09-27-2026"
        # Assert: timestamp comes from the plaintext
        assert result.timestamp_str == "12:00:00,09-27-2026"
        # Assert: CRC and length valid on the wire form
        assert result.crc_valid and result.length_declared == result.length_actual
        dumped = json.dumps(dataclasses.asdict(result))
        # Assert: neither key nor pad leaks into the output
        assert _KEY_128.hex().upper() not in dumped.upper() and "pppp" not in dumped

    def test_encrypted_null_decodes(self) -> None:
        """
        An encrypted *NULL decodes to id_token NULL, sequence 0, content ']_ts'.

        Expected result:
        - id_token 'NULL', encrypted True, sequence 0
        - data_decrypted ']_12:00:00,09-27-2026'
        """
        frame = SIAMessageBuilder(crc_format="SIA").make_supervision_message(
            "1234", encryption=True, encryption_key=_KEY_128, timestamp=_TS)
        result = decode(frame.hex(), key=_KEY_128)
        # Assert: Null Message header
        assert (result.id_token, result.encrypted, result.sequence) == ("NULL", True, 0)
        # Assert: region content
        assert result.data_decrypted == "]_12:00:00,09-27-2026"

    def test_encrypted_frame_with_wrong_key_data_decrypted_none(self) -> None:
        """
        decode() with an incorrect key returns data_decrypted=None and a clean error (no crash).

        Expected result:
        - data_decrypted is None
        - decrypt_error explains the failure without the key
        """
        builder = SIAMessageBuilder(crc_format="SIA", pad_source=lambda n: b"p" * n)
        frame = builder.encode_message("1234", "BA", timestamp=_TS, encryption=True, encryption_key=_KEY_128)
        wrong_key = b"\x00" * 16
        result = decode(frame.hex(), key=wrong_key)
        # Assert: failed decryption yields None, not an exception
        assert result.data_decrypted is None
        # Assert: a clean, key-free error message is reported
        assert result.decrypt_error and wrong_key.hex() not in result.decrypt_error

    def test_bad_key_size_is_a_clean_error(self) -> None:
        """
        A key of an unsupported size gives decrypt_error, not an AESKeyError traceback.

        Expected result:
        - data_decrypted None, decrypt_error set
        """
        frame = SIAMessageBuilder(crc_format="SIA").encode_message(
            "1234", "BA", encryption=True, encryption_key=_KEY_128)
        result = decode(frame.hex(), key=b"short")
        # Assert: key problem reported cleanly
        assert result.data_decrypted is None and result.decrypt_error

    def test_bracketed_hex_still_accepted(self) -> None:
        """
        '[hex]' (spec § 5.4.7 example form, V5) is still parsed.

        Expected result:
        - V5 decrypts to its expected content
        """
        v5 = vector("V5_spec")
        result = decode(_frame_hex(v5.frame_body), key=v5.key)
        # Assert: trailing ']' tolerated
        assert result.data_decrypted == EXPECTED_CONTENT["V5_spec"].decode()

    @pytest.mark.parametrize("name", ["V1_ajax", "V2_ajax", "V4_dc09gen", "V5_spec", "V6_null_nopipe", "S1_swiss_null"])
    def test_external_vectors_decode(self, name: str) -> None:
        """
        The decoder decrypts and parses every external event/NULL vector (AC9).

        Expected result:
        - encrypted True, data_decrypted equals the known content
        - declared CRC/length (when quoted) equal the recomputed ones
        """
        v = vector(name)
        result = decode(_frame_hex(v.frame_body), key=v.key)
        # Assert: encrypted frame recognised
        assert result.encrypted is True
        # Assert: region content recovered
        assert result.data_decrypted == EXPECTED_CONTENT[name].decode("windows-1252")
        if v.crc is not None:
            # Assert: real-panel CRC/length match our computation over the wire body
            assert (f"{crc16_arc(v.frame_body.encode()):04X}", f"0{len(v.frame_body):03X}") == (v.crc, v.length)

    def test_cli_decode_encrypted_with_env_key(self) -> None:
        """
        `sia_protocol.py --decode` with SIA_ENCRYPTION_KEY (hex) decrypts (PHP inspector path).

        Expected result:
        - exit 0, data_decrypted set, key absent from stdout
        """
        frame = SIAMessageBuilder(crc_format="SIA").encode_message(
            "1234", "BA", timestamp=_TS, encryption=True, encryption_key=_KEY_128)
        result = subprocess.run(
            [sys.executable, str(_SIA_PROTOCOL_SCRIPT), "--decode", frame.hex()],
            capture_output=True, text=True, env={**os.environ, "SIA_ENCRYPTION_KEY": _KEY_128.hex()},
        )
        # Assert: script-mode import works and decode succeeds
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        # Assert: decrypted content returned
        assert data["data_decrypted"] == "#1234|BA]_12:00:00,09-27-2026"
        # Assert: key never echoed
        assert _KEY_128.hex() not in result.stdout.lower()

    def test_cli_decode_rejects_bad_env_key(self) -> None:
        """
        An invalid SIA_ENCRYPTION_KEY gives an error JSON without the key.

        Expected result:
        - exit 1, {'error': ...}, key text absent
        """
        result = subprocess.run(
            [sys.executable, str(_SIA_PROTOCOL_SCRIPT), "--decode", _GOLDEN_HEX],
            capture_output=True, text=True, env={**os.environ, "SIA_ENCRYPTION_KEY": "notakey123"},
        )
        # Assert: error exit
        assert result.returncode == 1
        # Assert: error JSON without the key
        assert "error" in json.loads(result.stdout) and "notakey123" not in result.stdout


def _frame_hex(body: str) -> str:
    """Wrap a wire message into LF CRC LEN body CR (CRC recomputed) and return its hex."""
    raw = body.encode("windows-1252")
    return (b"\n" + f"{crc16_arc(raw):04X}0{len(raw):03X}".encode() + raw + b"\r").hex()


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
