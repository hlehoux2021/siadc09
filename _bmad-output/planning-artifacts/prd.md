---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success']
inputDocuments:
  - '_bmad-output/brainstorming/brainstorming-session-2026-02-17.md'
  - 'internal-docs/design/daemon-design.md'
  - 'internal-docs/design/php-core-design.md'
  - 'internal-docs/design/wizard-design.md'
  - 'internal-docs/design/supervision-design.md'
  - 'internal-docs/design/error-handler-design.md'
  - 'internal-docs/design/logging-design.md'
  - 'internal-docs/design/debug-ui-design.md'
  - 'internal-docs/design/widget-design.md'
  - 'internal-docs/experimentation.md'
workflowType: 'prd'
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 1
  projectDocs: 9
classification:
  projectType: 'iot_embedded'
  projectTypeNote: 'Jeedom platform plugin — no firmware, software-only'
  domain: 'security'
  domainNote: 'Jeedom Market security category — alarm/CSR bridge; no life safety codes or PE requirements'
  complexity: 'high'
  complexityReasons: 'AES-128 CBC encryption, real-time state machines (SM1+SM2), SIA DC-09-2021 protocol compliance, Jeedom internals'
  projectContext: 'brownfield'
  distribution: 'Jeedom Market (security category)'
---

# Product Requirements Document - my-project

**Author:** Herve
**Date:** 2026-03-10

## Executive Summary

The **siaDC09** plugin bridges Jeedom's alarm plugin to a professional Central Station Receiver (CSR) using the SIA DC-09-2021 (*Internet Protocol Event Reporting*) industry standard. It enables Jeedom users who already own home automation hardware to access 24/7 professional alarm monitoring — without purchasing proprietary hardware from a traditional alarm company.

The plugin targets Jeedom power users who have deployed the Jeedom alarm plugin and want professional monitoring continuity: the assurance that a trained operator receives and responds to alarm events even when the user is unreachable. The core value is **peace of mind and trust** — confidence that the system is working reliably and that events reach a human professional, not just a push notification.

The v1.0 release targets **IMA Protect** as the sole CSR preset, leveraging their offer for customers who are already equipped with compatible home automation hardware. All SIA DC-09 protocol complexity (encryption, timestamps, supervision keep-alives, ACK/NAK state machines) is hidden behind a zero-jargon configuration wizard in plain French.

### What Makes This Special

Traditional alarm monitoring forces users to buy a second set of sensors bundled with the alarm company's proprietary system. Jeedom users already own the sensors, the automation logic, and the alarm management layer (Jeedom alarm plugin). **siaDC09** is the missing transport bridge — the only Jeedom Market plugin that converts an existing Jeedom alarm setup into a professionally monitored security system.

The key insight: IMA Protect's open offer for pre-equipped users removes the last barrier. The plugin makes this accessible to non-technical users through a configuration wizard that speaks domain language (zone names, camera associations, notification contacts) — never protocol language.

Continuous supervision health monitoring is a first-class feature, not an afterthought: the plugin maintains a persistent SIA DC-09 supervision heartbeat and exposes its health state as a Jeedom INFO command, enabling scenarios to react to monitoring loss before an alarm event ever occurs.

## Project Classification

- **Project Type:** Jeedom platform plugin (`iot_embedded`) — Python asyncio daemon + PHP plugin core, no firmware
- **Domain:** Security (`security` — Jeedom Market category) — professional alarm monitoring bridge
- **Complexity:** High — AES-128 CBC encryption, dual state machines (SM1 connection/supervision + SM2 alarm event), SIA DC-09-2021 protocol compliance, Jeedom internals integration
- **Project Context:** Brownfield — extends existing Jeedom ecosystem; builds on `jeedom-daemon-py` framework and `aiodemo` plugin patterns
- **Distribution:** Jeedom Market (`security` category)

## Success Criteria

### User Success

- A non-technical Jeedom user completes the configuration wizard and establishes a working supervision connection to IMA Protect without any knowledge of the SIA DC-09 protocol
- Every alarm event (burglar, fire, panic) sent to the CSR produces a visible outcome: `last_event_success` = 1 (ACK confirmed) or an immediate critical notification on failure — no silent failures
- Any failure of the monitoring link (event undelivered, supervision lost) triggers a critical notification through the user's configured safe-path channel (push, SMS, or other Jeedom notification command)
- The supervision health state is visible on the Jeedom dashboard widget at all times, giving the user continuous confidence that professional monitoring is active

### Business Success

- Plugin released as free, open-source software on GitHub under the Jeedom community ecosystem
- Plugin architecture allows community contributors to add CSR presets beyond IMA Protect without modifying the core transport layer
- At least one real-world deployment validates end-to-end supervision and alarm event delivery to IMA Protect

### Technical Success

- Full SIA DC-09-2021 protocol compliance: AES-128 CBC encryption, correct timestamp handling, supervision NULL keep-alive, ACK/NAK dialog, SIA-DCS data block per Annex B with DC-03 area (`Nri1/…`, ADR-21 — corrected 2026-10-17)
- Supervision heartbeat maintained continuously; SM1 state machine detects connection degradation within 3 missed supervision cycles and notifies the user
- Alarm event delivery: immediate failure report on error; at least one retry on timeout before declaring failure and triggering critical notification
- CSR assumed always available (no failover in v1.0); network-level transient errors handled via SM1 reconnection logic (TCP) or supervision timeout detection (UDP)
- All INFO commands (`supervision_state`, `supervision_label`, `last_event_success`, `last_event_status`) updated in real time after every state transition

### Measurable Outcomes

- Zero silent failures: every undelivered alarm event results in a critical notification within the SIA DC-09 ACK timeout window
- Supervision state lag ≤ one supervision interval after a connection change
- Plugin installs cleanly via Jeedom dependency manager with no manual steps beyond the wizard

## Product Scope

### MVP — v1.0

- SIA DC-09-2021 protocol engine: message builder, AES-128 CBC encryption, ACK/NAK parser, UDP + TCP transport
- SM1 (connection/supervision) + SM2 (alarm event) state machines
- 3 alarm event types: burglar alarm, fire alarm, panic alarm
- IMA Protect CSR preset (single CSR, no failover)
- Zero-jargon configuration wizard (4 steps: CSR preset, live connection test, zone mapping, notifications)
- Zone mapping table: zone order number + zone name → optional camera action + optional media URL; the number is what the SIA frame carries
- Supervision health widget (dashboard + mobile)
- 3-tier error handler: auto-heal, user-actionable, critical infrastructure notifications
- Debug UI: status badge, error panel, protocol inspector (Diagnostic tab)
- Structured logging (French user-facing strings, English debug)
- Jeedom Market–ready: info.json, documentation, icon

### Growth Features — v1.1+

- Timestamp auto-heal via NAK (CSR time resync)
- Retry resilience improvements and supervision history timeline
- Community-contributed CSR presets (architecture already supports extension)
- Restoral and cancel events: BC (Burglary Cancel) followed by OP (Opening Report) when the user disarms during a burglary alarm, both addressed to a configured SIA user number, so the CSR can close the incident as a user-cancelled false alarm (Epic 13 / Story 13.1); BR (Burglary Restore) parked for lack of a source (Story 13.2); FC/PC cancels for fire/panic (Story 13.3)
- Arm/disarm reporting: CL (Closing Report) on arming, OP (Opening Report) on a normal disarm, same user number (Story 13.4)
- Frigate NVR integration for automatic snapshot/clip attachment to alarm events — *implemented, Epic 14 (ADR-17 + amendments 1-4), done 2026-09-26*

### Vision — v1.5+

- Multi-CSR failover (primary + backup receiver) — *scoped 2026-10-02: design spec ready, see ADR-20 in architecture.md; no implementation stories yet, no change to v1.0 scope*
- Auto-configure alarm plugin zone actions from zone mapping table
