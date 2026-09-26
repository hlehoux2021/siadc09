"""Story 14-2 (ADR-17 Amendment 3, Option D) — daemon-side prefetchEvent dispatch.

Tests cover:
- on_message("prefetchEvent", ...) spawns a tracked background task and returns
  before the Frigate REST call resolves (fire-and-forget, never awaited)
- the tracked task calls _send_callback() with the exact "prefetch_result" shape on
  both a confirmed hit and a miss — including int 0/1 for "found", never a Python bool
- missing required params are rejected without spawning a task or sending anything
- an unknown alarm command (the pre-existing branch) is unaffected by the new branch

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SIADaemon, SM1State, SM2State
from resources.siadc09d.frigate_prefetch import PrefetchResult
from tests.conftest import make_daemon_preset


@pytest.fixture
def mock_daemon():
    """Create a SIADaemon instance with mocked transport/callback plumbing."""
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=make_daemon_preset())

    daemon._logger = MagicMock()
    daemon._preset = MagicMock(
        crc_format="SIA",
        supervision_interval_s=10,
        encryption_enabled=False,
        max_retries=3,
    )
    daemon._account = "001234"
    daemon._receiver_prefix = None
    daemon._account_prefix = "L0"
    daemon._sia_seq = 0
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._encryption_key = b""
    daemon._transport = "UDP"
    daemon._sm1_state = SM1State.HEALTHY
    daemon._sm2_state = SM2State.IDLE
    daemon._strike_counter = 0
    daemon._sm1_t3_fired = False
    daemon._last_supervision_ack = None
    daemon._send_callback = AsyncMock()

    return daemon


class TestPrefetchEventDispatch:
    """on_message("prefetchEvent", ...) — Task 4.2/4.3."""

    @pytest.mark.asyncio
    async def test_spawns_tracked_task_and_returns_before_network_resolves(self, mock_daemon) -> None:
        """
        on_message() must never await the Frigate REST call itself — it hands off to a
        tracked background task and returns immediately.

        Expected result:
        - on_message() completes while the mocked network call is still pending
        - the spawned task is present in daemon._tasks while pending
        """
        release_gate = asyncio.Event()

        async def _slow_prefetch(*_args, **_kwargs) -> PrefetchResult:
            await release_gate.wait()
            return PrefetchResult(found=True, event_id="evt-1")

        with patch("resources.siadc09d.daemon.prefetch_person_event", side_effect=_slow_prefetch):
            await mock_daemon.on_message(
                "prefetchEvent",
                {"camera_eqlogic_id": 42, "camera_name": "vigi_sud-est", "frigate_host": "192.168.100.18:5000"},
            )
            # Assert: on_message returned even though the network call is still blocked
            assert len(mock_daemon._tasks) == 1
            release_gate.set()
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: the task completed and removed itself from _tasks (existing _track_task contract)
        assert len(mock_daemon._tasks) == 0

    @pytest.mark.asyncio
    async def test_sends_hit_result_with_int_found_flag(self, mock_daemon) -> None:
        """
        A confirmed Frigate person event must push found=1 (int, never a Python bool —
        _send_callback() drops any payload containing a bool value) with the event id.

        Expected result:
        - _send_callback called once with type=prefetch_result, found=1, the event id
        """
        with patch(
            "resources.siadc09d.daemon.prefetch_person_event",
            new=AsyncMock(return_value=PrefetchResult(
                found=True, event_id="1790193165.543115-0e6wzj", clip_found=True
            )),
        ):
            await mock_daemon.on_message(
                "prefetchEvent",
                {"camera_eqlogic_id": 42, "camera_name": "vigi_sud-est", "frigate_host": "192.168.100.18:5000"},
            )
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: exactly one callback push, with the expected shape
        mock_daemon._send_callback.assert_awaited_once_with({
            "type": "prefetch_result",
            "camera_eqlogic_id": 42,
            "found": 1,
            "event_id": "1790193165.543115-0e6wzj",
            "clip_found": 1,
        })
        # Assert: found/clip_found are real ints, never Python bools (would be silently dropped)
        sent_payload = mock_daemon._send_callback.await_args.args[0]
        assert type(sent_payload["found"]) is int
        assert type(sent_payload["clip_found"]) is int

    @pytest.mark.asyncio
    async def test_sends_hit_result_with_person_found_but_clip_not_ready(self, mock_daemon) -> None:
        """
        Story 14-3, AC1/AC2: a confirmed person event whose clip never became ready must
        still push found=1 with clip_found=0 — the two outcomes are independent.

        Expected result:
        - _send_callback called once with found=1, clip_found=0 (both real ints)
        """
        with patch(
            "resources.siadc09d.daemon.prefetch_person_event",
            new=AsyncMock(return_value=PrefetchResult(
                found=True, event_id="1790193165.543115-0e6wzj", clip_found=False
            )),
        ):
            await mock_daemon.on_message(
                "prefetchEvent",
                {"camera_eqlogic_id": 42, "camera_name": "vigi_sud-est", "frigate_host": "192.168.100.18:5000"},
            )
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: person hit is unaffected by the clip miss, clip_found is explicitly 0
        mock_daemon._send_callback.assert_awaited_once_with({
            "type": "prefetch_result",
            "camera_eqlogic_id": 42,
            "found": 1,
            "event_id": "1790193165.543115-0e6wzj",
            "clip_found": 0,
        })
        sent_payload = mock_daemon._send_callback.await_args.args[0]
        assert type(sent_payload["clip_found"]) is int

    @pytest.mark.asyncio
    async def test_sends_miss_result_so_php_clears_any_stale_hit(self, mock_daemon) -> None:
        """
        AC5: every prefetch outcome, including a miss, must overwrite PHP's per-camera
        cache entry — a miss is a real, meaningful result, not a "nothing happened" case.

        Expected result:
        - _send_callback called once with found=0, event_id=""
        """
        with patch(
            "resources.siadc09d.daemon.prefetch_person_event",
            new=AsyncMock(return_value=PrefetchResult(found=False, event_id=None, clip_found=False)),
        ):
            await mock_daemon.on_message(
                "prefetchEvent",
                {"camera_eqlogic_id": 42, "camera_name": "vigi_sud-est", "frigate_host": "192.168.100.18:5000"},
            )
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: a miss is still actively pushed (never silently skipped) — clip_found=0 always on a miss
        mock_daemon._send_callback.assert_awaited_once_with({
            "type": "prefetch_result",
            "camera_eqlogic_id": 42,
            "found": 0,
            "event_id": "",
            "clip_found": 0,
        })

    @pytest.mark.asyncio
    async def test_missing_params_never_spawns_task_or_sends_callback(self, mock_daemon) -> None:
        """
        A malformed prefetchEvent message (missing camera identity) must be rejected
        immediately — no task spawned, no network call, no callback push.

        Expected result:
        - no task added to daemon._tasks
        - _send_callback never called
        """
        with patch("resources.siadc09d.daemon.prefetch_person_event") as mock_prefetch:
            await mock_daemon.on_message("prefetchEvent", {"camera_eqlogic_id": 42})
            # Assert: nothing was spawned for an incomplete payload
            assert len(mock_daemon._tasks) == 0
            mock_prefetch.assert_not_called()
        mock_daemon._send_callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_command_still_warns_and_is_unaffected(self, mock_daemon) -> None:
        """
        The pre-existing "unknown alarm command" branch must still work for any command
        that isn't prefetchEvent/burglarAlarm/fireAlarm/panicAlarm — the new branch must
        not have swallowed or short-circuited it.

        Expected result:
        - a warning is logged, no task spawned, no callback sent
        """
        await mock_daemon.on_message("totallyUnknownCommand", {})
        # Assert: existing unknown-command warning path still fires
        mock_daemon._logger.warning.assert_called_once()
        assert len(mock_daemon._tasks) == 0
        mock_daemon._send_callback.assert_not_awaited()
