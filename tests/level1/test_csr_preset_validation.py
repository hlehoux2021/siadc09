"""
CSRPreset validation tests (QA Round 2).

Tests __post_init__() transport string→enum conversion with invalid inputs.
Flagged as MEDIUM gap — bad transport strings not rejected.

Reference: resources/siadc09d/presets.py::CSRPreset
"""

import pytest
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_transport import TransportType


def _make_preset(**overrides) -> CSRPreset:
    """Build CSRPreset with defaults, overriding specified fields."""
    defaults = dict(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='UDP',
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
        reconnect_delay_s=5.0,
    )
    defaults.update(overrides)
    return CSRPreset(**defaults)


# ===== Valid transport strings =====


def test_transport_udp_string_converted():
    """
    transport='UDP' is converted to TransportType.UDP in __post_init__.

    Expected result:
    - preset.transport is TransportType.UDP (not string 'UDP')
    """
    preset = _make_preset(transport='UDP')
    # Assert: converted to enum
    assert preset.transport is TransportType.UDP
    assert isinstance(preset.transport, TransportType)


def test_transport_tcp_string_converted():
    """
    transport='TCP' is converted to TransportType.TCP in __post_init__.

    Expected result:
    - preset.transport is TransportType.TCP
    """
    preset = _make_preset(transport='TCP')
    # Assert: converted to enum
    assert preset.transport is TransportType.TCP


def test_transport_enum_passthrough():
    """
    transport=TransportType.UDP passes through without conversion.

    Expected result:
    - If already an enum, __post_init__ doesn't re-convert
    """
    preset = _make_preset(transport=TransportType.UDP)
    # Assert: stays as enum
    assert preset.transport is TransportType.UDP


# ===== Invalid transport strings =====


@pytest.mark.parametrize("bad_transport", [
    "WEBSOCKET",
    "MQTT",
    "HTTP",
    "INVALID",
    "",
    "udp",
    "tcp",
    "Udp",
    "Tcp",
])
def test_invalid_transport_string_raises(bad_transport):
    """
    Invalid transport strings raise ValueError from TransportType(value).

    Expected result:
    - ValueError raised for each invalid transport string
    - TransportType enum only accepts 'UDP' and 'TCP' (case-sensitive)
    """
    with pytest.raises(ValueError):
        _make_preset(transport=bad_transport)


def test_none_transport_raises():
    """
    transport=None raises error (not a valid enum value).

    Expected result:
    - ValueError or TypeError raised
    """
    with pytest.raises((ValueError, TypeError)):
        _make_preset(transport=None)


def test_int_transport_raises():
    """
    transport=0 (integer) raises error.

    Expected result:
    - ValueError raised (int is not a valid TransportType value)
    """
    with pytest.raises(ValueError):
        _make_preset(transport=0)


# ===== Frozen dataclass immutability =====


def test_preset_is_frozen():
    """
    CSRPreset is frozen — fields cannot be modified after creation.

    Expected result:
    - Assigning to any field raises FrozenInstanceError (dataclasses.FrozenInstanceError)
    """
    preset = _make_preset()
    with pytest.raises(AttributeError):
        preset.host = '10.0.0.1'


def test_preset_reconnect_delay_default():
    """
    reconnect_delay_s defaults to 30.0 if not specified (story 7-2 AC20 — base of the
    growing backoff schedule, was 5.0).

    Expected result:
    - Default value is 30.0 (from dataclass field default)
    """
    preset = CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='UDP',
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
    )
    # Assert: default value applied
    assert preset.reconnect_delay_s == 30.0


def test_preset_reconnect_max_attempts_default():
    """
    reconnect_max_attempts defaults to 6 if not specified (story 7-2 AC20 — was the dead
    TCP_RECONNECT_MAX_ATTEMPTS=3 module constant).

    Expected result:
    - Default value is 6 (from dataclass field default)
    """
    preset = CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='UDP',
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
    )
    # Assert: default value applied
    assert preset.reconnect_max_attempts == 6


@pytest.mark.parametrize("bad_max_attempts", [0, -1])
def test_reconnect_max_attempts_below_one_raises(bad_max_attempts):
    """
    reconnect_max_attempts < 1 raises ValueError (story 7-2 code-review patch).
    A value of 0 would silently skip the reconnect loop entirely with no probe
    and no warning — fail fast instead, mirroring the transport validation precedent.

    Expected result:
    - ValueError raised for 0 and negative values
    """
    with pytest.raises(ValueError):
        _make_preset(reconnect_max_attempts=bad_max_attempts)


def test_reconnect_delay_s_negative_raises():
    """
    reconnect_delay_s < 0 raises ValueError (story 7-2 code-review patch).
    A negative delay would be passed straight into asyncio.sleep(), which
    raises at runtime with a confusing error deep in the reconnect loop.

    Expected result:
    - ValueError raised for a negative reconnect_delay_s
    """
    with pytest.raises(ValueError):
        _make_preset(reconnect_delay_s=-1.0)
