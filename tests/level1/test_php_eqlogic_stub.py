"""
PHP eqLogic & cmd source-validation tests for Stories 6.1, 6.2, 6.3, 6.4, and 8.2.

Parses core/class/siaDC09.class.php and core/class/siaDC09Cmd.class.php to
verify that the implementation matches the design specification. These tests
fail when logicalIds are renamed, the wrong equipment-lookup method is used,
or security guards are removed — they do not require a Jeedom instance.

Reference: _bmad-output/implementation-artifacts/6-1-php-eqlogic-cmd-classes.md
Reference: _bmad-output/implementation-artifacts/6-2-auto-equipment-creation.md
Reference: _bmad-output/implementation-artifacts/6-3-json-callback-ipc-protocol.md
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""
import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PHP_CLASS_FILE = _PROJECT_ROOT / "core/class/siaDC09.class.php"
PHP_CMD_FILE = _PROJECT_ROOT / "core/class/siaDC09Cmd.class.php"

# ── Spec constants ────────────────────────────────────────────────────────────

ACTION_LOGICAL_IDS: list[str] = ["burglarAlarm", "fireAlarm", "panicAlarm"]
INFO_LOGICAL_IDS: list[str] = [
    "supervision_state",
    "supervision_label",
    "event_state",
    "event_label",
]
ALL_LOGICAL_IDS: list[str] = ACTION_LOGICAL_IDS + INFO_LOGICAL_IDS
NUMERIC_INFO_IDS: list[str] = ["supervision_state", "event_state"]
STRING_INFO_IDS: list[str] = ["supervision_label", "event_label"]

# ── Helper ────────────────────────────────────────────────────────────────────


def _extract_method_body(source: str, method_name: str) -> str:
    """Extract the body of a named PHP method by tracking brace depth.

    Finds the method by name, skips past the parameter list by counting
    parentheses, then extracts everything between the opening and matching
    closing brace of the method body.
    """
    match = re.search(rf"function\s+{re.escape(method_name)}\s*\(", source)
    if not match:
        return ""
    # Walk past the parameter list using paren counting
    pos = match.end() - 1  # position of '('
    depth = 1
    i = pos + 1
    while i < len(source) and depth > 0:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
        i += 1
    # Find the opening brace of the method body
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


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def php_source() -> str:
    return PHP_CLASS_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def php_cmd_source() -> str:
    return PHP_CMD_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def postsave_body(php_source: str) -> str:
    return _extract_method_body(php_source, "postSave")


@pytest.fixture(scope="module")
def deamon_start_body(php_source: str) -> str:
    return _extract_method_body(php_source, "deamon_start")


@pytest.fixture(scope="module")
def deamon_info_body(php_source: str) -> str:
    return _extract_method_body(php_source, "deamon_info")


@pytest.fixture(scope="module")
def action_cmds_loop_body(postsave_body: str) -> str:
    """The foreach ($actionCmds ...) block only, excluding the info cmds loop."""
    start = postsave_body.index("foreach ($actionCmds")
    end = postsave_body.index("foreach ($infoCmds")
    return postsave_body[start:end]


@pytest.fixture(scope="module")
def info_cmds_loop_body(postsave_body: str) -> str:
    """The foreach ($infoCmds ...) block only (the last statement in postSave())."""
    start = postsave_body.index("foreach ($infoCmds")
    return postsave_body[start:]


@pytest.fixture(scope="module")
def get_auto_equipment_body(php_source: str) -> str:
    # _getAutoEquipmentSafe ends with 'Safe(' so \s*\( won't match it
    return _extract_method_body(php_source, "_getAutoEquipment")


@pytest.fixture(scope="module")
def execute_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "execute")


@pytest.fixture(scope="module")
def fan_out_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "_fanOutBurglaryCancel")


@pytest.fixture(scope="module")
def run_notify_target_body(php_source: str) -> str:
    """Single entry point for critical notifications — every caller delegates here."""
    return _extract_method_body(php_source, "_runNotifyTarget")


@pytest.fixture(scope="module")
def has_notify_target_body(php_source: str) -> str:
    """Guard helper: tells deamon_info() whether step 4 left a usable alert target."""
    return _extract_method_body(php_source, "_hasNotifyTarget")


# ── Story 6.1 — File existence ────────────────────────────────────────────────


def test_eqlogic_php_file_exists() -> None:
    """
    The eqLogic PHP class file exists at the expected path.

    Expected result:
    - core/class/siaDC09.class.php is present before any parsing tests run
    """
    # Assert: eqLogic source file is present
    assert PHP_CLASS_FILE.exists(), f"PHP class file not found: {PHP_CLASS_FILE}"


def test_cmd_php_file_exists() -> None:
    """
    The cmd PHP class file exists as a separate file (Jeedom convention).

    Expected result:
    - core/class/siaDC09Cmd.class.php is present and separate from eqLogic
    """
    # Assert: cmd class is a separate file (not merged into eqLogic)
    assert PHP_CMD_FILE.exists(), f"PHP cmd file not found: {PHP_CMD_FILE}"


# ── Story 6.1 — postSave() command contract ───────────────────────────────────


def test_all_seven_logical_ids_in_postsave(postsave_body: str) -> None:
    """
    postSave() must reference exactly the 7 agreed logicalIds as string literals.
    Any rename in postSave() breaks the PHP↔daemon JSON contract.

    Expected result:
    - All 7 logicalIds appear as quoted strings inside the postSave() body
    """
    for logical_id in ALL_LOGICAL_IDS:
        # Assert: each logicalId is hardcoded as a quoted string in postSave()
        assert f"'{logical_id}'" in postsave_body, (
            f"logicalId '{logical_id}' not found in postSave() — rename or deletion detected"
        )


def test_action_commands_use_message_subtype(postsave_body: str) -> None:
    """
    Action commands use 'message' subType so Jeedom passes the title field
    containing #zone# substitution to siaDC09Cmd::execute().

    Expected result:
    - 'message' appears as a subType value in the action command spec block
    - All three action logicalIds are present in postSave()
    """
    # Assert: 'message' subtype is declared for action commands
    assert "'message'" in postsave_body, (
        "subType 'message' not found in postSave() — action command contract broken"
    )
    for logical_id in ACTION_LOGICAL_IDS:
        # Assert: each action logicalId is present
        assert f"'{logical_id}'" in postsave_body, (
            f"Action command '{logical_id}' missing from postSave()"
        )


def test_prefetch_event_command_uses_message_subtype(postsave_body: str) -> None:
    """
    Story 14-2 (ADR-17 Amendment 3 / Option D): prefetchEvent is a new action
    command, auto-created alongside burglarAlarm/fireAlarm/panicAlarm, wired
    manually by the installer into the alarm plugin's immediate-actions
    bucket. It MUST use subType 'message', not 'other': the alarm plugin only
    exposes a *Titre* field (where #zone# gets substituted into
    $_options['title']) for 'message'-subtype action commands
    (docs/design/php-core-design.md:1264) — 'other' has no options field at
    all, so the zone would never reach execute(). Confirmed as a real bug on
    the live host (2026-09-24): prefetchEvent fired but $_options['title']
    was always empty, so no camera could ever be resolved.

    Expected result:
    - 'prefetchEvent' is present in the $actionCmds array literal
    - it is declared with subType 'message', immediately followed by 'message'
      as its own subType value (not merely present elsewhere in the array)
    """
    # Scope to the $actionCmds array literal only (declared before the foreach loop)
    array_literal = postsave_body[: postsave_body.index("foreach ($actionCmds")]
    # Assert: prefetchEvent logicalId is declared in postSave()'s action array
    assert "'prefetchEvent'" in array_literal, (
        "logicalId 'prefetchEvent' not found in postSave() — command definition missing"
    )
    # Assert: prefetchEvent's own entry declares subType 'message' (not 'other') —
    # scoped to the single-line entry so this doesn't just match burglarAlarm's own
    # 'message' subType elsewhere in the same array literal.
    prefetch_entry = re.search(r"'prefetchEvent'\s*=>\s*\[[^\]]*\]", array_literal)
    assert prefetch_entry, "prefetchEvent entry not found as a single-line array literal"
    assert "'subType' => 'message'" in prefetch_entry.group(0), (
        "prefetchEvent must use subType 'message' — 'other' has no *Titre* field in the "
        "alarm plugin's action UI, so #zone# could never reach execute()"
    )


def test_numeric_info_commands_use_numeric_subtype(postsave_body: str) -> None:
    """
    supervision_state and event_state use 'numeric' subType so Jeedom
    scenario triggers can compare integer threshold values.

    Expected result:
    - 'numeric' appears in the info command spec block
    - supervision_state and event_state logicalIds are present
    """
    # Assert: 'numeric' subtype is declared for state info commands
    assert "'numeric'" in postsave_body, (
        "subType 'numeric' not found in postSave() — numeric info command contract broken"
    )
    for logical_id in NUMERIC_INFO_IDS:
        # Assert: each numeric info command logicalId is present
        assert f"'{logical_id}'" in postsave_body, (
            f"Numeric info command '{logical_id}' missing from postSave()"
        )


def test_string_info_commands_use_string_subtype(postsave_body: str) -> None:
    """
    supervision_label and event_label use 'string' subType for human-readable
    state labels displayed in Jeedom widgets.

    Expected result:
    - 'string' appears in the info command spec block
    - supervision_label and event_label logicalIds are present
    """
    # Assert: 'string' subtype is declared for label info commands
    assert "'string'" in postsave_body, (
        "subType 'string' not found in postSave() — string info command contract broken"
    )
    for logical_id in STRING_INFO_IDS:
        # Assert: each string info command logicalId is present
        assert f"'{logical_id}'" in postsave_body, (
            f"String info command '{logical_id}' missing from postSave()"
        )


def test_postsave_does_not_restart_daemon(postsave_body: str) -> None:
    """
    postSave() must only create/verify commands — never restart the daemon.
    Design decision: config changes take effect on next manual daemon start.
    Restarting in postSave() would cause unexpected service interruptions.

    Expected result:
    - 'deamon_stop' does not appear in the postSave() body
    - 'deamon_start' does not appear in the postSave() body
    """
    # Assert: daemon stop is not called from postSave (design invariant)
    assert "deamon_stop" not in postsave_body, (
        "postSave() must not call deamon_stop() — config changes apply on next daemon start"
    )
    # Assert: daemon start is not called from postSave (design invariant)
    assert "deamon_start" not in postsave_body, (
        "postSave() must not call deamon_start() — config changes apply on next daemon start"
    )


# ── Story 6.1 — Security guards in deamon_start() ────────────────────────────


def test_deamon_start_escapes_mandatory_string_configs(deamon_start_body: str) -> None:
    """
    User-supplied string config values passed to the shell command must be
    wrapped with escapeshellarg() to prevent command injection attacks.
    These four are mandatory and always present in the command string.

    Expected result:
    - escapeshellarg() wraps getConfiguration() for csr_ip, transport,
      account_number, and crc_format
    """
    mandatory_string_configs = ["csr_ip", "transport", "account_number", "crc_format"]
    for config_key in mandatory_string_configs:
        # Assert: each mandatory string config is passed through escapeshellarg
        assert (
            f"escapeshellarg($eqLogic->getConfiguration('{config_key}'" in deamon_start_body
        ), (
            f"Config key '{config_key}' not wrapped with escapeshellarg() in deamon_start() "
            f"— command injection risk"
        )


def test_encryption_key_redacted_before_logging(deamon_start_body: str) -> None:
    """
    The encryption key must never appear in logs. deamon_start() builds a
    sanitized copy of the command string via preg_replace before logging.

    Expected result:
    - '[REDACTED]' appears in the method body (preg_replace target)
    - log::add is called with the sanitized $cmdLog variable, not raw $cmd
    """
    # Assert: preg_replace redaction sentinel is present
    assert "[REDACTED]" in deamon_start_body, (
        "Encryption key redaction missing from deamon_start() — key would appear in logs"
    )
    # Assert: log::add uses $cmdLog (the sanitized variable), not bare $cmd
    assert re.search(r"log::add.*\$cmdLog", deamon_start_body, re.DOTALL), (
        "log::add in deamon_start() must reference $cmdLog (redacted copy), not $cmd"
    )


# ── Story 6.1 — siaDC09Cmd: execute() zone extraction ────────────────────────


def test_execute_handles_all_alarm_commands(execute_body: str) -> None:
    """
    execute() must handle all three alarm commands. Missing a case means
    that alarm type silently does nothing when triggered from Jeedom.

    Expected result:
    - 'burglarAlarm', 'fireAlarm', 'panicAlarm' all appear as case labels
    """
    for logical_id in ACTION_LOGICAL_IDS:
        # Assert: each alarm command appears as a switch case
        assert f"'{logical_id}'" in execute_body, (
            f"execute() missing case for '{logical_id}' — that alarm type will be silently ignored"
        )


def test_execute_extracts_zone_from_title(execute_body: str) -> None:
    """
    Zone name comes from $_options['title'] — the field where Jeedom substitutes
    the #zone# tag from the alarm plugin action command title.

    Expected result:
    - $_options['title'] is read in execute()
    - The result is sent to sendToDaemon() under the 'zone' key
    """
    # Assert: zone is read from the title option (not message or other keys)
    assert "$_options['title']" in execute_body, (
        "execute() must read zone from $_options['title'] — "
        "that is where Jeedom places the #zone# tag substitution"
    )
    # Assert: zone key is sent to the daemon
    assert "'zone'" in execute_body, (
        "execute() must send 'zone' key to sendToDaemon() — daemon uses it for SIA frame building"
    )


def test_execute_sends_cmd_key_to_daemon(execute_body: str) -> None:
    """
    The daemon dispatcher routes on the 'cmd' key to distinguish burglarAlarm
    from fireAlarm from panicAlarm. Missing it causes silent routing failure.

    Expected result:
    - 'cmd' key is included in the sendToDaemon() payload
    """
    # Assert: 'cmd' key is present in the sendToDaemon payload
    assert "'cmd'" in execute_body, (
        "execute() must include 'cmd' key in sendToDaemon payload — daemon routes on this"
    )


# ── Story 6.2 — Two-method equipment lookup contract ─────────────────────────


def test_get_auto_equipment_return_type_is_non_nullable(php_source: str) -> None:
    """
    _getAutoEquipment() always returns an equipment instance — it auto-creates
    one if missing. PHP return type must be 'self' (non-nullable), not '?self',
    so callers in deamon_start() can use the result without a null check.

    Expected result:
    - _getAutoEquipment() signature declares ': self' return type
    """
    match = re.search(
        r"function\s+_getAutoEquipment\s*\(\s*\)\s*:\s*(\??self)", php_source
    )
    # Assert: method exists with typed return
    assert match is not None, "_getAutoEquipment() method signature not found in PHP source"
    # Assert: return type is non-nullable self (not ?self)
    assert match.group(1) == "self", (
        f"_getAutoEquipment() return type is '{match.group(1)}', "
        f"expected 'self' — callers would need a null check they don't have"
    )


def test_get_auto_equipment_safe_return_type_is_nullable(php_source: str) -> None:
    """
    _getAutoEquipmentSafe() may return null when no equipment exists. PHP
    return type must be '?self' (nullable) so call sites in deamon_info()
    perform a null check before accessing config values.

    Expected result:
    - _getAutoEquipmentSafe() signature declares ': ?self' return type
    """
    match = re.search(
        r"function\s+_getAutoEquipmentSafe\s*\(\s*\)\s*:\s*(\??self)", php_source
    )
    # Assert: method exists with typed return
    assert match is not None, "_getAutoEquipmentSafe() method signature not found in PHP source"
    # Assert: return type is nullable ?self
    assert match.group(1) == "?self", (
        f"_getAutoEquipmentSafe() return type is '{match.group(1)}', "
        f"expected '?self' — null returns would be undetected by callers"
    )


def test_deamon_start_uses_auto_creating_method(deamon_start_body: str) -> None:
    """
    deamon_start() must use _getAutoEquipment() so equipment always exists
    when the daemon launches, even on first install (Story 6.2, AC5).
    Using _getAutoEquipmentSafe() here would cause a null-dereference on
    first launch before the user has manually created equipment.

    Expected result:
    - deamon_start() body contains a call to _getAutoEquipment()
    - deamon_start() body does NOT contain a call to _getAutoEquipmentSafe()
    """
    # Assert: auto-creating variant is called
    assert "_getAutoEquipment()" in deamon_start_body, (
        "deamon_start() must call _getAutoEquipment() to auto-create equipment on first launch"
    )
    # Assert: side-effect-free variant is NOT used (would return null on first launch)
    assert "_getAutoEquipmentSafe()" not in deamon_start_body, (
        "deamon_start() must not call _getAutoEquipmentSafe() — "
        "equipment would not be created and caller would get null"
    )


def test_deamon_info_uses_safe_method(deamon_info_body: str) -> None:
    """
    deamon_info() is called by Jeedom's health-check polling loop. It must
    use _getAutoEquipmentSafe() (no side effects) not _getAutoEquipment()
    (which writes to the DB on every poll if equipment is missing).

    Expected result:
    - deamon_info() body contains a call to _getAutoEquipmentSafe()
    - deamon_info() body does NOT contain a bare call to _getAutoEquipment()
    """
    # Assert: side-effect-free variant is used in the polling-safe method
    assert "_getAutoEquipmentSafe()" in deamon_info_body, (
        "deamon_info() must call _getAutoEquipmentSafe() — it runs in Jeedom's polling loop"
    )
    # Assert: auto-creating variant is NOT called (negative lookahead skips 'Safe' suffix)
    auto_creating_calls = re.findall(r"_getAutoEquipment(?!Safe)\s*\(\)", deamon_info_body)
    # Assert: no DB-writing variant found in the polling-loop method
    assert len(auto_creating_calls) == 0, (
        "deamon_info() must not call _getAutoEquipment() — "
        "it would write to the DB on every Jeedom health-check poll"
    )


def test_auto_create_logs_at_warning_level(get_auto_equipment_body: str) -> None:
    """
    When _getAutoEquipment() auto-creates missing equipment it logs at WARNING.
    Auto-creation is expected plugin behavior (not an error), but should be
    visible in logs so admins can diagnose unexpected re-creation after deletion.

    Expected result:
    - _getAutoEquipment() body calls log::add with 'warning' severity
    """
    # Assert: log::add is called with 'warning' level on the auto-create path
    assert "'warning'" in get_auto_equipment_body, (
        "_getAutoEquipment() must log at 'warning' level on auto-create"
    )
    # Assert: log::add is actually present (not just the string literal somewhere else)
    assert "log::add" in get_auto_equipment_body, (
        "_getAutoEquipment() must call log::add when auto-creating equipment"
    )


def test_auto_create_sets_canonical_equipment_name(get_auto_equipment_body: str) -> None:
    """
    Auto-created equipment must be named 'Télésurveillance' — the canonical
    plugin display name shown in Jeedom's equipment list and dashboard.
    A different name would confuse users who expect to see this specific label.

    Expected result:
    - _getAutoEquipment() calls setName('Télésurveillance')
    """
    # Assert: canonical equipment name is set on auto-creation
    assert "'Télésurveillance'" in get_auto_equipment_body, (
        "_getAutoEquipment() must set equipment name to 'Télésurveillance'"
    )


def test_auto_equipment_idempotent_guard(get_auto_equipment_body: str) -> None:
    """
    _getAutoEquipment() must check whether equipment already exists before
    creating a new one. The byType() call must come before 'new self()' so that
    repeated calls never produce duplicate equipment (AC7: calling 10 times = 1
    equipment).

    Expected result:
    - byType appears in _getAutoEquipment() body (existence check present)
    - 'new self()' appears in _getAutoEquipment() body (creation path present)
    - byType() check precedes 'new self()' in the method source (guard is first)
    """
    # Assert: byType existence check is present in the method
    assert "byType" in get_auto_equipment_body, (
        "_getAutoEquipment() must call byType() to check for existing equipment before creating"
    )
    # Assert: new self() creation path exists
    assert "new self()" in get_auto_equipment_body, (
        "_getAutoEquipment() must contain 'new self()' auto-creation path"
    )
    # Assert: guard (byType) comes before creation (new self()) — prevents duplicate creation
    assert get_auto_equipment_body.index("byType") < get_auto_equipment_body.index("new self()"), (
        "byType() check must appear before 'new self()' in _getAutoEquipment() — "
        "creation must only happen after confirming no equipment exists"
    )


def test_auto_recreate_after_delete_path_exists(get_auto_equipment_body: str) -> None:
    """
    If the user deletes the equipment, the next call to _getAutoEquipment() must
    recreate it (AC2). This requires that the creation path (new self() + save())
    is reachable when byType() returns empty — i.e., the empty-array branch leads
    to object creation, not just an early return.

    Expected result:
    - 'new self()' is present (creation path exists)
    - '$eq->save()' is called after new self() (triggers postSave() → 7 commands)
    - The creation path is inside the method body (not a separate method)
    """
    # Assert: new self() creates the equipment object
    assert "new self()" in get_auto_equipment_body, (
        "_getAutoEquipment() must create equipment with 'new self()' when none exists"
    )
    # Assert: save() is called to persist and trigger postSave() → command creation
    assert "$eq->save()" in get_auto_equipment_body, (
        "_getAutoEquipment() must call $eq->save() — triggers postSave() which creates the 7 commands"
    )
    # Assert: save() comes after new self() (logical creation order)
    assert get_auto_equipment_body.index("new self()") < get_auto_equipment_body.index("$eq->save()"), (
        "$eq->save() must come after 'new self()' in _getAutoEquipment()"
    )


# ── Story 6.3 — Fixtures ────────────────────────────────────────────────────


CALLBACK_PHP_FILE = _PROJECT_ROOT / "core/php/jeesiaDC09.php"

sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from fixtures.ipc_schema import CALLBACK_TYPES


@pytest.fixture(scope="module")
def message_body(php_source: str) -> str:
    return _extract_method_body(php_source, "message")


@pytest.fixture(scope="module")
def handle_info_update_body(php_source: str) -> str:
    return _extract_method_body(php_source, "_handleInfoUpdate")


@pytest.fixture(scope="module")
def handle_prefetch_result_body(php_source: str) -> str:
    return _extract_method_body(php_source, "_handlePrefetchResult")


@pytest.fixture(scope="module")
def callback_php_source() -> str:
    return CALLBACK_PHP_FILE.read_text(encoding="utf-8")


# ── Story 6.3 — jeesiaDC09.php exists ───────────────────────────────────────


def test_callback_php_file_exists() -> None:
    """
    The daemon→PHP callback endpoint must exist at core/php/jeesiaDC09.php.

    Expected result:
    - core/php/jeesiaDC09.php is present
    """
    # Assert: callback file exists
    assert CALLBACK_PHP_FILE.exists(), f"Callback file not found: {CALLBACK_PHP_FILE}"


def test_callback_php_routes_to_message(callback_php_source: str) -> None:
    """
    jeesiaDC09.php must call siaDC09::message() to dispatch the callback.

    Expected result:
    - 'siaDC09::message(' appears in the callback file
    """
    # Assert: message() dispatch is present
    assert "siaDC09::message(" in callback_php_source, (
        "jeesiaDC09.php must call siaDC09::message() to dispatch callbacks"
    )


def test_callback_php_validates_api_key(callback_php_source: str) -> None:
    """
    jeesiaDC09.php must validate the API key before processing.

    Expected result:
    - jeedom::apiAccess call with 'siaDC09' plugin ID
    """
    # Assert: API key validation present
    assert "jeedom::apiAccess" in callback_php_source, (
        "jeesiaDC09.php must validate API key via jeedom::apiAccess()"
    )
    # Assert: correct plugin ID used
    assert "'siaDC09'" in callback_php_source, (
        "jeesiaDC09.php must use 'siaDC09' plugin ID in apiAccess check"
    )


# ── Story 6.3 — message() method ────────────────────────────────────────────


def test_message_method_exists(php_source: str) -> None:
    """
    message() must be defined as a static method in siaDC09.class.php.

    Expected result:
    - 'function message(' appears in the PHP source
    """
    # Assert: message method exists
    assert re.search(r"function\s+message\s*\(", php_source), (
        "message() method not found in siaDC09.class.php"
    )


def test_message_dispatches_all_callback_types(message_body: str) -> None:
    """
    message() must handle every IPC callback type as a switch case (6 as of
    story 14-2's prefetch_result addition). Missing a case means that callback
    type is silently dropped.

    Expected result:
    - Every callback type string in CALLBACK_TYPES appears as a case label in
      message() body
    """
    for cb_type in CALLBACK_TYPES:
        # Assert: each callback type appears as a case label
        assert f"'{cb_type}'" in message_body, (
            f"message() missing case for '{cb_type}' — "
            "that callback type will be silently dropped"
        )


def test_message_uses_safe_equipment_lookup(message_body: str) -> None:
    """
    message() is called from the HTTP callback and must use the side-effect-free
    _getAutoEquipmentSafe() — never the auto-creating _getAutoEquipment().

    Expected result:
    - _getAutoEquipmentSafe() is called in message()
    - _getAutoEquipment() (non-Safe) is NOT called in message()
    """
    # Assert: safe variant used
    assert "_getAutoEquipmentSafe()" in message_body, (
        "message() must use _getAutoEquipmentSafe() — "
        "auto-creating inside a callback causes re-entrancy issues"
    )
    # Assert: auto-creating variant NOT used
    auto_creating = re.findall(r"_getAutoEquipment(?!Safe)\s*\(\)", message_body)
    assert len(auto_creating) == 0, (
        "message() must NOT call _getAutoEquipment() — "
        "it would write to the DB on every callback"
    )


# ── Story 6.3 — _handleInfoUpdate() ─────────────────────────────────────────


def test_handle_info_update_uses_check_and_update_cmd(
    handle_info_update_body: str,
) -> None:
    """
    _handleInfoUpdate() must use checkAndUpdateCmd() to update INFO commands.
    This is the correct Jeedom API that handles dashboard refresh, scenario
    triggers, history, and collectDate updates.

    Expected result:
    - 'checkAndUpdateCmd' appears in _handleInfoUpdate() body
    """
    # Assert: checkAndUpdateCmd is used
    assert "checkAndUpdateCmd" in handle_info_update_body, (
        "_handleInfoUpdate() must use checkAndUpdateCmd() — "
        "direct setValue would skip scenario triggers and dashboard refresh"
    )


def test_handle_info_update_maps_all_four_info_commands(
    handle_info_update_body: str,
) -> None:
    """
    _handleInfoUpdate() must map all 4 INFO logicalIds.

    Expected result:
    - supervision_state, supervision_label, event_state, event_label all present
    """
    for logical_id in INFO_LOGICAL_IDS:
        # Assert: each INFO logicalId is referenced
        assert f"'{logical_id}'" in handle_info_update_body, (
            f"_handleInfoUpdate() missing mapping for '{logical_id}'"
        )


# ── Story 14-2 — _handlePrefetchResult() ────────────────────────────────────


def test_message_dispatches_prefetch_result_to_handler(message_body: str) -> None:
    """
    Expected result:
    - the 'prefetch_result' case delegates to _handlePrefetchResult(), matching
      the existing case '_handleInfoUpdate()' delegation pattern
    """
    # Assert: dedicated handler is called, no inline logic in the switch
    assert "_handlePrefetchResult(" in message_body


def test_handle_prefetch_result_keys_cache_by_camera_eqlogic_id(
    handle_prefetch_result_body: str,
) -> None:
    """
    Expected result:
    - camera_eqlogic_id is read from the incoming message and used as the cache key
    """
    # Assert: camera identity is the cache key
    assert "camera_eqlogic_id" in handle_prefetch_result_body


def test_handle_prefetch_result_writes_via_set_cache(
    handle_prefetch_result_body: str,
) -> None:
    """
    Expected result:
    - the outcome is persisted via $eqLogic->setCache('sia_prefetch_cache', ...)
    """
    # Assert: uses the standard Jeedom ad hoc cache, same mechanism as sia_open_alarms
    assert "setCache('sia_prefetch_cache'" in handle_prefetch_result_body


def test_handle_prefetch_result_stores_found_event_id_and_timestamp(
    handle_prefetch_result_body: str,
) -> None:
    """
    Expected result:
    - the cache entry stores 'found', 'event_id', and a timestamp ('ts')
    """
    # Assert: all three fields siaDC09Cmd::_resolveFrigateSnapshotUrl() reads are written
    assert "'found'" in handle_prefetch_result_body
    assert "'event_id'" in handle_prefetch_result_body
    assert "'ts'" in handle_prefetch_result_body


def test_handle_prefetch_result_never_merges_stale_entries(
    handle_prefetch_result_body: str,
) -> None:
    """
    AC5: every prefetch outcome — including a miss — must unconditionally overwrite
    the per-camera cache entry, never merge with or preserve a previous entry's
    'found'/'event_id' values (that would let a stale hit survive a later miss on the
    same camera).

    Expected result:
    - the assignment writes a fresh array literal at $cache[<key>], not a partial
      merge into an existing entry
    """
    # Assert: a plain assignment (fresh entry), not array_merge or a conditional keep
    assert re.search(r"\$cache\[[^\]]+\]\s*=\s*\[", handle_prefetch_result_body), (
        "_handlePrefetchResult() must overwrite the cache entry with a fresh array, "
        "never merge with a previous entry"
    )
    assert "array_merge" not in handle_prefetch_result_body


# ── Story 6.3 — error_update uses plugin-level config ───────────────────────


def test_error_update_uses_config_save(message_body: str) -> None:
    """
    error_update and message_trace store data at plugin level via config::save,
    NOT via $eqLogic->setConfiguration() which would trigger postSave().

    Expected result:
    - 'config::save' appears in message() body
    """
    # Assert: plugin-level config::save is used
    assert "config::save" in message_body, (
        "message() must use config::save() for sia_last_errors/sia_last_messages — "
        "not $eqLogic->setConfiguration() which triggers postSave()"
    )


# ── Story 6.3 — notify uses sia_notify_cmd_id ───────────────────────────────


def test_notify_reads_sia_notify_cmd_id(
    message_body: str, run_notify_target_body: str
) -> None:
    """
    The notify case must read the config key 'sia_notify_cmd_id' (with sia_
    prefix) — NOT bare 'notify_cmd_id' as incorrectly shown in error-handler-design.md.

    Since epic 12 the read lives in _runNotifyTarget(), which message() delegates to so
    the command target and the Jeedom internal action share one code path.

    Expected result:
    - message() routes the 'notify' case to _runNotifyTarget()
    - 'sia_notify_cmd_id' appears in _runNotifyTarget()
    """
    # Assert: message() delegates instead of reading the config itself
    assert "_runNotifyTarget(" in message_body, (
        "message() notify case must delegate to _runNotifyTarget() — "
        "single entry point shared with the supervision alert"
    )
    # Assert: canonical config key with sia_ prefix is used
    assert "sia_notify_cmd_id" in run_notify_target_body, (
        "_runNotifyTarget() must use 'sia_notify_cmd_id' config key "
        "(not bare 'notify_cmd_id')"
    )


# ── Story 6.3 — callback URL uses http: not proto: ──────────────────────────


def test_deamon_start_callback_url_uses_http(deamon_start_body: str) -> None:
    """
    The callback URL in deamon_start() must use 'http:127.0.0.1:port:comp'
    not 'proto:127.0.0.1:port:comp'. proto: may resolve to HTTPS on setups
    with reverse proxies, breaking localhost daemon callbacks.

    Expected result:
    - 'http:127.0.0.1:port:comp' appears in deamon_start()
    - 'proto:127.0.0.1:port:comp' does NOT appear
    """
    # Assert: http: scheme used (forces HTTP for localhost)
    assert "http:127.0.0.1:port:comp" in deamon_start_body, (
        "deamon_start() must use 'http:127.0.0.1:port:comp' — "
        "'proto:' may resolve to HTTPS and break daemon callbacks"
    )
    # Assert: proto: NOT used
    assert "proto:127.0.0.1:port:comp" not in deamon_start_body, (
        "deamon_start() must NOT use 'proto:127.0.0.1:port:comp'"
    )


# ── Story 6.3 QA — G1: isset() guard mandate ────────────────────────────────


def test_handle_info_update_uses_isset_not_empty(
    handle_info_update_body: str,
) -> None:
    """
    _handleInfoUpdate() must guard each field with isset(), never empty().
    empty(0) returns true in PHP, which would silently drop supervision_state=0
    (the most critical "problem" state).

    Expected result:
    - 'isset(' appears in _handleInfoUpdate() body
    - 'empty(' does NOT appear in _handleInfoUpdate() body
    """
    # Assert: isset() guard is used
    assert "isset(" in handle_info_update_body, (
        "_handleInfoUpdate() must use isset() — not empty() — "
        "empty(0) would drop supervision_state=0 (problem state)"
    )
    # Assert: empty() is NOT used (would silently drop 0 and '' values)
    assert "empty(" not in handle_info_update_body, (
        "_handleInfoUpdate() must NOT use empty() — "
        "empty(0) is true in PHP, hiding critical state=0"
    )


# ── Story 6.3 QA — G2: default branch exists ────────────────────────────────


def test_message_has_default_branch(message_body: str) -> None:
    """
    message() must have a default: branch in its switch statement to log
    unknown callback types. Without it, new/malformed types are silently dropped.

    Expected result:
    - 'default:' appears in message() body
    - Unknown type logging is present near the default branch
    """
    # Assert: default branch exists
    assert "default:" in message_body, (
        "message() switch must have a default: branch — "
        "unknown callback types would be silently swallowed"
    )
    # Assert: the default branch logs a warning about the unknown type
    assert "type inconnu" in message_body or "unknown" in message_body.lower(), (
        "message() default branch must log unknown type for debugging"
    )


# ── Story 6.3 QA — G3: config key names ─────────────────────────────────────


def test_error_update_uses_sia_last_errors_key(message_body: str) -> None:
    """
    error_update must use the canonical config key 'sia_last_errors' (with sia_
    prefix). Using bare 'last_errors' would collide with other plugins.

    Expected result:
    - 'sia_last_errors' appears in message() body
    """
    # Assert: canonical config key used
    assert "sia_last_errors" in message_body, (
        "message() error_update must use 'sia_last_errors' config key"
    )


def test_message_trace_uses_sia_last_messages_key(message_body: str) -> None:
    """
    message_trace must use the canonical config key 'sia_last_messages' (with sia_
    prefix). Using bare 'last_messages' would collide with other plugins.

    Expected result:
    - 'sia_last_messages' appears in message() body
    """
    # Assert: canonical config key used
    assert "sia_last_messages" in message_body, (
        "message() message_trace must use 'sia_last_messages' config key"
    )


# ── Story 6.3 QA — G4/G5: cap enforcement ───────────────────────────────────


def test_error_update_enforces_max_10_cap(message_body: str) -> None:
    """
    error_update must cap sia_last_errors at 10 entries. Without the cap,
    the config key grows unbounded with each error event.

    Expected result:
    - 'array_slice' with limit 10 appears in message() body
    """
    # Assert: array_slice with 10 cap is present
    assert re.search(r"array_slice\s*\(\s*\$errors\s*,\s*0\s*,\s*10\s*\)", message_body), (
        "message() error_update must enforce max-10 cap via array_slice($errors, 0, 10)"
    )


def test_message_trace_enforces_max_50_cap(message_body: str) -> None:
    """
    message_trace must cap sia_last_messages at 50 entries. Without the cap,
    protocol dialogs accumulate indefinitely.

    Expected result:
    - 'array_slice' with limit 50 appears in message() body
    """
    # Assert: array_slice with 50 cap is present
    assert re.search(r"array_slice\s*\(\s*\$messages\s*,\s*0\s*,\s*50\s*\)", message_body), (
        "message() message_trace must enforce max-50 cap via array_slice($messages, 0, 50)"
    )


# ── Story 6.3 QA — G6: test ping handler ────────────────────────────────────


def test_callback_php_handles_test_ping(callback_php_source: str) -> None:
    """
    jeesiaDC09.php must handle the daemon's test ping (sent on startup).
    The jeedomdaemon framework sends init('test') != '' to verify the callback
    URL is reachable. Missing this handler causes daemon startup to fail silently.

    Expected result:
    - "init('test')" check present in the callback file
    - 'OK' echo response for test ping
    """
    # Assert: test ping check exists
    assert "init('test')" in callback_php_source, (
        "jeesiaDC09.php must check init('test') for daemon startup ping"
    )
    # Assert: OK response for test ping
    assert "echo 'OK'" in callback_php_source, (
        "jeesiaDC09.php must echo 'OK' for test ping — "
        "daemon startup depends on this response"
    )


# ── Story 6.3 QA — G7: notify try/catch safety ──────────────────────────────


def test_notify_wraps_exec_cmd_in_try_catch(run_notify_target_body: str) -> None:
    """
    The notify case must wrap execCmd() in try/catch. If a misconfigured
    notification command throws, it would propagate up as HTTP 500 and crash
    the entire callback pipeline for ALL callback types (not just notify).

    The execCmd() call moved into _runNotifyTarget() with epic 12, so the guard is
    asserted there — message() only delegates.

    Expected result:
    - 'try' and 'catch' appear in _runNotifyTarget() near 'execCmd'
    """
    # Assert: try/catch exists
    assert "try {" in run_notify_target_body or "try{" in run_notify_target_body, (
        "_runNotifyTarget() must wrap execCmd in try/catch — "
        "exception would crash the entire callback pipeline"
    )
    # Assert: catch block exists
    assert (
        "catch (Exception" in run_notify_target_body
        or "catch(Exception" in run_notify_target_body
    ), "_runNotifyTarget() must catch Exception from execCmd"
    # Assert: execCmd is the thing being wrapped
    assert "execCmd" in run_notify_target_body, (
        "_runNotifyTarget() must call execCmd() on the configured command"
    )


# ── Story 6.3 QA — W4: T1 resolve codes match ErrorCode enum ────────────────


def test_t1_resolve_codes_match_error_handler_enum() -> None:
    """
    The T1 auto-resolve codes hard-coded in PHP ('SUPERVISION_TIMEOUT',
    'SUPERVISION_NAK') must match the Python ErrorCode enum values. If the
    enum is renamed, T1 auto-resolve silently stops working.

    Expected result:
    - ErrorCode.SUPERVISION_TIMEOUT and ErrorCode.SUPERVISION_NAK exist in Python
    - Their .name values match what PHP uses for T1 filtering
    """
    from resources.siadc09d.error_handler import ErrorCode

    # Assert: T1 error codes exist in the enum
    t1_codes = ["SUPERVISION_TIMEOUT", "SUPERVISION_NAK"]
    enum_names = [e.name for e in ErrorCode]
    for code in t1_codes:
        assert code in enum_names, (
            f"ErrorCode.{code} not found in Python enum — "
            f"PHP T1 auto-resolve hard-codes this string"
        )


# ── Story 6.4 — returnStateTime / returnStateValue ────────────────────────


def test_postsave_sets_return_state_time_on_commands(action_cmds_loop_body: str) -> None:
    """
    Momentary action alarm commands (burglarAlarm/fireAlarm/panicAlarm) must
    have returnStateTime=30 to prevent stuck PENDING state (event_state=3)
    if the daemon crashes mid-alarm. Jeedom auto-reverts the command value
    after this many minutes of no update.

    Expected result:
    - 'returnStateTime' appears in the action cmds loop of postSave() body
    - The value 30 appears associated with returnStateTime
    """
    # Assert: returnStateTime is set on the momentary action cmds
    assert "returnStateTime" in action_cmds_loop_body, (
        "postSave() must set returnStateTime on the momentary action cmds — "
        "prevents event_state=3 stuck if daemon crashes"
    )
    # Assert: value 30 is used (spec: 30 minutes)
    assert (
        "'returnStateTime', 30" in action_cmds_loop_body
        or '"returnStateTime", 30' in action_cmds_loop_body
    ), "postSave() must set returnStateTime=30 (30-minute auto-revert) on action cmds"


def test_postsave_sets_return_state_value_zero(action_cmds_loop_body: str) -> None:
    """
    Momentary action alarm commands must revert to 0 (not null) after
    returnStateTime expires. Value 0 means 'no alarm' — a safe idle state.

    Expected result:
    - 'returnStateValue' appears in the action cmds loop of postSave() body
    - The revert value is 0
    """
    # Assert: returnStateValue is set on the momentary action cmds
    assert "returnStateValue" in action_cmds_loop_body, (
        "postSave() must set returnStateValue on the momentary action cmds"
    )
    # Assert: revert value is 0 (safe idle state)
    assert (
        "'returnStateValue', 0" in action_cmds_loop_body
        or '"returnStateValue", 0' in action_cmds_loop_body
    ), "postSave() must set returnStateValue=0 (safe idle revert) on action cmds"


def test_postsave_info_cmds_do_not_get_return_state_config(info_cmds_loop_body: str) -> None:
    """
    Persistent 'info' commands (supervision_state/label, event_state/label) must
    NOT get returnStateTime/returnStateValue — that auto-revert-to-0 config is for
    the momentary action alarm commands (burglarAlarm/fireAlarm/panicAlarm) only.
    Applying it to info cmds (copy-pasted from the action-cmd block) caused the
    event/supervision badges to auto-revert to a bare "0" during normal operation.

    Expected result:
    - 'returnStateTime' does not appear in the info cmds foreach loop
    - 'returnStateValue' does not appear in the info cmds foreach loop
    """
    # Assert: no auto-revert timer on the persistent info cmds
    assert "returnStateTime" not in info_cmds_loop_body, (
        "info cmds must not have returnStateTime — that's for momentary action cmds only"
    )
    # Assert: no auto-revert value on the persistent info cmds
    assert "returnStateValue" not in info_cmds_loop_body, (
        "info cmds must not have returnStateValue — persistent state is driven by the daemon, not a timer"
    )


# ── Story 6.4 — isVisible=0 on all commands ───────────────────────────────


def test_all_commands_are_invisible(postsave_body: str) -> None:
    """
    All INFO and ACTION commands must be invisible in Jeedom's dashboard
    command list (isVisible=0). State display is via toHtml() widget only.

    Expected result:
    - setIsVisible(0) appears in postSave() for command creation
    """
    # Assert: isVisible is explicitly set to 0
    assert "setIsVisible(0)" in postsave_body, (
        "postSave() must call setIsVisible(0) on all commands — "
        "display is via toHtml() widget only"
    )


# ── Story 6.4 — _handleInfoUpdate() uses checkAndUpdateCmd ────────────────


def test_handle_info_update_uses_check_and_update_cmd(
    handle_info_update_body: str,
) -> None:
    """
    _handleInfoUpdate() must use checkAndUpdateCmd() — the standard Jeedom API
    for updating INFO command values. This triggers scenario events, updates
    collectDate, and persists the value. Both the eqLogic shortcut form and the
    getCmd+cmd form are acceptable (expert-confirmed identical behavior).

    Expected result:
    - 'checkAndUpdateCmd' appears in _handleInfoUpdate() body
    """
    # Assert: checkAndUpdateCmd is used to update INFO values
    assert "checkAndUpdateCmd" in handle_info_update_body, (
        "_handleInfoUpdate() must call checkAndUpdateCmd() to update INFO values"
    )


# ── Story 6.5 — Method 1: no dependancy overrides ───────────────────────────


def test_no_dependancy_info_override(php_source: str) -> None:
    """
    With Method 1 (packages.json), Jeedom's core handles dependency checking.
    The plugin must NOT override dependancy_info() — doing so would conflict
    with the core's automatic mechanism.

    Expected result:
    - 'function dependancy_info' does NOT appear in siaDC09.class.php
    """
    # Assert: no dependancy_info override
    assert "function dependancy_info" not in php_source, (
        "siaDC09.class.php must NOT override dependancy_info() — "
        "Method 1 (packages.json) lets the Jeedom core handle it"
    )


def test_no_dependancy_install_override(php_source: str) -> None:
    """
    With Method 1 (packages.json), Jeedom's core handles dependency install.
    The plugin must NOT provide dependancy_install() — the core reads
    packages.json and installs automatically.

    Expected result:
    - 'function dependancy_install' does NOT appear in siaDC09.class.php
    """
    # Assert: no dependancy_install override
    assert "function dependancy_install" not in php_source, (
        "siaDC09.class.php must NOT override dependancy_install() — "
        "Method 1 (packages.json) lets the Jeedom core handle it"
    )


def test_guard3d_supervision_interval_default_matches_system_default(
    deamon_info_body: str,
) -> None:
    """
    Guard 3d in deamon_info() must default supervision_interval to 60, matching
    the system-wide default used by deamon_start() and siadc09d.py's CLI arg.
    A default of 0 blocks daemon launch whenever the wizard field is left blank
    (trusting the "60" placeholder hint text, which sets no actual value) —
    the exact bug observed in the field on 2026-09-21.

    Expected result:
    - getConfiguration('supervision_interval', <default>) in Guard 3d defaults to 60, not 0
    """
    match = re.search(
        r"""getConfiguration\(\s*['"]supervision_interval['"]\s*,\s*(\d+)\s*\)""",
        deamon_info_body,
    )
    # Assert: Guard 3d reads supervision_interval with an explicit numeric default
    assert match is not None, (
        "Guard 3d must call getConfiguration('supervision_interval', <default>)"
    )
    # Assert: default matches the system-wide default (60s), not 0
    assert match.group(1) == "60", (
        f"Guard 3d defaults supervision_interval to {match.group(1)}, expected 60 — "
        "leaving the wizard field blank (trusting the '60' placeholder) would "
        "incorrectly block daemon launch"
    )


def test_deamon_info_does_not_call_dependancy_info(deamon_info_body: str) -> None:
    """
    deamon_info() must NOT call dependancy_info() — the Jeedom core's
    plugin::deamon_info() wrapper automatically adds the dependency check.
    Calling it manually would double-check and waste cycles on every
    watchdog tick (once per minute).

    Expected result:
    - 'dependancy_info' does NOT appear in deamon_info() body
    """
    # Assert: no manual dependancy check in deamon_info
    assert "dependancy_info" not in deamon_info_body, (
        "deamon_info() must NOT call dependancy_info() — "
        "the Jeedom core wrapper adds it automatically"
    )


# ── Story 8.2 — Wizard Guards ─────────────────────────────────────────────────


def test_guard2_uses_sia_wizard_step_key(deamon_info_body: str) -> None:
    """
    Guard 2 in deamon_info() must use the quoted config key 'sia_wizard_step'
    (not the old unprefixed 'wizard_step'). Substring match would also pass for
    'sia_wizard_step_completed' — we require the exact quoted form.

    Expected result:
    - The quoted string 'sia_wizard_step' (single or double quotes) appears in
      deamon_info() body as a config key reference
    """
    # Assert: exact quoted key present — not just a substring match on the identifier
    assert re.search(r"""['"]sia_wizard_step['"]""", deamon_info_body), (
        "deamon_info() Guard 2 must reference 'sia_wizard_step' as a quoted config key"
    )
    # Assert: old unprefixed key is NOT used
    assert not re.search(r"""['"]wizard_step['"]""", deamon_info_body), (
        "deamon_info() must not reference bare 'wizard_step' — "
        "key was renamed to 'sia_wizard_step' to avoid inter-plugin collision"
    )


def test_guard3_blocks_tbd_ip(deamon_info_body: str) -> None:
    """
    Guard 3 in deamon_info() must explicitly compare csr_ip against the quoted
    string 'TBD'. Without this guard, a daemon start would be attempted against
    the literal hostname 'TBD' (IMA Protect preset placeholder).

    Expected result:
    - The quoted string 'TBD' or "TBD" appears inside a comparison in deamon_info()
    """
    # Assert: quoted TBD literal is used in a comparison (not just present anywhere)
    assert re.search(r"""[=!]=\s*['"]TBD['"]|['"]TBD['"]\s*[=!]=""", deamon_info_body), (
        "deamon_info() Guard 3 must compare csr_ip against 'TBD' — "
        "quoted literal must appear in a comparison expression"
    )


def test_guard6_blocks_missing_notify_cmd(
    deamon_info_body: str, has_notify_target_body: str
) -> None:
    """
    Guard 6 in deamon_info() must validate that a notification target is configured
    before allowing daemon start. Missing target would cause critical notifications to
    be silently dropped. Since epic 12 the check is _hasNotifyTarget(), which accepts an
    equipment command or a Jeedom internal action.

    The key must appear as a quoted string in a getConfiguration() call, not just
    anywhere in the method body (e.g., in a comment).

    Expected result:
    - deamon_info() blocks the start on !_hasNotifyTarget()
    - _hasNotifyTarget() calls getConfiguration('sia_notify_cmd_id') for the cmd kind
    """
    # Assert: Guard 6 blocks the start when no target is configured
    assert re.search(r"if\s*\(\s*!\s*self::_hasNotifyTarget\s*\(", deamon_info_body), (
        "deamon_info() Guard 6 must block the start on !self::_hasNotifyTarget() — "
        "no reachable target means the first alarm fails silently"
    )
    # Assert: sia_notify_cmd_id used in getConfiguration(), not just in a comment
    assert re.search(
        r"""getConfiguration\s*\(\s*['"]sia_notify_cmd_id['"]""", has_notify_target_body
    ), (
        "_hasNotifyTarget() must call getConfiguration('sia_notify_cmd_id') — "
        "string only in a comment would pass a bare substring check"
    )


# ── Story 8.3 — JS wizard step contract ──────────────────────────────────────

_JS_FILE = _PROJECT_ROOT / "desktop/js/siaDC09.js"


def _extract_js_handler(js_source: str, btn_id: str) -> str:
    """Extract the full body of a jQuery .on('click', ...) handler block.

    Finds the btn_id string, then walks forward to the first '{' of the
    handler function body, tracks brace depth to find the matching '}', and
    returns the content between them. Works correctly on nested callbacks.
    """
    start = js_source.find(f"'{btn_id}'")
    if start == -1:
        start = js_source.find(f'"{btn_id}"')
    assert start != -1, f"Handler for {btn_id} not found in siaDC09.js"

    brace_start = js_source.index("{", start)
    depth = 1
    i = brace_start + 1
    while i < len(js_source) and depth > 0:
        if js_source[i] == "{":
            depth += 1
        elif js_source[i] == "}":
            depth -= 1
        i += 1
    return js_source[brace_start + 1 : i - 1]


def _extract_js_function(js_source: str, fn_name: str) -> str:
    """Extract the body of a top-level `function <name>() { ... }` declaration.

    Same brace walk as _extract_js_handler, anchored on the declaration instead of a
    selector — wizard logic that moved out of a click handler into a named helper stays
    assertable.
    """
    match = re.search(rf"function\s+{re.escape(fn_name)}\s*\(", js_source)
    assert match, f"function {fn_name} not found in siaDC09.js"

    brace_start = js_source.index("{", match.end())
    depth = 1
    i = brace_start + 1
    while i < len(js_source) and depth > 0:
        if js_source[i] == "{":
            depth += 1
        elif js_source[i] == "}":
            depth -= 1
        i += 1
    return js_source[brace_start + 1 : i - 1]


@pytest.fixture(scope="module")
def js_source() -> str:
    assert _JS_FILE.exists(), f"JS file not found: {_JS_FILE}"
    return _JS_FILE.read_text(encoding="utf-8")


def test_bt_step3next_sets_wizard_step_4(js_source: str) -> None:
    """
    Story 8-3 bug fix: #bt_step3Next click handler must call
    siaDC09_setWizardStep(4) before jeedom.eqLogic.save(), so the saved
    sia_wizard_step value matches the step displayed by siaDC09_showStep(4).

    The original bug was siaDC09_setWizardStep(3) — wizard would show step 4
    HTML but the DB would record step=3, causing step 3 to re-appear on reload.

    Expected result:
    - siaDC09_setWizardStep(4) appears inside the bt_step3Next handler block
    - siaDC09_setWizardStep(3) does NOT appear inside the bt_step3Next handler block
    """
    handler_body = _extract_js_handler(js_source, "#bt_step3Next")

    # Assert: correct step (4) is set before save
    assert "siaDC09_setWizardStep(4)" in handler_body, (
        "#bt_step3Next handler must call siaDC09_setWizardStep(4) — "
        "step must be saved as 4 so DB matches siaDC09_showStep(4)"
    )
    # Assert: the bug (step 3) is not present
    assert "siaDC09_setWizardStep(3)" not in handler_body, (
        "#bt_step3Next handler must NOT call siaDC09_setWizardStep(3) — "
        "this was the original bug: DB saved step=3 while UI showed step=4"
    )


def test_bt_step3next_calls_show_step_4_on_success(js_source: str) -> None:
    """
    After jeedom.eqLogic.save() succeeds, the #bt_step3Next handler must call
    siaDC09_showStep(4) to display the notification command picker.

    Expected result:
    - siaDC09_showStep(4) appears in the success callback of the bt_step3Next handler
    """
    handler_body = _extract_js_handler(js_source, "#bt_step3Next")

    # Assert: step 4 is shown after successful save
    assert "siaDC09_showStep(4)" in handler_body, (
        "#bt_step3Next success callback must call siaDC09_showStep(4) — "
        "without it the UI stays on step 3 after zone mapping is saved"
    )


def test_bt_restart_wizard_sets_step_0_before_save(js_source: str) -> None:
    """
    #bt_restartWizard must call siaDC09_setWizardStep(0) BEFORE jeedom.eqLogic.save().
    This prevents a race condition: if step is set after save(), the daemon watchdog
    may see the old step value and skip the auto-stop.

    Expected result:
    - siaDC09_setWizardStep(0) appears before the jeedom.eqLogic.save call
      in the bt_restartWizard handler
    """
    handler_body = _extract_js_handler(js_source, "#bt_restartWizard")

    # Assert: setWizardStep(0) present
    assert "siaDC09_setWizardStep(0)" in handler_body, (
        "#bt_restartWizard must call siaDC09_setWizardStep(0) before save()"
    )
    # Assert: setWizardStep(0) precedes save() in source order (race-condition guard)
    set_pos = handler_body.find("siaDC09_setWizardStep(0)")
    save_pos = handler_body.find("jeedom.eqLogic.save")
    assert set_pos != -1 and save_pos != -1, (
        "#bt_restartWizard must contain both siaDC09_setWizardStep(0) and jeedom.eqLogic.save"
    )
    assert set_pos < save_pos, (
        "#bt_restartWizard must set wizard step to 0 BEFORE calling jeedom.eqLogic.save — "
        "race condition: watchdog may read old step if order is reversed"
    )


def test_bt_step4finish_validates_notify_cmd_before_save(js_source: str) -> None:
    """
    #bt_step4Finish must check that sia_notify_cmd_id is non-empty and show an
    error if not — never save without a valid notification command. Without this
    guard, users could complete the wizard without configuring the mandatory T3
    notification command, causing critical alerts to be silently dropped.

    Since epic 12 the check is siaDC09_validateNotifyTarget(), which validates whichever
    target kind is selected (equipment command, message, scenario).

    Expected result:
    - #bt_step4Finish returns early when siaDC09_validateNotifyTarget() is falsy
    - siaDC09_validateNotifyTarget() reads sia_notify_cmd_id from the DOM and guards it
    """
    handler_body = _extract_js_handler(js_source, "#bt_step4Finish")
    validator_body = _extract_js_function(js_source, "siaDC09_validateNotifyTarget")

    # Assert: the handler aborts the save when validation fails
    assert re.search(r"if\s*\(\s*!\s*siaDC09_validateNotifyTarget\s*\(\s*\)", handler_body), (
        "#bt_step4Finish must return early on !siaDC09_validateNotifyTarget() — "
        "never save the wizard without a usable notification target"
    )
    # Assert: notify cmd id is read from the DOM
    assert "sia_notify_cmd_id" in validator_body, (
        "siaDC09_validateNotifyTarget() must read sia_notify_cmd_id from the DOM"
    )
    # Assert: a guard check exists (if !notifyCmdId or if not set)
    assert re.search(r"if\s*\(\s*!", validator_body), (
        "siaDC09_validateNotifyTarget() must guard against an empty target"
    )


def test_sia_wizard_step_set_via_data_l2key_attribute(js_source: str) -> None:
    """
    siaDC09_setWizardStep() must set the value via
    .eqLogicAttr[data-l2key="sia_wizard_step"] — the Jeedom DOM pattern that
    getValues('.eqLogicAttr') reads when building the save payload. Any other
    selector would mean the step is never persisted.

    Expected result:
    - The function uses data-l2key="sia_wizard_step" selector
    """
    match = re.search(
        r"function\s+siaDC09_setWizardStep\s*\([^)]*\)\s*\{([^}]*)\}", js_source, re.DOTALL
    )
    assert match is not None, "siaDC09_setWizardStep() function not found in siaDC09.js"
    fn_body = match.group(1)

    # Assert: sia_wizard_step is targeted via data-l2key attribute (Jeedom save contract)
    assert 'data-l2key="sia_wizard_step"' in fn_body or "data-l2key='sia_wizard_step'" in fn_body, (
        "siaDC09_setWizardStep() must use data-l2key='sia_wizard_step' selector — "
        "Jeedom reads this attribute to build the eqLogic save payload"
    )


# ── Story 12.1 AC8 — Equipment page bootstraps the auto-equipment ─────────────

EQUIPMENT_PAGE_FILE = _PROJECT_ROOT / "desktop/php/siaDC09.php"


@pytest.fixture(scope="module")
def equipment_page() -> str:
    return EQUIPMENT_PAGE_FILE.read_text(encoding="utf-8")


def test_ensure_auto_equipment_is_public_static(php_source: str) -> None:
    """
    _getAutoEquipment() is private, so the equipment page cannot call it.
    A public static ensureAutoEquipment() wrapper is the only supported
    bootstrap entry point (Story 12.1, AC8).

    Expected result:
    - ensureAutoEquipment() is declared public static with ': self' return type
    """
    match = re.search(
        r"public\s+static\s+function\s+ensureAutoEquipment\s*\(\s*\)\s*:\s*self", php_source
    )
    # Assert: public static accessor exists with non-nullable return type
    assert match is not None, (
        "ensureAutoEquipment() must be declared 'public static function "
        "ensureAutoEquipment(): self' — desktop/php/siaDC09.php cannot call the private method"
    )


def test_ensure_auto_equipment_delegates_to_creating_method(php_source: str) -> None:
    """
    ensureAutoEquipment() must delegate to _getAutoEquipment() (the
    auto-creating variant). Delegating to _getAutoEquipmentSafe() would
    return null on a fresh install and never create the equipment.

    Expected result:
    - Body calls _getAutoEquipment()
    - Body does NOT call _getAutoEquipmentSafe()
    """
    body = _extract_method_body(php_source, "ensureAutoEquipment")
    # Assert: the wrapper actually reaches the creating variant
    assert "_getAutoEquipment()" in body, (
        "ensureAutoEquipment() must call _getAutoEquipment() to create the equipment"
    )
    # Assert: the null-returning variant is not used — no equipment would be created
    assert "_getAutoEquipmentSafe()" not in body, (
        "ensureAutoEquipment() must not call _getAutoEquipmentSafe() — "
        "it returns null on a fresh install and creates nothing"
    )


def test_equipment_page_bootstraps_before_listing(equipment_page: str) -> None:
    """
    On a fresh install no equipment exists, so eqLogic::byType() returns an
    empty list, no equipment card is rendered and the wizard is unreachable —
    while deamon_info() Guard 1 reports 'L'équipement n'existe pas'. The page
    must therefore create the equipment before listing it (Story 12.1, AC8).

    Expected result:
    - desktop/php/siaDC09.php calls siaDC09::ensureAutoEquipment()
    - the call appears before the eqLogic::byType() lookup
    """
    bootstrap = re.search(r"siaDC09::ensureAutoEquipment\s*\(\s*\)", equipment_page)
    listing = re.search(r"eqLogic::byType\s*\(", equipment_page)
    # Assert: the page bootstraps the equipment
    assert bootstrap is not None, (
        "desktop/php/siaDC09.php must call siaDC09::ensureAutoEquipment() — "
        "otherwise a fresh install has no equipment card and the wizard cannot be opened"
    )
    # Assert: the listing exists (guards against the regex silently matching nothing)
    assert listing is not None, "desktop/php/siaDC09.php must list equipment via eqLogic::byType()"
    # Assert: bootstrap runs first, so the new equipment is included in the listing
    assert bootstrap.start() < listing.start(), (
        "siaDC09::ensureAutoEquipment() must run before eqLogic::byType() — "
        "otherwise the freshly created equipment is missing from the rendered list"
    )


def test_daemon_not_required_to_reach_the_wizard(php_source: str) -> None:
    """
    The wizard runs with the daemon stopped (wizard-design.md §374-381) and
    deamon_info() Guard 2 keeps launchable='nok' until sia_wizard_step >= 4.
    So equipment creation must not be reachable only through deamon_start() —
    that is the install-time deadlock this story fixes.

    Expected result:
    - _getAutoEquipment() is called from at least two methods
      (deamon_start() and ensureAutoEquipment())
    """
    call_sites = re.findall(r"self::_getAutoEquipment(?!Safe)\s*\(\s*\)", php_source)
    # Assert: creation is reachable outside the daemon-start path
    assert len(call_sites) >= 2, (
        "_getAutoEquipment() is only called from deamon_start(), which throws when "
        "launchable != 'ok' — equipment can never be created before the wizard runs"
    )


# ── Story 13.1 — sia_open_alarms table (Task 3, AC3) ─────────────────────────


def test_execute_records_open_alarm_after_dispatch(execute_body: str) -> None:
    """
    Task 3 / AC3: every alarm dispatch (burglarAlarm/fireAlarm/panicAlarm) must
    create or refresh an entry in the sia_open_alarms table, written right
    after sendToDaemon() so a later burglaryCancel fan-out has something to
    close — per php-core-design.md's "Point d'écriture" note.

    Expected result:
    - execute() calls a _recordOpenAlarm()-style helper
    - that call appears after the sendToDaemon() call, not before
    """
    dispatch = re.search(r"sendToDaemon\s*\(", execute_body)
    record = re.search(r"_record\w*OpenAlarm\w*\s*\(", execute_body)
    # Assert: a recording helper is called from execute()
    assert record is not None, (
        "execute() must call a _recordOpenAlarm()-style helper — otherwise no BA/FA/PA "
        "is ever memorized and burglaryCancel has nothing to fan out to"
    )
    # Assert: the recording happens after sendToDaemon(), matching the design's write point
    assert dispatch is not None and dispatch.start() < record.start(), (
        "sia_open_alarms must be written right after sendToDaemon() — "
        "recording before dispatch could memorize an alarm that never actually sent"
    )


def test_open_alarms_cache_key_matches_design(php_cmd_source: str) -> None:
    """
    php-core-design.md specifies the eqLogic cache key literal 'sia_open_alarms'
    for the table (setCache/getCache, Redis-backed, survives daemon restarts —
    the A-PHP decision of 2026-09-18).

    Expected result:
    - the literal cache key 'sia_open_alarms' appears in the source
    - setCache() and getCache() are both used to persist/read the table
    """
    # Assert: the documented cache key literal is present
    assert "'sia_open_alarms'" in php_cmd_source, (
        "sia_open_alarms cache key literal missing — must match php-core-design.md exactly"
    )
    # Assert: the table is persisted via setCache()
    assert re.search(r"->setCache\s*\(", php_cmd_source), (
        "sia_open_alarms must be persisted via eqLogic::setCache() (A-PHP decision, Redis-backed)"
    )
    # Assert: the table is read back via getCache()
    assert re.search(r"->getCache\s*\(", php_cmd_source), (
        "sia_open_alarms must be read back via eqLogic::getCache()"
    )


def test_open_alarms_key_format_dedups_by_zone_or_account(php_cmd_source: str) -> None:
    """
    Design: key = sia_code . '|' . (zone_number !== null ? zone_number : 'account').
    This dedups repeated BA on the same zone and collapses every unresolved
    zone onto a single 'account' entry instead of producing one doublon per
    unknown label.

    Expected result:
    - the key concatenation uses the '|' separator
    - the literal fallback 'account' is used when zone_number is null
    """
    # Assert: keys are built with the '|' separator (sia_code|zone_number-or-account)
    assert re.search(r"\.\s*['\"]\|['\"]\s*\.", php_cmd_source), (
        "sia_open_alarms key must concatenate sia_code and zone with a '|' separator"
    )
    # Assert: unresolved/account-wide entries fall back to the literal 'account'
    assert "'account'" in php_cmd_source, (
        "sia_open_alarms key must fall back to the literal 'account' when zone_number is null — "
        "otherwise unresolved zones never dedup onto a single entry"
    )


def test_open_alarms_entry_shape(php_cmd_source: str) -> None:
    """
    Design: entry = ['sia_code' => .., 'zone' => .., 'zone_number' => .., 'ts' => ..].
    Missing any field breaks either the fan-out (needs sia_code + zone_number),
    the debug log for abandoned FA/PA (needs zone), or eviction/TTL (needs ts).

    Expected result:
    - all four keys 'sia_code', 'zone', 'zone_number', 'ts' appear in the source
    """
    for entry_key in ("'sia_code'", "'zone'", "'zone_number'", "'ts'"):
        # Assert: each entry field from the design is present in the table's shape
        assert entry_key in php_cmd_source, (
            f"sia_open_alarms entry missing {entry_key} — required by the design's entry shape"
        )


def test_open_alarms_max_and_ttl_constants_declared(php_cmd_source: str) -> None:
    """
    Design: a hard cap OPEN_ALARMS_MAX guards against a corrupted cache, and a
    TTL OPEN_ALARMS_TTL guards the case where no reset ever arrives (alarm
    plugin disabled mid-alarm).

    Expected result:
    - both OPEN_ALARMS_MAX and OPEN_ALARMS_TTL are declared as class constants
    """
    # Assert: OPEN_ALARMS_MAX is declared
    assert re.search(r"const\s+OPEN_ALARMS_MAX\s*=", php_cmd_source), (
        "OPEN_ALARMS_MAX constant missing — table has no hard cap against a corrupted cache"
    )
    # Assert: OPEN_ALARMS_TTL is declared
    assert re.search(r"const\s+OPEN_ALARMS_TTL\s*=", php_cmd_source), (
        "OPEN_ALARMS_TTL constant missing — an alarm with no reset would stay open forever"
    )


def test_open_alarms_eviction_is_oldest_by_timestamp(php_cmd_source: str) -> None:
    """
    Design: eviction beyond OPEN_ALARMS_MAX must drop the oldest entry BY
    'ts', never "the first in the dict" — insertion order is not a contract
    for a PHP associative array after a json_decode()/setCache() round-trip.

    Expected result:
    - a sort-by-ts comparator drives eviction (uasort/usort comparing 'ts')
    - array_shift() is not used as an eviction shortcut
    """
    # Assert: a sort-by-ts comparator drives eviction (uasort/usort comparing 'ts')
    assert re.search(r"(uasort|usort)\s*\(", php_cmd_source) and "'ts'" in php_cmd_source, (
        "eviction must sort by the 'ts' field — insertion order is not a contract"
    )
    # Assert: the forbidden shortcut (evict "first in dict") is not used
    assert "array_shift(" not in php_cmd_source, (
        "array_shift() evicts by insertion order, not by 'ts' — forbidden by the design"
    )


def test_open_alarms_ttl_prunes_by_elapsed_time(php_cmd_source: str) -> None:
    """
    Design: OPEN_ALARMS_TTL protects the case where no reset ever arrives by
    expiring stale entries, measured from a captured $now = time().

    Expected result:
    - $now = time() is captured to measure elapsed time
    - OPEN_ALARMS_TTL is used (not just declared) to prune expired entries
    """
    # Assert: a $now timestamp is captured to measure how stale an entry is
    assert re.search(r"\$now\s*=\s*time\s*\(\s*\)", php_cmd_source), (
        "sia_open_alarms must capture $now = time() to measure how stale an entry is"
    )
    # Assert: OPEN_ALARMS_TTL is referenced outside its own declaration, i.e. actually used
    assert len(re.findall(r"OPEN_ALARMS_TTL", php_cmd_source)) >= 2, (
        "OPEN_ALARMS_TTL constant must actually be used to prune expired entries, not just declared"
    )


def test_open_alarms_sia_code_mapping_covers_all_alarm_commands(php_cmd_source: str) -> None:
    """
    The table's key and the future fan-out rely on the actual SIA code
    ('BA'/'FA'/'PA'), not the Jeedom logicalId ('burglarAlarm') — the daemon
    dispatch key and the SIA code are two different vocabularies.

    Expected result:
    - 'burglarAlarm' -> 'BA', 'fireAlarm' -> 'FA', 'panicAlarm' -> 'PA' are
      each mapped somewhere in the source
    """
    mapping = {
        "burglarAlarm": "BA",
        "fireAlarm": "FA",
        "panicAlarm": "PA",
    }
    for logical_id, sia_code in mapping.items():
        pattern = rf"'{logical_id}'\s*=>\s*'{sia_code}'"
        # Assert: each logicalId is mapped to its SIA code for the open-alarms table
        assert re.search(pattern, php_cmd_source), (
            f"missing mapping '{logical_id}' => '{sia_code}' — sia_open_alarms needs the "
            "SIA code, not the Jeedom logicalId, as its key prefix"
        )


# ── Story 13.1 — burglaryCancel fan-out (Task 4, AC4, AC5) ───────────────────


def test_fan_out_method_exists(php_cmd_source: str) -> None:
    """
    Design: the fan-out algorithm (story doc "Éventail sur annulation") lives
    in its own method so it stays testable in isolation from the execute()
    wiring, which is deferred to Task 2 (blocked by 10-3).

    Expected result:
    - a private method _fanOutBurglaryCancel() is declared on siaDC09Cmd
    """
    # Assert: the fan-out method is declared
    assert re.search(
        r"private\s+function\s+_fanOutBurglaryCancel\s*\(", php_cmd_source
    ), "expected a private _fanOutBurglaryCancel() method implementing the AC4/AC5 algorithm"


def test_fan_out_emits_one_bc_per_open_ba_entry(fan_out_body: str) -> None:
    """
    Design (AC4): a burglaryCancel with an empty Titre emits exactly N BC for
    N open BA zones, by iterating the sia_open_alarms table and dispatching
    one sendToDaemon() per BA entry.

    Expected result:
    - the method reads sia_open_alarms via getCache
    - it iterates the entries and dispatches via sendToDaemon() for 'BA' entries
    """
    # Assert: the open-alarms table is read back from the eqLogic cache
    assert re.search(r"getCache\s*\(\s*['\"]sia_open_alarms['\"]", fan_out_body), (
        "fan-out must read the sia_open_alarms table via getCache()"
    )
    # Assert: a dispatch call is made for BA entries (the only code BC closes)
    assert re.search(r"sendToDaemon\s*\(", fan_out_body), (
        "fan-out must call sendToDaemon() to emit BC frames for open BA entries"
    )
    # Assert: the code discriminates on the BA sia_code before dispatching
    assert re.search(r"['\"]BA['\"]", fan_out_body), (
        "fan-out must check for the 'BA' sia_code — BC only closes burglary entries"
    )


def test_fan_out_bc_carries_matching_zone_number(fan_out_body: str) -> None:
    """
    Design: each BC must carry the same zone_number as the BA it closes —
    the zone label is not a usable correlation key (story Dépendance section).

    Expected result:
    - the sendToDaemon() payload sources 'zone_number' from the open-alarm entry
    """
    # Assert: zone_number is forwarded from the stored entry, not recomputed
    assert re.search(r"zone_number.*entry\[['\"]zone_number['\"]\]", fan_out_body) or re.search(
        r"entry\[['\"]zone_number['\"]\].*zone_number", fan_out_body
    ), "each BC frame must carry the zone_number of the BA entry it closes"


def test_fan_out_skips_fa_pa_and_logs_debug(fan_out_body: str) -> None:
    """
    Design: BC never closes FA/PA — they are abandoned and logged at debug
    level so they remain traceable without producing a frame (future
    FC/PC of story 13-3).

    Expected result:
    - the method distinguishes 'FA' and 'PA' sia_codes from 'BA'
    - abandoned FA/PA entries are logged via log::add(..., 'debug', ...)
    """
    # Assert: FA and PA are recognized as distinct from BA
    assert re.search(r"['\"]FA['\"]", fan_out_body) and re.search(r"['\"]PA['\"]", fan_out_body), (
        "fan-out must distinguish FA/PA entries from BA so they are never closed by a BC"
    )
    # Assert: abandoned FA/PA entries are logged at debug level, not silently dropped
    assert re.search(r"log::add\([^)]*['\"]debug['\"]", fan_out_body), (
        "abandoned FA/PA entries must be logged at 'debug' level"
    )


def test_fan_out_purges_table_after_processing(fan_out_body: str) -> None:
    """
    Design (AC4): after emitting the BC fan-out (or the fallback), the table
    is emptied so a later burglaryCancel does not re-close stale entries.

    Expected result:
    - setCache('sia_open_alarms', ...) is called with an empty array
    """
    # Assert: the table is purged (written back empty) after fan-out
    assert re.search(
        r"setCache\s*\(\s*['\"]sia_open_alarms['\"]\s*,\s*\[\s*\]\s*\)", fan_out_body
    ), "sia_open_alarms must be purged (set back to []) once the fan-out is processed"


def test_fan_out_empty_table_falls_back_to_single_account_level_bc(fan_out_body: str) -> None:
    """
    Design (AC5): an empty table (duplicate cancel, cleared cache, daemon or
    Redis restart) must never produce zero frames — exactly one account-level
    BC is emitted, flagged with a warning so the operator sees the anomaly.

    Expected result:
    - an emptiness check on the BA entries exists
    - the fallback branch still calls sendToDaemon() with a null zone/zone_number
    - the fallback branch logs a 'warning'
    """
    # Assert: the code checks whether any BA entry was found before deciding the fallback
    assert re.search(r"empty\s*\(", fan_out_body) or re.search(r"===\s*0", fan_out_body), (
        "fan-out must check whether the open BA entries are empty to trigger the AC5 fallback"
    )
    # Assert: the fallback still dispatches a frame — AC5 forbids zero frames
    assert len(re.findall(r"sendToDaemon\s*\(", fan_out_body)) >= 2, (
        "the empty-table fallback must still call sendToDaemon() — AC5 forbids zero frames"
    )
    # Assert: the fallback is flagged with a warning so the anomaly is visible
    assert re.search(r"log::add\([^)]*['\"]warning['\"]", fan_out_body), (
        "the account-level fallback BC must be logged at 'warning' level"
    )
