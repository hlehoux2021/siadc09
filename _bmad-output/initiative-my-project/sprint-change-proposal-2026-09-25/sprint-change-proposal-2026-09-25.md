# Sprint Change Proposal — 2026-09-25

**Trigger story:** 13-1 (`13-1-burglary-restore-cancel-events`), in-progress, Tasks 1-8 done but uncommitted
**Author:** Developer agent (bmad-correct-course), with Herve
**Mode:** Batch
**Status:** approved 2026-09-25 by Herve; §4.1-4.6 applied to prd.md, epics.md, architecture.md
(ADR-18), the four design docs, the story file and sprint-status.yaml

---

## 1. Issue Summary

Story 13-1 was built on the premise that a **BC (Burglary Cancel) frame carries a zone number**. Because of
that premise, it fans out one `[#001234|BC nnn]` per zone that alarmed. The fan-out is driven by a
`sia_open_alarms` table and triggered by a `burglaryCancel` command wired on the alarm plugin's `raz` action.

The premise is wrong. The SIA DC-03 event-code table (`internal-docs/SIA Codes – Complete DC-03 Event Code List _
Peoplecall Cloud.pdf`, p. 4) defines:

| Code | Name | Address field |
|---|---|---|
| BA | Burglary Alarm | Zone or point |
| **BC** | **Burglary Cancel — "Alarm has been cancelled by authorized user"** | **User number** |

So `[#001234|BC 003]` means "cancelled by **user 3**", not "zone 3 closed". A frame with no address
(`[#001234|BC]`) is legal DC-09, but a CSR automation may reject it or mis-file it. Gemini gave the same
warning.

The review of the trigger also brought in a **scope extension** that Herve accepted. The plugin should report
the system's arm/disarm state changes, not only the end of a burglary. Codes (confirmed by Herve against the
full DC-03 table; the repo copy has only pages 1-4, up to BC):

| Code | Meaning | Address field |
|---|---|---|
| CL | Closing Report — system armed | User number |
| OP | Opening Report — system disarmed, normal | User number |
| ~~OR~~ | *Disarm From Alarm*. Not used: Herve chose BC + OP (2026-09-25) | User number |
| BC | Burglary Cancel — alarm cancelled by authorized user | User number |
| ~~CR~~ | *Recent Closing* — alarm within 5 min of arming. **Not** "armed"; rejected. | — |

**Evidence gathered (all verified in source, 2026-09-25):**

- **The alarm plugin forwards no user identity** (`~/dev-hlx/plugin-alarm/core/class/alarm.class.php`).
  - `alarmCmd::execute($_options)` receives the Jeedom core's `user_login`/`user_id` but never forwards them.
  - `doAction()` (`:639-670`) substitutes only `#mode#` and `#alarm_trigger#`.
  - Consequence: the user number must be a **configured value**.
- **Disarm order** (`:697-717`).
  - `released` always runs `doAction('release')` first.
  - Then `razImmediate` / `raz` run, **only if** the alarm had fired.
  - Consequence: a command on `release` sees every disarm, and must itself know whether a BA is open.
- **Arming** (`:727-743`, `:115-131`).
  - `activationImmediateOk` fires on **every** successful arm.
  - `activationOk` fires only if no detector was active at arming. After `activationKo` (a door left open) it
    never fires.
  - Consequence: CL belongs on `activationImmediateOk`.
- **Two ways to end a sounding alarm** (`:700-717`, `:812-832`). The "Réinitialisation" tab (`raz`) is an
  action hook, not a command.
  - **Désactiver while sounding:** "Désactivation OK" (`release`) runs, **then** Réinitialisation (`raz`). The
    system ends up disarmed.
  - **Mode change while sounding:** Réinitialisation (`raz`) runs **alone**, with no `release`. The system
    **stays armed**.
  - Consequence: an intrusion can be reset without a disarm. BC is therefore sent in one of two ways: paired
    with OP on a disarm, or alone on a mode-change reset. Two commands, one per hook. Because `release` runs
    first, it purges the table before `raz` looks at it, so no BC is ever duplicated.
- **Ajax evidence** (`plugin-ajaxSystem/core/config/sia_code.json`).
  - Arming is reported as CL (and variants); disarming as OP / OR (and variants).
  - Ajax never uses CR for arming, and never uses BC.

## 2. Impact Analysis

### Epic impact

**Epic 13 — Alarm Event Vocabulary Extension (v1.1):**
- It stays viable. Its goal ("report the end of an alarm") widens to "report the end of an alarm and the
  system's arm/disarm state".
- The stories become:
  - **13-1** (rescoped): end of a burglary alarm. A disarm sends BC then OP; a mode-change reset sends BC
    alone. Both use the user number.
  - **13-2**: BR, stays parked, unchanged.
  - **13-3** (new, backlog): FC/PC cancels for fire/panic. This is Herve's "for later" item.
  - **13-4** (new, backlog): CL on arming and OP on a normal disarm.

**Other epics:**
- None is invalidated.
- Epic 14 (Frigate) is unaffected; BC/CL/OP carry no `media_url`.
- Epic 12's 12-7 is unaffected.

### Story impact — 13-1

| Item | Fate |
|---|---|
| Daemon `BC` support (Task 5: `SiaEventCode`, `_EVENT_SIA_CODES`, `event_type_fr`) | **kept**; `OP` is added alongside |
| `sia_open_alarms` table (Task 3: write, key, dedup, `OPEN_ALARMS_MAX`, TTL) | **kept**. Its purpose shrinks from "which zones to close" to "is a BA open?". FA/PA entries stay recorded for 13-3 |
| Per-zone fan-out, one-zone override, FA/PA debug-skip, account-level fallback (Task 4, AC4/AC5/AC6) | **dropped** |
| `burglaryCancel` command on `raz` (Task 2, AC2) | **replaced** by two commands: `disarm` ("Désarmement") on `release`, and `alarmReset` ("Réinitialisation alarme") on `raz` |
| Tests `test_burglary_cancel_behavior.py` (14), TC-IPC6 (3), stub/label tests | **rewritten** around the two new commands; the table tests (dedup, eviction, TTL, JSON string) are kept |
| Wizard help text, `jeedom-alarm/SKILL.md` wiring note (Task 8) | **rewritten** |
| Design sections in `daemon-design.md` / `php-core-design.md` / `widget-design.md` (Task 1) | **rewritten again** |
| AC8 frame expectation `[#001234|BC 001]` | now **correct**, but for the right reason (user 1, not zone 1) and followed by `[#001234|OP 001]` |
| Open review findings #2 (`siaDC09_update()` empty: existing installs never get new commands) and #4 (EVENT_FAILED T3 wording for a BC) | **carried into 13-1** as tasks |

Nothing is committed yet, so nothing is rolled back in git; the work is reshaped in the working tree.

### Artifact conflicts

| Artifact | Conflict | Change |
|---|---|---|
| `prd.md` §Growth v1.1+ (`:110`) | Says BC is "user cancelled from the abort window", zone-scoped | Rewrite the bullet (see §4.1) |
| `epics.md` Epic 13 (`:2194-2228`) | Story 13.1 still describes BR+BC with zone correlation | Rewrite 13.1; add 13.3 and 13.4 (§4.2) |
| `architecture.md` | No decision record for user-addressed codes / configured user | Add **ADR-18** (§4.3) |
| `internal-docs/design/php-core-design.md` (`:436`, `:535`, `:582`, `:1248-1360`) | Fan-out design, `burglaryCancel` spec | Rewrite the 13.1 section |
| `internal-docs/design/daemon-design.md` (`:1384-1417`) | BC-by-zone narrative | Rewrite: the address field comes from `user_number` for user-addressed codes |
| `internal-docs/design/widget-design.md` (13.1 section) | `event_label` examples by zone | `Annulation (utilisateur 1) : …`, `Désarmement (utilisateur 1) : …` |
| `internal-docs/design/wizard-design.md` | No user-number setting | Step 3 gains "Numéro utilisateur SIA" |
| UX | Wizard gains one field; the help text changes | Covered by wizard-design |
| `sprint-status.yaml` | 13-3 / 13-4 missing | Add both as `backlog`; 13-1 stays `in-progress` |

### Technical impact

- **PHP:**
  - Two new action commands, `disarm` and `alarmReset`, both `subType other`: neither needs a *Titre*.
  - A new `sia_user_number` configuration key (3 digits, default `1`, 1-999).
  - `burglaryCancel` removed from `$actionCmds`. It was never shipped, so no migration is needed.
  - `siaDC09_update()` must now call the command-creation path, so existing installs get the new commands
    (finding #2).
- **IPC:** a new optional payload key `user_number`. The daemon puts it in the address field
  (`_build_event_frame()`, `daemon.py:1667`) for user-addressed codes, reusing the same `:03d` formatting as
  zone numbers → `BC 001`, `OP 001`.
- **Daemon:** `SiaEventCode` adds `'OP'`; `_EVENT_SIA_CODES` maps the IPC `cmd` names to BC / OP.
  - The two frames go out in order through the normal EVENT path: priority 0, retries, CONFIRMED/FAILED.
  - Nothing else changes in SM2.
- **Residual gaps, to be documented:**
  - An installer who wires only one of the two commands loses the other path. Wizard help and SKILL.md must
    say "wire both".
  - A disarm during the trigger delay (before the BA was sent) sends nothing in 13-1. That is correct: the CSR
    never saw an alarm. It becomes OP in 13-4.

## 3. Recommended Approach

**Option 1 — Direct Adjustment**, within Epic 13. Effort **medium**, risk **low**.

- **Option 2 (rollback)** is not needed: nothing is committed, and the daemon half plus the table are reused.
- **Option 3 (MVP review)** is not relevant: Epic 13 is post-MVP (v1.1), and the MVP is untouched.

**Rationale.**
- 13-1 keeps its core value: the CSR learns the alarm is over, and now also that it was a false alarm cancelled
  by a known user.
- Using a configured user number instead of a zone makes every frame DC-03-conformant, and removes the
  fan-out, its fallback and its override: about half of the PHP complexity.
- Splitting CL/OP into 13-4 (Herve's call) keeps 13-1 shippable and field-testable on its own.
  - The seam is clean: 13-1's `disarm` command sends BC+OP when a BA is open, and **nothing** otherwise.
    `alarmReset` is complete in 13-1.
  - 13-4 fills the `else` branch with OP and adds CL.

**Trade-off accepted.** Between 13-1 and 13-4, a normal disarm sends nothing to the CSR. That is the same as
v1.0 today, so it is no regression.

## 4. Detailed Change Proposals

### 4.1 PRD — `prd.md` §Growth Features v1.1+ (`:110`)

OLD:
```
- Restoral and cancel events: BR (Burglary Restore — zone back to normal) and BC (Burglary Cancel — user cancelled from the abort window), so the CSR can close an incident instead of keeping it open (Epic 13 / Story 13.1)
```
NEW:
```
- Restoral and cancel events: BC (Burglary Cancel) followed by OP (Opening Report) when the user disarms during a burglary alarm, and BC alone when the alarm is reset by a mode change, all addressed to a configured SIA user number, so the CSR can close the incident as a user-cancelled false alarm (Epic 13 / Story 13.1); BR (Burglary Restore) parked for lack of a source (Story 13.2); FC/PC cancels for fire/panic (Story 13.3)
- Arm/disarm reporting: CL (Closing Report) on arming, OP (Opening Report) on a normal disarm, same user number (Story 13.4)
```
Rationale: the old bullet encodes the wrong BC semantics, and the scope now includes arm/disarm reporting.

### 4.2 Epics — `epics.md` Epic 13

**Epic intro (`:2196`)**

OLD: "Report the *end* of an alarm, not only its start: Burglary Restore (BR) when a zone returns to normal,
Burglary Cancel (BC) when the user cancels from the abort window. …"

NEW: "Report the *end* of an alarm and the system's arm/disarm state, not only the start of an alarm: BC + OP
when the user disarms during a burglary alarm, BC alone when the alarm is reset by a mode change while staying
armed, CL/OP on arming and a normal disarm, and later BR and the FC/PC
cancels. All of BC/CL/OP are addressed to a **user number** (DC-03), never a zone. The alarm plugin forwards
no user identity to its actions (`alarm.class.php:639-670`), so the number is a single configured value.
v1.0 emits BA/FA/PA only, so a CSR keeps an incident open until an operator calls back."

**Story 13.1 (`:2202-2228`): replace the whole block with**

> ### Story 13.1: Disarm During an Alarm — Burglary Cancel (BC) + Opening Report (OP)
>
> As a monitored Jeedom user,
> I want disarming my alarm while a burglary alarm is open to tell the CSR that user N cancelled it and disarmed
> the system,
> So that the operator stops the emergency procedure instead of calling the police.
>
> **Acceptance criteria:**
>
> - **Given** a `disarm` action command ("Désarmement") wired on the alarm plugin's `release` action, and a
>   configured `sia_user_number` (default 1)
>   **When** the user disarms while at least one BA sent by siaDC09 is still open (`sia_open_alarms`)
>   **Then** exactly two frames are sent, in this order: `[#{account}|BC {user:03d}]` then
>   `[#{account}|OP {user:03d}]`, and the open-alarm table is purged.
> - **And** when no BA is open, `disarm` sends **no** frame (OP is Story 13.4) and logs at debug.
> - **Given** an `alarmReset` action command ("Réinitialisation alarme") wired on the alarm plugin's `raz`
>   action ("Réinitialisation")
>   **When** the alarm is reset by a mode change while sounding (no `release`, the system stays armed) and a BA
>   is open
>   **Then** exactly one `[#{account}|BC {user:03d}]` is sent, and the table is purged.
> - **And** on a normal Désactiver during an alarm (`release` then `raz`), `alarmReset` finds the table
>   already purged by `disarm` and sends **nothing**: the whole sequence produces exactly BC, OP, and never a
>   second BC.
> - **And** the address field is never a zone number, and never empty.
> - **And** `siaDC09_update()` creates both new commands on existing installs without a manual equipment save.
> - **And** `SiaEventCode`, `_EVENT_SIA_CODES` and `error_handler.py` accept BC and OP.
>   - `event_label` reads `Annulation (utilisateur 1) : Confirmée par la centrale`, and the equivalent for OP.
>   - The EVENT_FAILED T3 notification names a failed cancel/disarm, not an "alarm".
> - **And** both frames are ACKed by `192.168.100.15:10002` over TCP, account `001234`, from the real Jeedom UI
>   on `test-jeedom.lehoux.net`. Two checks, both read in the protocol inspector:
>   - trigger a zone, then disarm → BA, BC, OP;
>   - trigger a zone, then change the mode → BA, BC.

**New Story 13.3 (backlog), appended**

> ### Story 13.3: Fire & Panic Cancels (FC / PC) — *backlog*
>
> BC's counterparts for the other alarm families. `sia_open_alarms` already records FA/PA entries for this
> purpose. It needs the DC-03 address-field definition of FC and of the panic cancel code, checked against
> the full table before any code. Blocking question: which alarm-plugin action ends a fire/panic alarm, given
> those are often separate alarm equipments with no delay.

**New Story 13.4 (backlog), appended**

> ### Story 13.4: Arm/Disarm Reporting — Closing (CL) & Opening (OP)
>
> As a monitored Jeedom user,
> I want the CSR to know when my system is armed and disarmed, and by which user,
> So that it can check openings/closings against my schedule.
>
> - **Given** a new `arm` command ("Armement") wired on `activationImmediateOk`
>   **When** the alarm is armed
>   **Then** `[#{account}|CL {user:03d}]` is sent. It must not go on `activationOk`, which never fires after
>   `activationKo`.
> - **And** the `disarm` command from 13.1 sends `[#{account}|OP {user:03d}]` when no BA is open, instead of
>   nothing.
> - **And** CR is never used for arming. It means "Recent Closing", an alarm within 5 min of arming.
> - Open question to settle in the story: report arming with bypassed zones (`activationKo`) differently or not.
> - Real-UI validation on `test-jeedom`: arm, disarm, read CL and OP in the inspector.

### 4.3 Architecture — `architecture.md`: add ADR-18, and add it to `adrsCompleted`

> ### ADR-18 — User-addressed event codes and the configured SIA user *(added 2026-09-25)*
>
> **Context.** DC-03 addresses BC, OP and CL by **user number**, and BA/FA/PA by zone. The Jeedom alarm
> plugin drops the core's `user_login`/`user_id` before running its actions (`alarm.class.php:639-670`).
>
> **Decision.**
> - One configured `sia_user_number` (1-999, default 1, wizard step 3) addresses every user-addressed frame.
> - The IPC payload carries `user_number`. The daemon writes it to the address field with the same `:03d`
>   formatting as zone numbers.
> - BC is sent on the two alarm-plugin hooks that end a sounding alarm:
>   - `disarm` on `release` sends BC→OP;
>   - `alarmReset` on `raz` sends BC alone, for a mode-change reset while the system stays armed.
>   - `release` runs before `raz` (`alarm.class.php:703-712`), so the first to act purges `sia_open_alarms`
>     and the second finds nothing. There is never a duplicate BC.
>
> **Rejected.**
> - Per-zone BC: violates the DC-03 address semantics.
> - Address-less BC: legal DC-09, but CSRs may reject it.
> - Login→user mapping via `lastExecutionUser`: couples us to another plugin's internal cache, and a
>   scenario-driven disarm reports `system`. Revisit only if multi-user reporting is requested.
> - CR for arming: it means Recent Closing.
>
> **Consequences.**
> - `sia_open_alarms` becomes the "is a BA open?" oracle.
> - The dedup relies on the alarm plugin's `release`-before-`raz` order. A test pins our side of it, and the
>   order is cited in the design doc so that a change upstream is recognisable.

### 4.4 Design docs

- **`php-core-design.md` §13.1 (`:1248-1360`):**
  - Replace the fan-out section with the spec of the two commands:
    - `disarm` on `release`: BC→OP plus a purge, or silence when no BA is open;
    - `alarmReset` on `raz`: BC plus a purge, or silence;
    - the `release`-before-`raz` ordering argument.
  - Update `sia_open_alarms` to its reduced role (the table itself is unchanged).
  - `$actionCmds` (`:535`): `burglaryCancel` → `disarm` ("Désarmement") and `alarmReset` ("Réinitialisation
    alarme").
  - Add the `siaDC09_update()` requirement.
- **`daemon-design.md` (`:1384-1417`):**
  - Add `user_number` to the payload and to `EventItem`.
  - Address-field rule: `user_number` for BC/OP (later CL), `zone_number` for BA/FA/PA.
  - `SiaEventCode` adds `'OP'`.
- **`widget-design.md`:** add the two `event_label` examples (`utilisateur N`).
- **`wizard-design.md` step 3:** add the "Numéro utilisateur SIA" field (1-999, default 1), with help text:
  "declare this number to your monitoring centre as the Jeedom user".

### 4.5 Story file — `13-1-burglary-restore-cancel-events.md`

Keep the file key (same precedent as the 2026-09-18 rescope), and make these changes:

- New title.
- New Story statement.
- "Conception retenue" rewritten per §4.4.
- ACs replaced by the 13.1 ACs above. The numbering restarts, and the old ACs are kept struck through under a
  "Rescopée le 2026-09-25" banner for traceability.
- Tasks reset:
  - T1 design docs (redo)
  - T2 `disarm` and `alarmReset` commands plus `sia_user_number` config plus wizard field
  - T3 table (kept `[x]`, its role note updated)
  - T4 `disarm`: BC→OP pair plus purge plus silent-when-no-BA; `alarmReset`: BC plus purge plus silent;
    a test for the `release`-then-`raz` sequence (exactly BC, OP)
  - T5 daemon (BC kept, OP plus `user_number` added)
  - T6 `siaDC09_update()` (finding #2)
  - T7 EVENT_FAILED wording (finding #4)
  - T8 tests rewritten
  - T9 help text / SKILL.md
  - T10 real-UI validation
- The Change Log gets a 2026-09-25 rescope row.

### 4.6 `sprint-status.yaml`

- Update the comment on `13-1-…: in-progress` to the rescope.
- Add `13-3-fire-panic-cancel-events: backlog` and `13-4-arm-disarm-closing-opening-reports: backlog`.
- Recompute the summary from the status lines: total_stories 55→57, stories_backlog 4→6.

## 5. Implementation Handoff

**Scope: Moderate.** The backlog is reorganized: two new stories, one rescoped. The changes stay inside
Epic 13. There is no PM/Architect escalation beyond ADR-18, which is recorded here.

| Who | Does |
|---|---|
| Developer agent (this session, after approval) | Apply §4.1-4.6 to the artifacts, then resume `bmad-dev-story` on the rescoped 13-1 (T1-T9) |
| Herve | Approve this proposal. Tell the CSR which user number is used. Run T10 on `test-jeedom` after the push |

**Success criteria for 13-1:**
- Level 1 is back to 2 failures, level 2 to 6, level 2.5 to 1, with no new ones.
- A disarm during a BA yields exactly BC 001 → OP 001, and a disarm without a BA yields nothing.
- A mode-change reset during a BA yields exactly one BC 001.
- Both frames are ACKed by the real receiver, and are visible in the protocol inspector from the real Jeedom UI.
