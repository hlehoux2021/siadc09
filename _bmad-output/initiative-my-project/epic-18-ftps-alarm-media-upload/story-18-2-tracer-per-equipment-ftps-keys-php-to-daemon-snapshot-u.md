---
id: 2
type: story
title: "18.2 — Tracer: per-equipment FTPS keys, PHP to daemon, snapshot upload on BA alarm"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1, E18-R2, E18-R7]
after: [1]
hitl: false
risk: medium
---

# 18.2 — Tracer: per-equipment FTPS keys, PHP to daemon, snapshot upload on BA alarm

## Description

Adds the equipment configuration keys for the FTPS upload (password as a password field like encryption_key), passes them to the daemon, and uploads the Frigate snapshot of a BA alarm, with no wizard yet.

## Acceptance Criteria

Verify: With the keys set by hand on test-jeedom, a BA alarm puts a snapshot on the test server and the frame is sent as before.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- resources/siadc09d/frigate_prefetch.py
- core/class/siaDC09.class.php
