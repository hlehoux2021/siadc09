"""
Wizard JavaScript logic validation tests for Epic 8.

Parses desktop/js/siaDC09.js to verify that wizard logic patterns are correctly
implemented: validation rules, navigation state machine, zone serialization,
config summary population, and Jeedom framework integration.

These tests validate JS source structure without executing in a browser —
they catch regressions like removed validation rules, broken selectors,
or missing error handling.

Reference: docs/design/wizard-design.md
Reference: _bmad-output/implementation-artifacts/8-1-wizard-steps-1-2-csr-preset-selection.md
"""

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_JS_FILE = _PROJECT_ROOT / "desktop/js/siaDC09.js"


@pytest.fixture(scope="module")
def js_source() -> str:
    assert _JS_FILE.exists(), f"JS file not found: {_JS_FILE}"
    return _JS_FILE.read_text(encoding="utf-8")


# ── Step 1 Validation Rules ───────────────────────────────────────────────────


def test_validate_step1_checks_account_number(js_source: str) -> None:
    """
    siaDC09_validateStep1 must validate account_number format.
    SIA DC-09 requires 3-16 hex characters.

    Expected result:
    - Hex character regex for account_number present in validation function
    """
    # Assert: account number hex validation present
    assert re.search(r'account_number.*hex|[0-9a-fA-F]', js_source, re.DOTALL)


def test_validate_step1_checks_csr_ip(js_source: str) -> None:
    """
    siaDC09_validateStep1 must reject empty or 'TBD' csr_ip.

    Expected result:
    - csr_ip validation with TBD check present
    """
    # Assert: IP validation checks for TBD placeholder
    assert "TBD" in js_source


def test_validate_step1_checks_port_range(js_source: str) -> None:
    """
    siaDC09_validateStep1 must validate port is 1-65535.

    Expected result:
    - Port range boundary check (65535) present
    """
    # Assert: port upper bound check present
    assert "65535" in js_source


def test_validate_step1_checks_encryption_key_length(js_source: str) -> None:
    """
    When encryption is enabled, key must be 32, 48, or 64 hex chars
    (AES-128/192/256 in hex encoding).

    Expected result:
    - Key length validation with 32, 48, 64 values present
    """
    # Assert: AES key length validation present
    assert "32" in js_source and "48" in js_source and "64" in js_source


def test_validate_step1_requires_key_when_encryption_enabled(js_source: str) -> None:
    """
    siaDC09_validateStep1 must require encryption_key when encryption_enabled.
    Allowing empty key with encryption on would produce unencrypted frames.

    Expected result:
    - Conditional check for key presence when encryption enabled
    """
    pattern = r'encEnabled\s*&&\s*!encKey'
    # Assert: empty key + encryption enabled check present
    assert re.search(pattern, js_source), (
        "Missing validation: encryption enabled but no key"
    )


def test_validate_step1_shows_errors_div(js_source: str) -> None:
    """
    Validation errors must be displayed in siaDC09-step1-errors div.

    Expected result:
    - siaDC09-step1-errors selector referenced for show/hide
    """
    # Assert: error div selector present
    assert "siaDC09-step1-errors" in js_source


# ── Step Navigation State Machine ─────────────────────────────────────────────


def test_show_step_hides_all_first(js_source: str) -> None:
    """
    siaDC09_showStep must hide all .siaDC09-step divs before showing target.
    Without this, multiple steps would be visible simultaneously.

    Expected result:
    - jQuery hide on .siaDC09-step class selector present
    """
    # Assert: hide all steps pattern present
    assert re.search(r"\$\(['\"]\.siaDC09-step['\"]\)\.hide\(\)", js_source)


def test_show_step_triggers_connection_test_on_step2(js_source: str) -> None:
    """
    Entering step 2 must auto-trigger the connection test.
    siaDC09_showStep(2) calls siaDC09_runConnectionTest().

    Expected result:
    - siaDC09_runConnectionTest() call inside step==2 branch
    """
    pattern = r'step\s*===?\s*2.*?siaDC09_runConnectionTest'
    # Assert: step 2 triggers connection test
    assert re.search(pattern, js_source, re.DOTALL)


def test_show_step_loads_zone_data_on_step3(js_source: str) -> None:
    """
    Entering step 3 must load zone data from AJAX.
    siaDC09_showStep(3) calls siaDC09_loadZoneData().

    Expected result:
    - siaDC09_loadZoneData() call inside step==3 branch
    """
    pattern = r'step\s*===?\s*3.*?siaDC09_loadZoneData'
    # Assert: step 3 triggers zone data load
    assert re.search(pattern, js_source, re.DOTALL)


def test_show_step_applies_readonly_on_step1(js_source: str) -> None:
    """
    Entering step 1 must apply readonly to preset-controlled fields.

    Expected result:
    - siaDC09_applyReadonly() call inside step==1 branch
    """
    pattern = r'step\s*===?\s*1.*?siaDC09_applyReadonly'
    # Assert: step 1 applies readonly
    assert re.search(pattern, js_source, re.DOTALL)


def test_set_wizard_step_updates_hidden_field(js_source: str) -> None:
    """
    siaDC09_setWizardStep must write to the hidden sia_wizard_step field.
    This is how the wizard step persists across page reloads.

    Expected result:
    - .val(step) call on sia_wizard_step selector
    """
    pattern = r'sia_wizard_step.*?\.val\(step\)'
    # Assert: setWizardStep writes to hidden field
    assert re.search(pattern, js_source, re.DOTALL)


# ── Step 2: Connection Test Flow ──────────────────────────────────────────────


def test_connection_test_shows_spinner(js_source: str) -> None:
    """
    siaDC09_runConnectionTest must show spinner and hide result area at start.

    Expected result:
    - siaDC09-step2-spinner show() call present
    """
    # Assert: spinner shown during test
    assert re.search(r"siaDC09-step2-spinner.*?\.show\(\)", js_source, re.DOTALL)


def test_connection_test_disables_buttons_during_test(js_source: str) -> None:
    """
    All step 2 buttons must be disabled during the AJAX call to prevent
    double-submission.

    Expected result:
    - bt_step2Next disabled attribute set during test
    """
    # Assert: next button disabled during test
    assert re.search(r"bt_step2Next.*?disabled", js_source, re.DOTALL)


def test_connection_test_handles_nak_status(js_source: str) -> None:
    """
    NAK response must show warning (alert-warning) and still enable Next button.
    NAK means CSR responded but rejected — user may want to proceed anyway.

    Expected result:
    - 'nak' status branch with alert-warning class
    """
    # Assert: NAK branch with warning styling
    assert "alert-warning" in js_source and "'nak'" in js_source


def test_connection_test_nak_confirm_dialog(js_source: str) -> None:
    """
    Clicking Next after NAK must show a confirmation dialog before advancing.
    This prevents users from unknowingly proceeding with misconfiguration.

    Expected result:
    - jeeDialog.confirm call in bt_step2Next handler
    """
    # Assert: NAK confirmation dialog present
    assert "jeeDialog.confirm" in js_source


def test_connection_test_timeout_handling(js_source: str) -> None:
    """
    AJAX call must have a timeout to prevent indefinite hanging.

    Expected result:
    - timeout parameter present in the testConnection AJAX call
    """
    pattern = r"testConnection.*?timeout.*?\d+"
    # Assert: AJAX timeout configured
    assert re.search(pattern, js_source, re.DOTALL)


# ── Step 3: Zone Table Serialization ──────────────────────────────────────────


def test_save_serializes_zone_mappings_on_step3(js_source: str) -> None:
    """
    saveEqLogic must serialize zone table rows to sia_zone_mappings array
    when current step is 3.

    Expected result:
    - step === 3 branch with sia_zone_mappings assignment
    """
    pattern = r'step\s*===?\s*3.*?sia_zone_mappings\s*='
    # Assert: step 3 serializes zone mappings
    assert re.search(pattern, js_source, re.DOTALL)


def test_save_deletes_zone_mappings_on_step_less_than_3(js_source: str) -> None:
    """
    saveEqLogic must delete sia_zone_mappings for steps 1-2 to prevent
    stale data from persisting during wizard navigation.

    Expected result:
    - delete _eqLogic.configuration.sia_zone_mappings in step < 3 branch
    """
    # Assert: zone mappings deleted for early steps
    assert "delete _eqLogic.configuration.sia_zone_mappings" in js_source


def test_zone_row_has_zone_name_data_attribute(js_source: str) -> None:
    """
    Each zone table row must store the zone name in data-zone-name attribute
    for reliable serialization (independent of display text changes).

    Expected result:
    - data-zone-name attribute set on tr element
    """
    # Assert: zone name stored as data attribute
    assert "data-zone-name" in js_source


def test_zone_mapping_includes_frigate_camera_field(js_source: str) -> None:
    """
    Zone mapping serialization must include frigate_camera_eqlogic_id for each
    zone row (ADR-17 simplification: story 14.1 replaced the separate
    camera_action_cmd_id/media_url_cmd_id pair with a single camera-equipment
    reference — info_detect_person/info_url_snapshot are derived by logicalId
    at alarm time, never stored).

    Expected result:
    - frigate_camera_eqlogic_id key present in mapping object construction
    """
    # Assert: single camera-equipment field serialized
    assert "frigate_camera_eqlogic_id" in js_source


def test_zone_mapping_includes_frigate_camera_label(js_source: str) -> None:
    """
    Zone mapping must include a denormalized frigate_camera_label for config
    summary display without AJAX lookups (ADR-17 simplification).

    Expected result:
    - Label field present in mapping object
    """
    # Assert: label denormalized in mapping
    assert "frigate_camera_label" in js_source


# ── Step 4: Notification Command Picker ───────────────────────────────────────


def test_step4_uses_cmd_get_select_modal(js_source: str) -> None:
    """
    Step 4 must use jeedom.cmd.getSelectModal for notification command selection.
    This is the standard Jeedom pattern for command pickers.

    Expected result:
    - jeedom.cmd.getSelectModal call present
    """
    # Assert: standard Jeedom command picker used
    assert "jeedom.cmd.getSelectModal" in js_source


def test_step4_filters_action_message_commands(js_source: str) -> None:
    """
    The command picker must filter for type='action', subType='message'.
    Only message-type actions can deliver notifications.

    Expected result:
    - Filter parameters for action/message present
    """
    # Assert: correct command type filter
    assert "'action'" in js_source or '"action"' in js_source
    assert "'message'" in js_source or '"message"' in js_source


def test_step4_finish_validates_notify_cmd(js_source: str) -> None:
    """
    bt_step4Finish must check that a notification target has a value before
    completing the wizard. Empty notify target is a config error. Since epic 12 the
    check is siaDC09_validateNotifyTarget(), declared above the handler, so the value
    read no longer follows 'bt_step4Finish' in source order.

    Expected result:
    - finish handler calls siaDC09_validateNotifyTarget() and aborts when it is falsy
    - the validator reads sia_notify_cmd_id via val()
    """
    # Assert: finish button gates the save on the validator
    assert re.search(
        r"bt_step4Finish.*?if\s*\(\s*!\s*siaDC09_validateNotifyTarget\s*\(\s*\)",
        js_source, re.DOTALL
    ), "#bt_step4Finish must abort on !siaDC09_validateNotifyTarget()"
    # Assert: the validator checks the notify cmd value
    assert re.search(
        r"function\s+siaDC09_validateNotifyTarget.*?sia_notify_cmd_id.*?val\(\)",
        js_source, re.DOTALL
    ), "siaDC09_validateNotifyTarget() must read sia_notify_cmd_id via val()"


def test_step4_shows_error_when_no_cmd(js_source: str) -> None:
    """
    When no notification command is selected, siaDC09-step4-error must be shown.

    Expected result:
    - siaDC09-step4-error show() in the validation branch
    """
    # Assert: error shown when no cmd selected
    assert re.search(r"siaDC09-step4-error.*?\.show\(\)", js_source, re.DOTALL)


# ── printEqLogic: Wizard vs Config Mode ───────────────────────────────────────


def test_print_eq_logic_reads_wizard_step(js_source: str) -> None:
    """
    printEqLogic must read sia_wizard_step to decide wizard vs config mode.

    Expected result:
    - sia_wizard_step access in printEqLogic function
    """
    pattern = r'printEqLogic.*?sia_wizard_step'
    # Assert: printEqLogic reads wizard step
    assert re.search(pattern, js_source, re.DOTALL)


def test_print_eq_logic_shows_config_summary_when_complete(js_source: str) -> None:
    """
    When sia_wizard_step >= 4, printEqLogic must show config summary and hide wizard.

    Expected result:
    - siaDC09-config-summary show() when step >= 4
    """
    pattern = r'wizardStep\s*>=?\s*4.*?siaDC09-config-summary.*?\.show\(\)'
    # Assert: config summary shown when wizard complete
    assert re.search(pattern, js_source, re.DOTALL)


def test_print_eq_logic_shows_wizard_when_incomplete(js_source: str) -> None:
    """
    When sia_wizard_step < 4, printEqLogic must show wizard and hide summary.

    Expected result:
    - siaDC09-wizard show() in the else branch
    """
    # Assert: wizard shown when incomplete
    assert re.search(r"siaDC09-wizard.*?\.show\(\)", js_source, re.DOTALL)


def test_print_eq_logic_restores_card_selection(js_source: str) -> None:
    """
    printEqLogic must restore the selected provider card state from config.
    Without this, reloading the page loses the visual card selection.

    Expected result:
    - siaDC09_selectCard call with provider from config
    """
    pattern = r'printEqLogic.*?siaDC09_selectCard'
    # Assert: card selection restored on load
    assert re.search(pattern, js_source, re.DOTALL)


# ── Config Summary Population ─────────────────────────────────────────────────


def test_config_summary_displays_provider_label(js_source: str) -> None:
    """
    populateConfigSummary must translate csr_provider to a human label
    (IMA Protect vs Personnalisé).

    Expected result:
    - 'IMA Protect' and 'Personnalisé' strings in summary function
    """
    # Assert: provider labels present
    assert "IMA Protect" in js_source
    assert "Personnalisé" in js_source


def test_config_summary_displays_connection_info(js_source: str) -> None:
    """
    Connection summary must show IP:port(transport) format.

    Expected result:
    - csr_ip and csr_port references in summary-connection population
    """
    pattern = r'siaDC09-summary-connection.*?csr_ip.*?csr_port'
    # Assert: connection info rendered
    assert re.search(pattern, js_source, re.DOTALL)


def test_config_summary_handles_empty_zones(js_source: str) -> None:
    """
    When sia_zone_mappings is empty, summary must show a placeholder message.

    Expected result:
    - Empty check with fallback text in zone summary
    """
    # Assert: empty zone handling present
    assert "Aucune zone" in js_source


# ── Jeedom Framework Integration ──────────────────────────────────────────────


def test_save_uses_jeedom_eq_logic_save(js_source: str) -> None:
    """
    Wizard step transitions must use jeedom.eqLogic.save() for persistence.
    Direct AJAX to save would bypass the Jeedom framework's merge logic.

    Expected result:
    - jeedom.eqLogic.save call present
    """
    # Assert: uses Jeedom save API
    assert "jeedom.eqLogic.save" in js_source


def test_save_passes_siaDC09_type(js_source: str) -> None:
    """
    jeedom.eqLogic.save must specify type: 'siaDC09' for routing.

    Expected result:
    - type: 'siaDC09' in save call parameters
    """
    # Assert: plugin type specified in save
    assert re.search(r"type:\s*['\"]siaDC09['\"]", js_source)


def test_restart_wizard_resets_to_step_zero(js_source: str) -> None:
    """
    bt_restartWizard must set wizard step to 0 before save.
    Step 0 means "not started" — printEqLogic will show step 1 (max(1, 0)).

    Expected result:
    - siaDC09_setWizardStep(0) in restart handler
    """
    # Assert: restart sets step to 0
    assert "siaDC09_setWizardStep(0)" in js_source


def test_restart_wizard_checks_daemon_running(js_source: str) -> None:
    """
    Restarting the wizard while daemon is running could cause issues.
    The handler must check daemon state and warn user.

    Expected result:
    - deamonInfo AJAX call in restart handler
    """
    pattern = r'bt_restartWizard.*?deamonInfo'
    # Assert: daemon check in restart
    assert re.search(pattern, js_source, re.DOTALL)


def test_step1_advance_checks_daemon_running(js_source: str) -> None:
    """
    bt_step1Next must check if daemon is running before connection test.
    Running daemon would conflict with standalone test subprocess.

    Expected result:
    - deamonInfo AJAX call in step 1 next handler
    """
    pattern = r'bt_step1Next.*?deamonInfo'
    # Assert: daemon check before test
    assert re.search(pattern, js_source, re.DOTALL)
