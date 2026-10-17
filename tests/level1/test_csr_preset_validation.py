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


# ===== Story 17.1: periodic-frame fields (supervision_format, RP) =====


def test_periodic_frame_defaults_match_previous_behaviour():
    """
    Story 17.1 AC3/AC9: a preset built without the new fields keeps today's behaviour.

    Expected result:
    - supervision_format defaults to "sia-dcs"
    - rp_enabled defaults to False
    - rp_interval_s defaults to 60.0
    """
    preset = _make_preset()
    # Assert: supervision frame format unchanged
    assert preset.supervision_format == "sia-dcs"
    # Assert: RP cyclic test off
    assert preset.rp_enabled is False
    # Assert: RP interval default
    assert preset.rp_interval_s == 60.0


@pytest.mark.parametrize("fmt", ["sia-dcs", "null", "none"])
def test_each_supervision_format_accepted(fmt):
    """
    Story 17.1 AC3: the three SupervisionFormat values are accepted.

    Scenario: RP is enabled so that "none" is a valid combination.

    Expected result:
    - the preset stores the given format
    """
    preset = _make_preset(supervision_format=fmt, rp_enabled=True)
    # Assert: format stored as given
    assert preset.supervision_format == fmt


def test_supervision_none_without_rp_rejected():
    """
    Story 17.1 AC7: "none" with RP off leaves no periodic frame at all.

    Expected result:
    - ValueError naming supervision_format
    """
    # Assert: no-periodic-frame combination refused
    with pytest.raises(ValueError, match="supervision_format"):
        _make_preset(supervision_format="none", rp_enabled=False)


def test_supervision_none_with_rp_accepted():
    """
    Story 17.1 AC7: "none" with RP on is the Ajax/Scutum profile combination.

    Expected result:
    - preset built, RP enabled
    """
    preset = _make_preset(supervision_format="none", rp_enabled=True, rp_interval_s=60.0)
    # Assert: RP carries the periodic frame
    assert preset.rp_enabled is True


@pytest.mark.parametrize("interval", [60.0, 86400.0])
def test_rp_interval_bounds_inclusive(interval):
    """
    Story 17.1 AC7: the RP interval bounds 60 and 86400 s are inclusive.

    Expected result:
    - preset built with the bound value
    """
    preset = _make_preset(rp_enabled=True, rp_interval_s=interval)
    # Assert: bound value accepted
    assert preset.rp_interval_s == interval


@pytest.mark.parametrize("interval", [59.0, 86401.0])
def test_rp_interval_out_of_range_rejected_when_enabled(interval):
    """
    Story 17.1 AC7: with RP on, an interval outside [60, 86400] is refused.

    Expected result:
    - ValueError naming rp_interval_s
    """
    # Assert: out-of-range interval refused
    with pytest.raises(ValueError, match="rp_interval_s"):
        _make_preset(rp_enabled=True, rp_interval_s=interval)


def test_rp_interval_out_of_range_ignored_when_disabled():
    """
    Story 17.1 AC7 (clarification approved 2026-10-17): a stored but unused
    rp_interval must not block the daemon.

    Expected result:
    - preset built with RP off and rp_interval_s=5
    """
    preset = _make_preset(rp_enabled=False, rp_interval_s=5.0)
    # Assert: unused interval accepted as-is
    assert preset.rp_interval_s == 5.0


def test_unknown_supervision_format_rejected():
    """
    Story 17.1 AC7: a format outside SupervisionFormat is refused.

    Expected result:
    - ValueError naming supervision_format
    """
    # Assert: unknown format refused
    with pytest.raises(ValueError, match="supervision_format"):
        _make_preset(supervision_format="keepalive")


def test_crc_format_bin_rejected():
    """
    Story 17.1 AC8: crc_format "bin" was removed from the sender side.

    Expected result:
    - ValueError naming crc_format
    """
    # Assert: bin refused on the sender side
    with pytest.raises(ValueError, match="crc_format"):
        _make_preset(crc_format="bin")
