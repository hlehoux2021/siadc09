---
title: '18.12 - Wizard step 2: single test button and results'
type: 'feature'
ticket: '12'
created: '2026-11-10'
status: done
baseline_revision: 'a18f619d37ee6d81a9bba7c1507cffd86d669ef3'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/EXPERIENCE.md'
  - '{project-root}/_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/DESIGN.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Step 2 still starts the SIA test by itself on arrival, shows one result, and lets Ignorer and Suivant coexist; the approved mockup (screens C, C1, C2, H) wants no automatic test, one button for every test, one result zone per test, and one right-hand slot (E18-R1, E18-R6).

**Approach:** Arriving on step 2 runs nothing and shows two zones at "Pas encore testé.". One button "Lancer le test" / "Relancer le test" validates the advanced options, saves the form, then runs the SIA test and, under FTPS, the FTPS test. The right-hand slot is "Suivant" only when every test passed, otherwise "Ignorer". Editing a setting clears the results. A stub `testFtps` action answers "unavailable" until 18.7.

## Boundaries & Constraints

**Always:** Texts are the French wording of EXPERIENCE.md. A disabled button looks disabled (`siaDC09_setButtonEnabled`). Suivant and Ignorer are never visible together. Step 3 shows one warning per test not passed ("Connexion non testée" / "Test échoué", "Serveur FTPS non testé" / "Test du serveur FTPS échoué", each followed by "le plugin ne pourra peut-être pas transmettre d'alarmes ni déposer la photo ou la vidéo."). After a NAK Suivant keeps its confirmation dialog. "Modifier la centrale" stays live in every state and abandons a running test (run token). The FTPS password is never sent to the browser result nor logged. The trust action only fills `ftps_cert_fingerprint` (and selects "auto-signé"), shows "Empreinte enregistrée. Relancez le test." and starts no test. The `testFtps` result contract is `{status: ok|untrusted|changed|error|unavailable, step?, detail, fingerprint?}`; the stub returns `unavailable`. Decision (user, 2026-11-10): `unavailable` counts as not passed, so under FTPS only Ignorer shows and step 3 warns "Serveur FTPS non testé" until 18.7 lands.

**Never:** The real FTPS connection code, the daemon, `testConnection` internals (18.7 and earlier work). Any change to step 1, the FTPS card or its validation (18.11). Writing the result zones inside the advanced panel.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Arrival | Any transport | Nothing runs; SIA zone "Pas encore testé."; FTPS zone only under FTPS (incomplete: "Réglages à compléter dans les options avancées ci-dessous."); buttons "Lancer le test" + "Ignorer" | None |
| Transport adresse, ACK | Press the button | One zone, SIA success; right slot becomes Suivant | None |
| FTPS, both pass | Press the button | SIA then FTPS run; both zones green; Suivant | None |
| One test fails | SIA or FTPS fails | Failure in its zone; test button "Relancer le test"; Ignorer | Step-named failure (C2) |
| Self-signed, no fingerprint | testFtps `untrusted` | "Certificat non reconnu", fingerprint, "Le mot de passe n'a pas été envoyé.", trust button; Ignorer | `changed` gives "Le certificat a changé" |
| Invalid options | Missing FTPS field or bad RP interval | Nothing runs; errors under fields and banner "Impossible de lancer le test :" | Existing messages |
| Edit after a test | Any setting changed | Zones back to "Pas encore testé.", slot back to Ignorer, button "Relancer le test" | None |
| Ignorer | Any state | Step 3 with the warning of each test not passed | None |
| Back while running | "Modifier la centrale" | Run abandoned, late answers ignored | None |

</frozen-after-approval>

## Code Map

- `desktop/php/siaDC09.php:243-254,384-392` -- step 2 spinner/result block and buttons: replace with two zones (`siaDC09-step2-sia`, `siaDC09-step2-ftps`), a hint line, one test button (keep id `bt_step2Retest`), `bt_step2Skip` and `bt_step2Next` as the single right-hand slot (toggled by display); `:399-401` step 3 warning: one line per test
- `desktop/js/siaDC09.js:116-132` -- `siaDC09_showStep(2)`: drop `siaDC09_runConnectionTest()`, call a new reset (zones, buttons); `:804-877` `siaDC09_runConnectionTest`: becomes the SIA part, reused; `:777-802` `siaDC09_renderStep2Failure`: reuse for the SIA zone
- `desktop/js/siaDC09.js:890-945` -- `bt_step2Retest` (validate, save, run): run SIA then FTPS; `bt_step2Skip`, `bt_step2Next` (NAK dialog kept), `siaDC09_advanceToStep3`; run token `_siaDC09_testRun` (:773) and `bt_step2Back` (:881)
- `desktop/js/siaDC09.js:587-602` -- `siaDC09_validateAdvanced` is reused untouched; `:518` `.siaDC09-media-field` change handler: add the clear-results handler on step 2 fields
- `core/ajax/siaDC09.ajax.php:54` -- add action `testFtps` after `testConnection`: stub returning `status: unavailable`; no `ftps_password` read
- `core/i18n/fr_FR.json` -- new strings; `internal-docs/design/wizard-design.md:179-247` -- Auto-trigger and Button behavior sections rewritten
- Do not change: `siaDC09_ftpsConfigErrors`, the FTPS card markup, `testConnection` internals, the daemon
- Tests: `tests/fixtures/js_wizard_flow_harness.js` (markup :59-72, buttons :159, snapshot :195), `tests/level1/test_wizard_step1_flow_js_dom.py` (:234-401 step 2 flow), `test_wizard_php_structure.py` (:182-212,391), `test_wizard_js_logic.py` (:124-243 asserts auto-trigger), `tests/render/render_wizard.py`, `test_i18n_roundtrip.py`

## Tasks & Acceptance

**Execution:**
- [ ] `desktop/php/siaDC09.php` -- two result zones, single test button, one right-hand slot, per-test step 3 warnings -- screens C, H
- [ ] `desktop/js/siaDC09.js` -- no auto-run; test orchestration SIA then FTPS; slot and button state machine; clear-on-edit; trust action; per-test warnings -- matrix
- [ ] `core/ajax/siaDC09.ajax.php` -- stub `testFtps` -- contract for 18.7
- [ ] `core/i18n/fr_FR.json` -- new strings -- round trip
- [ ] `tests/` -- rewrite the auto-trigger and button tests; one test per matrix row on the DOM harness; PHP stub test -- proves the matrix
- [ ] `internal-docs/design/wizard-design.md` -- Step 2 sections and `testFtps` contract -- spec stays current

**Acceptance Criteria:**
- Given test-jeedom, when step 2 opens, then nothing runs and the zones read "Pas encore testé.".
- Given the single button pressed, when every test passed, then only Suivant shows; otherwise only Ignorer shows.
- Given the approved mockup, when step 2 is rendered in Dark and Light, then it matches screens C, C1, C2, H and the user checks the render.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Pass 1 (quick): 0 high, 0 medium, 2 low, 4 false/none, 1 maybe-false.

| Verdict | Route | Finding and evidence |
|---|---|---|
| low | rejected | Ignorer after a SIA NAK shows no SIA warning. EXPERIENCE.md lists four warning labels and none for NAK; the centrale did answer. A fix needs new wording. |
| false | rejected | Stale step 3 warning: `siaDC09_advanceToStep3` hides it and a failed save never reaches the warnings; the reviewer found no bug. |
| maybe-false | rejected | The clear-on-edit handler could abandon a running test on a programmatic `change`. `siaDC09_updateFtpsCard` and the radio handler run on step 1 or on a user action, not during a run; low at worst. |
| low | rejected | The trust action also clears a passed SIA result. A fingerprint is a setting and EXPERIENCE.md clears results on any setting change. |
| false | rejected | `testFtps` stub placement: after `isConnect('admin')` and `ajax::init()`, no password read. |
| false | rejected | i18n duplicate key: `test_i18n_roundtrip.py` passes. |
| low | patch | `siaDC09-fingerprint-box` has no CSS, while DESIGN.md asks for monospace, grey `#e9ecef`, selectable. Added to `desktop/css/siaDC09.css`. |

## Design Notes

The trust action sets the fingerprint field, which fires the clear-results handler; show its message after the clear. `testFtps` receives no password from the browser: 18.7 reads the saved config server-side, so the form is saved before every test, as for `testConnection`.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the baseline (5 level2)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom: nothing runs on arrival, one button runs the tests, Suivant and Ignorer never show together, Dark and Light render against the mockup.
