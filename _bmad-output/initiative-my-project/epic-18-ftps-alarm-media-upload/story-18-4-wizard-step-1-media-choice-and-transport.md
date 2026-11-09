---
id: 4
type: story
title: "18.4 — Wizard step 1: media choice and transport"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R6]
after: [2, 3]
hitl: false
risk: medium
---

# 18.4 — Wizard step 1: media choice and transport

## Description

Reworks step 1 of the wizard per the approved mockup (screens A, B, D, G): the photo/video choice moves from the step 2 advanced panel into the media card with the transport choice (URL in the SIA frame or FTPS); the Frigate address is asked only for the URL transport; no FTPS field on step 1; media_transport and ftps_enabled stay coherent and the Frigate-address checks skip FTPS; the summaries show the verification-media choice.

## Acceptance Criteria

Verify: On test-jeedom the step 1 card matches the mockup in Dark and Light, a profile locks Photo and Video with its caption, an FTPS equipment saves without a Frigate address, and an existing URL equipment behaves as before.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block

## Notes

- bien utiliser la maquette comme input au build
