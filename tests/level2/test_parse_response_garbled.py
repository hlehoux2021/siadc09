"""
_parse_response() garbled input tests (QA Round 2).

Tests the base transport _parse_response() method with completely invalid CSR
responses — random bytes, empty frames, oversized input. Validates that the
transport-level mapping (unknown → 'timeout') works for all garbage scenarios.

Reference: resources/siadc09d/sia_transport.py::SIABaseTransport._parse_response()
"""

import pytest
from resources.siadc09d.sia_transport import (
    SIABaseTransport,
    SIATransportResult,
)


class _TestTransport(SIABaseTransport):
    """Concrete subclass for testing _parse_response() in isolation."""

    async def send_frame(self, frame: bytes) -> SIATransportResult:
        raise NotImplementedError

    async def close(self) -> None:
        pass


@pytest.fixture
def transport() -> _TestTransport:
    return _TestTransport(crc_format='hex')


# ===== Completely garbled responses =====


@pytest.mark.parametrize("garbage", [
    b'',
    b'\x00',
    b'\xFF' * 50,
    b'HTTP/1.1 404 Not Found\r\n',
    b'{"error":"invalid"}',
    b'\x0A\x0D',
    b'random garbage bytes 12345',
    b'\x0A' + b'\x00' * 100 + b'\x0D',
])
def test_garbled_response_maps_to_timeout(transport, garbage):
    """
    Completely garbled CSR responses map to status='timeout'.

    Expected result:
    - _parse_response() returns status='timeout', raw_nak=None
    - No exception raised
    """
    result = transport._parse_response(garbage)
    # Assert: garbage → timeout (unknown response)
    assert result['status'] == 'timeout'
    assert result['raw_nak'] is None


# ===== Partial SIA frames =====


def test_frame_with_lf_only(transport):
    """
    Response with just LF byte and nothing else.

    Expected result:
    - Too short for valid frame → 'timeout'
    """
    result = transport._parse_response(b'\x0A')
    # Assert: incomplete frame → timeout
    assert result['status'] == 'timeout'


def test_frame_with_lf_crc_but_no_message(transport):
    """
    Response with LF + CRC + length but no message body.

    Expected result:
    - CRC will fail (no message to validate) → 'timeout'
    """
    result = transport._parse_response(b'\x0AABCD0010\x0D')
    # Assert: truncated frame → timeout
    assert result['status'] == 'timeout'


# ===== Non-SIA protocol responses =====


def test_xml_response(transport):
    """
    CSR accidentally returns XML (misconfigured endpoint).

    Expected result:
    - Not SIA protocol → 'timeout'
    """
    result = transport._parse_response(b'<?xml version="1.0"?><error>bad</error>')
    # Assert: XML → timeout
    assert result['status'] == 'timeout'


def test_binary_protocol_response(transport):
    """
    Response from a non-SIA binary protocol on the same port.

    Expected result:
    - Random binary → 'timeout'
    """
    result = transport._parse_response(bytes(range(256)))
    # Assert: full byte range → timeout
    assert result['status'] == 'timeout'


# ===== Binary CRC format with garbled input =====


def test_garbled_with_bin_crc_format():
    """
    Garbled response parsed with binary CRC format also returns 'timeout'.

    Expected result:
    - Binary CRC format doesn't make garbage parseable
    """
    t = _TestTransport(crc_format='bin')
    result = t._parse_response(b'\xFF\xFE\xFD\xFC\xFB\xFA')
    # Assert: still timeout
    assert result['status'] == 'timeout'
    assert result['raw_nak'] is None


# ===== Oversized response =====


def test_oversized_response(transport):
    """
    10KB response (larger than any valid SIA frame).

    Expected result:
    - Handles gracefully → 'timeout'
    - No memory issues
    """
    result = transport._parse_response(b'\x0A' + b'X' * 10000 + b'\x0D')
    # Assert: oversized → timeout
    assert result['status'] == 'timeout'
