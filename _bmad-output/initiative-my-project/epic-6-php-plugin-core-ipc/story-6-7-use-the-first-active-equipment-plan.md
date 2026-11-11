---
title: '6.7 - Use the first active equipment'
type: 'feature'
ticket: '7'
created: '2026-11-11'
status: built
baseline_revision: 'b691d17878a09968e58a687247c19e3422eca264'
route: 'oneshot'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The plugin works on the first siaDC09 equipment found, enabled or not, and creates one only when none exists. A user cannot keep a disabled equipment in reserve.

**Approach:** One PHP resolver returns the first enabled equipment; auto-creation happens only when none is enabled. The class methods and the four ajax actions that took the first equipment (test connection, test FTPS, diagnostic data, key generation) use it. Design docs and ADRs that state "one equipment only" are reviewed and amended (an ADR is superseded by a new one, never edited).

</frozen-after-approval>

## Implementation Notes

Oneshot: about 60 lines across one class, one ajax file, level1 tests and docs. Assumptions from the ticket stand: several enabled equipments keep today's behaviour (first one, error logged); the equipment list page keeps listing every equipment.

## Review Triage Log

Quick review, 1 lens. Level1: 1688 passed before the fix, targeted files re-run after.

- high, patched: `getDiagnosticData` kept `$eqLogic = $eqLogics[0];` after the resolver call, which nulled the equipment and crashed the debug UI. Line removed; test now asserts no `$eqLogics` remains in the ajax file.
- medium, patched: `supervision-design.md` Guard 1 wording; `testFtps` / `testConnection` error text said "introuvable" while a disabled equipment may exist. Reworded to "Aucun équipement actif — activez un équipement." (fr_FR key updated).
- low, rejected: en_US has no entries for the new ajax strings. en_US is partial and falls back to the French key; same as before this change.
- low, rejected: README.md:35, daemon-design.md:1170, ajax.md:402 say "one equipment". Still true for the active equipment; no ADR in architecture-my-project states a one-equipment rule (only the area YAGNI line 729, which stays correct). Review of the ADRs found nothing to supersede.
