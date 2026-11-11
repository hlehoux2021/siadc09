---
type: epic
title: "Epic 13 — Alarm Event Vocabulary Extension"
parent: initiative-my-project
covers: []
after: []
assignee: ""
status: in-progress
risk: medium
---

# Epic 13 — Alarm Event Vocabulary Extension

## Description

Report the end of an alarm and the arm/disarm state (BC, OP, CL; BR and FC/PC later), addressed to a configured SIA user number.

## Outcome

Report the end of an alarm and the arm/disarm state (BC, OP, CL; BR and FC/PC later), addressed to a configured SIA user number.

## Requirements

No functional requirement is assigned to this epic in epics.md.

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin's code are outside it. Decision (2026-11-11, Herve): writing siaDC09's own action commands into an Alarm equipment's configuration data is inside the epic (story 13.5). Changing the Alarm plugin's code is not.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 13
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 12, Story 8.2 (zone numbers)
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 13 of epics.md (archive-v6/epics.md).
