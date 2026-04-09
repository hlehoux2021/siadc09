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

from datetime import datetime
from typing import Dict, Literal, Optional

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

    def reset(self, account_number: Optional[str] = None) -> None:
        """
        Reset sequence counter for specified account or all accounts.

        Args:
            account_number: Account to reset. If None, resets ALL accounts.
        """
        if account_number is None:
            self._seq_map.clear()
        else:
            self._seq_map[account_number] = 0


# Backward compatibility alias
class SequenceManager(SequenceTracker):
    """
    Deprecated: Use SequenceTracker or SIAMessageBuilder instead.

    This class exists only for backward compatibility with code that may have
    imported SequenceManager directly. In v1.0+, use:
    - SIAMessageBuilder: For full message building with integrated sequence tracking
    - SequenceTracker: If you need only sequence management without message building

    SequenceManager and SequenceTracker are identical; this is just a renamed alias.
    """


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

    def __init__(self, crc_format: Literal["SIA", "ADM"]) -> None:
        """
        Initialize message builder with CRC format.

        Args:
            crc_format: CRC algorithm ("SIA" or "ADM") - set once, used for all messages

        Instance Variables:
            crc_format: Configured CRC algorithm for this builder
            _sequence_tracker: Per-account sequence number tracker
        """
        self.crc_format: Literal["SIA", "ADM"] = crc_format
        self._sequence_tracker = SequenceTracker()

    # ===== Public Methods =====

    def encode_message(
        self,
        account_number: str,
        event_code: str,
        account_prefix: str = "L0",
        receiver_number: Optional[str] = None,
        extended_data: Optional[Dict] = None,
        timestamp: Optional[datetime] = None,
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
            timestamp: Optional datetime (UTC); None = omit timestamp
            encryption: Whether to encrypt (default False)

        Returns:
            Complete frame as bytes: LF + CRC + Length + Message + CR

        Raises:
            ValueError: If account_number, prefix, or receiver_number invalid hex

        Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1
        """
        if extended_data is None:
            extended_data = {}

        # Build message components per spec § 5.5.1
        account_id_str = self._format_account_id(account_number, account_prefix, receiver_number)
        data_field = self._format_data_field(account_number, event_code, extended_data)
        timestamp_str = self._format_timestamp(timestamp)

        # Select ID token per § 5.5.1.4
        if encryption:
            id_token = f'"{ENCRYPTED_MARKER}{SIA_DCS_TOKEN}"'
        else:
            id_token = f'"{SIA_DCS_TOKEN}"'

        # Sequence number (auto-incremented per account)
        seq = self._sequence_tracker.next_seq(account_number)

        # Build message core (everything included in CRC calculation)
        message_core_str = id_token + seq + account_id_str + data_field
        if timestamp_str is not None:
            message_core_str += timestamp_str

        message_core = message_core_str.encode('ascii')

        # Calculate CRC and length
        crc = self._calculate_crc(message_core)
        length = self._calculate_length(message_core)

        # Build complete frame: LF + CRC + Length + Message + CR
        frame = (
            LF +
            crc.encode('ascii') +
            length.encode('ascii') +
            message_core +
            CR
        )

        return frame

    def make_supervision_message(
        self,
        account_number: str,
        account_prefix: str = "L0",
        receiver_number: Optional[str] = None,
        encryption: bool = False
    ) -> bytes:
        """
        Create a NULL/supervision message.

        Args:
            account_number: 3-16 hex ASCII characters
            account_prefix: Optional prefix (default "L0")
            receiver_number: Optional receiver number
            encryption: Whether to encrypt (default False)

        Returns:
            Complete NULL message frame as bytes

        Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.2.1
        """
        return self.encode_message(
            account_number=account_number,
            event_code=SIA_NULL_CODE,
            account_prefix=account_prefix,
            receiver_number=receiver_number,
            encryption=encryption
        )

    def reset_sequence(self, account_number: Optional[str] = None) -> None:
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

    def _compute_crc_modbus(self, data: bytes) -> int:
        """
        Compute CRC-16 MODBUS (polynomial 0xA001).

        Per expert validation, SIA DC-09 uses CRC-16 MODBUS, NOT CRC-32.

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

    def _calculate_crc(self, data: bytes) -> str:
        """
        Calculate CRC for SIA protocol message.

        Args:
            data: Plaintext bytes from first quote through CR (excluding CR)

        Returns:
            4-character ASCII hex CRC (uppercase)

        Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.2
        """
        crc_value = self._compute_crc_modbus(data)
        return f"{crc_value:04X}"

    def _calculate_length(self, data: bytes) -> str:
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

    @staticmethod
    def _validate_hex(value: str, min_len: int = 1, max_len: Optional[int] = None) -> bool:
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
        receiver_number: Optional[str] = None
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

        Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.6
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
        return f"[#{account_number}|{event_code}]"

    @staticmethod
    def _format_timestamp(ts: Optional[datetime] = None) -> Optional[str]:
        """
        Format timestamp field per SIA DC-09 § 5.5.1.9.

        Args:
            ts: datetime object (UTC), or None to omit timestamp

        Returns:
            Formatted string: _HH:MM:SS,MM-DD-YYYY (exactly 20 characters), or None

        Reference: docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.9
        Example: "_22:49:34,04-07-2026"
        """
        if ts is None:
            return None

        return ts.strftime("_%H:%M:%S,%m-%d-%Y")
