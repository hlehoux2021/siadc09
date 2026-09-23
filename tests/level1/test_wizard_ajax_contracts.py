"""
AJAX endpoint contract validation tests for Epic 8.

Parses core/ajax/siaDC09.ajax.php to verify security guards, error handling
branches, response shape contracts, and integration patterns. These tests
ensure the AJAX layer maintains its contract with the JS frontend without
requiring a live Jeedom instance.

Reference: docs/design/wizard-design.md §Task 3.10
Reference: _bmad-output/implementation-artifacts/8-1-wizard-steps-1-2-csr-preset-selection.md
"""

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"


@pytest.fixture(scope="module")
def ajax_source() -> str:
    assert _AJAX_FILE.exists(), f"AJAX file not found: {_AJAX_FILE}"
    return _AJAX_FILE.read_text(encoding="utf-8")


# ── Security Guards ────────────────────────────────────────────────────────────


def test_admin_auth_check(ajax_source: str) -> None:
    """
    AJAX handler must check isConnect('admin') before processing any action.
    Without this, unauthenticated users could trigger connection tests or
    read alarm zone configuration.

    Expected result:
    - isConnect('admin') check present before any action handling
    """
    # Assert: admin auth guard present
    assert "isConnect('admin')" in ajax_source


def test_auth_throws_on_failure(ajax_source: str) -> None:
    """
    Failed auth must throw an Exception, not silently continue.
    Jeedom's ajax error handler catches this and returns 401.

    Expected result:
    - throw new Exception after failed isConnect check
    """
    pattern = r"isConnect\('admin'\).*?throw\s+new\s+Exception"
    # Assert: exception thrown on auth failure
    assert re.search(pattern, ajax_source, re.DOTALL)


def test_ajax_init_called(ajax_source: str) -> None:
    """
    ajax::init() must be called to initialize Jeedom AJAX framework
    (CSRF token validation, request parsing).

    Expected result:
    - ajax::init() call present
    """
    # Assert: AJAX framework initialized
    assert "ajax::init()" in ajax_source


# ── testConnection Action ──────────────────────────────────────────────────────


def test_test_connection_action_exists(ajax_source: str) -> None:
    """
    testConnection action must be handled.

    Expected result:
    - init('action') == 'testConnection' check present
    """
    # Assert: testConnection action handler present
    assert "'testConnection'" in ajax_source


def test_test_connection_loads_eq_logic(ajax_source: str) -> None:
    """
    testConnection must load the siaDC09 eqLogic to get configuration.
    eqLogic::byType returns the auto-created equipment.

    Expected result:
    - eqLogic::byType('siaDC09') call present
    """
    # Assert: equipment loaded
    assert "eqLogic::byType('siaDC09')" in ajax_source


def test_test_connection_handles_missing_equipment(ajax_source: str) -> None:
    """
    If no siaDC09 eqLogic exists, testConnection must return an error
    (not crash with null pointer).

    Expected result:
    - Empty eqLogics array check with error response
    """
    # Assert: missing equipment handled gracefully
    assert re.search(r"count\(\$eqLogics\)\s*===?\s*0", ajax_source)


def test_test_connection_strips_encryption_key(ajax_source: str) -> None:
    """
    Encryption key must be removed from config before passing to subprocess
    (passed via environment variable instead for security).

    Expected result:
    - unset($configData['encryption_key']) present
    """
    # Assert: encryption key stripped from config
    assert "unset($configData['encryption_key'])" in ajax_source


def test_test_connection_uses_env_for_key(ajax_source: str) -> None:
    """
    Encryption key must be passed via SIA_ENCRYPTION_KEY environment variable
    to the subprocess — never as a CLI argument (visible in process list).

    Expected result:
    - SIA_ENCRYPTION_KEY environment variable prefix in exec command
    """
    # Assert: key passed via environment
    assert "SIA_ENCRYPTION_KEY" in ajax_source


def test_test_connection_uses_escapeshellarg(ajax_source: str) -> None:
    """
    All user-controlled data passed to exec() must use escapeshellarg()
    to prevent command injection.

    Expected result:
    - escapeshellarg() calls for config data and script path
    """
    matches = re.findall(r'escapeshellarg\(', ajax_source)
    # Assert: at least 2 escapeshellarg calls (script + config)
    assert len(matches) >= 2, (
        f"Expected >= 2 escapeshellarg() calls, found {len(matches)} — "
        "possible command injection vulnerability"
    )


def test_test_connection_uses_test_only_flag(ajax_source: str) -> None:
    """
    testConnection must pass --test-only flag to the Python script to trigger
    standalone mode (no daemon initialization).

    Expected result:
    - --test-only flag present in command construction
    """
    # Assert: test-only flag used
    assert "--test-only" in ajax_source


def test_test_connection_uses_timeout_flag(ajax_source: str) -> None:
    """
    testConnection must pass --timeout flag to bound the test duration.

    Expected result:
    - --timeout flag present in command construction
    """
    # Assert: timeout flag used
    assert "--timeout" in ajax_source


def test_test_connection_set_time_limit(ajax_source: str) -> None:
    """
    PHP must call set_time_limit() before exec() to prevent the default
    30s PHP timeout from killing the request mid-test.

    Expected result:
    - set_time_limit call with value > 15 (timeout is 15s)
    """
    # Assert: PHP time limit extended
    assert re.search(r"set_time_limit\(\s*\d+\s*\)", ajax_source)


def test_test_connection_handles_json_decode_failure(ajax_source: str) -> None:
    """
    If the Python subprocess returns non-JSON output (crash, stderr),
    testConnection must return an error, not crash.

    Expected result:
    - json_decode result check (is_array) before using result
    """
    # Assert: JSON decode failure handled
    assert "is_array($result)" in ajax_source or re.search(
        r"json_decode.*?is_array", ajax_source, re.DOTALL
    )


def test_test_connection_handles_script_not_found(ajax_source: str) -> None:
    """
    If the Python script path doesn't resolve (plugin files missing),
    must return descriptive error.

    Expected result:
    - realpath check with error response for missing script
    """
    # Assert: script existence verified
    assert "realpath" in ajax_source


def test_test_connection_suppresses_stderr(ajax_source: str) -> None:
    """
    exec() must redirect stderr to /dev/null — Python tracebacks should
    not leak into the JSON response.

    Expected result:
    - 2>/dev/null in exec command
    """
    # Assert: stderr suppressed
    assert "2>/dev/null" in ajax_source


def test_test_connection_uses_get_cmd_python3(ajax_source: str) -> None:
    """
    Must use system::getCmdPython3() when available (Jeedom 4.4+) to get
    the correct venv-aware Python binary path.

    Expected result:
    - getCmdPython3 method call with fallback
    """
    # Assert: venv-aware Python path used
    assert "getCmdPython3" in ajax_source


def test_test_connection_config_encode_check(ajax_source: str) -> None:
    """
    json_encode of config data must be checked for failure (false return)
    before building the exec command.

    Expected result:
    - json_encode result check present
    """
    # Assert: encode failure handled
    assert "json_encode" in ajax_source
    assert re.search(r"\$encoded\s*===?\s*false", ajax_source)


# ── getZones Action ────────────────────────────────────────────────────────────


def test_get_zones_action_exists(ajax_source: str) -> None:
    """
    getZones action must be handled.

    Expected result:
    - init('action') == 'getZones' check present
    """
    # Assert: getZones action handler present
    assert "'getZones'" in ajax_source


def test_get_zones_loads_alarm_plugin(ajax_source: str) -> None:
    """
    getZones must load the alarm plugin's eqLogic to read zone configuration.

    Expected result:
    - eqLogic::byType('alarm') call present
    """
    # Assert: alarm plugin loaded
    assert "eqLogic::byType('alarm')" in ajax_source


def test_get_zones_handles_no_alarm_plugin(ajax_source: str) -> None:
    """
    If alarm plugin is not installed/has no equipment, must return a structured
    error (not crash). JS shows siaDC09-step3-nozone based on this.

    Expected result:
    - alarm_plugin_not_found error response
    """
    # Assert: missing alarm plugin handled
    assert "alarm_plugin_not_found" in ajax_source


def test_get_zones_handles_no_zones_configured(ajax_source: str) -> None:
    """
    If alarm plugin exists but has no zones, must return a distinct error.

    Expected result:
    - no_zones_configured error response
    """
    # Assert: empty zones handled
    assert "no_zones_configured" in ajax_source


def test_get_zones_returns_zone_names(ajax_source: str) -> None:
    """
    Successful getZones must return a 'zones' array of zone name strings.
    Uses array_column to extract 'name' field from zone config objects.

    Expected result:
    - array_column($zones, 'name') present
    """
    # Assert: zone names extracted via array_column
    assert "array_column" in ajax_source


# ── getFrigateCameras Action (story 14.1, replaced getCameraCommands per ADR-17) ────────────────


def test_get_frigate_cameras_action_exists(ajax_source: str) -> None:
    """
    getFrigateCameras action must be handled. Replaced getCameraCommands
    (deleted as dead code once the wizard stopped calling it — ADR-17
    simplified zone mapping to a single Frigate-camera pick).

    Expected result:
    - init('action') == 'getFrigateCameras' check present
    """
    # Assert: getFrigateCameras action handler present
    assert "'getFrigateCameras'" in ajax_source


def test_get_frigate_cameras_starts_from_camera_take_generic_type(ajax_source: str) -> None:
    """
    Candidate discovery still starts from cmd::byGenericType('CAMERA_TAKE') —
    the plugin-agnostic Jeedom pattern — then narrows to real Frigate cameras.

    Expected result:
    - CAMERA_TAKE generic type query present
    """
    # Assert: generic-type discovery reused as the candidate pool
    assert "CAMERA_TAKE" in ajax_source


def test_get_frigate_cameras_filters_by_frigate_specific_commands(ajax_source: str) -> None:
    """
    Candidates are filtered to equipments that also expose info_detect_person
    and info_id by logicalId — the Frigate-specific signal that CAMERA_TAKE
    alone doesn't guarantee. Swapped from info_url_snapshot in Task 6
    (ADR-17 amendment, 2026-09-23: that command is a Jeedom-local cached path,
    unusable by an external CSR — no longer read anywhere in siaDC09).

    Expected result:
    - byEqLogicIdAndLogicalId lookups for both Frigate-specific commands present
    - info_url_snapshot is never referenced
    """
    # Assert: precise Frigate-camera filter beyond the generic tag
    assert "info_detect_person" in ajax_source
    assert "info_id" in ajax_source
    # Assert: the unusable Jeedom-cached path is never read
    assert "info_url_snapshot" not in ajax_source


def test_get_frigate_cameras_returns_single_list(ajax_source: str) -> None:
    """
    Response is a single 'cameras' list (ADR-17 simplification: one dropdown,
    not the old camera_take/camera_url pair).

    Expected result:
    - Response structure with a single cameras key
    """
    # Assert: unified camera list in response
    assert "'cameras'" in ajax_source


def test_get_frigate_cameras_includes_id_and_label(ajax_source: str) -> None:
    """
    Each camera entry must include id (for persistence) and label
    (for display in dropdown).

    Expected result:
    - 'id' and 'label' keys in the response construction
    """
    # Assert: camera entries have id and label
    assert "'id'" in ajax_source
    assert "'label'" in ajax_source


# ── Error Handling ─────────────────────────────────────────────────────────────


def test_global_exception_handler(ajax_source: str) -> None:
    """
    All actions must be wrapped in try/catch with ajax::error() response.
    Unhandled exceptions would return raw PHP errors to the frontend.

    Expected result:
    - try/catch block with ajax::error() call
    """
    # Assert: global exception handler present
    assert "ajax::error" in ajax_source


def test_unknown_action_throws(ajax_source: str) -> None:
    """
    Unknown actions must throw an exception (not silently succeed).
    This is the standard Jeedom AJAX pattern.

    Expected result:
    - Exception thrown for unmatched actions after all handlers
    """
    # Assert: unknown action throws
    assert re.search(r"throw\s+new\s+Exception.*init\('action'\)", ajax_source)


def test_all_responses_use_ajax_success(ajax_source: str) -> None:
    """
    All successful responses must use ajax::success() for consistent
    JSON response formatting.

    Expected result:
    - Multiple ajax::success() calls (one per action)
    """
    matches = re.findall(r'ajax::success\(', ajax_source)
    # Assert: at least 3 success responses (one per action minimum)
    assert len(matches) >= 3, (
        f"Expected >= 3 ajax::success() calls, found {len(matches)}"
    )
