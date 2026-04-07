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

**Design documents produced** (all in [`docs/design/`](design/)):

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

**Steps completed (5 of 6+):**

| Step | Focus | Outcome |
|------|-------|---------|
| 1 — Init | Document discovery + project context | 7 cross-cutting concerns identified; 8 NFRs formalized |
| 2 — Context + ADRs + Validation | Self-consistency validation across all design docs | 16 ADRs documented; 5 cross-document inconsistencies found and resolved |
| 3 — Starter Template | Technology stack confirmation | Jeedom plugin template confirmed; Python 3.10+/Debian 12 floor declared |
| 4 — Architectural Decisions | Testing strategy, versioning, CI/CD | Contract-driven 4-level test pyramid; single-version strategy; GitHub Actions with self-hosted Pi 5 runner |
| 5 — Implementation Patterns | Consistency rules for AI agent implementation | 80+ rules across naming, structure, communication, process, and PHP/Python boundary patterns |

**Self-consistency validation findings (Step 2) — all resolved:**
- CRC format detection removed (daemon is sender, not receiver — format is a preset config field)
- `_notify()` call pattern clarified (sync wrapper calling `_track_task(_dispatch_notify(...))`)
- Staleness threshold corrected from 2× to 3× `supervision_interval` across all docs
- SM1 strike reset on TCP reconnect success added to both ADR and daemon pseudocode
- Wizard connection test flow clarified (warn + confirm before daemon stop; JS fields preserved)

**Implementation patterns depth (Step 5):** Went through 5 rounds of Advanced Elicitation and 41 rounds of Party Mode (multiple AI agent perspectives), producing over 200 individual consistency rules covering: exception hierarchy, CSRPreset dataclass, transport layer dispatch, UDP persistent protocol, shutdown discipline, retry/backoff policy, PHP config key namespace, schema versioning, error context schemas, eqLogic lifecycle, canonical file creation order, and Pattern Compliance Checklist.

**Key observations from this phase:**
- The self-consistency validation step alone found 5 real inconsistencies that had survived 11 adversarial reviews — a different class of check (cross-document coherence vs single-document correctness).
- The Party Mode technique (multiple agent personas reviewing in parallel) was particularly effective at surfacing implementation traps invisible to a single reviewer — including the `deamon_` spelling trap, CancelledError swallowing, and UDP socket lifecycle.

---

## Phase 4 — Implementation (planned, 8 weeks)

Implementation will follow the design documents in build sequence order:

1. Daemon skeleton + protocol layer (message builder, UDP/TCP, ACK/NAK)
2. Supervision loop + 3-strike state machine
3. PHP plugin scaffold + auto-equipment
4. Config wizard (steps 1–2: preset + connection test)
5. Config wizard (step 3: zone mapping)
6. Error translation + protocol inspector
7. Widget + notifications + end-to-end testing
8. Polish + documentation + Jeedom Market submission

**BMAD workflows available for implementation phase:**
- `/bmad-bmm-create-epics-and-stories` — Break design docs into sprint-ready stories
- `/bmad-bmm-sprint-planning` — Generate sprint plan
- `/bmad-bmm-dev-story` — AI-assisted story implementation
- `/bmad-bmm-code-review` — Adversarial code review per story

---

## Key Observations for the Team

- **BMAD compressed the design phase significantly.** What would normally require multiple architecture meetings and back-and-forth was completed in a series of focused AI-facilitated sessions.
- **Domain-expert skills (`/sia-dc09-expert`, `/jeedom-plugin`) were essential.** Generic AI knowledge would not have been sufficient for a niche protocol like SIA DC-09 — having a skill that reads and cites the actual standard made all the difference.
- **The adversarial review step (`/bmad-review-adversarial-general`) caught real issues.** 11 review passes, ~120 findings across 8 design documents — including invented protocol behaviors, stale state machine references, security risks (encryption key in process list), DB write floods, architecture incoherence, and Python best practice violations (asyncio task leaks, type safety gaps, deprecated APIs, priority queue crash scenarios) that would have caused silent failures or bugs in implementation.
- **Artifacts accumulate fast.** By the end of design phase, 8 detailed design documents (each 200–500 lines) were produced and cross-referenced — a level of documentation that would have been impractical to write manually in the same timeframe.
- **The architecture phase catches a different class of problem.** Adversarial reviews check correctness within a single document; the self-consistency validation step checks coherence *between* documents. 5 cross-document inconsistencies were found that had survived 11 adversarial review passes — demonstrating that these are genuinely complementary quality tools, not redundant.
- **Multi-agent Party Mode is surprisingly effective for implementation patterns.** Running 41 rounds of simulated multi-agent design review — where different AI personas (architect, developer, QA, analyst, PM) each apply their lens to the same patterns — produced over 200 actionable consistency rules. Many of the most valuable rules came from the developer and QA perspectives catching traps the architect perspective missed.
