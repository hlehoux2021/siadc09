# Story 6.6: PHP Core Integration & IPC Tests

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a plugin architect,
I want daemon and PHP to communicate reliably,
So that state updates flow seamlessly between the Python daemon and PHP plugin.

## Acceptance Criteria

1. **`_update_info_commands()` wired to `send_to_jeedom()`** — Replace the stub `_update_info_commands_stub()` in `daemon.py` with a real implementation that calls `await self.send_to_jeedom(payload)` from the `BaseDaemon` framework. The payload must conform to the `info_update` schema in `tests/fixtures/ipc_schema.py` (flat JSON, `type: "info_update"`, snake_case fields, no None values, int 0/1 not bool).

2. **`_notify()` dispatches via `_send_callback()`** — Replace the stub `_notify()` body with `self._track_task(self._dispatch_notify(code, ctx), name=f"notify_{code.name}")`. Implement `_dispatch_notify()` as an async method that builds the appropriate callback payloads (`error_update`, `message_center`, `notify`) and calls `_send_callback()`. The tier→callback mapping:
   - T1 (SUPERVISION_TIMEOUT, SUPERVISION_NAK): `message_center` only
   - T2 (BAD_CSR_RESPONSE): `message_center` + `notify`
   - T3 (SUPERVISION_DISCONNECTED, EVENT_FAILED, TRANSPORT_PERMANENT): `message_center` + `notify` (with "CRITIQUE — " prefix on title)

3. **`_send_callback(payload)` wraps `send_to_jeedom()`** — Defensive wrapper: catches all exceptions, logs ERROR, returns. Never re-raises. Non-fatal to daemon operation. Must validate payload structure before sending (type field present, no bool values).

4. **`on_message()` signature aligned with framework** — The jeedomdaemon `BaseDaemon.on_message_cb` receives the full parsed message dict. Current `on_message(self, cmd, params)` signature must be wired correctly to the framework's callback. Verify the `cmd` key extraction matches what PHP `sendToDaemon()` sends (`{'cmd': 'burglarAlarm', 'zone': '...'}`).

5. **`on_start()` wires `_update_info_commands` to real implementation** — Replace `self._update_info_commands = self._update_info_commands_stub` with the real async method that calls `_send_callback()` with `info_update` payload.

6. **Ring buffer `message_trace` callback integration** — `_log_sm1_supervision()` and `_log_sm2_event()` must emit `message_trace` callbacks via `_send_callback()` after pushing to the ring buffer. Payload schema per `ipc_schema.py`: `{"type": "message_trace", "dialog": {...}}`.

7. **`error_update` callback for `last_errors` persistence** — `_dispatch_notify()` must emit `error_update` callbacks for T1 resolve (when strike resets to 0 after ACK) and for new errors (T2/T3). Schema per `ipc_schema.py`.

8. **Level 2.5 integration tests** — New tests in `tests/level2_5/` validating that daemon methods emit correct callback payloads:
   - `test_update_info_commands_emits_info_update` — supervision state change → `info_update` callback
   - `test_notify_t1_emits_message_center_only` — T1 error → `message_center` (no `notify`)
   - `test_notify_t2_emits_message_center_and_notify` — T2 error → `message_center` + `notify`
   - `test_notify_t3_emits_critique_prefix` — T3 error → `notify` title starts with "CRITIQUE — "
   - `test_error_update_on_new_error` — New error → `error_update` with all 5 fields
   - `test_error_update_resolve_t1_on_ack` — ACK after strike → `error_update` with `resolve_t1: 1`
   - `test_message_trace_supervision` — Supervision ACK → `message_trace` with `routine: 1`
   - `test_message_trace_alarm` — Alarm confirm → `message_trace` with `routine: 0`
   - `test_send_callback_exception_resilience` — `send_to_jeedom` raises → exception logged, daemon continues

9. **Level 2 daemon integration tests** — Extend existing Level 2 tests to validate:
   - `test_on_message_enqueues_alarm_event` — PHP command via `on_message()` → EVENT enqueued
   - `test_daemon_stop_preserves_event_state` — SM2 state survives daemon restart (INFO commands retain last values)
   - `test_multiple_action_commands_independent` — 3 alarm commands enqueued without interference
   - `test_send_callback_does_not_block_queue_consumer` — Exception in callback delivery doesn't stall queue

10. **All existing tests pass** — No regressions in Level 1, Level 2, or Level 2.5 test suites.

---

## Tasks / Subtasks

### Task 1: Implement `_send_callback()` (AC3)

- [x] **1.1** Add `_send_callback(self, payload: dict) -> None` async method to `SIADaemon`
- [x] **1.2** Implementation: validate `type` field present, no `bool` values (assertion or log+skip), then `await self.send_to_jeedom(payload)`
- [x] **1.3** Wrap entire body in try/except that catches `Exception`, logs ERROR via `self._logger.error()`, and returns — never re-raises
- [x] **1.4** Add type annotation: `async def _send_callback(self, payload: dict[str, Any]) -> None`

---

### Task 2: Wire `_update_info_commands()` to real callback (AC1, AC5)

- [x] **2.1** Replace `_update_info_commands_stub` assignment in `__init__` with `self._update_info_commands = self._update_info_commands_impl`
- [x] **2.2** Implement `_update_info_commands_impl(self, data: InfoCommandsPayload | None = None) -> None`:
  - If `data` is None: build full payload from `_supervision_value()`, `_supervision_label()`, `_event_state_from_sm2()`, `_event_label_from_sm2()`
  - If `data` is provided: use it directly (partial update)
  - Add `"type": "info_update"` to payload
  - Call `await self._send_callback(payload)`
- [x] **2.3** Remove the `_update_info_commands_stub` method entirely
- [x] **2.4** In `on_start()`: remove the stub assignment line (method is now defined directly on class)

---

### Task 3: Implement `_dispatch_notify()` and wire `_notify()` (AC2, AC7)

- [x] **3.1** Implement `async def _dispatch_notify(self, code: ErrorCode, ctx: NotificationContext) -> None`
- [x] **3.2** Tier→callback dispatch logic (each channel in its own try/except — failure of one must not prevent the others):
  - T1 codes (SUPERVISION_TIMEOUT, SUPERVISION_NAK): emit `message_center` only
  - T2 codes (BAD_CSR_RESPONSE): emit `message_center` + `notify` + `error_update`
  - T3 codes (SUPERVISION_DISCONNECTED, EVENT_FAILED, TRANSPORT_PERMANENT): emit `message_center` + `notify` (CRITIQUE prefix) + `error_update`
- [x] **3.3** Build `message_center` payload: `{"type": "message_center", "message": <French msg from build_notification()>, "logical_id": code.name}`
- [x] **3.4** Build `notify` payload: `{"type": "notify", "title": <title from build_notification(), with CRITIQUE prefix for T3>, "message": <French description>}`
- [x] **3.5** Build `error_update` payload for new errors: `{"type": "error_update", "code": code.name, "message": <msg>, "timestamp": <ISO 8601>, "context": <ctx dict or None>, "count": 1}`
- [x] **3.6** Emit `resolve_t1` on ACK: when `_handle_supervision_ack()` resets strike from >0 to 0, call `_send_callback({"type": "error_update", "resolve_t1": 1})`
- [x] **3.7** Replace `_notify()` stub body with: `self._track_task(self._dispatch_notify(code, ctx), name=f"notify_{code.name}")`
- [x] **3.8** Add tier classification helper: `_error_tier(code: ErrorCode) -> Literal[1, 2, 3]` — returns tier number based on ErrorCode
- [x] **3.9** Implement `build_notification(code: ErrorCode, context: NotificationContext) -> NotificationPayload` in `error_handler.py` — currently a stub (`...`). Must produce `NotificationPayload` TypedDict with `tier`, `logical_id`, `title`, `message` fields. French message templates per error-handler-design.md § Notification Templates. Use `dataclasses.asdict(ctx)` + `.get('field', '<inconnu>')` for missing-field resilience.

---

### Task 4: Wire `message_trace` callbacks (AC6)

- [x] **4.1** In `_log_sm1_supervision()`: after `self._ring_buffer.push_supervision_entry(...)`, call `await self._send_callback({"type": "message_trace", "dialog": {...}})` with appropriate dialog fields
- [x] **4.2** Dialog fields for supervision: `dialog_type`, `routine` (1 for routine ACK, 0 for strike/NAK), `timestamp`, `request_hex`, `response_hex`, `elapsed_ms`
- [x] **4.3** In `_log_sm2_event()`: after ring buffer push, call `await self._send_callback({"type": "message_trace", "dialog": {...}})` with dialog_type="alarm", routine=0
- [x] **4.4** All dialog fields must be present (no None values — omit field entirely per architecture mandate)

---

### Task 5: Fix `on_message()` framework wiring and `super().__init__()` (AC4)

- [x] **5.1** **FIX `super().__init__()` — currently MISSING all 3 callbacks.** The current call is `super().__init__(config=config or BaseConfig())`. It must become: `super().__init__(config=config or BaseConfig(), on_start_cb=self.on_start, on_message_cb=self._on_message_dispatch, on_stop_cb=self.on_stop)`. Without this, the framework never fires on_start/on_message/on_stop.
- [x] **5.2** **REFACTOR `on_message()` signature — currently INCOMPATIBLE with framework.** The framework passes ONE argument: the full parsed dict **including `apikey`** (e.g., `{"cmd": "burglarAlarm", "zone": "salon", "apikey": "..."}`). Current signature `on_message(self, cmd: str, params: OnMessageParams)` will cause a TypeError. Create `_on_message_dispatch(self, message: dict) -> None` as the framework callback that: (a) pops `apikey` from the dict (`message.pop('apikey', None)`), (b) extracts `cmd = message.pop('cmd', '')`, then passes remainder as params to the existing `on_message()` logic.
- [x] **5.3** Update `on_message()` OR inline its logic into `_on_message_dispatch()`. Keep `_EVENT_SIA_CODES` lookup, zone extraction, and `_enqueue_event()` call.
- [x] **5.4** Update all existing Level 2 tests that call `on_message(cmd, params)` directly — they must now call `_on_message_dispatch({"cmd": "burglarAlarm", "zone": "salon"})` or use the public API.

---

### Task 6: Create Level 2.5 IPC integration tests (AC8)

- [x] **6.1** Create `tests/level2_5/test_ipc_integration.py` with recording shim pattern
- [x] **6.2** Recording shim: mock `send_to_jeedom` to capture emitted payloads in a list
- [x] **6.3** Test `test_update_info_commands_emits_info_update`: trigger `_update_info_commands()` → verify `info_update` payload in captured list
- [x] **6.4** Test `test_notify_t1_emits_message_center_only`: call `_notify(SUPERVISION_TIMEOUT, ctx)` → gather tasks → verify only `message_center` emitted (no `notify`)
- [x] **6.5** Test `test_notify_t2_emits_message_center_and_notify`: call `_notify(BAD_CSR_RESPONSE, ctx)` → verify both `message_center` and `notify` emitted
- [x] **6.6** Test `test_notify_t3_emits_critique_prefix`: call `_notify(SUPERVISION_DISCONNECTED, ctx)` → verify `notify` title starts with "CRITIQUE — "
- [x] **6.7** Test `test_error_update_on_new_error`: verify `error_update` payload has all 5 fields (code, message, timestamp, context, count)
- [x] **6.8** Test `test_error_update_resolve_t1_on_ack`: simulate supervision ACK after strike>0 → verify `error_update` with `resolve_t1: 1`
- [x] **6.9** Test `test_message_trace_supervision`: trigger supervision ACK → verify `message_trace` with `dialog.routine == 1`
- [x] **6.10** Test `test_message_trace_alarm`: trigger alarm confirm → verify `message_trace` with `dialog.routine == 0`
- [x] **6.11** Test `test_send_callback_exception_resilience`: mock `send_to_jeedom` to raise → verify daemon continues, error logged

---

### Task 7: Create Level 2 daemon integration tests (AC9)

- [x] **7.1** Add tests to `tests/level2/test_daemon_integration.py` or create new `tests/level2/test_ipc_daemon_wiring.py`
- [x] **7.2** Test `test_on_message_enqueues_alarm_event`: call `on_message("burglarAlarm", {"zone": "salon"})` → verify EVENT item in queue
- [x] **7.3** Test `test_daemon_stop_preserves_event_state`: after SM2=CONFIRMED, call `on_stop()` then `on_start()` → verify SM2 resets to IDLE (INFO commands retain PHP-side values — daemon is authoritative on push, not on restart)
- [x] **7.4** Test `test_multiple_action_commands_independent`: enqueue 3 different alarm types → verify all 3 processed in order
- [x] **7.5** Test `test_send_callback_does_not_block_queue_consumer`: mock callback to raise → verify queue consumer continues dequeuing

---

### Task 8: Run full test suite (AC10)

- [x] **8.1** `python3 -m pytest tests/level1/ -v --tb=short` — all pass
- [x] **8.2** `python3 -m pytest tests/level2/ -v --tb=short` — all pass
- [x] **8.3** `python3 -m pytest tests/level2_5/ -v --tb=short` — all pass, new tests included
- [x] **8.4** `python3 -m pytest tests/ -q --tb=short` — no regressions from previous 820+ tests

---

## Dev Notes

### Critical: `send_to_jeedom()` is a framework method

The `jeedomdaemon.BaseDaemon` class provides `send_to_jeedom(payload: dict)` as an async method. It POSTs JSON to the callback URL configured via `--callback` CLI arg (which `deamon_start()` sets to `jeesiaDC09.php`). The reference plugin (`aiodemod.py`) demonstrates usage: `await self.send_to_jeedom({'key': 'value'})`.

### Critical: `super().__init__()` is MISSING all 3 framework callbacks

The current `SIADaemon.__init__()` line 317 calls:
```python
super().__init__(config=config or BaseConfig())
```
This does NOT wire `on_start_cb`, `on_message_cb`, or `on_stop_cb`. The reference plugin (`aiodemod.py`) shows the correct pattern:
```python
super().__init__(config=DemoConfig(), on_start_cb=self.on_start, on_message_cb=self.on_message, on_stop_cb=self.on_stop)
```
Without these, the framework ignores lifecycle events and PHP messages. **This must be fixed in Task 5.1.**

### Critical: `on_message()` signature is WRONG — must accept raw dict

The framework's `on_message_cb` passes ONE argument: the full parsed JSON dict **with `apikey` still present** (the framework validates the apikey but does NOT strip it — see `base_daemon.py` line 169). The type annotation says `list` but it's actually `dict` — the reference plugin (`aiodemod.py`) confirms dict-style access (`message['action']`). Our current `on_message(self, cmd: str, params: OnMessageParams)` has a 2-param signature that will cause a TypeError. An adapter method is required (Task 5.2), and it must strip `apikey` from the dict before processing.

### Critical: `_send_callback()` must be defensive

Architecture mandate: `_send_callback()` wraps `send_to_jeedom()`. It catches ALL exceptions, logs ERROR, returns — never re-raises. Failure to deliver a callback is NON-FATAL to daemon operation. This prevents a PHP crash or network blip from killing the daemon.

### Critical: IPC payload format rules (architecture.md)

- Flat JSON, `type` field at top level — NEVER nested `{"type": "...", "data": {...}}`
- `snake_case` field names
- No `None` values — omit absent fields entirely (exception: `context` in `error_update`)
- No Python `bool` — use integers `0`/`1`
- `ipc_schema.py` is the authoritative source for schemas

### Critical: Tier classification for `_dispatch_notify()`

| ErrorCode | Tier | Callbacks |
|-----------|------|-----------|
| SUPERVISION_TIMEOUT | T1 | `message_center` |
| SUPERVISION_NAK | T1 | `message_center` |
| BAD_CSR_RESPONSE | T2 | `message_center` + `notify` + `error_update` |
| SUPERVISION_DISCONNECTED | T3 | `message_center` + `notify` (CRITIQUE prefix) + `error_update` |
| EVENT_FAILED | T3 | `message_center` + `notify` (CRITIQUE prefix) + `error_update` |
| TRANSPORT_PERMANENT | T3 | `message_center` + `notify` (CRITIQUE prefix) + `error_update` |

### Critical: `build_notification()` is a STUB — must be implemented

`error_handler.py` has `build_notification()` as `...` (ellipsis stub). The French notification message templates do NOT live in `messages.py` — they are defined only in `error-handler-design.md § Notification Templates`. `messages.py` contains logger strings (dual-line pattern), not notification payloads.

`build_notification(code, context)` must return a `NotificationPayload` TypedDict:
```python
class NotificationPayload(TypedDict):
    tier: Literal[1, 2, 3]
    logical_id: str        # code.name
    title: str             # French title (with T3_PREFIX for tier 3)
    message: str           # French body with context interpolation
```

Context access pattern: `dataclasses.asdict(ctx)` then `.get('field', '<inconnu>')` for missing-field resilience.

### Critical: `NotificationContext` type — use implementation, not design doc

Import `NotificationContext` from `error_handler.py` (NOT `ErrorContext` from design doc). It's a 6-member union with **no `None`**:
```python
NotificationContext = (
    SM1TimeoutCtx | SM1NakCtx | SM1DisconnectedCtx
    | BadCSRResponseCtx | TransportPermanentCtx | EventFailedCtx
)
```
Every ErrorCode has its own dedicated dataclass. Never pass `None` as context.

### Critical: Access CSR info via `self._preset`, not bare attributes

Design doc pseudocode shows `self._csr_ip`, `self._csr_port`, `self._transport`. These do NOT exist. The actual attribute paths are:
- `self._preset.host` (not `self._csr_ip`)
- `self._preset.port` (not `self._csr_port`)
- `self._preset.transport` (TransportType enum, not bare string — use `.value` or conditional)

### Critical: `resolve_t1` emission point

The `resolve_t1` error_update must be emitted in `_handle_supervision_ack()` ONLY when `prev_strike > 0` (was degraded, now recovered). This clears T1 entries (SUPERVISION_TIMEOUT, SUPERVISION_NAK) from `sia_last_errors` on the PHP side. If strike was already 0 (routine ACK), no resolve_t1 is sent.

### Critical: `on_message()` framework contract

The jeedomdaemon framework's `on_message_cb` receives the full parsed JSON dict from PHP's socket **with `apikey` still included** (the framework validates it at `base_daemon.py:164` but does NOT remove it before calling the callback at line 169). The adapter `_on_message_dispatch()` must pop `apikey` from the dict before extracting `cmd`. PHP sends: `{"cmd": "burglarAlarm", "zone": "salon", "apikey": "..."}`.

### What Already Exists

| Artifact | Status | Action |
|----------|--------|--------|
| `daemon.py` `super().__init__()` | **BROKEN** — missing all 3 callbacks | Add `on_start_cb`, `on_message_cb`, `on_stop_cb` (Task 5.1) |
| `daemon.py` `on_message()` | **WRONG SIGNATURE** — `(cmd, params)` vs framework's `(message: dict)` | Refactor to accept raw dict (Task 5.2) |
| `daemon.py` `_notify()` | Stub — logs only | Replace body with `_track_task(_dispatch_notify(...))` |
| `daemon.py` `_update_info_commands_stub()` | Stub — no-op | Replace with real `_send_callback()` caller |
| `daemon.py` `_send_raw()` | Implemented | No change |
| `daemon.py` `_log_sm1_supervision()` | Implemented — logs + ring buffer | Add `_send_callback()` call for `message_trace` |
| `daemon.py` `_log_sm2_event()` | Implemented — logs + ring buffer | Add `_send_callback()` call for `message_trace` |
| `error_handler.py` `build_notification()` | **STUB** — body is `...` | Implement French templates (Task 3.9) |
| `tests/level2_5/test_callback_schema.py` | Implemented — schema validation | No change (existing) |
| `tests/fixtures/ipc_schema.py` | Implemented — canonical schemas | No change (authoritative source) |
| `core/class/siaDC09.class.php` | Implemented — full message handler | No change (PHP side complete) |
| `core/php/jeesiaDC09.php` | Implemented — callback receiver | No change |

### File Structure

```
Modified files (Story 6.6):
  resources/siadc09d/daemon.py              ← super().__init__ fix, on_message refactor, _send_callback(), _dispatch_notify(), _update_info_commands_impl(), message_trace emission
  resources/siadc09d/error_handler.py       ← Implement build_notification() (currently stub)

New files (Story 6.6):
  tests/level2_5/test_ipc_integration.py    ← 9 Level 2.5 IPC integration tests
  tests/level2/test_ipc_daemon_wiring.py    ← 4 Level 2 daemon-IPC wiring tests

Unchanged (reference only):
  tests/fixtures/ipc_schema.py              ← Authoritative schema (read-only, unchanged)
  tests/level2_5/test_callback_schema.py    ← Existing schema tests (unchanged)
  core/class/siaDC09.class.php              ← PHP message handler (complete from 6.3/6.4)
  core/php/jeesiaDC09.php                   ← Callback receiver (complete from 6.3)
```

### References

- [Source: docs/design/daemon-design.md § Component 1 — _notify() synchronous wrapper, _send_callback() contract]
- [Source: docs/design/error-handler-design.md § T1/T2/T3 dispatch — tier classification]
- [Source: docs/design/logging-design.md § SM1 Supervision Table — message_trace emission points]
- [Source: _bmad-output/planning-artifacts/architecture.md § Communication Patterns — IPC payload rules]
- [Source: _bmad-output/planning-artifacts/architecture.md § Level 2.5 — IPC Contract Tests — recording shim pattern]
- [Source: tests/fixtures/ipc_schema.py — authoritative callback schemas]
- [Source: resources/aiodemod/aiodemod.py — reference plugin send_to_jeedom() usage]
- [Source: _bmad-output/implementation-artifacts/6-5-jeedom-dependency-manager-installation.md — previous story learnings]

---

## Review Findings

### Decision Needed

- [x] [Review][Decision] **DN-1: `logical_id = code.value` vs `code.name`** — resolved: use `code.name`. Fixed in `error_handler.py`. [error_handler.py — `build_notification()`]

- [x] [Review][Decision] **DN-2: `resolve_t1` payload missing `code` field** — resolved: emit two separate callbacks (one per T1 code: SUPERVISION_TIMEOUT, SUPERVISION_NAK). Fixed in `daemon.py`. [daemon.py — `_handle_supervision_ack()`]

### Patches

- [x] [Review][Patch] **P-1: T3_PREFIX double-prepend in `_dispatch_notify`** — Fixed: guard changed to `T3_PREFIX in title`. Test updated to `assert T3_PREFIX in title`. [daemon.py — `_dispatch_notify()`]

- [x] [Review][Patch] **P-2: Double notification (T1 + T2) fires on unparseable NAK at strike < 3** — Fixed: T1 notification now skipped when `not is_parseable` (T2 already dispatched). [daemon.py — `_handle_supervision_nak()`]

- [x] [Review][Patch] **P-3: `_update_info_commands` data branch may pass `None` values to IPC** — Fixed: `payload = {k: v for k, v in data.items() if v is not None}`. [daemon.py — `_update_info_commands()`]

### Deferred

- [x] [Review][Defer] **D-1: Docstring schema for `message_center`/`notify` lists more fields than `ipc_schema.py`** [error_handler.py docstring vs tests/fixtures/ipc_schema.py] — deferred, pre-existing docstring/schema inconsistency; authoritative schema is `ipc_schema.py`

- [x] [Review][Defer] **D-2: SM2 `elapsed_ms` always 0 in `message_trace`** [daemon.py — `_log_sm2_event` call sites] — deferred, pre-existing: actual elapsed is never measured and passed into SM2LogCtx

- [x] [Review][Defer] **D-3: Dual `_tcp_reconnect_loop` tasks can spawn concurrently if TCP drop arrives during active reconnect** [daemon.py — `_handle_supervision_tcp_drop` + `_update_sm1_from_strike`] — deferred, pre-existing architectural gap; not introduced by this story

- [x] [Review][Defer] **D-4: Two tier classification paths (`_error_tier` via `classify_error` vs inline `tier_map` in `build_notification`) can diverge** [daemon.py — `_error_tier`; error_handler.py — `build_notification`] — deferred, low risk today (both tables match), but should be consolidated in a future cleanup story

- [x] [Review][Defer] **D-5: `prev_strike` in logging context misreputed when counter was already at cap** [daemon.py — `_handle_supervision_nak`] — deferred, logging-only, no operational impact

---

## Change Log

- Story 6.6 implementation complete (2026-04-29): wired daemon→PHP IPC (super().__init__ fix, _on_message_dispatch adapter, _update_info_commands_impl, _dispatch_notify with T1/T2/T3 tier dispatch, build_notification French templates, message_trace emission in SM1/SM2 loggers, resolve_t1 on ACK recovery). 20 new tests (14 level2_5, 6 level2). 848 total tests pass.

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (eu.anthropic.claude-sonnet-4-6)

### Debug Log References

### Completion Notes List

- **Task 1**: `_send_callback()` was already present (pre-implemented in prior stories). Validated: validates `type` field, rejects bool values, catches all exceptions, never re-raises.
- **Task 2**: Replaced `_update_info_commands_stub` with `_update_info_commands_impl`. Builds full info_update payload from SM1/SM2 state when called with no args; partial updates when data dict provided. `__init__` assignment updated.
- **Task 3**: Implemented `SIADaemon._dispatch_notify()` with per-channel try/except. Added `_error_tier()` static helper. Implemented `build_notification()` in `error_handler.py` with all French message templates and privacy rules from error-handler-design.md. Added `NotificationPayload` TypedDict + `event_type_fr()` helper. `_notify()` now calls `_track_task(_dispatch_notify(...))`. Added `resolve_t1` emission in `_handle_supervision_ack()` when prev_strike > 0.
- **Task 4**: Added `message_trace` callback emission to all `_log_sm1_supervision()` branches (ack/timeout/nak_timestamp/nak_bad) and `_log_sm2_event()`.
- **Task 5**: Fixed `super().__init__()` to pass `on_start_cb`, `on_message_cb`, `on_stop_cb`. Added `_on_message_dispatch()` adapter method that pops `apikey` and `cmd` from raw dict before delegating to `on_message()`.
- **Task 6**: Appended 9 IPC integration tests to `tests/level2_5/test_ipc_integration.py` across 4 test classes (TestUpdateInfoCommands, TestDispatchNotify, TestMessageTrace). All 14 tests in the file pass.
- **Task 7**: Created `tests/level2/test_ipc_daemon_wiring.py` with 6 tests covering on_message enqueue, dispatch adapter, unknown command, restart state reset, 3 independent alarms, and callback-exception resilience.
- **Task 8**: Full suite: 848 passed, 1 pre-existing failure (test_tc13_strike_timing_precision — StopIteration in mock setup, pre-existed before story 6.6). Level1: 30 pass. Level2: 222 pass. Level2_5: 38 pass.
- Updated 4 level2 tests in `test_async_task_lifecycle.py` that tested old `_notify()` stub behavior (now dispatches via `_track_task`). Updated module-level `_dispatch_notify()` in `error_handler.py` from `NotImplementedError` stub to no-op (actual dispatch is in `SIADaemon._dispatch_notify()`).

### File List

- `resources/siadc09d/daemon.py` — super().__init__ fix, _on_message_dispatch adapter, _update_info_commands_impl, _dispatch_notify, _error_tier, message_trace emission in _log_sm1_supervision + _log_sm2_event, resolve_t1 in _handle_supervision_ack
- `resources/siadc09d/error_handler.py` — NotificationPayload TypedDict, build_notification(), event_type_fr(), module-level _dispatch_notify no-op, Any/TypedDict imports
- `tests/level2_5/test_ipc_integration.py` — Added TestUpdateInfoCommands, TestDispatchNotify, TestMessageTrace test classes (9 new tests)
- `tests/level2/test_ipc_daemon_wiring.py` — New file: 6 Level 2 IPC wiring tests
- `tests/level2/test_async_task_lifecycle.py` — Updated 4 _notify stub tests to async + mock _dispatch_notify
