"""
Wizard PHP page structure validation tests for Epic 8.

Parses desktop/php/siaDC09.php to verify that wizard HTML structure matches
the design specification: correct data-l2key bindings, step div IDs, button IDs,
preset data attributes, and Jeedom integration patterns.

These tests fail if HTML elements are renamed, data attributes are removed,
or the wizard structure is broken — no Jeedom instance required.

Reference: docs/design/wizard-design.md
Reference: _bmad-output/implementation-artifacts/8-1-wizard-steps-1-2-csr-preset-selection.md
Reference: _bmad-output/implementation-artifacts/8-2-wizard-steps-3-4-zone-mapping.md
"""

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PHP_PAGE = _PROJECT_ROOT / "desktop/php/siaDC09.php"


@pytest.fixture(scope="module")
def php_page() -> str:
    assert _PHP_PAGE.exists(), f"Wizard PHP page not found: {_PHP_PAGE}"
    return _PHP_PAGE.read_text(encoding="utf-8")


# ── Wizard Step Structure ────────────────────────────────────────────────────


def test_wizard_root_div_exists(php_page: str) -> None:
    """
    The wizard root container must have id="siaDC09-wizard".
    printEqLogic() toggles this div's visibility based on sia_wizard_step.

    Expected result:
    - id="siaDC09-wizard" div exists in the PHP page
    """
    # Assert: wizard root div present
    assert 'id="siaDC09-wizard"' in php_page


def test_config_summary_div_exists(php_page: str) -> None:
    """
    The config summary container must have id="siaDC09-config-summary".
    Shown when sia_wizard_step == 4 (wizard complete).

    Expected result:
    - id="siaDC09-config-summary" div exists
    """
    # Assert: config summary div present
    assert 'id="siaDC09-config-summary"' in php_page


@pytest.mark.parametrize("step_id", [
    "siaDC09-step1",
    "siaDC09-step2",
    "siaDC09-step3",
    "siaDC09-step4",
])
def test_step_div_exists(php_page: str, step_id: str) -> None:
    """
    Each wizard step must have a dedicated div with the expected ID pattern.
    siaDC09_showStep(n) targets these IDs to show/hide steps.

    Expected result:
    - Each step div exists with correct ID
    """
    # Assert: step div present
    assert f'id="{step_id}"' in php_page, (
        f"Step div '{step_id}' not found — siaDC09_showStep() will fail"
    )


@pytest.mark.parametrize("step_id", [
    "siaDC09-step1",
    "siaDC09-step2",
    "siaDC09-step3",
    "siaDC09-step4",
])
def test_step_div_has_class_marker(php_page: str, step_id: str) -> None:
    """
    Each step div must have class="siaDC09-step" for jQuery selector
    targeting in siaDC09_showStep() which hides all .siaDC09-step first.

    Expected result:
    - The step div includes the siaDC09-step class
    """
    pattern = rf'id="{step_id}"[^>]*class="[^"]*siaDC09-step[^"]*"'
    # Assert: class marker present on step div
    assert re.search(pattern, php_page), (
        f"'{step_id}' missing class='siaDC09-step' — "
        "siaDC09_showStep() hides all .siaDC09-step before showing target"
    )


# ── Hidden wizard_step field (Jeedom save contract) ─────────────────────────


def test_hidden_wizard_step_field_exists(php_page: str) -> None:
    """
    A hidden input with data-l2key="sia_wizard_step" must exist in the page.
    siaDC09_setWizardStep() writes to this field; Jeedom framework reads it
    via getValues('.eqLogicAttr') during save.

    Expected result:
    - Hidden input with correct data-l2key present
    """
    # Assert: hidden wizard step field present
    assert 'data-l2key="sia_wizard_step"' in php_page


def test_wizard_step_field_is_hidden_input(php_page: str) -> None:
    """
    The sia_wizard_step field must be type="hidden" — not visible to users.
    A visible field would confuse non-technical users and allow direct editing.

    Expected result:
    - The input with data-l2key="sia_wizard_step" has type="hidden"
    """
    pattern = r'<input[^>]*type="hidden"[^>]*data-l2key="sia_wizard_step"'
    alt_pattern = r'<input[^>]*data-l2key="sia_wizard_step"[^>]*type="hidden"'
    # Assert: field is hidden type
    assert re.search(pattern, php_page) or re.search(alt_pattern, php_page), (
        "sia_wizard_step field must be type='hidden'"
    )


# ── Step 1: CSR Fields with correct data-l2key bindings ─────────────────────


_STEP1_CONFIG_FIELDS = [
    "csr_provider",
    "csr_ip",
    "csr_port",
    "transport",
    "account_number",
    "encryption_enabled",
    "encryption_key",
    "supervision_interval",
    "retry_count",
    "reconnect_delay",
]


@pytest.mark.parametrize("field", _STEP1_CONFIG_FIELDS)
def test_step1_config_field_binding(php_page: str, field: str) -> None:
    """
    Every config field in step 1 must use data-l2key="<field>" for the
    Jeedom getValues/setValues save contract. Wrong data-l2key means the
    value is never persisted to the eqLogic configuration.

    Expected result:
    - data-l2key="<field>" appears in the PHP page source
    """
    # Assert: data-l2key binding present
    assert f'data-l2key="{field}"' in php_page, (
        f"Config field '{field}' missing data-l2key binding — "
        "value will not be saved by Jeedom framework"
    )


def test_step1_csr_fields_have_readonly_class(php_page: str) -> None:
    """
    CSR preset-controlled fields must have class="siaDC09-csr-field" so
    siaDC09_applyReadonly() can target them via jQuery selector.
    account_number and encryption_key are NOT in this class (always editable).

    Expected result:
    - Multiple elements have the siaDC09-csr-field class
    """
    matches = re.findall(r'siaDC09-csr-field', php_page)
    # Assert: at least 4 fields have the readonly-targetable class
    assert len(matches) >= 4, (
        f"Expected >= 4 elements with 'siaDC09-csr-field' class, found {len(matches)}"
    )


def test_account_number_not_csr_field_class(php_page: str) -> None:
    """
    account_number must NOT have class siaDC09-csr-field — it is always
    editable regardless of preset mode (subscriber-specific, not preset value).

    Expected result:
    - The line containing data-l2key="account_number" does NOT also contain
      siaDC09-csr-field
    """
    for line in php_page.split('\n'):
        if 'data-l2key="account_number"' in line:
            # Assert: account_number is not in the readonly-targetable class
            assert 'siaDC09-csr-field' not in line, (
                "account_number must NOT have siaDC09-csr-field class — "
                "it should always be editable"
            )
            return
    pytest.fail("data-l2key='account_number' not found in page")


# ── Step 1: Preset cards ────────────────────────────────────────────────────


def test_ima_protect_card_has_data_provider(php_page: str) -> None:
    """
    IMA Protect card must have data-provider="ima_protect" for the click
    handler to identify which preset was selected.

    Expected result:
    - data-provider="ima_protect" present on a card element
    """
    # Assert: data-provider attribute present
    assert 'data-provider="ima_protect"' in php_page


def test_manual_card_has_data_provider(php_page: str) -> None:
    """
    Personnalisé card must have data-provider="manual" for the click handler.

    Expected result:
    - data-provider="manual" present on a card element
    """
    # Assert: data-provider attribute present
    assert 'data-provider="manual"' in php_page


def test_ima_preset_data_attributes_rendered(php_page: str) -> None:
    """
    The IMA Protect card must render data-preset-* attributes from the preset
    JSON loaded server-side. These attributes are read by siaDC09_fillFromPreset()
    to populate CSR fields without an AJAX call.

    Expected result:
    - data-preset-csr_port and data-preset-transport attributes present
    """
    # Assert: preset data attributes are rendered server-side
    assert 'data-preset-csr_port' in php_page
    assert 'data-preset-transport' in php_page


# ── Step 2: Connection test UI elements ─────────────────────────────────────


def test_step2_spinner_div_exists(php_page: str) -> None:
    """
    Step 2 must have a spinner div shown during connection test.

    Expected result:
    - id="siaDC09-step2-spinner" present
    """
    # Assert: spinner div present
    assert 'id="siaDC09-step2-spinner"' in php_page


def test_step2_result_div_exists(php_page: str) -> None:
    """
    Step 2 must have a result area for displaying test outcome.

    Expected result:
    - id="siaDC09-step2-result" present
    """
    # Assert: result area present
    assert 'id="siaDC09-step2-result"' in php_page


@pytest.mark.parametrize("btn_id", ["bt_step2Retest", "bt_step2Skip", "bt_step2Next"])
def test_step2_buttons_exist(php_page: str, btn_id: str) -> None:
    """
    Step 2 must have three navigation buttons: retest, skip, and next.

    Expected result:
    - Each button ID present in the page
    """
    # Assert: button present
    assert f'id="{btn_id}"' in php_page, (
        f"Button '{btn_id}' not found in step 2"
    )


# ── Step 3: Zone table structure ────────────────────────────────────────────


def test_step3_zone_table_exists(php_page: str) -> None:
    """
    Step 3 must have a zone mapping table with id="siaDC09-zone-table".
    siaDC09_loadZoneTable() populates its tbody dynamically.

    Expected result:
    - id="siaDC09-zone-table" present
    """
    # Assert: zone table present
    assert 'id="siaDC09-zone-table"' in php_page


def test_step3_zone_tbody_exists(php_page: str) -> None:
    """
    The zone table must have a tbody with id="siaDC09-zone-tbody" for
    dynamic row insertion by siaDC09_loadZoneTable().

    Expected result:
    - id="siaDC09-zone-tbody" present
    """
    # Assert: zone tbody present
    assert 'id="siaDC09-zone-tbody"' in php_page


def test_step3_nozone_warning_exists(php_page: str) -> None:
    """
    Step 3 must have a hidden warning div shown when no alarm zones are found.

    Expected result:
    - id="siaDC09-step3-nozone" present
    """
    # Assert: nozone warning div present
    assert 'id="siaDC09-step3-nozone"' in php_page


# ── Step 4: Notification command picker ─────────────────────────────────────


def test_step4_notify_cmd_human_field(php_page: str) -> None:
    """
    Step 4 must have a readonly text input bound to sia_notify_cmd_human
    for displaying the selected notification command label.

    Expected result:
    - data-l2key="sia_notify_cmd_human" present with readonly attribute
      on the same input element (may span multiple lines)
    """
    # Assert: notify cmd human display field present
    assert 'data-l2key="sia_notify_cmd_human"' in php_page
    pattern = r'<input[^>]*data-l2key="sia_notify_cmd_human"[^>]*readonly'
    alt_pattern = r'<input[^>]*readonly[^>]*data-l2key="sia_notify_cmd_human"'
    # Assert: field is readonly (display-only)
    assert re.search(pattern, php_page, re.DOTALL) or re.search(alt_pattern, php_page, re.DOTALL), (
        "sia_notify_cmd_human field must be readonly"
    )


def test_step4_notify_cmd_id_hidden_field(php_page: str) -> None:
    """
    Step 4 must have a hidden input bound to sia_notify_cmd_id for storing
    the selected command's ID. This is persisted to eqLogic config.

    Expected result:
    - data-l2key="sia_notify_cmd_id" present as hidden input
    """
    # Assert: notify cmd id hidden field present
    assert 'data-l2key="sia_notify_cmd_id"' in php_page


def test_step4_search_button_exists(php_page: str) -> None:
    """
    Step 4 must have the search button that opens jeedom.cmd.getSelectModal().

    Expected result:
    - id="siaDC09_searchNotifyCmd" button present
    """
    # Assert: search button present
    assert 'id="siaDC09_searchNotifyCmd"' in php_page


def test_step4_finish_button_exists(php_page: str) -> None:
    """
    Step 4 must have the "Terminer" button to complete the wizard.

    Expected result:
    - id="bt_step4Finish" button present
    """
    # Assert: finish button present
    assert 'id="bt_step4Finish"' in php_page


def test_step4_error_div_exists(php_page: str) -> None:
    """
    Step 4 must have an error div shown when notify cmd is not selected.

    Expected result:
    - id="siaDC09-step4-error" div present
    """
    # Assert: step 4 error div present
    assert 'id="siaDC09-step4-error"' in php_page


# ── Navigation buttons across all steps ─────────────────────────────────────


@pytest.mark.parametrize("btn_id", [
    "bt_step1Next",
    "bt_step2Next",
    "bt_step3Next",
    "bt_step4Finish",
    "bt_restartWizard",
    "bt_personnaliser",
])
def test_navigation_button_exists(php_page: str, btn_id: str) -> None:
    """
    Every wizard navigation button referenced in siaDC09.js must have a
    matching HTML element with the expected ID.

    Expected result:
    - Each button ID present in the page
    """
    # Assert: navigation button present
    assert f'id="{btn_id}"' in php_page, (
        f"Button '{btn_id}' not found — JS handler will not bind"
    )


# ── Config summary display areas ────────────────────────────────────────────


@pytest.mark.parametrize("div_id", [
    "siaDC09-summary-connection",
    "siaDC09-summary-zones",
    "siaDC09-summary-notify",
])
def test_config_summary_area_exists(php_page: str, div_id: str) -> None:
    """
    Config summary mode (step==4) must have display areas for connection,
    zones, and notification info. siaDC09_populateConfigSummary() targets these.

    Expected result:
    - Each summary area div exists
    """
    # Assert: summary area present
    assert f'id="{div_id}"' in php_page, (
        f"Config summary area '{div_id}' not found — "
        "siaDC09_populateConfigSummary() will fail"
    )


# ── JS inclusion at bottom ──────────────────────────────────────────────────


def test_js_file_included_at_bottom(php_page: str) -> None:
    """
    siaDC09.js must be included at the bottom of the PHP page via Jeedom's
    include_file() function. This is the standard Jeedom pattern.

    Expected result:
    - include_file call for siaDC09 JS present
    """
    # Assert: JS inclusion present
    assert re.search(r"include_file\s*\(\s*'desktop'\s*,\s*'siaDC09'\s*,\s*'js'", php_page), (
        "desktop/js/siaDC09.js not included via include_file() at page bottom"
    )


def test_plugin_template_js_included(php_page: str) -> None:
    """
    plugin.template.js must be included — required for Jeedom command table
    rendering (addCmdToTable).

    Expected result:
    - include_file call for plugin.template.js present
    """
    # Assert: plugin template JS present
    assert "plugin.template" in php_page


# ── Jeedom page skeleton ────────────────────────────────────────────────────


def test_page_has_admin_auth_check(php_page: str) -> None:
    """
    The PHP page must check isConnect('admin') to prevent unauthorized access.

    Expected result:
    - isConnect('admin') check present
    """
    # Assert: admin auth check present
    assert "isConnect('admin')" in php_page


def test_page_has_send_var_to_js(php_page: str) -> None:
    """
    sendVarToJS must set eqType so Jeedom JS framework knows the plugin ID.

    Expected result:
    - sendVarToJS('eqType', ...) call present
    """
    # Assert: sendVarToJS present
    assert "sendVarToJS" in php_page


def test_page_has_table_cmd(php_page: str) -> None:
    """
    A table with id="table_cmd" must exist — Jeedom framework requires it
    for the command management tab.

    Expected result:
    - id="table_cmd" present
    """
    # Assert: command table present
    assert 'id="table_cmd"' in php_page
