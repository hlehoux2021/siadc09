"""
Shared pytest fixtures and helpers for all tests.

Provides reusable fixtures for CSR simulator testing, frame construction helpers,
and encryption test utilities.
"""

import pytest
from datetime import datetime, timezone
from resources.siadc09d.csr_simulator import CSRSimulatorPreset
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_protocol import SIAMessageBuilder, _compute_crc_modbus
from resources.siadc09d.sia_crypto import SIACipher


def make_daemon_preset(transport: str = 'UDP') -> CSRPreset:
    """Create a minimal CSRPreset for daemon tests.

    Args:
        transport: 'UDP' or 'TCP' (string — CSRPreset converts to TransportType)
    """
    return CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport=transport,
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
        reconnect_delay_s=0.01,
    )


# ============================================================================
# Frame Builder Helper (Task 13.5)
# ============================================================================

def _build_frame(message_string: str, crc_format: str) -> bytes:
    """
    Build a valid SIA-formatted frame with proper CRC and delimiters.

    Args:
        message_string: Raw message string (e.g., '"ACK"0001R0L0#000001[]')
        crc_format: 'hex' or 'bin' for CRC encoding

    Returns:
        Complete frame bytes: LF + CRC + Length + Message + CR

    Raises:
        ValueError: If crc_format invalid or message cannot be encoded
    """
    if crc_format not in ('hex', 'bin'):
        raise ValueError(f"Invalid crc_format: '{crc_format}' (must be 'hex' or 'bin')")

    # Encode message to windows-1252
    message_bytes = message_string.encode('windows-1252')

    # Compute CRC using Story 1.1's algorithm
    crc_int = _compute_crc_modbus(message_bytes)

    # Format CRC and Length based on format
    if crc_format == 'hex':
        crc_bytes = f"{crc_int:04X}".encode('ascii')
        length_bytes = f"{len(message_bytes):04X}".encode('ascii')
    else:  # bin
        crc_bytes = crc_int.to_bytes(2, byteorder='little')
        length_bytes = f"{len(message_bytes):04X}".encode('ascii')

    # Build complete frame: LF + CRC + Length + Message + CR
    frame = b'\x0A' + crc_bytes + length_bytes + message_bytes + b'\x0D'
    return frame


# ============================================================================
# Preset Fixtures (Task 9)
# ============================================================================

@pytest.fixture
def preset_plain() -> CSRSimulatorPreset:
    """Preset configuration without encryption."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': None
    }


@pytest.fixture
def preset_encrypted() -> CSRSimulatorPreset:
    """Preset configuration with fixed AES-128 test key (reproducibility)."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': bytes.fromhex('0123456789ABCDEF0123456789ABCDEF')  # 128-bit fixed key
    }


@pytest.fixture
def preset_bin_crc() -> CSRSimulatorPreset:
    """Preset configuration with binary CRC format."""
    return {
        'crc_format': 'bin',
        'account_number': '000001',
        'encryption_key': None
    }


# ============================================================================
# Frame Fixtures (Task 9)
# ============================================================================

@pytest.fixture
def alarm_frame(preset_plain) -> bytes:
    """Valid alarm message frame (plaintext)."""
    return _build_frame('"ALARM"0001R0L0#000001[]', preset_plain['crc_format'])


@pytest.fixture
def null_supervision_frame(preset_plain) -> bytes:
    """Valid NULL supervision message frame (plaintext)."""
    return _build_frame('"NULL"0000R0L0#000001[]', preset_plain['crc_format'])


@pytest.fixture
def frame_malformed_crc(preset_plain) -> bytes:
    """Frame with incorrect CRC (malformed)."""
    # Build valid frame, then corrupt CRC
    message_string = '"ALARM"0001R0L0#000001[]'
    message_bytes = message_string.encode('windows-1252')

    # Use wrong CRC (0000 instead of computed)
    crc_bytes = b'0000'  # Intentionally wrong
    length_bytes = f"{len(message_bytes):04X}".encode('ascii')

    frame = b'\x0A' + crc_bytes + length_bytes + message_bytes + b'\x0D'
    return frame


@pytest.fixture
def frame_bad_delimiter(preset_plain) -> bytes:
    """Frame missing CR delimiter (0x0D)."""
    message_string = '"ALARM"0001R0L0#000001[]'
    message_bytes = message_string.encode('windows-1252')
    crc_int = _compute_crc_modbus(message_bytes)

    crc_bytes = f"{crc_int:04X}".encode('ascii')
    length_bytes = f"{len(message_bytes):04X}".encode('ascii')

    # Build frame WITHOUT CR (0x0D)
    frame = b'\x0A' + crc_bytes + length_bytes + message_bytes  # Missing b'\x0D'
    return frame


@pytest.fixture
def frame_truncated(preset_plain) -> bytes:
    """Frame cut off mid-message."""
    # Build valid frame then truncate it
    valid_frame = _build_frame('"ALARM"0001R0L0#000001[]', preset_plain['crc_format'])
    # Return only first half
    return valid_frame[:len(valid_frame) // 2]


# ============================================================================
# CSRSimulator Fixtures (Task 9)
# ============================================================================

@pytest.fixture
async def csr_simulator_instance(preset_plain):
    """
    Initialized CSRSimulator instance for testing (async fixture).

    Automatically starts and stops simulator for test scope.
    """
    from resources.siadc09d.csr_simulator import CSRSimulator

    simulator = CSRSimulator(
        udp_port=10001,
        tcp_port=5000,
        preset=preset_plain,
        response_delay_ms=0
    )

    # Start simulator
    await simulator.start()

    yield simulator

    # Cleanup: stop simulator
    await simulator.stop()


# ============================================================================
# Encryption Helpers (Task 13)
# ============================================================================

@pytest.fixture
def test_cipher(preset_encrypted) -> SIACipher:
    """Create a cipher instance with test key for roundtrip testing."""
    return SIACipher(preset_encrypted['encryption_key'])
