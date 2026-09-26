"""Level 1 behavioral tests for Story 13.1 — disarm/alarmReset, BC/OP addressed by user number.

Executes the REAL core/class/siaDC09Cmd.class.php via `php`, with the Jeedom framework
replaced by minimal stubs (cmd base class, log::add, siaDC09::sendToDaemon, __(), and an
eqLogic whose getCache()/setCache()/getConfiguration() are backed by plain arrays). The
regex-based tests in test_php_eqlogic_stub.py check the shape of the source; these check
what actually reaches the daemon — AC1-AC4 are counts and order, which only running the
code can verify.

Each scenario is a sequence of execute() calls on commands of the same equipment, so the
sia_open_alarms table written by burglarAlarm/fireAlarm/panicAlarm is the one disarm/
alarmReset read — the same shared-eqLogic-cache path as on a real Jeedom.

Rescope (2026-09-25): DC-03 addresses BC/OP by user number, never by zone
(`sprint-change-proposal-2026-09-25.md`, ADR-18). `burglaryCancel`'s per-zone fan-out
(never shipped) is replaced by two commands: `disarm` (wired on `release`) and
`alarmReset` (wired on `raz`).

Reference: _bmad-output/implementation-artifacts/13-1-burglary-restore-cancel-events.md
Reference: tests/level1/test_frigate_snapshot_resolution.py (precedent for running PHP)
"""
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PHP_CMD_FILE = _PROJECT_ROOT / "core/class/siaDC09Cmd.class.php"

# Matches siaDC09Cmd::OPEN_ALARMS_TTL (86400s) with margin — an entry this old is expired.
EXPIRED_AGE_S = 2 * 86400

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

_PHP_STUBS = r"""
class log {
    public static array $entries = [];
    public static function add($plugin, $level, $message): void {
        self::$entries[] = ['level' => $level, 'message' => $message];
    }
}

function __($text, $file = '') {
    return $text;
}

class FakeEqLogic {
    public array $cache;
    private array $config;
    public function __construct(array $cache, array $config) {
        $this->cache = $cache;
        $this->config = $config;
    }
    public function getCache($key, $default = null) {
        return $this->cache[$key] ?? $default;
    }
    public function setCache($key, $value): void {
        $this->cache[$key] = $value;
    }
    public function getConfiguration($key, $default = null) {
        return $this->config[$key] ?? $default;
    }
}

class cmd {
    public string $logicalId = '';
    public ?FakeEqLogic $eqLogic = null;
    public function getLogicalId() {
        return $this->logicalId;
    }
    public function getEqLogic() {
        return $this->eqLogic;
    }
}

class siaDC09 {
    public static array $sent = [];
    public static function sendToDaemon(array $params): void {
        self::$sent[] = $params;
    }
}
"""

_PHP_DRIVER = r"""
$scenario = json_decode(file_get_contents($argv[1]), true);
$config = ['sia_zone_mappings' => $scenario['zone_mappings']];
if (array_key_exists('user_number', $scenario) && $scenario['user_number'] !== null) {
    $config['sia_user_number'] = $scenario['user_number'];
}
$eqLogic = new FakeEqLogic($scenario['cache'], $config);
foreach ($scenario['steps'] as $step) {
    $cmd = new siaDC09Cmd();
    $cmd->logicalId = $step['logical_id'];
    $cmd->eqLogic = $eqLogic;
    $options = array_key_exists('title', $step) ? ['title' => $step['title']] : [];
    $cmd->execute($options);
}
echo json_encode([
    'sent'  => siaDC09::$sent,
    'logs'  => log::$entries,
    'cache' => $eqLogic->cache,
]);
"""


def _class_source_without_bootstrap() -> str:
    """The siaDC09Cmd class exactly as shipped, minus the opening tag and Jeedom bootstrap."""
    source = PHP_CMD_FILE.read_text(encoding="utf-8")
    source = source.replace("<?php", "", 1)
    return re.sub(r"^require_once .*core\.inc\.php';\s*$", "", source, count=1, flags=re.MULTILINE)


def _run(
    steps: list[dict[str, Any]],
    cache: dict[str, Any] | None = None,
    user_number: int | None = None,
) -> dict[str, Any]:
    """Run a sequence of execute() calls against one equipment and return what they produced.

    Args:
        steps: [{"logical_id": "disarm", "title": ...}, ...] — "title" omitted means
            execute() receives no options at all, matching how the alarm plugin calls
            `release`/`raz` (no #zone# tag on either hook).
        cache: initial eqLogic cache (e.g. a pre-seeded sia_open_alarms table).
        user_number: configured `sia_user_number`, or None to leave it unset (default 1).

    Returns:
        {"sent": [payloads passed to sendToDaemon()], "logs": [{"level", "message"}],
         "cache": final eqLogic cache}
    """
    scenario = {
        "steps": steps,
        "cache": cache or {},
        "zone_mappings": [{"zone_name": "Salon", "zone_number": 3}],
        "user_number": user_number,
    }
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.php"
        harness.write_text(
            "<?php\n" + _PHP_STUBS + _class_source_without_bootstrap() + _PHP_DRIVER,
            encoding="utf-8",
        )
        scenario_file = Path(tmp) / "scenario.json"
        scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            ["php", str(harness), str(scenario_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert result.returncode == 0, f"PHP execution failed: {result.stderr}\n{result.stdout}"
    return json.loads(result.stdout)


def _open_alarm_seed(sia_code: str, zone: str | None, zone_number: int | None, ts: int | None = None) -> dict[str, Any]:
    return {
        "sia_code": sia_code,
        "zone": zone,
        "zone_number": zone_number,
        "ts": ts if ts is not None else int(time.time()),
    }


def _open_alarms(cache: dict[str, Any] | list[Any]) -> dict[str, Any]:
    # PHP json_encode() renders an empty array as [] rather than {}, at both levels
    if not isinstance(cache, dict):
        return {}
    table = cache.get("sia_open_alarms", {})
    if isinstance(table, str):
        table = json.loads(table)
    return table if isinstance(table, dict) else {}


def _logs_at(logs: list[dict[str, str]], level: str) -> list[str]:
    return [entry["message"] for entry in logs if entry["level"] == level]


def _cancel_frames(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the disarm/alarmReset frames — burglarAlarm/fireAlarm/panicAlarm setup steps
    also call sendToDaemon() with a different payload shape (no 'sia_code' key)."""
    return [p for p in sent if p.get("cmd") in ("disarm", "alarmReset")]


# ── AC1/AC2 — disarm (wired on `release`) ────────────────────────────────────────


def test_disarm_with_open_ba_emits_bc_then_op_in_order_and_purges_table() -> None:
    """
    AC1: a burglary alarm is still open when the user disarms — disarm must emit exactly
    two frames, BC then OP, in that order, both carrying the configured user number, and
    purge sia_open_alarms afterwards.

    Expected result:
    - exactly 2 frames are sent, in order: cmd=disarm/sia_code=BC, then cmd=disarm/sia_code=OP
    - both carry user_number == 1 (default)
    - sia_open_alarms is empty afterwards
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "disarm"},
    ])
    sent = _cancel_frames(out["sent"])
    # Assert: exactly two frames, in the mandated order BC then OP
    assert [(p["cmd"], p["sia_code"]) for p in sent] == [("disarm", "BC"), ("disarm", "OP")], sent
    # Assert: both frames carry the configured (default) user number
    assert [p["user_number"] for p in sent] == [1, 1]
    # Assert: the table is purged once disarm has reported
    assert _open_alarms(out["cache"]) == {}


def test_disarm_with_no_open_ba_emits_op() -> None:
    """
    Story 13-4 AC3: disarming with no open burglary alarm memorized (normal disarm,
    outside any alarm context) must send a single OP — filling the `else` branch that
    story 13-1 left silent.

    Expected result:
    - exactly one frame is sent: cmd=disarm/sia_code=OP
    """
    out = _run([{"logical_id": "disarm"}])
    frames = _cancel_frames(out["sent"])
    # Assert: a normal disarm now reports OP, never BC (no alarm was open)
    assert [p["sia_code"] for p in frames] == ["OP"]


def test_disarm_uses_the_configured_sia_user_number() -> None:
    """
    AC5: the address field is the configured `sia_user_number` (wizard step 3), not a
    hardcoded value — a non-default configuration (7) must reach both frames.

    Expected result:
    - both BC and OP carry user_number == 7
    """
    out = _run(
        [
            {"logical_id": "burglarAlarm", "title": "Salon"},
            {"logical_id": "disarm"},
        ],
        user_number=7,
    )
    numbers = [p["user_number"] for p in _cancel_frames(out["sent"])]
    # Assert: the configured user number reaches every frame
    assert numbers == [7, 7]


def test_disarm_defaults_user_number_to_one_when_unconfigured() -> None:
    """
    AC5: an installation that never configured `sia_user_number` (or left the wizard's
    default) must still address the CSR — default is 1, never empty (AC5's "never empty"
    rule applies even to a missing config key).

    Expected result:
    - both BC and OP carry user_number == 1
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "disarm"},
    ], user_number=None)
    numbers = [p["user_number"] for p in _cancel_frames(out["sent"])]
    # Assert: default user number is 1, never null/empty
    assert numbers == [1, 1]


@pytest.mark.parametrize("bad_user_number", [0, -1, 1000, 9999])
def test_disarm_falls_back_to_one_when_sia_user_number_out_of_range(bad_user_number: int) -> None:
    """
    Code review finding (2026-09-26): the wizard field has min="1" max="999" (DC-03 Annex B:
    3 zero-padded digits) but nothing enforced that range server-side — a saved out-of-range
    value would reach f"{n:03d}" unclamped on the daemon side, breaking the fixed-width
    address-field contract (a negative number, or 4+ digits).

    Expected result:
    - an out-of-range configured sia_user_number falls back to the same default (1) as an
      unconfigured one, never reaching the daemon payload as-is
    """
    out = _run(
        [
            {"logical_id": "burglarAlarm", "title": "Salon"},
            {"logical_id": "disarm"},
        ],
        user_number=bad_user_number,
    )
    numbers = [p["user_number"] for p in _cancel_frames(out["sent"])]
    # Assert: out-of-range value clamped to the default, never sent as-is
    assert numbers == [1, 1]


# ── Story 13-4 — arm (wired on `activationImmediateOk`) ──────────────────────────


def test_arm_emits_cl_unconditionally() -> None:
    """
    Story 13-4 AC1, AC6: arming always sends exactly one CL — never conditional on
    sia_open_alarms, unlike disarm/alarmReset.

    Expected result:
    - exactly one frame is sent, with cmd=arm and user_number set
    """
    out = _run([{"logical_id": "arm"}])
    arm_frames = [p for p in out["sent"] if p.get("cmd") == "arm"]
    # Assert: exactly one arm frame, unconditionally
    assert len(arm_frames) == 1
    # Assert: addressed by the (default) configured user number
    assert arm_frames[0]["user_number"] == 1
    # Assert: arm never sends its own sia_code — the daemon derives CL from the cmd name
    assert "sia_code" not in arm_frames[0]


def test_arm_uses_the_configured_sia_user_number() -> None:
    """
    Story 13-4 AC1: the address field is the configured `sia_user_number` (wizard step 3,
    shared with disarm/alarmReset), not a hardcoded value.

    Expected result:
    - the arm frame carries user_number == 7
    """
    out = _run([{"logical_id": "arm"}], user_number=7)
    arm_frames = [p for p in out["sent"] if p.get("cmd") == "arm"]
    # Assert: the configured user number reaches the frame
    assert arm_frames[0]["user_number"] == 7


def test_arm_emits_cl_even_with_open_ba() -> None:
    """
    Story 13-4 AC6 (review 13-4): an open burglary alarm must not change what arm does —
    arm never reads or touches sia_open_alarms, and never sends BC/OP.

    Expected result:
    - exactly one arm frame is sent
    - no disarm/alarmReset (BC/OP) frame is sent
    - the open BA entry is still in sia_open_alarms afterwards
    """
    cache = {"sia_open_alarms": {"BA|3": _open_alarm_seed("BA", "Salon", 3)}}
    out = _run([{"logical_id": "arm"}], cache=cache)
    arm_frames = [p for p in out["sent"] if p.get("cmd") == "arm"]
    # Assert: exactly one arm frame, open BA or not
    assert len(arm_frames) == 1
    # Assert: arm never emits a cancel/disarm frame
    assert _cancel_frames(out["sent"]) == []
    # Assert: the open-alarm table is left untouched
    assert set(_open_alarms(out["cache"])) == {"BA|3"}


def test_disarm_with_only_fire_or_panic_open_emits_op_not_bc() -> None:
    """
    AC2 (13-1) / AC3 (13-4): BC closes a burglary alarm only — an open fire or panic alarm
    alone must not make disarm emit a BC (FA/PA are kept for the future story 13-3, not
    closed here). No BA being open means this is, from disarm's perspective, a normal
    disarm: it sends OP alone (13-4).

    Expected result:
    - exactly one frame is sent: cmd=disarm/sia_code=OP (never BC)
    - the table still holds the FA/PA entries afterwards (not purged, since no BA fired)
    """
    out = _run([
        {"logical_id": "fireAlarm", "title": "Garage"},
        {"logical_id": "panicAlarm"},
        {"logical_id": "disarm"},
    ])
    # Assert: OP alone for a fire/panic-only table — never BC
    assert [p["sia_code"] for p in _cancel_frames(out["sent"])] == ["OP"]
    # Assert: FA/PA entries are untouched — only a BC purges the table
    assert len(_open_alarms(out["cache"])) == 2


def test_disarm_with_ba_and_fire_open_purges_only_ba() -> None:
    """
    AC1/AC2: a fire alarm concurrent with the burglary alarm is unrelated to this disarm —
    `_purgeOpenAlarms('BA')` must remove only the BA entry, leaving the FA entry for the
    future story 13-3. A whole-table purge here would silently lose it (regression guard
    for the design's own stated intent: "FA/PA entries stay recorded for story 13-3").

    Expected result:
    - BC then OP are sent (the open BA still triggers disarm's normal path)
    - the FA entry survives the purge; only the BA entry is gone
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "fireAlarm", "title": "Garage"},
        {"logical_id": "disarm"},
    ])
    # Assert: BC then OP still fire — the open BA is real
    codes = [p["sia_code"] for p in _cancel_frames(out["sent"])]
    assert codes == ["BC", "OP"]
    # Assert: the FA entry survives; only the BA entry was purged
    remaining = _open_alarms(out["cache"])
    assert len(remaining) == 1
    assert next(iter(remaining.values()))["sia_code"] == "FA"


# ── AC3/AC4 — alarmReset (wired on `raz`) ────────────────────────────────────────


def test_alarm_reset_with_open_ba_emits_bc_alone_and_purges_table() -> None:
    """
    AC3: a mode-change reset while the alarm is sounding runs `raz` alone, without
    `release` — the system stays armed. alarmReset must still close the open burglary
    alarm with a single BC (no OP: the system was never disarmed).

    Expected result:
    - exactly 1 frame is sent: cmd=alarmReset/sia_code=BC, carrying the user number
    - sia_open_alarms is empty afterwards
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "alarmReset"},
    ])
    sent = _cancel_frames(out["sent"])
    # Assert: exactly one BC, never an OP (the system was not disarmed)
    assert [(p["cmd"], p["sia_code"]) for p in sent] == [("alarmReset", "BC")], sent
    assert sent[0]["user_number"] == 1
    # Assert: the table is purged
    assert _open_alarms(out["cache"]) == {}


def test_alarm_reset_with_no_open_ba_emits_nothing_and_logs_debug() -> None:
    """
    AC4: the normal Désactiver-while-sounding path runs `release` before `raz`
    (alarm.class.php:703-712, ADR-18) — by the time alarmReset runs, disarm has already
    purged the table. alarmReset must find it empty and stay silent.

    Expected result:
    - no frame is sent
    - a debug log line explains why
    """
    out = _run([{"logical_id": "alarmReset"}])
    # Assert: nothing to close, so nothing is sent
    assert _cancel_frames(out["sent"]) == []
    # Assert: the silence is explained at debug level
    assert _logs_at(out["logs"], "debug"), "alarmReset with no open BA must log at debug"


# ── AC4 — release-then-raz sequence: exactly BC, OP, never a second BC ───────────


def test_release_then_raz_sequence_emits_exactly_bc_op_never_a_second_bc() -> None:
    """
    AC4: the alarm plugin's normal Désactiver-while-sounding path calls `release` then
    `raz` — this pins our dependency on that ordering (ADR-18): disarm purges the table
    first, so alarmReset's later call must never re-close the same alarm.

    Expected result:
    - the full sequence produces exactly BC, then OP, and nothing more — no second BC
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "disarm"},     # release
        {"logical_id": "alarmReset"},  # raz, right after — table already empty
    ])
    codes = [p["sia_code"] for p in _cancel_frames(out["sent"])]
    # Assert: exactly BC then OP, never a second BC from the trailing alarmReset
    assert codes == ["BC", "OP"], codes


# ── Table oracle mechanics — TTL and JSON-string cache tolerance kept from the
#    prior design (sprint-change-proposal-2026-09-25.md §4.5) ────────────────────


def test_expired_ba_entry_is_not_treated_as_open() -> None:
    """
    AC5 (via Task 3, unchanged): OPEN_ALARMS_TTL expires an entry whose reset never
    arrived. An expired BA (two days old) must not count as "open" for disarm — story
    13-4: a disarm with nothing open sends OP alone, never BC.

    Expected result:
    - disarm emits OP alone for an expired-only table (never BC)
    """
    stale_ts = int(time.time()) - EXPIRED_AGE_S
    cache = {"sia_open_alarms": {"BA|3": _open_alarm_seed("BA", "Salon", 3, ts=stale_ts)}}
    out = _run([{"logical_id": "disarm"}], cache=cache)
    # Assert: an expired entry is not "open" — disarm reports a normal disarm (OP), not BC
    assert [p["sia_code"] for p in _cancel_frames(out["sent"])] == ["OP"]


def test_table_read_as_json_string_still_detects_open_ba() -> None:
    """
    Task 3 (unchanged): the eqLogic cache may hand back the table JSON-encoded (Redis
    round trip) — disarm's "is a BA open?" oracle must tolerate that, same as the
    fan-out design it replaces did.

    Expected result:
    - a JSON-string-encoded table with one open BA still yields BC then OP
    """
    table = {"BA|3": _open_alarm_seed("BA", "Salon", 3)}
    out = _run(
        [{"logical_id": "disarm"}],
        cache={"sia_open_alarms": json.dumps(table)},
    )
    codes = [p["sia_code"] for p in _cancel_frames(out["sent"])]
    # Assert: the string-encoded table is decoded and detected as an open BA
    assert codes == ["BC", "OP"]


def test_bc_and_op_are_never_recorded_as_open_alarms() -> None:
    """
    A BC/OP closes an alarm; it must never be memorized as one itself, or a later
    disarm/alarmReset would try to close a cancel. Story 13-4: the second disarm now
    reports its own OP (normal disarm, nothing open) instead of staying silent.

    Expected result:
    - the first disarm finds the open BA and sends BC then OP
    - the second disarm finds nothing open (BC/OP created no new entry) and sends OP alone
    """
    out = _run([
        {"logical_id": "burglarAlarm", "title": "Salon"},
        {"logical_id": "disarm"},
        {"logical_id": "disarm"},
    ])
    # Assert: first disarm closes the BA (BC, OP); second disarm reports its own OP alone
    assert [p["sia_code"] for p in _cancel_frames(out["sent"])] == ["BC", "OP", "OP"]
