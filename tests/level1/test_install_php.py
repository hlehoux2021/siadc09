"""
Plugin install.php structural tests for Story 6.5.

Validates that plugin_info/install.php has the three mandatory Jeedom hook
functions and that siaDC09_remove() properly cleans up daemon processes
without referencing the removed sentinel file pattern.

Reference: docs/design/php-core-design.md § Task 2.11
Reference: _bmad-output/implementation-artifacts/6-5-jeedom-dependency-manager-installation.md
"""
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
INSTALL_PHP_FILE = _PROJECT_ROOT / "plugin_info/install.php"


@pytest.fixture(scope="module")
def install_source() -> str:
    return INSTALL_PHP_FILE.read_text(encoding="utf-8")


def test_install_php_exists() -> None:
    """
    plugin_info/install.php must exist — Jeedom requires it for plugin
    install/update/remove lifecycle hooks.

    Expected result:
    - File is present at plugin_info/install.php
    """
    # Assert: install.php exists
    assert INSTALL_PHP_FILE.exists(), f"install.php not found: {INSTALL_PHP_FILE}"


def test_install_php_has_install_hook(install_source: str) -> None:
    """
    siaDC09_install() function must be defined. Called on first plugin install.

    Expected result:
    - 'function siaDC09_install' appears in source
    """
    # Assert: install hook present
    assert "function siaDC09_install" in install_source, (
        "install.php must define siaDC09_install() — required Jeedom hook"
    )


def test_install_php_has_update_hook(install_source: str) -> None:
    """
    siaDC09_update() function must be defined. Called on plugin update.

    Expected result:
    - 'function siaDC09_update' appears in source
    """
    # Assert: update hook present
    assert "function siaDC09_update" in install_source, (
        "install.php must define siaDC09_update() — required Jeedom hook"
    )


def test_install_php_has_remove_hook(install_source: str) -> None:
    """
    siaDC09_remove() function must be defined. Called on plugin removal.

    Expected result:
    - 'function siaDC09_remove' appears in source
    """
    # Assert: remove hook present
    assert "function siaDC09_remove" in install_source, (
        "install.php must define siaDC09_remove() — required Jeedom hook"
    )


def test_install_php_remove_kills_daemon(install_source: str) -> None:
    """
    siaDC09_remove() must kill the daemon process on plugin removal.
    Without this, a running daemon survives plugin uninstall and holds
    the socket port open, blocking reinstall.

    Expected result:
    - 'siadc09d.py' (daemon script name) appears in remove function
    - 'system::kill' appears in source (kill mechanism)
    """
    # Assert: daemon script name targeted for kill
    assert "siadc09d.py" in install_source, (
        "siaDC09_remove() must kill siadc09d.py on plugin removal"
    )
    # Assert: kill mechanism present
    assert "system::kill" in install_source, (
        "siaDC09_remove() must use system::kill() for daemon cleanup"
    )


def test_no_install_dep_sh_exists() -> None:
    """
    With Method 1 (packages.json), there must be no install_dep.sh script.
    Having both packages.json AND install_dep.sh creates a Method 1+2 conflict
    where dependencies may be installed twice or to different locations.

    Expected result:
    - resources/siadc09d/install_dep.sh does NOT exist
    """
    install_script = _PROJECT_ROOT / "resources/siadc09d/install_dep.sh"
    # Assert: no install script (Method 1 — packages.json handles install)
    assert not install_script.exists(), (
        "install_dep.sh must NOT exist — Method 1 (packages.json) handles "
        "dependency installation. Having both creates a conflict."
    )


def test_install_php_remove_no_sentinel_reference(install_source: str) -> None:
    """
    With Method 1 (packages.json), there is no .install_ok sentinel file.
    siaDC09_remove() must NOT reference it — the sentinel pattern was removed.
    If someone adds it back (copying from the design doc's Method 2 spec),
    it would reference a nonexistent file.

    Expected result:
    - 'install_ok' does NOT appear in install.php
    """
    # Assert: no sentinel file reference (Method 1 — no sentinel)
    assert "install_ok" not in install_source, (
        "install.php must NOT reference .install_ok — "
        "Method 1 (packages.json) does not use sentinel files"
    )
