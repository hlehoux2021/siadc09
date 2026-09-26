"""Story 14-2/14-4 (ADR-17 Amendment 3/4, Option D) — daemon-side prefetchEvent dispatch.

Tests cover:
- on_message("prefetchEvent", ...) spawns a tracked background task and returns
  before the Frigate REST call resolves (fire-and-forget, never awaited)
- the tracked task's on_result callback pushes _send_callback() with the exact
  "prefetch_result" shape on every improvement — including int 0/1 for "found"/
  "clip_found", "rank" as an int, and "run_id" echoed back verbatim (Story 14-4)
- missing required params (including the new run_id) are rejected without spawning a
  task or sending anything
- an unknown alarm command (the pre-existing branch) is unaffected by the new branch

Test level: Level 2 (async, no Jeedom required)
Framework: pytest-asyncio
Reference: _bmad-output/implementation-artifacts/14-4-best-effort-alarm-media-forced-capture.md
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SIADaemon, SM1State, SM2State
from resources.siadc09d.frigate_prefetch import RANK_MANUAL, RANK_NONE, RANK_PERSON, PrefetchResult
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


_BASE_PARAMS = {
    "camera_eqlogic_id": 42,
    "camera_name": "vigi_sud-est",
    "frigate_host": "192.168.100.18:5000",
    "run_id": "1790193160.123456",
}


class TestPrefetchEventDispatch:
    """on_message("prefetchEvent", ...) — Task 4.2/4.3, extended by Story 14-4 Task 3.2."""

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

        async def _slow_prefetch(base_url, camera, on_result, **_kwargs) -> PrefetchResult:
            await release_gate.wait()
            return PrefetchResult(found=True, event_id="evt-1", rank=RANK_PERSON)

        with patch("resources.siadc09d.daemon.prefetch_alarm_media", side_effect=_slow_prefetch):
            await mock_daemon.on_message("prefetchEvent", dict(_BASE_PARAMS))
            # Assert: on_message returned even though the network call is still blocked
            assert len(mock_daemon._tasks) == 1
            release_gate.set()
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: the task completed and removed itself from _tasks (existing _track_task contract)
        assert len(mock_daemon._tasks) == 0

    @pytest.mark.asyncio
    async def test_on_result_callback_pushes_expected_shape_with_rank_and_run_id(self, mock_daemon) -> None:
        """
        Story 14-4: each PrefetchResult improvement pushed via on_result must carry the
        full new shape — int 0/1 for found/clip_found (never a Python bool —
        _send_callback() drops any payload containing one), rank as an int, and run_id
        echoed back verbatim from the incoming params.

        Expected result:
        - _send_callback called once with the exact expected payload shape
        """
        async def _fake_prefetch(base_url, camera, on_result, **_kwargs) -> PrefetchResult:
            result = PrefetchResult(
                found=True, event_id="1790193165.543115-0e6wzj", clip_found=True, rank=RANK_PERSON
            )
            await on_result(result)
            return result

        with patch("resources.siadc09d.daemon.prefetch_alarm_media", side_effect=_fake_prefetch):
            await mock_daemon.on_message("prefetchEvent", dict(_BASE_PARAMS))
            await asyncio.gather(*mock_daemon._tasks)

        # Assert: exactly one callback push, with the expected shape
        mock_daemon._send_callback.assert_awaited_once_with({
            "type": "prefetch_result",
            "camera_eqlogic_id": 42,
            "found": 1,
            "event_id": "1790193165.543115-0e6wzj",
            "clip_found": 1,
            "rank": RANK_PERSON,
            "run_id": "1790193160.123456",
        })
        # Assert: found/clip_found are real ints, never Python bools (would be silently dropped)
        sent_payload = mock_daemon._send_callback.await_args.args[0]
        assert type(sent_payload["found"]) is int
        assert type(sent_payload["clip_found"]) is int
        assert type(sent_payload["rank"]) is int
        assert isinstance(sent_payload["run_id"], str)

    @pytest.mark.asyncio
    async def test_multiple_improvements_push_multiple_ordered_callbacks(self, mock_daemon) -> None:
        """
        Story 14-4: a run with several rank improvements (manual, then person) must push
        one _send_callback() call per improvement, in order, all sharing the same run_id.

        Expected result:
        - _send_callback awaited twice, ranks in order [RANK_MANUAL, RANK_PERSON]
        - both calls carry the same run_id
        """
        async def _fake_prefetch(base_url, camera, on_result, **_kwargs) -> PrefetchResult:
            manual = PrefetchResult(found=True, event_id="evt-manual-1", clip_found=True, rank=RANK_MANUAL)
            await on_result(manual)
            person = PrefetchResult(found=True, event_id="evt-person-1", clip_found=True, rank=RANK_PERSON)
            await on_result(person)
            return person

        with patch("resources.siadc09d.daemon.prefetch_alarm_media", side_effect=_fake_prefetch):
            await mock_daemon.on_message("prefetchEvent", dict(_BASE_PARAMS))
            await asyncio.gather(*mock_daemon._tasks)

        assert mock_daemon._send_callback.await_count == 2
        sent_ranks = [call.args[0]["rank"] for call in mock_daemon._send_callback.await_args_list]
        assert sent_ranks == [RANK_MANUAL, RANK_PERSON]
        sent_run_ids = [call.args[0]["run_id"] for call in mock_daemon._send_callback.await_args_list]
        assert sent_run_ids == ["1790193160.123456", "1790193160.123456"]

    @pytest.mark.asyncio
    async def test_sends_miss_result_with_rank_none(self, mock_daemon) -> None:
        """
        Story 14-4 AC9: a run that finds nothing at all pushes exactly one final miss
        callback with rank=RANK_NONE (replacing 14-2 AC5's "always send a result").

        Expected result:
        - _send_callback called once with found=0, event_id="", clip_found=0, rank=4
        """
        async def _fake_prefetch(base_url, camera, on_result, **_kwargs) -> PrefetchResult:
            miss = PrefetchResult(found=False, event_id=None, clip_found=False, rank=RANK_NONE)
            await on_result(miss)
            return miss

        with patch("resources.siadc09d.daemon.prefetch_alarm_media", side_effect=_fake_prefetch):
            await mock_daemon.on_message("prefetchEvent", dict(_BASE_PARAMS))
            await asyncio.gather(*mock_daemon._tasks)

        mock_daemon._send_callback.assert_awaited_once_with({
            "type": "prefetch_result",
            "camera_eqlogic_id": 42,
            "found": 0,
            "event_id": "",
            "clip_found": 0,
            "rank": RANK_NONE,
            "run_id": "1790193160.123456",
        })

    @pytest.mark.asyncio
    async def test_missing_run_id_never_spawns_task_or_sends_callback(self, mock_daemon) -> None:
        """
        Story 14-4: run_id is now required — without it (or camera identity), a
        malformed prefetchEvent message must be rejected immediately.

        Expected result:
        - no task added to daemon._tasks
        - _send_callback never called
        """
        with patch("resources.siadc09d.daemon.prefetch_alarm_media") as mock_prefetch:
            await mock_daemon.on_message(
                "prefetchEvent",
                {"camera_eqlogic_id": 42, "camera_name": "vigi_sud-est", "frigate_host": "192.168.100.18:5000"},
            )
            # Assert: nothing was spawned for a payload missing run_id
            assert len(mock_daemon._tasks) == 0
            mock_prefetch.assert_not_called()
        mock_daemon._send_callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_camera_params_never_spawns_task_or_sends_callback(self, mock_daemon) -> None:
        """
        A malformed prefetchEvent message (missing camera identity) must be rejected
        immediately — no task spawned, no network call, no callback push.

        Expected result:
        - no task added to daemon._tasks
        - _send_callback never called
        """
        with patch("resources.siadc09d.daemon.prefetch_alarm_media") as mock_prefetch:
            await mock_daemon.on_message(
                "prefetchEvent", {"camera_eqlogic_id": 42, "run_id": "1790193160.123456"}
            )
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
