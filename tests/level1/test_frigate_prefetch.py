"""
Tests for resources/siadc09d/frigate_prefetch.py — Story 14-2, Task 3.

Verifies the Frigate REST person-event prefetch module: correct query params, bounded
polling, and that any HTTP/network failure resolves to PrefetchResult(found=False, ...)
rather than raising — no synchronous PHP code ever awaits this, but the daemon's own
tracked task (Task 4) must never crash from it either.

Reference: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md
Reference: ADR-17, Amendment 3, _bmad-output/planning-artifacts/architecture.md
"""
import sys
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "resources" / "siadc09d"))

import frigate_prefetch  # noqa: E402


@pytest.mark.asyncio
async def test_returns_found_true_with_event_id_on_immediate_match() -> None:
    """
    A single successful query returning a matching event must resolve immediately,
    without polling further for the person-event confirmation itself. The clip-readiness
    check (Story 14-3) is mocked here as immediately ready so this test stays about the
    person-event match, not clip timing (covered separately below).

    Expected result:
    - PrefetchResult(found=True, event_id="1790193165.543115-0e6wzj", clip_found=True)
    - the underlying query function is called exactly once
    """
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value="1790193165.543115-0e6wzj"
    ) as mock_query, patch.object(frigate_prefetch, "_check_clip_ready", return_value=True):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=10.0, poll_interval_s=1.0
        )
    # Assert: confirmed hit surfaced correctly
    assert result.found is True
    assert result.event_id == "1790193165.543115-0e6wzj"
    # Assert: clip readiness is carried through on the result
    assert result.clip_found is True
    # Assert: no unnecessary re-polling once a match is found
    assert mock_query.call_count == 1


@pytest.mark.asyncio
async def test_returns_found_false_when_no_event_appears_before_deadline() -> None:
    """
    When Frigate never reports a matching event, the poll loop must give up at
    max_wait_s rather than looping forever.

    Expected result:
    - PrefetchResult(found=False, event_id=None, clip_found=False)
    - the loop polls more than once within the bounded window
    - the clip-readiness check is never attempted (no person event to check a clip for)
    """
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value=None
    ) as mock_query, patch.object(frigate_prefetch, "_check_clip_ready") as mock_clip:
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.3, poll_interval_s=0.1
        )
    # Assert: bounded timeout resolves to a clean miss, never raises
    assert result.found is False
    assert result.event_id is None
    assert result.clip_found is False
    # Assert: polled at least twice within the bounded window (proves it's a real loop)
    assert mock_query.call_count >= 2
    # Assert: a person-event miss never attempts the clip check at all
    mock_clip.assert_not_called()


@pytest.mark.asyncio
async def test_query_sends_expected_params() -> None:
    """
    The REST query must filter by camera, label=person, an after= lower bound, and
    request only has-snapshot events, sorted to get the most recent one. Must NOT filter
    on in_progress: confirmed via live-host validation (2026-09-24) that Frigate sets a
    concrete end_time immediately, even for a manually-created event, and a real short
    person detection closes out just as fast — in_progress=1 would exclude almost every
    real detection by the time this query runs.

    Expected result:
    - the requested URL contains camera, label=person, after, has_snapshot, sort=desc,
      limit=1
    - the requested URL never contains in_progress
    """
    captured_urls: list[str] = []

    def _fake_get_json(url: str, timeout: float) -> object | None:
        captured_urls.append(url)
        return [{"id": "evt123"}]

    with patch.object(frigate_prefetch, "_get_json", side_effect=_fake_get_json), patch.object(
        frigate_prefetch, "_check_clip_ready", return_value=True
    ):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=5.0, poll_interval_s=1.0
        )
    # Assert: the query resolved to the mocked event
    assert result == frigate_prefetch.PrefetchResult(found=True, event_id="evt123", clip_found=True)
    assert len(captured_urls) == 1
    url = captured_urls[0]
    # Assert: all documented Frigate REST filters are present
    assert "camera=vigi_sud-est" in url
    assert "label=person" in url
    assert "after=" in url
    assert "has_snapshot=1" in url
    assert "sort=desc" in url
    assert "limit=1" in url
    # Assert: in_progress is never sent — would exclude an already-closed real detection
    assert "in_progress" not in url


@pytest.mark.asyncio
async def test_http_error_resolves_to_miss_never_raises() -> None:
    """
    A Frigate outage (connection refused, timeout, malformed body) must never propagate
    an exception out of prefetch_person_event() — the daemon's tracked task calling this
    must never crash because Frigate is unreachable.

    Expected result:
    - PrefetchResult(found=False, event_id=None, clip_found=False), no exception raised
    """
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", side_effect=_raise):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.2, poll_interval_s=0.1
        )
    # Assert: network failure degrades cleanly to a miss, never an exception
    assert result.found is False
    assert result.event_id is None
    assert result.clip_found is False


@pytest.mark.asyncio
async def test_malformed_response_body_resolves_to_miss() -> None:
    """
    A response that isn't a non-empty JSON list of dicts (Frigate's error-shape
    responses aren't always the expected structure) must resolve to a miss, not a
    crash.

    Expected result:
    - PrefetchResult(found=False, event_id=None) for an empty list, a non-list body,
      and a list of non-dict items
    """
    for malformed_body in ([], {"error": "bad request"}, ["not-a-dict"], [{"id": ""}], [{"no_id_key": 1}]):
        with patch.object(frigate_prefetch, "_get_json", return_value=malformed_body):
            result = await frigate_prefetch.prefetch_person_event(
                "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.15, poll_interval_s=0.1
            )
        # Assert: every malformed shape degrades to a clean miss
        assert result.found is False, f"expected a miss for body={malformed_body!r}"
        assert result.event_id is None
        assert result.clip_found is False


# ── Story 14-3 — clip-readiness check (AC1, AC2) ────────────────────────────────


def test_check_clip_ready_true_when_has_clip_true() -> None:
    """
    _check_clip_ready() reads the event row's has_clip boolean (per
    scripts/frigate_latency_probe.py's poll(), line 137).

    Expected result:
    - True when the event row's has_clip field is truthy
    """
    with patch.object(frigate_prefetch, "_get_json", return_value={"has_clip": True}):
        result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
    # Assert: truthy has_clip resolves to True
    assert result is True


def test_check_clip_ready_false_when_has_clip_false_or_absent() -> None:
    """
    Expected result:
    - False when has_clip is explicitly False, or absent from the event row entirely
    """
    for body in ({"has_clip": False}, {}, {"other_field": 1}):
        with patch.object(frigate_prefetch, "_get_json", return_value=body):
            result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
        # Assert: not-ready-yet shapes resolve to False
        assert result is False, f"expected False for body={body!r}"


def test_check_clip_ready_never_raises_on_malformed_or_missing_response() -> None:
    """
    Same never-raise contract as _get_json()/_query_latest_person_event() — a Frigate
    outage or malformed body during the clip check must never propagate.

    Expected result:
    - False for a non-dict body (None, a list, a string) — never an exception
    """
    for malformed_body in (None, ["not-a-dict"], "not-a-dict-either"):
        with patch.object(frigate_prefetch, "_get_json", return_value=malformed_body):
            result = frigate_prefetch._check_clip_ready("http://192.168.100.18:5000", "evt123", 5.0)
        # Assert: malformed response degrades cleanly to False
        assert result is False, f"expected False for body={malformed_body!r}"


@pytest.mark.asyncio
async def test_clip_check_only_attempted_after_confirmed_person_event() -> None:
    """
    AC2: a clip probe that would have succeeded is never attempted if no person event
    was confirmed in the first place.

    Expected result:
    - _check_clip_ready is never called when the person-event poll itself misses
    """
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value=None
    ), patch.object(frigate_prefetch, "_check_clip_ready") as mock_clip:
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.15, poll_interval_s=0.1
        )
    # Assert: a person-event miss short-circuits before any clip check
    assert result.found is False
    assert result.clip_found is False
    mock_clip.assert_not_called()


@pytest.mark.asyncio
async def test_clip_check_http_error_resolves_false_without_affecting_found_or_event_id() -> None:
    """
    AC2: the clip-readiness check is its own network operation — a Frigate outage or
    timeout affecting only the clip check resolves clip_found=False without affecting
    found/event_id.

    Expected result:
    - found=True and event_id unchanged despite the clip check itself failing
    - clip_found=False
    """
    # A genuine HTTP/network failure inside _check_clip_ready (exercised through its own
    # _get_json dependency, matching its documented never-raise contract) degrades to
    # clip_found=False without touching found/event_id.
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value="evt123"
    ), patch.object(frigate_prefetch, "_get_json", return_value=None):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.15, poll_interval_s=0.1
        )
    assert result.found is True
    assert result.event_id == "evt123"
    assert result.clip_found is False


@pytest.mark.asyncio
async def test_clip_ready_resolves_clip_found_true() -> None:
    """
    Expected result:
    - clip_found=True when the clip-readiness check succeeds, found/event_id unaffected
    """
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value="evt123"
    ), patch.object(frigate_prefetch, "_check_clip_ready", return_value=True):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=5.0, poll_interval_s=1.0
        )
    # Assert: full triple confirmed
    assert result == frigate_prefetch.PrefetchResult(found=True, event_id="evt123", clip_found=True)


@pytest.mark.asyncio
async def test_total_elapsed_time_across_both_checks_stays_bounded_by_max_wait_s() -> None:
    """
    Task 1.3: the clip check must fit inside the SAME deadline as the person-event
    confirmation, never adding a second independent budget on top — the whole prefetch
    (snapshot-confirmation + clip-check combined) must stay bounded by max_wait_s.

    Expected result:
    - wall-clock elapsed time for a person-hit-but-clip-never-ready run stays within
      max_wait_s plus a small tolerance for the per-request timeout/slack overhead
    """
    start = time.monotonic()
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value="evt123"
    ), patch.object(frigate_prefetch, "_check_clip_ready", return_value=False):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.4, poll_interval_s=0.1
        )
    elapsed = time.monotonic() - start
    # Assert: clip never became ready within budget
    assert result.found is True
    assert result.clip_found is False
    # Assert: total elapsed time (person-event confirmation, immediate, + clip polling)
    # stays close to the single shared max_wait_s budget, not double it
    assert elapsed < 0.4 + 1.0, f"elapsed={elapsed}s exceeded the shared budget by too much"
