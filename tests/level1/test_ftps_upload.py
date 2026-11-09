"""FTPS upload module (epic 18, ticket 18.2) against a mocked ftplib.

Covers the explicit-TLS call sequence, fingerprint pinning, and the guarantee that the
password never appears in the raised error or in the settings repr.
"""

import ftplib
import hashlib
import http.client
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import frigate_prefetch, ftps_upload
from resources.siadc09d.ftps_upload import (
    FtpsSettings,
    FtpsUploadError,
    normalize_fingerprint,
    upload_bytes,
)

_SECRET = "s3cr3t-pw"
_RESET_ERRORS = [ConnectionResetError("reset"), http.client.IncompleteRead(b"x")]
_CERT_DER = b"fake-der-certificate"
_CERT_SHA = hashlib.sha256(_CERT_DER).hexdigest()


def _settings(**overrides: object) -> FtpsSettings:
    """FTPS settings, complete and enabled unless overridden."""
    values: dict[str, object] = {
        "enabled": True, "host": "ftp.example", "port": 2121, "user": "siaftps",
        "password": _SECRET, "folder": "upload",
    }
    values.update(overrides)
    return FtpsSettings(**values)  # type: ignore[arg-type]


def _fake_ftp() -> MagicMock:
    """FTP_TLS double presenting the known certificate."""
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = _CERT_DER
    return ftp


def test_upload_sequence_is_explicit_tls_then_store() -> None:
    """
    Normal upload.

    Expected result:
    - connect, AUTH TLS, login, PROT P, cwd, STOR, close - in that order
    """
    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "a.jpg", b"jpeg")

    names = [c[0] for c in ftp.method_calls if c[0] in
             {"connect", "auth", "login", "prot_p", "cwd", "storbinary", "close"}]
    # Assert: explicit TLS sequence
    assert names == ["connect", "auth", "login", "prot_p", "cwd", "storbinary", "close"]
    # Assert: configured endpoint, credentials and remote name
    ftp.connect.assert_called_once_with("ftp.example", 2121)
    ftp.login.assert_called_once_with("siaftps", _SECRET)
    assert ftp.storbinary.call_args[0][0] == "STOR a.jpg"


def test_no_folder_skips_cwd() -> None:
    """
    Empty folder setting.

    Expected result:
    - no CWD command is sent
    """
    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(folder=""), "a.jpg", b"x")
    # Assert: stays in the login directory
    ftp.cwd.assert_not_called()


def test_pinned_fingerprint_match_and_mismatch() -> None:
    """
    Pinned SHA-256 fingerprint.

    Expected result:
    - matching certificate: upload proceeds
    - other certificate: error, no login (credentials never sent), connection closed
    """
    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(cert_fingerprint=_CERT_SHA), "a.jpg", b"x")
    # Assert: matching pin uploads
    ftp.storbinary.assert_called_once()

    bad = _fake_ftp()
    bad.sock.getpeercert.return_value = b"other"
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=bad):
        with pytest.raises(FtpsUploadError, match="fingerprint"):
            upload_bytes(_settings(cert_fingerprint=_CERT_SHA), "a.jpg", b"x")
    # Assert: mismatch stops before the password is sent
    bad.login.assert_not_called()
    bad.close.assert_called_once()


def test_failure_message_never_contains_password() -> None:
    """
    Server reply that echoes the password.

    Expected result:
    - FtpsUploadError names the exception type but not the secret; connection closed
    """
    ftp = _fake_ftp()
    ftp.login.side_effect = ftplib.error_perm(f"530 bad login for {_SECRET}")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        with pytest.raises(FtpsUploadError) as excinfo:
            upload_bytes(_settings(), "a.jpg", b"x")
    # Assert: secret scrubbed
    assert _SECRET not in str(excinfo.value)
    # Assert: reason kept
    assert "error_perm" in str(excinfo.value)
    # Assert: no leaked connection
    ftp.close.assert_called_once()


def test_connection_refused_is_wrapped() -> None:
    """
    Server down.

    Expected result:
    - FtpsUploadError naming ConnectionRefusedError
    """
    ftp = _fake_ftp()
    ftp.connect.side_effect = ConnectionRefusedError("refused")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        # Assert: wrapped error with the reason
        with pytest.raises(FtpsUploadError, match="ConnectionRefusedError"):
            upload_bytes(_settings(), "a.jpg", b"x")


def test_password_hidden_from_repr() -> None:
    """
    Settings repr (appears in tracebacks and debug output).

    Expected result:
    - password absent
    """
    # Assert: secret not in repr
    assert _SECRET not in repr(_settings())


def test_active_requires_enabled_host_and_user() -> None:
    """
    Incomplete keys.

    Expected result:
    - active only when enabled with host and user
    """
    # Assert: complete settings are active
    assert _settings().active
    # Assert: each missing piece deactivates
    assert not _settings(enabled=False).active
    assert not _settings(host="").active
    assert not _settings(user="").active


def test_normalize_fingerprint() -> None:
    """
    Fingerprint formats.

    Expected result:
    - colon-separated uppercase normalized; empty stays empty; garbage rejected
    """
    colon = ":".join(_CERT_SHA[i:i + 2].upper() for i in range(0, 64, 2))
    # Assert: normalized to lowercase hex
    assert normalize_fingerprint(colon) == _CERT_SHA
    # Assert: empty means no pin
    assert normalize_fingerprint("") == ""
    # Assert: malformed rejected
    with pytest.raises(ValueError):
        normalize_fingerprint("abc")


def test_safe_name_part() -> None:
    """
    Remote name built from an external id.

    Expected result:
    - path separators and spaces replaced
    """
    # Assert: unsafe characters replaced
    assert ftps_upload.safe_name_part("../1700.5-ab c") == ".._1700.5-ab_c"


@pytest.mark.parametrize("error", _RESET_ERRORS)
def test_snapshot_download_never_raises_on_a_broken_body(error: Exception) -> None:
    """
    A connection reset or truncated body while reading the snapshot must not escape.

    Expected result:
    - the download returns None, so the upload is skipped instead of crashing its task
    """
    response = MagicMock()
    response.__enter__.return_value.read.side_effect = error
    with patch("resources.siadc09d.frigate_prefetch.urllib.request.urlopen", return_value=response):
        # Assert: no exception, no data
        assert frigate_prefetch._get_bytes("http://frigate:5000/x", 1.0) is None
