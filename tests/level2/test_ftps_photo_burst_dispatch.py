"""Epic 18 / ticket 18.15: photo series by FTP/FTPS on a BA alarm.

The I/O matrix of the plan, with Frigate and ftplib mocked: the series is taken on
prefetchEvent, held in memory per run_id, and sent on the BA alarm over one connection
with the event snapshot last; without a series the single snapshot goes as before.
"""

import asyncio
import logging
import re
from unittest.mock import AsyncMock, patch

import pytest

from resources.siadc09d import daemon as daemon_module
from resources.siadc09d import frigate_prefetch
from resources.siadc09d.daemon import BURST_TTL_S, SIADaemon
from resources.siadc09d.frigate_prefetch import BURST_COUNT, capture_burst
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError
from tests.conftest import make_daemon_preset

_SECRET = "s3cr3t-pw"
_HOST = "10.0.0.5:5000"
_EVENT = "1700000.1-abc"
_RUN = "1700000000.123456-a1b2c3"
_CAMERA = "vigi_sud-est"
_NAME = re.compile(r"001234_03_(\d{10})_(\d{4})\.jpg")


@pytest.fixture
def daemon(caplog: pytest.LogCaptureFixture):
    """Daemon with complete FTPS settings and stubbed queue and callbacks."""
    caplog.set_level(logging.DEBUG)
    with patch("sys.argv", ["test"]):
        d = SIADaemon(preset=make_daemon_preset())
    d._enqueue_event = AsyncMock()
    d._send_callback = AsyncMock()
    d._run_prefetch = AsyncMock()
    d._ftps = FtpsSettings(enabled=True, host="ftp.example", port=21, user="u",
                           password=_SECRET, folder="upload")
    yield d
    for series in d._burst_series.values():
        series.expiry.cancel()


async def _drain(d: SIADaemon) -> None:
    """Join the tracked tasks (twice: the upload task is spawned by on_message)."""
    await asyncio.gather(*d._tasks, return_exceptions=True)
    await asyncio.gather(*d._tasks, return_exceptions=True)


def _photos(n: int) -> list[bytes]:
    """n distinct fake JPEG frames."""
    return [f"jpeg-{i}".encode() for i in range(1, n + 1)]


def _fake_capture(
    frames: list[bytes], hold: asyncio.Event | None = None, ready: asyncio.Event | None = None
):
    """capture_burst double: appends `frames`, sets `ready`, then waits on `hold` if given."""

    async def capture(_host: str, _camera: str, photos: list[bytes], **_kw: object) -> None:
        photos.extend(frames)
        if ready is not None:
            ready.set()
        if hold is not None:
            await hold.wait()

    return capture


async def _prefetch(d: SIADaemon, burst: bool = True) -> None:
    """Send the prefetchEvent of the immediate action."""
    await d.on_message("prefetchEvent", {
        "camera_eqlogic_id": 42, "camera_name": _CAMERA, "frigate_host": _HOST,
        "run_id": _RUN, "burst": burst,
    })


async def _alarm(d: SIADaemon, event_id: str = _EVENT, run_id: str = _RUN, **flags: bool) -> None:
    """Send the BA alarm with its ftps_upload payload."""
    upload = {"frigate_host": _HOST, "event_id": event_id, "run_id": run_id,
              "snapshot": True, "clip": False, **flags}
    await d.on_message("burglarAlarm", {"zone": "Z", "zone_number": 3, "ftps_upload": upload})


# ---- capture_burst ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_takes_five_frames_one_per_second() -> None:
    """
    Frigate serves every frame.

    Expected result:
    - 5 frames in order; 4 waits of about 1 s between frame starts; latest.jpg URL plain
    """
    urls: list[str] = []

    def get_bytes(url: str, _timeout: float) -> bytes:
        urls.append(url)
        return f"f{len(urls)}".encode()

    clock = [1000.0]

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    photos: list[bytes] = []
    with patch.object(frigate_prefetch, "_get_bytes", get_bytes), \
         patch.object(frigate_prefetch.time, "monotonic", lambda: clock[0]), \
         patch.object(frigate_prefetch.asyncio, "sleep", AsyncMock(side_effect=fake_sleep)) as sleep:
        await capture_burst(_HOST, _CAMERA, photos)
    # Assert: five frames, in order
    assert photos == [b"f1", b"f2", b"f3", b"f4", b"f5"] and BURST_COUNT == 5
    # Assert: one wait of 1 s between two frames, none after the last
    assert [c.args[0] for c in sleep.await_args_list] == pytest.approx([1.0] * 4)
    # Assert: the camera's current frame, no overlay
    assert urls[0] == (f"http://{_HOST}/api/{_CAMERA}/latest.jpg"
                       "?timestamp=0&bbox=0&zones=0&mask=0&motion=0&regions=0")


@pytest.mark.asyncio
async def test_capture_refused_gives_no_series_and_one_warning(caplog) -> None:
    """
    latest.jpg refused (HTTP error -> _get_bytes returns None).

    Expected result:
    - no frame held; exactly one WARNING; no further request
    """
    caplog.set_level(logging.WARNING)
    calls: list[str] = []

    def refused(url: str, _timeout: float) -> None:
        calls.append(url)

    photos: list[bytes] = []
    with patch.object(frigate_prefetch, "_get_bytes", refused):
        await capture_burst(_HOST, _CAMERA, photos)
    # Assert: no series
    assert photos == []
    # Assert: stopped at the first refusal
    assert len(calls) == 1
    # Assert: one warning
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


@pytest.mark.asyncio
async def test_identical_frames_are_kept_with_one_warning(caplog) -> None:
    """
    Camera offline: Frigate returns the same bytes every time.

    Expected result:
    - the 5 frames are kept; one WARNING only
    """
    caplog.set_level(logging.WARNING)
    photos: list[bytes] = []
    with patch.object(frigate_prefetch, "_get_bytes", return_value=b"same"), \
         patch.object(frigate_prefetch.asyncio, "sleep", AsyncMock()):
        await capture_burst(_HOST, _CAMERA, photos)
    # Assert: series kept
    assert photos == [b"same"] * 5
    # Assert: one warning for the frozen camera
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "identical" in warnings[0].getMessage()


# ---- daemon: I/O matrix ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_series_then_event_snapshot_on_one_connection(daemon) -> None:
    """
    Full series: 5 photos held, BA alarm with an event.

    Expected result:
    - one upload_many call: 0001..0005 (the series), then 0006 (the event snapshot)
    - one shared timestamp; no single-file upload; frame enqueued; series gone from memory
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"event")), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _prefetch(daemon)
        await _drain(daemon)
        await _alarm(daemon)
        await _drain(daemon)
    # Assert: one connection for the whole alarm
    many.assert_called_once()
    single.assert_not_called()
    files = many.call_args.args[1]
    parts = [_NAME.fullmatch(name).groups() for name, _ in files]
    # Assert: image numbers 0001..0006, series first, event snapshot last
    assert [img for _, img in parts] == ["0001", "0002", "0003", "0004", "0005", "0006"]
    assert [data for _, data in files] == _photos(5) + [b"event"]
    # Assert: same timestamp for every file
    assert len({ts for ts, _ in parts}) == 1
    # Assert: the frame went out, and the series is no longer held
    daemon._enqueue_event.assert_awaited_once()
    assert daemon._burst_series == {}


@pytest.mark.asyncio
async def test_alarm_early_sends_the_photos_held(daemon) -> None:
    """
    Alarm early: 2 photos held, capture still running.

    Expected result:
    - the 2 photos are sent (plus the event snapshot); the capture is stopped
    """
    hold, ready = asyncio.Event(), asyncio.Event()
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(2), hold, ready)), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"event")), \
         patch.object(daemon_module, "upload_many") as many:
        await _prefetch(daemon)
        await asyncio.wait_for(ready.wait(), timeout=1.0)
        capture_task = daemon._burst_series[_RUN].task
        await _alarm(daemon)
        await _drain(daemon)
    files = many.call_args.args[1]
    # Assert: the 2 held photos then the snapshot
    assert [data for _, data in files] == _photos(2) + [b"event"]
    # Assert: capture stopped
    assert capture_task.cancelled()


@pytest.mark.asyncio
async def test_no_series_sends_the_single_snapshot_as_before(daemon) -> None:
    """
    No series: unknown run (daemon restarted) or a payload without run_id.

    Expected result:
    - one single-file upload named ..._0001.jpg per alarm; upload_many never used
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"event")), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _alarm(daemon)
        await _alarm(daemon, run_id="")
        await _drain(daemon)
    # Assert: no series upload
    many.assert_not_called()
    # Assert: the 18.13 single snapshot, twice
    assert single.call_count == 2
    assert all(_NAME.fullmatch(c.args[1]).group(2) == "0001" for c in single.call_args_list)


@pytest.mark.asyncio
async def test_latest_refused_falls_back_to_the_single_snapshot(daemon) -> None:
    """
    latest.jpg refused: the capture held nothing.

    Expected result:
    - the event snapshot goes alone, as before
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture([])), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"event")), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _prefetch(daemon)
        await _drain(daemon)
        await _alarm(daemon)
        await _drain(daemon)
    # Assert: fallback single snapshot
    many.assert_not_called()
    single.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_in_delay_nothing_uploaded_and_series_expires(daemon) -> None:
    """
    Cancelled in the delay: no BA alarm follows.

    Expected result:
    - the series expires BURST_TTL_S (120 s) after the prefetch; nothing is uploaded
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _prefetch(daemon)
        await _drain(daemon)
        series = daemon._burst_series[_RUN]
        loop = asyncio.get_running_loop()
        # Assert: expiry armed at 120 s
        assert BURST_TTL_S == 120.0
        assert series.expiry.when() - loop.time() == pytest.approx(BURST_TTL_S, abs=1.0)
        daemon._expire_burst(_RUN)  # what the timer runs at 120 s
    # Assert: the series is gone
    assert daemon._burst_series == {}
    # Assert: nothing uploaded
    many.assert_not_called()
    single.assert_not_called()


@pytest.mark.asyncio
async def test_partial_failure_one_notification_naming_the_count(daemon, caplog) -> None:
    """
    Partial failure: the connection drops after 3 photos of 5 (no event).

    Expected result:
    - one notification pair saying "3 photos sur 5"; ERROR logged; no retry; no password
    """
    err = FtpsUploadError("step upload: ConnectionResetError: reset", sent=3)
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "upload_many", side_effect=err) as many:
        await _prefetch(daemon)
        await _drain(daemon)
        await _alarm(daemon, event_id="")
        await _drain(daemon)
    sent = [c.args[0] for c in daemon._send_callback.await_args_list]
    # Assert: a single attempt
    many.assert_called_once()
    # Assert: one notification, naming how many photos arrived
    assert [p["type"] for p in sent] == ["message_center", "notify"]
    assert "3 photos sur 5" in sent[1]["message"]
    # Assert: logged at ERROR
    assert any(r.levelno == logging.ERROR and "3 photos sur 5" in r.getMessage()
               for r in caplog.records)
    # Assert: password nowhere
    assert _SECRET not in caplog.text and _SECRET not in repr(sent)


@pytest.mark.asyncio
async def test_missing_event_photo_is_reported_once_and_series_still_sent(daemon) -> None:
    """
    Series held, event exists, but Frigate serves no event snapshot.

    Expected result:
    - the 5 series photos are sent; exactly one notification pair naming the missing
      event photo and the count of series photos sent
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=None)), \
         patch.object(daemon_module, "upload_many") as many:
        await _prefetch(daemon)
        await _drain(daemon)
        await _alarm(daemon)
        await _drain(daemon)
    sent = [c.args[0] for c in daemon._send_callback.await_args_list]
    # Assert: the series went out without the event photo
    assert [data for _, data in many.call_args.args[1]] == _photos(5)
    # Assert: one notification pair
    assert [p["type"] for p in sent] == ["message_center", "notify"]
    # Assert: it names the count and the missing event photo
    assert "5 photos de la série envoyées" in sent[1]["message"]
    assert f"aucune photo reçue de Frigate {_HOST} pour l'évènement {_EVENT}" in sent[1]["message"]


@pytest.mark.asyncio
async def test_no_frigate_event_sends_the_series_alone(daemon, caplog) -> None:
    """
    No Frigate event (manual create refused), series held, clip wanted too.

    Expected result:
    - the series is sent; no event snapshot or clip fetched; one WARNING for the missing event
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock()) as snap, \
         patch.object(daemon_module, "fetch_event_clip", AsyncMock()) as clip, \
         patch.object(daemon_module, "upload_many") as many:
        await _prefetch(daemon)
        await _drain(daemon)
        caplog.clear()
        await _alarm(daemon, event_id="", clip=True)
        await _drain(daemon)
    # Assert: series sent, 5 files
    assert [data for _, data in many.call_args.args[1]] == _photos(5)
    # Assert: no event media fetched
    snap.assert_not_awaited()
    clip.assert_not_awaited()
    # Assert: one warning about the missing event
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "no Frigate event" in warnings[0].getMessage()


@pytest.mark.asyncio
@pytest.mark.parametrize("burst, active", [(False, True), (True, False)])
async def test_no_burst_without_flag_or_ftps(daemon, burst: bool, active: bool) -> None:
    """
    prefetchEvent without the burst flag, or a daemon without active FTPS settings.

    Expected result:
    - no capture starts and nothing is held
    """
    if not active:
        daemon._ftps = FtpsSettings()
    capture = AsyncMock()
    with patch.object(daemon_module, "capture_burst", capture):
        await _prefetch(daemon, burst=burst)
        await _drain(daemon)
    # Assert: no capture
    capture.assert_not_called()
    # Assert: nothing held
    assert daemon._burst_series == {}


@pytest.mark.asyncio
async def test_photo_switch_off_never_sends_the_series(daemon) -> None:
    """
    Series held but the BA payload wants the clip only.

    Expected result:
    - no photo upload; the series is dropped from memory
    """
    with patch.object(daemon_module, "capture_burst", _fake_capture(_photos(5))), \
         patch.object(daemon_module, "fetch_event_clip",
                      AsyncMock(side_effect=daemon_module.ClipFetchError("x"))), \
         patch.object(daemon_module, "upload_many") as many:
        await _prefetch(daemon)
        await _drain(daemon)
        await _alarm(daemon, snapshot=False, clip=True)
        await _drain(daemon)
    # Assert: no photo upload
    many.assert_not_called()
    # Assert: series dropped
    assert daemon._burst_series == {}
