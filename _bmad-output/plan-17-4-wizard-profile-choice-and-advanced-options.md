---
title: '17-4 Wizard step 1 — profile choice and advanced options'
type: 'feature'
ticket: ''
created: '2026-10-18'
status: 'built'
baseline_revision: 'd3f683db9348c299ec68cea211e04818cfea825c'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture.md'
  - '{project-root}/.claude/rules/php-style.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 17.1-17.3 added supervision format, supervision period and RP settings plus `core/config/csr_presets.json`, but nothing in the wizard lets a user set them. `getCsrProfiles()` has no caller, and the step-1 field "Tentatives" (`retry_count`) is mislabelled (it is reconnection attempts).

**Approach:** Add a profile selector (Ajax / Scutum / Personnalisé) and a collapsed "Options avancées" block to wizard step 1. A profile fills the advanced fields from the PHP-embedded presets and locks them; Personnalisé unlocks them. The JS refuses to save "supervision none + RP off".

## Boundaries & Constraints

**Always:** Profile names stay PHP/JS-side (ADR-22) — the daemon only gets resolved values via the existing `deamon_start` keys. Store the choice as equipment config `csr_profile` ('' = Personnalisé). Existing equipment with no `csr_profile` opens on Personnalisé showing its current values. Keep existing `data-l2key` names (key-consistency tests). French UI text in `{{ }}`.

**Never:** No daemon or `deamon_start` change. No new profiles. No IMA preset (D-84). Do not validate by code reading only — UI validation on test-jeedom is required before closing.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Pick Scutum | selector = Scutum | format=none, RP on, RP period 60 filled; fields read-only | n/a |
| Pick Personnalisé | after a profile | fields unlock, values kept | n/a |
| Legacy equipment | no `csr_profile` | selector on Personnalisé, current values shown, unlocked | n/a |
| Dead config | format none + RP off | Suivant blocked | message in `#siaDC09-step1-errors` |
| Format null | format = null | warning "certains récepteurs le rejettent" visible | warning only |
| Bad RP period | RP on, period outside 60–86400 | Suivant blocked | message in step-1 errors |

</frozen-after-approval>

## Code Map

- `core/config/csr_presets.json` -- profiles `ajax`/`scutum` (`label`, `supervision_format`, `rp_enabled`, `rp_interval`); no `supervision_interval` (leave the field untouched when a preset omits it).
- `core/class/siaDC09.class.php:~503` -- `getCsrProfiles()` ("No caller yet" docblock to update); `periodicFrameConfigError()` is the PHP twin of the JS rules; `SUPERVISION_FORMATS`, `RP_INTERVAL_MIN_S/MAX_S` constants.
- `desktop/php/siaDC09.php:~91-190` -- step 1 markup (`#siaDC09-step1`, `#siaDC09-step1-errors`); line 6 `sendVarToJS` is the pattern to hand profiles to JS; `supervision_interval` and `retry_count` inputs at 178/184.
- `desktop/js/siaDC09.js` -- `siaDC09_validateStep1()` (l.110), `printEqLogic` (l.22), config summary `retry_count` text (l.600).
- `tests/level1/test_wizard_php_structure.py`, `test_wizard_config_key_consistency.py` -- structure pins; extend, keep green.
- `internal-docs/design/wizard-design.md` -- v0.2, still describes IMA step 1.

## Tasks & Acceptance

**Execution:**
- [ ] `desktop/php/siaDC09.php` -- add `csr_profile` select (options built from `siaDC09::getCsrProfiles()` + Personnalisé), collapsed "Options avancées" panel with `supervision_format` select (none/sia-dcs/null), `supervision_interval` (moved here), `rp_enabled` checkbox, `rp_interval`; `null` warning div; `sendVarToJS` of the profiles; relabel `retry_count` "Tentatives de reconnexion" -- AC fields and presets source
- [ ] `desktop/js/siaDC09.js` -- `siaDC09_applyProfile()` (fill + lock / unlock), run on change and in `printEqLogic` (empty profile → Personnalisé); null-warning toggle; extend `siaDC09_validateStep1()` with none+RP-off and RP range rules; relabel summary text -- behaviour
- [ ] `core/class/siaDC09.class.php` -- update `getCsrProfiles()` docblock (caller now exists) -- accuracy
- [ ] `tests/level1/test_wizard_php_structure.py` and `test_wizard_config_key_consistency.py` -- pin new fields, selector, profiles var, relabel, validator rule text -- regression
- [ ] `internal-docs/design/wizard-design.md` -- rewrite step 1 to the real fields (no IMA), bump version/date -- AC
- [ ] `_bmad-output/implementation-artifacts/sprint-status.yaml` -- 17-4 to `review` only after UI validation -- tracking

**Acceptance Criteria:**
- Given step 1 opens, when rendered, then the selector offers Ajax/Scutum/Personnalisé and "Options avancées" is collapsed.
- Given a profile is chosen, when applied, then advanced fields hold its values, are read-only, and survive Save/reload.
- Given none + RP off or an out-of-range RP period, when Suivant is clicked, then it is refused with a message.
- Given the flow is run on test-jeedom through the UI (new equipment, legacy equipment, each profile, null warning), then it behaves as above and `.eqLogicAttr` read-only fields are actually saved.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Pass 1 (quick): high 0 / medium 0 / low 3 / false 3 / maybe-false 1 (plus 2 not-a-defect rows).
- UI validation not yet run -- not a defect: pending by plan, gates `review` in sprint-status. No action.
- Stale values on legacy equipment (setValues may skip absent keys) -- maybe-false: depends on Jeedom setValues behaviour; the UI run settles it. Deferred.
- Unknown saved `csr_profile` loses choice -- low, rejected: needs a removed preset; fix adds a branch.
- Errors point at folded fields -- low, patched: the advanced panel opens when a periodic-frame error fires.
- Lock incomplete (keyboard/label) -- false: `tabindex=-1` blocks focus and the checkbox has no wrapping label.
- Wizard-design stale IMA -- low, patched: Task 3.2, presets section and test-table rows rewritten. testConnection code sample still shows `csr_provider` -- deferred.
- PHP twin not run at save time -- false: `deamon_start` Guard 3e covers it.
- Tests pin source strings -- low, rejected: matches the repo's existing pattern. Matrix rows are behavioural, covered only by the UI run.
- fr_FR.json reorder -- low, rejected: no functional effect.

## Design Notes

Locking caveat: disabled inputs may be skipped by Jeedom's form serialisation; prefer `readonly` (inputs) and verify selects/checkbox are saved in the UI run, else mirror them via `pointer-events:none` styling.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: 0 failures
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- test-jeedom UI (push first; host pulls by git): walk the AC scenarios above and report observed results.

## Code Review

### 2026-10-18 — 0 decision-needed, 2 patch, 0 defer, 14 rejected (second pass; lenses: blind-hunter, edge-case-hunter, verification-gap, intent-alignment)

- [x] [Review][Patch] jsdom harness never runs `printEqLogic` nor the change handlers: legacy defaults (no csr_profile → sia-dcs / RP 60, unlocked), saved-profile restore with `fill=false`, selector `change` opening `#siaDC09-advanced`, NULL-warning toggle (`nullWarningVisible` is output but never asserted), `rp_enabled: 0` / `"0"` preset, preset carrying `supervision_interval` [tests/level1/test_wizard_step1_js_dom.py, tests/fixtures/js_wizard_step1_harness.js]
- [x] [Review][Patch] Periodic-frame rule duplicated in `siaDC09_validateStep1` (error pushes and the "open advanced" condition): compute two booleans once [desktop/js/siaDC09.js:226-243]

#### Rejected
- Unknown saved `csr_profile` blanks the selector — low, already rejected in pass 1: needs a removed preset, fix adds a branch.
- Locked select/checkbox changeable from keyboard/label (3 lenses) — false: `pointer-events:none` prevents focus by click, `tabindex=-1` by Tab; no label wraps the controls. Same as pass 1.
- Switching profile leaves stale `supervision_interval` in a locked field — low: both presets use `none`, where the interval is unused.
- `printEqLogic` does not reset `supervision_interval` / `rp_enabled` between equipments — false: Jeedom reloads the page per equipment.
- Saved `supervision_format` not in none/sia-dcs/null — low: needs hand-edited config; PHP Guard 3e rejects it at daemon start.
- Preset `rp_enabled` as boolean/"true" — low: `csr_presets.json` is repo-owned and uses integers.
- `rp_interval` 60.5 passes `parseInt` — low: number input, negligible.
- Config summary shows 60 s with format none — false: `siaDC09_periodicSummaryLines` already prints "aucune trame de supervision" for none.
- Preset drifting from stored values after upgrade — low: design choice (`fill=false` keeps saved values), no preset change planned.
- `supervision_interval` has no range check — pre-existing field, outside this story.
- Harness brittleness (marker slicing, node/jsdom skip) — low: matches repo test pattern.
- Source-string assertions — low, rejected in pass 1.
- `tentatives de reconnexion` / en_US not translated — low: en_US is hand-maintained and partial (known).
- a11y (`aria-expanded`, lock explanation), PHP twin comment, intent divergences (UI/save path only verifiable on test-jeedom) — no defect; the UI validation run is the plan's own gate.
