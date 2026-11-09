"""Epic 18 / ticket 18.5: clip fetch and its FTPS dispatch on a BA alarm.

The I/O matrix of the plan, with Frigate and ftplib mocked. The frame never waits and no
temporary clip file remains.
"""

import asyncio
import logging
import os
import time
from unittest.mock import AsyncMock, patch

import pytest

from resources.siadc09d import daemon as daemon_module
from resources.siadc09d import frigate_prefetch
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.frigate_prefetch import ClipFetchError, ClipFile, fetch_event_clip
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError
from tests.conftest import make_daemon_preset

_SECRET = "s3cr3t-pw"
_HOST = "10.0.0.5:5000"
_EVENT = "1700000.1-abc"


def _upload(**flags: bool) -> dict[str, object]:
    """ftps_upload payload with the given media flags."""
    return {"frigate_host": _HOST, "event_id": _EVENT, **flags}


@pytest.fixture
def daemon(caplog: pytest.LogCaptureFixture):
    """Daemon with complete FTPS settings and stubbed queue and callbacks."""
    caplog.set_level(logging.DEBUG)
    with patch("sys.argv", ["test"]):
        d = SIADaemon(preset=make_daemon_preset())
    d._enqueue_event = AsyncMock()
    d._send_callback = AsyncMock()
    d._ftps = FtpsSettings(enabled=True, host="ftp.example", port=21, user="u",
                           password=_SECRET, folder="upload")
    return d


async def _drain(d: SIADaemon) -> None:
    """Join the tracked tasks."""
    await asyncio.gather(*d._tasks, return_exceptions=True)


def _clip_file(tmp_path, duration: float = 35.0) -> ClipFile:
    """A real temporary clip file the daemon must delete."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"mp4")
    return ClipFile(path=str(path), size=3, duration_s=duration)


# ---- fetch_event_clip ------------------------------------------------------------------


def _fake_download(content: bytes = b"mp4", results: list[int] | None = None):
    """_download_clip_to_file double: writes content, returns the scripted sizes then len."""
    calls: list[str] = []
    scripted = list(results or [])

    def download(_url: str, path: str, _deadline: float) -> int:
        calls.append(path)
        if scripted and (size := scripted.pop(0)) == 0:
            return 0
        with open(path, "wb") as out:
            out.write(content)
        return len(content)

    download.calls = calls  # type: ignore[attr-defined]
    return download


@pytest.mark.asyncio
async def test_ended_event_downloads_at_once() -> None:
    """
    BA after the trigger delay: the event ended long ago.

    Expected result:
    - no sleep, the clip is in a temp file, duration read from the row
    """
    row = {"start_time": time.time() - 100, "end_time": time.time() - 60}
    download = _fake_download()
    with patch.object(frigate_prefetch, "_get_json", return_value=row), \
         patch.object(frigate_prefetch, "_download_clip_to_file", download), \
         patch.object(frigate_prefetch.asyncio, "sleep", AsyncMock()) as sleep:
        clip = await fetch_event_clip(_HOST, _EVENT)
    try:
        # Assert: no wait for a finished event
        sleep.assert_not_awaited()
        # Assert: the file exists with the clip and the duration comes from the row
        assert os.path.getsize(clip.path) == 3 and clip.duration_s == pytest.approx(40.0)
    finally:
        frigate_prefetch.remove_clip_file(clip.path)


@pytest.mark.asyncio
async def test_running_event_waits_for_its_end_plus_margin() -> None:
    """
    Event still running, ending soon.

    Expected result:
    - one sleep of about end - now + margin before the download
    """
    now = time.time()
    row = {"start_time": now - 5, "end_time": now + 20}
    with patch.object(frigate_prefetch, "_get_json", return_value=row), \
         patch.object(frigate_prefetch, "_download_clip_to_file", _fake_download()), \
         patch.object(frigate_prefetch.asyncio, "sleep", AsyncMock()) as sleep:
        clip = await fetch_event_clip(_HOST, _EVENT)
    frigate_prefetch.remove_clip_file(clip.path)
    # Assert: waited for the end plus the margin
    assert sleep.await_args.args[0] == pytest.approx(20 + frigate_prefetch.CLIP_END_MARGIN_S, abs=1.0)


@pytest.mark.asyncio
async def test_clip_not_ready_is_retried_then_fails_without_leftover(monkeypatch, tmp_path) -> None:
    """
    Frigate keeps answering an error.

    Expected result:
    - several attempts, then ClipFetchError; the temp file is gone
    """
    monkeypatch.setattr(frigate_prefetch, "CLIP_MAX_WAIT_S", 0.1)
    monkeypatch.setattr(frigate_prefetch, "CLIP_POLL_INTERVAL_S", 0.02)
    monkeypatch.setattr(frigate_prefetch.tempfile, "tempdir", str(tmp_path))
    download = _fake_download(results=[0] * 1000)
    with patch.object(frigate_prefetch, "_get_json", return_value={"end_time": 1.0}), \
         patch.object(frigate_prefetch, "_download_clip_to_file", download):
        with pytest.raises(ClipFetchError, match="non disponible"):
            await fetch_event_clip(_HOST, _EVENT)
    # Assert: retried more than once
    assert len(download.calls) > 1
    # Assert: no temp file remains
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_clip_ready_on_second_attempt(monkeypatch) -> None:
    """
    First answer is an error, then the clip is served.

    Expected result:
    - two attempts and a clip
    """
    monkeypatch.setattr(frigate_prefetch, "CLIP_POLL_INTERVAL_S", 0.01)
    download = _fake_download(results=[0])
    with patch.object(frigate_prefetch, "_get_json", return_value=None), \
         patch.object(frigate_prefetch, "_download_clip_to_file", download):
        clip = await fetch_event_clip(_HOST, _EVENT)
    frigate_prefetch.remove_clip_file(clip.path)
    # Assert: retried once
    assert len(download.calls) == 2


@pytest.mark.asyncio
async def test_too_large_clip_leaves_no_file(monkeypatch, tmp_path) -> None:
    """
    Body above CLIP_MAX_BYTES.

    Expected result:
    - ClipFetchError naming the cap; the temp file is deleted
    """
    from tests.level1.test_ftps_clip import _FakeResponse  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(frigate_prefetch, "CLIP_MAX_BYTES", 1024)
    monkeypatch.setattr(frigate_prefetch, "CLIP_CHUNK_BYTES", 256)
    monkeypatch.setattr(frigate_prefetch.tempfile, "tempdir", str(tmp_path))
    with patch.object(frigate_prefetch, "_get_json", return_value=None), \
         patch.object(frigate_prefetch.urllib.request, "urlopen",
                      return_value=_FakeResponse(b"x" * 5000)):
        with pytest.raises(ClipFetchError, match="limite"):
            await fetch_event_clip(_HOST, _EVENT)
    # Assert: nothing left behind
    assert list(tmp_path.iterdir()) == []


# ---- daemon dispatch ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_switches_upload_snapshot_then_clip(daemon, tmp_path) -> None:
    """
    Both media wanted.

    Expected result:
    - snapshot uploaded first, then the clip file; frame untouched; temp clip deleted
    """
    clip = _clip_file(tmp_path)
    order: list[str] = []
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"jpeg")), \
         patch.object(daemon_module, "fetch_event_clip", AsyncMock(return_value=clip)), \
         patch.object(daemon_module, "upload_bytes", side_effect=lambda *a: order.append(a[1])), \
         patch.object(daemon_module, "upload_file", side_effect=lambda *a: order.append(a[1])):
        await daemon.on_message("burglarAlarm", {"zone": "Z", "ftps_upload": _upload(snapshot=True, clip=True)})
        await _drain(daemon)
    # Assert: snapshot then clip, with the fixed names
    assert order == ["001234-1700000.1-abc-snapshot.jpg", "001234-1700000.1-abc-clip.mp4"]
    # Assert: frame enqueued once, no media tag
    daemon._enqueue_event.assert_awaited_once()
    assert daemon._enqueue_event.await_args.kwargs["media"] is None
    # Assert: temporary file deleted
    assert not os.path.exists(clip.path)


@pytest.mark.asyncio
async def test_clip_only(daemon, tmp_path) -> None:
    """
    Snapshot switch off, clip on.

    Expected result:
    - no snapshot fetch or upload; the clip is uploaded
    """
    clip = _clip_file(tmp_path)
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock()) as snap, \
         patch.object(daemon_module, "fetch_event_clip", AsyncMock(return_value=clip)), \
         patch.object(daemon_module, "upload_bytes") as up_bytes, \
         patch.object(daemon_module, "upload_file") as up_file:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=False, clip=True)})
        await _drain(daemon)
    # Assert: snapshot untouched
    snap.assert_not_awaited()
    up_bytes.assert_not_called()
    # Assert: clip uploaded from its file
    assert up_file.call_args[0][2] == clip.path


@pytest.mark.asyncio
async def test_snapshot_only_is_the_18_2_behaviour(daemon) -> None:
    """
    Clip switch off, and a payload without flags (older plugin).

    Expected result:
    - the clip is never fetched; the snapshot is uploaded in both cases
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"j")), \
         patch.object(daemon_module, "fetch_event_clip", AsyncMock()) as clip_fetch, \
         patch.object(daemon_module, "upload_bytes") as up_bytes:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=True, clip=False)})
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload()})
        await _drain(daemon)
    # Assert: no clip work
    clip_fetch.assert_not_awaited()
    # Assert: one snapshot upload per alarm
    assert up_bytes.call_count == 2


@pytest.mark.asyncio
async def test_clip_never_ready_notifies_video_and_snapshot_is_unaffected(daemon, caplog) -> None:
    """
    The clip is never ready.

    Expected result:
    - snapshot uploaded, frame enqueued, ERROR + message center + notify with video wording
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"j")), \
         patch.object(daemon_module, "fetch_event_clip",
                      AsyncMock(side_effect=ClipFetchError("clip non disponible sur Frigate"))), \
         patch.object(daemon_module, "upload_bytes") as up_bytes:
        await daemon.on_message("burglarAlarm", {"zone": "Z", "ftps_upload": _upload(snapshot=True, clip=True)})
        await _drain(daemon)
    # Assert: snapshot uploaded and frame sent
    up_bytes.assert_called_once()
    daemon._enqueue_event.assert_awaited_once()
    sent = [c.args[0] for c in daemon._send_callback.await_args_list]
    # Assert: user told once for the video
    assert [p["type"] for p in sent] == ["message_center", "notify"]
    assert "vidéo" in sent[1]["title"] and "vidéo" in sent[1]["message"]
    # Assert: ERROR logged
    assert any(r.levelno == logging.ERROR and "vidéo" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_too_large_clip_names_the_cap_in_the_notification(daemon) -> None:
    """
    Clip above the cap.

    Expected result:
    - nothing uploaded, notification naming the cap
    """
    with patch.object(daemon_module, "fetch_event_clip",
                      AsyncMock(side_effect=ClipFetchError("clip trop volumineux (limite 200 Mo)"))), \
         patch.object(daemon_module, "upload_file") as up_file:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=False, clip=True)})
        await _drain(daemon)
    # Assert: no upload
    up_file.assert_not_called()
    # Assert: the cap is named
    assert "limite 200 Mo" in daemon._send_callback.await_args_list[1].args[0]["message"]


@pytest.mark.asyncio
async def test_snapshot_fails_clip_still_attempted(daemon, tmp_path, caplog) -> None:
    """
    FTPS refuses the snapshot, accepts the clip.

    Expected result:
    - clip uploaded; exactly one failure notification (photo wording); password nowhere
    """
    clip = _clip_file(tmp_path)
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"j")), \
         patch.object(daemon_module, "fetch_event_clip", AsyncMock(return_value=clip)), \
         patch.object(daemon_module, "upload_bytes", side_effect=FtpsUploadError("step login: refused")), \
         patch.object(daemon_module, "upload_file") as up_file:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=True, clip=True)})
        await _drain(daemon)
    # Assert: clip attempted despite the snapshot failure
    up_file.assert_called_once()
    sent = [c.args[0] for c in daemon._send_callback.await_args_list]
    # Assert: one notification pair, for the photo
    assert [p["type"] for p in sent] == ["message_center", "notify"]
    assert "photo" in sent[1]["title"]
    # Assert: password absent
    assert _SECRET not in caplog.text and _SECRET not in repr(sent)


@pytest.mark.asyncio
async def test_clip_upload_failure_deletes_the_temp_file(daemon, tmp_path) -> None:
    """
    FTPS refuses the clip.

    Expected result:
    - video failure reported and the temporary file deleted anyway
    """
    clip = _clip_file(tmp_path)
    with patch.object(daemon_module, "fetch_event_clip", AsyncMock(return_value=clip)), \
         patch.object(daemon_module, "upload_file", side_effect=FtpsUploadError("step connect: refused")):
        await daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=False, clip=True)})
        await _drain(daemon)
    # Assert: user told about the video
    assert "vidéo" in daemon._send_callback.await_args_list[1].args[0]["title"]
    # Assert: file removed
    assert not os.path.exists(clip.path)


@pytest.mark.asyncio
async def test_clip_wait_does_not_delay_the_frame(daemon) -> None:
    """
    A clip fetch that is still waiting must not hold back on_message().

    Expected result:
    - the frame is enqueued while the clip task is pending
    """
    release = asyncio.Event()

    async def slow_fetch(*_args: object) -> ClipFile:
        await release.wait()
        raise ClipFetchError("late")

    with patch.object(daemon_module, "fetch_event_clip", slow_fetch):
        await asyncio.wait_for(
            daemon.on_message("burglarAlarm", {"ftps_upload": _upload(snapshot=False, clip=True)}),
            timeout=1.0,
        )
        # Assert: frame enqueued, clip task pending
        daemon._enqueue_event.assert_awaited_once()
        assert daemon._tasks
        release.set()
        await _drain(daemon)
