---
type: epic
title: "Daemon Core & Dual State Machines"
parent: initiative-my-project
covers: [FR4, FR5, FR6, FR7, FR8, FR9, FR10]
after: []
assignee: ""
status: done
risk: low
---

# Daemon Core & Dual State Machines

## Description

Build asyncio daemon with SM1 (connection/supervision) and SM2 (alarm events) state machines, PriorityQueue coordination, UDP/TCP transport, and async task lifecycle. Integration tests with CSR simulator.

## Outcome

Build asyncio daemon with SM1 (connection/supervision) and SM2 (alarm events) state machines, PriorityQueue coordination, UDP/TCP transport, and async task lifecycle.

## Requirements

- FR4: UDP Transport — Datagram-based communication with CSR for firewall-friendly deployment
- FR5: TCP Transport — Stream-based communication with CSR and automatic reconnection on failure
- FR6: SM1 State Machine — Manage connection/supervision states (INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING → NO_NETWORK)
- FR7: SM2 State Machine — Manage alarm event states (IDLE → PENDING → CONFIRMED/FAILED)
- FR8: Burglar Alarm Event — Send burglar alarm events to CSR with proper SIA encoding
- FR9: Fire Alarm Event — Send fire alarm events to CSR with proper SIA encoding
- FR10: Panic Alarm Event — Send panic alarm events to CSR with proper SIA encoding

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. State transition integration tests with csr_simulator (no PHP/supervision loop required).

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 5
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 1, Epic 3, Epic 4
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 5 of epics.md (archive-v6/epics.md).
