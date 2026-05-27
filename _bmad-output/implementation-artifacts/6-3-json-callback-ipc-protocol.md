# Story 6.3: JSON Callback IPC Protocol

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a daemon architect,
I want the daemon to push state updates to PHP via JSON callbacks,
So that PHP always has current daemon state without polling.

## Acceptance Criteria

1. **`core/php/jeesiaDC09.php` created** — HTTP endpoint called by the daemon via `send_to_jeedom()`. Validates API key, handles test ping, dispatches JSON payload to `siaDC09::message()`. Matches the `jeeaiodemo.php` reference pattern exactly.

2. **`message()` fully implemented** — All 5 callback type cases are complete (not stubs): `info_update`, `message_center`, `notify`, `error_update`, `message_trace`. The `default:` branch logs an unknown-type warning.

3. **`_handleInfoUpdate()` fully implemented** — Updates the 4 INFO commands (`supervision_state`, `supervision_label`, `event_state`, `event_label`) via `checkAndUpdateCmd()`. Uses `isset()` guard on each field (never `empty()`).

4. **`message_center` case implemented** — Calls `message::add(__CLASS__, $message, '', $logicalId)` using the `logical_id` field from the payload as dedup key.

5. **`notify` case implemented** — Reads `sia_notify_cmd_id` from eqLogic config. If ≤ 0: logs warning and breaks. Otherwise: `cmd::byId()` + `execCmd(['title' => ..., 'message' => ...])` wrapped in `try/catch`.

6. **`error_update` case implemented** — Reads `sia_last_errors` from plugin-level config (`config::byKey`), prepends new entry, enforces max-10 cap, saves back via `config::save`. T1 auto-resolve: removes `SUPERVISION_TIMEOUT` and `SUPERVISION_NAK` entries when `resolve_t1: true` flag is in payload.

7. **`message_trace` case implemented** — Reads `sia_last_messages` from plugin-level config, handles routine-entry replacement vs. prepend logic, enforces max-50 cap, saves back via `config::save`.

8. **`en_US.json` updated** — All new French strings in `message()` have English translations in the `siaDC09.class.php` section.

9. **`tests/fixtures/ipc_schema.py` created** — Canonical schema definitions for all 5 callback types. Includes `# schema_version = 1` comment header. All fields mandatory per type defined.

10. **`tests/level2_5/test_callback_schema.py` created** — Tests verify each callback type's required fields, types, and round-trip JSON serialization. Uses the recording-shim pattern (not silent mocks).

11. **Idempotent** — Duplicate callbacks (same data sent twice) do not corrupt state: `checkAndUpdateCmd()` is idempotent, `message::add()` uses `logical_id` for occurrence counting, `error_update` prepend at caller side avoids double-entry.

12. **Failed callbacks non-fatal** — `_dispatch_notify()` (Python side) already wraps each channel in `try/except`. PHP `message()` never raises exceptions that would propagate back as HTTP 500 — all errors are logged and execution continues.

---

## Tasks / Subtasks

### Task 1: Create `core/php/jeesiaDC09.php` (AC1)

- [x] **1.1** Create `core/php/jeesiaDC09.php` based on `core/php/jeeaiodemo.php`:
  - Replace `aiodemo` plugin ID with `siaDC09` in `jeedom::apiAccess()`
  - Replace `aiodemo::handleFeedback($result)` with `siaDC09::message($result)`
  - Replace `log::add('aiodemo', ...)` with `log::add('siaDC09', ...)`
  - Keep exact same structure: `try { ... } catch (Exception $e) { ... }`
- [x] **1.2** Verify the callback URL matches what `deamon_start()` already builds:
  ```
  network::getNetworkAccess('internal', 'http:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php'
  ```
  *(Note: `deamon_start()` currently uses `proto:127.0.0.1:port:comp` — verify which is correct against design doc)*

---

### Task 2: Implement `siaDC09::message()` body (AC2, AC3, AC4, AC5, AC6, AC7)

- [x] **2.1** Replace stub `case 'info_update':` with full `_handleInfoUpdate($eqLogic, $message)` call
- [x] **2.2** Implement `case 'message_center':` (AC4):
  ```php
  message::add(
      __CLASS__,
      $message['message'],
      '',
      $message['logical_id']
  );
  ```
- [x] **2.3** Implement `case 'notify':` (AC5):
  - Reads `sia_notify_cmd_id` from eqLogic (NOT from plain `notify_cmd_id` — see Critical Note below)
  - Guard: `if ($notifyCmdId <= 0)` → log warning + break
  - `cmd::byId($notifyCmdId)` → if not object, log warning + break
  - `try { $notifyCmd->execCmd(['title' => $message['title'], 'message' => $message['message']]); } catch (Exception $e) { log::add(...) }`
- [x] **2.4** Implement `case 'error_update':` (AC6):
  - `$errors = json_decode(config::byKey('sia_last_errors', __CLASS__, '[]'), true) ?: []`
  - T1 auto-resolve: `if (!empty($message['resolve_t1'])) { $errors = array_values(array_filter($errors, fn($e) => !in_array($e['code'], ['SUPERVISION_TIMEOUT', 'SUPERVISION_NAK']))); }`
  - Prepend: `array_unshift($errors, ['code' => ..., 'message' => ..., 'timestamp' => ..., 'context' => ..., 'count' => ...])` — all 5 fields mandatory
  - Cap: `$errors = array_slice($errors, 0, 10)`
  - Save: `config::save('sia_last_errors', json_encode($errors), __CLASS__)`
- [x] **2.5** Implement `case 'message_trace':` (AC7):
  - `$messages = json_decode(config::byKey('sia_last_messages', __CLASS__, '[]'), true) ?: []`
  - Routine branch: `if ($message['dialog']['dialog_type'] === 'supervision' && $message['dialog']['routine'])` → find and replace existing routine entry; if not found, prepend
  - Non-routine branch: `array_unshift($messages, $message['dialog'])`
  - Cap both paths: `$messages = array_slice($messages, 0, 50)`
  - Save: `config::save('sia_last_messages', json_encode($messages), __CLASS__)`
- [x] **2.6** Confirm `default:` warning branch logs unknown type without crashing

---

### Task 3: Implement `_handleInfoUpdate()` (AC3)

- [x] **3.1** Add `private static function _handleInfoUpdate($eqLogic, array $data): void` method
- [x] **3.2** Map 4 fields: `supervision_state`, `supervision_label`, `event_state`, `event_label`
- [x] **3.3** For each: `if (isset($data[$key]))` → `$eqLogic->checkAndUpdateCmd($logicalId, $data[$key])` (Pattern A — idiomatic Jeedom convenience wrapper, internally calls `getCmd(null, ...)`)
- [x] **3.4** Pattern A is null-safe and type-agnostic — confirmed by Jeedom plugin expert skill (design doc updated)

---

### Task 4: Update `en_US.json` translations (AC8)

- [x] **4.1** Add translations for all new French strings used in `message()`:
  - `"Message daemon reçu mais équipement absent — ignoré jusqu'à réactivation du plugin."` → `"Daemon message received but equipment missing — ignored until plugin reactivation."`
  - `"Commande notification non configurée — alerte ignorée"` → `"Notification command not configured — alert ignored"`
  - `"Impossible d'envoyer la notification : "` → `"Unable to send notification: "`
- [x] **4.2** Confirm `"Vous n'êtes pas autorisé à effectuer cette action"` is already in json for `jeesiaDC09.php` (check if key exists under its file path section — may need new section)

---

### Task 5: Create `tests/fixtures/ipc_schema.py` (AC9)

- [x] **5.1** Create `tests/fixtures/` directory if not exists (golden/ is already there)
- [x] **5.2** Create `tests/fixtures/ipc_schema.py` with `# schema_version = 1` header comment
- [x] **5.3** Define schemas as typed dicts / constants for all 5 types:
  - `INFO_UPDATE_SCHEMA`: `supervision_state` (int), `supervision_label` (str), `event_state` (int), `event_label` (str) — all optional (only present fields updated)
  - `MESSAGE_CENTER_SCHEMA`: `type` (str), `message` (str), `logical_id` (str)
  - `NOTIFY_SCHEMA`: `type` (str), `title` (str), `message` (str)
  - `ERROR_UPDATE_SCHEMA`: `type` (str), `code` (str), `message` (str), `timestamp` (str), `context` (dict|None), `count` (int), `resolve_t1` (bool optional)
  - `MESSAGE_TRACE_SCHEMA`: `type` (str), `dialog` (dict with `dialog_type`, `routine` fields at minimum)
- [x] **5.4** Add `REQUIRED_FIELDS` dict mapping type name → list of mandatory field names

---

### Task 6: Create `tests/level2_5/` IPC contract tests (AC10)

- [x] **6.1** Create `tests/level2_5/` directory + `__init__.py`
- [x] **6.2** Create `tests/level2_5/test_callback_schema.py` with tests:
  - `test_info_update_schema_valid_full()` — all 4 fields present, correct types
  - `test_info_update_schema_partial()` — only supervision fields present (event fields absent) — valid (partial updates allowed)
  - `test_message_center_required_fields()` — missing `logical_id` detected
  - `test_notify_required_fields()` — missing `title` or `message` detected
  - `test_error_update_all_five_fields_mandatory()` — all 5 entry fields required
  - `test_message_trace_dialog_structure()` — `dialog_type` and `routine` keys required in dialog
  - `test_all_payloads_json_round_trip()` — `json.dumps()` + `json.loads()` preserves all fields
  - `test_no_none_values_in_payloads()` — no None values (architecture mandate: omit absent fields)
  - `test_no_boolean_values_use_integers()` — Python `bool` not in schema (use 0/1)

---

### Task 7: PHP structural tests (AC2, AC3)

- [x] **7.1** Add tests to `tests/level1/test_php_eqlogic_stub.py`:
  - `test_message_method_exists()` — `message` function found in PHP source
  - `test_message_dispatches_all_five_types()` — `info_update`, `message_center`, `notify`, `error_update`, `message_trace` all appear as case labels in `message()` body
  - `test_message_uses_safe_equipment_lookup()` — `_getAutoEquipmentSafe()` called in message() body, NOT `_getAutoEquipment()`
  - `test_handle_info_update_uses_check_and_update_cmd()` — `checkAndUpdateCmd` present in `_handleInfoUpdate()` body
  - `test_error_update_uses_config_save_not_set_configuration()` — `config::save` present in message() body (NOT `setConfiguration`)
  - `test_notify_reads_sia_notify_cmd_id_not_bare_key()` — `sia_notify_cmd_id` (with sia_ prefix) is the config key, NOT `notify_cmd_id`

---

### Task 8: Run tests (AC10)

- [x] **8.1** `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short` — all pass
- [x] **8.2** `python3 -m pytest tests/level2_5/ -v --tb=short` — all pass
- [x] **8.3** `python3 -m pytest tests/level1/ tests/level2/ -q --tb=short` — no new regressions (pre-existing: 8 failures unchanged)

---

## Dev Notes

### Critical: Config Key is `sia_notify_cmd_id` (not `notify_cmd_id`)

`error-handler-design.md` line 499 incorrectly uses `notify_cmd_id`. The **canonical key** is `sia_notify_cmd_id` per:
- `php-core-design.md` § config table (line 87)
- `architecture.md` § IPC contract table (line 1030)
- `core/class/siaDC09.class.php` line 155 (already implemented correctly in Story 6.1)

The dev agent must use `sia_notify_cmd_id` everywhere. Do not follow the error-handler-design.md spelling.

### Critical: Flat JSON Payload — No Nested `data:` Envelope

Architecture mandate: payloads are flat `{"type": "...", "field": value, ...}`. **Never** `{"type": "...", "data": {"field": value}}`. The epics file AC says `data: {...}` — this is misleading. The canonical spec in `architecture.md` is flat JSON. The `type` field lives at the top level alongside all other fields.

### Critical: `message_center` and `message_trace` Use Plugin-Level Config

`sia_last_errors` and `sia_last_messages` are stored via `config::byKey()` / `config::save()` at **plugin level** (second arg = `__CLASS__`). They are **NOT** stored via `$eqLogic->setConfiguration()` or `$eqLogic->getConfiguration()`. Using eqLogic storage would trigger `postSave()` on every callback write (unacceptable overhead). This is confirmed in both `error-handler-design.md` and `logging-design.md`.

### `message()` Is Already Partially Stubbed in `siaDC09.class.php`

Story 6.1 added the `message()` skeleton with all 5 case labels as stubs and comments pointing to the design docs. Story 6.3 replaces the stub bodies with real implementations — **do not rewrite the method structure, only fill the stubs**.

Current stub structure (lines ~594–645):
```php
public static function message($message) {
    $eqLogic = self::_getAutoEquipmentSafe();
    if (!$eqLogic) { log::add(...warning...); return; }
    switch ($message['type']) {
        case 'info_update': ...stub...; break;
        case 'message_center': ...stub...; break;
        case 'notify': ...stub...; break;
        case 'error_update': ...stub...; break;
        case 'message_trace': ...stub...; break;
        default: log::add(...unknown type warning...); break;
    }
}
```

### `_handleInfoUpdate()` Does Not Exist Yet

Task 2.6 in `php-core-design.md` specifies it as a `private static` method. It must be added to `siaDC09.class.php` alongside `message()`. The `getCmd(null, $logicalId)` pattern (type-agnostic) is intentional — see design doc rationale.

### `jeesiaDC09.php` Callback URL in `deamon_start()`

The current `deamon_start()` implementation (Story 6.1) builds the callback URL with `proto:127.0.0.1:port:comp`:
```php
$cmd .= ' --callback ' . network::getNetworkAccess('internal', 'proto:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php';
```
The design doc (Task 2.12) specifies `http:127.0.0.1:port:comp`. This discrepancy was noted in Review 8 (`malformed callback URL proto: → http:`). Verify which is correct: `http:` forces HTTP (correct for localhost), `proto:` may resolve to HTTPS. **Use `http:127.0.0.1:port:comp`**. If `deamon_start()` was not updated in Story 6.1/6.2, fix it here.

### T1 Auto-Resolve in `error_update`

When SM1 recovers (ACK received after DEGRADED), the daemon sends an `error_update` with `resolve_t1: true`. PHP must remove all entries with `code` in `['SUPERVISION_TIMEOUT', 'SUPERVISION_NAK']` before prepending the new entry. The daemon also sends a final `error_update` with empty data on recovery — PHP discards it if no new entry needs adding. The `resolve_t1` flag controls cleanup only; it is not a required field.

### Level 2.5 Test Pattern (Recording Shim)

Level 2.5 tests use a **recording shim** — not a silent mock. The shim wraps `send_to_jeedom()` and records every payload the daemon emits. Tests then assert on payload shape, types, and field presence. This is NOT the same as `MagicMock(return_value=None)`. Pattern:

```python
class CallbackRecorder:
    def __init__(self):
        self.calls: list[dict] = []
    async def record(self, payload: dict) -> None:
        self.calls.append(payload)
```

Tests for `test_callback_schema.py` in Story 6.3 are **pure Python schema validators** — they do NOT require a running daemon (Level 2 test). They validate that the schemas in `ipc_schema.py` are internally consistent and that sample payloads conform to them.

### Pre-existing Test Failures

The 7 failing tests in `tests/level1/test_error_handler.py` are caused by `_dispatch_notify` raising `NotImplementedError` (stub from Story 3.3). **Story 6.3 does NOT implement `_dispatch_notify`** — that is the Python daemon side of `_notify()`, part of Epic 5 stories already done or Epic 7. These 7 failures remain pre-existing after this story.

Story 6.3 implements only the **PHP side** of the callback protocol. The Python `_dispatch_notify` in the daemon is already fully implemented (Story 5.x). What is missing is the PHP receiver side (`jeesiaDC09.php` + `message()` implementation) and the contract test fixture.

### Two-Phase Boundary: PHP Receiver vs. Python Sender

| Side | Already done | Story 6.3 adds |
|------|-------------|----------------|
| Python (sender) | `_dispatch_notify()` in `daemon.py`, `send_to_jeedom()` in jeedomdaemon framework | Nothing |
| PHP (receiver) | `message()` skeleton with stubs | `jeesiaDC09.php`, full `message()` impl, `_handleInfoUpdate()` |
| Contract tests | None | `tests/fixtures/ipc_schema.py`, `tests/level2_5/test_callback_schema.py` |

### File Structure

```
New files (Story 6.3):
  core/php/jeesiaDC09.php                          ← Daemon→PHP HTTP router shim
  tests/fixtures/ipc_schema.py                     ← Canonical IPC callback schemas
  tests/level2_5/__init__.py                        ← Package init
  tests/level2_5/test_callback_schema.py           ← IPC contract tests

Modified files (Story 6.3):
  core/class/siaDC09.class.php                     ← Implement message() cases + _handleInfoUpdate()
  core/i18n/en_US.json                             ← Add new message() strings
  tests/level1/test_php_eqlogic_stub.py            ← Add PHP structural tests for message()

Possibly modified (Story 6.3):
  core/class/siaDC09.class.php (deamon_start)      ← Fix proto: → http: in callback URL if not already done

Reference files (DO NOT MODIFY):
  core/php/jeeaiodemo.php                          ← Template for jeesiaDC09.php
  docs/design/php-core-design.md § Task 2.6, 2.12 ← message() and jeesiaDC09.php spec
  docs/design/error-handler-design.md § PHP callbacks ← message_center/notify/error_update spec
  docs/design/logging-design.md § message_trace    ← message_trace spec
```

### References

- [Source: docs/design/php-core-design.md § Task 2.6 — message() full spec with all cases]
- [Source: docs/design/php-core-design.md § Task 2.12 — jeesiaDC09.php spec]
- [Source: docs/design/error-handler-design.md § PHP callback — new payload types]
- [Source: docs/design/logging-design.md § message_trace PHP callback]
- [Source: _bmad-output/planning-artifacts/architecture.md § IPC callback types (canonical list)]
- [Source: _bmad-output/planning-artifacts/architecture.md § Communication Patterns (flat JSON mandate)]
- [Source: core/php/jeeaiodemo.php — reference router shim to copy/adapt]
- [Source: core/class/siaDC09.class.php — existing message() stub to fill in]
- [Source: _bmad-output/implementation-artifacts/6-2-auto-equipment-creation.md — Story 6.2 patterns]

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Created `core/php/jeesiaDC09.php` — daemon→PHP callback router. API key validation, test ping, JSON dispatch to `siaDC09::message()`. Based on `jeeaiodemo.php` reference.
- Fixed callback URL in `deamon_start()`: `proto:127.0.0.1:port:comp` → `http:127.0.0.1:port:comp` (Review 8 finding, confirmed by Jeedom plugin expert skill).
- Implemented full `message()` method with all 5 callback types: `info_update` (delegates to `_handleInfoUpdate`), `message_center` (Jeedom message center with dedup), `notify` (execCmd with try/catch), `error_update` (plugin-level config, T1 auto-resolve, max-10 cap), `message_trace` (routine replacement vs prepend, max-50 cap).
- Implemented `_handleInfoUpdate()` — maps 4 INFO commands via `$eqLogic->checkAndUpdateCmd($logicalId, $value)` (Pattern A — idiomatic Jeedom convenience wrapper) with `isset()` guards.
- Uses `_getAutoEquipmentSafe()` (never `_getAutoEquipment()`) in `message()` — confirmed by expert validation.
- Uses `config::byKey` / `config::save` for `sia_last_errors` and `sia_last_messages` at plugin level (not eqLogic).
- Uses `sia_notify_cmd_id` (canonical key with `sia_` prefix, not bare `notify_cmd_id`).
- Added 3 new French→English translations to `en_US.json` + new `jeesiaDC09.php` section.
- Created `tests/fixtures/ipc_schema.py` — canonical IPC callback schemas with `# schema_version = 1`, required fields, and 9 sample payloads.
- Created `tests/level2_5/test_callback_schema.py` — 17 contract tests covering schema consistency, field validation, JSON round-trip, no-None mandate, no-boolean mandate, null-context round-trip, extensibility guard.
- Added 20 PHP structural tests to `test_php_eqlogic_stub.py`: callback file/API key/message dispatch/safe equipment lookup/checkAndUpdateCmd/config::save/sia_notify_cmd_id/callback URL + QA gap tests (isset guard, default branch, config key names, cap enforcement, test ping, try/catch safety, T1 resolve code sync).
- Regression check: 776 passed, 8 pre-existing failures unchanged (7 `_dispatch_notify` NotImplementedError + 1 `test_tc13` StopIteration).

### File List

- `core/php/jeesiaDC09.php` — **NEW** — Daemon→PHP HTTP callback router
- `core/class/siaDC09.class.php` — Added `message()` + `_handleInfoUpdate()`, fixed callback URL proto:→http:
- `core/i18n/en_US.json` — Added 3 translations + jeesiaDC09.php section
- `tests/fixtures/ipc_schema.py` — **NEW** — Canonical IPC callback schemas (schema_version=1)
- `tests/level2_5/__init__.py` — **NEW** — Package init
- `tests/level2_5/test_callback_schema.py` — **NEW** — 15 IPC contract tests
- `tests/level1/test_php_eqlogic_stub.py` — Added 11 Story 6.3 PHP structural tests

### Change Log

- 2026-04-27: Story 6.3 created — JSON Callback IPC Protocol
- 2026-04-27: Story 6.3 implemented — jeesiaDC09.php, message() with 5 callback types, _handleInfoUpdate(), IPC schema fixture, 26 new tests (11 PHP structural + 15 IPC contract)
- 2026-04-27: QA challenge — 11 gap tests added (isset guard, default branch, config keys, caps, test ping, try/catch, T1 sync, null-context, extensibility)
- 2026-04-27: Adversarial review — F1 Pattern A confirmed (design doc updated), F2 preRemove cleanup fixed (code + design doc), F3 noted, F8 TypedDicts removed
- 2026-04-27: Edge case hunter — dialog null guard added, error_update notice-level edges noted
- 2026-04-27: Code review — completion notes corrected, status → done
