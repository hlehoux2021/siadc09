---
story_id: "10-3"
story_key: "10-3-widget-live-refresh-on-command-update"
epic_id: "epic-10"
epic_name: "Dashboard Widget"
status: "in-progress"
created: "2026-09-18"
analysis_completed: "2026-09-18"
---

# Story 10.3: Widget Live Refresh on Command Update

Status: in-progress

## Story

As a Jeedom user watching the siaDC09 tile on my dashboard,
I want the badge and event label to update by themselves when the daemon pushes new state,
So that I see the current connection health and the last alarm result without manually
reloading the page.

## Context — Field Observations (2026-09-18)

Reported by Herve during live use on the Jeedom test host; recorded in
`12-6-widget-debug-ui-rendering.md` → "Field Observations — 2026-09-18". Two symptoms,
one root cause:

1. The dashboard tile never refreshes on its own — a full page reload is required to see
   any state change.
2. After the daemon logged `[2026-09-17 21:58:48] INFO : Centrale confirmée — alarme BA
   transmise (zone: Zone1)`, the tile label stayed on "OK" instead of showing the confirmed
   event. The daemon **did** push the updated `event_label` (`_event_label_from_sm2()` →
   "Confirmé", `daemon.py:1365/1411/1457/1502/1532/1552`); the value reached the DB but the
   tile never re-rendered.

### Root cause

- `core/template/dashboard/siaDC09.html:19,25` renders `#supervision_label#` and
  `#event_label#` as plain interpolated text — no `cmdValue` class, no `data-cmd_id`
  attribute. Jeedom's native `cmd::update` websocket handler only updates in place DOM nodes
  bound to the changed command, so it has nothing to touch. The only inline JS
  (`siaDC09.html:31-79`) is the one-shot stale check from story 10-2; it does not subscribe
  to `cmd::update`.
- `docs/design/widget-design.md:20-22,66-70` assumed the full-tile re-render path fires
  automatically ("no custom JS required"); epics.md Story 10.1 AC accepted **reload-only**
  refresh. Live push was never actually wired.
- Secondary: `toHtml()` reads INFO values via `execCmd()` (`siaDC09.class.php:589-591`),
  contradicting `widget-design.md:199-202` which mandates `getValue()`. **Note the history:**
  story 10-2 review finding **F1 intentionally changed `getValue()` → `execCmd()`**
  ("for cached state"). This story must resolve that contradiction deliberately, not silently
  flip it back — see Task 3 + Dev Notes.

## Acceptance Criteria

1. **Live badge refresh:** Given the tile is visible on the dashboard and the daemon pushes
   a `supervision_state` change (e.g. HEALTHY→DEGRADED), the badge color and
   `supervision_label` text update **without a page reload**, within one supervision cycle
   of the push.

2. **Live event label refresh:** Given the tile is visible and the daemon confirms an alarm
   (SM2 CONFIRMED, pushing `event_label`), the event label line updates to the confirmed
   value ("Confirmé") **without a page reload**. This directly reproduces and fixes the
   "reste à OK" observation.

3. **No regression to stale detection:** The story 10-2 one-shot stale check still fires
   (grey `text-muted` + "Données non disponibles" after `3 × supervision_interval`), and the
   live-refresh path must not re-arm a green badge over a genuinely stale tile.

4. **Value-source consistency:** The value shown by the initial server render, the live
   update, and the stale check are mutually consistent — no flip between a stale `execCmd()`
   live-fetch and the DB value. The `getValue()`-vs-`execCmd()` contradiction (10-2 F1 vs
   widget-design.md:199-202) is resolved and the chosen direction is documented in the Dev
   Agent Record with rationale.

5. **Mobile identical:** `core/template/mobile/siaDC09.html` receives the identical change
   and behaves the same. `diff` of the two templates is empty.

6. **No dashboard JS-file dependency:** The refresh logic lives in the inline template
   `<script>` (or via `data-cmd_id`-bound spans), NOT in `desktop/js/siaDC09.js` — per
   10-2 Dev Notes, that file is not loaded on the dashboard.

7. **Regression suite green:** `php -l` passes on all PHP files; `python3 -m pytest
   tests/level1/` shows no new failures beyond the known baseline (compare against the
   2 known-failing tests, per memory `level1-test-baseline-failures`).

## Tasks / Subtasks

- [x] Task 1: Confirm the live-update mechanism Jeedom actually uses on the dashboard (AC: 1, 6)
  - [ ] 1.1 On the test host, open the dashboard with DevTools, trigger a state change
        (stop simulator → DEGRADED), and observe whether Jeedom fires a `cmd::update` and
        whether it re-renders the tile or only updates `data-cmd_id` nodes. Record findings.
        **(Mechanism confirmed by source reading; DevTools-on-host observation folded into
        Task 6 live validation.)**
  - [x] 1.2 Decide the binding strategy from evidence:
        (a) emit `<span class="cmdValue" data-cmd_id="#..._id#">` for label + event so Jeedom's
        native updater targets them, or
        (b) subscribe to `cmd::update` inside the inline script and re-fetch via
        `jeedom.eqLogic.byId({id, getCmdState:1})` then patch badge/label in place.

- [x] Task 2: Implement live refresh in the dashboard template (AC: 1, 2, 3, 6)
  - [x] 2.1 Apply the chosen binding for `supervision_label` and `event_label`.
  - [x] 2.2 If badge color must follow `supervision_state`, map the pushed numeric value to
        the badge class client-side (reuse the toHtml mapping: 2→success, 1→warning,
        else→danger, null→muted).
  - [x] 2.3 Ensure the stale check (10-2) and the live update cooperate — live update must
        not clear a stale-grey badge; stale check must not fight a fresh push.

- [x] Task 3: Resolve the value-source contradiction in `toHtml()` (AC: 4)
  - [x] 3.1 Decide `getValue()` vs `execCmd()` at `siaDC09.class.php:589-591` with rationale;
        reconcile 10-2 review F1 against widget-design.md:199-202 and the 12-6 KNOWN-BUG note.
  - [x] 3.2 Apply and document the decision in the Dev Agent Record.

- [x] Task 4: Mirror to mobile template (AC: 5)
  - [x] 4.1 Copy the dashboard template to `core/template/mobile/siaDC09.html`.
  - [x] 4.2 `diff` the two — must be byte-for-byte identical.

- [x] Task 5: Regression + syntax (AC: 7)
  - [x] 5.1 `php -l core/class/siaDC09.class.php` and `find core/ desktop/ -name "*.php" | xargs -n1 php -l`.
  - [x] 5.2 `python3 -m pytest tests/level1/` — compare against the known 2-failure baseline.

- [ ] Task 6: Live validation on the Jeedom test host (AC: 1, 2, 3, 5) — **awaiting push + Herve's UI validation**
  - [ ] 6.1 Deploy (git push then pull on the host — code arrives by git pull).
  - [ ] 6.2 With the dashboard open and untouched: trigger DEGRADED, then recovery, then an
        alarm confirmation. **Verify** badge + labels update live, no reload. Screenshot each.
  - [ ] 6.3 Verify the "reste à OK" scenario is fixed: event label moves off "OK" to the
        confirmed value on its own.
  - [ ] 6.4 Verify stale-grey still appears after daemon stop > 3× interval (no live-refresh
        interference).

## Dev Notes

### Prior art — read before implementing
- `_bmad-output/implementation-artifacts/10-2.md` — the inline-script pattern, the
  `jeedom.eqLogic.byId({id, getCmdState:1})` call (10-2 review F2/F3 replaced the
  non-existent `jeedom.cmd.getStatsByEqLogicId`), the Safari-safe date parse, and the
  "What NOT To Do" list. **Note 10-2 review F1 (`getValue()`→`execCmd()`) — Task 3 revisits it.**
- `docs/design/widget-design.md:20-22,66-70,199-202` — the (partly incorrect) live-update
  and value-source assumptions this story corrects.
- `12-6-widget-debug-ui-rendering.md` "Field Observations — 2026-09-18" — the source report.

### Key files
| File | Change |
|------|--------|
| `core/template/dashboard/siaDC09.html` | live-refresh binding for label + event_label |
| `core/template/mobile/siaDC09.html` | identical copy |
| `core/class/siaDC09.class.php:578-618` | `toHtml()` — value-source decision, any new `data-cmd_id` placeholders |

### Constraints
- Dashboard has no access to `desktop/js/siaDC09.js` (10-2). Inline template script or
  native `data-cmd_id` binding only.
- Multiple siaDC09 tiles may coexist — keep the IIFE scoping from 10-2.
- Test host & deploy: see memory `jeedom-test-host-deploy` (push before validating).
- Daemon is the merge hot-spot across parallel agents (memory
  `parallel-agents-daemon-conflict`) — but this story touches the PHP/template layer, not
  `daemon.py`, so conflict risk is low.

## Dev Agent Record

### Implementation Plan

Root cause (Task 1) confirmed by **direct source reading**, not yet by DevTools on the
host — that observation is deferred to the Task 6 live validation. The template rendered
`#supervision_label#` / `#event_label#` as plain interpolated text with no `cmdValue`
class or `data-cmd_id`, so Jeedom's native `cmd::update` websocket handler (which only
writes the pushed value in place into the DOM node bound to the changed command) had no
node to touch. That is why a full page reload was required, and why the event line stayed
on "OK" after the daemon pushed "Confirmé" — the value reached the DB (via
`checkAndUpdateCmd`) but nothing in the DOM was bound to receive it.

### Binding strategy chosen (Task 1.2 → option a, extended)

- **Text labels** (`supervision_label`, `event_label`): native `class="cmdValue"
  data-cmd_id="#..._id#"` spans. Jeedom writes the pushed value straight into them — this
  is the direct fix for AC1 (label) and AC2 (the "reste à OK" event line).
- **Badge colour** follows a *numeric* `supervision_state` (2→success, 1→warning,
  else→danger, null→muted) — a mapping Jeedom cannot express natively. Solution: a
  **hidden** `cmdValue`-bound `supervision_state` span + a `MutationObserver` that recolours
  `.siaDC09-badge` whenever Jeedom writes a new value into that span. Observing the *result*
  of the native update (not an internal event name) is robust to Jeedom internals and fully
  testable in jsdom. A live push also proves freshness, so the observer clears any
  `text-muted` stale-grey the 10-2 one-shot check applied (AC3). The stale check writes
  label text + badge classList (neither is observed), so there is no feedback loop.

### Value-source decision (Task 3, AC4): `execCmd()` → `getValue()`

Reverted `siaDC09.class.php` to `getValue()` for all three INFO reads. **Rationale,
reconciling 10-2 review F1 against `widget-design.md:199-202`:** 10-2 F1 switched to
`execCmd()` to get "cached state" for freshness at render time. With this story, freshness
is delivered client-side by the `cmdValue` binding, so the server render only needs the
last persisted value — which is exactly what `getValue()` returns, with no side effects
and no re-running of the full command path on every dashboard paint. `getValue()` also
reads precisely what the daemon's `checkAndUpdateCmd` wrote, guaranteeing the initial
render, the live update, and the stale check are mutually consistent (AC4). This restores
the behaviour mandated by `widget-design.md:199-202`; 10-2 F1 is superseded and documented
here rather than silently flipped.

Added placeholders `#supervision_state_id#`, `#supervision_label_id#`, `#event_label_id#`
(from `$cmd->getId()`) and `#supervision_state_value#` (the numeric state, '' when null,
seeds the hidden mirror so the observer has a correct starting point).

### Testing

TDD red→green. New DOM harness `tests/fixtures/widget_dom_harness.js` renders the real
template with `#placeholder#` substitution into jsdom, executes the inline `<script>`, and
drives live pushes by writing `span.innerHTML = value` into the `cmdValue` spans — exactly
how Jeedom mutates them — then asserts on resulting DOM (badge class, label/event text,
title). `tests/level1/test_widget_live_refresh.py` (9 tests) covers AC1 (label bound;
state 1/0/2 → warning/danger/success), AC2 (event bound, "OK"→"Confirmé"), AC3 (stale-grey
still fires at 600s/interval 60; live push clears grey; fresh 30s keeps server badge), and
AC5 (dashboard/mobile byte-identical). Red phase: 6 failed / 3 passed (no bindings yet).
Green phase: **9 passed**.

### Completion Notes

- `php -l` clean on `siaDC09.class.php` and across all `core/`+`desktop/` PHP.
- `node --check` clean on the harness.
- Full `tests/level1/` = **2 failed / 1068 passed** — the 2 failures are the known
  pre-existing baseline (`test_connection_test::test_run_connection_test_preset_crc_format_used`,
  `test_wizard_config_key_consistency::test_csr_provider_key_in_python`), unrelated to this
  story. No new failures.
- **Task 6 (live UI validation on test-jeedom.lehoux.net) is NOT done** — per memory
  `jeedom-ui-validation-over-reflection`, acceptance requires validating on the real
  dashboard, and per `jeedom-test-host-deploy` the code must be pushed first so the host
  can `git pull`. Awaiting Herve's go-ahead to push, then live verification of: badge/label
  live refresh on DEGRADED+recovery, event line moving off "OK" to "Confirmé" unaided, and
  stale-grey still appearing after a >3×interval daemon stop.

### File List

| File | Change |
|------|--------|
| `core/template/dashboard/siaDC09.html` | Added `cmdValue`/`data-cmd_id` bindings for label + event; hidden state-mirror span + `MutationObserver` for live badge recolour; kept the 10-2 one-shot stale check. |
| `core/template/mobile/siaDC09.html` | Byte-for-byte copy of the dashboard template. |
| `core/class/siaDC09.class.php` | `toHtml()`: `execCmd()` → `getValue()` (reverts 10-2 F1); added `#supervision_state_id#`, `#supervision_label_id#`, `#event_label_id#`, `#supervision_state_value#` placeholders. |
| `tests/fixtures/widget_dom_harness.js` | New jsdom harness rendering the real template and driving live `cmdValue` pushes. |
| `tests/level1/test_widget_live_refresh.py` | New — 9 DOM tests for AC1/AC2/AC3/AC5. |

## Change Log

| Date | Change |
|------|--------|
| 2026-09-18 | Story created from Herve's 2026-09-18 field observations on 12-6 (widget never auto-refreshes; "reste à OK" after SM2 CONFIRMED). |
| 2026-09-18 | Implemented live refresh (cmdValue bindings + hidden state mirror + MutationObserver), reverted toHtml to `getValue()`, mirrored to mobile. New DOM harness + 9 tests, all green; level-1 at the known 2-failure baseline. Task 6 (live host UI validation) pending push + Herve's verification. |
