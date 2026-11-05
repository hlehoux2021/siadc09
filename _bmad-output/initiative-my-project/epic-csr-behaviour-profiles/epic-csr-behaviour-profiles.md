---
type: epic
title: "CSR Behaviour Profiles & Periodic Frames"
parent: initiative-my-project
covers: [FR11, NFR4, NFR7]
after: []
assignee: ""
status: in-progress
risk: medium
---

# CSR Behaviour Profiles & Periodic Frames

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
- Decision: when the snapshot and clip formats differ, the frame carries one tag each; the one-tag option is unavailable in the wizard and the daemon does not accept it (user, 2026-11-05).
- Decision: format U is settled as `[U<url>]`, same syntax and character rules as V; it blocks nothing (user, 2026-11-05). It is absent from the local DC-09-2021 spec (section 5.5.1.8 lists V only).
- Decision: no "send media" master switch; the snapshot and clip on/off choices are enough, both off means no media tag (user, 2026-11-05).
- Decision: an equipment saved before entry 7 keeps today's behavior (snapshot and clip, format V, one tag, one space between URLs). Only a test environment exists, so this is not a constraint (user, 2026-11-05).
- Decision: the media URL template stays a per-equipment setting, never part of a profile. It is shown only when the snapshot or clip is on, and the wizard errors when it is needed and empty (user, 2026-11-05).
- Decision: entries 7 and 8 stay separate; the user tests 7 with the Personnalisé profile (user, 2026-11-05).
- Decision: the Vesta and FoxStream profiles set sia-dcs supervision every 30 s and RP every 120 s; these are test values (user, 2026-11-05).
- Open question (17.7): the current code attaches media to burglar, fire and panic alarms alike. The user asked for BA only. Does the new setting apply to all three, or do fire and panic keep today's behavior?
- Open question (17.7): when one media URL cannot be resolved and the formats differ, does the frame carry one tag for the available media only? Assumed yes.
- Open question (17.7, 17.8): 17.7 is large (wizard, equipment config, PHP, daemon, tests). Split into frames and wizard if the build plan finds it too big.
- Source: v6 epic 17 of epics.md (archive-v6/epics.md).
