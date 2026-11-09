---
id: 6
type: story
title: "18.6 — Upload robustness: timeout, certificate, secret handling"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R3, E18-R4]
after: [2]
hitl: false
risk: medium
---

# 18.6 — Upload robustness: timeout, certificate, secret handling

## Description

Adds the timeout so the frame is never delayed, certificate validation with a CA-signed or pinned self-signed certificate, and keeps the password out of logs and the debug UI.

## Acceptance Criteria

Verify: With the server down or stalled the frame is ACKed on time and the failure is logged; a wrong certificate is refused; the password appears in no log.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
