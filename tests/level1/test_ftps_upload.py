"""FTPS upload module (epic 18, ticket 18.2) against a mocked ftplib.

Covers the explicit-TLS call sequence, fingerprint pinning, and the guarantee that the
password never appears in the raised error or in the settings repr.
"""

import ftplib
import hashlib
import http.client
import ssl
import time
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import frigate_prefetch, ftps_upload
from resources.siadc09d.ftps_upload import (
    FtpsSettings,
    FtpsUploadError,
    normalize_fingerprint,
    upload_bytes,
    upload_file,
)
from tests.ftps_stall_fake import STALLING_PAYLOAD_BYTES, StalledFtp

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
             {"connect", "auth", "login", "prot_p", "cwd", "transfercmd", "close"}]
    # Assert: explicit TLS sequence
    assert names == ["connect", "auth", "login", "prot_p", "cwd", "transfercmd", "close"]
    # Assert: configured endpoint, credentials and remote name
    ftp.connect.assert_called_once_with("ftp.example", 2121)
    ftp.login.assert_called_once_with("siaftps", _SECRET)
    assert ftp.transfercmd.call_args[0][0] == "STOR a.jpg"


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
    ftp.transfercmd.assert_called_once()

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


def test_debug_trace_follows_every_step_without_the_password(caplog: pytest.LogCaptureFixture) -> None:
    """
    A successful upload leaves a debug trail of each step.

    Expected result:
    - connect, certificate, login and upload lines are logged; the password is not
    """
    caplog.set_level("DEBUG", logger=ftps_upload.__name__)
    ftp = _fake_ftp()
    ftp.voidresp.return_value = "226 Transfer complete"
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(cert_fingerprint=_CERT_SHA), "a.jpg", b"jpeg")
    # Assert: each step is traced
    for expected in ("FTPS connect", "FTPS server certificate", "FTPS login", "FTPS upload"):
        assert expected in caplog.text
    # Assert: the server reply is traced, the password never is
    assert "226 Transfer complete" in caplog.text
    assert _SECRET not in caplog.text


def test_failure_names_the_step_and_the_presented_fingerprint() -> None:
    """
    A refused connection and a wrong pinned certificate both say where they failed.

    Expected result:
    - the error starts with the failing step; a mismatch shows the fingerprint the server presents
    """
    refused = _fake_ftp()
    refused.connect.side_effect = ConnectionRefusedError(111, "Connection refused")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=refused), \
         pytest.raises(FtpsUploadError) as excinfo:
        upload_bytes(_settings(), "a.jpg", b"x")
    # Assert: the step is named
    assert str(excinfo.value).startswith("step connect:")

    wrong = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=wrong), \
         pytest.raises(FtpsUploadError) as excinfo:
        upload_bytes(_settings(cert_fingerprint="0" * 64), "a.jpg", b"x")
    # Assert: the mismatch names its step and shows the certificate the server presents
    assert str(excinfo.value).startswith("step fingerprint:")
    assert _CERT_SHA in str(excinfo.value)


class _Clock:
    """Controllable replacement for time.monotonic()."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_tls_context_refuses_below_tls_1_2() -> None:
    """
    The TLS minimum is explicit, with and without a pinned fingerprint.

    Expected result:
    - minimum_version is TLS 1.2 in CA mode and in pinned mode
    """
    # Assert: CA mode
    assert ftps_upload._build_context(_settings()).minimum_version == ssl.TLSVersion.TLSv1_2
    # Assert: pinned mode
    pinned = _settings(cert_fingerprint=_CERT_SHA)
    assert ftps_upload._build_context(pinned).minimum_version == ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize("error", [
    ssl.SSLCertVerificationError("certificate verify failed"),
    ssl.SSLError("UNSUPPORTED_PROTOCOL"),
])
def test_tls_refusal_names_the_tls_step_and_sends_nothing(error: Exception) -> None:
    """
    Wrong certificate (CA mode) or old TLS version: the handshake fails at AUTH TLS.

    Expected result:
    - FtpsUploadError names step "tls"; login and STOR were never attempted
    """
    ftp = _fake_ftp()
    ftp.auth.side_effect = error
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp), \
         pytest.raises(FtpsUploadError) as excinfo:
        upload_bytes(_settings(), "a.jpg", b"x")
    # Assert: step named
    assert str(excinfo.value).startswith("step tls:")
    # Assert: nothing sent after the refusal
    ftp.login.assert_not_called()
    ftp.transfercmd.assert_not_called()
    # Assert: password not in the message
    assert _SECRET not in str(excinfo.value)


def test_expired_deadline_aborts_before_connecting() -> None:
    """
    Deadline already passed when the thread starts.

    Expected result:
    - the connect step fails naming the deadline; no connection is attempted
    """
    ftp = _fake_ftp()
    clock = _Clock()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp), \
         patch.object(ftps_upload.time, "monotonic", clock), \
         pytest.raises(FtpsUploadError) as excinfo:
        upload_bytes(_settings(), "a.jpg", b"x", deadline=clock.now - 1)
    # Assert: deadline named at the connect step
    assert str(excinfo.value) == "step connect: upload deadline exceeded"
    # Assert: no connection attempted
    ftp.connect.assert_not_called()
    # Assert: the object is still closed
    ftp.close.assert_called_once()


def test_trickling_upload_is_aborted_between_two_blocks() -> None:
    """
    Slow server: each block is accepted, but the total exceeds the deadline.

    Expected result:
    - the read after the deadline raises; the error names step upload and the deadline
    - blocks are requested with the 64 KiB block size
    """
    ftp = _fake_ftp()
    clock = _Clock()
    seen_sizes: list[int] = []

    def trickle(block: bytes) -> None:
        seen_sizes.append(len(block))
        clock.now += 4.0  # each block "takes" 4 s on the wire

    ftp.transfercmd.return_value.sendall.side_effect = trickle
    data = b"x" * (ftps_upload.FTPS_BLOCK_SIZE * 10)
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp), \
         patch.object(ftps_upload.time, "monotonic", clock), \
         pytest.raises(FtpsUploadError) as excinfo:
        upload_bytes(_settings(), "a.mp4", data, deadline=clock.now + 10.0)
    # Assert: aborted at the deadline, step and cause named
    assert str(excinfo.value) == "step upload: upload deadline exceeded"
    # Assert: aborted after a few blocks, not after all ten
    assert 0 < len(seen_sizes) < 10
    # Assert: block size is the 64 KiB constant
    assert set(seen_sizes) == {ftps_upload.FTPS_BLOCK_SIZE}
    # Assert: the data connection is closed after the abort
    ftp.transfercmd.return_value.close.assert_called_once()


def test_socket_timeout_shrinks_with_the_time_left() -> None:
    """
    A stalled server must not hold a step longer than the time left.

    Expected result:
    - the control socket and the data timeout are set to the remaining time when it is
      below FTPS_TIMEOUT_S, and never above FTPS_TIMEOUT_S
    """
    ftp = _fake_ftp()
    clock = _Clock()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp), \
         patch.object(ftps_upload.time, "monotonic", clock):
        upload_bytes(_settings(), "a.jpg", b"x", deadline=clock.now + 3.0)
    timeouts = [c.args[0] for c in ftp.sock.settimeout.call_args_list]
    # Assert: timeouts were set and all equal the 3 s left (below the 10 s cap)
    assert timeouts and all(t == 3.0 for t in timeouts)
    # Assert: the data connection created by storbinary inherits the shrunk timeout
    assert ftp.timeout == 3.0

    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp), \
         patch.object(ftps_upload.time, "monotonic", clock):
        upload_bytes(_settings(), "a.jpg", b"x", deadline=clock.now + 300.0)
    # Assert: capped at the per-socket timeout when plenty of time is left
    assert all(c.args[0] == ftps_upload.FTPS_TIMEOUT_S for c in ftp.sock.settimeout.call_args_list)


_STALL_DEADLINE_S = 0.5
_STALL_SLACK_S = 0.5


@pytest.mark.parametrize("kind", ["bytes", "file"])
@pytest.mark.parametrize("payload_size,stalled_part", [
    (STALLING_PAYLOAD_BYTES, "data connection"),
    (16, "closing reply"),
])
def test_real_upload_against_a_stalled_server_ends_at_the_deadline(
    tmp_path, kind: str, payload_size: int, stalled_part: str
) -> None:
    """
    The REAL upload functions against sockets that never answer (unread data / no 226).

    Expected result:
    - FtpsUploadError naming step "upload", raised within deadline + slack (wall clock)
    - the connection is closed (the worker is released)
    """
    fake = StalledFtp()
    data = b"x" * payload_size
    path = tmp_path / "clip.mp4"
    path.write_bytes(data)
    started = time.monotonic()
    deadline = started + _STALL_DEADLINE_S
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=fake), \
         pytest.raises(FtpsUploadError) as excinfo:
        if kind == "bytes":
            upload_bytes(_settings(), "a.mp4", data, deadline=deadline)
        else:
            upload_file(_settings(), "a.mp4", str(path), deadline=deadline)
    elapsed = time.monotonic() - started
    # Assert: the upload step is named (stalled part: data connection or closing reply)
    assert str(excinfo.value).startswith("step upload:"), stalled_part
    # Assert: aborted at the deadline, not after the 10 s socket timeout
    assert elapsed < _STALL_DEADLINE_S + _STALL_SLACK_S
    # Assert: not before the deadline either (the stall was really waited on)
    assert elapsed >= _STALL_DEADLINE_S - 0.05
    # Assert: the password is not in the message
    assert _SECRET not in str(excinfo.value)
    # Assert: connection closed
    assert fake.closed.is_set()


def test_no_deadline_keeps_previous_behaviour() -> None:
    """
    deadline=None (existing callers).

    Expected result:
    - the upload completes and STOR is issued
    """
    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "a.jpg", b"x")
    # Assert: STOR issued
    assert ftp.transfercmd.call_args[0][0] == "STOR a.jpg"
