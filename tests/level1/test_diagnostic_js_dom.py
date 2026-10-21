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
import re
import subprocess
import sys
from datetime import datetime
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
    """siaDC09_formatTimestamp converts ISO 8601 -> widget-style local time."""

    @staticmethod
    def _local_ms(iso_local: str) -> int:
        """Epoch ms of a naive local ISO string, parsed like the JS (local time)."""
        return int(datetime.fromisoformat(iso_local).timestamp() * 1000)

    def test_recent_event_is_relative_with_clock_time(self) -> None:
        """
        An event less than a minute old reads "à l'instant" followed by the clock time.

        Expected result:
        - "à l'instant · 14:32:11" (local time, no timezone shift)
        """
        base = self._local_ms("2026-05-18T14:32:11")
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11", base + 30_000]})
        # Assert: relative prefix plus local clock time
        assert r["value"] == "à l'instant · 14:32:11"

    def test_minutes_old_event(self) -> None:
        """
        An event minutes old reads "il y a N min · hh:mm:ss".

        Expected result:
        - "il y a 5 min · 14:32:11"
        """
        base = self._local_ms("2026-05-18T14:32:11")
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11", base + 5 * 60_000]})
        # Assert: minutes branch
        assert r["value"] == "il y a 5 min · 14:32:11"

    def test_yesterday_event(self) -> None:
        """
        An event from the previous day reads "hier hh:mm:ss".

        Expected result:
        - "hier 14:32:11"
        """
        base = self._local_ms("2026-05-18T14:32:11")
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11", base + 24 * 3600_000]})
        # Assert: yesterday branch
        assert r["value"] == "hier 14:32:11"

    def test_older_than_yesterday_is_absolute(self) -> None:
        """
        Errors older than yesterday show dd/mm hh:mm:ss (widget format).

        Expected result:
        - "18/05 14:32:11"
        """
        base = self._local_ms("2026-05-18T14:32:11")
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11", base + 5 * 24 * 3600_000]})
        # Assert: absolute branch
        assert r["value"] == "18/05 14:32:11"

    def test_offset_iso_is_accepted(self) -> None:
        """
        ISO strings with an offset (what the daemon writes) are parsed, shown in local time.

        Expected result:
        - A recent offset-ISO timestamp ends with a local hh:mm:ss
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18T14:32:11+00:00", 0]})
        # Assert: format valid whatever the machine timezone
        assert re.search(r"\d{2}:\d{2}:\d{2}$|^\d{2}/\d{2} \d{2}:\d{2}:\d{2}$", r["value"])

    def test_jeedom_date_format_is_accepted(self) -> None:
        """
        Jeedom collectDate strings ("Y-m-d H:i:s") are parsed as local time.

        Expected result:
        - "il y a 5 min · 14:32:11"
        """
        base = self._local_ms("2026-05-18T14:32:11")
        r = _one({"fn": "siaDC09_formatTimestamp", "args": ["2026-05-18 14:32:11", base + 5 * 60_000]})
        # Assert: dash-separated Jeedom date handled
        assert r["value"] == "il y a 5 min · 14:32:11"

    def test_empty_string_returns_empty(self) -> None:
        """
        Empty string must return empty string (no crash, no placeholder).

        Expected result:
        - Returns ''
        """
        r = _one({"fn": "siaDC09_formatTimestamp", "args": [""]})
        # Assert: empty input -> empty output
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
        # Assert: invalid date -> empty (isNaN guard)
        assert r["value"] == ""


# ── renderBadge (SM1) ──────────────────────────────────────────────────────────


class TestRenderBadge:
    """siaDC09_renderBadge colors the SM1 ring (widget classes) and writes label/sub/time."""

    @staticmethod
    def _ring(args: list[Any]) -> dict[str, Any]:
        return _one({"fn": "siaDC09_renderBadge", "args": args, "query": "#siaDC09_badge",
                     "attr": "class"})

    def test_state_2_sets_success_class(self) -> None:
        """
        supervision_state=2 (healthy) must put text-success on the ring.

        Expected result:
        - ring class contains text-success
        """
        # Assert: green for healthy
        assert "text-success" in self._ring([2, "Connexion OK"])["attr"]

    def test_state_1_sets_warning_class(self) -> None:
        """
        supervision_state=1 (degraded) must put text-warning on the ring.

        Expected result:
        - ring class contains text-warning
        """
        # Assert: orange for degraded
        assert "text-warning" in self._ring([1, "Dégradée"])["attr"]

    def test_state_0_sets_danger_class(self) -> None:
        """
        supervision_state=0 (disconnected) must put text-danger on the ring.

        Expected result:
        - ring class contains text-danger
        """
        # Assert: red for disconnected
        assert "text-danger" in self._ring([0, "Liaison perdue"])["attr"]

    def test_unknown_and_nan_state_fall_back_to_warning(self) -> None:
        """
        Unknown or non-numeric state falls back to warning (no blank, no crash).

        Expected result:
        - text-warning for 99 and for null
        """
        # Assert: unknown state falls back to the degraded class
        assert "text-warning" in self._ring([99, "?"])["attr"]
        # Assert: NaN state falls back to the degraded class
        assert "text-warning" in self._ring([None, "?"])["attr"]

    def test_label_text_set_correctly(self) -> None:
        """
        renderBadge must set #siaDC09_badgeLabel text to the label.

        Expected result:
        - badgeLabel textContent == 'Connexion OK'
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [2, "Connexion OK"],
                  "query": "#siaDC09_badgeLabel"})
        # Assert: label text matches second argument
        assert r["text"] == "Connexion OK"

    def test_empty_label_sets_empty_text(self) -> None:
        """
        Empty/null label must give empty text (not 'null').

        Expected result:
        - badgeLabel textContent == ''
        """
        r = _one({"fn": "siaDC09_renderBadge", "args": [2, None], "query": "#siaDC09_badgeLabel"})
        # Assert: null label -> empty string
        assert r["text"] == ""

    def test_failure_counter_split_into_sub_label(self) -> None:
        """
        "Liaison dégradée (2/3)" is split: label without counter, sub-label "2 échecs sur 3".

        Expected result:
        - label 'Liaison dégradée', sub-label '2 échecs sur 3', sub-label visible
        """
        label = _one({"fn": "siaDC09_renderBadge", "args": [1, "Liaison dégradée (2/3)"],
                      "query": "#siaDC09_badgeLabel"})
        sub = _one({"fn": "siaDC09_renderBadge", "args": [1, "Liaison dégradée (2/3)"],
                    "query": "#siaDC09_badgeSub"})
        # Assert: counter stripped from the label
        assert label["text"] == "Liaison dégradée"
        # Assert: counter rewritten in words
        assert sub["text"] == "2 échecs sur 3"
        # Assert: sub-label displayed
        assert sub["style"]["display"] == "block"

    def test_single_failure_is_singular(self) -> None:
        """
        One failure reads "1 échec sur 3" (singular).

        Expected result:
        - sub-label '1 échec sur 3'
        """
        sub = _one({"fn": "siaDC09_renderBadge", "args": [1, "Liaison dégradée (1/3)"],
                    "query": "#siaDC09_badgeSub"})
        # Assert: singular form
        assert sub["text"] == "1 échec sur 3"

    def test_time_shown_from_state_date(self) -> None:
        """
        The last-update time comes from the state date argument.

        Expected result:
        - badgeTime non-empty with a clock time for a valid date, empty without one
        """
        with_date = _one({"fn": "siaDC09_renderBadge", "args": [2, "OK", "2026-05-18 14:32:11"],
                          "query": "#siaDC09_badgeTime"})
        without = _one({"fn": "siaDC09_renderBadge", "args": [2, "OK"], "query": "#siaDC09_badgeTime"})
        # Assert: formatted time present
        assert re.search(r"14:32:11$", with_date["text"])
        # Assert: no date -> no time
        assert without["text"] == ""


# ── renderEventBadge (SM2) ──────────────────────────────────────────────────────


class TestRenderEventBadge:
    """siaDC09_renderEventBadge renders the 'Dernier événement' card like the widget."""

    def test_confirmed_intrusion_colors_bar_and_head(self) -> None:
        """
        "Intrusion (zone 3) : confirmée" -> danger-colored bar, type and zone shown.

        Expected result:
        - eventBar has text-danger, type 'Intrusion', where 'zone 3', status 'confirmée'
        """
        label = "Intrusion (zone 3) : confirmée"
        bar = _one({"fn": "siaDC09_renderEventBadge", "args": [1, label],
                    "query": "#siaDC09_eventBar", "attr": "class"})
        typ = _one({"fn": "siaDC09_renderEventBadge", "args": [1, label],
                    "query": "#siaDC09_eventTypeText"})
        where = _one({"fn": "siaDC09_renderEventBadge", "args": [1, label],
                      "query": "#siaDC09_eventWhere"})
        status = _one({"fn": "siaDC09_renderEventBadge", "args": [1, label],
                       "query": "#siaDC09_eventBadgeLabel"})
        # Assert: intrusion is red
        assert "text-danger" in bar["attr"]
        # Assert: type parsed
        assert typ["text"] == "Intrusion"
        # Assert: zone parsed
        assert where["text"] == "zone 3"
        # Assert: status text parsed
        assert status["text"] == "confirmée"

    def test_pending_status_is_warning(self) -> None:
        """
        An "en cours" status is colored warning on the status text.

        Expected result:
        - eventBadgeLabel has text-warning
        """
        r = _one({"fn": "siaDC09_renderEventBadge", "args": [3, "Armement (utilisateur 1) : en cours"],
                  "query": "#siaDC09_eventBadgeLabel", "attr": "class"})
        # Assert: pending is orange
        assert "text-warning" in r["attr"]

    def test_failed_status_is_danger(self) -> None:
        """
        A "sans réponse" status is colored danger on the status text.

        Expected result:
        - eventBadgeLabel has text-danger
        """
        r = _one({"fn": "siaDC09_renderEventBadge", "args": [2, "Intrusion (zone 1) : sans réponse"],
                  "query": "#siaDC09_eventBadgeLabel", "attr": "class"})
        # Assert: failure is red
        assert "text-danger" in r["attr"]

    def test_idle_label_shown_raw_and_muted(self) -> None:
        """
        An idle label has no type/status: raw text, muted bar, head hidden.

        Expected result:
        - eventBadgeLabel == 'Inactif', eventBar text-muted, eventHead hidden
        """
        label = _one({"fn": "siaDC09_renderEventBadge", "args": [0, "Inactif"],
                      "query": "#siaDC09_eventBadgeLabel"})
        bar = _one({"fn": "siaDC09_renderEventBadge", "args": [0, "Inactif"],
                    "query": "#siaDC09_eventBar", "attr": "class"})
        head = _one({"fn": "siaDC09_renderEventBadge", "args": [0, "Inactif"],
                     "query": "#siaDC09_eventHead"})
        # Assert: raw text kept
        assert label["text"] == "Inactif"
        # Assert: muted bar
        assert "text-muted" in bar["attr"]
        # Assert: head hidden
        assert head["style"]["display"] == "none"

    def test_nan_state_does_not_crash(self) -> None:
        """
        Null state and null label must not crash and leave the label empty.

        Expected result:
        - eventBadgeLabel textContent == ''
        """
        r = _one({"fn": "siaDC09_renderEventBadge", "args": [None, None],
                  "query": "#siaDC09_eventBadgeLabel"})
        # Assert: null label -> empty string
        assert r["text"] == ""

    def test_time_shown_only_for_real_events(self) -> None:
        """
        The event time is prefixed ' · ' for a real event and blank for idle.

        Expected result:
        - event: time starts with '·'; idle: empty
        """
        ev = _one({"fn": "siaDC09_renderEventBadge",
                   "args": [1, "Intrusion (zone 3) : confirmée", "2026-05-18 14:32:11"],
                   "query": "#siaDC09_eventTime"})
        idle = _one({"fn": "siaDC09_renderEventBadge", "args": [0, "Inactif", "2026-05-18 14:32:11"],
                     "query": "#siaDC09_eventTime"})
        # Assert: prefixed time for a real event
        assert ev["text"].startswith("·")
        # Assert: no time for idle
        assert idle["text"] == ""

    def test_load_diagnostic_data_wires_event_state_into_event_badge(self) -> None:
        """
        loadDiagnosticData forwards event_label and event_date to renderEventBadge.

        Expected result:
        - eventBadgeLabel == 'confirmée' from the mocked payload
        """
        r = _one({"fn": "siaDC09_loadDiagnosticData",
                  "ajax_result": {"event_state": 1, "event_label": "Intrusion (zone 3) : confirmée",
                                  "event_date": "2026-05-18 14:32:11"},
                  "query": "#siaDC09_eventBadgeLabel"})
        # Assert: end-to-end wiring reaches the event card
        assert r["text"] == "confirmée"

    def test_load_diagnostic_data_wires_state_date_into_badge(self) -> None:
        """
        loadDiagnosticData forwards state_date to renderBadge.

        Expected result:
        - badgeTime ends with the clock time of the mocked state_date
        """
        r = _one({"fn": "siaDC09_loadDiagnosticData",
                  "ajax_result": {"supervision_state": 2, "supervision_label": "OK",
                                  "state_date": "2026-05-18 14:32:11"},
                  "query": "#siaDC09_badgeTime"})
        # Assert: SM1 time comes from state_date
        assert r["text"].endswith("14:32:11")

    def test_load_diagnostic_data_missing_event_fields_do_not_crash(self) -> None:
        """
        event fields missing entirely from the payload must not crash.

        Expected result:
        - eventBadgeLabel is empty, eventBar muted
        """
        r = _one({"fn": "siaDC09_loadDiagnosticData",
                  "ajax_result": {"supervision_state": 2, "supervision_label": "OK"},
                  "query": "#siaDC09_eventBar", "attr": "class"})
        # Assert: muted fallback
        assert "text-muted" in r["attr"]


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

    def test_no_tier_badge(self) -> None:
        """
        The T1/T2/T3 tier badge is gone: no label element in the errors table.

        Expected result:
        - zero .label elements for T3 and T1 errors
        """
        r = _one({"fn": "siaDC09_renderErrors", "args": [[SAMPLE_ERROR, SAMPLE_ERROR_T1]],
                  "count_query": "#siaDC09_errorsList .label"})
        # Assert: no badge rendered
        assert r["count"] == 0

    def test_error_row_has_three_td_cells_top_aligned(self) -> None:
        """
        Each error row has exactly 3 <td> cells (time, code, message), all top-aligned.

        Expected result:
        - 3 <td> per row, each with vertical-align:top
        """
        r = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[SAMPLE_ERROR]],
            "count_query": "#siaDC09_errorsList td",
        })
        top = _one({
            "fn": "siaDC09_renderErrors",
            "args": [[SAMPLE_ERROR]],
            "count_query": "#siaDC09_errorsList td[style*='vertical-align:top']",
        })
        # Assert: 3 cells per row
        assert r["count"] == 3
        # Assert: every cell top-aligned
        assert top["count"] == 3

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

    @staticmethod
    def _field(msg: dict[str, Any], selector: str) -> dict[str, Any]:
        return _one({"fn": "siaDC09_renderMessages", "args": [[msg]],
                     "query": f"#siaDC09_inspectorList {selector}"})

    def test_routine_supervision_shows_routine_label(self) -> None:
        """
        Routine supervision message: grey 'routine' kind label.

        Expected result:
        - .sia-kind text 'routine' with label-default
        """
        r = self._field(SAMPLE_MESSAGE, ".sia-kind")
        # Assert: text
        assert r["text"] == "routine"
        # Assert: grey class
        assert "label-default" in (r.get("outerHTML") or "")

    def test_alarm_message_shows_event_label(self) -> None:
        """
        Alarm frame delivered normally: green 'événement' kind label.

        Expected result:
        - .sia-kind text 'événement' with label-success
        """
        r = self._field(SAMPLE_ALARM_MESSAGE, ".sia-kind")
        # Assert: text
        assert r["text"] == "événement"
        # Assert: green class
        assert "label-success" in (r.get("outerHTML") or "")

    def test_alarm_retry_shows_retry_label(self) -> None:
        """
        Alarm frame sent again (nak_retry / failed_timeout): orange 'retry'.

        Expected result:
        - .sia-kind text 'retry' with label-warning for both transitions
        """
        for tr in ("nak_retry", "failed_timeout"):
            r = self._field({**SAMPLE_ALARM_MESSAGE, "transition": tr}, ".sia-kind")
            # Assert: text
            assert r["text"] == "retry"
            # Assert: orange class
            assert "label-warning" in (r.get("outerHTML") or "")

    def test_supervision_failure_shows_incident_label(self) -> None:
        """
        Non-routine supervision (timeout / NAK): red 'incident'.

        Expected result:
        - .sia-kind text 'incident' with label-danger
        """
        r = self._field({**SAMPLE_MESSAGE, "routine": 0}, ".sia-kind")
        # Assert: text
        assert r["text"] == "incident"
        # Assert: red class
        assert "label-danger" in (r.get("outerHTML") or "")

    def test_failed_alarm_shows_incident_label(self) -> None:
        """
        Alarm that ended in a final failure (not a retry): red 'incident'.

        Expected result:
        - .sia-kind text 'incident' for transition failed_refused
        """
        r = self._field({**SAMPLE_ALARM_MESSAGE, "transition": "failed_refused"}, ".sia-kind")
        # Assert: final failure is an incident
        assert r["text"] == "incident"

    def test_elapsed_ms_shown_uncolored(self) -> None:
        """
        Elapsed time is plain text '<N>ms', with no label/color class.

        Expected result:
        - '245ms' in .sia-delay, no 'label' class on it
        """
        r = self._field(SAMPLE_MESSAGE, ".sia-delay")
        # Assert: elapsed_ms value + 'ms' suffix present
        assert r["text"] == "245ms"
        # Assert: delay is not colored
        assert "label" not in (r.get("outerHTML") or "").split(">")[0]

    def test_token_shows_event_code(self) -> None:
        """
        The token cell shows the frame/event code from the daemon, not SIA-DCS.

        Expected result:
        - 'BA' shown, and its explanation 'Alarme intrusion'
        """
        msg = {**SAMPLE_ALARM_MESSAGE, "event_code": "BA"}
        tok = self._field(msg, ".sia-token")
        exp = self._field(msg, ".sia-explain")
        # Assert: code displayed
        assert tok["text"] == "BA"
        # Assert: explanation displayed
        assert exp["text"] == "Alarme intrusion"

    def test_token_defaults_to_null_for_supervision(self) -> None:
        """
        A message without event_code (supervision) shows NULL and its explanation.

        Expected result:
        - token 'NULL', explanation mentions supervision
        """
        tok = self._field(SAMPLE_MESSAGE, ".sia-token")
        exp = self._field(SAMPLE_MESSAGE, ".sia-explain")
        # Assert: NULL fallback
        assert tok["text"] == "NULL"
        # Assert: explanation present
        assert "supervision" in exp["text"]

    def test_time_uses_widget_format(self) -> None:
        """
        The row time column uses the widget format, not bare UTC hh:mm:ss.

        Expected result:
        - text matches 'dd/mm hh:mm:ss' for an old message
        """
        r = self._field(SAMPLE_MESSAGE, ".sia-time")
        # Assert: absolute widget format for an old timestamp
        assert re.match(r"^\d{2}/\d{2} \d{2}:\d{2}:\d{2}$", r["text"])

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
