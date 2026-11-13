---
type: epic
title: "Epic 18 — FTPS Upload of Alarm Verification Media"
parent: initiative-my-project
covers: []
after: []
assignee: ""
risk: medium
---

# Epic 18 — FTPS Upload of Alarm Verification Media

## Description

Today the plugin only puts a URL in the alarm frame (`[U…]` / `[V…]`, epics 14 and 17.7); the monitoring station must fetch the media itself from Frigate. This epic lets the daemon push the verification snapshot and clip (images and video) to a remote FTPS server, configured per equipment, so the media reaches a place the receiver can read without access to Frigate. The upload is independent of the SIA frame: the frame is sent as before and never waits for it.

## Outcome

An installer who owns an FTPS server sees the snapshot and the clip of every alarm of an equipment land on that server, and an unreachable server never delays or blocks the alarm frame.

## Requirements

No parent requirement id covers this capability; the PRD does not describe it. Epic-local ids, to be confirmed at inception:

- E18-R1: Per equipment, the user enables the upload and sets the FTPS server (host, port, user, password, remote folder).
- E18-R2: On an alarm that carries media, the daemon uploads the snapshot and/or the clip to the server, according to the existing snapshot and clip switches (17.7).
- E18-R3: The upload never delays or blocks the SIA frame; failure and timeout are logged and visible, and the alarm is still delivered.
- E18-R4: The server certificate is validated by default; the password is stored and logged like a secret.
- E18-R5: The user can test the connection from the wizard.
- E18-R6: Per equipment, the user chooses how the verification media is transmitted: by URL in the SIA frame (the current behaviour, SIA-DCS) or by FTPS upload. The wizard's verification-media block is reworked for this choice.
- E18-R7: The upload applies to intrusion (BA) alarms only.

## Done when

1. With a real FTPS server, a Frigate alarm on a configured equipment puts the snapshot and the clip in the remote folder, and the SIA frame reaches the CSR as before.
2. With the server down or slow, the frame is still ACKed within its usual time, and the failure is logged and shown to the user.
3. The password never appears in logs, in the debug UI, or in anything sent to the CSR.
4. Level 1 and level 2 tests pass against a local FTPS fixture; the wizard fields and the connection test are checked on test-jeedom.

## Boundaries

The daemon's media upload and the per-equipment settings that drive it. Not the content of the SIA frame (epics 14 and 17), not fetching media from Frigate (reused from `frigate_prefetch.py`), not the CSR's side. SFTP is out of scope (see Decision).

## References

- parent — _bmad-output/initiative-my-project/initiative-my-project.md
- epic 14 — _bmad-output/initiative-my-project/epic-14-camera-snapshot-attachment/epic-14-camera-snapshot-attachment.md
- story 17.7 — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/story-17-7-configurable-alarm-media-in-ba-frames-snapshot-clip-u-o.md (snapshot/clip switches and keys)
- code — resources/siadc09d/frigate_prefetch.py (media retrieval), core/class/siaDC09.class.php (equipment config keys `media_*`)
- design — internal-docs/design/wizard-design.md, internal-docs/design/daemon-design.md (to update)
- constraint — ADR-22 (profiles lock the keys they declare); the FTPS keys are not profile fields

## Notes

- Decision: the upload is independent of the SIA frame; the frame does not reference the uploaded file and does not wait for the upload (user, 2026-11-09).
- Decision: the FTPS settings are per equipment and never part of a CSR profile (user, 2026-11-09).
- Decision: a failed or slow upload is best-effort with a timeout; it is logged and signalled and never prevents the frame from reaching the CSR (user, 2026-11-09).
- Decision: the protocol is FTPS only; SFTP is not covered (user, 2026-11-09).
- Decision: the user chooses per equipment between media by URL in the SIA frame (current behaviour) and FTPS upload; the wizard block is reworked for it, after a mockup (user, 2026-11-09).
- Decision: the wizard story is built from the approved mockup, which is its input; the mockup is a hitl entry before it (user, 2026-11-09).
- Decision: the FTPS upload applies to BA alarms only (user, 2026-11-09).
- Decision: both CA-signed and self-signed server certificates must be supported (user, 2026-11-09).
- Decision: the epic is split into 10 entries, with a closing Refactor sweep (user, 2026-11-09).
- Decision: the two transports are exclusive; with FTPS chosen, the frame carries no U/V media tag (user, 2026-11-09).
- Decision: the transport choice is a user choice, not a profile field (ADR-22) (user, 2026-11-09).
- Decision (supersedes the previous Frigate-address line, user 2026-11-09 after the mockup review): the Frigate address (`frigate_media_url_template`) belongs to the URL transport only, since the daemon reads Frigate's host from the Frigate plugin in FTPS; it is not asked in the common zone.
- Decision: the approved mockup (`ux-18-wizard-media-block`, 2026-11-09) fixes the wizard: Photo/Vidéo in the common part of step 1 (still profile-locked), the FTPS technical settings in the step 2 advanced options, one test button on step 2 with no automatic test, and one right-hand button, Suivant only after full success, otherwise Ignorer (user, 2026-11-09).
- Decision: entry 4 is split in two (re-slice, user 2026-11-09): 18.4 is step 1 and the data model, the new 18.11 is step 2; 18.7 becomes the FTPS test action called from step 2 and waits on 18.11 (the wizard work was about 400-500 lines and 25-35 tests, too much for one plan).
- Decision (supersedes "the transport choice is a user choice, not a profile field"; user, 2026-11-09 while testing 18.4): a CSR profile locks the media transport like it locks Photo/Vidéo. Profiles that receive media in the frame declare `media_transport = url`; FTPS is then reachable in "Personnalisé". The FTPS settings (server, user, password, folder, certificate) are not profile fields and are never locked.
- Decision (user, 2026-11-09): entry 11 is split in two because the step 2 work was about 400 lines and 25-30 tests: 18.11 moves the FTPS settings into the advanced options, the new 18.12 is the single test button, the result zones and the Suivant/Ignorer slot; 18.7 now waits on 18.12.
- Decision: the epic now has 12 entries (supersedes the counts of 10 and 11 above).
- Decision: the FTPS password follows the precedent of the AES `encryption_key`: a `type="password"` field in the equipment configuration, passed to the daemon the same way, and kept out of logs (user, 2026-11-09). Not a conflict with the `media_url` rule, which only says the URL template carries no real secret.
- Unknown: FTPS mode (explicit TLS on port 21 vs implicit on 990) and certificate handling (public CA, self-signed with pinned fingerprint); to settle with the first test server.
- Decision (user, 2026-11-13, supersedes the 18.8 layout): remote files go flat at the root of the FTPS folder, named `{UID}_{zone}_{timestamp}_{image}.{jpg|mp4}` (account, zone number, Unix epoch seconds, image 0001). Entry 13 (18.13) builds it.
- Unknown: any retention or cleanup on the server.
- Unknown: whether the clip is ready when the alarm fires; `frigate_prefetch.py` already upgrades to the clip later, so the upload may have to wait for it.
- Open question: no test server exists yet; entry 1 is a hitl story to set one up.
