---
id: 8
type: story
title: "17.8 — Vesta (Climax) and FoxStream (FoxBox) CSR Profiles"
parent: epic-csr-behaviour-profiles
covers: [FR11, NFR7]
after: [1, 2, 3, 7]
hitl: false
risk: low
---

# 17.8 — Vesta (Climax) and FoxStream (FoxBox) CSR Profiles

## Description

Two new profiles in the wizard profile list: Vesta (Climax) sends snapshot and clip, format U, one tag with a single space between the URLs; FoxStream (FoxBox) sends snapshot and clip, format V, one tag with a single space between the URLs. Both also set the supervision frame to sia-dcs every 30 s and the RP cyclic test on every 120 s. These two timings are test values.

## Acceptance Criteria

Verify: Choosing each profile in the wizard sets the media options and the two timings as described and nothing else changes in the equipment. The level 1 test on the preset file accepts both profiles.

## References

- parent — _bmad-output/initiative-my-project/epic-csr-behaviour-profiles/epic-csr-behaviour-profiles.md
- media options and their configuration keys — story 17.7

## Notes

- Decision: the Vesta and FoxStream profiles set sia-dcs supervision every 30 s and RP every 120 s; these are test values (user, 2026-11-05).
- Decision: the media URL template is never part of a profile (user, 2026-11-05).
- Decision: Vesta uses format U and FoxStream format V, both with one tag and a single space between the URLs (user, 2026-11-05). U is `[U<url>]`, see 17.7.
