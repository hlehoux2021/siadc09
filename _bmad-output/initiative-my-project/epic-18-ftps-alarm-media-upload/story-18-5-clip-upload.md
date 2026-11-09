---
id: 5
type: story
title: "18.5 — Clip upload"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R2]
after: [2]
hitl: false
risk: medium
---

# 18.5 — Clip upload

## Description

Uploads the clip of a BA alarm once Frigate has it, in addition to the snapshot, following the snapshot and clip switches.

## Acceptance Criteria

Verify: A BA alarm with both switches on leaves a snapshot and a clip on the test server.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md

## Notes

- Unknown: Whether the clip is ready when the alarm fires; frigate_prefetch.py upgrades to the clip later, so the upload may have to wait.
