---
title: '17.10 — Photo/Video Verification Card and Locked Media Keys'
type: feature
ticket: 'story-17-10-photo-video-verification-card-and-locked-media-keys'
created: '2026-11-06'
status: 'in-progress'
baseline_revision: '2a03d057b24d505c892f12741e37ef6354282d78'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '{project-root}/internal-docs/design/wizard-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Step 1 hides the media options in the advanced panel, profiles only fill them (17.7/17.8 decisions), and an empty Frigate address is only caught at step 3 (bug B2).

**Approach:** Add a "Levée de doute photo / vidéo" card on step 1 (checkbox `media_enabled`, absent = on, plus the required Frigate address); profiles declare and lock the media content keys; `media_enabled=0` sends no media and skips prefetch/forced capture; the daemon refuses to start with media on and no address.

## Boundaries & Constraints

**Always:** Follow `ux-17-wizard-step-1/EXPERIENCE.md` (Photo / video verification card, Profiles and media, Build contracts). A legacy equipment (no `media_enabled`) reads on and sends the same bytes. Step 3 empty-URL check stays. The Frigate value is kept in the form when the box is off. The checkbox is never locked, only greyed+unchecked when the profile declares no media keys (Ajax).

**Never:** Touch step 2 regions (17.12 builds them in parallel: `siaDC09_runConnectionTest`, step 2 HTML, DUH view) or the supervision card. No new bytes on the wire. Do not edit `ux-17-*` or `helpers/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Vesta / FoxStream | Profile picked | Content keys filled and locked, box checked | none |
| Scutum | Profile picked | snapshot 0, clip 1, formats V locked, box unchecked | none |
| Ajax | Profile picked | Box greyed, unchecked, caption "Cette centrale ne reçoit ni photo ni vidéo." | none |
| Personnalisé | Picked | Content keys unlocked, box available, values kept | none |
| Box off | `media_enabled=0` | No `media` in BA payload, no `prefetchEvent` sent, Frigate value kept | none |
| Box on, empty address | Click Suivant | Field error + banner, focus, nothing saved | Daemon start refused (`deamon_info` nok) |
| Legacy equipment | `media_enabled` absent | Box reads on, same bytes as before; daemon still starts with an empty address (decision below) | none |

**Decision (user, 2026-11-06):** the empty-Frigate start guard in `deamon_info()` applies only when `media_enabled` is explicitly stored as 1. Existing installs (key absent) keep launching; the wizard writes the key on save.

</frozen-after-approval>

## Code Map

- `core/config/csr_presets.json` -- add `media_enabled` to vesta/foxstream (1), scutum (0 plus snapshot 0, clip 1, formats V, flagged to test); ajax unchanged (no media keys).
- `resources/siadc09d/presets.py` (l.22-42) -- `_ALLOWED_PROFILE_KEYS` + defaults: accept `media_enabled`; `tests/level1/test_csr_presets_json.py` mirrors it.
- `core/class/siaDC09.class.php` -- `MEDIA_DEFAULTS` (l.52) add `media_enabled=>1`; `deamon_info()` guards (l.208-240, next to Guard 3e) add the empty-Frigate guard; `launchable_message` French.
- `core/class/siaDC09Cmd.class.php` -- `prefetchEvent` case (l.44) returns early when `media_enabled` off; BA/FA/PA case (l.127) skips resolvers when off; `_mediaSetting` reusable.
- `desktop/php/siaDC09.php` (l.242-277) -- move the Frigate field out of `#siaDC09-advanced` into a new card above "Options avancées"; add `media_enabled` checkbox; media content fields get class `siaDC09-profile-field` (locked), keep `siaDC09-media-field`.
- `desktop/js/siaDC09.js` -- `printEqLogic` (l.31 defaults add `media_enabled:1`), `siaDC09_applyProfileMedia` (l.171), `siaDC09_applyProfile` (l.187: lock media fields, grey box when no media key), `siaDC09_updateMediaFields` (l.234: Frigate group follows the box), `siaDC09_mediaConfigError`/`siaDC09_validateStep1` (l.283: add Frigate error with key `frigate_media_url_template`, shared message).
- `tests/level1/test_wizard_step1_js_dom.py`, `tests/fixtures/js_wizard_step1_harness.js`, `test_wizard_js_logic.py`, `test_wizard_config_key_consistency.py`, `test_wizard_php_structure.py`, `test_frigate_prefetch_trigger.py` -- extend/adjust.
- `internal-docs/design/wizard-design.md` (l.1110-1114 profile media; l.1161 17.7 section), ADR-22 in `_bmad-output/initiative-my-project/architecture-my-project/architecture-my-project.md`, story files 17-7 and 17-8 -- correct "not profile fields" / "filled but not locked".

## Tasks & Acceptance

**Execution:**
- [ ] `core/config/csr_presets.json`, `resources/siadc09d/presets.py` -- add `media_enabled` and Scutum keys -- profile model
- [ ] `core/class/siaDC09.class.php` -- default + start guard -- server-side B2
- [ ] `core/class/siaDC09Cmd.class.php` -- gate prefetch and media on `media_enabled` -- no capture when off
- [ ] `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` -- card, lock, grey, validation -- step 1 UX
- [ ] tests (level1) -- preset keys, JS lock/grey/validation, PHP gating, legacy default
- [ ] docs and story files -- correct the reversed decisions

**Acceptance Criteria:**
- Given Vesta or FoxStream chosen, when step 1 shows, then media content keys are locked and the box is checked; Scutum locks video-only V with box off; Ajax greys the box; Personnalisé unlocks.
- Given the box is off, when an alarm fires, then the frame has no media tag, no prefetch is sent, and the Frigate value stays in the form.
- Given an equipment saved before this story, when loaded, then the box reads on and the frame bytes are unchanged.
- Given box on and empty address, when Suivant is clicked or the daemon starts, then step 1 refuses with field error and banner, and `deamon_info` is `nok`.

## Implementation Notes

Built directly (no subagent) on master 2a03d05 (17.9 merged). Guard 3f is `siaDC09::mediaConfigError()`, called from `deamon_info()`. Media content fields are locked only by a profile that declares media (Ajax leaves them alone, box greyed). `fr_FR.json` synced. 17.7/17.8 story files got a one-line reversal note; ADR-22 amended; `wizard-design.md` updated in the 17.7/17.8 sections only. The worktree needed a copied `node_modules` (ignored by git) to run the jsdom tests.

## Plan Change Log

## Review Triage Log

## Design Notes

Scutum single_tag: set `media_single_tag` 1 (irrelevant with one content). The 17.12 agent edits step 2 regions of the same JS/PHP/wizard-design files: keep edits to step 1 blocks, commit small.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: only the known baseline failure `test_php_periodic_frame_guard.py::test_get_csr_profiles_reads_real_file`
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom (Personnalisé and each profile): card, locks, refusal banner, then daemon start with empty address.
