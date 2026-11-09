---
id: 11
type: story
title: "18.11 — Wizard step 2: single test button and FTPS settings"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1, E18-R6]
after: [4]
hitl: false
risk: medium
---

# 18.11 — Wizard step 2: single test button and FTPS settings

## Description

Reworks step 2 per the approved mockup (screens C, C1, C2, D2, H): no automatic test, one button Lancer le test / Relancer le test for the SIA test and the FTPS test, a right-hand slot that is Suivant only when every test passed and Ignorer otherwise, results cleared when a setting changes, and the Serveur FTPS card in the advanced options with its validation; works against a stub until 18.7 builds the FTPS test action; wizard-design.md updated.

## Acceptance Criteria

Verify: On test-jeedom nothing runs on arrival, the single button runs the tests, Suivant and Ignorer never show together, incomplete FTPS settings are refused with their errors, and the step 2 render matches the mockup in Dark and Light.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block
