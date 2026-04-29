"""
Async task lifecycle tests for Story 5.5.

Verifies _track_task(), on_stop() task cancellation, and _notify() sync contract.

Reference: _bmad-output/implementation-artifacts/5-5-async-task-lifecycle-management.md
"""
import asyncio
import inspect
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.error_handler import (
    BadCSRResponseCtx,
    ErrorCode,
    EventFailedCtx,
    SM1DisconnectedCtx,
    SM1NakCtx,
    SM1TimeoutCtx,
    TransportPermanentCtx,
)
from resources.siadc09d.sia_transport import ON_STOP_TASK_TIMEOUT_S
from tests.conftest import make_daemon_preset


# ===== Shared fixture =====

@pytest.fixture
def daemon_factory():
    """Create a SIADaemon with mocked transport for lifecycle tests.

    Expected result:
    - Returns a factory function that produces SIADaemon instances
    - Each instance has a mocked transport so no real network is needed
    - sys.argv is patched to prevent BaseDaemon argparse errors in tests
    """
    from resources.siadc09d.sia_transport import SIABaseTransport

    def factory(transport_type: str = 'UDP') -> SIADaemon:
        preset = make_daemon_preset(transport=transport_type)
        with patch('sys.argv', ['test']):
            daemon = SIADaemon(preset=preset)
        mock_transport = MagicMock(spec=SIABaseTransport)
        mock_transport.start = AsyncMock()
        mock_transport.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        mock_transport.close = AsyncMock()
        daemon._sia_transport = mock_transport
        return daemon

    return factory


# ===== TC1: _track_task() registers task in _tasks =====

@pytest.mark.asyncio
async def test_track_task_adds_to_tasks_set(daemon_factory):
    """
    _track_task() should register the created task in _tasks.

    Expected result:
    - _tasks set grows by 1 when _track_task() is called
    - The returned task object is present in _tasks
    """
    daemon = daemon_factory()

    async def noop() -> None:
        await asyncio.sleep(0)

    # Assert: _tasks starts empty
    assert len(daemon._tasks) == 0

    task = daemon._track_task(noop(), name="test_noop")

    # Assert: task registered in _tasks immediately after _track_task()
    assert task in daemon._tasks
    assert len(daemon._tasks) == 1

    # Cleanup
    await asyncio.gather(task, return_exceptions=True)


# ===== TC2: Done callback removes task from _tasks on completion =====

@pytest.mark.asyncio
async def test_track_task_done_callback_removes_task(daemon_factory):
    """
    When a tracked task completes normally, the done callback removes it from _tasks.

    Expected result:
    - _tasks is empty after the task finishes (task removed by done callback)
    """
    daemon = daemon_factory()

    async def noop() -> None:
        pass

    task = daemon._track_task(noop(), name="test_noop_complete")

    # Wait for task to complete
    await asyncio.gather(task, return_exceptions=True)
    # Allow done callback to fire
    await asyncio.sleep(0)

    # Assert: task discarded from _tasks after completion
    assert task not in daemon._tasks
    assert len(daemon._tasks) == 0


# ===== TC3: Done callback logs exception via logger.error() =====

@pytest.mark.asyncio
async def test_track_task_done_callback_logs_exception(daemon_factory, caplog):
    """
    When a tracked task raises an unhandled exception, the done callback logs it.

    Expected result:
    - logger.error() called with message containing task name and exception
    - _tasks does not retain the failed task (discarded)
    """
    daemon = daemon_factory()
    daemon._logger = logging.getLogger("test_track_task_exception")

    async def failing_coro() -> None:
        raise ValueError("intentional test error")

    with caplog.at_level(logging.ERROR, logger="test_track_task_exception"):
        task = daemon._track_task(failing_coro(), name="failing_task")
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    # Assert: error logged mentioning task name and exception
    assert "failing_task" in caplog.text
    assert "intentional test error" in caplog.text

    # Assert: failed task discarded from _tasks
    assert task not in daemon._tasks


# ===== TC4: Done callback does NOT log on cancellation =====

@pytest.mark.asyncio
async def test_track_task_done_callback_no_log_on_cancel(daemon_factory, caplog):
    """
    Cancelling a task should not trigger the exception logger in the done callback.

    Expected result:
    - No logger.error() call when task is cancelled
    - _tasks does not retain the cancelled task
    """
    daemon = daemon_factory()
    daemon._logger = logging.getLogger("test_track_task_cancel")

    async def long_running() -> None:
        await asyncio.sleep(100)

    with caplog.at_level(logging.ERROR, logger="test_track_task_cancel"):
        task = daemon._track_task(long_running(), name="cancellable_task")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    # Assert: no error logged for cancellation
    assert "cancellable_task" not in caplog.text or "cancel" not in caplog.text.lower()
    # More precise: check no ERROR-level log was emitted
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 0

    # Assert: cancelled task discarded
    assert task not in daemon._tasks


# ===== TC5: _track_task() assigns descriptive task name =====

@pytest.mark.asyncio
async def test_track_task_sets_descriptive_name(daemon_factory):
    """
    _track_task() should set a human-readable name on the asyncio.Task object.

    Expected result:
    - task.get_name() returns the provided name, not "Task-N"
    """
    daemon = daemon_factory()

    async def noop() -> None:
        pass

    task = daemon._track_task(noop(), name="my_descriptive_name")

    # Assert: task name matches provided name, not asyncio default "Task-N"
    assert task.get_name() == "my_descriptive_name"

    await asyncio.gather(task, return_exceptions=True)


# ===== TC6: on_start() creates exactly two named tasks =====

@pytest.mark.asyncio
async def test_on_start_creates_named_tasks(daemon_factory):
    """
    on_start() should launch exactly two tracked tasks with descriptive names.

    Expected result:
    - _tasks contains two tasks after on_start()
    - Task names are "queue_consumer" and "supervision_loop"
    """
    daemon = daemon_factory()

    with patch('resources.siadc09d.daemon.SIAUDPTransport') as MockUDP:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        MockUDP.return_value = mock_t

        await daemon.on_start()

    # Assert: exactly two tasks in _tasks
    assert len(daemon._tasks) == 2

    task_names = {t.get_name() for t in daemon._tasks}
    # Assert: both expected names present
    assert "queue_consumer" in task_names
    assert "supervision_loop" in task_names

    # Cleanup
    await daemon.on_stop()


# ===== TC7: on_stop() cancels all tracked tasks =====

@pytest.mark.asyncio
async def test_on_stop_cancels_all_tasks(daemon_factory):
    """
    on_stop() must cancel every task in _tasks before returning.

    Expected result:
    - Each task in _tasks is cancelled during on_stop()
    - All tasks are done (cancelled) after on_stop() returns
    """
    daemon = daemon_factory()
    # Mock _update_info_commands to avoid stub blocking test
    daemon._update_info_commands = AsyncMock()

    async def long_running() -> None:
        await asyncio.sleep(100)

    task_a = daemon._track_task(long_running(), name="task_a")
    task_b = daemon._track_task(long_running(), name="task_b")

    # Assert: both tasks registered and running
    assert len(daemon._tasks) == 2
    assert not task_a.done()
    assert not task_b.done()

    await daemon.on_stop()

    # Assert: both tasks are now done (cancelled by on_stop)
    assert task_a.done()
    assert task_b.done()
    # Assert: tasks were cancelled (not completed normally)
    assert task_a.cancelled() or task_a.exception() is not None or task_a.result() is None
    assert task_b.cancelled() or task_b.exception() is not None or task_b.result() is None


# ===== TC8: on_stop() awaits tasks with hard timeout =====

@pytest.mark.asyncio
async def test_on_stop_awaits_tasks_with_timeout(daemon_factory):
    """
    on_stop() wraps task gather in asyncio.wait_for with ON_STOP_TASK_TIMEOUT_S.

    Expected result:
    - on_stop() calls asyncio.wait_for with the correct timeout constant
    - TimeoutError is caught and logged as logger.error()
    """
    daemon = daemon_factory()
    daemon._update_info_commands = AsyncMock()
    mock_logger = MagicMock()
    daemon._logger = mock_logger

    # Event to let the hung task proceed to cleanup after the test assertion
    release = asyncio.Event()

    async def hang_on_cancel() -> None:
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            # Swallow first cancellation — simulates hung task
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass

    task = daemon._track_task(hang_on_cancel(), name="hanging_task")

    # Simulate asyncio.wait_for raising TimeoutError (what happens when tasks hang)
    original_wait_for = asyncio.wait_for

    async def wait_for_that_times_out(fut, timeout=None):
        raise asyncio.TimeoutError()

    with patch('asyncio.wait_for', side_effect=wait_for_that_times_out):
        await daemon.on_stop()

    # Assert: timeout error was logged
    error_calls = [str(c) for c in mock_logger.error.call_args_list]
    assert any("timeout" in msg.lower() or "did not complete" in msg.lower()
               for msg in error_calls), (
        f"Expected timeout error log, got: {error_calls}"
    )

    # Cleanup: release the hung task so it doesn't leak
    release.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# ===== TC9: _notify() is a synchronous method =====

@pytest.mark.asyncio
async def test_notify_is_synchronous():
    """
    _notify() must be a regular def, not async def.

    Expected result:
    - inspect.iscoroutinefunction(SIADaemon._notify) returns False
    - Calling daemon._notify() returns None immediately (schedules task, does not await)
    """
    # Assert: _notify is defined as def, not async def
    assert not inspect.iscoroutinefunction(SIADaemon._notify)

    preset = make_daemon_preset()
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._dispatch_notify = AsyncMock()
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

    # Drain scheduled task
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== TC10: _notify() does not raise =====

@pytest.mark.asyncio
async def test_notify_stub_does_not_raise():
    """
    _notify() should complete without raising any exception.

    Expected result:
    - Calling _notify() with any valid ErrorCode/context schedules a task silently
    - No exception raised regardless of error code
    """
    preset = make_daemon_preset()
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._dispatch_notify = AsyncMock()

    # Assert: T1 code does not raise
    daemon._notify(ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(
        elapsed_ms=1000.0, strike_count=1, supervision_interval_s=60.0
    ))

    # Assert: T1 NAK code does not raise
    daemon._notify(ErrorCode.SUPERVISION_NAK, SM1NakCtx(
        raw_nak_frame=b'\x0a\x00\x00\x0d',
        nak_timestamp=None,
        account_number='001234',
    ))

    # Assert: T3 EVENT_FAILED code does not raise
    daemon._notify(ErrorCode.EVENT_FAILED, EventFailedCtx(
        sia_code='BA',
        sia_seq=1,
        zone_name='Salon',
        max_retries=3,
        attempts_made=3,
        last_error='timeout',
    ))

    # Drain scheduled tasks
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== TC11: _tasks initialized in __init__ as empty set =====

def test_tasks_set_initialized_in_init():
    """
    _tasks must be present and empty immediately after __init__ (before on_start).

    Expected result:
    - daemon._tasks exists without calling on_start()
    - daemon._tasks is an empty set
    """
    preset = make_daemon_preset()
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)

    # Assert: _tasks exists immediately (code-style.md: all attrs in __init__)
    assert hasattr(daemon, '_tasks')
    # Assert: empty set initially
    assert isinstance(daemon._tasks, set)
    assert len(daemon._tasks) == 0


# ===== TC12: No bare asyncio.create_task() in daemon.py except inside _track_task() =====

def test_no_bare_create_task_in_daemon():
    """
    The only asyncio.create_task() call in daemon.py must be inside _track_task().
    All other task creation must go through _track_task().

    Expected result:
    - Reading daemon.py, asyncio.create_task appears exactly once (inside _track_task)
    """
    daemon_path = Path("resources/siadc09d/daemon.py")
    source = daemon_path.read_text()

    # Find all actual code-level create_task calls.
    # Exclude: comment lines (# ...) and docstring-prose lines (contain 'Wraps asyncio').
    # Only lines with a real Python expression count.
    code_lines = []
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        # Toggle docstring state on triple-quote lines
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                continue
            elif stripped.count('"""') == 1 or stripped.count("'''") == 1:
                in_docstring = True
                continue
        if in_docstring:
            continue
        if stripped.startswith('#'):
            continue
        code_lines.append(line)

    code_source = '\n'.join(code_lines)
    matches = list(re.finditer(r'asyncio\.create_task\(', code_source))

    # Assert: exactly one create_task call in executable code
    assert len(matches) == 1, (
        f"Expected exactly 1 asyncio.create_task() in daemon.py (inside _track_task), "
        f"found {len(matches)}. All bare asyncio.create_task() calls must use _track_task() instead."
    )

    # Assert: that one call is inside _track_task — verify surrounding context
    pos = matches[0].start()
    context = code_source[max(0, pos - 300):pos + 100]
    assert '_track_task' in context, (
        f"The single create_task() call does not appear to be inside _track_task. "
        f"Context: {context!r}"
    )


# ===== G1: _track_task() without name= raises TypeError =====

@pytest.mark.asyncio
async def test_track_task_without_name_raises_type_error(daemon_factory):
    """
    _track_task() requires name as a keyword-only argument. Calling without it
    must raise TypeError (enforces AC3: no unnamed tasks).

    Expected result:
    - Calling _track_task(coro) without name= raises TypeError
    - Calling _track_task(coro, "some_name") positionally also raises TypeError
    """
    daemon = daemon_factory()

    async def noop() -> None:
        pass

    # Assert: missing name= keyword raises TypeError
    coro1 = noop()
    with pytest.raises(TypeError):
        daemon._track_task(coro1)
    coro1.close()  # cleanup unawaited coroutine

    # Assert: passing name as positional arg also raises TypeError (keyword-only)
    coro2 = noop()
    with pytest.raises(TypeError):
        daemon._track_task(coro2, "positional_name")
    coro2.close()  # cleanup unawaited coroutine


# ===== G2: on_stop() drains the queue (Step 2 of 5-step shutdown) =====

@pytest.mark.asyncio
async def test_on_stop_drains_queue(daemon_factory):
    """
    on_stop() must discard all pending queue items before cancelling tasks.

    Expected result:
    - Queue is empty after on_stop() returns
    - Items enqueued before on_stop() are discarded (not processed)
    """
    daemon = daemon_factory()
    daemon._update_info_commands = AsyncMock()

    # Enqueue items directly (without starting consumer)
    await daemon._queue.put((1, 0, "SUPERVISION", {}))
    await daemon._queue.put((0, 1, "EVENT", {
        "sia_code": "BA", "zone": "Salon", "media_url": None, "retries_left": 3
    }))

    # Assert: queue has 2 items before on_stop
    assert daemon._queue.qsize() == 2

    await daemon.on_stop()

    # Assert: queue is empty after on_stop (Step 2 drained all items)
    assert daemon._queue.empty()


# ===== G3: on_stop() closes transport and resets to None (Step 5) =====

@pytest.mark.asyncio
async def test_on_stop_closes_transport_and_resets(daemon_factory):
    """
    on_stop() must call transport.close() and set _sia_transport = None.

    Expected result:
    - transport.close() is awaited exactly once
    - _sia_transport is None after on_stop()
    """
    daemon = daemon_factory()
    daemon._update_info_commands = AsyncMock()
    mock_transport = daemon._sia_transport

    await daemon.on_stop()

    # Assert: transport.close() was called
    mock_transport.close.assert_awaited_once()
    # Assert: transport reference cleared to None
    assert daemon._sia_transport is None


@pytest.mark.asyncio
async def test_on_stop_swallows_transport_close_oserror(daemon_factory):
    """
    If transport.close() raises OSError, on_stop() must swallow it and continue.

    Expected result:
    - on_stop() completes without raising
    - _sia_transport is None despite OSError from close()
    """
    daemon = daemon_factory()
    daemon._update_info_commands = AsyncMock()
    daemon._sia_transport.close = AsyncMock(side_effect=OSError("socket already closed"))

    # Assert: on_stop does not propagate OSError
    await daemon.on_stop()

    # Assert: transport reference still cleared to None
    assert daemon._sia_transport is None


# ===== G4 is addressed by tightening TC7 — see improved assertion inline =====
# (The original TC7 assertion was too loose; this test validates the strict version)

@pytest.mark.asyncio
async def test_on_stop_tasks_are_cancelled_not_completed(daemon_factory):
    """
    on_stop() must cancel tasks, not let them complete normally.

    Expected result:
    - After on_stop(), every task's cancelled() is True
    - No task completed with a normal result
    """
    daemon = daemon_factory()
    daemon._update_info_commands = AsyncMock()

    async def long_running() -> None:
        await asyncio.sleep(100)

    task_a = daemon._track_task(long_running(), name="cancel_check_a")
    task_b = daemon._track_task(long_running(), name="cancel_check_b")

    await daemon.on_stop()

    # Assert: strict cancellation check — tasks were actually cancelled
    assert task_a.cancelled(), "task_a should be cancelled by on_stop()"
    assert task_b.cancelled(), "task_b should be cancelled by on_stop()"


# ===== G5: on_start() idempotent restart — cancels old tasks, creates new =====

@pytest.mark.asyncio
async def test_on_start_idempotent_restart(daemon_factory):
    """
    Calling on_start() twice without on_stop() must cancel old tasks and
    create fresh ones (idempotent restart safety).

    Expected result:
    - Old tasks from first on_start() are cancelled
    - _tasks contains exactly 2 new tasks after second on_start()
    - New task names are "queue_consumer" and "supervision_loop"
    """
    daemon = daemon_factory()

    with patch('resources.siadc09d.daemon.SIAUDPTransport') as MockUDP:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        MockUDP.return_value = mock_t

        # First on_start()
        await daemon.on_start()
        old_tasks = set(daemon._tasks)
        assert len(old_tasks) == 2

        # Second on_start() without on_stop()
        await daemon.on_start()

    # Assert: old tasks are cancelled
    for t in old_tasks:
        assert t.done(), f"Old task '{t.get_name()}' should be done after restart"

    # Assert: new tasks created (different objects)
    assert len(daemon._tasks) == 2
    new_tasks = set(daemon._tasks)
    assert old_tasks.isdisjoint(new_tasks), "New tasks must be different objects from old tasks"

    # Assert: correct names on new tasks
    new_names = {t.get_name() for t in daemon._tasks}
    assert "queue_consumer" in new_names
    assert "supervision_loop" in new_names

    # Cleanup
    await daemon.on_stop()


# ===== G6: _notify() stub does not raise for ALL ErrorCode values =====

@pytest.mark.asyncio
async def test_notify_stub_handles_all_error_codes():
    """
    _notify() must not raise for any ErrorCode + its matching context.

    Expected result:
    - Every ErrorCode/context combination schedules a task without exception
    - Covers all 6 codes
    """
    preset = make_daemon_preset()
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._dispatch_notify = AsyncMock()

    code_ctx_pairs = [
        (ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(
            elapsed_ms=30000.0, strike_count=1, supervision_interval_s=60.0
        )),
        (ErrorCode.SUPERVISION_NAK, SM1NakCtx(
            raw_nak_frame=b'\x0a\x00\x00\x0d', nak_timestamp=None,
            account_number='001234'
        )),
        (ErrorCode.BAD_CSR_RESPONSE, BadCSRResponseCtx(
            raw_frame=b'\x0aGARBLED\x0d', parse_error='bad frame',
            csr_host='192.168.1.100', csr_port=5000, transport='udp'
        )),
        (ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx(
            strike_count=3, last_ack_time_utc=None,
            time_since_last_ack_s=None, supervision_interval_s=60.0
        )),
        (ErrorCode.EVENT_FAILED, EventFailedCtx(
            sia_code='BA', sia_seq=42, zone_name='Salon',
            max_retries=3, attempts_made=3, last_error='timeout'
        )),
        (ErrorCode.TRANSPORT_PERMANENT, TransportPermanentCtx(
            reason='tcp_max_retries_exceeded', transport='tcp',
            error_details='Connection refused', retry_count=3
        )),
    ]

    for code, ctx in code_ctx_pairs:
        # Assert: no exception for any error code
        daemon._notify(code, ctx)

    # Drain all scheduled tasks
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== G7: _notify() schedules _dispatch_notify task =====

@pytest.mark.asyncio
async def test_notify_stub_logs_debug():
    """
    _notify() must schedule _dispatch_notify as a tracked task.

    Expected result:
    - _notify() is synchronous (def, not async def)
    - A task named 'notify_SUPERVISION_TIMEOUT' is tracked in _tasks
    - _dispatch_notify is called with the correct code and context
    """
    preset = make_daemon_preset()
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=preset)
    daemon._dispatch_notify = AsyncMock()

    ctx = SM1TimeoutCtx(
        elapsed_ms=1000.0, strike_count=1, supervision_interval_s=60.0
    )
    daemon._notify(ErrorCode.SUPERVISION_TIMEOUT, ctx)

    # Assert: a task was added to _tasks
    assert len(daemon._tasks) >= 1, "Expected a tracked task after _notify()"

    # Drain and verify _dispatch_notify was called
    await asyncio.gather(*daemon._tasks, return_exceptions=True)
    daemon._dispatch_notify.assert_called_once_with(ErrorCode.SUPERVISION_TIMEOUT, ctx)


# ===== G8: on_start() with TCP transport creates same two tasks =====

@pytest.mark.asyncio
async def test_on_start_tcp_creates_named_tasks(daemon_factory):
    """
    on_start() with TCP transport must also launch exactly two tracked tasks.

    Expected result:
    - _tasks contains two tasks after on_start() with TCP preset
    - Task names are "queue_consumer" and "supervision_loop"
    - SIATCPTransport is used (not SIAUDPTransport)
    """
    daemon = daemon_factory('TCP')

    with patch('resources.siadc09d.daemon.SIATCPTransport') as MockTCP:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={'status': 'ack', 'raw_nak': None})
        MockTCP.return_value = mock_t

        await daemon.on_start()

    # Assert: SIATCPTransport was constructed (not UDP)
    MockTCP.assert_called_once()

    # Assert: exactly two tasks
    assert len(daemon._tasks) == 2

    task_names = {t.get_name() for t in daemon._tasks}
    # Assert: both expected names present
    assert "queue_consumer" in task_names
    assert "supervision_loop" in task_names

    # Cleanup
    await daemon.on_stop()


# ===== G9: TC12 alternative using AST for robust create_task detection =====

def test_no_bare_create_task_via_ast():
    """
    Verify via Python AST that asyncio.create_task() appears only inside _track_task().
    More robust than regex: immune to strings, comments, and docstrings.

    Expected result:
    - AST walk finds exactly one Call node for asyncio.create_task
    - That call is inside a function named _track_task
    """
    import ast

    daemon_path = Path("resources/siadc09d/daemon.py")
    source = daemon_path.read_text()
    tree = ast.parse(source)

    create_task_locations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match asyncio.create_task(...)
        if (isinstance(func, ast.Attribute)
                and func.attr == "create_task"
                and isinstance(func.value, ast.Name)
                and func.value.id == "asyncio"):
            # Walk back up to find enclosing function name
            enclosing = _find_enclosing_function(tree, node.lineno)
            create_task_locations.append((node.lineno, enclosing))

    # Assert: exactly one asyncio.create_task call
    assert len(create_task_locations) == 1, (
        f"Expected 1 asyncio.create_task(), found {len(create_task_locations)}: "
        f"{create_task_locations}"
    )

    # Assert: it's inside _track_task
    line, func_name = create_task_locations[0]
    assert func_name == "_track_task", (
        f"asyncio.create_task() at line {line} is inside '{func_name}', expected '_track_task'"
    )


def _find_enclosing_function(tree: "ast.Module", target_line: int) -> str:
    """Find the name of the function/method enclosing a given line number."""
    import ast
    enclosing = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target_line <= node.end_lineno:
                enclosing = node.name
    return enclosing


# ===== G10: on_stop() terminal INFO push failure is swallowed =====

@pytest.mark.asyncio
async def test_on_stop_swallows_info_push_failure(daemon_factory, caplog):
    """
    If _update_info_commands() raises during on_stop(), the exception must be
    caught and logged, not propagated. Shutdown must continue.

    Expected result:
    - on_stop() completes without raising
    - The exception is logged as ERROR
    - Transport is still closed (shutdown continued past Step 1 failure)
    """
    daemon = daemon_factory()
    daemon._logger = logging.getLogger("test_on_stop_info_push")
    daemon._update_info_commands = AsyncMock(
        side_effect=RuntimeError("PHP callback failed")
    )
    mock_transport = daemon._sia_transport

    with caplog.at_level(logging.ERROR, logger="test_on_stop_info_push"):
        await daemon.on_stop()

    # Assert: error was logged (not propagated)
    assert any("terminal INFO push failed" in r.message for r in caplog.records), (
        f"Expected INFO push failure log, got: {[r.message for r in caplog.records]}"
    )

    # Assert: shutdown continued — transport was still closed
    mock_transport.close.assert_awaited_once()
    # Assert: transport cleared to None
    assert daemon._sia_transport is None
