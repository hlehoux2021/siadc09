"""
SIA DC-09-2021 AES-128 CBC Cipher Module

Provides class-based interface for AES-128 CBC encryption/decryption per SIA DC-09-2021 standard.

**Encryption Standard (per SIA DC-09-2021 § 5.5.1.10):**
- Algorithm: AES-128 CBC
- Key length: exactly 16 bytes (128-bit) — bound at construction
- IV (Initialization Vector): 16 zero bytes (b'\\x00' * 16) — **FIXED per standard, not random**
- Padding: PKCS#7 (RFC 5652)
- Block size: 16 bytes

**Key Lifecycle (per SIA DC-09-2021 § 5.4.5):**
The encryption key is a static configuration value programmed identically on PE and CSR.
It does not change per-message or per-session. NAK retries use the same key with an
updated timestamp (§ 5.5.1.9). Therefore, the key is bound at cipher construction time
and stored as instance state.

**Semantic Design:**
The `SIACipher` class groups encryption operations as a domain concept (SIA protocol
concept), provides clear namespacing, and mirrors the `SIAMessageBuilder` pattern
(configuration bound at construction, methods use self._key transparently).

[Expert validation: sia-dc09-expert skill]
[Source: SIA DC-09-2021 spec § 5.4 – 5.4.7; daemon-design.md § Encryption Contract]
"""

from typing import ClassVar
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# ============================================================================
# Error Classes
# ============================================================================

class AESKeyError(Exception):
    """Raised when encryption key validation fails."""
    pass


class AESEncryptionError(Exception):
    """Raised when encryption operation fails."""
    pass


class AESDecryptionError(Exception):
    """Raised when decryption operation fails."""
    pass


# ============================================================================
# Private Module-Level Validation Helper
# ============================================================================

def _validate_key(key: bytes | None) -> None:
    """
    Validate encryption key is exactly 16 bytes (128-bit).

    Per SIA DC-09-2021 standard, AES-128 keys must be exactly 16 bytes.

    Args:
        key: The encryption key to validate

    Raises:
        AESKeyError: If key is None, wrong type, or wrong length

    Reference:
        SIA DC-09-2021 spec § 5.4.5 - Encryption Key
    """
    if key is None or not isinstance(key, bytes):
        raise AESKeyError("Encryption key must be bytes, not None")

    if len(key) != 16:
        raise AESKeyError(
            f"Encryption key must be exactly 16 bytes (128-bit), "
            f"got {len(key)} bytes"
        )


# ============================================================================
# SIACipher Class
# ============================================================================

class SIACipher:
    """
    AES-128 CBC cipher for SIA DC-09-2021 protocol.

    Key is bound at construction and stored as instance state. Per SIA DC-09-2021 § 5.4.5,
    the key is a static configuration value that does not change per-message or per-session.
    NAK retries use the same key with an updated timestamp (§ 5.5.1.9).

    **Encryption Contract:**
    - Input: plaintext bytes (any length)
    - Process: Apply PKCS#7 padding, then AES-128 CBC encryption
    - Output: ciphertext bytes (length multiple of 16)
    - IV: Fixed at 16 zero bytes per SIA DC-09 standard
    - Deterministic: Same plaintext + key → same ciphertext (no random IV)

    **Decryption Contract:**
    - Input: ciphertext bytes (must be multiple of 16 bytes)
    - Process: AES-128 CBC decryption, then PKCS#7 unpadding
    - Output: plaintext bytes
    - Validation: Rejects malformed ciphertext or invalid padding

    Reference: SIA DC-09-2021 spec § 5.4 – 5.4.7
    """

    # Class-level constants (per code-style.md ClassVar pattern)
    KEY_SIZE: ClassVar[int] = 16  # 128-bit key
    BLOCK_SIZE: ClassVar[int] = 16  # AES block size in bytes
    IV: ClassVar[bytes] = b'\x00' * 16  # Fixed IV per SIA DC-09-2021 standard (16 zero bytes, not random)

    def __init__(self, key: bytes) -> None:
        """
        Initialize cipher with encryption key.

        Key is validated and bound at construction. Once set, the key is invariant
        for the lifetime of this cipher instance, matching the daemon's session-level
        key storage pattern (self._encryption_key).

        Args:
            key: Encryption key (exactly 16 bytes for AES-128)

        Raises:
            AESKeyError: If key is None, not bytes, or not exactly 16 bytes

        Instance Variables:
            _key: The AES-128 encryption key (16 bytes)

        Reference:
            SIA DC-09-2021 spec § 5.4.5 - Encryption Key
        """
        _validate_key(key)
        self._key: bytes = key

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt plaintext using AES-128 CBC with fixed IV per SIA DC-09 standard.

        IV is always 16 zero bytes per SIA DC-09-2021 § 5.5.1.10 (not random).

        Process:
        1. Apply PKCS#7 padding to plaintext
        2. Create AES-CBC cipher with fixed IV
        3. Encrypt padded plaintext
        4. Return ciphertext (IV is implicit, not prepended)

        Args:
            plaintext: Unencrypted message bytes (any length)

        Returns:
            Ciphertext (IV is implicit per SIA DC-09 standard)

        Raises:
            AESEncryptionError: If encryption fails

        Reference:
            SIA DC-09-2021 spec § 5.5.1.10 - Encryption Support
            internal-docs/design/daemon-design.md § Encryption Contract
        """
        try:
            # Apply PKCS#7 padding
            padded_plaintext = self._apply_pkcs7_padding(plaintext)

            # Create cipher: AES-128 CBC with fixed IV per SIA DC-09 standard
            cipher = Cipher(
                algorithms.AES(self._key),
                modes.CBC(self.IV),
                backend=default_backend()
            )

            # Encrypt
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()

            return ciphertext

        except AESKeyError:
            raise  # Key validation errors already raised by __init__
        except Exception as e:
            raise AESEncryptionError(f"Encryption failed: {e}") from e

    def decrypt(self, ciphertext: bytes) -> bytes:
        """
        Decrypt ciphertext using AES-128 CBC with fixed IV per SIA DC-09 standard.

        IV is always 16 zero bytes per SIA DC-09-2021 § 5.5.1.10 (same as encryption).

        Process:
        1. Validate ciphertext length is multiple of 16 bytes
        2. Create AES-CBC cipher with fixed IV
        3. Decrypt ciphertext
        4. Remove PKCS#7 padding
        5. Return plaintext

        Args:
            ciphertext: Encrypted message bytes (must be multiple of 16 bytes)

        Returns:
            Plaintext (decrypted and unpadded)

        Raises:
            AESDecryptionError: If ciphertext invalid or decryption fails

        Reference:
            SIA DC-09-2021 spec § 5.5.1.10 - Encryption Support
            internal-docs/design/daemon-design.md § Decryption Contract
        """
        try:
            # Validate ciphertext length is multiple of AES block size
            if len(ciphertext) % self.BLOCK_SIZE != 0:
                raise AESDecryptionError(
                    f"Invalid ciphertext length: {len(ciphertext)} bytes. "
                    f"Must be multiple of {self.BLOCK_SIZE} bytes (AES block size)"
                )

            # Create cipher: AES-128 CBC with fixed IV per SIA DC-09 standard
            cipher = Cipher(
                algorithms.AES(self._key),
                modes.CBC(self.IV),
                backend=default_backend()
            )

            # Decrypt
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            # Remove PKCS#7 padding
            plaintext = self._remove_pkcs7_padding(padded_plaintext)

            return plaintext

        except AESKeyError:
            raise  # Key validation errors (should not happen post-construction)
        except AESDecryptionError:
            raise  # Padding validation errors
        except Exception as e:
            raise AESDecryptionError(f"Decryption failed: {e}") from e

    def encrypt_frame(self, plaintext_frame: bytes) -> bytes:
        """
        Encrypt a SIA protocol frame for transmission to CSR.

        **Semantic Intent:** Explicit frame-level method for daemon code clarity.
        Equivalent to `encrypt()` but call-site intent is obvious (frame, not raw bytes).

        Input: plaintext SIA frame from `SIAMessageBuilder.encode_message()`
        (includes LF prefix, CRC, length, message string, CR suffix)

        Output: ciphertext ready for wire transmission

        The daemon will wrap the encrypted frame in SIA message format with
        '*SIA-DCS' token to mark it as encrypted.

        Args:
            plaintext_frame: Full SIA protocol frame (bytes)

        Returns:
            Ciphertext (IV is implicit per SIA DC-09 standard)

        Raises:
            AESEncryptionError: If encryption fails

        Reference:
            internal-docs/design/daemon-design.md § Message Flow: Plaintext → Encrypt → Send
            Story 1.1: SIA Protocol Message Builder
        """
        return self.encrypt(plaintext_frame)

    def decrypt_frame(self, encrypted_frame: bytes) -> bytes:
        """
        Decrypt a SIA protocol frame received from CSR.

        **Semantic Intent:** Explicit frame-level method for daemon code clarity.
        Equivalent to `decrypt()` but call-site intent is obvious (frame, not raw bytes).

        Input: encrypted ACK/NAK or other response frame (ciphertext)
        IV is implicit per SIA DC-09 standard.

        Output: plaintext frame for ACK/NAK parser (Story 1.3) to validate

        Args:
            encrypted_frame: Encrypted SIA protocol frame (bytes)

        Returns:
            Plaintext frame (ready for parsing/validation)

        Raises:
            AESDecryptionError: If decryption fails

        Reference:
            internal-docs/design/daemon-design.md § ACK/NAK Handling
            Story 1.3: ACK/NAK Response Parser (dependency)
        """
        return self.decrypt(encrypted_frame)

    @staticmethod
    def _apply_pkcs7_padding(data: bytes) -> bytes:
        """
        Apply PKCS#7 padding to data.

        Pads data to a multiple of AES_BLOCK_SIZE. Padding bytes = padding length.
        Example: if 3 bytes of padding needed, appends b'\\x03\\x03\\x03'

        Args:
            data: Data to pad

        Returns:
            Padded data (length is multiple of AES_BLOCK_SIZE)

        Reference:
            RFC 5652 Section 6.3 - PKCS#7 Padding
        """
        pad_len = 16 - (len(data) % 16)
        return data + bytes([pad_len] * pad_len)

    @staticmethod
    def _remove_pkcs7_padding(data: bytes) -> bytes:
        """
        Remove PKCS#7 padding from data.

        Reads last byte as padding length, validates all padding bytes match,
        then removes padding.

        Args:
            data: Padded data

        Returns:
            Unpadded data

        Raises:
            AESDecryptionError: If padding is invalid (bytes don't match declared length)

        Reference:
            RFC 5652 Section 6.3 - PKCS#7 Padding Removal
        """
        if len(data) == 0:
            raise AESDecryptionError("Invalid PKCS#7 padding: data is empty")

        pad_len = data[-1]  # Last byte indicates padding length

        # Validate pad_len is reasonable
        if pad_len == 0 or pad_len > 16:
            raise AESDecryptionError(
                f"Invalid PKCS#7 padding: pad length {pad_len} outside valid range [1, 16]"
            )

        # Validate all padding bytes match the declared length
        for i in range(pad_len):
            if data[-(i + 1)] != pad_len:
                raise AESDecryptionError(
                    f"Invalid PKCS#7 padding: byte at offset -{i + 1} is {data[-(i + 1)]}, "
                    f"expected {pad_len}"
                )

        # Remove padding
        return data[:-pad_len]
