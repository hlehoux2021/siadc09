# BMAD Experimentation — Jeedom SIA DC-09 Plugin

> High-level log of how the BMAD method (Breakthrough Method for AI Development) was used to design this plugin from scratch, for team presentation purposes.

---

## What is BMAD?

BMAD is a structured AI-assisted development method that guides projects through ideation, planning, architecture, and implementation using specialized AI agents. Each phase produces concrete artifacts (documents, specs, plans) that feed the next phase.

In this project, BMAD was used as a **design accelerator** — replacing weeks of whiteboard sessions with structured AI-facilitated workshops.

---

## The Project

**Goal:** Build a Jeedom home automation plugin that bridges alarm events from a Jeedom installation to a professional Central Station Receiver (CSR) using the **SIA DC-09-2021** protocol over UDP/TCP.

**Why it matters:** SIA DC-09 is the industry standard for IP alarm reporting. Implementing it correctly requires handling encryption, CRC validation, strict timing, acknowledgement/retry logic, and supervision heartbeats — all while presenting a zero-technical-knowledge interface to the end user.

---

## Phase 1 — Ideation (February 2026)

**BMAD workflow used:** Brainstorming (`/bmad-brainstorming`)

**What happened:** A facilitated AI brainstorming session explored the full problem space across 7 design dimensions: architecture, transport, event mapping, configuration UX, zone/camera integration, status feedback, and error handling. Four ideation techniques were applied sequentially.

**Output:** [`_bmad-output/brainstorming/brainstorming-session-2026-02-17.md`](../_bmad-output/brainstorming/brainstorming-session-2026-02-17.md)

**Techniques applied (AI-recommended sequence):**

1. **First Principles Thinking** — Stripped away all assumptions to identify the irreducible core of the problem. Key insight: the plugin is a *transport bridge*, not an alarm system — it takes a standardized Jeedom event and delivers it via SIA DC-09, nothing more.
2. **Morphological Analysis** — Built a structured matrix of 8 independent design dimensions (transport, encryption, event mapping, UI, error recovery, camera integration, status feedback, debugging) and systematically explored all viable combinations (~12–15 out of a theoretical 256). Cross-dimension synergies emerged that would have been missed with ad-hoc design.
3. **Assumption Reversal** — Challenged the assumption that "easy setup" and "powerful debugging" are in conflict. This unlocked the dual-audience design: a zero-protocol wizard for end users, and a full protocol inspector for integrators.
4. **Day in the Life Scenario Walking** — Walked through 4 concrete user journeys (first setup, alarm event, supervision loss, expert debugging) to validate UX decisions against real stress conditions.

**Key outcomes:**
- 69 ideas generated across 4 techniques
- Plugin-centric architecture selected (auto-created equipment, not user-created)
- Supervision health monitoring identified as the primary daemon responsibility
- Zero-protocol configuration wizard concept validated
- Zone-to-camera mapping pattern defined
- 3-tier error handling model (auto-heal / user-actionable / infrastructure) established

---

## Phase 2 — Component Design (February–March 2026)

Rather than generating a formal PRD and architecture document via BMAD workflows, the project adopted a **custom component-by-component design process** directly guided by the brainstorming outcomes. Each component was designed interactively with dedicated domain-expert AI skills (`/sia-dc09-expert`, `/jeedom-plugin`).

**Design documents produced** (all in [`internal-docs/design/`](design/)):

| Component | Document | Scope |
|-----------|----------|-------|
| 0 — Protocol Layer | [`daemon-design.md`](design/daemon-design.md) | SIA DC-09 message builder, crypto, CRC, ACK/NAK parser, CSR simulator |
| 1 — Daemon Core | [`daemon-design.md`](design/daemon-design.md) | Async event loop, SM1 (connection/supervision) + SM2 (alarm event) state machines, priority queue |
| 2 — PHP Plugin Core | [`php-core-design.md`](design/php-core-design.md) | eqLogic/cmd classes, auto-equipment, INFO commands, daemon bridge |
| 3 — Config Wizard | [`wizard-design.md`](design/wizard-design.md) | 4-step zero-protocol wizard, CSR presets, live connection test, zone mapping table |
| 4 — Supervision & Health | [`supervision-design.md`](design/supervision-design.md) | 3-strike degradation model, SM1 state machine, TCP half-open detection |
| 5a — Error Handler | [`error-handler-design.md`](design/error-handler-design.md) | 3-tier error classification, 6-code ErrorCode enum, notification routing |
| 5b — Logging | [`logging-design.md`](design/logging-design.md) | Dual-line log pattern, ring buffer, French user messages, Jeedom integration |
| 5c — Debug UI | [`debug-ui-design.md`](design/debug-ui-design.md) | Protocol inspector panel, error panel, diagnostic tab, encrypted frame decoding |
| 6 — Widget | [`widget-design.md`](design/widget-design.md) | Real-time supervision badge, last event status, staleness detection |

**BMAD quality tools used:**
- `/bmad-review-adversarial-general` — 11 adversarial review passes applied to date; all findings resolved. Review 9 (2026-03-27): 12 findings — cross-document incoherence, architecture patterns, Jeedom/daemon integration. Review 10 (2026-03-27): 10 findings — Python best practices pass. Key issues caught in R10: asyncio task lifecycle (untracked fire-and-forget tasks vulnerable to garbage collection and silent exception loss), priority queue crash on simultaneous alarms (fixed with monotonic counter tie-breaker), API type safety throughout (TypedDict return type, Literal trigger parameters, keyword-only required argument), Python version floor formally declared via Jeedom's Debian OS constraint mechanism, deprecated datetime API replaced, and redundant data eliminated from logging context dataclasses. Review 11 (2026-03-30): 9 findings applied — second Python best practices pass. Key issues: missing `asyncio.wait_for()` wrapper on TCP connect (bare `asyncio.open_connection()` could hang indefinitely on filtered ports), `ValueError` from CRC format detection not caught inside `_send_raw()` (design prose and code block contradicted each other), instance attribute `_tasks` initialized in `on_start()` instead of `__init__()` (AttributeError risk if `on_stop()` called before startup completes), SIA code lookup dict `_event_sia_code` mislabelled as function and misplaced in logging-design (moved to daemon-design as `_EVENT_SIA_CODES` constant), `_track_task()` parameter untyped and task name missing (unhelpful `Task-N` in error logs), `PriorityQueue` not parameterized with item type, and `Optional[Union[...]]` type aliases replaced with Python 3.10+ `|` syntax (misleading "all Python versions" comment removed).

---

## Phase 3 — Solution Architecture (March–April 2026)

**BMAD workflow used:** Create Architecture (`/bmad-bmm-create-architecture`)

**What happened:** With all 9 component design documents complete, the create-architecture workflow was run to synthesize them into a formal, implementation-ready architecture document. The workflow is structured in sequential steps: project context analysis, self-consistency validation, starter template selection, core architectural decisions, and implementation patterns.

**Output:** [`_bmad-output/planning-artifacts/architecture.md`](../_bmad-output/planning-artifacts/architecture.md)

**Steps completed (8 of 8 — COMPLETE):**

| Step | Focus | Outcome |
|------|-------|---------|
| 1 — Init | Document discovery + project context | 7 cross-cutting concerns identified; 8 NFRs formalized |
| 2 — Context + ADRs + Validation | Self-consistency validation across all design docs | 16 ADRs documented; 5 cross-document inconsistencies found and resolved |
| 3 — Starter Template | Technology stack confirmation | Jeedom plugin template confirmed; Python 3.10+/Debian 12 floor declared |
| 4 — Architectural Decisions | Testing strategy, versioning, CI/CD | Contract-driven 4-level test pyramid; single-version strategy; GitHub Actions with self-hosted Pi 5 runner |
| 5 — Implementation Patterns | Consistency rules for AI agent implementation | 80+ rules across naming, structure, communication, process, and PHP/Python boundary patterns |
| 6 — Project Structure | Directory layout and component file organization | Complete siadc09 plugin structure (adapted from aiodemo template); all 8 design components mapped to files; requirements-to-file traceability established |
| 7 — Validation | Architecture coherence and readiness verification | All checks passed (decision compatibility ✅, pattern consistency ✅, structure alignment ✅); 12 FRs + 7 NFRs covered; implementation readiness HIGH |
| 8 — Completion | Architecture finalization and implementation handoff | 1,400+ line architecture.md; all 8 design docs aligned; 16 ADRs + 200+ consistency rules; implementation sequence confirmed |

**Self-consistency validation findings (Step 2) — all resolved:**
- CRC format detection removed (daemon is sender, not receiver — format is a preset config field)
- `_notify()` call pattern clarified (sync wrapper calling `_track_task(_dispatch_notify(...))`)
- Staleness threshold corrected from 2× to 3× `supervision_interval` across all docs
- SM1 strike reset on TCP reconnect success added to both ADR and daemon pseudocode
- Wizard connection test flow clarified (warn + confirm before daemon stop; JS fields preserved)

**Implementation patterns depth (Step 5):** Went through 5 rounds of Advanced Elicitation and 41 rounds of Party Mode (multiple AI agent perspectives), producing over 200 individual consistency rules covering: exception hierarchy, CSRPreset dataclass, transport layer dispatch, UDP persistent protocol, shutdown discipline, retry/backoff policy, PHP config key namespace, schema versioning, error context schemas, eqLogic lifecycle, canonical file creation order, and Pattern Compliance Checklist.

**Project structure mapping (Step 6):** Adapted the existing Jeedom aiodemo plugin template to siadc09. File naming and class naming updated throughout (aiodemo → siadc09). All 8 design components mapped to concrete file paths with clear boundaries. Requirements-to-file traceability established, showing which design decisions are realized in which source files.

**Architecture validation (Step 7):** Comprehensive validation covering: (1) decision compatibility — all 16 ADRs consistent, no internal contradictions; (2) pattern consistency — 200+ rules applied across all boundary types; (3) structure alignment — project layout matches architectural boundaries. All 12 functional requirements and 7 non-functional requirements verified covered. Implementation readiness assessed as HIGH confidence.

**Workflow completion (Step 8):** Architecture document finalized at 1,400+ lines with complete frontmatter (stepsCompleted, workflowStatus, completedAt). All 8 design documents aligned with architecture patterns in a single focused session. Implementation handoff package includes: file structure blueprint, build sequence (8 phases), consistency checklist for code review, and deployment target specification (Raspberry Pi 5, Debian 12).

**Key observations from this phase:**
- The self-consistency validation step alone found 5 real inconsistencies that had survived 11 adversarial reviews — a different class of check (cross-document coherence vs single-document correctness).
- The Party Mode technique (multiple agent personas reviewing in parallel) was particularly effective at surfacing implementation traps invisible to a single reviewer — including the `deamon_` spelling trap, CancelledError swallowing, and UDP socket lifecycle.

---

## Phase 4 — Epic & Story Decomposition (April 2026)

**BMAD workflow used:** Create Epics and Stories (`/bmad-bmm-create-epics-and-stories`)

**What happened:** With architecture fully documented and validated, the create-epics-and-stories workflow was run to decompose the 9 design components and 12 FRs into a sprint-ready epic and story breakdown. The workflow processes sequentially: validate prerequisites → design epics → create stories → final validation.

**Output:** [`_bmad-output/planning-artifacts/epics.md`](../_bmad-output/planning-artifacts/epics.md)

**Workflow completion (Steps 1–4 — COMPLETE):**

| Step | Focus | Outcome |
|------|-------|---------|
| 1 — Validate Prerequisites | Requirements inventory assembly | 15 FRs + 8 NFRs extracted; all inputs validated; 2 input documents linked |
| 2 — Design Epics | Epic structure and dependencies | 11 epics designed around components, not user journeys (deliberate rejection of value-stream decomposition in favor of technical architecture); corrected dependency chain (Epic 2 depends on 1.1+1.2 only, not full Epic 1) |
| 3 — Create Stories | Story breakdown with acceptance criteria | 37 stories written across 11 epics; each story has clear AC, no forward dependencies; 6 critical stories enhanced with detailed test strategies from design docs |
| 4 — Final Validation | Coverage + dependency + quality checks | ✅ All 15 FRs mapped ✅ No forward dependencies ✅ 11-epic chain valid ✅ Design doc integration complete |

**Epic structure (11 total, 37 stories):**

1. **Protocol Engine** (3 stories) — message builder, AES-128, ACK/NAK parser
2. **CSR Simulator** (5 stories) — standalone tool for Ajax protocol testing (separate from Jeedom plugin, releasable)
3. **Error Handler** (3 stories) — ErrorCode enum, notification contexts, callback contracts (design-doc integrated)
4. **Logging** (3 stories) — messages.py French strings, logging infrastructure, ring buffer (design-doc integrated)
5. **Daemon Core** (6 stories) — SM1 + SM2 state machines, transport, task lifecycle (SM1/SM2 design-doc integrated)
6. **PHP Plugin** (6 stories) — eqLogic, auto-equipment, IPC, INFO commands, dependency manager
7. **Supervision** (3 stories) — supervision loop, strike escalation, TCP stall detection (design-doc integrated)
8. **Config Wizard** (3 stories) — 4 steps, CSR preset selection, zone mapping
9. **Debug UI** (3 stories) — status badge, error panel, protocol inspector
10. **Widget** (2 stories) — supervision health display, staleness detection
11. **E2E Testing & Market** (4 stories) — Ajax protocol conformance, IMA Protect validation, documentation (CSR validation design-doc integrated)

**Design doc integration approach (6 critical stories):**

Rather than embed full test harness details in all 37 stories, a selective integration strategy was applied:
- **Critical stories** (SM1, SM2, Supervision, ErrorCode, messages.py, CSR Validation) receive detailed test strategies, test data filenames, validation thresholds, logging output tables, and state transition matrices extracted from design documents
- **Other stories** include cross-references to relevant design doc sections with brief AC summaries
- Design documents remain the authoritative source for edge cases, protocols, and architectural patterns

This balanced approach keeps acceptance criteria readable while ensuring developers have everything needed for the most complex/critical components.

**Key decisions from this phase:**
- Epic 2 (CSR Simulator) made standalone and releasable (not bundled with plugin) — enables protocol testing for other alarm systems (Ajax, etc.)
- Epics organized by technical components (not user journeys) since v1.0 is already minimal scope — this front-loads the infrastructure and enables dependent features
- Corrected Epic 2 dependency chain: depends on Protocol Engine stories 1.1 + 1.2 only, not full Epic 1

**Next workflow:** `/bmad-bmm-check-implementation-readiness` — Validates that PRD + Architecture + Epics/Stories are fully aligned and complete before implementation begins.

---

## Key Observations for the Team

- **BMAD compressed the design phase significantly.** What would normally require multiple architecture meetings and back-and-forth was completed in a series of focused AI-facilitated sessions.
- **Domain-expert skills (`/sia-dc09-expert`, `/jeedom-plugin`) were essential.** Generic AI knowledge would not have been sufficient for a niche protocol like SIA DC-09 — having a skill that reads and cites the actual standard made all the difference.
- **The adversarial review step (`/bmad-review-adversarial-general`) caught real issues.** 11 review passes, ~120 findings across 8 design documents — including invented protocol behaviors, stale state machine references, security risks (encryption key in process list), DB write floods, architecture incoherence, and Python best practice violations (asyncio task leaks, type safety gaps, deprecated APIs, priority queue crash scenarios) that would have caused silent failures or bugs in implementation.
- **Artifacts accumulate fast.** By the end of design phase, 8 detailed design documents (each 200–500 lines) were produced and cross-referenced — a level of documentation that would have been impractical to write manually in the same timeframe.
- **The architecture phase catches a different class of problem.** Adversarial reviews check correctness within a single document; the self-consistency validation step checks coherence *between* documents. 5 cross-document inconsistencies were found that had survived 11 adversarial review passes — demonstrating that these are genuinely complementary quality tools, not redundant.
- **Multi-agent Party Mode is surprisingly effective for implementation patterns.** Running 41 rounds of simulated multi-agent design review — where different AI personas (architect, developer, QA, analyst, PM) each apply their lens to the same patterns — produced over 200 actionable consistency rules. Many of the most valuable rules came from the developer and QA perspectives catching traps the architect perspective missed.
- **Architecture workflow is fully complete.** Steps 6–8 (project structure, validation, finalization) took one focused session following Step 5, demonstrating that with comprehensive patterns in place, the final synthesis moves quickly. Implementation can now proceed with high confidence from the architecture blueprint.
- **Design doc integration into stories is selective, not exhaustive.** Rather than embedding the full test harness spec into all 37 stories (which would balloon acceptance criteria and reduce readability), critical stories (SM1, SM2, Supervision, ErrorCode, messages.py, CSR Validation) received detailed integration while others use cross-references. This keeps stories actionable while preserving design docs as the authoritative source — a practical balance between convenience and maintainability.
- **Epic structure choice: components over user journeys.** For a system with v1.0 as hard scope (no phased user-value delivery), organizing by technical components is more appropriate than user journeys. This front-loads infrastructure dependencies and enables dependent features — clearer for development planning.
- **CSR Simulator as standalone epic was a good call.** Separating the simulator from the plugin (Epic 2 of 11) makes it independently testable, releasable, and useful for protocol validation against other alarm systems (e.g., Ajax). This emerged naturally from the story creation process and represents a minor but valuable scope clarification.

---

## Phase 5 — Implementation Readiness (April 2026)

**BMAD workflow used:** Check Implementation Readiness (`/bmad-bmm-check-implementation-readiness`)

**What happened:** With all planning artifacts complete (PRD, Architecture, Epics & Stories), the readiness check workflow was run to validate alignment and completeness across all three documents. The workflow performs document discovery, PRD coverage analysis, epic/story validation, architecture alignment, and quality review — producing a formal go/no-go assessment for implementation.

**Output:** [`_bmad-output/planning-artifacts/implementation-readiness-report-2026-04-07.md`](../_bmad-output/planning-artifacts/implementation-readiness-report-2026-04-07.md)

**Workflow completion (Steps 1–6 — COMPLETE):**

| Step | Focus | Outcome |
|------|-------|---------|
| 1 — Document Discovery | Artifact inventory assembly | 3 documents found (PRD, Architecture, Epics); 0 duplicates; UX design not found (expected, deferred from planning) |
| 2 — PRD Analysis | Functional + non-functional requirement coverage | 15 FRs + 8 NFRs verified against prd.md; 100% coverage across all epics |
| 3 — Epic Coverage Validation | Story-to-FR traceability | 37 stories across 11 epics; no orphaned epics; no forward dependencies; complete coverage of all FRs |
| 4 — UX Alignment | Wizard/widget coherence check | wizard-design.md + widget-design.md aligned with PRD UX requirements; zero-protocol goal confirmed |
| 5 — Epic Quality Review | Story acceptance criteria completeness | 6 critical stories with design-doc-integrated test strategies validated; AC clear and verifiable for all stories |
| 6 — Final Assessment | Blockers + readiness verdict | **0 critical issues ✅ | 0 minor issues ✅ | READY FOR IMPLEMENTATION** |

**Assessment summary:**
- **Overall Readiness:** READY FOR IMPLEMENTATION
- **Assessment Status:** COMPLETE — All Issues Resolved
- **Critical Blockers:** 0
- **Requirement Coverage:** 100% (17/17 FRs + NFRs)
- **Epic Dependency Violations:** 0
- **Resolution Date:** 2026-04-07

**Key validation outcomes:**
- All 15 functional requirements traced to specific epics and stories
- All 8 non-functional requirements embedded in architecture and epic design (e.g., supervision heartbeat intervals in Epic 7, encryption in Epic 1)
- Zero forward dependencies confirmed (all stories have complete prerequisites)
- Epic 1 → Epic 2 dependency chain validated (simulator depends only on protocol + crypto, not error handler)
- Configuration wizard (Epic 8) properly sequenced after daemon infrastructure (Epics 1–5)
- All design-doc-integrated test strategies (SM1, SM2, Supervision, ErrorCode, messages.py, CSR Simulator) verified against acceptance criteria
- Security properties validated (encryption key scrubbing, principal least-privilege, no cleartext supervision)

**Next workflow:** `/bmad-bmm-sprint-planning` — Generates sprint status and implementation task sequence for the development phase. Kicks off the 4-implementation phase where stories will be cycled through create → validate → develop → review → repeat.

---

## Phase 6 — Implementation (April 2026)

**BMAD workflow used:** Dev Story (`/bmad-bmm-dev-story`) — Story-by-story implementation with domain expert validation

**What's happening:** Stories are being implemented in dependency order using the dev-story workflow. Each story goes through: (1) expert skill validation of approach before coding, (2) implementation via code agent, (3) test execution with coverage verification, (4) code review with adversarial findings, and (5) approval → done.

**Implementation progress (11 Epics, 37 Stories):**

| Epic | Title | Stories | Status |
|------|-------|---------|--------|
| 1 | Protocol Engine | 3 | 1/3 done |
| 2 | CSR Simulator | 5 | Backlog |
| 3 | Error Handler | 3 | Backlog |
| 4 | Logging | 3 | Backlog |
| 5 | Daemon Core | 6 | Backlog |
| 6 | PHP Plugin | 6 | Backlog |
| 7 | Supervision | 3 | Backlog |
| 8 | Config Wizard | 3 | Backlog |
| 9 | Debug UI | 3 | Backlog |
| 10 | Widget | 2 | Backlog |
| 11 | E2E Testing & Market | 4 | Backlog |

**Completed Stories:**

### Story 1.1: SIA Protocol Message Builder ✅ DONE

**Status:** Completed 2026-04-09 (code review + pylint + tests all passing)

**Implementation approach:**
- Created `SIAMessageBuilder` class with integrated `SequenceTracker` for automatic per-account sequence management
- Implemented CRC-16 MODBUS algorithm (not zlib.crc32) per expert validation
- Timestamp formatting as `_HH:MM:SS,MM-DD-YYYY` (20 chars, UTC) — corrected per expert
- All message building functions as private methods on builder class (encapsulation)
- Backward-compatibility alias `SequenceManager = SequenceTracker` for future migrations

**Test results:**
- **96 unit tests** all passing (92 existing + 4 new sequence increment tests)
- **Coverage:** Constants, SequenceTracker, CRC, length, account IDs, data fields, timestamps, complete encoding, NULL messages, sequence per-account independence, wrap-around (9999→0001), reset functionality
- **Pylint:** 10.00/10 perfect score

**Code review findings (1-1-sia-protocol-message-builder code review, 2026-04-09):**
- **Critical issues found and fixed:** 5 (task spec mismatches, signature mismatches, documentation gaps)
- **Medium issues found and fixed:** 5 (test count, module structure, API patterns, backward-compat clarity)
- **All findings resolved:** Story file Tasks section updated to match class-based implementation; API usage patterns documented; Dev Notes rewritten

**Files created/modified:**
- `resources/siadc09d/sia_protocol.py` (main module, 416 lines)
- `tests/level1/test_sia_protocol.py` (96 tests, 2070 lines)
- `_bmad-output/implementation-artifacts/1-1-sia-protocol-message-builder.md` (story file, fully aligned with implementation)

**Key decisions documented:**
- `crc_format` set at builder initialization (not per-call) — enforces preset config
- Sequence auto-increments on each `encode_message()` call (no separate call needed)
- Private methods on builder for all message components (CRC, length, account ID, data field, timestamp)
- Deprecated `SequenceManager` alias kept for backward compatibility only

**Next story:** 1.2 (AES-128 CBC Encryption Module) — will import this module to encrypt plaintext frames

**Expert skills consulted:**
- `sia-dc09-expert` — Protocol validation (CRC algorithm, timestamp format, frame structure)

**Observation:** The code review identified 10 distinct issues (5 critical, 5 medium) that had survived the development process. Story file Tasks section documentation was significantly out of sync with the class-based implementation that emerged. Updates took ~45 min to resolve all findings and ensure consistency across story file, Dev Notes, and implementation. Type safety and documentation improvements added significant value.
