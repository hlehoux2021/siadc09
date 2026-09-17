---
story_id: "13-1"
story_key: "13-1-burglary-restore-cancel-events"
epic_id: "epic-13"
epic_name: "Alarm Event Vocabulary Extension (v1.1)"
status: "backlog"
created: "2026-09-17"
---

# Story 13.1: Burglary Restore (BR) & Burglary Cancel (BC) Events

Status: backlog

## Story

As a monitored Jeedom user,
I want the plugin to report the *end* of an intrusion event — zone back to normal (BR) and alarm cancelled by the user (BC) —
So that the CSR closes the incident instead of keeping an open alarm until an operator calls.

## Context — why this is not a trivial addition

Discovered during Epic 12 VM integration testing (Story 12-5), while validating the first
real BA frame against the internal test receiver (`192.168.100.15:10002`, TCP, account
`001234`).

v1.0 supports exactly three event codes:

```python
# resources/siadc09d/daemon.py:144
SiaEventCode = Literal['BA', 'FA', 'PA']  # SIA alarm event codes: Burglary, Fire, Panic
```

`BR` and `BC` are absent from the whole repo, from the v1.1+ Growth list and from the
v1.5+ Vision list. They are **restoral/cancel** codes: unlike BA/FA/PA they are not
self-contained — each one refers back to a *previous* alarm on a *specific* zone. That
reference is what makes this a design story and not a two-line `Literal` extension.

Three obstacles must be resolved before implementation. They are stated as open design
questions below, each with the evidence found in the code.

### Obstacle 1 — SM2 has no per-zone state, so BR cannot be correlated

SM2 keeps a **single** current event:

```python
# resources/siadc09d/daemon.py:339-340
self._event_sia_code: SiaEventCode | None = None  # Latest event code (BA|FA|PA)
self._event_zone: str | None = None  # Latest zone from command #zone# tag
```

`_queue_consumer()` serialises events so at most one is PENDING at a time, and each new
event overwrites the previous `_event_sia_code`/`_event_zone`. There is no history and no
per-zone map.

Consequence: after `BA Salon` then `BA Cuisine`, the daemon can no longer tell that
`BR Salon` closes an alarm that is still open. Sending `BR` for a zone that never alarmed
(or sending it twice) is a protocol-level inconsistency the CSR may reject or, worse,
silently mis-attribute.

**Open question 1:** does SM2 gain a per-zone active-alarm map
(`dict[zone_number, {sia_code, sia_seq, timestamp}]`), or is BR emitted unconditionally
and correlation left entirely to the CSR? A per-zone map also needs a persistence and
eviction policy (restart, and a zone that never restores).

### Obstacle 2 — `event_state` has no vocabulary for "restored" or "cancelled"

`event_state` is a numeric info command (`core/class/siaDC09.class.php:647`, default 0)
with four values today: 0 inactive, 1 confirmed, 2 failed, 3 in progress. None of them
expresses "the zone returned to normal" or "the user cancelled".

Adding values is not local to the daemon: it changes the widget template and its JS, the
`event_label` French strings, and the diagnostic tab rendering. Reusing 0 (inactive) for
"restored" is tempting and wrong — 0 also means "nothing ever happened since install",
which the widget renders differently from "an intrusion ended two minutes ago".

**Open question 2:** new numeric states (e.g. 4 "Rétabli", 5 "Annulé"), or keep four
states and expose the restoral through a separate command / the ring buffer only?
Whichever is chosen, `event_label` and the widget must be updated in the same story.

### Obstacle 3 — the alarm plugin gives no zone on the restore path

Upstream `jeedom/plugin-alarm` (`core/class/alarm.class.php`, master) exposes exactly
three tags — `#mode#`, `#alarm_trigger#`, `#zone#` — and substitution is a plain
`str_replace` over every value of the action's `options` array, so a tag works in *Titre*
as well as in *Message*.

`#zone#` is supplied by only these actions:

| Action | Supplies `#zone#` | Reference |
|--------|-------------------|-----------|
| `outbreak`, `outbreakImmediate` | yes (`$zone['name']`) | `alarm.class.php:583-584`, `:605-606` |
| zone-level `actions` / `actionsImmediate` | yes (`doZoneAction`) | same |
| `reenableTrigger` | yes | `:547` |
| `activationKo` | yes (comma-joined list) | `:111`, `:794` |
| `release`, `raz`, `razImmediate`, `activationOk`, `activationImmediateOk` | **no — `#mode#` only** | `:703-712`, `:743`, `:809` |

The natural BR/BC triggers are `release` (siren off / alarm ended) and `raz` (reset), and
**neither passes a zone**. So the zone of a BR cannot come from the alarm plugin at all.

**Open question 3:** which Jeedom action commands do we expose
(`burglaryRestore` / `burglaryCancel`?), and where does their zone come from —
(a) our own per-zone SM2 map from Obstacle 1 (no user configuration, but only works for
zones we saw alarm), (b) one action per zone configured by the user with a hard-coded
title, or (c) BR without a zone number (account-level restoral)?
Note that `doAction()` skips any action whose cmd belongs to the alarm eqLogic itself
(`$this->getId() == $cmd->getEqLogic_id()` → `continue`), which does not affect us but
constrains how the user wires it.

## Dependency

Requires the zone-number resolution shipped by the Story 8.2 evolution (`zone_number` in
`sia_zone_mappings`, resolved in `siaDC09Cmd::execute()`): a BR must carry the **same**
zone number as the BA it closes, and the zone label is not usable as a correlation key.

## Acceptance Criteria

1. **Design decisions recorded:** the three open questions above are answered in
   `docs/design/daemon-design.md` (SM2 per-zone state), `docs/design/widget-design.md`
   (`event_state` vocabulary) and `docs/design/php-core-design.md` (commands + alarm
   plugin wiring) **before** any code is written.

2. **Event codes extended:** `SiaEventCode` accepts `BR` and `BC`;
   `_EVENT_SIA_CODES` maps the new Jeedom logical ids to them; `error_handler.py`'s
   `sia_code: Literal["BA", "FA", "PA"]` and its `event_type` → French label map
   (`error_handler.py:328`, `:366`) are extended in the same change.

3. **Jeedom commands exposed:** the new action commands appear on the equipment with
   French names, are created idempotently by `postSave()`, and are documented in the
   plugin documentation as "à câbler sur l'action `release` / la fenêtre d'abandon du
   plugin alarme".

4. **Frame correctness:** a BR frame is `[#{account}|BR {zone_number}]` and a BC frame is
   `[#{account}|BC {zone_number}]`, both accepted (ACK) by the internal test receiver
   `192.168.100.15:10002` over TCP with account `001234`.

5. **No zone → no zone field:** consistent with the Story 8.2 evolution, an unresolved
   zone yields `[#{account}|BR]` with a warning in the log — never the zone label.

6. **Correlation behaviour is deterministic:** whichever answer Open question 1 receives,
   there is a test proving what happens on `BR` for a zone that never alarmed and on a
   duplicate `BR`.

7. **`event_state` after restoral** matches the vocabulary chosen in Open question 2, in
   the daemon, the widget and the diagnostic tab, with the French label asserted.

8. **UI validation on `test-jeedom`:** validated through the real Jeedom UI on
   `test-jeedom.lehoux.net` (192.168.100.40), not by code reflection — trigger the alarm,
   end it, and read both frames in the protocol inspector.

## Tasks / Subtasks

- [ ] Task 1: Answer the three open design questions and update the three design docs (AC1)
- [ ] Task 2: Extend `SiaEventCode`, `_EVENT_SIA_CODES`, `error_handler` code/label maps (AC2)
- [ ] Task 3: SM2 restoral handling per the Open question 1 decision (AC6)
- [ ] Task 4: `event_state` vocabulary + widget + diagnostic tab per Open question 2 (AC7)
- [ ] Task 5: New action commands in `postSave()` + `siaDC09Cmd::execute()` cases (AC3)
- [ ] Task 6: Frame building + zone-number reuse; unmatched zone → no zone field (AC4, AC5)
- [ ] Task 7: Tests — level 1 frame building, level 2 SM2 correlation, level 2.5 IPC payload
- [ ] Task 8: Documentation (plugin doc + `.claude/skills/jeedom-alarm/SKILL.md` wiring note)
- [ ] Task 9: UI validation on `test-jeedom` against the internal receiver (AC8)

## Dev Notes

- **Do not start with the `Literal` extension.** Adding `'BR'` to `SiaEventCode` makes the
  code compile and the frame build, which hides all three obstacles above until a CSR
  rejects an uncorrelated restoral in production.
- The three tags are **undocumented in the alarm plugin UI** (`desktop/php/alarm.php` and
  `desktop/js/alarm.js` contain zero tag references), so the plugin documentation must
  spell out the wiring for the user.
- `#zone#` yields the zone **label** (`$zone['name']`), never a number — the alarm zone
  data model is `{name, actions, actionsImmediate, triggers}` only
  (`desktop/js/alarm.js:232-238`), the array position is never persisted or exposed.

## Change Log

| Date | Description |
|------|-------------|
| 2026-09-17 | Story created from Epic 12 findings — BR/BC support with the three blocking design questions (zone correlation, `event_state` vocabulary, commands + alarm plugin wiring) |
