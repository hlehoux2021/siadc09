---
title: 'Widget: SM1 pictogram badge and SM2 last-event card'
type: 'feature'
ticket: ''
created: '2026-10-20'
status: 'built'
baseline_revision: 'ccce4e06c134f462a5b9ea54209139f5cbdecd84'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'none'
review_source: 'pinned'
lenses_ran: []
review_loop_iteration: 0
context: ['/internal-docs/design/widget-design.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The SM1 supervision indicator is a bare colored dot whose states are hard to tell apart, and the SM2 event line is a single grey text string that is neither clear nor pleasant.

**Approach:** SM1 variant B (round colored badge holding an icon + label + optional sub-label) and SM2 variant B ("Dernier événement" card: type pill with zone/user, then a status line with icon and time), both chosen by the user. Rendered client-side from the existing label texts; no daemon change. Event time is relative when recent and absolute once older than today.

</frozen-after-approval>

## Implementation Notes

- Templates `core/template/{dashboard,mobile}/siaDC09.html` (shared body + script), harness `tests/fixtures/widget_dom_harness.js`, tests `tests/level1/test_widget_live_refresh.py`, doc `internal-docs/design/widget-design.md`.
- Icon is chosen from the `supervision_label` text; `event_state` is not needed because the status sub-reason is only in `event_label`, so no `event_state` callback and no PHP change.
- Event time comes from the live push `collectDate`, else the `event_label` entry of the existing `byId(getCmdState)` call (no `getCollectDate()` placeholder, avoids an unverified Jeedom API).
- Existing event test changed: `.siaDC09-event` now holds a card, so the full label is asserted through `data-raw`.
- Not done: visual validation on test-jeedom (out of scope); no review subagent run (self-checked, full level1 suite 1445 passed).
