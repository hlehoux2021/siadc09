"""
ACK/NAK parser assertion hardening tests (QA supplement).

Fills the gap where original test_sia_protocol_ack_nak.py tests only checked
a single field per test (96% of tests had 0-1 assertions). Each test here
validates ALL THREE response fields together: type, seq, raw_nak.

Reference: tests/level1/test_sia_protocol_ack_nak.py (originals)
"""

import struct
import pytest
from resources.siadc09d.sia_protocol import _compute_crc_modbus, decode_ack_nak


def _build_frame(message: bytes, crc_format: str = 'hex') -> bytes:
    """Build a complete SIA frame with correct CRC and length."""
    crc_value = _compute_crc_modbus(message)
    if crc_format == 'hex':
        crc_data = f"{crc_value:04X}".encode()
    else:
        crc_data = struct.pack('<H', crc_value)
    length_data = f"0{len(message):03X}".encode()
    return b'\x0A' + crc_data + length_data + message + b'\x0D'


# ===== Full triple-field validation on every parse =====


@pytest.mark.parametrize("msg,expected_type,expected_seq,has_raw_nak", [
    (b'"ACK"0000R0L0A0[]', 'ACK', 0, False),
    (b'"ACK"0001R0L0A0[]', 'ACK', 1, False),
    (b'"ACK"5000R0L0A0[]', 'ACK', 5000, False),
    (b'"ACK"9999R0L0A0[]', 'ACK', 9999, False),
    (b'"NAK"0000R0L0A0[]', 'NAK', 0, True),
    (b'"*ACK"0001R0L0A0[]', 'ACK', 1, False),
    (b'"*NAK"0000R0L0A0[]', 'NAK', 0, True),
    (b'"ACK"0001L0A0[]', 'ACK', 1, False),
    (b'"ACK"0001R99L0A0[]', 'ACK', 1, False),
    (b'"NAK"0000R0L0A0[]_14:32:45,03-22-2026', 'NAK', 0, True),
])
def test_triple_field_validation(msg, expected_type, expected_seq, has_raw_nak):
    """
    Every decode result is checked for ALL three fields (type, seq, raw_nak).

    Expected result:
    - type matches expected_type
    - seq matches expected_seq
    - raw_nak is None for ACK, full frame bytes for NAK
    """
    frame = _build_frame(msg)
    result = decode_ack_nak(frame)

    # Assert: type field matches
    assert result['type'] == expected_type, f"Expected type={expected_type}, got {result['type']}"
    # Assert: seq field matches
    assert result['seq'] == expected_seq, f"Expected seq={expected_seq}, got {result['seq']}"
    # Assert: raw_nak field matches
    if has_raw_nak:
        assert result['raw_nak'] == frame, "NAK should have raw_nak = full frame bytes"
        assert isinstance(result['raw_nak'], bytes), "raw_nak must be bytes"
    else:
        assert result['raw_nak'] is None, "ACK should have raw_nak=None"


@pytest.mark.parametrize("bad_input", [
    b'',
    b'\x0A',
    b'\x0D',
    b'\x0A\x0D',
    b'not a frame at all',
    b'\x0A' + b'XXXX' + b'0010' + b'"ACK"0001R0L0A0[]' + b'\x0D',
    b'\x0A' + b'0000' + b'0050' + b'"ACK"0001R0L0A0[]' + b'\x0D',
    b'\x00' * 100,
])
def test_triple_field_validation_unknown(bad_input):
    """
    All invalid inputs return consistent 'unknown' triple (type, seq, raw_nak).

    Expected result:
    - type='unknown', seq=None, raw_nak=None — all three checked
    """
    result = decode_ack_nak(bad_input)

    # Assert: all three fields are the 'unknown' defaults
    assert result['type'] == 'unknown'
    assert result['seq'] is None
    assert result['raw_nak'] is None


# ===== Binary CRC format triple-field validation =====


@pytest.mark.parametrize("msg,expected_type,expected_seq", [
    (b'"ACK"0001R0L0A0[]', 'ACK', 1),
    (b'"NAK"0000R0L0A0[]', 'NAK', 0),
    (b'"ACK"9999R0L0A0[]', 'ACK', 9999),
])
def test_binary_crc_triple_field(msg, expected_type, expected_seq):
    """
    Binary CRC frames also validate all three fields.

    Expected result:
    - Binary CRC encoding produces same type/seq/raw_nak semantics as hex
    """
    frame = _build_frame(msg, crc_format='bin')
    result = decode_ack_nak(frame, crc_format='bin')

    # Assert: type
    assert result['type'] == expected_type
    # Assert: seq
    assert result['seq'] == expected_seq
    # Assert: raw_nak
    if expected_type == 'NAK':
        assert result['raw_nak'] == frame
    else:
        assert result['raw_nak'] is None


# ===== Cross-format rejection =====


def test_hex_frame_rejected_as_binary():
    """
    Hex CRC frame parsed with crc_format='bin' is rejected.

    Expected result:
    - CRC mismatch → all three fields are 'unknown' defaults
    """
    msg = b'"ACK"0001R0L0A0[]'
    hex_frame = _build_frame(msg, crc_format='hex')
    result = decode_ack_nak(hex_frame, crc_format='bin')

    # Assert: full triple is unknown
    assert result['type'] == 'unknown'
    assert result['seq'] is None
    assert result['raw_nak'] is None


def test_binary_frame_rejected_as_hex():
    """
    Binary CRC frame parsed with crc_format='hex' is rejected.

    Expected result:
    - CRC mismatch → all three fields are 'unknown' defaults
    """
    msg = b'"ACK"0001R0L0A0[]'
    bin_frame = _build_frame(msg, crc_format='bin')
    result = decode_ack_nak(bin_frame, crc_format='hex')

    # Assert: full triple is unknown
    assert result['type'] == 'unknown'
    assert result['seq'] is None
    assert result['raw_nak'] is None
