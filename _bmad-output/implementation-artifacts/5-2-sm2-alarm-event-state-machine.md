# Story 5.2: SM2 Alarm Event State Machine

**Status:** in-progress

**Created:** 2026-04-10

**Last Updated:** 2026-04-13

**Current Session:** Session 1 of 2 (Foundation work complete, core implementation deferred to Session 2)

**Checkpoint:** Commit 8e3b1ce - Solid foundation with skeleton structures

---

## Story

As a daemon architect,

I want SM2 to track alarm event delivery status,

So that the daemon and PHP know whether alarms reached the CSR.

---

## Acceptance Criteria

1. **SM2 State Machine Implementation** — SM2 has state machine (IDLE startup-only → PENDING ↔ CONFIRMED/FAILED direct transitions) with documented transitions (ref: daemon-design.md § SM2 — Alarm Event State)

2. **Alarm Event Lifecycle** — Alarm events trigger from PriorityQueue dequeue, transition through PENDING with configurable retries, result in CONFIRMED (ACK) or FAILED (NAK/timeout/NO_NETWORK)

3. **SM2 INFO Command Mapping** — SM2 state maps to `event_state` numeric (0=no alarm, 1=confirmed, 2=failed, 3=pending) and `event_label` string (French), persisted across daemon restarts

4. **NAK Dispatch Logic** — Parseable NAK (timestamp extraction) → strike++; undecodable/bad NAK → strike++ + `_notify(ErrorCode.BAD_CSR_RESPONSE)` (T2); any NAK in event send → `SM2State.FAILED`

5. **Network Loss Handling** — When SM1 transitions to NO_NETWORK: any SM2=PENDING events fail immediately with `_notify(ErrorCode.EVENT_FAILED, EventFailedCtx)` (T3), daemon stops

6. **Retry Mechanism** — `_send_with_retry()` implements exponential backoff or fixed intervals (TBD with dev), configurable max retries per preset, logged transitions include attempt count

7. **Persistence Across Restarts** — `event_state` and `event_label` persist in equipment command.execAttr (PHP manages storage), daemon reads on startup and restores state (NOT reset to IDLE)

8. **Logging Output** — All SM2 transitions logged with French INFO lines (from messages.py) and English DEBUG lines (technical); ring buffer entries for state changes and failures

9. **Tests Comprehensive** — 7–10 test cases covering happy path (ACK), NAK handling, persistence, multiple alarms, timeout with retries, no-IDLE re-entry, zone extraction from alarm command

---

## Tasks / Subtasks

### Task 1: Define SM2 state machine class structure (5.2.1)

- [x] 1.1 Define `SM2State` enum with values: IDLE, PENDING, CONFIRMED, FAILED
  - [x] 1.1.1 Use `from enum import Enum` for type safety
  - [x] 1.1.2 Document state transitions (IDLE→PENDING; PENDING→CONFIRMED|FAILED; CONFIRMED/FAILED→PENDING direct, no IDLE re-entry)

- [x] 1.2 Define `SM2LogCtx` TypedDict for logging context
  - [x] 1.2.1 `SM2LogCtx`: zone (str | None), sia_code (str), attempt (int), elapsed (float), state_change (bool)

- [x] 1.3 Ensure all type hints match error-handler-design.md `EventFailedCtx` signature
  - [x] 1.3.1 EventFailedCtx imported from error_handler.py
  - [x] 1.3.2 All parameters type-hinted, no bare `dict` or `str`

**Acceptance Criteria mapping:** 1

---

### Task 2: Implement SM2 state machine instance variables and initialization (5.2.2)

- [x] 2.1 Initialize SM2 instance variables in daemon `__init__()`
  - [x] 2.1.1 `_sm2_state: SM2State` = IDLE
  - [x] 2.1.2 `_event_state: int` = 0 (persisted from config.execAttr on startup)
  - [x] 2.1.3 `_event_label: str` = "Inactif" (persisted from config.execAttr on startup)
  - [x] 2.1.4 `_event_sia_code: str | None` = None (latest event code: 'BA'|'FA'|'PA')
  - [x] 2.1.5 `_event_zone: str | None` = None (latest zone from command #zone# tag)
  - [x] 2.1.6 `_event_attempt_count: int` = 0 (track total send attempts for current event)

- [x] 2.2 Implement `_event_state_from_sm2()` helper
  - [x] 2.2.1 Returns numeric value for `event_state` INFO command (0, 1, 2, or 3)
  - [x] 2.2.2 Logic: IDLE→0, PENDING→3, CONFIRMED→1, FAILED→2

- [x] 2.3 Implement `_event_label_from_sm2()` helper
  - [x] 2.3.1 Returns French-language string for `event_label` INFO command
  - [x] 2.3.2 IDLE→"Inactif", PENDING→"En cours", CONFIRMED→"Confirmé", FAILED→"Échoué"

- [ ] 2.4 Restore event state from config on daemon startup
  - [ ] 2.4.1 In `on_start()` or `__init__()`, read `command.execAttr['event_state']` (defaults to 0)
  - [ ] 2.4.2 Translate numeric event_state back to SM2 state (inverse of 2.2.2 logic)
  - [ ] 2.4.3 Read `command.execAttr['event_label']` and `_event_sia_code` (if available)
  - [ ] 2.4.4 Do NOT reset to IDLE or 0 on restart — retain previous state

**Acceptance Criteria mapping:** 3, 7

---

### Task 3: Implement alarm dequeue and send retry logic (5.2.3)

- [ ] 3.1 Create `_send_with_retry()` async method
  - [ ] 3.1.1 Signature: `async def _send_with_retry(self, event_item: EventItem, max_retries: int = 3) -> SM2State`
  - [ ] 3.1.2 Parameter: EventItem contains alarm details (zone, sia_code, timestamp, etc.)
  - [ ] 3.1.3 Returns final SM2 state: CONFIRMED or FAILED

- [ ] 3.2 Implement retry loop in `_send_with_retry()`
  - [ ] 3.2.1 Initialize `_sm2_state = PENDING`, `_event_attempt_count = 0`
  - [ ] 3.2.2 For each retry (0 to max_retries):
    - [ ] 3.2.2a Increment `_event_attempt_count`
    - [ ] 3.2.2b Build SIA-DCS message with current seq, zone, timestamp
    - [ ] 3.2.2c Call `_send_raw()` with timeout (configurable, default 10s)
    - [ ] 3.2.2d On SIATransportError: log, sleep(backoff_interval), continue retry
    - [ ] 3.2.2e On ACK: set `_sm2_state = CONFIRMED`, break
    - [ ] 3.2.2f On NAK (parseable timestamp): log with timestamp, `_update_sm1_from_nak()` (delegate to SM1), but SM2 FAILED (v1.0 no auto-heal)
    - [ ] 3.2.2g On NAK (undecodable): `_notify(ErrorCode.BAD_CSR_RESPONSE, ...)` (T2), SM2 FAILED, break

- [ ] 3.3 Handle max retries exhausted
  - [ ] 3.3.1 When retries exhausted: set `_sm2_state = FAILED`
  - [ ] 3.3.2 Call `_notify(ErrorCode.EVENT_FAILED, EventFailedCtx(zone=..., sia_code=..., attempts=_event_attempt_count))` (T3)
  - [ ] 3.3.3 Log transition with final attempt count

- [ ] 3.4 Update INFO commands after each transition
  - [ ] 3.4.1 After state change: call `_update_info_commands({'event_state': new_value, 'event_label': new_label})`
  - [ ] 3.4.2 Persist state to config.execAttr for daemon restart recovery

**Acceptance Criteria mapping:** 2, 4, 6

---

### Task 4: Integrate SM2 with PriorityQueue consumer (5.2.4)

- [ ] 4.1 Modify `_queue_consumer()` to handle EVENT items
  - [ ] 4.1.1 On dequeue of EVENT item: check `_sm1_state` before dispatch
  - [ ] 4.1.2 If SM1=NO_NETWORK: immediately fail event → `SM2State.FAILED`, `_notify(ErrorCode.EVENT_FAILED, ...)` (T3), skip send
  - [ ] 4.1.3 Otherwise: call `_send_with_retry()` and await result
  - [ ] 4.1.4 After `_send_with_retry()` completes: `_sm2_state` is CONFIRMED or FAILED

- [ ] 4.2 Prevent IDLE re-entry
  - [ ] 4.2.1 In `_queue_consumer()`, unconditionally set `_sm2_state = PENDING` at dequeue time (never IDLE)
  - [ ] 4.2.2 After CONFIRMED or FAILED, next alarm dequeue goes directly to PENDING (no IDLE step)

- [ ] 4.3 Multiple alarm scenario
  - [ ] 4.3.1 While SM2=PENDING, new alarm arrives in queue
  - [ ] 4.3.2 New alarm stays queued at IDLE state (not consumed yet)
  - [ ] 4.3.3 When first alarm completes (CONFIRMED/FAILED), `_queue_consumer()` dequeues next and sets SM2=PENDING

**Acceptance Criteria mapping:** 2

---

### Task 5: Implement NAK timestamp dispatch and SM1 strike updates (5.2.5)

- [ ] 5.1 Parse NAK responses in `_send_raw()` return
  - [ ] 5.1.1 `_send_raw()` returns dict with `status` (ACK/NAK/timeout) and `raw_nak` (bytes if NAK)
  - [ ] 5.1.2 If NAK: try `parse_nak_timestamp(raw_nak) -> datetime` (may raise ValueError)

- [ ] 5.2 Handle parseable NAK (timestamp valid or extractable)
  - [ ] 5.2.1 Call `_update_sm1_from_nak(parsed_ts=...)` or similar SM1 handler
  - [ ] 5.2.2 SM1 increments strike (delegates NAK to SM1 retry logic)
  - [ ] 5.2.3 SM2 **always** transitions to FAILED (v1.0 no auto-heal)
  - [ ] 5.2.4 Fire `_notify(ErrorCode.SUPERVISION_NAK, ...)` (T1, via SM1 handler)

- [ ] 5.3 Handle undecodable NAK
  - [ ] 5.3.1 ValueError from `parse_nak_timestamp()` → undecodable
  - [ ] 5.3.2 `_notify(ErrorCode.BAD_CSR_RESPONSE, SM1NakCtx(...))` (T2)
  - [ ] 5.3.3 SM2 FAILED, stop retrying

**Acceptance Criteria mapping:** 4

---

### Task 6: Network loss and daemon stop handling (5.2.6)

- [ ] 6.1 When SM1 transitions to NO_NETWORK
  - [ ] 6.1.1 If SM2=PENDING: immediately transition to FAILED
  - [ ] 6.1.2 Fire `_notify(ErrorCode.EVENT_FAILED, EventFailedCtx(...))` (T3)
  - [ ] 6.1.3 Ring buffer entry: "Alarme {type} non transmise — réseau inaccessible (zone: {zone})"

- [ ] 6.2 Daemon stop behavior
  - [ ] 6.2.1 All queued events (both SUPERVISION and EVENT) are drained
  - [ ] 6.2.2 If any EVENT=PENDING when stop() called: FAILED + notification
  - [ ] 6.2.3 `_sm2_state` and `event_state` persisted to config.execAttr before stop completes

**Acceptance Criteria mapping:** 5, 7

---

### Task 7: Logging integration (5.2.7)

- [ ] 7.1 Implement `_log_sm2_event()` helper
  - [ ] 7.1.1 Signature: `def _log_sm2_event(self, transition: str, ctx: SM2LogCtx | None = None) -> None`
  - [ ] 7.1.2 Writes French INFO line (from messages.py) + English DEBUG line
  - [ ] 7.1.3 Pushes to ring buffer (immediate for state changes/failures, not throttled)

- [ ] 7.2 Log all SM2 transitions
  - [ ] 7.2.1 IDLE (startup): DEBUG only, no INFO
  - [ ] 7.2.2 PENDING (alarm trigger): INFO "Alarme {type} reçue (zone: {zone}) — transmission en cours"
  - [ ] 7.2.3 CONFIRMED (ACK): INFO "Centrale confirmée — alarme {type} transmise (zone: {zone})"
  - [ ] 7.2.4 FAILED (NAK): INFO "Réponse invalide de la centrale — alarme {type} non transmise (zone: {zone})"
  - [ ] 7.2.5 FAILED (timeout×N): INFO "Pas de réponse de la centrale — tentative {attempt}/{max}"
  - [ ] 7.2.6 FAILED (NO_NETWORK): INFO "Alarme {type} non transmise — réseau inaccessible (zone: {zone})"

- [ ] 7.3 Ensure `_log_sm2_event()` is the ONLY place SM2 logging happens (no inline `self._logger` calls in SM2 code)

**Acceptance Criteria mapping:** 8

---

### Task 8: Comprehensive testing (5.2.8)

- [ ] 8.1 Create test file: `tests/level2/test_sm2_alarm_event_suite.py`
  - [ ] 8.1.1 Mock CSR simulator with ACK/NAK/timeout scenarios
  - [ ] 8.1.2 Use `pytest-asyncio` for async tests

- [ ] 8.2 Test Cases (minimum 7, target 10)
  - [ ] TC1: Happy Path (alarm → PENDING → ACK → CONFIRMED, event_state=1)
  - [ ] TC2: NAK Undecodable (alarm → PENDING → bad NAK → FAILED, event_state=2, T2 notification)
  - [ ] TC3: Parseable NAK (alarm → PENDING → NAK with timestamp → FAILED, T1 notification fired by SM1)
  - [ ] TC4: Timeout with Retries (alarm → 3 timeouts → FAILED, event_state=2, T3 notification after max_retries)
  - [ ] TC5: Persistence (CONFIRMED → stop daemon → restart → event_state=1 retained)
  - [ ] TC6: Multiple Alarms (zone A CONFIRMED → zone B PENDING → ACK → CONFIRMED)
  - [ ] TC7: No IDLE Re-entry (CONFIRMED → next alarm goes directly to PENDING)
  - [ ] TC8: Zone Extraction (#zone#="Salon" in command → included in SIA frame)
  - [ ] TC9: SM1 NO_NETWORK (alarm PENDING → SM1 NO_NETWORK → SM2 FAILED immediately, T3)
  - [ ] TC10: Concurrent Supervision + Alarms (supervision queue priority, alarms queued without blocking)

- [ ] 8.3 Test fixtures
  - [ ] 8.3.1 Mock daemon with proper CSR preset configuration
  - [ ] 8.3.2 Mock PriorityQueue for EVENT/SUPERVISION items
  - [ ] 8.3.3 Use `csr_simulator` with response delay to inject timeout scenarios

- [ ] 8.4 Assertions
  - [ ] 8.4.1 Verify SM2 state transitions are correct
  - [ ] 8.4.2 Verify event_state and event_label updated correctly
  - [ ] 8.4.3 Verify notifications fired at correct times (T1, T2, T3)
  - [ ] 8.4.4 Verify ring buffer entries logged
  - [ ] 8.4.5 Verify retry count and attempt tracking

**Acceptance Criteria mapping:** 9

---

## Dev Notes

### Architecture Requirements

- **State Machine Invariants** (ref: daemon-design.md § SM2 — Alarm Event State):
  - IDLE is startup-only; never re-entered after first alarm
  - PENDING and IDLE cannot occur simultaneously (only one alarm in flight at a time)
  - CONFIRMED→PENDING and FAILED→PENDING are direct (no IDLE step)
  - SM2=IDLE before queue consumer dequeues first EVENT

- **SIA DC-09 Frame Generation** (ref: sia_protocol.py § encode_message):
  - Alarm frame: `id_type='SIA-DCS'` (unencrypted v1.0), account=from preset, seq=incremented per previous story, zone=extracted from action command `#zone#` tag
  - Timestamp: fresh from `make_timestamp()`, **no `_` prefix** (encode_message adds it)
  - CRC format: `crc_format=self._crc_format` (loaded from preset at daemon startup)
  - Optional media_url: appended if configured (deferred to v1.5)

- **PriorityQueue Integration** (ref: daemon-design.md § Component 1 — Daemon Core):
  - EVENT items dequeue with lower priority than SUPERVISION (supervision keeps CSR connection alive)
  - At dequeue: check SM1 state before send attempt
  - If SM1=NO_NETWORK: fail event immediately without send attempt
  - Single `_queue_consumer()` coroutine ensures only one item in flight at a time (no race conditions on SM2 state)

- **Error Handler Integration** (ref: error-handler-design.md):
  - T1 notifications (SUPERVISION_TIMEOUT, SUPERVISION_NAK) fired by SM1, not SM2
  - T2 notifications (BAD_CSR_RESPONSE) fired when NAK is undecodable
  - T3 notifications (EVENT_FAILED) fired when SM2 fails after max retries or SM1 NO_NETWORK
  - `_notify()` signature: `_notify(code: ErrorCode, ctx: ErrorContext = None)`
  - EventFailedCtx: `zone: str | None`, `sia_code: str`, `attempts: int`

### Project Structure Notes

- **Daemon file**: `resources/siadc09d/daemon.py` (already contains SM1State enum and SM1 methods from story 5-1)
- **Add to daemon.py**: SM2State enum, SM2LogCtx TypedDict, `_sm2_state`, `_event_state`, `_event_label`, `_send_with_retry()`, SM2 transitions in `_queue_consumer()`, `_log_sm2_event()`, helpers `_event_state_from_sm2()` and `_event_label_from_sm2()`
- **Messages file**: `resources/siadc09d/messages.py` (already contains SM1 labels; add SM2 labels: SM2_IDLE_FR, SM2_EVENT_RECEIVED_FR, SM2_CONFIRMED_FR, SM2_FAILED_FR, SM2_FAILED_NAK_FR, SM2_FAILED_NO_NETWORK_FR)
- **Test file**: `tests/level2/test_sm2_alarm_event_suite.py` (new file, follows testing.md standards)
- **No new files** — SM2 logic is part of daemon.py, not a separate module

### Constraints and Dependencies

- **Depends on Story 5-1** (SM1 state machine) — must be completed first
- **Uses PriorityQueue** from story 5-3 (or stub if 5-3 not yet implemented; use `asyncio.Queue` for now, upgrade to PriorityQueue in 5-3)
- **Error codes** from `error_handler.py` (Component 5a) — EventCode.SUPERVISION_NAK, BAD_CSR_RESPONSE, EVENT_FAILED, TRANSPORT_PERMANENT
- **Logging constants** from `messages.py` (Component 4-1) — SM2_EVENT_RECEIVED, SM2_CONFIRMED, SM2_FAILED, SM2_FAILED_NAK, SM2_FAILED_NO_NETWORK, SM1_NAK_TIMESTAMP (for v1.1 reference)
- **Supervision interval** from CSR preset config (default 30s for tests, 60-120s production) — used for retry backoff

### Previous Story Intelligence (Story 5-1)

**SM1 Context You Must Know:**

From story 5-1 implementation:
- SM1State enum: INITIALIZING, HEALTHY, DEGRADED, TCP_RECONNECTING, NO_NETWORK
- Strike counter logic: increments on timeout/NAK, caps at 3, resets on ACK
- `_update_sm1_from_strike()` returns `bool` (True if T3 just fired)
- `_sm1_state` property accessible to SM2 for NO_NETWORK check
- `_send_raw()` returns dict with `{status: 'ack'|'nak'|'timeout', raw_nak: bytes|None}`
- Ring buffer integration: `_log_sm1_supervision()` handles all SM1 logging
- Supervision sequence counter (`_supervision_seq`) separate from event sequence counter (increment per story 5-2)

**Integration Points You Must Handle in SM2:**

1. When NAK received during SM2 event send: call SM1's NAK handler (e.g., `_update_sm1_from_nak()` or similar) to increment strike
2. When SM1 transitions to NO_NETWORK: SM2 must fail any PENDING event with T3 notification
3. When SM1 recovers (DEGRADED→HEALTHY): SM2 can resume event retries from queue
4. Both SM1 and SM2 use same sequence number counter (SIAMessageBuilder.sequence) — coordinate initialization in daemon `__init__()`

### Code Patterns to Follow

**Pattern 1: Async Error Handling**
```python
try:
    raw_response = await asyncio.wait_for(
        self._send_raw(frame),
        timeout=10.0  # SIATransportError on timeout
    )
except asyncio.TimeoutError:
    # Transport timeout — retry
    self._sm2_state = SM2State.PENDING
    continue
except SIATransportError as e:
    logger.warning(f"Transport error: {e}")
    # Retry
    continue
except SIAProtocolError as e:
    logger.error(f"Protocol error: {e}")
    # Cannot recover — fail
    self._sm2_state = SM2State.FAILED
    break
```

**Pattern 2: Notification with Context**
```python
self._notify(
    ErrorCode.EVENT_FAILED,
    EventFailedCtx(
        zone=self._event_zone,
        sia_code=self._event_sia_code,
        attempts=self._event_attempt_count
    )
)
```

**Pattern 3: State Persistence**
```python
self._update_info_commands({
    'event_state': self._event_state_from_sm2(),
    'event_label': self._event_label_from_sm2()
})
```

### References

- Daemon design: [docs/design/daemon-design.md](../../docs/design/daemon-design.md) § SM2 — Alarm Event State
- Error handling: [docs/design/error-handler-design.md](../../docs/design/error-handler-design.md) § 3-tier error model
- Logging design: [docs/design/logging-design.md](../../docs/design/logging-design.md) § SM2 state transitions table
- Protocol specification: [docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md](../../docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md) § 5.5.1 (frame format), § 5.5.3 (NAK/ACK)
- Epics file: [_bmad-output/planning-artifacts/epics.md](../_bmad-output/planning-artifacts/epics.md) § Story 5.2

## Dev Agent Record

### Agent Model Used

Claude Haiku 4.5 (2026-04-13)

### Implementation Summary

**Session 2026-04-13 Progress:**

**✅ COMPLETED (Tasks 1-2, ~40% story):**
1. Defined SM2State enum with 4 states (IDLE, PENDING, CONFIRMED, FAILED)
2. Defined SM2LogCtx TypedDict for logging context
3. Added 6 SM2 instance variables to daemon __init__
4. Implemented _event_state_from_sm2() helper (returns 0/1/2/3)
5. Implemented _event_label_from_sm2() helper (returns French labels)
6. Defined EventItem dataclass for queue items
7. Created test framework with mock_daemon fixture
8. All 14 tests passing for completed tasks

**⚠️  IN PROGRESS (Tasks 3-7, skeleton structure ~30% story):**
1. Task 3: _send_with_retry() - skeleton with full structure, needs:
   - SIAMessageBuilder integration for frame building
   - Full NAK/ACK response handling
   - Exponential backoff logic
2. Task 4-5: Queue consumer and NAK dispatch - not yet started
3. Task 6: Network loss handling - not yet started
4. Task 7: Logging integration - stub in place

**🔄 DEFERRED (Task 2.4, Task 8 tests):**
1. Task 2.4: Event state restoration from config (requires PHP integration)
2. Task 8: Comprehensive test suite (10+ test cases) - framework ready

### Session 1 Completion Notes

- [x] Core SM2 state machine structure complete (enum, context types, instance vars)
- [x] Helper methods (_event_state_from_sm2, _event_label_from_sm2) implemented and tested
- [x] Skeleton implementations in place for Tasks 3-7 with detailed TODO comments
- [x] Test framework established with mock_daemon fixture and 14 tests passing
- [x] SM2State enum definition and tests
- [x] SM2LogCtx TypedDict definition and tests
- [x] SM2 instance variables initialized correctly
- [x] State-to-value helper methods working
- [ ] PriorityQueue integration verified (deferred - awaiting Task 5-3)
- [ ] All error paths tested (deferred - partially in skeleton)
- [ ] Logging integration complete (deferred - framework in place)
- [ ] Info commands persistence verified (deferred - partial in _send_with_retry)
- [ ] 10/10 test cases passing (deferred - framework ready, cases to be filled in)
- [ ] Code review completed (deferred - awaiting full implementation)
- [ ] Story marked done (deferred - pending full Tasks 3-8 implementation)

### Handoff Guide for Session 2

**Start Point:**
- Commit: 8e3b1ce "Story 5-2: SM2 Alarm Event State Machine - Foundation & Skeleton"
- Working directory: clean
- Story status: in-progress
- All foundation tests passing (14/14)

**Key Files to Review Before Starting:**
1. `resources/siadc09d/daemon.py` (lines ~850-970) - Skeleton methods with TODO comments
2. `tests/level2/test_sm2_alarm_event_suite.py` - Test framework and fixtures
3. Story Tasks 3-8 sections - Detailed requirements

**Implementation Order (Recommended):**

1. **Task 3: _send_with_retry() - PRIORITY 1**
   - Replace SIAMessageBuilder stub with real encoder
   - Implement _build_event_frame() using daemon._sia_builder
   - Test: Happy path (ACK), NAK handling, timeouts

2. **Task 5: NAK Dispatch - PRIORITY 2** (do before Task 4)
   - Implement parse_nak_timestamp() or use existing from sia_protocol
   - Add NAK handling logic in _send_with_retry()
   - Call _update_sm1_from_nak() for SM1 strike increment
   - Test: Parseable NAK, undecodable NAK

3. **Task 4: Queue Consumer Integration - PRIORITY 3**
   - Implement or modify _queue_consumer() to handle EventItem
   - Check SM1 state before processing
   - Fail immediately if SM1=NO_NETWORK
   - Test: Multiple alarms, no IDLE re-entry

4. **Task 6: Network Loss Handling - PRIORITY 4**
   - Monitor SM1 state transitions
   - Fail in-flight SM2=PENDING events when SM1→NO_NETWORK
   - Test: NO_NETWORK scenario

5. **Task 7: Logging Integration - PRIORITY 5**
   - Implement _log_sm2_event() with ring buffer
   - Map transitions to messages.py French strings
   - Test: Log output and ring buffer entries

6. **Task 8: Comprehensive Tests - PRIORITY 6**
   - Fill in 10+ test cases (framework ready)
   - Test both happy paths and error scenarios
   - Run full test suite for regressions

**Critical Code Patterns to Follow:**

```python
# Frame building (Task 3):
frame = self._sia_builder.encode_message(
    account=self._account,
    seq=self._sia_seq,
    crc_format=self._crc_format,
    id_type='SIA-DCS',
    receiver_prefix=self._receiver_prefix,
    account_prefix=self._account_prefix,
    zone=event_item.zone,
    timestamp=event_item.timestamp
)

# NAK timestamp parsing (Task 5):
try:
    parsed_ts = parse_nak_timestamp(raw_nak)
    # Handle parseable NAK
except ValueError:
    # Handle undecodable NAK

# State updates (all tasks):
await self._update_info_commands({
    'event_state': self._event_state_from_sm2(),
    'event_label': self._event_label_from_sm2()
})
```

**Dependency Notes:**
- Task 3 needs: SIAMessageBuilder (already in daemon)
- Task 5 needs: parse_nak_timestamp() from sia_protocol
- Task 4 needs: _queue_consumer() method (may already exist from SM1)
- Task 7 needs: messages.py SM2 constants (already defined in story 4-1)

**Testing Commands:**
```bash
# Run SM2 tests only
python3 -m pytest tests/level2/test_sm2_alarm_event_suite.py -v

# Run all Level 2 tests for regression
python3 -m pytest tests/level2/ -v

# Run specific test class
python3 -m pytest tests/level2/test_sm2_alarm_event_suite.py::TestSM2SendWithRetry -v
```

**Expected Final State:**
- All 8 tasks marked [x] complete
- 10+ test cases in test_sm2_alarm_event_suite.py passing
- File List updated with all implementation details
- Story status changed to "review"
- Ready for code review with /bmad-bmm-code-review workflow

### File List

**Completed:**
- resources/siadc09d/daemon.py (modified):
  - SM2State enum with IDLE, PENDING, CONFIRMED, FAILED states
  - SM2LogCtx TypedDict for logging context
  - EventItem dataclass for queue items
  - _event_state_from_sm2() helper method
  - _event_label_from_sm2() helper method
  - SM2 instance variables in __init__ (_sm2_state, _event_state, _event_label, _event_sia_code, _event_zone, _event_attempt_count)

**In Progress (Skeleton with TODO comments):**
- resources/siadc09d/daemon.py (added skeleton methods):
  - _send_with_retry() async method (core retry logic with structure in place)
  - _build_event_frame() method (stub - needs SIAMessageBuilder integration)
  - _log_sm2_event() method (stub - needs ring buffer integration)

**Pending:**
- resources/siadc09d/daemon.py (deferred tasks):
  - Task 2.4: Restore event state from config (requires PHP config reading)
  - Task 4: _queue_consumer() integration (awaiting Task 5-3 PriorityQueue)
  - Task 5: NAK timestamp dispatch and SM1 integration
  - Task 6: Network loss and daemon stop handling
  - Task 7: Full logging integration with French messages

**Test Infrastructure:**
- tests/level2/test_sm2_alarm_event_suite.py (new):
  - TestSM2StateEnumDefinition (2 tests: enum exists, enum values)
  - TestSM2LogCtxDefinition (2 tests: TypedDict exists, field types)
  - TestSM2InstanceVariablesInitialization (2 tests: vars exist, initial values)
  - TestSM2StateHelpers (8 tests: all helper method transitions)
  - Test framework with mock_daemon fixture
  - Placeholder test cases for Tasks 3-8 (to be filled in during implementation)
