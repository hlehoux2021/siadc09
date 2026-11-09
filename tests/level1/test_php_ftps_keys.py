"""PHP side of the FTPS keys (epic 18, ticket 18.2): daemon args, redaction, payload, field.

The redaction is exercised with the php CLI on the exact preg_replace of deamon_start(); the
rest is checked in source, like the encryption-key guard.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_CLASS = (_ROOT / "core/class/siaDC09.class.php").read_text(encoding="utf-8")
_CMD = (_ROOT / "core/class/siaDC09Cmd.class.php").read_text(encoding="utf-8")
_PAGE = (_ROOT / "desktop/php/siaDC09.php").read_text(encoding="utf-8")
_PHP_TIMEOUT_S = 10

_FTPS_ARGS = ["--ftps-enabled", "--ftps-host", "--ftps-port", "--ftps-user",
              "--ftps-password", "--ftps-folder", "--ftps-cert-fingerprint"]
_FTPS_KEYS = ["media_transport", "ftps_enabled", "ftps_host", "ftps_port", "ftps_user",
              "ftps_password", "ftps_folder", "ftps_cert_fingerprint"]


def test_deamon_start_passes_every_ftps_arg() -> None:
    """
    deamon_start() hands every FTPS key to the daemon.

    Expected result:
    - each --ftps-* option appears in the command built by deamon_start()
    """
    for arg in _FTPS_ARGS:
        # Assert: the option is part of the command line
        assert f"' {arg}" in _CLASS, f"{arg} missing from deamon_start()"


def test_daemon_cli_declares_every_ftps_arg() -> None:
    """
    The daemon accepts every option PHP sends.

    Expected result:
    - each --ftps-* option is declared in siadc09d.py
    """
    cli = (_ROOT / "resources/siadc09d/siadc09d.py").read_text(encoding="utf-8")
    for arg in _FTPS_ARGS:
        # Assert: the option is declared
        assert f'"{arg}"' in cli


def test_password_is_a_password_input_and_every_key_has_a_field() -> None:
    """
    The hand-entry form exposes every key and hides the password.

    Expected result:
    - one form field per key; ftps_password is an input of type password
    """
    for key in _FTPS_KEYS:
        # Assert: the key has a field
        assert f'data-l2key="{key}"' in _PAGE
    # Assert: the password field is masked
    assert re.search(r'type="password"[^>]*data-l2key="ftps_password"', _PAGE)


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_log_line_redacts_both_secrets() -> None:
    """
    The daemon-start log line hides the AES key and the FTPS password.

    Expected result:
    - neither secret (even shell-quoted with a space and a quote) appears; the markers do
    """
    match = re.search(r"\$cmdLog = preg_replace\((.*?)\n\s*\);", _CLASS, re.S)
    assert match, "cmdLog redaction not found"
    script = (
        "$cmd = json_decode(stream_get_contents(STDIN), true);"
        f"$cmdLog = preg_replace({match.group(1)}\n);"
        "echo $cmdLog;"
    )
    command = ("x.py --encryption-key 'AAAA' --ftps-host 'h' --ftps-password 'p w'\\''d!9' "
               "--ftps-folder 'upload'")
    out = subprocess.run(["php", "-r", script], input=json.dumps(command),
                         capture_output=True, text=True, check=True, timeout=_PHP_TIMEOUT_S)
    # Assert: no secret fragment survives
    assert "AAAA" not in out.stdout and "d!9" not in out.stdout and "p w" not in out.stdout
    # Assert: the FTPS password is replaced as a whole and the next argument survives
    assert "--ftps-password [REDACTED] --ftps-folder 'upload'" in out.stdout
    # Assert: the AES key is still redacted
    assert "--encryption-key [REDACTED]" in out.stdout


def test_burglar_payload_carries_ftps_upload_and_drops_media() -> None:
    """
    A BA alarm with the ftps transport sends ftps_upload and no media tag.

    Expected result:
    - the payload code adds ftps_upload and clears media before attaching it
    """
    # Assert: the payload key exists
    assert "'ftps_upload'" in _CMD
    # Assert: media is dropped only for a BA alarm with the ftps transport
    assert "$logicalId === 'burglarAlarm' && $this->_ftpsTransportActive()" in _CMD
    # Assert: media is cleared before it is attached to the payload
    ftps_block = _CMD.index("$this->_ftpsTransportActive()) {\n                    $media = [];")
    assert ftps_block < _CMD.index("$payload['media'] = $media;")


def test_ftps_upload_follows_the_media_switches() -> None:
    """
    E18-R2: the FTPS upload obeys the same switches as the URL path.

    Expected result:
    - ftps_upload is only resolved when the media master switch and the snapshot switch are on
    """
    # Assert: the wanted flag combines the master and snapshot switches
    assert ("$snapshotWanted = $mediaOn && "
            "$this->_mediaSetting(siaDC09::MEDIA_SNAPSHOT_ENABLED_KEY);") in _CMD
    # Assert: the upload is resolved only for a BA alarm with that flag
    # (ticket 18.5: the clip switch also triggers the resolution, and both flags are sent)
    assert "($logicalId === 'burglarAlarm' && ($snapshotWanted || $clipWanted))" in _CMD
    assert "$ftpsUpload['snapshot'] = (bool) $snapshotWanted;" in _CMD
    assert "$ftpsUpload['clip'] = (bool) $clipWanted;" in _CMD
