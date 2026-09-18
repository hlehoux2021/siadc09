# Story 9.1: Status Badge & Error Panel

> **Amendment 2026-09-18 — SM2 event badge added to Diagnostic tab (AC11, Task 9).**
> The Diagnostic tab showed only the SM1 (`supervision_state`/`supervision_label`) badge; `getDiagnosticData`
> already returned `event_state`/`event_label` (SM2 — see story 9-1 Task 2.3) but nothing rendered them.
> Added a second badge row below the SM1 badge, wired to a new `_siaDC09_eventBadgeColors` map and
> `siaDC09_renderEventBadge()` function. Status reopened `done → in-progress → review` for AC11/Task 9
> only; AC1–AC10 stay done.

Status: review

## Story

As a Jeedom user troubleshooting a connection issue,
I want to see the current connection status and recent errors in a diagnostic tab,
So that I can understand what went wrong without opening Jeedom logs.

## Acceptance Criteria

1. **Given** equipment page with `sia_wizard_step == 4`, **When** page loads, **Then** a "Diagnostic" tab appears after the "Commandes" tab with a stethoscope icon.

2. **Given** Diagnostic tab opened, **When** badge renders, **Then** color coding matches `supervision_state`:
   - Green (●): `supervision_state=2` (HEALTHY)
   - Orange (●): `supervision_state=1` (DEGRADED/INITIALIZING)
   - Red (●): `supervision_state=0` (NO_NETWORK/STOPPED)

3. **And** the `supervision_label` string is displayed inline next to the badge dot.

4. **Given** Diagnostic tab opened, **When** error panel renders, **Then** it shows up to 10 most recent errors from `sia_last_errors` config key, newest first.

5. **And** each error row displays: timestamp (HH:MM:SS), tier badge (T1 blue / T2 orange / T3 red), error title, short description.

6. **And** empty state shows: "Aucune erreur enregistrée" (grey italic).

7. **Given** Diagnostic tab, **When** user clicks "Actualiser", **Then** a single AJAX call (`getDiagnosticData`) refreshes both badge and error panel. Button is disabled for 2 seconds after click.

8. **Given** Diagnostic tab, **When** user clicks "Vider" on error panel, **Then** `clearDiagnosticData` AJAX clears `sia_last_errors` config key to `[]` and re-renders empty state.

9. **Given** `sia_wizard_step < 4`, **Then** Diagnostic tab is NOT rendered.

10. **Given** Diagnostic tab, **Then** layout uses Bootstrap 3 panel styling consistent with Jeedom.

11. **Given** Diagnostic tab opened, **When** badge renders, **Then** a second badge shows SM2 `event_state`/`event_label` below the SM1 badge, with color coding:
   - Grey (●): `event_state=0` (IDLE) or unknown/NaN state
   - Green (●): `event_state=1` (CONFIRMED)
   - Red (●): `event_state=2` (FAILED)
   - Orange (●): `event_state=3` (PENDING)

## Tasks / Subtasks

- [x] Task 1 — Add Diagnostic tab HTML to `siaDC09.php` (AC: 1, 9, 10)
  - [x] 1.1 Add `<li>` tab header with stethoscope icon after Commandes tab — hidden by default, shown via JS when step >= 4
  - [x] 1.2 Add `<div role="tabpanel" id="diagnosticTab">` with status badge panel + error panel + empty protocol inspector placeholder
  - [x] 1.3 Tab visibility controlled via `siaDC09_initDiagnosticTab(wizardStep)` in JS (called from `printEqLogic`)

- [x] Task 2 — Implement `getDiagnosticData` AJAX action (AC: 7)
  - [x] 2.1 Add `getDiagnosticData` action in `siaDC09.ajax.php`
  - [x] 2.2 Read `supervision_state` and `supervision_label` from INFO commands via eqLogic `getCmd('info', ...)->execCmd()`
  - [x] 2.3 Read `event_state` and `event_label` from INFO commands
  - [x] 2.4 Read `sia_last_errors` from `config::byKey('sia_last_errors', 'siaDC09', '[]')`
  - [x] 2.5 Read `sia_last_messages` from `config::byKey('sia_last_messages', 'siaDC09', '[]')`
  - [x] 2.6 Return combined JSON: `{supervision_state, supervision_label, event_state, event_label, errors, messages}`

- [x] Task 3 — Implement `clearDiagnosticData` AJAX action (AC: 8)
  - [x] 3.1 Add `clearDiagnosticData` action in `siaDC09.ajax.php`
  - [x] 3.2 Accept `target` param: `errors` → `config::save('sia_last_errors', '[]', 'siaDC09')`, `messages` → `config::save('sia_last_messages', '[]', 'siaDC09')`
  - [x] 3.3 Return `{success: true}`

- [x] Task 4 — Implement Diagnostic JS: badge rendering (AC: 2, 3)
  - [x] 4.1 Add `siaDC09_loadDiagnosticData()` function — calls `getDiagnosticData` AJAX
  - [x] 4.2 Add `siaDC09_renderBadge(supervision_state, supervision_label)` — sets dot color class + label text
  - [x] 4.3 Call `siaDC09_loadDiagnosticData()` on Diagnostic tab activation (`shown.bs.tab` event)

- [x] Task 5 — Implement Diagnostic JS: error panel rendering (AC: 4, 5, 6)
  - [x] 5.1 Add `siaDC09_renderErrors(errors)` — builds error rows or empty state
  - [x] 5.2 Tier badge rendering: `T1`=`label-info`, `T2`=`label-warning`, `T3`=`label-danger`
  - [x] 5.3 Timestamp formatting: parse ISO string → display `HH:MM:SS` local time

- [x] Task 6 — Implement refresh and clear buttons (AC: 7, 8)
  - [x] 6.1 "Actualiser" click → disable 2s → call `siaDC09_loadDiagnosticData()` → re-render all
  - [x] 6.2 "Vider" (errors) click → call `clearDiagnosticData` with `target=errors` → re-render empty state

- [x] Task 7 — Write Level 1 tests (AC: all)
  - [x] 7.1 Test: PHP syntax check passes for all modified PHP files
  - [x] 7.2 Test: `getDiagnosticData` AJAX action structure (verify return keys)
  - [x] 7.3 Test: `clearDiagnosticData` AJAX action for both targets
  - [x] 7.4 Test: Diagnostic tab HTML only rendered when step >= 4 (grep PHP guard)
  - [x] 7.5 Test: JS badge color mapping logic (green/orange/red for state 2/1/0)
  - [x] 7.6 Test: JS error panel renders correct tier badge classes
  - [x] 7.7 Test: JS Actualiser button rate-limit (disabled 2000ms)

- [x] Task 8 — Run full regression suite and PHP syntax checks

- [x] Task 9 — SM2 event badge on Diagnostic tab (AC: 11) — amendment 2026-09-18
  - [x] 9.1 Add `_siaDC09_eventBadgeColors` map (0=grey, 1=green, 2=red, 3=orange) in `siaDC09.js`
  - [x] 9.2 Add `siaDC09_renderEventBadge(eventState, eventLabel)` — sets dot color + label text, falls back to grey on unknown/NaN state
  - [x] 9.3 Call `siaDC09_renderEventBadge(result.event_state, result.event_label)` in `siaDC09_loadDiagnosticData()` AJAX success handler, alongside the existing SM1 `siaDC09_renderBadge` call
  - [x] 9.4 Add second badge markup (`#siaDC09_eventBadgeDot` / `#siaDC09_eventBadgeLabel`) below the SM1 badge in `siaDC09_statusPanel`, `desktop/php/siaDC09.php`
  - [x] 9.5 Extend `js_dom_harness.js` DOM template + `resetDOM()` with the new element IDs
  - [x] 9.6 Write Level 1 tests: `TestRenderEventBadge` (8 tests — state 0/1/2/3, unknown state, NaN state, label text, empty label)

## Dev Notes

### Architecture Constraints

- **Tab location:** Third tab in equipment page, after "Commandes" — only visible when `sia_wizard_step >= 4` (wizard complete). [Source: docs/design/debug-ui-design.md#Tab-integration]
- **Single AJAX call pattern:** `getDiagnosticData` returns ALL diagnostic data (badge + errors + messages) in one call. All panels refresh together. [Source: docs/design/debug-ui-design.md#Task-5c.4]
- **Plugin-level config keys:** `sia_last_errors` and `sia_last_messages` are stored via `config::byKey(..., 'siaDC09')` — NOT eqLogic configuration. This avoids triggering `postSave()`. [Source: docs/design/debug-ui-design.md#Task-5c.5]
- **No auto-refresh:** All panels are manual-only. No `setInterval`, no WebSocket, no polling. [Source: docs/design/debug-ui-design.md#Task-5c.4]
- **Bootstrap 3 panels:** Jeedom 4.x uses Bootstrap 3. Use `panel panel-default`, `panel-heading`, `panel-body`. Do NOT use Bootstrap 4/5 classes.
- **AJAX authentication:** All actions go through the existing `siaDC09.ajax.php` file which already has `isConnect('admin')` + `ajax::init()` at the top — no per-action auth needed.

### Existing Code to Extend (DO NOT reinvent)

**`desktop/php/siaDC09.php`** (lines 86–90): Existing tab `<ul>` — add the Diagnostic `<li>` after the Commandes tab `<li>`. The entire tab structure already exists; just add a third tab.

**`desktop/js/siaDC09.js`**: Add diagnostic functions AFTER the existing `addCmdToTable` function (end of file, before the closing). Follow the existing naming convention: `siaDC09_` prefix for all functions.

**`core/ajax/siaDC09.ajax.php`**: Add new `if (init('action') == '...')` blocks BEFORE the final `throw new Exception(...)`. Follow the exact pattern of existing actions (`testConnection`, `getZones`, `getCameraCommands`).

**`core/class/siaDC09.class.php`** (line 412–456): Already implements `error_update` and `message_trace` callbacks writing to `sia_last_errors` and `sia_last_messages`. The data is already being persisted — this story just reads it.

### Data Structures

**`sia_last_errors`** JSON array (max 10 entries, newest first):
```json
[{
  "code": "SUPERVISION_DISCONNECTED",
  "message": "Supervision perdue — 3 cycles consécutifs sans réponse",
  "timestamp": "2026-05-18T14:32:11+02:00",
  "context": {"strike": 3, "last_ack": "14:29:00"},
  "count": 1
}]
```

**`sia_last_messages`** JSON array (max 50 entries, newest first): Ring buffer of SIA dialogs — structure irrelevant for this story (rendered in story 9-2).

**INFO commands** (already created by `postSave()` in siaDC09.class.php):
- `supervision_state`: numeric (0/1/2)
- `supervision_label`: string (French human-readable)
- `event_state`: numeric (0/1/2/3)
- `event_label`: string (French human-readable)

### Reading INFO Command Values in AJAX

The AJAX handler reads INFO command current values like this:
```php
$eqLogic = siaDC09::_getAutoEquipment(); // private — need alternative
// Actually: use eqLogic::byType('siaDC09')[0] as already done in testConnection
$stateCmd = $eqLogic->getCmd('info', 'supervision_state');
$supervisionState = $stateCmd ? (int)$stateCmd->execCmd() : 1;
```

**IMPORTANT:** Use the same pattern as `testConnection` action (line 29–34 in `siaDC09.ajax.php`): `eqLogic::byType('siaDC09')` then `$eqLogics[0]`.

### Diagnostic Tab HTML Structure

Per debug-ui-design.md, the tab content should be:
```html
<div role="tabpanel" class="tab-pane" id="diagnosticTab">
  <!-- Status badge -->
  <div class="panel panel-default" id="siaDC09_statusPanel">
    <div class="panel-body">
      <span class="badge badge-lg" id="siaDC09_badgeDot" style="font-size:1.5em;">●</span>
      <span id="siaDC09_badgeLabel"></span>
    </div>
  </div>
  <!-- Error panel -->
  <div class="panel panel-default" id="siaDC09_errorsPanel">
    <div class="panel-heading">
      Dernières erreurs
      <button class="btn btn-xs btn-danger pull-right" id="siaDC09_errorsClear" style="margin-left:5px;">Vider</button>
      <button class="btn btn-xs btn-default pull-right" id="siaDC09_errorsRefresh">Actualiser</button>
    </div>
    <div class="panel-body" id="siaDC09_errorsList"></div>
  </div>
  <!-- Protocol inspector (placeholder for story 9-2) -->
  <div class="panel panel-default" id="siaDC09_inspectorPanel">
    <div class="panel-heading">
      Inspecteur de protocole
      <button class="btn btn-xs btn-danger pull-right" id="siaDC09_inspectorClear" style="margin-left:5px;">Vider</button>
      <button class="btn btn-xs btn-default pull-right" id="siaDC09_inspectorRefresh">Actualiser</button>
    </div>
    <div class="panel-body" id="siaDC09_inspectorList">
      <em class="text-muted">Aucun échange SIA enregistré</em>
    </div>
  </div>
</div>
```

### Badge Color CSS

Use inline styles (Jeedom convention for plugin-specific coloring):
- State 2: `color: #5cb85c` (Bootstrap success green)
- State 1: `color: #f0ad4e` (Bootstrap warning orange)
- State 0: `color: #d9534f` (Bootstrap danger red)

### Button Rate Limit Pattern

```js
$('#siaDC09_errorsRefresh').on('click', function() {
  var $btn = $(this)
  if ($btn.attr('disabled')) return
  $btn.attr('disabled', true)
  siaDC09_loadDiagnosticData()
  setTimeout(function() { $btn.removeAttr('disabled') }, 2000)
})
```

### Tier Classification (for display)

Map error `code` to tier for badge display:
- T1: `SUPERVISION_TIMEOUT`, `SUPERVISION_NAK`
- T2: `BAD_CSR_RESPONSE`
- T3: `SUPERVISION_DISCONNECTED`, `EVENT_FAILED`, `TRANSPORT_PERMANENT`

This mapping is defined in `error-handler-design.md` and the `error_handler.py` module. The JS should derive the tier from the code string using a simple lookup object.

### Testing Strategy

**Level 1 tests only** (no Jeedom instance required):
- PHP syntax: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`
- Python tests: `python3 -m pytest tests/level1/`
- JS logic tests: test the badge color mapping, tier classification, and button disable logic by parsing the JS source and verifying patterns exist

Follow the same testing patterns used in stories 8-1/8-2/8-3 — see `tests/level1/test_php_eqlogic_stub.py` for PHP structure testing via regex and `tests/level1/test_wizard_js_logic.py` for JS logic testing.

### Scope Boundaries

**IN SCOPE (this story):**
- Diagnostic tab structure (all three panel shells)
- Status badge (rendering + AJAX data fetch)
- Error panel (rendering + clear)
- `getDiagnosticData` AJAX endpoint (returns ALL data including messages)
- `clearDiagnosticData` AJAX endpoint (both targets)
- "Actualiser" button wiring (refreshes all panels)

**OUT OF SCOPE (story 9-2):**
- Protocol inspector row rendering (collapsed/expanded)
- `decodeFrame` AJAX endpoint and subprocess
- Frame field-by-field decryption display
- Clipboard copy button for raw hex

**OUT OF SCOPE (story 9-3):**
- Integration testing with live daemon
- End-to-end flow: trigger error → see in panel

### Previous Story Learnings (from 8-3)

- Always verify PHP syntax after changes: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`
- The `printEqLogic` function in JS is the entry point when equipment page loads — use it to detect step and initialize diagnostic tab
- Test files follow pattern: `tests/level1/test_<feature>.py`
- Keep JS handler patterns consistent with existing code (jQuery event delegation, `$(this).attr('disabled')` guard)

### Project Structure Notes

- PHP tab HTML: `desktop/php/siaDC09.php` — inline within existing template
- JS functions: `desktop/js/siaDC09.js` — append to end of file
- AJAX handlers: `core/ajax/siaDC09.ajax.php` — before final `throw`
- Tests: `tests/level1/test_diagnostic_tab.py` (new file)

### References

- [Source: docs/design/debug-ui-design.md — Task 5c.1, 5c.2, 5c.4, 5c.5]
- [Source: docs/design/php-core-design.md — Task 2.10 (AJAX skeleton)]
- [Source: _bmad-output/planning-artifacts/epics.md — Epic 9, Story 9.1]
- [Source: core/class/siaDC09.class.php — error_update/message_trace callbacks, lines 411–457]
- [Source: desktop/php/siaDC09.php — existing tab structure, lines 86–90]
- [Source: core/ajax/siaDC09.ajax.php — existing AJAX pattern]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

None — implementation proceeded without errors.

### Completion Notes List

- Tab visibility uses JS-based show/hide on `<li>` rather than PHP server-side guard, since `printEqLogic` loads wizard step dynamically
- Both AJAX endpoints (`getDiagnosticData` + `clearDiagnosticData`) added in a single block before the final `throw`
- `getDiagnosticData` returns all data in one call (badge + errors + messages) per single-AJAX-call pattern
- Inspector panel placeholder included with working Actualiser/Vider buttons (clearing `messages` target)
- Data loads on `shown.bs.tab` event — no polling, no auto-refresh
- 42 Level 1 tests written covering all ACs; full suite (863 tests) passes with zero regressions

**Amendment 2026-09-18 (Task 9, AC11 — SM2 event badge):** `getDiagnosticData` already returned
`event_state`/`event_label` (Task 2.3, original scope) but the Diagnostic tab never rendered them —
only the SM1 badge existed. Added a second badge row, reusing the SM1 `_siaDC09_badgeColors` pattern
but as its own `_siaDC09_eventBadgeColors` map, since SM2 semantics invert SM1's good/bad polarity
(SM1: 2=good/0=bad; SM2: 1=good/2=bad) — sharing one map would have required a state-remapping layer
for no benefit. New color convention (no prior spec existed): IDLE(0)=grey `#777777`, CONFIRMED(1)=green
`#5cb85c`, FAILED(2)=red `#d9534f`, PENDING(3)=orange `#f0ad4e`; unknown/NaN state falls back to grey.
TDD RED→GREEN: 8 new tests in `TestRenderEventBadge` (`tests/level1/test_diagnostic_js_dom.py`) confirmed
failing (function not found) before implementation, then passing after. Full Level 1 suite: 1077 passed,
2 failed — identical to the pre-existing baseline (`test_run_connection_test_preset_crc_format_used`,
`test_csr_provider_key_in_python`, both unrelated to this change) via git-stash diff comparison; net +8
passing, 0 regressions. `php -l desktop/php/siaDC09.php` clean.

### File List

| File | Action | Reason |
|------|--------|--------|
| `desktop/php/siaDC09.php` | UPDATE | Add Diagnostic tab `<li>` + tabpanel with badge, errors, inspector panels |
| `desktop/js/siaDC09.js` | UPDATE | Add `siaDC09_initDiagnosticTab`, `siaDC09_loadDiagnosticData`, `siaDC09_renderBadge`, `siaDC09_renderErrors`, `siaDC09_formatTimestamp`, refresh/clear handlers |
| `core/ajax/siaDC09.ajax.php` | UPDATE | Add `getDiagnosticData` + `clearDiagnosticData` AJAX actions |
| `tests/level1/test_diagnostic_tab.py` | NEW | 42 Level 1 tests for diagnostic tab (PHP syntax, AJAX structure, JS logic) |
| `desktop/php/siaDC09.php` | UPDATE (amendment 2026-09-18) | Add SM2 event badge markup (`#siaDC09_eventBadgeDot` / `#siaDC09_eventBadgeLabel`) below the SM1 badge |
| `desktop/js/siaDC09.js` | UPDATE (amendment 2026-09-18) | Add `_siaDC09_eventBadgeColors` map + `siaDC09_renderEventBadge()`; wire into `siaDC09_loadDiagnosticData()` |
| `tests/fixtures/js_dom_harness.js` | UPDATE (amendment 2026-09-18) | Add SM2 badge element IDs to DOM template + `resetDOM()` |
| `tests/level1/test_diagnostic_js_dom.py` | UPDATE (amendment 2026-09-18) | Add `TestRenderEventBadge` (8 tests) |

### Change Log

- 2026-05-18: Story 9-1 implementation complete — all 8 tasks done, 42 tests passing, 863 total Level 1 tests green
- 2026-09-18: **Amendment — SM2 event badge on Diagnostic tab (AC11, Task 9).** Reopened `done → in-progress`. Wired the already-fetched `event_state`/`event_label` into a second badge row using a new `_siaDC09_eventBadgeColors` map + `siaDC09_renderEventBadge()`. 8 new Level 1 tests (`TestRenderEventBadge`), TDD RED→GREEN. Full suite: 1077 passed / 2 failed, identical to pre-existing baseline (0 regressions). `php -l` clean. Status `in-progress → review`.

### Review Findings

- [ ] [Review][Decision] **D1 — 9-2 scope code shipped in 9-1** — `decodeFrame` AJAX action (60+ lines in `core/ajax/siaDC09.ajax.php`), `siaDC09_renderMessages`, `siaDC09_renderFrameDetail`, `siaDC09_buildHexButtons`, `siaDC09_buildFieldTable`, `siaDC09_copyHexFallback`, and `_siaDC09_decodeCache` are all explicitly OUT OF SCOPE per story 9-1 spec. `siaDC09_loadDiagnosticData()` also calls `siaDC09_renderMessages()` (live cross-story coupling). Options: (a) keep as-is since 9-2 code is already written and working; (b) strip 9-2 code and mark for reintroduction in 9-2; (c) formally close 9-1 and 9-2 together and skip separate 9-2 review.

- [ ] [Review][Decision] **D2 — AC 9: tab present-but-hidden vs. not-rendered** — The diagnostic tab HTML is always emitted by `siaDC09.php` (with `style="display:none;"`), shown/hidden via JS. The spec says "Diagnostic tab is NOT rendered" for `wizard_step < 4`. Dev intentionally chose JS show/hide over PHP conditional. Diagnostic panel structure is in DOM for all users, visible via browser devtools. Flag for explicit acceptance.

- [ ] [Review][Decision] **D3 — AC 5: `err.code` raw Python enum shown as "error title"** — `siaDC09_renderErrors()` shows `err.code` (e.g. `SUPERVISION_DISCONNECTED`) as the title column. AC 5 specifies "error title" (user-facing label). No mapping to French display names exists in the JS. Accept raw code as title, or add a `_siaDC09_errorTitles` lookup map.

- [x] [Review][Patch] **P1 — AC 4: no defensive `array_slice(..., 10)` cap in `getDiagnosticData` read path** [`core/ajax/siaDC09.ajax.php`] — Fixed: `$errors = array_slice($errors, 0, 10);` added after `is_array` guard.

- [x] [Review][Patch] **P2 — encKey not scrubbed after exec() in `decodeFrame`** [`core/ajax/siaDC09.ajax.php`] — Fixed: `$encKey = null; $encKeyHex = null;` added after `exec()`.

- [x] [Review][Patch] **P3 — `context` variable computed but never used in `siaDC09_renderMessages`** [`desktop/js/siaDC09.js`] — Fixed: dead code removed.

- [x] [Review][Patch] **P4 — XSS: `decoded.crc_received` / `decoded.crc_computed` injected raw into `.html()`** [`desktop/js/siaDC09.js` — `siaDC09_buildFieldTable`] — Fixed: replaced string concat with `document.createTextNode()` + safe DOM construction.

- [x] [Review][Defer] **`shown.bs.tab` direct binding may miss dynamically injected anchor** [`desktop/js/siaDC09.js` line 795] — deferred, pre-existing pattern in codebase; delegated binding would be safer but is a non-regression refactor (D-21)
- [x] [Review][Defer] **`_siaDC09_decodeCache` unbounded growth** [`desktop/js/siaDC09.js`] — deferred, 9-2 scope; track for 9-2 review (D-22)
- [x] [Review][Defer] **Inspector detail panel lost after re-render while AJAX decode in-flight** [`desktop/js/siaDC09.js`] — deferred, 9-2 scope (D-23)
- [x] [Review][Defer] **`siaDC09_copyHexFallback` — `$ta` not removed on `select()` throw** [`desktop/js/siaDC09.js`] — deferred, 9-2 scope (D-24)
