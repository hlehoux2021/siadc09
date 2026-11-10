---
id: 9
type: story
title: "18.9 — Field validation against a real FTPS server"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R1, E18-R2, E18-R3]
after: [4, 5, 6, 7, 8, 11, 12]
hitl: true
risk: low
---

# 18.9 — Field validation against a real FTPS server

## Description

Runs the whole path against the user's real server and records the evidence.

## Acceptance Criteria

Verify: A real alarm on test-jeedom puts its snapshot and clip on the server and the CSR still gets the frame; the evidence is written in the story.

## Evidence

Field run on test-jeedom, 2026-11-10, reported by Herve (all checks OK). Daemon log extract (lines 0086-0097, 16:59:28-29):

- Alarm BA zone Zone1 sent as SIA-DCS sequence 0005, account 20881; the request decodes to `#20881|Nri1/BA001]_16:59:28,11-10-2026`.
- The CSR answered `ACK` (response_hex decodes to `"ACK"0005L0#20881[]`); SM2 confirmed on attempt 1 (`Centrale confirmée — alarme BA transmise`), `event_state: 1`.
- Clip: fetched from Frigate for event `1794329938.978561-wp67a7` (411495 bytes in 0.08s, upload deadline 65s).
- FTPS: connect 192.168.40.20:21 with `verify=fingerprint`, AUTH TLS (TLSv1.3), certificate sha256 equal to the expected fingerprint (`6280d136...0c9ecd`), login ok.
- Upload: `STOR 165928_Zone1_1794329938.978561-wp67a7.mp4` -> `226 Transfer complete.` in 0.06s, `FTPS upload ... done` (0.17s). No password appears in the log.

Not shown in this extract: the snapshot upload (it precedes line 0086) and the negative cases. Add their log lines here if they should be on record.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
