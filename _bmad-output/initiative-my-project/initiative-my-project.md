---
type: initiative
title: "siaDC09 - SIA DC-09 professional monitoring for Jeedom"
parent: none
covers: [FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8, FR9, FR10, FR11, FR12, FR13, FR14, FR15, NFR1, NFR2, NFR3, NFR4, NFR5, NFR6, NFR7, NFR8]
after: []
assignee: ""
status: in-progress
risk: medium
---

# siaDC09 - SIA DC-09 professional monitoring for Jeedom

## Description

The **siaDC09** plugin bridges Jeedom's alarm plugin to a professional Central Station Receiver (CSR) using the SIA DC-09-2021 (*Internet Protocol Event Reporting*) industry standard. It enables Jeedom users who already own home automation hardware to access 24/7 professional alarm monitoring — without purchasing proprietary hardware from a traditional alarm company.

## Outcome

The plugin targets Jeedom power users who have deployed the Jeedom alarm plugin and want professional monitoring continuity: the assurance that a trained operator receives and responds to alarm events even when the user is unreachable. The core value is **peace of mind and trust** — confidence that the system is working reliably and that events reach a human professional, not just a push notification.

## Requirements

- FR1: Protocol Message Builder — SIA DC-09-2021 compliant message construction with proper framing
- FR2: AES-128 CBC Encryption/Decryption — Secure encryption and decryption of CSR communications
- FR3: ACK/NAK Parser — Parse and interpret CSR responses and handle acknowledgments/negative acknowledgments
- FR4: UDP Transport — Datagram-based communication with CSR for firewall-friendly deployment
- FR5: TCP Transport — Stream-based communication with CSR and automatic reconnection on failure
- FR6: SM1 State Machine — Manage connection/supervision states (INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING → NO_NETWORK)
- FR7: SM2 State Machine — Manage alarm event states (IDLE → PENDING → CONFIRMED/FAILED)
- FR8: Burglar Alarm Event — Send burglar alarm events to CSR with proper SIA encoding
- FR9: Fire Alarm Event — Send fire alarm events to CSR with proper SIA encoding
- FR10: Panic Alarm Event — Send panic alarm events to CSR with proper SIA encoding
- FR11: IMA Protect CSR Preset — Configure single CSR endpoint for v1.0 without failover — *amended 2026-10-17: IMA removed (D-84); replaced by CSR behaviour profiles (Ajax, Scutum, Personnalisé) in `core/config/csr_presets.json`, still a single CSR without failover (ADR-22, Epic 17)*
- FR12: 4-Step Configuration Wizard — Zero-jargon domain-language setup in French (preset selection, connection test, zone mapping, notifications)
- FR13: Zone Mapping Table — Map zone names to optional camera actions and optional media URLs
- FR14: Supervision Health Widget — Display connection state on Jeedom dashboard and mobile
- FR15: 3-Tier Error Handler — Auto-heal notifications (T1), user-actionable notifications (T2), critical infrastructure notifications (T3)
- NFR1: Zero Silent Failures — Every undelivered alarm must trigger a critical notification within the ACK timeout window
- NFR2: Supervision State Lag ≤ 1 Interval — INFO commands updated immediately after state transitions
- NFR3: Non-Technical Usability — Configuration wizard uses domain language only; no protocol jargon exposed
- NFR4: Full SIA DC-09-2021 Compliance — Encryption, timestamp handling, supervision NULL keep-alive, ACK/NAK dialog — *amended 2026-10-17: supervision frame (`sia-dcs` empty block or `NULL`) and RP periodic test, each configurable with its own period (ADR-22)*
- NFR5: Python 3.10+ / Debian 12+ Platform Floor — Declared in info.json; no legacy compatibility required
- NFR6: Encryption Key Security — Key scrubbed from PHP scope after exec(); debug UI shows length-only
- NFR7: CSR Extensibility — JSON preset architecture allows community-contributed CSR support without modifying core
- NFR8: Clean Installation — Jeedom dependency manager handles all setup; no manual steps required

## Done when

1. Zero silent failures: every undelivered alarm event results in a critical notification within the SIA DC-09 ACK timeout window
2. Supervision state lag ≤ one supervision interval after a connection change
3. Plugin installs cleanly via Jeedom dependency manager with no manual steps beyond the wizard

## Boundaries

The siaDC09 Jeedom plugin (PHP) and its Python daemon. Not the Jeedom alarm plugin, not the central station receiver (CSR) itself.

## References

- prd — initiative-my-project/prd-my-project/prd-my-project.md
- architecture — initiative-my-project/architecture-my-project/architecture-my-project.md
- readiness — implementation-readiness-report-2026-04-07/ and implementation-readiness-report-2026-05-04/
- change proposals — sprint-change-proposal-2026-09-25/, -2026-10-02/, -2026-10-17/, -2026-10-17-csr-profiles/
- requirements — requirements-14-4-frigate-forced-capture-2026-09-26.md
- v6 sources — archive-v6/epics.md, archive-v6/sprint-status.yaml
- deferred work — deferred-work.md (register D-xx), deferred-work-builds.md (build outputs)

## Notes

- Decision: v6 to v7 migration plan approved 2026-11-05, see `../migration-v6-v7/migration-v6-v7.md`.
- Assumption: the Done when section is taken from the PRD Measurable Outcomes; to be reviewed with the owner.
- Open question: requirement ids FR/NFR come from epics.md; the PRD carries none of its own.
