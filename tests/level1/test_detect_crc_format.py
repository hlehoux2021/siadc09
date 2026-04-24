"""
Tests for detect_crc_format() in simulate_frames.py (QA Round 2).

Covers: hex detection, binary detection, short frames, mixed bytes, garbled input.
Flagged as CRITICAL in both QA audits — function had ZERO test coverage.

Reference: resources/siadc09d/simulate_frames.py::detect_crc_format()
"""

import struct
import pytest
from resources.siadc09d.simulate_frames import detect_crc_format
from resources.siadc09d.sia_protocol import _compute_crc_modbus


def _build_hex_frame(message: bytes) -> bytes:
    """Build frame with hex (ASCII) CRC and length fields."""
    crc = _compute_crc_modbus(message)
    crc_bytes = f"{crc:04X}".encode('ascii')
    length_bytes = f"0{len(message):03X}".encode('ascii')
    return b'\x0A' + crc_bytes + length_bytes + message + b'\x0D'


def _build_bin_frame(message: bytes) -> bytes:
    """Build frame with binary (little-endian) CRC and hex length fields."""
    crc = _compute_crc_modbus(message)
    crc_bytes = struct.pack('<H', crc)
    length_bytes = f"0{len(message):03X}".encode('ascii')
    return b'\x0A' + crc_bytes + length_bytes + message + b'\x0D'


# ===== Hex format detection =====


def test_detect_hex_crc_from_valid_ack_frame():
    """
    Valid ACK frame with hex CRC detected as 'hex'.

    Expected result:
    - detect_crc_format() returns 'hex' for a properly formatted hex CRC frame
    """
    frame = _build_hex_frame(b'"ACK"0001R0L0A0[]')
    result = detect_crc_format(frame)
    # Assert: hex CRC detected
    assert result == "hex"


def test_detect_hex_crc_from_valid_nak_frame():
    """
    Valid NAK frame with hex CRC detected as 'hex'.

    Expected result:
    - detect_crc_format() returns 'hex'
    """
    frame = _build_hex_frame(b'"NAK"0000R0L0A0[]_14:32:45,03-22-2026')
    result = detect_crc_format(frame)
    # Assert: hex format
    assert result == "hex"


def test_detect_hex_crc_lowercase_digits():
    """
    Frame with lowercase hex digits (a-f) in CRC detected as 'hex'.

    Expected result:
    - Lowercase hex is still valid ASCII hex → 'hex'
    """
    frame = b'\x0Aabcd0012' + b'"ACK"0001R0L0A0[]' + b'\x0D'
    result = detect_crc_format(frame)
    # Assert: lowercase hex still detected as hex
    assert result == "hex"


# ===== Binary format detection =====


def test_detect_binary_crc_from_valid_frame():
    """
    Frame with binary (non-ASCII) CRC bytes detected as 'binary'.

    Expected result:
    - detect_crc_format() returns 'binary' when CRC contains non-hex bytes
    """
    frame = _build_bin_frame(b'"ACK"0001R0L0A0[]')
    result = detect_crc_format(frame)
    # Assert: binary CRC detected (raw bytes, not ASCII hex)
    assert result == "binary"


def test_detect_binary_with_high_bytes():
    """
    Frame with 0xFF bytes in CRC area detected as 'binary'.

    Expected result:
    - 0xFF is not ASCII hex → 'binary'
    """
    frame = b'\x0A\xFF\xFF\xFF\xFF0012' + b'"ACK"0001' + b'\x0D'
    result = detect_crc_format(frame)
    # Assert: high bytes → binary
    assert result == "binary"


def test_detect_binary_with_null_bytes():
    """
    Frame with 0x00 bytes in CRC area detected as 'binary'.

    Expected result:
    - 0x00 is not ASCII hex → 'binary'
    """
    frame = b'\x0A\x00\x01\x02\x030012' + b'message' + b'\x0D'
    result = detect_crc_format(frame)
    # Assert: null bytes → binary
    assert result == "binary"


# ===== Edge cases =====


@pytest.mark.parametrize("short_frame", [
    b'',
    b'\x0A',
    b'\x0A\x0D',
    b'\x0A12345',
    b'\x0A123456789',
])
def test_short_frame_defaults_to_hex(short_frame):
    """
    Frames shorter than 10 bytes default to 'hex'.

    Expected result:
    - detect_crc_format() returns 'hex' for short frames (< 10 bytes)
    """
    result = detect_crc_format(short_frame)
    # Assert: short frame → default 'hex'
    assert result == "hex"


def test_exactly_10_bytes_hex():
    """
    Frame of exactly 10 bytes with hex CRC returns 'hex'.

    Expected result:
    - 10 bytes is the minimum length that triggers actual detection
    """
    frame = b'\x0A' + b'ABCD0012' + b'\x0D'
    assert len(frame) == 10
    result = detect_crc_format(frame)
    # Assert: 10 bytes with hex content → 'hex'
    assert result == "hex"


def test_exactly_10_bytes_binary():
    """
    Frame of exactly 10 bytes with non-hex CRC returns 'binary'.

    Expected result:
    - Detection works at the minimum 10-byte boundary
    """
    frame = b'\x0A' + b'\xFF\xFE0012AB' + b'\x0D'
    assert len(frame) == 10
    result = detect_crc_format(frame)
    # Assert: non-hex bytes at minimum length → 'binary'
    assert result == "binary"


def test_mixed_ascii_and_binary_returns_binary():
    """
    Frame with some ASCII hex and some binary bytes returns 'binary'.

    Expected result:
    - Even one non-hex byte in positions 1-8 triggers 'binary'
    """
    frame = b'\x0AABCD\xFF012' + b'message' + b'\x0D'
    result = detect_crc_format(frame)
    # Assert: one bad byte → binary
    assert result == "binary"
