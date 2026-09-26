"""
Tests for resources/siadc09d/frigate_prefetch.py — Story 14-4 (ADR-17 Amendment 4).

Verifies the Frigate REST alarm-media prefetch module: forced-capture create first, the
any-label search and its exclusion/ranking rules, the incremental callback sequence, and
that any HTTP/network failure degrades cleanly rather than raising — no synchronous PHP
code ever awaits this, but the daemon's own tracked task must never crash from it either.

Story 14-2's `prefetch_person_event()`/`_query_latest_person_event()` are superseded by
`prefetch_alarm_media()`/`_query_candidate_events()` and removed along with their tests;
`_check_clip_ready()` is unchanged and kept. `_poll_clip_ready()` is removed: the new
orchestrator interleaves the clip check with the any-label search itself (a person event
can still appear after a non-person one is chosen), so a separate blocking poll no longer
fits.

Reference: _bmad-output/implementation-artifacts/14-4-best-effort-alarm-media-forced-capture.md
Reference: ADR-17, Amendment 4, _bmad-output/planning-artifacts/architecture.md
"""
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "resources" / "siadc09d"))

import frigate_prefetch  # noqa: E402
from frigate_prefetch import PrefetchResult  # noqa: E402


def _manual_ok(event_id: str = "1790200000.000000-alarm1") -> tuple[str | None, int | None]:
    return event_id, 200


def _manual_fail(status: int | None = 401) -> tuple[str | None, int | None]:
    return None, status


class _ResultCollector:
    """Awaitable on_result callback that records every PrefetchResult it receives."""

    def __init__(self) -> None:
        self.calls: list[PrefetchResult] = []

    async def __call__(self, result: PrefetchResult) -> None:
        self.calls.append(result)


# ── AC1/AC2 — forced capture first, early rank-3 push ───────────────────────────


@pytest.mark.asyncio
async def test_create_called_before_first_events_query() -> None:
    """
    AC1: the manual event create call happens before any `/api/events` poll.

    Expected result:
    - _create_manual_event is called, and by the time _query_candidate_events is first
      called, the create call has already returned
    """
    call_order: list[str] = []

    def _fake_create(base_url: str, camera: str, timeout: float) -> tuple[str | None, int | None]:
        call_order.append("create")
        return _manual_ok()

    def _fake_query(base_url: str, camera: str, after_ts: int, timeout: float) -> list[dict]:
        call_order.append("query")
        return []

    on_result = _ResultCollector()
    with patch.object(frigate_prefetch, "_create_manual_event", side_effect=_fake_create), patch.object(
        frigate_prefetch, "_query_candidate_events", side_effect=_fake_query
    ):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.2, poll_interval_s=0.05,
        )
    assert call_order[0] == "create"
    assert "query" in call_order


@pytest.mark.asyncio
async def test_create_url_and_body_match_frigate_contract() -> None:
    """
    AC1: POST /api/events/{camera}/alarm/create with duration=30, include_recording=true.

    Expected result:
    - the exact URL and JSON body sent to _post_json
    """
    captured: list[tuple[str, dict]] = []

    def _fake_post(url: str, body: dict, timeout: float) -> tuple[int, dict]:
        captured.append((url, body))
        return 200, {"success": True, "event_id": "evt-manual-1"}

    with patch.object(frigate_prefetch, "_post_json", side_effect=_fake_post):
        event_id, status = frigate_prefetch._create_manual_event(
            "http://192.168.100.18:5000", "vigi_sud-est", 5.0
        )
    assert event_id == "evt-manual-1"
    assert status == 200
    assert len(captured) == 1
    url, body = captured[0]
    assert url == "http://192.168.100.18:5000/api/events/vigi_sud-est/alarm/create"
    assert body == {"duration": 30, "include_recording": True}


@pytest.mark.asyncio
async def test_manual_event_pushed_immediately_with_clip_found_true() -> None:
    """
    AC2/AC7: the manual event (rank 3) is pushed to on_result right after create succeeds,
    with clip_found=True straight away (Decision 6 — unlike ranks 1/2, never waiting for
    Frigate's own clip-readiness confirmation).

    Expected result:
    - first on_result call is rank=3, found=True, clip_found=True, the manual event id
    """
    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_ok("evt-manual-1")
    ), patch.object(frigate_prefetch, "_query_candidate_events", return_value=[]):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.15, poll_interval_s=0.05,
        )
    assert on_result.calls[0] == PrefetchResult(
        found=True, event_id="evt-manual-1", clip_found=True, rank=frigate_prefetch.RANK_MANUAL
    )


@pytest.mark.asyncio
async def test_create_failure_skips_rank3_push_and_continues_search() -> None:
    """
    AC9: a refused/failed create call (401/403, timeout, Frigate down) logs a warning,
    pushes no rank-3 callback, and the any-label search still runs.

    Expected result:
    - no PrefetchResult with rank=RANK_MANUAL is ever emitted
    - _query_candidate_events is still called
    """
    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail(401)
    ), patch.object(frigate_prefetch, "_query_candidate_events", return_value=[]) as mock_query:
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.15, poll_interval_s=0.05,
        )
    assert all(c.rank != frigate_prefetch.RANK_MANUAL for c in on_result.calls)
    assert mock_query.call_count >= 1


# ── AC3 — any-label query shape and exclusion ───────────────────────────────────


def test_query_candidate_events_sends_expected_params_without_label_filter() -> None:
    """
    AC3: no label filter, has_snapshot=1, sort=date_desc, a bounded limit, and NOT
    in_progress (memory: frigate-rest-in-progress-filter-unreliable).

    Expected result:
    - the requested URL contains camera, after, has_snapshot=1, sort=date_desc, limit
    - it never contains label= or in_progress
    """
    captured_urls: list[str] = []

    def _fake_get_json(url: str, timeout: float) -> object | None:
        captured_urls.append(url)
        return []

    with patch.object(frigate_prefetch, "_get_json", side_effect=_fake_get_json):
        frigate_prefetch._query_candidate_events("http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0)
    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "camera=vigi_sud-est" in url
    assert "after=1000" in url
    assert "has_snapshot=1" in url
    assert "sort=date_desc" in url
    assert f"limit={frigate_prefetch.EVENTS_QUERY_LIMIT}" in url
    assert "label=" not in url
    assert "in_progress" not in url


def test_query_candidate_events_excludes_manual_alarm_label() -> None:
    """
    AC3/AC4: a row labelled "alarm" (the forced-capture manual event, including one left
    over from an earlier trip on the same camera) is dropped.

    Expected result:
    - excluded even though it has a snapshot
    """
    rows = [{"id": "evt-manual", "label": "alarm", "has_snapshot": True, "data": {"type": "api"}}]
    with patch.object(frigate_prefetch, "_get_json", return_value=rows):
        result = frigate_prefetch._query_candidate_events(
            "http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0
        )
    assert result == []


def test_query_candidate_events_excludes_via_type_api_backstop_even_with_other_label() -> None:
    """
    AC3: the `data.type == "api"` backstop drops a manual event even if its label were
    ever something other than "alarm".

    Expected result:
    - a row with label="person" but data.type="api" is excluded
    """
    rows = [{"id": "evt-x", "label": "person", "has_snapshot": True, "data": {"type": "api"}}]
    with patch.object(frigate_prefetch, "_get_json", return_value=rows):
        result = frigate_prefetch._query_candidate_events(
            "http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0
        )
    assert result == []


def test_query_candidate_events_excludes_rows_without_snapshot() -> None:
    """
    Expected result:
    - a real, non-manual row missing has_snapshot is excluded
    """
    rows = [{"id": "evt-x", "label": "cat", "has_snapshot": False, "data": {"type": "object"}}]
    with patch.object(frigate_prefetch, "_get_json", return_value=rows):
        result = frigate_prefetch._query_candidate_events(
            "http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0
        )
    assert result == []


def test_query_candidate_events_keeps_real_events_and_tolerates_missing_data() -> None:
    """
    Expected result:
    - a real event with has_snapshot=True and no "data" key at all is kept (never crashes
      on a missing/malformed data field)
    """
    rows = [{"id": "evt-cat", "label": "cat", "has_snapshot": True}]
    with patch.object(frigate_prefetch, "_get_json", return_value=rows):
        result = frigate_prefetch._query_candidate_events(
            "http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0
        )
    assert result == rows


def test_query_candidate_events_malformed_response_resolves_to_empty_list() -> None:
    """
    Expected result:
    - a non-list body, or a list with non-dict items, resolves to [] — never raises
    """
    for malformed_body in ({"error": "bad request"}, ["not-a-dict"], None):
        with patch.object(frigate_prefetch, "_get_json", return_value=malformed_body):
            result = frigate_prefetch._query_candidate_events(
                "http://192.168.100.18:5000", "vigi_sud-est", 1000, 5.0
            )
        assert result == [], f"expected [] for body={malformed_body!r}"


# ── AC4 — ranking and most-recent tie-break ──────────────────────────────────────


def test_best_candidate_person_beats_more_recent_other_label() -> None:
    """
    Expected result:
    - a person event wins over a more recent cat event
    """
    rows = [
        {"id": "evt-cat", "label": "cat", "start_time": 200.0},
        {"id": "evt-person", "label": "person", "start_time": 100.0},
    ]
    assert frigate_prefetch._best_candidate(rows) == (frigate_prefetch.RANK_PERSON, "evt-person")


def test_best_candidate_most_recent_wins_among_same_rank() -> None:
    """
    Expected result:
    - among two "other label" events, the one with the later start_time wins
    """
    rows = [
        {"id": "evt-dog", "label": "dog", "start_time": 100.0},
        {"id": "evt-cat", "label": "cat", "start_time": 200.0},
    ]
    assert frigate_prefetch._best_candidate(rows) == (frigate_prefetch.RANK_OTHER, "evt-cat")


def test_best_candidate_empty_or_no_usable_id_returns_none() -> None:
    """
    Expected result:
    - an empty list, or rows with no usable "id" field, return None — never raises
    """
    assert frigate_prefetch._best_candidate([]) is None
    assert frigate_prefetch._best_candidate([{"label": "cat", "start_time": 1.0}]) is None
    assert frigate_prefetch._best_candidate([{"id": "", "label": "cat"}]) is None


# ── AC4/AC5 — orchestration: incremental callbacks, no same-rank switch ─────────


@pytest.mark.asyncio
async def test_rank_improves_3_to_2_to_1_pushes_three_callbacks() -> None:
    """
    AC4/AC5: rank improves strictly across polls — manual (3), then a cat (2), then a
    person (1) — each improvement pushes exactly one callback, in order.

    Expected result:
    - on_result receives rank sequence [3, 2, 1] (clip_found handled by other tests)
    """
    query_results = iter([
        [],
        [{"id": "evt-cat", "label": "cat", "has_snapshot": True, "start_time": 10.0}],
        [
            {"id": "evt-cat", "label": "cat", "has_snapshot": True, "start_time": 10.0},
            {"id": "evt-person", "label": "person", "has_snapshot": True, "start_time": 20.0},
        ],
    ])

    def _fake_query(base_url: str, camera: str, after_ts: int, timeout: float) -> list[dict]:
        return next(query_results, [
            {"id": "evt-cat", "label": "cat", "has_snapshot": True, "start_time": 10.0},
            {"id": "evt-person", "label": "person", "has_snapshot": True, "start_time": 20.0},
        ])

    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_ok("evt-manual-1")
    ), patch.object(frigate_prefetch, "_query_candidate_events", side_effect=_fake_query), patch.object(
        frigate_prefetch, "_check_clip_ready", return_value=True
    ):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=1.0, poll_interval_s=0.05,
        )
    # Dedupe consecutive same-rank clip-upgrade calls; only the first appearance of each
    # rank matters for the "3 -> 2 -> 1" improvement sequence.
    ranks = [c.rank for c in on_result.calls]
    first_seen_ranks = list(dict.fromkeys(ranks))
    assert first_seen_ranks == [frigate_prefetch.RANK_MANUAL, frigate_prefetch.RANK_OTHER, frigate_prefetch.RANK_PERSON]


@pytest.mark.asyncio
async def test_same_rank_different_event_never_replaces_chosen_one() -> None:
    """
    AC4: within a run, a later poll returning a different but same-rank event never
    replaces the one already chosen.

    Expected result:
    - after the first cat is chosen (rank 2), a second, different cat appearing later
      produces no additional rank-2 callback and the held event_id is unchanged
    """
    query_results = iter([
        [{"id": "evt-cat-1", "label": "cat", "has_snapshot": True, "start_time": 10.0}],
    ])

    def _fake_query(base_url: str, camera: str, after_ts: int, timeout: float) -> list[dict]:
        return next(query_results, [
            {"id": "evt-cat-2", "label": "cat", "has_snapshot": True, "start_time": 999.0},
        ])

    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail()
    ), patch.object(frigate_prefetch, "_query_candidate_events", side_effect=_fake_query), patch.object(
        frigate_prefetch, "_check_clip_ready", return_value=False
    ):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.3, poll_interval_s=0.05,
        )
    rank2_calls = [c for c in on_result.calls if c.rank == frigate_prefetch.RANK_OTHER]
    assert len(rank2_calls) == 1
    assert rank2_calls[0].event_id == "evt-cat-1"


@pytest.mark.asyncio
async def test_stops_early_on_rank1_with_clip_ready() -> None:
    """
    AC4: the run stops early once rank 1 (person) is reached and its clip is ready —
    no more polling after that.

    Expected result:
    - _query_candidate_events is called exactly once (the poll that found the person)
    - elapsed time is well under max_wait_s
    """
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail()
    ), patch.object(
        frigate_prefetch, "_query_candidate_events",
        return_value=[{"id": "evt-person", "label": "person", "has_snapshot": True, "start_time": 10.0}],
    ) as mock_query, patch.object(frigate_prefetch, "_check_clip_ready", return_value=True):
        result = await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", _ResultCollector(),
            max_wait_s=5.0, poll_interval_s=0.2,
        )
    assert result.rank == frigate_prefetch.RANK_PERSON
    assert result.clip_found is True
    assert mock_query.call_count == 1


@pytest.mark.asyncio
async def test_keeps_polling_on_rank2_until_budget_exhausted() -> None:
    """
    AC4: on rank 2 (a non-person event), polling continues until the budget runs out,
    in case a person still appears.

    Expected result:
    - _query_candidate_events is called more than once even though a rank-2 event (with
      its clip ready) was found on the very first poll
    """
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail()
    ), patch.object(
        frigate_prefetch, "_query_candidate_events",
        return_value=[{"id": "evt-cat", "label": "cat", "has_snapshot": True, "start_time": 10.0}],
    ) as mock_query, patch.object(frigate_prefetch, "_check_clip_ready", return_value=True):
        result = await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", _ResultCollector(),
            max_wait_s=0.3, poll_interval_s=0.05,
        )
    assert result.rank == frigate_prefetch.RANK_OTHER
    assert mock_query.call_count >= 2


@pytest.mark.asyncio
async def test_clip_upgrade_pushes_second_callback_for_same_rank() -> None:
    """
    AC5/AC7: a rank-1/2 event found without its clip ready gets exactly one further
    callback once _check_clip_ready confirms it, same rank, clip_found flips 0 -> 1.

    Expected result:
    - two callbacks for the person event: clip_found=False then clip_found=True
    """
    clip_ready_calls = {"count": 0}

    def _fake_clip_ready(base_url: str, event_id: str, timeout: float) -> bool:
        clip_ready_calls["count"] += 1
        return clip_ready_calls["count"] >= 2

    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail()
    ), patch.object(
        frigate_prefetch, "_query_candidate_events",
        return_value=[{"id": "evt-person", "label": "person", "has_snapshot": True, "start_time": 10.0}],
    ), patch.object(frigate_prefetch, "_check_clip_ready", side_effect=_fake_clip_ready):
        on_result = _ResultCollector()
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=1.0, poll_interval_s=0.05,
        )
    person_calls = [c for c in on_result.calls if c.rank == frigate_prefetch.RANK_PERSON]
    assert [c.clip_found for c in person_calls] == [False, True]
    assert person_calls[0].event_id == person_calls[1].event_id == "evt-person"


@pytest.mark.asyncio
async def test_nothing_found_sends_exactly_one_final_rank_none_miss() -> None:
    """
    AC9: if the create call fails AND the any-label search finds nothing at all, exactly
    one final miss (rank=RANK_NONE) is sent — the only "miss" callback of the run.

    Expected result:
    - exactly one on_result call, found=False, event_id=None, clip_found=False, rank=4
    """
    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_fail()
    ), patch.object(frigate_prefetch, "_query_candidate_events", return_value=[]):
        result = await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.15, poll_interval_s=0.05,
        )
    assert len(on_result.calls) == 1
    assert on_result.calls[0] == PrefetchResult(
        found=False, event_id=None, clip_found=False, rank=frigate_prefetch.RANK_NONE
    )
    assert result == on_result.calls[0]


@pytest.mark.asyncio
async def test_successful_manual_create_with_nothing_better_sends_no_final_miss() -> None:
    """
    AC5: when the manual event was successfully pushed (rank 3) and nothing better ever
    appears, no additional final-miss callback is sent — the manual push already stands.

    Expected result:
    - exactly one on_result call total (the rank-3 push)
    """
    on_result = _ResultCollector()
    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_ok("evt-manual-1")
    ), patch.object(frigate_prefetch, "_query_candidate_events", return_value=[]):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", on_result,
            max_wait_s=0.15, poll_interval_s=0.05,
        )
    assert len(on_result.calls) == 1
    assert on_result.calls[0].rank == frigate_prefetch.RANK_MANUAL


@pytest.mark.asyncio
async def test_on_result_exception_does_not_end_the_run() -> None:
    """
    Expected result:
    - an on_result callback that raises is logged and swallowed; the run still proceeds
      to a later, better-ranked callback
    """
    calls: list[PrefetchResult] = []

    async def _flaky_on_result(result: PrefetchResult) -> None:
        calls.append(result)
        if result.rank == frigate_prefetch.RANK_MANUAL:
            raise RuntimeError("simulated callback failure")

    with patch.object(
        frigate_prefetch, "_create_manual_event", return_value=_manual_ok("evt-manual-1")
    ), patch.object(
        frigate_prefetch, "_query_candidate_events",
        return_value=[{"id": "evt-person", "label": "person", "has_snapshot": True, "start_time": 10.0}],
    ), patch.object(frigate_prefetch, "_check_clip_ready", return_value=True):
        result = await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", _flaky_on_result,
            max_wait_s=1.0, poll_interval_s=0.05,
        )
    # The manual (rank 3) callback raised and was swallowed; the run still proceeded to
    # push the person event, including its own clip-ready upgrade.
    assert result.rank == frigate_prefetch.RANK_PERSON
    assert result.clip_found is True
    assert [c.rank for c in calls] == [
        frigate_prefetch.RANK_MANUAL, frigate_prefetch.RANK_PERSON, frigate_prefetch.RANK_PERSON,
    ]


@pytest.mark.asyncio
async def test_http_error_during_create_or_query_resolves_cleanly_never_raises() -> None:
    """
    AC9: a Frigate outage (connection refused) affecting both the create call and every
    events query must never propagate an exception.

    Expected result:
    - a clean final miss, no exception raised
    """
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", side_effect=_raise):
        result = await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", _ResultCollector(),
            max_wait_s=0.15, poll_interval_s=0.05,
        )
    assert result.found is False
    assert result.rank == frigate_prefetch.RANK_NONE


@pytest.mark.asyncio
async def test_budget_respected_including_create_call_latency() -> None:
    """
    NFR1: the deadline is set once at entry, before the create call — the create call's
    own latency counts against the same budget, it is not added on top of it.

    Expected result:
    - total elapsed time for a run whose create call itself takes noticeable time stays
      within max_wait_s plus a small tolerance, not max_wait_s + create-call time
    """
    import asyncio
    import time as time_module

    async def _slow_create(base_url: str, camera: str, timeout: float) -> tuple[str | None, int | None]:
        await asyncio.sleep(0.1)
        return _manual_fail()

    def _sync_slow_create(base_url: str, camera: str, timeout: float) -> tuple[str | None, int | None]:
        time_module.sleep(0.1)
        return _manual_fail()

    start = time_module.monotonic()
    with patch.object(
        frigate_prefetch, "_create_manual_event", side_effect=_sync_slow_create
    ), patch.object(frigate_prefetch, "_query_candidate_events", return_value=[]):
        await frigate_prefetch.prefetch_alarm_media(
            "http://192.168.100.18:5000", "vigi_sud-est", _ResultCollector(),
            max_wait_s=0.3, poll_interval_s=0.05,
        )
    elapsed = time_module.monotonic() - start
    assert elapsed < 0.3 + 1.0, f"elapsed={elapsed}s — create-call latency was not counted against the budget"


# ── Source-scan test: never a mutating Frigate call ─────────────────────────────


def test_module_source_never_deletes_ends_or_retains_events() -> None:
    """
    AC10 (never delete, per Herve's explicit decision): the only mutating Frigate call in
    this module is the manual-event create. No DELETE, no /end, no /retain, no PUT.

    Expected result:
    - the module source contains no DELETE method, no "/end" or "/retain" endpoint
      fragment, and exactly one POST call site (the create helper)
    """
    source = Path(frigate_prefetch.__file__).read_text(encoding="utf-8")
    assert 'method="DELETE"' not in source
    assert 'method="PUT"' not in source
    # Endpoint-literal checks (not prose like "ends"/"retains" in comments/docstrings):
    assert '/end"' not in source
    assert '/end}"' not in source
    # Endpoint-literal check for retention mutation, e.g. a hypothetical "/retain" call —
    # excludes this test's own docstring/module-docstring prose ("retains") by requiring
    # the slash.
    assert "/retain" not in source
    assert source.count('method="POST"') == 1


# ── Story 14-3 — clip-readiness check (unchanged) ────────────────────────────────


def test_check_clip_ready_true_when_has_clip_true() -> None:
    """
    _check_clip_ready() reads the event row's has_clip boolean (per
    scripts/frigate_latency_probe.py's poll(), line 137).

    Expected result:
    - True when the event row's has_clip field is truthy
    """
    with patch.object(frigate_prefetch, "_get_json", return_value={"has_clip": True}):
        result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
    assert result is True


def test_check_clip_ready_false_when_has_clip_false_or_absent() -> None:
    """
    Expected result:
    - False when has_clip is explicitly False, or absent from the event row entirely
    """
    for body in ({"has_clip": False}, {}, {"other_field": 1}):
        with patch.object(frigate_prefetch, "_get_json", return_value=body):
            result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
        assert result is False, f"expected False for body={body!r}"


def test_check_clip_ready_never_raises_on_malformed_or_missing_response() -> None:
    """
    Same never-raise contract as _get_json() — a Frigate outage or malformed body during
    the clip check must never propagate.

    Expected result:
    - False for a non-dict body (None, a list, a string) — never an exception
    """
    for malformed_body in (None, ["not-a-dict"], "not-a-dict-either"):
        with patch.object(frigate_prefetch, "_get_json", return_value=malformed_body):
            result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
        assert result is False, f"expected False for body={malformed_body!r}"


# ── _post_json ────────────────────────────────────────────────────────────────


def test_post_json_success_returns_status_and_body() -> None:
    """
    Expected result:
    - (200, decoded body) on a normal successful response
    """
    class _FakeResp:
        status = 200

        def read(self) -> bytes:
            return b'{"success": true, "event_id": "evt-1"}'

        def __enter__(self) -> "_FakeResp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch("urllib.request.urlopen", return_value=_FakeResp()):
        status, body = frigate_prefetch._post_json("http://x/create", {"duration": 30}, 5.0)
    assert status == 200
    assert body == {"success": True, "event_id": "evt-1"}


def test_post_json_http_error_returns_status_code_and_decoded_error_body() -> None:
    """
    AC1/R1: a 401/403 refusal (no admin role) must surface its status code so the caller
    can log a precise warning, not just "unreachable".

    Expected result:
    - (401, decoded error body) when Frigate returns an HTTPError
    """
    import io

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "http://x/create", 401, "Unauthorized", {}, io.BytesIO(b'{"detail": "not authorized"}')
        )

    with patch("urllib.request.urlopen", side_effect=_raise):
        status, body = frigate_prefetch._post_json("http://x/create", {"duration": 30}, 5.0)
    assert status == 401
    assert body == {"detail": "not authorized"}


def test_post_json_network_error_returns_none_none() -> None:
    """
    Expected result:
    - (None, None) on a connection failure — never raises
    """
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", side_effect=_raise):
        status, body = frigate_prefetch._post_json("http://x/create", {"duration": 30}, 5.0)
    assert status is None
    assert body is None


# ── _create_manual_event ──────────────────────────────────────────────────────


def test_create_manual_event_returns_none_when_success_false() -> None:
    """
    Expected result:
    - (None, status) when Frigate responds with success: false
    """
    with patch.object(
        frigate_prefetch, "_post_json", return_value=(404, {"success": False, "message": "not a valid camera"})
    ):
        event_id, status = frigate_prefetch._create_manual_event("http://x", "bad_camera", 5.0)
    assert event_id is None
    assert status == 404


def test_create_manual_event_returns_none_on_malformed_or_missing_response() -> None:
    """
    Expected result:
    - (None, status) for a non-dict body, or a dict missing/empty event_id — never raises
    """
    for status, body in ((None, None), (200, {"success": True}), (200, {"success": True, "event_id": ""})):
        with patch.object(frigate_prefetch, "_post_json", return_value=(status, body)):
            event_id, returned_status = frigate_prefetch._create_manual_event("http://x", "cam", 5.0)
        assert event_id is None
        assert returned_status == status
