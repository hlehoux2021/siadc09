"""
Level 2.5 IPC contract tests for Epic 8 wizard config → daemon integration.

Validates that wizard configuration values (from PHP's deamon_start() CLI args
passed via CSRPreset) correctly initialize the daemon and produce proper initial
IPC callbacks. Uses mock send_to_jeedom to capture emitted payloads.

Key contract: when the daemon starts with wizard-configured values, it must:
1. Emit an initial info_update with supervision_state=1 (INITIALIZING)
2. NOT include event_state/event_label in the initial push (retained across restarts)
3. Use preset values for transport creation (host, port, crc_format)

Reference: docs/design/wizard-design.md
Reference: docs/design/daemon-design.md § on_start()
Reference: _bmad-output/implementation-artifacts/8-1-wizard-steps-1-2-csr-preset-selection.md
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SM1State, SM2State, SIADaemon
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_transport import TransportType


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_wizard_preset(
    transport: str = "UDP",
    host: str = "192.168.1.200",
    port: int = 5000,
    account: str = "ABC123",
    crc_format: str = "hex",
    encryption_enabled: bool = False,
    supervision_interval_s: float = 60.0,
) -> CSRPreset:
    """Create a CSRPreset mimicking wizard config from PHP deamon_start()."""
    return CSRPreset(
        csr_provider="ima_protect",
        schema_version=1,
        host=host,
        port=port,
        account_number=account,
        transport=transport,
        crc_format=crc_format,
        encryption_enabled=encryption_enabled,
        connect_timeout_s=5.0,
        receive_timeout_s=10.0,
        supervision_interval_s=supervision_interval_s,
        reconnect_delay_s=5.0,
    )


@pytest.fixture
def wizard_preset() -> CSRPreset:
    """Default wizard preset (IMA Protect defaults)."""
    return _make_wizard_preset()


@pytest.fixture
def daemon_with_capture(wizard_preset: CSRPreset) -> tuple[SIADaemon, list[dict]]:
    """Create SIADaemon with captured payloads fixture.

    Returns (daemon, captured_payloads) tuple. Mocks send_to_jeedom to
    capture all emitted IPC payloads.
    """
    with patch("sys.argv", ["test"]):
        d = SIADaemon(preset=wizard_preset)
    d._account = "ABC123"
    d._receiver_prefix = ""
    d._account_prefix = "L0"

    payloads: list[dict] = []

    async def _capture(payload: dict) -> None:
        payloads.append(payload)

    d.send_to_jeedom = AsyncMock(side_effect=_capture)
    return d, payloads


# ── on_start initial IPC callback contract ───────────────────────────────────


class TestOnStartInitialCallback:
    """Validates the initial info_update emitted during on_start()."""

    @pytest.mark.asyncio
    async def test_on_start_emits_initializing_info_update(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        on_start() emits info_update with supervision_state=1 (INITIALIZING)
        before launching background tasks.

        Expected result:
        - First payload type is 'info_update'
        - supervision_state == 1 (impaired — INITIALIZING)
        - supervision_label is a non-empty string
        """
        daemon, payloads = daemon_with_capture

        transport_cls = "SIAUDPTransport"
        with patch(f"resources.siadc09d.daemon.{transport_cls}") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: at least one payload emitted
            assert len(payloads) >= 1
            first = payloads[0]
            # Assert: first payload is info_update
            assert first["type"] == "info_update"
            # Assert: supervision_state is 1 (INITIALIZING)
            assert first["supervision_state"] == 1
            # Assert: supervision_label is non-empty string
            assert isinstance(first["supervision_label"], str)
            assert len(first["supervision_label"]) > 0
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_on_start_does_not_include_event_state(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        on_start() initial info_update must NOT include event_state/event_label.
        These are retained across daemon restarts — the initial push only updates
        supervision state.

        Expected result:
        - First payload does NOT contain 'event_state' key
        - First payload does NOT contain 'event_label' key
        """
        daemon, payloads = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            first = payloads[0]
            # Assert: event_state NOT in initial push (retained across restarts)
            assert "event_state" not in first
            # Assert: event_label NOT in initial push
            assert "event_label" not in first
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_on_start_sm1_state_initializing(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        After on_start() completes, SM1 must be INITIALIZING (first supervision
        not yet sent). The daemon waits for the first ACK to transition to HEALTHY.

        Expected result:
        - daemon._sm1_state == SM1State.INITIALIZING after on_start()
        """
        daemon, _ = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: SM1 is INITIALIZING
            assert daemon._sm1_state == SM1State.INITIALIZING
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_on_start_sm2_state_idle(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        After on_start(), SM2 must be IDLE (no alarm events queued yet).

        Expected result:
        - daemon._sm2_state == SM2State.IDLE
        """
        daemon, _ = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: SM2 is IDLE (no alarm in flight)
            assert daemon._sm2_state == SM2State.IDLE
        finally:
            await daemon.on_stop()


# ── Preset values → transport creation ───────────────────────────────────────


class TestPresetToTransport:
    """Validates that wizard preset values are correctly passed to transport."""

    @pytest.mark.asyncio
    async def test_udp_preset_creates_udp_transport(self) -> None:
        """
        Wizard preset with transport=UDP creates SIAUDPTransport.

        Expected result:
        - SIAUDPTransport instantiated with preset's host, port, crc_format
        """
        preset = _make_wizard_preset(transport="UDP", host="10.0.0.1", port=9876)
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"
        daemon.send_to_jeedom = AsyncMock()

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockUDP:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockUDP.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: SIAUDPTransport instantiated
            assert MockUDP.called
            call_args = MockUDP.call_args
            # Assert: preset host passed to transport
            assert call_args[0][0] == "10.0.0.1" or call_args[1].get("host") == "10.0.0.1"
            # Assert: preset port passed to transport
            assert 9876 in call_args[0] or call_args[1].get("port") == 9876
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_tcp_preset_creates_tcp_transport(self) -> None:
        """
        Wizard preset with transport=TCP creates SIATCPTransport.

        Expected result:
        - SIATCPTransport instantiated (not SIAUDPTransport)
        """
        preset = _make_wizard_preset(transport="TCP")
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"
        daemon.send_to_jeedom = AsyncMock()

        with patch("resources.siadc09d.daemon.SIATCPTransport") as MockTCP:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockTCP.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: SIATCPTransport instantiated
            assert MockTCP.called
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_preset_crc_format_passed_to_transport(self) -> None:
        """
        Wizard preset crc_format is passed to transport constructor.
        A mismatch would cause CRC validation failures on CSR responses.

        Expected result:
        - Transport created with crc_format from preset
        """
        preset = _make_wizard_preset(crc_format="bin")
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"
        daemon.send_to_jeedom = AsyncMock()

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockUDP:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockUDP.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: crc_format from preset passed to transport
            call_kwargs = MockUDP.call_args[1] if MockUDP.call_args[1] else {}
            call_args = MockUDP.call_args[0] if MockUDP.call_args[0] else ()
            assert "bin" in str(call_args) + str(call_kwargs)
        finally:
            await daemon.on_stop()


# ── on_stop terminal IPC callback contract ───────────────────────────────────


class TestOnStopTerminalCallback:
    """Validates the terminal info_update emitted during on_stop()."""

    @pytest.mark.asyncio
    async def test_on_stop_emits_stopped_info_update(self) -> None:
        """
        on_stop() emits info_update with supervision_state=0 (STOPPED).
        This is best-effort — failure does not prevent shutdown.

        Expected result:
        - A payload with supervision_state=0 is emitted during on_stop()
        """
        preset = _make_wizard_preset()
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"

        payloads: list[dict] = []

        async def _capture(payload: dict) -> None:
            payloads.append(payload)

        daemon.send_to_jeedom = AsyncMock(side_effect=_capture)

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        # Clear payloads from on_start, only check on_stop
        payloads.clear()
        await daemon.on_stop()

        # Assert: on_stop emitted at least one payload
        assert len(payloads) >= 1
        # Assert: supervision_state=0 (STOPPED) present in one of the payloads
        stopped_payloads = [
            p for p in payloads
            if p.get("type") == "info_update" and p.get("supervision_state") == 0
        ]
        assert len(stopped_payloads) >= 1

    @pytest.mark.asyncio
    async def test_on_stop_does_not_include_event_state(self) -> None:
        """
        on_stop() terminal info_update must NOT include event_state/event_label.
        Event state is retained across restarts.

        Expected result:
        - Terminal info_update payload does NOT contain 'event_state'
        """
        preset = _make_wizard_preset()
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"

        payloads: list[dict] = []

        async def _capture(payload: dict) -> None:
            payloads.append(payload)

        daemon.send_to_jeedom = AsyncMock(side_effect=_capture)

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        payloads.clear()
        await daemon.on_stop()

        stopped_payloads = [
            p for p in payloads
            if p.get("type") == "info_update" and p.get("supervision_state") == 0
        ]
        # Assert: terminal payload does not include event_state
        if stopped_payloads:
            assert "event_state" not in stopped_payloads[0]


# ── First supervision → HEALTHY transition IPC ───────────────────────────────


class TestFirstSupervisionIPC:
    """Validates IPC emitted on first successful supervision (INITIALIZING → HEALTHY)."""

    @pytest.mark.asyncio
    async def test_first_ack_emits_healthy_info_update(self) -> None:
        """
        After on_start(), the first supervision ACK transitions to HEALTHY and
        emits info_update with supervision_state=2.

        Expected result:
        - After _send_supervision ACK, info_update with supervision_state=2 emitted
        """
        preset = _make_wizard_preset()
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"
        daemon._receiver_prefix = ""
        daemon._account_prefix = "L0"
        daemon._log_sm1_supervision = AsyncMock()

        payloads: list[dict] = []

        async def _capture(payload: dict) -> None:
            payloads.append(payload)

        daemon.send_to_jeedom = AsyncMock(side_effect=_capture)

        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(
            return_value={"status": "ack", "raw_nak": None}
        )
        daemon._sia_transport = mock_t
        daemon._sm1_state = SM1State.INITIALIZING

        # Clear any prior payloads
        payloads.clear()

        await daemon._send_supervision()

        # Assert: transitioned to HEALTHY
        assert daemon._sm1_state == SM1State.HEALTHY
        # Assert: info_update with supervision_state=2 emitted
        healthy_updates = [
            p for p in payloads
            if p.get("type") == "info_update" and p.get("supervision_state") == 2
        ]
        assert len(healthy_updates) >= 1

    @pytest.mark.asyncio
    async def test_first_timeout_emits_degraded_info_update(self) -> None:
        """
        After on_start(), if the first supervision times out, daemon transitions
        to DEGRADED and emits info_update with supervision_state=1.

        Expected result:
        - After _send_supervision timeout, supervision_state=1 in info_update
        - SM1 state is DEGRADED
        """
        preset = _make_wizard_preset()
        with patch("sys.argv", ["test"]):
            daemon = SIADaemon(preset=preset)
        daemon._account = "ABC123"
        daemon._receiver_prefix = ""
        daemon._account_prefix = "L0"
        daemon._log_sm1_supervision = AsyncMock()

        payloads: list[dict] = []

        async def _capture(payload: dict) -> None:
            payloads.append(payload)

        daemon.send_to_jeedom = AsyncMock(side_effect=_capture)

        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(
            return_value={"status": "timeout", "raw_nak": None}
        )
        daemon._sia_transport = mock_t
        daemon._sm1_state = SM1State.INITIALIZING

        payloads.clear()
        await daemon._send_supervision()

        # Assert: SM1 transitioned to DEGRADED
        assert daemon._sm1_state == SM1State.DEGRADED
        # Assert: info_update with supervision_state=1 (impaired) emitted
        impaired_updates = [
            p for p in payloads
            if p.get("type") == "info_update" and p.get("supervision_state") == 1
        ]
        assert len(impaired_updates) >= 1


# ── Wizard config key validation in daemon ───────────────────────────────────


class TestWizardConfigPresetMapping:
    """Validates wizard config keys are correctly stored in CSRPreset → daemon."""

    def test_preset_host_from_wizard(self) -> None:
        """
        Wizard step 1 csr_ip → CSRPreset.host → used in transport creation.

        Expected result:
        - CSRPreset.host matches the configured value
        """
        preset = _make_wizard_preset(host="10.20.30.40")
        # Assert: host stored in preset
        assert preset.host == "10.20.30.40"

    def test_preset_port_from_wizard(self) -> None:
        """
        Wizard step 1 csr_port → CSRPreset.port → used in transport creation.

        Expected result:
        - CSRPreset.port matches the configured value (integer)
        """
        preset = _make_wizard_preset(port=9876)
        # Assert: port stored as integer in preset
        assert preset.port == 9876

    def test_preset_transport_from_wizard(self) -> None:
        """
        Wizard step 1 transport → CSRPreset.transport → selects UDP/TCP class.

        Expected result:
        - CSRPreset.transport is TransportType.UDP for "UDP" input
        - CSRPreset.transport is TransportType.TCP for "TCP" input
        """
        preset_udp = _make_wizard_preset(transport="UDP")
        preset_tcp = _make_wizard_preset(transport="TCP")
        # Assert: UDP string maps to TransportType.UDP
        assert preset_udp.transport == TransportType.UDP
        # Assert: TCP string maps to TransportType.TCP
        assert preset_tcp.transport == TransportType.TCP

    def test_preset_account_from_wizard(self) -> None:
        """
        Wizard step 1 account_number → CSRPreset.account_number → used in frame building.

        Expected result:
        - CSRPreset.account_number matches configured value
        """
        preset = _make_wizard_preset(account="DEADBEEF")
        # Assert: account stored in preset
        assert preset.account_number == "DEADBEEF"

    def test_preset_crc_format_from_wizard(self) -> None:
        """
        Wizard step 1 crc_format → CSRPreset.crc_format → determines CRC algorithm.

        Expected result:
        - CSRPreset.crc_format matches configured value
        """
        preset = _make_wizard_preset(crc_format="bin")
        # Assert: crc_format stored in preset
        assert preset.crc_format == "bin"

    def test_preset_supervision_interval_from_wizard(self) -> None:
        """
        Wizard supervision_interval → CSRPreset.supervision_interval_s → loop timing.

        Expected result:
        - CSRPreset.supervision_interval_s matches configured value
        """
        preset = _make_wizard_preset(supervision_interval_s=120.0)
        # Assert: interval stored in preset
        assert preset.supervision_interval_s == 120.0


# ── IPC payload contract for wizard startup sequence ─────────────────────────


class TestWizardStartupPayloadContract:
    """Validates IPC payload shape contract during wizard-driven daemon startup."""

    @pytest.mark.asyncio
    async def test_initial_payload_no_boolean_values(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        All IPC payloads emitted during startup must not contain Python bool values.
        PHP's json_decode treats true/false differently from 1/0.

        Expected result:
        - No field value is of type bool in any emitted payload
        """
        daemon, payloads = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: at least one payload was emitted
            assert len(payloads) >= 1
            for i, payload in enumerate(payloads):
                for key, value in payload.items():
                    # Assert: no boolean values in payload
                    assert not isinstance(value, bool), (
                        f"Payload {i} field '{key}' is bool ({value}) — "
                        "must use int 0/1 for IPC"
                    )
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_initial_payload_has_type_field(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        All IPC payloads emitted during startup must have a 'type' field.
        PHP routing switch uses this field as the discriminator.

        Expected result:
        - Every emitted payload has a 'type' key
        - 'type' value is a non-empty string
        """
        daemon, payloads = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            # Assert: all payloads have type field
            for i, payload in enumerate(payloads):
                assert "type" in payload, f"Payload {i} missing 'type' field"
                assert isinstance(payload["type"], str), (
                    f"Payload {i} 'type' must be str"
                )
                assert len(payload["type"]) > 0, (
                    f"Payload {i} 'type' must be non-empty"
                )
        finally:
            await daemon.on_stop()

    @pytest.mark.asyncio
    async def test_supervision_state_is_integer(
        self, daemon_with_capture: tuple[SIADaemon, list[dict]]
    ) -> None:
        """
        supervision_state must be an integer (0, 1, or 2), never a string or bool.
        PHP checkAndUpdateCmd() casts to int — sending a string "1" would work
        but violates the IPC contract.

        Expected result:
        - supervision_state value is an int in range [0, 2]
        """
        daemon, payloads = daemon_with_capture

        with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
            mock_t = MagicMock()
            mock_t.start = AsyncMock()
            mock_t.close = AsyncMock()
            mock_t.send_frame = AsyncMock(
                return_value={"status": "ack", "raw_nak": None}
            )
            MockT.return_value = mock_t
            await daemon.on_start()

        try:
            info_updates = [p for p in payloads if p.get("type") == "info_update"]
            # Assert: at least one info_update emitted
            assert len(info_updates) >= 1
            for p in info_updates:
                if "supervision_state" in p:
                    # Assert: supervision_state is int
                    assert isinstance(p["supervision_state"], int)
                    # Assert: in valid range
                    assert p["supervision_state"] in (0, 1, 2)
        finally:
            await daemon.on_stop()
