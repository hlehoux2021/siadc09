"""Story 17.3: RP cyclic test loop, frame, ACK handling and failure reporting.

Test level: Level 2 (async, mocked transport, no Jeedom required)
Reference: SIA DC-09-2021 § 5.5.1.5 (seq), § 5.6.1.2 (NAK re-send); ADR-08 / ADR-22
"""
import asyncio
import dataclasses
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SUPERVISION_NAK_RESENDS, SIADaemon, SM1State, SM2State
from resources.siadc09d.error_handler import ErrorCode
from resources.siadc09d.sia_protocol import parse_frame_header
from resources.siadc09d.sia_transport import SIATransportError
from tests.conftest import make_daemon_preset

_ACK = {"status": "ack", "raw_nak": None}
_RP_BODY = r'"SIA-DCS"(\d{4})L0#001234\[#001234\|Nri0/RP0000\]_\d\d:\d\d:\d\d,\d\d-\d\d-\d{4}'


def _make_daemon(**replace: object) -> SIADaemon:
    """Daemon with RP enabled and a mocked transport that ACKs."""
    preset = dataclasses.replace(make_daemon_preset(), rp_enabled=True, rp_interval_s=60.0, **replace)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = "001234"
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()
    transport = MagicMock()
    transport.start = AsyncMock()
    transport.close = AsyncMock()
    transport.send_frame = AsyncMock(return_value=dict(_ACK))
    daemon._sia_transport = transport
    return daemon


def _sent(daemon: SIADaemon, n: int = -1) -> bytes:
    return daemon._sia_transport.send_frame.await_args_list[n].args[0]


@pytest.mark.asyncio
async def test_rp_clear_frame_golden_and_seq_from_tracker() -> None:
    """
    RP clear frame matches the golden template and draws its seq from the shared tracker.

    Expected result:
    - body is "SIA-DCS"<seq>L0#001234[#001234|Nri0/RP0000]_ts (area 0, zone 0000)
    - seq 0001 is consumed: the next event gets 0002
    """
    daemon = _make_daemon()
    await daemon._send_rp()
    body = _sent(daemon)[9:-1].decode()
    # Assert: golden RP body
    assert re.fullmatch(_RP_BODY, body)
    # Assert: seq 0001 consumed from the shared tracker
    assert re.match(_RP_BODY, body).group(1) == "0001"
    assert parse_frame_header(daemon._sia_builder.encode_message("001234", "BA"))[1] == "0002"


@pytest.mark.asyncio
async def test_rp_encrypted_frame_header() -> None:
    """
    With encryption on the RP leaves as *SIA-DCS.

    Expected result:
    - header ("*SIA-DCS", "0001")
    """
    daemon = _make_daemon(encryption_enabled=True)
    daemon._encryption_key = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
    await daemon._send_rp()
    # Assert: encrypted SIA-DCS header, tracker seq
    assert parse_frame_header(_sent(daemon)) == ("*SIA-DCS", "0001")


@pytest.mark.asyncio
async def test_rp_ack_refreshes_sm1_without_touching_event_state() -> None:
    """
    An RP ACK refreshes SM1 and pushes supervision_state; event state is untouched.

    Expected result:
    - SM1 HEALTHY, strike counter 0, supervision_state pushed
    - SM2 state, event_label, sia code/zone unchanged; _sia_seq unchanged
    """
    daemon = _make_daemon()
    daemon._strike_counter = 2
    daemon._set_sm1_state(SM1State.DEGRADED)
    daemon._sm2_state = SM2State.CONFIRMED
    daemon._event_sia_code = "BA"
    daemon._event_zone = "Salon"
    seq_before = daemon._sia_seq
    await daemon._send_rp()
    # Assert: SM1 refreshed
    assert daemon._sm1_state == SM1State.HEALTHY
    assert daemon._strike_counter == 0
    pushes = [c.args[0] for c in daemon.send_to_jeedom.await_args_list]
    # Assert: supervision_state pushed, without event keys
    assert any("supervision_state" in p and "event_state" not in p for p in pushes)
    # Assert: user-facing event state untouched
    assert (daemon._sm2_state, daemon._event_sia_code, daemon._event_zone) == (SM2State.CONFIRMED, "BA", "Salon")
    assert daemon._sia_seq == seq_before


@pytest.mark.asyncio
async def test_rp_timeout_is_one_attempt_and_one_sm1_strike() -> None:
    """
    No ACK: a single attempt and a supervision strike, like a missed supervision frame.

    Expected result:
    - exactly one frame sent and no backoff sleep (the next cycle is the retry)
    - strike counter 1, SM1 DEGRADED, one SUPERVISION_TIMEOUT notification
    - no EVENT_FAILED; SM2 stays IDLE and event_sia_code None
    """
    daemon = _make_daemon()
    daemon._sia_transport.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})
    with patch("resources.siadc09d.daemon.asyncio.sleep", new=AsyncMock()) as sleep:
        await daemon._send_rp()
    # Assert: one attempt, no backoff
    assert daemon._sia_transport.send_frame.await_count == 1
    sleep.assert_not_called()
    # Assert: one strike, SM1 degraded
    assert daemon._strike_counter == 1
    assert daemon._sm1_state == SM1State.DEGRADED
    # Assert: T1 supervision timeout only, no EVENT_FAILED
    daemon._notify.assert_called_once()
    assert daemon._notify.call_args.args[0] == ErrorCode.SUPERVISION_TIMEOUT
    # Assert: user-facing event state untouched
    assert daemon._sm2_state == SM2State.IDLE
    assert daemon._event_sia_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize("supervision_format", ["none", "sia-dcs"])
async def test_rp_three_missed_cycles_reach_t3_whatever_the_supervision_format(
    supervision_format: str,
) -> None:
    """
    Three missed RP cycles lose the CSR, including when RP is the only periodic frame (D-1b).

    Expected result:
    - strike counter 3 and one SUPERVISION_DISCONNECTED (T3) notification
    - SM1 DEGRADED on UDP (no TCP_RECONNECTING)
    """
    daemon = _make_daemon(supervision_format=supervision_format)
    daemon._sia_transport.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})
    for _ in range(3):
        await daemon._send_rp()
    # Assert: strike cap reached
    assert daemon._strike_counter == 3
    # Assert: T3 fired exactly once
    codes = [c.args[0] for c in daemon._notify.call_args_list]
    assert codes.count(ErrorCode.SUPERVISION_DISCONNECTED) == 1
    # Assert: UDP stays DEGRADED
    assert daemon._sm1_state == SM1State.DEGRADED


@pytest.mark.asyncio
async def test_rp_tcp_drop_starts_reconnect_without_strike() -> None:
    """
    A TCP drop on an RP goes through the SM1 reconnect logic, not an RP retry.

    Expected result:
    - SM1 TCP_RECONNECTING, tcp_reconnect_loop tracked
    - no strike; a single frame sent
    """
    daemon = _make_daemon(supervision_format="none")
    daemon._sia_transport.send_frame = AsyncMock(return_value={"status": "tcp_drop", "raw_nak": None})
    daemon._tcp_reconnect_loop = AsyncMock()
    await daemon._send_rp()
    await asyncio.gather(*daemon._tasks)
    # Assert: reconnect started via SM1
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    daemon._tcp_reconnect_loop.assert_awaited_once()
    # Assert: no strike, no RP retry
    assert daemon._strike_counter == 0
    assert daemon._sia_transport.send_frame.await_count == 1


@pytest.mark.asyncio
async def test_rp_transport_error_counts_as_timeout() -> None:
    """
    A transport exception on an RP is a missed frame, like for supervision.

    Expected result:
    - strike counter 1, one SUPERVISION_TIMEOUT notification
    """
    daemon = _make_daemon()
    daemon._sia_transport.send_frame = AsyncMock(side_effect=SIATransportError("boom"))
    await daemon._send_rp()
    # Assert: one strike
    assert daemon._strike_counter == 1
    # Assert: T1 notification
    assert daemon._notify.call_args.args[0] == ErrorCode.SUPERVISION_TIMEOUT


@pytest.mark.asyncio
async def test_rp_loop_first_frame_before_sleep_then_period_after_exchange() -> None:
    """
    The first RP is enqueued before any sleep; the sleep starts only after the exchange ends.

    Expected result:
    - one enqueue and no sleep while the exchange is pending
    - after release: one sleep of rp_interval_s, then a second enqueue
    """
    daemon = _make_daemon()
    events: list[str] = []
    first = asyncio.Event()
    second = asyncio.Event()

    async def spy_enqueue() -> None:
        daemon._rp_exchange_done.clear()
        events.append("enqueue")
        (first if events.count("enqueue") == 1 else second).set()

    async def spy_sleep(delay: float) -> None:
        events.append(f"sleep:{delay}")

    daemon._enqueue_rp = spy_enqueue
    with patch("resources.siadc09d.daemon.asyncio.sleep", new=spy_sleep):
        task = asyncio.create_task(daemon._rp_loop())
        await asyncio.wait_for(first.wait(), timeout=2)
        # Assert: first frame enqueued, exchange pending, no sleep yet
        assert events == ["enqueue"]
        daemon._rp_exchange_done.set()
        await asyncio.wait_for(second.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    # Assert: sleep of the interval only after the release
    assert events == ["enqueue", "sleep:60.0", "enqueue"]


@pytest.mark.asyncio
async def test_rp_no_network_drop_releases_wait() -> None:
    """
    NO_NETWORK: the consumer drops the RP and still releases the loop's wait.

    Expected result:
    - no frame sent, _rp_exchange_done set, queue drained
    """
    daemon = _make_daemon()
    daemon._set_sm1_state(SM1State.NO_NETWORK)
    consumer = asyncio.create_task(daemon._queue_consumer())
    await daemon._enqueue_rp()
    await asyncio.wait_for(daemon._queue.join(), timeout=2)
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    # Assert: dropped, wait released
    assert daemon._sia_transport.send_frame.await_count == 0
    assert daemon._rp_exchange_done.is_set()


@pytest.mark.asyncio
async def test_rp_off_starts_no_task() -> None:
    """
    rp_enabled False: no RP task and no RP frame.

    Expected result:
    - task names == {"queue_consumer", "supervision_loop"}
    """
    daemon = _make_daemon()
    daemon._preset = dataclasses.replace(daemon._preset, rp_enabled=False)
    with patch("resources.siadc09d.daemon.SIAUDPTransport") as mock_cls:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value=dict(_ACK))
        mock_cls.return_value = mock_t
        await daemon.on_start()
    # Assert: no rp_loop
    assert {t.get_name() for t in daemon._tasks} == {"queue_consumer", "supervision_loop"}
    await daemon.on_stop()


@pytest.mark.asyncio
async def test_rp_bad_key_notifies_once_across_cycles() -> None:
    """
    Encryption on with an invalid key: two RP cycles give a single EVENT_FAILED.

    Expected result:
    - nothing is sent
    - exactly one EVENT_FAILED notification (last_error encryption_key)
    """
    daemon = _make_daemon(encryption_enabled=True)
    daemon._encryption_key = b""
    await daemon._send_rp()
    await daemon._send_rp()
    # Assert: nothing sent
    assert daemon._sia_transport.send_frame.await_count == 0
    # Assert: one notification only
    failed = [c for c in daemon._notify.call_args_list if c.args[0] == ErrorCode.EVENT_FAILED]
    assert len(failed) == 1
    assert failed[0].args[1].last_error == "encryption_key"


_NAK = {"status": "nak", "raw_nak": b""}


@pytest.mark.asyncio
async def test_rp_nak_then_ack_resends_with_same_wire_seq() -> None:
    """
    A NAK is answered by an immediate re-send on the same wire seq, then an ACK ends the cycle.

    Expected result (§ 5.6.1.2, § 5.5.1.5):
    - two frames sent, no sleep, same wire seq
    - no notification; SM1 refreshed by the ACK
    """
    daemon = _make_daemon()
    daemon._sia_transport.send_frame = AsyncMock(side_effect=[dict(_NAK), dict(_ACK)])
    daemon._refresh_sm1_on_ack = AsyncMock()
    with patch("resources.siadc09d.daemon.asyncio.sleep", new=AsyncMock()) as sleep:
        await daemon._send_rp()
    # Assert: NAK re-send, no backoff
    assert daemon._sia_transport.send_frame.await_count == 2
    sleep.assert_not_called()
    # Assert: same wire seq on both frames
    seqs = {parse_frame_header(c.args[0])[1] for c in daemon._sia_transport.send_frame.await_args_list}
    assert len(seqs) == 1
    # Assert: nothing reported, SM1 refreshed
    daemon._notify.assert_not_called()
    daemon._refresh_sm1_on_ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_rp_nak_every_attempt_is_one_sm1_strike() -> None:
    """
    NAK on every re-send: one supervision strike, like a NAKed supervision frame.

    Expected result:
    - 1 + SUPERVISION_NAK_RESENDS frames sent (same re-send budget as supervision)
    - strike counter 1, SM1 DEGRADED
    - unparseable NAK -> one BAD_CSR_RESPONSE notification, no EVENT_FAILED
    """
    daemon = _make_daemon()
    daemon._sia_transport.send_frame = AsyncMock(return_value=dict(_NAK))
    await daemon._send_rp()
    # Assert: supervision re-send budget
    assert daemon._sia_transport.send_frame.await_count == SUPERVISION_NAK_RESENDS + 1
    # Assert: one strike
    assert daemon._strike_counter == 1
    assert daemon._sm1_state == SM1State.DEGRADED
    # Assert: a single BAD_CSR_RESPONSE
    daemon._notify.assert_called_once()
    assert daemon._notify.call_args.args[0] == ErrorCode.BAD_CSR_RESPONSE


@pytest.mark.asyncio
async def test_rp_ack_after_missed_cycles_resets_strikes() -> None:
    """
    An RP ACK after missed cycles restores SM1, as a supervision ACK would.

    Expected result:
    - two missed cycles -> strike 2; the next ACK -> strike 0, SM1 HEALTHY
    """
    daemon = _make_daemon()
    daemon._sia_transport.send_frame = AsyncMock(return_value={"status": "timeout", "raw_nak": None})
    await daemon._send_rp()
    await daemon._send_rp()
    # Assert: two strikes accumulated
    assert daemon._strike_counter == 2
    daemon._sia_transport.send_frame = AsyncMock(return_value=dict(_ACK))
    await daemon._send_rp()
    # Assert: recovered
    assert daemon._strike_counter == 0
    assert daemon._sm1_state == SM1State.HEALTHY
