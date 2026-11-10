"""
Level 1 DOM flow tests for the wizard step 1 buttons (Story 17.9).

Loads the whole desktop/js/siaDC09.js in jsdom with scripted Jeedom core stubs and asserts on
the ordered call log and on DOM snapshots (buttons, banner, field marks).
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HARNESS = _PROJECT_ROOT / "tests" / "fixtures" / "js_wizard_flow_harness.js"
_NODE_MODULES = _PROJECT_ROOT / "node_modules" / "jsdom"

pytestmark = pytest.mark.skipif(not _NODE_MODULES.exists(), reason="jsdom not installed")

_VALID_FIELDS: dict[str, Any] = {
    "account_number": "001234", "csr_ip": "192.168.1.1", "csr_port": "10002",
    "supervision_format": "sia-dcs",
}
_NEXT = {"op": "click", "selector": "#bt_step1Next"}
_RESTART = {"op": "click", "selector": "#bt_restartWizard"}
_SNAP = {"op": "snapshot"}


def _run(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario through the flow harness and return its output."""
    result = subprocess.run(
        ["node", str(_HARNESS), json.dumps(scenario)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, f"Harness error:\n{result.stderr}"
    return json.loads(result.stdout)


def test_relaunch_then_suivant_saves_again() -> None:
    """
    B1: Suivant -> save OK -> step 2 -> Relancer -> Suivant.

    Expected result:
    - the wizard is back on step 1 with Suivant enabled
    - the second click saves again (step 2 written a second time)
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "nok",
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _RESTART, _SNAP, _NEXT]})

    snap = out["snapshots"][0]
    # Assert: back on step 1 with a live Suivant
    assert snap["step"] == 1
    assert snap["buttons"]["bt_step1Next"]["disabledClass"] is False
    # Assert: two saves of step 2 happened, the relaunch saved step 0 between them
    assert [c for c in out["calls"] if c.startswith("save:")] == ["save:2", "save:0", "save:2"]


def test_several_errors_banner_marks_every_field() -> None:
    """
    Bad account, empty IP, media on with an empty Frigate address.

    Expected result:
    - banner titled « Impossible de continuer : » lists 3 messages, role alert kept
    - three fields marked with aria-describedby on their message
    - focus on the account field, the advanced panel (Test step) untouched, nothing saved
    """
    out = _run({"fields": {"account_number": "zz", "csr_ip": "", "csr_port": "10002",
                           "media_enabled": True, "media_snapshot_enabled": True,
                           "frigate_media_url_template": ""},
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: banner title and three items
    assert snap["bannerVisible"] is True
    # (the harness does not run Jeedom's {{...}} translation, so the markers stay)
    assert snap["bannerTitle"] == "{{Impossible de continuer :}}"
    assert len(snap["bannerItems"]) == 3
    # Assert: three faulty fields with described-by messages
    assert set(snap["fieldErrors"]) == {"account_number", "csr_ip", "frigate_media_url_template"}
    assert snap["fieldErrors"]["account_number"]["describedBy"] == "siaDC09-error-account_number"
    assert all(v["message"] for v in snap["fieldErrors"].values())
    # Assert: focus on the first faulty field, the advanced panel lives on step 2 and stays folded
    assert snap["focused"] == "account_number"
    assert snap["advancedVisible"] is False
    # Assert: no save, no daemon probe
    assert not any(c.startswith(("save:", "getDeamonInfo")) for c in out["calls"])


def test_errors_cleared_after_fix() -> None:
    """
    A second click after fixing the fields clears the banner and marks.

    Expected result:
    - no banner, no help-block after the corrected click
    """
    out = _run({"fields": {**_VALID_FIELDS, "account_number": "zz"}, "daemon": "nok",
                "actions": [{"op": "showStep", "step": 1}, _NEXT,
                            {"op": "fields", "fields": {"account_number": "001234"}}, _NEXT, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: marks removed
    assert snap["bannerVisible"] is False
    assert snap["helpBlocks"] == 0
    assert snap["fieldErrors"] == {}


def test_daemon_running_confirm_saves_then_stops() -> None:
    """
    Daemon running, user confirms.

    Expected result:
    - order: probe, confirm, save step 2, stop; no connection test on arrival (story 18.12)
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok", "test": "pending",
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    # Assert: save precedes the stop
    assert out["calls"] == ["getDeamonInfo:siaDC09", "confirm", "save:2", "deamonStop:siaDC09"]
    # Assert: step 2 shown
    assert out["snapshots"][0]["step"] == 2


def test_daemon_running_cancel_saves_nothing() -> None:
    """
    Daemon running, user cancels.

    Expected result:
    - no save, no stop; stays on step 1 with Suivant enabled
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok", "confirm": [False],
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: only probe and confirm happened
    assert out["calls"] == ["getDeamonInfo:siaDC09", "confirm"]
    # Assert: button live, still step 1
    assert snap["step"] == 1
    assert snap["buttons"]["bt_step1Next"]["disabledClass"] is False


def test_save_error_does_not_stop_daemon() -> None:
    """
    Daemon running, user confirms, save fails.

    Expected result:
    - no deamonStop call, an alert is shown, Suivant re-enabled, still step 1
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok", "save": ["error"],
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: no stop
    assert "deamonStop:siaDC09" not in out["calls"]
    # Assert: alert displayed
    assert "alert:save failed" in out["calls"]
    # Assert: button live, step 1
    assert snap["step"] == 1
    assert snap["buttons"]["bt_step1Next"]["disabledClass"] is False


def test_stop_error_reenables_and_stays_on_step_1() -> None:
    """
    Daemon running, confirm, save OK, stop fails.

    Expected result:
    - alert shown, Suivant re-enabled, no move to step 2
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok", "stop": "error",
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: alert displayed and no connection test
    assert "alert:stop failed" in out["calls"]
    assert "ajax:testConnection" not in out["calls"]
    # Assert: step 1, live button
    assert snap["step"] == 1
    assert snap["buttons"]["bt_step1Next"]["disabledClass"] is False


def test_probe_failure_proceeds_as_not_running() -> None:
    """
    getDeamonInfo errors.

    Expected result:
    - no dialog, no stop, save then step 2
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "error",
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _SNAP]})

    # Assert: no confirm and no stop
    assert "confirm" not in out["calls"]
    assert "deamonStop:siaDC09" not in out["calls"]
    # Assert: saved and advanced
    assert "save:2" in out["calls"]
    assert out["snapshots"][0]["step"] == 2


def test_restart_confirm_stops_after_saving_step_zero() -> None:
    """
    « Relancer l'assistant » with a running daemon, confirmed.

    Expected result:
    - order: probe, confirm, save step 0, stop; step 1 shown, restart button live
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok",
                "actions": [_RESTART, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: save before stop
    assert out["calls"] == ["getDeamonInfo:siaDC09", "confirm", "save:0", "deamonStop:siaDC09"]
    # Assert: step 1 displayed, buttons live
    assert snap["step"] == 1
    assert snap["buttons"]["bt_restartWizard"]["disabledClass"] is False


def test_restart_cancel_reenables_button() -> None:
    """
    « Relancer l'assistant », user cancels.

    Expected result:
    - nothing saved or stopped, the button is live again
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "ok", "confirm": [False],
                "actions": [_RESTART, _SNAP]})

    # Assert: no save, no stop
    assert out["calls"] == ["getDeamonInfo:siaDC09", "confirm"]
    # Assert: button live
    assert out["snapshots"][0]["buttons"]["bt_restartWizard"]["disabledClass"] is False


_RETEST = {"op": "click", "selector": "#bt_step2Retest"}


@pytest.mark.parametrize("button_id", ["bt_step2Retest", "bt_step2Skip", "bt_step2Next"])
def test_step2_buttons_look_disabled_while_testing(button_id: str) -> None:
    """
    While the connection test runs (no answer yet, started by the single button), every step 2
    button looks disabled.

    Expected result:
    - class disabled, aria-disabled true, tabindex -1
    """
    out = _run({"fields": _VALID_FIELDS, "test": "pending",
                "actions": [{"op": "showStep", "step": 2}, _RETEST, _SNAP]})

    btn = out["snapshots"][0]["buttons"][button_id]
    # Assert: real disabled look and out of tab order
    assert btn["disabledClass"] is True
    assert btn["ariaDisabled"] == "true"
    assert btn["tabindex"] == "-1"


_BACK = {"op": "click", "selector": "#bt_step2Back"}
_DUH_EXTRA = {"outcome": "duh", "sent": {"type": "SIA-DCS", "account": "001234", "transport": "UDP"}}


def test_modifier_la_centrale_during_test_ignores_late_answer() -> None:
    """
    Story 17.12: Modifier la centrale while the test runs, then the answer arrives late.

    Expected result:
    - step 1 shown with every value kept and a live Suivant
    - the back button was live while testing
    - the late answer renders nothing and enables no step 2 button
    - nothing was saved by the back click
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "nok", "test": "pending",
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _RETEST, _SNAP, _BACK, _SNAP,
                            {"op": "answer", "status": "ok"}, _SNAP]})

    testing, back, late = out["snapshots"]
    # Assert: back live while the test runs
    assert testing["step"] == 2 and testing["buttons"]["bt_step2Back"]["disabledClass"] is False
    assert "Test en cours" in testing["step2ResultText"] and testing["testLabel"].startswith("{{Test en cours")
    # Assert: step 1 with values kept and Suivant live
    assert back["step"] == 1
    assert back["buttons"]["bt_step1Next"]["disabledClass"] is False
    assert back["fieldValues"] == {"csr_ip": "192.168.1.1", "account_number": "001234"}
    # Assert: the late answer is ignored
    assert late["step"] == 1 and late["step2ResultText"] == back["step2ResultText"]
    assert late["nextVisible"] is False
    # Assert: the step 1 save and the test's save happened, the back click saved nothing
    assert [c for c in out["calls"] if c.startswith("save:")] == ["save:2", "save:2"]


def test_duh_view_shows_sent_message_and_two_checks_then_back_works() -> None:
    """
    Story 17.12: a DUH answer, then Modifier la centrale.

    Expected result:
    - the view shows the DUH sentence, the sent message and exactly two checks
    - no profile name, no NULL / Personnalisé advice
    - Modifier, Relancer and Ignorer live, Suivant hidden
    - back to step 1 with a live Suivant, which saves again
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "nok", "test": "fail", "testExtra": _DUH_EXTRA,
                "actions": [{"op": "showStep", "step": 1}, _NEXT, _RETEST, _SNAP, _BACK, _SNAP, _NEXT]})

    duh, back = out["snapshots"]
    text = duh["step2ResultText"]
    # Assert: sentence, sent message, checks
    assert "(DUH)" in text and "SIA-DCS" in text and "001234" in text
    assert duh["step2ChecksCount"] == 2
    # Assert: forbidden advice absent
    assert "NULL" not in text and "Personnalisé" not in text and "FoxStream" not in text
    # Assert: button states of the failure view
    b = duh["buttons"]
    assert [b[k]["disabledClass"] for k in ("bt_step2Back", "bt_step2Retest", "bt_step2Skip")] == [False] * 3
    assert duh["nextVisible"] is False and duh["skipVisible"] is True
    # Assert: step 1 is live again and saves again
    assert back["step"] == 1 and back["buttons"]["bt_step1Next"]["disabledClass"] is False
    assert [c for c in out["calls"] if c.startswith("save:")] == ["save:2", "save:2", "save:2"]


def test_non_duh_failure_still_shows_sent_message() -> None:
    """
    Story 17.12: a timeout failure keeps its text and shows the message sent.

    Expected result:
    - the detail text and the sent summary are shown, no DUH checks
    """
    out = _run({"fields": _VALID_FIELDS, "daemon": "nok", "test": "fail",
                "testExtra": {"detail": "Pas de réponse", "sent": _DUH_EXTRA["sent"]},
                "actions": [{"op": "showStep", "step": 2}, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: detail and sent summary, no checks list
    assert "Pas de réponse" in snap["step2ResultText"] and "SIA-DCS" in snap["step2ResultText"]
    assert snap["step2ChecksCount"] == 0


# ── Story 17.14: three steps, advanced options on the Test step ──────────────

_FOX = {"label": "FoxStream (FoxBox)", "supervision_format": "sia-dcs", "supervision_interval": 30,
        "rp_enabled": 1, "rp_interval": 120}
_GO_CUSTOM = {"op": "click", "selector": "#bt_siaDC09_goCustom"}
_FINISH = {"op": "click", "selector": "#bt_step3Finish"}


def test_stepper_follows_the_step_shown() -> None:
    """
    The read-only stepper highlights the step being shown.

    Expected result:
    - active tab 1, 2, 3 after showStep(1), showStep(2), showStep(3)
    """
    out = _run({"fields": _VALID_FIELDS, "test": "pending",
                "actions": [{"op": "showStep", "step": 1}, _SNAP, {"op": "showStep", "step": 2}, _SNAP,
                            {"op": "showStep", "step": 3}, _SNAP]})

    # Assert: one active tab per step
    assert [s["activeTab"] for s in out["snapshots"]] == ["1", "2", "3"]


def test_switch_to_custom_from_failed_test_does_not_rerun_the_test() -> None:
    """
    Story 17.14 (user decision): after a refused test, « Passer en Personnalisé » unlocks the
    panel but never starts a new test; only « Relancer le test » does, after saving.

    Expected result:
    - the profile select reads Personnalisé and the caption is hidden after the switch
    - exactly one testConnection call (the first) and only that test's save before « Relancer le test »
    - « Relancer le test » then saves (step 2) BEFORE the second testConnection
    """
    out = _run({"fields": {**_VALID_FIELDS, "csr_profile": "fox"}, "profiles": {"fox": _FOX},
                "daemon": "nok", "test": "fail", "testExtra": _DUH_EXTRA,
                "actions": [{"op": "showStep", "step": 2}, _RETEST, {"op": "fields", "fields": {"csr_profile": "fox"}},
                            _GO_CUSTOM, _SNAP, {"op": "mark", "label": "retest"}, _RETEST]})

    snap = out["snapshots"][0] if out["snapshots"] else {}
    calls = out["calls"]
    # Assert: no second test and no save before the explicit retest
    before = calls[:calls.index("--retest")]
    assert before.count("ajax:testConnection") == 1
    assert [c for c in before if c.startswith("save:")] == ["save:2"]
    # Assert: retest = save, then the test
    after = calls[calls.index("--retest") + 1:]
    assert after[:2] == ["save:2", "ajax:testConnection"]
    assert snap.get("captionVisible") is False


def test_retest_with_invalid_advanced_options_saves_and_tests_nothing() -> None:
    """
    Personnalisé with supervision none and RP off, then « Relancer le test ».

    Expected result:
    - the step 2 error box shows, the panel opens, no save and no second test
    """
    out = _run({"fields": {**_VALID_FIELDS, "supervision_format": "sia-dcs"}, "daemon": "nok", "test": "fail",
                "testExtra": _DUH_EXTRA,
                "actions": [{"op": "showStep", "step": 2},
                            {"op": "fields", "fields": {"supervision_format": "none", "rp_enabled": False}},
                            {"op": "mark", "label": "retest"}, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    after = out["calls"][out["calls"].index("--retest") + 1:]
    # Assert: refused before any save or ajax
    assert after == []
    # Assert: errors shown, panel open, Relancer live again
    assert snap["step2ErrorsVisible"] is True and snap["advancedVisible"] is True
    assert snap["buttons"]["bt_step2Retest"]["disabledClass"] is False


def test_terminer_writes_the_done_step_and_has_no_step_four() -> None:
    """
    « Terminer » on the merged step 3.

    Expected result:
    - the wizard step is saved as 4 ("complete"), after the notification target was checked
    - an unusable target refuses and saves nothing
    """
    refused = _run({"fields": _VALID_FIELDS, "actions": [{"op": "showStep", "step": 3}, _FINISH]})
    # Assert: no target chosen -> no save
    assert not any(c.startswith("save:") for c in refused["calls"])

    ok = _run({"fields": {**_VALID_FIELDS, "sia_notify_cmd_id": "12"}, "actions": [{"op": "showStep", "step": 3}, _FINISH]})
    # Assert: saved as 4
    assert [c for c in ok["calls"] if c.startswith("save:")] == ["save:4"]


# ── Story 18.12: single test button, one result zone per test ────────────────

_FTPS_FIELDS: dict[str, Any] = {
    **_VALID_FIELDS, "media_enabled": True, "media_transport": "ftps", "ftps_host": "ftp.exemple.fr",
    "ftps_port": "21", "ftps_user": "alarme", "ftps_password": "secret",
}
_STEP2 = {"op": "showStep", "step": 2}
_SKIP = {"op": "click", "selector": "#bt_step2Skip"}
_NEXT2 = {"op": "click", "selector": "#bt_step2Next"}
_TRUST = {"op": "click", "selector": ".siaDC09-ftps-trust"}
_FINGERPRINT = "AB" * 32


def _calls(out: dict[str, Any], prefix: str) -> list[str]:
    """Calls of the log starting with a prefix."""
    return [c for c in out["calls"] if c.startswith(prefix)]


def test_arrival_runs_nothing_and_shows_two_untested_zones_under_ftps() -> None:
    """
    Matrix row 'Arrival' (FTPS, complete settings).

    Expected result:
    - no ajax call, no save
    - both zones read "Pas encore testé."; the FTPS zone is visible
    - test button "Lancer le test", right-hand slot is Ignorer, Suivant hidden
    """
    out = _run({"fields": _FTPS_FIELDS, "actions": [_STEP2, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: nothing ran
    assert _calls(out, "ajax:") == [] and _calls(out, "save:") == []
    # Assert: two untested zones
    assert "Pas encore testé." in snap["step2ResultText"] and "Pas encore testé." in snap["ftpsText"]
    assert snap["ftpsZoneVisible"] is True
    # Assert: buttons
    assert snap["testLabel"] == "{{Lancer le test}}"
    assert snap["skipVisible"] is True and snap["nextVisible"] is False


def test_arrival_with_address_transport_has_one_zone_and_incomplete_ftps_message() -> None:
    """
    Matrix row 'Arrival': address transport shows only the SIA zone; incomplete FTPS settings
    show "Réglages à compléter..." in the FTPS zone and open the advanced panel.

    Expected result:
    - address: FTPS zone hidden
    - FTPS without host: message in the FTPS zone, panel open
    """
    address = _run({"fields": _VALID_FIELDS, "actions": [_STEP2, _SNAP]})
    incomplete = _run({"fields": {**_FTPS_FIELDS, "ftps_host": ""}, "actions": [_STEP2, _SNAP]})

    # Assert: one zone under the address way
    assert address["snapshots"][0]["ftpsZoneVisible"] is False
    # Assert: incomplete settings message and open panel
    assert "Réglages à compléter" in incomplete["snapshots"][0]["ftpsText"]
    assert incomplete["snapshots"][0]["advancedVisible"] is True


def test_address_transport_ack_gives_suivant_only() -> None:
    """
    Matrix row 'Transport adresse, ACK'.

    Expected result:
    - one testConnection, no testFtps; Suivant visible, Ignorer hidden; label "Relancer le test"
    """
    out = _run({"fields": _VALID_FIELDS, "test": "ok", "actions": [_STEP2, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: only the SIA test ran
    assert _calls(out, "ajax:") == ["ajax:testConnection"]
    # Assert: the right-hand slot is Suivant alone
    assert snap["nextVisible"] is True and snap["skipVisible"] is False
    assert snap["buttons"]["bt_step2Next"]["disabledClass"] is False
    assert snap["testLabel"] == "{{Relancer le test}}"


def test_ftps_both_pass_runs_sia_then_ftps_and_gives_suivant() -> None:
    """
    Matrix row 'FTPS, both pass'.

    Expected result:
    - save, then testConnection, then testFtps; Suivant alone; the FTPS zone shows success
    """
    out = _run({"fields": _FTPS_FIELDS, "test": "ok", "ftps": "ok", "actions": [_STEP2, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: order of the calls
    assert [c for c in out["calls"] if c.startswith(("save:", "ajax:"))] == ["save:2", "ajax:testConnection", "ajax:testFtps"]
    # Assert: both green, Suivant alone
    assert "Serveur FTPS joignable" in snap["ftpsText"]
    assert snap["nextVisible"] is True and snap["skipVisible"] is False


@pytest.mark.parametrize("sia,ftps", [("fail", "ok"), ("ok", "fail"), ("ok", "unavailable")])
def test_one_failing_test_gives_ignorer_and_relancer(sia: str, ftps: str) -> None:
    """
    Matrix row 'One test fails' (and 'unavailable counts as not passed').

    Expected result:
    - both tests ran; Ignorer alone; label "Relancer le test"
    """
    out = _run({"fields": _FTPS_FIELDS, "test": sia, "ftps": ftps,
                "ftpsExtra": {"step": "connexion", "detail": "refusée"} if ftps == "fail" else {},
                "actions": [_STEP2, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: the FTPS test ran even after a SIA failure
    assert _calls(out, "ajax:") == ["ajax:testConnection", "ajax:testFtps"]
    # Assert: Ignorer alone
    assert snap["skipVisible"] is True and snap["nextVisible"] is False
    assert snap["testLabel"] == "{{Relancer le test}}"
    if ftps == "fail":
        # Assert: the failure names its step
        assert "connexion" in snap["ftpsText"] and "Échec à l'étape" in snap["ftpsText"]


def test_untrusted_certificate_then_trust_fills_fingerprint_without_testing() -> None:
    """
    Matrix row 'Self-signed, no fingerprint' and the trust action.

    Expected result:
    - zone shows "Certificat non reconnu", the fingerprint and "Le mot de passe n'a pas été envoyé."; Ignorer alone
    - the trust button fills ftps_cert_fingerprint, shows "Empreinte enregistrée. Relancez le test."
    - no second testFtps call, no password in any request
    """
    out = _run({"fields": _FTPS_FIELDS, "test": "ok", "ftps": "untrusted", "ftpsExtra": {"fingerprint": _FINGERPRINT},
                "actions": [_STEP2, _RETEST, _SNAP, _TRUST, _SNAP]})

    refused, trusted = out["snapshots"]
    # Assert: refusal view
    assert "Certificat non reconnu" in refused["ftpsText"] and _FINGERPRINT in refused["ftpsText"]
    assert "Le mot de passe n'a pas été envoyé." in refused["ftpsText"]
    assert refused["skipVisible"] is True and refused["nextVisible"] is False
    # Assert: fingerprint stored, message shown, results cleared
    assert trusted["fingerprintField"] == _FINGERPRINT
    assert "Empreinte enregistrée. Relancez le test." in trusted["ftpsText"]
    assert trusted["testLabel"] == "{{Relancer le test}}" and trusted["skipVisible"] is True
    # Assert: nothing relaunched
    assert _calls(out, "ajax:") == ["ajax:testConnection", "ajax:testFtps"]


def test_changed_certificate_says_so() -> None:
    """
    Matrix row 'changed'.

    Expected result:
    - "Le certificat a changé" with the trust button, Ignorer alone
    """
    out = _run({"fields": _FTPS_FIELDS, "test": "ok", "ftps": "changed", "ftpsExtra": {"fingerprint": _FINGERPRINT},
                "actions": [_STEP2, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: changed wording and Ignorer
    assert "Le certificat a changé" in snap["ftpsText"] and "PAS été envoyé" in snap["ftpsText"]
    assert snap["skipVisible"] is True


def test_invalid_ftps_options_run_nothing_and_name_the_error() -> None:
    """
    Matrix row 'Invalid options': FTPS without password.

    Expected result:
    - no save, no ajax; the step 2 error banner shows; the panel is open
    """
    out = _run({"fields": {**_FTPS_FIELDS, "ftps_password": ""}, "test": "ok",
                "actions": [_STEP2, _RETEST, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: nothing ran
    assert _calls(out, "ajax:") == [] and _calls(out, "save:") == []
    # Assert: errors visible
    assert snap["step2ErrorsVisible"] is True and snap["advancedVisible"] is True


def test_editing_a_setting_clears_the_results() -> None:
    """
    Matrix row 'Edit after a test': after a full success, a change of the user.

    Expected result:
    - zones back to "Pas encore testé.", slot back to Ignorer, label "Relancer le test"
    """
    out = _run({"fields": _FTPS_FIELDS, "test": "ok", "ftps": "ok",
                "actions": [_STEP2, _RETEST, _SNAP, {"op": "edit", "fields": {"ftps_user": "autre"}}, _SNAP]})

    done, edited = out["snapshots"]
    # Assert: passed before the edit
    assert done["nextVisible"] is True
    # Assert: cleared after
    assert "Pas encore testé." in edited["step2ResultText"] and "Pas encore testé." in edited["ftpsText"]
    assert edited["skipVisible"] is True and edited["nextVisible"] is False
    assert edited["testLabel"] == "{{Relancer le test}}"


@pytest.mark.parametrize("actions,sia_warn,ftps_warn", [
    ([_STEP2, _SKIP, {"op": "showStep", "step": 3}], "Connexion non testée", "Serveur FTPS non testé"),
    ([_STEP2, _RETEST, _SKIP], "Test échoué", "Serveur FTPS non testé"),
])
def test_ignorer_gives_one_warning_per_test_not_passed(actions: list[dict[str, Any]], sia_warn: str, ftps_warn: str) -> None:
    """
    Matrix row 'Ignorer': step 3 warns for each test not passed.

    Expected result:
    - never tested: both "non testé" lines
    - SIA failed and FTPS unavailable: "Test échoué" and "Serveur FTPS non testé"
    - each line ends with the plugin consequence
    """
    out = _run({"fields": _FTPS_FIELDS, "test": "fail", "ftps": "unavailable", "actions": actions + [_SNAP]})

    snap = out["snapshots"][0]
    # Assert: step 3 with the two lines
    assert snap["step"] == 3
    assert sia_warn in snap["warnSia"] and ftps_warn in snap["warnFtps"]
    assert "ne pourra peut-être pas transmettre d'alarmes" in snap["warnFtps"]


def test_ignorer_with_address_transport_warns_only_for_the_centrale() -> None:
    """
    Ignorer under the address way.

    Expected result:
    - the SIA line only, no FTPS line
    """
    out = _run({"fields": _VALID_FIELDS, "actions": [_STEP2, _SKIP, _SNAP]})

    snap = out["snapshots"][0]
    # Assert: one line
    assert "Connexion non testée" in snap["warnSia"] and snap["warnFtps"] is None


def test_nak_keeps_the_confirmation_dialog_on_suivant() -> None:
    """
    After a NAK, Suivant is shown and still asks for confirmation.

    Expected result:
    - Suivant visible; one confirm; step 3 reached on confirmation
    """
    out = _run({"fields": _VALID_FIELDS, "test": "nak", "confirm": [True],
                "actions": [_STEP2, _RETEST, _SNAP, _NEXT2, _SNAP]})

    first, last = out["snapshots"]
    # Assert: Suivant shown after the NAK
    assert first["nextVisible"] is True
    # Assert: dialog asked, step 3 reached
    assert _calls(out, "confirm") == ["confirm"] and last["step"] == 3
