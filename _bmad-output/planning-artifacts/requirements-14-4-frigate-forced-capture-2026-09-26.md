# Requirements — Story 14-4: Best-Effort Alarm Media (any-label events + forced Frigate capture)

- **Date:** 2026-09-26
- **Author:** Mary (Business Analyst), with Herve (product owner, decisions below are his)
- **Audience:** Winston (Architect), who writes ADR-17 Amendment 4; then `bmad-create-story` for story 14-4
- **Status:** Requirements agreed with Herve. Architecture: ADR-17 Amendment 4 (2026-09-26) resolves §7 R1-R5.
- **Builds on:** 14-2 (prefetch/cache, ADR-17 Amendment 3) and 14-3 (snapshot + clip in one `[V...]` field)

---

## 1. Problem

The alarm fires because the alarm plugin tripped a sensor, whatever Frigate did or didn't see. Today (14-2/14-3),
`media_url` is attached only when Frigate already has a **`person`** event in the prefetch window. In every other
case the BA frame goes out with no `[V...]` field. The operator gets nothing, even when:

- Frigate did record something with another label (cat, dog, bird, car). That is useful information for the
  operator ("an animal triggered the alarm").
- Frigate recorded nothing at all, but the camera was pointing at the zone at the moment of the trip.

Time matters: an intruder can leave the camera's view within seconds of the trip.

## 2. Principle change (for ADR-17 Amendment 4)

| | ADR-17 up to Amendment 3 | Amendment 4 (this story) |
|---|---|---|
| Principle | "No photo is fine, a wrong photo never is" | "Every real image of the zone taken while the alarm is happening is useful; a person image beats everything; never a stale image or one from another alarm" |
| What "wrong" means | Anything that isn't a `person` event | **Stale** (from before the window) or **not this alarm's** (another camera, another alarm) |
| Non-person events | Excluded | Accepted, ranked below `person` |
| Nothing detected | No media | **Forced capture**: a manual Frigate event created when the sensor trips |

**Premise, as the user stated it:** alarm triggers are genuine. The alarm plugin decides that. Legitimate occupants
don't trip sensors before disarming. A trip followed by a disarm during the entry delay is still accepted (see §6).

## 3. Functional requirements

### FR1 — Forced capture at trip time
When `prefetchEvent` fires (the alarm plugin's immediate action, t0), the daemon **first** creates a manual Frigate
event on the zone's mapped camera, before any polling:

`POST /api/events/{camera}/alarm/create` with body `{"duration": 30, "include_recording": true}`

- Label: **`alarm`**, a label dedicated to these events (see §5 for why this works in Frigate 0.17.2).
- Duration: **30 s**.
- The returned `event_id` is enough to build both URLs straight away (`/api/events/{id}/snapshot.jpg`,
  `/api/events/{id}/clip.mp4`) through the existing `frigate_media_url_template` mechanism. No `media_url` template
  change is needed (memory: template tokens only, never a real secret).

### FR2 — Early push of the forced capture
As soon as the create call returns, the daemon pushes a `prefetch_result` callback to PHP for the manual event.
The cache then holds a usable entry well before `burglarAlarm` reads it.
**This is a required change, not an optimisation:** today the only callback is sent when polling ends
(`resources/siadc09d/daemon.py:2231-2239`), ~25 s after t0 on a miss. That already races with the BA frame (≤ 25 s).

### FR3 — Any-label event search
In parallel with FR1/FR2, and continuing after them, the daemon polls `GET /api/events` on the same camera, in the
same window as today (`after = t0 − 30 s`, every 2 s, up to 25 s, `start_time` descending), **without the
`label=person` filter**. It keeps only events that:
- are **not** the manual events: exclude `label == "alarm"`, with `type == "api"` as a backstop (§5);
- have a snapshot (`has_snapshot`).

### FR4 — Priority ladder
For each camera, the best source found so far wins:

| Rank | Source | Snapshot | Clip |
|---|---|---|---|
| 1 | Real `person` event, most recent | attached | attached only once ready (14-3 rule, unchanged) |
| 2 | Real event with any other label, most recent | attached | attached only once ready (14-3 rule) |
| 3 | Manual `alarm` event (FR1) | attached | **URL attached straight away, even if the clip isn't ready yet** |
| 4 | Nothing (Frigate unreachable, create refused/failed, no mapping) | — | — (plain BA, unchanged) |

- The daemon pushes a new callback **each time the rank improves** (3 → 2 → 1). A lower-ranked result never
  overwrites a higher one for the same prefetch run.
- Polling stops early on rank 1. On rank 2 it keeps going until the budget runs out, in case a `person` event shows up.
- When several real events share a rank: **the most recent** wins (decided; never seen in practice).

### FR5 — Manual events are never deleted
siaDC09 never deletes or ends a manual `alarm` event, not even when a real event outranks it or when the alarm is
disarmed. They exist because the alarm fired, so they stay as a trace. Frigate's retention policy and the operator
handle deletion.

### FR6 — Send path unchanged in shape
`burglarAlarm` keeps its single, synchronous, local cache read (`_readPrefetchCacheEntry()`, the 14-3 TOCTOU fix)
and its space-separated `[V snapshot clip]` join. It never blocks and never makes a network call. It is never delayed.

## 4. Non-functional requirements / constraints

- **NFR1 — 25 s ceiling.** The BA frame has to go out at most 25 s after t0. No step of this story adds latency to
  the send path. The prefetch budget stays within that window.
- **NFR2 — Daemon boundary.** All Frigate REST calls stay in the daemon's `frigate_prefetch` module, which has no
  Jeedom dependency (the ADR-17 Amendment 3 boundary is unchanged).
- **NFR3 — Never crash.** A refused create call (e.g. HTTP 401/403), a timeout, or Frigate being down only drops
  down the ladder, with a warning logged. It never raises, and never blocks or delays the frame.
- **NFR4 — Frigate version.** Verified against **Frigate 0.17.2** (the deployed version). 0.18 is out and has
  **not** been checked. Re-verify §5 before upgrading.

## 5. Frigate 0.17.2 facts (verified in source, `blakeblackshear/frigate` tag `v0.17.2`)

| Fact | Where | Consequence |
|---|---|---|
| `create_event` validates only the camera. The label is free text. | `frigate/api/event.py:1749-1767` | `alarm` is accepted without being in `objects.track` |
| `objects.track` labels not in the model's labelmap are dropped with a warning | `frigate/config/config.py:268-281` | **Don't** add `alarm` to `objects.track`. It would be silently dropped. |
| Create body defaults: `duration=30`, `include_recording=True` | `frigate/api/defs/request/events_body.py:38-43` | Matches FR1 |
| Event id generated and returned **before** the async insert and snapshot save | `frigate/api/event.py:1769-1798`, `frigate/track/object_processing.py:506-545` | URLs can be built right away. For a very short time the snapshot may not be served yet. |
| Manual events are stored with `type="api"`, `has_snapshot=True`, `has_clip = record.enabled && include_recording` | `frigate/track/object_processing.py:525-545` | Backstop exclusion field for FR3 |
| Manual (api) events **always** become **alert** review segments, whatever `review.alerts.labels` says | `frigate/review/maintainer.py:693-708` | Clip retention = `record.alerts.retain` (Herve's config: 15 days, mode `all`) |
| Snapshot retention per label: `snapshots.retain.objects` is a free `dict[str, float]`, falling back to `default` | `frigate/config/camera/snapshots.py:11-16`, `frigate/events/cleanup.py:143-169` | Today `alarm` snapshots fall to `default: 7` days. Herve can add `alarm: 15`. |
| Events flagged `retain_indefinitely` are never cleaned up | `frigate/events/cleanup.py` | Manual use only. siaDC09 doesn't set it. |
| **Create requires the `admin` role.** Listing events needs any authenticated user. | `frigate/api/event.py:1735-1738` | **Open risk R1** |
| Manual events never publish to MQTT `events`/`reviews` | memory `frigate-manual-event-api-no-mqtt` | Invisible to the Jeedom Frigate plugin, which doesn't matter: 14-2 no longer reads it |

Herve's Frigate config: `pailly-proxified/etc/frigate/config.yml`.

## 6. Accepted consequences

- **Every sensor trip creates an `alarm` event in Frigate**, including a trip followed by a disarm during the entry
  delay. Accepted: it's a trace, and there is usually also a real `person` event of the occupant walking up and
  disarming, covered by the existing retention.
- **The forced clip isn't playable at send time** (it plays from about t0 + 30 s + Frigate latency). An operator who
  opens it very early may get an error or an incomplete clip. Accepted by Herve. What the receiving centre actually
  shows needs field validation.
- **Scope: BA (`burglarAlarm`) only.** PA/FA stay out of scope (zero or independent delays), as in 14-2.

## 7. Open points for the Architect

- **R1 — `admin` role for create.** The daemon uses the Frigate plugin's global `URL`/port (`_resolvePrefetchTarget`).
  `scripts/frigate_latency_probe.py` has already created manual events successfully, so a working path exists.
  Confirm the daemon uses that same path (e.g. the internal unauthenticated port), or decide how it authenticates.
- **R2 — Callback sequence and cache semantics.** Several `prefetch_result` callbacks per run (FR2/FR4). The cache
  entry needs a source/rank (e.g. `source: person|other|manual`) so PHP can refuse a downgrade. It also needs a
  run/t0 marker, so a late callback from an **older** run can't overwrite a newer run's entry on the same camera.
  Check this against the existing `PREFETCH_CACHE_TTL`.
- **R3 — Same camera, two quick trips** (e.g. two zones mapped to one camera, or a re-trip within 30 s). Each run
  creates its own `alarm` event. The FR3 exclusion drops all of them from the real-event search (label filter), not
  only the current run's.
- **R4 — Clip rule asymmetry.** Rank 1/2 attach the clip only once ready (14-3). Rank 3 attaches it straight away.
  Confirm this stays a per-source rule and doesn't leak into ranks 1/2.
- **R5 — A snapshot that doesn't exist yet.** The manual event's snapshot is saved asynchronously, right after
  create returns. It's almost certainly ready by the time the operator opens it, but the story should measure it with
  `scripts/frigate_latency_probe.py`.

## 8. Acceptance-criteria seeds (for `bmad-create-story`)

1. Trip with **no** Frigate event → the BA frame carries `[V {alarm-event}/snapshot.jpg {alarm-event}/clip.mp4]`, sent
   within the normal delay. The manual event exists in Frigate with label `alarm`, a 30 s duration, and a clip.
2. Trip with a **cat/dog/bird/car** event in the window, no person → the BA frame carries that event's media. The
   manual event still exists and is **not** deleted.
3. Trip with a **person** event → the BA frame carries the person event's media, even if a non-person event is more
   recent. The manual event still exists.
4. The manual `alarm` event is **never** picked as a "real" event (ranks 1/2), including one left over from an earlier
   trip on the same camera less than 30 s before.
5. Create call refused/failed or Frigate unreachable → ranks 1/2 still work if reachable, otherwise a plain BA. Never
   delayed, never an exception.
6. Disarm during the entry delay → no BA frame (unchanged), and the manual event stays in Frigate.
7. A late callback from an earlier run never overwrites the current run's cache entry (R2).
8. Level-1/level-2 tests cover the ranking, the exclusion, the early push, and the no-downgrade rule **before** any
   live retry (memory `prefer-tests-over-live-trial-and-error`).
9. Live validation on `test-jeedom.lehoux.net` against the real receiver `192.168.100.15:10002` / account `001234`,
   for cases 1, 2 (if an animal can be staged or found), and 3. Check through the real Jeedom UI/API, not by reflection.

## 9. Out of scope

- PA/FA media attachment.
- Deleting, ending, or setting `retain_indefinitely` on manual events.
- Changes to Herve's Frigate config (adding `snapshots.retain.objects.alarm` is his call; the story only recommends it).
- Frigate 0.18 compatibility.
- A text label for the operator ("person" / "cat" / "forced capture") in the frame. `[V...]` carries URLs only. Not
  asked for; can be revisited with `/sia-dc09-expert`.
