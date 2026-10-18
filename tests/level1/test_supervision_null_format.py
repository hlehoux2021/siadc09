"""
Story 17-2: supervision_format "null" builds the real Null Message (§ 5.5.2.1).

Level 1 Unit Tests: SIAMessageBuilder.make_supervision_message(supervision_format=...)
checked against the decoder and the CSR simulator parser.

Reference: SIA DC-09-2021 § 5.5.2.1 (Null Message), § 5.4.4.3
"""
import re
from datetime import datetime, timezone

import pytest

from resources.siadc09d.csr_simulator import CSRSimulator
from resources.siadc09d.sia_protocol import (
    SIAMessageBuilder,
    SIAProtocolError,
    decode,
    parse_frame_header,
)
from tests.level1._dc09_crypto_oracle import oracle_region, split_frame, split_wire

KEY = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
TS = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
TS_STR = "_12:00:00,09-27-2026"


@pytest.fixture
def builder() -> SIAMessageBuilder:
    return SIAMessageBuilder(crc_format="SIA")


@pytest.mark.golden_frames
def test_clear_null_golden_frame(builder):
    """Clear null frame is exactly "NULL"0000L0#001234[]_ts.

    Expected result:
    - body matches the § 5.5.2.1 template, CRC/length valid per the oracle split
    """
    frame = builder.make_supervision_message("001234", timestamp=TS, supervision_format="null")
    # Body is the clear Null Message template
    assert split_frame(frame)[2] == f'"NULL"0000L0#001234[]{TS_STR}'


def test_clear_null_without_timestamp_uses_now(builder):
    """A clear null frame always carries a timestamp.

    Expected result:
    - body matches "NULL"0000L0#001234[]_HH:MM:SS,MM-DD-YYYY
    """
    frame = builder.make_supervision_message("001234", supervision_format="null")
    # Timestamp present although none was passed
    assert re.fullmatch(r'"NULL"0000L0#001234\[\]_\d\d:\d\d:\d\d,\d\d-\d\d-\d{4}', split_frame(frame)[2])


def test_null_does_not_consume_tracker_and_ignores_seq(builder):
    """Null never draws a tracker seq and keeps 0000 even with an explicit seq.

    Expected result:
    - header ("NULL", "0000") for clear, with and without seq=
    - the next event is still seq 0001
    """
    first = builder.make_supervision_message("001234", supervision_format="null")
    resend = builder.make_supervision_message("001234", supervision_format="null", seq="0007")
    # Both headers use seq 0000
    assert parse_frame_header(first) == ("NULL", "0000")
    assert parse_frame_header(resend) == ("NULL", "0000")
    # Tracker untouched
    assert parse_frame_header(builder.encode_message("001234", "BA"))[1] == "0001"


def test_encrypted_null_is_star_null(builder):
    """Encrypted null is the real "*NULL"0000L0#acct[<cipher> frame.

    Expected result:
    - header ("*NULL", "0000"), tracker not consumed
    - decrypted region is "]" + timestamp
    """
    frame = builder.make_supervision_message(
        "001234", encryption=True, encryption_key=KEY, timestamp=TS, supervision_format="null")
    body = split_frame(frame)[2]
    # Real *NULL header
    assert re.fullmatch(r'"\*NULL"0000L0#001234\[[0-9A-F]+', body)
    _, content = oracle_region(split_wire(body)[1], KEY)
    # Region is the empty data field close + timestamp
    assert content == f"]{TS_STR}".encode()
    # Tracker not consumed
    assert parse_frame_header(builder.encode_message("001234", "BA"))[1] == "0001"


def test_sia_dcs_format_is_default_and_unchanged(builder):
    """The default format and the explicit sia-dcs format give the same frame.

    Expected result:
    - clear body "SIA-DCS"0001L0#001234[#001234|0000], explicit format identical in shape
    """
    default = builder.make_supervision_message("001234")
    explicit = builder.make_supervision_message("001234", supervision_format="sia-dcs")
    # Default is the D-86 frame
    assert split_frame(default)[2] == '"SIA-DCS"0001L0#001234[#001234|0000]'
    # Explicit sia-dcs is the same form (next tracker seq)
    assert split_frame(explicit)[2] == '"SIA-DCS"0002L0#001234[#001234|0000]'


def test_unknown_format_rejected(builder):
    """An unknown format is a protocol error, not a silent fallback.

    Expected result:
    - SIAProtocolError
    """
    with pytest.raises(SIAProtocolError):
        builder.make_supervision_message("001234", supervision_format="keepalive")


def test_decoder_accepts_clear_and_encrypted_null(builder):
    """The decoder parses both null forms.

    Expected result:
    - clear: token NULL, seq 0, account 001234, CRC valid
    - encrypted: token NULL, encrypted True, seq 0
    """
    clear = decode(builder.make_supervision_message(
        "001234", timestamp=TS, supervision_format="null").hex())
    enc = decode(builder.make_supervision_message(
        "001234", encryption=True, encryption_key=KEY, timestamp=TS, supervision_format="null").hex(), key=KEY)
    # Clear null decoded
    assert (clear.id_token, clear.sequence, clear.account, clear.crc_valid) == ("NULL", 0, "001234", True)
    # Encrypted null decoded
    assert (enc.id_token, enc.encrypted, enc.sequence) == ("NULL", True, 0)


def test_simulator_accepts_clear_null(builder):
    """The CSR simulator classifies the clear null frame as NULL.

    Expected result:
    - type NULL, seq 0, account 001234
    """
    sim = CSRSimulator(0, 0, {"crc_format": "hex", "account_number": "001234"})
    frame = SIAMessageBuilder(crc_format="SIA").make_supervision_message(
        "001234", timestamp=TS, supervision_format="null")
    parsed = sim._parse_received_message(frame, sim.preset)
    # Simulator parses the clear Null Message
    assert (parsed["type"], parsed["seq"], parsed["account"]) == ("NULL", 0, "001234")
