"""
SIA DC-09 AES-CBC Cipher Tests (story 1-5, AC1/AC9)

Level 1 Unit Tests (pytest): Pure Python, no I/O, no async.

Test coverage for SIACipher:
- Key validation (16/24/32 bytes) and hex key parsing
- Region encryption per DC-09-2021 § 5.4.4-5.4.7: random front pad + '|',
  AES-CBC with zero IV, uppercase hex output
- Decryption: byte-level pad strip at the first '|', ']' fallback for
  pipe-less *NULL/*ACK regions, clean errors on bad input
- External vectors (real Ajax hub, spec example, DC09Gen, gosia, Swissdotnet)
- An independent oracle (tests/level1/_dc09_crypto_oracle.py) built on raw
  `cryptography` primitives, never on SIACipher

Reference: SIA DC-09-2021 § 5.4.3 - 5.4.7
"""

import pytest
from resources.siadc09d.sia_crypto import (
    AESDecryptionError,
    AESEncryptionError,
    AESKeyError,
    SIACipher,
    parse_hex_key,
)
from tests.level1._dc09_crypto_oracle import (
    EXPECTED_CONTENT,
    VECTORS,
    oracle_aes_decrypt,
    oracle_region,
    split_wire,
    vector,
)


KEY_128 = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")
KEY_192 = bytes.fromhex("0123456789ABCDEF" * 3)
KEY_256 = bytes.fromhex("0123456789ABCDEF" * 4)
FORBIDDEN_PAD_BYTES = {0x7C, 0x5B, 0x5D}


def _fixed_pad(n: int) -> bytes:
    """Deterministic pad source for tests: 'p' * n (spec example style)."""
    return b"p" * n


@pytest.fixture
def cipher() -> SIACipher:
    """SIACipher bound to a fixed AES-128 key with the production pad source."""
    return SIACipher(KEY_128)


# ============================================================================
# Constants and key validation
# ============================================================================

def test_class_constants_follow_spec():
    """Class constants match DC-09 § 5.4.5/§ 5.4.6.

    - IV is 16 zero bytes
    - block size is 16
    - supported key sizes are 16, 24 and 32 bytes
    """
    # IV is 16 zero bytes (§ 5.4.6)
    assert SIACipher.IV == b"\x00" * 16
    # AES block size is 16 bytes
    assert SIACipher.BLOCK_SIZE == 16
    # AES-128/192/256 key sizes (§ 5.4.5)
    assert SIACipher.KEY_SIZES == (16, 24, 32)


def test_pad_alphabet_excludes_delimiters():
    """The default pad alphabet is printable ASCII minus '|', '[' and ']'.

    - every byte is in 0x20-0x7E
    - none of 0x7C, 0x5B, 0x5D appear
    """
    # All alphabet bytes are printable ASCII
    assert all(0x20 <= b <= 0x7E for b in SIACipher.PAD_ALPHABET)
    # No pipe or square bracket in the alphabet (§ 5.4.4.2)
    assert not FORBIDDEN_PAD_BYTES & set(SIACipher.PAD_ALPHABET)


@pytest.mark.parametrize("key", [KEY_128, KEY_192, KEY_256])
def test_accepts_128_192_256_bit_keys(key):
    """16, 24 and 32-byte keys construct a cipher.

    - no exception for each supported size
    """
    # Construction succeeds for a supported key size
    assert SIACipher(key) is not None


@pytest.mark.parametrize("key", [b"", b"x" * 15, b"x" * 17, b"x" * 33, None, "0123456789ABCDEF"])
def test_rejects_bad_keys_without_echoing_them(key):
    """Wrong-size, None and str keys raise AESKeyError.

    - AESKeyError raised
    - the message never contains the key value
    """
    with pytest.raises(AESKeyError) as exc:
        SIACipher(key)
    if key:
        # The key value is never echoed in the error
        assert str(key) not in str(exc.value) and repr(key) not in str(exc.value)


@pytest.mark.parametrize("text,size", [
    ("0123456789abcdef" * 2, 16),
    ("0123456789ABCDEF" * 3, 24),
    ("0123456789ABCDEF" * 4, 32),
    ("  " + "0123456789ABCDEF" * 2 + "\n", 16),
])
def test_parse_hex_key_accepts_32_48_64_hex_digits(text, size):
    """parse_hex_key decodes 32/48/64 hex digits (surrounding whitespace trimmed).

    - returns bytes of the matching AES key size
    """
    # Decoded key has the AES key size matching the hex length
    assert len(parse_hex_key(text)) == size


@pytest.mark.parametrize("text", [
    None, "", "0123", "0123456789ABCDEF",  # 16 hex digits = ASCII-style key (D-93)
    "0x" + "0123456789ABCDEF" * 2, "0123456789ABCDEF 0123456789ABCDEF",
    "G123456789ABCDEF0123456789ABCDEF", "0123456789ABCDEF" * 2 + "0",
])
def test_parse_hex_key_rejects_everything_else(text):
    """parse_hex_key rejects any other shape, never echoing the input.

    - AESKeyError raised
    - message does not contain the input
    """
    with pytest.raises(AESKeyError) as exc:
        parse_hex_key(text)
    if text:
        # Input is not echoed in the error message
        assert text.strip() not in str(exc.value)


# ============================================================================
# Encryption (§ 5.4.4 - 5.4.7)
# ============================================================================

@pytest.mark.parametrize("content_len", [0, 1, 14, 15, 16, 31, 32, 47, 200])
def test_encrypt_pads_front_to_block_multiple(content_len):
    """Region = pad + '|' + content; pad_len = 16 - (len('|'+content) % 16).

    - oracle decryption gives pad + '|' + content exactly
    - total length is a multiple of 16
    - pad length is 1..16, and 16 when '|'+content is already aligned
    """
    content = b"A" * content_len
    hex_text = SIACipher(KEY_128, pad_source=_fixed_pad).encrypt(content)
    plain = oracle_aes_decrypt(hex_text, KEY_128)
    expected_pad = 16 - ((content_len + 1) % 16)
    # Plaintext is exactly pad + '|' + content
    assert plain == b"p" * expected_pad + b"|" + content
    # Total length is a whole number of blocks
    assert len(plain) % 16 == 0
    # Pad length is never 0 (full block when aligned)
    assert 1 <= expected_pad <= 16


def test_encrypt_returns_uppercase_hex(cipher):
    """encrypt() returns uppercase hex ASCII (§ 5.4.7).

    - str of hex digits, no lowercase letters
    """
    hex_text = cipher.encrypt(b"#1234|NBA001]_12:00:00,09-27-2026")
    # Output is uppercase hex
    assert hex_text == hex_text.upper() and bytes.fromhex(hex_text)


def test_default_pad_is_random_and_never_uses_delimiters(cipher):
    """Production pad bytes come from the pad alphabet and vary per call.

    - no '|', '[' or ']' in any pad
    - two encryptions of the same content differ
    """
    content = b"#1234|NBA001]_12:00:00,09-27-2026"
    pads = []
    for _ in range(50):
        pad, recovered = oracle_region(cipher.encrypt(content), KEY_128)
        # Content survives after the first '|'
        assert recovered == content
        pads.append(pad)
    # No delimiter byte in any pad (§ 5.4.4.2)
    assert not any(FORBIDDEN_PAD_BYTES & set(p) for p in pads)
    # Pads are random: at most a handful of collisions in 50 draws, not the
    # near-constant generator a bare "len(set(pads)) > 1" would still pass
    # (review finding 2026-09-28)
    assert len(set(pads)) >= 45


@pytest.mark.parametrize("key", [KEY_128, KEY_192, KEY_256])
def test_oracle_decrypts_our_output_for_every_key_size(key):
    """The independent oracle decrypts SIACipher output for AES-128/192/256.

    - content recovered after the pad
    """
    content = b"#001234|NBA001]_12:00:00,09-27-2026"
    _, recovered = oracle_region(SIACipher(key).encrypt(content), key)
    # Content recovered by the oracle
    assert recovered == content


def test_bad_pad_source_is_rejected():
    """An injected pad containing '|' or of wrong length raises AESEncryptionError.

    - '|' in pad rejected
    - wrong length rejected
    """
    # Pad containing '|' is rejected
    with pytest.raises(AESEncryptionError):
        SIACipher(KEY_128, pad_source=lambda n: b"|" * n).encrypt(b"x")
    # Pad of the wrong length is rejected
    with pytest.raises(AESEncryptionError):
        SIACipher(KEY_128, pad_source=lambda n: b"p").encrypt(b"x")


def test_encrypt_rejects_non_bytes(cipher):
    """encrypt() needs bytes (callers encode str themselves).

    - AESEncryptionError for str input
    """
    # str content is rejected
    with pytest.raises(AESEncryptionError):
        cipher.encrypt("#1234|NBA001]")


def test_pkcs7_and_frame_aliases_removed():
    """PKCS#7 helpers and the encrypt_frame/decrypt_frame aliases are gone.

    - none of the old attributes exist
    """
    for name in ("_apply_pkcs7_padding", "_remove_pkcs7_padding", "encrypt_frame", "decrypt_frame", "KEY_SIZE"):
        # Old PKCS#7-era attribute removed
        assert not hasattr(SIACipher, name)


# ============================================================================
# Decryption
# ============================================================================

@pytest.mark.parametrize("content", [b"", b"]_12:00:00,09-27-2026", b"#1234|NBA001][Vhttp://x/y]_12:00:00,09-27-2026"])
def test_roundtrip(cipher, content):
    """decrypt(encrypt(x)) == x.

    - content returned without the pad and '|'
    """
    # Round trip returns the original content
    assert cipher.decrypt(cipher.encrypt(content)) == content


def test_decrypt_accepts_lowercase_hex(cipher):
    """Lowercase hex (ioBroker, RoslynServer2, DC09Gen) decrypts too.

    - same content as uppercase
    """
    hex_text = cipher.encrypt(b"#1234|NBA001]")
    # Lowercase hex decrypts to the same content
    assert cipher.decrypt(hex_text.lower()) == b"#1234|NBA001]"


def test_decrypt_strips_binary_pad_at_byte_level():
    """A binary pad (bytes >= 0x80, LF) is stripped before any text decoding.

    - V1 (real Ajax hub, pad contains 0x0A and 0xB5) gives the clean content
    """
    v1 = vector("V1_ajax")
    _, hex_text = split_wire(v1.frame_body)
    # Byte-level strip keeps the content intact
    assert SIACipher(v1.key).decrypt(hex_text) == EXPECTED_CONTENT["V1_ajax"]


@pytest.mark.parametrize("bad", ["", "ABC", "ZZ" * 16, "00" * 15, "00" * 17])
def test_decrypt_rejects_malformed_hex(cipher, bad):
    """Empty, odd-length, non-hex or non-block-multiple input raises AESDecryptionError.

    - AESDecryptionError raised
    """
    # Malformed ciphertext rejected cleanly
    with pytest.raises(AESDecryptionError):
        cipher.decrypt(bad)


def test_decrypt_with_wrong_key_fails_cleanly():
    """A wrong key yields AESDecryptionError, never a traceback or the original content.

    Uses a fixed pad source (review finding 2026-09-28: with the production
    random pad, this specific plaintext decrypts under the wrong key to
    garbage without a '|' or ']' about a third of the time and to garbage
    that happens to contain one the rest of the time — an either/or
    assertion couldn't tell a correctly-hardened decrypt from a subtly
    broken one apart. Fixing the pad makes the outcome deterministic, so a
    single, precise branch can be asserted).

    - AESDecryptionError, with the standard "no pad terminator" message
    """
    right_key_cipher = SIACipher(KEY_128, pad_source=_fixed_pad)
    hex_text = right_key_cipher.encrypt(b"#1234|NBA001]_12:00:00,09-27-2026")
    # Wrong key raises cleanly, it never silently recovers the original content
    with pytest.raises(AESDecryptionError, match="no pad terminator"):
        SIACipher(KEY_256).decrypt(hex_text)


def test_decrypt_error_never_contains_key_or_pad(cipher):
    """Decryption errors carry no key and no plaintext.

    - error text does not contain the key hex
    - error text does not contain the decrypted garbage plaintext either
      (review finding 2026-09-28: the docstring already claimed this, but
      only the key was actually checked)
    """
    ciphertext_hex = "00" * 16
    with pytest.raises(AESDecryptionError) as exc:
        cipher.decrypt(ciphertext_hex)
    error_text = str(exc.value)
    # Key hex not in the error text
    assert KEY_128.hex().upper() not in error_text.upper()
    # The decrypted garbage (computed independently, never returned by decrypt()
    # itself since it raised) is not in the error text either
    garbage = oracle_aes_decrypt(ciphertext_hex, KEY_128)
    assert garbage.decode('windows-1252') not in error_text


# ============================================================================
# External vectors (independent evidence)
# ============================================================================

@pytest.mark.parametrize("v", VECTORS, ids=lambda v: v.name)
def test_external_vector_decrypts_to_expected_content(v):
    """SIACipher.decrypt recovers the region content of every external vector.

    - V1/V2 real Ajax, V4 DC09Gen, V5 spec example, S1 Swissdotnet ('|' split)
    - V6 *NULL and V7 *ACK without '|' (']' fallback)
    """
    _, hex_text = split_wire(v.frame_body)
    # Content equals the known plaintext after the pad
    assert SIACipher(v.key).decrypt(hex_text) == EXPECTED_CONTENT[v.name]


@pytest.mark.parametrize("v", VECTORS, ids=lambda v: v.name)
def test_oracle_self_check_on_external_vectors(v):
    """The oracle itself decrypts every vector to its transcribed plaintext.

    - guards the oracle against being wrong in the same way as SIACipher
    """
    _, hex_text = split_wire(v.frame_body)
    # Oracle output equals the independently transcribed plaintext
    assert oracle_aes_decrypt(hex_text, v.key) == v.plaintext
