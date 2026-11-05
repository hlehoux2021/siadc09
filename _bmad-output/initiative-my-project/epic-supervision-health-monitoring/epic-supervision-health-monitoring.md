---
type: epic
title: "Epic 7 — Supervision Health Monitoring"
parent: initiative-my-project
covers: [FR6]
after: []
assignee: ""
status: done
risk: low
---

# Epic 7 — Supervision Health Monitoring

## Description

Implement continuous supervision loop with 3-strike connection state, real-time INFO updates, and TCP stall detection.

## Outcome

Implement continuous supervision loop with 3-strike connection state, real-time INFO updates, and TCP stall detection.

## Requirements

- FR6: SM1 State Machine — Manage connection/supervision states (INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING → NO_NETWORK)

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. E2E supervision loop tests (strikes, ACK recovery, TCP reconnect).

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 7
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 5, 6, Epic 3, Epic 4
- Retrospective: epic-supervision-health-monitoring-retrospective.md
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 7 of epics.md (archive-v6/epics.md).
