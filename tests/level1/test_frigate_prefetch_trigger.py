"""
PHP source-validation tests for Story 14.2, Task 2 — the `prefetchEvent` trigger side.

Parses core/class/siaDC09Cmd.class.php to verify execute()'s `prefetchEvent` case resolves
the zone's mapped camera's Frigate-native name and the Frigate server's host:port without
ever reading a new siaDC09 config field for either, sends a fire-and-forget message to the
daemon, and never blocks or throws regardless of camera/plugin state.

Reference: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md
Reference: ADR-17, Amendment 3, _bmad-output/planning-artifacts/architecture.md
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PHP_CMD_FILE = _PROJECT_ROOT / "core/class/siaDC09Cmd.class.php"


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


def _extract_case_block(execute_body: str, case_label: str, next_case_label: str) -> str:
    """Extract a `case '<case_label>':` block up to (not including) the next case label."""
    start = execute_body.index(f"case '{case_label}'")
    end = execute_body.index(f"case '{next_case_label}'", start)
    return execute_body[start:end]


@pytest.fixture(scope="module")
def php_cmd_source() -> str:
    return PHP_CMD_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def execute_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "execute")


@pytest.fixture(scope="module")
def prefetch_case_body(execute_body: str) -> str:
    return _extract_case_block(execute_body, "prefetchEvent", "burglarAlarm")


@pytest.fixture(scope="module")
def resolve_target_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_resolvePrefetchTarget")


class TestPrefetchEventCase:
    """execute()'s new `prefetchEvent` case — Task 2.1/2.3."""

    def test_case_exists(self, execute_body: str) -> None:
        """
        Expected result:
        - a `case 'prefetchEvent':` block is present in execute()
        """
        # Assert: the new case label is present
        assert "case 'prefetchEvent'" in execute_body

    def test_guards_against_unsubstituted_zone_tag(self, prefetch_case_body: str) -> None:
        """
        Code review finding (2026-09-24): the alarm plugin might fail to substitute #zone#
        into the Titre field (wrong action type, templating change) — the literal string
        "#zone#" would otherwise fall through to the generic "zone not mapped" warning,
        masking the real cause.

        Expected result:
        - the case explicitly checks for the literal '#zone#' string and logs a distinct
          diagnostic before falling through to zone-mapping resolution
        """
        # Assert: explicit guard against the unsubstituted tag, not just an empty string
        assert "'#zone#'" in prefetch_case_body
        # Assert: the guard breaks before reaching zone-mapping resolution
        guard_pos = prefetch_case_body.index("'#zone#'")
        resolve_pos = prefetch_case_body.index("_findZoneEntry(")
        assert guard_pos < resolve_pos

    def test_case_is_separate_from_alarm_cases(self, prefetch_case_body: str) -> None:
        """
        The prefetchEvent case must not fall through into or share code with the
        burglarAlarm/fireAlarm/panicAlarm case (different payload shape, no zone-number
        resolution, no _recordOpenAlarm() call).

        Expected result:
        - _recordOpenAlarm is never called from the prefetchEvent case
        - _resolveZoneNumber is never called from the prefetchEvent case
        """
        # Assert: no open-alarm bookkeeping in the prefetch path
        assert "_recordOpenAlarm(" not in prefetch_case_body
        # Assert: zone_number resolution (irrelevant to a prefetch trigger) is not duplicated here
        assert "_resolveZoneNumber(" not in prefetch_case_body

    def test_resolves_zone_entry_before_sending(self, prefetch_case_body: str) -> None:
        """
        Expected result:
        - the case resolves the zone entry via the existing helpers, reused as-is
        """
        # Assert: reuses the existing zone-lookup helpers rather than duplicating logic
        assert "_findZoneEntry(" in prefetch_case_body
        assert "_getZoneMapping(" in prefetch_case_body

    def test_calls_resolve_prefetch_target(self, prefetch_case_body: str) -> None:
        """
        Expected result:
        - _resolvePrefetchTarget() is called with the resolved zone entry
        """
        # Assert: the new resolver is invoked
        assert "_resolvePrefetchTarget(" in prefetch_case_body

    def test_send_is_conditional_on_target_not_null(self, prefetch_case_body: str) -> None:
        """
        A camera with no Frigate config/host resolvable must never reach sendToDaemon() —
        AC2's "logs a warning and returns — no send" contract. Implemented as an early
        `break` on a null target (with a diagnostic warning log), so sendToDaemon() is only
        ever reached in the fall-through path once $target is known non-null.

        Expected result:
        - a null-target check exists, followed by a `break` before sendToDaemon() is called
        - sendToDaemon() appears textually after that guard
        """
        # Assert: a null-target guard exists and short-circuits via break
        guard = re.search(r"if\s*\(\s*\$target\s*===\s*null\s*\)\s*\{[^}]*break;", prefetch_case_body)
        assert guard, "sendToDaemon() call must be guarded by an early-return null check on the resolved target"
        # Assert: sendToDaemon is only reached after the guard, never before it
        assert prefetch_case_body.index("siaDC09::sendToDaemon(") > guard.end()

    def test_sends_cmd_and_camera_fields_to_daemon(self, prefetch_case_body: str) -> None:
        """
        Expected result:
        - the payload sent to the daemon carries cmd=prefetchEvent, camera_eqlogic_id,
          camera_name, frigate_host, run_id (Story 14-4)
        """
        # Assert: fire-and-forget payload carries all fields the daemon needs
        assert "'cmd'" in prefetch_case_body and "'prefetchEvent'" in prefetch_case_body
        assert "'camera_eqlogic_id'" in prefetch_case_body
        assert "'camera_name'" in prefetch_case_body
        assert "'frigate_host'" in prefetch_case_body
        assert "'run_id'" in prefetch_case_body
        # Assert: uses the existing fire-and-forget transport, no new IPC primitive
        assert "siaDC09::sendToDaemon(" in prefetch_case_body

    def test_run_id_generated_via_microtime(self, prefetch_case_body: str) -> None:
        """
        Story 14-4 (ADR-17 Amendment 4, R2): run_id is generated here, by the process that
        owns the cache, as a numeric string — no clock-sync question with the daemon.

        Expected result:
        - runId is assigned from (string) microtime(true)
        """
        # Assert: the documented generation shape
        assert re.search(r"\$runId\s*=\s*\(string\)\s*microtime\(true\)", prefetch_case_body)

    def test_placeholder_written_before_send_to_daemon(self, prefetch_case_body: str) -> None:
        """
        Story 14-4 AC8: the placeholder cache entry must be written BEFORE sendToDaemon()
        is called, so a create call that never gets a callback still can't leave a stale
        hit sitting in the cache.

        Expected result:
        - _writePrefetchPlaceholder(...) is called, and it appears textually before
          siaDC09::sendToDaemon(...)
        """
        # Assert: both calls present, in the required order
        assert "_writePrefetchPlaceholder(" in prefetch_case_body
        assert prefetch_case_body.index("_writePrefetchPlaceholder(") < prefetch_case_body.index(
            "siaDC09::sendToDaemon("
        )

    def test_placeholder_not_written_on_any_early_return_path(self, execute_body: str) -> None:
        """
        Story 14-4: an empty zone, an unsubstituted '#zone#' tag, or an unresolved target
        must never write a placeholder — there is no run to protect the cache for.

        Expected result:
        - _writePrefetchPlaceholder(...) appears exactly once in execute() (the single
          call site, after target resolution, not duplicated on any early-return path)
        """
        # Assert: the placeholder write is the one and only call site
        assert execute_body.count("_writePrefetchPlaceholder(") == 1


class TestResolvePrefetchTarget:
    """_resolvePrefetchTarget() — Task 2.2."""

    def test_method_exists(self, resolve_target_body: str) -> None:
        """
        Expected result:
        - _resolvePrefetchTarget() is defined
        """
        # Assert: method body is non-empty (found by the fixture's brace-tracking extractor)
        assert resolve_target_body.strip() != ""

    def test_reads_frigate_camera_eqlogic_id(self, resolve_target_body: str) -> None:
        """
        Expected result:
        - the method reads frigate_camera_eqlogic_id from the zone entry (reused as-is
          from story 14-1/8-2, never a new mapping field)
        """
        # Assert: same zone-mapping key story 14-1 already established
        assert "frigate_camera_eqlogic_id" in resolve_target_body

    def test_reads_camera_name_from_configuration_not_get_name(self, resolve_target_body: str) -> None:
        """
        Confirmed against the Frigate plugin's own source: the Frigate-native camera slug is
        stored as getConfiguration('name') (frigate.class.php:1803), set once at camera
        creation — never getName(), which may carry a " by frigate plugin" suffix and is not
        guaranteed to equal the slug used by Frigate's own REST/MQTT topics.

        Expected result:
        - getConfiguration('name', ...) is called on the resolved camera eqLogic
        """
        # Assert: reads the Frigate-native slug from configuration, not the display name
        assert "getConfiguration('name'" in resolve_target_body or 'getConfiguration("name"' in resolve_target_body

    def test_never_stores_camera_name_in_new_sia_config_field(self, resolve_target_body: str) -> None:
        """
        Confirmed via repo-wide investigation this session: neither the Frigate camera's
        native name nor the Frigate server's host:port is stored anywhere in siaDC09's own
        config today, and both are already available cross-plugin — no new wizard field
        should be introduced for either.

        Expected result:
        - no siaDC09-specific config key like 'frigate_camera_name' or 'frigate_host' is
          read from $this->getEqLogic()->getConfiguration(...) (that would mean a new,
          unnecessary wizard field was added instead of reading the Frigate plugin's own data)
        """
        # Assert: no new siaDC09 config field invented for data that already exists cross-plugin
        assert "getConfiguration('frigate_camera_name'" not in resolve_target_body
        assert "getConfiguration('frigate_host'" not in resolve_target_body

    def test_reads_frigate_host_from_frigate_global_config(self, resolve_target_body: str) -> None:
        """
        Confirmed against the Frigate plugin's own source: host/port are its global config
        keys 'URL' and 'port' under the 'frigate' plugin id — read directly via config::byKey(),
        deliberately not by calling \\frigate::getUrlFrigate() (which would add a hard class
        dependency on a plugin that may be absent or disabled).

        Expected result:
        - config::byKey('URL', 'frigate', ...) and config::byKey('port', 'frigate', ...) are
          both called
        - \\frigate::getUrlFrigate() is never called
        """
        # Assert: reads Frigate's own global config directly, plugin-agnostic API
        assert "config::byKey('URL', 'frigate'" in resolve_target_body
        assert "config::byKey('port', 'frigate'" in resolve_target_body
        # Assert: no hard class dependency on the Frigate plugin's own class
        assert "frigate::getUrlFrigate(" not in resolve_target_body
        assert "\\frigate::" not in resolve_target_body

    def test_wrapped_in_try_catch(self, resolve_target_body: str) -> None:
        """
        Same life-safety framing as _resolveFrigateSnapshotUrl() (14-1 AC5) — a misconfigured
        or absent Frigate camera/plugin must never throw from the alarm-trigger path.

        Expected result:
        - the method body is wrapped in try/catch (\\Throwable $e)
        """
        # Assert: defensive try/catch present
        assert "try {" in resolve_target_body
        assert "catch (\\Throwable" in resolve_target_body or "catch (Throwable" in resolve_target_body

    def test_returns_null_type_hint(self, php_cmd_source: str) -> None:
        """
        Expected result:
        - the method signature declares a nullable array return type
        """
        # Assert: ?array return type declared
        assert re.search(r"_resolvePrefetchTarget\([^)]*\)\s*:\s*\?array", php_cmd_source)


# ── Story 14-4 — real-execution: run_id + placeholder cache write ───────────────
#
# Executes the REAL core/class/siaDC09Cmd.class.php via `php`, following the exact
# precedent of tests/level1/test_frigate_snapshot_resolution.py's
# `_run_execute_burglar_alarm()` — this is what actually reaches the daemon payload and
# the Jeedom-side cache, not just source-text shape.

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

_EXECUTE_STUBS = r"""
class log {
    public static array $entries = [];
    public static function add($plugin, $level, $message): void {
        self::$entries[] = ['level' => $level, 'message' => $message];
    }
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

class eqLogic {
    public static array $byId = [];
    public static function byId($id) {
        return self::$byId[(int) $id] ?? null;
    }
}

class config {
    public static array $values = [];
    public static function byKey($key, $plugin, $default = null) {
        return self::$values["$plugin.$key"] ?? $default;
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
config::$values = [
    'frigate.URL'  => $scenario['frigate_url'],
    'frigate.port' => $scenario['frigate_port'],
];
eqLogic::$byId = [
    $scenario['camera_eqlogic_id'] => new FakeEqLogic([], ['name' => $scenario['camera_name']]),
];
$siaEqLogic = new FakeEqLogic($scenario['initial_cache'], [
    'sia_zone_mappings' => $scenario['zone_mappings'],
]);
$cmd = new siaDC09Cmd();
$cmd->logicalId = 'prefetchEvent';
$cmd->eqLogic = $siaEqLogic;
$cmd->execute(['title' => $scenario['zone']]);
echo json_encode(['sent' => siaDC09::$sent, 'cache' => $siaEqLogic->cache, 'logs' => log::$entries]);
"""


def _run_execute_prefetch_event(
    zone: str = "Salon",
    camera_eqlogic_id: int = 42,
    camera_name: str = "vigi_sud-est",
    frigate_url: str = "192.168.100.18",
    frigate_port: str = "5000",
    initial_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one real execute(['title' => zone]) call for logicalId='prefetchEvent' and
    return the daemon payload plus the resulting Jeedom-side cache.

    Returns:
        {"sent": [payloads passed to sendToDaemon()], "cache": {...}, "logs": [...]}
    """
    source = PHP_CMD_FILE.read_text(encoding="utf-8")
    source = source.replace("<?php", "", 1)
    source = re.sub(r"^require_once .*core\.inc\.php';\s*$", "", source, count=1, flags=re.MULTILINE)
    scenario = {
        "zone": zone,
        "zone_mappings": [
            {"zone_name": zone, "zone_number": 3, "frigate_camera_eqlogic_id": camera_eqlogic_id}
        ],
        "camera_eqlogic_id": camera_eqlogic_id,
        "camera_name": camera_name,
        "frigate_url": frigate_url,
        "frigate_port": frigate_port,
        "initial_cache": {"sia_prefetch_cache": initial_cache} if initial_cache else {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.php"
        harness.write_text("<?php\n" + _EXECUTE_STUBS + source + _EXECUTE_DRIVER, encoding="utf-8")
        scenario_file = Path(tmp) / "scenario.json"
        scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            ["php", str(harness), str(scenario_file)], capture_output=True, text=True, timeout=10
        )
    assert result.returncode == 0, f"PHP execution failed: {result.stderr}\n{result.stdout}"
    return json.loads(result.stdout)


class TestExecutePrefetchEventRealRun:
    """Story 14-4, AC8: real execute()'s prefetchEvent case writes the placeholder and
    sends run_id, in that order, end to end."""

    def test_placeholder_present_in_cache_after_execute(self) -> None:
        """
        Expected result:
        - after execute(), the eqLogic's sia_prefetch_cache carries a placeholder entry
          for the resolved camera, with rank=4, found=false, event_id=null
        """
        result = _run_execute_prefetch_event(camera_eqlogic_id=42)
        entry = result["cache"]["sia_prefetch_cache"]["42"]
        # Assert: the placeholder shape
        assert entry["found"] is False
        assert entry["event_id"] is None
        assert entry["clip_found"] is False
        assert entry["rank"] == 4

    def test_placeholder_run_id_matches_sent_payload_run_id(self) -> None:
        """
        Expected result:
        - the run_id stored in the placeholder is exactly the run_id sent to the daemon —
          the same value, generated once
        """
        result = _run_execute_prefetch_event(camera_eqlogic_id=42)
        entry = result["cache"]["sia_prefetch_cache"]["42"]
        sent_run_id = result["sent"][0]["run_id"]
        # Assert: same run_id in both places
        assert entry["run_id"] == sent_run_id
        assert isinstance(sent_run_id, str) and sent_run_id != ""

    def test_placeholder_replaces_earlier_run_but_new_run_id_is_still_greater(self) -> None:
        """
        Expected result:
        - a placeholder written for a camera that already has an older entry stores a
          numerically greater run_id than the one that was there before
        """
        older_entry = {
            "found": True, "event_id": "evt-old", "clip_found": True, "rank": 1,
            "run_id": "1000.000000", "ts": 900,
        }
        result = _run_execute_prefetch_event(camera_eqlogic_id=42, initial_cache={"42": older_entry})
        entry = result["cache"]["sia_prefetch_cache"]["42"]
        # Assert: the placeholder overwrote the older entry with a numerically newer run_id
        assert entry["rank"] == 4
        assert entry["event_id"] is None
        assert float(entry["run_id"]) > float(older_entry["run_id"])

    def test_no_placeholder_or_send_when_target_unresolved(self) -> None:
        """
        Expected result:
        - when the Frigate global config (URL/port) is absent, no placeholder is written
          and no payload is sent
        """
        result = _run_execute_prefetch_event(frigate_url="", frigate_port="")
        # Assert: nothing sent, no cache entry created (an untouched cache round-trips as
        # an empty PHP array, decoded by json.loads() as either {} or [])
        assert result["sent"] == []
        assert "sia_prefetch_cache" not in result["cache"] or not result["cache"]["sia_prefetch_cache"]
