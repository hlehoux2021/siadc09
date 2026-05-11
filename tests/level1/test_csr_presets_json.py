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
