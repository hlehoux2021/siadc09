---
title: '17.11 — Advanced Panel Rework: Labels, Extension Choice, Supervision'
type: feature
ticket: 'story-17-11-advanced-panel-rework-labels-extension-choice-supervis'
created: '2026-11-06'
status: 'in-review'
baseline_revision: '60567195453c329b1c93199284dcb2d1f36c3422'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/internal-docs/design/wizard-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The advanced panel shows bare "U"/"V" letters, a "one tag" checkbox that is hidden-in-spirit (only a help text when unavailable), loose supervision fields, no lock caption, and an orange NULL warning that wrongly blames the NULL format.

**Approach:** Rework the panel into two sub-sections per `ux-17-wizard-step-1/EXPERIENCE.md` ("Contents sent with the alarm", "Supervision card"): official format labels, an always-visible one-extension/one-per-link choice with real examples, a supervision card with intro, a lock caption naming the profile, and no NULL warning.

## Boundaries & Constraints

**Always:** Same config keys and stored values (`media_*`, `supervision_*`, `rp_*`); `media_single_tag` stays the bound key (1 = one extension). Locked fields stay readable, saved, and expose `readonly` or `aria-disabled="true"`. Folding the panel never changes a value. Labels: "Video Verification Link (V)" and "URL Multimedia Direct (U)". Examples use a space between URLs, abbreviated `https://monsite/..../snapshot.jpg` and `clip.mp4`, and match `_format_media_tags`. French vouvoiement. Update wizard-design.md and the JS test harness.

**Never:** Touch step 2/3/4 regions or the media card (17.10) / `media_enabled` logic, PHP/daemon code, the wire format, `ux-17-*` or `helpers/`. No new palette (no orange on step 1). No mention of § 5.5.1.8.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Profile chosen | e.g. FoxStream | Every panel field visible, locked (readonly or aria-disabled), caption « Fixé par le profil « FoxStream (FoxBox) ». Choisissez « Personnalisé » pour le modifier. » | none |
| Personnalisé | empty profile | All editable, no caption | none |
| Same format, both sent | V + V | Choice enabled; examples `[Vhttps://monsite/..../snapshot.jpg https://monsite/..../clip.mp4]` and `[Vhttps://monsite/..../snapshot.jpg][Vhttps://monsite/..../clip.mp4]` (letter follows the format) | none |
| Single content | one of photo/video off | Choice visible, greyed, reason « Disponible seulement si photo et vidéo sont envoyées avec le même format. », value unchecked | none |
| Mixed formats | U + V | Same greyed state and reason | none |
| Fold / unfold | any | No value lost | none |
| Supervision NULL | format = null | No warning shown | none |
| Ajax (no media keys) | Profile picked | Supervision card locked with caption; content fields stay editable (17.10 behavior), no caption on the content sub-section | none |

**Decision (user, 2026-11-06):** for a profile that declares no media keys (Ajax), keep the 17.10 behavior: the media content fields stay editable and only supervision is locked. This deliberately departs from the story AC wording "in a profile every field is read-only".

</frozen-after-approval>

## Code Map

- `desktop/php/siaDC09.php` l.228-293 -- `#siaDC09-advanced`: supervision group (l.235-263, incl. `#siaDC09-null-warning` l.243), media content group (l.265-292, `siaDC09-media-single-tag-group`). Restructure only here.
- `desktop/js/siaDC09.js` -- `siaDC09_lockProfileFields` (l.151), `siaDC09_updateNullWarning` (l.165, l.220, l.241, l.249: remove), `siaDC09_applyProfile` (l.214), `siaDC09_updateMediaFields` (l.265, owns the one-tag logic), `#bt_siaDC09_toggleAdvanced` (l.287). Reuse `siaDC09_mediaState()`. Do not change `siaDC09_applyProfileMedia`, `siaDC09_mediaConfigError`, validation.
- `resources/siadc09d/sia_protocol.py` l.635 `_format_media_tags` -- reference bytes for the examples; read-only.
- `tests/fixtures/js_wizard_step1_harness.js`, `tests/fixtures/js_wizard_flow_harness.js` -- DOM harness: new ids and removal of the null warning.
- `tests/level1/test_wizard_step1_js_dom.py` (null-warning test l.294, single-tag test l.327, lock tests l.38-120), `test_wizard_php_structure.py`, `test_wizard_config_key_consistency.py` -- adjust/extend.
- `core/i18n/fr_FR.json` -- hand-synced strings. `internal-docs/design/wizard-design.md` l.111-125 (advanced panel, null warning), l.1114-1122, l.1171-1173 -- update.

## Tasks & Acceptance

**Execution:**
- [ ] `desktop/php/siaDC09.php` -- two sub-sections with headings (« Contenu envoyé avec l'alarme (photo / vidéo) », « Supervision de la liaison » + intro), one lock caption element per sub-section, photo/video rows with format selects labelled V/U, always-visible extension choice (two radios, examples spans, reason span), remove the NULL warning -- panel structure
- [ ] `desktop/js/siaDC09.js` -- lock caption text from the profile label; add `aria-disabled` to locked non-input fields; radios drive `media_single_tag` (checkbox kept hidden as the bound field); examples built from current formats; greyed state plus reason; delete `siaDC09_updateNullWarning` and its calls -- behavior
- [ ] harness + level1 tests -- lock/readable per profile and Personnalisé; greyed choice (single content, mixed); example strings equal to `_format_media_tags` output for the same entries; fold keeps values; no null-warning element -- I/O matrix
- [ ] `core/i18n/fr_FR.json`, `internal-docs/design/wizard-design.md` -- new strings; drop the NULL warning sentence; describe the panel -- docs

**Acceptance Criteria:**
- Given a profile, when the panel opens, then every field is visible with readonly or aria-disabled and the lock caption; given Personnalisé, then all are editable with no caption.
- Given photo and video sent in the same format, when the panel is open, then the choice is enabled and its examples equal `SIAMessageBuilder._format_media_tags` output (single tag and per-link).
- Given a single content or mixed formats, then the choice is visible, greyed, unchecked, with the reason text.
- Given the panel is folded then unfolded, then no value changed; and `#siaDC09-null-warning` no longer exists.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

The radios are not `eqLogicAttr`: the existing checkbox `media_single_tag` stays the saved field (so Jeedom serialisation and PHP are untouched) and is visually hidden; radios mirror it. Example check in tests: call `_format_media_tags` from Python for the two entries and compare with the text the JS puts in the DOM.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: only the known baseline failure `test_php_periodic_frame_guard.py::test_get_csr_profiles_reads_real_file` (jsdom tests need a `node_modules` symlink to the main tree)
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom: each profile (locked, caption) and Personnalisé; toggle photo/video and formats to see the examples and the greyed reason; no orange warning with NULL.
