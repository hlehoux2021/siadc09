---
id: 5
type: story
title: "13.5 — Automatic wiring of the siaDC09 commands into the Alarm plugin"
parent: epic-13-alarm-event-vocabulary
after: [1, 4]
hitl: true
risk: high
---

# 13.5 — Automatic wiring of the siaDC09 commands into the Alarm plugin

## Description

From the identifier of one Alarm plugin equipment, the plugin inserts its own action commands into that equipment's action lists, so the installer no longer pastes them by hand.

The installer picks the Alarm equipment, and for each of its zones the kind of alarm to report. One action then wires everything. A person runs the live round trip on test-jeedom through the Jeedom UI (arm, trigger, disarm) and confirms what the CSR received.

What gets wired:

| Alarm plugin hook | siaDC09 command | Title field |
|---|---|---|
| Activation OK, immediate | Armement | none |
| Désactivation OK | Désarmement | none |
| Réinitialisation | Réinitialisation alarme | none |
| Each zone, standard actions | Alarme intrusion for that zone | `#zone#` |
| Each zone, immediate actions | Prefetch événement Frigate, for zones with a mapped camera while photo/video verification is on | `#zone#` |

Linking again, after a zone is added or renamed, brings the wiring up to date. Unlinking removes what siaDC09 added and nothing else.

## Acceptance Criteria

Verify: On test-jeedom, link the alarm, then arm it, trigger a zone and disarm while the alarm is sounding: the CSR receives CL, the zone alarm with the right zone number, then BC and OP. Disarming with no alarm open sends OP alone, which is correct. Unlink removes only the entries siaDC09 added.

## References

- parent — _bmad-output/initiative-my-project/epic-13-alarm-event-vocabulary/epic-13-alarm-event-vocabulary.md
- design — internal-docs/design/wizard-design.md, "Step 3 — Zones et alertes" and "getZones"
- decision — _bmad-output/initiative-my-project/architecture-my-project/architecture-my-project.md, "ADR-18 — User-addressed event codes and the configured SIA user"
- sibling — _bmad-output/initiative-my-project/epic-13-alarm-event-vocabulary/story-13-1-burglary-restore-cancel-events-plan.md
- sibling — _bmad-output/initiative-my-project/epic-13-alarm-event-vocabulary/story-13-4-arm-disarm-closing-opening-reports-plan.md

## Notes

Decisions (2026-11-11, Herve, after a read-only study of the Alarm plugin source):

- Decision: write into the Alarm equipment's configuration ("plan A"). The alternative, listening to the Alarm plugin's state commands, was studied and rejected. It loses a second intrusion when the Alarm option « Réarmement automatique » or « Séparer les zones » is on, it can send false arm/disarm reports after a restore or a re-save, it can reorder messages, and it can only guess the zone and the triggering sensor. Wiring is exact because the Alarm plugin itself calls our commands and fills in `#zone#`.
- Decision: the whole plan stays one story. The builder may propose a split at plan time (pure wiring function with tests; AJAX action and wizard; resync and docs).
- Decision: the entry point is the wizard's step 3, which already lists the zones read from the Alarm plugin. There is no an Alarm equipment selector because only Intrusion is supported by  the plugin.
- Decision: the Alarm equipment identifier is stored on the siaDC09 equipment and validated server-side (it exists and is an Alarm equipment). The zone list then reads that equipment, not the first one found.
- Decision: wiring is idempotent. Entries that point at a command of this siaDC09 equipment are removed, then the wanted ones are added. The installer's existing hand-made wiring is replaced, never duplicated. Entries of other commands are never touched.
- Decision: each added entry is enabled and set to run in all modes (`options.enable` set, `onMode` = `all`).
- Decision: siaDC09 writes only the five hooks in the table. It never writes into « Activation OK » standard, « Activation KO », « Réinitialisation immédiate », the outbreak hooks or « reenableTrigger ». Wiring the arm report on the standard Activation OK hook would lose it when an arm has a bypass (story 13.4), and the others would duplicate reports.
- Decision: `release` carries the disarm and `raz` carries the alarm reset, both wired, because the Alarm plugin runs `raz` alone on a mode change while armed (story 13.1).

Facts checked in the Alarm plugin source (2026-11-10, read only, nothing run on Jeedom):

- The Alarm equipment keeps its action lists in its configuration under one key per hook, and per zone under the zone's standard and immediate lists. An entry holds the command id, its options (title, message, enable, background) and the mode filter.
- `#zone#` and `#alarm_trigger#` are supplied to the zone actions (standard and immediate) and to the outbreak, outbreak-immediate, activation-KO and re-enable hooks; `#zone#` is the zone label. `release`, `raz` and the immediate activation hook receive `#mode#` only, so the three hooks wired without a title never get a zone.
- The Alarm plugin skips an action whose command belongs to the Alarm equipment itself. This does not affect siaDC09 commands, which belong to another equipment.
- Saving the Alarm equipment from PHP is safe: its save rebuilds its commands and its sensor listeners.
- The wizard's zone list takes the first Alarm equipment found. With two Alarm equipments it can show the wrong zones.

Assumption: the option that disables an action in the Alarm UI is honoured by the way the Alarm plugin runs its actions, and writing it as enabled is enough. Confirm in the Jeedom core source before relying on it.

Assumption: the Alarm plugin's equipment page, if open in a browser while the link is applied, overwrites the new entries when it is saved. The wizard warns about it and the link action can be run again.

Decision (2026-11-11, Herve): writing into the Alarm equipment's configuration is accepted and is in the scope of epic 13. The epic's Boundaries are amended to say so.

Decision (2026-11-11, Herve): a zone with no mapped camera, or with photo/video verification off, gets no prefetch entry. No other rule is wanted.

Decision (2026-11-11, Herve): the unlink button sits on the siaDC09 equipment page, next to the « relancer assistant » button. The wizard has no unlink.

Check outside the criteria (high risk): Herve reads the Alarm equipment's configuration before and after link, and before and after unlink, and confirms that no entry other than siaDC09's changed. The level 1 suite also passes on the final commit. The live round trip on test-jeedom (link, arm, trigger, disarm, unlink) stays the Verify line.

Risk reason: a wrong or duplicated wiring means a real intrusion is reported late, twice, or not at all to the monitoring station.
