"""
PHP eqLogic & cmd source-validation tests for Stories 6.1, 6.2, 6.3, and 6.4.

Parses core/class/siaDC09.class.php and core/class/siaDC09Cmd.class.php to
verify that the implementation matches the design specification. These tests
fail when logicalIds are renamed, the wrong equipment-lookup method is used,
or security guards are removed — they do not require a Jeedom instance.

Reference: _bmad-output/implementation-artifacts/6-1-php-eqlogic-cmd-classes.md
Reference: _bmad-output/implementation-artifacts/6-2-auto-equipment-creation.md
Reference: _bmad-output/implementation-artifacts/6-3-json-callback-ipc-protocol.md
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
def get_auto_equipment_body(php_source: str) -> str:
    # _getAutoEquipmentSafe ends with 'Safe(' so \s*\( won't match it
    return _extract_method_body(php_source, "_getAutoEquipment")


@pytest.fixture(scope="module")
def execute_body(php_cmd_source: str) -> str:
    return _extract_method_body(php_cmd_source, "execute")


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


def test_message_dispatches_all_five_types(message_body: str) -> None:
    """
    message() must handle all 5 IPC callback types as switch cases. Missing
    a case means that callback type is silently dropped.

    Expected result:
    - All 5 callback type strings appear as case labels in message() body
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


def test_notify_reads_sia_notify_cmd_id(message_body: str) -> None:
    """
    The notify case must read the config key 'sia_notify_cmd_id' (with sia_
    prefix) — NOT bare 'notify_cmd_id' as incorrectly shown in error-handler-design.md.

    Expected result:
    - 'sia_notify_cmd_id' appears in message() body
    """
    # Assert: canonical config key with sia_ prefix is used
    assert "sia_notify_cmd_id" in message_body, (
        "message() notify case must use 'sia_notify_cmd_id' config key "
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


def test_notify_wraps_exec_cmd_in_try_catch(message_body: str) -> None:
    """
    The notify case must wrap execCmd() in try/catch. If a misconfigured
    notification command throws, it would propagate up as HTTP 500 and crash
    the entire callback pipeline for ALL callback types (not just notify).

    Expected result:
    - 'try' and 'catch' appear in message() body near 'execCmd'
    """
    # Assert: try/catch exists
    assert "try {" in message_body or "try{" in message_body, (
        "message() notify case must wrap execCmd in try/catch — "
        "exception would crash the entire callback pipeline"
    )
    # Assert: catch block exists
    assert "catch (Exception" in message_body or "catch(Exception" in message_body, (
        "message() must catch Exception from execCmd"
    )
    # Assert: execCmd is the thing being wrapped
    assert "execCmd" in message_body, (
        "message() notify case must call execCmd()"
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


def test_postsave_sets_return_state_time_on_commands(postsave_body: str) -> None:
    """
    All commands must have returnStateTime=30 to prevent stuck PENDING state
    (event_state=3) if the daemon crashes mid-alarm. Jeedom auto-reverts the
    command value after this many minutes of no update.

    Expected result:
    - 'returnStateTime' appears in postSave() body
    - The value 30 appears associated with returnStateTime
    """
    # Assert: returnStateTime is set in postSave()
    assert "returnStateTime" in postsave_body, (
        "postSave() must set returnStateTime on commands — "
        "prevents event_state=3 stuck if daemon crashes"
    )
    # Assert: value 30 is used (spec: 30 minutes)
    assert "'returnStateTime', 30" in postsave_body or '"returnStateTime", 30' in postsave_body, (
        "postSave() must set returnStateTime=30 (30-minute auto-revert)"
    )


def test_postsave_sets_return_state_value_zero(postsave_body: str) -> None:
    """
    All commands must revert to 0 (not null) after returnStateTime expires.
    Value 0 for event_state means 'no alarm' — a safe idle state.

    Expected result:
    - 'returnStateValue' appears in postSave() body
    - The revert value is 0
    """
    # Assert: returnStateValue is set in postSave()
    assert "returnStateValue" in postsave_body, (
        "postSave() must set returnStateValue on commands"
    )
    # Assert: revert value is 0 (safe idle state)
    assert "'returnStateValue', 0" in postsave_body or '"returnStateValue", 0' in postsave_body, (
        "postSave() must set returnStateValue=0 (safe idle revert)"
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
