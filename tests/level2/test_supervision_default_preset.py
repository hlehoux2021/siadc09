"""Story 17.1 AC9: a default CSRPreset keeps today's supervision frame and cadence.

The periodic-frame fields (supervision_format, rp_enabled, rp_interval_s) are
stored by the daemon but not acted on until Stories 17.2/17.3. A daemon built
from a preset that leaves them at their defaults must run one supervision loop
at supervision_interval_s and send the unchanged "SIA-DCS"…[#acct|0000] frame.

Test level: Level 2 (async, mocked transport, no Jeedom required)
Reference: SIA DC-09-2021 § 5.5.2 Supervision Message; D-86 (SIA-DCS keep-alive)
"""
import asyncio
import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SIADaemon, SM1State
from resources.siadc09d.sia_protocol import parse_frame_header
from tests.conftest import make_daemon_preset

_ACCOUNT = "001234"
_LOOP_CYCLES = 2
# Differs from the rp_interval_s default (60 s) so a loop driven by RP would be caught.
_SUPERVISION_INTERVAL_S = 45.0


def _make_default_daemon(supervision_interval_s: float | None = None) -> SIADaemon:
    """SIADaemon whose preset leaves the 17.1 fields at their defaults.

    Args:
        supervision_interval_s: Override of the preset supervision interval; None keeps it.

    Returns:
        A daemon with mocked transport and Jeedom callbacks.
    """
    preset = make_daemon_preset()
    if supervision_interval_s is not None:
        preset = dataclasses.replace(preset, supervision_interval_s=supervision_interval_s)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = _ACCOUNT
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()
    transport = MagicMock()
    transport.start = AsyncMock()
    transport.close = AsyncMock()
    transport.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = transport
    return daemon


def test_default_preset_periodic_fields() -> None:
    """
    The preset used by the daemon tests carries the 17.1 defaults.

    Expected result:
    - supervision_format "sia-dcs", rp_enabled False, rp_interval_s 60.0
    """
    preset = make_daemon_preset()
    # Assert: defaults equal today's behaviour
    assert (preset.supervision_format, preset.rp_enabled, preset.rp_interval_s) == ("sia-dcs", False, 60.0)


@pytest.mark.asyncio
async def test_default_preset_supervision_cadence_unchanged() -> None:
    """
    _supervision_loop() sends the first frame at start, then sleeps exactly
    supervision_interval_s between enqueues (story 17-2).

    Scenario: asyncio.sleep is replaced by a recorder (no wall-clock wait); the
    loop is cancelled after two enqueues.

    Expected result:
    - the first enqueue happens before any sleep (one sleep for two enqueues)
    - every sleep is supervision_interval_s (45 s, distinct from the 60 s rp_interval_s default)
    """
    daemon = _make_default_daemon(supervision_interval_s=_SUPERVISION_INTERVAL_S)
    # Assert: 17.1 fields still at their defaults, RP interval distinct from supervision
    assert daemon._preset.rp_interval_s != _SUPERVISION_INTERVAL_S
    sleeps: list[float] = []
    enqueues: list[int] = []
    done = asyncio.Event()

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def spy_enqueue() -> None:
        enqueues.append(1)
        if len(enqueues) >= _LOOP_CYCLES:
            done.set()
            raise asyncio.CancelledError

    daemon._enqueue_supervision = spy_enqueue
    with patch("resources.siadc09d.daemon.asyncio.sleep", record_sleep):
        with pytest.raises(asyncio.CancelledError):
            await daemon._supervision_loop()

    # Assert: loop stopped after the expected number of cycles
    assert done.is_set()
    # Assert: cadence is the supervision interval, first frame sent without a sleep
    assert sleeps == [_SUPERVISION_INTERVAL_S] * (_LOOP_CYCLES - 1)
    # Assert: the expected number of enqueues
    assert len(enqueues) == _LOOP_CYCLES


@pytest.mark.asyncio
async def test_default_preset_supervision_frame_unchanged() -> None:
    """
    _send_supervision() sends the unchanged SIA-DCS keep-alive frame (D-86).

    Expected result:
    - exactly one frame sent on ACK
    - frame carries "SIA-DCS" and the [#<acct>|0000] data block, not *NULL / RP
    """
    daemon = _make_default_daemon()

    await daemon._send_supervision()

    send_frame = daemon._sia_transport.send_frame
    # Assert: one frame sent (ACK on first attempt)
    assert send_frame.await_count == 1
    frame: bytes = send_frame.await_args.args[0]
    # Assert: SIA-DCS keep-alive token
    assert b'"SIA-DCS"' in frame
    # Assert: unchanged data block
    assert f"[#{_ACCOUNT}|0000]".encode() in frame


def _make_daemon_with_format(fmt: str, **replace: object) -> SIADaemon:
    """Default test daemon whose preset uses the given supervision_format."""
    daemon = _make_default_daemon()
    daemon._preset = dataclasses.replace(daemon._preset, supervision_format=fmt, **replace)
    return daemon


@pytest.mark.asyncio
async def test_null_format_clear_frame_and_tracker_untouched() -> None:
    """
    Format null in clear sends "NULL"0000L0#acct[]_ts and does not use the tracker (§ 5.5.2.1).

    Expected result:
    - frame body is "NULL"0000L0#001234[]_HH:MM:SS,MM-DD-YYYY
    - the next event still gets tracker seq 0001
    """
    daemon = _make_daemon_with_format("null")

    await daemon._send_supervision()

    frame: bytes = daemon._sia_transport.send_frame.await_args.args[0]
    body = frame[9:-1].decode()
    # Assert: clear Null Message template
    assert re.fullmatch(r'"NULL"0000L0#001234\[\]_\d\d:\d\d:\d\d,\d\d-\d\d-\d{4}', body)
    # Assert: tracker not consumed, first event is still seq 0001
    assert parse_frame_header(daemon._sia_builder.encode_message("001234", "BA"))[1] == "0001"


@pytest.mark.asyncio
async def test_null_format_nak_resend_keeps_seq_0000_fresh_timestamp() -> None:
    """
    A NAKed null frame is re-sent with seq 0000 (§ 5.5.1.5).

    Expected result:
    - two frames sent (NAK then ACK), both seq 0000 and token NULL
    """
    daemon = _make_daemon_with_format("null")
    nak = daemon._sia_builder.encode_message("001234", "BA")  # any bytes; _nak_offset is stubbed
    daemon._nak_offset = MagicMock(return_value=None)
    daemon._sia_transport.send_frame = AsyncMock(side_effect=[
        {"status": "nak", "raw_nak": nak}, {"status": "ack", "raw_nak": None}])

    await daemon._send_supervision()

    frames = [c.args[0] for c in daemon._sia_transport.send_frame.await_args_list]
    # Assert: NAK then re-send
    assert len(frames) == 2
    # Assert: both frames are NULL with seq 0000
    assert [parse_frame_header(f) for f in frames] == [("NULL", "0000")] * 2


@pytest.mark.asyncio
async def test_null_format_encrypted_is_star_null_and_sia_dcs_keeps_fallback() -> None:
    """
    With encryption on, null sends "*NULL"0000 and sia-dcs keeps the "*SIA-DCS" fallback.

    Expected result:
    - null: header ("*NULL", "0000")
    - sia-dcs: header ("*SIA-DCS", "0001") from the tracker
    """
    key = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
    headers = {}
    for fmt in ("null", "sia-dcs"):
        daemon = _make_daemon_with_format(fmt, encryption_enabled=True)
        daemon._encryption_key = key
        await daemon._send_supervision()
        headers[fmt] = parse_frame_header(daemon._sia_transport.send_frame.await_args.args[0])
    # Assert: real Null Message for format null
    assert headers["null"] == ("*NULL", "0000")
    # Assert: encrypted SIA-DCS fallback unchanged for format sia-dcs
    assert headers["sia-dcs"] == ("*SIA-DCS", "0001")


@pytest.mark.asyncio
async def test_none_format_starts_no_supervision_task() -> None:
    """
    Format none: on_start() creates only the queue consumer and no frame is sent.

    Expected result:
    - task names == {"queue_consumer"}
    - no frame sent
    """
    daemon = _make_daemon_with_format("none", rp_enabled=True)
    with patch("resources.siadc09d.daemon.SIAUDPTransport") as mock_cls:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        mock_cls.return_value = mock_t
        await daemon.on_start()
    # Assert: no supervision task
    assert {t.get_name() for t in daemon._tasks} == {"queue_consumer"}
    # Assert: nothing sent
    assert mock_t.send_frame.await_count == 0
    await daemon.on_stop()


@pytest.mark.asyncio
async def test_period_counts_from_end_of_exchange() -> None:
    """
    The loop sleeps only after the exchange has ended, however long it took.

    Scenario: the enqueue spy leaves the exchange pending; sleep is recorded.

    Expected result:
    - no sleep while the exchange is pending
    - one sleep of the interval once the exchange-done event is set
    """
    daemon = _make_default_daemon(supervision_interval_s=_SUPERVISION_INTERVAL_S)
    enqueued = asyncio.Event()
    slept = asyncio.Event()
    sleeps: list[float] = []

    async def spy_enqueue() -> None:
        daemon._supervision_exchange_done.clear()
        enqueued.set()

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)
        slept.set()
        raise asyncio.CancelledError

    daemon._enqueue_supervision = spy_enqueue
    with patch("resources.siadc09d.daemon.asyncio.sleep", record_sleep):
        task = asyncio.create_task(daemon._supervision_loop())
        await enqueued.wait()
        # Assert: exchange pending, so the loop has not slept
        assert sleeps == [] and not slept.is_set()
        daemon._supervision_exchange_done.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    # Assert: the sleep started after the exchange ended
    assert sleeps == [_SUPERVISION_INTERVAL_S]


@pytest.mark.asyncio
async def test_no_network_drop_releases_exchange_wait() -> None:
    """
    A SUPERVISION item dropped in NO_NETWORK still releases the loop wait.

    Expected result:
    - after enqueue the event is cleared; once the consumer drops the item it is set
    - no frame sent
    """
    daemon = _make_default_daemon()
    daemon._set_sm1_state(SM1State.NO_NETWORK)
    consumer = asyncio.create_task(daemon._queue_consumer())
    await daemon._enqueue_supervision()
    # Assert: pending right after enqueue
    assert not daemon._supervision_exchange_done.is_set()
    await asyncio.wait_for(daemon._queue.join(), timeout=2.0)
    consumer.cancel()
    # Assert: released by the consumer's finally
    assert daemon._supervision_exchange_done.is_set()
    # Assert: item dropped, nothing sent
    assert daemon._sia_transport.send_frame.await_count == 0


def test_initializing_reentry_enqueues_no_supervision() -> None:
    """
    Re-entering INITIALIZING (reconnect) does not enqueue a supervision frame.

    Expected result:
    - queue stays empty after two INITIALIZING transitions
    """
    daemon = _make_default_daemon()
    daemon._set_sm1_state(SM1State.TCP_RECONNECTING)
    daemon._set_sm1_state(SM1State.INITIALIZING)
    daemon._set_sm1_state(SM1State.INITIALIZING)
    # Assert: no extra enqueue
    assert daemon._queue.qsize() == 0
