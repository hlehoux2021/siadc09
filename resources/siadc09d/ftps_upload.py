"""Explicit-TLS FTPS upload of alarm media (epic 18, ticket 18.2).

The one module that talks FTPS. `upload_bytes()` is blocking: callers run it through
`asyncio.to_thread()` under `asyncio.wait_for()`. The password is never logged and never
appears in the exceptions raised here.

Certificate policy: the chain and host name are verified by default; when a SHA-256
fingerprint is configured, only a certificate with that fingerprint is accepted (self-signed
server).

Reference: internal-docs/ftps-test-server.md, scripts/ftps_probe.py
"""

from __future__ import annotations

import ftplib
import hashlib
import io
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO, Final, Literal, TypedDict

_logger = logging.getLogger(__name__)

# Fixed per-socket timeout (connect and every transfer step). Hardening is ticket 18.6.
FTPS_TIMEOUT_S: Final[float] = 10.0
FTPS_BLOCK_SIZE: Final[int] = 64 * 1024  # deadline is checked between two blocks
MIN_SOCKET_TIMEOUT_S: Final[float] = 0.1  # never arm a zero/negative (non-blocking) timeout
FTPS_DEFAULT_PORT: Final[int] = 21
SHA256_HEX_LENGTH: Final[int] = 64
_HEX_DIGITS: Final[str] = "0123456789abcdef"
# ftplib.all_errors covers ftplib.Error, OSError (timeouts, ssl.SSLError) and EOFError.
_FTP_ERRORS: Final[tuple[type[BaseException], ...]] = (*ftplib.all_errors, ValueError)
# Remote names are built from external ids: keep only filename-safe characters.
_UNSAFE_NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")
NO_ACCOUNT: Final[str] = "noaccount"
IMAGE_NUMBER: Final[str] = "0001"  # image part of the receiver file name (no series yet)


class FtpsUploadError(Exception):
    """The upload failed; the message never contains the password."""


@dataclass(frozen=True)
class FtpsSettings:  # pylint: disable=too-many-instance-attributes
    """Per-equipment FTPS settings, passed by PHP at daemon start.

    Attributes:
        enabled: Upload switch (transport "ftps" is chosen per alarm by PHP).
        host: FTPS server name or address.
        port: Control-channel port.
        user: Login.
        password: Secret; excluded from repr and never logged.
        folder: Remote folder to change into (empty = login directory).
        cert_fingerprint: Normalized SHA-256 (64 lowercase hex) or "" for CA verification.
        plain: Plain FTP, no TLS at all (ticket 18.14); the fingerprint is then ignored.
    """

    enabled: bool = False
    host: str = ""
    port: int = FTPS_DEFAULT_PORT
    user: str = ""
    password: str = field(default="", repr=False)
    folder: str = ""
    cert_fingerprint: str = ""
    plain: bool = False

    @property
    def complete(self) -> bool:
        """True when host and user are set (the minimum to attempt an upload)."""
        return bool(self.host and self.user)

    @property
    def active(self) -> bool:
        """True when uploads are enabled and the keys are complete."""
        return self.enabled and self.complete


def normalize_fingerprint(text: str) -> str:
    """Return a SHA-256 fingerprint as 64 lowercase hex characters.

    Args:
        text: Fingerprint, with or without ':' or space separators; empty means none.

    Returns:
        The normalized fingerprint, or "" for empty input.

    Raises:
        ValueError: The text is not 64 hex characters.
    """
    cleaned = text.replace(":", "").replace(" ", "").strip().lower()
    if not cleaned:
        return ""
    if len(cleaned) != SHA256_HEX_LENGTH or any(c not in _HEX_DIGITS for c in cleaned):
        raise ValueError("fingerprint must be 64 hex characters (SHA-256)")
    return cleaned


def safe_name_part(text: str) -> str:
    """Replace every character that is not filename-safe by '_'."""
    return _UNSAFE_NAME_CHARS.sub("_", text)


def _path_part(text: str, fallback: str) -> str:
    """Return `text` as one safe path component (never empty, never made only of dots)."""
    part = safe_name_part(text)
    if not part.strip("."):
        return fallback
    return part


def remote_location(
    account: str, zone_number: int | None, when: datetime, extension: str
) -> str:
    """Return the remote file name of one alarm media (ticket 18.13).

    Flat layout at the root of the configured FTPS folder:
    `<account>_<zone, 2 digits>_<Unix epoch seconds>_0001.<extension>`. The epoch is
    timezone-independent, so a snapshot and a clip of one alarm differ only by extension.
    Two alarms of the same zone in the same second share a name (the later overwrites).

    Args:
        account: SIA account.
        zone_number: Zone number sent with the alarm (None becomes 00).
        when: Alarm time (timezone-aware, or naive local time).
        extension: File extension without the dot ("jpg" or "mp4").

    Returns:
        The file name; the account went through `_path_part()` and the extension through
        `safe_name_part()`.
    """
    zone = zone_number if zone_number is not None else 0
    return (
        f"{_path_part(account, NO_ACCOUNT)}_{zone:02d}_{int(when.timestamp())}_"
        f"{IMAGE_NUMBER}.{safe_name_part(extension)}"
    )


def _build_context(settings: FtpsSettings) -> ssl.SSLContext:
    """TLS context: full verification, or none when a fingerprint is pinned."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if settings.cert_fingerprint:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _peer_fingerprint(ftp: ftplib.FTP_TLS) -> str:
    """SHA-256 (64 lowercase hex) of the certificate the server presented, "" if none."""
    der = ftp.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
    return hashlib.sha256(der).hexdigest() if der else ""


def _mask(text: str, settings: FtpsSettings) -> str:
    """Hide the password in a server or library message."""
    return text.replace(settings.password, "***") if settings.password else text


def _check_fingerprint(ftp: ftplib.FTP_TLS, expected: str) -> None:
    """Compare the server certificate SHA-256 with the pinned one.

    Raises:
        FtpsUploadError: The certificate is missing or does not match.
    """
    seen = _peer_fingerprint(ftp)
    _logger.debug(f"FTPS server certificate sha256={seen or 'none'} (expected {expected})")
    if not seen or seen != expected:
        # A certificate fingerprint is public: showing it lets the user fix the setting.
        raise FtpsUploadError(
            "server certificate does not match the configured fingerprint "
            f"(server presents {seen or 'none'})"
        )


@dataclass(frozen=True)
class _Transfer:
    """What one upload sends and where (shared by the bytes and file uploads, ticket 18.10).

    Attributes:
        name: Remote file name (no path).
        source: Open binary stream to send.
        size: Number of bytes in `source`, for the log line.
        deadline: Absolute `time.monotonic()` abort time (None = only the per-socket timeout).
    """

    name: str
    source: BinaryIO
    size: int
    deadline: float | None = None


def upload_bytes(
    settings: FtpsSettings, name: str, data: bytes, deadline: float | None = None
) -> None:
    """Upload `data` as `name` into the configured folder (blocking).

    Args:
        settings: FTPS settings (must be complete).
        name: Remote file name (no path).
        data: File content.
        deadline: Absolute `time.monotonic()` value after which the upload aborts
            (None = no overall deadline, only the per-socket timeout).

    Raises:
        FtpsUploadError: Any connection, TLS, login or transfer failure. The message names
            the failing exception type and server reply, never the password.
    """
    _upload_stream(settings, _Transfer(name, io.BytesIO(data), len(data), deadline))


def upload_file(
    settings: FtpsSettings, name: str, path: str, deadline: float | None = None
) -> None:
    """Upload the local file at `path` as `name` (blocking, streamed, not read into memory).

    Same connection, TLS, fingerprint and error handling as `upload_bytes()`.

    Args:
        settings: FTPS settings (must be complete).
        name: Remote file name (no path).
        path: Local file to send.
        deadline: Absolute `time.monotonic()` abort time (None = none).

    Raises:
        FtpsUploadError: Any connection, TLS, login, transfer or local file failure.
    """
    try:
        with open(path, "rb") as source:
            size = os.fstat(source.fileno()).st_size
            _upload_stream(settings, _Transfer(name, source, size, deadline))
    except OSError as err:
        # FtpsUploadError is not an OSError, so only local file problems land here.
        raise FtpsUploadError(f"step read: {type(err).__name__}: {err}") from None


def _remaining(deadline: float | None) -> float:
    """Seconds left before `deadline`, capped by the per-socket timeout.

    Raises:
        FtpsUploadError: The deadline has passed.
    """
    if deadline is None:
        return FTPS_TIMEOUT_S
    left = deadline - time.monotonic()
    if left <= 0:
        raise FtpsUploadError("upload deadline exceeded")
    return min(FTPS_TIMEOUT_S, left)


def _socket_timeout(deadline: float | None) -> float:
    """Timeout to arm on a socket: the time left, capped, never below MIN_SOCKET_TIMEOUT_S."""
    return max(MIN_SOCKET_TIMEOUT_S, _remaining(deadline))


def _arm(ftp: ftplib.FTP, deadline: float | None) -> None:
    """Shrink the control and future data socket timeouts to the time left."""
    left = _socket_timeout(deadline)
    ftp.timeout = left
    if ftp.sock is not None:
        ftp.sock.settimeout(left)


def _store(
    ftp: ftplib.FTP, command: str, source: BinaryIO, deadline: float | None
) -> str:
    """Run a STOR transfer, bounding every send and the final reply by `deadline`.

    Replaces `ftplib.storbinary()`, which arms nothing between blocks: the data socket is
    re-armed before each block, the control socket before the closing reply.

    Args:
        ftp: Logged-in connection with data protection set.
        command: Full command, e.g. "STOR name".
        source: Local data to send.
        deadline: Absolute `time.monotonic()` abort time, or None.

    Returns:
        The server's final reply.

    Raises:
        FtpsUploadError: The deadline passed.
    """
    _arm(ftp, deadline)
    ftp.voidcmd("TYPE I")
    _arm(ftp, deadline)
    conn = ftp.transfercmd(command)
    try:
        while block := source.read(FTPS_BLOCK_SIZE):
            conn.settimeout(_socket_timeout(deadline))
            conn.sendall(block)
        if isinstance(conn, ssl.SSLSocket):
            conn.settimeout(_socket_timeout(deadline))
            conn.unwrap()
    finally:
        conn.close()
    _arm(ftp, deadline)
    return ftp.voidresp()


def _verify_label(settings: FtpsSettings) -> str:
    """Short description of the certificate policy, for the debug log."""
    if settings.plain:
        return "none (plain FTP, sans TLS)"
    return "fingerprint" if settings.cert_fingerprint else "CA chain"


def _upload_stream(  # pylint: disable=too-many-statements
    settings: FtpsSettings, transfer: _Transfer
) -> None:
    """Connect, authenticate and STOR the transfer's source (shared by bytes and file uploads).

    Args:
        settings: FTPS settings (must be complete).
        transfer: What to send (remote name, source, size) and the deadline.

    Raises:
        FtpsUploadError: Any connection, TLS, login or transfer failure, naming the failed step.
    """
    name, source, size = transfer.name, transfer.source, transfer.size
    deadline = transfer.deadline
    step = "connect"
    ftp: ftplib.FTP
    tls: ftplib.FTP_TLS | None = None  # None = plain FTP (18.14)
    if settings.plain:
        ftp = ftplib.FTP(timeout=FTPS_TIMEOUT_S)  # noqa: S321 - explicit user choice (18.14)
    else:
        tls = ftplib.FTP_TLS(context=_build_context(settings), timeout=FTPS_TIMEOUT_S)
        ftp = tls
    target = f"{settings.host}:{settings.port}"
    started = time.monotonic()
    try:
        if settings.plain:
            _logger.warning(f"FTP sans TLS: the link to {target} is not encrypted")
        _logger.debug(
            f"FTPS {step}: {target} user={settings.user!r} folder={settings.folder!r} "
            f"verify={_verify_label(settings)} timeout={FTPS_TIMEOUT_S}s"
        )
        ftp.timeout = _remaining(deadline)
        ftp.connect(settings.host, settings.port)
        if tls is not None:
            step = "tls"
            _arm(tls, deadline)
            tls.auth()
            _arm(tls, deadline)
            tls_version = tls.sock.version()  # type: ignore[union-attr]
            _logger.debug(f"FTPS {step}: AUTH TLS done ({tls_version})")
            if settings.cert_fingerprint:
                step = "fingerprint"
                _check_fingerprint(tls, settings.cert_fingerprint)
        step = "login"
        _arm(ftp, deadline)
        ftp.login(settings.user, settings.password)
        _logger.debug(f"FTPS {step}: logged in as {settings.user!r}")
        if tls is not None:
            step = "data-protection"
            _arm(tls, deadline)
            tls.prot_p()
        if settings.folder:
            step = "cwd"
            _arm(ftp, deadline)
            ftp.cwd(settings.folder)
        step = "upload"
        reply = _store(ftp, f"STOR {name}", source, deadline)
        _logger.debug(
            f"FTPS {step}: STOR {name} {size} bytes -> {reply!r} "
            f"in {time.monotonic() - started:.2f}s"
        )
    except FtpsUploadError as err:
        raise FtpsUploadError(f"step {step}: {err}") from None
    except _FTP_ERRORS as err:
        raise FtpsUploadError(_mask(f"step {step}: {type(err).__name__}: {err}", settings)) from None
    finally:
        ftp.close()


# ===== Connection probe (ticket 18.7): read-only, nothing is written or listed =====

PROBE_DEADLINE_S: Final[float] = 15.0  # overall deadline of one probe
PROBE_STEP_CONNECT: Final[str] = "connexion"
PROBE_STEP_TLS: Final[str] = "sécurité TLS"
PROBE_STEP_LOGIN: Final[str] = "identifiants"
PROBE_STEP_TIMEOUT: Final[str] = "délai dépassé"


class _ProbeResult(TypedDict, total=False):
    """Answer of `probe_connection()`; never contains the password."""

    status: Literal["ok", "untrusted", "changed", "error"]
    step: str
    detail: str
    fingerprint: str


def _probe_error(step: str, detail: str) -> _ProbeResult:
    """Error answer naming the failed step."""
    return {"status": "error", "step": step, "detail": detail}


def _read_presented_fingerprint(settings: FtpsSettings, deadline: float) -> str:
    """Handshake once more with no verification, only to read the certificate SHA-256.

    Nothing but the TLS hello is sent: no login. Safe because the result is only displayed
    for the user to compare.

    Args:
        settings: FTPS settings (only host and port are used).
        deadline: Absolute `time.monotonic()` abort time.

    Returns:
        The presented certificate SHA-256 (64 lowercase hex), or "" if none was presented.

    Raises:
        FtpsUploadError: The deadline passed.
        OSError: Connection or handshake failure.
        ftplib.Error: The server refused AUTH TLS.
    """
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    ftp = ftplib.FTP_TLS(context=context, timeout=FTPS_TIMEOUT_S)
    try:
        ftp.timeout = _remaining(deadline)
        ftp.connect(settings.host, settings.port)
        _arm(ftp, deadline)
        ftp.auth()
        return _peer_fingerprint(ftp)
    finally:
        ftp.close()


def _probe_failure(step: str, err: BaseException, settings: FtpsSettings) -> _ProbeResult:
    """Map an exception raised during `step` to the wizard's error answer."""
    target = f"{settings.host}:{settings.port}"
    if isinstance(err, (TimeoutError, FtpsUploadError)):
        return _probe_error(
            PROBE_STEP_TIMEOUT,
            f"{target} n'a pas répondu à temps. Vérifiez l'adresse, le port et le pare-feu.",
        )
    reason = _mask(f"{type(err).__name__}: {err}", settings)
    # Only a server reply (ftplib.Error) refuses credentials; a reset or EOF during login is a connection fault.
    if step == PROBE_STEP_LOGIN and isinstance(err, ftplib.Error):
        return _probe_error(
            PROBE_STEP_LOGIN,
            "Identifiant ou mot de passe refusé par le serveur. Corrigez-les dans les options "
            f"avancées ci-dessous, puis relancez le test. ({reason})",
        )
    if step == PROBE_STEP_TLS:
        return _probe_error(
            PROBE_STEP_TLS,
            f"Le serveur {target} n'accepte pas une connexion TLS sécurisée (TLS 1.2 minimum, "
            f"AUTH TLS requis). ({reason})",
        )
    service = "FTP" if settings.plain else "FTPS"
    return _probe_error(
        PROBE_STEP_CONNECT,
        f"Impossible de joindre {target} (connexion refusée). Vérifiez : l'adresse et le "
        f"port ; que le service {service} est démarré ; le pare-feu. ({reason})",
    )


def _probe_certificate_refusal(
    settings: FtpsSettings, status: str, deadline: float
) -> _ProbeResult:
    """Answer for a refused certificate: the fingerprint the server presents, no login."""
    try:
        seen = _read_presented_fingerprint(settings, deadline)
    except (*_FTP_ERRORS, FtpsUploadError) as err:
        return _probe_failure(PROBE_STEP_TLS, err, settings)
    if not seen:
        return _probe_error(PROBE_STEP_TLS, "Le serveur ne présente aucun certificat.")
    return {
        "status": status,
        "detail": "Le mot de passe n'a pas été envoyé.",
        "fingerprint": seen,
    }


def _probe_plain(settings: FtpsSettings, deadline: float) -> _ProbeResult:
    """Plain FTP probe (ticket 18.14): connect and log in, no TLS step, no certificate."""
    _logger.warning(
        f"FTP sans TLS: connection test to {settings.host}:{settings.port}, link not encrypted"
    )
    step = PROBE_STEP_CONNECT
    ftp = ftplib.FTP(timeout=FTPS_TIMEOUT_S)  # noqa: S321 - explicit user choice (18.14)
    try:
        ftp.timeout = _remaining(deadline)
        ftp.connect(settings.host, settings.port)
        step = PROBE_STEP_LOGIN
        _arm(ftp, deadline)
        ftp.login(settings.user, settings.password)
        return {
            "status": "ok",
            "detail": "Connexion FTP sans TLS : la liaison n'est pas chiffrée.",
        }
    except (*_FTP_ERRORS, FtpsUploadError) as err:
        return _probe_failure(step, err, settings)
    finally:
        ftp.close()


def probe_connection(settings: FtpsSettings, deadline: float) -> _ProbeResult:
    """Connect, negotiate TLS, check the certificate, log in (blocking). Writes nothing.

    No STOR, no listing, no change of folder: the folder is checked at the first alarm.
    A certificate problem stops before the password is sent.

    Args:
        settings: FTPS settings as saved (host and user required).
        deadline: Absolute `time.monotonic()` abort time for the whole probe.

    Returns:
        `{status: ok|untrusted|changed|error, step?, detail?, fingerprint?}`. Never raises
        for a network problem; no field ever contains the password.
    """
    if not settings.complete:
        return _probe_error(
            PROBE_STEP_CONNECT, "Réglages FTPS incomplets : serveur et utilisateur requis."
        )
    if settings.plain:
        return _probe_plain(settings, deadline)
    step = PROBE_STEP_CONNECT
    ftp = ftplib.FTP_TLS(context=_build_context(settings), timeout=FTPS_TIMEOUT_S)
    try:
        ftp.timeout = _remaining(deadline)
        ftp.connect(settings.host, settings.port)
        step = PROBE_STEP_TLS
        _arm(ftp, deadline)
        ftp.auth()
        if settings.cert_fingerprint:
            seen = _peer_fingerprint(ftp)
            if seen != settings.cert_fingerprint:
                return {
                    "status": "changed",
                    "detail": "Le mot de passe n'a pas été envoyé.",
                    "fingerprint": seen,
                }
        step = PROBE_STEP_LOGIN
        _arm(ftp, deadline)
        ftp.login(settings.user, settings.password)
        return {"status": "ok", "detail": ""}
    except ssl.SSLCertVerificationError:
        # CA mode only: the pinned mode accepts any chain and compares fingerprints above.
        return _probe_certificate_refusal(settings, "untrusted", deadline)
    except (*_FTP_ERRORS, FtpsUploadError) as err:
        return _probe_failure(step, err, settings)
    finally:
        ftp.close()
