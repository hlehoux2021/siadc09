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

Uploads a series of photos instead of one, for the verification of a BA alarm sent by FTP or FTPS. The count (5) and the interval (1 second) are fixed. The photos are taken during the Prefetch événement Frigate window, between the immediate action of the alarm and its effective trigger. They are kept in memory and sent only when the effective alarm arrives, named {UID}_{zone}_{timestamp}_{image} with image 0001, 0002 and so on, so the receiver can rebuild a video from them. Without a series (capture failed, daemon restarted) the single event snapshot is sent as today. Applies to the FTP and FTPS transports only, and only when the equipment sends the photo; the SIA URL transport keeps its [V...] video tag unchanged.

## Acceptance Criteria

Verify: An alarm on a zone with a trigger delay, with the photo on and the FTPS transport, puts five photos named ...0001.jpg to ...0005.jpg on the server, taken about one second apart before the trigger, over one connection; an alarm cancelled during the delay uploads nothing; with no series available, one photo is sent as before.

## References

- parent — _bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/epic-18-ftps-alarm-media-upload.md

## Notes

- Decision: 5 photos, one per second, as fixed values named in the code; no equipment setting and no wizard field for the count or the interval for now (user, 2026-11-13).
- Decision: the whole series goes through one FTP connection, so _upload_stream is split to send several files on one login (user, 2026-11-13).
- Decision: FTP and FTPS only; in SIA mode the [V...] video tag covers the need and does not change (user, 2026-11-13).
- Decision: the receiver is built for a burst, and some rebuild a video from it, so image numbers 0001, 0002... are valid (user, 2026-11-13). Follows the 18.13 decision that the image number is the rank in a series. Amended 2026-11-14 (user): each file carries the epoch second its own photo was taken, so names differ by timestamp and image number, not one shared timestamp.
- Decision: the photos are captured in a separate tracked daemon task started by the prefetchEvent command, not inside prefetch_alarm_media, which stops early once a person and its clip are found; they are tied to the run_id, held in memory only, dropped after PREFETCH_CACHE_TTL (120 s), and never sent unless the BA alarm arrives.
- Decision: if the alarm arrives before the series is complete, the daemon sends the photos it has; if it has none, it falls back to the single event snapshot.
- Decision: a partial failure raises one notification (for example 3 photos of 5 sent), not one per photo.
- Decision: the photo source is GET /api/<camera>/latest.jpg (user, 2026-11-13). The Frigate documentation lists it with jpg, png and webp, and says it falls back to preview frames when the camera is offline.
- Assumption: the endpoint needs no login on the internal port 5000, like the other calls of the daemon. Check with curl on test-frigate before coding, with the query parameters (size, quality), which the documentation page does not list.
- Risk: with a camera offline the endpoint serves preview frames, so the series could hold five near identical images. The build decides whether to detect it (same bytes) and log a warning.
- Assumption: if latest.jpg is refused or unusable, the fallback is extracting frames from the recordings of the manual event.
- Decision (2026-11-14, user): with a series, the Frigate event snapshot is not sent; it stays the photo of the SIA URL transport. Without a series the single snapshot is sent as before.
- Risk: the series keeps images of a possible false alarm in memory for up to 120 s. They are never written to disk and never sent without a BA alarm. Check outside the ticket: the user cancels an alarm during its delay on test-jeedom and confirms that nothing reaches the server.
- Check in the field: the real receiver accepts several image numbers for the same zone, with a different timestamp per photo (user, to confirm at 18.9 level).
- Code to change: resources/siadc09d/frigate_prefetch.py (series capture); daemon.py (_run_prefetch, on_message ftps_upload, _upload_snapshot); ftps_upload.py (IMAGE_NUMBER becomes a parameter of remote_location); core/class/siaDC09Cmd.class.php (prefetchEvent payload, ftps_upload payload with run_id); tests/level1 and tests/level2; internal-docs/ftps-test-server.md line 98 and internal-docs/design/daemon-design.md (FTPS section).
