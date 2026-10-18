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
