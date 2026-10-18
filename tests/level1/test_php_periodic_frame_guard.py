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


_GUARD_SEQUENCE_START = "// Guard 3c'"
_GUARD_SEQUENCE_END = "// Guard 4 "

# (equipment config, expected launchable) — each case flips one condition of Guards 3c'/3d/3e.
_DEAMON_INFO_CASES: list[tuple[dict, str]] = [
    ({}, "ok"),                                                         # legacy equipment: defaults
    ({"crc_format": "bin"}, "nok"),                                     # Guard 3c'
    ({"crc_format": "hex"}, "ok"),
    ({"supervision_format": "none"}, "nok"),                            # 3e: rp_enabled defaults to 0
    ({"supervision_format": "none", "rp_enabled": 0}, "nok"),
    ({"supervision_format": "none", "rp_enabled": 1, "rp_interval": 60,
      "supervision_interval": 0}, "ok"),                                # 3d skipped when 'none'
    ({"supervision_format": "sia-dcs", "supervision_interval": 0}, "nok"),   # Guard 3d
    ({"supervision_format": "null", "supervision_interval": 0}, "nok"),
    ({"supervision_format": "sia-dcs", "rp_enabled": 1, "rp_interval": 59}, "nok"),
    ({"supervision_format": "sia-dcs", "rp_enabled": 1, "rp_interval": 120}, "ok"),
    ({"supervision_format": "sia-dcs", "rp_enabled": 0, "rp_interval": 5}, "ok"),
    ({"supervision_format": "keepalive"}, "nok"),
]


def _php_deamon_info_guard_results(cases: list[tuple[dict, str]]) -> list[str]:
    """Run the Guard 3c'..3e source slice of deamon_info() for each stubbed config."""
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    body = _extract_method_body(source, "deamon_info")
    start, end = body.find(_GUARD_SEQUENCE_START), body.find(_GUARD_SEQUENCE_END)
    assert 0 <= start < end, "Guard 3c'..Guard 4 markers missing from deamon_info"
    guards = body[start:end]
    guard_body = _extract_method_body(source, "periodicFrameConfigError")
    consts = _class_constants(source, [
        "SENDER_CRC_FORMATS", "SUPERVISION_FORMATS", "SUPERVISION_FORMAT_DEFAULT",
        "RP_INTERVAL_DEFAULT_S", "RP_INTERVAL_MIN_S", "RP_INTERVAL_MAX_S",
    ])
    script = (
        _PHP_STUBS
        + " class StubEq { public function __construct(private array $c) {}"
        " public function getConfiguration($k, $d = null) {"
        " return array_key_exists($k, $this->c) ? $this->c[$k] : $d; } }"
        " class siaDC09 { " + consts
        + " public static function periodicFrameConfigError(string $format, bool $rpEnabled,"
        " int $rpInterval): ?string {" + guard_body + "}"
        " public static function run($eqLogic) { $return = ['launchable' => 'ok'];"
        + guards + " return $return; } }"
        " $cases = json_decode(stream_get_contents(STDIN), true);"
        " echo json_encode(array_map(fn($c) =>"
        " siaDC09::run(new StubEq($c))['launchable'], $cases));"
    )
    return json.loads(_run_php(script, json.dumps([c for c, _ in cases])))


@_requires_php
def test_deamon_info_guards_execute_as_specified() -> None:
    """
    deamon_info() Guards 3c', 3d and 3e give the expected verdict when actually executed.

    Source-text checks cannot catch an inverted condition, swapped arguments, a wrong
    default or a dropped early `return`; each case here flips exactly one of those.

    Expected result:
    - non-hex crc_format -> nok; hex -> ok
    - format 'none' + RP off (explicit or defaulted) -> nok
    - Guard 3d (interval <= 0) applies to sia-dcs / null, not to 'none'
    - RP interval below 60 -> nok only when RP is on
    - unknown format -> nok
    """
    results = _php_deamon_info_guard_results(_DEAMON_INFO_CASES)

    # Assert: one verdict per case, matching the specification
    assert results == [expected for _, expected in _DEAMON_INFO_CASES]


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


@_requires_php
def test_shortest_periodic_interval_staleness_basis() -> None:
    """
    Story 17.3 / ADR-08: staleness is 3 x the shortest active periodic interval.

    Expected result:
    - supervision 60 + RP 120 -> 60 (threshold 180 s)
    - 'none' ignores the supervision interval: none + RP 60 -> 60
    - RP off ignores the RP interval: sia-dcs 90 + RP 60 off -> 90
    - RP shorter than supervision wins: null 300 + RP 120 -> 120
    """
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    body = _extract_method_body(source, "shortestPeriodicInterval")
    assert body, "shortestPeriodicInterval missing"
    cases = [("sia-dcs", 60, True, 120), ("none", 999, True, 60), ("sia-dcs", 90, False, 60),
             ("null", 300, True, 120)]
    script = (
        "class siaDC09 { public static function shortestPeriodicInterval(string $format,"
        " int $supervisionInterval, bool $rpEnabled, int $rpInterval): int {" + body + "} }"
        " $cases = json_decode(stream_get_contents(STDIN), true);"
        " echo json_encode(array_map(fn($c) => siaDC09::shortestPeriodicInterval(...$c), $cases));"
    )
    result = json.loads(_run_php(script, json.dumps(cases)))
    # Assert: shortest active interval per case
    assert result == [60, 60, 90, 120]


@_requires_php
def test_shortest_periodic_interval_of_reads_equipment_config() -> None:
    """
    _shortestPeriodicIntervalOf() feeds shortestPeriodicInterval() the right config keys.

    The helper test above passes literal arguments; a swapped key, a wrong default or a
    dropped cast in the wrapper would go unnoticed without running it on a config.

    Expected result:
    - legacy equipment (no key) -> default format sia-dcs, supervision 60 -> 60
    - format none + RP 120 -> 120 (supervision interval ignored)
    - RP configured but disabled -> supervision interval 90
    - string values from the Jeedom config are cast ("45" -> 45)
    """
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    helper = _extract_method_body(source, "shortestPeriodicInterval")
    wrapper = _extract_method_body(source, "_shortestPeriodicIntervalOf")
    assert helper and wrapper, "shortest-interval methods missing"
    consts = _class_constants(source, ["SUPERVISION_FORMAT_DEFAULT", "RP_INTERVAL_DEFAULT_S"])
    configs = [
        {},
        {"supervision_format": "none", "supervision_interval": 999, "rp_enabled": 1, "rp_interval": 120},
        {"supervision_interval": 90, "rp_enabled": 0, "rp_interval": 60},
        {"supervision_interval": "45", "rp_enabled": "0"},
    ]
    script = (
        " class StubEq { public function __construct(private array $c) {}"
        " public function getConfiguration($k, $d = null) {"
        " return array_key_exists($k, $this->c) ? $this->c[$k] : $d; } }"
        " class siaDC09 { " + consts
        + " public static function shortestPeriodicInterval(string $format,"
        " int $supervisionInterval, bool $rpEnabled, int $rpInterval): int {" + helper + "}"
        " public static function _shortestPeriodicIntervalOf($eqLogic): int {" + wrapper + "} }"
        " $cases = json_decode(stream_get_contents(STDIN), true);"
        " echo json_encode(array_map(fn($c) => siaDC09::_shortestPeriodicIntervalOf(new StubEq($c)), $cases));"
    )
    result = json.loads(_run_php(script, json.dumps(configs)))
    # Assert: shortest active interval per equipment config
    assert result == [60, 120, 90, 45]


def test_freshness_and_widget_use_shortest_interval() -> None:
    """
    The cron5 freshness check and the widget tag both use the shortest-interval helper.

    Expected result:
    - _checkSupervisionFreshness() does not read supervision_interval itself
    - #supervision_interval# is the helper value (templates already multiply by 3)
    """
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    fresh = _extract_method_body(source, "_checkSupervisionFreshness")
    # Assert: freshness threshold derives from the helper
    assert "_shortestPeriodicIntervalOf($eqLogic) * 3" in fresh
    assert "'supervision_interval'" not in fresh
    # Assert: widget tag carries the shortest interval, not multiplied by 3 in PHP
    assert re.search(r"#supervision_interval#'\]\s*=\s*self::_shortestPeriodicIntervalOf\(\$this\);", source)
