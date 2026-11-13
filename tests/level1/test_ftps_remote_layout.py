"""FTPS remote file naming and layout (epic 18, ticket 18.13).

Flat layout at the root of the configured folder: `<account>_<zone 2 digits>_<epoch>_0001.<ext>`.
"""

import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from resources.siadc09d import ftps_upload
from resources.siadc09d.ftps_upload import FtpsSettings, remote_location, upload_bytes

_WHEN = datetime.fromtimestamp(1675938881, tz=timezone.utc)
_SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")


def _settings(**overrides: object) -> FtpsSettings:
    """FTPS settings, complete and enabled unless overridden."""
    values: dict[str, object] = {
        "enabled": True, "host": "ftp.example", "user": "u", "password": "pw", "folder": "upload",
    }
    values.update(overrides)
    return FtpsSettings(**values)  # type: ignore[arg-type]


def test_name_follows_the_receiver_layout() -> None:
    """
    Account 12345678, zone 1, epoch 1675938881.

    Expected result:
    - 12345678_01_1675938881_0001.jpg, a bare name (no directory)
    """
    name = remote_location("12345678", 1, _WHEN, "jpg")
    # Assert: documented layout
    assert name == "12345678_01_1675938881_0001.jpg"
    # Assert: no directory component
    assert "/" not in name


def test_clip_has_the_same_name_with_mp4() -> None:
    """
    Snapshot and clip of one alarm.

    Expected result:
    - names differ only by the extension
    """
    jpg = remote_location("12345678", 1, _WHEN, "jpg")
    mp4 = remote_location("12345678", 1, _WHEN, "mp4")
    # Assert: clip name
    assert mp4 == "12345678_01_1675938881_0001.mp4"
    # Assert: only the extension differs
    assert jpg[:-3] == mp4[:-3]


def test_three_digit_zone_is_not_truncated() -> None:
    """
    Zone 123.

    Expected result:
    - the zone part is 123
    """
    # Assert: no truncation to 2 digits
    assert remote_location("12345678", 123, _WHEN, "jpg") == "12345678_123_1675938881_0001.jpg"


def test_two_zones_same_second_do_not_collide() -> None:
    """
    Two zones, same account, same second.

    Expected result:
    - distinct names
    """
    # Assert: the zone number separates the names
    assert remote_location("12345678", 1, _WHEN, "jpg") != remote_location("12345678", 2, _WHEN, "jpg")


def test_same_zone_same_second_gives_the_same_name() -> None:
    """
    Two events of one zone in the same second.

    Expected result:
    - identical name (the later file overwrites; accepted by the user)
    """
    # Assert: same name
    assert remote_location("12345678", 1, _WHEN, "jpg") == remote_location("12345678", 1, _WHEN, "jpg")


@pytest.mark.parametrize("account", ["../x", "..", "", "00/12 34", "Comptée é", "a\nb"])
def test_hostile_account_gives_a_safe_name(account: str) -> None:
    """
    Hostile, empty or accented account.

    Expected result:
    - only safe characters, no separator, never an empty or dots-only account part
    """
    name = remote_location(account, 1, _WHEN, "jpg")
    # Assert: safe characters only (no slash, so no traversal)
    assert _SAFE_NAME.fullmatch(name)
    # Assert: the receiver layout is kept after the account part
    suffix = "_01_1675938881_0001.jpg"
    assert name.endswith(suffix)
    # Assert: the account part is never empty nor made only of dots
    assert name[: -len(suffix)].strip(".")


def test_empty_or_dots_account_gets_the_placeholder() -> None:
    """
    Empty and dots-only accounts.

    Expected result:
    - the noaccount placeholder
    """
    # Assert: empty account
    assert remote_location("", 1, _WHEN, "jpg") == "noaccount_01_1675938881_0001.jpg"
    # Assert: dots-only account
    assert remote_location("..", 1, _WHEN, "jpg") == "noaccount_01_1675938881_0001.jpg"


def test_absent_zone_number_gives_00() -> None:
    """
    zone_number is None.

    Expected result:
    - zone part 00, no crash
    """
    # Assert: placeholder zone
    assert remote_location("12345678", None, _WHEN, "jpg") == "12345678_00_1675938881_0001.jpg"


def test_upload_goes_to_the_configured_folder_without_subfolder() -> None:
    """
    Upload of a flat name.

    Expected result:
    - only the configured folder is entered, no mkd, STOR with the bare name
    """
    ftp = MagicMock()
    ftp.sock.getpeercert.return_value = b"x"
    name = remote_location("12345678", 1, _WHEN, "jpg")
    with patch.object(ftps_upload.ftplib, "FTP_TLS", return_value=ftp):
        upload_bytes(_settings(), name, b"x")
    # Assert: single cwd into the configured folder
    assert [c.args[0] for c in ftp.cwd.call_args_list] == ["upload"]
    # Assert: no subfolder created
    ftp.mkd.assert_not_called()
    # Assert: STOR with the flat name
    assert ftp.transfercmd.call_args[0][0] == f"STOR {name}"
