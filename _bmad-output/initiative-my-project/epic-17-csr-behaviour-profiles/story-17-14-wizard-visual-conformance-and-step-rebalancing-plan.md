---
title: '17.14 — Wizard Visual Conformance and Step Rebalancing'
type: 'feature'
ticket: '14'
created: '2026-11-06'
status: 'in-review'
baseline_revision: '87c671e7b92de0bc11df25412af74c7b7c7f31f3'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/.working/flow-wizard-step-1-2026-11-05.excalidraw'
  - '{project-root}/.cleanup/excalidraw-dump.txt'
  - '{project-root}/_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/DESIGN.md'
  - '{project-root}/_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/EXPERIENCE.md'
  - '{project-root}/internal-docs/design/wizard-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The user rejected 17.9-17.12 on test-jeedom (2026-11-06): the pages are not like the Excalidraw mockup (no stepper at all, two-column title/field rows, a lock caption almost everywhere, a toggle button instead of the dashed Options avancées bar, long scroll, grey link hover unreadable). Step 1 is huge, step 4 is tiny.

**Approach:** Build the wizard from the mockup (the drawing is the layout source of truth; it wins over DESIGN.md text where they differ) in three steps: 1 Centrale (center + photo/video), 2 Test (test + Options avancées), 3 Zones et alertes (former 3 and 4 merged). First update the mockup and UX texts to three tabs, then build, then check real rendered pages.

**Decisions (user, 2026-11-06):**
- Three steps as above. Personnalisé chosen on the Test step modifies no preset and behaves exactly as if chosen on step 1 (profile select becomes Personnalisé, fields unlock, values kept).
- After switching to Personnalisé on the Test step the test NEVER reruns by itself; it runs only when the user clicks « Relancer le test ».
- Equipments already saved at a wizard step are out of scope (test phase): no mapping of stored steps.
- The unfolded « Options avancées » bar stays ABOVE its content, as a standard collapsible panel (user, 2026-11-06). Screen B of the mockup is corrected accordingly; it overrides the drawing.
- « Suivant » stays Jeedom green (`btn-success`), as in DESIGN.md; the light blue in the mockup was a placeholder (user, 2026-11-06).
- The plan stays whole (not split).
- The user checks a rendered page before the story is called built; a jsdom or structure test alone does not close it.

## Boundaries & Constraints

**Always:** Stock Jeedom Bootstrap 3 and theme (no new typeface or icon set); plugin CSS in its own file, never inline; i18n via `{{...}}`; every disabled wizard button looks disabled; Light theme readable, Dark theme not broken.

**Never:** Migrate stored `sia_wizard_step`; push; change daemon, presets or protocol code; edit `helpers/`; touch `deamon_info` guard logic beyond what the Code Map lists; auto-rerun the test.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| Failed test then expert fix | Test red (DUH), user opens Options avancées, clicks Personnalisé link, edits a field | Fields unlock, profile select = Personnalisé, no preset changed, test NOT rerun; « Relancer le test » saves the form then tests | Invalid advanced values: banner + field error, panel opens, test not launched |
| Profile locked | FoxStream on Test step | One lock caption for the whole panel, fields grey | none |
| Terminer | Valid notify target | `sia_wizard_step=4`, reload to config mode | Missing target: existing error alerts, no save |

</frozen-after-approval>

## Code Map

Step-number dependents (all must follow the new scheme). Scheme: stored `sia_wizard_step` = step shown, 1..3; `4` stays the "wizard complete" sentinel (config mode, launch guard `< 4`); only « Terminer » on step 3 writes 4. Hence no stored-value migration and class/guard code keep working.
- `desktop/php/siaDC09.php` -- no stepper exists; step1 L133-319 (legend, 2-col `form-group` rows, `#bt_siaDC09_toggleAdvanced` button L231, `#siaDC09-advanced` L235-308 with per-section lock captions L238, L279); step2 L322-346; step3 L349-392; step4 L395-475 (`bt_step4Finish`, `siaDC09-step4-error*`, notify ids kept); config summary L479. Wizard sits in `col-lg-6` L126 (width ~ mockup 760px; keep). Needs: stepper, zones, advanced block moved into step2, step3+4 merged (remove `#siaDC09-step4`), `include_file('desktop','siaDC09','css','siaDC09')`.
- `desktop/css/siaDC09.css` -- DOES NOT EXIST (no plugin CSS today; styles are inline/JS `.css()`); create. Pattern: `helpers/plugin-frigate/desktop/php/frigate.php:501` includes its css.
- `desktop/js/siaDC09.js` -- `printEqLogic` L42-53 (`wizardStep >= 4`, `Math.max(1, wizardStep)`); `saveEqLogic` L56-80 (`step === 3` serialises zones, `step > 0 && step < 3` deletes mappings: unchanged); `siaDC09_currentStep` L84 (regex `step(\d+)`); `siaDC09_showStep` L104-139 (branches 1..4: merge 3+4: load zones AND `initNotifyTarget`, reset Terminer; step 2 must also not auto-run when arrived from a Personnalisé switch—only on entry); `siaDC09_lockProfileFields/setLockCaptions/applyProfile` L151-253 (two captions -> one; applying '' = Personnalisé path reused by step 2); profile `change` handler L250 opens panel (move to step 2 behaviour); toggle L326; `validateStep1` L353-399 (advanced rules `supervision_format`, `rp_interval`, L379-390, move to a step-2 validation run by « Relancer le test » before saving); `renderStep1Errors` L402 (`#siaDC09-advanced` closest); step1Next L478-502 (`setWizardStep(2)`); step2 L506-683 (`setWizardStep(3)` x2, `advanceToStep3`; Relancer must `save` then test because `core/ajax/siaDC09.ajax.php:54-79` tests the SAVED config); restart L687-715 (`setWizardStep(0)`, `showStep(1)`); step3Next L828-849 (`setWizardStep(4)`, `showStep(4)` -> removed); step4 L856-943 (`bt_step4Finish`, `setWizardStep(4)`, reload) -> merged Terminer: validate notify target + `siaDC09_mediaConfigError()` + serialise zones (`saveEqLogic`) + save.
- `core/class/siaDC09.class.php:166` -- `(int) getConfiguration('sia_wizard_step',0) < 4` launch guard: unchanged by the scheme; verify only. Also L132 comment.
- Tests naming steps/ids (update): `tests/level1/test_wizard_php_structure.py` (step1..4 ids L59-84, `bt_step3Next/bt_step4Finish` L392-395, step3/4 markup slice L306), `test_wizard_js_logic.py`, `test_wizard_step1_js_dom.py`, `test_wizard_step1_flow_js_dom.py`, `test_wizard_config_key_consistency.py`, `test_php_eqlogic_stub.py` (guard 2 only: keep), `test_diagnostic_tab.py`, `test_diagnostic_js_dom.py`; fixtures `tests/fixtures/js_wizard_flow_harness.js`, `js_wizard_step1_harness.js`. Run `grep -rn "siaDC09-step4\|bt_step4\|bt_step3Next\|setWizardStep" tests` before editing.
- Docs: `internal-docs/design/wizard-design.md` (L12 "4 steps", step map L30-38, steps table L68-75 and "stepper" claim L75 which no code ever built, Step 1/2/3/4 sections, L469 finish, L659-700 JS notes, key table L531-549); `ux-17-wizard-step-1/DESIGN.md` (Layout & Spacing table), `EXPERIENCE.md` (IA table, "Steps 3 and 4 are unchanged", Step 2 states, Key flows); mockup `.working/flow-wizard-step-1-2026-11-05.excalidraw` (JSON: 119 elements, tabs at x20/195/370/545 w165 h34; edit with a throwaway Python script in `.cleanup/`, never committed).
- Jeedom theme facts (grepped in `helpers/jeedom/core`): `desktop/css/desktop.main.css:68` `a:hover{color:var(--linkHover-color)!important}`; Light `core/themes/core2019_Light/desktop/colors.css:22` `--linkHover-color: rgb(140,140,148)` on panel `240,241,242` (about 3:1, the unreadable hover); `core2019_Light.css:7` `a{color:var(--link-color)!important}`; `.well` uses theme bg (`desktop.main.css:3297`), so #f8f9fa zones need their own class. Plugin CSS must out-specify with ids plus `!important`.
- Excalidraw geometry to reproduce (from dump + JSON): screen box 760 wide, 20px outer margin, zones x20 w720 fill #f8f9fa 1px #1e1e1e, 20px between zones; tabs y20 h34 active #a5d8ff else white; zone title 20px; label 14px directly above a 34px-high white field (label y+22 gap); row: IP w250 / Port w110 / Transport w140; Account w250 with the AES checkbox on its row; Frigate field w520, error: 2px #e03131 border + 13px red message; help 12-13px #868e96; folded bar x20 w720 h56 dashed 1px, #f8f9fa, two lines (title, 12px muted hint); unfolded: two zones then a same-size dashed bar « v Options avancées (cliquer pour replier) »; locked fields fill #e9ecef border #868e96 text #868e96; error banner #ffe3e3/#e03131 h90 above Suivant; Suivant right-aligned; screen C: red zone #ffe3e3/#e03131 2px (w660) with sent frame, « Vérifiez » list, then four buttons in a row (Modifier la centrale left; Relancer, Ignorer, Suivant grey dashed disabled).

## Tasks & Acceptance

**Execution:**
- [ ] `ux-17-wizard-step-1/.working/flow-wizard-step-1-2026-11-05.excalidraw` -- 3 tabs on every screen (Centrale / Test / Zones et alertes); screen A without the Options avancées bar and its hint now pointing to the Test step; B = Test step with advanced unfolded; C kept (3 tabs); new D = step 3 merged (two zones: zones, alertes); orange side notes updated -- the user judges against it, so it must be right BEFORE code
- [ ] `ux-17-wizard-step-1/DESIGN.md`, `EXPERIENCE.md`, `internal-docs/design/wizard-design.md` -- 3-step text, advanced panel on Test, single lock caption, Personnalisé switch on Test step, no auto-rerun, step map (4 = complete); say the mockup wins over DESIGN.md
- [ ] `tests/render/render_wizard.py` (+ `tests/render/stub_prelude.php`) -- rendering harness (see Verification); screenshots to `.cleanup/screens/` (untracked)
- [ ] `desktop/css/siaDC09.css` -- zone, stepper, field-row, locked, advanced bar, caption, link-hover rules
- [ ] `desktop/php/siaDC09.php` -- restructure per Code Map
- [ ] `desktop/js/siaDC09.js` -- step logic per Code Map; stepper active state in `showStep`; `siaDC09_switchToCustom()`; Relancer = validate advanced, save, test
- [ ] tests listed in Code Map -- update to 3 steps; add jsdom tests for: Personnalisé switch from step 2 (no preset change, no auto test), Relancer saves before testing, Terminer writes 4, no `step4` id
- [ ] Render the 4 screens, compare with the mockup, fix, attach paths in Implementation Notes

**Acceptance Criteria** (each is checked on the rendered page unless marked [test]):
- AC1 Given any wizard step, then a stepper of exactly three tabs « 1 Centrale », « 2 Test », « 3 Zones et alertes » sits at the top of the wizard column, tabs 34px high with 5-10px gaps filling the 720px width, active tab filled #a5d8ff, others white, 1px #1e1e1e border, not clickable.
- AC2 Given a screen, then each topic is one framed zone: x offset 20px, fill #f8f9fa, 1px border #1e1e1e, rounded as Bootstrap, 20px between zones, title 20px at the zone top, no `legend` and no icon in titles.
- AC3 Given any field, then its label sits ABOVE the field (never to its left), label 14px, field 34px high, no 2-column title/field layout anywhere in the wizard.
- AC4 Given step 1, then IP, Port and Transport share one row (about 250/110/140px), and Numéro de compte shares a row with « Chiffrer les échanges (clé AES) »; the AES key field appears under it only when checked.
- AC5 Given the Options avancées panel (step 2), then Photo and Vidéo (sent + link format) share a row each pair side by side, and Message de vie and Test cyclique (RP) show their « Toutes les (secondes) » fields on the right as drawn.
- AC6 Given a profile is chosen, then the Options avancées panel shows exactly ONE lock caption « Fixé par le profil « {nom} ». Choisissez « Personnalisé » pour le modifier. », located at the top of the panel; no caption appears on step 1, per field or per zone; locked fields are fill #e9ecef, border #868e96, grey text.
- AC7 Given step 1, then the order is: stepper, zone « Votre centrale de télésurveillance » (profile, help text right of the select, row IP/port/transport, account row), zone « Levée de doute photo / vidéo », error banner (only after a refusal), « Suivant » right-aligned; no Options avancées bar on step 1.
- AC8 Given step 2, then the Options avancées bar is a full-width dashed 1px bar, fill #f8f9fa, 56px high, folded text « > Options avancées : contenu envoyé, supervision de la liaison » plus the muted hint « (cliquez pour afficher ; s'ouvre toute seule si une erreur s'y trouve) »; unfolded, the bar stays at the same place and reads « v Options avancées (cliquer pour replier) »; the two zones « Contenu envoyé avec l'alarme (photo / vidéo) » and « Supervision de la liaison » appear BELOW it (standard collapsible, user decision), otherwise as screen B once corrected. « Suivant » is `btn-success` green.
- AC9 Given a failed test, then the page matches screen C: summary line, red zone (#ffe3e3, 2px #e03131) with sent frame, type line, « Vérifiez » list and « Puis relancez le test. », then a row « ← Modifier la centrale » left, « Relancer le test », « Ignorer », and « Suivant » grey and inert.
- AC10 Given a failed test and a locked profile, when the user clicks the Personnalisé action in the lock caption, then the profile select reads Personnalisé, the panel opens unlocked with values kept, the caption disappears, and no request is sent [test]; the test runs only after « Relancer le test », which first saves the form [test].
- AC11 Given Personnalisé with an invalid RP interval, when « Relancer le test » is clicked, then the field shows its error, the panel is open, nothing is saved or tested [test].
- AC12 Given step 3, then one page holds the zones zone and the « Alertes critiques » zone, with one « Terminer » button; completing writes `sia_wizard_step=4` and reloads to config mode; no element with id `siaDC09-step4` remains [test].
- AC13 Given the Light theme, when hovering any link or `.btn` in the wizard, then text keeps at least 4.5:1 contrast with its background (measured in the screenshot); Dark theme hover stays readable.
- AC14 Given 1440x900, then the wizard block is at most 1010px high on screen A and at most 640px on screen C (mockup heights), and screen B (unfolded) at most 1400px; no screen needs more than two viewport heights.
- AC15 Given the existing equipment tests, then `python3 -m pytest tests/level1/` shows no failures beyond the recorded baseline [test].

## Implementation Notes

Built directly (no implementation subagent), then a quick independent review.

- **Rendering could NOT be run in this environment.** Chrome (`/Applications/Google Chrome.app`) was refused by the user for this run ("utilise firefox"); Firefox headless starts but cannot spawn its child processes inside the Seatbelt sandbox (`bootstrap_check_in failed`, no PNG produced). No screenshot exists. `tests/render/render_wizard.py` does generate four standalone pages (`.cleanup/screens/wizard-{A,B,C,D}-{Light,Dark}.html`) from the real PHP page, the real Jeedom CSS from `helpers/` and the real JS; they were only loaded in jsdom (script errors and screen state checked, no layout). The user must open them, or test-jeedom, to judge AC1-AC9, AC13, AC14.
- Mockup (`flow-wizard-step-1-2026-11-05.excalidraw`) updated by a throwaway script: 3 tabs on A, B, C; A without the bar and with a green Suivant; B redrawn as the Test step with the bar ABOVE its content and one lock caption; C with the folded bar; new screen D (step 3). Not opened in Excalidraw either.
- Step scheme: stored value = step shown (1..3), `SIADC09_WIZARD_DONE = 4` written by « Terminer » only; PHP guard `< 4` untouched.
- Deviations to confirm visually: (1) Photo/Vidéo « Envoyée » is a checkbox in a field-sized box, not the `Envoyée v` select of the drawing (the saved keys are checkboxes; a select needs a mirrored field); (2) reconnection retries/delay moved into the Supervision zone (the mockup has no place for them); (3) screen C draws the raw frame line `"SIA-DCS"0001L0#...`; the backend deliberately returns only type/account/transport (story 17.12, bytes may be encrypted), so only the typed summary is shown; (4) a name clash with the diagnostic `siaDC09_renderErrors` was avoided by naming the new helper `siaDC09_renderFieldErrors`.
- i18n: `core/i18n/fr_FR.json` resynced for the page and JS (18 added, 14 removed in the page section).

## Plan Change Log

## Review Triage Log

## Design Notes

- The drawing put the unfolded bar below its content; the user decided it stays above (standard collapsible); screen B is redrawn that way.
- Order on step 2: summary, result, Options avancées (bar + content), button row, so the user edits settings then presses « Relancer le test » without scrolling past them.
- #f8f9fa zones set their own text color (#333) and hover colors, so they stay readable on both Jeedom themes.
- Buttons keep Bootstrap `btn-success` / `btn-default` (DESIGN.md); the mockup's light-blue Suivant was a placeholder (confirmed by the user). Mockup Suivant fills are recoloured green.
- Token budget: well above 1600 because the user asked for every layout rule as an AC; the ACs are the spec.

## Verification

**Rendered check (required before « built »):** `tests/render/render_wizard.py` runs the real page: `php` (installed, 8.5) executes `desktop/php/siaDC09.php` behind a stub prelude (isConnect, plugin/eqLogic/jeeObject/scenario stubs, sendVarToJS, include_file, `{{x}}` stripped) and writes an HTML page linking the real Jeedom CSS from `helpers/jeedom/core` (bootstrap.css, desktop.main.css, core2019_Light colors+theme, font-awesome5, jquery) plus `desktop/css/siaDC09.css` and the real `siaDC09.js` with a stub `jeedom` object that drives the screens A, B, C, D (and Dark variant). Chrome is installed (`/Applications/Google Chrome.app`, headless `--screenshot`); the planning agent could not launch it (command guard refused the spaced path), so feasibility is UNVERIFIED: the build session must try it first, and if it cannot run, say so and the user checks on test-jeedom instead. Never install anything. Screenshots land in `.cleanup/screens/`, compared with the mockup AC by AC; link hover contrast read from computed styles via `--dump-dom` or a pixel sample.
**Commands:**
- `python3 -m pytest tests/level1/` -- expected: no new failures vs baseline (re-measure on clean master)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors
**Manual checks:** user compares screens A, B, C, D on test-jeedom (or the screenshots) side by side with the updated mockup; hovers a link in Light theme; failed test, Personnalisé, edit, Relancer works without leaving step 2.
