"""
Plugin info.json contract tests for Story 6.5.

Validates that plugin_info/info.json contains correct metadata for Jeedom
Market submission and runtime plugin registration. These tests catch drift
in critical fields that would break installation or Market listing.

Reference: docs/design/php-core-design.md § Task 2.1
Reference: _bmad-output/implementation-artifacts/6-5-jeedom-dependency-manager-installation.md
"""
import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
INFO_JSON_FILE = _PROJECT_ROOT / "plugin_info/info.json"


@pytest.fixture(scope="module")
def info() -> dict:
    return json.loads(INFO_JSON_FILE.read_text(encoding="utf-8"))


def test_info_json_exists() -> None:
    """
    plugin_info/info.json must exist — Jeedom cannot register the plugin without it.

    Expected result:
    - File is present at plugin_info/info.json
    """
    # Assert: info.json exists
    assert INFO_JSON_FILE.exists(), f"info.json not found: {INFO_JSON_FILE}"


def test_info_json_valid_json() -> None:
    """
    info.json must be valid JSON — Jeedom's parser rejects malformed files silently.

    Expected result:
    - File parses as valid JSON without errors
    """
    # Assert: file parses without exception
    data = json.loads(INFO_JSON_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "info.json root must be a JSON object"


def test_info_json_id_matches_plugin(info: dict) -> None:
    """
    The plugin ID must be 'siaDC09' — this is the class name and the routing
    key for all Jeedom core calls.

    Expected result:
    - id field is exactly 'siaDC09'
    """
    # Assert: plugin ID matches class name
    assert info["id"] == "siaDC09", (
        f"info.json id must be 'siaDC09', got '{info.get('id')}'"
    )


def test_info_json_require_is_string(info: dict) -> None:
    """
    require must be a bare string (e.g. '4.5'), not an object. Expert confirmed:
    bare string is the original format, still supported by all Jeedom versions,
    and safer for backward compatibility.

    Expected result:
    - require is a str, not a dict
    """
    # Assert: require is bare string (not object format)
    assert isinstance(info["require"], str), (
        f"info.json require must be a bare string (e.g. '4.5'), "
        f"got {type(info['require']).__name__}: {info['require']}"
    )


def test_info_json_has_dependency_flags(info: dict) -> None:
    """
    hasDependency and hasOwnDeamon must both be true for Jeedom to show the
    dependency install button and daemon controls in the plugin manager.

    Expected result:
    - hasDependency is True
    - hasOwnDeamon is True (note Jeedom's historical misspelling)
    """
    # Assert: dependency flag set
    assert info.get("hasDependency") is True, (
        "info.json hasDependency must be true — enables dependency install UI"
    )
    # Assert: daemon flag set (note: Jeedom uses 'Deamon' spelling)
    assert info.get("hasOwnDeamon") is True, (
        "info.json hasOwnDeamon must be true — enables daemon controls"
    )


def test_info_json_os_min_is_12(info: dict) -> None:
    """
    os.min must be 12 (Debian 12 / Bookworm) to enforce Python 3.10+ availability.
    Debian 11 ships Python 3.9 which lacks PEP 604 union types used in the daemon.

    Expected result:
    - os.min == 12
    """
    # Assert: minimum Debian version enforced
    assert info.get("os", {}).get("min") == 12, (
        "info.json os.min must be 12 (Debian 12 for Python 3.10+)"
    )


def test_info_json_max_dependancy_install_time(info: dict) -> None:
    """
    maxDependancyInstallTime must be 10 minutes. Two pip packages install in
    under 2 minutes — 10 gives comfortable margin without leaving users waiting
    an hour on a hung install.

    Expected result:
    - maxDependancyInstallTime == 10
    """
    # Assert: install timeout is 10 minutes
    assert info.get("maxDependancyInstallTime") == 10, (
        f"info.json maxDependancyInstallTime must be 10, "
        f"got {info.get('maxDependancyInstallTime')}"
    )


def test_info_json_category_is_security(info: dict) -> None:
    """
    Category must be 'security' for correct Market placement. This plugin
    bridges alarm events to a professional monitoring center.

    Expected result:
    - category == 'security'
    """
    # Assert: correct Market category
    assert info.get("category") == "security", (
        f"info.json category must be 'security', got '{info.get('category')}'"
    )


def test_info_json_name_is_canonical(info: dict) -> None:
    """
    Name must be 'Télésurveillance SIA DC-09' — the full canonical name shown
    in Jeedom's plugin manager and Market listing. Short names like
    'Télésurveillance' are ambiguous (many plugins could use that).

    Expected result:
    - name == 'Télésurveillance SIA DC-09'
    """
    # Assert: canonical name with protocol identifier
    assert info.get("name") == "Télésurveillance SIA DC-09", (
        f"info.json name must be 'Télésurveillance SIA DC-09', "
        f"got '{info.get('name')}'"
    )


def test_info_json_description_fr_present(info: dict) -> None:
    """
    description.fr_FR is the Market listing text for French users (the primary
    Jeedom audience). Must be the canonical description with protocol reference.

    Expected result:
    - description.fr_FR is a non-empty string
    - Contains 'SIA DC-09' protocol reference
    """
    desc = info.get("description", {}).get("fr_FR", "")
    # Assert: French description is present and non-empty
    assert isinstance(desc, str) and len(desc) > 0, (
        "info.json description.fr_FR must be a non-empty string"
    )
    # Assert: protocol name referenced in description
    assert "SIA DC-09" in desc, (
        "info.json description.fr_FR must reference 'SIA DC-09' protocol"
    )


def test_info_json_licence_is_agpl(info: dict) -> None:
    """
    Licence must be 'AGPL' for Market submission. Required field.

    Expected result:
    - licence == 'AGPL'
    """
    # Assert: licence field present and correct
    assert info.get("licence") == "AGPL", (
        f"info.json licence must be 'AGPL', got '{info.get('licence')}'"
    )


def test_info_json_author_present(info: dict) -> None:
    """
    Author must be a non-empty string. Required for Market listing.

    Expected result:
    - author is a non-empty string
    """
    # Assert: author present and non-empty
    assert isinstance(info.get("author"), str) and len(info["author"]) > 0, (
        "info.json author must be a non-empty string"
    )
