---
id: 11
type: story
title: "18.11 — Wizard step 2: FTPS settings in the advanced options"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1]
after: [4]
hitl: false
risk: medium
---

# 18.11 — Wizard step 2: FTPS settings in the advanced options

## Description

Moves the FTPS settings from the interim step 1 card into the Options avancées panel of step 2 per the approved mockup (screens C, D2): server, port, user, password, folder, certificate radios with the fingerprint field, never profile-locked, the panel opening by itself when the settings are incomplete, the step 1 note shown and the interim card removed, FTPS validation with the banner Impossible de lancer le test, the FTPS completeness check at Terminer, and the step 2 summary.

## Acceptance Criteria

Verify: On test-jeedom the settings are edited in the advanced panel, an incomplete FTPS setup is refused with its errors, an FTPS equipment saves and reaches the daemon, and the render matches the mockup in Dark and Light.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block
