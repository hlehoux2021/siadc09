"""
SIA DC-09-2021.17 Protocol Message Builder Module

Pure protocol layer for constructing and serializing SIA DC-09 compliant message frames.
No external dependencies beyond Python stdlib.

Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5 Messages

Expert Validation: sia-dc09-expert (2026-04-07)
- CRC: CRC-16 MODBUS (polynomial 0xA001)
- Timestamp: Formatted string _HH:MM:SS,MM-DD-YYYY (20 chars, UTC)
- Message frame: LF + CRC + Length + Message + CR
"""

import zlib
from datetime import datetime, timezone
from typing import Dict, Optional

# ===== TASK 1: Frame Component Constants =====

# Frame delimiters (binary)
LF = b'\x0A'  # Line feed (0x0A)
CR = b'\x0D'  # Carriage return (0x0D)

# NULL code for supervision messages
SIA_NULL_CODE = "0000"

# Event type codes (per SIA spec, as 4-digit hex strings)
BURGLARY = "1"
FIRE = "2"
PANIC = "3"

# ID tokens (unencrypted vs encrypted)
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


# ===== TASK 3: Sequence Number Management =====

class SequenceManager:
    """
    Maintains separate sequence counter per account number.
    Wraps from 9999 → 0001 (never 0000).

    Per SIA DC-09 § 5.5.1.5: "Sequence numbers are associated with PE account numbers"
    """

    def __init__(self):
        """Initialize empty sequence state."""
        self._seq_map: Dict[str, int] = {}

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


# ===== TASK 2: CRC and Length Calculation =====

def _compute_crc_modbus(data: bytes) -> int:
    """
    Compute CRC-16 MODBUS (polynomial 0xA001).

    Per expert validation and reference implementation,
    SIA DC-09 uses CRC-16 MODBUS, NOT CRC-32.

    Args:
        data: Bytes to compute CRC over

    Returns:
        CRC value as integer
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


def calculate_crc(data: bytes, crc_format: str) -> str:
    """
    Calculate CRC for SIA protocol message.

    Args:
        data: Plaintext bytes from first quote through CR (excluding CR)
        crc_format: CRC algorithm selector ("SIA", "ADM")

    Returns:
        4-character ASCII hex CRC (uppercase)

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.2
    Expert: sia-dc09-expert (uses CRC-16 MODBUS polynomial 0xA001)
    """
    if crc_format not in [CRC_FORMAT_SIA, CRC_FORMAT_ADM]:
        raise ValueError(f"CRC format not supported: {crc_format}")

    # Both SIA and ADM use CRC-16 MODBUS
    crc_value = _compute_crc_modbus(data)
    return f"{crc_value:04X}"


def calculate_length(data: bytes) -> str:
    """
    Calculate message length field.

    Args:
        data: Plaintext bytes from first quote through CR (excluding CR)

    Returns:
        Length field: "0" + 3-digit hex (e.g., "0123" = 291 bytes)

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.3
    """
    length = len(data)
    return f"0{length:03X}"


# ===== TASK 4: Account Identification Fields =====

def _validate_hex(value: str, min_len: int = 1, max_len: int = None) -> bool:
    """Validate string contains only hex characters."""
    if not isinstance(value, str) or len(value) < min_len:
        return False
    if max_len and len(value) > max_len:
        return False
    return all(c in "0123456789ABCDEFabcdef" for c in value)


def format_account_id(
    account_number: str,
    account_prefix: str = "L0",
    receiver_number: Optional[str] = None
) -> str:
    """
    Format account identification fields.

    Args:
        account_number: 3-16 hex ASCII characters (required)
        account_prefix: 1-6 hex ASCII digits, default "L0" (required)
        receiver_number: 1-6 hex ASCII digits (optional; omit if None or "0")

    Returns:
        Combined string (e.g., "#001234L1R2")

    Raises:
        ValueError: If account_number or prefix invalid hex

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.6
    """
    # Validate account number
    if not _validate_hex(account_number, 3, 16):
        raise ValueError(f"Invalid account_number: {account_number}")

    # Validate account prefix - must start with "L" and have 1-6 hex digits after
    if not account_prefix.startswith("L") or len(account_prefix) < 2:
        raise ValueError(f"Invalid account_prefix format: {account_prefix}")
    prefix_digits = account_prefix[1:]  # Skip the "L"
    if not _validate_hex(prefix_digits, 1, 6):
        raise ValueError(f"Invalid account_prefix: {account_prefix}")

    # Build result
    result = f"#{account_number}{account_prefix}"

    # Add receiver number if provided and not "0"
    if receiver_number and receiver_number != "0":
        if not receiver_number.startswith("R") or len(receiver_number) < 2:
            raise ValueError(f"Invalid receiver_number format: {receiver_number}")
        receiver_digits = receiver_number[1:]  # Skip the "R"
        if not _validate_hex(receiver_digits, 1, 6):
            raise ValueError(f"Invalid receiver_number: {receiver_number}")
        result = f"{receiver_number}" + result  # Receiver comes first per spec

    return result


# ===== TASK 5: Message Data Field (Unencrypted) =====

def format_data_field(
    account_number: str,
    event_code: str,
    extended_data: Optional[Dict] = None
) -> str:
    """
    Format unencrypted data field.

    Args:
        account_number: Account ID (3-16 hex chars)
        event_code: 4-digit event code (e.g., "1130")
        extended_data: Optional dict of additional fields (deferred to v1.1)

    Returns:
        Data field string: [#{account}|{event_code}...]

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.7
    """
    if extended_data is None:
        extended_data = {}

    # Basic format: [#{account}|{event_code}]
    data = f"[#{account_number}|{event_code}]"

    return data


# ===== TASK 6: Timestamp Field =====

def format_timestamp(ts: Optional[datetime] = None) -> str:
    """
    Format timestamp field per SIA DC-09 § 5.5.1.9.

    Args:
        ts: datetime object (UTC) or None for current time

    Returns:
        Formatted string: _HH:MM:SS,MM-DD-YYYY (exactly 20 characters)

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.9
    Expert Validation: sia-dc09-expert (formatted string, NOT hex)

    Example: "_22:49:34,04-07-2026"
    """
    if ts is None:
        ts = datetime.now(timezone.utc)

    # Format: _HH:MM:SS,MM-DD-YYYY (20 chars exactly)
    return ts.strftime("_%H:%M:%S,%m-%d-%Y")


# ===== TASK 7: Core `encode_message()` Function =====

def encode_message(
    account_number: str,
    event_code: str,
    account_prefix: str = "L0",
    receiver_number: Optional[str] = None,
    extended_data: Optional[Dict] = None,
    timestamp: Optional[datetime] = None,
    *,
    crc_format: str,
    encryption: bool = False
) -> bytes:
    """
    Encode a complete SIA protocol message frame.

    Args:
        account_number: 3-16 hex ASCII characters
        event_code: 4-digit event code (e.g., "1130" for burglary)
        account_prefix: 1-6 hex digits (default "L0")
        receiver_number: Optional 1-6 hex digits
        extended_data: Optional additional fields
        timestamp: Optional datetime (UTC); None = current time
        crc_format: REQUIRED, keyword-only. CRC algorithm ("SIA" or "ADM")
        encryption: Whether data is encrypted (default False)

    Returns:
        Complete frame as bytes: LF + CRC + Length + Message + CR

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1
    Expert Validation: sia-dc09-expert
    """
    if extended_data is None:
        extended_data = {}

    # Build message components per spec § 5.5.1
    account_id_str = format_account_id(account_number, account_prefix, receiver_number)
    data_field = format_data_field(account_number, event_code, extended_data)
    timestamp_str = format_timestamp(timestamp)

    # Select ID token per § 5.5.1.4 and § 5.5.1.4.1
    if encryption:
        id_token = f'"{ENCRYPTED_MARKER}{SIA_DCS_TOKEN}"'
    else:
        id_token = f'"{SIA_DCS_TOKEN}"'

    # Sequence number (4 digits per spec § 5.5.1.5)
    # Note: Caller should use SequenceManager for proper per-account sequencing
    seq = "0001"

    # Build message core (everything included in CRC calculation)
    # Per § 5.5.1.2: "starting with the first quote character of the ID
    # and ending with the character before the terminating CR"
    message_core = (
        id_token +
        seq +
        account_id_str +
        data_field +
        timestamp_str
    ).encode('ascii')

    # Calculate CRC and length per § 5.5.1.2 and § 5.5.1.3
    crc = calculate_crc(message_core, crc_format)
    length = calculate_length(message_core)

    # Build complete frame: LF + CRC + Length + Message + CR
    frame = (
        LF +
        crc.encode('ascii') +
        length.encode('ascii') +
        message_core +
        CR
    )

    return frame


# ===== TASK 8: Supervision NULL Message Helper =====

def make_supervision_message(
    account_number: str,
    *,
    crc_format: str,
    encryption: bool = False,
    account_prefix: str = "L0",
    receiver_number: Optional[str] = None
) -> bytes:
    """
    Create a NULL/supervision message.

    Args:
        account_number: 3-16 hex ASCII characters
        crc_format: REQUIRED, keyword-only. CRC algorithm selector
        encryption: Whether to encrypt (default False)
        account_prefix: Optional prefix (default "L0")
        receiver_number: Optional receiver number

    Returns:
        Complete NULL message frame as bytes

    Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.2.1
    """
    # NULL message uses event code "0000" per § 5.5.2.1
    return encode_message(
        account_number=account_number,
        event_code=SIA_NULL_CODE,
        account_prefix=account_prefix,
        receiver_number=receiver_number,
        crc_format=crc_format,
        encryption=encryption
    )


# Module-level sequence manager (can be used or replaced by caller)
_default_seq_manager = SequenceManager()


def get_sequence_manager() -> SequenceManager:
    """Get the default module-level sequence manager."""
    return _default_seq_manager
