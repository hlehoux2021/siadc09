"""
Level 2 async integration tests for Epic 8 connection test.

Tests _send_raw_once() and run_connection_test() with real asyncio event loop
integration — transport lifecycle, timeout races, concurrent behavior, and
transport selection. Unlike level 1 tests (patched transport, no real async),
these exercise the actual async control flow.

Reference: resources/siadc09d/siadc09d.py
Reference: _bmad-output/implementation-artifacts/8-1-wizard-steps-1-2-csr-preset-selection.md
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.siadc09d import _send_raw_once, run_connection_test
from resources.siadc09d.sia_transport import (
    SIABaseTransport,
    SIATCPTransport,
    SIATransportError,
    SIATransportResult,
    SIAUDPTransport,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


_VALID_MANUAL_CONFIG = {
    "csr_provider": "manual",
    "csr_ip": "192.168.1.100",
    "csr_port": "5000",
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


class FakeTransport(SIABaseTransport):
    """Minimal async transport for integration testing.

    Tracks lifecycle calls (start/send_frame/close) and allows configurable
    responses and delays to test timeout and error paths.
    """

    def __init__(
        self,
        response: SIATransportResult | None = None,
        delay_s: float = 0.0,
        start_error: Exception | None = None,
        send_error: Exception | None = None,
    ) -> None:
        super().__init__(crc_format="hex")
        self._response: SIATransportResult = response or SIATransportResult(
            status="ack", raw_nak=None
        )
        self._delay_s = delay_s
        self._start_error = start_error
        self._send_error = send_error
        self.started = False
        self.closed = False
        self.frames_sent: list[bytes] = []

    async def start(self) -> None:
        if self._start_error:
            raise self._start_error
        self.started = True

    async def send_frame(self, frame: bytes) -> SIATransportResult:
        self.frames_sent.append(frame)
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._send_error:
            raise self._send_error
        return self._response

    async def close(self) -> None:
        self.closed = True


# ── _send_raw_once — transport lifecycle integration ─────────────────────────


@pytest.mark.asyncio
async def test_send_raw_once_start_send_close_sequence():
    """
    _send_raw_once() follows start → send_frame → close lifecycle in order.

    Expected result:
    - Transport.start() called before send_frame()
    - Transport.close() called after send_frame()
    - Frame bytes passed through to send_frame()
    """
    fake_t = FakeTransport()

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"test-frame", timeout=5)

    # Assert: transport was started
    assert fake_t.started is True
    # Assert: frame was sent
    assert b"test-frame" in fake_t.frames_sent
    # Assert: transport was closed
    assert fake_t.closed is True
    # Assert: ack status returned
    assert result == {"status": "ack"}


@pytest.mark.asyncio
async def test_send_raw_once_close_called_after_start_failure():
    """
    _send_raw_once() calls close() even when start() raises SIATransportError.
    Ensures no resource leak on failed initialization.

    Expected result:
    - Transport.close() called despite start() failure
    - Returns {"status": "timeout"} (error mapped to timeout)
    """
    fake_t = FakeTransport(start_error=SIATransportError("bind failed"))

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=5)

    # Assert: close() called in finally block
    assert fake_t.closed is True
    # Assert: SIATransportError mapped to timeout
    assert result == {"status": "timeout"}


@pytest.mark.asyncio
async def test_send_raw_once_close_called_after_send_frame_error():
    """
    _send_raw_once() calls close() even when send_frame() raises.

    Expected result:
    - Transport.close() called after send_frame raises SIATransportError
    - Returns {"status": "timeout"}
    """
    fake_t = FakeTransport(send_error=SIATransportError("socket error"))

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=5)

    # Assert: close() called in finally block
    assert fake_t.closed is True
    # Assert: transport error mapped to timeout
    assert result == {"status": "timeout"}


@pytest.mark.asyncio
async def test_send_raw_once_timeout_via_wait_for():
    """
    _send_raw_once() uses asyncio.wait_for() to enforce the timeout parameter.
    A slow send_frame that exceeds the timeout is cancelled and returns timeout.

    Expected result:
    - Transport with delay > timeout returns {"status": "timeout"}
    - Transport.close() still called (finally block)
    """
    fake_t = FakeTransport(delay_s=10.0)

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=0.05)

    # Assert: timeout correctly enforced via wait_for
    assert result == {"status": "timeout"}
    # Assert: close() called despite timeout
    assert fake_t.closed is True


@pytest.mark.asyncio
async def test_send_raw_once_nak_status_propagated():
    """
    _send_raw_once() propagates NAK status from transport but strips raw_nak.

    Expected result:
    - Returns {"status": "nak"} (no raw_nak in return value)
    """
    nak_response = SIATransportResult(status="nak", raw_nak=b"\x00\x01")
    fake_t = FakeTransport(response=nak_response)

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=5)

    # Assert: nak status propagated
    assert result == {"status": "nak"}


# ── _send_raw_once — transport selection ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_str,expected_class", [
    ("udp", "SIAUDPTransport"),
    ("UDP", "SIAUDPTransport"),
    ("tcp", "SIATCPTransport"),
    ("TCP", "SIATCPTransport"),
])
async def test_send_raw_once_transport_selection(
    transport_str: str, expected_class: str
):
    """
    _send_raw_once() selects correct transport class based on transport string.
    Case-insensitive: "udp"/"UDP" → SIAUDPTransport, "tcp"/"TCP" → SIATCPTransport.

    Expected result:
    - The correct transport class is instantiated for each transport string variant
    """
    fake_t = FakeTransport()

    with patch(f"resources.siadc09d.siadc09d.{expected_class}", return_value=fake_t) as mock_cls:
        await _send_raw_once("host", 5000, transport_str, b"frame", timeout=5)

    # Assert: correct transport class was instantiated
    assert mock_cls.called


@pytest.mark.asyncio
async def test_send_raw_once_udp_transport_params():
    """
    _send_raw_once() passes correct parameters to SIAUDPTransport constructor.

    Expected result:
    - host, port, receive_timeout_s, crc_format all passed correctly
    - receive_timeout_s is min(timeout, _TEST_RECEIVE_TIMEOUT_S)
    """
    with patch("resources.siadc09d.siadc09d.SIAUDPTransport") as MockUDP:
        fake_t = FakeTransport()
        MockUDP.return_value = fake_t
        await _send_raw_once("10.0.0.1", 9876, "udp", b"frame", timeout=5)

    # Assert: constructor called with correct params
    call_kwargs = MockUDP.call_args[1]
    assert call_kwargs["host"] == "10.0.0.1"
    assert call_kwargs["port"] == 9876
    assert call_kwargs["crc_format"] == "hex"
    # Assert: receive_timeout_s is min(timeout=5, _TEST_RECEIVE_TIMEOUT_S=10)
    assert call_kwargs["receive_timeout_s"] == 5.0


@pytest.mark.asyncio
async def test_send_raw_once_tcp_transport_params():
    """
    _send_raw_once() passes correct parameters to SIATCPTransport constructor.

    Expected result:
    - host, port, connect_timeout_s, receive_timeout_s, crc_format all passed
    - connect_timeout_s is _TEST_CONNECT_TIMEOUT_S (5.0)
    """
    with patch("resources.siadc09d.siadc09d.SIATCPTransport") as MockTCP:
        fake_t = FakeTransport()
        MockTCP.return_value = fake_t
        await _send_raw_once("10.0.0.1", 9876, "tcp", b"frame", timeout=15)

    # Assert: constructor called with correct params
    call_kwargs = MockTCP.call_args[1]
    assert call_kwargs["host"] == "10.0.0.1"
    assert call_kwargs["port"] == 9876
    assert call_kwargs["crc_format"] == "hex"
    # Assert: connect_timeout uses constant (5.0)
    assert call_kwargs["connect_timeout_s"] == 5.0
    # Assert: receive_timeout is min(timeout=15, _TEST_RECEIVE_TIMEOUT_S=10)
    assert call_kwargs["receive_timeout_s"] == 10.0


# ── _send_raw_once — concurrent behavior ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_raw_once_concurrent_calls_independent():
    """
    Multiple concurrent _send_raw_once() calls each get their own transport
    instance and operate independently.

    Expected result:
    - Two concurrent calls each create separate transports
    - Both return correct results independently
    - No shared state corruption between calls
    """
    call_count = 0

    def make_transport(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return FakeTransport(delay_s=0.01)

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", side_effect=make_transport):
        results = await asyncio.gather(
            _send_raw_once("host1", 5000, "udp", b"frame1", timeout=5),
            _send_raw_once("host2", 5001, "udp", b"frame2", timeout=5),
        )

    # Assert: two independent transports were created
    assert call_count == 2
    # Assert: both calls succeeded independently
    assert results[0] == {"status": "ack"}
    assert results[1] == {"status": "ack"}


@pytest.mark.asyncio
async def test_send_raw_once_one_timeout_does_not_affect_other():
    """
    When one concurrent _send_raw_once() times out, the other still succeeds.

    Expected result:
    - Slow transport returns timeout
    - Fast transport returns ack
    - No cross-contamination between independent calls
    """
    transports_created = []

    def make_transport(*args, **kwargs):
        host = kwargs.get("host", args[0] if args else "")
        if host == "slow":
            t = FakeTransport(delay_s=10.0)
        else:
            t = FakeTransport(delay_s=0.0)
        transports_created.append(t)
        return t

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", side_effect=make_transport):
        results = await asyncio.gather(
            _send_raw_once("slow", 5000, "udp", b"frame1", timeout=0.05),
            _send_raw_once("fast", 5000, "udp", b"frame2", timeout=5),
        )

    # Assert: slow call timed out
    assert results[0] == {"status": "timeout"}
    # Assert: fast call succeeded
    assert results[1] == {"status": "ack"}
    # Assert: both transports closed
    assert all(t.closed for t in transports_created)


# ── _send_raw_once — error classification ────────────────────────────────────


@pytest.mark.asyncio
async def test_send_raw_once_oserror_mapped_to_timeout():
    """
    _send_raw_once() maps OSError (network unreachable, socket failure) to
    {"status": "timeout"} — it never propagates network exceptions to caller.

    Expected result:
    - OSError during start → {"status": "timeout"}
    """
    fake_t = FakeTransport(start_error=OSError("Network unreachable"))

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=5)

    # Assert: OSError mapped to timeout (not propagated)
    assert result == {"status": "timeout"}


@pytest.mark.asyncio
async def test_send_raw_once_unexpected_exception_mapped_to_timeout():
    """
    _send_raw_once() maps unexpected exceptions (RuntimeError, etc.) to
    {"status": "timeout"} — the caller (run_connection_test) never crashes.

    Expected result:
    - Unexpected exception → {"status": "timeout"}
    - Transport still closed
    """
    fake_t = FakeTransport(send_error=RuntimeError("unexpected"))

    with patch("resources.siadc09d.siadc09d.SIAUDPTransport", return_value=fake_t):
        result = await _send_raw_once("host", 5000, "udp", b"frame", timeout=5)

    # Assert: unexpected error mapped to timeout
    assert result == {"status": "timeout"}
    # Assert: close still called
    assert fake_t.closed is True


# ── run_connection_test — async integration ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_connection_test_builds_frame_from_config(
    capsys, monkeypatch
):
    """
    run_connection_test() uses SIAMessageBuilder to build a NULL supervision
    frame from the config's account_number and encryption settings.

    Expected result:
    - _send_raw_once receives a non-empty frame (bytes)
    - Frame is passed as positional arg to _send_raw_once
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    sent_frames: list[bytes] = []

    async def capturing_send(host, port, transport, frame, *, timeout):
        sent_frames.append(frame)
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=capturing_send):
        await run_connection_test(_VALID_MANUAL_CONFIG, timeout=5)

    # Assert: frame was built and sent
    assert len(sent_frames) == 1
    # Assert: frame is non-empty bytes
    assert isinstance(sent_frames[0], bytes)
    assert len(sent_frames[0]) > 0


@pytest.mark.asyncio
async def test_run_connection_test_passes_correct_host_port_transport(
    capsys, monkeypatch
):
    """
    run_connection_test() passes host/port/transport from config to _send_raw_once.

    Expected result:
    - host, port, transport match config values
    - port is integer (parsed from string)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    call_args: list[tuple] = []

    async def capturing_send(host, port, transport, frame, *, timeout):
        call_args.append((host, port, transport))
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=capturing_send):
        await run_connection_test(_VALID_MANUAL_CONFIG, timeout=5)

    # Assert: host from config
    assert call_args[0][0] == "192.168.1.100"
    # Assert: port parsed from string to int (PHP passes strings)
    assert call_args[0][1] == 5000
    # Assert: transport from config
    assert call_args[0][2] == "udp"


@pytest.mark.asyncio
async def test_run_connection_test_preset_mode_reads_host_from_preset(
    capsys, monkeypatch, tmp_path
):
    """
    run_connection_test() in preset mode reads csr_ip/csr_port from the preset
    JSON, not from the config dict.

    Expected result:
    - _send_raw_once receives host from preset (192.168.1.200)
    - _send_raw_once receives port from preset (5000)
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    (tmp_path / "csr_presets.json").write_text(
        json.dumps(_PRESETS_DATA), encoding="utf-8"
    )

    config = {"csr_provider": "ima_protect", "account_number": "001234"}
    call_args: list[tuple] = []

    async def capturing_send(host, port, transport, frame, *, timeout):
        call_args.append((host, port, transport))
        return {"status": "ack"}

    real_path = Path

    def patched_path(arg):
        p = real_path(arg)
        if str(p).endswith("siadc09d.py"):
            return real_path(str(tmp_path) + "/siadc09d.py")
        return p

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=capturing_send), \
         patch("resources.siadc09d.siadc09d.Path", side_effect=patched_path):
        await run_connection_test(config, timeout=5)

    # Assert: host from preset JSON (not config dict)
    assert call_args[0][0] == "192.168.1.200"
    # Assert: port from preset JSON
    assert call_args[0][1] == 5000


@pytest.mark.asyncio
async def test_run_connection_test_timeout_passed_to_send_raw_once(
    capsys, monkeypatch
):
    """
    run_connection_test() passes the timeout parameter through to _send_raw_once.

    Expected result:
    - _send_raw_once receives the exact timeout value from the caller
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    received_timeouts: list[int] = []

    async def capturing_send(host, port, transport, frame, *, timeout):
        received_timeouts.append(timeout)
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=capturing_send):
        await run_connection_test(_VALID_MANUAL_CONFIG, timeout=42)

    # Assert: timeout passed through unchanged
    assert received_timeouts == [42]


@pytest.mark.asyncio
async def test_run_connection_test_elapsed_ms_in_output(capsys, monkeypatch):
    """
    run_connection_test() measures elapsed time and includes it in "ok" output.

    Expected result:
    - stdout JSON detail contains elapsed time (e.g., "ACK reçu en Xms")
    - elapsed value is a reasonable positive integer
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")

    async def delayed_send(*args, **kwargs):
        await asyncio.sleep(0.01)
        return {"status": "ack"}

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=delayed_send):
        await run_connection_test(_VALID_MANUAL_CONFIG, timeout=5)

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: status is ok
    assert out["status"] == "ok"
    # Assert: detail contains elapsed time pattern
    assert "ms" in out["detail"]


@pytest.mark.asyncio
async def test_run_connection_test_encryption_with_env_key(capsys, monkeypatch):
    """
    run_connection_test() reads encryption key from SIA_ENCRYPTION_KEY env var.
    When both encryption_enabled and key are present, the frame is built with
    encryption=True.

    Expected result:
    - Frame is built (non-empty bytes sent to _send_raw_once)
    - No error — encryption config accepted
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "0123456789ABCDEF0123456789ABCDEF")
    sent_frames: list[bytes] = []

    async def capturing_send(host, port, transport, frame, *, timeout):
        sent_frames.append(frame)
        return {"status": "ack"}

    config = dict(_VALID_MANUAL_CONFIG, encryption_enabled=True)

    with patch("resources.siadc09d.siadc09d._send_raw_once", new=capturing_send):
        await run_connection_test(config, timeout=5)

    out = json.loads(capsys.readouterr().out.strip())
    # Assert: frame was sent (encryption did not block)
    assert len(sent_frames) == 1
    # Assert: result is ok
    assert out["status"] == "ok"


@pytest.mark.asyncio
async def test_run_connection_test_no_output_leaks_on_error(
    capsys, monkeypatch
):
    """
    run_connection_test() produces exactly one JSON line on stdout even on
    error paths. No stack traces or debug prints leak through.

    Expected result:
    - stdout is a single line of valid JSON
    - No stderr output
    """
    monkeypatch.setenv("SIA_ENCRYPTION_KEY", "")
    config = dict(_VALID_MANUAL_CONFIG, csr_ip="")

    await run_connection_test(config, timeout=5)

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip()]
    # Assert: exactly one line of output
    assert len(lines) == 1
    # Assert: it's valid JSON
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict)
    # Assert: no stderr leakage
    assert captured.err == ""
