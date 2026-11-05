---
title: 'Widget: Jeedom standard conformance (resize, name banner)'
type: 'bugfix'
ticket: ''
created: '2026-10-20'
status: 'built'
baseline_revision: 'aa533fd3130a2400934c3f0f2a40c74915b7629f'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: ['/internal-docs/design/widget-design.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The siaDC09 dashboard tile is not a standard Jeedom widget: its root lacks the `eqLogic` / `allowResize` classes and the `width/height/#style#` inline style, so it spans the full row and cannot be resized in dashboard edit mode; its header is a Bootstrap `panel-heading`, not the standard `widget-name` banner.

**Approach:** Rebuild the template root and header on the stock Jeedom eqLogic widget markup (as `core/template/dashboard/eqLogic.html` in jeedom/core), keeping the body content, element classes (`siaDC09`, `siaDC09-badge`, `siaDC09-label`, `siaDC09-event`) and the inline JS untouched.

Out of scope (deferred, `deferred-work.md`): new SM1 pictograms, SM2 redesign.

</frozen-after-approval>

## Implementation Notes

Oneshot: template-only change, no daemon or PHP logic change. Root keeps `data-eqLogic_id`/`.siaDC09`, which the inline script and `tests/level1/test_widget_live_refresh.py` select on.

Files: `core/template/{dashboard,mobile}/siaDC09.html`, `tests/level1/test_widget_live_refresh.py`, `internal-docs/design/widget-design.md`.

Review changed the approach: mobile no longer a byte copy of dashboard. Stock mobile `eqLogic.html` has no fixed width/height/`allowResize`, so the mobile root and banner follow it; the body and script stay shared and the identity test now compares only those.

## Review Triage Log

- medium (patched): mobile root carried dashboard sizing/`allowResize` — confirmed against jeedom/core mobile `eqLogic.html`; mobile root split.
- low (patched): invented `eqlogic-widget-content` class — absent in stock; replaced by a plain padded div.
- medium (patched): `widget-design.md` still described the Bootstrap panel — updated Task 6.2, 6.6, decisions table.
- low (patched): weak test assertions — class tokens parsed, `#custom_layout#/#category#/#uid#/#tags#` asserted.
- false: `preToHtml()` may not supply new placeholders — jeedom/core `preToHtml()` sets every one used (`#name_display#`, `#object_name#`, `#alert_*#`, `#uid#`, `#tags#`, `#translate_category#`, `#width#`, `#height#`, `#style#`, `#custom_layout#`).
- low (rejected): whole header no longer clickable and tower icon dropped — deliberate, matches stock banner (link on name).
