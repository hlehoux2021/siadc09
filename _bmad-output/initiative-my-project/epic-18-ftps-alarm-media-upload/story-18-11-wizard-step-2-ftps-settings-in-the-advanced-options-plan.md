---
title: '18.11 - Wizard step 2: FTPS settings in the advanced options'
type: 'feature'
ticket: '11'
created: '2026-11-09'
status: done
baseline_revision: '815b84ddd878811669cf24f29ec30372bd240dbb'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/EXPERIENCE.md'
  - '{project-root}/_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/DESIGN.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The FTPS settings sit in a provisional card on step 1, while the approved mockup puts every technical setting of a transport in the step 2 Options avancées (screens C, D2); the settings have no certificate choice and no validation (E18-R1).

**Approach:** Move the settings into a "Serveur FTPS" card inside the step 2 advanced panel, with the certificate radios (reconnu / auto-signé) and the fingerprint field, never profile-locked; open the panel by itself when they are incomplete; validate them where the advanced options are validated, with the banner "Impossible de lancer le test :"; check them again at "Terminer"; show the step 1 note and delete the provisional card. The test button, the result zones and Suivant/Ignorer are story 18.12.

## Boundaries & Constraints

**Always:** The card exists in the page only under the FTPS transport with the media box ticked. FTPS inputs never carry the `siaDC09-profile-field` class. No new config key: an empty fingerprint means "certificat reconnu", a filled one "auto-signé"; the radios only drive what is shown, and choosing "reconnu" empties the fingerprint at save. Port is pre-filled with 21 when empty. Existing `ftps_*` keys and their names are unchanged (daemon plumbing untouched). Texts are the French wording of EXPERIENCE.md.

**Never:** The test button, result zones, Suivant/Ignorer slot, "Faire confiance" action, the FTPS test action, the stub (all 18.12/18.7). Any change to the automatic test on arrival (18.12). A FTPS check at step 1 "Suivant".

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| FTPS, fresh | Transport FTPS, nothing typed, arrive on step 2 | Options avancées open by themselves, card shown, port 21, fingerprint field hidden | None |
| Transport adresse | Any | No FTPS card in the panel; step 1 shows the Frigate card as before | None |
| Incomplete settings | Server, user or password empty, test relaunched | Nothing runs; red fields and messages; banner "Impossible de lancer le test :" | "Serveur FTPS : obligatoire." and the two siblings |
| Bad port or fingerprint | Port 0 or 70000; fingerprint not 64 hex (separators allowed) | Refused | "Port : nombre entre 1 et 65535 requis" / "Empreinte SHA-256 : 64 caractères hexadécimaux requis" |
| Certificate choice | "Auto-signé" then "Reconnu" | Fingerprint field shown then hidden and emptied at save | None |
| Profile locks media | Personnalisé with FTPS | FTPS fields editable, never greyed | None |
| Terminer | FTPS chosen, settings incomplete | Refused on step 3 with the same messages | Same messages |
| Existing FTPS equipment | Saved by hand in 18.2/18.4 | Values appear in the new card, nothing lost | None |

</frozen-after-approval>

## Code Map

- `desktop/php/siaDC09.php:230-263` -- provisional card `#siaDC09-ftps-card` (fields `ftps_host`, `ftps_port`, `ftps_user`, `ftps_password`, `ftps_folder`, `ftps_cert_fingerprint`): remove from step 1 and rebuild inside `#siaDC09-advanced` (:294-371, before the supervision zone :333); add labels with `*`, the help texts, the certificate radios and the card title/subtitle of EXPERIENCE.md
- `desktop/php/siaDC09.php:226` -- `#siaDC09-media-ftps-note`: shown under FTPS
- `desktop/js/siaDC09.js:365-367` -- `siaDC09_updateMediaFields`: show the note and the new card (`ftps && enabled`), drop the old card toggle; `:123-126` `siaDC09_showStep(2)`: auto-open the panel via `siaDC09_setAdvancedOpen` (:217-225) when FTPS is incomplete
- `desktop/js/siaDC09.js:496-511,518-551` -- `siaDC09_validateAdvanced` (add FTPS rules under ftps + media) and `siaDC09_renderFieldErrors` (:545 hardcoded banner title: add a title parameter, step 2 passes "Impossible de lancer le test :")
- `desktop/js/siaDC09.js:407-425,1077` -- `siaDC09_mediaConfigErrors`/`siaDC09_mediaConfigError`: keep the Frigate/photo-video rules for step 1; add a separate FTPS completeness function shared by `validateAdvanced` and the Terminer net (:1077)
- `desktop/js/siaDC09.js:621-677` -- step 2 summary: "(à renseigner)" wording while incomplete
- Do not change: `siaDC09_runConnectionTest` and the step 2 buttons (18.12), `core/class/siaDC09*.php`, the daemon, the lock lists (FTPS inputs must stay out of them)
- Tests: `tests/level1/test_wizard_php_structure.py:627` (provisional card assertion, rewrite), `tests/fixtures/js_wizard_step1_harness.js:45-47,173-174` (card and note), `test_wizard_step1_js_dom.py`; imitate the flow harness for the panel/auto-open; `test_i18n_roundtrip.py` for new strings

## Tasks & Acceptance

**Execution:**
- [ ] `desktop/php/siaDC09.php` -- move the card into the advanced panel with certificate radios, labels, help; remove the provisional card -- mockup screens C, D2
- [ ] `desktop/js/siaDC09.js` -- show/hide, auto-open, validation, banner title, Terminer check, summary wording -- the matrix
- [ ] `core/i18n/fr_FR.json` -- new strings -- i18n round trip
- [ ] `tests/` -- rewrite the provisional-card tests; one test per matrix row on the DOM harness -- proves the matrix
- [ ] `internal-docs/design/wizard-design.md` -- the Serveur FTPS card in the advanced panel, the interim card gone -- spec stays current

**Acceptance Criteria:**
- Given the approved mockup, when step 2 is rendered with the FTPS transport in Dark and Light, then the advanced panel matches screen C and the user checks the render.
- Given FTPS chosen, when the settings are incomplete and the test is relaunched, then nothing runs and the errors are under the fields and in the banner "Impossible de lancer le test :".
- Given an equipment with FTPS saved before this story, when step 2 opens, then its values are in the new card.

## Implementation Notes

- Card moved to `#siaDC09-advanced` before the supervision zone; step 1 note now shown under FTPS; interim card deleted. Visibility is `siaDC09_updateFtpsCard()`, called from `siaDC09_updateMediaFields()`.
- Certificate radios: no new key. Radios are synced from the fingerprint field on load and on a field change; a radio change only shows/hides the field (guard flag so the radio's own change trigger does not snap it back); `saveEqLogic()` empties the fingerprint when "reconnu" is selected.
- Validation: `siaDC09_ftpsConfigErrors()` is joined into `siaDC09_validateAdvanced()` (banner "Impossible de lancer le test :", new title parameter on `siaDC09_renderFieldErrors`) and into the Terminer net via `siaDC09_finishConfigError()`. Fingerprint is only checked under "auto-signé" with a value (empty self-signed is the trust-on-first-use flow of 18.12). Port is checked as an integer 1..65535; an emptied port field is refused (it is pre-filled with 21 only when the card is shown).
- The banner title change also applies to the existing periodic-frame errors of step 2 (EXPERIENCE.md gives one title for the step 2 banner).
- Summary wording unchanged: "(à renseigner)" already shows while the host is empty; user/password are not part of the summary line (password must never appear).
- Not done (outside scope): obfuscated password placeholder (EXPERIENCE contract, 18.7/18.12), test button and zones.
- Tests: harness gets the card, `ftpsErrors`/`finishError`/`openIfIncomplete`/`save` ops; harness slice now extends to `// ===== WIZARD NAVIGATION =====` so `saveEqLogic` is loaded.

## Plan Change Log

## Review Triage Log

## Design Notes

Until 18.12 the automatic test on arrival still exists and validates the advanced options first: a fresh FTPS equipment therefore sees the errors immediately on arrival. That is acceptable for one story and disappears with 18.12. The certificate radios add no config key so nothing changes for the daemon.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the baseline (5 level2)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom: step 2 render in Dark and Light against the mockup (screens C, D2); FTPS settings editable under Personnalisé; an incomplete setup refused with its messages.
