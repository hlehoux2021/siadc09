"""
Level 1 tests for Protocol Inspector JS logic (Story 9-2 Tasks 4–7).

Validates siaDC09.js source text for CSS classes, data attributes, French
labels and clipboard button presence — no browser required.

Reference: internal-docs/design/debug-ui-design.md § 5c.3
Reference: _bmad-output/implementation-artifacts/9-2-protocol-inspector-hex-viewer-decryption.md
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


# ── Task 8.8: message row CSS classes and data attributes ────────────────────


class TestMessageRowRendering:
    """Verify siaDC09_renderMessages builds rows with correct CSS and data attributes."""

    def test_render_messages_function_exists(self, js_source: str) -> None:
        """
        siaDC09_renderMessages function must exist.

        Expected result:
        - Function definition present in source
        """
        # Assert: render function defined
        assert "function siaDC09_renderMessages" in js_source

    def test_render_messages_called_from_load_diagnostic(self, js_source: str) -> None:
        """
        siaDC09_loadDiagnosticData success handler must call siaDC09_renderMessages.

        Expected result:
        - siaDC09_renderMessages call present inside loadDiagnosticData
        """
        # Assert: render wired into the diagnostic data loader
        pattern = r"siaDC09_loadDiagnosticData.*?siaDC09_renderMessages"
        assert re.search(pattern, js_source, re.DOTALL)

    def test_row_class_sia_msg_row(self, js_source: str) -> None:
        """
        Each message row must use the CSS class 'sia-msg-row'.

        Expected result:
        - 'sia-msg-row' class assigned to row div
        """
        # Assert: canonical row class present for event delegation
        assert "sia-msg-row" in js_source

    def test_row_data_request_hex_attribute(self, js_source: str) -> None:
        """
        Message row must set data-request-hex attribute for AJAX decode.

        Expected result:
        - data-request-hex attribute assignment present
        """
        # Assert: request hex stored on DOM element for later retrieval
        assert "data-request-hex" in js_source

    def test_row_data_response_hex_attribute(self, js_source: str) -> None:
        """
        Message row must set data-response-hex attribute.

        Expected result:
        - data-response-hex attribute assignment present
        """
        # Assert: response hex stored on DOM element
        assert "data-response-hex" in js_source

    def test_status_badge_label_success(self, js_source: str) -> None:
        """
        Successful/routine messages must use label-success Bootstrap class.

        Expected result:
        - 'label-success' class assigned as default badge
        """
        # Assert: green badge class used for routine/successful frames
        assert "label-success" in js_source

    def test_status_badge_label_warning(self, js_source: str) -> None:
        """
        Warning-level messages must use label-warning Bootstrap class.

        Expected result:
        - 'label-warning' class present in badge logic
        """
        # Assert: orange badge class used for partial failures
        assert "label-warning" in js_source

    def test_status_badge_label_danger(self, js_source: str) -> None:
        """
        Alarm messages with multiple failed attempts must use label-danger class.

        Expected result:
        - 'label-danger' class present in badge logic
        """
        # Assert: red badge class used for multi-attempt alarms
        assert "label-danger" in js_source

    def test_empty_state_message(self, js_source: str) -> None:
        """
        Empty message list must display a French empty-state message.

        Expected result:
        - 'Aucun échange SIA enregistré' text in source
        """
        # Assert: French empty-state message present
        assert "Aucun" in js_source and "SIA" in js_source

    def test_elapsed_ms_displayed_in_badge(self, js_source: str) -> None:
        """
        Status badge must include elapsed_ms value.

        Expected result:
        - elapsed_ms referenced in badge text construction
        """
        # Assert: timing information surfaced to user
        assert "elapsed_ms" in js_source

    def test_decode_cache_variable_exists(self, js_source: str) -> None:
        """
        Module-level decode result cache _siaDC09_decodeCache must exist.

        Expected result:
        - var _siaDC09_decodeCache declaration present
        """
        # Assert: cache variable prevents redundant AJAX calls
        assert "_siaDC09_decodeCache" in js_source


# ── Task 8.9: French labels in field table ───────────────────────────────────


class TestFieldTableFrenchLabels:
    """Verify siaDC09_buildFieldTable uses French column headers and labels."""

    def test_build_field_table_function_exists(self, js_source: str) -> None:
        """
        siaDC09_buildFieldTable function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: field table builder defined
        assert "function siaDC09_buildFieldTable" in js_source

    def test_champ_column_header(self, js_source: str) -> None:
        """
        Field table must have French column header 'Champ'.

        Expected result:
        - 'Champ' text used as first column header
        """
        # Assert: French label for field name column
        assert "'Champ'" in js_source or '"Champ"' in js_source

    def test_valeur_column_header(self, js_source: str) -> None:
        """
        Field table must have French column header 'Valeur'.

        Expected result:
        - 'Valeur' text used as second column header
        """
        # Assert: French label for field value column
        assert "'Valeur'" in js_source or '"Valeur"' in js_source

    def test_id_token_row_label(self, js_source: str) -> None:
        """
        Field table must include 'ID Token' row.

        Expected result:
        - 'ID Token' label present in table row definitions
        """
        # Assert: id_token field surfaced with French-compatible label
        assert "ID Token" in js_source

    def test_sequence_row_label(self, js_source: str) -> None:
        """
        Field table must include 'Séquence' row.

        Expected result:
        - 'Séquence' label present in table row definitions
        """
        # Assert: sequence number row in French
        assert "Séquence" in js_source

    def test_compte_row_label(self, js_source: str) -> None:
        """
        Field table must include 'Compte' row for account number.

        Expected result:
        - 'Compte' label present
        """
        # Assert: account number row in French
        assert "Compte" in js_source

    def test_crc_row_present(self, js_source: str) -> None:
        """
        Field table must include CRC validity row.

        Expected result:
        - 'CRC' row label present
        """
        # Assert: CRC validation result surfaced in table
        assert "'CRC'" in js_source or '"CRC"' in js_source

    def test_crc_valid_green_checkmark(self, js_source: str) -> None:
        """
        Valid CRC must render green checkmark (✓ CRC valide).

        Expected result:
        - 'CRC valide' text with green color (#5cb85c) present
        """
        # Assert: positive CRC feedback in French
        assert "CRC valide" in js_source

    def test_crc_invalid_red_cross(self, js_source: str) -> None:
        """
        Invalid CRC must render red cross (✗ CRC invalide).

        Expected result:
        - 'CRC invalide' text with red color (#d9534f) present
        """
        # Assert: negative CRC feedback in French
        assert "CRC invalide" in js_source

    def test_encryption_aes_label(self, js_source: str) -> None:
        """
        Encrypted frames must show AES-128-CBC indicator label.

        Expected result:
        - 'AES-128-CBC' text present in field table builder
        """
        # Assert: encryption algorithm identified for user
        assert "AES-128-CBC" in js_source

    def test_table_condensed_class(self, js_source: str) -> None:
        """
        Field table must use Bootstrap 3 table-condensed class.

        Expected result:
        - 'table-condensed' class present in table creation
        """
        # Assert: compact Bootstrap table style applied
        assert "table-condensed" in js_source

    def test_table_bordered_class(self, js_source: str) -> None:
        """
        Field table must use Bootstrap 3 table-bordered class.

        Expected result:
        - 'table-bordered' class present in table creation
        """
        # Assert: bordered Bootstrap table style applied
        assert "table-bordered" in js_source


# ── Task 8.10: clipboard copy button in expanded view ────────────────────────


class TestClipboardCopyButton:
    """Verify clipboard copy button is present and wired up in expanded view."""

    def test_build_hex_buttons_function_exists(self, js_source: str) -> None:
        """
        siaDC09_buildHexButtons function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: hex button builder defined
        assert "function siaDC09_buildHexButtons" in js_source

    def test_sia_copy_hex_class_on_buttons(self, js_source: str) -> None:
        """
        Hex copy buttons must use CSS class 'sia-copy-hex' for event delegation.

        Expected result:
        - 'sia-copy-hex' class assigned to copy buttons
        """
        # Assert: canonical class for click delegation
        assert "sia-copy-hex" in js_source

    def test_copy_sent_frame_button_text(self, js_source: str) -> None:
        """
        'Copier hex (envoyé)' button must exist for sent frame.

        Expected result:
        - French button text for sent-frame copy present
        """
        # Assert: French label for sent frame copy action
        assert "Copier hex (envoy" in js_source

    def test_copy_received_frame_button_text(self, js_source: str) -> None:
        """
        'Copier hex (reçu)' button must exist for received frame.

        Expected result:
        - French button text for received-frame copy present
        """
        # Assert: French label for received frame copy action
        assert "Copier hex (re" in js_source

    def test_data_hex_attribute_on_button(self, js_source: str) -> None:
        """
        Copy buttons must store hex value in data-hex attribute.

        Expected result:
        - .attr('data-hex', ...) call present in buildHexButtons
        """
        # Assert: hex value stored on button element for handler retrieval
        assert "data-hex" in js_source

    def test_clipboard_write_text_api_used(self, js_source: str) -> None:
        """
        Click handler must use navigator.clipboard.writeText for modern browsers.

        Expected result:
        - navigator.clipboard.writeText call present
        """
        # Assert: modern Clipboard API used as primary method
        assert "navigator.clipboard" in js_source
        assert "writeText" in js_source

    def test_exec_command_copy_fallback(self, js_source: str) -> None:
        """
        Click handler must fall back to document.execCommand('copy') for older browsers.

        Expected result:
        - document.execCommand('copy') call present in fallback function
        """
        # Assert: legacy fallback present for Safari/older browsers
        assert "execCommand('copy')" in js_source

    def test_copied_feedback_text(self, js_source: str) -> None:
        """
        Copy button must show 'Copié !' feedback text after successful copy.

        Expected result:
        - 'Copié' text used as temporary button label
        """
        # Assert: French success feedback after clipboard write
        assert "Copié" in js_source

    def test_feedback_timeout_1500ms(self, js_source: str) -> None:
        """
        Copied feedback must revert after 1500ms timeout.

        Expected result:
        - setTimeout with 1500 delay present in copy handler
        """
        # Assert: feedback duration matches design spec (1.5s)
        assert "1500" in js_source

    def test_copy_handler_on_sia_copy_hex(self, js_source: str) -> None:
        """
        Click event handler must be bound to '.sia-copy-hex' class via event delegation.

        Expected result:
        - $(document).on('click', '.sia-copy-hex', ...) or equivalent present
        """
        # Assert: delegated event binding for dynamically created buttons
        assert re.search(r"on\('click',\s*'\.sia-copy-hex'", js_source)

    def test_render_frame_detail_function_exists(self, js_source: str) -> None:
        """
        siaDC09_renderFrameDetail function must exist.

        Expected result:
        - Function definition present
        """
        # Assert: frame detail renderer defined
        assert "function siaDC09_renderFrameDetail" in js_source

    def test_tentative_label_for_multi_attempt(self, js_source: str) -> None:
        """
        Multi-attempt alarm detail must display 'Tentative X/Y' sub-block headers.

        Expected result:
        - 'Tentative' text in renderFrameDetail for multi-attempt alarms
        """
        # Assert: French attempt counter label for multi-retry alarm events
        assert "Tentative" in js_source

    def test_decode_ajax_action_used_in_inspector(self, js_source: str) -> None:
        """
        Inspector click handler must call decodeFrame AJAX action.

        Expected result:
        - action: 'decodeFrame' present in AJAX call inside click handler
        """
        # Assert: inspector uses the decodeFrame backend action
        assert re.search(r"action:\s*'decodeFrame'", js_source)
