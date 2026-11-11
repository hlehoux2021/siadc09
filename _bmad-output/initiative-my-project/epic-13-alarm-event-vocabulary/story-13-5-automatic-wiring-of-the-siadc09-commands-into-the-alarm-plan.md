---
title: '13.5 — Automatic wiring of the siaDC09 commands into the Alarm plugin'
type: 'feature'
ticket: '5'
created: '2026-11-11'
status: 'built'
baseline_revision: 'd26ff4c1c5aebb579576e7f1b7f15f8ac3bb8740'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The installer pastes siaDC09's action commands into the Alarm plugin by hand. A missed, wrong or duplicated entry means an intrusion is reported late, twice, or never to the CSR.

**Approach:** From one chosen Alarm equipment, siaDC09 writes its own commands into that equipment's five hooks ("plan A", decided 2026-11-11), idempotently. The wizard's step 3 gains the Alarm selector and a link button; the equipment page gains an unlink button.

## Boundaries & Constraints

**Always:**
- Hooks written, nothing else: `activationImmediateOk` (arm), `release` (disarm), `raz` (alarm reset), and per zone `actions` (« Alarme intrusion » only, title `#zone#`) and `actionsImmediate` (prefetch, title `#zone#`).
- Entry shape: `{cmd:'#id#', onMode:'all', options:{enable:1, background:0, title, message}}`.
- Idempotent: first drop every entry whose cmd is a command of this siaDC09 equipment, then add the wanted ones. Entries of other commands are never touched.
- Prefetch entry only for a zone with a mapped camera while `media_enabled` is on (absent = on). No other rule.
- The Alarm equipment id is stored on the siaDC09 equipment and validated server-side (exists, eqType `alarm`). `getZones` reads that equipment.
- Unlink button sits next to « relancer assistant ». The wizard has no unlink.
- Decision (2026-11-11, Herve): the plugin handles intrusion only. Every zone gets « Alarme intrusion »; there is no alarm-kind column. Fire and panic are postponed to a later story.
- Decision (2026-11-11, Herve): linking is a button in step 3, clickable again. It does not run on « Terminer » or on save.
- Decision (2026-11-11, Herve): unlink only removes siaDC09's entries. The chosen Alarm equipment stays stored and selected.

**Never:**
- Write into `activationOk`, `activationKo`, `razImmediate`, `outbreak*`, `reenableTrigger`.
- Change the Alarm plugin's code, or listen to its state commands.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Link | Alarm eq with 3 zones | 3 hooks + per-zone entries written | No error expected |
| Re-link | Zone added or renamed | Same entries refreshed, no duplicate | No error expected |
| Hand wiring | Installer already pasted our cmds | Replaced, not duplicated | No error expected |
| Foreign entry | Entry of another cmd in a list | Left untouched, same order | No error expected |
| Bad id | Id not an Alarm equipment | Nothing written | `ajax::error`, config unchanged |
| Unlink | Linked equipment | Only our entries removed | No error expected |

</frozen-after-approval>

## Code Map

- `core/class/siaDC09.class.php` -- commands created in `postSave` (~1049-1086): logicalIds `arm`, `disarm`, `alarmReset`, `burglarAlarm`, `prefetchEvent` (message subType, except the first three: other). `fireAlarm`/`panicAlarm` exist but are not wired (intrusion only); `getActiveEquipment()` (112). Add pure static `buildAlarmWiring()` plus link/unlink methods.
- `core/ajax/siaDC09.ajax.php` -- `getZones` (216-231) takes `byType('alarm')[0]`: change to the stored id. Add `linkAlarm`/`unlinkAlarm`; pattern `eqLogic::byId` + `getEqType_name()`, `ajax::error(__())`.
- `desktop/php/siaDC09.php` -- step 3 table header (416-423), help lines (428-430, 438-440), `#bt_restartWizard` (120).
- `desktop/js/siaDC09.js` -- `siaDC09_loadZoneData` (1137), `siaDC09_buildZoneRow` (1220), `saveEqLogic` (59-87, `sia_zone_mappings`, unchanged), restart handler (1105-1133).
- `core/class/siaDC09Cmd.class.php` -- `_getZoneMapping` (749), `_findZoneEntry` (765): zone number resolved by name; prefetch needs `frigate_camera_eqlogic_id`. Do not change.
- `helpers/plugin-alarm/core/class/alarm.class.php` -- read only: hooks 703-830, `enable` default 1 (core `scenarioExpression.class.php:1384`), `#zone#` only in zone and outbreak hooks.
- `tests/level1/test_php_periodic_frame_guard.py` -- pattern: `_extract_method_body` + php CLI. `test_wizard_ajax_contracts.py:275-335` asserts `getZones` source: update.
- Docs: `docs/fr_FR/index.md:103-149`, `docs/en_US/index.md:11`, `wizard-design.md` (Step 3, `getZones`), `php-core-design.md:424-441`, `core/i18n/{fr_FR,en_US}.json`.

## Tasks & Acceptance

**Execution:**
- [ ] `core/class/siaDC09.class.php` -- pure `buildAlarmWiring` (lists in, lists out), `linkAlarm`, `unlinkAlarm`, config `alarm_eqlogic_id` -- exact, idempotent
- [ ] `core/ajax/siaDC09.ajax.php` -- `linkAlarm`, `unlinkAlarm`, `getZones` by id -- server validation
- [ ] `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` -- selector, link button, unlink button, warning about an open Alarm page
- [ ] `core/i18n/*.json` -- new strings
- [ ] `tests/level1/` -- wiring cases of the matrix, ajax contract updates
- [ ] docs listed in the Code Map -- manual wiring replaced by the link

**Acceptance Criteria:**
- Given linked equipment, when the matrix cases run, then each outcome holds (level 1).
- Given test-jeedom, when I arm, trigger a zone and disarm during the alarm, then the CSR receives CL, the zone alarm with the right number, BC and OP; disarm with no alarm sends OP alone.
- Given unlink, then only siaDC09's entries disappear (Herve diffs the Alarm configuration before/after link and unlink).

## Implementation Notes

## Plan Change Log

## Review Triage Log

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | getZones empty until the selector is used | low | rejected | Plan says the selector starts empty on purpose; fix would add auto-select branch |
| 2 | linkAlarm writes hooks before storing the id | low | patch | Unlink could not find a half-written link; id now stored first |
| 3 | unlinkAlarm throws when the stored Alarm equipment is gone | false | rejected | A clear error is the right outcome; nothing to unlink |
| 4 | Entries of deleted-and-recreated siaDC09 commands are not recognised | low | defer | Command ids are stable per logicalId in postSave; only a manual delete triggers it |
| 5 | en_US lacks desktop strings | false | rejected | en_US was already partial for desktop strings before this change |
| 6 | Bad id covered by source-string checks only | low | rejected | Jeedom classes are not loadable in level 1; live check covers it |
| 7 | Link button saves the whole form first | false | rejected | Plan forbids linking on save, not saving before link; zone mappings are otherwise unsaved |

## Design Notes

Zones are identified by name only in the Alarm plugin, so `#zone#` is resolved by siaDC09 against `sia_zone_mappings`. The Alarm UI save rebuilds lists from form fields, so entries are recognised by their cmd id, not by a marker key.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: no new failure vs baseline
- `find core/ desktop/ -name "*.php" | xargs -n1 php -l` -- expected: no syntax error

**Manual checks (if no CLI):**
- Live round trip on test-jeedom through the UI, then the before/after configuration diff.
