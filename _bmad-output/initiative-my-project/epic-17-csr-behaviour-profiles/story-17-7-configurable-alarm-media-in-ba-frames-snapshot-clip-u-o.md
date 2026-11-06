---
id: 7
type: story
title: "17.7 — Configurable Alarm Media in BA Frames (Snapshot / Clip, U or V, One Tag or Several)"
parent: epic-17-csr-behaviour-profiles
after: [1, 4]
hitl: false
risk: medium
---

# 17.7 — Configurable Alarm Media in BA Frames (Snapshot / Clip, U or V, One Tag or Several)

## Description

To choose, per equipment, whether intrusion (BA) frames carry a snapshot, a clip, both or nothing, in which tag format (U or V) each travels, and, when both formats are the same, whether both URLs share one tag; the media URL setting moves into the wizard advanced options, shown only when the snapshot or the clip is on. Today the frame carries the snapshot and the clip, when available, in a single V tag with one space between them. This story defines the equipment configuration keys for these choices, so that a profile can carry them (see 17.8).

## Acceptance Criteria

Verify: A BA frame is built for each valid combination of snapshot on/off, clip on/off, format U/V per media and, when both are on, one tag or one tag each; each frame matches the expected bytes. One tag with different formats is refused by the wizard and by the daemon. With both off, the frame has no media tag. The URL field is hidden with both off and shown with at least one on; saving with one on and an empty URL shows an error in the wizard. An equipment saved before this story sends the same bytes as today.

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- spec — internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md, section 5.5.1.8
- design — internal-docs/design/wizard-design.md, advanced options (to update with this story)

## Notes

- Decision: when the snapshot and clip formats differ, the frame carries one tag each; the one-tag option is unavailable in the wizard and the daemon does not accept it (user, 2026-11-05).
- Decision: format U is `[U<url>]`, with the same syntax and character rules as V (user, 2026-11-05). The local DC-09-2021 spec lists V only (section 5.5.1.8). To confirm against Vesta documentation or in the field.
- Decision: no "send media" master switch; the snapshot and clip on/off choices are enough, both off means no media tag (user, 2026-11-05).
- Decision: an equipment saved before this story keeps today's behavior (snapshot and clip, format V, one tag, one space between URLs). Only a test environment exists, so this is not a constraint (user, 2026-11-05).
- Decision: the media URL template stays a per-equipment setting, never part of a profile. It is shown only when the snapshot or clip is on, and the wizard errors when it is needed and empty (user, 2026-11-05).
- Decision: this story is tested with the Personnalisé profile; the Vesta and FoxStream profiles are 17.8 (user, 2026-11-05).
- Open question: the current code attaches media to burglar, fire and panic alarms alike. The user asked for BA only. Does the new setting apply to all three, or do fire and panic keep today's behavior?
- Open question: when one media URL cannot be resolved and the formats differ, does the frame carry one tag for the available media only? Assumed yes.
- Open question: this story is large (wizard, equipment config, PHP, daemon, tests). Split into frames and wizard if the build plan finds it too big.
- Decision (reversed by 17.10, user 2026-11-06): the media content keys are profile fields, locked by the profile; only media_enabled and the Frigate address are user choices.
