---
id: 11
type: story
title: "17.11 — Advanced Panel Rework: Labels, Extension Choice, Supervision"
parent: epic-17-csr-behaviour-profiles
after: [10]
hitl: true
risk: low
---

# 17.11 — Advanced Panel Rework: Labels, Extension Choice, Supervision

## Description

The advanced panel shows what is sent (photo, video, link formats named U URL Multimedia Direct and V Video Verification Link), the one-extension-or-one-per-link choice with real examples using a space between URLs (always visible, greyed with its reason when unavailable), the supervision card, and locked fields that stay readable with a caption; the orange NULL warning is removed, with wizard-design.md and the test harness updated.

## Acceptance Criteria

Verify: In a profile every field is visible, read-only (readonly or aria-disabled) with the lock caption; in Personnalisé all are editable. The one-extension choice is greyed with its reason for a single content or mixed formats, and the examples match the bytes of _format_media_tags. Folding the panel loses no value. The NULL warning is gone. Then looked at in the browser on test-jeedom.

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- ux — ux-17-wizard-step-1/EXPERIENCE.md, Contents sent with the alarm, Supervision card; DESIGN.md
- ux — ux-17-wizard-step-1/.memlog.md, D4 D7 D10 D12
