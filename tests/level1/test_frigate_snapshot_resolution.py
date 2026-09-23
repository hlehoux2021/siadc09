"""
PHP source-validation tests for Story 14.1 — Frigate snapshot attachment (majority case only).

Parses core/class/siaDC09Cmd.class.php to verify the alarm-trigger path resolves a Frigate
camera snapshot via execCmd() (never getValue()) only when info_detect_person reads 1, never
blocks/throws on a missing camera/plugin, and never attaches a clip URL.

Reference: _bmad-output/implementation-artifacts/14-1-attach-frigate-snapshot-alarm-frame.md
Reference: ADR-17, _bmad-output/planning-artifacts/architecture.md
"""
import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PHP_CMD_FILE = _PROJECT_ROOT / "core/class/siaDC09Cmd.class.php"
PHP_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"


def _extract_method_body(source: str, method_name: str) -> str:
    """Extract the body of a named PHP method by tracking brace depth."""
    match = re.search(rf"function\s+{re.escape(method_name)}\s*\(", source)
    if not match:
        return ""
    pos = match.end() - 1
    depth = 1
    i = pos + 1
    while i < len(source) and depth > 0:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
        i += 1
    brace_start = source.index("{", i)
    depth = 1
    i = brace_start + 1
    while i < len(source) and depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[brace_start + 1 : i - 1]


def _extract_if_action_body(source: str, action_name: str) -> str:
    """Extract the brace-balanced body of `if (init('action') == '<action_name>') { ... }`."""
    match = re.search(
        rf"if\s*\(\s*init\(\s*['\"]action['\"]\s*\)\s*==\s*['\"]{re.escape(action_name)}['\"]\s*\)",
        source,
    )
    if not match:
        return ""
    brace_start = source.index("{", match.end())
    depth = 1
    i = brace_start + 1
    while i < len(source) and depth > 0:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    return source[brace_start + 1 : i - 1]


@pytest.fixture(scope="module")
def php_cmd_source() -> str:
    return PHP_CMD_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def php_ajax_source() -> str:
    return PHP_AJAX_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def get_frigate_cameras_body(php_ajax_source: str) -> str:
    return _extract_if_action_body(php_ajax_source, "getFrigateCameras")


@pytest.fixture(scope="module")
def execute_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "execute")


@pytest.fixture(scope="module")
def resolve_snapshot_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_resolveFrigateSnapshotUrl")


class TestResolveFrigateSnapshotUrlExists:
    """The resolver helper exists as its own method — never inlined into execute()."""

    def test_method_exists(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - _resolveFrigateSnapshotUrl() is a real method with a non-empty body
        """
        # Assert: helper method present
        assert resolve_snapshot_body != ""


class TestResolveFrigateSnapshotUrlReadsCorrectCommands:
    """The resolver reads info_detect_person and info_url_snapshot by logicalId, via execCmd()."""

    def test_reads_frigate_camera_eqlogic_id(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the zone entry's frigate_camera_eqlogic_id field is read
        """
        # Assert: new simplified schema field is read
        assert "frigate_camera_eqlogic_id" in resolve_snapshot_body

    def test_looks_up_info_detect_person_by_logical_id(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - cmd::byEqLogicIdAndLogicalId(..., 'info_detect_person') is called — scoped to the
          mapped equipment (cmd::byLogicalId has no eqLogicId parameter in Jeedom core and
          returns an array, not a single cmd; it must never be used here)
        """
        # Assert: detection command resolved by logicalId, scoped to one equipment
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_detect_person['\"]", resolve_snapshot_body)

    def test_looks_up_info_url_snapshot_by_logical_id(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - cmd::byEqLogicIdAndLogicalId(..., 'info_url_snapshot') is called — scoped to the
          mapped equipment
        """
        # Assert: snapshot command resolved by logicalId, scoped to one equipment
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_url_snapshot['\"]", resolve_snapshot_body)

    def test_never_uses_unscoped_by_logical_id(self, resolve_snapshot_body: str) -> None:
        """
        cmd::byLogicalId($_logical_id, $_type) has no eqLogicId parameter in Jeedom core
        (core/class/cmd.class.php) and returns an array of every matching cmd across all
        equipments — a live bug found via Task 4 host validation (2026-09-23): it raised
        "Call to a member function execCmd() on array".

        Expected result:
        - the unscoped, single-equipment-unsafe byLogicalId() call is never used here
        """
        # Assert: only the eqLogic-scoped lookup is used
        assert "byLogicalId(" not in resolve_snapshot_body

    def test_never_reads_info_url_clip(self, resolve_snapshot_body: str) -> None:
        """
        ADR-17: media_url must never map to a clip/video URL.

        Expected result:
        - info_url_clip is never referenced in the resolver
        """
        # Assert: clip is out of scope per ADR-17
        assert "info_url_clip" not in resolve_snapshot_body

    def test_uses_exec_cmd_never_get_value(self, resolve_snapshot_body: str) -> None:
        """
        Per project memory jeedom-info-cmd-execcmd-vs-getvalue: getValue() is frozen forever
        for non-historized info cmds; execCmd() is the live accessor.

        Expected result:
        - execCmd() is used to read the live values
        - getValue() is never used in this method
        """
        # Assert: live read via execCmd()
        assert "execCmd()" in resolve_snapshot_body
        # Assert: getValue() never used here — would silently freeze the feature
        assert "getValue()" not in resolve_snapshot_body


class TestResolveFrigateSnapshotUrlNeverThrows:
    """The alarm-send path must never block or throw on camera/plugin absence (AC5)."""

    def test_wrapped_in_try_catch(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the whole method body is guarded by try/catch
        """
        # Assert: defensive wrapping present
        assert "try" in resolve_snapshot_body
        assert "catch" in resolve_snapshot_body

    def test_returns_null_type_hint(self, php_cmd_source: str) -> None:
        """
        Expected result:
        - the method is typed to return ?string (nullable) — null is a valid, expected outcome,
          not an error condition
        """
        # Assert: nullable return type declared
        assert re.search(r"_resolveFrigateSnapshotUrl\([^)]*\)\s*:\s*\?string", php_cmd_source)


class TestGetFrigateCamerasAction:
    """New AJAX action discovers Frigate cameras precisely — CAMERA_TAKE-tagged AND exposing
    both info_detect_person and info_url_snapshot on the same equipment (Task 1.2)."""

    def test_action_exists(self, get_frigate_cameras_body: str) -> None:
        """
        Expected result:
        - the getFrigateCameras action is defined
        """
        # Assert: new dedicated discovery action present
        assert get_frigate_cameras_body != ""

    def test_starts_from_camera_take_generic_type(self, get_frigate_cameras_body: str) -> None:
        """
        Expected result:
        - candidates come from cmd::byGenericType('CAMERA_TAKE'), same starting point as the
          existing plugin-agnostic getCameraCommands action
        """
        # Assert: reuses the existing generic-type discovery as its candidate pool
        assert re.search(r"byGenericType\(\s*['\"]CAMERA_TAKE['\"]", get_frigate_cameras_body)

    def test_filters_by_info_detect_person_and_info_url_snapshot(self, get_frigate_cameras_body: str) -> None:
        """
        Expected result:
        - candidates are filtered to those whose equipment also has both
          info_detect_person and info_url_snapshot (the Frigate-specific signal)
        """
        # Assert: precise filter beyond the generic CAMERA_TAKE tag, scoped per-equipment
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_detect_person['\"]", get_frigate_cameras_body)
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_url_snapshot['\"]", get_frigate_cameras_body)
        # Assert: the unscoped, array-returning byLogicalId() is never used here either
        assert "byLogicalId(" not in get_frigate_cameras_body

    def test_never_returns_camera_url_split_shape(self, get_frigate_cameras_body: str) -> None:
        """
        ADR-17 simplification: a single camera list, not the old camera_take/camera_url split.

        Expected result:
        - the old two-list response shape is not reintroduced here
        """
        # Assert: single unified list, matching the "just pick a camera" simplification
        assert "camera_take" not in get_frigate_cameras_body
        assert "camera_url" not in get_frigate_cameras_body


class TestExecuteWiresMediaUrlConditionally:
    """execute() attaches media_url to the daemon payload only when resolution succeeds."""

    def test_calls_resolver(self, execute_body: str) -> None:
        """
        Expected result:
        - the alarm case calls _resolveFrigateSnapshotUrl()
        """
        # Assert: resolver invoked from the alarm-trigger path
        assert "_resolveFrigateSnapshotUrl(" in execute_body

    def test_media_url_key_is_conditional_not_unconditional(self, execute_body: str) -> None:
        """
        Expected result:
        - 'media_url' is not a literal key inside the base sendToDaemon() payload array
          (it must be added conditionally afterward, never unconditionally with a possible
          null value — matches the existing zone/zone_number key style of omitting rather
          than nulling absent data)
        """
        # Assert: media_url is set outside/after the literal payload array construction
        payload_array_match = re.search(r"sendToDaemon\(\s*(\[.*?\])\s*\)", execute_body, re.DOTALL)
        if payload_array_match:
            assert "media_url" not in payload_array_match.group(1)
        else:
            # payload built as a variable and passed by reference — assert conditional assignment exists
            assert re.search(r"if\s*\([^)]*!==\s*null[^)]*\)\s*\{[^}]*media_url", execute_body, re.DOTALL) \
                or re.search(r"\$\w+\['media_url'\]\s*=", execute_body)
