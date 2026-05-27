"""Level 3 E2E test fixtures for SIA DC-09 supervision integration tests.

Provides CSR simulator lifecycle fixtures, E2E daemon factory, port helpers,
and the poll-with-timeout _wait_for helper for CI-safe state assertions.

All Level 3 tests use real transport (UDP/TCP) against a real CSRSimulator
on localhost. Only send_to_jeedom is mocked (no PHP required).
"""
import asyncio
import socket
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from resources.siadc09d.csr_simulator import CSRSimulator
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.presets import CSRPreset

# ===== ACCOUNT CONSTANT (shared between daemon preset and simulator preset) =====

E2E_ACCOUNT = "001234"
E2E_ENCRYPTION_KEY = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")


# ===== PORT HELPERS =====


def _find_free_udp_port() -> int:
    """Return a free ephemeral UDP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_free_tcp_port() -> int:
    """Return a free ephemeral TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ===== POLL-WITH-TIMEOUT HELPER =====


async def _wait_for(predicate, *, timeout: float = 10.0, poll_interval: float = 0.02) -> None:
    """Poll predicate until True or timeout expires.

    Args:
        predicate: Zero-arg callable returning bool.
        timeout: Maximum wait in seconds (default 10s — 5× worst-case cycle).
        poll_interval: Sleep between polls in seconds (default 20ms).

    Raises:
        TimeoutError: If predicate not satisfied within timeout.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise TimeoutError(f"Condition not met within {timeout}s")
        await asyncio.sleep(poll_interval)


# ===== CSR SIMULATOR FIXTURE =====


@pytest_asyncio.fixture
async def csr_sim():
    """Start CSRSimulator on ephemeral UDP+TCP ports. Yield (sim, udp_port, tcp_port).

    Lifecycle:
    - Allocates free ports before starting (no TIME_WAIT conflicts)
    - Starts simulator with start()
    - Launches _handle_udp() as a tracked asyncio task
    - On teardown: cancels UDP task, stops simulator

    Instrumentation:
    - sim.tcp_connect_count: incremented by patched _handle_tcp_client (AC2)
    """
    udp_port = _find_free_udp_port()
    tcp_port = _find_free_tcp_port()

    sim_preset = {
        "crc_format": "hex",
        "account_number": E2E_ACCOUNT,
        "encryption_key": None,
    }

    sim = CSRSimulator(
        udp_port=udp_port,
        tcp_port=tcp_port,
        preset=sim_preset,
        response_delay_ms=0,
    )

    # Instrument: TCP connection counter for AC2
    sim.tcp_connect_count = 0
    original_handle_tcp = sim._handle_tcp_client

    async def _counted_handle_tcp(reader, writer):
        sim.tcp_connect_count += 1
        await original_handle_tcp(reader, writer)

    sim._handle_tcp_client = _counted_handle_tcp

    await sim.start()

    # UDP recv loop must be started explicitly (not started by sim.start())
    udp_task = asyncio.create_task(sim._handle_udp(), name="sim_udp_recv")

    yield sim, udp_port, tcp_port

    # Teardown: cancel UDP task first, then stop simulator
    udp_task.cancel()
    with suppress(asyncio.CancelledError):
        await udp_task
    await sim.stop()


# ===== E2E DAEMON FACTORY =====


def _make_e2e_preset(
    transport: str,
    host: str,
    udp_port: int,
    tcp_port: int,
    supervision_interval_s: float = 1.0,
    encryption_enabled: bool = False,
) -> CSRPreset:
    """Build a CSRPreset for E2E testing pointing at the given simulator ports.

    Args:
        transport: "UDP" or "TCP"
        host: Simulator host (127.0.0.1)
        udp_port: Ephemeral UDP port from csr_sim fixture
        tcp_port: Ephemeral TCP port from csr_sim fixture
        supervision_interval_s: Supervision interval (default 1.0s)
        encryption_enabled: Whether to enable AES-128-CBC encryption

    Returns:
        CSRPreset configured for E2E testing.
    """
    port = udp_port if transport == "UDP" else tcp_port
    return CSRPreset(
        csr_provider="test",
        schema_version=1,
        host=host,
        port=port,
        account_number=E2E_ACCOUNT,
        transport=transport,
        crc_format="hex",
        encryption_enabled=encryption_enabled,
        connect_timeout_s=0.5,
        receive_timeout_s=0.5,
        supervision_interval_s=supervision_interval_s,
        reconnect_delay_s=0.05,
    )


def make_e2e_daemon(
    transport: str,
    udp_port: int,
    tcp_port: int,
    supervision_interval_s: float = 1.0,
    encryption_enabled: bool = False,
) -> SIADaemon:
    """Create an E2E SIADaemon preset pointing at the given simulator ports.

    Wires up:
    - send_to_jeedom as AsyncMock (no PHP required)
    - _account, _account_prefix, _receiver_prefix from preset

    Returns:
        SIADaemon instance (NOT started — caller calls await daemon.on_start()).
    """
    import sys
    from unittest.mock import patch

    preset = _make_e2e_preset(
        transport=transport,
        host="127.0.0.1",
        udp_port=udp_port,
        tcp_port=tcp_port,
        supervision_interval_s=supervision_interval_s,
        encryption_enabled=encryption_enabled,
    )

    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)

    # Wire account fields (not set from preset automatically)
    daemon._account = E2E_ACCOUNT
    daemon._account_prefix = "L0"
    daemon._receiver_prefix = ""

    # Wire encryption key if enabled
    if encryption_enabled:
        daemon._encryption_key = E2E_ENCRYPTION_KEY
        from resources.siadc09d.sia_protocol import SIAMessageBuilder
        daemon._sia_builder = SIAMessageBuilder(crc_format=preset.crc_format)
        daemon._sia_builder._encryption_key = E2E_ENCRYPTION_KEY

    # Mock send_to_jeedom (no PHP)
    daemon.send_to_jeedom = AsyncMock()

    return daemon


# ===== SMOKE TEST HELPER (Task 1.4) =====


async def _sim_udp_roundtrip(udp_port: int, timeout: float = 2.0) -> bool:
    """Send a raw NULL supervision frame to simulator and wait for ACK response.

    Used in Task 1.4 smoke test to verify UDP handle_udp() task is running.

    Returns:
        True if ACK received, False on timeout.
    """
    from resources.siadc09d.sia_protocol import SIAMessageBuilder

    builder = SIAMessageBuilder(crc_format="SIA")
    frame = builder.make_supervision_message(
        account_number=E2E_ACCOUNT,
        account_prefix="L0",
    )

    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)  # blocking with timeout (not setblocking(False))

    try:
        sock.sendto(frame, ("127.0.0.1", udp_port))

        try:
            data = await loop.run_in_executor(None, lambda: sock.recv(1024))
            return len(data) > 0
        except (OSError, TimeoutError):
            return False
    finally:
        sock.close()
