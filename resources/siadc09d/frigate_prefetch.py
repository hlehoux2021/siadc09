"""Frigate REST event-prefetch module — Story 14-2 (ADR-17 Amendment 3, Option D).

Promotes the already-validated poll logic from scripts/frigate_latency_probe.py into
production daemon code (not a duplicate rewrite). Queries Frigate's own `GET /api/events`
REST endpoint directly, filtered by camera + label=person + after=<grace window>, polling
with a bounded total wait. Runs entirely inside the alarm zone's immediate-action window —
never awaited by any PHP code, never blocks the daemon's event loop (blocking urllib calls
are offloaded via asyncio.to_thread()).

Reference: _bmad-output/planning-artifacts/architecture.md ADR-17, Amendment 3
Reference: scripts/frigate_latency_probe.py (validated poll-loop shape, promoted here)
Reference: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Final

_logger = logging.getLogger(__name__)

# Grace window before "now" for the `after=` filter — catches a Frigate event that started
# before the alarm zone's real sensor tripped (a person is typically seen by the camera
# before reaching/triggering a door/PIR sensor). Widened from 15.0 to 60.0 after live-host
# validation (2026-09-24) showed a tight race at 15s even in a fast manual test — a real
# scenario, where the person walks from camera view to the sensor, needs more margin.
PREFETCH_AFTER_BUFFER_S: Final[float] = 60.0
# Total polling budget — bounded well under a typical 30-60s alarm-zone trigger delay.
PREFETCH_MAX_WAIT_S: Final[float] = 25.0
# Delay between polls while waiting for Frigate to record/confirm the event.
PREFETCH_POLL_INTERVAL_S: Final[float] = 2.0
# Per-HTTP-request timeout.
PREFETCH_HTTP_TIMEOUT_S: Final[float] = 5.0
# Extra slack added to the outer asyncio.wait_for() bound around the per-request timeout,
# defending against a blocking call that doesn't honor its own timeout promptly.
PREFETCH_WAIT_FOR_SLACK_S: Final[float] = 1.0

_PERSON_LABEL: Final[str] = "person"


@dataclass
class PrefetchResult:
    """Outcome of a single Frigate person-event prefetch query."""

    found: bool
    event_id: str | None


def _get_json(url: str, timeout: float) -> object | None:
    """GET url, return the decoded JSON body, or None on any HTTP/network error.

    Never raises — a Frigate outage during prefetch must never propagate past this
    function; the caller treats None the same as "no event found" (AC6's two-outcome
    contract: confirmed hit or nothing, no third tier).

    Args:
        url: Full request URL, including query string.
        timeout: Per-request timeout in seconds.

    Returns:
        The decoded JSON body, or None on any error/malformed response.
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _query_latest_person_event(base_url: str, camera: str, after_ts: int, timeout: float) -> str | None:
    """Single `GET /api/events` query; returns the most recent matching event id, or None.

    Deliberately does NOT filter on `in_progress` — confirmed via live-host validation
    (2026-09-24) that Frigate sets a concrete `end_time` immediately, even for a manually
    created event, and a real short person detection closes out just as fast. Requiring
    `in_progress=1` would exclude almost every real detection by the time this query runs,
    which is exactly the majority case ADR-17 exists to catch.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name (siaDC09Cmd::_resolvePrefetchTarget()'s
            camera_name, read from the camera eqLogic's own getConfiguration('name')).
        after_ts: Unix timestamp lower bound for the event's start time.
        timeout: Per-request timeout in seconds.

    Returns:
        The event id string, or None if no matching event was found.
    """
    params = urllib.parse.urlencode({
        "camera": camera,
        "label": _PERSON_LABEL,
        "after": after_ts,
        "has_snapshot": 1,
        "sort": "desc",
        "limit": 1,
    })
    url = f"{base_url}/api/events?{params}"
    body = _get_json(url, timeout)
    _logger.debug(f"_query_latest_person_event: GET {url} -> {body!r}")
    if not isinstance(body, list) or not body:
        return None
    first = body[0]
    if not isinstance(first, dict):
        return None
    event_id = first.get("id")
    return event_id if isinstance(event_id, str) and event_id else None


async def prefetch_person_event(
    base_url: str,
    camera: str,
    *,
    max_wait_s: float = PREFETCH_MAX_WAIT_S,
    poll_interval_s: float = PREFETCH_POLL_INTERVAL_S,
    http_timeout_s: float = PREFETCH_HTTP_TIMEOUT_S,
    after_buffer_s: float = PREFETCH_AFTER_BUFFER_S,
) -> PrefetchResult:
    """Poll Frigate's REST API for a confirmed person event on `camera`.

    Runs entirely inside the alarm zone's immediate-action window — bounded by
    `max_wait_s`, never awaited by any PHP code.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name.
        max_wait_s: Total polling budget in seconds.
        poll_interval_s: Delay between polls in seconds.
        http_timeout_s: Per-request timeout in seconds.
        after_buffer_s: Grace window before "now" for the `after=` filter.

    Returns:
        PrefetchResult(found=True, event_id=...) on a confirmed match,
        PrefetchResult(found=False, event_id=None) on timeout or any error — never raises.
    """
    after_ts = int(time.time() - after_buffer_s)
    deadline = time.monotonic() + max_wait_s
    _logger.debug(
        f"prefetch_person_event: starting base_url={base_url!r} camera={camera!r} "
        f"after_ts={after_ts} max_wait_s={max_wait_s} poll_interval_s={poll_interval_s}"
    )
    while True:
        try:
            event_id = await asyncio.wait_for(
                asyncio.to_thread(_query_latest_person_event, base_url, camera, after_ts, http_timeout_s),
                timeout=http_timeout_s + PREFETCH_WAIT_FOR_SLACK_S,
            )
        except (asyncio.TimeoutError, TimeoutError):
            _logger.debug("prefetch_person_event: poll attempt timed out")
            event_id = None
        if event_id:
            _logger.debug(f"prefetch_person_event: confirmed event_id={event_id!r}")
            return PrefetchResult(found=True, event_id=event_id)
        if time.monotonic() >= deadline:
            _logger.debug("prefetch_person_event: max_wait_s exhausted, no matching event — miss")
            return PrefetchResult(found=False, event_id=None)
        await asyncio.sleep(poll_interval_s)
