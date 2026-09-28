"""
SIA DC-09-2021.17 Protocol Message Builder Module

Pure protocol layer for constructing and serializing SIA DC-09 compliant message frames.
Encryption of the message region is delegated to sia_crypto (story 1-5).

Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5 Messages

Expert Validation: sia-dc09-expert (2026-04-07)
- CRC: CRC-16 MODBUS (polynomial 0xA001)
- Timestamp: Formatted string _HH:MM:SS,MM-DD-YYYY (20 chars, UTC)
- Message frame: LF + CRC + Length + Message + CR
"""

import dataclasses
import struct
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypedDict
try:
    from .sia_crypto import AESDecryptionError, AESKeyError, PadSource, SIACipher, parse_hex_key
except ImportError:  # run as a script: `python3 sia_protocol.py --decode` (PHP inspector)
    from sia_crypto import AESDecryptionError, AESKeyError, PadSource, SIACipher, parse_hex_key  # type: ignore[no-redef]

# CRC encoding format for SIA DC-09 frames (canonical definition — re-exported by sia_transport)
CrcFormat = Literal['hex', 'bin']

# ===== Module-Level Constants =====

# Frame delimiters (binary)
LF = b'\x0A'  # Line feed (0x0A)
CR = b'\x0D'  # Carriage return (0x0D)

# NULL code for supervision messages
SIA_NULL_CODE = "0000"

# Event type codes (per SIA spec)
BURGLARY = "1"
FIRE = "2"
PANIC = "3"

# ID tokens
SIA_DCS_TOKEN = "SIA-DCS"
ADM_CID_TOKEN = "ADM-CID"
NULL_TOKEN = "NULL"
ACK_TOKEN = "ACK"
NAK_TOKEN = "NAK"
DUH_TOKEN = "DUH"

# Encrypted token marker
ENCRYPTED_MARKER = "*"

# CRC format types (preset-configured)
CRC_FORMAT_SIA = "SIA"
CRC_FORMAT_ADM = "ADM"

# ACK/NAK response type constants
ACK_RESPONSE = "ACK"
NAK_RESPONSE = "NAK"
UNKNOWN_RESPONSE: Literal["unknown"] = "unknown"

# Timestamp field constants
TIMESTAMP_DELIMITER = '_'
TIMESTAMP_LENGTH = 19  # HH:MM:SS,MM-DD-YYYY = 19 characters
TIMESTAMP_FORMAT = '%H:%M:%S,%m-%d-%Y'
TIMESTAMP_PATTERN = r'^\d{2}:\d{2}:\d{2},\d{2}-\d{2}-\d{4}$'

# Message field lengths (characters)
SEQUENCE_FIELD_LENGTH = 4

# Length field is "0" + 3 hex digits (§ 5.5.1.3): largest encodable message
MAX_MESSAGE_LENGTH = 0xFFF

# Encrypted region (§ 5.4.3): the hex runs from after '[' to the end of the
# message. D1 (2026-09-27) originally omitted the closing ']', per a survey of
# third-party frames. Reverted 2026-09-28: live AC11 evidence against a real
# ioBroker.sia instance (testsia.lehoux.net) showed its parser applies an
# outer regex to the WIRE message *before* decrypting, expecting a literal
# ']' to delimit the data block — without it, valid ciphertext (which
# verified as decrypting cleanly with the shared key) was rejected with
# "Incorrect format of data message" before decryption was ever attempted.
# Kept as a constant so this is a one-line change either way.
ENCRYPTED_REGION_TERMINATOR = "]"

# Encrypted supervision token (story 1-5 D2): "*NULL" per § 5.5.2.1, with a
# fallback to an encrypted "*SIA-DCS" 0000 event (the seq then comes from the
# tracker) for a CSR that has no *NULL branch at all. Switched to the fallback
# 2026-09-28: live AC11 evidence against ioBroker.sia showed it decrypts and
# accepts the *NULL correctly (content and CRC both verified) but has no *NULL
# response path — its own log shows it answering with a degenerate, tokenless
# LF+"0000"+"0000"+CR frame (CRC/LEN both correctly computed for an empty
# body) instead of a real ACK, which our decoder classifies as unparseable.
ENCRYPTED_SUPERVISION_TOKEN = SIA_DCS_TOKEN
NULL_MESSAGE_SEQ = "0000"  # § 5.5.2.1 template

_SEQ_RE = re.compile(r"(?!0000)\d{4}")
_FRAME_HEADER_RE = re.compile(rb'^\n.{8}"(?P<token>[^"]+)"(?P<seq>\d{4})')


# ===== Type Definitions =====

class AckNakResponse(TypedDict):
    """Response from ACK/NAK decoder."""
    type: Literal["ACK", "NAK", "unknown"]
    seq: int | None
    raw_nak: bytes | None


# ===== Exception Classes =====

class SIATransportError(OSError):
    """Network/socket failure — TCP timeout, UDP timeout, socket closed."""


class SIAProtocolError(ValueError):
    """
    SIA DC-09 protocol violation — malformed frame, decode failure.

    Used for malformed frames, invalid data, or protocol violations.
    Never raised by defensive parsing functions (decode_ack_nak) — they return
    type='unknown' instead. Raised by encoding functions or explicit validators.
    """


# ===== Sequence Tracker Class =====

class SequenceTracker:
    """
    Tracks sequence numbers per account.
    Wraps from 9999 → 0001 (never 0000).

    Per SIA DC-09 § 5.5.1.5: "Sequence numbers are associated with PE account numbers"
    """

    def __init__(self) -> None:
        """Initialize empty sequence state.

        Instance Variables:
            _seq_map: Dictionary mapping account numbers (str) to their current sequence
                      number (int). Used to track per-account sequence counters.
        """
        self._seq_map: dict[str, int] = {}

    def next_seq(self, account_number: str) -> str:
        """
        Increment and return next sequence number for account.

        Args:
            account_number: Account identifier (hex string, 3-16 chars)

        Returns:
            4-character ASCII decimal string (0001-9999)
        """
        current = self._seq_map.get(account_number, 0)
        current = current + 1
        if current > 9999:
            current = 1  # Wrap: 9999 → 0001 (per § 5.5.1.5)
        self._seq_map[account_number] = current
        return f"{current:04d}"

    def current_seq(self, account_number: str) -> str:
        """
        Return current sequence number without incrementing.

        Args:
            account_number: Account identifier

        Returns:
            4-character ASCII decimal string (0001-9999)
        """
        current = self._seq_map.get(account_number, 0)
        return f"{current:04d}"

    def reset(self, account_number: str | None = None) -> None:
        """
        Reset sequence counter for specified account or all accounts.

        Args:
            account_number: Account to reset. If None, resets ALL accounts.
        """
        if account_number is None:
            self._seq_map.clear()
        else:
            self._seq_map[account_number] = 0



# ===== SIA Message Builder Class =====

class SIAMessageBuilder:
    """
    SIA DC-09 protocol message builder with integrated sequence tracking.

    Encapsulates all message building functionality with automatic per-account
    sequence number management. CRC format is set once at initialization.

    Per SIA DC-09 § 5.5.1.5: Sequence numbers are tracked per account.

    Example:
        builder = SIAMessageBuilder(crc_format="SIA")
        frame1 = builder.encode_message("001234", "1130")  # seq=0001
        frame2 = builder.encode_message("001234", "2130")  # seq=0002
        frame3 = builder.encode_message("005678", "1130")  # seq=0001 (different account)
        builder.reset_sequence("001234")  # Reset account to seq=0001
    """

    def __init__(self, crc_format: Literal["SIA", "ADM"], pad_source: PadSource | None = None) -> None:
        """
        Initialize message builder with CRC format.

        Args:
            crc_format: CRC algorithm ("SIA" or "ADM") - set once, used for all messages
            pad_source: Optional pad generator for encrypted frames (tests only;
                default is SIACipher's random pad)

        Instance Variables:
            crc_format: Configured CRC algorithm for this builder
            _sequence_tracker: Per-account sequence number tracker
            _pad_source: Pad generator handed to SIACipher
        """
        self.crc_format: Literal["SIA", "ADM"] = crc_format
        self._sequence_tracker = SequenceTracker()
        self._pad_source: PadSource | None = pad_source

    # ===== Public Methods =====

    def encode_message(
        self,
        account_number: str,
        event_code: str,
        account_prefix: str = "L0",
        receiver_number: str | None = None,
        extended_data: dict[str, str] | None = None,
        timestamp: datetime | None = None,
        encryption: bool = False,
        encryption_key: bytes | None = None,
        seq: str | None = None,
    ) -> bytes:
        """
        Encode a complete SIA protocol message frame.

        Encrypted frames (§ 5.4.3) keep the header in clear and encrypt the
        region from after '[' through the timestamp:
        ``"*SIA-DCS"seq L0#acct[<hex>``. A timestamp is mandatory when
        encrypting (§ 5.5.1.9); None then means "UTC now".

        Args:
            account_number: 3-16 hex ASCII characters
            event_code: 4-digit event code (e.g., "1130" for burglary)
            account_prefix: 1-6 hex digits (default "L0")
            receiver_number: Optional 1-6 hex digits
            extended_data: Optional additional string fields
            timestamp: Optional datetime (UTC); None = omit timestamp
                (unencrypted) or UTC now (encrypted)
            encryption: Whether to encrypt (default False)
            encryption_key: Raw AES key (16/24/32 bytes), required when encrypting
            seq: Explicit wire sequence number, for retries of the same event
                (§ 5.5.1.5, Annex F.5). None = next from the per-account tracker.

        Returns:
            Complete frame as bytes: LF + CRC + Length + Message + CR

        Raises:
            ValueError: If account_number, prefix, or receiver_number invalid hex
            SIAProtocolError: If seq is malformed or the message exceeds 0xFFF characters
            AESKeyError: If encryption is requested without a valid key

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1
        """
        if extended_data is None:
            extended_data = {}
        if seq is not None and _SEQ_RE.fullmatch(seq) is None:
            raise SIAProtocolError(f"Invalid sequence number: {seq!r} (expected 0001-9999)")
        cipher = self._make_cipher(encryption_key) if encryption else None

        # Build message components per spec § 5.5.1
        account_id_str = self._format_account_id(account_number, account_prefix, receiver_number)
        data_field = self._format_data_field(account_number, event_code, extended_data)
        extended_data_field = self._format_extended_data_field(extended_data)
        if cipher is not None and timestamp is None:
            timestamp = datetime.now(timezone.utc)
        timestamp_str = self._format_timestamp(timestamp) or ""

        # Sequence number (auto-incremented per account unless given)
        if seq is None:
            seq = self._sequence_tracker.next_seq(account_number)

        # Field order per § 5.5.1 template: [Data] then [x…data…] then <timestamp>
        if cipher is None:
            core = f'"{SIA_DCS_TOKEN}"{seq}{account_id_str}{data_field}{extended_data_field}{timestamp_str}'
        else:
            # Region = everything after the data field's '[' (§ 5.4.3)
            region = data_field[1:] + extended_data_field + timestamp_str
            core = (f'"{ENCRYPTED_MARKER}{SIA_DCS_TOKEN}"{seq}{account_id_str}['
                    f'{cipher.encrypt(region.encode("ascii"))}{ENCRYPTED_REGION_TERMINATOR}')
        return self._frame(core.encode('ascii'))

    def make_supervision_message(
        self,
        account_number: str,
        account_prefix: str = "L0",
        receiver_number: str | None = None,
        encryption: bool = False,
        encryption_key: bytes | None = None,
        timestamp: datetime | None = None,
        seq: str | None = None,
    ) -> bytes:
        """
        Create a NULL/supervision message.

        Unencrypted: the field-validated ``"SIA-DCS"seq…[#acct|0000]`` event
        (D-86, unchanged). Encrypted: the § 5.5.2.1 Null Message
        ``"*NULL"0000L0#acct[<hex of pad|]_ts>`` (story 1-5 D2). The '|' is
        always present (§ 5.4.4.3). It does not consume a tracker seq.

        Args:
            account_number: 3-16 hex ASCII characters
            account_prefix: Optional prefix (default "L0")
            receiver_number: Optional receiver number
            encryption: Whether to encrypt (default False)
            encryption_key: Raw AES key, required when encrypting
            timestamp: Encrypted: None = UTC now. Unencrypted: None = no timestamp
            seq: Unencrypted only: explicit wire seq for a NAK re-send (§ 5.5.1.5);
                None draws from the tracker. ``*NULL`` always uses 0000.

        Returns:
            Complete NULL message frame as bytes

        Raises:
            AESKeyError: If encryption is requested without a valid key

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.2.1
        """
        if not encryption or ENCRYPTED_SUPERVISION_TOKEN != NULL_TOKEN:
            return self.encode_message(
                account_number=account_number,
                event_code=SIA_NULL_CODE,
                account_prefix=account_prefix,
                receiver_number=receiver_number,
                timestamp=timestamp,
                encryption=encryption,
                encryption_key=encryption_key,
                seq=seq,
            )
        cipher = self._make_cipher(encryption_key)
        account_id_str = self._format_account_id(account_number, account_prefix, receiver_number)
        timestamp_str = self._format_timestamp(timestamp or datetime.now(timezone.utc)) or ""
        region = "]" + timestamp_str
        core = (f'"{ENCRYPTED_MARKER}{NULL_TOKEN}"{NULL_MESSAGE_SEQ}{account_id_str}['
                f'{cipher.encrypt(region.encode("ascii"))}{ENCRYPTED_REGION_TERMINATOR}')
        return self._frame(core.encode('ascii'))

    def reset_sequence(self, account_number: str | None = None) -> None:
        """
        Reset sequence counter for specified account or all accounts.

        Args:
            account_number: Account to reset. If None, resets ALL accounts.

        Example:
            builder.reset_sequence("001234")  # Reset only this account
            builder.reset_sequence()          # Reset all accounts
        """
        self._sequence_tracker.reset(account_number)

    # ===== Private Helper Methods =====

    def _make_cipher(self, encryption_key: bytes | None) -> SIACipher:
        """Build the cipher for one frame; a missing key is an error, never a marker-only frame.

        Raises:
            AESKeyError: If the key is missing or has an unsupported size.
        """
        if encryption_key is None:
            raise AESKeyError("Encryption is enabled but no key is configured")
        return SIACipher(encryption_key, pad_source=self._pad_source)

    def _frame(self, message_core: bytes) -> bytes:
        """Wrap a message as LF + CRC + Length + message + CR.

        Raises:
            SIAProtocolError: If the message is longer than the length field can
                express (§ 5.5.1.3).
        """
        if len(message_core) > MAX_MESSAGE_LENGTH:
            raise SIAProtocolError(
                f"Message is {len(message_core)} characters, over the {MAX_MESSAGE_LENGTH} "
                "the length field allows"
            )
        crc = self._calculate_crc(message_core)
        length = self._calculate_length(message_core)
        return LF + crc.encode('ascii') + length.encode('ascii') + message_core + CR

    def _calculate_crc(self, data: bytes) -> str:
        """
        Calculate CRC for SIA protocol message.

        Args:
            data: Plaintext bytes from first quote through CR (excluding CR)

        Returns:
            4-character ASCII hex CRC (uppercase)

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.2
        """
        crc_value = _compute_crc_modbus(data)
        return f"{crc_value:04X}"

    def _calculate_length(self, data: bytes) -> str:
        """
        Calculate message length field.

        Args:
            data: Plaintext bytes from first quote through CR (excluding CR)

        Returns:
            Length field: "0" + 3-digit hex (e.g., "0123" = 291 bytes)

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.3
        """
        length = len(data)
        return f"0{length:03X}"

    @staticmethod
    def _validate_hex(value: str, min_len: int = 1, max_len: int | None = None) -> bool:
        """Validate string contains only hex characters."""
        if not isinstance(value, str) or len(value) < min_len:
            return False
        if max_len and len(value) > max_len:
            return False
        return all(c in "0123456789ABCDEFabcdef" for c in value)

    def _format_account_id(
        self,
        account_number: str,
        account_prefix: str = "L0",
        receiver_number: str | None = None
    ) -> str:
        """
        Format account identification fields.

        Args:
            account_number: 3-16 hex ASCII characters (required)
            account_prefix: 1-6 hex ASCII digits, default "L0" (required)
            receiver_number: 1-6 hex ASCII digits (optional; omit if None or "0")

        Returns:
            Combined string (e.g., "R2L0#001234")

        Raises:
            ValueError: If account_number or prefix invalid hex

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.6
        """
        # Validate account number
        if not self._validate_hex(account_number, 3, 16):
            raise ValueError(f"Invalid account_number: {account_number}")

        # Validate account prefix
        if not account_prefix.startswith("L") or len(account_prefix) < 2:
            raise ValueError(f"Invalid account_prefix format: {account_prefix}")
        prefix_digits = account_prefix[1:]
        if not self._validate_hex(prefix_digits, 1, 6):
            raise ValueError(f"Invalid account_prefix: {account_prefix}")

        # Build result
        result = f"{account_prefix}#{account_number}"

        # Add receiver number if provided and not "0"
        if receiver_number and receiver_number != "0":
            if not receiver_number.startswith("R") or len(receiver_number) < 2:
                raise ValueError(f"Invalid receiver_number format: {receiver_number}")
            receiver_digits = receiver_number[1:]
            if not self._validate_hex(receiver_digits, 1, 6):
                raise ValueError(f"Invalid receiver_number: {receiver_number}")
            result = f"{receiver_number}{result}"

        return result

    def _format_data_field(
        self,
        account_number: str,
        event_code: str,
        extended_data: dict[str, str] | None = None
    ) -> str:
        """
        Format unencrypted data field.

        Args:
            account_number: Account ID (3-16 hex chars)
            event_code: SIA event code (e.g., "BA", "FA", "PA", "NULL")
            extended_data: Optional dict; supports key "zone" (zone name appended after event code)

        Returns:
            Data field string: [#{account}|{event_code}] or [#{account}|{event_code} {zone}]

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.7, Annex B
        """
        if extended_data is None:
            extended_data = {}

        zone = extended_data.get("zone", "")
        if zone:
            return f"[#{account_number}|{event_code} {zone}]"
        return f"[#{account_number}|{event_code}]"

    @staticmethod
    def _format_extended_data_field(extended_data: dict[str, str] | None = None) -> str:
        """
        Format optional extended-data field per SIA DC-09 § 5.5.1.8.

        Its own bracket block, separate from [Data] (§ 5.5.1.7, where "zone" lives per the
        legacy Annex B convention handled by _format_data_field) — never merged into it.
        Currently supports only the Verification "V" identifier for a media/snapshot URL
        (story 14-1). extended_data is the same dict passed to _format_data_field(); this
        method reads "media_url" and ignores every other key.

        Args:
            extended_data: Optional dict; supports key "media_url" (Verification "V" block)

        Returns:
            "[V{media_url}]" when media_url is present and non-empty, else "" (no block —
            byte-identical to pre-14-1 frames when media_url is absent).

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.8, line 651
        """
        if not extended_data:
            return ""

        media_url = extended_data.get("media_url", "")
        if media_url:
            return f"[V{media_url}]"
        return ""

    @staticmethod
    def _format_timestamp(ts: datetime | None = None) -> str | None:
        """
        Format timestamp field per SIA DC-09 § 5.5.1.9.

        Args:
            ts: datetime object (UTC), or None to omit timestamp

        Returns:
            Formatted string: _HH:MM:SS,MM-DD-YYYY (exactly 20 characters), or None

        Reference: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.9
        Example: "_22:49:34,04-07-2026"
        """
        if ts is None:
            return None

        return ts.strftime("_%H:%M:%S,%m-%d-%Y")


def parse_frame_header(frame: bytes) -> tuple[str, str]:
    """Return the clear (token, seq) of a frame built by SIAMessageBuilder.

    Used for traces: an encrypted frame's token and seq stay in clear, so they
    can be logged without the key (story 1-5 AC7).

    Args:
        frame: Complete frame (LF + CRC + Length + message + CR)

    Returns:
        (token, seq), e.g. ("*SIA-DCS", "0001") or ("*NULL", "0000")

    Raises:
        SIAProtocolError: If the frame has no readable header.
    """
    match = _FRAME_HEADER_RE.match(frame)
    if match is None:
        raise SIAProtocolError("Frame has no readable token/sequence header")
    return match.group("token").decode("ascii"), match.group("seq").decode("ascii")


# ===== ACK/NAK Response Parser Module (Story 1.3) =====

# Constants for ACK/NAK frame structure
ACK_FRAME_MARKER = b'*ACK'
NAK_FRAME_MARKER = b'*NAK'
FRAME_LEAD = LF  # Reuse existing constant (0x0A)
FRAME_TRAIL = CR  # Reuse existing constant (0x0D)
CRC_MODBUS_POLY = 0xA001  # CRC-16 MODBUS polynomial


def _extract_frame_components(raw: bytes) -> tuple[bytes, str, bytes, bytes] | None:
    """
    Extract and validate frame structure components.

    Detects CRC format (hex or binary) and validates frame structure:
    - Hex: 0x0A + CRC(4 ASCII hex) + Length(4 ASCII hex) + message_string + 0x0D
    - Binary: 0x0A + CRC(2 bytes) + Length(4 ASCII hex) + message_string + 0x0D

    Args:
        raw: Complete raw frame bytes

    Returns:
        Tuple (crc_bytes, message_str, length_bytes, trailing_byte) on success
        None if any structural check fails (never raises)

    Reference: SIA DC-09 § 5.5.1 (frame envelope)
    """
    if len(raw) < 9:  # Minimum: LF(1) + CRC(min 2) + Length(4) + CR(1) + message(0)
        return None

    # Check leader (0x0A)
    if raw[0:1] != b'\x0A':
        return None

    # Check trailer (0x0D) at end
    if raw[-1:] != b'\x0D':
        return None

    # Detect CRC format: hex or binary
    # Per sia-dc09-expert: data[5]=='0' for hex, data[3]=='0' for binary
    # If data[5:9] looks like valid hex (4 ASCII hex digits), then hex format
    # Otherwise binary format (CRC is 2 bytes at [1:3])

    crc_is_hex = False
    if len(raw) >= 9:
        try:
            potential_length = raw[5:9].decode('ascii')
            # Check if this looks like a valid length field (4 ASCII hex)
            if all(c in '0123456789ABCDEFabcdef' for c in potential_length):
                crc_is_hex = True
        except (UnicodeDecodeError, ValueError):
            pass

    if crc_is_hex:
        # Hex CRC format: CRC is at [1:5], Length at [5:9]
        if len(raw) < 11:  # LF + CRC(4) + Length(4) + message(min 1) + CR
            return None

        crc_bytes = raw[1:5]
        if len(crc_bytes) < 4:
            return None

        length_bytes = raw[5:9]
        if len(length_bytes) < 4:
            return None

        message_start = 9
    else:
        # Binary CRC format: CRC is at [1:3], Length at [3:7]
        if len(raw) < 9:  # LF + CRC(2) + Length(4) + message(min 1) + CR
            return None

        crc_bytes = raw[1:3]
        if len(crc_bytes) < 2:
            return None

        length_bytes = raw[3:7]
        if len(length_bytes) < 4:
            return None

        message_start = 7

    # Parse length to determine message_string size
    try:
        length_str = length_bytes.decode('ascii')
        length_value = int(length_str, 16)
    except (ValueError, UnicodeDecodeError):
        return None

    # Extract message_string
    message_end = message_start + length_value
    if message_end + 1 != len(raw):  # +1 for trailer
        return None

    message_bytes = raw[message_start:message_end]

    # Decode message_string to str (Windows-1252 encoding per spec)
    try:
        message_str = message_bytes.decode('windows-1252')
    except UnicodeDecodeError:
        return None

    trailing_byte = raw[-1:]

    return (crc_bytes, message_str, length_bytes, trailing_byte)


def _validate_crc(crc_bytes: bytes, message_str: str, crc_format: CrcFormat = 'hex') -> bool:
    """
    Validate CRC matches computed value.

    Args:
        crc_bytes: CRC bytes from frame (4 ASCII hex or 2 binary)
        message_str: Message string to compute CRC over
        crc_format: 'hex' (default) or 'bin'

    Returns:
        True if CRC valid, False otherwise

    Reference: SIA DC-09 § 5.5.1.2 (CRC calculation)
    """
    # Encode message_string to bytes (Windows-1252 per spec)
    message_bytes = message_str.encode('windows-1252')

    # Compute expected CRC using MODBUS algorithm
    crc_value = _compute_crc_modbus(message_bytes)

    if crc_format == 'hex':
        # Decode hex CRC from frame
        try:
            received_crc = int(crc_bytes.decode('ascii'), 16)
        except (ValueError, UnicodeDecodeError):
            return False
    else:  # bin
        # Decode binary CRC (little-endian, 2 bytes)
        if len(crc_bytes) < 2:
            return False
        received_crc = struct.unpack('<H', crc_bytes[:2])[0]

    return received_crc == crc_value


def _compute_crc_modbus(data: bytes) -> int:
    """
    Compute CRC-16 MODBUS (polynomial 0xA001).

    Args:
        data: Bytes to compute CRC over

    Returns:
        CRC value as integer (0-65535)

    Reference: SIA DC-09 § 5.5.1.2
    """
    crc = 0
    for byte in data:
        temp = byte & 0xFF
        for _ in range(8):
            temp ^= crc & 1
            crc >>= 1
            if temp & 1:
                crc ^= 0xA001
            temp >>= 1
    return crc


def _parse_ack_nak_type_and_seq(message_str: str) -> tuple[str, int | None]:
    """
    Parse message_string to extract ACK/NAK type and sequence number.

    Args:
        message_str: Decoded message_string (e.g., '"ACK"0001R0L0A0[]')

    Returns:
        Tuple (type_str, seq_int) where:
        - type_str: 'ACK', 'NAK', or 'unknown'
        - seq_int: Sequence number as int, or None for 'unknown'

    Reference: SIA DC-09 § 5.5.3 (ACK/NAK format)
    """
    try:
        if not message_str or len(message_str) < 6:
            return (UNKNOWN_RESPONSE, None)

        # Extract id_token (between first two quotes)
        if not message_str.startswith('"'):
            return (UNKNOWN_RESPONSE, None)

        end_quote = message_str.find('"', 1)
        if end_quote < 0:
            return (UNKNOWN_RESPONSE, None)

        id_token = message_str[1:end_quote]

        # Remove encryption marker if present
        if id_token.startswith(ENCRYPTED_MARKER):
            id_token = id_token[1:]

        # Classify as ACK or NAK
        if id_token.startswith(ACK_TOKEN):
            ack_type = ACK_RESPONSE
        elif id_token.startswith(NAK_TOKEN):
            ack_type = NAK_RESPONSE
        else:
            return (UNKNOWN_RESPONSE, None)

        # Extract sequence number (4 digits after id_token)
        seq_start = end_quote + 1
        seq_end = seq_start + SEQUENCE_FIELD_LENGTH

        if seq_end > len(message_str):
            return (UNKNOWN_RESPONSE, None)

        seq_str = message_str[seq_start:seq_end]

        try:
            seq_int = int(seq_str)
        except ValueError:
            return (UNKNOWN_RESPONSE, None)

        return (ack_type, seq_int)

    except (IndexError, AttributeError, UnicodeDecodeError):
        return (UNKNOWN_RESPONSE, None)


def decode_ack_nak(raw: bytes, crc_format: CrcFormat = 'hex') -> AckNakResponse:
    """
    Parse and validate ACK/NAK response from CSR.

    Defensive parsing: never raises exceptions. Returns type='unknown' on any error.

    Args:
        raw: Complete raw response bytes from CSR
        crc_format: CRC algorithm ('hex' or 'bin'), from CSR preset. Defaults to 'hex'.

    Returns:
        AckNakResponse with keys:
        - type: 'ACK', 'NAK', or 'unknown'
        - seq: Echoed sequence number (int), or None
        - raw_nak: Full raw bytes if type='NAK', else None

    Reference: internal-docs/design/daemon-design.md § decode_ack_nak()
    """
    unknown_response: AckNakResponse = {'type': UNKNOWN_RESPONSE, 'seq': None, 'raw_nak': None}

    try:
        # Check for frame leader
        if not raw or raw[0:1] != LF:
            return unknown_response

        # Extract frame components
        components = _extract_frame_components(raw)
        if components is None:
            return unknown_response

        crc_bytes, message_str, _length_bytes, _trailing_byte = components

        # Validate CRC using specified format
        if not _validate_crc(crc_bytes, message_str, crc_format=crc_format):
            return unknown_response

        # Parse type and sequence
        ack_type, seq = _parse_ack_nak_type_and_seq(message_str)

        # Populate raw_nak only for NAK frames
        raw_nak = raw if ack_type == NAK_RESPONSE else None

        return {'type': ack_type, 'seq': seq, 'raw_nak': raw_nak}  # type: ignore

    except (IndexError, AttributeError, UnicodeDecodeError):
        return unknown_response


def parse_nak_timestamp(nak_data: bytes) -> datetime:
    """
    Extract CSR timestamp from NAK response frame.

    Args:
        nak_data: Raw NAK frame bytes (full frame, not just message_string)

    Returns:
        datetime object (UTC, timezone-aware)

    Raises:
        ValueError: If NAK data is None, missing timestamp field, or malformed

    Reference: SIA DC-09 § 5.5.3.2 (NAK message format with timestamp)
    """
    if nak_data is None or not nak_data:
        raise ValueError("NAK data is None or empty")

    try:
        # Extract frame components
        components = _extract_frame_components(nak_data)
        if components is None:
            raise ValueError("Invalid NAK frame structure")

        _crc_bytes, message_str, _length_bytes, _trailing_byte = components

        # Find timestamp delimiter (_) - it marks the start of the timestamp
        # NAK message format: "NAK"0000R0L0A0[]_HH:MM:SS,MM-DD-YYYY
        delimiter_pos = message_str.find(TIMESTAMP_DELIMITER)
        if delimiter_pos < 0:
            raise ValueError("NAK timestamp field not present (no _ delimiter)")

        # Extract timestamp value after the delimiter (19 characters: HH:MM:SS,MM-DD-YYYY)
        timestamp_start = delimiter_pos + 1
        timestamp_end = timestamp_start + TIMESTAMP_LENGTH

        if timestamp_end > len(message_str):
            raise ValueError("NAK timestamp field truncated")

        timestamp_str = message_str[timestamp_start:timestamp_end]

        # Validate timestamp format: HH:MM:SS,MM-DD-YYYY
        if not re.match(TIMESTAMP_PATTERN, timestamp_str):
            raise ValueError(f"Invalid timestamp format: {timestamp_str}")

        # Parse timestamp
        ts = datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)

        # Make timezone-aware (UTC)
        ts = ts.replace(tzinfo=timezone.utc)

        return ts

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to parse NAK timestamp: {e}") from e


# ===== ParsedMessage Dataclass & decode() (Story 9-2 Task 1) =====

@dataclass(frozen=True)
class ParsedMessage:
    """Decoded SIA DC-09 frame — all fields JSON-serializable (str/int/bool/None/dict).

    Produced by decode(). Use dataclasses.asdict(result) + json.dumps() directly.

    Fields:
        raw_hex: Original hex string passed to decode()
        crc_received: CRC as hex string (e.g. "B368")
        crc_computed: Expected CRC as hex string
        crc_valid: True if received CRC matches computed
        crc_format: "hex" or "bin"
        length_declared: Length declared in frame header
        length_actual: Actual message string byte length
        id_token: Token without encrypted marker (e.g. "SIA-DCS", "NULL", "ACK")
        encrypted: True if frame used encrypted id_token (# prefix)
        sequence: Sequence number (int)
        receiver_prefix: e.g. "R0" or "" if absent
        account_prefix: e.g. "L0"
        account: Account number string
        data_raw: Raw data block content (between [ and ]); for encrypted
            frames, the ciphertext hex after '['
        data_decrypted: Decrypted region content, pad stripped (None if not
            encrypted, no key provided, or decryption failed)
        extended_fields: Parsed extended data fields dict
        timestamp_str: Raw timestamp string after _ delimiter (from the
            plaintext for encrypted frames), or None
        decrypt_error: Why decryption failed (never contains key or pad), or None
    """
    raw_hex: str
    crc_received: str
    crc_computed: str
    crc_valid: bool
    crc_format: str
    length_declared: int
    length_actual: int
    id_token: str
    encrypted: bool
    sequence: int
    receiver_prefix: str
    account_prefix: str
    account: str
    data_raw: str
    data_decrypted: str | None
    extended_fields: dict[str, str]
    timestamp_str: str | None
    decrypt_error: str | None = None


_NOT_A_DATA_BLOCK = "Decryption failed: plaintext is not a DC-09 data block (wrong key?)"


def _decrypt_region(hex_text: str, key: bytes) -> tuple[str | None, str | None]:
    """Decrypt an encrypted region for display.

    Without a MAC a wrong key cannot be detected for sure, so the content is
    sanity-checked: it must end with ']' followed by the timestamp, which
    § 5.5.1.9 makes mandatory in encrypted messages. Content decodes as
    windows-1252 with errors="replace" (AC1) — some receivers put extended-
    data bytes ≥ 0x80 in the region, so charset is not part of the sanity
    check.

    Returns:
        (content, None) on success, (None, error) otherwise. Neither carries
        the key or the pad.
    """
    try:
        content = SIACipher(key).decrypt(hex_text)
    except AESKeyError as e:
        return None, str(e)
    except AESDecryptionError as e:
        return None, f"Decryption failed: {e}"
    if b"]" not in content:
        return None, _NOT_A_DATA_BLOCK
    text = content.decode('windows-1252', errors='replace')
    timestamp = _region_timestamp(text)
    if timestamp is None or not re.match(TIMESTAMP_PATTERN, timestamp):
        return None, _NOT_A_DATA_BLOCK
    return text, None


def _region_timestamp(content: str) -> str | None:
    """Timestamp after the last ']' of a decrypted region, without its '_'."""
    tail = content[content.rfind(']') + 1:]
    return tail[1:] if tail.startswith(TIMESTAMP_DELIMITER) else None


def decode(raw_hex: str, key: bytes | None = None) -> ParsedMessage:
    """Decode a SIA DC-09 frame from its hex representation.

    Converts hex string to bytes internally via bytes.fromhex(), then reuses
    _extract_frame_components() and _validate_crc() for parsing.

    CRC mismatch does NOT raise — sets crc_valid=False in the result.

    Args:
        raw_hex: Hex string of the complete frame (LF + CRC + Length + Message + CR).
        key: Optional AES key (16, 24 or 32 bytes) for decryption of encrypted frames.

    Returns:
        ParsedMessage with all parsed fields (all JSON-serializable).

    Raises:
        SIAProtocolError: If frame cannot be parsed (malformed structure, bad hex).
    """
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError as e:
        raise SIAProtocolError(f"Invalid hex input: {e}") from e

    components = _extract_frame_components(raw)
    if components is None:
        raise SIAProtocolError("Malformed frame structure")

    crc_bytes, message_str, length_bytes, _trailing = components

    # Determine CRC format by inspecting crc_bytes length
    detected_format: CrcFormat = 'hex' if len(crc_bytes) == 4 else 'bin'

    # Compute received CRC string (hex representation)
    if detected_format == 'hex':
        try:
            crc_received_str = crc_bytes.decode('ascii').upper()
        except UnicodeDecodeError as e:
            raise SIAProtocolError(f"Invalid CRC bytes: {e}") from e
    else:
        val = struct.unpack('<H', crc_bytes[:2])[0]
        crc_received_str = f"{val:04X}"

    # Compute expected CRC
    crc_computed_int = _compute_crc_modbus(message_str.encode('windows-1252'))
    crc_computed_str = f"{crc_computed_int:04X}"

    # Validate CRC (non-fatal — populates crc_valid)
    crc_valid = _validate_crc(crc_bytes, message_str, crc_format=detected_format)

    # Parse length
    try:
        length_declared = int(length_bytes.decode('ascii'), 16)
    except (ValueError, UnicodeDecodeError) as e:
        raise SIAProtocolError(f"Invalid length field: {e}") from e
    length_actual = len(message_str.encode('windows-1252'))

    # Parse message string fields
    id_token, encrypted, sequence, receiver_prefix, account_prefix, account, data_raw, timestamp_str = \
        _parse_message_fields(message_str)

    # Decrypt if key provided and frame is encrypted (§ 5.4.3)
    data_decrypted: str | None = None
    decrypt_error: str | None = None
    if encrypted and key is not None:
        data_decrypted, decrypt_error = _decrypt_region(data_raw, key)
        if data_decrypted is not None:
            timestamp_str = _region_timestamp(data_decrypted)

    return ParsedMessage(
        raw_hex=raw_hex,
        crc_received=crc_received_str,
        crc_computed=crc_computed_str,
        crc_valid=crc_valid,
        crc_format=detected_format,
        length_declared=length_declared,
        length_actual=length_actual,
        id_token=id_token,
        encrypted=encrypted,
        sequence=sequence,
        receiver_prefix=receiver_prefix,
        account_prefix=account_prefix,
        account=account,
        data_raw=data_raw,
        data_decrypted=data_decrypted,
        extended_fields={},
        timestamp_str=timestamp_str,
        decrypt_error=decrypt_error,
    )


def _parse_message_fields(
    message_str: str,
) -> tuple[str, bool, int, str, str, str, str, str | None]:
    """Parse SIA DC-09 message string into individual fields.

    Message format per § 5.5:
        "id_token"seqRrecvLpfx#account[data]_timestamp

    Args:
        message_str: Decoded message string from frame.

    Returns:
        Tuple: (id_token, encrypted, sequence, receiver_prefix,
                account_prefix, account, data_raw, timestamp_str)

    Raises:
        SIAProtocolError: If message string structure is invalid.
    """
    try:
        # 1. Extract id_token between quotes
        if not message_str.startswith('"'):
            raise SIAProtocolError(f"Message does not start with quote: {message_str[:20]!r}")
        end_quote = message_str.find('"', 1)
        if end_quote < 0:
            raise SIAProtocolError("No closing quote for id_token")
        raw_token = message_str[1:end_quote]
        encrypted = raw_token.startswith(ENCRYPTED_MARKER)
        # Strip encryption marker char to get clean token name
        id_token = raw_token[1:] if encrypted else raw_token

        pos = end_quote + 1

        # 2. Extract 4-digit sequence number
        if pos + SEQUENCE_FIELD_LENGTH > len(message_str):
            raise SIAProtocolError("Message too short for sequence field")
        seq_str = message_str[pos:pos + SEQUENCE_FIELD_LENGTH]
        try:
            sequence = int(seq_str)
        except ValueError as e:
            raise SIAProtocolError(f"Invalid sequence number: {seq_str!r}") from e
        pos += SEQUENCE_FIELD_LENGTH

        # 3. Find account number (at # sign)
        hash_pos = message_str.find('#', pos)
        if hash_pos < 0:
            raise SIAProtocolError("No account # marker found")
        prefix_section = message_str[pos:hash_pos]

        # Parse receiver prefix (starts with R) and account prefix (starts with L)
        receiver_prefix = ""
        account_prefix = ""
        r_match = re.match(r'(R[0-9A-Fa-f]{1,6})', prefix_section)
        if r_match:
            receiver_prefix = r_match.group(1)
            prefix_section = prefix_section[r_match.end():]
        l_match = re.match(r'(L[0-9A-Fa-f]{1,6})', prefix_section)
        if l_match:
            account_prefix = l_match.group(1)

        # 4. Extract account (from # to [)
        bracket_open = message_str.find('[', hash_pos)
        if bracket_open < 0:
            raise SIAProtocolError("No data block [ found")
        account = message_str[hash_pos + 1:bracket_open]

        # 5a. Encrypted: the hex runs from '[' to the end of the message, with
        # no ']' (§ 5.4.3, story 1-5 D1). '[hex]' (§ 5.4.7 example) is accepted.
        # The timestamp is inside the ciphertext.
        if encrypted:
            data_raw = message_str[bracket_open + 1:]
            if data_raw.endswith(']'):
                data_raw = data_raw[:-1]
            return (id_token, encrypted, sequence, receiver_prefix,
                    account_prefix, account, data_raw, None)

        # 5. Extract data block (between [ and ])
        bracket_close = message_str.find(']', bracket_open)
        if bracket_close < 0:
            raise SIAProtocolError("No data block ] found")
        data_raw = message_str[bracket_open + 1:bracket_close]

        # 6. Extract timestamp (after _ delimiter)
        timestamp_str: str | None = None
        underscore_pos = message_str.find('_', bracket_close)
        if underscore_pos >= 0:
            timestamp_str = message_str[underscore_pos + 1:]

        return (id_token, encrypted, sequence, receiver_prefix,
                account_prefix, account, data_raw, timestamp_str)

    except SIAProtocolError:
        raise
    except Exception as e:
        raise SIAProtocolError(f"Failed to parse message fields: {e}") from e


if __name__ == '__main__':
    import json
    import os
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == '--decode':
        hex_input = sys.argv[2]
        key_hex = os.environ.get('SIA_ENCRYPTION_KEY', '')
        try:
            key = parse_hex_key(key_hex) if key_hex.strip() else None
            result = decode(hex_input, key)
            print(json.dumps(dataclasses.asdict(result)))
        except (SIAProtocolError, AESKeyError, ValueError) as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
