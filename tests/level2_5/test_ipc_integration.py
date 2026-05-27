"""Level 2.5 IPC integration tests for Story 6.6.

Validates that daemon methods emit correct callback payloads via send_to_jeedom().
Uses a recording shim (mock send_to_jeedom) to capture emitted payloads.

Reference: _bmad-output/implementation-artifacts/6-6-php-core-integration-ipc-tests.md
Reference: tests/fixtures/ipc_schema.py (authoritative callback schemas)
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.daemon import SIADaemon, SM1State, SM2State
from resources.siadc09d.error_handler import (
    BadCSRResponseCtx,
    ErrorCode,
    EventFailedCtx,
    SM1DisconnectedCtx,
    SM1NakCtx,
    SM1TimeoutCtx,
    T3_PREFIX,
    TransportPermanentCtx,
)
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_transport import TransportType


@pytest.fixture
def preset() -> CSRPreset:
    """Minimal CSRPreset for IPC tests (no real transport needed)."""
    return CSRPreset(
        csr_provider="test",
        schema_version=1,
        host="127.0.0.1",
        port=9999,
        account_number="ABC123",
        transport=TransportType.UDP,
        crc_format="hex",
        connect_timeout_s=5.0,
        receive_timeout_s=5.0,
        supervision_interval_s=60.0,
        encryption_enabled=False,
        reconnect_delay_s=5.0,
    )


@pytest.fixture
def daemon(preset: CSRPreset) -> SIADaemon:
    """Create SIADaemon instance for IPC testing."""
    with patch('sys.argv', ['test']):
        d = SIADaemon(preset=preset)
    d._account = "ABC123"
    return d


@pytest.fixture
def captured_payloads(daemon: SIADaemon) -> list[dict]:
    """Mock send_to_jeedom to capture emitted payloads."""
    payloads: list[dict] = []

    async def _capture(payload: dict) -> None:
        payloads.append(payload)

    daemon.send_to_jeedom = AsyncMock(side_effect=_capture)
    return payloads


# ── Task 1: _send_callback() tests ─────────────────────────────────────────


class TestSendCallback:
    """AC3: _send_callback() wraps send_to_jeedom() defensively."""

    @pytest.mark.asyncio
    async def test_send_callback_delivers_payload(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """_send_callback() calls send_to_jeedom with the given payload.

        Expected: payload appears in captured list unchanged.
        """
        payload = {"type": "info_update", "supervision_state": 2}
        await daemon._send_callback(payload)
        assert len(captured_payloads) == 1  # exactly one call
        assert captured_payloads[0] == payload  # payload delivered unchanged

    @pytest.mark.asyncio
    async def test_send_callback_validates_type_field(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """_send_callback() rejects payloads missing 'type' field.

        Expected: no call to send_to_jeedom, error logged.
        """
        payload = {"supervision_state": 2}  # missing 'type'
        await daemon._send_callback(payload)
        assert len(captured_payloads) == 0  # not sent

    @pytest.mark.asyncio
    async def test_send_callback_rejects_bool_values(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """_send_callback() rejects payloads containing Python bool values.

        Expected: no call to send_to_jeedom, error logged.
        """
        payload = {"type": "info_update", "encryption_enabled": True}  # bool forbidden
        await daemon._send_callback(payload)
        assert len(captured_payloads) == 0  # not sent

    @pytest.mark.asyncio
    async def test_send_callback_exception_resilience(
        self, daemon: SIADaemon, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3/AC8: send_to_jeedom raises → exception logged, daemon continues.

        Expected: ERROR logged, no exception propagated to caller.
        """
        daemon.send_to_jeedom = AsyncMock(side_effect=ConnectionError("PHP down"))
        with caplog.at_level(logging.ERROR):
            await daemon._send_callback({"type": "info_update", "supervision_state": 0})
        assert "PHP down" in caplog.text or "ConnectionError" in caplog.text

    @pytest.mark.asyncio
    async def test_send_callback_never_reraises(
        self, daemon: SIADaemon
    ) -> None:
        """_send_callback() never re-raises — non-fatal to daemon.

        Expected: method returns normally even on exception.
        """
        daemon.send_to_jeedom = AsyncMock(side_effect=RuntimeError("kaboom"))
        # Must not raise
        await daemon._send_callback({"type": "info_update", "supervision_state": 0})


# ── Task 2: _update_info_commands() tests ──────────────────────────────────


class TestUpdateInfoCommands:
    """AC1/AC5: _update_info_commands() emits info_update callback."""

    @pytest.mark.asyncio
    async def test_update_info_commands_emits_info_update(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC1/AC8: _update_info_commands() → info_update payload sent.

        Expected:
        - Exactly one payload in captured list
        - type == 'info_update'
        - All 4 state fields present with integer values
        """
        await daemon._update_info_commands()
        assert len(captured_payloads) == 1  # exactly one callback
        p = captured_payloads[0]
        assert p["type"] == "info_update"  # type field matches
        assert "supervision_state" in p  # supervision state included
        assert "supervision_label" in p  # supervision label included
        assert "event_state" in p  # event state included
        assert "event_label" in p  # event label included
        assert isinstance(p["supervision_state"], int)  # int, not bool
        assert isinstance(p["event_state"], int)  # int, not bool

    @pytest.mark.asyncio
    async def test_update_info_commands_partial_update(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC1: Partial payload uses provided data, always adds 'type'.

        Expected:
        - type == 'info_update' even when partial data provided
        - Only provided fields present (no extra state computation)
        """
        await daemon._update_info_commands({"supervision_state": 2, "supervision_label": "OK"})
        assert len(captured_payloads) == 1
        p = captured_payloads[0]
        assert p["type"] == "info_update"  # type always injected
        assert p["supervision_state"] == 2  # provided value kept


# ── Task 3: _dispatch_notify() + _notify() tests ───────────────────────────


class TestDispatchNotify:
    """AC2/AC7: _notify() dispatches via _dispatch_notify() with correct tier callbacks."""

    @pytest.mark.asyncio
    async def test_notify_t1_emits_message_center_only(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC2/AC8: T1 error → message_center only (no notify, no error_update).

        Expected:
        - One payload captured with type='message_center'
        - No 'notify' type payload emitted
        - No 'error_update' type payload emitted
        """
        ctx = SM1TimeoutCtx(elapsed_ms=5000.0, strike_count=1, supervision_interval_s=60.0)
        daemon._notify(ErrorCode.SUPERVISION_TIMEOUT, ctx)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

        types_emitted = {p["type"] for p in captured_payloads}
        assert "message_center" in types_emitted  # T1 fires message_center
        assert "notify" not in types_emitted  # T1 does NOT fire notify
        assert "error_update" not in types_emitted  # T1 does NOT fire error_update

    @pytest.mark.asyncio
    async def test_notify_t2_emits_message_center_and_notify(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC2/AC8: T2 error → message_center + notify + error_update.

        Expected:
        - message_center payload emitted
        - notify payload emitted
        - error_update payload emitted
        """
        ctx = BadCSRResponseCtx(
            raw_frame=b"\x00\x01",
            parse_error="test",
            csr_host="127.0.0.1",
            csr_port=9999,
            transport="udp",
        )
        daemon._notify(ErrorCode.BAD_CSR_RESPONSE, ctx)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

        types_emitted = {p["type"] for p in captured_payloads}
        assert "message_center" in types_emitted  # T2 fires message_center
        assert "notify" in types_emitted  # T2 fires notify
        assert "error_update" in types_emitted  # T2 fires error_update

    @pytest.mark.asyncio
    async def test_notify_t3_emits_critique_prefix(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC2/AC8: T3 error → notify title starts with 'CRITIQUE — '.

        Expected:
        - notify payload present
        - notify title starts with T3_PREFIX
        """
        ctx = SM1DisconnectedCtx(
            strike_count=3,
            last_ack_time_utc=None,
            time_since_last_ack_s=None,
            supervision_interval_s=60.0,
        )
        daemon._notify(ErrorCode.SUPERVISION_DISCONNECTED, ctx)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

        notify_payloads = [p for p in captured_payloads if p["type"] == "notify"]
        assert len(notify_payloads) >= 1  # at least one notify payload
        title = notify_payloads[0]["title"]
        assert T3_PREFIX in title  # T3 title contains CRITIQUE prefix

    @pytest.mark.asyncio
    async def test_error_update_on_new_error(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC7/AC8: New T2/T3 error → error_update with all 5 required fields.

        Expected:
        - error_update payload has: code, message, timestamp, context, count
        """
        ctx = BadCSRResponseCtx(
            raw_frame=b"\xff",
            parse_error="bad",
            csr_host="127.0.0.1",
            csr_port=9999,
            transport="udp",
        )
        daemon._notify(ErrorCode.BAD_CSR_RESPONSE, ctx)
        await asyncio.gather(*daemon._tasks, return_exceptions=True)

        error_updates = [p for p in captured_payloads if p["type"] == "error_update"
                         and "code" in p]
        assert len(error_updates) >= 1  # error_update emitted
        eu = error_updates[0]
        assert "code" in eu  # code field present
        assert "message" in eu  # message field present
        assert "timestamp" in eu  # timestamp field present
        assert "context" in eu  # context field present (may be None)
        assert "count" in eu  # count field present
        assert eu["count"] == 1  # new error starts at count=1

    @pytest.mark.asyncio
    async def test_error_update_resolve_t1_on_ack(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC7/AC8: ACK after strike>0 → error_update with resolve_t1=1.

        Expected:
        - error_update payload with resolve_t1=1 emitted
        """
        from unittest.mock import AsyncMock as AM
        daemon._log_sm1_supervision = AM()

        mock_transport = MagicMock()
        mock_transport.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        daemon._sia_transport = mock_transport
        daemon._strike_counter = 2  # was degraded
        daemon._sm1_state = SM1State.DEGRADED

        await daemon._handle_supervision_ack({"status": "ack", "raw_nak": None}, elapsed_ms=50.0)

        resolve_payloads = [p for p in captured_payloads
                            if p.get("type") == "error_update" and "resolve_t1" in p]
        assert len(resolve_payloads) >= 1  # resolve_t1 emitted
        assert resolve_payloads[0]["resolve_t1"] == 1  # integer 1, not True


# ── Task 4: message_trace callback tests ───────────────────────────────────


class TestMessageTrace:
    """AC6/AC8: _log_sm1_supervision() and _log_sm2_event() emit message_trace."""

    @pytest.mark.asyncio
    async def test_message_trace_supervision(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC6/AC8: Supervision ACK → message_trace with dialog.routine == 1.

        Expected:
        - message_trace payload emitted
        - dialog.routine == 1 (routine ACK)
        - dialog.dialog_type == 'supervision'
        """
        from resources.siadc09d.daemon import SM1AckLogCtx
        from resources.siadc09d.sia_transport import CrcFormat
        daemon._ring_buffer.push_supervision_entry = MagicMock(return_value=True)

        ctx: SM1AckLogCtx = {
            "seq": 1,
            "elapsed_ms": 42.0,
            "crc_format": "hex",
            "raw_hex": None,
            "prev_strike": 0,
        }
        await daemon._log_sm1_supervision("ack", ctx)

        trace_payloads = [p for p in captured_payloads if p["type"] == "message_trace"]
        assert len(trace_payloads) >= 1  # message_trace emitted
        dialog = trace_payloads[0]["dialog"]
        assert dialog["dialog_type"] == "supervision"  # supervision dialog
        assert dialog["routine"] == 1  # routine ACK → routine=1

    @pytest.mark.asyncio
    async def test_message_trace_alarm(
        self, daemon: SIADaemon, captured_payloads: list[dict]
    ) -> None:
        """AC6/AC8: SM2 event log → message_trace with dialog.routine == 0.

        Expected:
        - message_trace payload emitted after _log_sm2_event
        - dialog.routine == 0 (non-routine, alarm event)
        - dialog.dialog_type == 'alarm'
        """
        from resources.siadc09d.daemon import SM2LogCtx
        daemon._ring_buffer.push_supervision_entry = MagicMock(return_value=True)
        daemon._event_sia_code = "BA"
        daemon._event_zone = "Salon"
        daemon._event_attempt_count = 1

        ctx = SM2LogCtx(
            zone="Salon",
            sia_code="BA",
            attempt=1,
            elapsed=0.12,
            state_change=True,
        )
        await daemon._log_sm2_event("confirmed", ctx)

        trace_payloads = [p for p in captured_payloads if p["type"] == "message_trace"]
        assert len(trace_payloads) >= 1  # message_trace emitted
        dialog = trace_payloads[0]["dialog"]
        assert dialog["dialog_type"] == "alarm"  # alarm dialog
        assert dialog["routine"] == 0  # alarm is non-routine
