---
title: '18.4 - Wizard step 1: media choice and transport'
type: 'feature'
ticket: '4'
created: '2026-11-09'
status: 'built'
baseline_revision: 'f2a5b89d60108f7d547a310d071b7e0ff8e68775'
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

**Problem:** The verification-media card on step 1 only asks the Frigate address; Photo/Vidéo sit in the step 2 advanced panel and the transport is a hand-entry select, so a user cannot choose how the receiver gets the media (E18-R6).

**Approach:** Rebuild the step 1 card as in the approved mockup (screens A, B, D, G, folder `ux-18-wizard-media-block/`, which is an acceptance criterion): "Que joindre ?" (Photo, Vidéo) and the two transport radios in the common part; the Frigate address only under "adresse"; no FTPS field in the final design. The FTPS settings are moved to step 2 by 18.11, so until then the existing hand-entry FTPS card stays, shown only under FTPS, as an interim.

## Boundaries & Constraints

**Always:** Photo/Vidéo stay locked by the profile (grey + one caption on step 1), free in "Personnalisé", and the whole block is hidden under a profile without media. An equipment with no `media_transport` behaves as "adresse". `ftps_enabled` stops being a stored choice: it is derived from `media_transport == ftps` in one PHP place used by the daemon start and the payload. The Frigate-address checks (step 1, step 3 safety net, PHP save/daemon guards) apply to "adresse" only. Texts are the French wording of EXPERIENCE.md.

**Never:** Step 2 behaviour (single test button, Suivant/Ignorer, the Serveur FTPS card, FTPS validation, FTPS test zone): story 18.11. The FTPS test action: 18.7. The FTPS completeness check at "Terminer": 18.11 (the fields move there). No FTPS key in a CSR profile (ADR-22).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Address, both media | Box ticked, Photo+Vidéo, transport adresse | Frigate address shown and required; saves | Missing address: error under the field + banner |
| FTPS chosen | transport ftps | No Frigate address asked or required; saves; daemon starts with the FTPS options | None |
| Nothing to attach | Box ticked, Photo and Vidéo both off | Refused | "Photo / vidéo : choisissez au moins l'une des deux." |
| Profile locks media | Vesta/FoxStream | Photo/Vidéo grey with "Fixé par le profil « {nom} »." | None |
| Profile without media | Ajax | Box greyed, unchecked, everything below hidden | None |
| Old equipment | No `media_transport` stored | Treated as adresse | None |

</frozen-after-approval>

## Code Map

- `desktop/php/siaDC09.php:195-209` -- media card: add "Que joindre ?" (`media_snapshot_enabled`, `media_clip_enabled`, classes `siaDC09-profile-field siaDC09-media-field`), the transport radios (`media_transport`), the Frigate group `#siaDC09-media-url-group` (:203) only under adresse; drop the :208 hint; add the step 1 lock caption
- `desktop/php/siaDC09.php:211-257` -- hand-entry FTPS card: remove the `media_transport` select (:217) and `ftps_enabled` checkbox (:223); show the card only under FTPS; mark it interim (moves in 18.11)
- `desktop/php/siaDC09.php:293-331` -- step 2 advanced panel: remove the Photo/Vidéo switches (:297, :301); formats (:307, :314) and extension radios (:321-331) shown only under adresse
- `desktop/js/siaDC09.js:333-350,364-371` -- `siaDC09_updateMediaFields`, `siaDC09_mediaConfigError`: Frigate group/check only under adresse; add the photo-or-video rule
- `desktop/js/siaDC09.js:408-441` -- `siaDC09_validateStep1` (media errors at :434-437); `:983` Terminer safety net uses `mediaConfigError`
- `desktop/js/siaDC09.js:160-258` -- profile lock (`siaDC09_lockProfileFields`, `SIADC09_PROFILE_MEDIA_*` :221-222, `siaDC09_setLockCaption` :190, `siaDC09_applyProfileMedia` :230, `siaDC09_setMediaCardAvailable` :251): Photo/Vidéo keep the lock; add the step 1 caption; hide all below the box when no media
- `desktop/js/siaDC09.js:570-583,1022-1087` -- step 2 summary (line 2 "Levée de doute") and `siaDC09_populateConfigSummary` (new block, never the password)
- `core/class/siaDC09.class.php:69-70,361-372,254,568` -- derive `ftps_enabled` from the transport (one helper); the Frigate guards at :254 and :568 skip FTPS
- `core/class/siaDC09Cmd.class.php` -- `_ftpsTransportActive()` uses the same helper
- Tests to update: `test_wizard_php_structure.py`, `test_wizard_step1_js_dom.py` (media :61-87, :522-660), `test_wizard_config_key_consistency.py:401-447`, `test_wizard_js_logic.py:466`, `test_php_ftps_keys.py`; imitate `js_wizard_step1_harness.js`
- Do not change: `siaDC09_runConnectionTest` and the step 2 buttons (18.11), `core/config/csr_presets.json`

## Tasks & Acceptance

**Execution:**
- [ ] `desktop/php/siaDC09.php` -- step 1 card markup per screens A/B, FTPS card interim, step 2 panel loses Photo/Vidéo -- mockup is the layout source
- [ ] `desktop/js/siaDC09.js` -- media fields, validation, lock caption, summaries -- behaviour of the matrix
- [ ] `core/class/siaDC09.class.php`, `siaDC09Cmd.class.php` -- derived `ftps_enabled`, Frigate guards skip FTPS -- one source of truth
- [ ] `tests/level1/` -- update the broken tests, add one test per matrix row (DOM harness + PHP structure) -- proves the matrix
- [ ] `internal-docs/design/wizard-design.md` -- step 1 media card and the moved Photo/Vidéo -- spec stays current

**Acceptance Criteria:**
- Given the approved mockup, when step 1 is rendered in Dark and Light, then the card matches screens A and B (the user checks the render).
- Given transport FTPS, when the equipment is saved and the daemon started, then no Frigate address is required and the daemon receives the FTPS options.
- Given an existing equipment saved before this story, when step 1 opens, then the transport shows "adresse" and nothing else changed.

## Implementation Notes

## Plan Change Log

## Review Triage Log

- medium, patched: under FTPS the note "settings are on the next step" sat above the interim card that holds them -- the note stays hidden while the card exists (18.11 turns it on and removes the card).
- medium, patched: the formats/extension panel was shown when the media box was off or the profile had no media (`!(enabled && ftps)`) -- now `enabled && !ftps`.
- medium, patched: a stale hidden `media_transport=ftps` kept FTPS on in the daemon with the media box off -- `isFtpsTransport()` also requires media on.
- low, patched: `daemon-design.md` still listed `ftps_enabled` as hand-entered; summary line with neither Photo nor Vidéo.
- medium, deferred: Photo/Vidéo, the transport and the lock caption are only reachable inside the wizard (hidden once it is finished) -- not a regression (the old step 2 switches had the same limit); recorded in `deferred-work.md` as a config-mode editing gap.
- low, rejected: equipments saved by hand during 18.2 with `ftps_enabled=0` and transport ftps would switch on (only test-jeedom, no real user); a locked profile declaring both media off (presets set at least one; the box is hidden for a profile without media); hidden `media_transport` versus radios (checked consistent); "Photo or Vidéo" not enforced in PHP outside the wizard (the wizard is the only way to change it).
- Open for the user: the render against screens A and B, Dark and Light; whether the lock caption renders inside the greyed block as the mockup shows.

## Design Notes

The interim FTPS card keeps FTPS configurable between 18.4 and 18.11; 18.11 removes it. `ftps_enabled` is derived so a user can no longer have the transport on FTPS with the upload off.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs the baseline (5 level2)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom: step 1 render in Dark and Light against the mockup; a Vesta profile shows Photo/Vidéo grey with the caption; an FTPS equipment saves without a Frigate address.
