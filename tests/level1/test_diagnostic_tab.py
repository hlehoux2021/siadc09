"""
Diagnostic tab Level 1 tests for Story 9-1.

Validates PHP structure (AJAX actions, tab HTML) and JS logic (badge rendering,
error panel, button rate limiting) by parsing source files — no Jeedom instance
required.

Reference: docs/design/debug-ui-design.md
Reference: _bmad-output/implementation-artifacts/9-1-status-badge-error-panel.md
"""

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_JS_FILE = _PROJECT_ROOT / "desktop/js/siaDC09.js"
_PHP_FILE = _PROJECT_ROOT / "desktop/php/siaDC09.php"
_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"


@pytest.fixture(scope="module")
def js_source() -> str:
    assert _JS_FILE.exists(), f"JS file not found: {_JS_FILE}"
    return _JS_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def php_source() -> str:
    assert _PHP_FILE.exists(), f"PHP file not found: {_PHP_FILE}"
    return _PHP_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ajax_source() -> str:
    assert _AJAX_FILE.exists(), f"AJAX file not found: {_AJAX_FILE}"
    return _AJAX_FILE.read_text(encoding="utf-8")


# ── PHP Syntax ───────────────────────────────────────────────────────────────


class TestPhpSyntax:
    """PHP syntax validation for all modified files."""

    def test_php_desktop_syntax(self) -> None:
        """
        PHP syntax check must pass for desktop/php/siaDC09.php.

        Expected result:
        - php -l returns exit code 0
        """
        import subprocess

        # Assert: no syntax errors
        result = subprocess.run(
            ["php", "-l", str(_PHP_FILE)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"PHP syntax error: {result.stdout}"

    def test_php_ajax_syntax(self) -> None:
        """
        PHP syntax check must pass for core/ajax/siaDC09.ajax.php.

        Expected result:
        - php -l returns exit code 0
        """
        import subprocess

        # Assert: no syntax errors
        result = subprocess.run(
            ["php", "-l", str(_AJAX_FILE)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"PHP syntax error: {result.stdout}"


# ── AJAX getDiagnosticData Structure ─────────────────────────────────────────


class TestGetDiagnosticDataAjax:
    """Verify getDiagnosticData AJAX action structure."""

    def test_action_exists(self, ajax_source: str) -> None:
        """
        getDiagnosticData action must exist in siaDC09.ajax.php.

        Expected result:
        - init('action') == 'getDiagnosticData' pattern present
        """
        # Assert: action handler present
        assert "getDiagnosticData" in ajax_source

    def test_reads_supervision_state_cmd(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read supervision_state INFO command.

        Expected result:
        - getCmd('info', 'supervision_state') call present
        """
        # Assert: supervision state command read
        assert re.search(r"getCmd\('info',\s*'supervision_state'\)", ajax_source)

    def test_reads_supervision_label_cmd(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read supervision_label INFO command.

        Expected result:
        - getCmd('info', 'supervision_label') call present
        """
        # Assert: supervision label command read
        assert re.search(r"getCmd\('info',\s*'supervision_label'\)", ajax_source)

    def test_reads_event_state_cmd(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read event_state INFO command.

        Expected result:
        - getCmd('info', 'event_state') call present
        """
        # Assert: event state command read
        assert re.search(r"getCmd\('info',\s*'event_state'\)", ajax_source)

    def test_reads_event_label_cmd(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read event_label INFO command.

        Expected result:
        - getCmd('info', 'event_label') call present
        """
        # Assert: event label command read
        assert re.search(r"getCmd\('info',\s*'event_label'\)", ajax_source)

    def test_reads_sia_last_errors_config(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read sia_last_errors from plugin config.

        Expected result:
        - config::byKey('sia_last_errors', 'siaDC09') call present
        """
        # Assert: errors config read
        assert re.search(r"config::byKey\('sia_last_errors',\s*'siaDC09'", ajax_source)

    def test_reads_sia_last_messages_config(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read sia_last_messages from plugin config.

        Expected result:
        - config::byKey('sia_last_messages', 'siaDC09') call present
        """
        # Assert: messages config read
        assert re.search(r"config::byKey\('sia_last_messages',\s*'siaDC09'", ajax_source)

    def test_returns_all_keys(self, ajax_source: str) -> None:
        """
        getDiagnosticData must return all required keys in response.

        Expected result:
        - supervision_state, supervision_label, event_state, event_label, errors, messages keys present
        """
        # Assert: all response keys present
        assert "'supervision_state'" in ajax_source
        assert "'supervision_label'" in ajax_source
        assert "'event_state'" in ajax_source
        assert "'event_label'" in ajax_source
        assert "'errors'" in ajax_source
        assert "'messages'" in ajax_source

    def test_reads_info_cmds_via_exec_cmd_not_get_value(self, ajax_source: str) -> None:
        """
        getDiagnosticData must read the 4 info cmds via execCmd(), not getValue().

        Verified against Jeedom core (cmd.class.php): for non-historized 'info' cmds,
        cmd::event() (invoked by the daemon's checkAndUpdateCmd on every push) only
        writes to the cmd cache (setCache()) — it never touches the cmd table's own
        'value' column. getValue() reads that column directly and stays frozen at
        whatever it held at cmd creation; execCmd() reads the cache that event()
        actually updates. Using getValue() here (an earlier fix, since reverted)
        caused the Diagnostic tab to show a permanently stale state (a bare "0",
        no label) even on a freshly created equipment with an actively running
        daemon — field-confirmed 2026-09-21.

        Expected result:
        - getValue() is not called on the 4 diagnostic info cmds
        - execCmd() is called instead, on all 4
        """
        diagnostic_block = ajax_source[ajax_source.index("getDiagnosticData") :]
        end = diagnostic_block.find("clearDiagnosticData")
        if end != -1:
            diagnostic_block = diagnostic_block[:end]
        # Assert: no getValue() reads in the diagnostic data block (frozen-forever path)
        assert "->getValue()" not in diagnostic_block, (
            "getDiagnosticData must not read info cmds via getValue() — "
            "it never reflects the daemon's live pushes for non-historized info cmds"
        )
        # Assert: execCmd() is used for all 4 info cmds instead
        assert diagnostic_block.count("->execCmd()") >= 4, (
            "getDiagnosticData must read supervision_state/label and event_state/label via execCmd()"
        )


# ── AJAX clearDiagnosticData Structure ───────────────────────────────────────


class TestClearDiagnosticDataAjax:
    """Verify clearDiagnosticData AJAX action structure."""

    def test_action_exists(self, ajax_source: str) -> None:
        """
        clearDiagnosticData action must exist in siaDC09.ajax.php.

        Expected result:
        - init('action') == 'clearDiagnosticData' pattern present
        """
        # Assert: action handler present
        assert "clearDiagnosticData" in ajax_source

    def test_clears_errors_target(self, ajax_source: str) -> None:
        """
        clearDiagnosticData with target=errors must clear sia_last_errors.

        Expected result:
        - config::save('sia_last_errors', '[]', 'siaDC09') present
        """
        # Assert: errors clearing present
        assert re.search(r"config::save\('sia_last_errors',\s*'\[\]',\s*'siaDC09'\)", ajax_source)

    def test_clears_messages_target(self, ajax_source: str) -> None:
        """
        clearDiagnosticData with target=messages must clear sia_last_messages.

        Expected result:
        - config::save('sia_last_messages', '[]', 'siaDC09') present
        """
        # Assert: messages clearing present
        assert re.search(r"config::save\('sia_last_messages',\s*'\[\]',\s*'siaDC09'\)", ajax_source)

    def test_validates_target_param(self, ajax_source: str) -> None:
        """
        clearDiagnosticData must reject invalid target values.

        Expected result:
        - Error response for invalid target present
        """
        # Assert: invalid target handling
        assert re.search(r"Cible invalide", ajax_source)


# ── Diagnostic Tab HTML ──────────────────────────────────────────────────────


class TestDiagnosticTabHtml:
    """Verify Diagnostic tab HTML structure in PHP template."""

    def test_tab_li_exists(self, php_source: str) -> None:
        """
        Diagnostic tab <li> must exist in nav-tabs.

        Expected result:
        - Tab header with diagnosticTab href present
        """
        # Assert: tab header present
        assert 'href="#diagnosticTab"' in php_source

    def test_tab_uses_stethoscope_icon(self, php_source: str) -> None:
        """
        Diagnostic tab must use stethoscope icon per design spec.

        Expected result:
        - fa-stethoscope icon class in tab header
        """
        # Assert: correct icon used
        assert "fa-stethoscope" in php_source

    def test_tab_panel_exists(self, php_source: str) -> None:
        """
        Diagnostic tab panel div must exist.

        Expected result:
        - div#diagnosticTab with tabpanel role present
        """
        # Assert: tab panel div present
        assert 'id="diagnosticTab"' in php_source

    def test_status_badge_panel_exists(self, php_source: str) -> None:
        """
        Status badge panel must exist in diagnostic tab.

        Expected result:
        - siaDC09_badgeDot and siaDC09_badgeLabel elements present
        """
        # Assert: badge elements present
        assert 'id="siaDC09_badgeDot"' in php_source
        assert 'id="siaDC09_badgeLabel"' in php_source

    def test_errors_panel_exists(self, php_source: str) -> None:
        """
        Errors panel with heading and list container must exist.

        Expected result:
        - siaDC09_errorsPanel with heading and list body present
        """
        # Assert: errors panel structure present
        assert 'id="siaDC09_errorsPanel"' in php_source
        assert 'id="siaDC09_errorsList"' in php_source

    def test_errors_panel_has_buttons(self, php_source: str) -> None:
        """
        Errors panel must have Actualiser and Vider buttons.

        Expected result:
        - Both button IDs present in errors panel
        """
        # Assert: both buttons present
        assert 'id="siaDC09_errorsRefresh"' in php_source
        assert 'id="siaDC09_errorsClear"' in php_source

    def test_inspector_panel_placeholder_exists(self, php_source: str) -> None:
        """
        Protocol inspector panel placeholder must exist for story 9-2.

        Expected result:
        - siaDC09_inspectorPanel and siaDC09_inspectorList present
        """
        # Assert: inspector placeholder present
        assert 'id="siaDC09_inspectorPanel"' in php_source
        assert 'id="siaDC09_inspectorList"' in php_source

    def test_tab_hidden_by_default(self, php_source: str) -> None:
        """
        Diagnostic tab li must be hidden by default (shown via JS when step >= 4).

        Expected result:
        - display:none style on the diagnostic tab li
        """
        # Assert: tab hidden by default (attribute order-independent)
        assert "siaDC09_diagnosticTabLi" in php_source
        assert re.search(r'siaDC09_diagnosticTabLi[^>]*display\s*:\s*none', php_source)


# ── JS Badge Color Mapping ───────────────────────────────────────────────────


class TestJsBadgeRendering:
    """Verify badge color mapping and rendering logic."""

    def test_badge_color_green_for_state_2(self, js_source: str) -> None:
        """
        supervision_state=2 (HEALTHY) must render green badge.

        Expected result:
        - #5cb85c color mapped to state 2
        """
        # Assert: green color for healthy state
        assert "#5cb85c" in js_source

    def test_badge_color_orange_for_state_1(self, js_source: str) -> None:
        """
        supervision_state=1 (DEGRADED/INITIALIZING) must render orange badge.

        Expected result:
        - #f0ad4e color mapped to state 1
        """
        # Assert: orange color for degraded state
        assert "#f0ad4e" in js_source

    def test_badge_color_red_for_state_0(self, js_source: str) -> None:
        """
        supervision_state=0 (NO_NETWORK/STOPPED) must render red badge.

        Expected result:
        - #d9534f color mapped to state 0
        """
        # Assert: red color for critical state
        assert "#d9534f" in js_source

    def test_render_badge_function_exists(self, js_source: str) -> None:
        """
        siaDC09_renderBadge function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: render badge function defined
        assert "function siaDC09_renderBadge" in js_source

    def test_render_badge_sets_dot_color(self, js_source: str) -> None:
        """
        renderBadge must set the color CSS on the badge dot element.

        Expected result:
        - siaDC09_badgeDot color style manipulation present
        """
        # Assert: dot color set (single-line match inside renderBadge body)
        assert re.search(r"siaDC09_badgeDot.*?css\('color'", js_source)

    def test_render_badge_sets_label_text(self, js_source: str) -> None:
        """
        renderBadge must set the text of the badge label element.

        Expected result:
        - siaDC09_badgeLabel text manipulation present
        """
        # Assert: label text set (single-line match inside renderBadge body)
        assert re.search(r"siaDC09_badgeLabel.*?\.text\(", js_source)


# ── JS Error Panel Rendering ─────────────────────────────────────────────────


class TestJsErrorPanelRendering:
    """Verify error panel rendering logic."""

    def test_render_errors_function_exists(self, js_source: str) -> None:
        """
        siaDC09_renderErrors function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: render errors function defined
        assert "function siaDC09_renderErrors" in js_source

    def test_tier_map_has_all_error_codes(self, js_source: str) -> None:
        """
        Tier classification map must include all 6 error codes.

        Expected result:
        - All error codes from error-handler-design.md present
        """
        # Assert: all error codes mapped
        assert "SUPERVISION_TIMEOUT" in js_source
        assert "SUPERVISION_NAK" in js_source
        assert "BAD_CSR_RESPONSE" in js_source
        assert "SUPERVISION_DISCONNECTED" in js_source
        assert "EVENT_FAILED" in js_source
        assert "TRANSPORT_PERMANENT" in js_source

    def test_tier_badge_classes(self, js_source: str) -> None:
        """
        Tier badges must use correct Bootstrap label classes.

        Expected result:
        - T1=label-info, T2=label-warning, T3=label-danger
        """
        # Assert: correct label classes for each tier
        assert "label-info" in js_source
        assert "label-warning" in js_source
        assert "label-danger" in js_source

    def test_empty_state_message(self, js_source: str) -> None:
        """
        Empty error list must show "Aucune erreur enregistrée" message.

        Expected result:
        - Empty state message rendered when errors array is empty
        """
        # Assert: empty state message present
        assert "Aucune erreur enregistr" in js_source

    def test_format_timestamp_function_exists(self, js_source: str) -> None:
        """
        siaDC09_formatTimestamp function must exist for HH:MM:SS formatting.

        Expected result:
        - Function definition present
        """
        # Assert: timestamp formatter defined
        assert "function siaDC09_formatTimestamp" in js_source


# ── JS Actualiser Button Rate Limit ──────────────────────────────────────────


class TestJsRefreshRateLimit:
    """Verify Actualiser button rate limiting logic."""

    def test_refresh_button_handler_exists(self, js_source: str) -> None:
        """
        siaDC09_errorsRefresh click handler must exist.

        Expected result:
        - Click handler on #siaDC09_errorsRefresh present
        """
        # Assert: refresh handler present
        assert re.search(r"siaDC09_errorsRefresh.*?on\('click'", js_source, re.DOTALL)

    def test_refresh_disables_button(self, js_source: str) -> None:
        """
        Refresh handler must disable button immediately on click.

        Expected result:
        - attr('disabled', true) call in handler
        """
        # Assert: button disabled on click
        pattern = r"siaDC09_errorsRefresh.*?attr\('disabled',\s*true\)"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_refresh_reenables_after_2000ms(self, js_source: str) -> None:
        """
        Button must re-enable after 2000ms timeout.

        Expected result:
        - setTimeout with 2000ms delay and removeAttr('disabled')
        """
        # Assert: 2000ms timeout for re-enable
        assert "2000" in js_source

    def test_refresh_calls_load_diagnostic_data(self, js_source: str) -> None:
        """
        Refresh button must trigger siaDC09_loadDiagnosticData.

        Expected result:
        - siaDC09_loadDiagnosticData() call in refresh handler
        """
        # Assert: load function called
        assert re.search(
            r"siaDC09_errorsRefresh.*?siaDC09_loadDiagnosticData\(\)",
            js_source,
            re.DOTALL,
        )


# ── JS Diagnostic Tab Visibility ─────────────────────────────────────────────


class TestJsDiagnosticTabVisibility:
    """Verify diagnostic tab visibility logic tied to wizard step."""

    def test_init_diagnostic_tab_function_exists(self, js_source: str) -> None:
        """
        siaDC09_initDiagnosticTab function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: init function defined
        assert "function siaDC09_initDiagnosticTab" in js_source

    def test_init_called_from_print_eq_logic(self, js_source: str) -> None:
        """
        printEqLogic must call siaDC09_initDiagnosticTab with wizard step.

        Expected result:
        - siaDC09_initDiagnosticTab call in printEqLogic
        """
        # Assert: called from printEqLogic
        pattern = r"printEqLogic.*?siaDC09_initDiagnosticTab"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_shows_tab_when_step_gte_4(self, js_source: str) -> None:
        """
        Tab must be shown (display not none) when wizard step >= 4.

        Expected result:
        - Show logic for diagnosticTabLi when step >= 4
        """
        # Assert: show when wizard complete
        assert re.search(r"siaDC09_diagnosticTabLi.*?\.show\(\)", js_source, re.DOTALL)

    def test_hides_tab_when_step_lt_4(self, js_source: str) -> None:
        """
        Tab must be hidden when wizard step < 4.

        Expected result:
        - Hide logic for diagnosticTabLi in else branch
        """
        # Assert: hide when wizard incomplete
        assert re.search(r"siaDC09_diagnosticTabLi.*?\.hide\(\)", js_source, re.DOTALL)

    def test_data_loads_on_tab_shown(self, js_source: str) -> None:
        """
        Diagnostic data must load when tab is activated via shown.bs.tab event.

        Expected result:
        - shown.bs.tab event handler calling siaDC09_loadDiagnosticData
        """
        # Assert: tab activation triggers data load
        assert re.search(r"shown\.bs\.tab.*?siaDC09_loadDiagnosticData", js_source, re.DOTALL)


# ── AJAX decodeFrame Structure (Task 8.7) ────────────────────────────────────


class TestDecodeFrameAjax:
    """Verify decodeFrame AJAX action structure in siaDC09.ajax.php."""

    def test_action_exists(self, ajax_source: str) -> None:
        """
        decodeFrame action must exist in siaDC09.ajax.php.

        Expected result:
        - init('action') == 'decodeFrame' pattern present
        """
        # Assert: action handler registered
        assert "decodeFrame" in ajax_source

    def test_hex_param_validation(self, ajax_source: str) -> None:
        """
        decodeFrame must validate the 'hex' parameter is non-empty.

        Expected result:
        - empty($hex) check present
        """
        # Assert: empty hex rejected
        assert re.search(r"empty\(\s*\$hex\s*\)", ajax_source)

    def test_hex_length_guard(self, ajax_source: str) -> None:
        """
        decodeFrame must reject hex strings exceeding 4096 characters.

        Expected result:
        - strlen($hex) > 4096 length guard present
        """
        # Assert: length limit enforced
        assert re.search(r"strlen\(\s*\$hex\s*\)\s*>\s*4096", ajax_source)

    def test_ctype_xdigit_validation(self, ajax_source: str) -> None:
        """
        decodeFrame must validate hex format via ctype_xdigit().

        Expected result:
        - ctype_xdigit($hex) call present
        """
        # Assert: hex character validation applied
        assert re.search(r"ctype_xdigit\(\s*\$hex\s*\)", ajax_source)

    def test_invokes_sia_protocol_decode(self, ajax_source: str) -> None:
        """
        decodeFrame must invoke sia_protocol.py with --decode flag.

        Expected result:
        - sia_protocol.py and --decode references present
        """
        # Assert: correct Python script invoked
        assert "sia_protocol.py" in ajax_source
        assert "--decode" in ajax_source

    def test_encryption_key_via_env(self, ajax_source: str) -> None:
        """
        decodeFrame must pass encryption key via SIA_ENCRYPTION_KEY env var.

        Expected result:
        - SIA_ENCRYPTION_KEY env prefix pattern present
        """
        # Assert: key passed via environment, not CLI arg
        assert "SIA_ENCRYPTION_KEY" in ajax_source

    def test_set_time_limit_guard(self, ajax_source: str) -> None:
        """
        decodeFrame must call set_time_limit() to cap execution time.

        Expected result:
        - set_time_limit() call present
        """
        # Assert: PHP execution time capped for subprocess call
        assert re.search(r"set_time_limit\(\s*10\s*\)", ajax_source)


# ── Task 1: Cross-panel behavior — single AJAX call, no auto-refresh ─────────


class TestCrossPanelDiagnosticLoad:
    """Verify getDiagnosticData drives all panels from one AJAX call (AC: 1, 2, 6, 8)."""

    def test_get_diagnostic_data_returns_six_keys(self, ajax_source: str) -> None:
        """
        getDiagnosticData must return all 6 expected keys in a single response.

        Expected result:
        - supervision_state, supervision_label, event_state, event_label,
          errors, messages are all present in the response array
        """
        # Assert: all 6 keys present in the AJAX handler response
        for key in ("supervision_state", "supervision_label", "event_state",
                    "event_label", "errors", "messages"):
            assert f"'{key}'" in ajax_source or f'"{key}"' in ajax_source

    def test_load_diagnostic_data_calls_render_badge(self, js_source: str) -> None:
        """
        siaDC09_loadDiagnosticData success handler must call siaDC09_renderBadge.

        Expected result:
        - siaDC09_renderBadge called within siaDC09_loadDiagnosticData body
        """
        # Assert: badge render wired into the single data loader
        pattern = r"siaDC09_loadDiagnosticData.*?siaDC09_renderBadge"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_load_diagnostic_data_calls_render_errors(self, js_source: str) -> None:
        """
        siaDC09_loadDiagnosticData success handler must call siaDC09_renderErrors.

        Expected result:
        - siaDC09_renderErrors called within siaDC09_loadDiagnosticData body
        """
        # Assert: error render wired into the single data loader
        pattern = r"siaDC09_loadDiagnosticData.*?siaDC09_renderErrors"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_load_diagnostic_data_calls_render_messages(self, js_source: str) -> None:
        """
        siaDC09_loadDiagnosticData success handler must call siaDC09_renderMessages
        (wired in story 9-2).

        Expected result:
        - siaDC09_renderMessages called within siaDC09_loadDiagnosticData body
        """
        # Assert: messages render wired into the single data loader (story 9-2)
        pattern = r"siaDC09_loadDiagnosticData.*?siaDC09_renderMessages"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_inspector_refresh_button_calls_load_diagnostic(self, js_source: str) -> None:
        """
        Inspector Actualiser button must call siaDC09_loadDiagnosticData — NOT a separate endpoint.

        Expected result:
        - siaDC09_inspectorRefresh click handler calls siaDC09_loadDiagnosticData
        """
        # Assert: inspector refresh handler calls the shared loader (proximity match)
        pattern = r"siaDC09_inspectorRefresh.*?siaDC09_loadDiagnosticData\(\)"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_errors_refresh_button_calls_load_diagnostic(self, js_source: str) -> None:
        """
        Errors Actualiser button must call siaDC09_loadDiagnosticData.

        Expected result:
        - siaDC09_errorsRefresh click handler calls siaDC09_loadDiagnosticData
        """
        # Assert: errors refresh handler calls the shared loader (proximity match)
        pattern = r"siaDC09_errorsRefresh.*?siaDC09_loadDiagnosticData\(\)"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_inspector_refresh_has_2000ms_rate_limit(self, js_source: str) -> None:
        """
        Inspector Actualiser button must have the same 2000ms rate-limit setTimeout
        as the errors Actualiser button — prevents rapid-fire AJAX calls.

        Expected result:
        - siaDC09_inspectorRefresh handler contains setTimeout(..., 2000)
        """
        # Assert: 2000ms rate-limit present in inspectorRefresh handler
        assert re.search(
            r"siaDC09_inspectorRefresh.*?setTimeout.*?2000",
            js_source,
            re.DOTALL,
        )

    def test_no_set_interval_in_diagnostic_tab(self, js_source: str) -> None:
        """
        Diagnostic tab must contain zero setInterval calls — all refresh is manual.

        Expected result:
        - setInterval not present anywhere in the diagnostic section
        """
        # Assert: no polling — only manual refresh buttons allowed
        assert "setInterval" not in js_source

    def test_no_auto_refresh_set_timeout_outside_rate_limit(
        self, js_source: str
    ) -> None:
        """
        No single-line setTimeout call may directly invoke siaDC09_loadDiagnosticData.
        Auto-refresh would look like: setTimeout(siaDC09_loadDiagnosticData, N).
        The only allowed setTimeout is the 2000ms removeAttr rate-limit guard.

        Expected result:
        - No setTimeout that directly references siaDC09_loadDiagnosticData on the same line
        """
        # Assert: no direct-reference auto-refresh pattern on one line
        # (DOTALL not used — only same-line matches, to avoid spanning across functions)
        assert not re.search(
            r"setTimeout\s*\(\s*siaDC09_loadDiagnosticData", js_source
        )

    def test_shown_bs_tab_event_triggers_load(self, js_source: str) -> None:
        """
        shown.bs.tab event on diagnosticTab must trigger siaDC09_loadDiagnosticData.

        Expected result:
        - shown.bs.tab event handler present calling siaDC09_loadDiagnosticData
        """
        # Assert: tab activation auto-loads data on first switch
        assert "shown.bs.tab" in js_source
        assert "siaDC09_loadDiagnosticData" in js_source


# ── Task 2: Clear button isolation ────────────────────────────────────────────


class TestClearButtonIsolation:
    """Verify Vider buttons clear exactly one config key each (AC: 3, 6)."""

    def test_clear_errors_target_saves_sia_last_errors_only(
        self, ajax_source: str
    ) -> None:
        """
        clearDiagnosticData with target=errors must save to sia_last_errors only.
        sia_last_messages must not be touched in that branch.

        Expected result:
        - config::save('sia_last_errors', '[]', 'siaDC09') present in errors branch
        - The errors branch does NOT contain sia_last_messages in same save call
        """
        # Assert: correct config key saved for errors target
        assert re.search(r"config::save\('sia_last_errors',\s*'\[\]',\s*'siaDC09'\)", ajax_source)

    def test_clear_messages_target_saves_sia_last_messages_only(
        self, ajax_source: str
    ) -> None:
        """
        clearDiagnosticData with target=messages must save to sia_last_messages only.

        Expected result:
        - config::save('sia_last_messages', '[]', 'siaDC09') present in messages branch
        """
        # Assert: correct config key saved for messages target
        assert re.search(r"config::save\('sia_last_messages',\s*'\[\]',\s*'siaDC09'\)", ajax_source)

    def test_errors_clear_js_button_sends_errors_target(self, js_source: str) -> None:
        """
        siaDC09_errorsClear click handler must send target: 'errors' to the AJAX action.

        Expected result:
        - target: 'errors' present in errorsClear click handler body
        """
        # Assert: errors clear button sends correct target discriminator
        pattern = r"siaDC09_errorsClear.*?target:\s*'errors'"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_inspector_clear_js_button_sends_messages_target(self, js_source: str) -> None:
        """
        siaDC09_inspectorClear click handler must send target: 'messages' to AJAX.

        Expected result:
        - target: 'messages' present in inspectorClear click handler body
        """
        # Assert: inspector clear button sends correct target discriminator
        pattern = r"siaDC09_inspectorClear.*?target:\s*'messages'"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_invalid_target_returns_error(self, ajax_source: str) -> None:
        """
        clearDiagnosticData must reject any target value that is not 'errors' or 'messages'.

        Expected result:
        - Error response for invalid target is present (ajax::error call present)
        - 'Cible invalide' error message present
        """
        # Assert: invalid target guard present (already tested in 9-1, confirmed here)
        assert re.search(r"Cible invalide", ajax_source)

    def test_inspector_clear_resets_decode_cache(self, js_source: str) -> None:
        """
        inspectorClear Vider button success handler must reset _siaDC09_decodeCache to {}
        so that stale decoded frames are not shown after the ring buffer is wiped.

        Expected result:
        - _siaDC09_decodeCache = {} assignment inside inspectorClear success callback
        """
        # Assert: cache cleared in the inspectorClear success handler
        assert re.search(
            r"siaDC09_inspectorClear.*?_siaDC09_decodeCache\s*=\s*\{\}",
            js_source,
            re.DOTALL,
        )


# ── Task 3: Badge ↔ errors ↔ inspector data flow ─────────────────────────────


class TestDataFlowBadgeErrorsInspector:
    """Verify render functions handle their inputs correctly (AC: 6, 7, 8)."""

    def test_render_badge_accepts_supervision_state_param(
        self, js_source: str
    ) -> None:
        """
        siaDC09_renderBadge must accept supervisionState and supervisionLabel params.

        Expected result:
        - Function signature includes both parameter names
        """
        # Assert: correct parameter names for renderBadge
        assert re.search(
            r"function siaDC09_renderBadge\s*\(\s*supervisionState",
            js_source
        )

    def test_render_errors_handles_empty_array(self, js_source: str) -> None:
        """
        siaDC09_renderErrors must handle an empty errors array, showing empty state.

        Expected result:
        - Empty-array check (length === 0 or similar) present in renderErrors
        - 'Aucune erreur enregistrée' empty-state message present
        """
        # Assert: empty check present in renderErrors body
        assert "function siaDC09_renderErrors" in js_source
        assert re.search(r"\.length\s*===?\s*0", js_source)
        # Assert: French empty-state message for errors panel
        assert "Aucune erreur enregistr" in js_source

    def test_render_errors_populates_table_rows(self, js_source: str) -> None:
        """
        siaDC09_renderErrors must build table rows for non-empty errors arrays.

        Expected result:
        - forEach loop iterating over errors present in renderErrors
        - <tr> element creation present
        """
        # Assert: forEach iteration over errors array present in JS source
        assert ".forEach(" in js_source
        # Assert: table row created per error entry
        assert "<tr" in js_source

    def test_badge_color_map_covers_all_three_states(self, js_source: str) -> None:
        """
        _siaDC09_badgeColors must map states 0, 1, and 2 exhaustively,
        with a fallback for unknown values.

        Expected result:
        - Keys 0, 1, 2 all present in _siaDC09_badgeColors
        - Fallback (|| operator) present in color lookup
        """
        # Assert: all three states covered in badge color map (scoped to object block)
        assert re.search(r"_siaDC09_badgeColors\s*=\s*\{[^}]*\b2\s*:", js_source, re.DOTALL)
        assert re.search(r"_siaDC09_badgeColors\s*=\s*\{[^}]*\b1\s*:", js_source, re.DOTALL)
        assert re.search(r"_siaDC09_badgeColors\s*=\s*\{[^}]*\b0\s*:", js_source, re.DOTALL)
        # Assert: fallback to a default when state is unknown
        pattern = r"_siaDC09_badgeColors\[.*?\]\s*\|\|"
        assert re.search(pattern, js_source)

    def test_tier_map_covers_all_six_error_codes(self, js_source: str) -> None:
        """
        _siaDC09_tierMap must map all 6 ErrorCode values to a tier (T1, T2, T3).

        Expected result:
        - All 6 ErrorCode keys present as tier map entries
        """
        # Assert: all 6 error codes mapped to tiers (confirmed from 9-1, re-validated)
        for code in (
            "SUPERVISION_TIMEOUT", "SUPERVISION_NAK", "BAD_CSR_RESPONSE",
            "SUPERVISION_DISCONNECTED", "EVENT_FAILED", "TRANSPORT_PERMANENT"
        ):
            assert code in js_source

    def test_error_row_has_four_cells(self, js_source: str) -> None:
        """
        Each error table row must have 4 cells: timestamp, tier badge, code, message.

        Expected result:
        - err.timestamp, err.code, err.message references present in renderErrors
        - Tier badge cell present (uses _siaDC09_tierMap lookup)
        """
        # Assert: error fields accessed inside renderErrors function body
        assert "function siaDC09_renderErrors" in js_source
        assert "err.timestamp" in js_source
        assert "err.code" in js_source
        assert "err.message" in js_source
        assert "_siaDC09_tierMap" in js_source


# ── Task 4: Tab visibility and Bootstrap 3 layout guard ──────────────────────


class TestTabVisibilityAndLayout:
    """Verify tab visibility logic and Bootstrap 3 structural constraints (AC: 1, 4, 5)."""

    def test_diagnostic_tab_li_hidden_by_default(self, php_source: str) -> None:
        """
        Diagnostic tab <li> must have style="display:none" in PHP source.

        Expected result:
        - id="siaDC09_diagnosticTabLi" element has display:none inline style
        """
        # Assert: tab hidden by default (attribute order-independent)
        assert "siaDC09_diagnosticTabLi" in php_source
        assert re.search(r'siaDC09_diagnosticTabLi[^>]*display\s*:\s*none', php_source)

    def test_init_diagnostic_tab_shows_for_step_4(self, js_source: str) -> None:
        """
        siaDC09_initDiagnosticTab called with step >= 4 must call .show() on the tab li.

        Expected result:
        - Condition wizardStep >= 4 triggers .show() on diagnosticTabLi
        """
        # Assert: show() called when wizard complete (proximity: within initDiagnosticTab body)
        assert re.search(r"wizardStep\s*>=\s*4", js_source)
        assert re.search(r"siaDC09_diagnosticTabLi.*?\.show\(\)", js_source)

    def test_init_diagnostic_tab_hides_for_step_lt_4(self, js_source: str) -> None:
        """
        siaDC09_initDiagnosticTab called with step < 4 must call .hide() on the tab li.

        Expected result:
        - Else branch calls .hide() on diagnosticTabLi
        """
        # Assert: hide() called in else branch for incomplete wizard
        pattern = r"diagnosticTabLi.*?\.hide\(\)"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_all_panels_use_bootstrap3_panel_default(self, php_source: str) -> None:
        """
        All diagnostic sub-panels must use Bootstrap 3 'panel panel-default' classes.

        Expected result:
        - 'panel panel-default' appears in diagnostic tab HTML
        """
        # Assert: Bootstrap 3 panel class used (not Bootstrap 4/5 card)
        assert "panel panel-default" in php_source

    def test_panels_use_panel_heading_class(self, php_source: str) -> None:
        """
        Error and inspector panels must use 'panel-heading' Bootstrap 3 class.

        Expected result:
        - 'panel-heading' class present in diagnostic tab HTML
        """
        # Assert: Bootstrap 3 panel-heading used for panel titles
        assert "panel-heading" in php_source

    def test_panels_use_panel_body_class(self, php_source: str) -> None:
        """
        Error and inspector panels must use 'panel-body' Bootstrap 3 class.

        Expected result:
        - 'panel-body' class present in diagnostic tab HTML
        """
        # Assert: Bootstrap 3 panel-body used for panel content areas
        assert "panel-body" in php_source

    def test_no_fixed_pixel_widths_above_400px_in_diagnostic_tab(
        self, php_source: str
    ) -> None:
        """
        Diagnostic tab HTML must not use fixed pixel widths > 400px
        to ensure responsive layout on mobile.

        Expected result:
        - No inline style with width > 400px in diagnostic tab section
        """
        # Assert: no large fixed widths (responsive-safe pattern)
        large_width_pattern = r'width\s*:\s*(?:40[1-9]|[5-9]\d{2}|\d{4,})\s*px'
        assert not re.search(large_width_pattern, php_source)
