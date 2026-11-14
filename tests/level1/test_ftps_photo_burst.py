"""Epic 18 / ticket 18.15: photo series naming, one-login upload, recordings fetch, PHP payloads.

The PHP part runs the real core/class/siaDC09Cmd.class.php with the stubs of
test_frigate_prefetch_trigger.py (prefetchEvent then burglarAlarm on one equipment).
"""

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import frigate_prefetch, ftps_upload
from resources.siadc09d.ftps_upload import FtpsSettings, FtpsUploadError, remote_location, upload_many
from tests.level1.test_frigate_prefetch_trigger import _EXECUTE_STUBS, PHP_CMD_FILE

_WHEN = datetime.fromtimestamp(1675938881, tz=timezone.utc)
_SECRET = "pw-s3cr3t"


def _settings() -> FtpsSettings:
    """Complete FTPS settings."""
    return FtpsSettings(enabled=True, host="ftp.example", user="u", password=_SECRET, folder="upload")


def test_image_number_is_four_digits_and_defaults_to_0001() -> None:
    """
    Image numbers of a series.

    Expected result:
    - default 0001 (the 18.13 single photo); image=5 gives 0005; same epoch for all
    """
    # Assert: the single-photo name is unchanged
    assert remote_location("12345678", 1, _WHEN, "jpg") == "12345678_01_1675938881_0001.jpg"
    # Assert: series numbering
    assert remote_location("12345678", 1, _WHEN, "jpg", image=5) == "12345678_01_1675938881_0005.jpg"


def test_upload_many_stores_every_file_on_one_login() -> None:
    """
    Five photos uploaded as one batch.

    Expected result:
    - one connection, one login, one cwd, five STOR in order
    """
    ftp = MagicMock()
    files = [(remote_location("1", 1, _WHEN, "jpg", image=i), b"x") for i in range(1, 6)]
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp) as factory:
        upload_many(_settings(), files)
    # Assert: one connection and one login
    factory.assert_called_once()
    ftp.login.assert_called_once()
    assert [c.args[0] for c in ftp.cwd.call_args_list] == ["upload"]
    # Assert: five STOR, in order
    assert [c.args[0] for c in ftp.transfercmd.call_args_list] == [f"STOR {n}" for n, _ in files]


def test_upload_many_failure_counts_the_files_sent() -> None:
    """
    The connection drops on the 4th STOR.

    Expected result:
    - FtpsUploadError with sent=3, naming the step; no retry; password absent; socket closed
    """
    ftp = MagicMock()
    ftp.transfercmd.side_effect = [MagicMock(), MagicMock(), MagicMock(), ConnectionResetError("reset")]
    files = [(f"f{i}.jpg", b"x") for i in range(1, 6)]
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        with pytest.raises(FtpsUploadError) as err:
            upload_many(_settings(), files)
    # Assert: 3 files reached the server
    assert err.value.sent == 3
    # Assert: the step is named, the password is not
    assert "step upload" in str(err.value) and _SECRET not in str(err.value)
    # Assert: no retry
    assert ftp.transfercmd.call_count == 4
    # Assert: connection closed
    ftp.close.assert_called_once()


# ---- recordings fetch ----------------------------------------------------------------------

_HOST = "10.0.0.5:5000"
_START = 1700000000.5
_ROW = {"camera": "vigi_sud-est", "start_time": _START}


def _fetch(get_bytes: Any, row: Any = _ROW) -> Any:
    """Run fetch_event_frames with Frigate faked at _get_json/_get_bytes."""
    with patch.object(frigate_prefetch, "_get_json", return_value=row), \
         patch.object(frigate_prefetch, "_get_bytes", get_bytes):
        return asyncio.run(frigate_prefetch.fetch_event_frames(_HOST, "evt"))


def test_full_series_is_thirty_frames_three_per_second_from_start_time() -> None:
    """
    Full series: Frigate serves every frame.

    Expected result:
    - 30 frames in order; URLs are recordings/<start_time + n/3>/snapshot.jpg; no latest.jpg
    """
    urls: list[str] = []

    def get_bytes(url: str, _timeout: float) -> bytes:
        urls.append(url)
        return f"f{len(urls)}".encode()

    series = _fetch(get_bytes)
    # Assert: thirty frames in order, start_time kept for the file names
    assert series.start_time == _START
    assert series.frames == [f"f{i}".encode() for i in range(1, 31)]
    # Assert: timestamps from start_time, a third of a second apart, recordings API only
    stamps = [float(re.search(r"/recordings/([\d.]+)/snapshot\.jpg", u).group(1)) for u in urls]
    assert stamps == pytest.approx([_START + n / 3 for n in range(30)], abs=0.001)
    assert all("latest.jpg" not in u for u in urls)


def test_frame_refused_twice_is_skipped_and_numbers_stay_consecutive() -> None:
    """
    One frame (n=4) refused at ts and at ts + 0.2 s.

    Expected result:
    - 29 frames kept in order; one DEBUG line per refusal
    """
    bad = {f"{_START + 4 / 3:.3f}", f"{_START + 4 / 3 + 0.2:.3f}"}

    def get_bytes(url: str, _timeout: float) -> bytes | None:
        stamp = re.search(r"/recordings/([\d.]+)/", url).group(1)
        return None if stamp in bad else stamp.encode()

    series = _fetch(get_bytes)
    # Assert: 29 frames, none of the refused one
    assert len(series.frames) == 29
    assert all(f.decode() not in bad for f in series.frames)


def test_frame_refused_once_is_kept_in_its_place() -> None:
    """
    Frame n=2 answers 404 at ts, 200 at ts + 0.2 s.

    Expected result:
    - 30 frames; the retried frame sits at index 2
    """
    first = f"{_START + 2 / 3:.3f}"

    def get_bytes(url: str, _timeout: float) -> bytes | None:
        stamp = re.search(r"/recordings/([\d.]+)/", url).group(1)
        return None if stamp == first else stamp.encode()

    series = _fetch(get_bytes)
    # Assert: nothing lost, order kept
    assert len(series.frames) == 30
    assert series.frames[2].decode() == f"{_START + 2 / 3 + 0.2:.3f}"


def test_three_consecutive_double_failures_stop_the_series() -> None:
    """
    The recording ends after 5 frames: everything later fails.

    Expected result:
    - the 5 frames held are returned; requests stop after 3 frames failing twice
    """
    calls = [0]

    def get_bytes(_url: str, _timeout: float) -> bytes | None:
        calls[0] += 1
        return b"ok" if calls[0] <= 5 else None

    series = _fetch(get_bytes)
    # Assert: frames held are kept
    assert series.frames == [b"ok"] * 5
    # Assert: 5 ok + 3 frames x 2 attempts, then stop
    assert calls[0] == 11


def test_no_event_row_gives_none_and_no_frame_request() -> None:
    """
    Frigate down: the event row cannot be read.

    Expected result:
    - None returned, no recordings request
    """
    get_bytes = MagicMock(return_value=b"x")
    # Assert: no series, nothing requested
    assert _fetch(get_bytes, row=None) is None
    get_bytes.assert_not_called()


# ---- PHP: prefetch and BA payloads ---------------------------------------------------------

_DRIVER = r"""
if (!function_exists('__')) { function __($text, $file = '') { return $text; } }
$scenario = json_decode(file_get_contents($argv[1]), true);
config::$values = ['frigate.URL' => '192.168.100.18', 'frigate.port' => '5000'];
eqLogic::$byId = [42 => new FakeEqLogic([], ['name' => 'vigi'])];
$eq = new FakeEqLogic([], array_merge([
    'sia_zone_mappings' => [['zone_name' => 'Salon', 'zone_number' => 3, 'frigate_camera_eqlogic_id' => 42]],
], $scenario['eq_config']));
$cmd = new siaDC09Cmd();
$cmd->eqLogic = $eq;
$cmd->logicalId = 'prefetchEvent';
$cmd->execute(['title' => 'Salon']);
if ($scenario['result'] !== null) {
    $cache = $eq->getCache('sia_prefetch_cache', []);
    $cache[42] = array_merge($cache[42], $scenario['result']);
    $eq->setCache('sia_prefetch_cache', $cache);
}
$cmd->logicalId = 'burglarAlarm';
$cmd->execute(['title' => 'Salon']);
echo json_encode(['sent' => siaDC09::$sent, 'logs' => log::$entries]);
"""

_FTPS = {"media_transport": "ftps", "media_enabled": 1, "media_snapshot_enabled": 1, "media_clip_enabled": 0}


def _run(eq_config: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """prefetchEvent, then an optional prefetch_result written to the cache, then the BA alarm."""
    source = PHP_CMD_FILE.read_text(encoding="utf-8").replace("<?php", "", 1)
    source = re.sub(r"^require_once .*core\.inc\.php';\s*$", "", source, count=1, flags=re.MULTILINE)
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.php"
        harness.write_text("<?php\n" + _EXECUTE_STUBS + source + _DRIVER, encoding="utf-8")
        scenario = Path(tmp) / "scenario.json"
        scenario.write_text(json.dumps({"eq_config": eq_config, "result": result}), encoding="utf-8")
        out = subprocess.run(["php", str(harness), str(scenario)], capture_output=True, text=True,
                             timeout=10, check=False)
    assert out.returncode == 0, f"PHP execution failed: {out.stderr}\n{out.stdout}"
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_prefetch_payload_has_no_burst_flag_and_ba_payload_no_run_id() -> None:
    """
    An event was found for the run.

    Expected result:
    - prefetchEvent carries no burst flag; ftps_upload has host and event id, no run_id
    """
    out = _run(_FTPS, {"found": True, "event_id": "evt-1", "rank": 1, "ts": int(time.time())})
    prefetch, alarm = out["sent"]
    # Assert: no burst flag
    assert "burst" not in prefetch
    # Assert: only host and event id
    assert set(alarm["ftps_upload"]) >= {"frigate_host", "event_id"}
    assert "run_id" not in alarm["ftps_upload"] and alarm["ftps_upload"]["event_id"] == "evt-1"


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ba_payload_without_event_has_no_upload_and_one_warning() -> None:
    """
    No Frigate event (only the placeholder of the run is cached).

    Expected result:
    - no ftps_upload in the BA payload; one PHP warning
    """
    out = _run(_FTPS, None)
    # Assert: nothing to upload
    assert "ftps_upload" not in out["sent"][1]
    # Assert: one warning
    assert len([e for e in out["logs"] if e["level"] == "warning"]) == 1


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ba_payload_after_ttl_has_no_upload() -> None:
    """
    The run is older than the cache TTL.

    Expected result:
    - no ftps_upload in the BA payload
    """
    out = _run(_FTPS, {"found": True, "event_id": "evt-1", "ts": int(time.time()) - 3600})
    # Assert: nothing to upload
    assert "ftps_upload" not in out["sent"][1]

