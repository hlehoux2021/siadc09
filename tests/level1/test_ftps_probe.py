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
    # Assert: login was reached once the fingerprint matched
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
    # Assert: no login attempt on an unreachable host
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
    # Assert: nothing contacted
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


@pytest.mark.parametrize("port", ["0", "70000", "-5", "abc"])
def test_cli_entry_reports_an_out_of_range_port_as_an_error_answer(port: str) -> None:
    """
    A saved port outside 1-65535 (or not a number) must not crash the probe.

    Expected result:
    - status error, step "connexion", exit 0 (no "Erreur interne")
    """
    done = _run_cli({"ftps_host": "127.0.0.1", "ftps_port": port, "ftps_user": "u"}, _SECRET)
    result = json.loads(done.stdout)
    # Assert: a configuration error verdict, not the generic internal error
    assert (done.returncode, result["status"], result.get("step")) == (0, "error", "connexion")


def test_connection_reset_during_login_is_not_reported_as_bad_credentials() -> None:
    """
    The link drops while logging in (no server reply).

    Expected result:
    - error, step "connexion" rather than "identifiants"
    """
    ftp = _fake_ftp()
    ftp.login.side_effect = ConnectionResetError(54, "Connection reset by peer")
    result = _probe(ftp)
    # Assert: a connection fault, not a credentials refusal
    assert (result["status"], result["step"]) == ("error", "connexion")


def _probe_plain(ftp: MagicMock, settings: FtpsSettings | None = None) -> tuple[dict[str, str], MagicMock]:
    """Run the probe with plain FTP replaced by `ftp`; return the answer and the FTP_TLS double."""
    with patch.object(ftps_upload.ftplib, "FTP", return_value=ftp), \
            patch.object(ftps_upload.ftplib, "FTP_TLS") as tls:
        return probe_connection(settings or _settings(plain=True), time.monotonic() + 15), tls


def test_plain_probe_logs_in_without_tls_and_says_the_link_is_not_encrypted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Plain mode on, a server without FTPS (matrix: Test, plain on / Plain on, server has FTPS).

    Expected result:
    - status ok, detail says the link is not encrypted; connect + login only
    - FTP_TLS is never built, no AUTH TLS, no write
    - the log says "sans TLS" and never holds the password
    """
    ftp = MagicMock()
    with caplog.at_level("DEBUG"):
        result, tls = _probe_plain(ftp)
    # Assert: success with the unencrypted notice
    assert result["status"] == "ok" and "pas chiffrée" in result["detail"]
    # Assert: no TLS object, no AUTH TLS
    assert not tls.called and not ftp.auth.called
    # Assert: connect then login with the password
    ftp.connect.assert_called_once_with("ftp.example", 2121)
    ftp.login.assert_called_once_with("siaftps", _SECRET)
    _assert_no_write(ftp)
    # Assert: the log names the mode, without the secret
    assert "sans TLS" in caplog.text and _SECRET not in caplog.text


def test_plain_probe_ignores_a_saved_fingerprint() -> None:
    """
    Plain mode with an old pinned fingerprint (matrix: Plain on, fingerprint saved).

    Expected result:
    - status ok, no certificate read
    """
    ftp = MagicMock()
    result, _ = _probe_plain(ftp, _settings(plain=True, cert_fingerprint=_CERT_SHA))
    # Assert: success, certificate never looked at
    assert result["status"] == "ok"
    assert not ftp.sock.getpeercert.called


def test_plain_probe_bad_login_gives_the_login_failure() -> None:
    """
    Plain mode, the server refuses the credentials.

    Expected result:
    - error, step "identifiants", password masked
    """
    ftp = MagicMock()
    ftp.login.side_effect = ftplib.error_perm(f"530 Login incorrect {_SECRET}")
    result, _ = _probe_plain(ftp)
    # Assert: the login step is named
    assert (result["status"], result["step"]) == ("error", "identifiants")
    # Assert: the password is masked
    assert _SECRET not in json.dumps(result)


def test_plain_off_server_without_ftps_still_fails_at_the_tls_step() -> None:
    """
    Default mode against a server answering 530 to AUTH TLS (matrix: Plain off).

    Expected result:
    - error, step "sécurité TLS", plain FTP never used
    """
    ftp = _fake_ftp()
    ftp.auth.side_effect = ftplib.error_perm("530 Please login with USER and PASS")
    with patch.object(ftps_upload.ftplib, "FTP") as plain_ftp:
        result = _probe(ftp)
    # Assert: unchanged failure, no silent fallback
    assert (result["status"], result["step"]) == ("error", "sécurité TLS")
    assert not plain_ftp.called


def test_cli_entry_passes_the_plain_flag_to_the_probe() -> None:
    """
    The --test-ftps config carries ftps_plain (true) and a malformed fingerprint is then ignored.

    Expected result:
    - the answer is not the "Réglages FTPS invalides" error (the fingerprint is not parsed)
    - the connection error comes from the plain path: it speaks of the FTP service, not FTPS
    """
    done = _run_cli(
        {"ftps_host": "127.0.0.1", "ftps_port": "1", "ftps_user": "u",
         "ftps_cert_fingerprint": "zz", "ftps_plain": True},  # type: ignore[dict-item]
        _SECRET,
    )
    answer = json.loads(done.stdout)
    # Assert: connection error, not an invalid-settings error
    assert "invalides" not in answer["detail"]
    # Assert: the plain path ran (its connect failure names the FTP service)
    assert answer["step"] == "connexion" and "service FTP est" in answer["detail"]
