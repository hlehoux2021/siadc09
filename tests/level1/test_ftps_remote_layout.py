"""FTPS remote file naming and layout (epic 18, ticket 18.8).

Layout below the configured folder: `<account>/<YYYY-MM-DD>/<HHMMSS>_<zone>_<event_id>.<ext>`.
"""

import ftplib
import re
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import ftps_upload
from resources.siadc09d.ftps_upload import FtpsSettings, remote_location, upload_bytes

_WHEN = datetime(2026, 11, 10, 14, 5, 9)
_SAFE_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


def _settings(**overrides: object) -> FtpsSettings:
    """FTPS settings, complete and enabled unless overridden."""
    values: dict[str, object] = {
        "enabled": True, "host": "ftp.example", "user": "u", "password": "pw", "folder": "upload",
    }
    values.update(overrides)
    return FtpsSettings(**values)  # type: ignore[arg-type]


def test_name_is_deterministic_and_follows_the_layout() -> None:
    """
    Same input twice.

    Expected result:
    - identical (directory, name), shaped account/date and HHMMSS_zone_event.ext
    """
    first = remote_location("001234", "Salon", "1700.1-abc", _WHEN, "jpg")
    # Assert: deterministic
    assert first == remote_location("001234", "Salon", "1700.1-abc", _WHEN, "jpg")
    # Assert: documented layout
    assert first == ("001234/2026-11-10", "140509_Salon_1700.1-abc.jpg")


def test_two_zones_do_not_collide() -> None:
    """
    Two zones, same account, same second.

    Expected result:
    - distinct remote paths
    """
    a = remote_location("001234", "Salon", "e1", _WHEN, "jpg")
    b = remote_location("001234", "Garage", "e1", _WHEN, "jpg")
    # Assert: zone separates the names
    assert a != b


def test_two_times_do_not_collide() -> None:
    """
    Same zone, different seconds and different days.

    Expected result:
    - distinct remote paths
    """
    a = remote_location("001234", "Salon", "e1", _WHEN, "jpg")
    later = remote_location("001234", "Salon", "e1", datetime(2026, 11, 10, 14, 5, 10), "jpg")
    next_day = remote_location("001234", "Salon", "e1", datetime(2026, 11, 11, 14, 5, 9), "jpg")
    # Assert: time and date both separate the paths
    assert len({a, later, next_day}) == 3


def test_same_zone_same_second_is_separated_by_event_id() -> None:
    """
    Two Frigate events of one zone in the same second.

    Expected result:
    - distinct names
    """
    a = remote_location("001234", "Salon", "e1", _WHEN, "mp4")
    b = remote_location("001234", "Salon", "e2", _WHEN, "mp4")
    # Assert: the event id is the tie-break
    assert a != b


@pytest.mark.parametrize(
    ("account", "zone", "event_id"),
    [
        ("00/12 34", "Salon é/../x", "a b\\c:1"),
        ("..", "..", ".."),
        ("", None, ""),
        ("../../etc", "a\nb", "x*?"),
    ],
)
def test_every_part_is_filename_safe(account: str, zone: str | None, event_id: str) -> None:
    """
    Hostile or empty external values.

    Expected result:
    - only safe characters, no empty component, no '.' or '..' component
    """
    directory, name = remote_location(account, zone, event_id, _WHEN, "jpg")
    # Assert: safe characters only
    assert _SAFE_PATH.fullmatch(f"{directory}/{name}")
    # Assert: no traversal or empty component, exactly two levels
    parts = directory.split("/")
    assert len(parts) == 2 and all(p.strip(".") for p in parts)


def test_empty_or_dots_only_parts_get_a_placeholder() -> None:
    """
    Account, zone and event id that are empty or only dots.

    Expected result:
    - each part is replaced by its placeholder, so no component is empty or dots-only
    """
    directory, name = remote_location("..", None, "", _WHEN, "jpg")
    # Assert: placeholders in the account folder and in the file name
    assert (directory, name) == ("noaccount/2026-11-10", "140509_nozone_noevent.jpg")
    # Assert: dots-only zone and event id get theirs too
    assert remote_location("001234", "..", ".", _WHEN, "jpg")[1] == "140509_nozone_noevent.jpg"


def test_mkdir_failure_names_the_step() -> None:
    """
    The server refuses both the cwd and the mkd of a level (no write permission).

    Expected result:
    - FtpsUploadError whose message starts with "step mkdir:", nothing stored
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"

    def cwd(path: str) -> None:
        if path != "upload":
            raise ftplib.error_perm("550 no such directory")

    ftp.cwd.side_effect = cwd
    ftp.mkd.side_effect = ftplib.error_perm("550 permission denied")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        with pytest.raises(ftps_upload.FtpsUploadError) as err:
            upload_bytes(_settings(), "n.jpg", b"x", directory="001234/2026-11-10")
    # Assert: the failing step is named
    assert str(err.value).startswith("step mkdir:")
    # Assert: no transfer was started
    ftp.transfercmd.assert_not_called()


def test_snapshot_and_clip_share_prefix_and_differ_by_extension() -> None:
    """
    Both media of one alarm.

    Expected result:
    - same directory and base name, extensions jpg and mp4
    """
    jpg = remote_location("001234", "Salon", "e1", _WHEN, "jpg")
    mp4 = remote_location("001234", "Salon", "e1", _WHEN, "mp4")
    # Assert: same folder
    assert jpg[0] == mp4[0]
    # Assert: only the extension differs
    assert jpg[1][:-3] == mp4[1][:-3] and jpg[1].endswith(".jpg") and mp4[1].endswith(".mp4")


def test_missing_levels_are_created_in_order_then_stored() -> None:
    """
    Upload into a directory tree that does not exist yet.

    Expected result:
    - cwd folder, then per level cwd fails, mkd, cwd; then STOR with the bare name
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"
    state = {"made": set()}

    def cwd(path: str) -> None:
        if path not in ("upload", *state["made"]):
            raise ftplib.error_perm("550 no such directory")

    ftp.cwd.side_effect = cwd
    ftp.mkd.side_effect = lambda path: state["made"].add(path)
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "n.jpg", b"x", directory="001234/2026-11-10")
    # Assert: one mkd per missing level, top-down
    assert [c.args[0] for c in ftp.mkd.call_args_list] == ["001234", "2026-11-10"]
    # Assert: the file lands under the last level with the bare name
    assert ftp.transfercmd.call_args[0][0] == "STOR n.jpg"


def test_existing_levels_are_not_recreated() -> None:
    """
    Upload when the tree already exists (second alarm of the day).

    Expected result:
    - no mkd
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "n.jpg", b"x", directory="001234/2026-11-10")
    # Assert: cwd into each level, nothing created
    assert [c.args[0] for c in ftp.cwd.call_args_list] == ["upload", "001234", "2026-11-10"]
    ftp.mkd.assert_not_called()


def test_mkd_already_exists_race_is_tolerated() -> None:
    """
    Another upload creates the level between our cwd and mkd.

    Expected result:
    - mkd refusal ignored, the upload goes on
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"
    calls = {"n": 0}

    def cwd(path: str) -> None:
        calls["n"] += 1
        if path == "001234" and calls["n"] == 2:
            raise ftplib.error_perm("550 no such directory")

    ftp.cwd.side_effect = cwd
    ftp.mkd.side_effect = ftplib.error_perm("550 exists")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "n.jpg", b"x", directory="001234")
    # Assert: STOR still issued
    assert ftp.transfercmd.call_args[0][0] == "STOR n.jpg"


def test_no_directory_keeps_previous_behaviour() -> None:
    """
    Upload without a directory.

    Expected result:
    - only the configured folder is entered, no mkd
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), "n.jpg", b"x")
    # Assert: single cwd, no mkd
    assert [c.args[0] for c in ftp.cwd.call_args_list] == ["upload"]
    ftp.mkd.assert_not_called()
