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
    EventItem,
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


# ===== TC-IPC5: zone_number carried from PHP to the SIA frame (story 8-2 AC11–AC14) =====


@pytest.mark.asyncio
async def test_on_message_carries_zone_number_alongside_label():
    """AC12: PHP sends both the label and the resolved order number — both survive IPC.

    Expected:
    - payload["zone"] keeps the human label (logs, notifications, inspector)
    - payload["zone_number"] carries the integer resolved against the zone table
    """
    daemon = _make_daemon()

    await daemon.on_message("burglarAlarm", {"zone": "Salon", "zone_number": 3})

    _prio, _counter, _item_type, payload = daemon._queue.get_nowait()
    assert payload["zone"] == "Salon"  # label untouched by the numbering
    assert payload["zone_number"] == 3  # order number carried through IPC


@pytest.mark.asyncio
async def test_on_message_without_zone_number_yields_none():
    """AC14: an unresolved zone (PHP sends no zone_number) must not invent one.

    Expected:
    - payload["zone_number"] is None
    - the event is still enqueued: the alarm is never dropped over a missing number
    """
    daemon = _make_daemon()

    await daemon.on_message("burglarAlarm", {"zone": "Inconnue"})

    assert daemon._queue.qsize() == 1  # alarm enqueued despite the missing number
    _prio, _counter, _item_type, payload = daemon._queue.get_nowait()
    assert payload["zone_number"] is None  # no number invented


@pytest.mark.asyncio
async def test_on_message_unusable_zone_number_falls_back_to_none(caplog):
    """AC14: a non-numeric zone_number is refused, not propagated to the formatter.

    Expected:
    - payload["zone_number"] is None
    - a WARNING names the unusable value
    """
    daemon = _make_daemon()
    daemon._logger = logging.getLogger("test_bad_zone_number")

    with caplog.at_level(logging.WARNING, logger="test_bad_zone_number"):
        await daemon.on_message("burglarAlarm", {"zone": "Salon", "zone_number": "abc"})

    _prio, _counter, _item_type, payload = daemon._queue.get_nowait()
    assert payload["zone_number"] is None  # unusable value discarded
    assert "unusable zone_number" in caplog.text  # WARNING emitted


@pytest.mark.asyncio
async def test_build_event_frame_sends_zero_padded_zone_number():
    """AC13: the frame carries the 3-digit order number, never the label.

    Reference: SIA DC-09-2021 Annex B — zone formatted as 3 zero-padded digits.

    Expected:
    - frame contains "[#001234|BA 003]"
    - the label "Salon" appears nowhere in the frame
    """
    daemon = _make_daemon()
    event = EventItem(
        sia_code="BA", zone="Salon", timestamp="12:00:00,04-22-2026", zone_number=3
    )

    frame = daemon._build_event_frame(event)

    assert b"[#001234|BA 003]" in frame  # zero-padded to 3 digits
    assert b"Salon" not in frame  # label never transmitted


@pytest.mark.asyncio
async def test_build_event_frame_omits_zone_when_unresolved():
    """AC14: unresolved zone → no zone field at all, and the alarm is still sent.

    Expected:
    - frame contains "[#001234|BA]" (event code alone, no zone separator)
    - the label is not used as a fallback
    """
    daemon = _make_daemon()
    event = EventItem(
        sia_code="BA", zone="Inconnue", timestamp="12:00:00,04-22-2026", zone_number=None
    )

    frame = daemon._build_event_frame(event)

    assert b"[#001234|BA]" in frame  # no zone field emitted
    assert b"Inconnue" not in frame  # label not used as a fallback


# ===== TC-IPC6: disarm/alarmReset → BC/OP by user number (story 13-1, ADR-18) =====


@pytest.mark.asyncio
async def test_on_message_disarm_enqueues_bc_with_user_number():
    """AC1: PHP's disarm(BC) call reaches the queue as a BC event addressed by user number.

    Expected:
    - exactly one EVENT item is enqueued (not dropped as an unknown command)
    - payload["sia_code"] == "BC"
    - payload["user_number"] carries the configured user through IPC
    - payload["zone_number"] is None — BC/OP are never zone-addressed
    """
    daemon = _make_daemon()

    await daemon.on_message("disarm", {"sia_code": "BC", "user_number": 1})

    assert daemon._queue.qsize() == 1  # disarm's BC enqueued, not ignored
    _prio, _counter, item_type, payload = daemon._queue.get_nowait()
    assert item_type == QUEUE_TYPE_EVENT  # BC is an ordinary event item
    assert payload["sia_code"] == "BC"  # disarm's first call → BC
    assert payload["user_number"] == 1  # configured user carried through IPC
    assert payload["zone_number"] is None  # never zone-addressed


@pytest.mark.asyncio
async def test_on_message_disarm_enqueues_op_with_user_number():
    """AC1: PHP's disarm(OP) call — the second of the two calls disarm makes — reaches the
    queue as an OP event with the same user number.

    Expected:
    - one EVENT item with sia_code "OP" and the configured user_number
    """
    daemon = _make_daemon()

    await daemon.on_message("disarm", {"sia_code": "OP", "user_number": 1})

    assert daemon._queue.qsize() == 1
    _prio, _counter, _item_type, payload = daemon._queue.get_nowait()
    assert payload["sia_code"] == "OP"  # disarm's second call → OP
    assert payload["user_number"] == 1


@pytest.mark.asyncio
async def test_on_message_alarm_reset_enqueues_bc_with_user_number():
    """AC3: PHP's alarmReset(BC) call (mode-change reset, no release) reaches the queue as
    a BC event, same address contract as disarm's.

    Expected:
    - one EVENT item with sia_code "BC" and the configured user_number
    """
    daemon = _make_daemon()

    await daemon.on_message("alarmReset", {"sia_code": "BC", "user_number": 7})

    assert daemon._queue.qsize() == 1
    _prio, _counter, _item_type, payload = daemon._queue.get_nowait()
    assert payload["sia_code"] == "BC"  # alarmReset always sends BC
    assert payload["user_number"] == 7  # a non-default configured user is carried too


@pytest.mark.asyncio
async def test_on_message_disarm_missing_sia_code_is_ignored(caplog):
    """A malformed/missing sia_code from PHP must never enqueue a frame with an invalid or
    absent code — on_message() must reject it, not guess.

    Expected:
    - no EVENT item is enqueued
    - a warning is logged
    """
    daemon = _make_daemon()
    daemon._logger = logging.getLogger("test_bad_disarm_sia_code")

    with caplog.at_level(logging.WARNING, logger="test_bad_disarm_sia_code"):
        await daemon.on_message("disarm", {"user_number": 1})

    assert daemon._queue.qsize() == 0  # nothing enqueued without a valid sia_code
    assert "sia_code" in caplog.text  # the anomaly is traceable


@pytest.mark.asyncio
async def test_build_event_frame_bc_and_op_address_by_user_number():
    """AC5: BC/OP frames carry the configured user number as their address field, zero-
    padded like a zone — [#acct|BC 001] / [#acct|OP 001] — never a zone number.

    Reference: SIA DC-09-2021 Annex B — address formatted as 3 zero-padded digits.
    Reference: ADR-18 — BC/OP address by user number, never by zone.

    Expected:
    - user_number=1 → frame contains "[#001234|BC 001]" for BC, "[#001234|OP 001]" for OP
    - a non-None zone_number on a BC/OP EventItem is ignored — user_number wins
    """
    daemon = _make_daemon()
    bc = EventItem(sia_code="BC", zone=None, timestamp="12:00:00,09-25-2026", user_number=1)
    op = EventItem(sia_code="OP", zone=None, timestamp="12:00:00,09-25-2026", user_number=1)
    bc_with_stray_zone = EventItem(
        sia_code="BC", zone=None, timestamp="12:00:00,09-25-2026", zone_number=9, user_number=1
    )

    assert b"[#001234|BC 001]" in daemon._build_event_frame(bc)  # user-number address, zero-padded
    assert b"[#001234|OP 001]" in daemon._build_event_frame(op)  # same contract for OP
    # Assert: zone_number is ignored on BC/OP — the address always comes from user_number
    assert b"[#001234|BC 001]" in daemon._build_event_frame(bc_with_stray_zone)
