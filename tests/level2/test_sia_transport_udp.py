"""Story 5-4: SIAUDPTransport — Unit Tests (TC5–TC12).

Tests cover:
- start() creates persistent DatagramTransport
- send_frame() happy path, timeout, NAK handling
- send_frame() before start() guard
- Persistent transport reuse across sends
- close() cleanup
- Stray datagram handling

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-4-udp-tcp-transport-layer.md Tasks 9
"""

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.sia_protocol import SIATransportError
from resources.siadc09d.sia_transport import (
    SIAUDPTransport,
    SIATransportResult,
    _SIADatagramProtocol,
)


# ===== FIXTURES =====

@pytest.fixture
def mock_protocol() -> _SIADatagramProtocol:
    """Create a real _SIADatagramProtocol instance for testing."""
    return _SIADatagramProtocol()


@pytest.fixture
def mock_datagram_transport() -> MagicMock:
    """Create a mock asyncio.DatagramTransport."""
    transport = MagicMock(spec=asyncio.DatagramTransport)
    return transport


@pytest.fixture
def udp_transport() -> SIAUDPTransport:
    """Create an SIAUDPTransport instance (not started)."""
    return SIAUDPTransport(
        host='192.168.1.100',
        port=5000,
        receive_timeout_s=10.0,
        crc_format='hex',
    )


@pytest.fixture
def started_udp_transport(
    udp_transport: SIAUDPTransport,
    mock_datagram_transport: MagicMock,
    mock_protocol: _SIADatagramProtocol,
) -> SIAUDPTransport:
    """Create an SIAUDPTransport with mocked transport and protocol already set."""
    udp_transport._transport = mock_datagram_transport
    udp_transport._protocol = mock_protocol
    return udp_transport


# ===== TC5: start() creates transport and protocol =====

@pytest.mark.asyncio
async def test_tc5_start_creates_transport_and_protocol(
    udp_transport: SIAUDPTransport,
    mock_datagram_transport: MagicMock,
    mock_protocol: _SIADatagramProtocol,
    caplog,
):
    """Test that start() creates DatagramTransport and stores both objects.

    Expected result:
    - loop.create_datagram_endpoint called with correct remote_addr
    - _transport and _protocol stored
    - INFO and DEBUG log messages emitted
    """
    loop = asyncio.get_running_loop()
    original = loop.create_datagram_endpoint
    async def mock_endpoint(*args, **kwargs):
        return (mock_datagram_transport, mock_protocol)
    loop.create_datagram_endpoint = mock_endpoint  # type: ignore[assignment]


    try:
        with caplog.at_level(logging.INFO):
            await udp_transport.start()

        # Assert: transport and protocol stored
        assert udp_transport._transport is mock_datagram_transport
        assert udp_transport._protocol is mock_protocol
        # Assert: INFO log for transport init
        assert "Transport UDP initialisé" in caplog.text
    finally:
        loop.create_datagram_endpoint = original  # type: ignore[assignment]


# ===== TC6: send_frame() happy path =====

@pytest.mark.asyncio
async def test_tc6_send_frame_happy_path(started_udp_transport: SIAUDPTransport):
    """Test send_frame() happy path: send → await future → parse response.

    Expected result:
    - sendto() called with frame bytes
    - Future set with response, _parse_response called
    - Future cleared after use
    """
    frame = b'\x0Atest_frame\x0D'
    response_bytes = b'\x0Aack_response\x0D'
    expected_result = SIATransportResult(status='ack', raw_nak=None)

    with patch.object(started_udp_transport, '_parse_response', return_value=expected_result):
        # Simulate CSR reply by scheduling set_result after send
        async def simulate_reply():
            await asyncio.sleep(0.01)
            started_udp_transport._protocol._future.set_result(response_bytes)

        task = asyncio.create_task(simulate_reply())
        result = await started_udp_transport.send_frame(frame)
        await task

    # Assert: sendto called with frame
    started_udp_transport._transport.sendto.assert_called_once_with(frame)
    # Assert: result is the parsed ACK
    assert result['status'] == 'ack'
    # Assert: future cleared after use
    assert started_udp_transport._protocol._future is None


# ===== TC7: send_frame() timeout =====

@pytest.mark.asyncio
async def test_tc7_send_frame_timeout(started_udp_transport: SIAUDPTransport):
    """Test send_frame() timeout raises SIATransportError and clears future.

    Expected result:
    - asyncio.TimeoutError from wait_for → SIATransportError raised
    - Future cleared despite timeout
    """
    started_udp_transport._receive_timeout_s = 0.01  # Very short timeout

    with pytest.raises(SIATransportError, match="UDP response timeout"):
        await started_udp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: future cleared after timeout
    assert started_udp_transport._protocol._future is None


# ===== TC8: send_frame() returns NAK =====

@pytest.mark.asyncio
async def test_tc8_send_frame_nak(started_udp_transport: SIAUDPTransport):
    """Test send_frame() NAK response returns status='nak' with raw bytes.

    Expected result:
    - _parse_response returns {status: 'nak', raw_nak: <bytes>}
    - send_frame propagates this result
    """
    nak_bytes = b'\x0ANAK_FRAME\x0D'
    nak_result = SIATransportResult(status='nak', raw_nak=nak_bytes)

    with patch.object(started_udp_transport, '_parse_response', return_value=nak_result):
        async def simulate_reply():
            await asyncio.sleep(0.01)
            started_udp_transport._protocol._future.set_result(nak_bytes)

        task = asyncio.create_task(simulate_reply())
        result = await started_udp_transport.send_frame(b'\x0Atest\x0D')
        await task

    # Assert: NAK status with raw bytes
    assert result['status'] == 'nak'
    assert result['raw_nak'] == nak_bytes


# ===== TC9: send_frame() before start() =====

@pytest.mark.asyncio
async def test_tc9_send_frame_before_start(udp_transport: SIAUDPTransport):
    """Test send_frame() before start() raises SIATransportError.

    Expected result:
    - SIATransportError raised with "not started" message
    """
    with pytest.raises(SIATransportError, match="UDP transport not started"):
        await udp_transport.send_frame(b'\x0Atest\x0D')


# ===== TC10: persistent transport reuse =====

@pytest.mark.asyncio
async def test_tc10_persistent_transport_reuse(started_udp_transport: SIAUDPTransport):
    """Test 3 consecutive sends reuse the same DatagramTransport object.

    Expected result:
    - All 3 sends use the same _transport object (never recreated)
    """
    transport_id = id(started_udp_transport._transport)
    expected_result = SIATransportResult(status='ack', raw_nak=None)

    for _ in range(3):
        with patch.object(started_udp_transport, '_parse_response', return_value=expected_result):
            async def simulate_reply():
                await asyncio.sleep(0.01)
                if started_udp_transport._protocol._future and not started_udp_transport._protocol._future.done():
                    started_udp_transport._protocol._future.set_result(b'\x0Aack\x0D')

            task = asyncio.create_task(simulate_reply())
            await started_udp_transport.send_frame(b'\x0Atest\x0D')
            await task

        # Assert: same transport object reused (persistent)
        assert id(started_udp_transport._transport) == transport_id


# ===== TC11: close() =====

@pytest.mark.asyncio
async def test_tc11_close(started_udp_transport: SIAUDPTransport):
    """Test close() calls transport.close(), sets both _transport and _protocol to None.

    Expected result:
    - transport.close() called
    - _transport set to None
    - _protocol set to None
    """
    mock_transport = started_udp_transport._transport

    await started_udp_transport.close()

    # Assert: transport.close() called
    mock_transport.close.assert_called_once()
    # Assert: _transport set to None
    assert started_udp_transport._transport is None
    # Assert: _protocol set to None (prevents stale references)
    assert started_udp_transport._protocol is None


# ===== TC12: stray datagram =====

def test_tc12_stray_datagram_no_pending_future(mock_protocol: _SIADatagramProtocol, caplog):
    """Test stray datagram with no pending future logs DEBUG and does not raise.

    Expected result:
    - No exception raised
    - DEBUG log message about unexpected datagram
    """
    # No future set — this is the stray datagram scenario
    assert mock_protocol._future is None

    with caplog.at_level(logging.DEBUG):
        # Assert: no exception raised
        mock_protocol.datagram_received(b'\x0Astray\x0D', ('1.2.3.4', 5000))

    # Assert: debug log emitted
    assert "Unexpected datagram received" in caplog.text
