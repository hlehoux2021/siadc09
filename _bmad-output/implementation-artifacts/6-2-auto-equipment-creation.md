# Story 6.2: Auto-Equipment Creation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a Jeedom user,
I want the plugin to automatically create its equipment on first access,
So that I don't need to manually add it and the daemon can always report state.

## Acceptance Criteria

1. **Auto-create on first access** — `_getAutoEquipment()` (new method) auto-creates the single plugin equipment if none exists:
   - Name: `'Télésurveillance'`
   - `isEnable`: 1, `isVisible`: 1
   - `object_id`: null (user places it manually)
   - Triggers `postSave()` which creates the 7 commands (from Story 6.1)
   - Returns the existing equipment if one already exists

2. **Auto-recreate if deleted** — If user deletes the equipment, next `_getAutoEquipment()` call recreates it + logs a warning. Plugin-centric design requires equipment to always exist.

3. **Multiple equipment guard** — If multiple equipment exist (should never happen), `_getAutoEquipment()` logs error and returns the first one (same behavior as `_getAutoEquipmentSafe()`).

4. **`_getAutoEquipmentSafe()` unchanged** — The safe variant (from Story 6.1) stays as-is: returns null if no equipment, never auto-creates. Used by `message()` callback (Story 6.3) to avoid DB writes inside framework callbacks.

5. **`deamon_start()` uses `_getAutoEquipment()`** — The daemon start flow now uses the auto-creating variant so equipment always exists when the daemon launches. If equipment didn't exist, it's created on the fly.

6. **`deamon_info()` uses `_getAutoEquipmentSafe()`** — The launchable check must NOT auto-create (it's called by Jeedom's health check loop and must be side-effect-free).

7. **Idempotent** — Calling `_getAutoEquipment()` 10 times produces exactly 1 equipment (not 10). The `byType(__CLASS__)` check prevents duplicate creation.

8. **Python contract tests** — Update `tests/level1/test_php_eqlogic_stub.py` with a test documenting the two-method contract: `_getAutoEquipment()` (auto-creates) vs `_getAutoEquipmentSafe()` (returns null).

---

## Tasks / Subtasks

### Task 1: Add `_getAutoEquipment()` method to `siaDC09.class.php` (AC1, AC2, AC3)

- [x] **1.1** Add `private static function _getAutoEquipment(): self` method:
  ```php
  private static function _getAutoEquipment(): self {
      $eqLogics = eqLogic::byType(__CLASS__);
      if (is_array($eqLogics) && count($eqLogics) > 0) {
          if (count($eqLogics) > 1) {
              log::add(__CLASS__, 'error', __('Plusieurs équipements détectés — un seul attendu', __FILE__));
          }
          return $eqLogics[0];
      }
      // Auto-create on first access
      log::add(__CLASS__, 'warning', __('Équipement absent — création automatique', __FILE__));
      $eq = new self();
      $eq->setName('Télésurveillance');
      $eq->setEqType_name(__CLASS__);
      $eq->setIsEnable(1);
      $eq->setIsVisible(1);
      $eq->setObject_id(null);
      $eq->save(); // triggers postSave() → creates 7 commands
      return $eq;
  }
  ```
- [x] **1.2** Return type is `self` (never null) — callers don't need null checks
- [x] **1.3** Log at WARNING level on auto-creation (not ERROR — auto-create is by design)
- [x] **1.4** Log at ERROR level if multiple equipment found (same as `_getAutoEquipmentSafe()`)
- [x] **1.5** `setEqType_name(__CLASS__)` is required for Jeedom to associate the equipment with the plugin

---

### Task 2: Update `deamon_start()` to use `_getAutoEquipment()` (AC5)

- [x] **2.1** Replace `$eqLogic = self::_getAutoEquipmentSafe()` with `$eqLogic = self::_getAutoEquipment()`
- [x] **2.2** Remove the comment `// launchable=='ok' guarantees equipment exists with valid config` — `_getAutoEquipment()` creates if missing, so launchable=='ok' is no longer the guarantee
- [x] **2.3** Note: `deamon_info()` still uses `_getAutoEquipmentSafe()` — this is intentional (AC6). The launchable check must be side-effect-free because Jeedom calls it in a polling loop.

---

### Task 3: Verify `deamon_info()` still uses `_getAutoEquipmentSafe()` (AC6)

- [x] **3.1** Confirm `deamon_info()` calls `self::_getAutoEquipmentSafe()` (not the auto-creating version)
- [x] **3.2** Confirm `deamon_info()` returns `launchable='nok'` with message when no equipment exists — this is the correct behavior for the health check (user sees "Aucun équipement configuré" in plugin manager)

---

### Task 4: Add `en_US.json` translations for new strings (AC1)

- [x] **4.1** Add `"Équipement absent — création automatique": "Equipment missing — auto-creating"` to the siaDC09 section

---

### Task 5: Update Python contract tests (AC8)

- [x] **5.1** Add `test_two_equipment_method_contract()` to `tests/level1/test_php_eqlogic_stub.py`:
  - Documents the two-method pattern: `_getAutoEquipment()` never returns null (auto-creates), `_getAutoEquipmentSafe()` may return null (no side effects)
  - Pure Python — asserts on documented method signatures, not runtime PHP behavior

---

### Task 6: Run tests (AC8)

- [x] **6.1** Run `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short` — all pass
- [x] **6.2** Run `python3 -m pytest tests/level1/ tests/level2/ -q --tb=short` — no new regressions (pre-existing: 8 failures unchanged)

---

## Dev Notes

### Modified Files

```
Modified files (Story 6.2):
  core/class/siaDC09.class.php        ← Add _getAutoEquipment(), update deamon_start()
  core/i18n/en_US.json                ← Add new translation string
  tests/level1/test_php_eqlogic_stub.py ← Add contract tests

Reference files (DO NOT MODIFY):
  core/class/aiodemo.class.php        ← handleFeedback() pattern for auto-create reference
```


### Two Equipment Lookup Methods — Design Contract

| Method | Returns | Auto-creates? | Use in |
|--------|---------|---------------|--------|
| `_getAutoEquipment()` | `self` (never null) | Yes + log warning | `deamon_start()` |
| `_getAutoEquipmentSafe()` | `?self` (may be null) | No | `deamon_info()`, `message()` (Story 6.3) |

**Why two methods?** `message()` is a Jeedom framework callback invoked frequently. Auto-creating equipment (DB write + `postSave()` + command creation) inside a callback causes re-entrancy issues and unexpected side effects. `_getAutoEquipmentSafe()` is the safe variant for read-only contexts.

`deamon_start()` is the right place for auto-creation: it runs once, user-initiated, and the equipment must exist before the daemon launches. If the user deleted the equipment, `deamon_start()` recreates it transparently.

### Reference Pattern from aiodemo

`aiodemo.class.php::handleFeedback()` (lines 97-105) shows the Jeedom auto-create pattern:
```php
$eqLogic = eqLogic::byLogicalId('aiodemo', __CLASS__);
if (!is_object($eqLogic)) {
    $eqLogic = new self();
    $eqLogic->setLogicalId('aiodemo');
    $eqLogic->setEqType_name(__CLASS__);
    $eqLogic->setIsEnable(1);
    $eqLogic->setIsVisible(1);
    $eqLogic->setName('aiodemo');
    $eqLogic->save();
}
```

**Key difference:** aiodemo uses `byLogicalId()` (by logical name), we use `byType(__CLASS__)` (by plugin class). The aiodemo approach sets `logicalId` on the equipment; our approach identifies by `eqType` which is the standard Jeedom pattern for single-equipment plugins.

### `setEqType_name(__CLASS__)` Is Required

The aiodemo reference calls `setEqType_name(__CLASS__)` during auto-creation. This sets the equipment's plugin type and is required for `byType()` to find it. Without this, `byType('siaDC09')` returns empty and the equipment becomes orphaned.

### `postSave()` Handles Command Creation

Story 6.1's `postSave()` already creates all 7 commands idempotently. When `_getAutoEquipment()` calls `$eq->save()`, it triggers `postSave()` automatically. No additional command creation logic is needed in Story 6.2.

### Pre-existing Test Failures (Not Regressions)

- **Level 2:** `test_tc13_strike_timing_precision` — pre-existing StopIteration from time.monotonic mock
- **Level 1:** 7 tests in `test_error_handler.py` — `_dispatch_notify` NotImplementedError (deferred to Epic 6.3+)

### Cross-Story Dependencies

- **Story 6.1** (prerequisite): provides `siaDC09.class.php` with `_getAutoEquipmentSafe()`, `postSave()`, and all method skeletons
- **Story 6.3** (downstream): `message()` callback will use `_getAutoEquipmentSafe()` (not `_getAutoEquipment()`) per design doc
- **Story 6.5** (downstream): dependency install creates `.install_ok` sentinel used by `dependancy_info()`

### References

- [Source: docs/design/php-core-design.md § Task 2.9 — _getAutoEquipment() spec with auto-create logic]
- [Source: docs/design/php-core-design.md § Confirmed Design Decisions — "Auto-recreate if deleted: Yes + log warning"]
- [Source: docs/design/php-core-design.md § message() — uses _getAutoEquipmentSafe(), NOT _getAutoEquipment()]
- [Source: core/class/aiodemo.class.php lines 97-105 — handleFeedback() auto-create pattern]
- [Source: _bmad-output/implementation-artifacts/6-1-php-eqlogic-cmd-classes.md — Story 6.1 completion notes]
- [Source: _bmad-output/planning-artifacts/epics.md § Story 6.2 Acceptance Criteria]

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (1M context)

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Added `_getAutoEquipment(): self` alongside existing `_getAutoEquipmentSafe(): ?self` in `siaDC09.class.php`. The two-method contract is now fully implemented: auto-creating variant for `deamon_start()`, side-effect-free variant for `deamon_info()` and future `message()`.
- `deamon_start()` updated to use `_getAutoEquipment()` — stale comment removed.
- `deamon_info()` verified unchanged: still uses `_getAutoEquipmentSafe()` (side-effect-free per AC6).
- Translation string `"Équipement absent — création automatique"` added to `core/i18n/en_US.json`.
- 8 new contract tests added to `test_php_eqlogic_stub.py`: `test_get_auto_equipment_return_type_is_non_nullable`, `test_get_auto_equipment_safe_return_type_is_nullable`, `test_deamon_start_uses_auto_creating_method`, `test_deamon_info_uses_safe_method`, `test_auto_create_logs_at_warning_level`, `test_auto_create_sets_canonical_equipment_name`, `test_auto_equipment_idempotent_guard` (AC7), `test_auto_recreate_after_delete_path_exists` (AC2). All 20 tests pass.
- Regression check: 738 passed, 8 pre-existing failures unchanged (7 `_dispatch_notify` NotImplementedError + 1 StopIteration in `test_tc13`).

### File List

- `core/class/siaDC09.class.php` — Added `_getAutoEquipment()` method; updated `deamon_start()` to use it
- `core/i18n/en_US.json` — Added translation for `"Équipement absent — création automatique"`
- `tests/level1/test_php_eqlogic_stub.py` — Added 3 Story 6.2 contract tests; updated module docstring

### Change Log

- 2026-04-24: Story 6.2 implemented — Added `_getAutoEquipment()` auto-creating method, updated `deamon_start()`, added en_US translation, added 3 Python contract tests (Story 6.2)
- 2026-04-27: Code review — Added 2 missing tests (AC7 idempotency guard, AC2 delete-recreate path), removed unused $result variable in deamon_start(), corrected Dev Notes prose and Completion Notes test names; status → done
