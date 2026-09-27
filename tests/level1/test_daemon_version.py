"""
DAEMON_VERSION contract tests for Story 11.4 (AC6, Task 3.4).

architecture.md § Versioning Strategy: a single release version, carried by
info.json's ``pluginVersion`` for the Market and mirrored by a manually
maintained ``DAEMON_VERSION`` constant in the daemon package, logged at
startup. The two must be bumped together before every Market publish — this
test turns that pre-release checklist item into a failing build instead of a
silent drift.

Reference: _bmad-output/planning-artifacts/architecture.md § Versioning Strategy
"""
import json
import re
from pathlib import Path

from resources.siadc09d import DAEMON_VERSION

_PROJECT_ROOT = Path(__file__).parent.parent.parent
INFO_JSON_FILE = _PROJECT_ROOT / "plugin_info/info.json"
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_daemon_version_is_semver() -> None:
    """
    DAEMON_VERSION is a plain MAJOR.MINOR.PATCH string.

    Expected result:
    - DAEMON_VERSION matches N.N.N
    """
    # Assert: semver shape, no prefix/suffix
    assert _SEMVER_RE.match(DAEMON_VERSION), f"DAEMON_VERSION {DAEMON_VERSION!r} is not N.N.N"


def test_daemon_version_matches_info_json_plugin_version() -> None:
    """
    DAEMON_VERSION and info.json pluginVersion never drift apart.

    Expected result:
    - info.json declares pluginVersion
    - pluginVersion == DAEMON_VERSION
    """
    info = json.loads(INFO_JSON_FILE.read_text(encoding="utf-8"))
    # Assert: info.json declares the Market-visible version
    assert "pluginVersion" in info, "info.json must declare pluginVersion"
    # Assert: both version sources agree
    assert info["pluginVersion"] == DAEMON_VERSION, (
        f"info.json pluginVersion {info['pluginVersion']!r} != DAEMON_VERSION {DAEMON_VERSION!r} "
        "— bump both before publishing"
    )
