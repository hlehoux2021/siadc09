---
id: 12
type: story
title: "17.12 — Wizard Step 2 Without Dead End"
parent: epic-17-csr-behaviour-profiles
after: [9]
hitl: true
risk: medium
---

# 17.12 — Wizard Step 2 Without Dead End

## Description

A failed or refused test shows the message that was sent (testConnection returns the plaintext frame summary: type, account, transport; never an encrypted frame), only the two allowed suggestions and never the profile as if it were the center, and a Modifier la centrale button that returns to step 1 with values kept and live buttons, even during a running test; an expected DUH in the wizard test path is logged at WARNING in the AJAX handler.

## Acceptance Criteria

Verify: A jsdom scenario covers Modifier la centrale, including a late test answer being ignored and step 1 buttons live on return. A level 1 or 2 test shows testConnection returns the frame summary and no encrypted frame. A DUH on the wizard test path is logged at WARNING; the running daemon's SM1_DUH level is unchanged. Then looked at in the browser on test-jeedom.

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- ux — ux-17-wizard-step-1/EXPERIENCE.md, Step 2 states, Build contracts
- ux — ux-17-wizard-step-1/.memlog.md, D6 D11 D14

## Notes

- DUH at WARNING on the wizard test path only; the running daemon keeps SM1_DUH at error (user, 2026-11-06)
- Runs after 17.9 only, so it can run beside 17.10 and 17.11; they share siaDC09.js in different regions
