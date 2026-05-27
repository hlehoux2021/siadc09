# Story 7.1: Supervision Loop with Strike Management & INFO Updates

Status: done

## Story

As a daemon architect,
I want continuous supervision polling with strike escalation and real-time PHP INFO updates,
So that connection degradation is detected within 3 supervision cycles and displayed in Jeedom.

## Acceptance Criteria

1. **Supervision loop runs at `supervision_interval_s`** — Running the daemon with a mocked transport that always ACKs produces SUPERVISION queue items at `self._preset.supervision_interval_s` intervals, resulting in SM1=HEALTHY and `supervision_state=2` callbacks to PHP, with no T1 or T3 notifications fired.

2. **Strike counter escalation** — On each supervision timeout: `_strike_counter = min(_strike_counter + 1, 3)`. At strike=1: `_notify(SUPERVISION_TIMEOUT, SM1TimeoutCtx{...})` [T1]. At strike=2: no new notification. At strike=3: `_notify(SUPERVISION_DISCONNECTED, ...)` [T3, once, via `_sm1_t3_fired` flag]. Strike resets to 0 + `_sm1_t3_fired = False` on ACK.

3. **`supervision_state` / `supervision_label` INFO callbacks fire after every supervision cycle** — `_update_info_commands()` is called at the end of `_send_supervision()` (confirmed in code). Values: HEALTHY→state=2/label="OK", DEGRADED(1-2)→state=1/label=`SM1_DEGRADED_1_2_FR.format(N)`, DEGRADED(3)→state=0/label=`SM1_DEGRADED_3_FR`, TCP_RECONNECTING→state=0/label=`SM1_TCP_RECONNECTING_FR`, NO_NETWORK→state=0/label=`SM1_NO_NETWORK_FR`, STOPPED→state=0/label="ARRÊTÉ". All label values come from `messages.py` constants — verify against that file, do not hardcode string literals in tests.

4. **Ring buffer entries correct** — Routine ACKs: throttled (only 1 entry per 10-minute window). Strike escalations and state transitions: written immediately. Capped at 50 entries FIFO. `RingBuffer.push_supervision_entry(is_routine=True/False)` already exists.

5. **`on_start()` pushes INITIALIZING to PHP before any task starts** — `on_start()` currently does NOT send an INITIALIZING callback before launching tasks (see daemon.py:1881). This must be added: `await self._send_callback({"type": "info_update", "supervision_state": 1, "supervision_label": "DÉMARRAGE…"})` as the first await after resetting state — fail-fast if PHP unreachable (do not swallow). NOTE: event_state/event_label intentionally NOT included in this push (retained across restarts per design).

6. **`on_stop()` pushes STOPPED to PHP before tasks cancel** — `on_stop()` currently calls `_update_info_commands()` (full state push). This must be replaced with an explicit STOPPED push: `{"type": "info_update", "supervision_state": 0, "supervision_label": "ARRÊTÉ"}`. Best-effort: swallow exception (PHP may be stopping too). event_state/event_label NOT included.

7. **Enhanced `deamon_info()` with per-key config validation** — Current `deamon_info()` only checks for equipment existence and `csr_ip`. Must add guards for: wizard_step < 4, account_number format (3–16 hex chars), encryption_key when encryption_enabled, notify_cmd_id. Each guard returns a French `launchable_message` referencing the wizard step to fix. See supervision-design.md Task C.2 for the exact implementation.

8. **`cron5()` freshness check** — Add `cron5()` static method that calls `_checkSupervisionFreshness($eqLogic)` when daemon state is 'ok'. Must NOT attempt to restart the daemon (Jeedom handles this). See supervision-design.md Task C.3.

9. **`_checkSupervisionFreshness()` zombie detection** — Detects zombie daemon (PID alive but asyncio loop frozen) via `supervision_state.collectDate` staleness. Threshold: `3 × supervision_interval` seconds. Fires emergency notification via: (1) `notify_cmd_id` command, (2) Jeedom `message::add()`. Rate-limited to 1 alert per 30 minutes via `_freshness_alert_ts` plugin-level config key. See supervision-design.md Task C.4.

10. **All existing tests pass** — No regressions in Level 1, Level 2, Level 2.5 suites (848 existing tests as of 6.6).

11. **New tests** — Level 2 tests in `tests/level2/test_supervision_loop_integration.py` use mocked transport (no subprocess). Level 3 end-to-end tests using the real `csr_simulator` subprocess are deferred to Story 7.3. Tests required:
    - Healthy supervision (mocked ACK → HEALTHY → `supervision_state=2` callback)
    - Strike=1 timeout → DEGRADED, T1 (SUPERVISION_TIMEOUT) fired exactly once, `supervision_state=1`
    - Strike=2 timeout → still DEGRADED, NO second T1 notification
    - Strike=3 timeout → T3 (SUPERVISION_DISCONNECTED) fired exactly once, `supervision_state=0`
    - ACK after strike=3 → strike reset to 0, `_sm1_t3_fired=False`, `supervision_state=2`
    - TCP drop → immediate TCP_RECONNECTING (no strike increment, `supervision_state=0`)
    - NAK with parseable timestamp → strike++, T1 (SUPERVISION_NAK) fired, ring buffer entry written
    - NAK with unparseable data → strike++, T2 (BAD_CSR_RESPONSE) fired, ring buffer entry written
    - `on_start()` INITIALIZING push is the first `send_to_jeedom()` call (captured before any queue tasks run)
    - `on_stop()` STOPPED push emitted (state=0, label="ARRÊTÉ"), event_state/label absent from payload

## Tasks / Subtasks

### Task 1: Fix `on_start()` INITIALIZING push (AC5)

- [x] **1.1** In `daemon.py` `on_start()` (line ~1881): after SM state resets, before `_track_task()` calls, add:
  ```python
  await self.send_to_jeedom({
      "type": "info_update",
      "supervision_state": 1,
      "supervision_label": "DÉMARRAGE…",
  })
  ```
  Call `send_to_jeedom()` directly — NOT `_send_callback()`. `_send_callback()` swallows all exceptions, which would silently defeat the fail-fast guarantee. A bare `send_to_jeedom()` exception propagates, killing `on_start()`, and Jeedom's watchdog restarts the daemon.
- [x] **1.2** Do NOT wrap in try/except — fail-fast is intentional (see supervision-design.md Task A.1 rationale)
- [x] **1.3** Do NOT include `event_state`/`event_label` in this push — they are retained across restarts
- [x] **1.4** Audit all existing Level 2 tests that call `on_start()` — they now require `send_to_jeedom` to be mocked (e.g., `daemon.send_to_jeedom = AsyncMock()`), otherwise they will raise. Update affected tests before running the suite.

### Task 2: Fix `on_stop()` STOPPED push (AC6)

- [x] **2.1** In `daemon.py` `on_stop()` (line ~1941): replace Step 1 (`_update_info_commands()`) with explicit STOPPED push:
  ```python
  try:
      await self._send_callback({
          "type": "info_update",
          "supervision_state": 0,
          "supervision_label": "ARRÊTÉ",
      })
  except Exception as e:
      self._logger.warning(f"on_stop: STOPPED push failed: {e!r}")
  ```
- [x] **2.2** Do NOT include `event_state`/`event_label` — they persist across restarts

### Task 3: Enhanced `deamon_info()` (AC7)

- [x] **3.1** In `core/class/siaDC09.class.php` `deamon_info()` (line ~60): replace current minimal guard with full 6-guard implementation from supervision-design.md Task C.2:
  - Guard 1: equipment exists
  - Guard 2: wizard_step >= 4 (prevents auto-restart during wizard)
  - Guard 3: csr_ip non-empty
  - Guard 4: account_number non-empty AND matches `/^[0-9A-Fa-f]{3,16}$/`
  - Guard 5: encryption_key non-empty if encryption_enabled
  - Guard 6: notify_cmd_id non-empty
- [x] **3.2** Each guard: set `$return['launchable'] = 'nok'` + French `launchable_message` with wizard step reference, then `return $return`. Copy guard messages verbatim from supervision-design.md Task C.2 — they reference wizard step numbers that users see. The full implementation including the `$return['log']` key (must be `__CLASS__ . '_daemon'`) is in the design doc; copy it, don't paraphrase.

### Task 4: Add `cron5()` (AC8)

- [x] **4.1** Add `public static function cron5(): void` to `siaDC09.class.php`
- [x] **4.2** Implementation per supervision-design.md Task C.3: get equipment, check enabled, call `_checkSupervisionFreshness()` only if `deamon_info()['state'] == 'ok'`. No restart logic.

### Task 5: Add `_checkSupervisionFreshness()` (AC9)

- [x] **5.1** Add `private static function _checkSupervisionFreshness($eqLogic): void` to `siaDC09.class.php`
- [x] **5.2** Read `supervision_interval` from eqLogic config (default 60). Threshold = interval × 3. Rate limit = 30 min.
- [x] **5.3** Get `supervision_state` cmd via `$eqLogic->getCmd('info', 'supervision_state')`. Return early if null or collectDate empty.
- [x] **5.4** Staleness check: `time() - strtotime($collectDate) > $staleThreshold`
- [x] **5.5** On recovery (staleness OK): clear `_freshness_alert_ts` plugin config key (do NOT call eqLogic save)
- [x] **5.6** On stale: check rate limit via `config::byKey('_freshness_alert_ts', __CLASS__, 0)`. If within 30 min, return.
- [x] **5.7** Fire both notification channels: (1) `log::add(__CLASS__, 'error', $msg)` + `message::add(__CLASS__, $msg)`, (2) `$notifyCmd->execCmd(['title' => ..., 'message' => $msg])` for `notify_cmd_id`. Wrap execCmd in try/catch.
- [x] **5.8** Save `_freshness_alert_ts` via `config::save('_freshness_alert_ts', time(), __CLASS__)` — NOT via eqLogic (prevents postSave() trigger)

### Task 6: PHP unit tests for cron5() and _checkSupervisionFreshness() (AC8, AC9)

PHP does not have a pytest harness in this project — these are documented manual test cases that must be verified by the dev agent via `grep` and code inspection, or using any existing PHP test infrastructure if present.

- [x] **6.php.1** `cron5()` skips freshness check when daemon state is 'nok' — mock `deamon_info()` to return `['state' => 'nok']`, verify `_checkSupervisionFreshness()` is never called.
- [x] **6.php.2** `cron5()` skips when equipment missing or disabled — verify early return guards.
- [x] **6.php.3** `_checkSupervisionFreshness()` returns early when `supervision_state` command is null (plugin just installed, no commands yet).
- [x] **6.php.4** `_checkSupervisionFreshness()` returns early when `collectDate` is empty.
- [x] **6.php.5** Rate-limit enforced — `_freshness_alert_ts` set within 30 min, verify no second notification fired.
- [x] **6.php.6** Recovery clears `_freshness_alert_ts` — staleness recovers (within threshold), verify `config::save('_freshness_alert_ts', 0, __CLASS__)` called.
- [x] **6.php.7** `notify_cmd_id == 0` — verify `execCmd()` is NOT called (guard in Task 5.7 for `$notifyCmdId > 0`).

### Task 7: Supervision loop integration tests (AC11)

- [x] **7.1** Create `tests/level2/test_supervision_loop_integration.py`. All tests use mocked transport — call handler methods directly (`_handle_supervision_ack`, `_handle_supervision_timeout`, `_handle_supervision_nak`) or mock `_send_raw`. Level 3 csr_simulator tests are Story 7.3's scope.
- [x] **7.2** Test: healthy ACK → `_strike_counter==0`, SM1==HEALTHY, `info_update` callback has `supervision_state==2`. No T1/T3 dispatched.
- [x] **7.3** Test: `_handle_supervision_timeout()` once → `_strike_counter==1`, DEGRADED, exactly one `_notify` call for SUPERVISION_TIMEOUT.
- [x] **7.4** Test: `_handle_supervision_timeout()` twice → `_strike_counter==2`, still DEGRADED, still only one total SUPERVISION_TIMEOUT notification (no T1 at strike=2).
- [x] **7.5** Test: `_handle_supervision_timeout()` three times → `_strike_counter==3`, T3 (SUPERVISION_DISCONNECTED) fired exactly once, `supervision_state==0`.
- [x] **7.6** Test: ACK after strike=3 → `_strike_counter==0`, `_sm1_t3_fired==False`, `supervision_state==2`.
- [x] **7.7** Test: T3 fires only once per escalation — after strike=3→ACK→strike=3 again, T3 fires a second time (not suppressed across escalations).
- [x] **7.8** Test: `_handle_supervision_tcp_drop()` → SM1==TCP_RECONNECTING immediately, no strike increment, `supervision_state==0`. Verify `_tcp_reconnect_loop` task scheduled (check `_tasks`).
- [x] **7.9** Test: NAK with parseable timestamp → `_notify` called with SUPERVISION_NAK (not BAD_CSR_RESPONSE); ring buffer entry present with `is_routine=False`.
- [x] **7.10** Test: NAK with unparseable/empty bytes → `_notify` called with BAD_CSR_RESPONSE (T2, not T1); no duplicate SUPERVISION_NAK call.
- [x] **7.11** Test: `on_start()` INITIALIZING push is the first `send_to_jeedom` call — mock `send_to_jeedom`, call `on_start()`, verify first call has `supervision_state==1` and `supervision_label=="DÉMARRAGE…"`, and NO `event_state`/`event_label` keys in payload.
- [x] **7.12** Test: `on_stop()` STOPPED push emitted — mock `send_to_jeedom`/`_send_callback`, call `on_stop()`, verify a payload with `supervision_state==0`, `supervision_label=="ARRÊTÉ"`, and NO `event_state`/`event_label` keys.
- [x] **7.13** Run full suite: `python3 -m pytest tests/ -q --tb=short` — no regressions from 848 baseline.

## Dev Notes

### What Already Exists (DO NOT RE-IMPLEMENT)

The supervision loop and SM1 state machine are **fully implemented** in `daemon.py`. Story 7.1's Python work is narrow:

| Method | File | Lines | Status |
|--------|------|-------|--------|
| `_supervision_loop()` | daemon.py | 1807–1827 | ✅ Complete |
| `_send_supervision()` | daemon.py | 766–836 | ✅ Complete |
| `_handle_supervision_ack()` | daemon.py | 838–886 | ✅ Complete |
| `_handle_supervision_nak()` | daemon.py | 888–953 | ✅ Complete |
| `_handle_supervision_timeout()` | daemon.py | 955–997 | ✅ Complete |
| `_update_sm1_from_strike()` | daemon.py | 714–764 | ✅ Complete |
| `_supervision_value()` | daemon.py | 653–679 | ✅ Complete |
| `_supervision_label()` | daemon.py | 680–712 | ✅ Complete |
| `_log_sm1_supervision()` | daemon.py | 1098–1238 | ✅ Complete |
| `on_start()` | daemon.py | 1881–1937 | ⚠️ MISSING INITIALIZING push |
| `on_stop()` | daemon.py | 1941–1992 | ⚠️ Uses full `_update_info_commands()` instead of explicit STOPPED push |
| `deamon_info()` | siaDC09.class.php | 60–94 | ⚠️ Minimal guards only — needs wizard_step, account_number, encryption_key, notify_cmd_id guards |
| `cron5()` | siaDC09.class.php | — | ❌ Missing entirely |
| `_checkSupervisionFreshness()` | siaDC09.class.php | — | ❌ Missing entirely |
| `_getAutoEquipmentSafe()` | siaDC09.class.php | 30 | ✅ Already present |

### Key Design Facts

**on_start() INITIALIZING push is fail-fast by design — use `send_to_jeedom()` directly:**
If PHP is unreachable at startup, the exception must propagate and kill `on_start()`. Jeedom's watchdog then restarts the daemon. Do NOT use `_send_callback()` here — it swallows all exceptions internally and would silently defeat this guarantee. Call `await self.send_to_jeedom({...})` with no try/except wrapper.

**Existing Level 2 tests that call `on_start()` will break after Task 1:**
Any test that constructs a `SIADaemon` and calls `await daemon.on_start()` without mocking `send_to_jeedom` will now raise (a real HTTP call will be attempted). Audit `tests/level2/` for `on_start()` calls and add `daemon.send_to_jeedom = AsyncMock()` to their setup. Check at minimum: `test_daemon_integration.py`, `test_queue_consumer_integration.py`, `test_supervision_queue_integration.py`, `test_sm1_extended_suite.py`, `test_sm2_alarm_event_suite.py`.

**on_stop() STOPPED push is best-effort:**
PHP may itself be shutting down during a system reboot. Swallow exceptions — shutdown must never block.

**event_state/event_label intentionally NOT reset on daemon start/stop:**
The INFO commands retain their values across daemon restarts. The combination of `supervision_state=0` (stopped) + `event_state=3` (in-progress) conveys "daemon stopped during alarm-in-flight". See daemon.py on_start() comment at line 1907: "NOTE: event_state and event_label intentionally NOT reset here."

**Ring buffer throttle (already implemented in RingBuffer):**
`RingBuffer.push_supervision_entry(is_routine=True)` applies the 10-minute throttle for routine ACKs. `is_routine=False` writes immediately. The first-ever routine entry is always written immediately. This logic is in `ring_buffer.py` — do not duplicate.

**`_sm1_t3_fired` reset rules (must not break):**
Reset in two places (already correct in daemon.py):
1. `_handle_supervision_ack()` resets `_sm1_t3_fired = False` when strike→0 (line 863)
2. `_tcp_reconnect_loop()` on success resets both `_strike_counter = 0` and `_sm1_t3_fired = False` (line 1068–1069)

**SUPERVISION_TIMEOUT T1 fires at strike=1 ONLY:**
From `_handle_supervision_timeout()` (line 980): `if self._strike_counter == 1`. Strike=2 adds no new T1. Strike=3 fires T3 via `_update_sm1_from_strike()`. Do NOT change this logic.

**`deamon_info()` PHP config key name for notify:**
Current code at line 147 uses `'sia_notify_cmd_id'` — use same key in new guard (Guard 6). Do NOT change the key name.

**`deamon_info()` log key must be `__CLASS__ . '_daemon'`:**
Not `__CLASS__` (PHP log). The `_daemon` suffix points to the Python daemon's log output (in Jeedom: "siaDC09_daemon"). See supervision-design.md Task C.2 `$return['log']` line.

**cron5() must NOT restart the daemon:**
Jeedom's runtime watchdog (runs every minute) handles daemon crash-and-restart. Duplicating restart logic in `cron5()` would interfere with Jeedom's failure counter. cron5() only calls `_checkSupervisionFreshness()`.

**`_freshness_alert_ts` storage location:**
Plugin-level `config::save('_freshness_alert_ts', time(), __CLASS__)` — NOT eqLogic config. Using eqLogic would trigger `postSave()` on every set/clear. See supervision-design.md rationale.

**TOCTOU gap in zombie detection — acceptable by design, do NOT "fix" it:**
`_checkSupervisionFreshness()` reads `collectDate` (the check), then dispatches an emergency notification (the use). Between those two moments, the daemon could have recovered — e.g., an asyncio backlog cleared — making the alert a false positive. This race cannot be eliminated (re-reading `collectDate` immediately before notifying just creates a tighter race, not zero race). The design intentionally accepts it: the 30-minute rate limit bounds false-alarm frequency to at most 48/day, and a false positive is far less harmful than a missed zombie alert. Do not add a second staleness read, a delay, or any synchronization — it adds complexity for zero benefit.

### PHP `deamon_info()` — Current vs Required

Current (minimal):
```php
// Guard 1: equipment exists
// Guard 3: csr_ip non-empty → launchable='ok'
```

Required (full — per supervision-design.md Task C.2):
```php
// Guard 1: equipment exists
// Guard 2: wizard_step >= 4 (prevents Jeedom watchdog from restarting mid-wizard)
// Guard 3: csr_ip non-empty
// Guard 4: account_number non-empty + regex /^[0-9A-Fa-f]{3,16}$/
// Guard 5: encryption_key non-empty if encryption_enabled
// Guard 6: sia_notify_cmd_id non-empty
```

The full guard implementation with French messages is in supervision-design.md Task C.2. Copy it verbatim — the guard order, messages, and wizard step references are deliberate.

### PHP `deamon_start()` reads `deamon_info()`

`deamon_start()` at line 98 calls `deamon_info()` before launching. Adding guards to `deamon_info()` automatically protects `deamon_start()` from launching with incomplete config.

### Test Patterns from Story 6.6

From `tests/level2_5/test_ipc_integration.py` — recording shim pattern for PHP callback capture:
```python
captured = []
daemon._send_callback = AsyncMock(side_effect=lambda p: captured.append(p))
```
Use the same pattern for supervision loop tests to capture `info_update` callbacks.

For strike tests, use `_handle_supervision_timeout()` directly (no need to mock network):
```python
await daemon._handle_supervision_timeout(elapsed_ms=30000.0)
assert daemon._strike_counter == 1
```

### File Locations

```
Modified files (Story 7.1):
  resources/siadc09d/daemon.py        ← on_start() INITIALIZING push (send_to_jeedom direct) + on_stop() STOPPED push
  core/class/siaDC09.class.php        ← deamon_info() 6-guard expansion + cron5() + _checkSupervisionFreshness()
  tests/level2/*                      ← mock send_to_jeedom in any test that calls on_start()

New files (Story 7.1):
  tests/level2/test_supervision_loop_integration.py  ← 13 integration tests (Tasks 7.1–7.12)
```

### Deferred Work from Story 6.6 (not in scope for 7.1)

- **D-3**: Dual `_tcp_reconnect_loop` tasks on concurrent TCP drop — pre-existing, document in completion notes if observed during test
- **D-4**: Two tier classification paths in `_error_tier` vs `build_notification` — pre-existing, not in scope

### References

- [Source: docs/design/supervision-design.md — Task A.1 (on_start), A.2 (on_stop), B.1 (_update_sm1_from_strike), B.2 (_send_supervision), C.2 (deamon_info), C.3 (cron5), C.4 (_checkSupervisionFreshness)]
- [Source: docs/design/error-handler-design.md — T1/T2/T3 tiers, SUPERVISION_TIMEOUT, SUPERVISION_DISCONNECTED]
- [Source: docs/design/logging-design.md — SM1 Supervision logging table, ring buffer throttle]
- [Source: resources/siadc09d/daemon.py — full SM1 implementation (lines 714–1238)]
- [Source: core/class/siaDC09.class.php:60 — current deamon_info() to replace]
- [Source: _bmad-output/implementation-artifacts/6-6-php-core-integration-ipc-tests.md — recording shim test pattern, 848 test baseline]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Pre-existing test failure: `test_tc13_strike_timing_precision` — `time.monotonic` mock provides only 4 values but 6 are needed (3 calls × 2 reads each). Confirmed failing on `master` before any Story 7.1 changes.

### Completion Notes List

- Task 1: Added `await self.send_to_jeedom(...)` INITIALIZING push in `on_start()` after SM state resets, before transport creation. Uses `SM1_INITIALIZING_FR` constant directly.
- Task 1.4: Updated 4 Level 2 test files (`test_async_task_lifecycle`, `test_daemon_integration`, `test_sia_transport_daemon_wiring`, `test_ipc_daemon_wiring`) to mock `send_to_jeedom` in fixtures. Fixed `test_send_callback_does_not_block_queue_consumer` to allow initial INITIALIZING push to succeed then switch to raising.
- Task 2: Replaced `_update_info_commands()` call in `on_stop()` Step 1 with explicit `_send_callback({"type": "info_update", "supervision_state": 0, "supervision_label": "ARRÊTÉ"})`. Best-effort with warning log on failure. Updated existing `test_on_stop_swallows_info_push_failure` test to match new behavior.
- Task 3: Replaced minimal `deamon_info()` with full 6-guard implementation per supervision-design.md Task C.2. Added `auto` key. Guards: equipment exists, wizard_step >= 4, csr_ip, account_number format, encryption_key if enabled, sia_notify_cmd_id.
- Task 4: Added `cron5()` per design — calls `_checkSupervisionFreshness()` when daemon appears running, no restart logic.
- Task 5: Added `_checkSupervisionFreshness()` with zombie detection via `collectDate` staleness, 30-min rate limit via plugin-level `_freshness_alert_ts` config key, dual notification channels (message center + notify_cmd_id).
- Task 6: All 7 PHP test cases verified via code inspection — all guard paths confirmed correct.
- Task 7: Created `tests/level2/test_supervision_loop_integration.py` with 11 tests covering AC11 (TC7.2–TC7.12). All pass.
- Full suite: 859 passed, 1 pre-existing failure (test_tc13, unrelated to this story).

### Change Log

- 2026-05-04: Story 7.1 implementation complete — all 11 ACs satisfied, all tasks/subtasks checked.

### File List

Modified:
- resources/siadc09d/daemon.py (on_start INITIALIZING push, on_stop STOPPED push)
- core/class/siaDC09.class.php (deamon_info 6 guards, cron5, _checkSupervisionFreshness)
- tests/level2/test_async_task_lifecycle.py (mock send_to_jeedom + fix on_stop test)
- tests/level2/test_daemon_integration.py (mock send_to_jeedom)
- tests/level2/test_sia_transport_daemon_wiring.py (mock send_to_jeedom)
- tests/level2/test_ipc_daemon_wiring.py (mock send_to_jeedom + fix callback test)

New:
- tests/level2/test_supervision_loop_integration.py (11 integration tests)

### Review Findings

- [x] [Review][Decision] `logical_id` format reverted to `.value` (lowercase) — matches error-handler-design.md; daemon.py resolve_t1 callbacks also updated to `.value`
- [x] [Review][Decision] CSR port, transport, and supervision_interval guards added (Guard 3b, 3c, 3d) to `deamon_info()`
- [x] [Review][Patch] `resolve_t1` documented as idempotent — PHP handler no-op if code not in last_errors [daemon.py:882]
- [x] [Review][Patch] `strtotime()` return value checked for `false` before computing `$staleSince` [siaDC09.class.php]
- [x] [Review][Patch] Dead `except Exception` branch removed from `on_stop()` STOPPED push [daemon.py]
- [x] [Review][Patch] `supervision_interval <= 0` blocked at `deamon_info()` Guard 3d — daemon cannot launch with invalid interval [siaDC09.class.php]
- [x] [Review][Defer] `_update_info_commands` None-filter changes IPC contract — no current caller passes intentional None, but semantics changed [daemon.py:450] — deferred, out-of-scope enhancement
