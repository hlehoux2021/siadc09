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
import re
import subprocess
from datetime import datetime
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


_BODY_MARKER = '<div style="padding:4px 10px 8px 10px;">'


def test_dashboard_and_mobile_templates_share_body_and_script() -> None:
    """Only the root and name banner may differ between dashboard and mobile.

    - everything from the content body onward (badge, texts, inline script) is identical
    - the mobile root has no fixed width/height nor resize class (stock mobile markup)
    """
    dashboard = _DASHBOARD_TPL.read_text(encoding="utf-8")
    mobile = _MOBILE_TPL.read_text(encoding="utf-8")
    # AC5 (amended): the shared body and live-refresh script must not diverge
    assert dashboard[dashboard.index(_BODY_MARKER):] == mobile[mobile.index(_BODY_MARKER):]
    mobile_root = mobile[: mobile.index(">") + 1]
    # Fixed dashboard sizing is meaningless on the fluid mobile layout
    assert "#width#" not in mobile_root and "allowResize" not in mobile_root


def test_template_follows_stock_jeedom_widget_markup() -> None:
    """The tile root and header must follow the stock Jeedom eqLogic widget markup.

    - the root carries eqLogic/allowResize classes and the width/height/#style# inline style
    - the header is the standard widget-name banner, not a Bootstrap panel-heading
    - the root keeps the siaDC09 class and data-eqLogic_id the inline script selects on
    """
    html = _DASHBOARD_TPL.read_text(encoding="utf-8")
    root = html[: html.index(">") + 1]
    classes = root.split('class="', 1)[1].split('"', 1)[0].split()
    # Without eqLogic + allowResize, edit mode offers no resize handle
    assert "eqLogic" in classes and "allowResize" in classes
    # Placeholders Jeedom's preToHtml() fills for the stock behaviour (category, layout, uid)
    assert all(p in html for p in ("#custom_layout#", "#category#", "#uid#", "#tags#"))
    # Without the inline width/height, the tile stretches over the whole row
    assert "width:#width#;height:#height#;#style#" in root
    # Standard name banner, as on every stock widget
    assert 'class="widget-name"' in html and "#name_display#" in html
    # The Bootstrap panel header is what made the banner look non-standard
    assert "panel-heading" not in html
    # The live-refresh script finds its root through these two selectors
    assert "siaDC09" in classes and 'data-eqLogic_id="#id#"' in root


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
        - a pushed confirmed label replaces it in place (fixes 'reste à Inactif')
        - the card shows the status part, the full label stays in data-raw
        """
        confirmed = "Intrusion (zone 3) : Confirmé par la centrale"
        r = _one({
            "placeholders": {"event_label": "Inactif"},
            "actions": [{"type": "pushEvent", "value": confirmed}],
        })
        # AC2: the event line moves off 'Inactif' to the confirmed value on its own
        assert r["eventRaw"] == confirmed
        # The status line carries the part after ' : ' (type moved to the head)
        assert r["eventStatusText"] == "Confirmé par la centrale"


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


# ── Story 10-1 (suite): SM1 pictograms ───────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "state", "icon", "color"),
    [
        ("Connexion OK", "2", "fa-check-circle", "text-success"),
        ("Connexion en cours d'initialisation", "1", "fa-spinner fa-pulse", "text-warning"),
        ("Connexion dégradée (2/3)", "1", "fa-exclamation-triangle", "text-warning"),
        ("Connexion perdue", "0", "fa-unlink", "text-danger"),
        ("Tentative de reconnexion en cours", "0", "fa-sync-alt fa-spin", "text-danger"),
        ("Hors Réseau", "0", "fa-plug", "text-danger"),
        ("Clé de chiffrement invalide", "0", "fa-key", "text-danger"),
        ("ARRÊTÉ", "0", "fa-stop-circle", "text-danger"),
        ("Équipement désactivé", "0", "fa-pause-circle", "text-muted"),
    ],
)
def test_sm1_label_selects_icon_and_color(label: str, state: str, icon: str, color: str) -> None:
    """Each supervision_label gets its own pictogram and color in the round badge.

    - the icon classes come from the label text, not the 0/1/2 state alone
    - the badge color follows the state (muted for a disabled equipment)
    """
    r = _one({
        "actions": [
            {"type": "pushState", "value": state},
            {"type": "pushLabel", "value": label},
        ],
    })
    # SM1 B: pictogram per label
    assert r["iconClass"] == f"siaDC09-icon fas {icon}"
    # Color class on the badge (currentColor drives the ring and the icon)
    assert color in r["badgeClass"]


def test_sm1_degraded_counter_moves_to_sub_label() -> None:
    """A degraded label shows its N/3 counter as a sub-label.

    - the main label drops the counter, the sub-label shows it
    """
    r = _one({"actions": [{"type": "pushLabel", "value": "Connexion dégradée (2/3)"}]})
    # Main label without the counter
    assert r["labelText"] == "Connexion dégradée"
    # Counter in the visible sub-label
    assert r["subText"] == "2/3" and r["subShown"] is True


def test_sm1_stale_shows_clock_icon_then_live_push_restores() -> None:
    """Stale shows the grey clock; a live state push brings the real icon back.

    - stale: fa-clock + text-muted
    - after pushState 2 + label OK: fa-check-circle + text-success
    """
    base = {
        "placeholders": {"supervision_interval": "60", "badge_class": "text-success"},
        "now": _NOW_MS,
        "byId": {"staleSeconds": 600},
    }
    stale = _one(base)
    # Stale one-shot check greys the pictogram
    assert "fa-clock" in stale["iconClass"] and "text-muted" in stale["badgeClass"]
    live = _one({**base, "actions": [
        {"type": "pushState", "value": "2"},
        {"type": "pushLabel", "value": "Connexion OK"},
    ]})
    # Fresh values replace the stale view
    assert "fa-check-circle" in live["iconClass"] and "text-success" in live["badgeClass"]


# ── Story 10-1 (suite): SM2 last-event card ──────────────────────────────────


@pytest.mark.parametrize(
    ("label", "type_icon", "where", "status_icon", "color"),
    [
        ("Intrusion (zone 3) : En cours", "fa-user-secret", "zone 3", "fa-spinner fa-pulse", "text-warning"),
        ("Incendie (zone 1) : Confirmé par la centrale", "fa-fire", "zone 1", "fa-check-circle", "text-success"),
        ("Panique (zone 2) : Refusé par la centrale", "fa-bell", "zone 2", "fa-ban", "text-danger"),
        ("Armement (utilisateur 4) : Sans réponse de la centrale", "fa-lock", "utilisateur 4", "fa-times-circle", "text-danger"),
        ("Désarmement (utilisateur 4) : Non transmise — clé de chiffrement invalide", "fa-lock-open", "utilisateur 4", "fa-key", "text-danger"),
        ("Annulation (zone 3) : Confirmé par la centrale", "fa-undo", "zone 3", "fa-check-circle", "text-success"),
    ],
)
def test_sm2_event_card_parses_label(label: str, type_icon: str, where: str, status_icon: str, color: str) -> None:
    """The event_label is split into type pill, zone/user and a colored status line.

    - type icon and zone/user come from the part before ' : '
    - status icon and color come from the part after ' : '
    """
    r = _one({"actions": [{"type": "pushEvent", "value": label}]})
    # Head is shown for a real event
    assert r["eventHeadShown"] is True
    # Type pictogram
    assert type_icon in r["eventTypeIcon"]
    # Zone or user
    assert r["eventWhere"] == where
    # Status pictogram and color on both icon and text
    assert status_icon in r["eventStatusIcon"] and color in r["eventStatusIcon"]
    assert color in r["eventStatusTextClass"]
    # The side bar and the type ring carry the outcome color too (colored card)
    assert color in r["eventBar"] and color in r["eventTypeWrap"]


@pytest.mark.parametrize("label", ["Inactif", "Aucun événement depuis le démarrage"])
def test_sm2_idle_is_discreet(label: str) -> None:
    """An idle / unparseable event_label shows only a discreet raw line.

    - no type head, no status icon, no time
    """
    r = _one({"placeholders": {"event_label": label}})
    # Nothing to pill
    assert r["eventHeadShown"] is False and r["eventStatusIconShown"] is False
    # The raw text stays readable, without a time
    assert r["eventStatusText"] == label and r["eventTime"] == ""


@pytest.mark.parametrize(
    ("seconds_ago", "expected"),
    [
        (10, "à l'instant"),
        (5 * 60, "il y a 5 min"),
    ],
)
def test_sm2_recent_time_is_relative(seconds_ago: int, expected: str) -> None:
    """A recent event shows a relative time taken from the render-time collectDate.

    - under a minute: à l'instant; under an hour: il y a N min
    - the precise HH:MM:SS is appended
    """
    r = _one({
        "placeholders": {"event_label": "Intrusion (zone 3) : Confirmé par la centrale"},
        "now": _NOW_MS,
        "byId": {"staleSeconds": 0, "eventSeconds": seconds_ago},
    })
    # Relative text
    assert re.fullmatch(rf"· {expected} · \d{{2}}:\d{{2}}:\d{{2}}", r["eventTime"])


def test_sm2_older_times_are_absolute() -> None:
    """Events before today show hier HH:MM / JJ/MM HH:MM; the live push time wins.

    - yesterday: 'hier HH:MM'; three days ago: 'JJ/MM HH:MM'
    - a live push collectDate drives the time of the new event
    """
    label = "Intrusion (zone 3) : Confirmé par la centrale"
    common = {"placeholders": {"event_label": label}, "now": _NOW_MS}
    # One hour before local midnight: yesterday whatever the runner's timezone
    now = datetime.fromtimestamp(_NOW_MS / 1000)
    since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    yday = _one({**common, "byId": {"staleSeconds": 0, "eventSeconds": since_midnight + 3600}})
    # Previous calendar day, with the clock time
    assert yday["eventTime"].startswith("· hier ")
    old = _one({**common, "byId": {"staleSeconds": 0, "eventSeconds": 3 * 86400}})
    # Date and hour, no relative wording
    assert re.fullmatch(r"· \d{2}/\d{2} \d{2}:\d{2}:\d{2}", old["eventTime"])
    live = _one({**common, "byId": {"staleSeconds": 0, "eventSeconds": 3 * 86400},
                 "actions": [{"type": "pushEvent", "value": label, "secondsAgo": 120}]})
    # The push collectDate replaces the render-time one
    assert re.fullmatch(r"· il y a 2 min · \d{2}:\d{2}:\d{2}", live["eventTime"])


def test_sm1_shows_last_supervision_update_time() -> None:
    """SM1 shows when supervision_state was last updated (frame or RP ACK).

    - render time: relative + precise time from the byId collectDate
    - a live state push replaces it with the push collectDate
    - yesterday-or-older shows the absolute date with seconds
    """
    base = {"now": _NOW_MS, "byId": {"staleSeconds": 120}}
    r = _one(base)
    # Within the 180 s stale threshold: relative text plus HH:MM:SS
    assert re.fullmatch(r"il y a 2 min · \d{2}:\d{2}:\d{2}", r["healthTime"])
    live = _one({**base, "actions": [{"type": "pushState", "value": "2", "secondsAgo": 5}]})
    # The RP/supervision ACK push collectDate wins
    assert re.fullmatch(r"à l'instant · \d{2}:\d{2}:\d{2}", live["healthTime"])
    old = _one({"now": _NOW_MS, "byId": {"staleSeconds": 3 * 86400}})
    # Stale and old: absolute date with seconds
    assert re.fullmatch(r"\d{2}/\d{2} \d{2}:\d{2}:\d{2}", old["healthTime"])


def test_widget_poll_action_exists_and_is_not_admin_only() -> None:
    """The widget's date poll targets an endpoint that exists and serves any connected user.

    - the template posts action getWidgetDates to the plugin ajax file
    - the ajax file handles it before the admin-only gate
    """
    tpl = _DASHBOARD_TPL.read_text(encoding="utf-8")
    ajax = (_PROJECT_ROOT / "core" / "ajax" / "siaDC09.ajax.php").read_text(encoding="utf-8")
    # Same action name on both sides
    assert "action: 'getWidgetDates'" in tpl and "init('action') == 'getWidgetDates'" in ajax
    # Handled before the admin gate, with its own connected-user check
    assert ajax.index("'getWidgetDates'") < ajax.index("isConnect('admin')")
