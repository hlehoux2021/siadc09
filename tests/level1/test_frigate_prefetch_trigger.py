"""
PHP source-validation tests for Story 14.2, Task 2 — the `prefetchEvent` trigger side.

Parses core/class/siaDC09Cmd.class.php to verify execute()'s `prefetchEvent` case resolves
the zone's mapped camera's Frigate-native name and the Frigate server's host:port without
ever reading a new siaDC09 config field for either, sends a fire-and-forget message to the
daemon, and never blocks or throws regardless of camera/plugin state.

Reference: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md
Reference: ADR-17, Amendment 3, _bmad-output/planning-artifacts/architecture.md
"""
import re
from pathlib import Path

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
          camera_name, frigate_host
        """
        # Assert: fire-and-forget payload carries all fields the daemon needs
        assert "'cmd'" in prefetch_case_body and "'prefetchEvent'" in prefetch_case_body
        assert "'camera_eqlogic_id'" in prefetch_case_body
        assert "'camera_name'" in prefetch_case_body
        assert "'frigate_host'" in prefetch_case_body
        # Assert: uses the existing fire-and-forget transport, no new IPC primitive
        assert "siaDC09::sendToDaemon(" in prefetch_case_body


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
