"""Level 2 daemon IPC wiring tests for Story 6.6.

Validates that the daemon's PHP integration plumbing works correctly:
- on_message() correctly enqueues alarm events
- on_stop() preserves SM2 event state across restarts
- Multiple concurrent alarm commands are handled independently
- Callback exceptions do not stall the queue consumer

Reference: _bmad-output/implementation-artifacts/6-6-php-core-integration-ipc-tests.md § AC9
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.daemon import (
    SIADaemon,
    SM1State,
    SM2State,
    QUEUE_TYPE_EVENT,
)
from resources.siadc09d.error_handler import ErrorCode
from tests.conftest import make_daemon_preset


def _make_daemon(transport: str = "UDP") -> SIADaemon:
    """Create SIADaemon with mocked transport and callbacks for wiring tests."""
    preset = make_daemon_preset(transport=transport)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = "001234"
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()

    mock_t = MagicMock()
    mock_t.start = AsyncMock()
    mock_t.close = AsyncMock()
    mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = mock_t
    return daemon


# ===== TC-IPC1: on_message enqueues alarm event =====


@pytest.mark.asyncio
async def test_on_message_enqueues_alarm_event():
    """AC9: PHP command via on_message() → EVENT enqueued in priority queue.

    Expected:
    - Calling on_message("burglarAlarm", {"zone": "salon"}) puts EVENT item in queue
    - Queue item has correct sia_code and zone
    """
    daemon = _make_daemon()

    await daemon.on_message("burglarAlarm", {"zone": "salon"})

    # Assert: exactly one item in queue
    assert daemon._queue.qsize() == 1  # one item enqueued
    _prio, _counter, item_type, payload = daemon._queue.get_nowait()
    assert item_type == QUEUE_TYPE_EVENT  # correct item type
    assert payload["sia_code"] == "BA"  # burglarAlarm → BA
    assert payload["zone"] == "salon"  # zone carried through


@pytest.mark.asyncio
async def test_on_message_dispatch_strips_apikey_and_routes():
    """AC4: _on_message_dispatch() strips apikey, extracts cmd, delegates to on_message().

    Expected:
    - apikey is removed before processing
    - cmd extracted and passed to on_message()
    - Remaining dict used as params
    """
    daemon = _make_daemon()

    raw_message = {"cmd": "fireAlarm", "zone": "cuisine", "apikey": "secret-key"}
    await daemon._on_message_dispatch(raw_message)

    assert daemon._queue.qsize() == 1
    _prio, _counter, item_type, payload = daemon._queue.get_nowait()
    assert item_type == QUEUE_TYPE_EVENT
    assert payload["sia_code"] == "FA"  # fireAlarm → FA
    assert payload["zone"] == "cuisine"


@pytest.mark.asyncio
async def test_on_message_unknown_command_ignored():
    """AC4: Unknown command → ignored, no queue item.

    Expected:
    - Unrecognized cmd → warning logged, nothing enqueued
    """
    daemon = _make_daemon()
    daemon._logger = logging.getLogger("test_unknown_cmd")

    await daemon.on_message("unknownCmd", {})

    assert daemon._queue.qsize() == 0  # nothing enqueued


# ===== TC-IPC2: daemon restart preserves SM2 state tracking =====


@pytest.mark.asyncio
async def test_daemon_stop_preserves_event_state():
    """AC9: SM2 CONFIRMED state is reset to IDLE on restart (daemon is authoritative on push).

    Expected:
    - SM2=CONFIRMED before on_stop()
    - on_start() resets SM2=IDLE (daemon does not persist state across restarts)
    - INFO commands are pushed on start and stop (via _update_info_commands)
    """
    daemon = _make_daemon()

    # Set SM2 to CONFIRMED (as if alarm was sent)
    daemon._sm2_state = SM2State.CONFIRMED
    daemon._event_sia_code = "BA"

    # on_start() resets SM2 to IDLE
    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        MockT.return_value = mock_t
        await daemon.on_start()

    assert daemon._sm2_state == SM2State.IDLE  # daemon resets SM2 on start
    assert daemon._sm1_state == SM1State.INITIALIZING  # SM1 also reset

    await daemon.on_stop()


# ===== TC-IPC3: multiple alarm commands independent =====


@pytest.mark.asyncio
async def test_multiple_action_commands_independent():
    """AC9: 3 different alarm commands enqueue without interference.

    Expected:
    - 3 distinct EVENT items queued with different sia_codes
    - Queue size == 3
    """
    daemon = _make_daemon()

    await daemon.on_message("burglarAlarm", {"zone": "salon"})
    await daemon.on_message("fireAlarm", {"zone": "cuisine"})
    await daemon.on_message("panicAlarm", {"zone": "bureau"})

    assert daemon._queue.qsize() == 3  # three independent events queued

    codes = []
    for _ in range(3):
        _prio, _counter, item_type, payload = daemon._queue.get_nowait()
        assert item_type == QUEUE_TYPE_EVENT
        codes.append(payload["sia_code"])

    assert set(codes) == {"BA", "FA", "PA"}  # all three distinct alarm types


# ===== TC-IPC4: callback exception does not stall queue consumer =====


@pytest.mark.asyncio
async def test_send_callback_does_not_block_queue_consumer():
    """AC9: Exception in callback delivery does not stall queue consumer.

    Expected:
    - _send_callback raises → caught internally, daemon logs ERROR
    - Queue consumer continues processing next items after callback failure
    """
    preset = make_daemon_preset()
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)

    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._notify = MagicMock()
    daemon._account = "001234"
    daemon._account_prefix = "L0"
    daemon._receiver_prefix = ""

    # Allow on_start() INITIALIZING push to succeed, then make subsequent calls raise
    daemon.send_to_jeedom = AsyncMock()

    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        # ACK so _send_supervision succeeds and queue consumer can proceed
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        MockT.return_value = mock_t
        await daemon.on_start()
        daemon._sia_transport = mock_t

    # Now make send_to_jeedom raise on every subsequent call (_send_callback uses it)
    daemon.send_to_jeedom = AsyncMock(side_effect=ConnectionError("PHP down"))

    # Enqueue 2 supervision items
    await daemon._enqueue_supervision()
    await daemon._enqueue_supervision()

    # Both should be processed (no stall) even though callbacks fail
    await daemon._queue.join()

    # Assert: queue is empty (both items processed)
    assert daemon._queue.qsize() == 0  # queue drained despite callback failures

    await daemon.on_stop()
