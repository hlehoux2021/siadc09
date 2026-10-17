# Sprint Change Proposal — 2026-10-17

**Author:** Herve (via Correct Course workflow)
**Trigger:** Retroactive tracing of the `fix/sia-dcs-n-prefix` work (merged to master as 273bf75), which landed outside the backlog
**Mode:** Incremental — all 6 edit proposals approved individually

## 1. Issue Summary

Story 1.1 (done) built the SIA-DCS event data block as `[#acct|BA 001]`. It followed the Annex B examples in the Markdown copy of the spec (`internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`), which had been altered: the original PDF shows `[#12345A|NFA129]` and `[#12345A|Nid3OG2]`. The lenient receiver used for field validation (`192.168.100.15:10002`) accepted the old form. Scutum, a strict receiver, displayed CL/OP as "CODE INCONNU".

How it was discovered (2026-10-16/17):
- Ajax↔Scutum network captures were analysed (`internal-docs/ajax.md`, 4 pcapng files) and frames were probed with `scripts/sia_csr_probe.py`.
- Two commits fixed the block on branch `fix/sia-dcs-n-prefix`:
  - ee74db6 adds the `N` prefix and removes the space;
  - d35ec5a adds the DC-03 area `ri1/` from the daemon constant `SIA_AREA_NUMBER = 1`.

Evidence: a field validation from Jeedom at Scutum on 2026-10-17. CL0001 "Mise En Service par U0501", BA0002 "INTRUSION Zone 0002", BC0501 "ACQUITTEMENT ALARME" and OP0001 "Mise Hors Service par U0501" were all recognised. The same analysis showed that cancelled Story 15-1's "IP" `#KEY=VALUE` example is a receiver's display of this same block, with `ZONE=0008` = `ri8`. That reading is inferred, not confirmed at Aremis.

Issue type: misunderstanding of the original requirement, caused by a corrupted reference document.

## 2. Impact Analysis

- **Epic impact:**
  - Epic 1 (Protocol Engine): Story 1.1's data block was non-conforming, and no story records the correction. Epic 1 stays `in-progress` because 1-5 is in review.
  - Epic 11: Story 11.1 (Ajax frame comparison) is partly done in substance, but against the real CSR, not the simulator its ACs describe.
  - Epic 15: already cancelled.
  - Epic 16: unaffected.
- **Story impact:**
  - Story 1.6 is added retroactively as `done`.
  - Story 11.1 gets a note; its ACs and status are unchanged.
  - AC examples in done stories (8.2, 12.5, 13.1, 13.4) keep the old notation as history; ADR-21 takes precedence.
- **Artifact conflicts:**
  - architecture.md has no ADR on the data-block format, and one stale example.
  - Design docs (wizard, php-core, daemon) have stale examples.
  - The PRD compliance line doesn't mention the data block.
  - The FR changelog has no entry for the fix.
- **Technical impact:** none remaining. The code and tests (level1 + level2) are already on master and the baseline is unchanged. No PHP/JS code parses the data block.

## 3. Recommended Approach

**Option 1 — Direct Adjustment (selected).** Documentation and tracking only.
- Effort: Low. Risk: Low. No timeline impact.

Options considered and not chosen:
- Rollback (Option 2) is not viable: it would bring back "CODE INCONNU" at Scutum.
- MVP review (Option 3) is N/A: the MVP is unaffected.
- Absorbing the work into Story 11.1 was rejected. 11.1 stays open for the Ajax-supervision alignment discussion (NULL/RP/TCP), which is deliberately suspended.

## 4. Detailed Change Proposals

### Stories (`epics.md`)

**4.1 — New Story 1.6**, inserted after Story 1.5:

> ### Story 1.6: SIA-DCS Data Block per DC-09 Annex B — `N` Prefix and DC-03 Area
> *Added retroactively 2026-10-17 via correct-course …*
>
> ACs:
> - `[#acct|Nri1/<code><addr>]`, no separator, address padded to 3 digits;
> - unmapped zone gives `[#acct|Nri1/BA]`;
> - same block in clear and encrypted mode, and supervision carries no area;
> - the area is a daemon constant;
> - validated live at Scutum on 2026-10-17.
>
> Status: done — no story file.

Rationale: traces work already on master.

**4.2 — Note on Story 11.1**, under its heading. It records that the Ajax capture and comparison was done against real Scutum on 2026-10-16/17, and that it drove Story 1.6 / ADR-21. The supervision differences it found are still under discussion, and the ACs are unchanged and open.

### Architecture (`architecture.md`)

**4.3 — New ADR-21 "SIA-DCS data block per DC-09 Annex B and DC-03"**, inserted after ADR-20.
- Decision:
  - `[#acct|Nri<area>/<code><addr>]`, built only in `_format_data_field()`;
  - `SIA_AREA_NUMBER = 1` is a constant, not a setting;
  - non-2-letter codes (clear supervision `[#acct|0000]`) get no `N` and no area, and `*NULL` has no block;
  - encryption wraps the same block;
  - the PDF's Annex B wins over the Markdown copy.
- Rejected: the area as a setting (YAGNI); a per-CSR content format (ADR-19, withdrawn).
- Consequences: the examples in done stories are history; validated at Scutum, not yet at Aremis.

**4.4 — Stale examples**, find-and-replace (spec quotes untouched):

| File | OLD | NEW |
|---|---|---|
| `internal-docs/design/wizard-design.md:330` | `[#001234\|NBA001]` | `[#001234\|Nri1/BA001]` |
| `internal-docs/design/wizard-design.md:331` | `[#001234\|BA]` | `[#001234\|Nri1/BA]` |
| `internal-docs/design/php-core-design.md:465` | `[#001234\|BA]` | `[#001234\|Nri1/BA]` |
| `internal-docs/design/daemon-design.md:186` | `[#ABC123\|BA][V…]` | `[#ABC123\|Nri1/BA][V…]` |
| `_bmad-output/planning-artifacts/architecture.md:1351` | `[#001234\|BA]` | `[#001234\|Nri1/BA]` |

### PRD (`prd.md`)

**4.5 — Line 77**, compliance bullet: append "SIA-DCS data block per Annex B with DC-03 area (`Nri1/…`, ADR-21 — corrected 2026-10-17)". The MVP is unchanged.

### Documentation

**4.6 — `docs/fr_FR/changelog.md`**: new bullet in "Version de test":

> Trames d'alarme conformes à l'annexe B de DC-09 et à DC-03 (préfixe `N`, partition `ri1`) : reconnues par un centre de télésurveillance exigeant, qui affichait auparavant « CODE INCONNU » pour l'armement et le désarmement.

No CSR is named, per the public-docs editorial rules.

### Tracking (`sprint-status.yaml`)

**4.7**
- Add `1-6-sia-dcs-data-block-annex-b-dc03-area: done`, with a comment pointing to this proposal.
- Add a comment on `11-1`; its status stays `ready-for-dev`.
- Summary recounted from the status lines: total_stories 62→63, stories_done 53→54.
- Update `last_updated`.

## 5. Implementation Handoff

- **Scope: Minor.** Direct implementation by the Developer agent, documentation and tracking only, with no code change.
- **Success criteria:**
  - every edit in §4 is applied;
  - the sprint-status summary matches a recount of its status lines;
  - no example in an active design doc or in architecture.md still shows a data block without `Nri1/` (spec quotes excepted);
  - one commit on master.
- **Follow-ups (out of this proposal):**
  - The Ajax-supervision alignment discussion (real NULL, periodic RP, TCP handling), whose home is Story 11.1.
  - An optional Aremis probe (`--event Nri1/BA001`), run by Herve, to confirm the `ZONE` = `ri` reading.
