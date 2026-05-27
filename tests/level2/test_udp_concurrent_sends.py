"""
UDP transport concurrent/reentrancy tests (QA Round 2).

Tests that SIAUDPTransport's shared _future field handles overlapping sends
safely. The design is single-consumer (queue_consumer sends one at a time),
but these tests verify the guard and document the expected behavior if
concurrent sends ever occur.

Reference: resources/siadc09d/sia_transport.py::SIAUDPTransport
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.sia_transport import (
    SIAUDPTransport,
    SIATransportResult,
    _SIADatagramProtocol,
)


@pytest.fixture
def started_transport() -> SIAUDPTransport:
    """UDP transport with mocked DatagramTransport and protocol."""
    transport = SIAUDPTransport(
        host='192.168.1.100',
        port=5000,
        receive_timeout_s=1.0,
        crc_format='hex',
    )
    mock_dt = MagicMock(spec=asyncio.DatagramTransport)
    protocol = _SIADatagramProtocol()
    transport._transport = mock_dt
    transport._protocol = protocol
    return transport


# ===== Sequential rapid-fire sends =====


@pytest.mark.asyncio
async def test_rapid_sequential_sends(started_transport):
    """
    3 sequential sends complete correctly — future cleared between each.

    Expected result:
    - Each send gets its own future
    - Each future resolves independently
    - All 3 return ACK
    """
    results = []
    expected = SIATransportResult(status='ack', raw_nak=None)

    for i in range(3):
        with patch.object(started_transport, '_parse_response', return_value=expected):
            async def reply():
                await asyncio.sleep(0.01)
                if started_transport._protocol._future and not started_transport._protocol._future.done():
                    started_transport._protocol._future.set_result(b'\x0Aack\x0D')
            task = asyncio.create_task(reply())
            result = await started_transport.send_frame(f'frame_{i}'.encode())
            await task
            results.append(result)

    # Assert: all 3 sends completed with ACK
    assert len(results) == 3
    assert all(r['status'] == 'ack' for r in results)
    # Assert: future cleared after each send
    assert started_transport._protocol._future is None


# ===== Future overwrite detection =====


@pytest.mark.asyncio
async def test_second_send_overwrites_first_future(started_transport):
    """
    If two sends overlap, the second send overwrites the first's future.

    This documents the current behavior (not a bug — the queue consumer
    guarantees single-send-at-a-time). The test proves the overwrite happens
    so we know to never remove the queue consumer gate.

    Expected result:
    - First send's future is replaced by second send's future
    - First send raises SIATransportError (timeout, future never resolved)
    - Second send completes normally if its future is resolved
    """
    from resources.siadc09d.sia_protocol import SIATransportError

    started_transport._receive_timeout_s = 0.1
    expected = SIATransportResult(status='ack', raw_nak=None)

    async def first_send():
        with patch.object(started_transport, '_parse_response', return_value=expected):
            return await started_transport.send_frame(b'frame_1')

    async def second_send():
        await asyncio.sleep(0.02)
        with patch.object(started_transport, '_parse_response', return_value=expected):
            async def reply():
                await asyncio.sleep(0.01)
                if started_transport._protocol._future and not started_transport._protocol._future.done():
                    started_transport._protocol._future.set_result(b'\x0Aack\x0D')
            task = asyncio.create_task(reply())
            result = await started_transport.send_frame(b'frame_2')
            await task
            return result

    first_task = asyncio.create_task(first_send())
    second_task = asyncio.create_task(second_send())

    results = await asyncio.gather(first_task, second_task, return_exceptions=True)

    # Assert: first send failed (its future was overwritten, never resolved → timeout)
    assert isinstance(results[0], SIATransportError), (
        f"First send should timeout (future overwritten), got: {results[0]}"
    )
    # Assert: second send succeeded
    assert isinstance(results[1], dict) and results[1]['status'] == 'ack', (
        f"Second send should succeed, got: {results[1]}"
    )


# ===== Protocol error_received during send =====


@pytest.mark.asyncio
async def test_error_received_during_send(started_transport):
    """
    Protocol error_received() propagates to the pending future.

    Expected result:
    - send_frame() raises SIATransportError wrapping the OS error
    """
    from resources.siadc09d.sia_protocol import SIATransportError

    async def trigger_error():
        await asyncio.sleep(0.01)
        if started_transport._protocol._future and not started_transport._protocol._future.done():
            started_transport._protocol._future.set_exception(
                OSError("ICMP port unreachable")
            )

    task = asyncio.create_task(trigger_error())

    with pytest.raises(SIATransportError):
        await started_transport.send_frame(b'\x0Atest\x0D')

    await task


# ===== Connection lost during send =====


@pytest.mark.asyncio
async def test_connection_lost_during_send(started_transport):
    """
    Protocol connection_lost() during pending send propagates SIATransportError.

    Expected result:
    - send_frame() raises SIATransportError("UDP connection lost")
    """
    from resources.siadc09d.sia_protocol import SIATransportError

    async def trigger_disconnect():
        await asyncio.sleep(0.01)
        started_transport._protocol.connection_lost(ConnectionResetError("closed"))

    task = asyncio.create_task(trigger_disconnect())

    with pytest.raises(SIATransportError, match="UDP connection lost"):
        await started_transport.send_frame(b'\x0Atest\x0D')

    await task
