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
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

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
def resolve_clip_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_resolveFrigateClipUrl")


@pytest.fixture(scope="module")
def build_media_url_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_buildFrigateMediaUrl")


def _run_build_frigate_media_url(
    build_media_url_body: str,
    template: str,
    event_id: str,
    media_file: str | None = None,
) -> str | None:
    """Execute the REAL extracted _buildFrigateMediaUrl() body via `php`, no Jeedom bootstrap.

    The method is pure parse_url() string logic with zero Jeedom dependency (no cmd::, no
    log::, no $this), so its extracted source can run standalone — this verifies actual
    behavior for the tricky path-vs-query reassembly, not just that certain strings appear
    in the source text (the project's usual Level 1 PHP convention, which alone can't catch
    an ordering bug like this).

    Story 14-3: `media_file` is optional so existing two-argument callers (verifying the
    default stays 'snapshot.jpg') keep working unchanged; passing it exercises the new
    third parameter.
    """
    args = [template, event_id] if media_file is None else [template, event_id, media_file]
    call_args = ", ".join(f"$argv[{i + 1}]" for i in range(len(args)))
    harness = (
        "<?php\n"
        "function _test_build_frigate_media_url($template, $eventId, $mediaFile = 'snapshot.jpg') {\n"
        f"{build_media_url_body}\n"
        "}\n"
        f"echo json_encode(_test_build_frigate_media_url({call_args}));\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".php", delete=False) as f:
        f.write(harness)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ["php", tmp_path, *args],
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
    """Story 14-2 (ADR-17 Amendment 3 / Option D): the resolver reads the daemon's Frigate
    REST prefetch outcome from a Jeedom-side cache (sia_prefetch_cache), keyed by
    camera_eqlogic_id — never info_detect_person/info_id/info_label/info_url_snapshot again,
    since those were the exact data source that made Option A untenable (staleness, no label
    filter). Builds media_url from the configured template exactly as before (Task 6, unchanged)."""

    def test_reads_frigate_camera_eqlogic_id(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the zone entry's frigate_camera_eqlogic_id field is read
        """
        # Assert: new simplified schema field is read
        assert "frigate_camera_eqlogic_id" in resolve_snapshot_body

    def test_reads_prefetch_cache_keyed_by_eqlogic_id(self, resolve_snapshot_body: str) -> None:
        """
        Expected result:
        - the eqLogic's sia_prefetch_cache is read via getCache()
        - the cache entry is indexed by the camera's eqLogic id
        """
        # Assert: reads the Jeedom-side cache written by siaDC09::_handlePrefetchResult()
        assert "getCache('sia_prefetch_cache'" in resolve_snapshot_body
        # Assert: entry lookup is keyed by the camera eqLogic id, not by zone name or anything else
        assert re.search(r"\$cache\[\s*\(int\)\s*\$eqLogicId\s*\]", resolve_snapshot_body)

    def test_checks_found_flag_and_ttl(self, resolve_snapshot_body: str) -> None:
        """
        AC6: only a confirmed, non-expired hit resolves to a URL — a miss, a missing entry,
        or an expired entry must all resolve to null (no third fallback tier).

        Expected result:
        - the entry's 'found' key gates the result
        - the entry's age is compared against PREFETCH_CACHE_TTL
        """
        # Assert: found flag is checked before trusting the entry
        assert "'found'" in resolve_snapshot_body
        # Assert: TTL expiry is enforced
        assert "PREFETCH_CACHE_TTL" in resolve_snapshot_body

    def test_never_reads_info_detect_person_or_info_id(self, resolve_snapshot_body: str) -> None:
        """
        ADR-17 Amendment 3: info_detect_person (staleness) and info_id (no label filter,
        can be hijacked by any tracked object class) are the two confirmed problems that made
        Option A untenable — the resolver must never read either again.

        Expected result:
        - info_detect_person is never referenced in the resolver
        - info_id is never referenced in the resolver
        """
        # Assert: the superseded, problem-carrying data source is gone entirely
        assert "info_detect_person" not in resolve_snapshot_body
        assert "info_id" not in resolve_snapshot_body

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

    def test_media_file_param_defaults_to_snapshot_jpg(self, build_media_url_body: str) -> None:
        """
        Story 14-3, Task 5.1/5.4: the new third parameter must default to 'snapshot.jpg' so
        every pre-14-3 caller (_resolveFrigateSnapshotUrl()'s two-argument call form) keeps
        its exact existing behavior unchanged.

        Expected result:
        - calling with only (template, event_id) — no third argument — still produces
          snapshot.jpg, identical to pre-14-3 behavior
        """
        result = _run_build_frigate_media_url(build_media_url_body, "https://host/", "abc123")
        # Assert: default trailing segment unchanged
        assert result == "https://host/api/events/abc123/snapshot.jpg"

    def test_media_file_param_substitutes_clip_mp4(self, build_media_url_body: str) -> None:
        """
        Story 14-3: passing 'clip.mp4' as the third argument (as _resolveFrigateClipUrl()
        does) must substitute it for the trailing path segment, everything else unchanged.

        Expected result:
        - the resulting URL ends in .../clip.mp4 instead of .../snapshot.jpg
        """
        result = _run_build_frigate_media_url(build_media_url_body, "https://host/", "abc123", "clip.mp4")
        # Assert: clip.mp4 substituted in place of the default snapshot.jpg
        assert result == "https://host/api/events/abc123/clip.mp4"

    def test_media_file_param_declared_in_signature(self, php_cmd_source: str) -> None:
        """
        Expected result:
        - _buildFrigateMediaUrl()'s signature declares the new $mediaFile parameter with a
          default of 'snapshot.jpg'
        """
        # Assert: new parameter present with the documented default
        assert re.search(
            r"_buildFrigateMediaUrl\([^)]*\$mediaFile\s*=\s*'snapshot\.jpg'[^)]*\)",
            php_cmd_source,
        )


class TestResolveFrigateClipUrlExists:
    """Story 14-3: _resolveFrigateClipUrl() is _resolveFrigateSnapshotUrl()'s sibling —
    same cache entry, same TTL rule, gated on 'clip_found' instead of 'found'."""

    def test_method_exists(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - _resolveFrigateClipUrl() is a real method with a non-empty body
        """
        # Assert: helper method present
        assert resolve_clip_body != ""

    def test_gates_on_clip_found_not_found(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - the method checks the cache entry's 'clip_found' key, not 'found'
        """
        # Assert: gated on the clip-specific flag
        assert "'clip_found'" in resolve_clip_body

    def test_reads_prefetch_cache_keyed_by_eqlogic_id(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - reads the same sia_prefetch_cache, keyed by the camera's eqLogic id — the same
          cache _resolveFrigateSnapshotUrl() reads, not a separate one
        """
        # Assert: same cache mechanism as the snapshot resolver
        assert "getCache('sia_prefetch_cache'" in resolve_clip_body
        assert re.search(r"\$cache\[\s*\(int\)\s*\$eqLogicId\s*\]", resolve_clip_body)

    def test_checks_ttl(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - the same PREFETCH_CACHE_TTL expiry rule is enforced (no independent clip TTL)
        """
        # Assert: TTL expiry enforced, same constant as the snapshot resolver
        assert "PREFETCH_CACHE_TTL" in resolve_clip_body

    def test_reads_media_url_template_config(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - reads the same frigate_media_url_template configuration key
        """
        # Assert: same configurable template, no new config field
        assert "frigate_media_url_template" in resolve_clip_body

    def test_calls_build_frigate_media_url_with_clip_mp4(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - delegates URL construction to _buildFrigateMediaUrl(), passing 'clip.mp4'
        """
        # Assert: URL reassembly delegated, with the clip-specific trailing segment
        assert re.search(r"_buildFrigateMediaUrl\([^)]*'clip\.mp4'", resolve_clip_body)

    def test_wrapped_in_try_catch(self, resolve_clip_body: str) -> None:
        """
        Expected result:
        - the whole method body is guarded by try/catch (AC5: never blocks or throws)
        """
        # Assert: defensive wrapping present
        assert "try" in resolve_clip_body
        assert "catch" in resolve_clip_body

    def test_returns_null_type_hint(self, php_cmd_source: str) -> None:
        """
        Expected result:
        - the method is typed to return ?string (nullable)
        """
        # Assert: nullable return type declared
        assert re.search(r"_resolveFrigateClipUrl\([^)]*\)\s*:\s*\?string", php_cmd_source)


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


# ── Story 14-3 — execute()'s burglarAlarm case: real-execution AC5 cache-state matrix ──
#
# Executes the REAL core/class/siaDC09Cmd.class.php via `php`, Jeedom replaced by minimal
# stubs, following the exact precedent of tests/level1/test_burglary_cancel_behavior.py —
# this is what actually reaches the daemon payload, not just source-text shape.

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

_EXECUTE_STUBS = r"""
class log {
    public static array $entries = [];
    public static function add($plugin, $level, $message): void {
        self::$entries[] = ['level' => $level, 'message' => $message];
    }
}

function __($text, $file = '') {
    return $text;
}

class FakeEqLogic {
    public array $cache;
    private array $config;
    public function __construct(array $cache, array $config) {
        $this->cache = $cache;
        $this->config = $config;
    }
    public function getCache($key, $default = null) {
        return $this->cache[$key] ?? $default;
    }
    public function setCache($key, $value): void {
        $this->cache[$key] = $value;
    }
    public function getConfiguration($key, $default = null) {
        return $this->config[$key] ?? $default;
    }
}

class cmd {
    public string $logicalId = '';
    public ?FakeEqLogic $eqLogic = null;
    public function getLogicalId() {
        return $this->logicalId;
    }
    public function getEqLogic() {
        return $this->eqLogic;
    }
}

class siaDC09 {
    public static array $sent = [];
    public static function sendToDaemon(array $params): void {
        self::$sent[] = $params;
    }
}
"""

_EXECUTE_DRIVER = r"""
$scenario = json_decode(file_get_contents($argv[1]), true);
$config = ['sia_zone_mappings' => $scenario['zone_mappings']];
if (array_key_exists('template', $scenario) && $scenario['template'] !== null) {
    $config['frigate_media_url_template'] = $scenario['template'];
}
$eqLogic = new FakeEqLogic($scenario['cache'], $config);
$cmd = new siaDC09Cmd();
$cmd->logicalId = 'burglarAlarm';
$cmd->eqLogic = $eqLogic;
$cmd->execute(['title' => $scenario['zone']]);
echo json_encode(['sent' => siaDC09::$sent, 'logs' => log::$entries]);
"""


def _run_execute_burglar_alarm(
    cache: dict[str, Any],
    template: str | None = "https://cameras.lehoux.net/",
    zone: str = "Salon",
    camera_eqlogic_id: int = 99,
) -> dict[str, Any]:
    """Run one real execute(['title' => zone]) call for logicalId='burglarAlarm' and
    return the payload actually passed to siaDC09::sendToDaemon().

    Args:
        cache: the eqLogic's initial 'sia_prefetch_cache' content (keyed by
            camera_eqlogic_id, matching siaDC09::_handlePrefetchResult()'s write shape).
        template: frigate_media_url_template configuration value, or None to leave it
            unconfigured (both resolvers must then return null).
        zone: the zone label passed as the action's #zone# title.
        camera_eqlogic_id: the zone mapping's frigate_camera_eqlogic_id.

    Returns:
        {"sent": [payloads passed to sendToDaemon()], "logs": [{"level", "message"}]}
    """
    source = PHP_CMD_FILE.read_text(encoding="utf-8")
    source = source.replace("<?php", "", 1)
    source = re.sub(r"^require_once .*core\.inc\.php';\s*$", "", source, count=1, flags=re.MULTILINE)
    scenario = {
        "zone": zone,
        "zone_mappings": [
            {"zone_name": zone, "zone_number": 3, "frigate_camera_eqlogic_id": camera_eqlogic_id}
        ],
        "cache": {"sia_prefetch_cache": {str(camera_eqlogic_id): cache} if cache else {}},
        "template": template,
    }
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.php"
        harness.write_text(
            "<?php\n" + _EXECUTE_STUBS + source + _EXECUTE_DRIVER,
            encoding="utf-8",
        )
        scenario_file = Path(tmp) / "scenario.json"
        scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            ["php", str(harness), str(scenario_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert result.returncode == 0, f"PHP execution failed: {result.stderr}\n{result.stdout}"
    return json.loads(result.stdout)


def _fresh_entry(found: bool, clip_found: bool, event_id: str = "evt-1", age_s: int = 0) -> dict[str, Any]:
    return {
        "found": found,
        "clip_found": clip_found,
        "event_id": event_id,
        "ts": int(time.time()) - age_s,
    }


class TestExecuteBurglarAlarmMediaUrlJoin:
    """Story 14-3, AC4/AC5: execute()'s burglarAlarm case reads the cached entry once and
    resolves both snapshot and clip URLs, joining with a single space when both resolve —
    six cache-state combinations, matching 14-1's AC5 / 14-2's AC7 life-safety framing
    (never blocks or throws regardless of clip-cache state)."""

    def test_both_resolve_space_joined_single_string(self) -> None:
        """
        Expected result:
        - media_url is one string, snapshot URL then clip URL, space-separated
        """
        out = _run_execute_burglar_alarm(_fresh_entry(found=True, clip_found=True))
        # Assert: exactly one sendToDaemon() call, with both URLs space-joined in order
        assert out["sent"][0]["media_url"] == (
            "https://cameras.lehoux.net/api/events/evt-1/snapshot.jpg "
            "https://cameras.lehoux.net/api/events/evt-1/clip.mp4"
        )

    def test_snapshot_only_when_clip_not_found(self) -> None:
        """
        Expected result:
        - media_url carries only the snapshot URL when clip_found is false
        """
        out = _run_execute_burglar_alarm(_fresh_entry(found=True, clip_found=False))
        # Assert: single URL, snapshot only
        assert out["sent"][0]["media_url"] == "https://cameras.lehoux.net/api/events/evt-1/snapshot.jpg"

    def test_clip_only_when_snapshot_not_found(self) -> None:
        """
        Expected result:
        - media_url carries only the clip URL when found is false but clip_found is true
          (an inconsistent-looking but structurally possible cache state — the resolver
          must not assume one implies the other)
        """
        out = _run_execute_burglar_alarm(_fresh_entry(found=False, clip_found=True))
        # Assert: single URL, clip only
        assert out["sent"][0]["media_url"] == "https://cameras.lehoux.net/api/events/evt-1/clip.mp4"

    def test_neither_resolves_media_url_key_entirely_absent(self) -> None:
        """
        Expected result:
        - the 'media_url' key is entirely absent from the payload — never present as null
        """
        out = _run_execute_burglar_alarm(_fresh_entry(found=False, clip_found=False))
        # Assert: key omitted entirely, matching the unchanged 14-1/14-2 fallback contract
        assert "media_url" not in out["sent"][0]

    def test_stale_pre_14_3_cache_entry_missing_clip_found_key(self) -> None:
        """
        A pre-14-3 cache entry never had a 'clip_found' key at all — the clip resolver
        must treat its absence the same as false (never crash on a legacy/partial shape).

        Expected result:
        - clip resolves to null (media_url carries only the snapshot URL); no crash,
          no PHP warning-level log about an undefined key
        """
        legacy_entry = {"found": True, "event_id": "evt-1", "ts": int(time.time())}
        out = _run_execute_burglar_alarm(legacy_entry)
        # Assert: snapshot alone, clip silently absent
        assert out["sent"][0]["media_url"] == "https://cameras.lehoux.net/api/events/evt-1/snapshot.jpg"
        # Assert: no crash surfaced as a warning-level log entry
        assert not [e for e in out["logs"] if e["level"] == "error"]

    def test_expired_entry_resolves_neither(self) -> None:
        """
        Expected result:
        - an entry older than PREFETCH_CACHE_TTL resolves to neither URL, media_url absent
        """
        out = _run_execute_burglar_alarm(_fresh_entry(found=True, clip_found=True, age_s=999))
        # Assert: both expired, key omitted entirely
        assert "media_url" not in out["sent"][0]

    def test_never_throws_regardless_of_cache_state(self) -> None:
        """
        Life-safety framing (14-1 AC5 / 14-2 AC7): execute()'s burglarAlarm case must never
        block or throw regardless of clip-cache state — exercised across the full matrix.

        Expected result:
        - every scenario returns cleanly (php exits 0) and always sends exactly one frame
        """
        scenarios = [
            _fresh_entry(found=True, clip_found=True),
            _fresh_entry(found=True, clip_found=False),
            _fresh_entry(found=False, clip_found=True),
            _fresh_entry(found=False, clip_found=False),
            {"found": True, "event_id": "evt-1", "ts": int(time.time())},  # legacy shape
            {},  # empty/malformed entry
        ]
        for entry in scenarios:
            out = _run_execute_burglar_alarm(entry)
            # Assert: exactly one frame sent, no exception surfaced (php returncode already
            # asserted inside _run_execute_burglar_alarm)
            assert len(out["sent"]) == 1, f"expected exactly one frame for entry={entry!r}"

    def test_entry_carrying_run_id_and_rank_resolves_unaffected(self) -> None:
        """
        Story 14-4 (ADR-17 Amendment 4) AC11: burglarAlarm's send path is unchanged in
        shape — a cache entry that now also carries 'run_id' and 'rank' (written by
        _handlePrefetchResult()'s new monotonic-replace rule) must resolve exactly the
        same media_url as before; the extra fields are simply ignored by the resolvers.

        Expected result:
        - media_url resolves both URLs, space-joined, exactly as with a 14-3-shaped entry
        """
        entry = _fresh_entry(found=True, clip_found=True)
        entry["run_id"] = "1790193160.123456"
        entry["rank"] = 1
        out = _run_execute_burglar_alarm(entry)
        # Assert: unaffected by the two new fields
        assert out["sent"][0]["media_url"] == (
            "https://cameras.lehoux.net/api/events/evt-1/snapshot.jpg "
            "https://cameras.lehoux.net/api/events/evt-1/clip.mp4"
        )
