"""
Connection test module unit tests for Story 8-2.

Tests run_connection_test() and _send_raw_once() in isolation by patching
the transport layer. No real network I/O — purely unit-level validation of
config parsing, guard conditions, result mapping, and JSON output shape.

Reference: resources/siadc09d/siadc09d.py
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""

import asyncio
import errno
import json
import socket
from unittest.mock import AsyncMock, patch

import pytest

from resources.siadc09d.siadc09d import (
    # Re-imported from the module under test, not from resources.siadc09d.sia_protocol:
    # siadc09d.py inserts resources/ on sys.path and imports the package as
    # `siadc09d`, so `resources.siadc09d.sia_protocol.SIATransportError` is a
    # *different* class object and its `except` clause would not match it.
    SIATransportError,
    _send_raw_once,
    run_connection_test,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_MANUAL_CONFIG = {
    "csr_ip": "192.168.1.100",
    "csr_port": "5000",  # string — PHP always passes strings
    "transport": "udp",
    "crc_format": "hex",
    "encryption_enabled": False,
    "account_number": "001234",
}

def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _make_mock_transport(status: str = "ack") -> AsyncMock:
    t = AsyncMock()
    t.start = AsyncMock()
    t.send_frame = AsyncMock(return_value={"status": status})
    t.close = AsyncMock()
    return t


# ── _send_raw_once — transport routing ────────────────────────────────────────


def test_send_raw_once_returns_ack_status():
    """
    _send_raw_once returns {"status": "ack"} when the transport reports ACK.

    Expected result:
    - Returns dict with status == "ack"
    """
    mock_transport = _make_mock_transport("ack")

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: ack status is surfaced from transport
    assert result == {"status": "ack"}


def test_send_raw_once_returns_nak_status():
    """
    _send_raw_once returns {"status": "nak"} when the transport reports NAK.

    Expected result:
    - Returns dict with status == "nak"
    """
    mock_transport = _make_mock_transport("nak")

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: nak status is surfaced from transport
    assert result == {"status": "nak"}


def test_send_raw_once_returns_timeout_on_asyncio_timeout():
    """
    _send_raw_once returns {"status": "timeout"} when asyncio.TimeoutError is raised.

    Expected result:
    - Returns dict with status == "timeout"
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: timeout maps to timeout status
    assert result == {"status": "timeout"}


def test_send_raw_once_returns_network_on_unclassified_oserror():
    """
    _send_raw_once returns status "network" when an OSError with no usable errno
    is raised during socket setup (e.g. port bind failure). It must NOT be
    reported as "timeout" — nothing timed out.

    Expected result:
    - Returns status == "network" (not a propagated exception, not "timeout")
    - Carries an "error" key with the technical cause for the log
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock(side_effect=OSError("bind failed"))
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: unclassified OS error is reported as a network error, not a timeout
    assert result["status"] == "network"
    # Assert: the technical cause is preserved for the siaDC09 log
    assert "bind failed" in result["error"]


def test_send_raw_once_returns_refused_on_connection_refused():
    """
    _send_raw_once distinguishes a refused connection (nothing listening on the
    port) from a timeout. This is the single most common wizard misconfiguration
    — wrong port, or UDP configured against a TCP-only receiver.

    Expected result:
    - Returns status == "refused"
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIATCPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 10002, "tcp", b"frame", timeout=5))

    # Assert: connection refused is its own diagnosis, never a timeout
    assert result["status"] == "refused"


def test_send_raw_once_returns_dns_on_gaierror():
    """
    _send_raw_once reports a name-resolution failure as "dns" — the host name is
    unknown to the Jeedom machine, so no packet was ever sent.

    Expected result:
    - Returns status == "dns"
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock(side_effect=socket.gaierror(8, "nodename nor servname provided"))
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("csr.invalid", 5000, "udp", b"frame", timeout=5))

    # Assert: DNS failure is reported as such, not as a timeout
    assert result["status"] == "dns"


def test_send_raw_once_unwraps_transport_error_cause():
    """
    The transport wraps socket errors as SIATransportError(...) from e, so the
    original errno survives as __cause__. _send_raw_once must classify from the
    cause rather than collapsing every SIATransportError into one status.

    Expected result:
    - A wrapped ConnectionRefusedError yields status == "refused"
    """
    cause = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
    wrapped = SIATransportError("TCP socket error: ConnectionRefusedError()")
    wrapped.__cause__ = cause
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(side_effect=wrapped)
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIATCPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 10002, "tcp", b"frame", timeout=5))

    # Assert: the wrapped cause drives the diagnosis
    assert result["status"] == "refused"


def test_send_raw_once_returns_connect_timeout_for_tcp_connect_failure():
    """
    A TCP connect timeout (SYN dropped by a firewall) is raised as a
    SIATransportError with no __cause__ — it must be told apart from a receiver
    that accepted the connection and then stayed silent.

    Expected result:
    - Returns status == "connect_timeout", not "timeout"
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(
        side_effect=SIATransportError("TCP connect timeout (5.0s)")
    )
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIATCPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 10002, "tcp", b"frame", timeout=5))

    # Assert: connect-phase failure is distinguished from response silence
    assert result["status"] == "connect_timeout"


def test_send_raw_once_returns_bad_reply_when_response_unparseable():
    """
    The transport reports an unparseable reply as status 'timeout' with
    raw_response set (sia_transport.py _parse_response). _send_raw_once must
    surface that as "bad_reply" — the receiver DID answer, the frame just failed
    CRC/format validation (typically a hex vs bin CRC mismatch).

    Expected result:
    - Returns status == "bad_reply"
    - The raw bytes are carried in "error" for the log
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(return_value={
        "status": "timeout",
        "raw_nak": None,
        "raw_response": b"\x0a1234\"ACK\"0000\r",
    })
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: a reply that failed validation is not silence
    assert result["status"] == "bad_reply"
    # Assert: the raw bytes are available for the siaDC09 log
    assert "ACK" in result["error"]


def test_send_raw_once_uses_tcp_transport_for_tcp():
    """
    _send_raw_once instantiates SIATCPTransport when transport="tcp".

    Expected result:
    - SIATCPTransport is constructed (not SIAUDPTransport)
    """
    mock_transport = _make_mock_transport("ack")

    with patch("resources.siadc09d.siadc09d.SIATCPTransport", return_value=mock_transport) as mock_tcp, \
         patch("resources.siadc09d.siadc09d.SIAUDPTransport") as mock_udp:
        _run(_send_raw_once("host", 5000, "tcp", b"frame", timeout=5))

    # Assert: TCP transport was instantiated, not UDP
    assert mock_tcp.called
    assert not mock_udp.called


def test_send_raw_once_transport_close_called_on_exception():
    """
    _send_raw_once calls t.close() even when send_frame raises an exception.
    This ensures no dangling sockets under any error path.

    Expected result:
    - close() is called exactly once even after TimeoutError
    """
    mock_transport = _make_mock_transport()
    mock_transport.send_frame = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: close() was called (finally block executed)
    mock_transport.close.assert_awaited_once()


def test_send_raw_once_bad_transport_string_raises():
    """
    _send_raw_once raises ValueError when given an unknown transport string
    (e.g., "ftp"). TransportType("FTP") raises ValueError at line 65, BEFORE
    the try block that catches OSError/TimeoutError — so it propagates to the
    caller. Callers (run_connection_test) must only pass validated transport
    values ("udp"/"tcp").

    Expected result:
    - ValueError is raised, not silently swallowed
    """
    with pytest.raises(ValueError):
        # Assert: bad transport string propagates as ValueError (not silently mapped to timeout)
        _run(_send_raw_once("host", 5000, "ftp", b"frame", timeout=5))


# ── run_connection_test — config parsing and guard conditions ─────────────────


def test_run_connection_test_ack_prints_ok(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "ok", "detail": ...} to stdout when ACK.

    Expected result:
    - stdout JSON has status == "ok"
    - stdout JSON has a non-empty "detail" key (elapsed time string)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: ACK maps to status ok
    assert out["status"] == "ok"
    # Assert: detail key is present (elapsed time message)
    assert "detail" in out and out["detail"]


def test_run_connection_test_nak_prints_nak(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "nak", "detail": ...} when NAK.

    Expected result:
    - stdout JSON has status == "nak"
    - stdout JSON has a "detail" key
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "nak"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: NAK maps to status nak
    assert out["status"] == "nak"
    # Assert: detail key is present
    assert "detail" in out


def test_run_connection_test_timeout_prints_fail(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "fail", "detail": ...} on timeout.

    Expected result:
    - stdout JSON has status == "fail"
    - stdout JSON has a "detail" key mentioning timeout
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "timeout"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: timeout maps to status fail
    assert out["status"] == "fail"
    # Assert: detail mentions timeout
    assert "detail" in out and "timeout" in out["detail"].lower()


def test_run_connection_test_tbd_ip_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when csr_ip is "TBD" —
    the placeholder IP left by the removed IMA Protect preset in older configs.

    Expected result:
    - stdout JSON has status == "error" (no DNS lookup attempted)
    - stdout JSON has a "detail" key explaining the incomplete config
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_ip="TBD")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: TBD IP is rejected with error status
    assert out["status"] == "error"
    # Assert: detail key is present
    assert "detail" in out


def test_run_connection_test_missing_account_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when account_number is empty.

    Expected result:
    - stdout JSON has status == "error"
    - stdout JSON has a "detail" key
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, account_number="")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: missing account triggers error
    assert out["status"] == "error"
    # Assert: detail key is present
    assert "detail" in out


def test_run_connection_test_non_numeric_port_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when csr_port is a
    non-numeric string. int() conversion raises ValueError without the guard.

    Expected result:
    - stdout JSON has status == "error" (no ValueError propagated)
    - stdout JSON has a "detail" key
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_port="not-a-port")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: bad port value is handled gracefully
    assert out["status"] == "error"
    # Assert: detail key is present
    assert "detail" in out


def test_run_connection_test_string_port_parses_correctly(capsys, monkeypatch):
    """
    run_connection_test() accepts a string port ("5000") — the real production
    path where PHP passes all config values as strings.

    Expected result:
    - _send_raw_once is called (guard does not reject a valid string port)
    - stdout JSON has status == "ok"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_port="5000")

    async def fake_send(*args, **kwargs):
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: string port is accepted and parsed correctly
    assert out["status"] == "ok"


def test_run_connection_test_encryption_sends_frame(capsys, monkeypatch):
    """
    run_connection_test() still calls _send_raw_once when encryption_enabled=True
    and SIA_ENCRYPTION_KEY is non-empty. The frame is built with encryption=True.

    Expected result:
    - _send_raw_once is called (encryption config does not short-circuit the test)
    - stdout JSON has status == "ok"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "0123456789abcdef")

    call_args = []

    async def fake_send(*args, **kwargs):
        call_args.append((args, kwargs))
        return {"status": "ack"}

    config = dict(_VALID_MANUAL_CONFIG, encryption_enabled=True)

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: send was called even with encryption enabled
    assert call_args, "_send_raw_once must be called when encryption is configured"
    # Assert: result is ok
    assert out["status"] == "ok"


def test_run_connection_test_encryption_disabled_without_key(capsys, monkeypatch):
    """
    run_connection_test() sends an unencrypted frame when encryption_enabled=True
    but SIA_ENCRYPTION_KEY is absent. The guard `encryption_enabled and bool(key)`
    must prevent encrypting without a key.

    Expected result:
    - _send_raw_once is called
    - stdout JSON has status == "ok" (no crash from empty key)
    """
    monkeypatch.delenv("SIA_ENCRYPTION_KEY", raising=False)

    call_count = []

    async def fake_send(*args, **kwargs):
        call_count.append(1)
        return {"status": "ack"}

    config = dict(_VALID_MANUAL_CONFIG, encryption_enabled=True)

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: missing key degrades gracefully to unencrypted send
    assert call_count, "_send_raw_once must be called even without encryption key"
    # Assert: result is ok (not an error)
    assert out["status"] == "ok"


def test_run_connection_test_output_is_valid_json(capsys, monkeypatch):
    """
    run_connection_test() always writes exactly one line of valid JSON to stdout
    with no trailing garbage. PHP uses json_decode on this output — any extra
    output (warnings, debug prints) would break the PHP caller.

    Expected result:
    - stdout is parseable as JSON in a single json.loads() call
    - The parsed value is a dict
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    raw = capsys.readouterr().out.strip()
    # Assert: output is valid JSON
    parsed = json.loads(raw)
    # Assert: parsed value is a dict (not a list or scalar)
    assert isinstance(parsed, dict)
