---
id: 15
type: story
title: "18.15 — Photo burst by FTP and FTPS"
parent: epic-18-ftps-alarm-media-upload
covers: [E18-R2]
after: [13]
hitl: false
risk: medium
---

# 18.15 — Photo burst by FTP and FTPS

## Description

Uploads a series of 30 photos instead of one, for the verification of a BA alarm sent by FTP or FTPS. The photos are frames cut from the recordings of the Frigate event of the alarm, fetched when the effective alarm arrives. They cover 30 seconds at 1 frame per second, from the start of the event. Both values are fixed. They are named {UID}_{zone}_{timestamp}_{image}. The timestamp is the start time of the Frigate event, the same on every file of the series. The image number is 0001, 0002 and so on, so the receiver can rebuild a video from them. When no frame can be taken from the recordings, the single event snapshot is sent alone, as before the series. The clip keeps its own name, built from the time the alarm is handled, so its timestamp is not the series timestamp. Applies to the FTP and FTPS transports only, and only when the equipment sends the photo; the SIA URL transport keeps its [V...] video tag unchanged.

## Acceptance Criteria

Verify: An alarm on a zone with a trigger delay, with the photo on and the FTPS transport, on a camera that Frigate records, puts 30 photos named ...0001.jpg to ...0030.jpg on the server over one connection, all with the start time of the Frigate event in their name. A frame that Frigate cannot cut is retried once, then skipped, and the other photos are still sent with consecutive image numbers. On a camera with no recording, one photo (the event snapshot) is sent. An alarm cancelled during the delay uploads nothing.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md
- design — internal-docs/design/daemon-design.md, section on the photo series

## Notes

- Decision (2026-11-14, user): the photos come from the recordings of the Frigate event, `GET /api/<camera>/recordings/<ts>/snapshot.jpg`, fetched after the effective alarm arrives. Nothing is captured at the prefetch and nothing is held in memory between the prefetch and the alarm.
- Decision (2026-11-14, user): 30 frames, one per second over 30 s (decision 2026-11-15, was 3 per second over 10 s), from the event `start_time`, no further offset. An event created on demand already starts 5 seconds before its creation, so those 5 seconds are covered.
- Decision (2026-11-14, user): the timestamp in the file names is the event `start_time`, as whole seconds, on every file of the series. Only the image number changes.
- Decision (2026-11-14, user): the clip does not change. It keeps the epoch of the moment the alarm is handled (18.13). The series and the clip no longer share one timestamp.
- Decision (2026-11-14, user): when no frame can be obtained (no event, no recording, every frame refused), the single event snapshot is sent alone through the existing single-photo path, with one warning in the log. There is no parallel capture of the camera's current image.
- Decision (2026-11-14, user): a frame refused by Frigate with a 404 is retried once 0.2 second later, then skipped. The series never stops at one failed frame. Image numbers stay consecutive over the frames obtained.
- Decision (2026-11-15, user): the series starts at the event `start_time` for every event, existing or created by the plugin; no extra offset, since a created event already starts 5 seconds before its creation. If the recordings do not yet cover 30 seconds when the alarm is handled, the series is shorter (stops after 3 failed frames in a row); the daemon does not wait.
- Decision: the whole series goes through one FTP connection (user, 2026-11-13). Each upload budget stays at 2 seconds per file after the first (user, 2026-11-14).
- Decision: FTP and FTPS only; in SIA mode the [V...] video tag covers the need and does not change (user, 2026-11-13).
- Decision: image numbers 0001, 0002... are valid, the receiver is built for a burst (user, 2026-11-13). Follows the 18.13 decision that the image number is the rank in a series.
- Decision: a partial failure raises one notification (for example 12 photos of 30 sent), not one per photo.
- Decision (2026-11-14, user): with a series, the Frigate event snapshot is not sent; it stays the photo of the SIA URL transport and the fallback when there is no series.
- Decision (2026-11-14, user): the wizard label is "Rafale de photos", with no count. The count and the duration are in the user documentation.
- Evidence (2026-11-14, test-frigate): on an event created through the API, 30 frames from `start_time` gave 29 photos in 3.8 s (about 47 KB each, all different); from 5 seconds before `start_time` gave 30 in 4.0 s; `clip.mp4` of the event answered 200. An older event gave 30 of 30 in 3.6 s. A 404 "Unable to parse frame" appeared once per series.
- Unknown: why the 404 appears. In four observed cases the frame was 0.05 to 0.1 second before a whole second where a recording segment ended. This is not verified. The build checks it with the probe script and keeps the retry only if it recovers the frame.
- Assumption: the endpoint needs no login on the internal port 5000, like the other calls of the daemon. Confirmed on test-frigate on 2026-11-14.
- Risk: the series depends on Frigate recording the camera. A camera with no recording role has no frames, and the alarm falls back to the single snapshot. Check outside the ticket: one alarm on a camera that records, on the production setup, with the receiver of 18.9.
- Risk: the clip exists as a flag (has_clip) even when nothing was recorded, and then the clip download answers 400. Out of this ticket; the prefetch result reports the flag only. Open question: raise it as its own ticket.
- Check in the field: the real receiver accepts several image numbers for the same zone with one timestamp (user, to confirm at 18.9 level).
- Superseded 2026-11-14 (user): 5 photos one second apart; the source `latest.jpg`; the capture at prefetch in a tracked task tied to the run_id, held in memory and dropped after 120 seconds; the series sent with what was held when the alarm came early; one timestamp per photo (the second each was taken); the frozen-camera warning; the fallback "frames from the recordings" as an assumption. They were built in 18.15 first (commits e52580e and 0b2db08) and are to be removed.
- Code to change: resources/siadc09d/frigate_prefetch.py (the series capture goes, a recordings frame fetch with retry comes in); daemon.py (_run_prefetch, on_message ftps_upload, _upload_series, _upload_snapshot, burst state); core/class/siaDC09Cmd.class.php (the prefetchEvent burst flag; the ftps_upload payload keeps the event id and needs the event start time); desktop/js and core/i18n label; tests/level1 and tests/level2; docs/fr_FR/media-ftps.md, changelog, internal-docs/ftps-test-server.md and internal-docs/design/daemon-design.md. Probe: scripts/frigate_recordings_snapshot_probe.py.
