---
id: 4
type: story
title: "18.4 — Wizard UI: transport choice and FTPS settings"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1, E18-R6]
after: [2, 3]
hitl: false
risk: medium
---

# 18.4 — Wizard UI: transport choice and FTPS settings

## Description

Reworks the verification-media block per the approved mockup: choice between URL in the SIA frame and FTPS, FTPS fields shown only for FTPS, required-field errors at save, and the existing URL behaviour untouched.

## Acceptance Criteria

Verify: On test-jeedom the rendered block matches the mockup in Dark and Light themes, an FTPS equipment saves and reaches the daemon, and an existing URL equipment behaves as before.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-verification-media

## Notes

- bien utiliser la maquette comme input au build
