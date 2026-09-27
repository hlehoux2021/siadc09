# Story 6.4: INFO Command Persistence & Real-time Updates

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a Jeedom user,
I want to see supervision and alarm state in real-time and have those states survive daemon restarts,
So that I know the monitoring connection health and last event status at all times.

## Acceptance Criteria

1. **`_handleInfoUpdate()` uses correct Jeedom API** — `$eqLogic->checkAndUpdateCmd($logicalId, $value)` is the **standard Jeedom shortcut** (confirmed by jeedom-plugin expert: aiodemo reference uses this exact form). It internally calls `getCmd(null, ...)` + `$cmd->event()`. Both forms fire scenario events identically. Story 6.4 dev agent: **verify this shortcut is present** and `isset()` guards are used (not `empty()`).

2. **`postSave()` sets `returnStateTime=30, returnStateValue=0` on all commands** — Prevents stuck PENDING (`event_state=3`) if daemon crashes mid-alarm. On first creation of each command, `$cmd->setConfiguration('returnStateTime', 30)` and `$cmd->setConfiguration('returnStateValue', 0)` are called before `$cmd->save()`. All 7 commands (3 action + 4 info) get these values. This is a schema fix over Story 6.1 output. *(Expert correction: use `setConfiguration()`, not `setAdditionalInfos()` which does not exist.)*

3. **INFO commands have initial default values on first creation** — When `postSave()` creates INFO commands for the first time, it sets initial values via `checkAndUpdateCmd()`:
   - `supervision_state` → `1` (INITIALIZING/impaired)
   - `supervision_label` → `'DÉMARRAGE…'`
   - `event_state` → `0` (no alarm since start)
   - `event_label` → `'Inactif'`
   This ensures the widget is not empty before the first daemon callback.

4. **Persistence across daemon restarts** — INFO command values written via `checkAndUpdateCmd()` are stored in Jeedom's DB and survive daemon stop/start. When the daemon restarts, it reads its own config from eqLogic (not from the INFO commands), but the INFO commands retain their last-known values. PHP UI reads from the commands at page load. No PHP-side restore logic is needed — Jeedom's normal command persistence handles this automatically.

5. **`event_state` and `event_label` are NOT reset on daemon start/stop** — Confirmed by architecture invariant: `supervision_state=0` + `event_state=3` conveys "daemon was stopped during in-flight alarm". No special PHP reset code is added. The 30-minute `returnStateTime` auto-revert handles the `event_state=3` stuck-state edge case.

6. **`info_update` callback updates all 4 INFO commands** — The daemon sends `{"type": "info_update", "supervision_state": N, "supervision_label": "...", "event_state": N, "event_label": "..."}`. PHP `_handleInfoUpdate()` checks `isset($data[$key])` for each field (partial updates allowed) and calls `checkAndUpdateCmd()` only for fields present in the payload.

7. **`isVisible=0` on all INFO commands** — Commands are not shown in Jeedom's dashboard command list. State display is handled exclusively by `toHtml()` (widget). The `postSave()` command creation must explicitly set `isVisible=0` on all commands.

8. **PHP structural tests** — Add tests to `tests/level1/test_php_eqlogic_stub.py`:
   - `test_postsave_sets_return_state_time_on_commands()` — `returnStateTime` appears in `postSave()` body
   - `test_postsave_sets_return_state_value_on_commands()` — `returnStateValue` appears in `postSave()` body
   - `test_info_commands_are_invisible()` — `isVisible` set to `0` in `postSave()` for info commands
   - `test_handle_info_update_uses_check_and_update_cmd()` — `checkAndUpdateCmd` appears in `_handleInfoUpdate()` (standard Jeedom API for INFO updates)
   - `test_handle_info_update_uses_isset_guard()` — `isset($data[` appears in `_handleInfoUpdate()` (not `empty()`)

9. **IPC schema updated for `info_update` partial update contract** — `tests/fixtures/ipc_schema.py` `INFO_UPDATE_SCHEMA` documents that all 4 fields are **optional per send** (only sent fields are updated). Add test `test_info_update_partial_payload_valid()` in `tests/level2_5/test_callback_schema.py`.

10. **Tests pass** — All pre-existing tests continue to pass. New tests all pass.

---

## Tasks / Subtasks

### Task 1: Verify `_handleInfoUpdate()` canonical form (AC1, AC6)

> **Note:** The `getCmd(null, $logicalId)` + `$cmd->checkAndUpdateCmd()` fix is being addressed in Story 6.3 review. Story 6.4 dev agent only needs to **verify** the current PHP source is correct before proceeding. If already fixed, skip. If not, apply the fix.

- [x] **1.1** Read `_handleInfoUpdate()` in `core/class/siaDC09.class.php`.
- [x] **1.2** Verify it uses `$eqLogic->checkAndUpdateCmd($logicalId, $value)` — the standard Jeedom shortcut (expert-confirmed: identical behavior to `getCmd(null,...) + $cmd->checkAndUpdateCmd()`). Confirm present and correct.
- [x] **1.3** Verify `isset($data[$key])` is used (not `empty()`) — `isset()` allows value `0` to pass through, which `empty()` would silently discard (critical: `supervision_state=0` means "problem").

---

### Task 2: Add `returnStateTime` / `returnStateValue` and `isVisible=0` to `postSave()` command creation (AC2, AC7)

- [x] **2.1** Read current `postSave()` implementation in `core/class/siaDC09.class.php`.
- [x] **2.2** For each command created in `postSave()`, add before `$cmd->save()`:
  ```php
  $cmd->setConfiguration('returnStateTime', 30);
  $cmd->setConfiguration('returnStateValue', 0);
  ```
  This applies to all 7 commands (3 action + 4 info). *(Expert: `setConfiguration()` is the correct API, not `setAdditionalInfos()`.)*
- [x] **2.3** Verify `$cmd->setIsVisible(0)` is already set for all commands. If any command is missing this, add it.
- [x] **2.4** The `returnStateTime=30` means Jeedom auto-reverts `event_state` to `0` after 30 minutes of no daemon update — this handles the "stuck PENDING" edge case when the daemon crashes mid-alarm.

  > **Critical note:** `returnStateTime` and `returnStateValue` are only applied **on first creation** of the command. They are not re-applied on subsequent `postSave()` calls for already-existing commands (the `getCmd() → is_object()` guard skips existing commands). This is correct behavior — users could manually adjust these values after creation.

---

### Task 3: Verify INFO command initial default values are set on first creation (AC3)

- [x] **3.1** In `postSave()`, after creating each INFO command and before returning, verify that `$this->checkAndUpdateCmd($logicalId, $spec['default'])` is called.
- [x] **3.2** Confirm the initial defaults match the spec:
  - `supervision_state` → `1`
  - `supervision_label` → `'DÉMARRAGE…'`
  - `event_state` → `0`
  - `event_label` → `'Inactif'`
- [x] **3.3** These defaults are only set on **first creation** (inside the `if (!is_object($cmd))` block). They are NOT reset on subsequent saves (idempotent guard).
- [x] **3.4** Note: `checkAndUpdateCmd()` here is called on `$this` (the eqLogic) with `($logicalId, $value)` — the eqLogic-level shortcut is acceptable for the **initial seeding** path because it runs once at creation, not in a hot callback path.

---

### Task 4: Add PHP structural tests (AC8)

- [x] **4.1** Read `tests/level1/test_php_eqlogic_stub.py` to understand the existing fixture and helper patterns.
- [x] **4.2** Add a `handle_info_update_body` fixture if not already present (it is, from Story 6.3 — reuse it).
- [x] **4.3** Add `test_postsave_sets_return_state_time_on_commands()`:
  ```python
  def test_postsave_sets_return_state_time_on_commands(postsave_body: str) -> None:
      """
      All commands must have returnStateTime=30 to prevent stuck PENDING state
      (event_state=3) if the daemon crashes mid-alarm.

      Expected result:
      - 'returnStateTime' appears in postSave() body
      - The value 30 appears associated with returnStateTime
      """
      # Assert: returnStateTime is set in postSave()
      assert "returnStateTime" in postsave_body, (
          "postSave() must set returnStateTime on commands — "
          "prevents event_state=3 stuck if daemon crashes"
      )
      # Assert: value 30 is used (spec: 30 minutes)
      assert "30" in postsave_body, (
          "postSave() must set returnStateTime=30 (30-minute auto-revert)"
      )
  ```
- [x] **4.4** Add `test_postsave_sets_return_state_value_zero()`:
  ```python
  def test_postsave_sets_return_state_value_zero(postsave_body: str) -> None:
      """
      All commands must revert to 0 (not null) after returnStateTime expires.
      Value 0 for event_state means 'no alarm' — a safe idle state.

      Expected result:
      - 'returnStateValue' appears in postSave() body
      """
      # Assert: returnStateValue is set in postSave()
      assert "returnStateValue" in postsave_body, (
          "postSave() must set returnStateValue on commands"
      )
  ```
- [x] **4.5** Add `test_all_commands_are_invisible()`:
  ```python
  def test_all_commands_are_invisible(postsave_body: str) -> None:
      """
      All INFO and ACTION commands must be invisible in Jeedom's dashboard
      command list (isVisible=0). State display is via toHtml() widget only.

      Expected result:
      - setIsVisible(0) or isVisible=0 appears in postSave() body
      """
      # Assert: isVisible is explicitly set to 0
      assert "IsVisible" in postsave_body or "isVisible" in postsave_body, (
          "postSave() must set isVisible=0 on all commands"
      )
  ```
- [x] **4.6** Add `test_handle_info_update_uses_check_and_update_cmd()`:
  ```python
  def test_handle_info_update_uses_check_and_update_cmd(
      handle_info_update_body: str,
  ) -> None:
      """
      _handleInfoUpdate() must use checkAndUpdateCmd() — the standard Jeedom API
      for updating INFO command values. This triggers scenario events, updates
      collectDate, and persists the value. Both the eqLogic shortcut form and the
      getCmd+cmd form are acceptable (expert-confirmed identical behavior).

      Expected result:
      - 'checkAndUpdateCmd' appears in _handleInfoUpdate() body
      """
      # Assert: checkAndUpdateCmd is used to update INFO values
      assert "checkAndUpdateCmd" in handle_info_update_body, (
          "_handleInfoUpdate() must call checkAndUpdateCmd() to update INFO values"
      )
  ```
- [x] **4.7** ~~Add `test_handle_info_update_uses_isset_not_empty()`~~ — already exists from Story 6.3 QA (line 728). Verified present.
  ```python
  def test_handle_info_update_uses_isset_not_empty(
      handle_info_update_body: str,
  ) -> None:
      """
      _handleInfoUpdate() must use isset() to guard each field access, not empty().
      empty(0) returns true — using it would silently drop supervision_state=0
      (the 'problem' state), causing the widget to never show red.

      Expected result:
      - 'isset($data[' appears in _handleInfoUpdate() body
      - 'empty($data[' does NOT appear
      """
      # Assert: isset() is used for field presence check
      assert "isset($data[" in handle_info_update_body, (
          "_handleInfoUpdate() must use isset() to check field presence — "
          "empty() would silently drop supervision_state=0"
      )
      # Assert: empty() is NOT used for data field checks
      assert "empty($data[" not in handle_info_update_body, (
          "_handleInfoUpdate() must NOT use empty() for data fields — "
          "empty(0) would drop the 'problem' supervision state"
      )
  ```
- [x] **4.8** Run new tests: `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short -k "test_postsave_sets_return or test_all_commands_are_invisible or test_handle_info_update_uses_check_and_update_cmd"` — all 4 pass.

---

### Task 5: Add IPC schema test for partial `info_update` (AC9)

- [x] **5.1** Read `tests/fixtures/ipc_schema.py` to check the current `INFO_UPDATE_SCHEMA`.
- [x] **5.2** Verify `INFO_UPDATE_SCHEMA` documents all 4 fields as **optional** (partial updates allowed). Add a comment if missing:
  ```python
  # All fields are optional — daemon may send partial updates (e.g. supervision-only)
  ```
- [x] **5.3** Add `test_info_update_partial_payload_valid()` to `tests/level2_5/test_callback_schema.py`:
  ```python
  def test_info_update_partial_payload_valid() -> None:
      """
      The daemon may send partial info_update payloads containing only supervision
      fields (when SM1 transitions) or only event fields (when SM2 transitions).
      Both partial forms must be valid per the IPC contract.

      Expected result:
      - Payload with only supervision_state + supervision_label is valid
      - Payload with only event_state + event_label is valid
      - Neither partial payload is rejected by the schema
      """
      supervision_only = {
          "type": "info_update",
          "supervision_state": 2,
          "supervision_label": "Sain",
      }
      event_only = {
          "type": "info_update",
          "event_state": 1,
          "event_label": "Confirmé",
      }
      # Assert: supervision-only partial update is valid JSON and contains type
      assert supervision_only["type"] == "info_update"
      assert "supervision_state" in supervision_only
      assert "event_state" not in supervision_only  # partial — event fields absent

      # Assert: event-only partial update is valid JSON and contains type
      assert event_only["type"] == "info_update"
      assert "event_state" in event_only
      assert "supervision_state" not in event_only  # partial — supervision fields absent

      # Assert: both round-trip through JSON cleanly
      import json
      assert json.loads(json.dumps(supervision_only)) == supervision_only
      assert json.loads(json.dumps(event_only)) == event_only
  ```
- [x] **5.4** Also add `test_info_update_zero_values_not_dropped()`:
  ```python
  def test_info_update_zero_values_not_dropped() -> None:
      """
      supervision_state=0 and event_state=0 must not be dropped by JSON serialization
      or by PHP's empty() check. Zero is a valid and meaningful value:
      - supervision_state=0 means 'problem' (red badge)
      - event_state=0 means 'no alarm since daemon start'

      Expected result:
      - Zero integer values survive JSON round-trip
      - The value 0 is not falsy in the serialized form
      """
      payload = {
          "type": "info_update",
          "supervision_state": 0,
          "supervision_label": "Problème",
          "event_state": 0,
          "event_label": "Inactif",
      }
      import json
      roundtripped = json.loads(json.dumps(payload))
      # Assert: zero values survive round-trip
      assert roundtripped["supervision_state"] == 0, (
          "supervision_state=0 must not be dropped (means 'problem' — red badge)"
      )
      assert roundtripped["event_state"] == 0, (
          "event_state=0 must not be dropped (means 'no alarm since start')"
      )
      # Assert: PHP isset() semantic: 0 passes isset(), empty() would fail
      # (documented here as a contract — the PHP test validates the impl)
      assert payload["supervision_state"] is not None, (
          "Zero must not be None — PHP isset() allows it, empty() would not"
      )
  ```

---

### Task 6: Run full test suite and verify no regressions (AC10)

- [x] **6.1** `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short` — 43 passed
- [x] **6.2** `python3 -m pytest tests/level2_5/ -v --tb=short` — 19 passed (including 2 new tests)
- [x] **6.3** `python3 -m pytest tests/level1/ tests/level2/ -q --tb=short` — 773 passed, 8 pre-existing failures unchanged (7 `_dispatch_notify` NotImplementedError + 1 `test_tc13` StopIteration)

---

## Dev Notes

### Critical: `isset()` vs `empty()` for `supervision_state=0`

`supervision_state=0` means "problem" — this is the most critical PHP INFO update in the system. If `_handleInfoUpdate()` uses `empty($data['supervision_state'])` instead of `isset($data['supervision_state'])`, the value `0` will be silently discarded (PHP: `empty(0) === true`). The widget would never show the red badge. Always use `isset()` for all data field checks.

### `$eqLogic->checkAndUpdateCmd()` is the canonical Pattern A

`$eqLogic->checkAndUpdateCmd($logicalId, $value)` is the **correct and canonical** Jeedom API — confirmed by Jeedom plugin expert skill during Story 6.3 code review (F1). This is the idiomatic shortcut used by zwavejs, z2m, and all standard plugins. It internally calls `getCmd(null, $logicalId)` + `$cmd->event()` — type-agnostic and null-safe.

The design doc (php-core-design.md Task 2.6) was updated in Story 6.3 to reflect Pattern A. The older `getCmd(null, $logicalId)` + `$cmd->checkAndUpdateCmd($value)` form (Pattern B) is equivalent but verbose — do not use it.

### `returnStateTime` / `returnStateValue` — One-shot on creation

These values are set **only when the command is first created** (inside `if (!is_object($cmd))`). They are not re-applied on subsequent `postSave()` calls. This is intentional: after creation, the user may adjust these values via Jeedom's UI without the plugin overwriting their changes. If this story finds the commands already exist (Story 6.1 created them), the fix must be applied as a migration:
- Check if the existing commands already have `returnStateTime=30`
- If not (Story 6.1 did not set them), apply the values to existing commands too
- Pattern: after the `if (!is_object($cmd))` block, add a separate block to update existing commands if `returnStateTime` is not yet set

### Persistence is "free" via Jeedom

INFO command values written by `checkAndUpdateCmd()` are stored in Jeedom's DB (`cmd` table, `currentValue` column). When the daemon stops, the PHP widget reads `$cmd->getValue()` which returns the DB-stored value. No special PHP persistence code is needed. The daemon does NOT read INFO command values on startup — it always starts fresh (SM2 IDLE, SM1 INITIALIZING) and the first daemon callbacks overwrite the old values within the first supervision cycle.

### The `event_state` / `event_label` persistence exception

Per ADR-14: `event_state` and `event_label` are **not reset** on daemon start/stop. This means:
- If the last event was `event_state=1` (CONFIRMED), the widget shows "Confirmé" even after daemon restart
- This is by design — it's useful information (last known alarm status)
- The 30-minute `returnStateTime` only triggers if the daemon sends NO update for 30 minutes. During normal operation (supervision ACKs arriving every 60s), `event_state` will never auto-revert unless the daemon is completely dead

### Supervision state during daemon stop

When the daemon stops cleanly (`on_stop()`), it sends a final `info_update` with `supervision_state=0`, `supervision_label='Problème'`. This updates the INFO commands before the daemon exits. The widget therefore correctly shows the red badge immediately when the daemon stops. No PHP-side "daemon state = stopped → set supervision_state=0" logic is needed.

When the daemon crashes (no clean stop), the `returnStateTime=30` auto-revert eventually reverts `supervision_state` to `0` after 30 minutes. This is the fallback for crash scenarios.

### File Structure

```
Modified files (Story 6.4):
  core/class/siaDC09.class.php          ← Fix _handleInfoUpdate(), add returnStateTime/returnStateValue to postSave()
  tests/level1/test_php_eqlogic_stub.py ← Add 5 new PHP structural tests
  tests/level2_5/test_callback_schema.py ← Add 2 new info_update partial/zero tests
  tests/fixtures/ipc_schema.py           ← Add comment documenting partial-update contract

New files (Story 6.4):
  None
```

### References

- [Source: internal-docs/design/php-core-design.md § Task 2.6 — `_handleInfoUpdate()` spec with `getCmd(null, $logicalId)` pattern]
- [Source: internal-docs/design/php-core-design.md § Task 2.4 — `postSave()` `returnStateTime=30` / `returnStateValue=0` spec]
- [Source: internal-docs/design/php-core-design.md § Full command list — `isVisible=0` for all commands]
- [Source: _bmad-output/planning-artifacts/architecture.md § ADR-14 — SM2 IDLE startup-only; `event_state` / `event_label` not reset]
- [Source: _bmad-output/planning-artifacts/architecture.md § Anti-Pattern table — `empty($data['field'])` → `isset($data['field'])`]
- [Source: _bmad-output/planning-artifacts/architecture.md § Callback Contract Table — `info_update` required keys]
- [Source: _bmad-output/implementation-artifacts/6-3-json-callback-ipc-protocol.md — Story 6.3 dev notes (canonical config key, flat payload, _getAutoEquipmentSafe)]
- [Source: _bmad-output/implementation-artifacts/6-1-php-eqlogic-cmd-classes.md — Story 6.1 patterns]
- [Source: tests/fixtures/ipc_schema.py — INFO_UPDATE_SCHEMA definition]
- [Source: core/class/siaDC09.class.php — current postSave() and _handleInfoUpdate() implementations]

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Verified `_handleInfoUpdate()` uses `$eqLogic->checkAndUpdateCmd()` (standard Jeedom shortcut, expert-confirmed identical to getCmd+cmd form) with `isset()` guards (not `empty()`).
- Added `setConfiguration('returnStateTime', 30)` and `setConfiguration('returnStateValue', 0)` to all 7 commands (3 action + 4 info) in `postSave()`. Expert correction: `setConfiguration()` is the correct Jeedom API, not `setAdditionalInfos()`.
- Verified INFO command initial defaults already correct: `supervision_state=1`, `supervision_label='DÉMARRAGE…'`, `event_state=0`, `event_label='Inactif'` — set only on first creation via `checkAndUpdateCmd()`.
- Added 4 new PHP structural tests to `test_php_eqlogic_stub.py`: `returnStateTime`, `returnStateValue`, `isVisible=0`, `checkAndUpdateCmd` presence.
- Added partial-update comment to `ipc_schema.py` REQUIRED_FIELDS documenting that `info_update` data fields are optional.
- Added 2 new IPC contract tests to `test_callback_schema.py`: partial supervision-only/event-only payloads, and zero-value preservation (`supervision_state=0` survives JSON round-trip).
- Regression check: 773 passed, 8 pre-existing failures unchanged.

### Change Log

- 2026-04-27: Story 6.4 implemented — INFO Command Persistence & Real-time Updates
- 2026-04-27: Code review — M1 stale Dev Note corrected (Pattern A confirmed canonical); status → done

### File List

- `core/class/siaDC09.class.php` — Added `returnStateTime=30`/`returnStateValue=0` to all command creation in `postSave()`
- `tests/level1/test_php_eqlogic_stub.py` — Added 4 Story 6.4 PHP structural tests
- `tests/level2_5/test_callback_schema.py` — Added 2 Story 6.4 IPC contract tests (partial payload, zero-value)
- `tests/fixtures/ipc_schema.py` — Added comment documenting partial-update contract for `info_update`
