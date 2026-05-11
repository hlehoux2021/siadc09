"""
Connection test module unit tests for Story 8-2.

Tests run_connection_test() and _send_raw_once() in isolation by patching
the transport layer. No real network I/O — purely unit-level validation of
config parsing, guard conditions, and result mapping.

Reference: resources/siadc09d/siadc09d.py
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""

import asyncio
import io
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import resources.siadc09d.siadc09d as siadc09d_module
from resources.siadc09d.siadc09d import _send_raw_once, run_connection_test

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_MANUAL_CONFIG = {
    "csr_provider": "manual",
    "csr_ip": "192.168.1.100",
    "csr_port": 5000,
    "transport": "udp",
    "crc_format": "hex",
    "encryption_enabled": False,
    "account_number": "001234",
}


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ── _send_raw_once — transport routing ────────────────────────────────────────


def test_send_raw_once_returns_ack_status():
    """
    _send_raw_once returns {"status": "ack"} when the transport reports ACK.

    Expected result:
    - Returns dict with status == "ack"
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(return_value={"status": "ack"})
    mock_transport.close = AsyncMock()

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
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(return_value={"status": "nak"})
    mock_transport.close = AsyncMock()

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


def test_send_raw_once_returns_timeout_on_oserror():
    """
    _send_raw_once returns {"status": "timeout"} when OSError (e.g., connection refused) is raised.

    Expected result:
    - Returns dict with status == "timeout" (not propagated exception)
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock(side_effect=OSError("Connection refused"))
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: connection error maps to timeout status
    assert result == {"status": "timeout"}


def test_send_raw_once_uses_tcp_transport_for_tcp():
    """
    _send_raw_once instantiates SIATCPTransport when transport="tcp".

    Expected result:
    - SIATCPTransport is constructed (not SIAUDPTransport)
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock()
    mock_transport.send_frame = AsyncMock(return_value={"status": "ack"})
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIATCPTransport", return_value=mock_transport) as mock_tcp, \
         patch("resources.siadc09d.siadc09d.SIAUDPTransport") as mock_udp:
        _run(_send_raw_once("host", 5000, "tcp", b"frame", timeout=5))

    # Assert: TCP transport was instantiated, not UDP
    assert mock_tcp.called
    assert not mock_udp.called


# ── run_connection_test — config parsing and guard conditions ─────────────────


def test_run_connection_test_ack_prints_ok(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "ok", ...} to stdout when ACK is received.

    Expected result:
    - stdout contains JSON with status == "ok"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: ACK maps to status ok
    assert out["status"] == "ok"


def test_run_connection_test_nak_prints_nak(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "nak", ...} to stdout when NAK is received.

    Expected result:
    - stdout contains JSON with status == "nak"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "nak"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: NAK maps to status nak
    assert out["status"] == "nak"


def test_run_connection_test_timeout_prints_fail(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "fail", ...} to stdout on timeout.

    Expected result:
    - stdout contains JSON with status == "fail"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def fake_send(*args, **kwargs):
        return {"status": "timeout"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send):
        _run(run_connection_test(_VALID_MANUAL_CONFIG, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: timeout maps to status fail
    assert out["status"] == "fail"


def test_run_connection_test_tbd_ip_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when csr_ip is "TBD" —
    the placeholder value from the IMA Protect preset before real IP is configured.

    Expected result:
    - stdout contains JSON with status == "error" (no DNS lookup attempted)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_ip="TBD")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: TBD IP is rejected with error status
    assert out["status"] == "error"


def test_run_connection_test_missing_account_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when account_number is empty.

    Expected result:
    - stdout contains JSON with status == "error"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, account_number="")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: missing account triggers error
    assert out["status"] == "error"


def test_run_connection_test_non_numeric_port_prints_error(capsys, monkeypatch):
    """
    run_connection_test() prints {"status": "error"} when csr_port is a non-numeric string —
    int() conversion would raise ValueError without the guard.

    Expected result:
    - stdout contains JSON with status == "error" (no ValueError propagated)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_port="not-a-port")

    _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: bad port value is handled gracefully
    assert out["status"] == "error"


def test_run_connection_test_preset_crc_format_used(capsys, monkeypatch):
    """
    run_connection_test() reads crc_format from the preset JSON when provider != "manual".
    The builder must use the preset's crc_format, not a hardcoded value.

    Expected result:
    - _send_raw_once is called (i.e., guard passes), which implies crc_format was read
      from the preset without raising an error
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    # Use ima_protect preset (has crc_format="hex" in csr_presets.json)
    config = {
        "csr_provider": "ima_protect",
        "csr_ip": "192.168.1.100",  # override TBD for test
        "account_number": "001234",
    }

    call_count = []

    async def fake_send(*args, **kwargs):
        call_count.append(1)
        return {"status": "ack"}

    # Patch the preset csr_ip so the TBD guard doesn't fire
    presets_data = {
        "version": 1,
        "presets": [{
            "id": "ima_protect",
            "label": "IMA Protect",
            "csr_ip": "192.168.1.100",
            "csr_port": 5000,
            "transport": "udp",
            "crc_format": "hex",
            "encryption_enabled": False,
            "supervision_interval": 60,
            "retry_count": 3,
        }],
    }

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send), \
         patch("resources.siadc09d.siadc09d.Path") as mock_path:
        mock_path.return_value.__truediv__ = lambda self, other: mock_path.return_value
        mock_path.return_value.read_text = lambda **kw: json.dumps(presets_data)
        mock_path.return_value.parent = mock_path.return_value
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: preset was loaded and send was called (crc_format read successfully)
    assert call_count, "Expected _send_raw_once to be called"
    assert out["status"] == "ok"
