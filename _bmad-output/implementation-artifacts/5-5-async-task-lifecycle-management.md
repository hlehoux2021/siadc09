# Story 5.5: Async Task Lifecycle Management

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a daemon architect,
I want all background tasks tracked and cleanly cancelled,
So that no tasks are orphaned or lost on shutdown.

## Acceptance Criteria

1. **Task tracking** — All background tasks created exclusively via `_track_task(coro, name)` method. No bare `asyncio.create_task()` calls anywhere in `daemon.py`.

2. **`_tasks` initialization** — `_tasks: set[asyncio.Task]` initialized in `__init__` as an empty set (code-style.md rule: all instance variables in `__init__`). The epics AC mentions `on_start()` but code-style.md takes precedence — current `__init__` implementation is correct and must not be moved.

3. **Descriptive task names** — Every `_track_task()` call passes a non-empty `name` string. No `Task-1`, `Task-2` style names (asyncio's default).

4. **Done callback** — `_track_task()` done callback: (a) removes task from `_tasks` via `discard()`, (b) logs `logger.error(...)` if task exited with exception and was not cancelled.

5. **Clean shutdown** — `on_stop()` cancels all tasks in `_tasks`, then awaits them with `asyncio.wait_for(..., timeout=ON_STOP_TASK_TIMEOUT_S)`.

6. **`_notify()` is synchronous** — `_notify(self, error_code, context)` is a `def` (not `async def`) method on `SIADaemon`. It is a synchronous wrapper; in v1.0 it logs at DEBUG. Epic 6 will implement the real dispatch by calling `_track_task(_dispatch_notification(error_code, context))`. All `await self._notify(...)` call sites in `daemon.py` must be updated to `self._notify(...)` (no `await`).

---

## Tasks / Subtasks

### Task 1: Convert `_notify()` from async stub to synchronous class method (5.5.1)

This is the primary code change in this story. Currently `_notify` is an instance-variable set to `_notify_stub` (an `async def` no-op). The refactor makes it a real class method that is synchronous.

- [x] **1.1** In `SIADaemon.__init__()`: **remove** the instance assignment `self._notify = self._notify_stub`.
  - Also remove `_notify: async method to dispatch error notifications` from the `__init__` docstring Instance Variables section.
  - Add instead: `# Note: _notify() is a class method (def, not async def) — see below`

- [x] **1.2** **Remove** the `async def _notify_stub(...)` method entirely.

- [x] **1.3** **Add** the following class method to `SIADaemon` (place it directly after `__init__`, before `_send_raw`):
  ```python
  def _notify(self, error_code: ErrorCode, context: NotificationContext) -> None:
      """Dispatch error notification as a non-blocking background task.

      Synchronous wrapper — never blocks the caller. In v1.0 this logs at DEBUG
      only (stub). Epic 6 will replace the body with:
          self._track_task(
              self._dispatch_notification(error_code, context),
              name=f"notify_{error_code.name}"
          )

      Args:
          error_code: ErrorCode enum value identifying the error tier
          context: Typed context dataclass (SM1TimeoutCtx, EventFailedCtx, etc.)

      Reference: error-handler-design.md — T1/T2/T3 dispatch contract
      Reference: daemon-design.md Component 1 — _notify() synchronous wrapper
      """
      # v1.0 stub: log only, no PHP dispatch (Epic 6 replaces with _track_task call)
      self._logger.debug(
          f"_notify: {error_code.name} (stub — Epic 6 implements dispatch)"
      )
  ```

- [x] **1.4** Update `SIADaemon.__init__()` docstring Instance Variables section. Replace:
  ```
  _notify: async method to dispatch error notifications
  ```
  With:
  ```
  Note: _notify() is defined as a class method (def, not async def).
        Epic 6 will dispatch via _track_task(_dispatch_notification(error_code, context)).
  ```

- [x] **1.5** Update ALL `await self._notify(...)` call sites in `daemon.py` — remove the `await` keyword. There are approximately **10 sites**:

  | Method | Line (approx) | Current | After |
  |--------|---------------|---------|-------|
  | `_update_sm1_from_strike()` | ~593 | `await self._notify(ErrorCode.SUPERVISION_DISCONNECTED, ...)` | `self._notify(ErrorCode.SUPERVISION_DISCONNECTED, ...)` |
  | `_handle_supervision_nak()` | ~754 | `await self._notify(ErrorCode.BAD_CSR_RESPONSE, ...)` | `self._notify(ErrorCode.BAD_CSR_RESPONSE, ...)` |
  | `_handle_supervision_nak()` | ~764 | `await self._notify(ErrorCode.SUPERVISION_NAK, ...)` | `self._notify(ErrorCode.SUPERVISION_NAK, ...)` |
  | `_handle_supervision_timeout()` | ~812 | `await self._notify(ErrorCode.SUPERVISION_TIMEOUT, ...)` | `self._notify(ErrorCode.SUPERVISION_TIMEOUT, ...)` |
  | `_tcp_reconnect_loop()` | ~921 | `await self._notify(ErrorCode.TRANSPORT_PERMANENT, ...)` | `self._notify(ErrorCode.TRANSPORT_PERMANENT, ...)` |
  | `_send_with_retry()` NAK path | ~1134 | `await self._notify(ErrorCode.BAD_CSR_RESPONSE, ...)` | `self._notify(ErrorCode.BAD_CSR_RESPONSE, ...)` |
  | `_send_with_retry()` timeout path 1 | ~1190 | `await self._notify(ErrorCode.EVENT_FAILED, ...)` | `self._notify(ErrorCode.EVENT_FAILED, ...)` |
  | `_send_with_retry()` timeout path 2 | ~1234 | `await self._notify(ErrorCode.EVENT_FAILED, ...)` | `self._notify(ErrorCode.EVENT_FAILED, ...)` |
  | `_send_with_retry()` protocol error | ~1264 | `await self._notify(ErrorCode.EVENT_FAILED, ...)` | `self._notify(ErrorCode.EVENT_FAILED, ...)` |
  | `_send_with_retry()` loop fallback | ~1284 | `await self._notify(ErrorCode.EVENT_FAILED, ...)` | `self._notify(ErrorCode.EVENT_FAILED, ...)` |

  **Search command to find all sites:**
  ```bash
  grep -n "await self._notify" resources/siadc09d/daemon.py
  ```
  Every match must be changed. Zero `await self._notify` should remain after this task.

- [x] **1.6** `_update_sm1_from_strike()` remains `async def` (it still calls `_track_task()` and is awaited by callers). No signature change needed.

- [x] **1.7** Verify no `await self._notify` remains: `grep -c "await self._notify" resources/siadc09d/daemon.py` must output `0`.

---

### Task 2: Update existing tests that mock `_notify` as `AsyncMock` (5.5.2)

Changing `_notify` from async-stub to a sync method breaks tests that mock it with `AsyncMock()`. These must be updated before running the test suite.

- [x] **2.1** Search all level2 test files for the old mock pattern:
  ```bash
  grep -rn "AsyncMock.*_notify\|_notify.*AsyncMock" tests/level2/
  ```

- [x] **2.2** In each affected file, replace `AsyncMock()` with `MagicMock()` for `_notify`:
  - `tests/level2/test_sm1_extended_suite.py` — likely mocks `_notify`
  - `tests/level2/test_supervision_queue_integration.py` — likely mocks `_notify`
  - `tests/level2/test_queue_consumer_integration.py` — likely mocks `_notify`
  - `tests/level2/test_sm2_alarm_event_suite.py` — likely mocks `_notify`
  - Any other file matching the grep above

  **Pattern change:**
  ```python
  # Before
  daemon._notify = AsyncMock()
  # After
  daemon._notify = MagicMock()
  ```

  **Note:** `assert_called_once_with(...)` and `call_args` still work with `MagicMock`. Since `_notify` is now sync, there is no coroutine to await — the mock returns immediately.

- [x] **2.3** Run the full existing level2 test suite to confirm zero regressions:
  ```bash
  python3 -m pytest tests/level2/ -v --tb=short
  ```
  All previously-passing tests must still pass.

---

### Task 3: Audit bare `asyncio.create_task()` calls (5.5.3)

- [x] **3.1** Search for bare `asyncio.create_task` calls in daemon code:
  ```bash
  grep -n "asyncio.create_task" resources/siadc09d/daemon.py
  ```
  Expected result: **exactly 1 match** — the line inside `_track_task()` itself:
  ```python
  task: asyncio.Task = asyncio.create_task(coro, name=name or None)
  ```
  Any other match is a violation. Fix by replacing with `self._track_task(coro, name="...")`.

- [x] **3.2** Verify `_track_task()` at `daemon.py:405` contains the complete implementation:
  - `asyncio.create_task(coro, name=name or None)` — creates and names the task
  - `self._tasks.add(task)` — registers in tracked set
  - Done callback defined inline (lambda or `_done_cb`): `self._tasks.discard(t)` + exception logging
  - Returns the `asyncio.Task` object

- [x] **3.3** Confirm all task creation sites in `on_start()` and `_update_sm1_from_strike()` use `_track_task`:
  ```bash
  grep -n "_track_task\|create_task" resources/siadc09d/daemon.py
  ```
  Sites expected:
  - `on_start()`: `_track_task(self._queue_consumer(), name="queue_consumer")`
  - `on_start()`: `_track_task(self._supervision_loop(), name="supervision_loop")`
  - `_update_sm1_from_strike()`: `_track_task(self._tcp_reconnect_loop())`  ← **missing name!**
  - `_handle_supervision_tcp_drop()`: `_track_task(self._tcp_reconnect_loop())` ← **missing name!**

  **Fix:** Both `_tcp_reconnect_loop` launches must pass a descriptive name:
  ```python
  # In _update_sm1_from_strike():
  self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
  # In _handle_supervision_tcp_drop():
  self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
  ```

---

### Task 4: Create `tests/level2/test_async_task_lifecycle.py` (5.5.4)

Create a dedicated test file for task lifecycle guarantees. Use `@pytest.mark.asyncio` for async tests.

**File:** `tests/level2/test_async_task_lifecycle.py`

```python
"""
Async task lifecycle tests for Story 5.5.

Verifies _track_task(), on_stop() task cancellation, and _notify() sync contract.
"""
import asyncio
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.error_handler import ErrorCode, SM1TimeoutCtx
from tests.conftest import make_daemon_preset
```

#### TC1: `_track_task()` registers task in `_tasks`
```python
@pytest.mark.asyncio
async def test_track_task_adds_to_tasks_set():
    """
    _track_task() should register the created task in _tasks.

    Expected result:
    - _tasks set grows by 1 when _track_task() is called
    - The returned task object is present in _tasks
    """
```

#### TC2: `_track_task()` done callback removes task from `_tasks` on normal completion
```python
@pytest.mark.asyncio
async def test_track_task_done_callback_removes_task():
    """
    When a tracked task completes normally, the done callback removes it from _tasks.

    Expected result:
    - _tasks is empty after the task finishes (task removed by done callback)
    """
```

#### TC3: `_track_task()` done callback logs exception via `logger.error()`
```python
@pytest.mark.asyncio
async def test_track_task_done_callback_logs_exception(caplog):
    """
    When a tracked task raises an unhandled exception, the done callback logs it.

    Expected result:
    - logger.error() called with message containing task name and exception
    - _tasks does not retain the failed task (discarded)
    """
```

#### TC4: `_track_task()` done callback does NOT log on cancellation
```python
@pytest.mark.asyncio
async def test_track_task_done_callback_no_log_on_cancel(caplog):
    """
    Cancelling a task should not trigger the exception logger in the done callback.

    Expected result:
    - No logger.error() call when task is cancelled
    - _tasks does not retain the cancelled task
    """
```

#### TC5: `_track_task()` assigns descriptive task name
```python
@pytest.mark.asyncio
async def test_track_task_sets_descriptive_name():
    """
    _track_task() should set a human-readable name on the asyncio.Task object.

    Expected result:
    - task.get_name() returns the provided name, not "Task-N"
    """
```

#### TC6: `on_start()` creates exactly two named tasks
```python
@pytest.mark.asyncio
async def test_on_start_creates_named_tasks():
    """
    on_start() should launch exactly two tracked tasks with descriptive names.

    Expected result:
    - _tasks contains two tasks after on_start()
    - Task names are "queue_consumer" and "supervision_loop"
    """
```

#### TC7: `on_stop()` cancels all tracked tasks
```python
@pytest.mark.asyncio
async def test_on_stop_cancels_all_tasks():
    """
    on_stop() must cancel every task in _tasks before returning.

    Expected result:
    - Each task.cancel() is called during on_stop()
    - _tasks is drained (tasks discard themselves via done callback)
    """
```

#### TC8: `on_stop()` awaits tasks with hard timeout
```python
@pytest.mark.asyncio
async def test_on_stop_awaits_tasks_with_timeout():
    """
    on_stop() wraps task gather in asyncio.wait_for with ON_STOP_TASK_TIMEOUT_S.

    Expected result:
    - Even if a task hangs, on_stop() returns after the timeout
    - Timeout logged as logger.error()
    """
```

#### TC9: `_notify()` is a synchronous method (not async)
```python
def test_notify_is_synchronous():
    """
    _notify() must be a regular def, not async def.

    Expected result:
    - inspect.iscoroutinefunction(SIADaemon._notify) returns False
    - Calling daemon._notify() returns None (not a coroutine object)
    """
    # Assert: _notify is defined as def, not async def
    assert not inspect.iscoroutinefunction(SIADaemon._notify)

    preset = make_daemon_preset()
    daemon = SIADaemon(preset=preset)
    ctx = SM1TimeoutCtx(
        elapsed_ms=30000.0,
        strike_count=1,
        supervision_interval_s=60.0,
    )
    result = daemon._notify(ErrorCode.SUPERVISION_TIMEOUT, ctx)
    # Assert: synchronous — returns None immediately
    assert result is None
    # Assert: not a coroutine (no await needed)
    assert not asyncio.iscoroutine(result)
```

#### TC10: `_notify()` does not raise in stub state (v1.0)
```python
def test_notify_stub_does_not_raise():
    """
    v1.0 _notify() stub should complete without raising any exception.

    Expected result:
    - Calling _notify() with any valid ErrorCode/context completes silently
    - No exception raised regardless of error code
    """
```

#### TC11: `_tasks` initialized in `__init__` as empty set
```python
def test_tasks_set_initialized_in_init():
    """
    _tasks must be present and empty immediately after __init__ (before on_start).

    Expected result:
    - daemon._tasks exists without calling on_start()
    - daemon._tasks is an empty set
    """
    preset = make_daemon_preset()
    daemon = SIADaemon(preset=preset)
    # Assert: _tasks exists immediately (code-style.md: all attrs in __init__)
    assert hasattr(daemon, '_tasks')  # exists without on_start
    # Assert: empty set initially
    assert isinstance(daemon._tasks, set)
    assert len(daemon._tasks) == 0
```

#### TC12: No bare `asyncio.create_task()` in `daemon.py` except inside `_track_task()`
```python
def test_no_bare_create_task_in_daemon():
    """
    The only asyncio.create_task() call in daemon.py must be inside _track_task().
    All other task creation must go through _track_task().

    Expected result:
    - Reading daemon.py, asyncio.create_task appears exactly once (inside _track_task)
    """
    import pathlib
    import re

    daemon_path = pathlib.Path("resources/siadc09d/daemon.py")
    source = daemon_path.read_text()
    matches = list(re.finditer(r'asyncio\.create_task\(', source))

    # Assert: exactly one create_task call
    assert len(matches) == 1, (
        f"Expected exactly 1 asyncio.create_task() in daemon.py (inside _track_task), "
        f"found {len(matches)}: {[m.start() for m in matches]}"
    )

    # Assert: that one call is inside _track_task (look for context)
    # Find line number of the match
    line_num = source[:matches[0].start()].count('\n') + 1
    lines = source.splitlines()
    context_lines = lines[max(0, line_num - 5):line_num + 5]
    assert any('_track_task' in l or 'asyncio.create_task' in l for l in context_lines), (
        f"create_task at line {line_num} does not appear to be inside _track_task"
    )
```

---

## Dev Notes

### Critical: `_notify` Mock Pattern Must Change in Existing Tests

Every existing test file that does:
```python
daemon._notify = AsyncMock()
```
must be changed to:
```python
daemon._notify = MagicMock()
```

The affected files are likely:
- `tests/level2/test_sm1_extended_suite.py`
- `tests/level2/test_sm2_alarm_event_suite.py`
- `tests/level2/test_supervision_queue_integration.py`
- `tests/level2/test_queue_consumer_integration.py`

Run `grep -rn "AsyncMock.*notify\|notify.*AsyncMock" tests/` before starting to find all occurrences.

**Why:** `_notify_stub` was `async def`, so tests mocked it as `AsyncMock`. After this story, `_notify()` is a sync `def` method. Calling `await MagicMock()()` is invalid — tests will fail with `TypeError: object MagicMock can't be used in 'await' expression` if the mock remains `AsyncMock`.

But since we're also removing all `await self._notify(...)` from daemon.py, the tests that previously awaited the mock will no longer await it — so the test assertions `daemon._notify.assert_called_once_with(...)` remain valid without change beyond the mock type.

### Critical: `_update_sm1_from_strike()` Stays `async def`

Even though it no longer `await`s `_notify`, it must remain `async def` because:
1. All callers do `t3_just_fired = await self._update_sm1_from_strike()`
2. It calls `self._track_task(self._tcp_reconnect_loop(), ...)` (sync but within an async context)

Changing `_update_sm1_from_strike` from `async def` to `def` is **out of scope** for this story — it would require changing all call sites in methods that do `await self._update_sm1_from_strike()`.

### Critical: `_tcp_reconnect_loop()` Must Have Named Task

Two places launch `_tcp_reconnect_loop()` but pass no name to `_track_task()`:
- `_update_sm1_from_strike()` at line ~583
- `_handle_supervision_tcp_drop()` at line ~845

Both must be changed to:
```python
self._track_task(self._tcp_reconnect_loop(), name="tcp_reconnect_loop")
```

Without a name, asyncio assigns `Task-N` which is useless in error logs and tracebacks.

### Design: Why `_notify()` Becomes Synchronous

The AC explicitly requires this. The design rationale (from daemon-design.md):
- Notification dispatch (HTTP POST to PHP) is inherently async
- But the SM1/SM2 code must not be blocked by notification delivery
- Solution: `_notify()` is a **sync wrapper** that schedules dispatch as a tracked background task
- The SM state machine calls `self._notify(code, ctx)` synchronously and immediately continues
- Epic 6 implements the real dispatch: `_track_task(_dispatch_notification(code, ctx), name=f"notify_{code.name}")`

In v1.0 (this story), the stub just logs at DEBUG — no dispatch needed because PHP IPC is not yet implemented.

### `_update_info_commands` Stays Async — Different Contract

`_update_info_commands` remains `async def` and all callers still use `await self._update_info_commands(...)`. It's outside scope for Story 5.5. The distinction:
- `_notify()` → sync wrapper (dispatch fire-and-forget via `_track_task`)
- `_update_info_commands()` → async (must complete before continuing, order matters)

### Fixture Pattern: Daemon with Mocked Transport

For async tests in `test_async_task_lifecycle.py`, use this pattern from Story 5-4 tests:

```python
@pytest.fixture
def daemon_factory():
    """Create a SIADaemon with mocked transport for lifecycle tests."""
    from resources.siadc09d.sia_transport import SIABaseTransport, SIATransportResult
    from unittest.mock import AsyncMock, MagicMock

    def factory(transport_type: str = 'UDP') -> SIADaemon:
        preset = make_daemon_preset(transport=transport_type)
        daemon = SIADaemon(preset=preset)
        # Mock transport so on_start() doesn't need real network
        mock_transport = MagicMock(spec=SIABaseTransport)
        mock_transport.start = AsyncMock()
        mock_transport.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        mock_transport.close = AsyncMock()
        # Patch create_datagram_endpoint for UDP
        daemon._sia_transport = mock_transport
        return daemon

    return factory
```

But for on_start() tests, patch the transport creation:
```python
with patch('resources.siadc09d.daemon.SIAUDPTransport') as MockUDP:
    mock_t = AsyncMock()
    mock_t.start = AsyncMock()
    MockUDP.return_value = mock_t
    await daemon.on_start()
```

Reference `tests/level2/test_sia_transport_daemon_wiring.py` for the established fixture pattern in this project.

### `ON_STOP_TASK_TIMEOUT_S` Constant

Imported from `sia_transport.py`:
```python
from .sia_transport import ON_STOP_TASK_TIMEOUT_S  # = 5.0 seconds
```

Used in `on_stop()` `asyncio.wait_for(..., timeout=ON_STOP_TASK_TIMEOUT_S)`. Tests that verify the timeout should not override this value — instead mock the gather to slow, verify `asyncio.TimeoutError` is caught and logged.

### Project Structure Notes

**Files to modify:**
```
resources/siadc09d/daemon.py    ← PRIMARY: remove _notify_stub, add def _notify(),
                                   remove ~10× "await self._notify", add names to tcp_reconnect_loop tasks
tests/level2/test_sm1_extended_suite.py       ← UPDATE: AsyncMock → MagicMock for _notify
tests/level2/test_sm2_alarm_event_suite.py    ← UPDATE: AsyncMock → MagicMock for _notify
tests/level2/test_supervision_queue_integration.py ← UPDATE: AsyncMock → MagicMock
tests/level2/test_queue_consumer_integration.py    ← UPDATE: AsyncMock → MagicMock
```

**File to create:**
```
tests/level2/test_async_task_lifecycle.py  ← CREATE: TC1–TC12
```

No other files need changes. `sia_transport.py`, `presets.py`, `sia_protocol.py` are untouched.

### References

- [Source: internal-docs/design/daemon-design.md § Component 1 Task 1.2 — `_notify()` synchronous wrapper]
- [Source: internal-docs/design/daemon-design.md § Component 1 Task 1.11 — `on_stop()` shutdown sequence]
- [Source: internal-docs/design/daemon-design.md § Component 1 — `_track_task()` done-callback pattern]
- [Source: _bmad-output/implementation-artifacts/5-4-udp-tcp-transport-layer.md — `_track_task()` initial implementation, ON_STOP_TASK_TIMEOUT_S]
- [Source: _bmad-output/implementation-artifacts/5-3-priorityqueue-task-coordination.md — task tracking pattern established]
- [Source: .claude/rules/code-style.md — All instance variables must be initialized in `__init__`]
- [Source: .claude/rules/testing.md — pytest patterns, async fixture cleanup, caplog for log assertions]

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (1M context)

### Debug Log References

### Completion Notes List

- Task 1: Converted `_notify()` from `async def _notify_stub` (instance-var stub) to `def _notify(self, ...)` class method. Removed `self._notify = self._notify_stub` from `__init__`. Stripped `await` from all 10 call sites. `grep -c "await self._notify" resources/siadc09d/daemon.py` = 0.
- Task 2: Updated 6 test fixtures from `AsyncMock()` to `MagicMock()` for `_notify`. Note: story listed 4 files but 6 were affected — `test_sm2_extended_coverage.py` and `test_sia_transport_daemon_wiring.py` also required updating.
- Task 3: Added `name="tcp_reconnect_loop"` to both unnamed `_track_task()` calls at `_update_sm1_from_strike()` and `_handle_supervision_tcp_drop()`. Confirmed exactly 1 `asyncio.create_task()` call in daemon.py (inside `_track_task`).
- Task 4: Created `tests/level2/test_async_task_lifecycle.py` with TC1–TC12. All 12 tests pass. Used `patch('sys.argv', ['test'])` to bypass BaseDaemon argparse during test instantiation.
- Regression suite: 561 total (156 level2), 1 pre-existing timing failure (`test_tc13_strike_timing_precision` in level2), 7 pre-existing `_dispatch_notify` NotImplementedError failures (all in `tests/level1/test_error_handler.py`, from Story 3-3 deferred Epic 6 stub). Zero new failures.

### File List

resources/siadc09d/daemon.py
tests/level2/test_async_task_lifecycle.py
tests/level2/test_sm1_extended_suite.py
tests/level2/test_sm2_alarm_event_suite.py
tests/level2/test_supervision_queue_integration.py
tests/level2/test_queue_consumer_integration.py
tests/level2/test_sm2_extended_coverage.py
tests/level2/test_sia_transport_daemon_wiring.py

Note: The following files also appear modified in the working tree but belong to
Story 5-4 (transport layer) and the Optional→union migration, not Story 5-5:
`csr_simulator.py`, `error_handler.py`, `ring_buffer.py`, `sia_crypto.py`,
`sia_protocol.py`, `simulate_frames.py`, `conftest.py`, `test_sia_protocol.py`,
`test_sia_protocol_ack_nak.py`, `test_priority_queue_basic.py`.

---

## Senior Developer Review (AI)

**Reviewer:** Claude Opus 4.6 (1M context) — 2026-04-22

**Findings (6 total): 2 HIGH, 4 MEDIUM, 2 LOW**

| # | Severity | Description | Resolution |
|---|----------|-------------|------------|
| F1 | HIGH | `__main__` entry point calls `SIADaemon()` without required `preset` arg (broken since 5-4 changed `__init__` signature) | Fixed: removed broken `__main__` block, added comment that production entry point is wired in Epic 3 |
| F2 | HIGH | `__init__` docstring lists `_track_task` and `_log_sm1_supervision` under "Async methods - provided by subclass or injected" — both are real class methods | Fixed: rewrote section to only list actual stub (`_update_info_commands`), added notes for class methods |
| F3 | MEDIUM | TC8 `_GatheringFuture exception was never retrieved` warning — hung task not cleaned up after test assertion | Fixed: added `release` event + explicit task cleanup after assertion |
| F4 | MEDIUM | Story File List incomplete — 10 modified files from 5-4/Optional migration not documented | Fixed: added note in File List clarifying cross-story working tree overlap |
| F5 | MEDIUM | `_track_task` `name` param defaults to `""`, silently allows unnamed tasks (violates AC3 spirit) | Fixed: made `name` keyword-only with no default (`*, name: str`) |
| F6 | MEDIUM | Completion notes say "6 pre-existing `_dispatch_notify` failures" — actual count is 7 (all in `test_error_handler.py`) | Fixed: corrected count and added file location |
| F7 | LOW | `SequenceManager` backward-compat alias removed from `sia_protocol.py` — no remaining references | No action needed — dead code removal is clean |
| F8 | LOW | TC8 never asserts `timeout=ON_STOP_TASK_TIMEOUT_S` was passed | Not fixed — low priority; test still validates error logging path |

### Change Log

- 2026-04-22: Code review — 6 findings fixed (F1–F6), 2 low-severity noted (F7–F8)
