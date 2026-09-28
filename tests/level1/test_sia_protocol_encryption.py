"""
Encrypted frame encoding tests (story 1-5, AC2/AC9)

Level 1 Unit Tests: SIAMessageBuilder.encode_message / make_supervision_message
with encryption=True, checked with the independent oracle
(tests/level1/_dc09_crypto_oracle.py), never with SIACipher.

Reference: SIA DC-09-2021 § 5.4.3 - 5.4.7, § 5.5.1.2/3/5/9, § 5.5.2.1
"""

import re
from datetime import datetime, timezone
from pathlib import Path
import pytest
from resources.siadc09d.sia_crypto import AESKeyError, SIACipher
from resources.siadc09d.sia_protocol import (
    ENCRYPTED_SUPERVISION_TOKEN,
    MAX_MESSAGE_LENGTH,
    SIAMessageBuilder,
    SIAProtocolError,
    parse_frame_header,
)
from tests.level1._dc09_crypto_oracle import (
    crc16_arc,
    iobroker_parse_event,
    oracle_region,
    split_frame,
    split_wire,
)

KEY_128 = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
KEY_192 = bytes.fromhex("0123456789ABCDEF" * 3)
KEY_256 = bytes.fromhex("0123456789ABCDEF" * 4)
TS = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
TS_STR = "_12:00:00,09-27-2026"
GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden" / "frames_encrypted_alarm.hex"


def _p_pad(n: int) -> bytes:
    return b"p" * n


@pytest.fixture
def builder() -> SIAMessageBuilder:
    return SIAMessageBuilder(crc_format="SIA")


def _check_crc_len(frame: bytes) -> str:
    crc, length, body = split_frame(frame)
    # CRC-16/ARC computed over the wire body, hex included (§ 5.5.1.2)
    assert crc == f"{crc16_arc(body.encode('ascii')):04X}"
    # Length is "0" + 3 hex digits of the body length (§ 5.5.1.3)
    assert length == f"0{len(body):03X}"
    return body


@pytest.mark.parametrize("key", [KEY_128, KEY_192, KEY_256])
@pytest.mark.parametrize("extended", [{}, {"zone": "001"}, {"media_url": "http://cam/snap.jpg"}])
def test_encrypted_event_decrypts_with_oracle(builder, key, extended):
    """An encrypted event frame is `"*SIA-DCS"seq L0#acct[<hex>]` (D1 reverted 2026-09-28).

    - header fields stay in clear
    - oracle decrypts to pad + '|' + data (']' included) + ext + timestamp
    - pad has no '|', '[' or ']'; total region a multiple of 16
    - CRC/length computed over the wire body
    """
    frame = builder.encode_message("001234", "BA", extended_data=extended, timestamp=TS,
                                   encryption=True, encryption_key=key)
    body = _check_crc_len(frame)
    # Clear header then '[' then hex then ']' (D1 reverted: live AC11 evidence
    # against ioBroker.sia showed its parser requires the closing bracket)
    assert re.fullmatch(r'"\*SIA-DCS"0001L0#001234\[[0-9A-F]+\]', body)
    _, hex_text = split_wire(body)
    pad, content = oracle_region(hex_text, key)
    zone = " 001" if extended.get("zone") else ""
    ext = "[Vhttp://cam/snap.jpg]" if extended.get("media_url") else ""
    # Region content is data (with its ']') + extended data + timestamp (§ 5.4.3)
    assert content == f"#001234|BA{zone}]{ext}{TS_STR}".encode()
    # Pad free of delimiters (§ 5.4.4.2)
    assert not set(pad) & set(b"|[]")
    # Region is block aligned
    assert (len(pad) + 1 + len(content)) % 16 == 0


def test_encrypted_event_without_timestamp_gets_utc_now(builder):
    """timestamp=None with encryption=True inserts the current UTC time (§ 5.5.1.9).

    - decrypted content ends with a timestamp within a few seconds of now
    """
    before = datetime.now(timezone.utc).replace(microsecond=0)
    frame = builder.encode_message("001234", "BA", encryption=True, encryption_key=KEY_128)
    _, hex_text = split_wire(split_frame(frame)[2])
    _, content = oracle_region(hex_text, KEY_128)
    ts = datetime.strptime(content.decode().split("]_")[1], "%H:%M:%S,%m-%d-%Y").replace(tzinfo=timezone.utc)
    # Timestamp is present and current
    assert abs((ts - before).total_seconds()) <= 5


def test_unencrypted_without_timestamp_unchanged(builder):
    """The unencrypted path keeps timestamp=None meaning no timestamp.

    - frame is exactly the pre-1-5 form
    """
    frame = builder.encode_message("001234", "BA")
    # Unencrypted, untimestamped frame unchanged
    assert split_frame(frame)[2] == '"SIA-DCS"0001L0#001234[#001234|BA]'


def test_encryption_without_key_raises(builder):
    """encryption=True with no key raises AESKeyError; marker-only frames are impossible.

    - AESKeyError raised for event and supervision
    """
    # Event without key rejected
    with pytest.raises(AESKeyError):
        builder.encode_message("001234", "BA", encryption=True)
    # Supervision without key rejected
    with pytest.raises(AESKeyError):
        builder.make_supervision_message("001234", encryption=True)


def test_explicit_seq_bypasses_tracker(builder):
    """seq= reuses a wire seq for retries (§ 5.5.1.5, F.5) without consuming a number.

    - retry frame carries the given seq
    - next tracked frame continues from the tracker
    """
    first = builder.encode_message("001234", "BA", timestamp=TS)
    retry = builder.encode_message("001234", "BA", timestamp=TS, seq=parse_frame_header(first)[1])
    nxt = builder.encode_message("001234", "BA", timestamp=TS)
    # Retry reuses the first attempt's seq
    assert parse_frame_header(retry)[1] == "0001"
    # Tracker not advanced by the explicit seq
    assert parse_frame_header(nxt)[1] == "0002"


@pytest.mark.parametrize("bad", ["1", "00001", "abcd", "0000"])
def test_explicit_seq_must_be_4_digits(builder, bad):
    """seq= must be 4 decimal digits 0001-9999.

    - SIAProtocolError otherwise
    """
    # Invalid explicit seq rejected
    with pytest.raises(SIAProtocolError):
        builder.encode_message("001234", "BA", seq=bad)


@pytest.mark.parametrize("encryption", [False, True])
def test_length_guard_at_0xfff(builder, encryption):
    """A wire message over 0xFFF characters raises SIAProtocolError (§ 5.5.1.3).

    Real AES-CBC ciphertext hex only grows in 32-char (16-byte block) steps,
    so growing the plaintext one byte at a time cannot land exactly on 4095
    for the encrypted case — this test only checks the guard is within one
    block of the limit there. See test_length_boundary_exact_encrypted for a
    single-character-precise check of the encrypted case (review finding
    2026-09-28).

    - the guard never lets a message through over 4095 characters
    - for the encrypted case, the largest accepted message is within one
      AES block (32 hex chars) of the limit
    - for the plain case, exactly 4095 characters encodes, 4096 raises
    """
    kwargs = {"encryption": encryption, "encryption_key": KEY_128 if encryption else None, "timestamp": TS}

    def body_len(url_len: int) -> int:
        frame = builder.encode_message("001234", "BA", extended_data={"media_url": "u" * url_len}, **kwargs)
        return len(split_frame(frame)[2])

    # Largest URL that still encodes (the encrypted body grows 32 hex chars per 16-byte block)
    url_len = (MAX_MESSAGE_LENGTH - 200) // 2 if encryption else MAX_MESSAGE_LENGTH - 100
    last_ok = body_len(url_len)
    while True:
        try:
            last_ok = body_len(url_len)
        except SIAProtocolError:
            break
        url_len += 1
    # Largest accepted message fits the 3-hex-digit length field
    assert last_ok <= MAX_MESSAGE_LENGTH
    # And sits right under the limit, so the guard is not over-strict
    assert last_ok > MAX_MESSAGE_LENGTH - (32 if encryption else 1)


def test_length_boundary_exact_plain(builder):
    """Unencrypted: body of exactly 4095 chars encodes, 4096 raises.

    - boundary precise to one character
    """
    base = builder.encode_message("001234", "BA", extended_data={"media_url": "u"}, timestamp=TS)
    n = MAX_MESSAGE_LENGTH - len(split_frame(base)[2]) + 1
    frame = builder.encode_message("001234", "BA", extended_data={"media_url": "u" * n}, timestamp=TS)
    # Exactly 4095 characters accepted
    assert len(split_frame(frame)[2]) == MAX_MESSAGE_LENGTH
    # 4096 characters rejected
    with pytest.raises(SIAProtocolError):
        builder.encode_message("001234", "BA", extended_data={"media_url": "u" * (n + 1)}, timestamp=TS)


def test_length_boundary_exact_encrypted(builder, monkeypatch):
    """Encrypted: body of exactly 4095 chars encodes, 4096 raises (review finding 2026-09-28).

    Real ciphertext hex only grows in 32-char steps (§ 5.4.4's 16-byte
    blocks), so the length guard's own arithmetic (``len(message_core) >
    MAX_MESSAGE_LENGTH``) can never be exercised at single-character
    precision by growing a real encrypted payload. This stubs
    ``SIACipher.encrypt`` to return a hex string exactly as long as its
    input, isolating the guard's arithmetic from AES block quantization,
    the same way test_length_boundary_exact_plain checks the plain path.

    - boundary precise to one character, for the encrypted wire message too
    """
    monkeypatch.setattr(SIACipher, "encrypt", lambda self, content: "A" * len(content))
    kwargs = {"encryption": True, "encryption_key": KEY_128, "timestamp": TS}
    base = builder.encode_message("001234", "BA", extended_data={"media_url": "u"}, **kwargs)
    n = MAX_MESSAGE_LENGTH - len(split_frame(base)[2]) + 1
    frame = builder.encode_message("001234", "BA", extended_data={"media_url": "u" * n}, **kwargs)
    # Exactly 4095 characters accepted
    assert len(split_frame(frame)[2]) == MAX_MESSAGE_LENGTH
    # 4096 characters rejected
    with pytest.raises(SIAProtocolError):
        builder.encode_message("001234", "BA", extended_data={"media_url": "u" * (n + 1)}, **kwargs)


def test_encrypted_supervision_is_null_message(builder):
    """Encrypted supervision is `"*NULL"0000L0#acct[<hex>]`, region pad|]_ts (§ 5.5.2.1, § 5.4.4.3).

    - token *NULL, seq 0000, ']' after the hex (D1 reverted 2026-09-28)
    - decrypted content is ']' + timestamp, with the '|' present
    - does not consume a tracker seq
    """
    frame = builder.make_supervision_message("001234", encryption=True, encryption_key=KEY_128, timestamp=TS)
    body = _check_crc_len(frame)
    # Null Message header with literal 0000 seq, closing ']' after the hex
    assert re.fullmatch(r'"\*NULL"0000L0#001234\[[0-9A-F]+\]', body)
    pad, content = oracle_region(split_wire(body)[1], KEY_128)
    # Region content is ']' + timestamp after the mandatory '|'
    assert content == f"]{TS_STR}".encode()
    # Tracker untouched: next event is seq 0001
    assert parse_frame_header(builder.encode_message("001234", "BA"))[1] == "0001"
    # Default token constant is *NULL (D2)
    assert ENCRYPTED_SUPERVISION_TOKEN == "NULL"


def test_encrypted_supervision_without_timestamp_uses_now(builder):
    """Encrypted supervision always carries a timestamp.

    - decrypted content matches ]_HH:MM:SS,MM-DD-YYYY
    """
    frame = builder.make_supervision_message("001234", encryption=True, encryption_key=KEY_128)
    _, content = oracle_region(split_wire(split_frame(frame)[2])[1], KEY_128)
    # Timestamp present
    assert re.fullmatch(rb"\]_\d\d:\d\d:\d\d,\d\d-\d\d-\d{4}", content)


def test_unencrypted_supervision_unchanged(builder):
    """Unencrypted supervision stays the field-validated SIA-DCS/0000 form (D-86).

    - body is "SIA-DCS"0001L0#001234[#001234|0000]
    """
    frame = builder.make_supervision_message("001234")
    # Unchanged plaintext supervision
    assert split_frame(frame)[2] == '"SIA-DCS"0001L0#001234[#001234|0000]'


def test_parse_frame_header(builder):
    """parse_frame_header returns (token, seq) of a built frame.

    - encrypted event, encrypted NULL and plain event
    """
    enc = builder.encode_message("001234", "BA", encryption=True, encryption_key=KEY_128)
    null = builder.make_supervision_message("001234", encryption=True, encryption_key=KEY_128)
    plain = builder.encode_message("001234", "BA")
    # Encrypted event header
    assert parse_frame_header(enc) == ("*SIA-DCS", "0001")
    # Encrypted NULL header
    assert parse_frame_header(null) == ("*NULL", "0000")
    # Plain event header
    assert parse_frame_header(plain) == ("SIA-DCS", "0002")


def test_iobroker_port_parses_our_event_frames(builder):
    """ioBroker.sia's decrypt/parse path (Python port) accepts our encrypted events.

    - account, data and timestamp recovered, extended data included
    - *NULL is not parseable by ioBroker (documented limitation, D2 risk)
    """
    frame = builder.encode_message("001234", "BA", extended_data={"zone": "001", "media_url": "http://c/s.jpg"},
                                   timestamp=TS, encryption=True, encryption_key=KEY_128)
    parsed = iobroker_parse_event(split_frame(frame)[2], KEY_128)
    # ioBroker recovers account, data, extended data and timestamp
    assert (parsed["act"], parsed["data"], parsed["extended"], parsed["ts"]) == (
        "001234", "#001234|BA 001", "Vhttp://c/s.jpg", TS_STR[1:])
    null = builder.make_supervision_message("001234", encryption=True, encryption_key=KEY_128, timestamp=TS)
    # ioBroker has no *NULL branch at all
    with pytest.raises(ValueError):
        iobroker_parse_event(split_frame(null)[2], KEY_128)


def test_deterministic_golden_vector():
    """Fixed key + injected 'p' pad + fixed timestamp gives the golden frame (regression guard).

    - encode output equals tests/fixtures/golden/frames_encrypted_alarm.hex
    """
    builder = SIAMessageBuilder(crc_format="SIA", pad_source=_p_pad)
    frame = builder.encode_message("001234", "1130", timestamp=datetime(2026, 4, 9, 14, 23, 45, tzinfo=timezone.utc),
                                   encryption=True, encryption_key=KEY_128)
    lines = [ln for ln in GOLDEN.read_text().splitlines() if ln and not ln.startswith("#")]
    # Golden fixture matches byte for byte
    assert bytes.fromhex(lines[0].replace(" ", "")) == frame
