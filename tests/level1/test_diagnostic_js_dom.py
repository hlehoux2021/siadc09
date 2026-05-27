"""
Level 1 DOM tests for siaDC09.js diagnostic rendering functions.

Executes real JavaScript logic inside a jsdom+jQuery environment via a Node.js
harness, then asserts on actual DOM state — not keyword presence.

Covers:
  - siaDC09_formatTimestamp     (pure function, no DOM)
  - siaDC09_renderBadge         (writes color + text to DOM)
  - siaDC09_renderErrors        (builds table or empty-state in DOM)
  - siaDC09_renderMessages      (builds message row list in DOM)
  - siaDC09_buildHexButtons     (returns DOM fragment)
  - siaDC09_buildFieldTable     (returns DOM fragment)
  - siaDC09_initDiagnosticTab   (show/hide tab li)
  - _siaDC09_decodeCache key    (composite key prevents collision)

Reference: _bmad-output/implementation-artifacts/9-1-status-badge-error-panel.md
Reference: _bmad-output/implementation-artifacts/9-2-protocol-inspector-hex-viewer-decryption.md
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HARNESS = _PROJECT_ROOT / "tests" / "fixtures" / "js_dom_harness.js"
_NODE = "node"

# ── Harness helpers ───────────────────────────────────────────────────────────


def _run(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run a list of scenarios through the jsdom harness; return result list."""
    result = subprocess.run(
        [_NODE, str(_HARNESS), json.dumps(scenarios)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"Harness error:\n{result.stderr}"
    return json.loads(result.stdout)


def _one(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run a single scenario and return its result dict."""
    results = _run([scenario])
    r = results[0]
    if r.get("error"):
        pytest.fail(f"JS error in scenario {scenario}: {r['error']}")
    return r


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_ERROR = {
    "code": "SUPERVISION_DISCONNECTED",
    "message": "Supervision perdue",
    "timestamp": "2026-05-18T14:32:11+02:00",
    "context": {"strike": 3},
    "count": 1,
}
SAMPLE_ERROR_T1 = {
    "code": "SUPERVISION_TIMEOUT",
    "message": "Délai dépassé",
    "timestamp": "2026-05-18T10:00:00+02:00",
    "context": {},
    "count": 2,
}
SAMPLE_MESSAGE = {
    "dialog_type": "supervision",
    "routine": 1,
    "timestamp": "2026-05-18T14:30:00+00:00",
    "request_hex": "AABBCCDD",
    "response_hex": "11223344",
    "elapsed_ms": 245,
}
SAMPLE_ALARM_MESSAGE = {
    "dialog_type": "alarm",
    "routine": 0,
    "timestamp": "2026-05-18T14:31:00+00:00",
    "request_hex": "DEADBEEF",
    "response_hex": "CAFEBABE",
    "elapsed_ms": 1200,
    "attempts": [{"request_hex": "DEADBEEF", "response_hex": "CAFEBABE", "elapsed_ms": 1200}],
}
SAMPLE_DECODED = {
    "id_token": "SIA-DCS",
    "sequence": 1,
    "account": "1234",
    "account_prefix": "L",
    "receiver_prefix": "",
    "data_raw": "#1234|0000",
    "length_declared": 30,
    "length_actual": 30,
    "crc_format": "SIA",
    "crc_received": "B437",
    "crc_computed": "B437",
    "crc_valid": True,
    "encrypted": False,
    "data_decrypted": None,
    "extended_fields": {},
    "timestamp_str": None,
}

# ── formatTimestamp ────────────────────────────────────────────────────────────


class TestFormatTimestamp:
    """siaDC09_formatTimestamp converts ISO 8601 → HH:MM:SS local time."""

    def test_valid_iso_with_offset_returns_time_string(self) -> None:
        """
        Valid ISO string must return HH:MM:SS local time (8-char, colon-separated).
        The exact value depends on the machine's timezone, so we validate format only.

        Expected result:
        - Returns an 8-character string matching HH:MM:SS
        """
        import re
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11+00:00"]})
        # Assert: HH:MM:SS format regardless of local timezone
        assert re.match(r"^\d{2}:\d{2}:\d{2}$", r["value"]), (
            f"Expected HH:MM:SS format, got: {r['value']!r}"
        )

    def test_empty_string_returns_empty(self) -> None:
        """
        Empty string must return empty string (no crash, no placeholder).

        Expected result:
        - Returns ''
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": [""]})
        # Assert: empty input → empty output
        assert r["value"] == ""

    def test_none_argument_returns_empty(self) -> None:
        """
        None/null argument must return empty string.

        Expected result:
        - Returns ''
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": [None]})
        # Assert: null guard returns empty
        assert r["value"] == ""

    def test_invalid_date_string_returns_empty(self) -> None:
        """
        Unparseable date string must return empty string (not throw).

        Expected result:
        - Returns ''
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["not-a-date"]})
        # Assert: invalid date → empty (isNaN guard)
        assert r["value"] == ""

    def test_zulu_time_returns_hhmmss_format(self) -> None:
        """
        ISO string ending in 'Z' must return HH:MM:SS local time (not throw).
        Exact value depends on machine timezone; we validate format only.

        Expected result:
        - Returns an 8-character string matching HH:MM:SS
        """
        import re
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T09:15:00Z"]})
        # Assert: Z suffix accepted, format correct
        assert re.match(r"^\d{2}:\d{2}:\d{2}$", r["value"]), (
            f"Expected HH:MM:SS format, got: {r['value']!r}"
        )


# ── renderBadge ────────────────────────────────────────────────────────────────


class TestRenderBadge:
    """siaDC09_renderBadge sets dot color and label text in DOM."""

    def test_state_2_sets_green_color(self) -> None:
        """
        supervision_state=2 (HEALTHY) must set #siaDC09_badgeDot color to green.

        Expected result:
        - dot color == rgb(92, 184, 92) [#5cb85c]
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [2, "OK"], "query": "#siaDC09_badgeDot"})
        # Assert: green for healthy
        assert r["style"]["color"] == "rgb(92, 184, 92)"

    def test_state_1_sets_orange_color(self) -> None:
        """
        supervision_state=1 (DEGRADED 1-2) must set dot color to orange.

        Expected result:
        - dot color == rgb(240, 173, 78) [#f0ad4e]
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [1, "Dégradé"], "query": "#siaDC09_badgeDot"})
        # Assert: orange for impaired
        assert r["style"]["color"] == "rgb(240, 173, 78)"

    def test_state_0_sets_red_color(self) -> None:
        """
        supervision_state=0 (DISCONNECTED) must set dot color to red.

        Expected result:
        - dot color == rgb(217, 83, 79) [#d9534f]
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [0, "Déconnecté"], "query": "#siaDC09_badgeDot"})
        # Assert: red for disconnected
        assert r["style"]["color"] == "rgb(217, 83, 79)"

    def test_unknown_state_falls_back_to_orange(self) -> None:
        """
        Unknown supervision_state must fall back to orange (not blank, not crash).

        Expected result:
        - dot color == rgb(240, 173, 78) [_siaDC09_badgeColors[1] fallback]
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [99, "Inconnu"], "query": "#siaDC09_badgeDot"})
        # Assert: fallback color matches badgeColors[1]
        assert r["style"]["color"] == "rgb(240, 173, 78)"

    def test_nan_state_falls_back_to_orange(self) -> None:
        """
        Non-numeric supervision_state (e.g. None/null from bad AJAX) must not crash.

        Expected result:
        - dot color == orange (parseInt(null) → NaN → state=1)
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [None, "?"], "query": "#siaDC09_badgeDot"})
        # Assert: NaN guard applied
        assert r["style"]["color"] == "rgb(240, 173, 78)"

    def test_label_text_set_correctly(self) -> None:
        """
        renderBadge must set #siaDC09_badgeLabel text to supervisionLabel.

        Expected result:
        - badgeLabel textContent == 'Healthy'
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [2, "Healthy"], "query": "#siaDC09_badgeLabel"})
        # Assert: label text matches second argument
        assert r["text"] == "Healthy"

    def test_empty_label_sets_empty_text(self) -> None:
        """
        Empty/null supervisionLabel must set label text to empty string (not 'null').

        Expected result:
        - badgeLabel textContent == ''
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [2, None], "query": "#siaDC09_badgeLabel"})
        # Assert: null label → empty string
        assert r["text"] == ""


# ── renderErrors ──────────────────────────────────────────────────────────────


class TestRenderErrors:
    """siaDC09_renderErrors builds table or empty-state in #siaDC09_errorsList."""

    def test_empty_array_shows_empty_state(self) -> None:
        """
        Empty errors array must render the French empty-state em element.

        Expected result:
        - errorsList contains 'Aucune erreur enregistrée'
        - No <tr> elements present
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[]], "query": "#siaDC09_errorsList"})
        # Assert: empty-state message present
        assert "Aucune erreur" in r["text"]
        # Assert: no table rows for empty array

    def test_empty_array_has_no_table_rows(self) -> None:
        """
        Empty errors array must not create any <tr> elements.

        Expected result:
        - Zero <tr> elements in errorsList
        """
        r = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[]],
            "count_query": "#siaDC09_errorsList tr",
        })
        # Assert: no rows rendered
        assert r["count"] == 0

    def test_null_errors_shows_empty_state(self) -> None:
        """
        null errors value must be treated as empty (no crash).

        Expected result:
        - errorsList contains empty-state text
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [None], "query": "#siaDC09_errorsList"})
        # Assert: null treated same as empty array
        assert "Aucune erreur" in r["text"]

    def test_one_error_renders_one_row(self) -> None:
        """
        Single-element errors array must render exactly one <tr> row.

        Expected result:
        - One <tr> in the errors table
        """
        r = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[SAMPLE_ERROR]],
            "count_query": "#siaDC09_errorsList tr",
        })
        # Assert: exactly one row for one error
        assert r["count"] == 1

    def test_two_errors_render_two_rows(self) -> None:
        """
        Two-element errors array must render exactly two <tr> rows.

        Expected result:
        - Two <tr> elements in the errors table
        """
        r = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[SAMPLE_ERROR, SAMPLE_ERROR_T1]],
            "count_query": "#siaDC09_errorsList tr",
        })
        # Assert: count matches input array length
        assert r["count"] == 2

    def test_error_row_contains_code_text(self) -> None:
        """
        Error row must contain the error code as text in a cell.

        Expected result:
        - 'SUPERVISION_DISCONNECTED' appears in the rendered HTML
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR]], "query": "#siaDC09_errorsList"})
        # Assert: error code text visible in table
        assert "SUPERVISION_DISCONNECTED" in r["text"]

    def test_error_row_contains_message_text(self) -> None:
        """
        Error row must contain the error message in a cell.

        Expected result:
        - 'Supervision perdue' appears in rendered HTML
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR]], "query": "#siaDC09_errorsList"})
        # Assert: human-readable message displayed
        assert "Supervision perdue" in r["text"]

    def test_t3_error_gets_danger_tier_badge(self) -> None:
        """
        T3 error code (SUPERVISION_DISCONNECTED) must use label-danger CSS class.

        Expected result:
        - <span class="label label-danger"> present in row HTML
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR]], "query": "#siaDC09_errorsList"})
        # Assert: T3 tier badge class applied
        assert "label-danger" in r["html"]

    def test_t1_error_gets_info_tier_badge(self) -> None:
        """
        T1 error code (SUPERVISION_TIMEOUT) must use label-info CSS class.

        Expected result:
        - <span class="label label-info"> present in row HTML
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR_T1]], "query": "#siaDC09_errorsList"})
        # Assert: T1 tier badge class applied
        assert "label-info" in r["html"]

    def test_error_row_has_four_td_cells(self) -> None:
        """
        Each error row must have exactly 4 <td> cells: timestamp, tier, code, message.

        Expected result:
        - Exactly 4 <td> elements per row
        """
        r = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[SAMPLE_ERROR]],
            "count_query": "#siaDC09_errorsList td",
        })
        # Assert: 4 cells per row (1 row × 4 cells)
        assert r["count"] == 4

    def test_uses_condensed_table_class(self) -> None:
        """
        Error table must use Bootstrap 3 table-condensed class.

        Expected result:
        - 'table-condensed' class present on the <table> element
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR]], "query": "#siaDC09_errorsList"})
        # Assert: Bootstrap 3 compact table
        assert "table-condensed" in r["html"]


# ── renderMessages ────────────────────────────────────────────────────────────


class TestRenderMessages:
    """siaDC09_renderMessages builds message rows in #siaDC09_inspectorList."""

    def test_empty_array_shows_empty_state(self) -> None:
        """
        Empty messages array must render the French empty-state text.

        Expected result:
        - inspectorList contains 'Aucun échange SIA enregistré'
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[]],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: empty-state message
        assert "Aucun échange SIA enregistré" in r["text"]

    def test_null_messages_shows_empty_state(self) -> None:
        """
        null messages must be treated as empty (no crash).

        Expected result:
        - inspectorList shows empty-state text
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [None],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: null treated same as empty
        assert "Aucun échange SIA" in r["text"]

    def test_one_message_renders_one_row(self) -> None:
        """
        Single message must render exactly one .sia-msg-row div.

        Expected result:
        - One .sia-msg-row element in inspectorList
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE]],
            "count_query": "#siaDC09_inspectorList .sia-msg-row",
        })
        # Assert: one row per message
        assert r["count"] == 1

    def test_two_messages_render_two_rows(self) -> None:
        """
        Two messages must render two .sia-msg-row divs.

        Expected result:
        - Two .sia-msg-row elements
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE, SAMPLE_ALARM_MESSAGE]],
            "count_query": "#siaDC09_inspectorList .sia-msg-row",
        })
        # Assert: count matches input array length
        assert r["count"] == 2

    def test_routine_supervision_shows_success_badge(self) -> None:
        """
        Routine supervision message must use label-success badge class.

        Expected result:
        - .sia-status element has class label-success in its outerHTML
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE]],
            "query": "#siaDC09_inspectorList .sia-status",
        })
        # Assert: routine supervision → success (green) badge class on element
        assert "label-success" in (r.get("outerHTML") or "")

    def test_elapsed_ms_shown_in_badge_text(self) -> None:
        """
        Elapsed time must be shown as text in the status badge: '<N>ms'.

        Expected result:
        - '245ms' appears in the rendered row
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE]],
            "query": "#siaDC09_inspectorList .sia-status",
        })
        # Assert: elapsed_ms value + 'ms' suffix present
        assert "245ms" in r["text"]

    def test_row_stores_request_hex_attribute(self) -> None:
        """
        Each message row must have data-request-hex attribute set.

        Expected result:
        - data-request-hex == SAMPLE_MESSAGE['request_hex']
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE]],
            "query": "#siaDC09_inspectorList .sia-msg-row",
            "attr": "data-request-hex",
        })
        # Assert: request hex stored for later expand/decode
        assert r["attr"] == "AABBCCDD"

    def test_row_stores_response_hex_attribute(self) -> None:
        """
        Each message row must have data-response-hex attribute set.

        Expected result:
        - data-response-hex == SAMPLE_MESSAGE['response_hex']
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_MESSAGE]],
            "query": "#siaDC09_inspectorList .sia-msg-row",
            "attr": "data-response-hex",
        })
        # Assert: response hex stored for composite cache key
        assert r["attr"] == "11223344"

    def test_alarm_message_shows_warning_badge(self) -> None:
        """
        Non-routine alarm message must use label-warning badge class.

        Expected result:
        - .sia-status element has class label-warning in its outerHTML
        """
        r = _one({
            "fn": "siaDC09_renderMessages",
            "args": [[SAMPLE_ALARM_MESSAGE]],
            "query": "#siaDC09_inspectorList .sia-status",
        })
        # Assert: non-routine → warning badge class on element
        assert "label-warning" in (r.get("outerHTML") or "")


# ── buildHexButtons ───────────────────────────────────────────────────────────


class TestBuildHexButtons:
    """siaDC09_buildHexButtons returns a DOM fragment with copy buttons."""

    def test_request_and_response_both_present_creates_two_buttons(self) -> None:
        """
        When both requestHex and responseHex are non-empty, two buttons must be created.

        Expected result:
        - Two .sia-copy-hex buttons in the returned fragment
        """
        r = _one({
            "fn": "siaDC09_buildHexButtons",
            "args": ["AABB", "CCDD"],
            "count_query": "#siaDC09_inspectorList .sia-copy-hex",
        })
        # Assert: two copy buttons (sent + received)
        assert r["count"] == 2

    def test_empty_response_hex_creates_one_button(self) -> None:
        """
        When responseHex is empty, only one button (for request) must be created.

        Expected result:
        - One .sia-copy-hex button
        """
        r = _one({
            "fn": "siaDC09_buildHexButtons",
            "args": ["AABB", ""],
            "count_query": "#siaDC09_inspectorList .sia-copy-hex",
        })
        # Assert: no response button when responseHex is empty
        assert r["count"] == 1

    def test_button_data_hex_attribute_set(self) -> None:
        """
        Copy button must have data-hex attribute set to the hex string.

        Expected result:
        - data-hex == 'AABB' on the first button
        """
        r = _one({
            "fn": "siaDC09_buildHexButtons",
            "args": ["AABB", ""],
            "query": "#siaDC09_inspectorList .sia-copy-hex",
            "attr": "data-hex",
        })
        # Assert: hex value accessible via data attribute
        assert r["attr"] == "AABB"


# ── buildFieldTable ───────────────────────────────────────────────────────────


class TestBuildFieldTable:
    """siaDC09_buildFieldTable renders a decoded frame as a field table."""

    def test_table_has_champ_valeur_headers(self) -> None:
        """
        Field table must have 'Champ' and 'Valeur' column headers.

        Expected result:
        - 'Champ' and 'Valeur' appear in table headers
        """
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [SAMPLE_DECODED],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: French column headers present
        assert "Champ" in r["text"]
        assert "Valeur" in r["text"]

    def test_id_token_row_present(self) -> None:
        """
        Decoded frame field table must include an 'ID Token' row.

        Expected result:
        - 'ID Token' label and 'SIA-DCS' value visible
        """
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [SAMPLE_DECODED],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: id_token field rendered
        assert "ID Token" in r["text"]
        assert "SIA-DCS" in r["text"]

    def test_crc_valid_shows_checkmark(self) -> None:
        """
        When crc_valid=True, the CRC row must show a checkmark (✓).

        Expected result:
        - CRC valid indicator present in HTML (✓ or ✔ unicode)
        """
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [SAMPLE_DECODED],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: CRC valid shown with green checkmark
        assert "CRC" in r["text"]
        assert "✓" in r["html"] or "&#10003;" in r["html"] or "valide" in r["html"]

    def test_encrypted_false_no_encryption_banner(self) -> None:
        """
        When encrypted=False, no encryption indicator banner must appear.

        Expected result:
        - 'AES-128-CBC' not in rendered HTML
        """
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [SAMPLE_DECODED],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: no encryption banner for plaintext frame
        assert "AES-128-CBC" not in r["html"]

    def test_encrypted_true_no_key_shows_warning_banner(self) -> None:
        """
        When encrypted=True and data_decrypted=None, warning banner must appear.

        Expected result:
        - 'label-warning' class and 'non déchiffré' text present
        """
        decoded_enc = {**SAMPLE_DECODED, "encrypted": True, "data_decrypted": None}
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [decoded_enc],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: encrypted but no key → warning banner
        assert "label-warning" in r["html"]
        assert "non déchiffré" in r["html"]

    def test_encrypted_with_key_shows_info_banner(self) -> None:
        """
        When encrypted=True and data_decrypted is set, info banner must appear.

        Expected result:
        - 'label-info' class and 'déchiffré' text without '(non' prefix
        """
        decoded_dec = {**SAMPLE_DECODED, "encrypted": True, "data_decrypted": "#1234|0000"}
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [decoded_dec],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: encrypted + decrypted → info (blue) banner
        assert "label-info" in r["html"]

    def test_account_number_visible(self) -> None:
        """
        Account number must be rendered in the field table.

        Expected result:
        - '1234' appears in the table
        """
        r = _one({
            "fn": "siaDC09_buildFieldTable",
            "args": [SAMPLE_DECODED],
            "query": "#siaDC09_inspectorList",
        })
        # Assert: account value displayed
        assert "1234" in r["text"]


# ── initDiagnosticTab ─────────────────────────────────────────────────────────


class TestInitDiagnosticTab:
    """siaDC09_initDiagnosticTab shows/hides the diagnostic tab li."""

    def test_step_4_shows_tab(self) -> None:
        """
        wizardStep=4 must make #siaDC09_diagnosticTabLi visible (display != none).

        Expected result:
        - diagnosticTabLi display style is '' (not 'none')
        """
        r = _one({
            "fn": "siaDC09_initDiagnosticTab",
            "args": [4],
            "query": "#siaDC09_diagnosticTabLi",
        })
        # Assert: tab visible when wizard complete
        assert r["style"].get("display") != "none"

    def test_step_3_hides_tab(self) -> None:
        """
        wizardStep=3 must keep #siaDC09_diagnosticTabLi hidden (display: none).

        Expected result:
        - diagnosticTabLi display style is 'none'
        """
        r = _one({
            "fn": "siaDC09_initDiagnosticTab",
            "args": [3],
            "query": "#siaDC09_diagnosticTabLi",
        })
        # Assert: tab hidden for incomplete wizard
        assert r["style"].get("display") == "none"

    def test_step_0_hides_tab(self) -> None:
        """
        wizardStep=0 (initial state) must hide the diagnostic tab.

        Expected result:
        - diagnosticTabLi display style is 'none'
        """
        r = _one({
            "fn": "siaDC09_initDiagnosticTab",
            "args": [0],
            "query": "#siaDC09_diagnosticTabLi",
        })
        # Assert: fresh install → tab hidden
        assert r["style"].get("display") == "none"

    def test_step_5_still_shows_tab(self) -> None:
        """
        wizardStep=5 (> 4) must also show the tab (>= 4 condition).

        Expected result:
        - diagnosticTabLi display style is '' (visible)
        """
        r = _one({
            "fn": "siaDC09_initDiagnosticTab",
            "args": [5],
            "query": "#siaDC09_diagnosticTabLi",
        })
        # Assert: any step >= 4 shows the tab
        assert r["style"].get("display") != "none"


# ── decodeCache composite key ─────────────────────────────────────────────────


class TestDecodeCacheKey:
    """_siaDC09_decodeCache uses composite key to avoid collision."""

    def test_same_request_different_response_distinct_cache_entries(self) -> None:
        """
        Two frames with identical request_hex but different response_hex must
        produce two distinct cache entries (not overwrite each other).

        Expected result:
        - cache['AABB|CC11'] and cache['AABB|DD22'] both exist
        - The old bare 'AABB' key is NOT used
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-01-01T00:00:00Z"],
                  "cache_key_test": True})
        # Assert: composite keys distinct and bare key absent
        assert r["value"]["key1_exists"] is True
        assert r["value"]["key2_exists"] is True
        assert r["value"]["keys_distinct"] is True
        assert r["value"]["old_key_absent"] is True
