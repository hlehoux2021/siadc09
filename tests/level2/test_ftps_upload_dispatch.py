"""Epic 18 / ticket 18.2: daemon-side FTPS snapshot upload on a BA alarm.

The frame is enqueued exactly as before; the upload is a tracked background task that never
delays it, runs for BA only, and never logs the password.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d import daemon as daemon_module
from resources.siadc09d.daemon import SIADaemon
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError
from tests.conftest import make_daemon_preset

_SECRET = "s3cr3t-pw"
_UPLOAD = {"frigate_host": "10.0.0.5:5000", "event_id": "1700000.1-abc"}


def _settings(**overrides: object) -> FtpsSettings:
    """FTPS settings, complete and enabled unless overridden."""
    values: dict[str, object] = {
        "enabled": True, "host": "ftp.example", "port": 21, "user": "u",
        "password": _SECRET, "folder": "upload",
    }
    values.update(overrides)
    return FtpsSettings(**values)  # type: ignore[arg-type]


@pytest.fixture
def daemon(caplog: pytest.LogCaptureFixture):
    """Daemon with a complete FTPS config and a stubbed event queue."""
    caplog.set_level(logging.DEBUG)
    with patch("sys.argv", ["test"]):
        d = SIADaemon(preset=make_daemon_preset())
    d._enqueue_event = AsyncMock()
    d._ftps = _settings()
    return d


async def _drain(d: SIADaemon) -> None:
    """Join the tracked tasks."""
    await asyncio.gather(*d._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_ba_uploads_snapshot_and_enqueues_frame(daemon) -> None:
    """
    BA with ftps_upload: the frame is enqueued without media and the snapshot is uploaded.

    Expected result:
    - one frame enqueued, media None (no U/V tag)
    - upload_bytes called with the Frigate bytes and the fixed remote name
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"jpeg")), \
         patch.object(daemon_module, "upload_bytes") as upload:
        await daemon.on_message("burglarAlarm", {"zone": "Z", "zone_number": 1, "ftps_upload": _UPLOAD})
        await _drain(daemon)

    # Assert: frame enqueued once, carrying no media tag
    daemon._enqueue_event.assert_awaited_once()
    assert daemon._enqueue_event.await_args.kwargs["media"] is None
    settings, name, data = upload.call_args[0]
    # Assert: uploaded to the configured host with the downloaded bytes and fixed name
    assert settings.host == "ftp.example" and data == b"jpeg"
    assert name == "001234-1700000.1-abc-snapshot.jpg"


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", ["fireAlarm", "panicAlarm", "arm"])
async def test_non_ba_never_uploads(daemon, cmd: str) -> None:
    """
    Non-BA events never trigger an upload even if ftps_upload is present.

    Expected result:
    - no snapshot fetch; frame still enqueued
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"x")) as fetch:
        await daemon.on_message(cmd, {"user_number": 1, "ftps_upload": _UPLOAD})
        await _drain(daemon)
    # Assert: nothing fetched
    fetch.assert_not_awaited()
    # Assert: frame unaffected
    daemon._enqueue_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_or_incomplete_keys_never_upload(daemon) -> None:
    """
    Disabled upload, empty host or empty user: no upload.

    Expected result:
    - no snapshot fetch for any of the three settings
    """
    for settings in (_settings(enabled=False), _settings(host=""), _settings(user="")):
        daemon._ftps = settings
        with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"x")) as fetch:
            await daemon.on_message("burglarAlarm", {"ftps_upload": _UPLOAD})
            await _drain(daemon)
        # Assert: no fetch with these settings
        fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_ftps_upload_key_means_no_upload(daemon) -> None:
    """
    Transport url (no ftps_upload in the payload): behaviour unchanged.

    Expected result:
    - no snapshot fetch
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"x")) as fetch:
        await daemon.on_message("burglarAlarm", {"zone": "Z"})
        await _drain(daemon)
    # Assert: no fetch
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_slow_upload_does_not_delay_the_frame(daemon) -> None:
    """
    A stalled snapshot fetch must not hold back on_message().

    Expected result:
    - on_message returns and the frame is enqueued while the upload task is still pending
    """
    release = asyncio.Event()

    async def slow_fetch(*_args: object) -> bytes:
        await release.wait()
        return b"x"

    with patch.object(daemon_module, "fetch_event_snapshot", slow_fetch), \
         patch.object(daemon_module, "upload_bytes"):
        await asyncio.wait_for(
            daemon.on_message("burglarAlarm", {"ftps_upload": _UPLOAD}), timeout=1.0
        )
        # Assert: frame enqueued although the upload has not progressed
        daemon._enqueue_event.assert_awaited_once()
        # Assert: upload still pending in the background
        assert daemon._tasks
        release.set()
        await _drain(daemon)


@pytest.mark.asyncio
async def test_upload_failure_is_logged_without_password(daemon, caplog) -> None:
    """
    Server down: failure logged with host and reason, never the password.

    Expected result:
    - warning names host:port and reason; secret absent; no ERROR (task did not crash)
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"x")), \
         patch.object(daemon_module, "upload_bytes", side_effect=FtpsUploadError("OSError: refused")):
        await daemon.on_message("burglarAlarm", {"ftps_upload": _UPLOAD})
        await _drain(daemon)
    # Assert: host and reason logged
    assert "ftp.example:21" in caplog.text and "refused" in caplog.text
    # Assert: password never logged
    assert _SECRET not in caplog.text
    # Assert: handled, not an unhandled task exception
    assert "Unhandled exception" not in caplog.text


@pytest.mark.asyncio
async def test_snapshot_fetch_failure_skips_upload(daemon, caplog) -> None:
    """
    Frigate unreachable or no snapshot: no upload, frame unaffected.

    Expected result:
    - upload_bytes not called, frame enqueued, reason logged
    """
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=None)), \
         patch.object(daemon_module, "upload_bytes") as upload:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _UPLOAD})
        await _drain(daemon)
    # Assert: no upload attempted
    upload.assert_not_called()
    # Assert: frame enqueued regardless
    daemon._enqueue_event.assert_awaited_once()
    # Assert: failure logged
    assert "no snapshot" in caplog.text


def test_enabled_but_incomplete_warns_once_without_password(caplog) -> None:
    """
    FTPS enabled with empty host/user at start.

    Expected result:
    - exactly one FTPS warning; the password appears nowhere in the logs
    """
    caplog.set_level(logging.DEBUG)
    config = MagicMock(ftps_enabled=True, ftps_host="", ftps_user="", ftps_port=21,
                       ftps_password=_SECRET, ftps_folder="", ftps_cert_fingerprint="")
    with patch("sys.argv", ["test"]):
        SIADaemon(preset=make_daemon_preset(), config=config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "FTPS" in r.getMessage()]
    # Assert: one warning
    assert len(warnings) == 1
    # Assert: secret not logged
    assert _SECRET not in caplog.text


@pytest.mark.asyncio
async def test_inactive_daemon_says_so_when_plugin_requests_an_upload(daemon, caplog) -> None:
    """
    The plugin asks for an upload but the daemon started without FTPS settings.

    Expected result:
    - no fetch, frame enqueued, and a warning that points at the daemon settings (not silent)
    """
    daemon._ftps = FtpsSettings()
    with patch.object(daemon_module, "fetch_event_snapshot", AsyncMock(return_value=b"x")) as fetch:
        await daemon.on_message("burglarAlarm", {"ftps_upload": _UPLOAD})
        await _drain(daemon)
    # Assert: nothing fetched
    fetch.assert_not_awaited()
    # Assert: the reason is logged
    assert "no active FTPS settings" in caplog.text
