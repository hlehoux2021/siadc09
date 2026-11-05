---
title: 'Diagnostic tab refresh (header, errors table, inspector)'
type: 'feature'
ticket: ''
created: '2026-10-21'
status: 'built'
baseline_revision: '2924bc5611cbb5c1cbeea8ef47eb0bf7a0e2a56f'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Diagnostic tab lags behind the redesigned dashboard widget and is hard to read: bare dots in the header, errors shown as `HH:MM:SS` (UTC) whatever their age, cryptic `T1/T2/T3` badges, centered cells, a constant `SIA-DCS`/`NULL` token on every inspector row, a response time that looks like an alarm when colored, no explanation of tokens.

**Approach:** Port the widget's SM1/SM2 header and `formatTime` to the tab, clean the errors table, show the frame/event code (BA, RP, OP...) in inspector rows with a token explanation, and color the kind label (not the delay).

## Boundaries & Constraints

**Always:** Decisions from the user, 2026-10-21:
1. Header aligned on `core/template/dashboard/siaDC09.html` (SM1 card: icon in ring, "N échecs sur 3" sub-label, relative time; "Dernier événement" card: type/zone/status colors). Reuse its logic (`formatTime`, SM1_ICONS, SM2_*).
2. Errors older than today: widget `formatTime` (hier / jj/mm hh:mm:ss), local time not UTC.
3. Remove the T1/T2/T3 badge.
4. Table cells `vertical-align: top`.
4b. Inspector rows show the frame/event code (BA, RP, OP, CL...) instead of `SIA-DCS`/`NULL`; supervision frames keep `NULL`.
5. Short explanatory text for the token on each row, placed before the timestamp column.
6. Delay (ms) in normal color. The kind label is colored: routine grey, non-routine green, retry orange. "Non-routine" gets a better word.
7. Expanded detail: explanation restored on the "ID Token" field-table row.
6b. Kind labels: alarm -> "événement" (green); supervision timeout/NAK -> "incident" (red); routine -> "routine" (grey); alarm retry -> "retry" (orange).
8. Validate in the Jeedom UI (test-jeedom, push first), not by reflection. Level1 tests for JS; level2 for daemon changes.

**Never:** Touch CLAUDE.md (unrelated local edit). Re-add tier badges. Color the delay. Change `_trace_header()`'s return shape (level2 tests assert it).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|----------|--------------|----------|----------------|
| Old error | timestamp yesterday / 3 days ago | "hier hh:mm:ss" / "jj/mm hh:mm:ss" | invalid date -> empty |
| Today error | 10 min ago | relative + clock time like the widget | none |
| Alarm row | `event_code` "BA" | BA shown + explanation | missing -> "NULL" |
| Retry row | alarm `transition` failed_timeout / nak_retry | label "retry" orange | none |
| Encrypted RP | no readable code | falls back to NULL | none |

</frozen-after-approval>

## Code Map

- `desktop/js/siaDC09.js:826-1257` -- diagnostic render code: `siaDC09_renderBadge/EventBadge` (dots only), `siaDC09_renderErrors` (tier badge, `formatTimestamp` UTC), `siaDC09_renderMessages` (token label, delay badge), `siaDC09_buildFieldTable` (ID Token row). `_siaDC09_tierMap/tierClasses` to delete.
- `desktop/php/siaDC09.php:453-490` -- header markup (two dot spans) to replace by widget-like cards; ids `siaDC09_badgeDot/Label`, `eventBadgeDot/Label` are asserted by tests.
- `core/ajax/siaDC09.ajax.php:26-46,171-220` -- `getWidgetDates` (state_date/event_date) is already callable from the config page; `getDiagnosticData` returns states, labels, errors, messages.
- `core/template/dashboard/siaDC09.html:85-265` -- source of `formatTime`, `SM1_ICONS`, `SM2_TYPES/COLORS/STATUS`, label parsing. Copy, do not import.
- `resources/siadc09d/daemon.py:1053` (`_trace_header`), `:1521-1630` (SM1 traces, NULL), `:2279-2291` (alarm trace; `ctx['sia_code']`, `transition` in scope) -- `message_trace` dialogs lack the event code; RP success is not traced at all (out of scope).
- `tests/level1/test_diagnostic_tab.py` (tier tests at 436-481, 948-975), `test_diagnostic_js_dom.py` (formatTimestamp), `test_inspector_js_logic.py` (badge/label asserts), `tests/level2/test_nak_retry_and_key_config.py:486-514` -- tests to update; jsdom harness `tests/fixtures/js_dom_harness.js`.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/daemon.py` -- add `event_code` (regex on unencrypted `|[N][ri#/]XX` of `_last_sent_frame`, default `ctx['sia_code']` for alarms, absent for supervision) to the 5 dialogs, and `transition` to the alarm dialog -- gives the UI the code and the retry signal; minimal diff (hot-spot file)
- [ ] `tests/level2/` -- test the code extraction (plain BA, RP, encrypted fallback) and alarm `transition` -- daemon change needs a test
- [ ] `desktop/php/siaDC09.php` + `desktop/js/siaDC09.js` -- widget-like header, `formatTime`, errors table without tier, top-aligned cells -- items 1-4
- [ ] `desktop/js/siaDC09.js` -- inspector rows: code, token explanation column, colored kind label, uncolored delay, ID Token explanation in detail -- items 4b-7
- [ ] `tests/level1/` -- update tier/UTC/badge asserts, add tests for new rendering -- keep suite at baseline
- Not for the implementer: no push, no remote ops, no commit, and never touch CLAUDE.md. The orchestrator pushes (with the user's go) and validates the tab on test-jeedom through the UI after review.
- Bash rules for the implementer: no `cd <dir> &&`, project-relative paths or `~/`, temp files in `$TMPDIR`, no heredocs, Read/Grep tools instead of `sed -n`/`grep` through Bash.

**Acceptance Criteria:**
- Given an error from 3 days ago, when the tab loads, then the date is shown with the clock time.
- Given an alarm BA sent, when the inspector loads, then the row shows BA, not SIA-DCS.
- Given a supervision ACK, then the row shows NULL with a grey "routine" label and an uncolored delay.
- Given the errors table, then no T1/T2/T3 badge exists and cells are top-aligned.

## Implementation Notes

## Plan Change Log

## Review Triage Log

- Stale event_code on alarm dialogs (daemon.py `_log_sm2_event`): medium, patch. `_last_sent_frame` is not refreshed for event_received/failed_config. Fixed: alarm dialog uses `ctx["sia_code"]` directly. Level2 re-run: 5 failures = baseline (untouched files).
- `_siaDC09_codeExplain` has 8 codes only: low, rejected. Empty text for other codes is tolerable; fix would need meanings not yet confirmed.
- Jeedom collectDate parsed in browser time zone: low, rejected. Same behavior as the widget (`parseDate`), which the plan says to reuse; pre-existing.
- Non-alarm non-routine = "incident": false. All three `routine: 0` supervision traces are timeout/NAK (daemon.py 1586-1655).
- `eventState` unused in renderEventBadge: low, rejected. Colors come from the label like the widget; removing the arg is churn.
- test_inspector_js_logic.py untouched: false. No reference to removed identifiers remains (suite passes).
- Stale `_siaDC09_tierMap` mention in tests/level2_5 docstrings: low, rejected (docstring only).
- Hardcoded French in formatTime/explanations, no en_US: low, rejected. en_US is partial by project decision.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/test_nak_retry_and_key_config.py` -- expected: no new failures vs baseline
- `python3 -m pylint resources/siadc09d/` -- expected: no new warnings
- `node --check desktop/js/siaDC09.js` -- expected: no syntax error

**Manual checks (if no CLI):**
- Diagnostic tab on test-jeedom: header cards, errors table, inspector rows and expanded detail.
