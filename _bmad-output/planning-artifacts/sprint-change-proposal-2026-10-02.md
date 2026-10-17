# Sprint Change Proposal — 2026-10-02

**Author:** Herve (via Correct Course workflow)
**Trigger:** Request to add a story enabling failover to a backup monitoring center (centre de télésurveillance de secours)

## 1. Issue Summary

Herve asked to add a story for managing failover to a backup monitoring center (SIA CSR). Investigation showed this is **not a missing story** — it is "Multi-CSR failover (primary + backup receiver)", a feature explicitly listed as **out of scope for v1.0** and deferred to **Vision v1.5+** in both `prd.md:115` and `architecture.md:78`. The idea already existed in the original brainstorming session (`brainstorming-session-2026-02-17.md`) under "Multi-CSR Failover" / "Backup CSR Failover", explicitly moved out of Tier 1 MVP scope at that time.

A secondary issue was found during PRD review: `prd.md:116` still listed "Frigate NVR integration" under "Vision — v1.5+", but this was actually implemented and closed as Epic 14 (ADR-17 + 4 amendments, stories 14-1 through 14-4, all `done` by 2026-09-26). The PRD was never updated when this feature was promoted into the active sprint — a documentation drift, independent of the failover request but corrected in the same pass since both touch the same PRD section.

## 2. Impact Analysis

- **Epic Impact:** None. No existing epic (1-15) is touched. A future Epic 16+ would own eventual implementation, not created by this proposal.
- **Story Impact:** None. No new story created — scope explicitly limited to "scaffolding" (architecture decision only), per Herve's choice.
- **Artifact Conflicts:**
  - `prd.md` — Vision v1.5+ / Growth v1.1+ sections updated (see below).
  - `architecture.md` — new ADR-20 added, documenting the eventual failover design.
  - No UX design document exists for this project; not applicable.
- **Technical Impact:** None yet. ADR-20 is a design record only — `CSRPreset`, SM1, and the wizard/widget are unchanged in code.

## 3. Recommended Approach

**Direct Adjustment — scaffolding only, no implementation.** Herve explicitly chose "Préparer seulement (scaffolding)" over "Promouvoir en v1.0 / prochain sprint": the goal is to capture the architectural decision now (while context is fresh) without creating implementation work or touching the active sprint. This keeps v1.0 finalization (epic 1-5 review) and the in-progress epics 13-15 completely unaffected — ADR-20 touches a different layer (SM1 transport-level failover) that none of the shipped or in-flight stories depend on.

**Effort:** Documentation only, ~0 engineering risk. **Timeline impact:** none — v1.0 is not gated on this.

## 4. Detailed Change Proposals

### 4.1 PRD (`_bmad-output/planning-artifacts/prd.md`)

**Section: `### Growth Features — v1.1+`**

```diff
 - Arm/disarm reporting: CL (Closing Report) on arming, OP (Opening Report) on a normal disarm, same user number (Story 13.4)
+- Frigate NVR integration for automatic snapshot/clip attachment to alarm events — *implemented, Epic 14 (ADR-17 + amendments 1-4), done 2026-09-26*
```
Rationale: corrects a documentation drift — Frigate integration shipped, it is not a future vision item.

**Section: `### Vision — v1.5+`**

```diff
-- Multi-CSR failover (primary + backup receiver)
-- Frigate NVR integration for automatic video clip attachment to alarm events
+- Multi-CSR failover (primary + backup receiver) — *scoped 2026-10-02: design spec ready, see ADR-20 in architecture.md; no implementation stories yet, no change to v1.0 scope*
 - Auto-configure alarm plugin zone actions from zone mapping table
```
Rationale: removes the now-false Frigate entry (moved above); flags failover as spec-ready without promoting it out of Vision.

**Status: APPLIED.**

### 4.2 Architecture (`_bmad-output/planning-artifacts/architecture.md`)

New **ADR-20 — Multi-CSR Failover Design (Vision v1.5+, scoped not scheduled)**, inserted after ADR-19 (before ADR-18). Key decisions reached through discussion with Herve:

| Decision point | Resolution |
|---|---|
| Number of receivers | Exactly 2 (primary + secondary), not an open-ended list |
| Secondary's settings | Shared with primary (`account_number`, `crc_format`, `content_format`, encryption key) — use case is a redundant endpoint at the **same** provider, not an independent second provider |
| Failover trigger | At each transport's existing permanent-failure signal — TCP: before `NO_NETWORK` would stop the daemon (ADR-09/ADR-13); UDP: directly at strike=3 (T3 `SUPERVISION_DISCONNECTED`), since UDP has no reconnection mechanic to exhaust first and extra cycles would repeat the same measurement with no new information |
| Switchback | Daemon restart only — no automatic retry of the primary while running |
| New state machine (SM3) | Rejected — would violate ADR-02's SM1/SM2 independence model for no demonstrated benefit |

**Deferred (not decided, left for a future story):** wizard UI shape (optional Step 1 section, test-both-upfront vs test-secondary-on-first-use, protocol inspector labeling) and widget/dashboard representation (new visual state vs. label variant, new `active_receiver` INFO command) — both listed as open options in the ADR, not resolved here.

**Status: APPLIED.**

## 4.3 Epics & Stories (`_bmad-output/planning-artifacts/epics.md`) — Amendment 2026-10-02

Herve confirmed, after the initial proposal was applied, that he wanted the backlog scaffolding to go one step further: register the epic and its stories now (not just the ADR), so the design has a concrete backlog home — while keeping everything at `backlog` status, not `ready-for-dev`.

Added, append-only, after Epic 15 / Story 15.1 (nothing existing modified):

- **Epic 16: Multi-CSR Failover (Vision v1.5+ — scoped, not scheduled)** — status `backlog`.
- **Story 16.1: CSRPreset Dual Receiver & SM1 Failover Trigger** — fully specified from ADR-20's decisions (2 fixed receivers sharing account/crc_format/content_format/key, TCP switches before `NO_NETWORK`, UDP switches at strike=3 directly, switchback on daemon restart only, no SM3). Implementable as written but intentionally not started.
- **Story 16.2: Wizard & Widget Representation of the Secondary Receiver** — carries ADR-20's two deferred UI points as a blocking Task 0 (wizard test-both-upfront vs. test-on-first-use; widget new-state vs. label-variant), same pattern as story 15-1's Task 0 and story 1-5's Task 8. Stays `backlog` until Task 0 is answered.

**Status: APPLIED.**

### Why not `bmad-create-epics-and-stories` or `bmad-create-story`

Both were considered and rejected for this addition:
- `bmad-create-epics-and-stories`'s first step re-initializes `epics.md` from an empty template before re-extracting all FRs/NFRs — destructive to the 15 existing epics and ~61 stories, several in-flight (1-5 in review, 15-1 in-progress). Not safe to run on a mature backlog.
- `bmad-create-story` assumes the target epic/story already exists in `epics.md`/`sprint-status.yaml` — it discovers and elaborates a story, it does not create new epic sections.

This matches the project's own established pattern: epics 13, 14, and 15 were each registered directly through a correct-course pass rather than through `bmad-create-epics-and-stories`.

## 5. Implementation Handoff

**Scope classification: Minor** (documentation/backlog-only change, applied directly within this workflow — no code, no change to any in-flight story).

- **Routed to:** No handoff needed for this proposal itself — it is complete as applied.
- **Future handoff (when failover is actually scheduled for a sprint):** Product Owner / Developer, to resolve Story 16.2's Task 0, move both stories to `ready-for-dev`, and pick up Story 16.1 for implementation.

**Success criteria:** `prd.md` and `architecture.md` reflect the corrected scope and the new design record; `epics.md` carries Epic 16 and its two stories at `backlog`; `sprint-status.yaml` counters recomputed and matched (total_epics 15→16, total_stories 61→63, epics_backlog 0→1, stories_backlog 4→6); no existing epic, story, or in-flight status changed.
