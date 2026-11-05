---
type: epic
title: "Configuration Wizard & CSR Presets"
parent: initiative-my-project
covers: [FR11, FR12, FR13]
after: []
assignee: ""
status: done
risk: low
---

# Configuration Wizard & CSR Presets

## Description

Build 4-step zero-jargon wizard for non-technical users to configure CSR connection, test it, map zones, and configure notifications.

## Outcome

Build 4-step zero-jargon wizard for non-technical users to configure CSR connection, test it, map zones, and configure notifications.

## Requirements

- FR11: IMA Protect CSR Preset — Configure single CSR endpoint for v1.0 without failover — *amended 2026-10-17: IMA removed (D-84); replaced by CSR behaviour profiles (Ajax, Scutum, Personnalisé) in `core/config/csr_presets.json`, still a single CSR without failover (ADR-22, Epic 17)*
- FR12: 4-Step Configuration Wizard — Zero-jargon domain-language setup in French (preset selection, connection test, zone mapping, notifications)
- FR13: Zone Mapping Table — Map zone names to optional camera actions and optional media URLs

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. Wizard flow tests, connection test validation, zone mapping logic.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 8
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 1, 5, 6, 7, Epic 3, Epic 4
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 8 of epics.md (archive-v6/epics.md).
