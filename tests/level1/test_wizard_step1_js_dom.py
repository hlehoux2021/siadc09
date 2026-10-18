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
    assert (out["locked"], out["readonlyInputs"]) == (0, 0)


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
