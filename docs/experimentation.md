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
- `/bmad-review-adversarial-general` — 9 adversarial review passes applied to date; all findings resolved. Review 9 (2026-03-27): 12 findings across all 8 design documents, focusing on cross-document incoherence, architecture patterns, and Jeedom/daemon integration. Key issues caught: SM2 IDLE-is-startup-only (CONFIRMED/FAILED→PENDING direct transitions), CRC format interoperability (detect on first CSR response rather than assume hex), encryption key scope leak in PHP `exec()` call (scrub immediately after), wizard restart race condition (save `wizard_step=0` before `deamon_stop()`), ring buffer DB write flood reduced 10× (1 440→144/day via 10-min throttle), and logging architecture separation — all SM1/SM2 state-machine log lines centralized into `_log_sm1_supervision()` / `_log_sm2_event()` helpers with typed context dataclasses; supervision code calls helpers, not `self._logger` directly.

---

## Phase 3 — Implementation (planned, 8 weeks)

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
- **The adversarial review step (`/bmad-review-adversarial-general`) caught real issues.** 9 review passes, ~100 findings across 8 design documents — including invented protocol behaviors, stale state machine references, security risks (encryption key in process list), DB write floods, and architecture incoherence that would have caused bugs in implementation.
- **Artifacts accumulate fast.** By the end of design phase, 8 detailed design documents (each 200–500 lines) were produced and cross-referenced — a level of documentation that would have been impractical to write manually in the same timeframe.
