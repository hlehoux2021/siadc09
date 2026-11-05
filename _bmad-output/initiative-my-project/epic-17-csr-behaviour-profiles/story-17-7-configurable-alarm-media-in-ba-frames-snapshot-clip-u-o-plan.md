---
title: '17.7 Configurable alarm media in BA frames'
type: 'feature'
ticket: '7'
created: '2026-11-05'
status: 'built'
baseline_revision: '32e82bda209de4f61cc92f09bc671e038a77eeb7'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The snapshot and clip URLs of alarm frames are always sent, in one `[V...]` tag, space separated. Receivers differ (Vesta wants U, FoxStream V), so the behaviour must be a per-equipment setting.

**Approach:** Five equipment keys (snapshot on/off, clip on/off, format U/V per media, one tag or several). PHP resolves the enabled URLs and sends a `media` list plus the one-tag flag; the daemon groups them into `[U..]`/`[V..]` tags. The wizard shows the options and the URL template in the advanced options, only when a media is on.

## Boundaries & Constraints

**Always:** No master switch; both media off means no media tag. Snapshot URL before clip URL. A single tag holds one format only. The URL template stays per-equipment, never part of a profile. The setting applies to burglar, fire and panic alarms alike. Equipment saved before this story sends today's bytes (snapshot on, clip on, V, V, one tag). `[U<url>]` follows the V syntax. Keys must pass the existing config-key consistency tests.

**Never:** Touch 17.8 profiles or `csr_presets.json`. Add URL character validation (the documented forbidden-char policy is not implemented; out of scope). Make the daemon read equipment config.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Legacy | keys absent | `[Vsnap clip]` as today | No error |
| Both on, U+U, one tag | URLs a, b | `[Ua b]` | No error |
| Both on, U+V, several tags | | `[Ua][Vb]` | No error |
| One URL unresolved, formats differ | clip missing | one tag for the snapshot | No error |
| Both off | | no media tag, no `media` key | No error |
| Single tag, U+V | inconsistent request | alarm sent without media | daemon logs error |
| Wizard, media on, URL empty | step 3 Next | blocked | message in the wizard |

</frozen-after-approval>

## Code Map

- `core/class/siaDC09Cmd.class.php` -- shared case burglar/fire/panic lines 105-138; implode join 132-135; resolvers 463, 536
- `resources/siadc09d/sia_protocol.py` -- `_format_extended_data_field` ~592-617 builds `[V..]`
- `resources/siadc09d/daemon.py` -- `media_url` through `on_message` ~2766, `EventItem` 199, queue payload 286/320, rebuild 2598, frame 2135
- `desktop/php/siaDC09.php` -- step 1 advanced panel 211; URL field step 3 292-297
- `desktop/js/siaDC09.js` -- `printEqLogic` 22, `siaDC09_validateStep1` 200, `#bt_step3Next` 581, summary 719
- `tests/level1/test_frigate_snapshot_resolution.py`, `test_sia_protocol.py` (792-864), `tests/level2/test_sm2_frame_building.py` (302), `test_wizard_php_structure.py`, `test_wizard_step1_js_dom.py`, `test_wizard_config_key_consistency.py` -- to extend
- `internal-docs/design/wizard-design.md`, `daemon-design.md`, `php-core-design.md` -- to update

## Tasks & Acceptance

**Execution:**
- [ ] `core/class/siaDC09.class.php` -- constants for the five keys and defaults -- one source for PHP and tests
- [ ] `core/class/siaDC09Cmd.class.php` -- read keys, resolve only enabled media, send `media` list + `media_single_tag`, omit when empty -- replaces `media_url`
- [ ] `resources/siadc09d/sia_protocol.py` -- build tags from the list; raise `ValueError` for one tag with mixed formats -- U and V rendering
- [ ] `resources/siadc09d/daemon.py` -- carry `media` through event, queue and frame; on `ValueError` log error and send without media -- alarm never lost
- [ ] `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` -- media block in advanced options, URL moved there, shown only if a media is on, one-tag option disabled for mixed formats, error if URL empty -- wizard rules
- [ ] tests (files in Code Map) -- one frame per valid combination, refusal, wizard show/hide and error, legacy bytes, key consistency
- [ ] design docs and `docs/admin-guide.md` -- new keys and payload

**Acceptance Criteria:**
- Given any valid combination, when a BA/fire/panic frame is built, then its bytes match the matrix.
- Given an equipment without the new keys, when an alarm is sent, then the frame equals today's.
- Given media on and an empty URL, when the user moves past step 3, then an error is shown.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Pass 1 (quick lens): 0 high, 6 medium/low patched, 1 deferred, 2 rejected.

| Verdict | Route | Finding and evidence |
|---|---|---|
| medium | patch | Wizard show/hide/error behaviour only checked as source strings; third acceptance criterion untested. Add DOM tests. |
| medium | patch | No level 2 test of the legacy default (V, V, one tag) through the new media path. |
| low | patch | No fire/panic test although the setting applies to all three. |
| low | patch | Matrix row "one URL unresolved, formats differ" has no PHP test. |
| low | patch | `on_message` media parsing untested. |
| low | patch | Stale docstring of `_format_extended_data_field`. |
| low | defer | Media rule validated only in the wizard; an equipment saved with a media on and an empty URL sends no media and no error. Pre-existing pattern for the URL template. |
| low | rejected | Single-tag box stays unchecked after formats are made equal again: disabled state is the specified behaviour, cosmetic. |
| false | rejected | PHP sends single tag with mixed formats for API-saved equipment: the plan makes the daemon the guard, alarm still goes out without media. |

## Design Notes

Payload: `{"cmd":..,"zone":..,"media":[{"format":"U","url":".."},{"format":"V","url":".."}],"media_single_tag":true}`. Keys: `media_snapshot_enabled`, `media_clip_enabled`, `media_snapshot_format`, `media_clip_format`, `media_single_tag`.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failure against the baseline
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax error

**Manual checks (if no CLI):**
- Wizard on test-jeedom: URL field hidden with both off, shown with one on, error when empty.
