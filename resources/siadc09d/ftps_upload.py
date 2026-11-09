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
import re
import ssl
from dataclasses import dataclass, field
from typing import Final

# Fixed per-socket timeout (connect and every transfer step). Hardening is ticket 18.6.
FTPS_TIMEOUT_S: Final[float] = 10.0
FTPS_DEFAULT_PORT: Final[int] = 21
SHA256_HEX_LENGTH: Final[int] = 64
_HEX_DIGITS: Final[str] = "0123456789abcdef"
# ftplib.all_errors covers ftplib.Error, OSError (timeouts, ssl.SSLError) and EOFError.
_FTP_ERRORS: Final[tuple[type[BaseException], ...]] = (*ftplib.all_errors, ValueError)
# Remote names are built from external ids: keep only filename-safe characters.
_UNSAFE_NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")


class FtpsUploadError(Exception):
    """The upload failed; the message never contains the password."""


@dataclass(frozen=True)
class FtpsSettings:
    """Per-equipment FTPS settings, passed by PHP at daemon start.

    Attributes:
        enabled: Upload switch (transport "ftps" is chosen per alarm by PHP).
        host: FTPS server name or address.
        port: Control-channel port.
        user: Login.
        password: Secret; excluded from repr and never logged.
        folder: Remote folder to change into (empty = login directory).
        cert_fingerprint: Normalized SHA-256 (64 lowercase hex) or "" for CA verification.
    """

    enabled: bool = False
    host: str = ""
    port: int = FTPS_DEFAULT_PORT
    user: str = ""
    password: str = field(default="", repr=False)
    folder: str = ""
    cert_fingerprint: str = ""

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


def _build_context(settings: FtpsSettings) -> ssl.SSLContext:
    """TLS context: full verification, or none when a fingerprint is pinned."""
    context = ssl.create_default_context()
    if settings.cert_fingerprint:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _check_fingerprint(ftp: ftplib.FTP_TLS, expected: str) -> None:
    """Compare the server certificate SHA-256 with the pinned one.

    Raises:
        FtpsUploadError: The certificate is missing or does not match.
    """
    der = ftp.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
    if not der or hashlib.sha256(der).hexdigest() != expected:
        raise FtpsUploadError("server certificate does not match the configured fingerprint")


def upload_bytes(settings: FtpsSettings, name: str, data: bytes) -> None:
    """Upload `data` as `name` into the configured folder (blocking).

    Args:
        settings: FTPS settings (must be complete).
        name: Remote file name (no path).
        data: File content.

    Raises:
        FtpsUploadError: Any connection, TLS, login or transfer failure. The message names
            the failing exception type and server reply, never the password.
    """
    ftp = ftplib.FTP_TLS(context=_build_context(settings), timeout=FTPS_TIMEOUT_S)
    try:
        ftp.connect(settings.host, settings.port)
        ftp.auth()
        if settings.cert_fingerprint:
            _check_fingerprint(ftp, settings.cert_fingerprint)
        ftp.login(settings.user, settings.password)
        ftp.prot_p()
        if settings.folder:
            ftp.cwd(settings.folder)
        ftp.storbinary(f"STOR {name}", io.BytesIO(data))
    except FtpsUploadError:
        raise
    except _FTP_ERRORS as err:
        reason = f"{type(err).__name__}: {err}"
        if settings.password:
            reason = reason.replace(settings.password, "***")
        raise FtpsUploadError(reason) from None
    finally:
        ftp.close()
