#!/usr/bin/env python3
"""Frigate event-media latency probe.

Standalone investigation tool for ADR-17 (see _bmad-output/planning-artifacts/architecture.md).
Not part of the shipped siaDC09 plugin or daemon — run manually against a real Frigate
server on the local network to measure two things ADR-17 left open:

1. How long after `POST /api/events/{camera}/{label}/create` the snapshot/clip/thumbnail
   become actually fetchable (HTTP 200), independent of the Jeedom Frigate plugin's own
   caching/sleep pipeline.
2. Whether Frigate's snapshot/clip/thumbnail URLs are reliably guessable from the
   `event_id` alone (`/api/events/{event_id}/snapshot.jpg`, `.../clip.mp4`,
   `.../thumbnail.jpg` — confirmed as Frigate's own route shapes from its FastAPI source),
   without needing to read a stored "url" field anywhere.

Usage:
    python3 scripts/frigate_latency_probe.py --host 192.168.100.18:5000 --camera vigi_sud-est
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class MediaProbeResult:
    """First-200 timing for one guessed media URL."""

    url: str
    first_200_at: float | None = None
    last_status: int | str | None = None


@dataclass
class ProbeState:
    """Accumulated state across the polling loop."""

    event_id: str
    t0: float
    event_row_first_seen_at: float | None = None
    has_snapshot_first_true_at: float | None = None
    has_clip_first_true_at: float | None = None
    snapshot: MediaProbeResult = field(default_factory=lambda: MediaProbeResult(url=""))
    clip: MediaProbeResult = field(default_factory=lambda: MediaProbeResult(url=""))
    thumbnail: MediaProbeResult = field(default_factory=lambda: MediaProbeResult(url=""))


def _http_json(url: str, data: dict | None = None, timeout: float = 5.0) -> tuple[int, dict | None]:
    """POST (if data given) or GET url, return (status, decoded_json_or_none)."""
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except (json.JSONDecodeError, ValueError):
            return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        return -1, {"error": str(e)}


def _http_status(url: str, timeout: float = 5.0) -> int:
    """GET url, return the HTTP status code only (no body read beyond what's needed)."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError):
        return -1


def create_event(
    base_url: str, camera: str, label: str, score: float, duration: int
) -> tuple[str | None, dict | None]:
    """Fire Frigate's manual-event-create endpoint. Returns (event_id, raw_response)."""
    url = f"{base_url}/api/events/{camera}/{label}/create"
    status, resp = _http_json(
        url,
        data={
            "duration": duration,
            "include_recording": True,
            "score": score,
        },
    )
    print(f"[create] POST {url} -> status={status} body={resp}")
    if status == 200 and resp and resp.get("success"):
        return resp.get("event_id"), resp
    return None, resp


def poll(
    base_url: str,
    state: ProbeState,
    poll_interval: float,
    max_wait: float,
) -> None:
    """Poll the event row and the three guessed media URLs until max_wait elapses."""
    state.snapshot.url = f"{base_url}/api/events/{state.event_id}/snapshot.jpg"
    state.clip.url = f"{base_url}/api/events/{state.event_id}/clip.mp4"
    state.thumbnail.url = f"{base_url}/api/events/{state.event_id}/thumbnail.jpg"

    while True:
        elapsed = time.monotonic() - state.t0
        if elapsed > max_wait:
            break

        status, row = _http_json(f"{base_url}/api/events/{state.event_id}")
        if status == 200 and row:
            if state.event_row_first_seen_at is None:
                state.event_row_first_seen_at = elapsed
            if row.get("has_snapshot") and state.has_snapshot_first_true_at is None:
                state.has_snapshot_first_true_at = elapsed
            if row.get("has_clip") and state.has_clip_first_true_at is None:
                state.has_clip_first_true_at = elapsed

        for probe in (state.snapshot, state.clip, state.thumbnail):
            probe.last_status = _http_status(probe.url)
            if probe.last_status == 200 and probe.first_200_at is None:
                probe.first_200_at = elapsed

        print(
            f"t={elapsed:6.2f}s  event_row={'ok' if status == 200 else status}  "
            f"has_snapshot={row.get('has_snapshot') if row else '?'}  "
            f"has_clip={row.get('has_clip') if row else '?'}  "
            f"snapshot.jpg={state.snapshot.last_status}  "
            f"clip.mp4={state.clip.last_status}  "
            f"thumbnail.jpg={state.thumbnail.last_status}"
        )

        if (
            state.snapshot.first_200_at is not None
            and state.clip.first_200_at is not None
        ):
            print("[probe] both snapshot and clip are 200 — stopping early.")
            break

        time.sleep(poll_interval)


def print_summary(state: ProbeState) -> None:
    print("\n=== Summary ===")
    print(f"event_id: {state.event_id}")
    print(
        "event row first fetchable at: "
        f"{state.event_row_first_seen_at:.2f}s"
        if state.event_row_first_seen_at is not None
        else "event row never became fetchable within max-wait"
    )
    for name, probe in (
        ("snapshot.jpg", state.snapshot),
        ("clip.mp4", state.clip),
        ("thumbnail.jpg", state.thumbnail),
    ):
        if probe.first_200_at is not None:
            print(f"{name}: guessable URL returned 200 at t={probe.first_200_at:.2f}s -> {probe.url}")
        else:
            print(f"{name}: never returned 200 within max-wait (last status={probe.last_status}) -> {probe.url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Frigate host:port, e.g. 192.168.100.18:5000")
    parser.add_argument("--camera", required=True, help="Frigate camera name, e.g. vigi_sud-est")
    parser.add_argument("--label", default="latency_probe", help="Event label (default: latency_probe)")
    parser.add_argument("--score", type=float, default=50.0, help="Event score 0-100 (default: 50)")
    parser.add_argument("--duration", type=int, default=10, help="Event duration seconds (default: 10)")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="Seconds between polls (default: 0.5)")
    parser.add_argument("--max-wait", type=float, default=60.0, help="Max seconds to poll after creation (default: 60)")
    args = parser.parse_args()

    base_url = f"http://{args.host}"
    t0 = time.monotonic()
    event_id, _ = create_event(base_url, args.camera, args.label, args.score, args.duration)
    if event_id is None:
        print("[error] event creation failed, aborting.")
        return

    state = ProbeState(event_id=event_id, t0=t0)
    poll(base_url, state, args.poll_interval, args.max_wait)
    print_summary(state)


if __name__ == "__main__":
    main()
