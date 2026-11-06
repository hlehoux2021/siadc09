---
title: '17.12 — Wizard Step 2 Without Dead End'
type: 'feature'
ticket: 12
created: '2026-11-06'
status: 'draft'
baseline_revision: '2a03d057b24d505c892f12741e37ef6354282d78'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/EXPERIENCE.md'
  - '{project-root}/internal-docs/design/wizard-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A refused or failed connection test leaves the user stuck on step 2: the DUH text advises switching to the NULL format (which a locked profile forbids and EXPERIENCE bans), the message that was sent is only in the log, and no button returns to step 1.

**Approach:** `--test-only` adds a plaintext `sent` summary (type, account, transport) and an `outcome` marker to its JSON; PHP relays both and logs an expected DUH at WARNING; step 2 gains « ← Modifier la centrale » (available during a running test, late answer discarded) and renders the DUH/failure view per EXPERIENCE.

## Boundaries & Constraints

**Always:** EXPERIENCE.md wins over wizard-design.md on step 2 (its "Spec corrections" list the stepper/no-way-back point); `sent` never carries an encrypted frame nor the key (type/account/transport only); the UI statuses stay ok/nak/fail/error; the daemon's SM1_DUH level stays error (`daemon.py` untouched); Modifier la centrale saves nothing and keeps every field value; step 2 edits stay in step-2 regions of `siaDC09.js`, `siaDC09.php`, `wizard-design.md` (17.10 edits the same files in parallel).

**Never:** profile name in the refusal text; advice to change the supervision format or choose « Personnalisé »; step 1 media card, Frigate rule, null-warning removal (17.10/17.11); permanent TCP; changing the NAK/no-answer texts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| DUH | CSR answers DUH | JSON `fail`, `outcome: duh`, `sent`; red view: refusal sentence, sent message, two checks (profile matches the center; account N is the registered one), « Puis relancez le test. »; Modifier/Relancer/Ignorer live, Suivant disabled | PHP logs at WARNING, not ERROR |
| Other failure | timeout, refused, DNS... | `fail`/`error` with `sent` when a frame was built; Modifier la centrale available | PHP keeps ERROR for stderr |
| Encrypted test | encryption on | `sent` has type/account/transport only, no frame | — |
| Modifier during test | click while spinner | step 1 shown, all step 1 values kept, `bt_step1Next` live; the pending answer is ignored | no save, no alert |
| Late answer | answer arrives after leaving | no DOM change, no button state change | — |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/siadc09d.py` -- `run_connection_test` (l.310-412) builds the frame; `_TEST_VERDICTS[_STATUS_DUH]` (l.112) carries the NULL advice to replace; stderr frame print (l.387) stays (plaintext, non-encrypted only). Add `sent` + `outcome` to the printed JSON; `parse_frame_header` (sia_protocol) gives the type token.
- `core/ajax/siaDC09.ajax.php` -- `testConnection` (l.54-119): stderr is logged at error (l.104); log at warning when `$result['outcome'] === 'duh'`; result already forwarded whole by `ajax::success($result)`.
- `desktop/js/siaDC09.js` -- `siaDC09_runConnectionTest` (l.446), `siaDC09_populateStep2Summary`, `#bt_step2*` handlers, `siaDC09_showStep` (l.102). Reuse `siaDC09_setButtonEnabled`. Add a test-run token (`_siaDC09_testRun`) so a late answer is dropped; `#bt_step2Back` handler: bump token, hide spinner, `siaDC09_showStep(1)`, no save.
- `desktop/php/siaDC09.php` l.291-314 -- add `#bt_step2Back` button (step 2 block only).
- `internal-docs/design/wizard-design.md` -- "Step 2" section (l.150-230): result table, buttons, exit contract note (stderr relayed), `testConnection` response shape (~l.536).
- `tests/fixtures/js_wizard_flow_harness.js` -- add `#bt_step2Back` to markup/BUTTONS, scenario `test` payload extension (`sent`, `outcome`, `delay` for late answer).
- `tests/level1/test_connection_test.py` (l.642 DUH test must change), `tests/level1/test_wizard_ajax_contracts.py`, `tests/level1/test_wizard_step1_flow_js_dom.py` -- extend. Do not touch `daemon.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/siadc09d.py` -- DUH template: « {endpoint} a reçu le message de test mais l'a refusé (DUH). » (no NULL advice); emit `sent` (type from header, account, transport; no frame content) and `outcome` -- diagnosis data without an encrypted frame
- [ ] `core/ajax/siaDC09.ajax.php` -- warning level for DUH stderr, error otherwise -- expected DUH is not an error
- [ ] `desktop/php/siaDC09.php` -- `#bt_step2Back` « ← Modifier la centrale » button, step 2 block
- [ ] `desktop/js/siaDC09.js` -- DUH/failure view (sentence, sent message, two checks, « Puis relancez le test. »), back button, run token, buttons per EXPERIENCE "Step 2 states" (back live while testing) -- no dead end
- [ ] `tests/...` -- Python: `sent` summary present, no encrypted frame, DUH message without NULL; PHP structure/contract: warning branch; jsdom: Modifier la centrale incl. late answer ignored, step 1 buttons live, values kept, back live during test
- [ ] `internal-docs/design/wizard-design.md` -- update Step 2 sections (step-2 regions only)

**Acceptance Criteria:**
- Given a pending test, when Modifier la centrale is clicked then a test answer arrives, then step 1 stays shown, Suivant is live, values kept, nothing rendered from the late answer.
- Given encryption on, when the test runs, then JSON `sent` has type/account/transport and no frame.
- Given a DUH on the wizard path, then PHP logs it at WARNING and `daemon.py` SM1_DUH is unchanged.
- Given a DUH, then the view shows exactly the two suggestions and no profile name.

## Design Notes

`outcome` is a new key beside `status` because the UI status set (ok/nak/fail/error) must not grow (comment l.70 of siadc09d.py). The JS composes the user-facing DUH text from `outcome`, `sent` and the account, so the profile never appears.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: pass except the known baseline failure `test_php_periodic_frame_guard.py::test_get_csr_profiles_reads_real_file`
- `php -l core/ajax/siaDC09.ajax.php` -- expected: no syntax errors

**Manual checks (if no CLI):**
- On test-jeedom (after push): force a DUH, check the red view, click Modifier la centrale, confirm Suivant works; check the WARNING line in the siaDC09 log (not yet done: hitl).
