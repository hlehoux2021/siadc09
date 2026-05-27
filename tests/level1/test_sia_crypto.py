"""
SIA DC-09 AES-128 CBC Cipher Tests

Level 1 Unit Tests (pytest): Pure Python, no I/O, no async, no external dependencies.

Test coverage for SIACipher class:
- Key validation at construction
- AES-128 CBC encryption/decryption with fixed IV (per SIA DC-09 standard)
- PKCS#7 padding/unpadding
- Round-trip encryption/decryption
- Error handling (AESKeyError, AESEncryptionError, AESDecryptionError)
- SIA protocol frame integration
- Golden frame encryption/decryption (real SIA protocol frames)

Reference: SIA DC-09-2021 § 5.4 – 5.4.7 - Encryption Support
Expert validation: sia-dc09-expert skill
"""

import os
import pytest
from resources.siadc09d.sia_crypto import (
    SIACipher,
    AESKeyError,
    AESEncryptionError,
    AESDecryptionError,
)
from resources.siadc09d.sia_protocol import SIAMessageBuilder


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_key() -> bytes:
    """Fixture providing a deterministic test encryption key for reproducible tests.

    Note: This is a fixed test key (not random) to ensure tests are reproducible
    and can validate against golden ciphertexts.
    """
    return b'0123456789ABCDEF'


@pytest.fixture
def cipher(test_key: bytes) -> SIACipher:
    """Fixture providing a pre-built SIACipher bound to the test key.

    Use this in tests that just need to encrypt/decrypt. No need to construct
    the cipher yourself or manage key validation.
    """
    return SIACipher(test_key)


@pytest.fixture
def sia_builder() -> SIAMessageBuilder:
    """Fixture providing SIAMessageBuilder for generating test frames.

    Uses SIA CRC format (hex-encoded CRC per § 5.5.1.2).
    """
    return SIAMessageBuilder(crc_format="SIA")


# ============================================================================
# Class Constants Validation
# ============================================================================

def test_sia_cipher_key_size_constant():
    """Test that SIACipher.KEY_SIZE constant is exactly 16 (128-bit).

    Expected result:
    - SIACipher.KEY_SIZE == 16
    """
    assert SIACipher.KEY_SIZE == 16


def test_sia_cipher_block_size_constant():
    """Test that SIACipher.BLOCK_SIZE constant is exactly 16.

    Expected result:
    - SIACipher.BLOCK_SIZE == 16
    """
    assert SIACipher.BLOCK_SIZE == 16


def test_sia_cipher_iv_constant_is_16_zero_bytes():
    """Test that SIACipher.IV constant is exactly 16 zero bytes per SIA DC-09 standard.

    Expected result:
    - SIACipher.IV == b'\\x00' * 16 (16 zero bytes)
    - SIACipher.IV length is 16 bytes
    """
    assert SIACipher.IV == b'\x00' * 16
    assert len(SIACipher.IV) == 16


def test_error_classes_exist_and_inherit_from_exception():
    """Test that custom error classes are defined and properly inherit from Exception.

    Expected result:
    - AESKeyError is defined and is-a Exception
    - AESEncryptionError is defined and is-a Exception
    - AESDecryptionError is defined and is-a Exception
    """
    assert issubclass(AESKeyError, Exception)
    assert issubclass(AESEncryptionError, Exception)
    assert issubclass(AESDecryptionError, Exception)


# ============================================================================
# Constructor / Key Validation
# ============================================================================

def test_cipher_construction_with_valid_16_byte_key():
    """Test SIACipher construction with exactly 16-byte (128-bit) key.

    Expected result:
    - SIACipher(key) succeeds with valid 16-byte key
    - Cipher is ready for encrypt/decrypt
    """
    valid_key = os.urandom(16)
    cipher = SIACipher(valid_key)

    # Assert: cipher is constructed and usable
    assert cipher is not None


def test_cipher_construction_with_15_byte_key_raises_aeskeyerror():
    """Test SIACipher construction rejects keys shorter than 16 bytes.

    Expected result:
    - AESKeyError raised with message about key length
    """
    invalid_key = os.urandom(15)

    with pytest.raises(AESKeyError, match="16 bytes"):
        SIACipher(invalid_key)


def test_cipher_construction_with_17_byte_key_raises_aeskeyerror():
    """Test SIACipher construction rejects keys longer than 16 bytes.

    Expected result:
    - AESKeyError raised with message about key length
    """
    invalid_key = os.urandom(17)

    with pytest.raises(AESKeyError, match="16 bytes"):
        SIACipher(invalid_key)


def test_cipher_construction_with_none_raises_aeskeyerror():
    """Test SIACipher construction rejects None input.

    Expected result:
    - AESKeyError raised for None
    """
    with pytest.raises(AESKeyError):
        SIACipher(None)


def test_cipher_construction_with_32_byte_key_raises_aeskeyerror():
    """Test SIACipher construction rejects keys for AES-256 (not supported in this story).

    Expected result:
    - AESKeyError raised for 32-byte key
    """
    invalid_key = os.urandom(32)

    with pytest.raises(AESKeyError, match="16 bytes"):
        SIACipher(invalid_key)


def test_cipher_construction_with_string_key_raises_aeskeyerror():
    """Test SIACipher construction rejects string keys (not bytes).

    Expected result:
    - AESKeyError raised for non-bytes key even if correct length
    """
    key = "1234567890123456"  # 16 chars but not bytes

    with pytest.raises(AESKeyError):
        SIACipher(key)


# ============================================================================
# Encrypt/Decrypt Roundtrip Tests
# ============================================================================

def test_encrypt_decrypt_roundtrip_empty_plaintext(cipher):
    """Test AES-128 CBC encryption/decryption with empty plaintext (0 bytes).

    Expected result:
    - Empty plaintext encrypted produces 16-byte ciphertext (all PKCS#7 padding)
    - Decryption of 16-byte ciphertext returns empty plaintext
    - Round-trip validation: encrypt(b'') then decrypt() returns b''
    """
    plaintext = b''  # 0 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: round-trip succeeds for empty plaintext
    assert recovered == plaintext

    # Assert: ciphertext is 16 bytes (all padding per PKCS#7)
    assert len(ciphertext) == 16


def test_encrypt_decrypt_roundtrip_1_byte_plaintext(cipher):
    """Test AES-128 CBC encryption round-trip with 1-byte plaintext.

    Expected result:
    - plaintext (1 byte) encrypted and decrypted returns original
    - padding adds 15 bytes (PKCS#7)
    - encrypted data is 16 bytes (one AES block)
    """
    plaintext = b'X'  # 1 byte
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext length is multiple of 16 (after padding: 1 + 15 = 16)
    assert len(ciphertext) == 16


def test_encrypt_decrypt_roundtrip_15_byte_plaintext(cipher):
    """Test AES-128 CBC with plaintext 15 bytes (requires 1 byte padding).

    Expected result:
    - plaintext encrypted and decrypted returns original
    - encrypted data is 16 bytes (one AES block with 1-byte padding)
    """
    plaintext = b'0123456789ABCDE'  # 15 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext is 16 bytes (15 + 1 padding)
    assert len(ciphertext) == 16


def test_encrypt_decrypt_roundtrip_16_byte_plaintext(cipher):
    """Test AES-128 CBC with plaintext exactly 16 bytes (requires 16 bytes padding).

    Expected result:
    - plaintext encrypted and decrypted returns original
    - padding is applied even though plaintext == block size (PKCS#7 rule)
    - encrypted data is 32 bytes (two AES blocks: data + padding block)
    """
    plaintext = b'0123456789ABCDEF'  # 16 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext is 32 bytes (16 data + 16 padding per PKCS#7)
    assert len(ciphertext) == 32

    # Assert: encryption is deterministic (same plaintext + key = same ciphertext)
    ciphertext2 = cipher.encrypt(plaintext)
    assert ciphertext == ciphertext2


def test_encrypt_decrypt_roundtrip_17_byte_plaintext(cipher):
    """Test AES-128 CBC with plaintext 17 bytes (requires 15 bytes padding).

    Expected result:
    - plaintext encrypted and decrypted returns original
    - encrypted data is 32 bytes (16 data + 15 padding + 1)
    """
    plaintext = b'0123456789ABCDEF0'  # 17 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext is 32 bytes (17 + 15 padding)
    assert len(ciphertext) == 32


def test_encrypt_decrypt_roundtrip_31_byte_plaintext(cipher):
    """Test AES-128 CBC with plaintext 31 bytes (requires 1 byte padding).

    Expected result:
    - plaintext encrypted and decrypted returns original
    - encrypted data is 32 bytes
    """
    plaintext = b'0' * 31  # 31 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext is 32 bytes (31 + 1 padding)
    assert len(ciphertext) == 32


def test_encrypt_decrypt_roundtrip_32_byte_plaintext(cipher):
    """Test AES-128 CBC with plaintext 32 bytes (requires 16 bytes padding).

    Expected result:
    - plaintext encrypted and decrypted returns original
    - encrypted data is 48 bytes (32 data + 16 padding)
    """
    plaintext = b'0' * 32  # 32 bytes
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: recovered plaintext matches original
    assert recovered == plaintext

    # Assert: ciphertext is 48 bytes (32 + 16 padding)
    assert len(ciphertext) == 48


def test_encrypt_decrypt_roundtrip_256_byte_plaintext(cipher):
    """Test AES-128 CBC encryption with large plaintext (256 bytes).

    Expected result:
    - 256-byte plaintext encrypted and decrypted returns original
    - Ciphertext length is 272 bytes (256 data + 16 padding)
    - Scalability verified for multi-block plaintexts
    """
    plaintext = os.urandom(256)  # 16 AES blocks
    ciphertext = cipher.encrypt(plaintext)
    recovered = cipher.decrypt(ciphertext)

    # Assert: round-trip succeeds for large plaintext
    assert recovered == plaintext

    # Assert: ciphertext is 272 bytes (256 + 16 padding)
    assert len(ciphertext) == 272


# ============================================================================
# Determinism and Key Sensitivity
# ============================================================================

def test_encrypt_is_deterministic(cipher):
    """Test that encryption is deterministic (same input = same output).

    Expected result:
    - Encrypting same plaintext with same key twice produces identical ciphertext
    - (Due to fixed IV per SIA DC-09 standard, not random IV)
    """
    plaintext = b'deterministic test'
    cipher1 = cipher.encrypt(plaintext)
    cipher2 = cipher.encrypt(plaintext)

    # Assert: encryption is deterministic (fixed IV per SIA DC-09)
    assert cipher1 == cipher2


def test_encrypt_with_different_keys_produces_different_ciphertexts():
    """Test that different keys produce different ciphertexts for same plaintext.

    Expected result:
    - plaintext encrypted with key1 and key2 produces different ciphertexts
    - (IV is fixed per SIA DC-09, so only key differs)
    """
    plaintext = b'test message'
    key1 = os.urandom(16)
    key2 = os.urandom(16)

    cipher1 = SIACipher(key1).encrypt(plaintext)
    cipher2 = SIACipher(key2).encrypt(plaintext)

    # Assert: different keys produce different ciphertexts
    assert cipher1 != cipher2


def test_decrypt_with_wrong_key_fails_or_returns_garbage():
    """Test that decrypting with wrong key fails or returns incorrect plaintext.

    Expected result:
    - decrypt_message() with wrong key either:
      a) raises AESDecryptionError on invalid padding
      b) returns garbage (not the original plaintext)
    """
    plaintext = b'secret message'
    key1 = os.urandom(16)
    key2 = os.urandom(16)

    cipher1 = SIACipher(key1)
    cipher2 = SIACipher(key2)

    ciphertext = cipher1.encrypt(plaintext)

    # Try to decrypt with wrong key
    try:
        recovered = cipher2.decrypt(ciphertext)
        # Assert: if no exception, recovered is garbage (not original)
        assert recovered != plaintext
    except AESDecryptionError:
        # Assert: exception is acceptable (invalid padding with wrong key)
        pass


# ============================================================================
# Error Handling
# ============================================================================

def test_decrypt_with_truncated_ciphertext_raises_error(cipher):
    """Test that decrypting truncated ciphertext raises AESDecryptionError.

    Expected result:
    - AESDecryptionError raised for truncated/invalid ciphertext
    """
    plaintext = b'test'
    ciphertext = cipher.encrypt(plaintext)

    # Truncate ciphertext
    truncated = ciphertext[:8]

    # Assert: AESDecryptionError raised for truncated ciphertext
    with pytest.raises(AESDecryptionError):
        cipher.decrypt(truncated)


def test_decrypt_with_odd_length_ciphertext():
    """Test that decryption rejects ciphertext not multiple of 16 bytes.

    Expected result:
    - AESDecryptionError raised with message about block size
    - Error triggered before decryption attempt
    """
    invalid_ciphertext = os.urandom(17)
    cipher = SIACipher(os.urandom(16))

    # Assert: AESDecryptionError raised for invalid ciphertext length
    with pytest.raises(AESDecryptionError, match="multiple|block"):
        cipher.decrypt(invalid_ciphertext)


def test_decrypt_with_3_byte_ciphertext(cipher):
    """Test that decryption rejects very short invalid ciphertext.

    Expected result:
    - AESDecryptionError raised for 3-byte ciphertext (too short)
    """
    invalid_ciphertext = os.urandom(3)

    # Assert: AESDecryptionError raised
    with pytest.raises(AESDecryptionError):
        cipher.decrypt(invalid_ciphertext)


def test_decrypt_with_invalid_pad_len_zero():
    """Test PKCS#7 unpadding rejects padding with pad_len == 0 (invalid).

    Expected result:
    - AESDecryptionError raised when last byte indicates 0 padding
    """
    key = os.urandom(16)
    cipher = SIACipher(key)

    # Encrypt something valid first
    plaintext = b'test'
    ciphertext = cipher.encrypt(plaintext)

    # Now corrupt the last byte to be 0x00 (invalid pad_len)
    corrupted = ciphertext[:-1] + b'\x00'

    # Assert: AESDecryptionError on invalid pad_len (0)
    with pytest.raises(AESDecryptionError, match="range|padding"):
        cipher.decrypt(corrupted)


def test_decrypt_with_invalid_pad_len_too_large():
    """Test PKCS#7 unpadding rejects padding with pad_len > 16 (invalid).

    Expected result:
    - AESDecryptionError raised when last byte indicates padding > 16 bytes
    """
    cipher = SIACipher(os.urandom(16))

    # Create a 16-byte block where last byte is 0xFF (255, way too large)
    invalid_ciphertext = b'\x00' * 15 + b'\xFF'

    # Assert: AESDecryptionError on invalid pad_len (either range or mismatch message)
    with pytest.raises(AESDecryptionError):
        cipher.decrypt(invalid_ciphertext)


def test_aeskeyerror_has_descriptive_message():
    """Test that AESKeyError messages are descriptive and helpful.

    Expected result:
    - error message includes "16" or "byte" description
    """
    try:
        SIACipher(b'short')
    except AESKeyError as e:
        # Assert: error message is descriptive
        assert "16" in str(e) or "byte" in str(e).lower()


def test_aesdecryptionerror_on_invalid_padding(cipher):
    """Test that AESDecryptionError is raised on invalid padding.

    Expected result:
    - AESDecryptionError with message about padding
    """
    # Create invalid ciphertext (16 bytes of zeros is likely invalid padding)
    invalid_ciphertext = b'\x00' * 16

    with pytest.raises(AESDecryptionError):
        cipher.decrypt(invalid_ciphertext)


# ============================================================================
# Type Safety Tests
# ============================================================================

def test_encrypt_with_string_plaintext_raises_error():
    """Test cipher.encrypt() rejects string plaintext (not bytes).

    Expected result:
    - AESEncryptionError or TypeError raised when plaintext is string
    """
    cipher = SIACipher(os.urandom(16))
    plaintext = "not bytes, this is a string"

    # Assert: Error raised for non-bytes plaintext (wrapped in AESEncryptionError)
    with pytest.raises((AESEncryptionError, TypeError, AttributeError)):
        cipher.encrypt(plaintext)


# ============================================================================
# Frame Methods (Semantic Intent)
# ============================================================================

def test_encrypt_frame_with_valid_frame(cipher):
    """Test SIA protocol frame encryption.

    Expected result:
    - plaintext frame encrypted returns ciphertext
    - ciphertext can be decrypted back to original
    """
    plaintext_frame = b'\x0a"6F6FL0#001234[#001234|1130]_22:49:34,04-07-2026\x0d'
    ciphertext = cipher.encrypt_frame(plaintext_frame)
    recovered = cipher.decrypt_frame(ciphertext)

    # Assert: round-trip encryption/decryption returns original frame
    assert recovered == plaintext_frame


def test_decrypt_frame_with_valid_ciphertext(cipher):
    """Test SIA protocol frame decryption.

    Expected result:
    - encrypted frame decrypted returns plaintext
    """
    plaintext_frame = b'\x0a"4F4FL0#ACCOUNT[#ACCOUNT|1130]_22:49:34,04-07-2026\x0d'
    encrypted = cipher.encrypt_frame(plaintext_frame)
    decrypted = cipher.decrypt_frame(encrypted)

    # Assert: decrypted frame matches original plaintext
    assert decrypted == plaintext_frame


# ============================================================================
# Golden Frame Tests: Real SIA Protocol Frames with Encryption
# ============================================================================

def test_encrypt_golden_alarm_frame_roundtrip(sia_builder, test_key):
    """Test encryption of real SIA alarm frame with golden plaintext.

    Expected result:
    - Real alarm frame from SIAMessageBuilder can be encrypted and decrypted
    - Round-trip: plaintext → encrypt → decrypt → matches original
    - Validates encryption works with actual protocol frames per § 5.5.1.10
    """
    cipher = SIACipher(test_key)

    # Generate real alarm frame using protocol builder
    plaintext_frame = sia_builder.encode_message(
        account_number="001234",
        event_code="1130",  # Burglary alarm
        timestamp=None  # Disable timestamp for determinism
    )

    # Encrypt the plaintext frame
    ciphertext = cipher.encrypt_frame(plaintext_frame)
    recovered = cipher.decrypt_frame(ciphertext)

    # Assert: encryption is reversible
    assert recovered == plaintext_frame

    # Assert: ciphertext is longer due to PKCS#7 padding
    assert len(ciphertext) > len(plaintext_frame)

    # Assert: ciphertext length is multiple of 16 (AES block requirement)
    assert len(ciphertext) % 16 == 0


def test_encrypt_golden_supervision_frame_roundtrip(sia_builder, test_key):
    """Test encryption of real SIA supervision (NULL) frame with golden plaintext.

    Expected result:
    - Real supervision frame from SIAMessageBuilder can be encrypted/decrypted
    - Round-trip: supervision frame → encrypt → decrypt → original
    - Validates encryption works with NULL supervision messages per § 5.5.1.10
    """
    cipher = SIACipher(test_key)

    # Generate real supervision (NULL) frame
    plaintext_frame = sia_builder.make_supervision_message(
        account_number="001234"
    )

    # Encrypt the supervision frame
    ciphertext = cipher.encrypt_frame(plaintext_frame)
    recovered = cipher.decrypt_frame(ciphertext)

    # Assert: encryption is reversible for supervision messages
    assert recovered == plaintext_frame

    # Assert: ciphertext is valid AES block multiple
    assert len(ciphertext) % 16 == 0


def test_encrypt_deterministic_with_golden_key(sia_builder, test_key):
    """Test that encryption is deterministic with fixed IV per SIA DC-09 standard.

    Expected result:
    - Same plaintext frame + same key produces identical ciphertext (deterministic)
    - Validates fixed IV (not random) per § 5.5.1.10
    - Multiple encryption calls with same inputs produce same output
    """
    cipher = SIACipher(test_key)

    plaintext_frame = sia_builder.encode_message(
        account_number="002468",
        event_code="1130",
        timestamp=None
    )

    # Encrypt same frame twice with same key
    ciphertext1 = cipher.encrypt_frame(plaintext_frame)
    ciphertext2 = cipher.encrypt_frame(plaintext_frame)

    # Assert: encryption is deterministic (fixed IV)
    assert ciphertext1 == ciphertext2

    # Assert: both decrypt to original
    assert cipher.decrypt_frame(ciphertext1) == plaintext_frame
    assert cipher.decrypt_frame(ciphertext2) == plaintext_frame


def test_encrypt_different_frames_produce_different_ciphertexts(sia_builder, test_key):
    """Test that different plaintext frames produce different ciphertexts.

    Expected result:
    - Different alarm codes produce different encrypted outputs
    - Different account numbers produce different encrypted outputs
    - Validates encryption depends on plaintext content
    """
    cipher = SIACipher(test_key)

    frame1 = sia_builder.encode_message("001234", "1130", timestamp=None)  # Burglary
    frame2 = sia_builder.encode_message("001234", "1140", timestamp=None)  # Different event
    frame3 = sia_builder.encode_message("005678", "1130", timestamp=None)  # Different account

    ciphertext1 = cipher.encrypt_frame(frame1)
    ciphertext2 = cipher.encrypt_frame(frame2)
    ciphertext3 = cipher.encrypt_frame(frame3)

    # Assert: different plaintexts produce different ciphertexts
    assert ciphertext1 != ciphertext2, "Different events should produce different ciphertexts"
    assert ciphertext1 != ciphertext3, "Different accounts should produce different ciphertexts"
    assert ciphertext2 != ciphertext3


def test_encrypt_different_keys_produce_different_ciphertexts(sia_builder):
    """Test that different encryption keys produce different ciphertexts.

    Expected result:
    - Same plaintext encrypted with key1 and key2 produces different ciphertexts
    - Validates key material affects output
    """
    plaintext_frame = sia_builder.encode_message("001234", "1130", timestamp=None)

    key1 = b'0123456789ABCDEF'
    key2 = b'FEDCBA9876543210'

    cipher1 = SIACipher(key1)
    cipher2 = SIACipher(key2)

    ciphertext1 = cipher1.encrypt_frame(plaintext_frame)
    ciphertext2 = cipher2.encrypt_frame(plaintext_frame)

    # Assert: different keys produce different ciphertexts
    assert ciphertext1 != ciphertext2

    # Assert: each decrypts only with its matching key
    assert cipher1.decrypt_frame(ciphertext1) == plaintext_frame
    assert cipher2.decrypt_frame(ciphertext2) == plaintext_frame

    # Assert: wrong key decryption fails or returns garbage
    try:
        decrypted_wrong = cipher1.decrypt_frame(ciphertext2)
        # If no exception, should be garbage (not original plaintext)
        assert decrypted_wrong != plaintext_frame
    except AESDecryptionError:
        # Exception is also acceptable
        pass


def test_encrypt_golden_frame_preserves_structure_after_roundtrip(sia_builder, test_key):
    """Test that plaintext frame structure is preserved through encrypt/decrypt roundtrip.

    Expected result:
    - Recovered frame matches original byte-for-byte
    - Frame delimiters (LF/CR) are preserved
    - All fields (CRC, length, sequence, account, etc.) intact after roundtrip
    """
    cipher = SIACipher(test_key)

    # Generate frame with specific parameters
    plaintext = sia_builder.encode_message(
        account_number="ABCDEF123456",
        event_code="1130",
        timestamp=None
    )

    # Encrypt and decrypt
    encrypted = cipher.encrypt_frame(plaintext)
    recovered = cipher.decrypt_frame(encrypted)

    # Assert: structure perfectly preserved
    assert recovered == plaintext
    assert len(recovered) == len(plaintext)
    assert recovered[0:1] == plaintext[0:1]  # LF preserved
    assert recovered[-1:] == plaintext[-1:]  # CR preserved


@pytest.mark.parametrize("event_code,account", [
    ("1130", "001234"),  # Burglary alarm
    ("1230", "005678"),  # Fire alarm
    ("1330", "009999"),  # Panic alarm
    ("0000", "AABBCC"),  # Supervision NULL
])
def test_encrypt_parametrized_golden_frames(sia_builder, test_key, event_code, account):
    """Parametrized test: encrypt various alarm types with different accounts.

    Expected result:
    - All alarm types can be encrypted and decrypted successfully
    - Round-trip validation succeeds for all event/account combinations
    """
    cipher = SIACipher(test_key)

    plaintext = sia_builder.encode_message(account, event_code, timestamp=None)
    ciphertext = cipher.encrypt_frame(plaintext)
    recovered = cipher.decrypt_frame(ciphertext)

    # Assert: all variations can be encrypted/decrypted
    assert recovered == plaintext
