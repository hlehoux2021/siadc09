---
title: '17.8 Vesta (Climax) and FoxStream (FoxBox) CSR profiles'
type: 'feature'
ticket: '8'
created: '2026-11-05'
status: 'built'
baseline_revision: 'e366af7'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'none'
review_source: 'auto'
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Vesta (Climax) and FoxStream (FoxBox) receivers need their own media format (U and V) and test timings; users must not set them by hand.

**Approach:** Two entries in `core/config/csr_presets.json` carrying the 17.7 media keys, and the wizard fills those keys when a profile is chosen.

</frozen-after-approval>

## Implementation Notes

Oneshot: about 60 lines, one JSON file, one JS function, tests and one design doc section.

- `vesta`: snapshot + clip, U, one tag, sia-dcs every 30 s, RP every 120 s. `foxstream`: same with V.
- The wizard fills the media keys but does not lock them (Ajax and Scutum have none, locking would block media setup for them). The URL template is never a profile key.
- Tests: preset file (allowed keys, expected values), jsdom wizard (fill U/V, media-less profile leaves media alone).
- No separate review pass was run for this ticket; the diff is small and covered by tests.
- Verification: preset, wizard DOM, key consistency and i18n tests pass (110).
