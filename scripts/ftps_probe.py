#!/usr/bin/env python3
"""Probe an FTPS server (explicit TLS): connect, upload, list, download, delete.

Prints one PASS/FAIL line per step and the server certificate SHA-256
fingerprint. The password is read from the FTPS_PASSWORD environment variable
and never printed. Exit code is 0 only when every step passes.

Certificate handling:
  default        verify the chain and host name (CA-signed server)
  --fingerprint  accept only a certificate with this SHA-256 (self-signed server)
  --insecure     no verification at all (discovery only: shows the fingerprint)
"""
import argparse
import ftplib
import hashlib
import io
import os
import ssl
import sys
import time
from collections.abc import Callable, Sequence
from typing import TypeVar

PAYLOAD = b"siaDC09 ftps probe\n"
DEFAULT_PORT = 21
DEFAULT_TIMEOUT_SECONDS = 10.0
SHA256_HEX_LENGTH = 64
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_PASSWORD = 2

HEX_DIGITS = "0123456789abcdef"
REMOTE_SEPARATOR = "/"
# ftplib.all_errors covers ftplib.Error, OSError (timeouts, ssl.SSLError) and EOFError
FTP_ERRORS = (*ftplib.all_errors, ValueError)

T = TypeVar("T")


class ProbeError(Exception):
    """A probe step failed; the message names the step."""


def normalize_fingerprint(text: str) -> str:
    """Return a SHA-256 fingerprint as 64 lowercase hex characters.

    Args:
        text: Fingerprint, with or without ':' or space separators.

    Raises:
        ValueError: The text is not 64 hex characters.
    """
    cleaned = text.replace(":", "").replace(" ", "").lower()
    if len(cleaned) != SHA256_HEX_LENGTH or any(c not in HEX_DIGITS for c in cleaned):
        raise ValueError("fingerprint must be 64 hex characters (SHA-256)")
    return cleaned


def build_context(args: argparse.Namespace) -> ssl.SSLContext:
    """Build the TLS context matching the chosen certificate policy."""
    context = ssl.create_default_context()
    if args.insecure or args.fingerprint:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def certificate_fingerprint(ftp: ftplib.FTP_TLS) -> str:
    """Return the SHA-256 of the server certificate (control channel must be TLS)."""
    der = ftp.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
    return hashlib.sha256(der).hexdigest()


def report(step: str, ok: bool, detail: str = "") -> None:
    """Print one result line."""
    print(f"{'PASS' if ok else 'FAIL'} {step}" + (f" - {detail}" if detail else ""))


def run_step(step: str, action: Callable[[], T]) -> T:
    """Run one step, print its result and return its value.

    Raises:
        ProbeError: The step failed.
    """
    try:
        value = action()
    except FTP_ERRORS as err:
        report(step, False, f"{type(err).__name__}: {err}")
        raise ProbeError(step) from err
    report(step, True)
    return value


def check_fingerprint(ftp: ftplib.FTP_TLS, expected_text: str) -> None:
    """Print the certificate fingerprint and compare it when one is expected.

    Raises:
        ProbeError: The certificate does not match.
    """
    seen = certificate_fingerprint(ftp)
    print(f"INFO certificate sha256 {seen}")
    if not expected_text:
        return
    matches = seen == expected_text
    report("fingerprint", matches, "" if matches else "does not match the expected value")
    if not matches:
        raise ProbeError("fingerprint")


def exercise_transfer(ftp: ftplib.FTP_TLS, remote_name: str) -> None:
    """Upload the payload, list it and download it back.

    Raises:
        ProbeError: A step failed or the downloaded content differs.
    """
    run_step("upload", lambda: ftp.storbinary(f"STOR {remote_name}", io.BytesIO(PAYLOAD)))
    try:
        names = run_step("list", ftp.nlst)
        if remote_name not in [_basename(name) for name in names]:
            report("list", False, "uploaded file not in listing")
            raise ProbeError("list")
        received = io.BytesIO()
        run_step("download", lambda: ftp.retrbinary(f"RETR {remote_name}", received.write))
        if received.getvalue() != PAYLOAD:
            report("download", False, "content differs from what was uploaded")
            raise ProbeError("download")
    finally:
        deleted = _delete(ftp, remote_name)
    if not deleted:
        raise ProbeError("delete")


def _basename(remote_path: str) -> str:
    """Return the last component of a remote path."""
    return remote_path.rsplit(REMOTE_SEPARATOR, 1)[-1]


def _delete(ftp: ftplib.FTP_TLS, remote_name: str) -> bool:
    """Delete the probe file and report the outcome; never raises.

    Returns:
        True when the file was deleted.
    """
    try:
        ftp.delete(remote_name)
    except FTP_ERRORS as err:
        report("delete", False, f"{type(err).__name__}: {err}")
        return False
    report("delete", True)
    return True


def probe(args: argparse.Namespace, password: str) -> None:
    """Run every step against the server.

    Raises:
        ProbeError: The first step that fails.
    """
    ftp = ftplib.FTP_TLS(context=build_context(args), timeout=args.timeout)
    remote_name = f"probe-{int(time.time())}.txt"
    try:
        run_step("connect", lambda: ftp.connect(args.host, args.port))
        run_step("tls", ftp.auth)
        check_fingerprint(ftp, args.fingerprint or "")
        run_step("login", lambda: ftp.login(args.user, password))
        run_step("data-protection", ftp.prot_p)
        if args.folder:
            run_step("cwd", lambda: ftp.cwd(args.folder))
        exercise_transfer(ftp, remote_name)
    finally:
        ftp.close()


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Probe an FTPS server (explicit TLS).")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", required=True)
    parser.add_argument("--folder", default="", help="remote folder to work in")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--fingerprint", type=normalize_fingerprint,
                        help="accept only this SHA-256 certificate fingerprint")
    policy.add_argument("--insecure", action="store_true",
                        help="skip certificate verification (shows the fingerprint)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and return the process exit code."""
    args = parse_args(argv)
    password = os.environ.get("FTPS_PASSWORD")
    if not password:
        print("FAIL password - set the FTPS_PASSWORD environment variable")
        return EXIT_NO_PASSWORD
    try:
        probe(args, password)
    except ProbeError as err:
        print(f"RESULT FAIL at step {err}")
        return EXIT_FAILED
    print("RESULT PASS")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
