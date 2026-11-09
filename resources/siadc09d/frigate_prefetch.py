"""Frigate REST event-prefetch module — Story 14-2/14-3 (ADR-17 Amendment 3), extended by
Story 14-4 (ADR-17 Amendment 4: best-effort alarm media — any-label ranking + forced capture).

Queries Frigate's own REST API directly: first a forced manual "alarm" event created at the
trip itself (never awaiting Frigate's detection pipeline), then any-label real events on the
same camera, ranked person > other label > the manual event > nothing. Runs entirely inside
the alarm zone's immediate-action window — never awaited by any PHP code, never blocks the
daemon's event loop (blocking urllib calls are offloaded via asyncio.to_thread()). Never
deletes, ends, or sets retention on any Frigate event (Herve's explicit decision, Amendment 4).

Reference: _bmad-output/planning-artifacts/architecture.md ADR-17, Amendment 3 and Amendment 4
Reference: scripts/frigate_latency_probe.py (validated POST/poll shapes, promoted here)
Reference: _bmad-output/implementation-artifacts/14-4-best-effort-alarm-media-forced-capture.md
"""

from __future__ import annotations

import asyncio
import http.client
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Final, TypeVar

_logger = logging.getLogger(__name__)

# Grace window before "now" for the `after=` filter — catches a Frigate event that started
# before the alarm zone's real sensor tripped. Per the intended deployment principle (one
# camera per protected zone, narrow field of view on that zone's own entry — not a wide shot
# of the whole garden), Herve's own measured maximum detection duration is ~10s, so 30s is a
# comfortable ceiling — not just "safety margin": ADR-17 Amendment 4 redefines "wrong photo"
# as *stale* (from before this window) or *not this alarm's* (another camera, another
# prefetch run) — a real image is useful whatever its label, but it still has to be this
# alarm's. Widened once already (15.0 -> 60.0) after a live validation race, then narrowed
# back down (60.0 -> 30.0) once Herve clarified the deployment assumption (2026-09-24).
PREFETCH_AFTER_BUFFER_S: Final[float] = 30.0
# Total polling budget — bounded well under a typical 30-60s alarm-zone trigger delay. Story
# 14-4: this deadline is set once at entry, before the forced-capture create call, so the
# create call's own latency is counted against the same budget, not added on top of it.
PREFETCH_MAX_WAIT_S: Final[float] = 25.0
# Delay between polls while waiting for a better-ranked event or a clip to become ready.
PREFETCH_POLL_INTERVAL_S: Final[float] = 2.0
# Per-HTTP-request timeout.
PREFETCH_HTTP_TIMEOUT_S: Final[float] = 5.0
# Extra slack added to the outer asyncio.wait_for() bound around the per-request timeout,
# defending against a blocking call that doesn't honor its own timeout promptly.
PREFETCH_WAIT_FOR_SLACK_S: Final[float] = 1.0

# Story 14-4 (ADR-17 Amendment 4): forced-capture manual event, created at the trip itself
# (FR1). Frigate 0.17.2 validates only the camera on create — the label is free text and
# must NOT be added to objects.track, where it would be dropped as unknown to the model's
# labelmap (frigate/config/config.py verify_objects_track).
MANUAL_EVENT_LABEL: Final[str] = "alarm"
MANUAL_EVENT_DURATION_S: Final[int] = 30
# Frigate stores this in the event row's `data.type` for a manual (API-created) event,
# vs. "object" for a real detection — used as the exclusion backstop (FR3).
MANUAL_EVENT_API_TYPE: Final[str] = "api"

# Max rows requested per any-label events poll. Small on purpose: only the most recent
# handful of events on one camera matter, and the manual "alarm" event itself now takes a
# slot in the result set (it's filtered out client-side, not by the query).
EVENTS_QUERY_LIMIT: Final[int] = 20

# Upper bound on a downloaded snapshot (ticket 18.2): a JPEG far above this is not a snapshot.
SNAPSHOT_MAX_BYTES: Final[int] = 10 * 1024 * 1024

# Clip upload (ticket 18.5). Every limit follows the event row; these are the bounds.
# Margin after the event's end_time for Frigate to finish writing the clip.
CLIP_END_MARGIN_S: Final[float] = 3.0
# Longest wait for a clip (end of event, and retries while Frigate answers an error).
CLIP_MAX_WAIT_S: Final[float] = 60.0
CLIP_POLL_INTERVAL_S: Final[float] = 2.0
# Download deadline = this base + the clip duration.
CLIP_DOWNLOAD_BASE_S: Final[float] = 30.0
CLIP_MAX_BYTES: Final[int] = 200 * 1024 * 1024
CLIP_CHUNK_BYTES: Final[int] = 64 * 1024

_PERSON_LABEL: Final[str] = "person"

# Priority ladder (ADR-17 Amendment 4, Decision 3): person > any other real label > the
# forced manual event > nothing. Lower value = higher priority. Sent over IPC as a plain int.
RANK_PERSON: Final[int] = 1
RANK_OTHER: Final[int] = 2
RANK_MANUAL: Final[int] = 3
RANK_NONE: Final[int] = 4

_T = TypeVar("_T")


@dataclass
class PrefetchResult:
    """Outcome of a Frigate alarm-media prefetch, at some point during (or at the end of) a
    run. `rank` records which source it came from (RANK_PERSON/RANK_OTHER/RANK_MANUAL), or
    RANK_NONE when nothing was found."""

    found: bool
    event_id: str | None
    clip_found: bool = False
    rank: int = RANK_NONE


def _get_json(url: str, timeout: float) -> object | None:
    """GET url, return the decoded JSON body, or None on any HTTP/network error.

    Never raises — a Frigate outage during prefetch must never propagate past this function.

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


def _get_bytes(url: str, timeout: float) -> bytes | None:
    """GET url, return the raw body, or None on any HTTP/network error or empty/oversized body.

    Never raises (epic 18, ticket 18.2: snapshot download).

    Args:
        url: Full request URL.
        timeout: Per-request timeout in seconds.

    Returns:
        The body, or None on any error.
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(SNAPSHOT_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        # OSError covers a connection reset or timeout while reading the body.
        return None
    if not body or len(body) > SNAPSHOT_MAX_BYTES:
        return None
    return body


async def fetch_event_snapshot(frigate_host: str, event_id: str) -> bytes | None:
    """Download an event's snapshot from the Frigate API (best effort, never raises).

    Args:
        frigate_host: Frigate "host:port", e.g. "192.168.100.18:5000".
        event_id: Frigate event id.

    Returns:
        The JPEG bytes, or None when Frigate is unreachable or the event has no snapshot.
    """
    url = (
        f"http://{frigate_host}/api/events/"
        f"{urllib.parse.quote(event_id, safe='')}/snapshot.jpg"
    )
    return await _run_with_deadline_timeout(_get_bytes, url, PREFETCH_HTTP_TIMEOUT_S,
                                            timeout=PREFETCH_HTTP_TIMEOUT_S)


class ClipFetchError(Exception):
    """The clip could not be obtained; the message is shown to the user (French, no secret)."""


@dataclass(frozen=True)
class ClipFile:
    """A downloaded clip in a temporary file the caller must delete with `remove_clip_file()`.

    Attributes:
        path: Temporary file holding the mp4.
        size: Bytes written.
        duration_s: Clip duration from the event row (`end_time - start_time`), 0 when unknown.
    """

    path: str
    size: int
    duration_s: float


def remove_clip_file(path: str) -> None:
    """Delete a temporary clip file; a file already gone is fine."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        _logger.warning(f"clip temporary file {path} could not be deleted: {e!r}")


def _as_epoch(value: object) -> float | None:
    """A Frigate event time (epoch seconds) as a float, or None when missing or invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def clip_wait_s(end_time: float | None, now: float) -> float:
    """How long to wait before the clip of an event is complete.

    Args:
        end_time: The event row's `end_time` (epoch seconds), None while it runs or unknown.
        now: Current epoch time.

    Returns:
        Seconds until `end_time` plus `CLIP_END_MARGIN_S`; 0 when the event already ended,
        when `end_time` is missing, or when the wait would exceed `CLIP_MAX_WAIT_S` (the
        daemon then downloads what exists).
    """
    if end_time is None or end_time <= now:
        return 0.0
    wait = end_time - now + CLIP_END_MARGIN_S
    return wait if wait <= CLIP_MAX_WAIT_S else 0.0


_CONTENT_LENGTH: Final[str] = "Content-Length"
_DOWNLOAD_TOO_SLOW: Final[str] = "téléchargement trop long"


def _local_disk_error(err: OSError) -> ClipFetchError:
    """A local write problem is not "Frigate has no clip": name it for the user."""
    return ClipFetchError(f"écriture du clip impossible sur le disque ({err.strerror or err})")


def _open_clip_file(path: str):
    """Open the clip destination for writing; a local failure is a ClipFetchError."""
    try:
        return open(path, "wb")  # pylint: disable=consider-using-with
    except OSError as err:
        raise _local_disk_error(err) from None


def _write_clip_chunk(out, chunk: bytes) -> None:
    """Write one chunk; a local failure (disk full, permission) is a ClipFetchError."""
    try:
        out.write(chunk)
    except OSError as err:
        raise _local_disk_error(err) from None


def _download_clip_to_file(url: str, path: str, deadline: float) -> int:
    """Stream `url` into `path` in chunks, capped at `CLIP_MAX_BYTES` (blocking).

    Args:
        url: Clip URL.
        path: Destination file (overwritten).
        deadline: `time.monotonic()` value after which the download is abandoned.

    Returns:
        Bytes written; 0 when Frigate answers an error, has no clip yet, or the transfer broke.

    Raises:
        ClipFetchError: The body exceeds the cap, or the deadline passed mid-transfer.
    """
    req = urllib.request.Request(url, method="GET")
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=PREFETCH_HTTP_TIMEOUT_S) as resp:
            declared = resp.headers.get(_CONTENT_LENGTH)
            if declared and declared.isdigit() and int(declared) > CLIP_MAX_BYTES:
                raise ClipFetchError(_clip_too_large())
            with _open_clip_file(path) as out:
                while True:
                    if time.monotonic() > deadline:
                        raise ClipFetchError(_DOWNLOAD_TOO_SLOW)
                    chunk = resp.read(CLIP_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > CLIP_MAX_BYTES:
                        raise ClipFetchError(_clip_too_large())
                    _write_clip_chunk(out, chunk)
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        # HTTP 4xx/5xx, connection reset or timeout: not ready (a truncated body is rejected).
        return 0
    return total


def _clip_too_large() -> str:
    """Wording of the size-cap failure, naming the cap."""
    return f"clip trop volumineux (limite {CLIP_MAX_BYTES // (1024 * 1024)} Mo)"


async def fetch_event_clip(frigate_host: str, event_id: str) -> ClipFile:
    """Wait for the clip of an event to be complete, then download it to a temporary file.

    The wait comes from the event row (`clip_wait_s()`); retries of a clip Frigate does not
    serve yet stop at `CLIP_MAX_WAIT_S` after the call. The download deadline is
    `CLIP_DOWNLOAD_BASE_S` plus the clip duration. The clip is never held in memory.

    Args:
        frigate_host: Frigate "host:port".
        event_id: Frigate event id.

    Returns:
        The downloaded clip; the caller deletes it with `remove_clip_file()`.

    Raises:
        ClipFetchError: Clip not ready in time, too large, or download too slow. No file
            remains in that case.
    """
    quoted = urllib.parse.quote(event_id, safe="")
    row = await _run_with_deadline_timeout(
        _get_json, f"http://{frigate_host}/api/events/{quoted}", PREFETCH_HTTP_TIMEOUT_S,
        timeout=PREFETCH_HTTP_TIMEOUT_S,
    )
    start_time = _as_epoch(row.get("start_time")) if isinstance(row, dict) else None
    end_time = _as_epoch(row.get("end_time")) if isinstance(row, dict) else None
    duration = end_time - start_time if start_time is not None and end_time is not None else 0.0
    duration = max(0.0, duration)
    wait = clip_wait_s(end_time, time.time())
    _logger.debug(f"fetch_event_clip: event={event_id!r} wait={wait:.1f}s duration={duration:.1f}s")
    if wait > 0:
        await asyncio.sleep(wait)
    # Retries of a clip Frigate does not serve yet start counting after the event-end wait.
    give_up_at = time.monotonic() + CLIP_MAX_WAIT_S
    download_s = CLIP_DOWNLOAD_BASE_S + duration
    url = f"http://{frigate_host}/api/events/{quoted}/clip.mp4"
    try:
        fd, path = tempfile.mkstemp(prefix="sia-clip-", suffix=".mp4")
    except OSError as err:
        raise _local_disk_error(err) from None
    os.close(fd)
    keep = False
    try:
        while True:
            deadline = time.monotonic() + download_s
            try:
                size = await asyncio.wait_for(
                    asyncio.to_thread(_download_clip_to_file, url, path, deadline),
                    timeout=download_s + PREFETCH_WAIT_FOR_SLACK_S,
                )
            except (asyncio.TimeoutError, TimeoutError):
                raise ClipFetchError(_DOWNLOAD_TOO_SLOW) from None
            if size > 0:
                keep = True
                return ClipFile(path=path, size=size, duration_s=duration)
            if time.monotonic() >= give_up_at:
                raise ClipFetchError(f"clip non disponible sur Frigate {frigate_host}")
            await asyncio.sleep(CLIP_POLL_INTERVAL_S)
    finally:
        if not keep:
            remove_clip_file(path)


def _post_json(
    url: str, body: dict[str, object], timeout: float
) -> tuple[int | None, object | None]:
    """POST a JSON body to url, return (http_status, decoded_json_body_or_none).

    Never raises. Mirrors `_get_json()`'s never-raise contract, but also surfaces the HTTP
    status — needed to distinguish "Frigate refused (401/403 — no admin role)" from "Frigate
    unreachable" for a single, precise warning log (NFR3, ADR-17 Amendment 4 R1).

    Args:
        url: Full request URL.
        body: JSON-serializable request body.
        timeout: Per-request timeout in seconds.

    Returns:
        (status, decoded_body) on any response, even an HTTP error one (Frigate's error
        responses are themselves JSON). (None, None) on a network error, timeout, or
        malformed body.
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # HTTPError is a URLError subclass — must be caught first to keep e.code.
        try:
            return e.code, json.loads(e.read())
        except (json.JSONDecodeError, ValueError):
            return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return None, None
    # Code review (2026-09-27): decoding is split from the request itself, so a genuinely
    # successful response (status known) with a malformed body is distinguishable from a
    # total network failure — the status is never lost to None just because the body
    # didn't parse (weakened the AC9 "warning with the status when there is one" diagnostic).
    try:
        return status, json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return status, None


def _create_manual_event(
    base_url: str, camera: str, timeout: float
) -> tuple[str | None, int | None]:
    """Create a forced-capture manual Frigate event on `camera` (ADR-17 Amendment 4, FR1).

    `POST /api/events/{camera}/{label}/create` with a fixed 30s duration and recording
    enabled. Requires Frigate's `admin` role — granted automatically on the internal port
    5000 (frigate/api/auth.py), refused (401/403) on the authenticated port without
    credentials. siaDC09 never sends Frigate credentials (memory:
    media-url-template-never-real-secret) — a refusal here just drops to the any-label
    search, it is not treated as an error to recover from.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name.
        timeout: Per-request timeout in seconds.

    Returns:
        (event_id, http_status) on success, (None, http_status_or_none) on any refusal,
        error, or malformed response. Never raises.
    """
    url = f"{base_url}/api/events/{urllib.parse.quote(camera, safe='')}/{MANUAL_EVENT_LABEL}/create"
    body: dict[str, object] = {"duration": MANUAL_EVENT_DURATION_S, "include_recording": True}
    status, resp = _post_json(url, body, timeout)
    _logger.debug(
        f"_create_manual_event: POST {url} body={body!r} -> status={status} resp={resp!r}"
    )
    if not isinstance(resp, dict) or not resp.get("success"):
        return None, status
    event_id = resp.get("event_id")
    return (event_id, status) if isinstance(event_id, str) and event_id else (None, status)


def _is_real_candidate(row: dict[str, object]) -> bool:
    """True if an `/api/events` row is a real detection worth ranking (ADR-17 Amendment 4 FR3).

    Excludes the forced-capture manual event by label, with `data.type == "api"` as a
    backstop (catches a leftover manual event from an earlier trip on the same camera even
    if its label were ever changed), and requires a snapshot.

    Args:
        row: One decoded `/api/events` row.

    Returns:
        True if `row` should be considered as a ranking candidate.
    """
    if row.get("label") == MANUAL_EVENT_LABEL:
        return False
    data = row.get("data")
    if isinstance(data, dict) and data.get("type") == MANUAL_EVENT_API_TYPE:
        return False
    return bool(row.get("has_snapshot"))


def _query_candidate_events(
    base_url: str, camera: str, after_ts: int, timeout: float
) -> list[dict[str, object]]:
    """Single `GET /api/events` query for real (non-manual) candidate events on `camera`.

    Deliberately does NOT filter on `in_progress` (memory:
    frigate-rest-in-progress-filter-unreliable) and does NOT filter on `label` — any real
    label is a useful candidate (ADR-17 Amendment 4). Filtering for "real, not manual, has a
    snapshot" happens client-side via `_is_real_candidate()`.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name.
        after_ts: Unix timestamp lower bound for the event's start time.
        timeout: Per-request timeout in seconds.

    Returns:
        The filtered list of candidate event rows (each a dict), most-recent-first per
        Frigate's own `sort=date_desc`. Empty on any error or malformed response — never
        raises.
    """
    params = urllib.parse.urlencode({
        "camera": camera,
        "after": after_ts,
        "has_snapshot": 1,
        "sort": "date_desc",
        "limit": EVENTS_QUERY_LIMIT,
    })
    url = f"{base_url}/api/events?{params}"
    body = _get_json(url, timeout)
    _logger.debug(f"_query_candidate_events: GET {url} -> {body!r}")
    if not isinstance(body, list):
        return []
    return [row for row in body if isinstance(row, dict) and _is_real_candidate(row)]


def _best_candidate(rows: list[dict[str, object]]) -> tuple[int, str] | None:
    """Pick the single best-ranked real event among `rows` (ADR-17 Amendment 4, Decision 3).

    Person beats any other label; ties (same rank) are broken by the most recent
    `start_time`. `rows` is expected already filtered by `_query_candidate_events()`.

    Args:
        rows: Candidate event rows.

    Returns:
        (rank, event_id) for the best row, or None if `rows` is empty or has no row with a
        usable event id.
    """
    best_rank: int | None = None
    best_start_time: float = 0.0
    best_event_id: str = ""
    for row in rows:
        event_id = row.get("id")
        if not isinstance(event_id, str) or not event_id:
            continue
        rank = RANK_PERSON if row.get("label") == _PERSON_LABEL else RANK_OTHER
        start_time = row.get("start_time")
        start_time = float(start_time) if isinstance(start_time, (int, float)) else 0.0
        if best_rank is None or (rank, -start_time) < (best_rank, -best_start_time):
            best_rank, best_start_time, best_event_id = rank, start_time, event_id
    return (best_rank, best_event_id) if best_rank is not None else None


def _check_clip_ready(base_url: str, event_id: str, timeout: float) -> bool:
    """Single bounded check of whether Frigate reports a clip ready for `event_id`.

    Mirrors `_get_json()`'s never-raise contract: any HTTP/network error or malformed
    response resolves to False, the same as "not ready yet" — never raises.

    Reads the event row's `has_clip` boolean (per `scripts/frigate_latency_probe.py`'s
    `poll()`, line 137) rather than probing the guessable `.../clip.mp4` URL directly —
    one HTTP call cheaper, and the more direct readiness signal Frigate itself exposes.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        event_id: Frigate event id whose clip readiness to check.
        timeout: Per-request timeout in seconds.

    Returns:
        True if the event row's `has_clip` field is truthy, False otherwise (including
        on any error or malformed response).
    """
    url = f"{base_url}/api/events/{urllib.parse.quote(event_id, safe='')}"
    body = _get_json(url, timeout)
    _logger.debug(f"_check_clip_ready: GET {url} -> {body!r}")
    if not isinstance(body, dict):
        return False
    return bool(body.get("has_clip"))


async def _run_with_deadline_timeout(
    func: Callable[..., _T], *args: object, timeout: float
) -> _T | None:
    """Run a blocking `func` in a thread, bounded by `timeout` + slack. Never raises: a
    timeout resolves to None, matching each caller's own "no answer" handling.

    Args:
        func: Blocking callable to offload via `asyncio.to_thread()`.
        *args: Positional arguments forwarded to `func`.
        timeout: Per-call timeout in seconds (the `asyncio.wait_for()` bound adds
            `PREFETCH_WAIT_FOR_SLACK_S` on top).

    Returns:
        `func`'s return value, or None if it didn't complete within the bound.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args), timeout=timeout + PREFETCH_WAIT_FOR_SLACK_S
        )
    except (asyncio.TimeoutError, TimeoutError):
        return None


async def _create_forced_capture(
    base_url: str, camera: str, deadline: float, http_timeout_s: float
) -> PrefetchResult | None:
    """Step 1 (FR1): create the manual "alarm" event. Logs one warning on failure.

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name.
        deadline: Absolute `time.monotonic()` deadline for the whole run — the timeout
            passed to the create call is capped to whatever budget remains at entry (code
            review 2026-09-27: kept consistent with every other call in the any-label
            search loop, which already caps to `min(http_timeout_s, remaining)`).
        http_timeout_s: Per-request timeout in seconds.

    Returns:
        A rank-RANK_MANUAL `PrefetchResult` with `clip_found=True` (Decision 6) on success,
        or None on any refusal/timeout/error — never raises.
    """
    create_timeout = min(http_timeout_s, max(deadline - time.monotonic(), 0.0))
    result = await _run_with_deadline_timeout(
        _create_manual_event, base_url, camera, create_timeout, timeout=create_timeout
    )
    event_id, status = result if result is not None else (None, None)
    if event_id:
        return PrefetchResult(found=True, event_id=event_id, clip_found=True, rank=RANK_MANUAL)
    _logger.warning(
        f"_create_forced_capture: manual event create failed (status={status!r}) — "
        "continuing with the any-label search only"
    )
    return None


async def _maybe_upgrade_clip(
    base_url: str, best: PrefetchResult, deadline: float, http_timeout_s: float
) -> PrefetchResult:
    """Step 2 clip upgrade: check `_check_clip_ready()` for the currently held rank-1/2
    event, once per poll iteration (Decision 6 — unlike rank 3, ranks 1/2 wait for it).

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        best: The currently held best `PrefetchResult`.
        deadline: Absolute `time.monotonic()` deadline for the whole run.
        http_timeout_s: Per-request timeout in seconds.

    Returns:
        `best` with `clip_found=True` if the clip just became ready, otherwise `best`
        unchanged. Never raises.
    """
    if best.rank not in (RANK_PERSON, RANK_OTHER) or best.clip_found or not best.event_id:
        return best
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return best
    clip_timeout = min(http_timeout_s, remaining)
    ready = await _run_with_deadline_timeout(
        _check_clip_ready, base_url, best.event_id, clip_timeout, timeout=clip_timeout
    )
    return replace(best, clip_found=True) if ready else best


async def prefetch_alarm_media(  # pylint: disable=too-many-arguments,too-many-locals
    base_url: str,
    camera: str,
    on_result: Callable[[PrefetchResult], Awaitable[None]],
    *,
    max_wait_s: float = PREFETCH_MAX_WAIT_S,
    poll_interval_s: float = PREFETCH_POLL_INTERVAL_S,
    http_timeout_s: float = PREFETCH_HTTP_TIMEOUT_S,
    after_buffer_s: float = PREFETCH_AFTER_BUFFER_S,
) -> PrefetchResult:
    """Best-effort alarm media prefetch, per ADR-17 Amendment 4.

    Runs entirely inside the alarm zone's immediate-action window, bounded by `max_wait_s`
    measured from entry (the forced-capture create call's own latency counts against the
    same budget). Never awaited by any PHP code, never raises, never deletes, ends, or sets
    retention on any Frigate event.

    Sequence:
      1. Create a forced-capture manual event on `camera` (rank RANK_MANUAL). On success,
         `on_result` is awaited immediately with `clip_found=True` (Decision 6: the manual
         event's URL is attached straight away, even though the clip isn't complete yet).
         On failure (refused, timeout, Frigate down), logs one warning and continues.
      2. Polls `GET /api/events` for any-label real events, ranked person > other label,
         ignoring same-rank events once a rank has been chosen (a later poll never
         downgrades to a same-rank, different event). `on_result` is awaited again on every
         strict rank improvement, and once more when the chosen rank-1/2 event's clip
         becomes ready (Decision 6: unlike rank 3, ranks 1/2 wait for `_check_clip_ready()`).
      3. Stops early once rank 1 (person) is reached AND its clip is ready. Otherwise keeps
         polling until `max_wait_s` is exhausted, in case a person event still appears.
      4. If nothing was ever found (create failed and no real event matched), sends exactly
         one final `on_result` call with `rank=RANK_NONE` — the only "miss" callback of the
         run, replacing 14-2 AC5's "always send a result" contract (superseded by the
         `run_id`-owning placeholder cache entry PHP writes before triggering this run).

    Args:
        base_url: e.g. "http://192.168.100.18:5000"
        camera: Frigate-native camera name.
        on_result: Awaited with each `PrefetchResult` improvement, in order. Any exception it
            raises is caught and logged — one bad callback never ends the run.
        max_wait_s: Total budget in seconds, from entry.
        poll_interval_s: Delay between polls in seconds.
        http_timeout_s: Per-request timeout in seconds.
        after_buffer_s: Grace window before "now" for the any-label search's `after=` filter.

    Returns:
        The final, best `PrefetchResult` of the run (same value as the last `on_result` call,
        or a RANK_NONE miss if nothing was ever found).
    """
    after_ts = int(time.time() - after_buffer_s)
    deadline = time.monotonic() + max_wait_s
    best = PrefetchResult(found=False, event_id=None, clip_found=False, rank=RANK_NONE)
    _logger.debug(
        f"prefetch_alarm_media: starting base_url={base_url!r} camera={camera!r} "
        f"after_ts={after_ts} max_wait_s={max_wait_s} poll_interval_s={poll_interval_s}"
    )

    async def _emit(result: PrefetchResult) -> None:
        try:
            await on_result(result)
        except Exception:
            _logger.warning("prefetch_alarm_media: on_result callback failed", exc_info=True)

    # Step 1 (FR1/FR2): forced capture first, before any polling.
    forced_capture = await _create_forced_capture(base_url, camera, deadline, http_timeout_s)
    if forced_capture is not None:
        best = forced_capture
        await _emit(best)

    # Step 2/3 (FR3/FR4): any-label search, ranked, with a clip upgrade for whichever
    # rank-1/2 event currently holds `best`.
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        query_timeout = min(http_timeout_s, remaining)
        rows = await _run_with_deadline_timeout(
            _query_candidate_events, base_url, camera, after_ts, query_timeout,
            timeout=query_timeout,
        )
        candidate = _best_candidate(rows or [])
        if candidate is not None:
            rank, event_id = candidate
            if rank < best.rank:
                best = PrefetchResult(found=True, event_id=event_id, clip_found=False, rank=rank)
                await _emit(best)

        upgraded = await _maybe_upgrade_clip(base_url, best, deadline, http_timeout_s)
        if upgraded is not best:
            best = upgraded
            await _emit(best)

        if best.rank == RANK_PERSON and best.clip_found:
            break

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(poll_interval_s, remaining))

    if best.rank == RANK_NONE:
        await _emit(best)

    return best
