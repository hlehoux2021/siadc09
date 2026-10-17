"""PHP side of the periodic-frame plumbing (Story 17.1, ADR-22).

- deamon_info() Guard 3e (siaDC09::periodicFrameConfigError()) is extracted from
  core/class/siaDC09.class.php and run with the php CLI against the same cases as
  CSRPreset.__post_init__, so the PHP guard and the daemon cannot drift apart. A
  drift would let Jeedom's auto-restart relaunch a daemon that exits at start.
- deamon_start() argument building and siaDC09::getCsrProfiles() are checked in
  source and, for getCsrProfiles(), executed against the real and broken files.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from resources.siadc09d.presets import CSRPreset
from tests.level1.test_php_eqlogic_stub import _extract_method_body

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PHP_CLASS_FILE = _PROJECT_ROOT / "core/class/siaDC09.class.php"
_PROFILES_FILE = _PROJECT_ROOT / "core/config/csr_presets.json"
_PHP_TIMEOUT_S = 10

_requires_php = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

# (supervision_format, rp_enabled, rp_interval) — the boundary cases of AC7.
_GUARD_CASES: list[tuple[str, bool, int]] = [
    ("sia-dcs", False, 60),     # today's default
    ("null", False, 60),
    ("none", True, 60),         # Ajax/Scutum profile
    ("none", False, 60),        # no periodic frame → refused
    ("sia-dcs", True, 59),      # below RP minimum → refused
    ("sia-dcs", True, 86400),   # inclusive maximum
    ("sia-dcs", True, 86401),   # above RP maximum → refused
    ("sia-dcs", False, 5),      # unused RP interval → accepted
    ("keepalive", False, 60),   # unknown format → refused
    ("", True, 60),             # empty format → refused
]

# Stubs for the Jeedom globals the extracted methods call.
_PHP_STUBS = (
    "function __($s, $f = '') { return $s; }"
    " class log { public static array $lines = [];"
    " public static function add($c, $l, $m) { self::$lines[] = [$l, $m]; } }"
)


def _python_accepts(fmt: str, rp_enabled: bool, rp_interval: int) -> bool:
    """True when CSRPreset accepts the periodic-frame combination."""
    try:
        CSRPreset(
            csr_provider="test", schema_version=1, host="127.0.0.1", port=1,
            account_number="001234", transport="UDP", crc_format="hex",
            encryption_enabled=False, connect_timeout_s=5.0, receive_timeout_s=10.0,
            supervision_interval_s=60.0, supervision_format=fmt,  # type: ignore[arg-type]
            rp_enabled=rp_enabled, rp_interval_s=float(rp_interval),
        )
    except ValueError:
        return False
    return True


def _class_constants(source: str, names: list[str]) -> str:
    """Return the PHP `const NAME = …;` declarations for names, verbatim."""
    decls = []
    for name in names:
        match = re.search(rf"const {name}\s*=\s*[^;]*;", source)
        assert match, f"const {name} missing from siaDC09.class.php"
        decls.append(match.group(0))
    return " ".join(decls)


def _run_php(script: str, stdin: str = "") -> str:
    """Run a php -r script and return stdout."""
    out = subprocess.run(
        ["php", "-r", script], input=stdin, capture_output=True, text=True,
        check=True, timeout=_PHP_TIMEOUT_S,
    )
    return out.stdout


def _php_guard_errors(cases: list[tuple[str, bool, int]]) -> list[str | None]:
    """Run the extracted periodicFrameConfigError() over cases with the php CLI."""
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    body = _extract_method_body(source, "periodicFrameConfigError")
    assert body, "periodicFrameConfigError missing"
    consts = _class_constants(source, ["SUPERVISION_FORMATS", "RP_INTERVAL_MIN_S", "RP_INTERVAL_MAX_S"])
    script = (
        _PHP_STUBS
        + " class siaDC09 { " + consts
        + " public static function periodicFrameConfigError(string $format, bool $rpEnabled,"
        " int $rpInterval): ?string {" + body + "} }"
        " $cases = json_decode(stream_get_contents(STDIN), true);"
        " echo json_encode(array_map(fn($c) => siaDC09::periodicFrameConfigError($c[0], $c[1], $c[2]),"
        " $cases));"
    )
    return json.loads(_run_php(script, json.dumps(cases)))


def _php_get_profiles(path: Path) -> tuple[dict | list, list]:
    """Run the extracted getCsrProfiles() against path; return (profiles, log lines)."""
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    body = _extract_method_body(source, "getCsrProfiles")
    assert body, "getCsrProfiles missing"
    consts = _class_constants(source, ["CSR_PROFILES_SCHEMA_VERSION"])
    script = (
        _PHP_STUBS
        + " class siaDC09 { " + consts
        + " const CSR_PROFILES_FILE = " + json.dumps(str(path)) + ";"
        " public static function getCsrProfiles(): array {" + body + "} }"
        " echo json_encode([siaDC09::getCsrProfiles(), log::$lines]);"
    )
    profiles, lines = json.loads(_run_php(script))
    return profiles, lines


@_requires_php
def test_php_guard_3e_matches_csr_preset() -> None:
    """
    deamon_info() Guard 3e refuses exactly what CSRPreset refuses (AC7).

    Expected result:
    - for every case, "PHP returns no error" == "CSRPreset accepts"
    - the refused cases carry a French message pointing at the wizard's advanced options
    """
    errors = _php_guard_errors(_GUARD_CASES)

    # Assert: PHP verdict equals the daemon verdict for every case
    assert [e is None for e in errors] == [_python_accepts(*c) for c in _GUARD_CASES]
    # Assert: every refusal points at "étape 1 de l'assistant (Options avancées)"
    assert all("Options avancées" in e for e in errors if e is not None)


def test_deamon_info_wires_guards() -> None:
    """
    deamon_info() calls Guard 3e, makes Guard 3d conditional, and refuses a non-hex CRC.

    Expected result:
    - self::periodicFrameConfigError( called with the three equipment config keys
    - Guard 3d (supervision_interval > 0) skipped when supervision_format is 'none'
    - crc_format checked against SENDER_CRC_FORMATS (AC8, task 5.3)
    """
    body = _extract_method_body(_PHP_CLASS_FILE.read_text(encoding="utf-8"), "deamon_info")

    # Assert: Guard 3e called from deamon_info
    assert "self::periodicFrameConfigError(" in body
    # Assert: Guard 3d only applies when a supervision frame is sent
    assert re.search(r"\$supervisionFormat !== 'none'\s*&&\s*\(int\) \$eqLogic->getConfiguration\('supervision_interval'", body)
    # Assert: stored crc_format other than hex refused before launch
    assert "self::SENDER_CRC_FORMATS" in body


def test_deamon_start_passes_periodic_frame_args() -> None:
    """
    deamon_start() always passes --supervision-format and passes RP args only when on (AC5).

    Expected result:
    - --supervision-format passed through escapeshellarg, outside any condition
    - --rp-enabled and --rp-interval inside the `if (rp_enabled)` block
    - no profile name / csr_profile key on the command line (ADR-22)
    """
    body = _extract_method_body(_PHP_CLASS_FILE.read_text(encoding="utf-8"), "deamon_start")

    # Assert: format always passed, shell-escaped
    assert re.search(
        r"\$cmd \.= ' --supervision-format ' \. escapeshellarg\(\s*"
        r"\(string\) \$eqLogic->getConfiguration\('supervision_format'",
        body,
    )
    # Assert: RP args gated on rp_enabled, same pattern as --encryption-enabled
    assert re.search(
        r"if \(\(bool\) \$eqLogic->getConfiguration\('rp_enabled', 0\)\) \{\s*"
        r"\$cmd \.= ' --rp-enabled';\s*\$cmd \.= ' --rp-interval ' \. \(int\) "
        r"\$eqLogic->getConfiguration\('rp_interval'",
        body,
    )
    # Assert: daemon never receives a profile name
    assert "csr_profile" not in body


@_requires_php
def test_get_csr_profiles_reads_real_file() -> None:
    """
    getCsrProfiles() returns the `profiles` object of core/config/csr_presets.json (AC2).

    Expected result:
    - ajax and scutum returned, nothing logged
    """
    profiles, lines = _php_get_profiles(_PROFILES_FILE)

    # Assert: both profiles returned
    assert set(profiles) == {"ajax", "scutum"}
    # Assert: no error logged
    assert lines == []


@_requires_php
@pytest.mark.parametrize("content", [
    None,                                           # missing file
    "{not json",                                    # unparsable
    '{"schema_version": 2, "profiles": {}}',        # unsupported schema
    '{"schema_version": "1", "profiles": {}}',      # schema_version not the int 1
    '{"schema_version": 1}',                        # no profiles object
])
def test_get_csr_profiles_failure_returns_empty(tmp_path: Path, content: str | None) -> None:
    """
    getCsrProfiles() never throws: any failure logs at `error` and returns [] (AC2).

    Expected result:
    - [] returned
    - exactly one `error` log line
    """
    path = tmp_path / "csr_presets.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    profiles, lines = _php_get_profiles(path)

    # Assert: empty result instead of an exception
    assert profiles == []
    # Assert: one error-level log line
    assert [level for level, _ in lines] == ["error"]
