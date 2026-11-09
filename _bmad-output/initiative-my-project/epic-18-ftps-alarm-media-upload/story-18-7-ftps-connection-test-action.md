---
id: 7
type: story
title: "18.7 — FTPS connection test action"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R5]
after: [6, 12]
hitl: false
risk: low
---

# 18.7 — FTPS connection test action

## Description

Builds the FTPS test action that the step 2 test button calls (a stub until now): connection, certificate and login only, nothing written; it tells apart unreachable host, certificate failure and authentication failure, and returns the fingerprint the server presents for the trust button.

## Acceptance Criteria

Verify: Against the test server each of the three failures shows its own message in step 2 and a correct setup reports success.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
