"""
csr_presets.json structure validation tests for Story 8-2.

Validates that the presets JSON file is well-formed and all required fields
are present for each preset. These tests fail if a field is renamed, removed,
or if csr_presets.json is corrupted — no Jeedom instance required.

Reference: resources/siadc09d/csr_presets.json
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""

import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PRESETS_FILE = _PROJECT_ROOT / "resources/siadc09d/csr_presets.json"

_REQUIRED_PRESET_FIELDS = [
    "id",
    "label",
    "csr_ip",
    "csr_port",
    "transport",
    "crc_format",
    "encryption_enabled",
    "supervision_interval",
    "retry_count",
    "reconnect_delay",
]

_VALID_TRANSPORTS = {"udp", "tcp"}
_VALID_CRC_FORMATS = {"hex", "bin"}


@pytest.fixture(scope="module")
def presets_data() -> dict:
    return json.loads(_PRESETS_FILE.read_text(encoding="utf-8"))


def test_presets_file_exists() -> None:
    """
    csr_presets.json exists at the expected path.

    Expected result:
    - File is present at resources/siadc09d/csr_presets.json
    """
    # Assert: presets file is present
    assert _PRESETS_FILE.exists(), f"csr_presets.json not found at {_PRESETS_FILE}"


def test_presets_json_valid(presets_data: dict) -> None:
    """
    csr_presets.json is valid JSON with a top-level 'presets' array.

    Expected result:
    - File parses without error
    - Top-level 'presets' key is a non-empty list
    """
    # Assert: top-level structure is correct
    assert "presets" in presets_data, "csr_presets.json must have a 'presets' key"
    assert isinstance(presets_data["presets"], list), "'presets' must be a list"
    assert len(presets_data["presets"]) > 0, "'presets' list must not be empty"


def test_ima_protect_preset_exists(presets_data: dict) -> None:
    """
    IMA Protect preset ('ima_protect') is present in the presets list.

    Expected result:
    - At least one preset has id == "ima_protect"
    """
    ids = [p.get("id") for p in presets_data["presets"]]
    # Assert: ima_protect preset is defined
    assert "ima_protect" in ids, "IMA Protect preset ('ima_protect') must be in csr_presets.json"


@pytest.mark.parametrize("field", _REQUIRED_PRESET_FIELDS)
def test_ima_protect_has_required_field(presets_data: dict, field: str) -> None:
    """
    IMA Protect preset contains all required fields as defined in wizard-design.md.

    Expected result:
    - Each required field is present in the ima_protect preset
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None, "ima_protect preset not found"
    # Assert: required field is present in preset
    assert field in preset, f"ima_protect preset is missing required field '{field}'"


def test_ima_protect_crc_format_valid(presets_data: dict) -> None:
    """
    IMA Protect preset has a valid crc_format value ("hex" or "bin").

    Expected result:
    - crc_format is one of the two valid values defined in daemon-design.md
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    # Assert: crc_format is a valid value
    assert preset["crc_format"] in _VALID_CRC_FORMATS, (
        f"ima_protect.crc_format must be one of {_VALID_CRC_FORMATS}, "
        f"got '{preset.get('crc_format')}'"
    )


def test_ima_protect_transport_valid(presets_data: dict) -> None:
    """
    IMA Protect preset has a valid transport value ("udp" or "tcp").

    Expected result:
    - transport is one of the two valid values
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    # Assert: transport is a valid value
    assert preset["transport"] in _VALID_TRANSPORTS, (
        f"ima_protect.transport must be one of {_VALID_TRANSPORTS}, "
        f"got '{preset.get('transport')}'"
    )


def test_ima_protect_csr_port_is_int(presets_data: dict) -> None:
    """
    IMA Protect preset csr_port must be an integer, not a string.
    run_connection_test() calls int(preset.get("csr_port", 0)) — a string "5000"
    is accepted by that code, but the zero-guard (not port) would fail if the
    field is accidentally set to "0" or an empty string.

    Expected result:
    - csr_port is of type int
    - csr_port is in the valid port range 1–65535
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    port = preset.get("csr_port")
    # Assert: port is stored as integer, not string
    assert isinstance(port, int), f"ima_protect.csr_port must be int, got {type(port).__name__}"
    # Assert: port is in valid range
    assert 1 <= port <= 65535, f"ima_protect.csr_port={port} is outside valid range 1–65535"


def test_ima_protect_supervision_interval_is_positive_int(presets_data: dict) -> None:
    """
    IMA Protect preset supervision_interval must be a positive integer (seconds).
    Zero or negative values would disable supervision entirely.

    Expected result:
    - supervision_interval is an int
    - supervision_interval is > 0
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    interval = preset.get("supervision_interval")
    # Assert: stored as integer
    assert isinstance(interval, int), (
        f"ima_protect.supervision_interval must be int, got {type(interval).__name__}"
    )
    # Assert: positive value — zero disables supervision
    assert interval > 0, (
        f"ima_protect.supervision_interval={interval} must be > 0"
    )


def test_ima_protect_retry_count_is_non_negative_int(presets_data: dict) -> None:
    """
    IMA Protect preset retry_count must be a non-negative integer.
    Negative values would be nonsensical; non-int would break int() conversion.

    Expected result:
    - retry_count is an int
    - retry_count is >= 0
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    retries = preset.get("retry_count")
    # Assert: stored as integer
    assert isinstance(retries, int), (
        f"ima_protect.retry_count must be int, got {type(retries).__name__}"
    )
    # Assert: non-negative
    assert retries >= 0, f"ima_protect.retry_count={retries} must be >= 0"


def test_ima_protect_reconnect_delay_is_non_negative_int(presets_data: dict) -> None:
    """
    IMA Protect preset reconnect_delay must be a non-negative integer (story 7-2 AC20).
    Negative values would be nonsensical; non-int would break int() conversion.

    Expected result:
    - reconnect_delay is an int
    - reconnect_delay is >= 0
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    delay = preset.get("reconnect_delay")
    # Assert: stored as integer
    assert isinstance(delay, int), (
        f"ima_protect.reconnect_delay must be int, got {type(delay).__name__}"
    )
    # Assert: non-negative
    assert delay >= 0, f"ima_protect.reconnect_delay={delay} must be >= 0"


def test_ima_protect_encryption_enabled_is_bool(presets_data: dict) -> None:
    """
    IMA Protect preset encryption_enabled must be a JSON boolean (true/false),
    not the string "true" or "1". Python bool(config.get("encryption_enabled"))
    returns True for any non-empty string including "false".

    Expected result:
    - encryption_enabled is of type bool
    """
    preset = next((p for p in presets_data["presets"] if p.get("id") == "ima_protect"), None)
    assert preset is not None
    enc = preset.get("encryption_enabled")
    # Assert: stored as JSON boolean, not string
    assert isinstance(enc, bool), (
        f"ima_protect.encryption_enabled must be bool, got {type(enc).__name__} '{enc}'"
    )


def test_all_preset_ids_are_unique(presets_data: dict) -> None:
    """
    Every preset must have a unique id. Duplicate ids cause silent csr_provider
    lookup to always match the first occurrence, making subsequent presets
    unreachable.

    Expected result:
    - No two presets share the same id value
    """
    ids = [p.get("id") for p in presets_data["presets"]]
    # Assert: all ids are unique
    assert len(ids) == len(set(ids)), (
        f"Duplicate preset ids found: {[i for i in ids if ids.count(i) > 1]}"
    )


def test_all_preset_ids_are_non_empty_strings(presets_data: dict) -> None:
    """
    Every preset id must be a non-empty string. An empty or null id would pass
    the csr_provider lookup when the config key happens to be empty/None.

    Expected result:
    - Each preset's id is a non-empty string
    """
    for preset in presets_data["presets"]:
        pid = preset.get("id")
        # Assert: id is a non-empty string
        assert isinstance(pid, str) and pid, (
            f"Preset has empty or non-string id: {preset}"
        )


def test_top_level_version_is_int(presets_data: dict) -> None:
    """
    csr_presets.json must have a top-level 'version' key as an integer.
    Absence or wrong type would break any future migration logic that reads
    this field.

    Expected result:
    - 'version' key is present
    - 'version' is an integer >= 1
    """
    # Assert: version key is present
    assert "version" in presets_data, "csr_presets.json must have a 'version' key"
    version = presets_data["version"]
    # Assert: version is a positive integer
    assert isinstance(version, int) and version >= 1, (
        f"'version' must be a positive integer, got {type(version).__name__} '{version}'"
    )
