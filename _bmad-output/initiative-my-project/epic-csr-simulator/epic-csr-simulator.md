---
type: epic
title: "Epic 2 — CSR Simulator"
parent: initiative-my-project
covers: []
after: []
assignee: ""
status: done
risk: low
---

# Epic 2 — CSR Simulator

## Description

Build a standalone CSR simulator that responds to SIA DC-09 protocol frames, usable for testing daemon implementations and other alarm systems without a real CSR.

## Outcome

Build a standalone CSR simulator that responds to SIA DC-09 protocol frames, usable for testing daemon implementations and other alarm systems without a real CSR.

## Requirements

No functional requirement is assigned to this epic in epics.md.

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. Unit tests for simulator ACK/NAK generation, encryption, UDP/TCP modes; hex frame replay; PCAP extraction.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 2
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Story 1.1 (Message Builder) + Story 1.5 (DC-09 AES encryption; supersedes 1.2)
- Note (epics.md): Internal Testing Infrastructure (not user-facing v1.0 feature); can be deferred if v1.0 uses mock responses
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 2 of epics.md (archive-v6/epics.md).
