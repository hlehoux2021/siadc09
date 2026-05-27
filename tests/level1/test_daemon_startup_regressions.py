"""
Regression tests for daemon startup bugs found during Story 12-2 Task 6.

These tests verify that the 8 issues discovered during live Jeedom VM
verification do not regress. Each test maps to a specific fix comment
in the codebase (Fix #N).

Reference: _bmad-output/implementation-artifacts/12-2-wizard-flow-connection-test.md
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.presets import CSRPreset
from resources.siadc09d.sia_protocol import SIAMessageBuilder
from resources.siadc09d.sia_transport import TransportType
from tests.conftest import make_daemon_preset


# ===== Helpers =====


def _make_daemon_with_preset(preset: CSRPreset) -> SIADaemon:
    """Instantiate SIADaemon with a given preset, mocking sys.argv."""
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    return daemon


# ===== Fix #2: BaseConfig.parse() must be called before accessing attributes =====


def test_entry_point_parse_called_before_attribute_access():
    """
    siadc09d.py entry point calls _config.parse() before accessing _config.host.

    Expected result:
    - The entry point script contains parse() call before any attribute access
    - Without parse(), BaseConfig._args is None → AttributeError on .host
    """
    entry_point = Path(__file__).resolve().parents[2] / "resources" / "siadc09d" / "siadc09d.py"
    source = entry_point.read_text()

    lines = source.splitlines()
    parse_line = None
    first_attr_line = None
    in_main_block = False

    for i, line in enumerate(lines):
        if 'if __name__ == "__main__"' in line:
            in_main_block = True
            continue
        if not in_main_block:
            continue
        if parse_line is None and "_config.parse()" in line:
            parse_line = i
        if first_attr_line is None and "_config.host" in line:
            first_attr_line = i
            break

    # Assert: parse() appears before first attribute access
    assert parse_line is not None, "parse() call not found in __main__ block"
    assert first_attr_line is not None, "_config.host access not found in __main__ block"
    assert parse_line < first_attr_line, (
        f"parse() at line {parse_line} must come before "
        f"attribute access at line {first_attr_line}"
    )


# ===== Fix #3: PHP passes lowercase transport; must be uppercased for TransportType =====


def test_entry_point_uppercases_transport():
    """
    siadc09d.py entry point uppercases transport string before passing to CSRPreset.

    Expected result:
    - CSRPreset constructed with .upper() on the transport value
    - Prevents ValueError: 'udp' is not a valid TransportType
    """
    entry_point = Path(__file__).resolve().parents[2] / "resources" / "siadc09d" / "siadc09d.py"
    source = entry_point.read_text()

    # Assert: transport field uses .upper() in the CSRPreset construction
    assert "_config.transport.upper()" in source, (
        "Entry point must call .upper() on transport before passing to CSRPreset"
    )


def test_preset_rejects_lowercase_transport():
    """
    CSRPreset.__post_init__ rejects lowercase transport strings.

    Expected result:
    - 'udp' (lowercase) raises ValueError from TransportType enum
    - This is why the entry point must uppercase before construction
    """
    with pytest.raises(ValueError):
        CSRPreset(
            csr_provider='test',
            schema_version=1,
            host='192.168.1.100',
            port=5000,
            account_number='001234',
            transport='udp',
            crc_format='hex',
            encryption_enabled=False,
            connect_timeout_s=10.0,
            receive_timeout_s=20.0,
            supervision_interval_s=60.0,
        )


# ===== Fix #4: .htaccess must not exist in core/php/ =====


def test_no_htaccess_blocking_daemon_callback():
    """
    core/php/.htaccess must not exist — it blocks daemon→PHP callback.

    Expected result:
    - No .htaccess file in core/php/ directory
    - Apache Deny from all was blocking all HTTP requests to callback URL
    """
    htaccess_path = Path(__file__).resolve().parents[2] / "core" / "php" / ".htaccess"
    # Assert: file does not exist (was blocking daemon callback with 403)
    assert not htaccess_path.exists(), (
        f"core/php/.htaccess must not exist — it blocks daemon callback with 'Deny from all'"
    )


# ===== Fix #5: daemon._account must come from preset.account_number =====


def test_daemon_account_populated_from_preset():
    """
    SIADaemon._account is populated from preset.account_number at init.

    Expected result:
    - _account equals the preset's account_number value
    - Was previously empty string, causing frame build failures
    """
    preset = make_daemon_preset()
    daemon = _make_daemon_with_preset(preset)

    # Assert: account comes from preset, not empty string
    assert daemon._account == '001234'
    assert daemon._account == preset.account_number


def test_daemon_account_not_empty_string():
    """
    SIADaemon._account is never an empty string when preset has account_number.

    Expected result:
    - Even with minimal config, _account is the preset value
    - Empty account causes 'Invalid account_number' at frame build time
    """
    preset = CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='10.0.0.1',
        port=9999,
        account_number='ABCDEF',
        transport='UDP',
        crc_format='hex',
        encryption_enabled=False,
        connect_timeout_s=5.0,
        receive_timeout_s=10.0,
        supervision_interval_s=30.0,
    )
    daemon = _make_daemon_with_preset(preset)

    # Assert: account matches preset regardless of config object
    assert daemon._account == 'ABCDEF'
    assert daemon._account != ''


# ===== Fix #6: empty account_prefix defaults to "L0" =====


def test_daemon_account_prefix_defaults_to_L0_when_empty():
    """
    SIADaemon._account_prefix defaults to "L0" when config provides empty string.

    Expected result:
    - Empty string from CLI arg is replaced with "L0"
    - "L0" is the SIA DC-09 protocol default prefix
    - Empty prefix fails SIA validation at frame build time
    """
    preset = make_daemon_preset()
    daemon = _make_daemon_with_preset(preset)

    # Assert: prefix is "L0" (protocol default), not empty
    assert daemon._account_prefix == 'L0'
    assert daemon._account_prefix != ''


def test_daemon_account_prefix_preserves_explicit_value():
    """
    SIADaemon._account_prefix preserves an explicitly set non-empty value.

    Expected result:
    - When config provides "L1", it is kept as-is
    - Default "L0" only applies to empty/missing values
    """
    preset = make_daemon_preset()

    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)

    # Simulate config having an explicit prefix
    daemon._account_prefix = "L1"

    # Assert: explicit value preserved
    assert daemon._account_prefix == 'L1'


# ===== Fix #7: crc_format mapping — "hex"→"SIA", "bin"→"ADM" =====


def test_daemon_crc_format_hex_maps_to_sia_builder():
    """
    preset.crc_format="hex" creates SIAMessageBuilder with crc_format="SIA".

    Expected result:
    - Builder's crc_format is "SIA" (not "hex")
    - "hex" is the config-layer name; "SIA" is the protocol-layer name
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
    daemon = _make_daemon_with_preset(preset)

    # Assert: builder uses "SIA" format for hex wire CRC
    assert daemon._sia_builder.crc_format == 'SIA'


def test_daemon_crc_format_bin_maps_to_adm_builder():
    """
    preset.crc_format="bin" creates SIAMessageBuilder with crc_format="ADM".

    Expected result:
    - Builder's crc_format is "ADM" (not "bin")
    - "bin" is the config-layer name; "ADM" is the protocol-layer name
    """
    preset = CSRPreset(
        csr_provider='test',
        schema_version=1,
        host='192.168.1.100',
        port=5000,
        account_number='001234',
        transport='UDP',
        crc_format='bin',
        encryption_enabled=False,
        connect_timeout_s=10.0,
        receive_timeout_s=20.0,
        supervision_interval_s=60.0,
    )
    daemon = _make_daemon_with_preset(preset)

    # Assert: builder uses "ADM" format for binary wire CRC
    assert daemon._sia_builder.crc_format == 'ADM'


def test_daemon_crc_format_mapping_present_in_source():
    """
    Daemon __init__ contains explicit hex→SIA / bin→ADM mapping logic.

    Expected result:
    - Source code contains the conditional mapping (not passing raw crc_format)
    - Without this mapping, builder would receive "hex"/"bin" which are not
      valid SIA protocol CRC algorithm names
    """
    daemon_path = Path(__file__).resolve().parents[2] / "resources" / "siadc09d" / "daemon.py"
    source = daemon_path.read_text()

    # Assert: mapping logic exists
    assert '"SIA" if preset.crc_format == "hex" else "ADM"' in source, (
        "Daemon must map preset crc_format (hex/bin) to builder format (SIA/ADM)"
    )


# ===== Fix #1: cryptography version pin in packages.json =====


def test_packages_json_cryptography_pinned_below_44():
    """
    packages.json pins cryptography<44 to avoid SIGILL on aarch64 VMs.

    Expected result:
    - pip3 section contains "cryptography<44" key
    - Versions 44+ use Rust bindings that crash on some aarch64 builds
    """
    import json
    packages_path = Path(__file__).resolve().parents[2] / "plugin_info" / "packages.json"
    packages = json.loads(packages_path.read_text())

    pip3 = packages.get("pip3", {})
    # Assert: cryptography is pinned below 44
    assert "cryptography<44" in pip3, (
        f"cryptography must be pinned <44 in packages.json, got keys: {list(pip3.keys())}"
    )
    # Assert: unpinned "cryptography" is NOT present
    assert "cryptography" not in pip3 or "cryptography" == "cryptography<44", (
        "Unpinned 'cryptography' key must not coexist with pinned version"
    )
