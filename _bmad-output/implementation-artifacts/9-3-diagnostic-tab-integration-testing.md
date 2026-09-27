# Story 9.3: Diagnostic Tab Integration & Testing

Status: done

## Story

As a plugin architect,
I want the diagnostic tab properly integrated and tested end-to-end,
So that it's reliable for user troubleshooting when all panels work together.

## Acceptance Criteria

1. **Given** diagnostic tab in equipment configuration page, **When** user is in Step 4 (wizard complete), **Then** diagnostic tab is visible and all three panels (badge, error, inspector) render simultaneously.

2. **And** all refresh buttons are manual only (no auto-refresh, no setInterval, no polling).

3. **And** separate "Vider" button for each panel — errors clears `sia_last_errors`, inspector clears `sia_last_messages`.

4. **And** layout uses Bootstrap 3 panel styling consistent with Jeedom 4.x.

5. **And** responsive design works on mobile and desktop (no fixed pixel widths, standard Jeedom responsive patterns).

6. **And** integration tests verify:
   - Status badge updates rendering on supervision state change (0/1/2 → correct color)
   - Error panel populated with errors from `sia_last_errors` config key
   - Protocol inspector displays frames from `sia_last_messages` ring buffer
   - All refresh buttons call `getDiagnosticData` and re-render all panels
   - Clear buttons wipe correct config key without affecting other panel's data

7. **And** end-to-end test: error injected into `sia_last_errors` → error appears in panel after Actualiser → "Vider" clears panel → panel empty.

8. **And** cross-panel consistency test: `getDiagnosticData` single AJAX call returns badge + errors + messages together — no separate endpoints per panel.

9. **And** all existing Level 1 tests (863+) continue to pass with zero regressions.

## Tasks / Subtasks

- [x] Task 1 — Write Level 1 integration tests for diagnostic tab cross-panel behavior (AC: 1, 2, 6, 8)
  - [x] 1.1 Verify `getDiagnosticData` AJAX returns all 6 keys in one response (`supervision_state`, `supervision_label`, `event_state`, `event_label`, `errors`, `messages`)
  - [x] 1.2 Verify `siaDC09_loadDiagnosticData()` JS function calls `siaDC09_renderBadge` AND `siaDC09_renderErrors` from the same success handler. If story 9-2 is already implemented, also verify `siaDC09_renderMessages` is called — use conditional assertion (check if function exists in source first).
  - [x] 1.3 Verify all three refresh buttons (errorsRefresh, inspectorRefresh) call `siaDC09_loadDiagnosticData()` — not separate endpoints
  - [x] 1.4 Verify NO `setInterval`, NO `setTimeout` for auto-refresh in diagnostic tab code (only the 2000ms rate-limit setTimeout is allowed)
  - [x] 1.5 Verify `shown.bs.tab` event on diagnosticTab triggers data load

- [x] Task 2 — Write Level 1 tests for clear button isolation (AC: 3, 6)
  - [x] 2.1 Verify `clearDiagnosticData` with `target=errors` calls `config::save('sia_last_errors', '[]', 'siaDC09')` only — no `sia_last_messages` touched
  - [x] 2.2 Verify `clearDiagnosticData` with `target=messages` calls `config::save('sia_last_messages', '[]', 'siaDC09')` only — no `sia_last_errors` touched
  - [x] 2.3 Verify JS `#siaDC09_errorsClear` sends `target: 'errors'` (not `messages`)
  - [x] 2.4 Verify JS `#siaDC09_inspectorClear` sends `target: 'messages'` (not `errors`)
  - [x] 2.5 Verify invalid target returns error (existing test — confirm still passes)

- [x] Task 3 — Write Level 1 tests for badge ↔ error panel ↔ inspector data flow (AC: 6, 7, 8)
  - [x] 3.1 Verify badge render function accepts integer `supervision_state` and string `supervision_label`
  - [x] 3.2 Verify error panel render function handles empty array (empty state) and populated array (table rows)
  - [x] 3.3 Verify badge color mapping covers all 3 states exhaustively (0, 1, 2) with fallback to orange for unknown
  - [x] 3.4 Verify tier classification map covers all 6 ErrorCode values (`SUPERVISION_TIMEOUT`, `SUPERVISION_NAK`, `BAD_CSR_RESPONSE`, `SUPERVISION_DISCONNECTED`, `EVENT_FAILED`, `TRANSPORT_PERMANENT`)
  - [x] 3.5 Verify error row structure includes: timestamp cell, tier badge cell, code cell, message cell

- [x] Task 4 — Write Level 1 tests for tab visibility and guard logic (AC: 1, 4, 5)
  - [x] 4.1 Verify diagnostic tab `<li>` has `style="display:none"` by default in PHP
  - [x] 4.2 Verify `siaDC09_initDiagnosticTab` with step=4 calls `.show()` on tab li
  - [x] 4.3 Verify `siaDC09_initDiagnosticTab` with step=3 calls `.hide()` on tab li
  - [x] 4.4 Verify tab panel uses Bootstrap 3 classes: `panel panel-default`, `panel-heading`, `panel-body`
  - [x] 4.5 Verify tab uses responsive-safe patterns (no absolute positioning, no fixed pixel widths > 400px)

- [x] Task 5 — Write Level 2.5 IPC contract test: `error_update` → `sia_last_errors` → `getDiagnosticData` (AC: 7)
  - [x] 5.1 Verify `error_update` callback schema matches `sia_last_errors` entry structure (code, message, timestamp, context, count)
  - [x] 5.2 Verify `message_trace` callback schema matches `sia_last_messages` entry structure (dialog_type, routine, timestamp, elapsed_ms)
  - [x] 5.3 Verify config key format consistency: PHP `getDiagnosticData` reads JSON arrays that match daemon callback shapes

- [x] Task 6 — Run full test regression suite and PHP syntax checks (AC: 9)
  - [x] 6.1 Run `python3 -m pytest tests/level1/ -v` — all tests pass
  - [x] 6.2 Run `find core/ desktop/ -name "*.php" | xargs -n1 php -l` — no syntax errors
  - [x] 6.3 Verify new tests integrate cleanly with existing `test_diagnostic_tab.py` (extend file, don't duplicate)

## Dev Notes

### Architecture Constraints

- **Single AJAX call:** `getDiagnosticData` returns ALL diagnostic data in one call. All panels refresh from the same response. There is NO per-panel endpoint. [Source: internal-docs/design/debug-ui-design.md#Task-5c.4]
- **No auto-refresh:** Zero polling, zero `setInterval`. Only manual "Actualiser" buttons. The only `setTimeout` allowed is the 2000ms rate-limit on buttons. [Source: internal-docs/design/debug-ui-design.md#Task-5c.4]
- **Plugin-level config keys:** `sia_last_errors` and `sia_last_messages` use `config::byKey(..., 'siaDC09')` NOT `eqLogic->getConfiguration()`. This avoids triggering `postSave()`. [Source: internal-docs/design/debug-ui-design.md#Task-5c.5]
- **Clear isolation:** "Vider" on errors clears ONLY `sia_last_errors`. "Vider" on inspector clears ONLY `sia_last_messages`. Neither affects the daemon ring buffer. [Source: internal-docs/design/debug-ui-design.md#Task-5c.5]
- **Tab visibility:** Diagnostic tab hidden when `sia_wizard_step < 4`. Controlled by `siaDC09_initDiagnosticTab(step)` called from `printEqLogic`. [Source: 9-1 story, debug-ui-design.md]
- **Bootstrap 3:** Jeedom 4.x. Use `panel panel-default`, `panel-heading`, `panel-body`, `table-condensed`, `label-*`. No Bootstrap 4/5. [Source: all Jeedom UI conventions]

### Existing Code — All Already Implemented (DO NOT modify)

This is a **testing-only** story. All production code is already in place from stories 9-1 and 9-2. The files to test (not modify):

**`core/ajax/siaDC09.ajax.php`** (174 lines):
- `getDiagnosticData` (line 111): Returns `{supervision_state, supervision_label, event_state, event_label, errors, messages}` in one response
- `clearDiagnosticData` (line 158): Accepts `target` param (`errors` or `messages`), clears corresponding config key
- Uses `eqLogic::byType('siaDC09')[0]` for equipment access
- Validates target, returns error for invalid

**`desktop/js/siaDC09.js`** (858 lines):
- `siaDC09_initDiagnosticTab(wizardStep)` (line 724): Show/hide tab based on step
- `siaDC09_loadDiagnosticData()` (line 732): Single AJAX call, renders badge + errors
- `siaDC09_renderBadge(supervisionState, supervisionLabel)` (line 750): Sets dot color + label text
- `siaDC09_renderErrors(errors)` (line 758): Renders error table or empty state
- `siaDC09_formatTimestamp(isoString)` (line 779): ISO → HH:MM:SS local
- Refresh buttons (lines 798–814): Rate-limited, call `siaDC09_loadDiagnosticData()`
- Clear buttons (lines 816–858): Call `clearDiagnosticData` with correct target
- `shown.bs.tab` handler (line 794): Loads data on tab activation
- `_siaDC09_badgeColors` object (line 718): Maps 2→green, 1→orange, 0→red
- `_siaDC09_tierMap` object (line 703): Maps error codes to T1/T2/T3
- `_siaDC09_tierClasses` object (line 712): Maps T1→label-info, T2→label-warning, T3→label-danger

**`desktop/php/siaDC09.php`** (413 lines):
- Diagnostic tab `<li>` (line 90): `id="siaDC09_diagnosticTabLi"` with `style="display:none"` (in `<ul class="nav nav-tabs">` block)
- Tab panel (line 377): `id="diagnosticTab"` with badge, errors, inspector panels
- All panels use `panel panel-default` Bootstrap 3 structure
- Inspector panel has placeholder content: `<em class="text-muted">{{Aucun échange SIA enregistré}}</em>`

**`tests/level1/test_diagnostic_tab.py`** (550 lines):
- Already has 42 tests from story 9-1 covering: PHP syntax, AJAX structure, tab HTML, badge colors, error panel, refresh rate limit, tab visibility
- Extend this file (DO NOT create a separate file)

### Data Structures (for assertions)

**`getDiagnosticData` response shape:**
```json
{
  "supervision_state": 2,
  "supervision_label": "string",
  "event_state": 0,
  "event_label": "string",
  "errors": [],
  "messages": []
}
```

**`sia_last_errors` entry shape** (from `error_update` callback):
```json
{
  "code": "SUPERVISION_DISCONNECTED",
  "message": "Supervision perdue — 3 cycles consécutifs sans réponse",
  "timestamp": "2026-05-18T14:32:11+02:00",
  "context": {"strike": 3, "last_ack": "14:29:00"},
  "count": 1
}
```

**`sia_last_messages` entry shape** (from `message_trace` callback):
```json
{
  "dialog_type": "supervision",
  "routine": 1,
  "timestamp": "2026-05-18T14:30:00+00:00",
  "elapsed_ms": 245
}
```

**ErrorCode → Tier mapping (complete):**
- T1: `SUPERVISION_TIMEOUT`, `SUPERVISION_NAK`
- T2: `BAD_CSR_RESPONSE`
- T3: `SUPERVISION_DISCONNECTED`, `EVENT_FAILED`, `TRANSPORT_PERMANENT`

### Testing Strategy

**Level 1 tests** (extend `tests/level1/test_diagnostic_tab.py`):
- Parse JS/PHP source via regex to verify structural contracts
- No Jeedom instance needed, no daemon needed
- Pattern: read source file, assert patterns exist / do not exist
- Follow exact patterns from existing 42 tests in the file

**Level 2.5 test** (new file `tests/level2_5/test_diagnostic_ipc.py`):
- Validate IPC schema consistency between daemon callbacks and PHP reader
- Uses existing `tests/fixtures/ipc_schema.py` sample payloads
- Verifies callback shape matches what `getDiagnosticData` PHP expects to read
- No running daemon or Jeedom needed — pure Python validation

**What NOT to test in this story:**
- Live AJAX calls (requires Jeedom = Level 3)
- Daemon actually sending callbacks (requires running daemon = Level 2/3)
- Browser rendering (requires browser = manual)
- `decodeFrame` subprocess execution (covered in 9-2 tests)

### Test Patterns to Follow

From existing `test_diagnostic_tab.py`:
```python
@pytest.fixture(scope="module")
def js_source() -> str:
    assert _JS_FILE.exists(), f"JS file not found: {_JS_FILE}"
    return _JS_FILE.read_text(encoding="utf-8")

class TestSomething:
    def test_pattern_exists(self, js_source: str) -> None:
        """
        Describe what is being validated.

        Expected result:
        - Pattern X is present in source
        """
        # Assert: description
        assert re.search(r"pattern", js_source)
```

From existing `tests/level2_5/test_callback_schema.py`:
```python
from fixtures.ipc_schema import SAMPLE_ERROR_UPDATE, SAMPLE_MESSAGE_TRACE
```

### Previous Story Learnings (from 9-1)

- Inspector panel HTML and buttons already exist and are wired — do NOT test creation, test behavior
- `siaDC09_loadDiagnosticData()` currently renders badge + errors but NOT messages (9-2 will add `siaDC09_renderMessages` call) — tests should handle both states: check if `siaDC09_renderMessages` exists in source, and assert its call from loadDiagnosticData only if it does
- All diagnostic functions use `siaDC09_` prefix convention
- **Line numbers will shift if story 9-2 is implemented first** — never hardcode line numbers in test assertions; always use regex/content matching
- jQuery event delegation used for dynamic elements
- The 2000ms `setTimeout` in refresh handlers is the ONLY timer — verify no other timers exist

### Scope Boundaries

**IN SCOPE (this story):**
- Level 1 integration tests verifying cross-panel behavior via source parsing
- Level 2.5 IPC contract test for error_update/message_trace → config key → AJAX reader
- Full regression run
- PHP syntax verification

**OUT OF SCOPE:**
- Modifying any production code (PHP, JS, Python)
- Level 3 tests (require live Jeedom)
- Browser-based testing
- Performance testing with 50-entry message list
- Testing `decodeFrame` endpoint (covered by 9-2 tests)

### File List

| File | Action | Reason |
|------|--------|--------|
| `tests/level1/test_diagnostic_tab.py` | UPDATE | Extend with ~20 integration tests (Tasks 1–4) |
| `tests/level2_5/test_diagnostic_ipc.py` | NEW | IPC contract validation for diagnostic data flow (Task 5) |

### References

- [Source: internal-docs/design/debug-ui-design.md — Task 5c.1, 5c.2, 5c.3, 5c.4, 5c.5]
- [Source: _bmad-output/implementation-artifacts/9-1-status-badge-error-panel.md — all implementation details]
- [Source: _bmad-output/implementation-artifacts/9-2-protocol-inspector-hex-viewer-decryption.md — message rendering]
- [Source: tests/fixtures/ipc_schema.py — callback schema definitions]

### Review Findings

Code review performed: 2026-05-19.

- [x] **P1 — Minor — 3 loose existence checks strengthened to proximity regex**
  - `test_load_diagnostic_data_calls_render_messages`: replaced bare `in js_source` pair with `re.search(r"siaDC09_loadDiagnosticData.*?siaDC09_renderMessages", js_source, re.DOTALL)`
  - `test_inspector_refresh_button_calls_load_diagnostic`: replaced with `re.search(r"siaDC09_inspectorRefresh.*?siaDC09_loadDiagnosticData\(\)", js_source, re.DOTALL)`
  - `test_errors_refresh_button_calls_load_diagnostic`: replaced with `re.search(r"siaDC09_errorsRefresh.*?siaDC09_loadDiagnosticData\(\)", js_source, re.DOTALL)`

**Deferred:** D-29, D-30, D-31 (see `deferred-work.md`)

**Change log:**
- 2026-05-19: Code review findings added — 1 patch (3 strengthened assertions), 3 deferred
- [Source: tests/level2_5/test_callback_schema.py — IPC testing pattern]
- [Source: core/ajax/siaDC09.ajax.php — getDiagnosticData/clearDiagnosticData implementations]
- [Source: desktop/js/siaDC09.js — diagnostic functions, lines 710–859]
- [Source: desktop/php/siaDC09.php — diagnostic tab HTML, lines 370–407]

## Dev Agent Record

### Agent Model Used

eu.anthropic.claude-sonnet-4-6

### Debug Log References

- `test_no_auto_refresh_set_timeout_outside_rate_limit`: Initial regex with `re.DOTALL` caused false positive — `.*?` spanned across unrelated functions to match `siaDC09_loadDiagnosticData`. Fixed by removing DOTALL and using `r"setTimeout\s*\(\s*siaDC09_loadDiagnosticData"` (proximity pattern) instead.

### Completion Notes List

- Extended `tests/level1/test_diagnostic_tab.py` with 4 new test classes (34 tests, 76 total): `TestCrossPanelDiagnosticLoad` (9 tests, Task 1), `TestClearButtonIsolation` (5 tests, Task 2), `TestDataFlowBadgeErrorsInspector` (6 tests, Task 3), `TestTabVisibilityAndLayout` (7 tests, Task 4). Story 9-2 was already implemented so `siaDC09_renderMessages` call was unconditionally asserted.
- Created `tests/level2_5/test_diagnostic_ipc.py` (20 tests, Task 5): 3 classes validating IPC schema consistency for error_update→sia_last_errors, message_trace→sia_last_messages, and config key JSON array shapes end-to-end.
- Full regression: 955 passed, 0 regressions. PHP syntax: 9 files, 0 errors.

### File List

- `tests/level1/test_diagnostic_tab.py` — updated (42 → 76 tests)
- `tests/level2_5/test_diagnostic_ipc.py` — new (20 tests)

### Change Log

- 2026-05-18: Story 9-3 implemented — 34 new Level 1 tests + 20 Level 2.5 IPC contract tests. Zero regressions (955 total Level 1 tests pass).
