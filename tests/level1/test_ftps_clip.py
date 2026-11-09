"""Clip upload building blocks (epic 18, ticket 18.5): wait rule, capped download, file upload."""

import io
import os
import time
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import frigate_prefetch, ftps_upload
from resources.siadc09d.frigate_prefetch import ClipFetchError, clip_wait_s
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError, upload_file

_URL = "http://frigate:5000/api/events/e/clip.mp4"


class _FakeResponse:
    """urlopen() result: context manager with headers and a chunked body."""

    def __init__(self, body: bytes, length: str | None = None) -> None:
        self._body = io.BytesIO(body)
        self.headers = {"Content-Length": length} if length is not None else {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        """Next chunk."""
        return self._body.read(size)


def _settings() -> FtpsSettings:
    """Complete FTPS settings."""
    return FtpsSettings(enabled=True, host="ftp.example", port=21, user="u", password="pw",
                        folder="upload")


def test_clip_wait_follows_the_event_row() -> None:
    """
    Wait rule derived from end_time.

    Expected result:
    - ended or unknown end: 0; running: remaining time plus margin; beyond the cap: 0
    """
    now = 1000.0
    # Assert: already ended means no wait
    assert clip_wait_s(990.0, now) == 0.0
    # Assert: unknown end means download what exists
    assert clip_wait_s(None, now) == 0.0
    # Assert: running event waits until its end plus the margin
    assert clip_wait_s(1010.0, now) == pytest.approx(10.0 + frigate_prefetch.CLIP_END_MARGIN_S)
    # Assert: an end beyond the cap is not waited for
    assert clip_wait_s(now + frigate_prefetch.CLIP_MAX_WAIT_S + 1, now) == 0.0


def test_download_streams_to_the_file(tmp_path) -> None:
    """
    A normal clip body.

    Expected result:
    - the byte count is returned and the file holds the whole body
    """
    path = tmp_path / "c.mp4"
    with patch.object(frigate_prefetch.urllib.request, "urlopen",
                      return_value=_FakeResponse(b"x" * 100_000, "100000")):
        size = frigate_prefetch._download_clip_to_file(_URL, str(path), time.monotonic() + 5)
    # Assert: all bytes written
    assert size == 100_000 and path.read_bytes() == b"x" * 100_000


@pytest.mark.parametrize("declared", ["5000", None])
def test_download_stops_above_the_cap(tmp_path, monkeypatch, declared: str | None) -> None:
    """
    Body above CLIP_MAX_BYTES, announced by Content-Length or discovered while streaming.

    Expected result:
    - ClipFetchError naming the cap
    """
    monkeypatch.setattr(frigate_prefetch, "CLIP_MAX_BYTES", 1024)
    monkeypatch.setattr(frigate_prefetch, "CLIP_CHUNK_BYTES", 256)
    with patch.object(frigate_prefetch.urllib.request, "urlopen",
                      return_value=_FakeResponse(b"x" * 5000, declared)):
        with pytest.raises(ClipFetchError, match="limite"):
            frigate_prefetch._download_clip_to_file(_URL, str(tmp_path / "c"), time.monotonic() + 5)


def test_download_http_error_means_not_ready(tmp_path) -> None:
    """
    Frigate answers 400 (clip not flushed yet) or the connection fails.

    Expected result:
    - 0 bytes returned, no exception
    """
    error = urllib.error.HTTPError(_URL, 400, "bad", None, None)  # type: ignore[arg-type]
    with patch.object(frigate_prefetch.urllib.request, "urlopen", side_effect=error):
        # Assert: not ready, not an error
        assert frigate_prefetch._download_clip_to_file(_URL, str(tmp_path / "c"), time.monotonic() + 5) == 0


def test_download_past_deadline_aborts(tmp_path) -> None:
    """
    The deadline already passed when the first chunk is due.

    Expected result:
    - ClipFetchError
    """
    with patch.object(frigate_prefetch.urllib.request, "urlopen",
                      return_value=_FakeResponse(b"x" * 10)):
        with pytest.raises(ClipFetchError):
            frigate_prefetch._download_clip_to_file(_URL, str(tmp_path / "c"), time.monotonic() - 1)


def test_remove_clip_file_is_idempotent(tmp_path) -> None:
    """
    Deleting a temporary clip twice.

    Expected result:
    - the file is gone and the second call does not raise
    """
    path = tmp_path / "c.mp4"
    path.write_bytes(b"x")
    frigate_prefetch.remove_clip_file(str(path))
    frigate_prefetch.remove_clip_file(str(path))
    # Assert: removed
    assert not os.path.exists(path)


def test_upload_file_streams_the_file_with_the_same_sequence(tmp_path) -> None:
    """
    File upload.

    Expected result:
    - same explicit-TLS sequence as bytes; STOR receives the open file; traces unchanged
    """
    path = tmp_path / "c.mp4"
    path.write_bytes(b"mp4data")
    ftp = MagicMock()
    sent: list[bytes] = []
    ftp.transfercmd.return_value.sendall.side_effect = sent.append
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_file(_settings(), "a-clip.mp4", str(path))
    names = [c[0] for c in ftp.method_calls if c[0] in
             {"connect", "auth", "login", "prot_p", "cwd", "transfercmd", "close"}]
    # Assert: same sequence as upload_bytes
    assert names == ["connect", "auth", "login", "prot_p", "cwd", "transfercmd", "close"]
    # Assert: the file content reached STOR under the requested name
    assert sent == [b"mp4data"] and ftp.transfercmd.call_args[0][0] == "STOR a-clip.mp4"


def test_upload_file_missing_file_is_an_upload_error(tmp_path) -> None:
    """
    Local file vanished.

    Expected result:
    - FtpsUploadError, nothing sent
    """
    ftp = MagicMock()
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        with pytest.raises(FtpsUploadError, match="step read"):
            upload_file(_settings(), "a.mp4", str(tmp_path / "missing"))
    # Assert: no connection attempted
    ftp.connect.assert_not_called()


def test_local_disk_error_is_not_reported_as_clip_not_ready(tmp_path) -> None:
    """
    A local write failure while saving the clip must say so, not "no clip yet".

    Expected result:
    - the download raises a ClipFetchError naming the disk; nothing is retried as "not ready"
    """
    body = _FakeResponse(b"x" * 10)
    with patch.object(frigate_prefetch.urllib.request, "urlopen", return_value=body), \
         patch("builtins.open", side_effect=PermissionError(13, "Permission denied")), \
         pytest.raises(ClipFetchError, match="écriture du clip impossible"):
        frigate_prefetch._download_clip_to_file(_URL, str(tmp_path / "clip.mp4"), time.monotonic() + 5)


@pytest.mark.asyncio
async def test_retries_start_after_the_event_end_wait(tmp_path) -> None:
    """
    A long wait for the event end must not eat the retry window of a clip not served yet.

    Expected result:
    - after waiting the 60 s maximum, a first "not ready" answer is retried and the second attempt succeeds
    """
    clock = [1000.0]

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    answers = iter([0, 5])
    row = {"start_time": 0.0, "end_time": 100.0}
    with patch.object(frigate_prefetch, "_get_json", return_value=row), \
         patch.object(frigate_prefetch.time, "time", return_value=100.0 - 57.0), \
         patch.object(frigate_prefetch.time, "monotonic", side_effect=lambda: clock[0]), \
         patch.object(frigate_prefetch.asyncio, "sleep", fake_sleep), \
         patch.object(frigate_prefetch, "_download_clip_to_file",
                      side_effect=lambda *_a: next(answers)):
        clip = await frigate_prefetch.fetch_event_clip("frigate:5000", "e")
    # Assert: the second attempt delivered the clip after the maximum wait and one poll
    assert clip.size == 5
    frigate_prefetch.remove_clip_file(clip.path)


@pytest.mark.asyncio
async def test_temp_file_failure_is_a_clip_error() -> None:
    """
    No temporary file can be created (disk or directory problem).

    Expected result:
    - fetch_event_clip raises ClipFetchError (reported to the user), not a bare OSError
    """
    row = {"start_time": 100.0, "end_time": 130.0}
    with patch.object(frigate_prefetch, "_get_json", return_value=row), \
         patch.object(frigate_prefetch.tempfile, "mkstemp", side_effect=OSError(28, "No space left")), \
         pytest.raises(ClipFetchError, match="écriture du clip impossible"):
        await frigate_prefetch.fetch_event_clip("frigate:5000", "e")
