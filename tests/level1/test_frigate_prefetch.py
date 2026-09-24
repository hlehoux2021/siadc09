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
    without polling further.

    Expected result:
    - PrefetchResult(found=True, event_id="1790193165.543115-0e6wzj")
    - the underlying query function is called exactly once
    """
    with patch.object(
        frigate_prefetch, "_query_latest_person_event", return_value="1790193165.543115-0e6wzj"
    ) as mock_query:
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=10.0, poll_interval_s=1.0
        )
    # Assert: confirmed hit surfaced correctly
    assert result.found is True
    assert result.event_id == "1790193165.543115-0e6wzj"
    # Assert: no unnecessary re-polling once a match is found
    assert mock_query.call_count == 1


@pytest.mark.asyncio
async def test_returns_found_false_when_no_event_appears_before_deadline() -> None:
    """
    When Frigate never reports a matching event, the poll loop must give up at
    max_wait_s rather than looping forever.

    Expected result:
    - PrefetchResult(found=False, event_id=None)
    - the loop polls more than once within the bounded window
    """
    with patch.object(frigate_prefetch, "_query_latest_person_event", return_value=None) as mock_query:
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=0.3, poll_interval_s=0.1
        )
    # Assert: bounded timeout resolves to a clean miss, never raises
    assert result.found is False
    assert result.event_id is None
    # Assert: polled at least twice within the bounded window (proves it's a real loop)
    assert mock_query.call_count >= 2


@pytest.mark.asyncio
async def test_query_sends_expected_params() -> None:
    """
    The REST query must filter by camera, label=person, an after= lower bound, and
    request only in-progress/has-snapshot events, sorted to get the most recent one.

    Expected result:
    - the requested URL contains camera, label=person, after, in_progress, has_snapshot,
      sort=desc, limit=1
    """
    captured_urls: list[str] = []

    def _fake_get_json(url: str, timeout: float) -> object | None:
        captured_urls.append(url)
        return [{"id": "evt123"}]

    with patch.object(frigate_prefetch, "_get_json", side_effect=_fake_get_json):
        result = await frigate_prefetch.prefetch_person_event(
            "http://192.168.100.18:5000", "vigi_sud-est", max_wait_s=5.0, poll_interval_s=1.0
        )
    # Assert: the query resolved to the mocked event
    assert result == frigate_prefetch.PrefetchResult(found=True, event_id="evt123")
    assert len(captured_urls) == 1
    url = captured_urls[0]
    # Assert: all documented Frigate REST filters are present
    assert "camera=vigi_sud-est" in url
    assert "label=person" in url
    assert "after=" in url
    assert "in_progress=1" in url
    assert "has_snapshot=1" in url
    assert "sort=desc" in url
    assert "limit=1" in url


@pytest.mark.asyncio
async def test_http_error_resolves_to_miss_never_raises() -> None:
    """
    A Frigate outage (connection refused, timeout, malformed body) must never propagate
    an exception out of prefetch_person_event() — the daemon's tracked task calling this
    must never crash because Frigate is unreachable.

    Expected result:
    - PrefetchResult(found=False, event_id=None), no exception raised
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
