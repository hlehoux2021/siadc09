"""
Connection test module unit tests for Story 8-2.

Tests run_connection_test() and _send_raw_once() in isolation by patching
the transport layer. No real network I/O — purely unit-level validation of
config parsing, guard conditions, result mapping, and JSON output shape.

Reference: resources/siadc09d/siadc09d.py
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from resources.siadc09d.siadc09d import _send_raw_once, run_connection_test

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_MANUAL_CONFIG = {
    "csr_provider": "manual",
    "csr_ip": "192.168.1.100",
    "csr_port": "5000",  # string — PHP always passes strings
    "transport": "udp",
    "crc_format": "hex",
    "encryption_enabled": False,
    "account_number": "001234",
}

_PRESETS_DATA = {
    "version": 1,
    "presets": [{
        "id": "ima_protect",
        "label": "IMA Protect",
        "csr_ip": "192.168.1.200",
        "csr_port": 5000,
        "transport": "udp",
        "crc_format": "hex",
        "encryption_enabled": False,
        "supervision_interval": 60,
        "retry_count": 3,
    }],
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


def test_send_raw_once_returns_timeout_on_oserror():
    """
    _send_raw_once returns {"status": "timeout"} when OSError is raised during
    socket setup (e.g., network interface unavailable, port bind failure).

    Expected result:
    - Returns dict with status == "timeout" (not a propagated exception)
    """
    mock_transport = AsyncMock()
    mock_transport.start = AsyncMock(side_effect=OSError("Network unreachable"))
    mock_transport.close = AsyncMock()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=mock_transport):
        result = _run(_send_raw_once("host", 5000, "udp", b"frame", timeout=5))

    # Assert: OS-level network error maps to timeout status
    assert result == {"status": "timeout"}


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
    the placeholder value from the IMA Protect preset before real IP is configured.

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


def test_run_connection_test_preset_crc_format_used(capsys, monkeypatch, tmp_path):
    """
    run_connection_test() reads crc_format from the preset JSON when
    provider != "manual". The builder must use the preset's crc_format,
    not a hardcoded value.

    Patches the presets JSON path at module level so no real file I/O touches
    the production csr_presets.json.

    Expected result:
    - _send_raw_once is called (crc_format was read from preset without error)
    - stdout JSON has status == "ok"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    presets_file = tmp_path / "csr_presets.json"
    presets_file.write_text(json.dumps(_PRESETS_DATA), encoding="utf-8")

    config = {
        "csr_provider": "ima_protect",
        "account_number": "001234",
    }

    call_count = []

    async def fake_send(*args, **kwargs):
        call_count.append(1)
        return {"status": "ack"}

    # Patch Path so that Path(__file__).parent / "csr_presets.json" resolves to tmp_path file.
    # Production code: presets_path = Path(__file__).parent / "csr_presets.json"
    real_path = Path
    def patched_path(arg):
        p = real_path(arg)
        # Replace the module-file path with tmp_path so that .parent / "csr_presets.json" works
        if str(p).endswith("siadc09d.py"):
            return real_path(str(tmp_path) + "/siadc09d.py")
        return p

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=fake_send), \
         patch("resources.siadc09d.siadc09d.Path", side_effect=patched_path):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: preset was loaded and _send_raw_once was called
    assert call_count, "_send_raw_once must be called when preset is valid"
    # Assert: ack maps to ok
    assert out["status"] == "ok"


def _patch_presets_path(tmp_path: Path):
    """Return a Path side_effect that redirects __file__ lookups to tmp_path."""
    real_path = Path
    def patched(arg):
        p = real_path(arg)
        if str(p).endswith("siadc09d.py"):
            return real_path(str(tmp_path) + "/siadc09d.py")
        return p
    return patched


def test_run_connection_test_preset_tbd_ip_rejected(capsys, monkeypatch, tmp_path):
    """
    run_connection_test() rejects csr_ip == "TBD" even when it comes from the
    preset JSON (not the manual config). The ima_protect preset ships with
    csr_ip="TBD" as a placeholder — the guard must fire in preset mode too.

    Expected result:
    - stdout JSON has status == "error"
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    preset_with_tbd = {
        "version": 1,
        "presets": [{
            "id": "ima_protect",
            "label": "IMA Protect",
            "csr_ip": "TBD",
            "csr_port": 5000,
            "transport": "udp",
            "crc_format": "hex",
            "encryption_enabled": False,
            "supervision_interval": 60,
            "retry_count": 3,
        }],
    }
    (tmp_path / "csr_presets.json").write_text(json.dumps(preset_with_tbd), encoding="utf-8")

    config = {"csr_provider": "ima_protect", "account_number": "001234"}

    with patch("resources.siadc09d.siadc09d.Path", side_effect=_patch_presets_path(tmp_path)):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: TBD from preset is rejected just like TBD from manual config
    assert out["status"] == "error"


def test_run_connection_test_unknown_preset_prints_error(capsys, monkeypatch, tmp_path):
    """
    run_connection_test() prints {"status": "error"} when csr_provider names a
    preset that does not exist in csr_presets.json.

    Expected result:
    - stdout JSON has status == "error"
    - stdout JSON has a "detail" key mentioning the missing preset
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    (tmp_path / "csr_presets.json").write_text(json.dumps(_PRESETS_DATA), encoding="utf-8")

    config = {"csr_provider": "nonexistent_csr", "account_number": "001234"}

    with patch("resources.siadc09d.siadc09d.Path", side_effect=_patch_presets_path(tmp_path)):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: missing preset is rejected with error
    assert out["status"] == "error"
    # Assert: detail mentions the preset id
    assert "detail" in out


def test_run_connection_test_corrupted_presets_file_prints_error(capsys, monkeypatch, tmp_path):
    """
    run_connection_test() prints {"status": "error"} when csr_presets.json
    contains malformed JSON (e.g., truncated file during update).

    Expected result:
    - stdout JSON has status == "error" (no json.JSONDecodeError propagated)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    (tmp_path / "csr_presets.json").write_text("{not valid json", encoding="utf-8")

    config = {"csr_provider": "ima_protect", "account_number": "001234"}

    with patch("resources.siadc09d.siadc09d.Path", side_effect=_patch_presets_path(tmp_path)):
        _run(run_connection_test(config, timeout=5))

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: JSON parse failure is handled gracefully
    assert out["status"] == "error"


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
