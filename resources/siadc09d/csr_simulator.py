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
from datetime import datetime, timezone
from typing import Optional

from resources.siadc09d.sia_protocol import SIAMessageBuilder, decode_ack_nak, _compute_crc_modbus
from resources.siadc09d.sia_crypto import SIACipher


logger = logging.getLogger(__name__)


class CSRSimulatorError(Exception):
    """Exception raised for CSR Simulator-specific errors."""
    pass


def _validate_preset(preset: dict) -> None:
    """
    Validate CSR preset configuration.

    Validates required fields and raises CSRSimulatorError if invalid.

    Args:
        preset: Configuration dict with keys:
            - crc_format: 'hex' or 'bin'
            - account_number: 3-16 hex characters
            - encryption_key: Optional[bytes] (None or 16-byte AES-128 key)

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
        preset: CSR preset configuration dict (crc_format, account_number, encryption_key)
        response_delay_ms: Simulated response latency in milliseconds
        _udp_socket: UDP socket instance (None until started)
        _tcp_server: TCP server instance (None until started)
        _running: Flag indicating if simulator is running
        _logger: Module logger instance
    """

    def __init__(
        self,
        udp_port: int,
        tcp_port: int,
        preset: dict,
        response_delay_ms: float = 0
    ) -> None:
        """
        Initialize CSR Simulator.

        Args:
            udp_port: UDP port to listen on
            tcp_port: TCP port to listen on
            preset: CSR preset configuration with required fields
            response_delay_ms: Simulated response latency (default 0)

        Raises:
            CSRSimulatorError: If preset validation fails
        """
        # Validate preset at startup (fail-fast per ADR-09)
        _validate_preset(preset)

        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.preset = preset
        self.response_delay_ms = response_delay_ms

        self._udp_socket: Optional[socket.socket] = None
        self._tcp_server: Optional[asyncio.Server] = None
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
            self._udp_socket.bind(('127.0.0.1', self.udp_port))
            self._logger.debug(f"UDP socket bound to port {self.udp_port}")

            # Start TCP server (using asyncio.start_server)
            self._tcp_server = await asyncio.start_server(
                self._handle_tcp_client,
                '127.0.0.1',
                self.tcp_port
            )
            self._logger.debug(f"TCP server listening on port {self.tcp_port}")

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
                    lambda: sock.recvfrom(1024)
                )

                self._logger.debug(f"[RX] UDP frame from {addr[0]}:{addr[1]}")

                # Parse received frame
                parsed_frame = self._parse_received_message(frame_data, self.preset)

                # Detect if frame is encrypted
                encrypted_inbound = self._detect_encryption_from_frame(frame_data)

                # Log inbound frame
                frame_type = parsed_frame.get('type', 'unknown')
                seq = parsed_frame.get('seq', 0)
                self._log_frame_exchange('RX', frame_type, seq, encrypted_inbound, datetime.now(timezone.utc))

                # Decide response type
                response_type = self._decide_response(parsed_frame, self.preset)

                # Generate response frame
                if response_type == 'ACK':
                    seq = parsed_frame.get('seq', 0)
                    response_frame = self._generate_ack_frame(seq, self.preset, encrypted_inbound)
                else:  # NAK
                    response_frame = self._generate_nak_frame(self.preset)

                # Send response
                if response_frame:
                    await self._send_response_udp(sock, response_frame, addr, self.response_delay_ms)
                    # Log outbound response
                    self._log_frame_exchange('TX', response_type, seq if response_type == 'ACK' else 0, False, datetime.now(timezone.utc))

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

                    # Parse received frame
                    parsed_frame = self._parse_received_message(frame_data, self.preset)

                    # Detect if frame is encrypted
                    encrypted_inbound = self._detect_encryption_from_frame(frame_data)

                    # Log inbound frame
                    frame_type = parsed_frame.get('type', 'unknown')
                    seq = parsed_frame.get('seq', 0)
                    self._log_frame_exchange('RX', frame_type, seq, encrypted_inbound, datetime.now(timezone.utc))

                    # Decide response type
                    response_type = self._decide_response(parsed_frame, self.preset)

                    # Generate response frame
                    if response_type == 'ACK':
                        seq = parsed_frame.get('seq', 0)
                        response_frame = self._generate_ack_frame(seq, self.preset, encrypted_inbound)
                    else:  # NAK
                        response_frame = self._generate_nak_frame(self.preset)

                    # Send response
                    if response_frame:
                        await self._send_response_tcp(writer, response_frame, self.response_delay_ms)
                        # Log outbound response
                        self._log_frame_exchange('TX', response_type, seq if response_type == 'ACK' else 0, False, datetime.now(timezone.utc))

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
            frame, addr = sock.recvfrom(1024)

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

    def _decide_response(self, parsed_frame: dict, preset: dict) -> str:
        """
        Decide whether to respond with ACK or NAK based on frame type.

        Args:
            parsed_frame: Parsed frame dict with keys: type, seq, raw_nak
            preset: CSR preset configuration

        Returns:
            'ACK' or 'NAK' string indicating response type

        Logic:
            - ALARM → ACK (echo the sequence number)
            - NULL → ACK (supervision response)
            - ACK → ACK (echo back)
            - unknown → NAK (malformed frame)
            - malformed → NAK (frame parsing failed)
        """
        frame_type = parsed_frame.get('type', 'unknown')

        if frame_type in ('ALARM', 'NULL', 'ACK'):
            return 'ACK'
        else:  # unknown, malformed, or any other type
            return 'NAK'

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

    def _parse_received_message(self, raw_frame: bytes, preset: dict) -> dict[str, object]:
        """
        Parse received frame and extract message info.

        Args:
            raw_frame: Raw frame bytes
            preset: CSR preset with crc_format

        Returns:
            Dict with keys: type ('ACK', 'NAK', 'ALARM', 'NULL', 'unknown'),
                           seq (int | None), raw_nak (bytes | None)
        """
        try:
            # Use Story 1.3 decode_ack_nak to parse frame
            result = decode_ack_nak(raw_frame, crc_format=preset['crc_format'])
            return result
        except Exception as e:
            self._logger.debug(f"Frame parsing error: {e}")
            return {'type': 'unknown', 'seq': None, 'raw_nak': None}

    def _generate_ack_frame(
        self,
        received_seq: int,
        preset: dict,
        encrypted_inbound: bool
    ) -> bytes:
        """
        Generate ACK response frame.

        Args:
            received_seq: Sequence number from inbound frame
            preset: CSR preset (crc_format, account_number, encryption_key)
            encrypted_inbound: True if inbound was encrypted

        Returns:
            Complete ACK frame (bytes)
        """
        try:
            # Message construction: "ACK"<seq>R0L0#<account>[]
            seq_str = f"{received_seq:04d}"
            id_token = "*ACK" if encrypted_inbound else "ACK"
            account = preset.get('account_number', '000001')

            message_string = f'"{id_token}"{seq_str}R0L0#{account}[]'
            message_bytes = message_string.encode('windows-1252')

            # Compute CRC using Story 1.1
            crc_int = _compute_crc_modbus(message_bytes)

            # Format based on preset
            crc_format = preset['crc_format']
            if crc_format == 'hex':
                crc_bytes = f"{crc_int:04X}".encode('ascii')
                length_bytes = f"{len(message_bytes):04X}".encode('ascii')
            else:  # bin
                crc_bytes = crc_int.to_bytes(2, byteorder='little')
                length_bytes = f"{len(message_bytes):04X}".encode('ascii')

            # Build frame: LF + CRC + Length + Message + CR
            frame = b'\x0A' + crc_bytes + length_bytes + message_bytes + b'\x0D'

            # Encrypt if needed
            if encrypted_inbound and preset.get('encryption_key'):
                cipher = SIACipher(preset['encryption_key'])
                frame = cipher.encrypt_frame(frame)

            return frame
        except Exception as e:
            self._logger.error(f"ACK generation error: {e}")
            return b''

    def _generate_nak_frame(self, preset: dict) -> bytes:
        """
        Generate NAK response frame.

        Args:
            preset: CSR preset (crc_format, account_number)

        Returns:
            Complete NAK frame (bytes)
        """
        try:
            # NAK format: "NAK"0000R0L0A0[]_HH:MM:SS,MM-DD-YYYY
            # For v1.0, we simplify without timestamp (per Task 6 note)
            message_string = '"NAK"0000R0L0A0[]'
            message_bytes = message_string.encode('windows-1252')

            # Compute CRC
            crc_int = _compute_crc_modbus(message_bytes)

            # Format based on preset
            crc_format = preset['crc_format']
            if crc_format == 'hex':
                crc_bytes = f"{crc_int:04X}".encode('ascii')
                length_bytes = f"{len(message_bytes):04X}".encode('ascii')
            else:  # bin
                crc_bytes = crc_int.to_bytes(2, byteorder='little')
                length_bytes = f"{len(message_bytes):04X}".encode('ascii')

            # Build frame
            frame = b'\x0A' + crc_bytes + length_bytes + message_bytes + b'\x0D'
            return frame
        except Exception as e:
            self._logger.error(f"NAK generation error: {e}")
            return b''

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
