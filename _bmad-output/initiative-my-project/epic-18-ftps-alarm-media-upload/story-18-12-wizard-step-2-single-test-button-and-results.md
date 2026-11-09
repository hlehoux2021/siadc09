---
id: 12
type: story
title: "18.12 — Wizard step 2: single test button and results"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1, E18-R6]
after: [11]
hitl: false
risk: medium
---

# 18.12 — Wizard step 2: single test button and results

## Description

Reworks the step 2 behaviour per the approved mockup (screens C, C1, C2, H): no automatic test, one button Lancer le test / Relancer le test running the SIA test and, under FTPS, the FTPS test, two result zones starting at Pas encore testé, a right-hand slot that is Suivant only when every test passed and Ignorer otherwise, results cleared when a setting changes, the step 3 warnings per test, the trust-this-fingerprint action, and a stub FTPS action (testFtps returning unavailable) until 18.7 builds the real one; wizard-design.md updated.

## Acceptance Criteria

Verify: On test-jeedom nothing runs on arrival, the single button runs the tests, Suivant and Ignorer never show together, and the step 2 render matches the mockup in Dark and Light.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block
