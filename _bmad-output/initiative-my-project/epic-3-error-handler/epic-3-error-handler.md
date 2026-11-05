---
type: epic
title: "Epic 3 — Error Handler"
parent: initiative-my-project
covers: [FR15, NFR1]
after: []
assignee: ""
status: done
risk: low
---

# Epic 3 — Error Handler

## Description

Define error handling interfaces, ErrorCode enum, notification context types, and dispatcher contract that all daemon and PHP components depend on.

## Outcome

Define error handling interfaces, ErrorCode enum, notification context types, and dispatcher contract that all daemon and PHP components depend on.

## Requirements

- FR15: 3-Tier Error Handler — Auto-heal notifications (T1), user-actionable notifications (T2), critical infrastructure notifications (T3)
- NFR1: Zero Silent Failures — Every undelivered alarm must trigger a critical notification within the ACK timeout window

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. Type/interface validation only.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 3
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): None (foundation)
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 3 of epics.md (archive-v6/epics.md).
