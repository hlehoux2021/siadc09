"""
Independent DC-09 encryption oracle and external test vectors (story 1-5, AC9).

Nothing here imports ``resources.siadc09d``: the oracle is built directly on
``cryptography`` primitives so that tests of ``SIACipher`` / ``encode_message``
are not checked against the code under test.

External vectors were decrypted and CRC-checked on 2026-09-27. Sources:
- V1/V2: real Ajax hub traffic, https://github.com/eavanvalkenburg/pysiaalarm
  commits fc0fcfb (tests/run_re.py) and 894f8d6. Key used as ASCII bytes.
- V4: DC09Gen online generator (http://s545463982.onlinehome.us/DC09Gen/),
  quoted in ioBroker.sia and node-red-contrib-sia-ultimate. Hex key.
- V5: DC-09-2021 § 5.4.7 / Annex B.4 example. Key = 16 zero bytes. Its declared
  CRC/length (4B89/007B) are wrong and must not be used as an oracle.
- V6: pysiaalarm commit be4301b, tests/test_sia_package_cases.py. ``*NULL``
  with no ``|`` in the plaintext. ASCII key.
- V7: https://github.com/eyetowers/gosia @f76a848 parse_test.go:346-367, a
  real receiver ``*ACK`` with no ``|``. Hex key.
- S1: https://github.com/Swissdotnet/sia-dc-09-library @7437ae5
  ParsingStandardTest.java:180, ``*NULL`` with ``|``. Hex key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ZERO_IV = b"\x00" * 16


def oracle_aes_decrypt(hex_text: str, key: bytes) -> bytes:
    """Raw AES-CBC/zero-IV decryption of a hex ciphertext, no unpadding."""
    decryptor = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).decryptor()
    return decryptor.update(bytes.fromhex(hex_text)) + decryptor.finalize()


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC (poly 0xA001 reflected, init 0), per DC-09 § 5.5.1.2."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


_WIRE_RE = re.compile(r'^(?P<body>"(?P<token>[^"]+)".*?\[(?P<hex>[0-9A-Fa-f]+)\]?)$')


def split_wire(message: str) -> tuple[str, str]:
    """Return (token, hex) from a wire message ``"TOKEN"...[<hex>``."""
    match = _WIRE_RE.match(message)
    if match is None:
        raise ValueError("not an encrypted wire message")
    return match.group("token"), match.group("hex")


def split_frame(frame: bytes) -> tuple[str, str, str]:
    """Split ``LF CRC(4) LEN(4) body CR`` into (crc_hex, len_hex, body)."""
    text = frame.decode("windows-1252")
    if not (text.startswith("\n") and text.endswith("\r")):
        raise ValueError("frame must be LF ... CR")
    return text[1:5], text[5:9], text[9:-1]


def oracle_region(hex_text: str, key: bytes) -> tuple[bytes, bytes]:
    """Decrypt and split into (pad, content) at the first ``|``.

    Raises ValueError when there is no ``|`` (the oracle checks our encoder,
    which must always emit one).
    """
    plain = oracle_aes_decrypt(hex_text, key)
    idx = plain.find(b"|")
    if idx < 0:
        raise ValueError("no '|' pad terminator")
    return plain[:idx], plain[idx + 1:]


def iobroker_parse_event(message: str, key: bytes) -> dict:
    """Python port of ioBroker.sia's decrypt/parse path (src/lib/sia.ts).

    Only ``SIA-DCS``/``ADM-CID`` tokens are handled; ioBroker has no ``*NULL``
    branch at all, so a ``*NULL`` raises ValueError here as it fails there.
    """
    match = re.match(
        r'^"(\*?)(SIA-DCS|ADM-CID)"(\d{4})(R[0-9A-F]*)?(L[0-9A-F]*)?#([0-9A-F]+)\[([0-9A-Fa-f]+)\]?$',
        message)
    if match is None:
        raise ValueError("ioBroker: unsupported message")
    encrypted, token, seq, rpref, lpref, act, payload = match.groups()
    if encrypted:
        if len(key) not in (16, 24, 32):
            raise ValueError("ioBroker: key length")
        plain = oracle_aes_decrypt(payload, key).decode("utf-8", errors="replace")
        payload = plain[plain.index("|") + 1:]
    fields = re.match(r"(.+?)?\](\[(.*?)\])?(_(.+)){0,1}", payload)
    if fields is None:
        raise ValueError("ioBroker: payload")
    return {
        "token": token,
        "seq": seq,
        "rpref": rpref,
        "lpref": lpref,
        "act": act,
        "data": fields.group(1),
        "extended": fields.group(3),
        "ts": fields.group(5),
    }


@dataclass(frozen=True)
class Vector:
    name: str
    frame_body: str  # wire message ("..." to end), CRC/len stripped
    key: bytes
    plaintext: bytes  # full decrypted region, pad included
    crc: str | None  # declared CRC; None when not quoted / known wrong
    length: str | None


VECTORS: tuple[Vector, ...] = (
    Vector(
        "V1_ajax",
        '"*SIA-DCS"4480L0#EA1984[83F153789366885D5F83DD5A8D19F691DE6602D5D71342E244C040C5D10D89040444068312750F38DF7E63AD3DE8AD5A',
        b"3BD7E66AA9E2F190",
        b"v\nV\xb5\x02\xc0\xab|#EA1984|Nri0/RP0000]_16:57:20,08-11-2020",
        "85DF",
        "0078",
    ),
    Vector(
        "V2_ajax",
        '"*SIA-DCS"0764L0#EA1984[E759F1FE2FDBAF5B30AED69378DF87CF9DA82AA9292D0661E3EBA6DF2AD55AEA4D91968EE8460EC206B8AEAD69B33BCB',
        b"3BD7E66AA9E2F190",
        b"\xc6\n\xb9\xb7\xfa\xe9bA6-|#EA1984|Nri0/YG0]_12:56:10,07-17-2020",
        "021A",
        "0078",
    ),
    Vector(
        "V4_dc09gen",
        '"*SIA-DCS"9876R579BDFL789ABC#12345A[209c9d400b655df7a26aecb6a887e7ee6ed8103217079aae7cbd9dd7551e96823263460f7ef0514864897ae9789534f1',
        bytes.fromhex("0123456789ABCDEF0123456789ABCDEF"),
        b"ppppppppppppp|12345A|NFA129]_13:14:15,02-15-2006",
        None,
        None,
    ),
    Vector(
        "V5_spec",
        '"*ADM-CID"0001L0#1234[371baac130fe81508f556e6fd2ccfd8826e9ba186f0fb674bb87c079484e546dff35532aa285936a00c27b6feb053f68]',
        b"\x00" * 16,
        b"ppppppppp|#1234|1140 00 007]_22:49:34,01-22-2012",
        None,
        None,
    ),
    Vector(
        "V6_null_nopipe",
        '"*NULL"0000R0L0#AAAB[B4BC8B40D0E6D959D6BEA78E88CC0B2155741A3C44FBB96D476A3E557CAD64D9',
        b"AAAAAAAAAAAAAAAA",
        b"ppppppppppp]_18:24:52,07-05-2020",
        "76D8",
        "0055",
    ),
    Vector(
        "V7_gosia_ack",
        '"*ACK"0001L0#1001[FFAC5F1A3794837779D9C95762764263A68961C08ABD2942B4607F2321BF554A',
        bytes.fromhex("0123456789ABCDEF0123456789ABCDEF"),
        b"OKKTDDFXWNX]_13:41:10,04-30-2026",
        "C1B3",
        "0052",
    ),
    Vector(
        "S1_swiss_null",
        '"*NULL"0000RC0FFDL1234#080027E62A64[70D7DC480FA7DC0DE428CE02447BA2E2981A161EA14CB780D2CD917208059E11',
        bytes.fromhex("ABCD" * 8),
        b"L\xf8X\x8fI.\xeax\xcf\xae|]_13:43:09,06-22-2015",
        "CAC1",
        "0064",
    ),
)

# Expected region content (after the pad) for every vector.
EXPECTED_CONTENT: dict[str, bytes] = {
    "V1_ajax": b"#EA1984|Nri0/RP0000]_16:57:20,08-11-2020",
    "V2_ajax": b"#EA1984|Nri0/YG0]_12:56:10,07-17-2020",
    "V4_dc09gen": b"12345A|NFA129]_13:14:15,02-15-2006",
    "V5_spec": b"#1234|1140 00 007]_22:49:34,01-22-2012",
    "V6_null_nopipe": b"]_18:24:52,07-05-2020",
    "V7_gosia_ack": b"]_13:41:10,04-30-2026",
    "S1_swiss_null": b"]_13:43:09,06-22-2015",
}


def vector(name: str) -> Vector:
    return next(v for v in VECTORS if v.name == name)
