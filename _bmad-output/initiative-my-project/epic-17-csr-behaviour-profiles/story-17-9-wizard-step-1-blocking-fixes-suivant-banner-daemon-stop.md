---
id: 9
type: story
title: "17.9 — Wizard Step 1 Blocking Fixes (Suivant, Banner, Daemon Stop)"
parent: epic-17-csr-behaviour-profiles
after: [4]
hitl: false
risk: medium
---

# 17.9 — Wizard Step 1 Blocking Fixes (Suivant, Banner, Daemon Stop)

## Description

Suivant works on every click, including after Relancer l'assistant (B1); every refusal at step 1 lists all errors together in a banner and next to each field; the dialogs that promise to stop the daemon really stop it (B3); disabled wizard buttons look disabled.

## Acceptance Criteria

Verify: A jsdom scenario clicks Suivant, saves, relaunches the wizard and clicks Suivant again, which validates and saves. A form with several errors shows all of them in the banner (role=alert) and under each field (aria-describedby), with focus on the first. Confirming the dialog calls the daemon stop and cancelling or a save error re-enables the buttons. Disabled wizard buttons, step 2 included, carry the class disabled.

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- ux — ux-17-wizard-step-1/EXPERIENCE.md, Buttons, Banner and field errors, Accessibility Floor
- design — internal-docs/design/wizard-design.md, sections on Relancer l'assistant and daemon stop (code to follow the existing spec)

## Notes

- Unknown: Is there a Jeedom core deamonStop action the JS can call, or does the plugin AJAX need a new stop action? Check at plan time.
