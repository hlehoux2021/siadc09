"""SIA DC-09 transport layer.

Separates socket I/O and SIA frame boundary handling from daemon state
machine logic. Used exclusively by SIADaemon._send_raw().

Reference:
    internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.3, § 5.5.1.10
"""

import asyncio
import errno
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Literal, TypedDict

from . import sia_protocol
from .sia_protocol import CR, CrcFormat, SIATransportError

# ===== Module-Level Constants =====

ON_STOP_TASK_TIMEOUT_S: float = 5.0  # Hard timeout for task cancellation in on_stop()

_logger = logging.getLogger(__name__)


# ===== Enums =====

class TransportType(Enum):
    """Strong-typed transport selector.

    CSRPreset.transport is typed TransportType. String values from JSON config
    ("UDP", "TCP") are converted via TransportType(value) in
    CSRPreset.__post_init__() — the single conversion boundary.
    """
    UDP = "UDP"
    TCP = "TCP"


# ===== TypedDicts =====

class SIATransportResult(TypedDict):
    """Result from a transport send_frame() call.

    status: 'ack' (CSR acknowledged), 'nak' (CSR rejected), 'timeout' (no valid
            response / unparseable), 'tcp_drop' (TCP connection lost mid-frame)
    raw_nak: Full raw NAK frame bytes when status='nak'; None otherwise.
    raw_response: Full raw response bytes for any status with a response (ACK or NAK);
                  None on timeout/tcp_drop. Used by message_trace callbacks for hex display.
    """
    status: Literal['ack', 'nak', 'timeout', 'tcp_drop']
    raw_nak: bytes | None
    raw_response: bytes | None


# ===== Abstract Base Transport =====

class SIABaseTransport(ABC):
    """Abstract base for SIA DC-09 transport implementations.

    Provides shared response parsing via _parse_response() and a no-op
    start() that UDP overrides. Subclasses must implement send_frame()
    and close().
    """

    def __init__(self, crc_format: CrcFormat) -> None:
        """Initialize base transport.

        Args:
            crc_format: CRC algorithm ('hex' or 'bin') from CSR preset.

        Instance Variables:
            _crc_format: CRC format passed to decode_ack_nak() for response
                         validation. Set once here; never modified after init.
        """
        self._crc_format: CrcFormat = crc_format

    async def start(self) -> None:
        """Start the transport.

        No-op for TCP (per-frame connect needs no setup). SIAUDPTransport
        overrides this to create the persistent DatagramTransport.
        on_start() always calls await t.start() unconditionally.
        """

    @abstractmethod
    async def send_frame(self, frame: bytes) -> SIATransportResult:
        """Send one SIA frame and return the parsed CSR response.

        Args:
            frame: Complete SIA DC-09 frame bytes (LF + CRC + Length + msg + CR).

        Returns:
            SIATransportResult with status and optional raw_nak.

        Raises:
            SIATransportError: On network/socket failure.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release transport resources."""

    def _parse_response(self, raw: bytes) -> SIATransportResult:
        """Parse raw CSR response bytes into SIATransportResult.

        Calls sia_protocol.decode_ack_nak() with the preset's crc_format
        and maps the result to the transport-level status vocabulary.

        Args:
            raw: Complete raw response bytes from CSR.

        Returns:
            SIATransportResult: 'ack', 'nak', or 'timeout' (for unparseable).
        """
        result = sia_protocol.decode_ack_nak(raw, crc_format=self._crc_format)
        if result['type'] == 'ACK':
            return SIATransportResult(status='ack', raw_nak=None, raw_response=raw)
        elif result['type'] == 'NAK':
            return SIATransportResult(status='nak', raw_nak=result['raw_nak'], raw_response=raw)
        else:
            return SIATransportResult(status='timeout', raw_nak=None, raw_response=raw)


# ===== UDP Protocol =====

class _SIADatagramProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol for SIA DC-09 UDP communication.

    Bridges asyncio's callback-based DatagramProtocol to the Future-based
    send/receive model used by SIAUDPTransport.send_frame().
    """

    def __init__(self) -> None:
        """Initialize protocol.

        Instance Variables:
            _future: Pending Future awaiting the next CSR reply datagram.
                     Set by SIAUDPTransport.send_frame(), resolved by
                     datagram_received(). None when no send is in flight.
        """
        self._future: asyncio.Future[bytes] | None = None

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming datagram from CSR.

        Sets the pending Future's result if one exists. Stray datagrams
        arriving with no pending future are logged and discarded.
        """
        if self._future is not None and not self._future.done():
            self._future.set_result(data)
        else:
            _logger.debug("Unexpected datagram received — no pending future")

    def error_received(self, exc: Exception) -> None:
        """Handle transport-level error.

        Propagates the exception to the pending Future if one exists.
        """
        if self._future is not None and not self._future.done():
            self._future.set_exception(exc)
        else:
            _logger.warning("UDP error received (no pending future): %r", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection loss (UDP socket closed)."""
        _logger.debug("UDP connection lost: %r", exc)
        if self._future is not None and not self._future.done():
            self._future.set_exception(
                SIATransportError("UDP connection lost")
            )


# ===== UDP Transport =====

class SIAUDPTransport(SIABaseTransport):
    """Persistent UDP transport for SIA DC-09 communication.

    Creates one asyncio.DatagramTransport + _SIADatagramProtocol at start(),
    reused for all sends. Never creates a per-send socket.
    """

    def __init__(
        self,
        host: str,
        port: int,
        receive_timeout_s: float,
        crc_format: CrcFormat,
    ) -> None:
        """Initialize UDP transport.

        Args:
            host: CSR hostname or IP address.
            port: CSR UDP port number.
            receive_timeout_s: Timeout for awaiting CSR reply.
            crc_format: CRC algorithm ('hex' or 'bin') from CSR preset.

        Instance Variables:
            _host: CSR hostname or IP.
            _port: CSR port.
            _receive_timeout_s: Reply timeout in seconds.
            _transport: asyncio DatagramTransport; None before start().
            _protocol: _SIADatagramProtocol instance; None before start().
            _logger: Module logger.
        """
        super().__init__(crc_format)
        self._host: str = host
        self._port: int = port
        self._receive_timeout_s: float = receive_timeout_s
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _SIADatagramProtocol | None = None
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Create the persistent UDP DatagramTransport.

        Closes any existing transport first (idempotent restart).
        """
        if self._transport:
            self._transport.close()

        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _SIADatagramProtocol(),
            remote_addr=(self._host, self._port),
        )
        self._transport, self._protocol = transport, protocol

        self._logger.info("Transport UDP initialisé: %s:%d", self._host, self._port)
        self._logger.debug("UDP DatagramTransport created")

    async def send_frame(self, frame: bytes) -> SIATransportResult:
        """Send one SIA frame via UDP and return the parsed CSR response.

        Args:
            frame: Complete SIA DC-09 frame bytes.

        Returns:
            SIATransportResult with status and optional raw_nak.

        Raises:
            SIATransportError: If transport not started or network failure.
        """
        if self._transport is None or self._protocol is None:
            raise SIATransportError("UDP transport not started")

        try:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[bytes] = loop.create_future()
            self._protocol._future = future

            self._transport.sendto(frame)
            self._logger.debug("UDP frame sent: %d bytes", len(frame))

            try:
                raw = await asyncio.wait_for(
                    future, timeout=self._receive_timeout_s
                )
            except asyncio.TimeoutError:
                self._protocol._future = None
                raise SIATransportError("UDP response timeout")
            finally:
                self._protocol._future = None  # always clear — prevents stale future

            self._logger.debug("UDP reply received: %d bytes", len(raw))
            return self._parse_response(raw)

        except SIATransportError:
            raise  # re-raise before OSError catches it — SIATransportError
                   # inherits from OSError (daemon-design.md § Exception hierarchy)
        except OSError as e:
            raise SIATransportError(f"UDP socket error: {e!r}") from e

    async def close(self) -> None:
        """Close the persistent UDP transport and clear protocol reference."""
        if self._transport:
            self._transport.close()
            self._transport = None
        self._protocol = None  # clear always — prevents stale protocol receiving late datagrams
        self._logger.debug("UDP transport closed")


# ===== TCP Transport =====

class SIATCPTransport(SIABaseTransport):
    """Per-frame TCP transport for SIA DC-09 communication.

    A new connection is opened, used, and closed for each send_frame() call.
    Not reentrant — StreamReader/StreamWriter are owned exclusively within
    send_frame().

    Reference:
        internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.3
        "The PE may optionally close the socket connection."
    """

    def __init__(
        self,
        host: str,
        port: int,
        connect_timeout_s: float,
        receive_timeout_s: float,
        crc_format: CrcFormat,
    ) -> None:
        """Initialize TCP transport.

        Args:
            host: CSR hostname or IP address.
            port: CSR TCP port number.
            connect_timeout_s: Timeout for TCP connect.
            receive_timeout_s: Timeout for CSR response and drain.
            crc_format: CRC algorithm ('hex' or 'bin') from CSR preset.

        Instance Variables:
            _host: CSR hostname or IP.
            _port: CSR port.
            _connect_timeout_s: Connect timeout in seconds.
            _receive_timeout_s: Reply timeout in seconds.
            _logger: Module logger.
        """
        super().__init__(crc_format)
        self._host: str = host
        self._port: int = port
        self._connect_timeout_s: float = connect_timeout_s
        self._receive_timeout_s: float = receive_timeout_s
        self._logger = logging.getLogger(__name__)

    async def send_frame(self, frame: bytes) -> SIATransportResult:
        """Send one SIA frame via TCP and return the parsed CSR response.

        Opens a fresh TCP connection, sends, reads the response, and closes.
        TCP frame boundary uses readuntil(0x0D) — the SIA CR terminator
        (§ 5.5.1.10). Never uses reader.read(N) which can return partial
        frames on congested networks.

        Args:
            frame: Complete SIA DC-09 frame bytes.

        Returns:
            SIATransportResult with status and optional raw_nak.

        Raises:
            SIATransportError: On connect/send/receive failure.
        """
        writer: asyncio.StreamWriter | None = None
        try:
            # Connect with timeout guard
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._connect_timeout_s,
                )
            except asyncio.TimeoutError:
                raise SIATransportError(
                    f"TCP connect timeout ({self._connect_timeout_s}s)"
                )
            assert writer is not None  # guaranteed: open_connection succeeded or raised
            self._logger.debug("TCP connected to %s:%d", self._host, self._port)

            # Send frame with drain timeout guard
            writer.write(frame)
            try:
                await asyncio.wait_for(
                    writer.drain(), timeout=self._receive_timeout_s
                )
            except asyncio.TimeoutError:
                raise SIATransportError("TCP send buffer drain timeout")
            self._logger.debug("TCP frame sent: %d bytes", len(frame))

            # Read response with frame boundary guard (SIA CR terminator § 5.5.1.10)
            try:
                raw = await asyncio.wait_for(
                    reader.readuntil(CR),  # SIA DC-09 § 5.5.1.10 frame terminator
                    timeout=self._receive_timeout_s,
                )
            except asyncio.IncompleteReadError:
                raise SIATransportError(
                    "TCP connection closed before SIA frame complete"
                )
            except asyncio.LimitOverrunError:
                raise SIATransportError(
                    "TCP response exceeds StreamReader buffer limit — "
                    "no frame terminator found"
                )
            except asyncio.TimeoutError:
                raise SIATransportError("TCP response timeout")

            # readuntil() never returns b"" — it either returns bytes including
            # \x0D or raises IncompleteReadError / LimitOverrunError / TimeoutError

            self._logger.debug("TCP reply received: %d bytes", len(raw))
            return self._parse_response(raw)

        except SIATransportError:
            raise  # re-raise specific errors from inner try blocks before
                   # OSError catches them — SIATransportError inherits from OSError
        except OSError as e:
            if e.errno in (
                errno.ECONNRESET, errno.EPIPE, errno.ENOTCONN, errno.EBADF
            ):
                self._logger.warning("TCP connection lost: %r", e)
                return SIATransportResult(status='tcp_drop', raw_nak=None, raw_response=None)
            raise SIATransportError(f"TCP socket error: {e!r}") from e
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except OSError:
                    pass  # connection already reset — cleanup best-effort only

    async def close(self) -> None:
        """Close TCP transport (no-op — per-frame connect holds no persistent resource)."""
        self._logger.debug("TCP transport closed (no persistent resource)")
