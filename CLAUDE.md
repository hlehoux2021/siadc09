# Project Context

This project implements the **SIA DC-09-2021.17** protocol (*Internet Protocol Event Reporting*).

The full protocol reference is at `docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`.

## Experimentation Log

`docs/experimentation.md` is a high-level presentation document describing the BMAD experimentation on this project for a team audience. Keep it updated whenever:
- A new file is created in `docs/design/` (add a row to the component design table)
- A new file is created in `_bmad-output/` (add or update the relevant phase section)
- A new BMAD workflow is run (note it under the relevant phase with its output)
- A major design decision is confirmed (update the Key Observations section if noteworthy)

Keep the tone high-level and non-technical — it is for a team presentation, not for developers.

## Working Preferences

- **Component design workflow**: always explain the component first (scope, task grouping, task-by-task rationale and decisions), then ask one targeted question per task, then write the design document
- **Always use available skills**: invoke in priority the skill — never answer from general knowledge when a skill is available
- **Design document impact scan**: whenever a document in `docs/design/` is written or a confirmed decision changes a named concept (state name, method name, command name, config key, error code), immediately grep all existing design docs for the old/changed term. Report every hit, discuss the impact, and update affected docs before continuing. Do not wait for the user to point out stale references.
