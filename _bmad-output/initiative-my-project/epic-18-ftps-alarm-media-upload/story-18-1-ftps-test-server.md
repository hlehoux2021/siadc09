---
id: 1
type: story
title: "18.1 — FTPS test server"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1]
after: []
hitl: true
risk: low
---

# 18.1 — FTPS test server

## Description

Sets up an FTPS server the plugin can upload to, reachable from test-jeedom, with a known certificate.

## Acceptance Criteria

Verify: A standard FTPS client connects to it and uploads a file.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md

## Notes

- Unknown: Explicit (port 21) or implicit (port 990) TLS, and CA-signed or self-signed certificate: both certificate cases must be supported, settle which one the test server uses.
