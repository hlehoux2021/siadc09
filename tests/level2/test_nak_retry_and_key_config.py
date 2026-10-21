"""NAK immediate re-send and invalid-key blocking (story 1-5 AC3, AC4, AC7).

The daemon's _send_raw is wired straight into CSRSimulator._build_response, so
every frame the daemon builds is parsed (and decrypted) by the simulator in
process — no sockets. References: DC-09 § 5.5.1.5 (same seq on repeat),
§ 5.6.1.2 (NAK → repeat immediately with an updated timestamp).
"""

import logging
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jeedomdaemon import BaseConfig

from resources.siadc09d.csr_simulator import (
    DEFAULT_TIMESTAMP_WINDOW_S,
    CSRSimulator,
    CSRSimulatorPreset,
)
from resources.siadc09d.daemon import (
    ENCRYPTION_KEY_LOGICAL_ID,
    SUPERVISION_NAK_RESENDS,
    EventItem,
    SIADaemon,
    SM1State,
    SM2State,
)
from resources.siadc09d.error_handler import EVENT_FAILED_ENCRYPTION_KEY, ErrorCode
from resources.siadc09d.messages import SM1_CONFIG_ERROR_FR
from resources.siadc09d.sia_crypto import AESKeyError, parse_hex_key
from resources.siadc09d.sia_protocol import SIAMessageBuilder, parse_frame_header
from resources.siadc09d.sia_transport import SIATransportResult
from tests.conftest import make_daemon_preset
from tests.harness.run_harness import _get_free_port

_KEY_HEX = "0123456789ABCDEF0123456789ABCDEF"
_KEY = bytes.fromhex(_KEY_HEX)
_BAD_KEY_HEX = "0123456789ABCDEF0123456789ABCDEZ"  # 32 chars, one non-hex digit
_ACCOUNT = "001234"
_ONE_HOUR_S = 3600.0
_TWO_DAYS_S = 2 * 24 * 3600.0


def _simulator(
    key: bytes | None = None,
    *,
    nak_first: int = 0,
    clock_skew_s: float = 0.0,
    nak_with_timestamp: bool = True,
    timestamp_window_s: tuple[float, float] | None = None,
) -> CSRSimulator:
    """CSR simulator for account 001234 (never started — used in process)."""
    preset: CSRSimulatorPreset = {
        "crc_format": "hex", "account_number": _ACCOUNT, "encryption_key": key,
    }
    return CSRSimulator(
        _get_free_port(), _get_free_port(), preset,
        nak_first=nak_first, clock_skew_s=clock_skew_s,
        nak_with_timestamp=nak_with_timestamp, timestamp_window_s=timestamp_window_s,
    )


def _wire(daemon: SIADaemon, sim: CSRSimulator) -> list[bytes]:
    """Route daemon._send_raw through the simulator; return the list of sent frames."""
    sent: list[bytes] = []

    async def _send_raw(frame: bytes) -> SIATransportResult:
        sent.append(frame)
        daemon._last_sent_frame = frame
        decision, response = sim._build_response(frame)
        if decision == "ACK":
            return SIATransportResult(status="ack", raw_nak=None, raw_response=response)
        if decision == "NAK":
            return SIATransportResult(status="nak", raw_nak=response, raw_response=response)
        return SIATransportResult(status="timeout", raw_nak=None, raw_response=None)

    daemon._send_raw = _send_raw  # type: ignore[method-assign]
    return sent


def _daemon(*, encrypted: bool = False, config: BaseConfig | None = None) -> SIADaemon:
    """SIADaemon with encryption optionally on, callbacks and notify mocked."""
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=replace(make_daemon_preset(), encryption_enabled=encrypted),
                           config=config)
    if encrypted and config is None:
        daemon._encryption_key = _KEY
    daemon._sm1_state = SM1State.HEALTHY
    daemon._notify = MagicMock()
    daemon._send_callback = AsyncMock()
    daemon._update_info_commands = AsyncMock()
    return daemon


def _key_config(key_hex: str) -> BaseConfig:
    """BaseConfig parsed from --encryption-key, as siadc09d.py does in production."""
    config = BaseConfig()
    config.add_argument("--encryption-key", type=str, default="")
    config.parse(["--encryption-key", key_hex])
    return config


def _event() -> EventItem:
    """BA burglary event on zone Salon."""
    return EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")


def _seqs(frames: list[bytes]) -> list[str]:
    """Clear sequence field of each frame."""
    return [parse_frame_header(f)[1] for f in frames]


class TestEventNakRetry:
    """An event NAK is repeated immediately with the same seq (AC4)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encrypted", [False, True])
    async def test_nak_once_then_ack_confirms(self, encrypted: bool) -> None:
        """
        NAK once → immediate re-send → ACK, clear and encrypted.

        Expected result:
        - two frames sent, same wire seq
        - no sleep between them
        - CONFIRMED, no T2 BAD_CSR_RESPONSE
        - encrypted frames carry the *SIA-DCS token
        """
        daemon = _daemon(encrypted=encrypted)
        sent = _wire(daemon, _simulator(_KEY if encrypted else None, nak_first=1))

        with patch("asyncio.sleep") as mock_sleep:
            result = await daemon._send_with_retry(_event(), max_retries=2)

        # Assert: initial attempt + one NAK re-send
        assert len(sent) == 2
        # Assert: the re-send reuses the wire seq (§ 5.5.1.5)
        assert len(set(_seqs(sent))) == 1
        # Assert: NAK re-send is immediate
        mock_sleep.assert_not_called()
        # Assert: the event is confirmed
        assert result == SM2State.CONFIRMED
        # Assert: no T2 for a NAK that healed
        assert all(c.args[0] != ErrorCode.BAD_CSR_RESPONSE for c in daemon._notify.call_args_list)
        # Assert: token reflects encryption
        assert parse_frame_header(sent[0])[0] == ("*SIA-DCS" if encrypted else "SIA-DCS")

    @pytest.mark.asyncio
    async def test_nak_timestamp_heals_receiver_clock_skew(self) -> None:
        """
        The re-send uses the NAK timestamp, so a skewed receiver accepts it (§ 5.6.1.2).

        Receiver clock is 1 h ahead with the default ±window: the first frame
        (local UTC) is outside it, the re-send (NAK time) is inside.

        Expected result:
        - two frames sent, the second ACKed
        - CONFIRMED
        """
        daemon = _daemon(encrypted=True)
        sim = _simulator(_KEY, clock_skew_s=_ONE_HOUR_S, timestamp_window_s=DEFAULT_TIMESTAMP_WINDOW_S)
        sent = _wire(daemon, sim)

        result = await daemon._send_with_retry(_event(), max_retries=2)

        # Assert: rejected once, accepted on the re-send
        assert len(sent) == 2
        # Assert: the healed timestamp got the event through
        assert result == SM2State.CONFIRMED

    @pytest.mark.asyncio
    async def test_insane_nak_timestamp_ignored_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """
        A NAK timestamp more than 24 h away is ignored (D3).

        Expected result:
        - WARN logged about the NAK timestamp
        - the re-send still happens and is ACKed (unencrypted: no window check)
        """
        daemon = _daemon()
        sent = _wire(daemon, _simulator(nak_first=1, clock_skew_s=_TWO_DAYS_S))

        with caplog.at_level(logging.WARNING):
            result = await daemon._send_with_retry(_event(), max_retries=2)

        # Assert: re-sent once
        assert len(sent) == 2
        # Assert: confirmed on the re-send
        assert result == SM2State.CONFIRMED
        # Assert: the insane timestamp is reported
        assert any("more than 24 h" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("skew_s", "expect_applied"),
        [(24 * 3600 - 1, True), (24 * 3600 + 1, False)],
        ids=["just_inside_24h", "just_outside_24h"],
    )
    async def test_nak_offset_24h_boundary_precise(self, skew_s: float, expect_applied: bool) -> None:
        """
        _nak_offset's ±24 h sanity check (D3), tested one second either side of it.

        Review finding 2026-09-28: the existing tests only used 1 h (well
        inside) and 2 days (well outside) skews, leaving the exact boundary
        untested. Calls _nak_offset() directly with a NAK frame built at a
        precise skew, isolating the boundary check from a full send/retry
        round-trip.

        Expected result:
        - just inside 24 h: the NAK's own clock offset is applied (non-zero)
        - just outside 24 h: the offset is ignored (timedelta(0))
        """
        sim = _simulator(clock_skew_s=skew_s)
        daemon = _daemon()
        raw_nak = sim._generate_nak_frame(sim.preset)

        offset = daemon._nak_offset(raw_nak)

        if expect_applied:
            # Assert: a real, non-zero offset close to the configured skew
            assert abs(offset.total_seconds() - skew_s) < 2
        else:
            # Assert: ignored, falls back to zero offset
            assert offset == timedelta(0)

    @pytest.mark.asyncio
    async def test_nak_budget_exhausted_single_t2(self) -> None:
        """
        NAK on every attempt → FAILED 'nak' with exactly one T2.

        Expected result:
        - max_retries + 1 frames sent, one wire seq
        - FAILED, reason 'nak'
        - exactly one BAD_CSR_RESPONSE notification
        """
        daemon = _daemon()
        sent = _wire(daemon, _simulator(nak_first=10))

        result = await daemon._send_with_retry(_event(), max_retries=2)

        t2 = [c for c in daemon._notify.call_args_list if c.args[0] == ErrorCode.BAD_CSR_RESPONSE]
        # Assert: three attempts
        assert len(sent) == 3
        # Assert: one wire seq across them
        assert len(set(_seqs(sent))) == 1
        # Assert: FAILED
        assert result == SM2State.FAILED
        # Assert: attributed to the NAK
        assert daemon._event_failure_reason == "nak"
        # Assert: a single T2, not one per NAK
        assert len(t2) == 1

    @pytest.mark.asyncio
    async def test_nak_with_no_retry_left_fails_at_once(self) -> None:
        """
        retries_left = 0 then NAK → FAILED 'nak' after one attempt.

        Expected result:
        - one frame sent
        - FAILED, reason 'nak'
        """
        daemon = _daemon()
        sent = _wire(daemon, _simulator(nak_first=1))

        result = await daemon._send_with_retry(_event(), max_retries=0)

        # Assert: no re-send without budget
        assert len(sent) == 1
        # Assert: FAILED
        assert result == SM2State.FAILED
        # Assert: attributed to the NAK
        assert daemon._event_failure_reason == "nak"

    @pytest.mark.asyncio
    async def test_nak_timeout_nak_ack_confirms(self) -> None:
        """
        NAK / timeout / NAK / ACK → CONFIRMED on the fourth attempt, same seq.

        Expected result:
        - four frames sent, one wire seq
        - CONFIRMED
        """
        daemon = _daemon()
        nak = _simulator(nak_first=1)._generate_nak_frame(
            {"crc_format": "hex", "account_number": _ACCOUNT, "encryption_key": None})
        results = iter([
            SIATransportResult(status="nak", raw_nak=nak, raw_response=nak),
            SIATransportResult(status="timeout", raw_nak=None, raw_response=None),
            SIATransportResult(status="nak", raw_nak=nak, raw_response=nak),
            SIATransportResult(status="ack", raw_nak=None, raw_response=None),
        ])
        sent: list[bytes] = []

        async def _send_raw(frame: bytes) -> SIATransportResult:
            sent.append(frame)
            return next(results)

        daemon._send_raw = _send_raw  # type: ignore[method-assign]
        with patch("asyncio.sleep"):
            result = await daemon._send_with_retry(_event(), max_retries=3)

        # Assert: four attempts
        assert len(sent) == 4
        # Assert: one wire seq across them
        assert len(set(_seqs(sent))) == 1
        # Assert: confirmed on the last one
        assert result == SM2State.CONFIRMED


class TestSupervisionNakRetry:
    """A supervision NAK is repeated immediately before any strike (AC4)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encrypted", [False, True])
    async def test_nak_once_then_ack_no_strike(self, encrypted: bool) -> None:
        """
        NULL NAKed once then ACKed → healthy, no strike.

        Expected result:
        - two frames sent, same seq (*NULL: 0000)
        - no sleep between them (review finding 2026-09-28: AC4's Tests
          bullet asks for this on the supervision path too, not just events)
        - strike counter stays 0, SM1 HEALTHY
        """
        daemon = _daemon(encrypted=encrypted)
        sent = _wire(daemon, _simulator(_KEY if encrypted else None, nak_first=1))

        with patch("asyncio.sleep") as mock_sleep:
            await daemon._send_supervision()

        # Assert: one immediate re-send
        assert len(sent) == 2
        # Assert: same seq on both
        assert len(set(_seqs(sent))) == 1
        # Assert: NAK re-send is immediate
        mock_sleep.assert_not_called()
        # Assert: no strike for a healed NAK
        assert daemon._strike_counter == 0
        # Assert: still healthy
        assert daemon._sm1_state == SM1State.HEALTHY
        if encrypted:
            # Assert: encrypted supervision is the D2 fallback *SIA-DCS 0000
            # (ioBroker.sia has no real *NULL response path, story 1-5 D2)
            assert parse_frame_header(sent[0]) == ("*SIA-DCS", "0001")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encrypted", [False, True])
    async def test_nak_every_resend_single_strike(self, encrypted: bool) -> None:
        """
        NULL NAKed on every re-send → exactly one strike, clear and encrypted.

        Expected result:
        - SUPERVISION_NAK_RESENDS + 1 frames sent
        - no sleep between any of them
        - strike counter 1
        - encrypted case exhausts the same way, still under *NULL (review
          finding 2026-09-28: previously only the unencrypted exhaustion
          and the encrypted heal-on-first-retry cases were covered)
        """
        daemon = _daemon(encrypted=encrypted)
        sent = _wire(daemon, _simulator(_KEY if encrypted else None, nak_first=10))

        with patch("asyncio.sleep") as mock_sleep:
            await daemon._send_supervision()

        # Assert: initial + every allowed re-send
        assert len(sent) == SUPERVISION_NAK_RESENDS + 1
        # Assert: no sleep across the whole exhausted retry sequence
        mock_sleep.assert_not_called()
        # Assert: one strike for the whole exchange
        assert daemon._strike_counter == 1
        if encrypted:
            # Assert: every attempt stayed the D2 fallback *SIA-DCS 0001, even NAKed
            assert all(parse_frame_header(f) == ("*SIA-DCS", "0001") for f in sent)


class TestInvalidKeyBlocksSending:
    """Encryption on with a bad key → nothing is sent, the user is told (AC3)."""

    @pytest.mark.asyncio
    async def test_event_failed_config_and_single_notification(self, caplog: pytest.LogCaptureFixture) -> None:
        """
        A malformed key blocks every send and notifies once.

        Expected result:
        - no frame sent for two events and one supervision
        - events FAILED with reason 'config', EVENT_FAILED carries last_error 'encryption_key'
        - SM1 CONFIG_ERROR, supervision label SM1_CONFIG_ERROR_FR
        - message_center + notify sent once in total
        - the key never appears in any log record
        """
        with caplog.at_level(logging.DEBUG):
            daemon = _daemon(encrypted=True, config=_key_config(_BAD_KEY_HEX))
            daemon._send_raw = AsyncMock()
            first = await daemon._send_with_retry(_event(), max_retries=2)
            second = await daemon._send_with_retry(_event(), max_retries=2)
            await daemon._send_supervision()

        failed = [c for c in daemon._notify.call_args_list if c.args[0] == ErrorCode.EVENT_FAILED]
        callbacks = [c.args[0] for c in daemon._send_callback.call_args_list]
        # Assert: nothing ever reached the transport
        daemon._send_raw.assert_not_awaited()
        # Assert: both events FAILED
        assert first == second == SM2State.FAILED
        # Assert: failure reason is the configuration
        assert daemon._event_failure_reason == "config"
        # Assert: one EVENT_FAILED per event
        assert len(failed) == 2
        # Assert: EVENT_FAILED names the key, not the network
        assert all(c.args[1].last_error == EVENT_FAILED_ENCRYPTION_KEY for c in failed)
        # Assert: SM1 shows the configuration error
        assert daemon._sm1_state == SM1State.CONFIG_ERROR
        # Assert: supervision label says so
        assert daemon._supervision_label() == SM1_CONFIG_ERROR_FR
        # Assert: one message_center for the key, once
        assert [c.get("logical_id") for c in callbacks if c["type"] == "message_center"] == [
            ENCRYPTION_KEY_LOGICAL_ID]
        # Assert: one notify, once
        assert len([c for c in callbacks if c["type"] == "notify"]) == 1
        # Assert: the key never leaks into logs
        assert all(_BAD_KEY_HEX not in r.getMessage() for r in caplog.records)

    def test_valid_key_parsed_from_config(self) -> None:
        """
        A 32-hex-digit key is decoded to 16 bytes, no config error.

        Expected result:
        - _encryption_key == bytes.fromhex(key)
        - _encryption_config_error() is False
        """
        daemon = _daemon(encrypted=True, config=_key_config(_KEY_HEX))

        # Assert: key decoded from hex
        assert daemon._encryption_key == _KEY
        # Assert: no configuration error
        assert daemon._encryption_config_error() is False


class TestKeyNeverLeaks:
    """The key never appears in logs, traces, the ring buffer or error reprs (AC9 leak test)."""

    @pytest.mark.asyncio
    async def test_encrypted_send_leaks_no_key(self, caplog: pytest.LogCaptureFixture) -> None:
        """
        Encrypted supervision (NAK then ACK) and event (NAK then ACK), key given by config.

        Expected result:
        - the key hex (either case) is absent from DEBUG logs
        - absent from every Jeedom callback payload (message_trace, info updates)
        - absent from the inspector ring buffer
        - absent from repr() of the daemon config and of a key error
        """
        caplog.set_level(logging.DEBUG)
        config = _key_config(_KEY_HEX)
        daemon = _daemon(encrypted=True, config=config)
        _wire(daemon, _simulator(_KEY, nak_first=1))

        await daemon._send_supervision()
        _wire(daemon, _simulator(_KEY, nak_first=1))  # fresh NAK budget for the event
        await daemon._send_with_retry(_event(), max_retries=2)
        with pytest.raises(AESKeyError) as key_error:
            parse_hex_key(_BAD_KEY_HEX)

        haystacks = {
            "logs": caplog.text,
            "callbacks": repr(daemon._send_callback.call_args_list),
            "ring_buffer": repr(daemon._ring_buffer.__dict__),
            "config": repr(daemon._config),
            "key_error": repr(key_error.value),
        }
        for key_text in (_KEY_HEX, _KEY_HEX.lower(), _BAD_KEY_HEX):
            for where, text in haystacks.items():
                # Assert: the key text never appears in any sink
                assert key_text not in text, f"key leaked in {where}"
        # Assert: sanity — both encrypted frames were traced, so the sinks were exercised
        # (supervision now uses the D2 fallback token too, *SIA-DCS, so
        # 'dialog_type' distinguishes the two dialogs instead of the token)
        assert "'dialog_type': 'supervision'" in haystacks["callbacks"] \
            and "'dialog_type': 'alarm'" in haystacks["callbacks"]


class TestTraceHeader:
    """Traces report the token and seq of the frame actually sent (AC7)."""

    def test_trace_header_from_encrypted_frame(self) -> None:
        """
        An encrypted event frame yields *SIA-DCS and its wire seq.

        Expected result:
        - {"id_token": "*SIA-DCS", "sequence": "0001"}
        """
        daemon = _daemon(encrypted=True)
        daemon._last_sent_frame = SIAMessageBuilder("SIA").encode_message(
            _ACCOUNT, "BA", encryption=True, encryption_key=_KEY)

        # Assert: token and seq read from the frame
        assert daemon._trace_header("SIA-DCS", 99) == {"id_token": "*SIA-DCS", "sequence": "0001"}

    @pytest.mark.parametrize("frame", [b"", b"\x00\x01"])
    def test_trace_header_falls_back_to_defaults(self, frame: bytes) -> None:
        """
        No frame or an unreadable one → the given defaults, sequence as str.

        Expected result:
        - {"id_token": "NULL", "sequence": "7"} — sequence is always a str,
          on this fallback path and on the parsed-frame path alike (review
          finding 2026-09-28)
        """
        daemon = _daemon()
        daemon._last_sent_frame = frame

        # Assert: defaults returned, sequence normalized to str
        assert daemon._trace_header("NULL", 7) == {"id_token": "NULL", "sequence": "7"}


class TestTraceEventCode:
    """The inspector gets the SIA event code of the frame actually sent."""

    @pytest.mark.parametrize("code", ["BA", "RP", "OP"])
    def test_code_read_from_clear_frame(self, code: str) -> None:
        """
        An unencrypted frame yields its own event code, whatever the default.

        Expected result:
        - {"event_code": <code>} read from the data field, not from the default
        """
        daemon = _daemon()
        daemon._last_sent_frame = SIAMessageBuilder("SIA").encode_message(_ACCOUNT, code)

        # Assert: code read from the frame
        assert daemon._trace_event_code("ZZ") == {"event_code": code}

    def test_code_read_with_area_prefix(self) -> None:
        """
        A DC-03 area prefix (Nri1/CL001) does not hide the code.

        Expected result:
        - {"event_code": "CL"}
        """
        daemon = _daemon()
        daemon._last_sent_frame = SIAMessageBuilder("SIA").encode_message(
            _ACCOUNT, "CL", extended_data={"area": "1", "zone": "001"})

        # Assert: area prefix skipped
        assert daemon._trace_event_code() == {"event_code": "CL"}

    def test_encrypted_frame_falls_back_to_default(self) -> None:
        """
        An encrypted frame has no readable code: the caller's default is used.

        Expected result:
        - default given -> {"event_code": default}
        - no default -> {}
        """
        daemon = _daemon(encrypted=True)
        daemon._last_sent_frame = SIAMessageBuilder("SIA").encode_message(
            _ACCOUNT, "BA", encryption=True, encryption_key=_KEY)

        # Assert: default used for an alarm, nothing for supervision
        assert daemon._trace_event_code("BA") == {"event_code": "BA"}
        assert daemon._trace_event_code() == {}

    def test_supervision_frame_has_no_code(self) -> None:
        """
        The NULL supervision body must not match as a "NU" code.

        Expected result:
        - {}
        """
        daemon = _daemon()
        daemon._last_sent_frame = SIAMessageBuilder("NULL").encode_message(_ACCOUNT, "NULL")

        # Assert: no event code
        assert daemon._trace_event_code() == {}

    @pytest.mark.asyncio
    async def test_alarm_dialog_carries_code_and_transition(self) -> None:
        """
        A NAK-then-ACK event traces event_code and transition; supervision has no code.

        Expected result:
        - alarm dialogs all carry event_code BA and a transition
        - one of them is nak_retry
        - the supervision dialog has no event_code
        """
        daemon = _daemon()
        _wire(daemon, _simulator(nak_first=1))
        await daemon._send_with_retry(_event(), max_retries=2)
        _wire(daemon, _simulator())
        await daemon._send_supervision()

        dialogs = [c.args[0]["dialog"] for c in daemon._send_callback.call_args_list
                   if c.args[0].get("type") == "message_trace"]
        alarms = [d for d in dialogs if d["dialog_type"] == "alarm"]
        supervisions = [d for d in dialogs if d["dialog_type"] == "supervision"]

        # Assert: code and transition on every alarm dialog
        assert alarms and all(d["event_code"] == "BA" and d["transition"] for d in alarms)
        # Assert: the NAK retry is flagged
        assert "nak_retry" in [d["transition"] for d in alarms]
        # Assert: supervision keeps no code
        assert supervisions and all("event_code" not in d for d in supervisions)
