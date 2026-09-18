"""
Level 1 DOM tests for the siaDC09 dashboard widget live-refresh behaviour.

Renders core/template/{dashboard,mobile}/siaDC09.html with #placeholders#
substituted, executes the inline <script> in a jsdom window, then drives live
command pushes through Jeedom's real refresh path: the widget registers
callbacks with jeedom.cmd.addUpdateFunction(cmd_id, fn), and a push calls
jeedom.cmd.refreshValue([...]) which invokes them with an _options payload —
exactly what Jeedom's poll loop (cmd::update -> refreshValue) does in production.
Asserts on the resulting DOM — badge class, label text, event text — and on the
callback registration, not on keyword presence.

Story 10.3 acceptance criteria exercised:
  - AC1: live badge + supervision_label refresh without reload
  - AC2: live event_label refresh (fixes the "reste à OK" observation)
  - AC3: stale detection still fires; live push clears stale-grey
  - AC5: dashboard and mobile templates are byte-for-byte identical

Reference: _bmad-output/implementation-artifacts/10-3-widget-live-refresh-on-command-update.md
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HARNESS = _PROJECT_ROOT / "tests" / "fixtures" / "widget_dom_harness.js"
_DASHBOARD_TPL = _PROJECT_ROOT / "core" / "template" / "dashboard" / "siaDC09.html"
_MOBILE_TPL = _PROJECT_ROOT / "core" / "template" / "mobile" / "siaDC09.html"
_NODE = "node"

# A fixed clock well after any collectDate below, so the stale window is under
# control per-scenario via the collectDate we feed the byId stub.
_NOW_MS = 1_760_000_000_000  # 2025-10-09T… — arbitrary fixed epoch for determinism

# Default command ids the harness substitutes for the three info commands.
_STATE_ID = "101"
_LABEL_ID = "102"
_EVENT_ID = "103"


def _run(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run scenarios through the widget jsdom harness; return the result list."""
    result = subprocess.run(
        [_NODE, str(_HARNESS), json.dumps(scenarios)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"Harness error:\n{result.stderr}"
    return json.loads(result.stdout)


def _one(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run a single scenario and fail loudly on any JS error."""
    r = _run([scenario])[0]
    if r.get("error"):
        pytest.fail(f"JS error in scenario {scenario}: {r['error']}")
    return r


# ── AC5: templates identical ────────────────────────────────────────────────


def test_dashboard_and_mobile_templates_identical() -> None:
    """The mobile template must be a byte-for-byte copy of the dashboard one.

    - reading both files yields identical bytes
    """
    dashboard = _DASHBOARD_TPL.read_bytes()
    mobile = _MOBILE_TPL.read_bytes()
    # AC5: diff of the two templates is empty
    assert dashboard == mobile, "dashboard and mobile templates diverge"


# ── AC1/AC6: the widget registers live-update callbacks ─────────────────────


def test_widget_registers_update_callbacks_for_all_info_cmds() -> None:
    """The tile must register a jeedom.cmd.addUpdateFunction callback per command.

    - a callback is registered for supervision_state, supervision_label, event_label
    """
    r = _one({})
    # AC1/AC6: without these registrations the tile never live-refreshes
    assert _STATE_ID in r["registered"]
    assert _LABEL_ID in r["registered"]
    assert _EVENT_ID in r["registered"]


# ── AC1: live badge + supervision_label refresh ─────────────────────────────


class TestLiveSupervisionRefresh:
    """A pushed supervision_state/label updates the tile without a reload."""

    def test_label_push_updates_label_text(self) -> None:
        """A pushed supervision_label display_value replaces the label text live.

        - the label callback writes the pushed display_value into the label span
        """
        r = _one({
            "actions": [{"type": "pushLabel", "value": "Supervision perdue"}],
        })
        # AC1: refreshValue → registered callback → new label text, no reload
        assert r["labelText"] == "Supervision perdue"

    def test_push_state_degraded_sets_warning_badge(self) -> None:
        """Pushing supervision_state=1 recolors the badge to warning live.

        - badge class contains text-warning after the push
        - stale/other state colors are removed
        """
        r = _one({
            "placeholders": {"badge_class": "text-success"},
            "actions": [{"type": "pushState", "value": "1"}],
        })
        # AC1: numeric state → client-side badge mapping (1 → warning)
        assert "text-warning" in r["badgeClass"]
        assert "text-success" not in r["badgeClass"]
        assert "text-danger" not in r["badgeClass"]

    def test_push_state_lost_sets_danger_badge(self) -> None:
        """Pushing supervision_state=0 recolors the badge to danger live.

        - badge class contains text-danger after the push
        """
        r = _one({
            "placeholders": {"badge_class": "text-success"},
            "actions": [{"type": "pushState", "value": "0"}],
        })
        # AC1: state 0 (or any non 1/2) → danger
        assert "text-danger" in r["badgeClass"]
        assert "text-success" not in r["badgeClass"]

    def test_push_state_healthy_sets_success_badge(self) -> None:
        """Pushing supervision_state=2 recolors the badge to success live.

        - badge class contains text-success after the push
        """
        r = _one({
            "placeholders": {"badge_class": "text-danger"},
            "actions": [{"type": "pushState", "value": "2"}],
        })
        # AC1: state 2 → success
        assert "text-success" in r["badgeClass"]
        assert "text-danger" not in r["badgeClass"]


# ── AC2: live event_label refresh — the "reste à OK" fix ─────────────────────


class TestLiveEventRefresh:
    """A pushed event_label updates the event line without a reload."""

    def test_event_push_updates_event_text(self) -> None:
        """A pushed event_label display_value replaces the event line live.

        - the initial event text is the rendered placeholder
        - a pushed 'Confirmé' replaces it in place (fixes 'reste à OK')
        """
        r = _one({
            "placeholders": {"event_label": "OK"},
            "actions": [{"type": "pushEvent", "value": "Confirmé"}],
        })
        # AC2: the event line moves off 'OK' to the confirmed value on its own
        assert r["eventText"] == "Confirmé"


# ── AC3: stale detection + cooperation with live push ────────────────────────


class TestStaleCooperation:
    """The 10-2 one-shot stale check still fires and cooperates with live push."""

    def test_stale_check_greys_badge_when_collectdate_old(self) -> None:
        """With a collectDate older than 3× interval, badge goes text-muted.

        - badge class becomes text-muted
        - label text becomes the stale label
        """
        # 600s stale; interval 60 → threshold 180s → clearly stale
        r = _one({
            "placeholders": {"supervision_interval": "60", "badge_class": "text-success"},
            "now": _NOW_MS,
            "byId": {"staleSeconds": 600},
        })
        # AC3: stale one-shot check still greys the badge and relabels
        assert "text-muted" in r["badgeClass"]
        assert r["labelText"] == "Données non disponibles"

    def test_live_state_push_clears_stale_grey(self) -> None:
        """A fresh supervision_state push after stale-grey restores a live color.

        - after grey, pushing state=2 removes text-muted and sets text-success
        """
        r = _one({
            "placeholders": {"supervision_interval": "60", "badge_class": "text-success"},
            "now": _NOW_MS,
            "byId": {"staleSeconds": 600},
            "actions": [{"type": "pushState", "value": "2"}],
        })
        # AC3: a genuine new push proves freshness → stale-grey must give way
        assert "text-muted" not in r["badgeClass"]
        assert "text-success" in r["badgeClass"]

    def test_no_push_leaves_server_rendered_badge(self) -> None:
        """With a fresh collectDate and no push, the server badge class is kept.

        - badge keeps the server-rendered text-success, no stale grey
        """
        r = _one({
            "placeholders": {"supervision_interval": "60", "badge_class": "text-success"},
            "now": _NOW_MS,
            "byId": {"staleSeconds": 30},  # well within the 180s threshold
        })
        # AC3: live path must not fight a fresh server render
        assert "text-success" in r["badgeClass"]
        assert "text-muted" not in r["badgeClass"]
