# Sprint Change Proposal — 2026-10-17 (CSR behaviour profiles)

**Author:** Herve (via Correct Course workflow)
**Trigger:** Herve's request to bring back what had been set aside: wizard settings pre-set per CSR, with a "Personnalisé" choice, in a collapsed "Options avancées" section. The behaviours to cover come from the Ajax↔Scutum captures.
**Mode:** Incremental. All 6 edit proposals were approved individually.

## 1. Issue Summary

The Ajax↔Scutum captures (`internal-docs/ajax.md`) showed periodic-frame behaviour that the plugin cannot reproduce. Captures A (on-demand mode) and B (permanent mode, ping interval 5 min) were taken on 2026-10-17, together with the Scutum extranet log for capture A.

**Two periodic frames with different roles:**
- **Supervision frame** (`"NULL"0000L0#acct[]`): Ajax sends it only in permanent mode, to keep the TCP connection alive.
  - It goes on each connection. The connection cycle is ~10.4 s, set by Scutum's close 5 s after its ACK plus a ~5 s reconnect.
  - It is sent again every ~31 s while the connection stays open.
  - Its cadence does not depend on the ping interval.
- **Cyclic test** `[#acct|Nri0/RP0000]`: sent in both modes.
  - Its period is the hub's "Intervalle ping du centre de télésurveillance". At 1 min, the measured period was 62 to 65 s.
  - It uses the global sequence counter.
  - The timer counts from the end of the previous exchange, and an event does not shift it.

**Scutum supervises an on-demand transmitter by RP alone.** In capture A there is no `NULL`, and the extranet shows no link alarm.

**The plugin today:**
- It sends only `"SIA-DCS"…[#acct|0000]` (D-86) at `supervision_interval_s`.
- It has no RP.
- It cannot send a clear-text `NULL`.
- Its first supervision frame waits one full interval (D-42).
- The preset mechanism was removed with IMA Protect (D-84).
- Wizard step 1 has manual fields only.

**Herve's decisions (2026-10-17):**
- The "Ajax" profile means "behave like an Ajax hub", whatever the CSR.
- Story 11.1 is cancelled; Epic 17 supersedes it.
- Permanent TCP mode is **deferred**:
  - no available CSR accepts it, and a CSR serving thousands of clients would not hold as many idle connections;
  - Ajax works in both modes, so the plugin's Ajax profile is on-demand.
- The building blocks of permanent mode **stay**:
  - the supervision frame in both formats (`sia-dcs`, `null`);
  - separate periods for supervision and RP;
  - both settings independent of the connection mode.

## 2. Impact Analysis

- **Epic impact:**
  - new Epic 17 (5 stories, backlog);
  - Epic 11: Story 11.1 cancelled; epic-11 stays in-progress because of 11-2;
  - no other epic is touched.
- **Story impact:** 11.1 cancelled. Its goal was met against the real Scutum receiver instead of the simulator, which drove 1.6 / ADR-21. Its ACs (simulator, `test_data/*.hex`, `compare_frames.py`) are obsolete.
- **Artifact conflicts:**
  - PRD still names IMA Protect as the v1.0 preset and describes supervision as a "NULL keep-alive";
  - architecture ADR-03 describes a daemon-side `presets/` directory that never existed;
  - ADR-06 assumes `crc_format=bin` changes outgoing frames, which it does not today;
  - ADR-08's staleness rule only knows the supervision interval;
  - `wizard-design.md` still describes IMA; it is rewritten in Story 17.4.
- **Technical impact:**

  | Area | Location |
  |---|---|
  | Supervision frame | `sia_protocol.py` `make_supervision_message()` |
  | Supervision loop, SM1 staleness | `daemon.py` |
  | `CSRPreset` | `presets.py` (4 new fields with defaults) |
  | CLI arguments | `siadc09d.py` |
  | Daemon start | `siaDC09.class.php` `deamon_start` |
  | Wizard step 1 | `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` |
  | Profile file | new `core/config/csr_presets.json` |
  | Key consistency test | `tests/level1/test_wizard_config_key_consistency.py` |

  - Defaults reproduce today's behaviour, so existing installations do not change.

## 3. Recommended Approach

**Direct Adjustment.** Add Epic 17 and cancel 11.1. Nothing is rolled back and the MVP scope is unchanged. The periodic-frame work refines the supervision feature the MVP already has.

- **Effort:** medium.
  - 17.1 to 17.3 are daemon and PHP plumbing, with level1 tests.
  - 17.4 is the UI.
  - 17.5 is field validation; Herve does the sends to Scutum.
- **Risk:** low for existing users, since the defaults are unchanged. The `null` format is NAKed by the test receiver (ioBroker.sia), so it can only be proven at Scutum.
- **Order:** 17.1 → 17.2 and 17.3 (parallelisable, but both touch `daemon.py`, see the parallel-agents caveat) → 17.4 → 17.5.

## 4. Detailed Change Proposals

### Stories (`epics.md`)

**New Epic 17: CSR Behaviour Profiles & Periodic Frames**

Goal: per-CSR behaviour profiles (Ajax, Scutum, Personnalisé) pre-set the wizard's advanced options. The periodic frames become configurable: a supervision frame (`none` | `sia-dcs` | `null`) with its own period, and an RP cyclic test with its own period. Both are independent of the connection mode. Permanent TCP mode is deferred (D-115).

**Profiles:**

| Setting | Default (no profile) | Ajax | Scutum |
|---|---|---|---|
| Supervision frame | `sia-dcs` | none | none |
| Supervision period | current `supervision_interval_s` | – | – |
| RP cyclic test | off | on | on |
| RP period | – | 60 s | 60 s |
| Connection | on-demand | on-demand | on-demand |

- **17.1 CSR profile model and PHP → daemon plumbing.**
  - `core/config/csr_presets.json` (PHP-only, `schema_version`).
  - `CSRPreset` gains `supervision_format`, `rp_enabled` and `rp_interval_s`; `supervision_interval_s` already exists. All have defaults equal to today's behaviour.
  - New `siadc09d.py` arguments, passed by `deamon_start`.
  - Key consistency test extended.
  - The daemon rejects, at startup, a configuration with no periodic frame active.
  - Decide `crc_format=bin`: implement it or remove the value (ADR-06 note).
- **17.2 Configurable supervision frame.**
  - `sia-dcs` keeps the current `[#acct|0000]` shape (D-86). `null` sends `"NULL"0000L0#acct[]_ts` in clear. Encrypted supervision stays `*NULL`.
  - Supervision runs on its own period.
  - The first frame goes out at daemon start (D-42), at start only, not on every INITIALIZING.
  - An ACK refreshes SM1.
- **17.3 RP cyclic test.**
  - Frame `[#acct|Nri0/RP0000]`, built by `_format_data_field()` with area 0. It uses the global sequence counter and the normal send path; a missing ACK is a failure.
  - The period runs from 60 s to 24 h, counted from the end of the previous exchange; events do not shift it.
  - The first RP goes out at daemon start.
  - An ACK refreshes SM1.
  - SM1 staleness is 3 × the shortest active periodic interval (ADR-08).
- **17.4 Wizard step 1: profile choice and advanced options.**
  - Profile selector (Ajax / Scutum / Personnalisé).
  - Collapsed "Options avancées", read-only while a profile is selected.
  - Rule "at least one periodic frame".
  - Warning on `null` ("some receivers reject it").
  - The field currently labelled "retry_count" is relabelled "Tentatives de reconnexion", which is what it does.
  - Rewrite `wizard-design.md` (it still describes IMA).
  - Validation through the Jeedom UI on test-jeedom.
- **17.5 Field validation per profile.**
  - Scutum profile at Scutum: RP "Test Cyclique" in the extranet and no link alarm. Herve does the sends.
  - Test receiver (ioBroker.sia): ACK for `sia-dcs` and RP, NAK for `null`. An ACK there proves framing only.
  - Optional: `null` at Scutum, at Herve's convenience.

**Story 11.1: CANCELLED 2026-10-17.**
- Title suffixed, and the 2026-10-17 note replaced by a cancellation note.
- ACs kept as history, marked superseded.
- Story file: `status: "cancelled"`, with a "Cancellation — 2026-10-17" section modelled on 15-1.

### Architecture (`architecture.md`)

- **New ADR-22 "CSR behaviour profiles and periodic frames":**
  - two independent periodic frames, each with its own period, independent of the connection mode;
  - frame shapes as in 17.2 / 17.3, and periods counted from the end of the previous exchange;
  - first frame at daemon start;
  - profiles PHP-only; the daemon receives resolved values, never the profile name;
  - defaults equal to today's behaviour; at least one periodic frame active.
  - Rejected: a single periodic frame; the daemon reading profiles; permanent TCP mode now.
- **ADR-03:** superseded by ADR-22. The same correction goes in the "CSRPreset Dataclass" section, which still describes `presets/`, `ima_protect.json` and "Personnaliser".
- **ADR-06:** note that `bin` has no effect on outgoing frames today; Story 17.1 decides.
- **ADR-08:** staleness = 3 × the shortest active periodic interval (supervision or RP); an ACK to either frame refreshes it.

### PRD (`prd.md`)

- l. 96: IMA Protect preset → CSR behaviour profiles (Epic 17, ADR-22); IMA preset removed (D-84).
- l. 97: wizard step 1 = CSR profile plus collapsed "Options avancées".
- l. 109: community presets → additional CSR profiles in `csr_presets.json`; permanent TCP mode deferred.
- l. 77: "supervision NULL keep-alive" → supervision frame (SIA-DCS or NULL) and/or RP, independently configurable.
- l. 78: 3 missed periodic cycles (shortest active).
- Dated note after l. 42: IMA is no longer a target; field validation is at Scutum with Ajax as the reference; the IMA mentions at l. 48/64/73 are kept as history.

### Deferred work (`deferred-work.md`)

- D-84: a preset mechanism returns in a different form under Epic 17; the removal stands.
- D-42: carried by Story 17.2.
- D-86: addressed by Story 17.2 (`null` option; the default stays `sia-dcs`).
- New D-115: persistent TCP connection mode, deferred, with the observed Ajax behaviour and the work needed if revisited.

### Tracking (`sprint-status.yaml`)

- Epic 17 is added: `epic-17` backlog, `17-1` … `17-5` backlog, retrospective optional.
- 11-1 is commented out and excluded from the counters.
- Counters:

  | Counter | Before | After |
  |---|---|---|
  | total_epics | 15 | 16 |
  | epics_backlog | 1 | 2 |
  | total_stories | 63 | 67 |
  | stories_backlog | 6 | 11 |
  | stories_ready_for_dev | 2 | 1 |

### Documentation

- `internal-docs/ajax.md`:
  - captures A and B analysed, with the derived Ajax model and capture A's extranet log;
  - comparison table updated;
  - "À faire" points 2-4 moved to Epic 17, with permanent mode deferred.

## 5. Implementation Handoff

**Scope: Moderate.** The backlog is reorganised: new epic and one cancelled story. There is no replan of the MVP.

- **SM / Developer:** create the 17.1 story file (bmad-create-story), then implement in order. Each story includes level1 tests, written before any live trial.
- **Herve:**
  - Story 17.4 UI validation on test-jeedom;
  - the Scutum sends in Story 17.5;
  - the extranet RP log for capture B (period at a 5 min ping interval), still to be supplied.

**Success criteria:**
- With no profile chosen, an existing installation behaves exactly as before: same frames, same cadence.
- The Scutum profile shows "Test Cyclique" every ~60 s in the Scutum extranet, with no link alarm.
- SM1 reports a lost link after 3 × the shortest active period without an ACK.
- The first periodic frame leaves at daemon start (D-42 closed).
