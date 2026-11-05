---
type: epic
title: "Epic 1 — SIA DC-09 Protocol Engine"
parent: initiative-my-project
covers: [FR1, FR2, FR3]
after: []
assignee: ""
status: in-progress
risk: medium
---

# Epic 1 — SIA DC-09 Protocol Engine

## Description

Build core protocol layer with AES-128 encryption, message construction, ACK/NAK parsing.

## Outcome

Build core protocol layer with AES-128 encryption, message construction, ACK/NAK parsing.

## Requirements

- FR1: Protocol Message Builder — SIA DC-09-2021 compliant message construction with proper framing
- FR2: AES-128 CBC Encryption/Decryption — Secure encryption and decryption of CSR communications
- FR3: ACK/NAK Parser — Parse and interpret CSR responses and handle acknowledgments/negative acknowledgments

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. Unit tests (standalone, no daemon required).

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 1
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): None
- Retrospective: epic-1-protocol-engine-retrospective.md
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 1 of epics.md (archive-v6/epics.md).
