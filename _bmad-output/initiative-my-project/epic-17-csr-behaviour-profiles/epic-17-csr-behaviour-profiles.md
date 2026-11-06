---
type: epic
title: "Epic 17 — CSR Behaviour Profiles & Periodic Frames"
parent: initiative-my-project
covers: [FR11, NFR4, NFR7]
after: []
assignee: ""
status: in-progress
risk: medium
---

# Epic 17 — CSR Behaviour Profiles & Periodic Frames

## Description

Per-CSR profiles (Ajax, Scutum, Personnalisé) pre-set the advanced options; the supervision frame (`none` | `sia-dcs` | `null`) and the RP cyclic test become configurable, each with its own period (ADR-22). Supersedes Story 11.1; persistent TCP mode deferred (D-115).

## Outcome

Per-CSR profiles (Ajax, Scutum, Personnalisé) pre-set the advanced options; the supervision frame (`none` | `sia-dcs` | `null`) and the RP cyclic test become configurable, each with its own period (ADR-22).

## Requirements

- FR11: IMA Protect CSR Preset — Configure single CSR endpoint for v1.0 without failover — *amended 2026-10-17: IMA removed (D-84); replaced by CSR behaviour profiles (Ajax, Scutum, Personnalisé) in `core/config/csr_presets.json`, still a single CSR without failover (ADR-22, Epic 17)*
- NFR4: Full SIA DC-09-2021 Compliance — Encryption, timestamp handling, supervision NULL keep-alive, ACK/NAK dialog — *amended 2026-10-17: supervision frame (`sia-dcs` empty block or `NULL`) and RP periodic test, each configurable with its own period (ADR-22)*
- NFR7: CSR Extensibility — JSON preset architecture allows community-contributed CSR support without modifying core

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. level 1 golden frames and key consistency, level 2 periodic loops and SM1 staleness, Jeedom UI on test-jeedom, field validation at Scutum.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 17
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 1, 5, 6, Story 1.6 / ADR-21
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Decision: entries 7 and 8 (configurable alarm media, Vesta and FoxStream profiles) belong to this epic (user, 2026-11-05).
- Decision: stories 17.7 (configurable alarm media) and 17.8 (Vesta and FoxStream profiles) belong to this epic and stay separate; their other decisions are in their own files (user, 2026-11-05).
- Source conflict: stories 17.7 and 17.8 vs ADR-22 — 17.7 says the media options are "not profile fields" and 17.8 says they are "filled but not locked"; ADR-22 says a profile pre-fills and locks every key it declares.
- Decision: media keys a profile declares are locked by it; only media_enabled and the Frigate address are user choices; 17.10 corrects the code, wizard-design.md, ADR-22 and the two story files (user, 2026-11-05, D2/D13).
- Decision: stories 17.9 to 17.12 follow the wizard step 1 UX redesign in ux-17-wizard-step-1/ (spines still draft); order 17.9 → 17.10 → 17.11, with 17.12 after 17.9 only (user, 2026-11-06).
- Decision: 17.10 stays one story and includes the server-side Frigate check at daemon start; with media off it also skips the Frigate prefetch and forced capture (user, 2026-11-06).
- Decision: an expected DUH is logged at WARNING on the wizard test path only; the running daemon keeps SM1_DUH at error (user, 2026-11-06).
- Decision: a closing Refactor sweep, 17.13, is added (user, 2026-11-06).
- Source: v6 epic 17 of epics.md (archive-v6/epics.md).
