---
ticket: "6"
status: "done"
type: 'feature'
v6_key: "1-6-sia-dcs-data-block-annex-b-dc03-area"
---

# Plan: SIA-DCS Data Block per DC-09 Annex B — `N` Prefix and DC-03 Area

The v6 build record is missing; sprint-status.yaml recorded this story as `done`. This plan only carries the status.

## Acceptance criteria (epics.md)

**Given** a 2-letter SIA event code and an optional address
**When** the daemon builds the event frame
**Then** the data block is `[#acct|Nri1/<code><addr>]` — `N` new-event prefix, DC-03 area `ri<n>/` taken from the daemon constant `SIA_AREA_NUMBER` (= 1), no separator between code and address, address zero-padded to 3 digits — e.g. `[#001234|Nri1/BA001]`, `[#001234|Nri1/CL501]`

**And** an unmapped zone gives `[#acct|Nri1/BA]` (no address), unchanged from the existing rule

**And** the same block is used in clear and encrypted mode; supervision (`NULL`, `*NULL`) carries no data block and no area

**And** the area is a daemon constant, not a plugin setting (a single siaDC09 equipment = one area)

**And** it is validated live at Scutum (2026-10-17): CL, BA, BC and OP all recognised (`internal-docs/ajax.md`)

Status: done — no story file; evidence is the commits above, the level1/level2 tests, and `internal-docs/ajax.md`.
