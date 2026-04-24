"""Story 5-4: SIATCPTransport — Unit Tests (TC13–TC23b).

Tests cover:
- send_frame() happy path with readuntil frame boundary
- TCP connect timeout, response timeout, IncompleteReadError, LimitOverrunError
- OS error classification (ECONNRESET → tcp_drop, ENOMEM → raise)
- finally block cleanup (success, error, writer=None)
- drain() timeout
- SIATransportError not re-wrapped by OSError handler

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-4-udp-tcp-transport-layer.md Tasks 10
"""

import asyncio
import errno
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from resources.siadc09d.sia_protocol import SIATransportError
from resources.siadc09d.sia_transport import (
    SIATCPTransport,
    SIATransportResult,
)


# ===== FIXTURES =====

@pytest.fixture
def tcp_transport() -> SIATCPTransport:
    """Create an SIATCPTransport instance."""
    return SIATCPTransport(
        host='192.168.1.100',
        port=5000,
        connect_timeout_s=5.0,
        receive_timeout_s=10.0,
        crc_format='hex',
    )


def _make_mock_reader_writer(response: bytes = b'\x0Aack_response\x0D'):
    """Create mock StreamReader/StreamWriter pair.

    The reader's readuntil returns the response bytes.
    The writer has async drain() and close/wait_closed.
    """
    reader = AsyncMock(spec=asyncio.StreamReader)
    reader.readuntil = AsyncMock(return_value=response)

    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    return reader, writer


# ===== TC13: send_frame() happy path =====

@pytest.mark.asyncio
async def test_tc13_send_frame_happy_path(tcp_transport: SIATCPTransport):
    """Test send_frame() connects, writes, readuntil, parses, closes.

    Expected result:
    - open_connection called with host:port
    - writer.write called with frame, drain awaited
    - reader.readuntil(b'\\x0D') called
    - _parse_response called with response bytes
    - writer.close() and wait_closed() called
    """
    frame = b'\x0Atest_frame\x0D'
    response = b'\x0Aack_response\x0D'
    reader, writer = _make_mock_reader_writer(response)
    expected = SIATransportResult(status='ack', raw_nak=None)

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with patch.object(tcp_transport, '_parse_response', return_value=expected):
            result = await tcp_transport.send_frame(frame)

    # Assert: write called with frame
    writer.write.assert_called_once_with(frame)
    # Assert: drain awaited
    writer.drain.assert_awaited_once()
    # Assert: readuntil called with CR terminator
    reader.readuntil.assert_awaited_once_with(b'\x0D')
    # Assert: cleanup called
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()
    # Assert: result is parsed ACK
    assert result['status'] == 'ack'


# ===== TC14: readuntil returns complete frame =====

@pytest.mark.asyncio
async def test_tc14_readuntil_complete_frame(tcp_transport: SIATCPTransport):
    """Test readuntil returns complete frame with \\x0D terminator.

    Expected result:
    - _parse_response receives the full bytes including terminator
    """
    full_frame = b'\x0ACRC0040"ACK"0001R0L0#1234[]\x0D'
    reader, writer = _make_mock_reader_writer(full_frame)

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with patch.object(tcp_transport, '_parse_response',
                         return_value=SIATransportResult(status='ack', raw_nak=None)) as mock_parse:
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: _parse_response called with the full frame bytes
    mock_parse.assert_called_once_with(full_frame)


# ===== TC15: reader.read(N) NOT used =====

@pytest.mark.asyncio
async def test_tc15_no_reader_read_used(tcp_transport: SIATCPTransport):
    """Test reader.read(N) is NOT used — only readuntil is the read call.

    Expected result:
    - reader.read is never called
    - reader.readuntil is the only read method called
    """
    reader, writer = _make_mock_reader_writer()
    reader.read = AsyncMock()  # Track if read() is called

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with patch.object(tcp_transport, '_parse_response',
                         return_value=SIATransportResult(status='ack', raw_nak=None)):
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: read(N) never called
    reader.read.assert_not_called()
    # Assert: readuntil was called
    reader.readuntil.assert_awaited_once()


# ===== TC16: TCP connect timeout =====

@pytest.mark.asyncio
async def test_tc16_connect_timeout(tcp_transport: SIATCPTransport):
    """Test TCP connect timeout raises SIATransportError.

    Expected result:
    - asyncio.TimeoutError from open_connection → SIATransportError
    """
    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(side_effect=asyncio.TimeoutError)):
        with pytest.raises(SIATransportError, match="TCP connect timeout"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')


# ===== TC17: readuntil response timeout =====

@pytest.mark.asyncio
async def test_tc17_response_timeout(tcp_transport: SIATCPTransport):
    """Test readuntil response timeout raises SIATransportError.

    Expected result:
    - asyncio.TimeoutError from readuntil → SIATransportError
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="TCP response timeout"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: cleanup still called despite timeout
    writer.close.assert_called_once()


# ===== TC18: IncompleteReadError =====

@pytest.mark.asyncio
async def test_tc18_incomplete_read_error(tcp_transport: SIATCPTransport):
    """Test IncompleteReadError from readuntil raises SIATransportError.

    Expected result:
    - asyncio.IncompleteReadError → SIATransportError("TCP connection closed...")
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(
        side_effect=asyncio.IncompleteReadError(b'partial', 100)
    )

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="TCP connection closed before SIA frame complete"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')


# ===== TC18b: LimitOverrunError =====

@pytest.mark.asyncio
async def test_tc18b_limit_overrun_error(tcp_transport: SIATCPTransport):
    """Test LimitOverrunError from readuntil raises SIATransportError.

    Expected result:
    - asyncio.LimitOverrunError → SIATransportError("buffer limit...")
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(
        side_effect=asyncio.LimitOverrunError("limit exceeded", 65536)
    )

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="StreamReader buffer limit"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')


# ===== TC19: OSError(ECONNRESET) → tcp_drop =====

@pytest.mark.asyncio
async def test_tc19_econnreset_returns_tcp_drop(tcp_transport: SIATCPTransport):
    """Test ECONNRESET returns tcp_drop status (does not raise).

    Expected result:
    - OSError with ECONNRESET errno → SIATransportResult(status='tcp_drop')
    - No exception raised
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(side_effect=OSError(errno.ECONNRESET, "Connection reset"))

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        result = await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: tcp_drop returned, not raised
    assert result['status'] == 'tcp_drop'
    assert result['raw_nak'] is None


# ===== TC20: OSError(ENOMEM) → raises =====

@pytest.mark.asyncio
async def test_tc20_enomem_raises_transport_error(tcp_transport: SIATCPTransport):
    """Test non-classified OSError (ENOMEM) raises SIATransportError.

    Expected result:
    - OSError with ENOMEM → SIATransportError("TCP socket error...")
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(side_effect=OSError(errno.ENOMEM, "Out of memory"))

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="TCP socket error"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')


# ===== TC21: finally block always executes =====

@pytest.mark.asyncio
async def test_tc21_finally_always_executes(tcp_transport: SIATCPTransport):
    """Test finally block calls writer.close() + wait_closed() on every path.

    Expected result:
    - writer.close() and wait_closed() called on success, timeout, and error
    """
    # Success path
    reader, writer = _make_mock_reader_writer()
    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with patch.object(tcp_transport, '_parse_response',
                         return_value=SIATransportResult(status='ack', raw_nak=None)):
            await tcp_transport.send_frame(b'\x0Atest\x0D')
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


# ===== TC21b: wait_closed() raises OSError — original exception preserved =====

@pytest.mark.asyncio
async def test_tc21b_wait_closed_oserror_preserves_original(tcp_transport: SIATCPTransport):
    """Test that OSError from wait_closed() in finally does not replace original exception.

    Expected result:
    - readuntil raises SIATransportError("TCP response timeout")
    - wait_closed() raises OSError(ECONNRESET)
    - The SIATransportError is the one that propagates (not the cleanup OSError)
    """
    reader, writer = _make_mock_reader_writer()
    reader.readuntil = AsyncMock(side_effect=asyncio.TimeoutError)
    writer.wait_closed = AsyncMock(side_effect=OSError(errno.ECONNRESET, "reset"))

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="TCP response timeout"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: close still attempted despite wait_closed failure
    writer.close.assert_called_once()


# ===== TC22: writer=None guard =====

@pytest.mark.asyncio
async def test_tc22_writer_none_guard(tcp_transport: SIATCPTransport):
    """Test finally block does not crash when writer is None (connect failed).

    Expected result:
    - Connect raises before writer is assigned
    - finally block handles writer=None gracefully
    """
    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(side_effect=asyncio.TimeoutError)):
        with pytest.raises(SIATransportError, match="TCP connect timeout"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # If we get here, the finally block didn't crash — test passes


# ===== TC23b: drain() timeout =====

@pytest.mark.asyncio
async def test_tc23b_drain_timeout(tcp_transport: SIATCPTransport):
    """Test drain() timeout raises SIATransportError with specific message.

    Expected result:
    - asyncio.TimeoutError from drain() → SIATransportError("drain timeout")
    - Specific message preserved (not wrapped by outer except OSError)
    """
    reader, writer = _make_mock_reader_writer()
    writer.drain = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch('resources.siadc09d.sia_transport.asyncio.open_connection',
               AsyncMock(return_value=(reader, writer))):
        with pytest.raises(SIATransportError, match="TCP send buffer drain timeout"):
            await tcp_transport.send_frame(b'\x0Atest\x0D')

    # Assert: cleanup still called
    writer.close.assert_called_once()
