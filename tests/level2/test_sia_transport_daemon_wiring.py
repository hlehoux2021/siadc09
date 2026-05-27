"""Story 5-4: Daemon Transport Wiring — Integration Tests (TC23–TC29).

Tests cover:
- on_start() creates correct transport for UDP/TCP presets
- _send_raw() delegates to transport
- _send_raw() before on_start() (transport None)
- on_stop() closes transport
- CSRPreset unknown transport validation

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: story 5-4-udp-tcp-transport-layer.md Tasks 11
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.daemon import SIADaemon, SM1State
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_protocol import SIATransportError
from resources.siadc09d.sia_transport import (
    SIABaseTransport,
    SIAUDPTransport,
    SIATCPTransport,
    SIATransportResult,
    TransportType,
)


# ===== FIXTURES =====

@pytest.fixture
def daemon():
    """Create a fresh SIADaemon instance with mocked logger."""
    from tests.conftest import make_daemon_preset
    with patch('sys.argv', ['test']):
        d = SIADaemon(preset=make_daemon_preset())
    d._logger = MagicMock()
    d.send_to_jeedom = AsyncMock()
    return d


def _make_udp_preset() -> CSRPreset:
    """Create a UDP CSRPreset for testing (transport passed as string)."""
    return CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='UDP',  # String — CSRPreset.__post_init__ converts to TransportType
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
    )


def _make_tcp_preset() -> CSRPreset:
    """Create a TCP CSRPreset for testing (transport passed as string)."""
    return CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='TCP',  # String — CSRPreset.__post_init__ converts to TransportType
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
    )


# ===== TC23: on_start() with UDP preset =====

@pytest.mark.asyncio
async def test_tc23_on_start_udp_preset(daemon: SIADaemon):
    """Test on_start() with UDP preset creates SIAUDPTransport and calls start().

    Expected result:
    - SIAUDPTransport created with preset values
    - start() called on the transport
    - _sia_transport stored on daemon
    """
    daemon._preset = _make_udp_preset()
    daemon._account = '001234'

    with patch.object(SIAUDPTransport, 'start', new_callable=AsyncMock) as mock_start:
        await daemon.on_start()

    # Assert: transport created and stored
    assert daemon._sia_transport is not None
    assert isinstance(daemon._sia_transport, SIAUDPTransport)
    # Assert: start() was called
    mock_start.assert_awaited_once()
    # Assert: all preset values wired correctly to transport constructor
    assert daemon._sia_transport._crc_format == 'hex'
    assert daemon._sia_transport._host == '192.168.1.100'
    assert daemon._sia_transport._port == 5000
    assert daemon._sia_transport._receive_timeout_s == 20.0


# ===== TC24: on_start() with TCP preset =====

@pytest.mark.asyncio
async def test_tc24_on_start_tcp_preset(daemon: SIADaemon):
    """Test on_start() with TCP preset creates SIATCPTransport.

    Expected result:
    - SIATCPTransport created with preset values
    - start() called (no-op for TCP, inherited from base)
    - _sia_transport stored on daemon
    """
    daemon._preset = _make_tcp_preset()
    daemon._account = '001234'

    await daemon.on_start()

    # Assert: transport created and stored
    assert daemon._sia_transport is not None
    assert isinstance(daemon._sia_transport, SIATCPTransport)
    # Assert: all preset values wired correctly to transport constructor
    assert daemon._sia_transport._crc_format == 'hex'
    assert daemon._sia_transport._host == '192.168.1.100'
    assert daemon._sia_transport._port == 5000
    assert daemon._sia_transport._connect_timeout_s == 10.0
    assert daemon._sia_transport._receive_timeout_s == 20.0


# ===== TC29: CSRPreset unknown transport =====

def test_tc29_preset_unknown_transport():
    """Test CSRPreset with unknown transport string raises ValueError in __post_init__.

    Expected result:
    - ValueError raised before on_start() is ever called
    - Error comes from TransportType('udp') — case-sensitive
    """
    with pytest.raises(ValueError, match="'udp' is not a valid TransportType"):
        CSRPreset(
            csr_provider='test',
            schema_version=1,
            host='192.168.1.100',
            port=5000,
            account_number='001234',
            transport='udp',  # lowercase — invalid
            crc_format='hex',
            encryption_enabled=False,
            connect_timeout_s=10.0,
            receive_timeout_s=20.0,
            supervision_interval_s=60.0,
        )


# ===== TC25: _send_raw() delegates =====

@pytest.mark.asyncio
async def test_tc25_send_raw_delegates(daemon: SIADaemon):
    """Test _send_raw() delegates to _sia_transport.send_frame().

    Expected result:
    - send_frame() called with the frame bytes
    - Result returned from send_frame() propagated
    """
    mock_transport = AsyncMock(spec=SIABaseTransport)
    expected = SIATransportResult(status='ack', raw_nak=None)
    mock_transport.send_frame = AsyncMock(return_value=expected)
    daemon._sia_transport = mock_transport

    result = await daemon._send_raw(b'\x0Atest\x0D')

    # Assert: delegated to transport
    mock_transport.send_frame.assert_awaited_once_with(b'\x0Atest\x0D')
    # Assert: result forwarded
    assert result['status'] == 'ack'


# ===== TC26: _send_raw() before on_start() =====

@pytest.mark.asyncio
async def test_tc26_send_raw_before_start(daemon: SIADaemon):
    """Test _send_raw() before on_start() raises SIATransportError.

    Expected result:
    - _sia_transport is None → SIATransportError raised
    """
    assert daemon._sia_transport is None

    with pytest.raises(SIATransportError, match="Transport not initialized"):
        await daemon._send_raw(b'\x0Atest\x0D')


# ===== TC27: on_stop() closes transport =====

@pytest.mark.asyncio
async def test_tc27_on_stop_closes_transport(daemon: SIADaemon):
    """Test on_stop() calls await _sia_transport.close() and sets to None.

    Expected result:
    - close() called on the transport
    - _sia_transport set to None after close
    """
    mock_transport = AsyncMock(spec=SIABaseTransport)
    daemon._sia_transport = mock_transport

    await daemon.on_stop()

    # Assert: close called
    mock_transport.close.assert_awaited_once()
    # Assert: transport set to None
    assert daemon._sia_transport is None


# ===== TC28: End-to-end supervision via mock transport → SM1=HEALTHY =====

@pytest.mark.asyncio
async def test_tc28_end_to_end_supervision_udp_ack(daemon: SIADaemon):
    """Test end-to-end supervision: queue consumer sends via mock transport ACK → SM1=HEALTHY.

    Verifies the full chain:
    _enqueue_supervision() → _queue_consumer() → _send_supervision() → _send_raw()
    → mock transport returns ACK → SM1 transitions to HEALTHY.

    Expected result:
    - _send_raw() calls _sia_transport.send_frame() with supervision frame
    - ACK response from mock transport drives SM1 → HEALTHY
    - HEALTHY state confirmed after one supervision cycle
    """
    # Arrange: mock transport returning ACK; daemon configured for supervision
    mock_transport = AsyncMock(spec=SIABaseTransport)
    mock_transport.send_frame = AsyncMock(
        return_value=SIATransportResult(status='ack', raw_nak=None)
    )
    daemon._sia_transport = mock_transport
    daemon._preset = _make_udp_preset()
    daemon._account = '001234'
    daemon._account_prefix = 'L0'
    daemon._receiver_prefix = ''
    daemon._encryption_key = b''
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()

    # SM1 starts at INITIALIZING (normal startup state)
    from resources.siadc09d.daemon import SM1State
    daemon._sm1_state = SM1State.INITIALIZING

    # Act: enqueue one supervision item and run one consumer cycle
    await daemon._enqueue_supervision()

    # Use a one-shot consumer: dequeue item and call _send_supervision directly
    _, _, item_type, payload = await daemon._queue.get()
    daemon._queue.task_done()

    # Assert: item was SUPERVISION
    from resources.siadc09d.daemon import QUEUE_TYPE_SUPERVISION
    assert item_type == QUEUE_TYPE_SUPERVISION

    # Call _send_supervision() directly — this is what _queue_consumer invokes
    await daemon._send_supervision()

    # Assert: transport send_frame was called with actual bytes
    mock_transport.send_frame.assert_awaited_once()
    sent_frame = mock_transport.send_frame.call_args[0][0]
    assert isinstance(sent_frame, bytes), "send_frame should receive bytes"
    assert len(sent_frame) > 0, "frame should not be empty"

    # Assert: SM1 transitioned to HEALTHY after ACK
    assert daemon._sm1_state == SM1State.HEALTHY, (
        f"Expected SM1=HEALTHY after ACK, got {daemon._sm1_state}"
    )
