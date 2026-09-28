"""
CSR Simulator Framework

Standalone test tool that accepts UDP/TCP connections and generates valid CSR responses.
Uses the SIA DC-09-2021.17 protocol to simulate a Central Station Receiver (CSR) for testing.

Module Structure:
- CSRSimulatorError: Exception for simulator-specific errors
- _validate_preset(): Validates CSR preset configuration
- CSRSimulator: Main simulator class with UDP/TCP server support
"""

import asyncio
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict

from resources.siadc09d.sia_crypto import SIACipher
from resources.siadc09d.sia_protocol import (
    ENCRYPTED_MARKER,
    ENCRYPTED_REGION_TERMINATOR,
    NULL_TOKEN,
    SIA_DCS_TOKEN,
    SIA_NULL_CODE,
    TIMESTAMP_DELIMITER,
    TIMESTAMP_FORMAT,
    CrcFormat,
    SIAProtocolError,
    _compute_crc_modbus,
    _extract_frame_components,
    decode,
    decode_ack_nak,
)


logger = logging.getLogger(__name__)

# Largest legal frame is LF + CRC(4) + LEN(4) + 0xFFF + CR = 4105 bytes (§ 5.5.1.3).
UDP_RECEIVE_BUFFER_SIZE = 4200

# Receiver timestamp window (§ 5.5.1.9): message time may be up to 20 s ahead
# of, or 40 s behind, the receiver clock. (ahead_s, behind_s).
DEFAULT_TIMESTAMP_WINDOW_S: tuple[float, float] = (20.0, 40.0)

# § 5.5.3.2 NAK template; the receiver timestamp is appended when enabled.
NAK_MESSAGE = '"NAK"0000R0L0#0[]'

# Parsed type of an encrypted frame the simulator cannot decrypt.
UNDECRYPTABLE = 'undecryptable'

ResponseType = Literal['ACK', 'NAK', 'DISCARD']


class CSRSimulatorPreset(TypedDict):
    """CSR Simulator preset configuration.

    Defines the shape of the dict passed to CSRSimulator and _validate_preset().
    Separate from CSRPreset (daemon-side PE→CSR config) because the simulator
    IS the CSR: it needs the actual encryption key bytes and has no use for
    supervision intervals or connect timeouts.
    """
    crc_format: CrcFormat
    account_number: str
    encryption_key: bytes | None


class CSRSimulatorError(Exception):
    """Exception raised for CSR Simulator-specific errors."""
    pass


def _validate_preset(preset: CSRSimulatorPreset) -> None:
    """
    Validate CSR preset configuration.

    Validates required fields and raises CSRSimulatorError if invalid.

    Args:
        preset: CSRSimulatorPreset with keys crc_format, account_number, encryption_key

    Raises:
        CSRSimulatorError: If preset is invalid
    """
    # Validate crc_format
    if 'crc_format' not in preset:
        raise CSRSimulatorError("Missing required preset field: 'crc_format'")

    crc_format = preset['crc_format']
    if crc_format not in ('hex', 'bin'):
        raise CSRSimulatorError(f"Invalid crc_format: '{crc_format}' (must be 'hex' or 'bin')")

    # Validate encryption_key type
    if 'encryption_key' in preset:
        enc_key = preset['encryption_key']
        if enc_key is not None and not isinstance(enc_key, bytes):
            raise CSRSimulatorError(f"Invalid encryption_key type: must be bytes or None, got {type(enc_key).__name__}")

    # Validate account_number
    if 'account_number' in preset:
        account = preset['account_number']
        if not isinstance(account, str):
            raise CSRSimulatorError(f"account_number must be string, got {type(account).__name__}")

        if len(account) < 3 or len(account) > 16:
            raise CSRSimulatorError(f"account_number must be 3-16 characters, got {len(account)}")

        # Validate hex format
        try:
            int(account, 16)
        except ValueError:
            raise CSRSimulatorError(f"account_number must be valid hex characters, got '{account}'")


class CSRSimulator:
    """
    CSR Simulator — Standalone test tool for SIA DC-09 protocol testing.

    Accepts UDP/TCP connections and generates valid CSR responses (ACK/NAK).
    Uses preset configuration to determine CRC format and encryption.

    Instance Variables:
        udp_port: Port for UDP listening
        tcp_port: Port for TCP listening
        preset: CSRSimulatorPreset (crc_format, account_number, encryption_key)
        response_delay_ms: Simulated response latency in milliseconds
        _naks_remaining: Frames still to NAK before ACKing (NAK-first mode)
        _clock_skew_s: Receiver clock offset from UTC, in seconds
        _nak_with_timestamp: Whether NAKs carry the receiver timestamp
        _timestamp_window_s: (ahead_s, behind_s) window for encrypted frames, or None
        _udp_socket: UDP socket instance (None until started)
        _tcp_server: TCP server instance (None until started)
        _udp_task: Asyncio task running the UDP handler loop
        _running: Flag indicating if simulator is running
        _logger: Module logger instance
    """

    def __init__(
        self,
        udp_port: int,
        tcp_port: int,
        preset: CSRSimulatorPreset,
        response_delay_ms: float = 0,
        *,
        nak_first: int = 0,
        clock_skew_s: float = 0.0,
        nak_with_timestamp: bool = True,
        timestamp_window_s: tuple[float, float] | None = None,
    ) -> None:
        """
        Initialize CSR Simulator.

        Args:
            udp_port: UDP port to listen on
            tcp_port: TCP port to listen on
            preset: CSRSimulatorPreset configuration
            response_delay_ms: Simulated response latency (default 0)
            nak_first: NAK this many accepted events/NULLs, then ACK (1 = NAK-once mode)
            clock_skew_s: Receiver clock offset from UTC, used by the NAK
                timestamp and the window check
            nak_with_timestamp: False sends NAKs without a timestamp
            timestamp_window_s: (ahead_s, behind_s) window applied to encrypted
                frames (e.g. DEFAULT_TIMESTAMP_WINDOW_S); None disables the check

        Raises:
            CSRSimulatorError: If preset validation fails
        """
        # Validate preset at startup (fail-fast per ADR-09)
        _validate_preset(preset)

        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.preset = preset
        self.response_delay_ms = response_delay_ms
        self._naks_remaining: int = nak_first
        self._clock_skew_s: float = clock_skew_s
        self._nak_with_timestamp: bool = nak_with_timestamp
        self._timestamp_window_s: tuple[float, float] | None = timestamp_window_s

        self._udp_socket: socket.socket | None = None
        self._tcp_server: asyncio.Server | None = None
        self._udp_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Start both UDP and TCP servers.

        Raises:
            CSRSimulatorError: If server startup fails
        """
        try:
            self._running = True
            self._logger.info(f"CSR Simulator starting on UDP:{self.udp_port}, TCP:{self.tcp_port}")

            # Start UDP server (using socket, non-blocking)
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_socket.bind(('0.0.0.0', self.udp_port))
            self._logger.debug(f"UDP socket bound to port {self.udp_port}")

            # Start TCP server (using asyncio.start_server)
            self._tcp_server = await asyncio.start_server(
                self._handle_tcp_client,
                '0.0.0.0',
                self.tcp_port
            )
            self._logger.debug(f"TCP server listening on port {self.tcp_port}")

            # Start UDP handler task
            self._udp_task = asyncio.create_task(self._handle_udp())

            self._logger.info("CSR Simulator started successfully")

        except Exception as e:
            self._running = False
            raise CSRSimulatorError(f"Failed to start simulator: {e}") from e

    async def stop(self) -> None:
        """
        Stop both UDP and TCP servers.

        Performs graceful shutdown of all connections and sockets.
        """
        self._running = False

        # Cancel UDP handler task
        if self._udp_task and not self._udp_task.done():
            self._udp_task.cancel()
            try:
                await self._udp_task
            except asyncio.CancelledError:
                pass

        # Close TCP server
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
            self._logger.debug("TCP server closed")

        # Close UDP socket
        if self._udp_socket:
            self._udp_socket.close()
            self._logger.debug("UDP socket closed")

        self._logger.info("CSR Simulator stopped")

    async def _handle_udp(self) -> None:
        """
        Handle UDP frame reception and response.

        Receives frames on UDP port, parses them, and sends back ACK/NAK.
        Runs continuously while simulator is running.
        """
        if not self._udp_socket:
            return

        while self._running:
            try:
                # Receive frame and sender address (blocking, so use executor)
                loop = asyncio.get_event_loop()
                sock = self._udp_socket  # Type guard for mypy
                frame_data, addr = await loop.run_in_executor(
                    None,
                    lambda: sock.recvfrom(UDP_RECEIVE_BUFFER_SIZE)
                )

                self._logger.debug(f"[RX] UDP frame from {addr[0]}:{addr[1]}")

                _response_type, response_frame = self._build_response(frame_data)
                if response_frame:
                    await self._send_response_udp(sock, response_frame, addr, self.response_delay_ms)

            except Exception as e:
                if self._running:
                    self._logger.error(f"UDP reception error: {e}")

    async def _handle_tcp_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle TCP client connection.

        Receives frames from TCP client, parses them, and sends back ACK/NAK.
        Closes connection on client disconnect or error.

        Args:
            reader: asyncio StreamReader for reading from client
            writer: asyncio StreamWriter for writing to client
        """
        addr = writer.get_extra_info('peername')
        self._logger.debug(f"[TCP] Client connected from {addr[0]}:{addr[1]}")

        try:
            while self._running:
                # Read complete frame with timeout (LF + CRC + Length + Message + CR)
                try:
                    frame_data = await asyncio.wait_for(
                        self._receive_frame_tcp(reader),
                        timeout=5.0
                    )

                    if not frame_data:
                        break  # Client disconnected

                    self._logger.debug(f"[RX] TCP frame from {addr[0]}:{addr[1]}")

                    _response_type, response_frame = self._build_response(frame_data)
                    if response_frame:
                        await self._send_response_tcp(writer, response_frame, self.response_delay_ms)

                except asyncio.TimeoutError:
                    # No data for 5 seconds, client idle
                    break
                except asyncio.IncompleteReadError:
                    # Client disconnected
                    break

        except Exception as e:
            if self._running:
                self._logger.error(f"TCP client error from {addr[0]}:{addr[1]}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self._logger.debug(f"[TCP] Client disconnected from {addr[0]}:{addr[1]}")

    def _receive_frame_udp(self, sock: socket.socket) -> tuple[bytes, tuple[str, int]] | None:
        """
        Receive UDP frame with validation.

        Args:
            sock: UDP socket

        Returns:
            Tuple of (frame_bytes, (sender_ip, sender_port)) or None on error
        """
        try:
            frame, addr = sock.recvfrom(UDP_RECEIVE_BUFFER_SIZE)

            # Validate frame structure (leader/trailer)
            if not frame.startswith(b'\x0A') or not frame.endswith(b'\x0D'):
                self._logger.warning(f"Invalid frame structure from {addr[0]}:{addr[1]}")
                return None

            return (frame, addr)
        except Exception as e:
            self._logger.error(f"UDP frame reception error: {e}")
            return None

    async def _receive_frame_tcp(self, reader: asyncio.StreamReader) -> bytes | None:
        """
        Receive TCP frame with validation.

        Args:
            reader: asyncio StreamReader

        Returns:
            Frame bytes or None on error
        """
        try:
            # Read frame structure: LF + CRC + Length + Message + CR
            frame = await reader.readuntil(b'\x0D')

            # Validate structure
            if not frame.startswith(b'\x0A') or not frame.endswith(b'\x0D'):
                self._logger.warning("Invalid TCP frame structure")
                return None

            return frame
        except Exception as e:
            if self._running:
                self._logger.debug(f"TCP frame reception: {e}")
            return None

    def _build_response(self, frame_data: bytes) -> tuple[ResponseType, bytes | None]:
        """
        Parse an inbound frame, decide the answer and build it.

        Args:
            frame_data: Raw inbound frame

        Returns:
            (decision, frame); frame is None for DISCARD or when generation failed
        """
        parsed = self._parse_received_message(frame_data, self.preset)
        encrypted = self._detect_encryption_from_frame(frame_data)
        seq = parsed.get('seq') or 0
        self._log_frame_exchange('RX', str(parsed.get('type', 'unknown')), seq, encrypted,
                                 datetime.now(timezone.utc))

        decision = self._decide_response(parsed, self.preset)
        if decision == 'DISCARD':
            # § 5.6.2.4: a message that cannot be decrypted gets no ACK and no NAK.
            self._logger.info(f"[RX] seq={seq:04d} could not be decrypted, discarded (no response)")
            return decision, None

        if decision == 'ACK' and parsed.get('encrypted'):
            frame = self._generate_ack_frame(
                seq, self.preset, True,
                account=parsed.get('header_account'),
                receiver_prefix=parsed.get('receiver_prefix', ''),
                account_prefix=parsed.get('account_prefix', ''),
            )
        elif decision == 'ACK':
            frame = self._generate_ack_frame(seq, self.preset, False)
        else:
            frame = self._generate_nak_frame(self.preset)

        if frame:
            ack_encrypted = decision == 'ACK' and bool(parsed.get('encrypted'))
            self._log_frame_exchange('TX', decision, seq if decision == 'ACK' else 0, ack_encrypted,
                                     datetime.now(timezone.utc))
        return decision, frame or None

    def _decide_response(self, parsed_frame: dict, preset: CSRSimulatorPreset) -> ResponseType:
        """
        Decide whether to respond with ACK or NAK based on frame type and account.

        In NAK-first mode this consumes one NAK from the budget when it returns
        the NAK for an otherwise acceptable frame.

        Args:
            parsed_frame: Parsed frame dict with keys: type, seq, raw_nak, account
                (plus encrypted and timestamp for encrypted frames)
            preset: CSR preset configuration

        Returns:
            'ACK', 'NAK' or 'DISCARD' (send nothing)

        Logic:
            - undecryptable → DISCARD (§ 5.6.2.4)
            - unknown/malformed → NAK
            - ACK (echo) → ACK (no account check needed)
            - ALARM or NULL with mismatched account → NAK (account validation)
            - encrypted ALARM or NULL outside the timestamp window → NAK
            - NAK-first budget left → NAK
            - ALARM or NULL with matching account → ACK
        """
        frame_type = parsed_frame.get('type', 'unknown')

        if frame_type == UNDECRYPTABLE:
            return 'DISCARD'
        if frame_type == 'ACK':
            return 'ACK'
        if frame_type in ('ALARM', 'NULL'):
            inbound_account = parsed_frame.get('account')
            expected_account = preset.get('account_number', '')
            if inbound_account is not None and inbound_account.upper() != expected_account.upper():
                self._logger.debug(
                    f"Account mismatch: got {inbound_account!r}, expected {expected_account!r} → NAK"
                )
                return 'NAK'
            if (self._timestamp_window_s is not None and parsed_frame.get('encrypted')
                    and not self._timestamp_in_window(parsed_frame.get('timestamp'))):
                self._logger.debug("Timestamp missing or outside the receiver window → NAK")
                return 'NAK'
            if self._naks_remaining > 0:
                self._naks_remaining -= 1
                self._logger.debug(f"NAK-first mode → NAK ({self._naks_remaining} left)")
                return 'NAK'
            return 'ACK'
        return 'NAK'  # unknown, malformed

    def _receiver_now(self) -> datetime:
        """Current receiver time: UTC now plus the configured clock skew."""
        return datetime.now(timezone.utc) + timedelta(seconds=self._clock_skew_s)

    def _timestamp_in_window(self, timestamp: datetime | None) -> bool:
        """
        Check a message timestamp against the receiver window (§ 5.5.1.9).

        Args:
            timestamp: Message timestamp (UTC), or None when absent

        Returns:
            True when present and at most ahead_s ahead / behind_s behind the receiver clock
        """
        if timestamp is None or self._timestamp_window_s is None:
            return False
        ahead_s, behind_s = self._timestamp_window_s
        delta_s = (timestamp - self._receiver_now()).total_seconds()
        return -behind_s <= delta_s <= ahead_s

    def _detect_encryption_from_frame(self, raw_frame: bytes) -> bool:
        """
        Detect if frame contains encrypted message.

        Args:
            raw_frame: Raw frame bytes

        Returns:
            True if frame is encrypted (has * marker), False otherwise
        """
        try:
            # Parse frame to extract message_string
            # Frame format: LF + CRC + Length + Message + CR
            # Message format: "ID_TOKEN"SSSS...

            # Find the opening quote after CRC/Length
            start_idx = raw_frame.find(b'"')
            if start_idx < 0:
                return False

            # Check if id_token starts with * (encryption marker)
            if start_idx + 1 < len(raw_frame) and raw_frame[start_idx + 1:start_idx + 2] == b'*':
                return True

            return False
        except Exception:
            return False

    def _parse_received_message(self, raw_frame: bytes, preset: CSRSimulatorPreset) -> dict[str, object]:
        """
        Parse received frame and extract message info.

        Handles both SIA-DCS alarm/supervision frames (PE → CSR) and ACK/NAK
        response frames (CSR → PE). decode_ack_nak only handles ACK/NAK; SIA-DCS
        frames are parsed by extracting the id_token directly from the message string.

        Args:
            raw_frame: Raw frame bytes
            preset: CSR preset with crc_format

        Returns:
            Dict with keys: type ('ACK', 'NAK', 'ALARM', 'NULL', 'unknown'),
                           seq (int | None), raw_nak (bytes | None),
                           account (str | None)
        """
        try:
            # Try decode_ack_nak first (handles ACK/NAK frames)
            result = decode_ack_nak(raw_frame, crc_format=preset['crc_format'])
            if result['type'] != 'unknown':
                result['account'] = None
                return result

            if self._detect_encryption_from_frame(raw_frame):
                return self._parse_encrypted_message(raw_frame, preset)

            # Fallback: parse SIA-DCS frame type from id_token
            components = _extract_frame_components(raw_frame)
            if components is None:
                return {'type': 'unknown', 'seq': None, 'raw_nak': None, 'account': None}

            _crc_bytes, message_str, _length_bytes, _trailing = components
            if not message_str.startswith('"'):
                return {'type': 'unknown', 'seq': None, 'raw_nak': None, 'account': None}

            end_quote = message_str.find('"', 1)
            if end_quote < 0:
                return {'type': 'unknown', 'seq': None, 'raw_nak': None, 'account': None}

            id_token = message_str[1:end_quote]
            # Strip encryption marker if present
            if id_token.startswith(ENCRYPTED_MARKER):
                id_token = id_token[1:]

            # Extract sequence number (4 digits after id_token closing quote)
            seq_str = message_str[end_quote + 1: end_quote + 5]
            seq: int | None = int(seq_str) if seq_str.isdigit() else None

            if id_token == SIA_DCS_TOKEN:
                # Determine if NULL (supervision) or ALARM by event code in data block
                # NULL code is '0000'; alarm codes are non-zero
                frame_type = 'NULL'
                account: str | None = None
                bracket_start = message_str.find('[')
                if bracket_start >= 0:
                    data_block = message_str[bracket_start:]
                    if SIA_NULL_CODE not in data_block:
                        frame_type = 'ALARM'
                    # Extract account from [#ACCOUNT|...] pattern
                    acc_start = data_block.find('[#')
                    acc_end = data_block.find('|', acc_start)
                    if acc_start >= 0 and acc_end > acc_start:
                        account = data_block[acc_start + 2:acc_end]
                return {'type': frame_type, 'seq': seq, 'raw_nak': None, 'account': account}

            if id_token == NULL_TOKEN:
                # § 5.5.2.1 Null Message: "NULL"0000[R…][L…]#acct[]
                hash_pos = message_str.find('#', end_quote)
                bracket_pos = message_str.find('[', hash_pos)
                null_account = message_str[hash_pos + 1:bracket_pos] if 0 <= hash_pos < bracket_pos else None
                return {'type': 'NULL', 'seq': seq, 'raw_nak': None, 'account': null_account}

            return {'type': 'unknown', 'seq': seq, 'raw_nak': None, 'account': None}

        except Exception as e:
            self._logger.debug(f"Frame parsing error: {e}")
            return {'type': 'unknown', 'seq': None, 'raw_nak': None, 'account': None}

    def _parse_encrypted_message(self, raw_frame: bytes, preset: CSRSimulatorPreset) -> dict[str, object]:
        """
        Decrypt and classify an encrypted *SIA-DCS or *NULL frame (§ 5.4).

        Classification and the account come from the plaintext; the clear
        header supplies the prefixes and the account echoed in the *ACK.

        Args:
            raw_frame: Raw frame bytes carrying the '*' marker
            preset: CSR preset with the encryption key

        Returns:
            Dict with type ('ALARM', 'NULL', 'unknown' or UNDECRYPTABLE), seq,
            raw_nak, account, encrypted, timestamp, header_account,
            receiver_prefix and account_prefix
        """
        undecryptable: dict[str, object] = {
            'type': UNDECRYPTABLE, 'seq': None, 'raw_nak': None, 'account': None, 'encrypted': True}
        key = preset.get('encryption_key')
        if key is None:
            return undecryptable
        try:
            message = decode(raw_frame.hex(), key)
        except SIAProtocolError as e:
            self._logger.debug(f"Encrypted frame parsing error: {e}")
            return {'type': 'unknown', 'seq': None, 'raw_nak': None, 'account': None}
        content = message.data_decrypted
        if content is None:
            return {**undecryptable, 'seq': message.sequence}

        account: str | None = message.account
        if message.id_token == NULL_TOKEN:
            frame_type = 'NULL'
        elif message.id_token == SIA_DCS_TOKEN:
            # Region content: '#acct|code…]…_ts' (or '#acct|0000]_ts' for SIA-DCS supervision)
            data_block = content[:content.find(']')]
            account_part, _, code_part = data_block.partition('|')
            if account_part.startswith('#'):
                account = account_part[1:]
            frame_type = 'NULL' if code_part.startswith(SIA_NULL_CODE) else 'ALARM'
        else:
            frame_type = 'unknown'

        timestamp: datetime | None = None
        if message.timestamp_str:
            try:
                timestamp = datetime.strptime(message.timestamp_str, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
            except ValueError:
                timestamp = None
        return {
            'type': frame_type,
            'seq': message.sequence,
            'raw_nak': None,
            'account': account,
            'encrypted': True,
            'timestamp': timestamp,
            'header_account': message.account,
            'receiver_prefix': message.receiver_prefix,
            'account_prefix': message.account_prefix,
        }

    def _generate_ack_frame(
        self,
        received_seq: int,
        preset: CSRSimulatorPreset,
        encrypted_inbound: bool,
        *,
        account: str | None = None,
        receiver_prefix: str = "R0",
        account_prefix: str = "L0",
        timestamp: datetime | None = None,
    ) -> bytes:
        """
        Generate ACK response frame.

        Plain ACK: "ACK"<seq><rpref><lpref>#<acct>[]. When the inbound frame
        was encrypted and a key is configured, the § 5.5.3.1 encrypted ACK:
        "*ACK"<seq><rpref><lpref>#<acct>[<hex of pad|]_HH:MM:SS,MM-DD-YYYY>,
        with no ']' after the hex (story 1-5 D1).

        Args:
            received_seq: Sequence number from inbound frame
            preset: CSR preset (crc_format, account_number, encryption_key)
            encrypted_inbound: True if inbound was encrypted
            account: Account to echo (default: the preset account)
            receiver_prefix: Receiver prefix to echo, e.g. "R0" or ""
            account_prefix: Account prefix to echo, e.g. "L0" or ""
            timestamp: Encrypted-ACK timestamp (default: receiver clock now)

        Returns:
            Complete ACK frame (bytes), or b'' on error
        """
        try:
            seq_str = f"{received_seq:04d}"
            header = f'{seq_str}{receiver_prefix}{account_prefix}#{account or preset.get("account_number", "000001")}'
            key = preset.get('encryption_key')
            if encrypted_inbound and key:
                ack_time = timestamp or self._receiver_now()
                region = "]" + ack_time.strftime(TIMESTAMP_DELIMITER + TIMESTAMP_FORMAT)
                hex_text = SIACipher(key).encrypt(region.encode('ascii'))
                message_string = f'"{ENCRYPTED_MARKER}ACK"{header}[{hex_text}{ENCRYPTED_REGION_TERMINATOR}'
            else:
                message_string = f'"ACK"{header}[]'
            return self._wrap_frame(message_string, preset)
        except Exception as e:
            self._logger.error(f"ACK generation error: {e}")
            return b''

    def _generate_nak_frame(self, preset: CSRSimulatorPreset) -> bytes:
        """
        Generate NAK response frame (§ 5.5.3.2, never encrypted).

        Format: "NAK"0000R0L0#0[]_HH:MM:SS,MM-DD-YYYY, the timestamp being the
        receiver clock; omitted when nak_with_timestamp is False.

        Args:
            preset: CSR preset (crc_format, account_number)

        Returns:
            Complete NAK frame (bytes), or b'' on error
        """
        try:
            message_string = NAK_MESSAGE
            if self._nak_with_timestamp:
                message_string += self._receiver_now().strftime(TIMESTAMP_DELIMITER + TIMESTAMP_FORMAT)
            return self._wrap_frame(message_string, preset)
        except Exception as e:
            self._logger.error(f"NAK generation error: {e}")
            return b''

    @staticmethod
    def _wrap_frame(message_string: str, preset: CSRSimulatorPreset) -> bytes:
        """
        Wrap a message as LF + CRC + length + message + CR (§ 5.5.1).

        Args:
            message_string: Wire message
            preset: CSR preset (crc_format)

        Returns:
            Complete frame bytes
        """
        message_bytes = message_string.encode('windows-1252')
        crc_int = _compute_crc_modbus(message_bytes)
        if preset['crc_format'] == 'hex':
            crc_bytes = f"{crc_int:04X}".encode('ascii')
        else:  # bin
            crc_bytes = crc_int.to_bytes(2, byteorder='little')
        length_bytes = f"{len(message_bytes):04X}".encode('ascii')
        return b'\x0A' + crc_bytes + length_bytes + message_bytes + b'\x0D'

    async def _send_response_udp(
        self,
        sock: socket.socket,
        response: bytes,
        dest_addr: tuple[str, int],
        delay_ms: float
    ) -> None:
        """
        Send UDP response frame with latency simulation.

        Args:
            sock: UDP socket
            response: Response frame bytes
            dest_addr: Destination (ip, port) tuple
            delay_ms: Simulated latency in milliseconds
        """
        try:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: sock.sendto(response, dest_addr)
            )
            self._logger.debug(f"UDP response sent to {dest_addr[0]}:{dest_addr[1]}")
        except Exception as e:
            self._logger.error(f"UDP send error: {e}")

    async def _send_response_tcp(
        self,
        writer: asyncio.StreamWriter,
        response: bytes,
        delay_ms: float
    ) -> None:
        """
        Send TCP response frame with latency simulation.

        Args:
            writer: asyncio StreamWriter
            response: Response frame bytes
            delay_ms: Simulated latency in milliseconds
        """
        try:
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

            writer.write(response)
            await writer.drain()
            self._logger.debug("TCP response sent")
        except Exception as e:
            self._logger.error(f"TCP send error: {e}")

    def _log_frame_exchange(
        self,
        direction: str,
        frame_type: str,
        seq: int,
        encrypted: bool,
        timestamp: datetime
    ) -> None:
        """
        Log frame exchange with audit trail info.

        Args:
            direction: 'RX' or 'TX'
            frame_type: 'ACK', 'NAK', 'ALARM', 'NULL', 'UNKNOWN'
            seq: Sequence number
            encrypted: True if encrypted
            timestamp: Datetime of exchange
        """
        encryption_str = "(encrypted)" if encrypted else "(plaintext)"
        iso_time = timestamp.isoformat()
        self._logger.info(f"[{direction}] {frame_type} seq={seq:04d} {encryption_str} {iso_time}")
