"""Epic 18 / ticket 18.15: photo series by FTP/FTPS on a BA alarm.

The I/O matrix of the plan, with Frigate and ftplib mocked: nothing happens at the prefetch;
at the BA alarm the daemon cuts the series from the event recordings and sends it over one
connection, named with the event start_time; without a frame the single event snapshot goes.
"""

import asyncio
import logging
import re
from unittest.mock import AsyncMock, patch

import pytest

from resources.siadc09d import daemon as daemon_module
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.frigate_prefetch import ClipFile, EventSeries
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError
from tests.conftest import make_daemon_preset

_SECRET = "s3cr3t-pw"
_HOST = "10.0.0.5:5000"
_EVENT = "1700000.1-abc"
_CAMERA = "vigi_sud-est"
_NAME = re.compile(r"001234_03_(\d{10})_(\d{4})\.(jpg|mp4)")
_START = 1700000000.5  # event start_time
_ALARM_NAME = re.compile(r"001234_03_(\d{10})_0001\.jpg")


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
    return d


async def _drain(d: SIADaemon) -> None:
    """Join the tracked tasks (twice: the upload task is spawned by on_message)."""
    await asyncio.gather(*d._tasks, return_exceptions=True)
    await asyncio.gather(*d._tasks, return_exceptions=True)


def _frames(n: int) -> list[bytes]:
    """n distinct fake JPEG frames."""
    return [f"jpeg-{i}".encode() for i in range(1, n + 1)]


def _series(n: int) -> AsyncMock:
    """fetch_event_frames double returning n frames from _START."""
    return AsyncMock(return_value=EventSeries(start_time=_START, frames=_frames(n)))


async def _alarm(d: SIADaemon, event_id: str = _EVENT, **flags: bool) -> None:
    """Send the BA alarm with its ftps_upload payload."""
    upload = {"frigate_host": _HOST, "event_id": event_id, "snapshot": True, "clip": False, **flags}
    await d.on_message("burglarAlarm", {"zone": "Z", "zone_number": 3, "ftps_upload": upload})


@pytest.mark.asyncio
async def test_full_series_alone_on_one_connection_named_by_start_time(daemon) -> None:
    """
    Full series: event with recordings, BA alarm.

    Expected result:
    - one upload_many call: 0001..0030, every name with the event start_time epoch
    - the event snapshot is neither fetched nor sent; frame enqueued
    """
    with patch.object(daemon_module, "fetch_event_frames", _series(30)), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"e")) as snap, \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _alarm(daemon)
        await _drain(daemon)
    # Assert: one connection, no single upload
    many.assert_called_once()
    single.assert_not_called()
    files = many.call_args.args[1]
    parts = [_NAME.fullmatch(name).groups() for name, _ in files]
    # Assert: image numbers 0001..0030 in order
    assert [img for _, img, _ in parts] == [f"{i:04d}" for i in range(1, 31)]
    assert [data for _, data in files] == _frames(30)
    # Assert: one epoch, the event start_time
    assert {int(ts) for ts, _, _ in parts} == {int(_START)}
    # Assert: no event snapshot with a series; frame went out
    snap.assert_not_awaited()
    daemon._enqueue_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_prefetch_requests_no_frame_and_arms_no_timer(daemon) -> None:
    """
    prefetchEvent (even with an old burst flag).

    Expected result:
    - no frame requested from Frigate, no timer armed, no state held
    """
    loop = asyncio.get_running_loop()
    with patch.object(daemon_module, "fetch_event_frames", AsyncMock()) as frames, \
         patch.object(loop, "call_later") as timer:
        await daemon.on_message("prefetchEvent", {
            "camera_eqlogic_id": 42, "camera_name": _CAMERA, "frigate_host": _HOST,
            "run_id": "1700000000.1-aa", "burst": True,
        })
        await _drain(daemon)
    # Assert: nothing fetched, no timer
    frames.assert_not_awaited()
    timer.assert_not_called()
    # Assert: no burst state on the daemon
    assert not hasattr(daemon, "_burst_series")


@pytest.mark.asyncio
async def test_no_frame_falls_back_to_the_event_snapshot_with_one_warning(daemon, caplog) -> None:
    """
    No recording and Frigate answers nothing for frames.

    Expected result:
    - the event snapshot goes alone, named ..._0001.jpg with the alarm epoch
    - exactly one WARNING for the fallback; upload_many never used
    """
    with patch.object(daemon_module, "fetch_event_frames",
                      AsyncMock(return_value=EventSeries(start_time=_START, frames=[]))), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"event")), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        caplog.clear()
        await _alarm(daemon)
        await _drain(daemon)
    # Assert: single snapshot, no series
    many.assert_not_called()
    single.assert_called_once()
    name = single.call_args.args[1]
    assert _ALARM_NAME.fullmatch(name) and int(_ALARM_NAME.fullmatch(name).group(1)) != int(_START)
    # Assert: one WARNING
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


@pytest.mark.asyncio
async def test_event_row_unreadable_also_falls_back(daemon) -> None:
    """
    Frigate down for the event row (fetch_event_frames returns None).

    Expected result:
    - the single event snapshot is attempted
    """
    with patch.object(daemon_module, "fetch_event_frames", AsyncMock(return_value=None)), \
         patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"e")), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _alarm(daemon)
        await _drain(daemon)
    # Assert: fallback used
    many.assert_not_called()
    single.assert_called_once()


@pytest.mark.asyncio
async def test_partial_failure_one_notification_naming_the_count(daemon, caplog) -> None:
    """
    The connection drops after 3 photos of 30.

    Expected result:
    - one notification pair "3 photos sur 30"; ERROR logged; no retry; no password
    """
    err = FtpsUploadError("step upload: ConnectionResetError: reset", sent=3)
    with patch.object(daemon_module, "fetch_event_frames", _series(30)), \
         patch.object(daemon_module, "upload_many", side_effect=err) as many:
        await _alarm(daemon)
        await _drain(daemon)
    sent = [c.args[0] for c in daemon._send_callback.await_args_list]
    # Assert: single attempt
    many.assert_called_once()
    # Assert: one notification, with the count
    assert [p["type"] for p in sent] == ["message_center", "notify"]
    assert "3 photos sur 30" in sent[1]["message"]
    # Assert: logged at ERROR
    assert any(r.levelno == logging.ERROR and "3 photos sur 30" in r.getMessage()
               for r in caplog.records)
    # Assert: password nowhere
    assert _SECRET not in caplog.text and _SECRET not in repr(sent)


@pytest.mark.asyncio
async def test_no_event_sends_nothing_with_one_warning(daemon, caplog) -> None:
    """
    BA payload without event id.

    Expected result:
    - nothing fetched nor uploaded
    """
    with patch.object(daemon_module, "fetch_event_frames", AsyncMock()) as frames, \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await _alarm(daemon, event_id="")
        await _drain(daemon)
    # Assert: no request, no upload
    frames.assert_not_awaited()
    many.assert_not_called()
    single.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_in_delay_nothing_fetched_or_uploaded(daemon) -> None:
    """
    Cancelled in the delay: only the prefetch ran, no BA alarm.

    Expected result:
    - no frame request, no upload
    """
    with patch.object(daemon_module, "fetch_event_frames", AsyncMock()) as frames, \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_bytes") as single:
        await daemon.on_message("prefetchEvent", {
            "camera_eqlogic_id": 42, "camera_name": _CAMERA, "frigate_host": _HOST,
            "run_id": "1700000000.1-aa",
        })
        await _drain(daemon)
    # Assert: nothing fetched, nothing uploaded
    frames.assert_not_awaited()
    many.assert_not_called()
    single.assert_not_called()


@pytest.mark.asyncio
async def test_series_and_clip_are_independent_with_their_own_epoch(daemon) -> None:
    """
    Series and clip wanted together.

    Expected result:
    - series named with start_time; clip named with the alarm epoch
    """
    clip = AsyncMock(return_value=ClipFile(path="/nonexistent/c.mp4", size=3,
                                                         duration_s=1.0))
    with patch.object(daemon_module, "fetch_event_frames", _series(3)), \
         patch.object(daemon_module, "fetch_event_clip", clip), \
         patch.object(daemon_module, "remove_clip_file"), \
         patch.object(daemon_module, "upload_many") as many, \
         patch.object(daemon_module, "upload_file") as file_upload:
        await _alarm(daemon, clip=True)
        await _drain(daemon)
    series_epoch = {int(_NAME.fullmatch(n).group(1)) for n, _ in many.call_args.args[1]}
    clip_match = _NAME.fullmatch(file_upload.call_args.args[1])
    # Assert: series carries start_time
    assert series_epoch == {int(_START)}
    # Assert: clip carries the alarm epoch, an .mp4 name
    assert clip_match.group(3) == "mp4" and int(clip_match.group(1)) != int(_START)


@pytest.mark.asyncio
async def test_photo_switch_off_never_fetches_frames(daemon) -> None:
    """
    BA payload wants the clip only.

    Expected result:
    - no frame fetch, no photo upload
    """
    with patch.object(daemon_module, "fetch_event_frames", AsyncMock()) as frames, \
         patch.object(daemon_module, "fetch_event_clip",
                      AsyncMock(side_effect=daemon_module.ClipFetchError("x"))), \
         patch.object(daemon_module, "upload_many") as many:
        await _alarm(daemon, snapshot=False, clip=True)
        await _drain(daemon)
    # Assert: nothing for the photo
    frames.assert_not_awaited()
    many.assert_not_called()
