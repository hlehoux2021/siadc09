"""Fake `ftplib.FTP_TLS` backed by real sockets, for stalled-server tests (ticket 18.6).

The control and data connections are `socket.socketpair()` ends whose peer is never served,
so a send or a reply wait blocks for real until the socket timeout armed by the code under
test expires. Nothing is mocked in the upload function itself.
"""

import socket
import threading
from typing import Final

SMALL_BUFFER_BYTES: Final[int] = 4096
# Larger than both socket buffers together: a send of this size cannot complete unread.
STALLING_PAYLOAD_BYTES: Final[int] = 4 * 1024 * 1024


class _ControlSock:
    """Control-channel socket: real timeouts and `recv`, canned TLS answers."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock: socket.socket = sock

    def settimeout(self, value: float | None) -> None:
        """Arm the real socket timeout."""
        self._sock.settimeout(value)

    def recv(self, size: int) -> bytes:
        """Block until data or the armed timeout (the peer never writes)."""
        return self._sock.recv(size)

    def version(self) -> str:
        """TLS version string, as `SSLSocket.version()`."""
        return "TLSv1.3"

    def getpeercert(self, binary_form: bool = False) -> bytes:  # pylint: disable=unused-argument
        """Canned certificate."""
        return b"fake-der"


class StalledFtp:
    """Logs in normally, then stalls: nobody reads the data and the 226 never comes.

    A payload above STALLING_PAYLOAD_BYTES blocks in the data send; a small one is sent and
    the call then blocks in `voidresp()` (missing 226).

    Attributes:
        closed: Set by `close()`, i.e. when the upload function has returned or raised.
    """

    def __init__(self) -> None:
        self.timeout: float | None = None
        self.sock: _ControlSock | None = None
        self.closed: threading.Event = threading.Event()
        self._control, self._control_peer = socket.socketpair()
        self._data_peer: socket.socket | None = None

    def connect(self, _host: str, _port: int) -> str:
        """Open the (fake) control connection."""
        self.sock = _ControlSock(self._control)
        return "220 hello"

    def auth(self) -> str:
        """AUTH TLS accepted."""
        return "234 ok"

    def login(self, _user: str, _password: str) -> str:
        """Login accepted."""
        return "230 ok"

    def prot_p(self) -> str:
        """PROT P accepted."""
        return "200 ok"

    def cwd(self, _folder: str) -> str:
        """CWD accepted."""
        return "250 ok"

    def voidcmd(self, _command: str) -> str:
        """TYPE I accepted."""
        return "200 ok"

    def transfercmd(self, _command: str) -> socket.socket:
        """Return the sending end of a data connection nobody reads (small buffers)."""
        sender, self._data_peer = socket.socketpair()
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SMALL_BUFFER_BYTES)
        self._data_peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SMALL_BUFFER_BYTES)
        return sender

    def voidresp(self) -> str:
        """Wait for the closing reply: with stall="reply" it never comes."""
        assert self.sock is not None
        self.sock.recv(1)
        return "226 done"

    def close(self) -> None:
        """Release every socket and flag that the upload function is over."""
        for sock in (self._control, self._control_peer, self._data_peer):
            if sock is not None:
                sock.close()
        self.closed.set()
