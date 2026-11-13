"""Epic 18 / ticket 18.15: photo series naming, one-login upload, and the PHP payloads.

The PHP part runs the real core/class/siaDC09Cmd.class.php with the stubs of
test_frigate_prefetch_trigger.py (prefetchEvent then burglarAlarm on one equipment).
"""

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

from resources.siadc09d import ftps_upload
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


# ---- PHP: burst flag and run_id ------------------------------------------------------------

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
@pytest.mark.parametrize("config, burst", [
    (_FTPS, True),
    ({**_FTPS, "media_snapshot_enabled": 0, "media_clip_enabled": 1}, False),
    ({**_FTPS, "media_transport": "url"}, False),
])
def test_prefetch_payload_carries_the_burst_flag(config: dict[str, Any], burst: bool) -> None:
    """
    prefetchEvent payload per equipment setting.

    Expected result:
    - burst is true only with the ftps transport and the photo wanted
    """
    sent = _run(config, None)["sent"]
    # Assert: the flag follows transport + photo switch
    assert sent[0]["cmd"] == "prefetchEvent" and sent[0]["burst"] is burst


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ba_payload_carries_run_id_with_the_event() -> None:
    """
    An event was found for the run.

    Expected result:
    - ftps_upload has the event id and the run_id sent with prefetchEvent
    """
    out = _run(_FTPS, {"found": True, "event_id": "evt-1", "rank": 1, "ts": int(time.time())})
    prefetch, alarm = out["sent"]
    # Assert: same run, event kept
    assert alarm["ftps_upload"]["run_id"] == prefetch["run_id"]
    assert alarm["ftps_upload"]["event_id"] == "evt-1"


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ba_payload_without_event_still_carries_the_run() -> None:
    """
    No Frigate event (manual create refused): only the placeholder of the run is cached.

    Expected result:
    - ftps_upload is built with an empty event_id and the run_id; no PHP warning (the
      daemon logs the single warning, knowing the outcome)
    """
    out = _run(_FTPS, None)
    prefetch, alarm = out["sent"]
    # Assert: payload built without event
    assert alarm["ftps_upload"]["event_id"] == ""
    assert alarm["ftps_upload"]["run_id"] == prefetch["run_id"]
    # Assert: no PHP warning
    assert [e for e in out["logs"] if e["level"] == "warning"] == []


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_ba_payload_after_ttl_has_no_upload() -> None:
    """
    The run is older than the cache TTL.

    Expected result:
    - no ftps_upload in the BA payload
    """
    out = _run(_FTPS, {"ts": int(time.time()) - 3600})
    # Assert: nothing to upload
    assert "ftps_upload" not in out["sent"][1]
