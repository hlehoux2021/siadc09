"""
Plugin packages.json contract tests for Story 6.5.

Validates that plugin_info/packages.json correctly declares Python dependencies
for Jeedom's automatic dependency manager (Method 1). Catches missing packages,
empty stubs from the template, and structural issues.

Reference: docs/design/php-core-design.md § Task 2.2
Reference: _bmad-output/implementation-artifacts/6-5-jeedom-dependency-manager-installation.md
"""
import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PACKAGES_JSON_FILE = _PROJECT_ROOT / "plugin_info/packages.json"


@pytest.fixture(scope="module")
def packages() -> dict:
    return json.loads(PACKAGES_JSON_FILE.read_text(encoding="utf-8"))


def test_packages_json_valid_json() -> None:
    """
    packages.json must be valid JSON — Jeedom's dependency parser silently
    fails on malformed files, leaving dependencies in 'nok' state forever.

    Expected result:
    - File parses as valid JSON without errors
    """
    # Assert: file parses without exception
    data = json.loads(PACKAGES_JSON_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "packages.json root must be a JSON object"


def test_packages_json_exists() -> None:
    """
    plugin_info/packages.json must exist for Jeedom's Method 1 dependency
    management. Without it, hasDependency=true in info.json would show a
    broken install button.

    Expected result:
    - File is present at plugin_info/packages.json
    """
    # Assert: packages.json exists
    assert PACKAGES_JSON_FILE.exists(), f"packages.json not found: {PACKAGES_JSON_FILE}"


def test_packages_json_has_pip3_jeedomdaemon(packages: dict) -> None:
    """
    jeedomdaemon is the Python daemon framework. Without it, siadc09d.py
    fails to import on first launch.

    Expected result:
    - pip3.jeedomdaemon key present
    """
    # Assert: jeedomdaemon declared in pip3
    assert "jeedomdaemon" in packages.get("pip3", {}), (
        "packages.json must declare jeedomdaemon in pip3 section"
    )


def test_packages_json_has_pip3_cryptography(packages: dict) -> None:
    """
    cryptography provides AES-128-CBC for SIA DC-09 encrypted frames
    (imported by sia_crypto.py). Replaced pycryptodome in commit 6c4f77d.

    The key must be the bare distribution name: Jeedom's dependency manager
    looks the key up verbatim against `pip list` output to decide whether the
    package is installed. A key carrying a PEP 508 specifier (e.g.
    "cryptography<44") never matches, so the plugin's dependency status stays
    NOK forever and the daemon cannot be started.

    Expected result:
    - pip3.cryptography key present
    - key carries no version specifier characters
    """
    pip3 = packages.get("pip3", {})

    # Assert: cryptography declared in pip3 under its bare distribution name
    assert "cryptography" in pip3, (
        "packages.json must declare cryptography in pip3 section"
    )

    # Assert: no pip3 key embeds a version specifier (breaks Jeedom's status check)
    keys_with_specifiers = [k for k in pip3 if any(c in k for c in "<>=!~")]
    assert keys_with_specifiers == [], (
        "pip3 keys must be bare distribution names; put constraints in the "
        f'"version" field instead. Offending keys: {keys_with_specifiers}'
    )


def test_packages_json_has_apt_python3_pip(packages: dict) -> None:
    """
    python3-pip is needed on fresh Debian installs before pip3 can run.

    Expected result:
    - apt.python3-pip key present
    """
    # Assert: python3-pip declared in apt
    assert "python3-pip" in packages.get("apt", {}), (
        "packages.json must declare python3-pip in apt section"
    )


def test_packages_json_no_empty_stubs(packages: dict) -> None:
    """
    Template-inherited empty stubs (npm: {}, yarn: {}, plugin: {}, etc.) must
    be removed. They add noise and could confuse future Jeedom core versions.

    Expected result:
    - No top-level key maps to an empty dict (except apt/pip3 which have entries)
    """
    empty_stubs = [k for k, v in packages.items() if isinstance(v, dict) and len(v) == 0]
    # Assert: no empty stub sections remain
    assert len(empty_stubs) == 0, (
        f"packages.json has empty stubs: {empty_stubs} — remove template leftovers"
    )


def test_packages_json_pip3_entries_are_objects(packages: dict) -> None:
    """
    All pip3 entries must use object format {} (not string version specs).
    This is the standard packages.json format — string values may be
    handled differently by future Jeedom core versions.

    Expected result:
    - Every value in the pip3 section is a dict (object)
    """
    pip3 = packages.get("pip3", {})
    for pkg, value in pip3.items():
        # Assert: each pip3 entry is an object
        assert isinstance(value, dict), (
            f"packages.json pip3.{pkg} must be an object {{}}, "
            f"got {type(value).__name__}: {value}"
        )
