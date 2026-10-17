"""
Cross-component config key consistency tests for Epic 8.

Verifies that configuration keys referenced in the wizard are consistent
across all three layers: PHP page (data-l2key bindings), JavaScript handlers,
and Python daemon (config dict access / CLI args).

A config key mismatch means the value is silently lost between layers —
saved in PHP but never read in Python, or displayed in JS but never persisted.

Reference: internal-docs/design/wizard-design.md
Reference: internal-docs/design/daemon-design.md
"""

import re
from pathlib import Path

import pytest
from tests.level1.test_php_eqlogic_stub import _extract_method_body

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PHP_PAGE = _PROJECT_ROOT / "desktop/php/siaDC09.php"
_JS_FILE = _PROJECT_ROOT / "desktop/js/siaDC09.js"
_PYTHON_ENTRY = _PROJECT_ROOT / "resources/siadc09d/siadc09d.py"
_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"
_PHP_CLASS = _PROJECT_ROOT / "core/class/siaDC09.class.php"
_PRESETS_PY = _PROJECT_ROOT / "resources/siadc09d/presets.py"


@pytest.fixture(scope="module")
def php_page() -> str:
    assert _PHP_PAGE.exists(), f"PHP page not found: {_PHP_PAGE}"
    return _PHP_PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_source() -> str:
    assert _JS_FILE.exists(), f"JS file not found: {_JS_FILE}"
    return _JS_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def php_class() -> str:
    assert _PHP_CLASS.exists(), f"PHP class not found: {_PHP_CLASS}"
    return _PHP_CLASS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def python_source() -> str:
    assert _PYTHON_ENTRY.exists(), f"Python entry not found: {_PYTHON_ENTRY}"
    return _PYTHON_ENTRY.read_text(encoding="utf-8")


# ── CSR config keys: PHP ↔ Python ─────────────────────────────────────────────

_CSR_CONFIG_KEYS = [
    "csr_ip",
    "csr_port",
    "transport",
    "account_number",
    "encryption_enabled",
    "encryption_key",
]

_CSR_KEYS_IN_PYTHON_CONFIG = [
    "csr_ip",
    "csr_port",
    "transport",
    "account_number",
    "encryption_enabled",
]


@pytest.mark.parametrize("key", _CSR_CONFIG_KEYS)
def test_csr_key_in_php_page(php_page: str, key: str) -> None:
    """
    Every CSR config key must appear as a data-l2key binding in the PHP page.
    Jeedom's getValues/setValues persists values matched by data-l2key.

    Expected result:
    - data-l2key="<key>" present in PHP page source
    """
    # Assert: PHP data-l2key binding present
    assert f'data-l2key="{key}"' in php_page, (
        f"Config key '{key}' missing from PHP page data-l2key bindings"
    )


@pytest.mark.parametrize("key", _CSR_KEYS_IN_PYTHON_CONFIG)
def test_csr_key_in_python_config_get(python_source: str, key: str) -> None:
    """
    CSR config keys (except encryption_key, passed via env) must be accessed
    via config.get("<key>") in the Python connection test entry point.
    Mismatch means PHP saves a value Python never reads.

    Expected result:
    - config.get("<key>" or equivalent access present in Python source
    """
    # Assert: Python reads this key from config or preset
    assert f'"{key}"' in python_source, (
        f"Config key '{key}' not referenced in Python entry point — "
        "PHP may save a value Python never reads"
    )


def test_encryption_key_passed_via_env(python_source: str) -> None:
    """
    encryption_key must NOT be in config dict — it is passed via
    SIA_ENCRYPTION_KEY environment variable for security (avoids process list).

    Expected result:
    - SIA_ENCRYPTION_KEY env var access present in Python source
    """
    # Assert: encryption key read from env, not config
    assert "SIA_ENCRYPTION_KEY" in python_source


# ── CSR config keys: PHP ↔ JS ─────────────────────────────────────────────────

_JS_STEP1_FIELDS = [
    "csr_ip",
    "csr_port",
    "transport",
    "account_number",
    "encryption_enabled",
    "encryption_key",
]


@pytest.mark.parametrize("key", _JS_STEP1_FIELDS)
def test_csr_key_in_js_validation(js_source: str, key: str) -> None:
    """
    Step 1 validation in JS must reference each user-editable CSR key.
    If JS validates a field that doesn't exist in PHP, or misses one, the
    wizard allows incomplete config through.

    Expected result:
    - data-l2key="<key>" selector pattern present in JS source
    """
    # Assert: JS references this key via data-l2key selector
    assert f'data-l2key="{key}"' in js_source, (
        f"Config key '{key}' not referenced in JS — validation may be incomplete"
    )


# ── Wizard state key: all layers ───────────────────────────────────────────────


def test_wizard_step_key_in_php(php_page: str) -> None:
    """
    sia_wizard_step must be bound in PHP for Jeedom persistence.

    Expected result:
    - data-l2key="sia_wizard_step" present
    """
    # Assert: wizard step key bound in PHP
    assert 'data-l2key="sia_wizard_step"' in php_page


def test_wizard_step_key_in_js(js_source: str) -> None:
    """
    JS must use data-l2key="sia_wizard_step" selector in siaDC09_setWizardStep().

    Expected result:
    - sia_wizard_step selector present in JS
    """
    # Assert: JS references wizard step key
    assert 'data-l2key="sia_wizard_step"' in js_source


# ── Notification command keys: PHP ↔ JS ───────────────────────────────────────

_NOTIFY_KEYS = ["sia_notify_cmd_id", "sia_notify_cmd_human"]


@pytest.mark.parametrize("key", _NOTIFY_KEYS)
def test_notify_key_in_php(php_page: str, key: str) -> None:
    """
    Notification command keys must be bound in PHP for persistence.

    Expected result:
    - data-l2key="<key>" present in PHP page
    """
    # Assert: notify key bound in PHP
    assert f'data-l2key="{key}"' in php_page


@pytest.mark.parametrize("key", _NOTIFY_KEYS)
def test_notify_key_in_js(js_source: str, key: str) -> None:
    """
    JS step 4 handler must reference notification keys for read/write.

    Expected result:
    - data-l2key="<key>" selector present in JS
    """
    # Assert: JS references notify key
    assert f'data-l2key="{key}"' in js_source


# ── Zone mapping key: JS saveEqLogic ↔ JS populateConfigSummary ────────────────


def test_zone_mappings_key_in_save(js_source: str) -> None:
    """
    saveEqLogic must write to sia_zone_mappings so zone data persists.

    Expected result:
    - sia_zone_mappings assignment present in JS saveEqLogic
    """
    # Assert: zone mappings key written in save
    assert "sia_zone_mappings" in js_source


def test_zone_mappings_key_in_summary(js_source: str) -> None:
    """
    populateConfigSummary must read sia_zone_mappings to display zone config.

    Expected result:
    - sia_zone_mappings access present in populateConfigSummary
    """
    pattern = r'siaDC09_populateConfigSummary.*?sia_zone_mappings'
    # Assert: summary reads zone mappings
    assert re.search(pattern, js_source, re.DOTALL), (
        "populateConfigSummary does not read sia_zone_mappings"
    )


# ── AJAX actions: JS callers ↔ PHP handlers ────────────────────────────────────

_AJAX_ACTIONS = ["testConnection", "getZones", "getFrigateCameras"]


@pytest.mark.parametrize("action", _AJAX_ACTIONS)
def test_ajax_action_called_from_js(js_source: str, action: str) -> None:
    """
    Each AJAX action defined in siaDC09.ajax.php must be called from JS.
    An action without a caller is dead code; a JS call without a handler fails.

    Expected result:
    - Action string present in JS AJAX data
    """
    # Assert: JS calls this AJAX action
    assert f"'{action}'" in js_source or f'"{action}"' in js_source, (
        f"AJAX action '{action}' not called from JS — dead code or missing caller"
    )


@pytest.mark.parametrize("action", _AJAX_ACTIONS)
def test_ajax_action_handled_in_php(action: str) -> None:
    """
    Each AJAX action called from JS must have a matching handler in PHP.

    Expected result:
    - init('action') == '<action>' check present in AJAX PHP file
    """
    ajax_source = _AJAX_FILE.read_text(encoding="utf-8")
    # Assert: PHP handles this action
    assert f"'{action}'" in ajax_source, (
        f"AJAX action '{action}' not handled in PHP — JS call will get 'no method' error"
    )


# ── Supervision config keys: PHP ↔ JS ↔ Python CLI ────────────────────────────

_SUPERVISION_KEYS = ["supervision_interval", "retry_count", "reconnect_delay"]


@pytest.mark.parametrize("key", _SUPERVISION_KEYS)
def test_supervision_key_in_php(php_page: str, key: str) -> None:
    """
    Supervision config keys must be bound in PHP page.

    Expected result:
    - data-l2key="<key>" present in PHP page
    """
    # Assert: supervision key bound in PHP
    assert f'data-l2key="{key}"' in php_page


@pytest.mark.parametrize("key", _SUPERVISION_KEYS)
def test_supervision_key_in_python_cli(python_source: str, key: str) -> None:
    """
    Python daemon CLI must accept supervision keys as arguments. The PHP
    core passes these when starting the daemon via exec().

    Expected result:
    - CLI argument matching the key present (with hyphens for argparse convention)
    """
    cli_arg = key.replace("_", "-")
    # Assert: Python CLI accepts this argument
    assert cli_arg in python_source, (
        f"Supervision key '{key}' (as --{cli_arg}) not in Python CLI — "
        "PHP passes it but daemon ignores it"
    )


# ── Periodic-frame config keys (Story 17.1, ADR-22): PHP class ↔ Python CLI ───

_PERIODIC_FRAME_KEYS = ["supervision_format", "rp_enabled", "rp_interval"]


@pytest.mark.parametrize("key", _PERIODIC_FRAME_KEYS)
def test_periodic_frame_key_read_by_deamon_start(php_class: str, key: str) -> None:
    """
    deamon_start() reads each periodic-frame equipment config key.

    Expected result:
    - getConfiguration('<key>' present in the deamon_start() body (not elsewhere in the class)
    """
    body = _extract_method_body(php_class, "deamon_start")
    # Assert: deamon_start reads the key before building the daemon command line
    assert f"getConfiguration('{key}'" in body, (
        f"Periodic-frame key '{key}' not read in siaDC09::deamon_start() — daemon never gets it"
    )


@pytest.mark.parametrize("key", _PERIODIC_FRAME_KEYS)
def test_periodic_frame_key_in_python_cli(python_source: str, key: str) -> None:
    """
    The daemon CLI accepts each periodic-frame key as --<key-with-hyphens>.

    Expected result:
    - '"--<key-with-hyphens>"' argument declared in siadc09d.py
    """
    cli_arg = "--" + key.replace("_", "-")
    # Assert: Python CLI declares the argument PHP passes
    assert f'"{cli_arg}"' in python_source, (
        f"Periodic-frame key '{key}' ({cli_arg}) not accepted by siadc09d.py"
    )


@pytest.mark.xfail(strict=True, reason="wizard field added by Story 17.4")
@pytest.mark.parametrize("key", _PERIODIC_FRAME_KEYS)
def test_periodic_frame_key_in_php_page(php_page: str, key: str) -> None:
    """
    The wizard binds each periodic-frame key (Story 17.4 turns this green).

    Expected result:
    - data-l2key="<key>" present in desktop/php/siaDC09.php
    """
    # Assert: wizard field bound to the exact config key deamon_start() reads
    assert f'data-l2key="{key}"' in php_page


@pytest.mark.parametrize("constant, php_name", [
    ("RP_INTERVAL_MIN_S", "RP_INTERVAL_MIN_S"),
    ("RP_INTERVAL_MAX_S", "RP_INTERVAL_MAX_S"),
])
def test_rp_interval_bounds_in_sync(php_class: str, constant: str, php_name: str) -> None:
    """
    The RP interval bounds are the same in CSRPreset (Python) and deamon_info()
    Guard 3e (PHP), so the PHP guard refuses exactly what the daemon would refuse
    and Jeedom's auto-restart never loops on a refused start (Story 17.1 AC7).

    Expected result:
    - the PHP class constant equals the Python module constant
    """
    py_match = re.search(rf"^{constant}: int = (\d+)", _PRESETS_PY.read_text(encoding="utf-8"), re.M)
    php_match = re.search(rf"const {php_name} = (\d+);", php_class)
    # Assert: both constants found
    assert py_match and php_match, f"{constant} missing on one side"
    # Assert: same bound value on both sides
    assert py_match.group(1) == php_match.group(1)
