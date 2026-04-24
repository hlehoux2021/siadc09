"""Story 5-4: SIATransportResult and SIABaseTransport — Unit Tests (TC1–TC4).

Tests cover:
- SIATransportResult TypedDict structure
- _parse_response() mapping from decode_ack_nak result to SIATransportResult

Test level: Level 2 (async, no Jeedom required)
Framework: pytest
Reference: story 5-4-udp-tcp-transport-layer.md Tasks 8
"""

import pytest
from unittest.mock import patch

from resources.siadc09d.sia_transport import (
    SIABaseTransport,
    SIATransportResult,
)


# ===== FIXTURES =====

class _ConcreteTransport(SIABaseTransport):
    """Minimal concrete subclass for testing _parse_response() in isolation.

    SIABaseTransport is abstract (ABC) and cannot be instantiated directly.
    This subclass provides stub implementations of the abstract methods.
    start() is inherited from SIABaseTransport — no-op, no override needed.
    """

    async def send_frame(self, frame: bytes) -> SIATransportResult:
        raise NotImplementedError

    async def close(self) -> None:
        pass


@pytest.fixture
def transport() -> _ConcreteTransport:
    """Create a concrete transport instance with hex CRC format."""
    return _ConcreteTransport(crc_format='hex')


# ===== TC1: SIATransportResult structure =====

def test_tc1_transport_result_has_correct_keys_and_types():
    """Test that SIATransportResult TypedDict has the expected keys.

    Expected result:
    - SIATransportResult has 'status' and 'raw_nak' keys
    - Can be constructed with valid Literal values
    """
    # Assert: construct with valid values — no TypeError
    result = SIATransportResult(status='ack', raw_nak=None)
    assert result['status'] == 'ack'
    assert result['raw_nak'] is None

    # Assert: construct with NAK status and raw bytes
    nak_result = SIATransportResult(status='nak', raw_nak=b'\x0Atest\x0D')
    assert nak_result['status'] == 'nak'
    assert nak_result['raw_nak'] == b'\x0Atest\x0D'

    # Assert: construct with all status values
    for status in ('ack', 'nak', 'timeout', 'tcp_drop'):
        r = SIATransportResult(status=status, raw_nak=None)  # type: ignore[arg-type]
        assert r['status'] == status


# ===== TC2–TC4: _parse_response() mapping =====

def test_tc2_parse_response_ack(transport: _ConcreteTransport):
    """Test that _parse_response maps ACK to status='ack' with raw_nak=None.

    Expected result:
    - decode_ack_nak returns type='ACK'
    - _parse_response maps to SIATransportResult(status='ack', raw_nak=None)
    """
    with patch(
        'resources.siadc09d.sia_transport.sia_protocol.decode_ack_nak',
        return_value={'type': 'ACK', 'seq': 1, 'raw_nak': None},
    ):
        result = transport._parse_response(b'any_bytes')

    # Assert: ACK maps to 'ack' status
    assert result['status'] == 'ack'
    # Assert: raw_nak is None for ACK
    assert result['raw_nak'] is None


def test_tc3_parse_response_nak(transport: _ConcreteTransport):
    """Test that _parse_response maps NAK to status='nak' with raw_nak bytes.

    Expected result:
    - decode_ack_nak returns type='NAK' with raw_nak bytes
    - _parse_response maps to SIATransportResult(status='nak', raw_nak=<bytes>)
    """
    nak_bytes = b'\x0ANAK_FRAME\x0D'
    with patch(
        'resources.siadc09d.sia_transport.sia_protocol.decode_ack_nak',
        return_value={'type': 'NAK', 'seq': None, 'raw_nak': nak_bytes},
    ):
        result = transport._parse_response(b'any_bytes')

    # Assert: NAK maps to 'nak' status
    assert result['status'] == 'nak'
    # Assert: raw_nak contains the full raw NAK frame bytes
    assert result['raw_nak'] == nak_bytes


def test_tc4_parse_response_unknown(transport: _ConcreteTransport):
    """Test that _parse_response maps unknown to status='timeout' with raw_nak=None.

    Expected result:
    - decode_ack_nak returns type='unknown' (unparseable response)
    - _parse_response maps to SIATransportResult(status='timeout', raw_nak=None)
    """
    with patch(
        'resources.siadc09d.sia_transport.sia_protocol.decode_ack_nak',
        return_value={'type': 'unknown', 'seq': None, 'raw_nak': None},
    ):
        result = transport._parse_response(b'any_bytes')

    # Assert: unknown maps to 'timeout' status (treated as no valid response)
    assert result['status'] == 'timeout'
    # Assert: raw_nak is None for unknown
    assert result['raw_nak'] is None


def test_tc2_parse_response_passes_crc_format(transport: _ConcreteTransport):
    """Test that _parse_response passes crc_format to decode_ack_nak.

    Expected result:
    - decode_ack_nak is called with crc_format='hex' (from transport constructor)
    """
    with patch(
        'resources.siadc09d.sia_transport.sia_protocol.decode_ack_nak',
        return_value={'type': 'ACK', 'seq': 1, 'raw_nak': None},
    ) as mock_decode:
        transport._parse_response(b'test_frame')

    # Assert: crc_format kwarg passed through from SIABaseTransport._crc_format
    mock_decode.assert_called_once_with(b'test_frame', crc_format='hex')
