"""
PHP source-validation tests for Story 14.1 — Frigate snapshot attachment (majority case only).

Parses core/class/siaDC09Cmd.class.php to verify the alarm-trigger path resolves a Frigate
camera snapshot via execCmd() (never getValue()) only when info_detect_person reads 1, never
blocks/throws on a missing camera/plugin, and never attaches a clip URL. Task 6 (2026-09-23):
media_url is built from a configurable URL template + the Frigate event id (info_id), never
from info_url_snapshot (a Jeedom-local cached path unusable by an external CSR) —
_buildFrigateMediaUrl() has no Jeedom dependency, so its real extracted body is executed
directly via `php` for genuine behavioral coverage, not just source-text shape.

Reference: _bmad-output/implementation-artifacts/14-1-attach-frigate-snapshot-alarm-frame.md
Reference: ADR-17, _bmad-output/planning-artifacts/architecture.md
"""
import json
import re
import subprocess
import tempfile
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


@pytest.fixture(scope="module")
def build_media_url_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_buildFrigateMediaUrl")


def _run_build_frigate_media_url(build_media_url_body: str, template: str, event_id: str) -> str | None:
    """Execute the REAL extracted _buildFrigateMediaUrl() body via `php`, no Jeedom bootstrap.

    The method is pure parse_url() string logic with zero Jeedom dependency (no cmd::, no
    log::, no $this), so its extracted source can run standalone — this verifies actual
    behavior for the tricky path-vs-query reassembly, not just that certain strings appear
    in the source text (the project's usual Level 1 PHP convention, which alone can't catch
    an ordering bug like this).
    """
    harness = (
        "<?php\n"
        "function _test_build_frigate_media_url($template, $eventId) {\n"
        f"{build_media_url_body}\n"
        "}\n"
        "echo json_encode(_test_build_frigate_media_url($argv[1], $argv[2]));\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".php", delete=False) as f:
        f.write(harness)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["php", tmp_path, template, event_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"PHP execution failed: {result.stderr}"
        return json.loads(result.stdout)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
    """The resolver reads info_detect_person and info_id by logicalId, via execCmd(), then
    builds media_url from the configured template — never reads info_url_snapshot (Task 6,
    ADR-17 amendment 2026-09-23: that command is always a Jeedom-local cached-copy path,
    unusable by an external CSR)."""

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

    def test_looks_up_info_id_by_logical_id(self, resolve_snapshot_body: str) -> None:
        """
        Task 6: the Frigate event id (needed to build media_url) is read from info_id — the
        same per-camera equipment, populated by the same majEventsCmds() sweep as
        info_detect_person (confirmed in ADR-17 amendment).

        Expected result:
        - cmd::byEqLogicIdAndLogicalId(..., 'info_id') is called — scoped to the mapped
          equipment
        """
        # Assert: event id resolved by logicalId, scoped to one equipment
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_id['\"]", resolve_snapshot_body)

    def test_never_reads_info_url_snapshot(self, resolve_snapshot_body: str) -> None:
        """
        Task 6 (ADR-17 amendment, 2026-09-23): info_url_snapshot is always a Jeedom-local
        cached-copy path (confirmed via frigate.class.php:1236/1260) — an external CSR can
        never resolve it. siaDC09 no longer reads this command at all.

        Expected result:
        - info_url_snapshot is never referenced in the resolver
        """
        # Assert: the unusable Jeedom-cached path is never read
        assert "info_url_snapshot" not in resolve_snapshot_body

    def test_reads_media_url_template_config(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the eqLogic's frigate_media_url_template configuration key is read
        """
        # Assert: the configurable template (literal placeholders only, never a real secret)
        assert "frigate_media_url_template" in resolve_snapshot_body

    def test_calls_build_frigate_media_url(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the resolver delegates URL construction to _buildFrigateMediaUrl()
        """
        # Assert: URL reassembly is delegated to the dedicated builder, not inlined here
        assert "_buildFrigateMediaUrl(" in resolve_snapshot_body

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


class TestBuildFrigateMediaUrl:
    """_buildFrigateMediaUrl() (Task 6, AC8): inserts api/events/{event_id}/snapshot.jpg into
    a configurable URL template's path, before any existing query string, without ever
    resolving the template's literal placeholder credentials. Executes the REAL extracted
    method body via php (see _run_build_frigate_media_url) — this method has zero Jeedom
    dependency, so real behavior is verifiable without a live Jeedom bootstrap."""

    def test_method_exists(self, build_media_url_body: str) -> None:
        """
        Expected result:
        - _buildFrigateMediaUrl() is a real method with a non-empty body
        """
        # Assert: helper method present
        assert build_media_url_body != ""

    def test_uses_parse_url(self, build_media_url_body: str) -> None:
        """
        Expected result:
        - parse_url() is used to decompose the template
        """
        # Assert: standard URL parsing, not hand-rolled string splitting
        assert "parse_url(" in build_media_url_body

    def test_returns_null_type_hint(self, php_cmd_source: str) -> None:
        """
        Expected result:
        - the method is typed to return ?string
        """
        # Assert: nullable return type declared
        assert re.search(r"_buildFrigateMediaUrl\([^)]*\)\s*:\s*\?string", php_cmd_source)

    def test_userinfo_placeholder_template_form(self, build_media_url_body: str) -> None:
        """
        AC8 form 1: `https://<user>:<pass>@cameras.lehoux.net/`.

        Expected result:
        - api/events/{event_id}/snapshot.jpg inserted into the path; userinfo placeholders
          preserved verbatim (never resolved — siaDC09 doesn't know what they mean)
        """
        result = _run_build_frigate_media_url(
            build_media_url_body,
            "https://<user>:<pass>@cameras.lehoux.net/",
            "1790171912.267903-02fk1r",
        )
        # Assert: exact expected URL, placeholders untouched
        assert result == (
            "https://<user>:<pass>@cameras.lehoux.net/"
            "api/events/1790171912.267903-02fk1r/snapshot.jpg"
        )

    def test_query_token_placeholder_template_form(self, build_media_url_body: str) -> None:
        """
        AC8 form 2: `https://cameras.lehoux.net/?accesstoken=<token>` — the inserted path
        MUST land before the query string, not after it (a naive string concatenation would
        strand the new path segment after the '?', breaking the URL).

        Expected result:
        - path inserted before the query string; token stays at the very end of the URL
        """
        result = _run_build_frigate_media_url(
            build_media_url_body,
            "https://cameras.lehoux.net/?accesstoken=<token>",
            "1790171912.267903-02fk1r",
        )
        # Assert: query string relocated to the end, after the inserted path
        assert result == (
            "https://cameras.lehoux.net/api/events/1790171912.267903-02fk1r/snapshot.jpg"
            "?accesstoken=<token>"
        )

    def test_no_double_slash_when_template_path_has_no_trailing_slash(
        self, build_media_url_body: str
    ) -> None:
        """
        Expected result:
        - a template with no trailing slash (bare host) doesn't produce a double slash
        """
        result = _run_build_frigate_media_url(build_media_url_body, "https://cameras.lehoux.net", "abc123")
        # Assert: single slash between host and path
        assert result == "https://cameras.lehoux.net/api/events/abc123/snapshot.jpg"

    def test_missing_scheme_returns_null(self, build_media_url_body: str) -> None:
        """
        Expected result:
        - a template with no scheme (e.g. a bare hostname) returns null, never a malformed URL
        """
        result = _run_build_frigate_media_url(build_media_url_body, "cameras.lehoux.net", "abc123")
        # Assert: defensive null, no exception, no partial URL
        assert result is None

    def test_empty_template_returns_null(self, build_media_url_body: str) -> None:
        """
        Expected result:
        - an empty/unset template returns null
        """
        result = _run_build_frigate_media_url(build_media_url_body, "", "abc123")
        # Assert: defensive null
        assert result is None

    def test_event_id_is_url_encoded(self, build_media_url_body: str) -> None:
        """
        Defensive: an event_id containing characters that need escaping doesn't produce a
        broken URL (Frigate event ids are normally safe, but the builder must not assume).

        Expected result:
        - special characters in event_id are percent-encoded in the resulting path
        """
        result = _run_build_frigate_media_url(build_media_url_body, "https://host/", "a b/c")
        # Assert: space and slash inside event_id are escaped, not left raw
        assert result == "https://host/api/events/a%20b%2Fc/snapshot.jpg"


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
    both info_detect_person and info_id on the same equipment (Task 1.2, swapped from
    info_url_snapshot to info_id in Task 6 — same majEventsCmds() sweep, and this filter
    must stay consistent with what the resolver actually reads)."""

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

    def test_filters_by_info_detect_person_and_info_id(self, get_frigate_cameras_body: str) -> None:
        """
        Expected result:
        - candidates are filtered to those whose equipment also has both
          info_detect_person and info_id (the Frigate-specific signal)
        """
        # Assert: precise filter beyond the generic CAMERA_TAKE tag, scoped per-equipment
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_detect_person['\"]", get_frigate_cameras_body)
        assert re.search(r"byEqLogicIdAndLogicalId\([^;]*['\"]info_id['\"]", get_frigate_cameras_body)
        # Assert: the unscoped, array-returning byLogicalId() is never used here either
        assert "byLogicalId(" not in get_frigate_cameras_body

    def test_never_filters_by_info_url_snapshot(self, get_frigate_cameras_body: str) -> None:
        """
        Task 6: info_url_snapshot is never read anywhere in siaDC09 any more.

        Expected result:
        - info_url_snapshot is never referenced in this action either
        """
        # Assert: consistent with the resolver — the Jeedom-cached path is unused everywhere
        assert "info_url_snapshot" not in get_frigate_cameras_body

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
