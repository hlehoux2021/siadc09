#!/usr/bin/env python3
"""Probe Frigate recordings/<ts>/snapshot.jpg over the window of a recent event (read-only).

Usage: python3 scripts/frigate_recordings_snapshot_probe.py HOST:PORT|BASE_URL CAMERA [OFFSET_S [EVENT_ID]]
OFFSET_S shifts the first frame relative to the event start (default 0). With EVENT_ID (CAMERA "-"), that event is probed.
"""
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = 15
FRAMES = 30
STEP_S = 1.0 / 3.0


def get(url: str) -> tuple[int, bytes, float]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read(), time.monotonic() - started
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200], time.monotonic() - started
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, str(e).encode(), time.monotonic() - started


def main() -> None:
    host, camera = sys.argv[1], sys.argv[2]
    offset = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    event_id = sys.argv[4] if len(sys.argv) > 4 else ""
    base = host.rstrip("/") if host.startswith("http") else f"http://{host}"
    if event_id:
        status, body, _ = get(f"{base}/api/events/{urllib.parse.quote(event_id, safe='')}")
    else:
        query = urllib.parse.urlencode({"cameras": camera, "limit": 5, "has_clip": 1})
        status, body, _ = get(f"{base}/api/events?{query}")
    print(f"events: HTTP {status}")
    if status != 200:
        print(body[:200])
        return
    events = [json.loads(body)] if event_id else json.loads(body)
    if event_id and events:
        camera = events[0]["camera"]
    for ev in events:
        print(f"  {ev['id']} label={ev.get('label')} start={ev['start_time']:.1f} "
              f"end={ev.get('end_time')} age={time.time() - ev['start_time']:.0f}s")
    if not events:
        print("no event with a clip")
        return
    ev = events[0]
    first = ev["start_time"] + offset
    print(f"probing event {ev['id']} from {first:.2f}, {FRAMES} frames, step {STEP_S:.3f}s")
    digests: list[str] = []
    sizes: list[int] = []
    failures = 0
    total_started = time.monotonic()
    for i in range(FRAMES):
        ts = first + i * STEP_S
        status, data, took = get(f"{base}/api/{camera}/recordings/{ts:.3f}/snapshot.jpg")
        ok = status == 200 and data[:2] == b"\xff\xd8"
        if ok:
            digests.append(hashlib.md5(data).hexdigest())
            sizes.append(len(data))
        else:
            failures += 1
        print(f"  #{i + 1:02d} ts={ts:.3f} HTTP {status} {len(data)}B {took:.2f}s "
              f"{'ok' if ok else data[:80]!r}")
    print(f"total {time.monotonic() - total_started:.1f}s, ok={len(digests)}, "
          f"failures={failures}, distinct frames={len(set(digests))}, "
          f"size min/max={min(sizes, default=0)}/{max(sizes, default=0)}")


if __name__ == "__main__":
    main()
