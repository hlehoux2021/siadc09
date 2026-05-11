# Story 8-3: Wizard Integration & Testing

## Status: Ready for Dev

## Story

As a plugin maintainer,
I want the wizard to be robust and testable,
So that users can recover from errors and re-configure easily.

## Acceptance Criteria

1. **Given** wizard in any step, **When** user clicks "Relancer l'assistant", **Then** wizard saves `sia_wizard_step=0` before `daemon_stop()` to prevent race condition — current JS implementation calls `siaDC09_setWizardStep(0)` then `jeedom.eqLogic.save()`, which is correct; no changes needed here.

2. **And** daemon stops, wizard restarts from Step 1.

3. **And** existing config is preserved — fields pre-populate from last `jeedom.eqLogic.save()`.

4. **And** wizard validates config at each step before advancing (Step 1 validation already in `siaDC09_validateStep1()`).

5. **And** error messages are in French (already satisfied; messages use `{{...}}` i18n markers).

6. **And** `#bt_step3Next` advances to step 4 correctly (`siaDC09_setWizardStep(4)` not 3) — **BUG: current code sets step 3 (line 529)**.

7. **And** all Level 1 tests pass: `test_connection_test.py` (12 tests), `test_csr_presets_json.py` (14 tests), 8-2 guards in `test_php_eqlogic_stub.py` (3 tests) — **all 29 currently passing**.

8. **And** PHP syntax check passes for all modified files.

---

## Tasks

### Task 1 — Fix `#bt_step3Next` wizard step bug (JS)

**File:** `desktop/js/siaDC09.js:529`

The `#bt_step3Next` click handler calls `siaDC09_setWizardStep(3)` before advancing to step 4. This means after the zone mapping save, the wizard reloads step 3 instead of step 4.

**Fix:** Change `siaDC09_setWizardStep(3)` → `siaDC09_setWizardStep(4)` at line 529.

Current code (line 527–542):
```js
$('#bt_step3Next').on('click', function() {
  if ($(this).attr('disabled')) return
  siaDC09_setWizardStep(3)     // ← BUG: should be 4
  var eqLogic = $('.eqLogic').getValues('.eqLogicAttr')[0]
  eqLogic = saveEqLogic(eqLogic)
  jeedom.eqLogic.save({
    ...
    success: function() {
      siaDC09_showStep(4)      // ← shows step 4 HTML but saved step=3
    }
  })
})
```

**After fix:** `siaDC09_setWizardStep(4)` so the hidden input matches `siaDC09_showStep(4)`.

---

### Task 2 — Verify all 8-2 open findings are resolved

Review each finding from the 8-2 story dev notes and confirm status:

| # | Finding | Status |
|---|---------|--------|
| 1 | CRC format mismatch — `SIAMessageBuilder(crc_format="SIA")` hardcoded | **RESOLVED** — `siadc09d.py` reads `crc_format` from preset/config, no hardcoding |
| 2 | `csr_ip: "TBD"` passes `not config.get("csr_ip")` guard | **RESOLVED** — line 155: `if not host or host == "TBD" or not port or not account_number:` |
| 3 | Double `siaDC09_loadZoneData` call on step 3 page load | **RESOLVED** — `printEqLogic` (lines 22–37) only calls `siaDC09_showStep(step)`; no extra explicit call |
| 4 | `ajax::success()` without `return;` in guard branches | **RESOLVED** — verified `return;` present in all error branches of `testConnection`, `getZones`, `getCameraCommands` in `siaDC09.ajax.php` |
| 5 | `#bt_step3Next` sets wizard step to 3 instead of 4 | **OPEN** — fixed by Task 1 above |
| 6 | `int(config.get("csr_port", 0))` raises ValueError on non-numeric string | **RESOLVED** — line 145–148 wrapped in `try/except (ValueError, TypeError)` |
| 7 | No test coverage for story 8-2 new code | **RESOLVED** — all 3 test files present and passing (29 tests) |
| 8 | `cmd::byGenericType()` null → TypeError | **RESOLVED** — `?? []` guard confirmed in `siaDC09.ajax.php` |
| 9 | File List incomplete (siadc09d.py and csr_presets.json missing from 8-2) | **RESOLVED** — files exist in working tree (`resources/siadc09d/siadc09d.py`, `resources/siadc09d/csr_presets.json`) |

Only finding #5 requires a code change in this story.

---

### Task 3 — Run full test suite and PHP syntax checks

After Task 1, run:

```bash
python3 -m pytest tests/level1/ -v
```

Expected: all tests pass (29 from 8-2 files + existing).

```bash
find core/ desktop/ -name "*.php" | xargs -n1 php -l
```

Expected: no syntax errors.

---

### Task 4 — Update sprint status

Update `_bmad-output/implementation-artifacts/sprint-status.yaml`:
- Change `8-3-wizard-integration-testing: ready-for-dev` → `in-progress` when starting
- After implementation complete: → `review`

---

## Dev Notes

### Architecture Constraints

- **Two-mode wizard**: `sia_wizard_step < 4` → wizard UI; `sia_wizard_step == 4` → config summary. Do NOT call `printEqLogic` or `siaDC09_showStep` directly — they read the hidden `sia_wizard_step` input via `siaDC09_currentStep()`.
- **`saveEqLogic` is called by Jeedom framework** during `jeedom.eqLogic.save()`, not manually. The `#bt_step3Next` handler calls it explicitly via `eqLogic = saveEqLogic(eqLogic)` before passing to save — this is intentional to serialize the zone table.
- **Race condition on restart**: `siaDC09_setWizardStep(0)` → `jeedom.eqLogic.save()` → only THEN call any daemon stop. Current `#bt_restartWizard` handler (lines 380–419) already follows this pattern: sets step first, saves, success callback shows wizard. No daemon stop is called directly from JS — Jeedom watchdog handles restart after save sets step=0.

### Wizard Step Contract (canonical)

```
0 = not started (restart target)
1 = preset selection done / or in-progress step 1
2 = connection test done / or in-progress step 2  
3 = zone mapping done / or in-progress step 3
4 = config mode (wizard complete)
```

When `bt_step3Next` fires:
1. `siaDC09_setWizardStep(4)` — sets hidden input
2. `saveEqLogic(eqLogic)` — serializes zone table into `sia_zone_mappings`
3. `jeedom.eqLogic.save()` — persists all, including step=4
4. `success`: `siaDC09_showStep(4)` — shows step 4 HTML (notify command picker)

### Configuration Key Reference

| Key | Type | Set at |
|-----|------|--------|
| `sia_wizard_step` | int string | Every step advance |
| `csr_provider` | string | Step 1 card click |
| `csr_ip` | string | Step 1 form |
| `csr_port` | string | Step 1 form |
| `transport` | string | Step 1 form (preset or manual) |
| `crc_format` | string | Loaded from preset at test time (not stored in eqLogic config) |
| `encryption_enabled` | "0"/"1" | Step 1 checkbox |
| `encryption_key` | string | Step 1 form |
| `account_number` | string | Step 1 form |
| `sia_zone_mappings` | JSON string | Step 3 save |
| `sia_notify_cmd_id` | int string | Step 4 modal |
| `sia_notify_cmd_human` | string | Step 4 modal (display only) |

### Test Files Created in Story 8-2

These files are already present in the working tree (untracked in git status):

- `tests/level1/test_connection_test.py` — 12 tests for `_send_raw_once` and `run_connection_test`
- `tests/level1/test_csr_presets_json.py` — 14 tests for preset JSON structure
- `tests/level1/test_php_eqlogic_stub.py` — includes 3 tests for AJAX guards 2/3/6

All 29 tests pass as of story start (verified: `python3 -m pytest tests/level1/test_connection_test.py tests/level1/test_csr_presets_json.py` → 26 passed; guard tests → 3 passed).

### Notes on Restart Wizard Implementation

`#bt_restartWizard` (lines 380–419) does NOT call `jeedom.plugin.deamon_stop()` from JS. Instead:
- Sets `sia_wizard_step=0` and saves
- `success` callback hides config summary, shows wizard, calls `siaDC09_showStep(1)`
- Jeedom watchdog sees `sia_wizard_step=0` on next poll and auto-stops daemon if needed

This means the AC "daemon stops" is handled by Jeedom's built-in auto-stop on wizard restart — no explicit daemon stop in JS, which is the correct race-condition-safe pattern per `wizard-design.md`.

### File List

| File | Action | Reason |
|------|--------|--------|
| `desktop/js/siaDC09.js` | UPDATE | Fix `siaDC09_setWizardStep(4)` at line 529 |
| `tests/level1/test_connection_test.py` | VERIFY PASS | 12 tests already written |
| `tests/level1/test_csr_presets_json.py` | VERIFY PASS | 14 tests already written |
| `tests/level1/test_php_eqlogic_stub.py` | VERIFY PASS | 3 guard tests already written |

### Out of Scope for This Story

- Adding Level 2 or Level 3 wizard integration tests (requires Jeedom instance or real CSR)
- End-to-end test "complete wizard → daemon starts → supervision healthy" — this is Level 3 (requires live Jeedom + CSR simulator), deferred per project testing strategy
- Fixing any config wizard HTML/PHP — `desktop/php/siaDC09.php` is not changed

---

## Story Definition of Done

- [ ] `#bt_step3Next` calls `siaDC09_setWizardStep(4)` (not 3)
- [ ] All 29 Level 1 tests pass: `python3 -m pytest tests/level1/`
- [ ] PHP syntax check clean: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`
- [ ] Sprint status updated to `done` when complete
