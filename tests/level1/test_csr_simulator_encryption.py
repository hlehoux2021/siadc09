"""CSR simulator as an encrypting DC-09 receiver (story 1-5 AC8).

Covers inbound decryption, the spec-format ``*ACK``, the § 5.5.3.2 NAK
template, NAK-first mode, the timestamp window and the UDP buffer size.
Encrypted ACKs are checked with the independent oracle, not with SIACipher.
"""

import asyncio
import socket
from contextlib import suppress
from datetime import datetime, timedelta, timezone

import pytest

from resources.siadc09d.csr_simulator import (
    DEFAULT_TIMESTAMP_WINDOW_S,
    UDP_RECEIVE_BUFFER_SIZE,
    CSRSimulator,
    CSRSimulatorPreset,
)
from resources.siadc09d.sia_crypto import SIACipher
from resources.siadc09d.sia_protocol import (
    MAX_MESSAGE_LENGTH,
    SIAMessageBuilder,
    decode_ack_nak,
    parse_nak_timestamp,
)
from tests.harness.run_harness import _get_free_port
from tests.level1._dc09_crypto_oracle import crc16_arc, oracle_region, split_frame

_KEY = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
_OTHER_KEY = bytes.fromhex("FEDCBA9876543210FEDCBA9876543210")
_ACCOUNT = "000001"
_TS = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
_UDP_TIMEOUT_S = 3.0


def _preset(key: bytes | None = _KEY) -> CSRSimulatorPreset:
    """Hex-CRC preset for account 000001 with the given key."""
    return {"crc_format": "hex", "account_number": _ACCOUNT, "encryption_key": key}


def _event(key: bytes = _KEY, ts: datetime | None = _TS, **extra: object) -> bytes:
    """Encrypted BA event from account 000001."""
    return SIAMessageBuilder(crc_format="SIA").encode_message(
        _ACCOUNT, "BA", timestamp=ts, encryption=True, encryption_key=key, **extra)


def _null(key: bytes = _KEY, ts: datetime | None = _TS) -> bytes:
    """Encrypted *NULL from account 000001."""
    return SIAMessageBuilder(crc_format="SIA").make_supervision_message(
        _ACCOUNT, encryption=True, encryption_key=key, timestamp=ts)


def _wire_frame(body: str) -> bytes:
    """LF CRC LEN body CR with the CRC and length computed over body."""
    raw = body.encode("windows-1252")
    return b"\n" + f"{crc16_arc(raw):04X}0{len(raw):03X}".encode() + raw + b"\r"


class TestInboundEncrypted:
    """Inbound *-frames are decrypted and classified from the plaintext."""

    def test_encrypted_event_classified_from_plaintext(self) -> None:
        """
        An encrypted event decrypts to ALARM with its seq and account.

        Expected result:
        - type ALARM, seq 1, account 000001, encrypted True
        - the plaintext timestamp is reported
        """
        sim = CSRSimulator(0, 0, _preset())
        parsed = sim._parse_received_message(_event(), sim.preset)
        # Assert: classification and header data
        assert (parsed["type"], parsed["seq"], parsed["account"]) == ("ALARM", 1, _ACCOUNT)
        # Assert: encryption flag and plaintext timestamp
        assert parsed["encrypted"] is True and parsed["timestamp"] == _TS

    def test_encrypted_null_recognised(self) -> None:
        """
        An encrypted *NULL is a NULL with seq 0 and the header account.

        Expected result:
        - type NULL, seq 0, account 000001
        - ACK decision
        """
        sim = CSRSimulator(0, 0, _preset())
        parsed = sim._parse_received_message(_null(), sim.preset)
        # Assert: Null Message recognised
        assert (parsed["type"], parsed["seq"], parsed["account"]) == ("NULL", 0, _ACCOUNT)
        # Assert: a matching NULL is acknowledged
        assert sim._decide_response(parsed, sim.preset) == "ACK"

    def test_plain_null_token_recognised(self) -> None:
        """
        An unencrypted "NULL" token frame is a NULL too (§ 5.5.2.1).

        Expected result:
        - type NULL, account 000001
        """
        sim = CSRSimulator(0, 0, _preset(None))
        parsed = sim._parse_received_message(_wire_frame(f'"NULL"0000L0#{_ACCOUNT}[]'), sim.preset)
        # Assert: plain Null Message recognised
        assert (parsed["type"], parsed["account"]) == ("NULL", _ACCOUNT)

    def test_account_taken_from_plaintext(self) -> None:
        """
        The account inside the ciphertext wins over the clear header.

        Expected result:
        - account ABCDEF (plaintext), not 000001 (header)
        - NAK, because ABCDEF is not the configured account
        """
        region = SIACipher(_KEY).encrypt(b"#ABCDEF|BA]_10:00:00,09-28-2026")
        frame = _wire_frame(f'"*SIA-DCS"0001L0#{_ACCOUNT}[{region}')
        sim = CSRSimulator(0, 0, _preset())
        parsed = sim._parse_received_message(frame, sim.preset)
        # Assert: plaintext account used
        assert parsed["account"] == "ABCDEF"
        # Assert: account mismatch is NAKed
        assert sim._decide_response(parsed, sim.preset) == "NAK"

    @pytest.mark.parametrize("sim_key", [_OTHER_KEY, None], ids=["wrong_key", "no_key"])
    @pytest.mark.parametrize("build_frame", [_event, _null], ids=["event", "null"])
    def test_undecryptable_frame_discarded_silently(
        self, sim_key: bytes | None, build_frame
    ) -> None:
        """
        A frame the simulator cannot decrypt gets no ACK and no NAK (§ 5.6.2.4).

        Covers both an encrypted event and an encrypted *NULL supervision
        frame (review finding 2026-09-28: only the event case was covered).

        Expected result:
        - decision DISCARD
        - _build_response returns no frame
        """
        sim = CSRSimulator(0, 0, _preset(sim_key))
        frame = build_frame()
        parsed = sim._parse_received_message(frame, sim.preset)
        # Assert: discard decision
        assert sim._decide_response(parsed, sim.preset) == "DISCARD"
        # Assert: nothing is sent back
        assert sim._build_response(frame)[1] is None


class TestEncryptedAck:
    """The *ACK follows § 5.5.3.1 and is checked with the oracle."""

    def test_encrypted_ack_spec_format(self) -> None:
        """
        *ACK = "*ACK"seq<prefixes>#acct[hex of pad|]_ts], ']' after the hex (D1 reverted 2026-09-28).

        Expected result:
        - body header echoes seq, prefixes and account
        - CRC and length valid over the wire form
        - oracle decrypts to ']_10:00:00,09-28-2026'
        """
        sim = CSRSimulator(0, 0, _preset())
        ack = sim._generate_ack_frame(
            7, sim.preset, True, account="1234", receiver_prefix="R1", account_prefix="L0", timestamp=_TS)
        crc, length, body = split_frame(ack)
        header, _, hex_text = body.partition("[")
        hex_text = hex_text[:-1] if hex_text.endswith("]") else hex_text
        # Assert: echoed header
        assert header == '"*ACK"0007R1L0#1234'
        # Assert: CRC and length over the wire form
        assert (crc, length) == (f"{crc16_arc(body.encode()):04X}", f"0{len(body):03X}")
        # Assert: region content, and ']' after the hex
        assert oracle_region(hex_text, _KEY)[1] == b"]_10:00:00,09-28-2026" and body.endswith("]")

    def test_encrypted_ack_decodes_as_ack(self) -> None:
        """
        decode_ack_nak still classifies the *ACK as ACK with the right seq.

        Expected result:
        - type ACK, seq 7
        """
        sim = CSRSimulator(0, 0, _preset())
        decoded = decode_ack_nak(sim._generate_ack_frame(7, sim.preset, True), crc_format="hex")
        # Assert: PE-side classification unchanged
        assert (decoded["type"], decoded["seq"]) == ("ACK", 7)

    def test_encrypted_event_gets_encrypted_ack(self) -> None:
        """
        _build_response answers an encrypted event with an echoing *ACK.

        Expected result:
        - decision ACK, frame header '"*ACK"0001L0#000001['
        """
        sim = CSRSimulator(0, 0, _preset())
        decision, frame = sim._build_response(_event())
        # Assert: ACK decision
        assert decision == "ACK" and frame is not None
        # Assert: echoes the inbound header (no receiver prefix in the event)
        assert split_frame(frame)[2].startswith(f'"*ACK"0001L0#{_ACCOUNT}[')


class TestNak:
    """NAK template (§ 5.5.3.2), NAK-first mode and the timestamp window."""

    def test_nak_template_with_timestamp(self) -> None:
        """
        NAK = "NAK"0000R0L0#0[]_HH:MM:SS,MM-DD-YYYY, receiver clock time.

        Expected result:
        - template prefix exact
        - parse_nak_timestamp reads a time within 5 s of now
        """
        sim = CSRSimulator(0, 0, _preset())
        nak = sim._generate_nak_frame(sim.preset)
        # Assert: spec template
        assert split_frame(nak)[2].startswith('"NAK"0000R0L0#0[]_')
        # Assert: timestamp is the receiver's current time
        assert abs(parse_nak_timestamp(nak) - datetime.now(timezone.utc)) < timedelta(seconds=5)

    def test_nak_clock_skew(self) -> None:
        """
        clock_skew_s shifts the receiver clock carried by the NAK.

        Expected result:
        - NAK timestamp about one hour ahead
        """
        sim = CSRSimulator(0, 0, _preset(), clock_skew_s=3600)
        skew = parse_nak_timestamp(sim._generate_nak_frame(sim.preset)) - datetime.now(timezone.utc)
        # Assert: skew applied
        assert abs(skew - timedelta(hours=1)) < timedelta(seconds=5)

    def test_nak_without_timestamp(self) -> None:
        """
        nak_with_timestamp=False drops the timestamp (UTC-now fallback case).

        Expected result:
        - body is exactly '"NAK"0000R0L0#0[]'
        - decode_ack_nak still sees a NAK
        """
        sim = CSRSimulator(0, 0, _preset(), nak_with_timestamp=False)
        nak = sim._generate_nak_frame(sim.preset)
        # Assert: no timestamp
        assert split_frame(nak)[2] == '"NAK"0000R0L0#0[]'
        # Assert: still a NAK
        assert decode_ack_nak(nak, crc_format="hex")["type"] == "NAK"

    @pytest.mark.parametrize("make_frame", [_event, _null], ids=["event", "null"])
    def test_nak_first_then_ack(self, make_frame) -> None:
        """
        nak_first=1 NAKs the first event or *NULL and ACKs the retry.

        Expected result:
        - first NAK (plain, never encrypted), second ACK
        """
        sim = CSRSimulator(0, 0, _preset(), nak_first=1)
        first, nak = sim._build_response(make_frame())
        second, _ = sim._build_response(make_frame())
        # Assert: NAK once, then ACK
        assert (first, second) == ("NAK", "ACK")
        # Assert: the NAK is never encrypted
        assert split_frame(nak)[2].startswith('"NAK"')

    def test_default_window_is_spec(self) -> None:
        """
        The default window is +20/-40 s (§ 5.5.1.9).

        Expected result:
        - DEFAULT_TIMESTAMP_WINDOW_S == (20, 40)
        """
        # Assert: spec window
        assert DEFAULT_TIMESTAMP_WINDOW_S == (20.0, 40.0)

    @pytest.mark.parametrize(("offset_s", "expected"), [
        (0, "ACK"), (-30, "ACK"), (15, "ACK"), (-60, "NAK"), (30, "NAK"),
    ])
    def test_timestamp_window(self, offset_s: int, expected: str) -> None:
        """
        With the window on, encrypted frames outside +20/-40 s are NAKed.

        Expected result:
        - inside the window → ACK, outside → NAK
        """
        sim = CSRSimulator(0, 0, _preset(), timestamp_window_s=DEFAULT_TIMESTAMP_WINDOW_S)
        frame = _event(ts=datetime.now(timezone.utc) + timedelta(seconds=offset_s))
        # Assert: window decision
        assert sim._build_response(frame)[0] == expected

    def test_window_off_by_default(self) -> None:
        """
        Without timestamp_window_s, an old timestamp is still ACKed.

        Expected result:
        - ACK for a 2026-09-28 10:00 frame
        """
        sim = CSRSimulator(0, 0, _preset())
        # Assert: no window check by default
        assert sim._build_response(_event())[0] == "ACK"


class TestUdpBuffer:
    """Long encrypted frames are not truncated on UDP."""

    def test_buffer_holds_largest_frame(self) -> None:
        """
        The UDP buffer holds LF + CRC + LEN + 0xFFF + CR.

        Expected result:
        - UDP_RECEIVE_BUFFER_SIZE >= 4200 and >= the largest legal frame
        """
        # Assert: buffer size
        assert UDP_RECEIVE_BUFFER_SIZE >= max(4200, MAX_MESSAGE_LENGTH + 10)

    @pytest.mark.asyncio
    async def test_long_encrypted_frame_acked_over_udp(self) -> None:
        """
        A > 1024-byte encrypted event gets an encrypted ACK over real UDP.

        Expected result:
        - frame length > 1024
        - reply is a *ACK for seq 0001
        """
        udp_port = _get_free_port()
        sim = CSRSimulator(udp_port, _get_free_port(), _preset())
        frame = _event(extended_data={"media_url": "http://cam/" + "x" * 600})
        await sim.start()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(_UDP_TIMEOUT_S)
            sock.sendto(frame, ("127.0.0.1", udp_port))
            reply = await asyncio.get_running_loop().run_in_executor(None, lambda: sock.recv(UDP_RECEIVE_BUFFER_SIZE))
        finally:
            sock.close()
            with suppress(Exception):
                await sim.stop()
        # Assert: the frame really exceeds the old 1024-byte buffer
        assert len(frame) > 1024
        # Assert: encrypted ACK for the event
        assert split_frame(reply)[2].startswith('"*ACK"0001')
