"""FTPS connection probe (epic 18, ticket 18.7) against a mocked ftplib.

One test per row of the I/O matrix of the plan, plus the secrecy guarantees: the password is
never in the answer, and never sent when the certificate is refused.
"""

import ftplib
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import ftps_upload
from resources.siadc09d.ftps_upload import FtpsSettings, probe_connection

_SECRET = "s3cr3t-pw"
_CERT_DER = b"fake-der-certificate"
_CERT_SHA = hashlib.sha256(_CERT_DER).hexdigest()
_SCRIPT = Path(__file__).parent.parent.parent / "resources" / "siadc09d" / "siadc09d.py"


def _settings(**overrides: object) -> FtpsSettings:
    """Complete FTPS settings unless overridden."""
    values: dict[str, object] = {
        "enabled": True, "host": "ftp.example", "port": 2121, "user": "siaftps",
        "password": _SECRET,
    }
    values.update(overrides)
    return FtpsSettings(**values)  # type: ignore[arg-type]


def _fake_ftp() -> MagicMock:
    """FTP_TLS double presenting the known certificate."""
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = _CERT_DER
    return ftp


def _probe(ftp: MagicMock | list[MagicMock], settings: FtpsSettings | None = None) -> dict[str, str]:
    """Run the probe with FTP_TLS replaced by `ftp` (or by a sequence of doubles)."""
    patcher = (
        patch.object(ftps_upload.ftplib, "FTP_TLS", side_effect=ftp)
        if isinstance(ftp, list)
        else patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp)
    )
    with patcher:
        return probe_connection(settings or _settings(), time.monotonic() + 15)


def _assert_no_write(ftp: MagicMock) -> None:
    """Nothing written, listed or changed on the server."""
    for name in ("storbinary", "transfercmd", "cwd", "nlst", "retrlines", "mkd", "prot_p"):
        assert not getattr(ftp, name).called, name  # Assert: read-only probe


def test_correct_setup_with_a_public_chain_is_ok() -> None:
    """
    Valid chain, good login.

    Expected result:
    - status ok; AUTH TLS then login; no write, no listing, no folder change
    """
    ftp = _fake_ftp()
    result = _probe(ftp)
    # Assert: success
    assert result["status"] == "ok"
    # Assert: login done with the password
    ftp.login.assert_called_once_with("siaftps", _SECRET)
    _assert_no_write(ftp)


def test_correct_setup_with_a_matching_pinned_fingerprint_is_ok() -> None:
    """
    Fingerprint matches, good login.

    Expected result:
    - status ok
    """
    ftp = _fake_ftp()
    # Assert: success
    assert _probe(ftp, _settings(cert_fingerprint=_CERT_SHA))["status"] == "ok"
    ftp.login.assert_called_once()


def test_unreachable_host_names_the_connection_step_and_the_endpoint() -> None:
    """
    Connection refused.

    Expected result:
    - error, step "connexion", detail names host:port
    """
    ftp = _fake_ftp()
    ftp.connect.side_effect = ConnectionRefusedError(111, "Connection refused")
    result = _probe(ftp)
    # Assert: status and step
    assert (result["status"], result["step"]) == ("error", "connexion")
    # Assert: endpoint named
    assert "ftp.example:2121" in result["detail"]
    ftp.login.assert_not_called()


def test_unknown_host_is_a_connection_error() -> None:
    """
    Name resolution fails (OSError).

    Expected result:
    - error, step "connexion"
    """
    ftp = _fake_ftp()
    ftp.connect.side_effect = socket.gaierror(8, "nodename nor servname provided")
    result = _probe(ftp)
    # Assert: connection step
    assert result["step"] == "connexion"


def test_timeout_is_its_own_step() -> None:
    """
    The server does not answer in time.

    Expected result:
    - error, step "délai dépassé"
    """
    ftp = _fake_ftp()
    ftp.connect.side_effect = TimeoutError("timed out")
    result = _probe(ftp)
    # Assert: timeout step
    assert (result["status"], result["step"]) == ("error", "délai dépassé")


def test_an_already_passed_deadline_is_a_timeout() -> None:
    """
    The overall deadline is exhausted before the connection.

    Expected result:
    - error, step "délai dépassé"; nothing contacted
    """
    ftp = _fake_ftp()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        result = probe_connection(_settings(), time.monotonic() - 1)
    # Assert: timeout step
    assert result["step"] == "délai dépassé"
    ftp.connect.assert_not_called()


def test_self_signed_without_fingerprint_is_untrusted_and_sends_no_password() -> None:
    """
    Chain verification fails at AUTH TLS; a second handshake reads the fingerprint.

    Expected result:
    - status untrusted with the presented fingerprint; login never called on any connection
    """
    first = _fake_ftp()
    first.auth.side_effect = ssl.SSLCertVerificationError("self-signed certificate")
    second = _fake_ftp()
    result = _probe([first, second])
    # Assert: untrusted with the presented fingerprint
    assert (result["status"], result["fingerprint"]) == ("untrusted", _CERT_SHA)
    # Assert: password sent on neither connection
    first.login.assert_not_called()
    second.login.assert_not_called()
    # Assert: password absent from the answer
    assert _SECRET not in json.dumps(result)


def test_second_handshake_is_unverified() -> None:
    """
    The fingerprint-reading handshake must not verify (it has to accept the refused certificate).

    Expected result:
    - the context given to the second FTP_TLS has CERT_NONE and no host check
    """
    first = _fake_ftp()
    first.auth.side_effect = ssl.SSLCertVerificationError("self-signed certificate")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", side_effect=[first, _fake_ftp()]) as ctor:
        probe_connection(_settings(), time.monotonic() + 15)
    context = ctor.call_args_list[1].kwargs["context"]
    # Assert: unverified
    assert context.verify_mode == ssl.CERT_NONE and context.check_hostname is False
    # Assert: the first one verified
    assert ctor.call_args_list[0].kwargs["context"].verify_mode == ssl.CERT_REQUIRED


def test_fingerprint_that_differs_is_changed_and_sends_no_password() -> None:
    """
    The pinned value is not the server's.

    Expected result:
    - status changed with the presented fingerprint; login never called
    """
    ftp = _fake_ftp()
    result = _probe(ftp, _settings(cert_fingerprint="0" * 64))
    # Assert: changed + presented fingerprint
    assert (result["status"], result["fingerprint"]) == ("changed", _CERT_SHA)
    # Assert: password not sent
    ftp.login.assert_not_called()


def test_bad_login_names_the_credentials_step_and_masks_the_password() -> None:
    """
    The server answers 530, echoing the password in its message.

    Expected result:
    - error, step "identifiants"; the password does not appear in the answer
    """
    ftp = _fake_ftp()
    ftp.login.side_effect = ftplib.error_perm(f"530 Login incorrect for {_SECRET}")
    result = _probe(ftp)
    # Assert: credentials step
    assert (result["status"], result["step"]) == ("error", "identifiants")
    # Assert: password masked
    assert _SECRET not in json.dumps(result)


@pytest.mark.parametrize("error", [
    ssl.SSLError("UNSUPPORTED_PROTOCOL"),
    ftplib.error_perm("534 Policy requires TLS"),
    EOFError(),
])
def test_tls_refused_names_the_tls_step(error: Exception) -> None:
    """
    No TLS on the server, or a version below 1.2.

    Expected result:
    - error, step "sécurité TLS"; no login
    """
    ftp = _fake_ftp()
    ftp.auth.side_effect = error
    result = _probe(ftp)
    # Assert: TLS step
    assert (result["status"], result["step"]) == ("error", "sécurité TLS")
    ftp.login.assert_not_called()


@pytest.mark.parametrize("overrides", [{"host": ""}, {"user": ""}])
def test_incomplete_settings_contact_nothing(overrides: dict[str, str]) -> None:
    """
    No host or no user saved.

    Expected result:
    - error, step "connexion"; FTP_TLS never built
    """
    with patch.object(ftps_upload.ftplib, "FTP_TLS") as ctor:
        result = probe_connection(_settings(**overrides), time.monotonic() + 15)
    # Assert: connection step
    assert (result["status"], result["step"]) == ("error", "connexion")
    # Assert: nothing contacted
    ctor.assert_not_called()


def _run_cli(config: dict[str, str], password: str) -> subprocess.CompletedProcess[str]:
    """Run `siadc09d.py --test-ftps` as PHP does."""
    env = {**os.environ, "SIA_FTPS_PASSWORD": password}
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--test-ftps", "--config", json.dumps(config)],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )


def test_cli_entry_prints_one_json_line_and_never_the_password() -> None:
    """
    The subprocess boundary against a closed local port.

    Expected result:
    - exit 0, one JSON line with status error and step "connexion"
    - the password is in neither stdout nor stderr
    """
    done = _run_cli({"ftps_host": "127.0.0.1", "ftps_port": "1", "ftps_user": "u"}, _SECRET)
    # Assert: clean exit
    assert done.returncode == 0
    result = json.loads(done.stdout)
    # Assert: connection error
    assert (result["status"], result["step"]) == ("error", "connexion")
    # Assert: password absent from both streams
    assert _SECRET not in done.stdout and _SECRET not in done.stderr


def test_cli_entry_reports_an_invalid_fingerprint_as_an_error_answer() -> None:
    """
    A malformed saved fingerprint must still produce a JSON verdict.

    Expected result:
    - status error, nothing contacted
    """
    done = _run_cli(
        {"ftps_host": "127.0.0.1", "ftps_port": "1", "ftps_user": "u", "ftps_cert_fingerprint": "zz"},
        _SECRET,
    )
    # Assert: an error verdict
    assert json.loads(done.stdout)["status"] == "error"
