"""
SIA DC-09-2021 AES-CBC Cipher Module

Encrypts and decrypts the encrypted region of a DC-09 message per
SIA DC-09-2021 § 5.4.3 - 5.4.7:

- Key: 128, 192 or 256 bits (16/24/32 bytes), static configuration shared by
  PE and CSR (§ 5.4.5). Bound at construction.
- Cipher: AES-CBC with an IV of 16 zero bytes (§ 5.4.6). Nothing is prepended.
- Padding: random pad bytes at the FRONT of the region, then '|' (§ 5.4.4).
  The pad length makes pad + '|' + content a multiple of 16; when it already
  is, a full 16-byte pad is used. There is no PKCS#7 tail padding.
- Output: the ciphertext as uppercase hex ASCII (§ 5.4.7).

Callers pass the region content (data from after '[' through the timestamp)
as bytes and receive the hex string that goes after '[' on the wire.

[Source: SIA DC-09-2021 § 5.4.3 - 5.4.7; story 1-5]
"""

import re
import secrets
from collections.abc import Callable
from typing import ClassVar
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# ============================================================================
# Error Classes
# ============================================================================

class AESKeyError(Exception):
    """Raised when encryption key validation fails. Never carries the key."""


class AESEncryptionError(Exception):
    """Raised when encryption operation fails."""


class AESDecryptionError(Exception):
    """Raised when decryption operation fails. Never carries key or plaintext."""


# ============================================================================
# Key parsing
# ============================================================================

_HEX_KEY_RE = re.compile(r"(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{48}|[0-9A-Fa-f]{64})")

PadSource = Callable[[int], bytes]


def parse_hex_key(text: str | None) -> bytes:
    """Decode a configured key: 32, 48 or 64 hex digits (AES-128/192/256).

    Surrounding whitespace is trimmed. Internal whitespace, a '0x' prefix or any
    other length is rejected. ASCII-phrase keys are not supported (D-93).

    Args:
        text: Key as entered in the plugin configuration.

    Returns:
        The raw key bytes (16, 24 or 32 bytes).

    Raises:
        AESKeyError: If the key is missing or malformed. The message never
            contains the key.
    """
    if not isinstance(text, str) or not text.strip():
        raise AESKeyError("Encryption key is missing")
    stripped = text.strip()
    if _HEX_KEY_RE.fullmatch(stripped) is None:
        raise AESKeyError(
            f"Encryption key must be 32, 48 or 64 hex digits (got {len(stripped)} characters)"
        )
    return bytes.fromhex(stripped)


def _validate_key(key: bytes | None) -> None:
    """Validate a raw AES key is 16, 24 or 32 bytes.

    Raises:
        AESKeyError: If key is not bytes or has an unsupported length.
    """
    if not isinstance(key, bytes):
        raise AESKeyError("Encryption key must be bytes")
    if len(key) not in SIACipher.KEY_SIZES:
        raise AESKeyError(
            f"Encryption key must be 16, 24 or 32 bytes (AES-128/192/256), got {len(key)} bytes"
        )


# ============================================================================
# SIACipher Class
# ============================================================================

class SIACipher:
    """AES-CBC cipher for the DC-09 encrypted region (§ 5.4.3 - 5.4.7).

    Key is bound at construction and never logged or included in errors.
    """

    KEY_SIZES: ClassVar[tuple[int, ...]] = (16, 24, 32)
    BLOCK_SIZE: ClassVar[int] = 16
    IV: ClassVar[bytes] = b"\x00" * 16  # § 5.4.6: IV is all zeros
    PAD_TERMINATOR: ClassVar[bytes] = b"|"  # § 5.4.4.3
    DATA_END: ClassVar[bytes] = b"]"
    # § 5.4.4.2 allows any byte except '|', '[' and ']'. Printable ASCII is a
    # conformant subset that also survives receivers decoding the plaintext as
    # text (ioBroker: utf-8, pysiaalarm: ascii/ignore).
    PAD_ALPHABET: ClassVar[bytes] = bytes(b for b in range(0x20, 0x7F) if b not in b"|[]")

    def __init__(self, key: bytes, pad_source: PadSource | None = None) -> None:
        """Initialize cipher.

        Args:
            key: Raw AES key, 16/24/32 bytes.
            pad_source: Returns n pad bytes. Defaults to a `secrets`-based
                generator over PAD_ALPHABET. Injectable for deterministic tests.

        Raises:
            AESKeyError: If the key has an unsupported type or length.
        """
        _validate_key(key)
        self._key: bytes = key
        self._pad_source: PadSource = pad_source or self._random_pad

    def __repr__(self) -> str:
        return f"SIACipher(AES-{len(self._key) * 8})"

    @classmethod
    def _random_pad(cls, n: int) -> bytes:
        return bytes(secrets.choice(cls.PAD_ALPHABET) for _ in range(n))

    def _cipher(self) -> Cipher:
        return Cipher(algorithms.AES(self._key), modes.CBC(self.IV))

    def encrypt(self, content: bytes) -> str:
        """Encrypt region content into uppercase hex (§ 5.4.4 - 5.4.7).

        Args:
            content: Region content bytes, i.e. data after '[' (its ']'
                included), extended data and timestamp.

        Returns:
            Uppercase hex of AES-CBC(pad + '|' + content).

        Raises:
            AESEncryptionError: If content is not bytes, the pad source returns
                an invalid pad, or the cipher fails.
        """
        if not isinstance(content, bytes):
            raise AESEncryptionError("Region content must be bytes")
        body = self.PAD_TERMINATOR + content
        pad_len = self.BLOCK_SIZE - (len(body) % self.BLOCK_SIZE)
        pad = self._pad_source(pad_len)
        if not isinstance(pad, bytes) or len(pad) != pad_len or any(b in b"|[]" for b in pad):
            raise AESEncryptionError("Pad source returned an invalid pad")
        try:
            encryptor = self._cipher().encryptor()
            ciphertext = encryptor.update(pad + body) + encryptor.finalize()
        except ValueError as e:
            raise AESEncryptionError("Encryption failed") from e
        return ciphertext.hex().upper()

    def decrypt(self, hex_text: str) -> bytes:
        """Decrypt hex ciphertext and return the region content (pad stripped).

        The pad is stripped at byte level up to and including the first '|'.
        Without a '|', everything before the first ']' is treated as pad: some
        encoders write *NULL / *ACK regions straight from the § 5.5.2.1 /
        § 5.5.3.1 templates, which omit the '|'.

        Args:
            hex_text: Ciphertext hex, upper or lower case.

        Returns:
            Region content bytes. Callers decode as windows-1252.

        Raises:
            AESDecryptionError: On malformed hex, a length that is not a whole
                number of blocks, or a plaintext with neither '|' nor ']'.
        """
        try:
            ciphertext = bytes.fromhex(hex_text)
        except (TypeError, ValueError) as e:
            raise AESDecryptionError("Ciphertext is not valid hex") from e
        if not ciphertext or len(ciphertext) % self.BLOCK_SIZE != 0:
            raise AESDecryptionError(
                f"Ciphertext length {len(ciphertext)} bytes is not a positive multiple of {self.BLOCK_SIZE}"
            )
        decryptor = self._cipher().decryptor()
        plain = decryptor.update(ciphertext) + decryptor.finalize()
        idx = plain.find(self.PAD_TERMINATOR)
        if idx >= 0:
            return plain[idx + 1:]
        idx = plain.find(self.DATA_END)
        if idx >= 0:
            return plain[idx:]
        raise AESDecryptionError("Decrypted region has no pad terminator (wrong key?)")
