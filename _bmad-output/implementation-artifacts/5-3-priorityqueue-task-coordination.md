# Story 5.3: PriorityQueue Task Coordination

**Status:** done

**Created:** 2026-04-15

**Session 1:** Story creation — daemon-design.md confirmed as authoritative; priority values resolved.

**Session 2:** Full implementation complete — 26 new tests pass, 0 regressions.

---

## Story

As a daemon architect,
I want SM1 and SM2 tasks coordinated in a priority queue,
So that supervision keep-alives take priority over alarm retries.

---

## Acceptance Criteria

1. **PriorityQueue Initialization** — `asyncio.PriorityQueue` initialized as `(priority, counter, item_type, data)` 4-tuple with `itertools.count()` tie-breaker and tie-breaking guards against TypeError on equal-priority items

2. **Priority Constants** — `QUEUE_PRIORITY_EVENT = 0` (alarms, dequeued first — safety-critical), `QUEUE_PRIORITY_SUPERVISION = 1` (supervision, dequeued second). In Python's heapq/asyncio.PriorityQueue, **lower number = higher priority** (min-heap). Alarm delivery is safety-critical and always wins. [Source: daemon-design.md § "Priority Queue coordination", line 503 — "Event wins (priority 0 vs 1)"]

3. **Counter Tie-Breaking** — Each enqueue increments a monotonic counter to ensure FIFO ordering within same priority level, preventing TypeError when comparing dict payloads

4. **Item Type Semantics** — Queue items clearly distinguish between "SUPERVISION" (SM1 null-frame keep-alives) and "EVENT" (SM2 alarm events) with explicit item_type field

5. **Enqueue Methods** — `_enqueue_supervision()` and `_enqueue_event()` helper methods encapsulate priority/counter logic, called from appropriate SM lifecycle methods

6. **Consumer Dispatcher** — Single-consumer coroutine `_queue_consumer()` dequeues items and routes to `_send_raw()` (supervision) or `_send_with_retry()` (event) based on item_type

7. **Task Tracking Integration** — Queue consumer coroutine tracked in `_tasks` set with done callback, no orphaned tasks on shutdown

8. **Queue Resilience on SM1 State Transitions** — `_queue_consumer()` applies SM1 state guards before each dispatch:
   - **HEALTHY / INITIALIZING / DEGRADED (strike 1–3):** Socket remains open. Both SUPERVISION and EVENT items are dequeued and dispatched immediately (`_send_supervision()` and `_send_with_retry()` respectively). DEGRADED affects supervision quality monitoring (strike counter, T1/T3 notifications) but does **not** block queue dispatch.
   - **TCP_RECONNECTING:** Socket is closed (half-open stall). Consumer gates on `_sm1_state_changed` event **before** each `queue.get()` — items remain in the queue, not dequeued at all (no re-enqueue, no drop, no spin). When SM1 transitions out of TCP_RECONNECTING (→ INITIALIZING on reconnect success, → NO_NETWORK on failure), `_set_sm1_state()` fires the event and the consumer resumes.
   - **NO_NETWORK (terminal):** All items (SUPERVISION and EVENT) dropped silently. Daemon is stopping; queue contents abandoned. SM2 state reflects in-flight state at shutdown and is not reset.

---

## Design Decision Record

### Priority Values — RESOLVED (daemon-design.md is authoritative)

The epics.md story text ("supervision=10, alarms=5") used inverted semantics that implied supervision takes priority. **daemon-design.md overrides this.** Confirmed values:

| Queue item | Constant | Value | Heapq order | Rationale |
|---|---|---|---|---|
| Alarm event (SM2) | `QUEUE_PRIORITY_EVENT` | `0` | Dequeued FIRST | Safety-critical; alarm delivery cannot be delayed |
| Supervision NULL (SM1) | `QUEUE_PRIORITY_SUPERVISION` | `1` | Dequeued SECOND | Keep-alive; can wait one cycle |

> **heapq min-heap:** `asyncio.PriorityQueue` uses `heapq` — **lower number = dequeued first**. Priority 0 beats priority 1. The story's phrasing "supervision takes priority" was misleading; the intent is preserved (supervision runs regularly) but alarms always pre-empt a waiting supervision item.
>
> **Source:** daemon-design.md Component 1, table "Supervision vs event priority | Event wins (priority 0 vs 1) | Alarm delivery is safety-critical"

---

## Tasks / Subtasks

### Task 1: Define Queue Item Types and Constants (5.3.1)

- [x] 1.1 Define priority constants at module level
  - [x] 1.1.1 `QUEUE_PRIORITY_EVENT = 0` (alarms—higher priority in heapq)
  - [x] 1.1.2 `QUEUE_PRIORITY_SUPERVISION = 1` (supervision—lower priority in heapq)
  - [x] 1.1.3 Add comment explaining heapq min-heap semantics (lower=first)

- [x] 1.2 Define queue item type literals
  - [x] 1.2.1 `QUEUE_TYPE_EVENT = "EVENT"`
  - [x] 1.2.2 `QUEUE_TYPE_SUPERVISION = "SUPERVISION"`
  - [x] 1.2.3 Type alias: `QueueItemType = Literal["EVENT", "SUPERVISION"]`

- [x] 1.3 Define TypedDict for queue payload
  - [x] 1.3.1 `EventQueueItem(TypedDict)`: {type, zone, media_url, retries_left}
  - [x] 1.3.2 `SupervisionQueueItem(TypedDict)`: {} (empty for v1.0)
  - [x] 1.3.3 `QueuePayload = EventQueueItem | SupervisionQueueItem`

- [x] 1.4 Document queue tuple structure in module docstring
  - [x] 1.4.1 Show full 4-tuple: `(priority: int, counter: int, item_type: QueueItemType, payload: QueuePayload)`
  - [x] 1.4.2 Example: `(0, 42, "EVENT", {"type": "BA", "zone": "Salon", "media_url": None, "retries_left": 3})`
  - [x] 1.4.3 Reference: daemon-design.md § Priority Queue coordination

**Acceptance Criteria mapping:** 2

---

### Task 2: Initialize PriorityQueue and Counter in Daemon (5.3.2)

- [x] 2.1 Add instance variables to `SIADaemon.__init__()`
  - [x] 2.1.1 `self._queue: asyncio.PriorityQueue[tuple[int, int, QueueItemType, QueuePayload]]` = initialized as empty
  - [x] 2.1.2 `self._queue_counter: Iterator[int]` = `itertools.count()` for monotonic tie-breaker
  - [x] 2.1.3 Document both in `__init__` docstring under Instance Variables section

- [x] 2.2 Initialize queue in `on_start()` if not already created
  - [x] 2.2.1 Ensure `self._queue` is created fresh (or check it's empty from __init__)
  - [x] 2.2.2 Ensure `self._queue_counter` state is reset if needed (use fresh `itertools.count()`)

- [x] 2.3 Add type hint to `__init__` docstring
  - [x] 2.3.1 Document that queue items are 4-tuples: priority, counter, item_type, payload
  - [x] 2.3.2 Document counter purpose: "Monotonic int from itertools.count() — tie-breaker to ensure FIFO within same priority and prevent TypeError on dict comparison"

**Acceptance Criteria mapping:** 1, 3

---

### Task 3: Implement Enqueue Helper Methods (5.3.3)

- [x] 3.1 Implement `_enqueue_event(event_type: str, zone: str | None, media_url: str | None, retries_left: int) -> None`
  - [x] 3.1.1 Get next counter: `counter = next(self._queue_counter)`
  - [x] 3.1.2 Build payload: `{type: event_type, zone: zone, media_url: media_url, retries_left: retries_left}`
  - [x] 3.1.3 Enqueue: `await self._queue.put((QUEUE_PRIORITY_EVENT, counter, QUEUE_TYPE_EVENT, payload))`
  - [x] 3.1.4 Log: DEBUG `"Alarm {event_type} for zone {zone} enqueued (counter={counter})"`

- [x] 3.2 Implement `_enqueue_supervision() -> None`
  - [x] 3.2.1 Get next counter: `counter = next(self._queue_counter)`
  - [x] 3.2.2 Enqueue: `await self._queue.put((QUEUE_PRIORITY_SUPERVISION, counter, QUEUE_TYPE_SUPERVISION, {}))`
  - [x] 3.2.3 Log: DEBUG `"Supervision NULL enqueued (counter={counter})"`

- [x] 3.3 Document both methods in daemon docstring
  - [x] 3.3.1 Add to "Methods" section or "Queue Management" subsection
  - [x] 3.3.2 Note: These methods are called from SM1 supervision loop and SM2 on_message handler

**Acceptance Criteria mapping:** 5

---

### Task 4: Implement Queue Consumer Coroutine (5.3.4)

- [x] 4.1 Create `_queue_consumer() -> Coroutine` async method
  - [x] 4.1.1 Loop forever: `while True:`
  - [x] 4.1.2 Dequeue: `priority, counter, item_type, payload = await self._queue.get()`
  - [x] 4.1.3 Log dequeue: DEBUG `"Dequeued {item_type} (priority={priority}, counter={counter})"`

- [x] 4.2 Route to SM1 supervision handler
  - [x] 4.2.1 `if item_type == QUEUE_TYPE_SUPERVISION:`
  - [x] 4.2.2 Call `await self._send_raw_supervision()` (or similar, per SM1 design)
  - [x] 4.2.3 Log: INFO `"Supervision frame sent"` (French message from messages.py)

- [x] 4.3 Route to SM2 event handler
  - [x] 4.3.1 `elif item_type == QUEUE_TYPE_EVENT:`
  - [x] 4.3.2 Call `await self._send_with_retry(payload)`
  - [x] 4.3.3 Payload unpacked: `event_type = payload['type']`, `zone = payload['zone']`, etc.

- [x] 4.4 Mark queue task done
  - [x] 4.4.1 `self._queue.task_done()` after every dequeue cycle

- [x] 4.5 Handle exceptions in consumer
  - [x] 4.5.1 Wrap main loop in try/except for logging
  - [x] 4.5.2 Log exceptions: ERROR with full traceback
  - [x] 4.5.3 Consumer should NOT exit on transient errors (network timeouts, etc.)

**Acceptance Criteria mapping:** 4, 6

---

### Task 5: Launch Queue Consumer in on_start() (5.3.5)

- [x] 5.1 Launch consumer coroutine
  - [x] 5.1.1 In `on_start()` after SM1/SM2 initialization
  - [x] 5.1.2 `consumer_task = await self._track_task(self._queue_consumer(), name="queue_consumer")`
  - [x] 5.1.3 Store task reference (already in `_tasks` set via `_track_task`)

- [x] 5.2 Ensure consumer cleanup on shutdown
  - [x] 5.2.1 In `on_stop()`, consumer is already cancelled via `_tasks` cleanup
  - [x] 5.2.2 All queued items are abandoned (no need to drain queue on shutdown)

**Acceptance Criteria mapping:** 7

---

### Task 6: Update SM1 Supervision Loop to Enqueue via PriorityQueue (5.3.6)

- [x] 6.1 Locate `_supervision_loop()` in daemon.py (already implemented from Story 5-1)
  - [x] 6.1.1 Current implementation: directly calls `_send_raw()` in a timer loop
  - [x] 6.1.2 CHANGE: Call `_enqueue_supervision()` instead

- [x] 6.2 Modify supervision loop to use queue
  - [x] 6.2.1 Remove direct `_send_raw()` call
  - [x] 6.2.2 Replace with `await self._enqueue_supervision()`
  - [x] 6.2.3 Log: DEBUG `"Supervision check interval fired, enqueueing NULL frame"`

- [x] 6.3 Verify timing
  - [x] 6.3.1 Supervision interval (default 60s) unchanged
  - [x] 6.3.2 Enqueue → dequeue → send happens asynchronously now
  - [x] 6.3.3 If queue is backed up, supervision may be delayed (acceptable in v1.0)

**Acceptance Criteria mapping:** 2, 8

---

### Task 7: Update SM2 on_message to Enqueue via PriorityQueue (5.3.7)

- [x] 7.1 Locate `on_message(cmd, params)` in daemon.py (Story 5-2)
  - [x] 7.1.1 Current: directly returns (fire-and-forget)
  - [x] 7.1.2 CHANGE: Calls `_enqueue_event()` to queue the alarm

- [x] 7.2 Parse incoming alarm and enqueue
  - [x] 7.2.1 Extract `cmd` → event_type: "BA" | "FA" | "PA" (burglar, fire, panic)
  - [x] 7.2.2 Extract `params['zone']` → zone name (str)
  - [x] 7.2.3 Extract `params['media_url']` → optional URL (str | None)
  - [x] 7.2.4 Call: `await self._enqueue_event(event_type, zone, media_url, retries_left=RETRY_LIMIT)`

- [x] 7.3 Ensure enqueue returns immediately (fire-and-forget)
  - [x] 7.3.1 `on_message()` awaits `_enqueue_event()` and returns
  - [x] 7.3.2 No waiting for actual send; queue consumer handles send asynchronously
  - [x] 7.3.3 Guarantees PHP's sendToDaemon() call completes instantly

**Acceptance Criteria mapping:** 2, 8

---

### Task 8: Implement Queue Resilience During SM1 State Transitions (5.3.8)

- [x] 8.1 SM1 DEGRADED/HEALTHY states
  - [x] 8.1.1 Events dequeued normally, `_queue_consumer` attempts send
  - [x] 8.1.2 Supervision items dequeued normally (socket should be open)

- [x] 8.2 SM1 TCP_RECONNECTING state
  - [x] 8.2.1 In `_queue_consumer()`, gate on SM1 state **before** each `queue.get()` call
  - [x] 8.2.2 While SM1 = TCP_RECONNECTING: clear `_sm1_state_changed`, re-check, then await it
    - Items remain in queue (not dequeued) — no re-enqueue, no drop, no spin
    - Both EVENT and SUPERVISION items held; both dispatched normally after recovery
  - [x] 8.2.3 Log: DEBUG `"SM1 TCP_RECONNECTING: queue consumer waiting for state change"` on each gate wait

- [x] 8.3 SM1 NO_NETWORK state
  - [x] 8.3.1 In `_queue_consumer()`, if SM1 = NO_NETWORK:
    - [x] 8.3.1.1 All items (EVENT and SUPERVISION) dropped silently
    - [x] 8.3.1.2 Daemon is stopping, no point enqueueing
  - [x] 8.3.2 Log: DEBUG `"SM1 NO_NETWORK: queue item dropped, daemon stopping"`

**Acceptance Criteria mapping:** 8

---

### Task 9: Testing — Unit Tests for Queue (5.3.9)

Create `tests/level2/test_priority_queue_basic.py`:

- [x] 9.1 Test queue initialization
  - [x] TC1: PriorityQueue initialized, counter starts at 0
  - [x] TC2: First dequeue blocks (queue empty)
  - [x] TC3: Counter increments on each `next()` call

- [x] 9.2 Test priority ordering
  - [x] TC4: Enqueue EVENT (priority=0), SUPERVISION (priority=1) → dequeue returns EVENT first
  - [x] TC5: Enqueue multiple EVENTs → dequeue in FIFO order (counter preserved)
  - [x] TC6: Enqueue multiple SUPERVISIONs → dequeue in FIFO order

- [x] 9.3 Test tie-breaking prevents TypeError
  - [x] TC7: Enqueue two EVENTs with different zones (payloads not comparable) → no TypeError
  - [x] TC8: Enqueue with same priority and counter would fail, but counter is always unique

- [x] 9.4 Test enqueue methods
  - [x] TC9: `_enqueue_event("BA", "Salon", None, 3)` → item in queue with correct structure
  - [x] TC10: `_enqueue_supervision()` → item in queue with empty payload
  - [x] TC11: Counter increments on each enqueue

**Acceptance Criteria mapping:** 1, 3, 5

---

### Task 10: Testing — Integration Tests with Queue Consumer (5.3.10)

Create `tests/level2/test_queue_consumer_integration.py`:

- [x] 10.1 Test consumer happy path
  - [x] TC12: Start daemon, enqueue EVENT, consumer dequeues and routes to `_send_with_retry()`
  - [x] TC13: Consumer tracks dequeue counter in logging
  - [x] TC14: Consumer marks queue.task_done() after dispatch

- [x] 10.2 Test consumer with SM1 state transitions
  - [x] TC15: During TCP_RECONNECTING, EVENT items re-enqueued, SUPERVISION dropped
  - [x] TC16: Re-enqueued EVENT has same counter (or new counter? — clarify)
  - [x] TC17: Dropped SUPERVISION logged as DEBUG

- [x] 10.3 Test queue under backpressure
  - [x] TC18: Enqueue 3 EVENTs with slow sender (mock `_send_with_retry` with delay)
  - [x] TC19: Consumer dequeues and sends in priority order
  - [x] TC20: Backlog is managed without deadlock

**Acceptance Criteria mapping:** 1, 2, 3, 4, 5, 6, 7, 8

---

### Task 11: Testing — Supervision Loop Integration (5.3.11)

Create `tests/level2/test_supervision_queue_integration.py`:

- [x] 11.1 Test supervision enqueue
  - [x] TC21: Supervision timer fires, `_enqueue_supervision()` called
  - [x] TC22: SUPERVISION item appears in queue with priority=1

- [x] 11.2 Test supervision priority
  - [x] TC23: Enqueue SUPERVISION, then EVENT → consumer dequeues EVENT first (priority=0 < 1)
  - [x] TC24: Enqueue EVENT, then SUPERVISION → consumer dequeues EVENT first (same order)

- [x] 11.3 Test supervision under SM1 DEGRADED
  - [x] TC25: SM1 DEGRADED, enqueue SUPERVISION + EVENT → both dequeued and attempted
  - [x] TC26: Supervision timeout or retry not affected by queued EVENTs

**Acceptance Criteria mapping:** 2, 6, 8

---

## Dev Notes

### Architecture Alignment

- **Reference:** daemon-design.md § "Priority Queue coordination" (lines 803-890)
- **ADR-02 Decision:** PriorityQueue for SM1/SM2 coordination (independent SMs, explicit re-queue on TCP_RECONNECTING)
- **Type safety:** All queue items fully typed (TypedDict, Literal, Iterator)
- **Logging:** All enqueue/dequeue operations logged with counter for tracing

### Key Design Constraints

1. **Heapq min-heap semantics:** Lower priority number = higher priority (dequeued first)
   - EVENT (priority=0) dequeued before SUPERVISION (priority=1)
   - This matches daemon-design.md rationale: "Alarm delivery is safety-critical"

2. **Tie-breaking with itertools.count():** Guarantees FIFO within same priority, prevents TypeError
   - Counter is never compared directly; only used to distinguish items for heapq ordering
   - Each enqueue increments counter (via `next()`)

3. **Fire-and-forget enqueue:** `on_message()` returns immediately after enqueueing
   - Actual send happens asynchronously in `_queue_consumer()`
   - PHP sees instant return; daemon sends in background

4. **SM1 state gate in consumer:** Before calling `queue.get()`, check SM1 state
   - DEGRADED (any strike): socket open, both items dispatched normally
   - TCP_RECONNECTING: gate on `_sm1_state_changed` event — items stay in queue, consumer sleeps
   - NO_NETWORK: items dequeued then dropped silently (daemon stopping, queue abandoned)
   - This keeps queue resilient across network transitions with zero spin and no re-enqueue

5. **Consumer cleanup on shutdown:**
   - Consumer task auto-cancelled in `on_stop()` via `_tasks` cleanup
   - Remaining queued items abandoned (acceptable; daemon is stopping)
   - No need for graceful queue drain in v1.0

### File Modifications Required

- **resources/siadc09d/daemon.py**
  - Add: QUEUE_PRIORITY_* and QUEUE_TYPE_* constants (module level)
  - Add: TypedDict definitions (EventQueueItem, SupervisionQueueItem)
  - Add: `_queue` and `_queue_counter` instance variables in `__init__()`
  - Add: `_enqueue_event()`, `_enqueue_supervision()` methods
  - Add: `_queue_consumer()` async method
  - Modify: `on_start()` to launch consumer task
  - Modify: `_supervision_loop()` to call `_enqueue_supervision()` instead of direct `_send_raw()`
  - Modify: `on_message()` to call `_enqueue_event()` instead of direct send
  - Modify: `_queue_consumer()` to check SM1 state for TCP_RECONNECTING/NO_NETWORK handling

### Previous Story Intelligence

**Story 5-2 (SM2 Alarm Event State Machine) — Just Completed**
- SM2 state machine: IDLE → PENDING → CONFIRMED|FAILED
- `_send_with_retry()` method already implemented (handles retries, logging, NAK dispatch)
- `on_message(cmd, params)` stub exists but doesn't enqueue (will be modified by Task 7)
- Test patterns: pytest fixtures, asyncio.gather() for task joining, caplog for logging
- Code patterns: TypedDict for contexts, German messages in messages.py, INFO commands persist state

**Story 5-1 (SM1 Connection Supervision State Machine) — Previously Completed**
- SM1 state machine: INITIALIZING → HEALTHY → DEGRADED → TCP_RECONNECTING|NO_NETWORK
- `_supervision_loop()` method already implemented (sends NULL frame every 60s)
- `_send_raw()` method already implemented
- Strike counter: 0 (HEALTHY), 1-2 (DEGRADED), 3 (critical—forces TCP reconnect or NO_NETWORK)
- Test patterns: same as 5-2; state assertion patterns established

**Key learnings to apply:**
- Always track tasks in `_tasks` set; never bare `asyncio.create_task()`
- Use `_track_task()` helper for task creation with names and done callbacks
- Logging: dual-line pattern (French INFO + English DEBUG)
- Type safety: Literal, TypedDict, Enum for all categorical data
- Async cleanup: use `await asyncio.gather(*self._tasks)` to join all tasks in tests

### Interdependencies

- **Depends on:** Story 5-1 (SM1 _supervision_loop), Story 5-2 (SM2 _send_with_retry)
- **Blocks:** Story 5-4 (transport layer needs to know how to route based on dequeued item_type)
- **Blocks:** Story 5-6 (daemon core integration tests depend on working queue consumer)

---

## Project Context

**Project:** Jeedom SIA DC-09 Plugin

**Daemon location:** `resources/siadc09d/daemon.py`

**Protocol spec:** internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md

**Design documents:**
- [daemon-design.md](internal-docs/design/daemon-design.md) § Priority Queue coordination
- [error-handler-design.md](internal-docs/design/error-handler-design.md) § ErrorCode and T1/T2/T3 tiers
- [logging-design.md](internal-docs/design/logging-design.md) § Ring buffer, French messages

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (1M context)

### Debug Log References

- Sprint status: `/Users/herve.lehoux/Dev/my-project/_bmad-output/implementation-artifacts/sprint-status.yaml`
- Epic + story definitions: `/Users/herve.lehoux/Dev/my-project/_bmad-output/planning-artifacts/epics.md` (lines 787-810)
- Daemon design: `/Users/herve.lehoux/Dev/my-project/internal-docs/design/daemon-design.md` (lines 803-890)
- Architecture: `/Users/herve.lehoux/Dev/my-project/_bmad-output/planning-artifacts/architecture.md` (ADR-02)

### Completion Notes List

- ⚠️ **Uncommitted Story 5-2 files present in working tree** (not part of Story 5-3): `tests/level2/test_sm2_alarm_event_suite.py` (modified), `tests/level2/test_sm2_extended_coverage.py` (new), `_bmad-output/implementation-artifacts/tests/test-generation-summary-qa-sm2-extended.md` (new), `_bmad-output/implementation-artifacts/5-2-sm2-alarm-event-state-machine.md` (modified), `.claude/rules/code-style.md` (modified). These are QA additions from a Story 5-2 session. Commit them under Story 5-2 before closing that story.
- ✅ Story AC extracted from epics.md
- ✅ **RESOLVED:** Priority value discrepancy resolved — daemon-design.md is authoritative. `QUEUE_PRIORITY_EVENT=0` (alarms first), `QUEUE_PRIORITY_SUPERVISION=1`.
- ✅ SIA DC-09 expert pre-validation completed: one-at-a-time constraint satisfied
- ✅ **REVISED (code review):** TCP_RECONNECTING uses gate approach (`_sm1_state_changed` event) — items held in queue, not re-enqueued. Original payload (counter + retry budget) preserved. SUPERVISION also held rather than dropped.
- ✅ All 11 tasks implemented in `resources/siadc09d/daemon.py`
- ✅ `_track_task()` implemented (replaces stub) — anticipating Story 5-5 lifecycle management
- ✅ `on_start()`, `on_message()`, `_supervision_loop()`, `_queue_consumer()`, `_enqueue_event()`, `_enqueue_supervision()` all implemented
- ✅ 26 new tests across 3 test files — all pass
- ✅ 0 regressions in full suite (2 pre-existing SM1 failures from Story 5-1 unchanged)
- ✅ TCP_RECONNECTING loop fixed in tests using asyncio.Event spy pattern (no timing dependencies)
- ✅ All AC items 1–8 verified by test suite

### File List

**Python source files modified:**
- [resources/siadc09d/daemon.py](resources/siadc09d/daemon.py) — Added: `QUEUE_PRIORITY_EVENT/SUPERVISION`, `QUEUE_TYPE_EVENT/SUPERVISION`, `QueueItemType`, `EventQueuePayload`, `SupervisionQueuePayload`, `MAX_RETRY_DEFAULT`; added `_queue` + `_queue_counter` to `__init__`; replaced `_track_task_stub` with real `_track_task()`; added `_enqueue_event()`, `_enqueue_supervision()`, `_queue_consumer()`, `_supervision_loop()`, `on_message()`, `on_start()`

**Test files created:**
- [tests/level2/test_priority_queue_basic.py](tests/level2/test_priority_queue_basic.py) — 11 unit tests (TC1–TC11): init, priority ordering, FIFO, tie-breaking, enqueue methods
- [tests/level2/test_queue_consumer_integration.py](tests/level2/test_queue_consumer_integration.py) — 9 integration tests (TC12–TC20): happy path, TCP_RECONNECTING resilience, backpressure
- [tests/level2/test_supervision_queue_integration.py](tests/level2/test_supervision_queue_integration.py) — 6 integration tests (TC21–TC26): supervision enqueue, priority ordering, on_message mapping

---

## Testing Strategy

### Unit Test Coverage (test_priority_queue_basic.py)

| Test Case | Focus | Expected Behavior |
|-----------|-------|-------------------|
| TC1 | Queue init | PriorityQueue created, counter at 0 |
| TC2 | Empty queue | `queue.get()` blocks until item added |
| TC3 | Counter increment | `next(counter)` returns 0, 1, 2, ... monotonically |
| TC4 | Priority ordering | EVENT (0) dequeued before SUPERVISION (1) |
| TC5 | FIFO within priority | Multiple EVENTs dequeued in counter order |
| TC6 | FIFO SUPERVISION | Multiple SUPERVISIONs dequeued in counter order |
| TC7 | No TypeError (dicts) | Two EVENTs with different payloads don't trigger comparison error |
| TC8 | Unique counter | Same priority items never have same counter (by design) |
| TC9 | `_enqueue_event()` | Event item created with correct structure |
| TC10 | `_enqueue_supervision()` | Supervision item created with empty payload |
| TC11 | Counter increments | Each enqueue increments counter |

### Integration Test Coverage (test_queue_consumer_integration.py)

| Test Case | Focus | Expected Behavior |
|-----------|-------|-------------------|
| TC12 | Happy path | Enqueue EVENT → consumer dequeues → calls `_send_with_retry()` |
| TC13 | Logging | Dequeue logged with counter value |
| TC14 | task_done() | `queue.task_done()` called after dispatch |
| TC15 | TCP_RECONNECTING | EVENT held in queue (not dequeued); dispatched after SM1 recovers |
| TC16 | Hold retry budget | Held EVENT retains original retries_left (no budget reset — same payload) |
| TC17 | SUPERVISION held | SUPERVISION also held in queue; dispatched after SM1 recovers |
| TC18 | Backpressure | Multiple items in queue, consumer processes in order |
| TC19 | Priority under load | Even with 3 EVENTs queued, next SUPERVISION processes correctly (if dequeued) |
| TC20 | No deadlock | Slow sender + multiple items doesn't hang consumer |

### Supervision Loop Integration (test_supervision_queue_integration.py)

| Test Case | Focus | Expected Behavior |
|-----------|-------|-------------------|
| TC21 | Timer fires | Supervision interval triggered → `_enqueue_supervision()` called |
| TC22 | SUPERVISION enqueue | SUPERVISION item in queue with priority=1 |
| TC23 | Priority wins | EVENT enqueued first, SUPERVISION second → EVENT dequeued first |
| TC24 | Priority wins (reverse) | SUPERVISION enqueued first, EVENT second → EVENT still dequeued first |
| TC25 | Under DEGRADED | SM1 DEGRADED, queue items sent (no failures) |
| TC26 | Supervision timing | Supervision interval not affected by queued EVENTs (independent loop) |

### Test Implementation Notes

- **Async fixtures:** Reuse `daemon_factory` from Story 5-2 tests (already handles CSRSimulator, time_mock)
- **Logging assertions:** Use `caplog` fixture to verify queue DEBUG lines
- **Task cleanup:** Always `await asyncio.gather(*daemon._tasks)` after state transitions to ensure consumer tasks complete
- **Mock strategy:** Mock `_send_with_retry()` and `_send_raw()` return values to control queue flow in integration tests
- **Edge cases:** Test queue with 0 items (blocking), 1 item (instant), N items with varying priorities

---

## Open Questions (design-level, non-blocking)

1. ~~**Priority discrepancy:** Should we use story literal values (10/5) or daemon-design values (0/1)?~~ **RESOLVED:** daemon-design.md is authoritative — use `QUEUE_PRIORITY_EVENT=0`, `QUEUE_PRIORITY_SUPERVISION=1`.

2. **TCP_RECONNECTING hold strategy:** Original design re-enqueued EVENT items with fresh counter and retry budget. **REVISED (code review):** Gate approach used instead — consumer waits on `_sm1_state_changed` before dequeuing. Items remain in queue with original payload (counter and retries preserved). Simpler, no re-enqueue needed, SUPERVISION also held rather than dropped.

3. **Supervision timer independence:** The supervision timer (`_supervision_loop`) sleeps N seconds, then calls `_enqueue_supervision()`. The consumer coroutine dequeues and sends. These are already independent. No shared timing logic needed.

4. **Queue drain on shutdown:** `on_stop()` cancels consumer task via `_tasks` cleanup. Remaining queued items are abandoned. If a PENDING alarm was in queue during shutdown, SM2 state will show PENDING on next restart (expected — see AC7 of Story 5-2). Default: silent abandon for v1.0.

5. **Event retries and queue:** `_send_with_retry()` exhausts retries internally, transitions SM2 to FAILED, fires T3 notification. The event is NOT re-enqueued after failure — PHP can send another alarm command if needed. Default: do not re-enqueue failed events.

---

## Success Criteria

✅ **Acceptance Criteria Met:**
- [x] 1. PriorityQueue 4-tuple with tie-breaker
- [x] 2. Priority constants (EVENT=0, SUPERVISION=1)
- [x] 3. Monotonic counter via itertools.count()
- [x] 4. Item type semantics (SUPERVISION vs EVENT)
- [x] 5. Enqueue helper methods
- [x] 6. Consumer dispatcher routing to SM1/SM2
- [x] 7. Task tracking in _tasks set
- [x] 8. Queue resilience on SM1 state transitions (DEGRADED=dispatch, TCP_RECONNECTING=gate/hold-in-queue, NO_NETWORK=drop-all)

✅ **Test Coverage:**
- [x] 11 unit tests (queue initialization, ordering, tie-breaking, enqueue methods)
- [x] 9 integration tests (consumer behavior, SM1 transitions, backpressure)
- [x] 6 supervision tests (enqueue, priority, integration)
- [x] **Total: 26 tests, all passing, 0 regressions**

✅ **Code Quality:**
- [x] 100% type hints (no bare `str`, `dict`, `int`)
- [x] Full docstrings with Args/Returns/Raises
- [x] French INFO messages in messages.py
- [x] English DEBUG messages in code
- [x] No bare `asyncio.create_task()` (use `_track_task()`)
- [x] All tasks tracked and cleaned up on shutdown

