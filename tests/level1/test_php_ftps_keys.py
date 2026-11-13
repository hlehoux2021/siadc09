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
              "--ftps-folder", "--ftps-cert-fingerprint", "--ftps-plain"]
_FTPS_KEYS = ["media_transport", "ftps_host", "ftps_port", "ftps_user",
              "ftps_password", "ftps_folder", "ftps_cert_fingerprint", "ftps_plain"]


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
def test_log_line_redacts_every_secret() -> None:
    """
    The daemon-start log line hides the AES key, the apikey and the FTPS password (18.6).

    Expected result:
    - no secret (even shell-quoted with a space and a quote) appears; the markers do
    """
    match = re.search(r"\$cmdLog = preg_replace\((.*?)\n\s*\);", _CLASS, re.S)
    assert match, "cmdLog redaction not found"
    script = (
        "$input = json_decode(stream_get_contents(STDIN), true);"
        "$envPrefix = $input['env']; $cmd = $input['cmd'];"
        f"$cmdLog = preg_replace({match.group(1)}\n);"
        "echo $cmdLog;"
    )
    command = {
        "env": "SIA_FTPS_PASSWORD='p w'\\''d!9' ",
        "cmd": "x.py --apikey KEY123 --encryption-key 'AAAA' --ftps-host 'h' --ftps-folder 'upload'",
    }
    out = subprocess.run(["php", "-r", script], input=json.dumps(command),
                         capture_output=True, text=True, check=True, timeout=_PHP_TIMEOUT_S)
    # Assert: no secret fragment survives
    for secret in ("AAAA", "d!9", "p w", "KEY123"):
        assert secret not in out.stdout
    # Assert: each marker is present and the next argument survives
    assert "SIA_FTPS_PASSWORD=[REDACTED] x.py --apikey [REDACTED]" in out.stdout
    assert "--encryption-key [REDACTED] --ftps-host 'h'" in out.stdout


def test_ftps_password_travels_by_environment_only() -> None:
    """
    18.6: the FTPS password is never an argument, neither at daemon start nor in the test call.

    Expected result:
    - deamon_start() sets SIA_FTPS_PASSWORD with putenv() (not in the command string), unsets it
      after the launch, and has no --ftps-password argument
    - the daemon CLI declares no --ftps-password and reads the environment
    - testConnection removes ftps_password from the --config JSON
    """
    start = _CLASS.split("function deamon_start")[1]
    # Assert: the password is put in the environment, not in the command string
    assert "putenv('SIA_FTPS_PASSWORD=' . $ftpsPassword);" in start
    assert "exec($cmd . ' >> '" in start
    # Assert: and removed from the environment right after the launch
    assert "putenv('SIA_FTPS_PASSWORD');" in start
    assert "--ftps-password" not in _CLASS
    cli = (_ROOT / "resources/siadc09d/siadc09d.py").read_text(encoding="utf-8")
    daemon = (_ROOT / "resources/siadc09d/daemon.py").read_text(encoding="utf-8")
    ajax = (_ROOT / "core/ajax/siaDC09.ajax.php").read_text(encoding="utf-8")
    # Assert: the daemon side takes it from the environment
    assert '"--ftps-password"' not in cli
    assert 'FTPS_PASSWORD_ENV: Final[str] = "SIA_FTPS_PASSWORD"' in daemon
    # Assert: the test-connection config JSON drops the password
    assert "unset($configData['encryption_key'], $configData['ftps_password']);" in ajax


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


def test_remote_folder_field_suggests_no_default() -> None:
    """
    The remote folder has no default, so the field must not show one.

    Expected result:
    - the ftps_folder input carries no placeholder (a grey "upload" looked like an applied default)
    """
    field = re.search(r'<input[^>]*data-l2key="ftps_folder"[^>]*>', _PAGE)
    # Assert: the field exists
    assert field
    # Assert: and has no placeholder
    assert "placeholder" not in field.group(0)


def test_plain_ftp_setting_is_handed_over_and_never_a_profile_field() -> None:
    """
    Ticket 18.14: the "FTP sans TLS" setting is per equipment, off by default.

    Expected result:
    - deamon_start() adds --ftps-plain only when ftps_plain is on, and skips the fingerprint then
    - testFtps passes ftps_plain in the --config JSON
    - the checkbox is a plain eqLogicAttr, unchecked by default, with the warning
    """
    start = _CLASS.split("function deamon_start")[1]
    ajax = (_ROOT / "core/ajax/siaDC09.ajax.php").read_text(encoding="utf-8")
    # Assert: the flag is sent conditionally and the fingerprint is not sent in plain mode
    assert "if ($ftpsPlain) {\n                $cmd .= ' --ftps-plain';" in start
    assert "$ftpsFingerprint !== '' && !$ftpsPlain" in start
    # Assert: the connection test gets the setting
    assert "$ftpsConfig['ftps_plain']" in ajax
    # Assert: unchecked by default (no "checked" attribute) and a warning is in the page
    box = re.search(r'<input[^>]*data-l2key="ftps_plain"[^>]*>', _PAGE)
    assert box and "checked" not in box.group(0).replace('type="checkbox"', "")
    assert "n'est pas chiffrée" in _PAGE


def test_ftps_enabled_is_derived_from_the_transport_in_one_place() -> None:
    """
    Story 18.4: ftps_enabled is no longer a stored choice; the transport decides.

    Expected result:
    - no ftps_enabled form field and no ftps_enabled configuration read in PHP
    - the daemon start and the Cmd payload both call siaDC09::isFtpsTransport()
    """
    # Assert: the page has no ftps_enabled field
    assert 'data-l2key="ftps_enabled"' not in _PAGE
    # Assert: PHP no longer reads the key
    assert "ftps_enabled" not in _CLASS.replace("--ftps-enabled", "")
    assert "FTPS_ENABLED_KEY" not in _CLASS + _CMD
    # Assert: both consumers use the one helper
    assert "isFtpsTransport(" in _CLASS.split("function deamon_start")[1]
    assert "siaDC09::isFtpsTransport(" in _CMD


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
@pytest.mark.parametrize("value,media,expected", [
    ("ftps", None, True), ("ftps", 1, True), ("ftps", "1", True), ("ftps", "", True),
    ("ftps", 0, False), ("ftps", "0", False),
    ("url", 1, False), ("", 1, False), (None, 1, False),
])
def test_is_ftps_transport_values(value: object, media: object, expected: bool) -> None:
    """
    isFtpsTransport() is true for 'ftps' with media on (or absent) only; an old equipment (no key) is the address way.

    Expected result:
    - ftps with media on or absent -> true; ftps with media off, url, empty and absent -> false
    """
    body = re.search(r"function isFtpsTransport\(mixed \$transport, mixed \$mediaEnabled = null\): bool \{(.*?)\n    \}", _CLASS, re.S)
    assert body, "isFtpsTransport not found"
    php = ("function f(mixed $transport, mixed $mediaEnabled = null): bool {" + body.group(1)
           + "} echo json_encode(f(" + json.dumps(value) + ", " + json.dumps(media) + "));")
    result = subprocess.run(["php", "-r", php], capture_output=True, text=True,
                            timeout=_PHP_TIMEOUT_S, check=True)
    # Assert: derived value
    assert json.loads(result.stdout) is expected
