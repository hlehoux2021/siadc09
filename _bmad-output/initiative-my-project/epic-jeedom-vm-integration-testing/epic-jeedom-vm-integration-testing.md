---
type: epic
title: "Jeedom VM Integration Testing"
parent: initiative-my-project
covers: []
after: []
assignee: ""
status: in-progress
risk: medium
---

# Jeedom VM Integration Testing

## Description

Validate the complete plugin on a real Jeedom instance (Debian 12 VM) — installation, wizard, daemon lifecycle, supervision, alarm delivery, UI rendering, error handling, and Market packaging.

## Outcome

Validate the complete plugin on a real Jeedom instance (Debian 12 VM) — installation, wizard, daemon lifecycle, supervision, alarm delivery, UI rendering, error handling, and Market packaging.

## Requirements

No functional requirement is assigned to this epic in epics.md.

## Done when

1. Every entry of `tickets.toml` is done or dropped; its plan carries the status.
2. Real Jeedom UI, real daemon process, real alarm plugin, real notification commands.

## Boundaries

Scope as written in epics.md for this epic; the other epics and the Jeedom alarm plugin are outside it.

## References

- epics — initiative-my-project/archive-v6/epics.md, epic 12
- prd — initiative-my-project/prd-my-project/prd-my-project.md

## Notes

- Dependencies (epics.md, not written as `after`): Epic 1-10 (all features complete)
- Assumption: the Done when section was drafted at migration from the epics.md Testing line; to be reviewed with the owner.
- Source: v6 epic 12 of epics.md (archive-v6/epics.md).
