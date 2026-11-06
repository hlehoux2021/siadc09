"""
Level 1 DOM tests for the wizard step 1 profile choice and validation (Story 17.4).

Executes siaDC09_applyProfile() and siaDC09_validateStep1() from desktop/js/siaDC09.js in
a jsdom+jQuery environment and asserts on the resulting DOM, not on keyword presence.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HARNESS = _PROJECT_ROOT / "tests" / "fixtures" / "js_wizard_step1_harness.js"
_NODE_MODULES = _PROJECT_ROOT / "node_modules" / "jsdom"

pytestmark = pytest.mark.skipif(not _NODE_MODULES.exists(), reason="jsdom not installed")

_PROFILES = {
    "scutum": {"supervision_format": "none", "rp_enabled": 1, "rp_interval": 60},
    "ajax": {"supervision_format": "none", "rp_enabled": 1, "rp_interval": 90},
}
_VALID_CONNECTION = {"account_number": "001234", "csr_ip": "192.168.1.1", "csr_port": "10002"}


def _run(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario through the jsdom harness and return its output."""
    result = subprocess.run(
        ["node", str(_HARNESS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, f"Harness error:\n{result.stderr}"
    return json.loads(result.stdout)


def test_apply_profile_fills_and_locks_fields() -> None:
    """
    Choosing a profile copies its values into the fields and locks them.

    Expected result:
    - format none, RP on, interval 90 written to the fields
    - the four profile fields carry the lock class; the number inputs are readonly
    """
    out = _run({"profiles": _PROFILES,
                "actions": [{"op": "apply", "profile": "ajax", "fill": True}]})

    # Assert: preset values copied
    assert out["fields"] == {"supervision_format": "none", "supervision_interval": "",
                             "rp_interval": "90", "rp_enabled": True}
    # Assert: all four profile fields locked, number inputs readonly
    assert out["locked"] == 4
    assert out["readonlyInputs"] == 2
    # Assert: locked fields get the grey look from the stylesheet (class), not an inline opacity
    assert out["greyed"] == 4
    assert out["opacityDimmed"] == 0


@pytest.mark.parametrize("fmt", ["U", "V"])
def test_apply_media_profile_fills_media_options(fmt: str) -> None:
    """
    A profile carrying media keys (17.8) fills the media options (locked since 17.10).

    Expected result:
    - snapshot and clip on, both formats = fmt, one tag on, URL field shown
    """
    profile = {"supervision_format": "sia-dcs", "supervision_interval": 30,
               "rp_enabled": 1, "rp_interval": 120, "media_enabled": 1,
               "media_snapshot_enabled": 1, "media_clip_enabled": 1,
               "media_snapshot_format": fmt, "media_clip_format": fmt, "media_single_tag": 1}
    out = _run({"profiles": {"p": profile},
                "actions": [{"op": "apply", "profile": "p", "fill": True}]})

    # Assert: media options copied
    assert out["media"] == {"media_enabled": True, "media_snapshot_enabled": True,
                            "media_clip_enabled": True,
                            "media_snapshot_format": fmt, "media_clip_format": fmt,
                            "media_single_tag": True}
    # Assert: the Frigate field appears because the box is on
    assert out["mediaUrlVisible"] is True
    # Assert: periodic-frame values copied too
    assert out["fields"]["supervision_interval"] == "30"
    assert out["fields"]["rp_interval"] == "120"


def test_apply_profile_without_media_keys_leaves_media_options_alone() -> None:
    """
    Ajax/Scutum carry no media key: choosing them keeps the media options as they are.

    Expected result:
    - snapshot checkbox set by the user stays checked after applying a media-less profile
    """
    out = _run({"profiles": _PROFILES, "fields": {"media_snapshot_enabled": True},
                "actions": [{"op": "apply", "profile": "ajax", "fill": True}]})

    # Assert: untouched
    assert out["media"]["media_snapshot_enabled"] is True


def test_apply_profile_without_fill_keeps_saved_values_but_locks() -> None:
    """
    Reloading a saved equipment (fill=false) locks the fields without overwriting them.

    Expected result:
    - the saved rp_interval 300 survives
    - fields locked
    """
    out = _run({"profiles": _PROFILES, "fields": {"rp_interval": "300"},
                "actions": [{"op": "apply", "profile": "scutum", "fill": False}]})

    # Assert: saved value untouched
    assert out["fields"]["rp_interval"] == "300"
    # Assert: still locked
    assert out["locked"] == 4


def test_apply_empty_profile_unlocks_fields() -> None:
    """
    Choosing "Personnalisé" (empty profile) after a profile unlocks the fields.

    Expected result:
    - no locked field, no readonly input
    """
    out = _run({"profiles": _PROFILES, "actions": [
        {"op": "apply", "profile": "ajax", "fill": True},
        {"op": "apply", "profile": "", "fill": True},
    ]})

    # Assert: everything editable again
    assert (out["locked"], out["greyed"], out["readonlyInputs"]) == (0, 0, 0)


@pytest.mark.parametrize("fields, expected_ok, advanced_open", [
    ({}, True, False),                                                       # defaults
    ({"supervision_format": "none"}, False, True),                           # none + RP off
    ({"supervision_format": "none", "rp_enabled": True, "rp_interval": "60"}, True, False),
    ({"rp_enabled": True, "rp_interval": "59"}, False, True),                # below minimum
    ({"rp_enabled": True, "rp_interval": "86401"}, False, True),             # above maximum
    ({"rp_enabled": True, "rp_interval": ""}, False, True),                  # not a number
    ({"rp_enabled": False, "rp_interval": "5"}, True, False),                # unused interval
])
def test_validate_advanced_periodic_frame_rules(
    fields: dict[str, Any], expected_ok: bool, advanced_open: bool,
) -> None:
    """
    Story 17.14: the periodic-frame rules of siaDC09::periodicFrameConfigError() run on the Test
    step (validateAdvanced, before every test), no longer on step 1.

    Expected result:
    - format none needs RP on; RP on needs an interval in [60, 86400]
    - a refusal opens "Options avancées" (bar reads « cliquer pour replier ») and fills the step 2 box
    - step 1 validation does not look at these rules any more
    """
    out = _run({"fields": {**_VALID_CONNECTION, **fields}, "actions": [{"op": "validateAdvanced"}]})

    # Assert: verdict
    assert out["validate"] == [expected_ok]
    # Assert: advanced options opened exactly when a periodic-frame rule failed
    assert out["advancedVisible"] is advanced_open
    assert (out["advancedBar"]["expanded"] == "true") is advanced_open
    # Assert: step 2 error box filled only on refusal; step 1 box untouched
    assert bool(out["step2Errors"]) is (not expected_ok)
    assert not out["errors"]

    step1 = _run({"fields": {**_VALID_CONNECTION, **fields}, "actions": [{"op": "validate"}]})
    # Assert: step 1 accepts a valid connection whatever the advanced values are
    assert step1["validate"] == [True]


_LABELS_PROFILES = {"scutum": {"label": "Scutum", "supervision_format": "none"}}


@pytest.mark.parametrize("cfg, expected", [
    # Legacy equipment: no new key -> daemon-side defaults
    ({}, [["Profil : ", "Personnalisé"], ["Supervision : ", "SIA-DCS toutes les 60 s"],
          ["Test cyclique (RP) : ", "désactivé"],
          ["Reconnexion : ", "6 tentatives de reconnexion"]]),
    # Scutum profile as stored by the wizard (checkbox as "1" string)
    ({"csr_profile": "scutum", "supervision_format": "none", "rp_enabled": "1",
      "rp_interval": "60", "retry_count": "4"},
     [["Profil : ", "Scutum"], ["Supervision : ", "aucune trame de supervision"],
      ["Test cyclique (RP) : ", "activé, toutes les 60 s"],
      ["Reconnexion : ", "4 tentatives de reconnexion"]]),
    # Custom NULL supervision; unchecked RP stored as "0" must read as off
    ({"supervision_format": "null", "supervision_interval": "120", "rp_enabled": "0",
      "rp_interval": "300"},
     [["Profil : ", "Personnalisé"], ["Supervision : ", "NULL toutes les 120 s"],
      ["Test cyclique (RP) : ", "désactivé"],
      ["Reconnexion : ", "6 tentatives de reconnexion"]]),
])
def test_periodic_summary_lines(cfg: dict[str, Any], expected: list[list[str]]) -> None:
    """
    The configuration summary names the profile, supervision frame, RP and reconnection.

    Expected result:
    - absent keys read as the daemon defaults (legacy equipment)
    - RP "0" string is off, "1" is on, with its own interval
    - supervision 'none' states there is no frame instead of an interval
    - an unknown/empty profile reads Personnalisé
    """
    out = _run({"profiles": _LABELS_PROFILES, "actions": [{"op": "summary", "cfg": cfg}]})

    # Assert: summary lines match the specification
    assert out["summaries"] == [expected]


_SEL_PROFILE = "#siaDC09-csr-profile"
_SEL_FORMAT = '.eqLogicAttr[data-l2key="supervision_format"]'


def test_print_eqlogic_legacy_equipment_opens_on_defaults_unlocked() -> None:
    """
    Equipment saved before 17-4 (no csr_profile, no new keys) opens on Personnalisé.

    Expected result:
    - selector empty, format sia-dcs, RP interval 60, RP off
    - nothing locked
    """
    out = _run({"profiles": _PROFILES, "actions": [
        {"op": "printEqLogic", "eqLogic": {"configuration": {"account_number": "001234"}}},
    ]})

    # Assert: daemon-side defaults, not the first <option>
    assert out["selectedProfile"] in ("", None)
    assert out["fields"]["supervision_format"] == "sia-dcs"
    assert out["fields"]["rp_interval"] == "60"
    assert out["fields"]["rp_enabled"] is False
    # Assert: unlocked
    assert (out["locked"], out["readonlyInputs"]) == (0, 0)


def test_print_eqlogic_saved_profile_keeps_saved_values_and_locks() -> None:
    """
    Reloading equipment saved with a profile restores the selector and locks, without refill.

    Expected result:
    - selector on scutum, saved rp_interval 300 not overwritten by the preset's 60
    - four fields locked
    """
    cfg = {"csr_profile": "scutum", "supervision_format": "none", "rp_enabled": "1",
           "rp_interval": "300"}
    out = _run({"profiles": _PROFILES, "actions": [
        {"op": "printEqLogic", "eqLogic": {"configuration": cfg}},
    ]})

    # Assert: selector restored, saved value kept
    assert out["selectedProfile"] == "scutum"
    assert out["fields"]["rp_interval"] == "300"
    # Assert: locked
    assert out["locked"] == 4


def test_profile_change_fills_fields_and_keeps_advanced_folded() -> None:
    """
    Picking a profile in the selector (change event) applies it; the advanced panel (Test step)
    never opens by itself on a profile change (story 17.14).

    Expected result:
    - preset values in the fields, fields locked, "Options avancées" still folded
    - back to Personnalisé unlocks and keeps the values
    """
    out = _run({"profiles": _PROFILES, "actions": [
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "ajax"},
    ]})

    # Assert: filled, locked, still folded
    assert out["fields"]["rp_interval"] == "90"
    assert out["locked"] == 4
    assert out["advancedVisible"] is False

    back = _run({"profiles": _PROFILES, "actions": [
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "ajax"},
        {"op": "trigger", "selector": _SEL_PROFILE, "value": ""},
    ]})

    # Assert: unlocked, values kept
    assert back["locked"] == 0
    assert back["fields"]["rp_interval"] == "90"


@pytest.mark.parametrize("rp_enabled", [0, "0"])
def test_profile_with_rp_off_unchecks_rp(rp_enabled: Any) -> None:
    """A preset with rp_enabled 0 or "0" must switch RP off, whatever it was before."""
    profiles = {"quiet": {"supervision_format": "sia-dcs", "rp_enabled": rp_enabled}}
    out = _run({"profiles": profiles, "fields": {"rp_enabled": True},
                "actions": [{"op": "apply", "profile": "quiet", "fill": True}]})

    # Assert: RP off
    assert out["fields"]["rp_enabled"] is False


def test_profile_with_supervision_interval_copies_it() -> None:
    """A preset carrying supervision_interval writes it into the field."""
    profiles = {"p": {"supervision_format": "sia-dcs", "supervision_interval": 120}}
    out = _run({"profiles": profiles,
                "actions": [{"op": "apply", "profile": "p", "fill": True}]})

    # Assert: interval copied
    assert out["fields"]["supervision_interval"] == "120"


def test_null_format_warning_is_gone() -> None:
    """
    Story 17.11: the orange NULL warning no longer exists in the page nor in the script.

    Expected result:
    - no #siaDC09-null-warning in the PHP view, no updateNullWarning in the JS
    """
    php = (_PROJECT_ROOT / "desktop" / "php" / "siaDC09.php").read_text(encoding="utf-8")
    js = (_PROJECT_ROOT / "desktop" / "js" / "siaDC09.js").read_text(encoding="utf-8")

    # Assert: element and handler removed
    assert "siaDC09-null-warning" not in php
    assert "NullWarning" not in js and "siaDC09-null-warning" not in js


# ── Story 17.11: advanced panel (captions, extension choice) ──────────────────

_URL_SNAPSHOT = "https://monsite/..../snapshot.jpg"
_URL_CLIP = "https://monsite/..../clip.mp4"


@pytest.mark.parametrize("fmt", ["U", "V"])
def test_extension_examples_match_format_media_tags_bytes(fmt: str) -> None:
    """
    The examples shown next to the extension choice are the bytes _format_media_tags builds.

    Expected result:
    - single-extension example == _format_media_tags(..., single_tag=True), space between URLs
    - per-link example == _format_media_tags(..., single_tag=False)
    - the choice is enabled (photo and clip sent, same format)
    """
    from resources.siadc09d.sia_protocol import SIAMessageBuilder

    entries = [{"format": fmt, "url": _URL_SNAPSHOT}, {"format": fmt, "url": _URL_CLIP}]
    fields = {"media_snapshot_enabled": True, "media_clip_enabled": True, "media_single_tag": True,
              "media_snapshot_format": fmt, "media_clip_format": fmt}
    out = _run({"fields": fields, "actions": [_media_trigger("media_clip_format", value=fmt)]})

    # Assert: examples equal the real tag bytes
    assert out["extChoice"]["exampleSingle"] == SIAMessageBuilder._format_media_tags(entries, True)
    assert out["extChoice"]["exampleMulti"] == SIAMessageBuilder._format_media_tags(entries, False)
    # Assert: available, with the saved single-tag value reflected by the radios
    assert out["extChoice"]["disabled"] is False
    assert (out["extChoice"]["single"], out["extChoice"]["multi"]) == (True, False)
    assert out["extChoice"]["reasonVisible"] is False


@pytest.mark.parametrize("fields", [
    {"media_snapshot_enabled": False, "media_clip_enabled": True,
     "media_snapshot_format": "V", "media_clip_format": "V"},   # single content
    {"media_snapshot_enabled": True, "media_clip_enabled": False,
     "media_snapshot_format": "V", "media_clip_format": "V"},   # single content
    {"media_snapshot_enabled": True, "media_clip_enabled": True,
     "media_snapshot_format": "U", "media_clip_format": "V"},   # mixed formats
])
def test_extension_choice_greyed_with_reason(fields: dict[str, Any]) -> None:
    """
    The choice stays visible but greyed, nothing selected, with its reason.

    Expected result:
    - visible, radios disabled and unchecked, reason shown
    """
    out = _run({"fields": {**fields, "media_single_tag": True},
                "actions": [_media_trigger("media_clip_format", value=fields["media_clip_format"])]})

    # Assert: visible yet unavailable
    assert out["extChoice"]["visible"] is True
    assert out["extChoice"]["disabled"] is True
    # Assert: nothing selected
    assert (out["extChoice"]["single"], out["extChoice"]["multi"]) == (False, False)
    # Assert: the reason is displayed
    assert out["extChoice"]["reasonVisible"] is True


def test_extension_radio_drives_saved_single_tag_key() -> None:
    """
    In Personnalisé, picking « une extension par lien » clears media_single_tag.

    Expected result:
    - checkbox unchecked, second radio selected
    """
    fields = {"media_snapshot_enabled": True, "media_clip_enabled": True, "media_single_tag": True,
              "media_snapshot_format": "V", "media_clip_format": "V"}
    out = _run({"fields": fields, "actions": [
        _media_trigger("media_clip_format", value="V"),
        {"op": "trigger", "selector": '.siaDC09-ext-radio[value="0"]', "checked": True}]})

    # Assert: the saved key follows the radio
    assert out["singleTagChecked"] is False
    assert (out["extChoice"]["single"], out["extChoice"]["multi"]) == (False, True)


def test_locked_checkboxes_and_radios_refuse_a_click() -> None:
    """
    A profile-locked checkbox or radio keeps its value when clicked (also through its label).

    Expected result:
    - clicking a locked checkbox leaves it unchanged
    - clicking a locked radio leaves the saved choice unchanged
    - after Personnalisé the same checkbox toggles again
    """
    profile = {"label": "FoxStream (FoxBox)", "supervision_format": "sia-dcs", "supervision_interval": 30,
               "rp_enabled": 1, "rp_interval": 120, **_FULL_ON}
    locked = _run({"profiles": {"fox": profile}, "actions": [
        {"op": "apply", "profile": "fox", "fill": True},
        {"op": "click", "selector": '.eqLogicAttr[data-l2key="rp_enabled"]'},
        {"op": "click", "selector": '.eqLogicAttr[data-l2key="media_clip_enabled"]'}]})
    # Assert: both checkboxes kept the value the profile set
    assert locked["fields"]["rp_enabled"] is True
    assert locked["media"]["media_clip_enabled"] is True

    custom = _run({"profiles": {"fox": profile}, "actions": [
        {"op": "apply", "profile": "fox", "fill": True}, {"op": "apply", "profile": "", "fill": True},
        {"op": "click", "selector": '.eqLogicAttr[data-l2key="rp_enabled"]'}]})
    # Assert: unlocked, the click toggles it
    assert custom["fields"]["rp_enabled"] is False


def test_profile_locks_with_caption_and_exposes_state() -> None:
    """
    A profile locks every panel field, readable, with ONE caption for the whole panel.

    Expected result:
    - every locked field is readonly or aria-disabled
    - the single caption names the profile; Personnalisé hides it and unlocks
    """
    profile = {"label": "FoxStream (FoxBox)", "supervision_format": "sia-dcs", "supervision_interval": 30,
               "rp_enabled": 1, "rp_interval": 120, **_FULL_ON}
    out = _run({"profiles": {"fox": profile}, "actions": [{"op": "apply", "profile": "fox", "fill": True}]})
    expected = "{{Fixé par le profil}} « FoxStream (FoxBox) ». {{Choisissez « Personnalisé » pour le modifier.}}"

    # Assert: locked fields expose their state
    assert out["locked"] == 11
    assert out["lockedUnexposed"] == 0
    # Assert: one caption for the whole panel
    assert out["caption"] == expected

    custom = _run({"profiles": {"fox": profile}, "actions": [
        {"op": "apply", "profile": "fox", "fill": True}, {"op": "apply", "profile": "", "fill": True}]})
    # Assert: Personnalisé unlocks and hides the captions
    assert custom["locked"] == 0
    assert custom["caption"] is None


def test_folding_the_advanced_panel_loses_no_value() -> None:
    """
    Folding then unfolding the panel changes no value (story 17.11).

    Expected result:
    - panel closed after two clicks on the toggle, every field value identical to the start
    """
    fields = {"supervision_format": "null", "supervision_interval": "45", "rp_interval": "300",
              "media_snapshot_enabled": True, "media_clip_enabled": True, "media_single_tag": False,
              "media_snapshot_format": "U", "media_clip_format": "U"}
    toggle = {"op": "trigger", "selector": "#bt_siaDC09_toggleAdvanced"}
    start = _run({"fields": fields, "actions": []})
    out = _run({"fields": fields, "actions": [toggle, toggle]})

    # Assert: folded again, nothing lost
    assert out["advancedVisible"] is False
    assert out["fields"] == start["fields"]
    assert out["media"] == start["media"]


def test_ajax_locks_supervision_only_keeping_content_editable() -> None:
    """
    Decision 2026-11-06: a profile without media keys keeps the content fields editable.

    Expected result:
    - 4 supervision fields locked; the single caption shown
    """
    out = _run({"profiles": {"ajax": {**_AJAX, "label": "Ajax"}},
                "actions": [{"op": "apply", "profile": "ajax", "fill": True}]})

    # Assert: only the supervision card is locked
    assert out["locked"] == 4
    assert out["lockedUnexposed"] == 0
    # Assert: the one caption is shown because something is locked
    assert out["caption"] is not None


def test_go_custom_from_the_test_step_behaves_like_step_1_and_changes_no_preset() -> None:
    """
    « Passer en Personnalisé » on the Test step (story 17.14, user decision).

    Expected result:
    - the profile select reads Personnalisé, fields unlock, values kept, caption hidden
    - no preset object is modified (the same profile can be chosen again and refills)
    - the panel state is untouched (no auto-open) and nothing started a test (no ajax in the harness)
    """
    profile = {"label": "FoxStream (FoxBox)", "supervision_format": "sia-dcs", "supervision_interval": 30,
               "rp_enabled": 1, "rp_interval": 120, **_FULL_ON}
    out = _run({"profiles": {"fox": profile}, "actions": [
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "fox"},
        {"op": "click", "selector": "#bt_siaDC09_goCustom"},
    ]})

    # Assert: same end state as choosing Personnalisé on step 1
    assert out["selectedProfile"] in ("", None)
    assert out["locked"] == 0 and out["greyed"] == 0 and out["caption"] is None
    # Assert: values kept (preset values were filled by the first step)
    assert out["fields"]["supervision_interval"] == "30"
    assert out["fields"]["rp_interval"] == "120"
    # Assert: the preset is intact: choosing the profile again refills and locks
    again = _run({"profiles": {"fox": profile}, "actions": [
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "fox"},
        {"op": "click", "selector": "#bt_siaDC09_goCustom"},
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "fox"},
    ]})
    assert again["locked"] == 11 and again["fields"]["rp_interval"] == "120"


# ── Story 17.7: alarm media options ───────────────────────────────────────────


def _media_trigger(key: str, **kwargs: Any) -> dict[str, Any]:
    return {"op": "trigger", "selector": f'.eqLogicAttr[data-l2key="{key}"]', **kwargs}


def test_media_url_field_follows_media_box() -> None:
    """
    The Frigate address shows only when the photo/video box is checked (17.10).

    Expected result:
    - hidden with the box off, shown when it is checked
    """
    out_off = _run({"fields": {"media_enabled": True},
                    "actions": [_media_trigger("media_enabled", checked=False)]})
    out_on = _run({"fields": {"media_enabled": False},
                   "actions": [_media_trigger("media_enabled", checked=True)]})

    # Assert: hidden with the box off
    assert out_off["mediaUrlVisible"] is False
    # Assert: shown with the box on
    assert out_on["mediaUrlVisible"] is True


def test_single_tag_disabled_and_unchecked_for_mixed_formats() -> None:
    """
    One tag holds one format only.

    Expected result:
    - both media on, U and V: checkbox unchecked and disabled
    - same formats: enabled again
    """
    fields = {"media_snapshot_enabled": True, "media_clip_enabled": True, "media_single_tag": True,
              "media_snapshot_format": "V", "media_clip_format": "V"}
    mixed = _run({"fields": fields, "actions": [_media_trigger("media_snapshot_format", value="U")]})
    same = _run({"fields": fields, "actions": [_media_trigger("media_snapshot_format", value="V")]})

    # Assert: mixed formats force the option off
    assert (mixed["singleTagDisabled"], mixed["singleTagChecked"]) == (True, False)
    # Assert: equal formats leave it available
    assert same["singleTagDisabled"] is False


def test_media_config_error_on_empty_url() -> None:
    """
    Step 1 and step 3 Next are refused when the box is checked and the address empty (17.10).

    Expected result:
    - error with the box on and no address; none with an address or with the box off
    """
    on = {"media_enabled": True}
    out = _run({"fields": on, "actions": [{"op": "mediaError"}]})
    out_url = _run({"fields": {**on, "frigate_media_url_template": "https://h/"},
                    "actions": [{"op": "mediaError"}]})
    out_off = _run({"fields": {"media_enabled": False}, "actions": [{"op": "mediaError"}]})

    # Assert: error shown for an empty address
    assert out["mediaErrors"][0] != ""
    # Assert: no error once the address is set
    assert out_url["mediaErrors"] == [""]
    # Assert: no error with the box off
    assert out_off["mediaErrors"] == [""]


# ── Story 17.10: photo / video verification card and locked media keys ────────

_FULL_ON = {"media_enabled": 1, "media_snapshot_enabled": 1, "media_clip_enabled": 1,
            "media_snapshot_format": "U", "media_clip_format": "U", "media_single_tag": 1}
_SCUTUM = {"supervision_format": "none", "rp_enabled": 1, "rp_interval": 60,
           "media_enabled": 0, "media_snapshot_enabled": 0, "media_clip_enabled": 1,
           "media_snapshot_format": "V", "media_clip_format": "V", "media_single_tag": 1}
_AJAX = {"supervision_format": "none", "rp_enabled": 1, "rp_interval": 60}


def test_media_profile_locks_content_keys_and_checks_box() -> None:
    """
    A profile with media keys locks the five content keys and checks the box (not locked).

    Expected result:
    - box checked and available; Frigate address field shown
    - 4 periodic fields + 5 media content fields + the 2 extension radios locked
    """
    out = _run({"profiles": {"p": {"supervision_format": "sia-dcs", "supervision_interval": 30,
                                   "rp_enabled": 1, "rp_interval": 120, **_FULL_ON}},
                "actions": [{"op": "apply", "profile": "p", "fill": True}]})

    # Assert: box checked, not greyed
    assert out["media"]["media_enabled"] is True
    assert out["mediaBox"] == {"greyed": False, "ariaDisabled": False}
    # Assert: address field shown
    assert out["mediaUrlVisible"] is True
    # Assert: four periodic + five content fields + two radios locked
    assert out["locked"] == 11


def test_scutum_locks_video_only_v_and_leaves_box_off() -> None:
    """
    Scutum: video only in V, box unchecked yet available.

    Expected result:
    - snapshot off, clip on, formats V; box off and not greyed; Frigate field hidden
    """
    out = _run({"profiles": {"scutum": _SCUTUM},
                "actions": [{"op": "apply", "profile": "scutum", "fill": True}]})

    # Assert: video only in V
    assert (out["media"]["media_snapshot_enabled"], out["media"]["media_clip_enabled"]) == (False, True)
    assert (out["media"]["media_snapshot_format"], out["media"]["media_clip_format"]) == ("V", "V")
    # Assert: the box is off but the user may check it
    assert out["media"]["media_enabled"] is False
    assert out["mediaBox"]["greyed"] is False
    assert out["mediaUrlVisible"] is False


def test_ajax_greys_box_unchecked_with_caption() -> None:
    """
    A profile declaring no media key greys the box, unchecked, with the explanatory caption.

    Expected result:
    - box unchecked even if it was checked, greyed, aria-disabled; caption shown
    """
    out = _run({"profiles": {"ajax": _AJAX}, "fields": {"media_enabled": True},
                "actions": [{"op": "apply", "profile": "ajax", "fill": True}]})

    # Assert: unchecked and greyed
    assert out["media"]["media_enabled"] is False
    assert out["mediaBox"] == {"greyed": True, "ariaDisabled": True}
    # Assert: caption visible
    assert out["nomediaVisible"] is True


def test_custom_profile_unlocks_media_and_box_after_ajax() -> None:
    """
    Personnalisé (empty profile) unlocks everything and makes the box available again.

    Expected result:
    - no locked field, box not greyed, caption hidden
    """
    out = _run({"profiles": {"ajax": _AJAX},
                "actions": [{"op": "apply", "profile": "ajax", "fill": True},
                            {"op": "apply", "profile": "", "fill": True}]})

    # Assert: nothing locked, box available
    assert out["locked"] == 0
    assert out["mediaBox"] == {"greyed": False, "ariaDisabled": False}
    assert out["nomediaVisible"] is False


def test_box_off_keeps_frigate_value_and_hides_field() -> None:
    """
    Unchecking the box hides the address field but keeps its value.

    Expected result:
    - field hidden, value kept, no media error
    """
    out = _run({"fields": {"media_enabled": True, "frigate_media_url_template": "https://f/"},
                "actions": [_media_trigger("media_enabled", checked=False), {"op": "mediaError"}]})

    # Assert: hidden
    assert out["mediaUrlVisible"] is False
    # Assert: value kept in the form
    assert out["frigateValue"] == "https://f/"
    # Assert: nothing to complain about
    assert out["mediaErrors"] == [""]


def test_validate_step1_refuses_empty_frigate_with_field_error() -> None:
    """
    Suivant is refused at step 1 with the box on and an empty address.

    Expected result:
    - validate false; banner lists the message; the field carries the error class
    """
    out = _run({"fields": {**_VALID_CONNECTION, "supervision_format": "sia-dcs", "media_enabled": True},
                "actions": [{"op": "validate"}]})

    # Assert: refused
    assert out["validate"] == [False]
    # Assert: banner message and field marked
    assert "Adresse du serveur Frigate" in out["errors"]
    assert out["frigateInvalid"] is True


def test_legacy_equipment_reads_box_on() -> None:
    """
    An equipment saved before 17.10 (no media_enabled) loads with the box on.

    Expected result:
    - box checked after printEqLogic
    """
    out = _run({"actions": [{"op": "printEqLogic", "eqLogic": {"configuration": {"csr_profile": ""}}}]})

    # Assert: absent key reads as on
    assert out["media"]["media_enabled"] is True
