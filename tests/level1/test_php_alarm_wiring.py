"""Story 13.5 — buildAlarmWiring() matrix, run with the php CLI on the extracted methods.

The three pure static methods are lifted from core/class/siaDC09.class.php into a stub
class, so the test runs the real code with lists in and lists out.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.level1.test_php_eqlogic_stub import _extract_method_body

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PHP_CLASS_FILE = _PROJECT_ROOT / "core/class/siaDC09.class.php"
_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"

_requires_php = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

# siaDC09 command ids (own), Alarm foreign ids.
_OWN = [10, 11, 12, 13, 14, 15]
_IDS = {"arm": 10, "disarm": 11, "alarmReset": 12, "burglarAlarm": 13, "prefetchEvent": 14}


def _run(hooks: dict, zones: list, camera_zones: list, media: bool = True, link: bool = True) -> dict:
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    entry = _extract_method_body(source, "_alarmEntry")
    drop = _extract_method_body(source, "_dropOwnEntries")
    build = _extract_method_body(source, "buildAlarmWiring")
    program = (
        "<?php class W {"
        f" static function _alarmEntry(int $cmdId, string $title): array {{{entry}}}"
        f" static function _dropOwnEntries(mixed $list, array $ownCmdIds): array {{{drop}}}"
        " static function buildAlarmWiring(array $hooks, array $zones, array $ownCmdIds,"
        " array $logicalCmdIds, array $cameraZones, bool $mediaEnabled, bool $link = true): array"
        f" {{{build}}} }}"
        f" echo json_encode(W::buildAlarmWiring(json_decode('{json.dumps(hooks)}', true),"
        f" json_decode('{json.dumps(zones)}', true), {json.dumps(_OWN)},"
        f" json_decode('{json.dumps(_IDS)}', true), json_decode('{json.dumps(camera_zones)}', true),"
        f" {'true' if media else 'false'}, {'true' if link else 'false'}));"
    )
    out = subprocess.run(["php", "-r", program[len("<?php "):]], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _e(cmd: int, title: str = "") -> dict:
    return {"cmd": f"#{cmd}#", "onMode": "all",
            "options": {"enable": 1, "background": 0, "title": title, "message": ""}}


_FOREIGN = {"cmd": "#999#", "onMode": "all", "options": {"enable": 1}}


@_requires_php
def test_link_three_zones() -> None:
    """
    Matrix row "Link": an Alarm equipment with 3 zones, 2 of them with a camera.

    Expected result:
    - the three hooks each get our command
    - every zone gets « Alarme intrusion » with title #zone#
    - only camera zones get the prefetch entry (case/space insensitive)
    """
    zones = [{"name": n} for n in ("Salon", "Cuisine", "Garage")]
    res = _run({}, zones, ["Salon", "garage "])
    # Assert: arm, disarm and reset hooks carry exactly our entry
    assert res["hooks"]["activationImmediateOk"] == [_e(10)]
    assert res["hooks"]["release"] == [_e(11)]
    assert res["hooks"]["raz"] == [_e(12)]
    # Assert: every zone has the intrusion action with #zone#
    for z in res["zones"]:
        assert z["actions"] == [_e(13, "#zone#")]
    # Assert: prefetch only on the two camera zones
    assert [z["actionsImmediate"] for z in res["zones"]] == [[_e(14, "#zone#")], [], [_e(14, "#zone#")]]


@_requires_php
def test_relink_is_idempotent_and_refreshes_zones() -> None:
    """
    Matrix row "Re-link": a zone is added after a first link.

    Expected result:
    - linking again produces identical hooks and existing zones (no duplicate)
    - the new zone gets its entries
    """
    zones = [{"name": "Salon"}, {"name": "Cuisine"}]
    first = _run({}, zones, ["Salon"])
    zones2 = first["zones"] + [{"name": "Garage"}]
    again = _run(first["hooks"], zones2, ["Salon", "Garage"])
    # Assert: hooks unchanged on re-link
    assert again["hooks"] == first["hooks"]
    # Assert: an existing zone is unchanged, not duplicated
    assert again["zones"][0] == first["zones"][0]
    # Assert: the new zone is wired
    assert again["zones"][2]["actions"] == [_e(13, "#zone#")]
    assert again["zones"][2]["actionsImmediate"] == [_e(14, "#zone#")]


@_requires_php
def test_hand_wiring_is_replaced_not_duplicated() -> None:
    """
    Matrix row "Hand wiring": the installer already pasted our commands.

    Expected result:
    - each pasted entry of ours is replaced by the canonical one, once
    """
    hooks = {"release": [{"cmd": "#11#", "onMode": "all", "options": {"title": "manual"}}]}
    zones = [{"name": "Salon", "actions": [{"cmd": "#13#"}], "actionsImmediate": [{"cmd": "#14#"}]}]
    res = _run(hooks, zones, ["Salon"])
    # Assert: the hand-pasted hook entry is replaced, not doubled
    assert res["hooks"]["release"] == [_e(11)]
    # Assert: the hand-pasted zone entries are replaced, not doubled
    assert res["zones"][0]["actions"] == [_e(13, "#zone#")]
    assert res["zones"][0]["actionsImmediate"] == [_e(14, "#zone#")]


@_requires_php
def test_foreign_entries_untouched_same_order() -> None:
    """
    Matrix row "Foreign entry": lists hold entries of other commands.

    Expected result:
    - foreign entries stay, in the same relative order, ours go last
    - other zone keys are preserved
    """
    hooks = {"raz": [_FOREIGN, _e(12), {"cmd": "#998#"}]}
    zones = [{"name": "Salon", "actions": [_FOREIGN], "actionsImmediate": [_FOREIGN], "other": 1}]
    res = _run(hooks, zones, [])
    # Assert: foreign hook entries keep their order, ours is re-appended
    assert res["hooks"]["raz"] == [_FOREIGN, {"cmd": "#998#"}, _e(12)]
    # Assert: foreign zone entries are kept in front of ours
    assert res["zones"][0]["actions"] == [_FOREIGN, _e(13, "#zone#")]
    assert res["zones"][0]["actionsImmediate"] == [_FOREIGN]
    # Assert: unrelated zone keys survive
    assert res["zones"][0]["other"] == 1


@_requires_php
def test_prefetch_off_when_media_disabled() -> None:
    """
    Boundary: media_enabled off.

    Expected result:
    - no prefetch entry even for a camera zone
    - the intrusion action is still written
    """
    res = _run({}, [{"name": "Salon"}], ["Salon"], media=False)
    # Assert: prefetch absent when media is disabled
    assert res["zones"][0]["actionsImmediate"] == []
    # Assert: intrusion action unaffected
    assert res["zones"][0]["actions"] == [_e(13, "#zone#")]


@_requires_php
def test_unlink_removes_only_our_entries() -> None:
    """
    Matrix row "Unlink": a linked equipment with a foreign entry.

    Expected result:
    - only siaDC09 entries disappear, foreign ones remain
    """
    hooks = {"activationImmediateOk": [_e(10), _FOREIGN], "release": [_e(11)], "raz": [_e(12)]}
    zones = [{"name": "Salon", "actions": [_FOREIGN, _e(13, "#zone#")], "actionsImmediate": [_e(14, "#zone#")]}]
    res = _run(hooks, zones, ["Salon"], link=False)
    # Assert: hooks keep only the foreign entry
    assert res["hooks"] == {"activationImmediateOk": [_FOREIGN], "release": [], "raz": []}
    # Assert: zone lists keep only foreign entries
    assert res["zones"][0]["actions"] == [_FOREIGN]
    assert res["zones"][0]["actionsImmediate"] == []


@_requires_php
def test_only_the_five_hooks_are_returned() -> None:
    """
    Boundary: the Alarm equipment has other hooks (activationOk).

    Expected result:
    - the result only holds activationImmediateOk, release and raz
    """
    res = _run({"activationOk": [_FOREIGN]}, [], [])
    # Assert: no other hook is written
    assert set(res["hooks"]) == {"activationImmediateOk", "release", "raz"}


def test_ajax_validates_alarm_id_server_side() -> None:
    """
    Matrix row "Bad id": the Alarm id is checked on the server.

    Expected result:
    - both ajax actions exist and use getAlarmEquipment()
    - getAlarmEquipment() requires eqType 'alarm'
    """
    src = _AJAX_FILE.read_text(encoding="utf-8")
    # Assert: both actions are declared
    assert "'linkAlarm'" in src and "'unlinkAlarm'" in src
    # Assert: the id goes through the server-side validator
    assert "getAlarmEquipment" in src
    cls = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    # Assert: the validator checks the equipment type
    assert "getEqType_name() !== 'alarm'" in cls
