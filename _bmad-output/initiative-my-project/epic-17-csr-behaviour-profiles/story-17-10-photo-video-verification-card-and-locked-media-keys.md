---
id: 10
type: story
title: "17.10 — Photo/Video Verification Card and Locked Media Keys"
parent: epic-17-csr-behaviour-profiles
covers: [FR11, NFR7]
after: [9, 7, 8]
hitl: true
risk: medium
---

# 17.10 — Photo/Video Verification Card and Locked Media Keys

## Description

A levée de doute photo / vidéo card on step 1 holds the checkbox (new key media_enabled, absent = on, set explicitly by the JS on load) and the required Frigate address; the media keys a profile declares are locked by that profile; presets carry an explicit media_enabled default (Vesta and FoxStream on, Scutum off with video only in format V, flagged to test); Ajax keeps the checkbox greyed; media_enabled=0 sends no media tag and skips the Frigate prefetch and forced capture; starting the daemon refuses an empty Frigate address when media is on; this corrects the 17.7 'not profile fields' and 17.8 'filled but not locked' decisions in wizard-design.md, ADR-22 and the two story files. Also fixes B2.

## Acceptance Criteria

Verify: Choosing Vesta or FoxStream locks the media keys and checks the box; Scutum locks video only in V and leaves the box off; Ajax greys it; Personnalisé unlocks. With the box off, the frame has no media tag, no prefetch is triggered and the Frigate value is kept in the form. An equipment saved before this story still sends the same bytes and its box reads on. Box on with an empty Frigate address is refused at step 1 and at daemon start, and the step 3 check stays. The level 1 preset test accepts media_enabled and the Scutum keys. Then looked at in the browser on test-jeedom.

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- ux — ux-17-wizard-step-1/EXPERIENCE.md, Photo / video verification card, Profiles and media, Build contracts
- ux — ux-17-wizard-step-1/.memlog.md, D2 D3 D9 D13 D14
- story — story-17-7-configurable-alarm-media-in-ba-frames-snapshot-clip-u-o.md and story-17-8-vesta-climax-and-foxstream-foxbox-csr-profiles.md (decisions reversed)
- design — internal-docs/design/wizard-design.md, advanced options; ADR-22 in architecture-my-project.md

## Notes

- Keep it one story; the server-side Frigate check at daemon start is part of it (user, 2026-11-06)
- With media off, also skip the Frigate prefetch and forced capture (user, 2026-11-06)
