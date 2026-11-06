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
    # Assert: locked fields are visibly dimmed
    assert out["dimmed"] == 4


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
    assert (out["locked"], out["readonlyInputs"], out["dimmed"]) == (0, 0, 0)


@pytest.mark.parametrize("fields, expected_ok, advanced_open", [
    ({}, True, False),                                                       # defaults
    ({"supervision_format": "none"}, False, True),                           # none + RP off
    ({"supervision_format": "none", "rp_enabled": True, "rp_interval": "60"}, True, False),
    ({"rp_enabled": True, "rp_interval": "59"}, False, True),                # below minimum
    ({"rp_enabled": True, "rp_interval": "86401"}, False, True),             # above maximum
    ({"rp_enabled": True, "rp_interval": ""}, False, True),                  # not a number
    ({"rp_enabled": False, "rp_interval": "5"}, True, False),                # unused interval
])
def test_validate_step1_periodic_frame_rules(
    fields: dict[str, Any], expected_ok: bool, advanced_open: bool,
) -> None:
    """
    Step 1 validation applies the periodic-frame rules of siaDC09::periodicFrameConfigError().

    Expected result:
    - format none needs RP on; RP on needs an interval in [60, 86400]
    - a refusal opens "Options avancées" and fills the error box
    """
    out = _run({"fields": {**_VALID_CONNECTION, **fields}, "actions": [{"op": "validate"}]})

    # Assert: verdict
    assert out["validate"] == [expected_ok]
    # Assert: advanced options opened exactly when a periodic-frame rule failed
    assert out["advancedVisible"] is advanced_open
    # Assert: error box filled only on refusal
    assert bool(out["errors"]) is (not expected_ok)


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


def test_profile_change_fills_fields_and_opens_advanced() -> None:
    """
    Picking a profile in the selector (change event) applies it and unfolds the advanced block.

    Expected result:
    - preset values in the fields, fields locked, "Options avancées" visible
    - back to Personnalisé unlocks and keeps the values
    """
    out = _run({"profiles": _PROFILES, "actions": [
        {"op": "trigger", "selector": _SEL_PROFILE, "value": "ajax"},
    ]})

    # Assert: filled, locked, unfolded
    assert out["fields"]["rp_interval"] == "90"
    assert out["locked"] == 4
    assert out["advancedVisible"] is True

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


@pytest.mark.parametrize("value, visible", [("null", True), ("sia-dcs", False), ("none", False)])
def test_null_format_warning_follows_format_select(value: str, visible: bool) -> None:
    """The NULL-format warning is shown only while the format select is on null."""
    out = _run({"actions": [{"op": "trigger", "selector": _SEL_FORMAT, "value": value}]})

    # Assert: warning visibility
    assert out["nullWarningVisible"] is visible


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
    - 4 periodic fields + 5 media content fields locked
    """
    out = _run({"profiles": {"p": {"supervision_format": "sia-dcs", "supervision_interval": 30,
                                   "rp_enabled": 1, "rp_interval": 120, **_FULL_ON}},
                "actions": [{"op": "apply", "profile": "p", "fill": True}]})

    # Assert: box checked, not greyed
    assert out["media"]["media_enabled"] is True
    assert out["mediaBox"] == {"greyed": False, "ariaDisabled": False}
    # Assert: address field shown
    assert out["mediaUrlVisible"] is True
    # Assert: nine profile fields locked
    assert out["locked"] == 9


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
