"""
Real-PHP-execution tests for Story 14-4 (ADR-17 Amendment 4) — siaDC09::_handlePrefetchResult()'s
run_id/rank monotonic cache-replace rule (Decision 5).

Executes the REAL core/class/siaDC09.class.php via `php`, with minimal stubs for the two
symbols _handlePrefetchResult()/_prefetchResultShouldReplace() actually touch (`eqLogic`,
the class siaDC09 extends, and `log::add()`) — following the exact real-execution precedent
of tests/level1/test_frigate_snapshot_resolution.py's `_run_execute_burglar_alarm()`. The
private static method is invoked via ReflectionMethod (no setAccessible() call needed — a
no-op since PHP 8.1, deprecated in 8.5), bypassing message()/_getAutoEquipmentSafe() (and
the eqLogic::byType() lookup that would otherwise require), since AC6's replace rule is
entirely self-contained in that one method.

Reference: _bmad-output/implementation-artifacts/14-4-best-effort-alarm-media-forced-capture.md
Reference: ADR-17, Amendment 4, _bmad-output/planning-artifacts/architecture.md
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
PHP_SIA_FILE = _PROJECT_ROOT / "core/class/siaDC09.class.php"

pytestmark = pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")

_STUBS = r"""
class eqLogic {
}

class log {
    public static array $entries = [];
    public static function add($plugin, $level, $message): void {
        self::$entries[] = ['level' => $level, 'message' => $message];
    }
}

class FakeEqLogic extends eqLogic {
    public array $cache;
    public function __construct(array $cache) {
        $this->cache = $cache;
    }
    public function getCache($key, $default = null) {
        return $this->cache[$key] ?? $default;
    }
    public function setCache($key, $value): void {
        $this->cache[$key] = $value;
    }
}
"""

_DRIVER = r"""
$scenario = json_decode(file_get_contents($argv[1]), true);
$eqLogic = new FakeEqLogic(['sia_prefetch_cache' => $scenario['initial_cache']]);
$method = new ReflectionMethod('siaDC09', '_handlePrefetchResult');
$method->invoke(null, $eqLogic, $scenario['incoming']);
echo json_encode(['cache' => $eqLogic->cache['sia_prefetch_cache'], 'logs' => log::$entries]);
"""


def _run_handle_prefetch_result(initial_cache: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Invoke the real _handlePrefetchResult() once, return the resulting cache + logs.

    Args:
        initial_cache: the eqLogic's 'sia_prefetch_cache' content before the call, keyed
            by camera_eqlogic_id (string keys, matching PHP's json_decode(assoc) shape).
        incoming: the incoming prefetch_result message (without 'type').

    Returns:
        {"cache": <resulting sia_prefetch_cache>, "logs": [{"level", "message"}]}
    """
    source = PHP_SIA_FILE.read_text(encoding="utf-8")
    source = source.replace("<?php", "", 1)
    source = re.sub(r"^require_once .*;\s*$", "", source, count=0, flags=re.MULTILINE)
    scenario = {"initial_cache": initial_cache, "incoming": incoming}
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.php"
        harness.write_text("<?php\n" + _STUBS + source + _DRIVER, encoding="utf-8")
        scenario_file = Path(tmp) / "scenario.json"
        scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
        result = subprocess.run(
            ["php", str(harness), str(scenario_file)], capture_output=True, text=True, timeout=10
        )
    assert result.returncode == 0, f"PHP execution failed: {result.stderr}\n{result.stdout}"
    return json.loads(result.stdout)


def _entry(run_id: str, rank: int, clip_found: bool, event_id: str = "evt-old") -> dict[str, Any]:
    return {
        "found": True, "event_id": event_id, "clip_found": clip_found, "rank": rank,
        "run_id": run_id, "ts": 1000,
    }


def _incoming(run_id: str, rank: int, clip_found: bool, event_id: str = "evt-new", found: bool = True) -> dict[str, Any]:
    return {
        "camera_eqlogic_id": 42, "found": found, "event_id": event_id,
        "clip_found": clip_found, "rank": rank, "run_id": run_id,
    }


class TestPrefetchResultMonotonicReplace:
    """AC6 (ADR-17 Amendment 4, Decision 5): replaces only per the run_id/rank rule."""

    def test_newer_run_id_replaces(self) -> None:
        """
        Expected result:
        - a numerically greater run_id always replaces, regardless of rank
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=1, clip_found=True)},
            _incoming("2000.0", rank=4, clip_found=False),
        )["cache"]
        # Assert: the newer run's entry is now stored
        assert cache["42"]["run_id"] == "2000.0"
        assert cache["42"]["event_id"] == "evt-new"

    def test_older_run_id_is_ignored(self) -> None:
        """
        Expected result:
        - a numerically smaller run_id is ignored, even with a better rank
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("2000.0", rank=4, clip_found=False)},
            _incoming("1000.0", rank=1, clip_found=True),
        )["cache"]
        # Assert: the older run's entry never overwrote the stored one
        assert cache["42"]["run_id"] == "2000.0"
        assert cache["42"]["event_id"] == "evt-old"

    def test_same_run_better_rank_replaces(self) -> None:
        """
        Expected result:
        - same run_id, a smaller (better) rank replaces
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=3, clip_found=True)},
            _incoming("1000.0", rank=1, clip_found=False),
        )["cache"]
        # Assert: the better-ranked event replaced the manual one
        assert cache["42"]["rank"] == 1
        assert cache["42"]["event_id"] == "evt-new"

    def test_same_run_worse_rank_is_ignored(self) -> None:
        """
        Expected result:
        - same run_id, a larger (worse) rank is ignored
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=1, clip_found=False)},
            _incoming("1000.0", rank=2, clip_found=True),
        )["cache"]
        # Assert: the worse-ranked event never replaced the better one
        assert cache["42"]["rank"] == 1
        assert cache["42"]["event_id"] == "evt-old"

    def test_same_run_and_rank_clip_upgrade_replaces(self) -> None:
        """
        Expected result:
        - same run_id and rank, clip_found 0 -> 1 replaces (the clip-ready upgrade)
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=1, clip_found=False)},
            _incoming("1000.0", rank=1, clip_found=True),
        )["cache"]
        # Assert: the clip-ready upgrade was applied
        assert cache["42"]["clip_found"] is True
        assert cache["42"]["event_id"] == "evt-new"

    def test_same_run_and_rank_clip_downgrade_is_ignored(self) -> None:
        """
        Expected result:
        - same run_id and rank, clip_found 1 -> 0 is ignored (never a downgrade)
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=1, clip_found=True)},
            _incoming("1000.0", rank=1, clip_found=False),
        )["cache"]
        # Assert: the clip-ready flag was never cleared
        assert cache["42"]["clip_found"] is True
        assert cache["42"]["event_id"] == "evt-old"

    def test_missing_stored_run_id_legacy_entry_is_replaced(self) -> None:
        """
        A pre-14-4 cache entry (no 'run_id' key) must always be replaced — it can never
        be "newer" than a real run_id, so it must never block the first 14-4 callback.

        Expected result:
        - a legacy entry (found/event_id/clip_found/ts, no run_id/rank) is replaced
        """
        legacy_entry = {"found": True, "event_id": "evt-legacy", "clip_found": False, "ts": 1000}
        cache = _run_handle_prefetch_result(
            {"42": legacy_entry},
            _incoming("1000.0", rank=4, clip_found=False),
        )["cache"]
        # Assert: the legacy entry was replaced by the first 14-4 callback
        assert cache["42"]["event_id"] == "evt-new"
        assert cache["42"]["run_id"] == "1000.0"

    def test_entry_for_another_camera_is_untouched(self) -> None:
        """
        Expected result:
        - a callback for camera 42 never touches camera 99's stored entry
        """
        cache = _run_handle_prefetch_result(
            {"99": _entry("1000.0", rank=1, clip_found=True, event_id="evt-other-camera")},
            {**_incoming("2000.0", rank=1, clip_found=True), "camera_eqlogic_id": 42},
        )["cache"]
        # Assert: camera 99's entry is byte-for-byte unchanged
        assert cache["99"]["event_id"] == "evt-other-camera"
        assert cache["99"]["run_id"] == "1000.0"
        # Assert: camera 42 got its own new entry
        assert cache["42"]["event_id"] == "evt-new"

    def test_no_existing_entry_at_all_is_stored_unconditionally(self) -> None:
        """
        Expected result:
        - the very first callback for a camera with no prior cache entry is stored,
          whatever its rank
        """
        cache = _run_handle_prefetch_result({}, _incoming("1000.0", rank=4, clip_found=False))["cache"]
        # Assert: stored even though rank=4 (a miss) — nothing to compare against yet
        assert cache["42"]["run_id"] == "1000.0"
        assert cache["42"]["rank"] == 4

    def test_replacement_is_a_fresh_array_never_a_partial_merge(self) -> None:
        """
        Expected result:
        - a replaced entry carries exactly the incoming message's fields, with no
          leftover field from the previous entry (e.g. a stale event_id)
        """
        cache = _run_handle_prefetch_result(
            {"42": _entry("1000.0", rank=4, clip_found=False, event_id="evt-old")},
            _incoming("2000.0", rank=1, clip_found=True, event_id="evt-new"),
        )["cache"]
        # Assert: every field reflects only the incoming message, nothing from the old entry
        assert cache["42"] == {
            "found": True, "event_id": "evt-new", "clip_found": True, "rank": 1,
            "run_id": "2000.0", "ts": cache["42"]["ts"],
        }

    def test_non_numeric_rank_is_clamped_not_cast_to_zero(self) -> None:
        """
        Code review (2026-09-27): a malformed, non-numeric 'rank' would otherwise cast to
        0 via PHP's (int) cast, beating every real rank (1-4) and always winning the
        replace check regardless of actual priority.

        Expected result:
        - a string 'rank' that PHP casts to 0 is clamped to 1 (PREFETCH_RANK_PERSON),
          not stored as 0
        """
        incoming = _incoming("1000.0", rank=1, clip_found=False)
        incoming["rank"] = "not-a-number"
        cache = _run_handle_prefetch_result({}, incoming)["cache"]
        # Assert: clamped to the valid minimum, never 0
        assert cache["42"]["rank"] == 1

    def test_out_of_range_rank_is_clamped_to_valid_bounds(self) -> None:
        """
        Expected result:
        - a rank below 1 clamps to 1, a rank above 4 clamps to 4
        """
        low = _run_handle_prefetch_result({}, _incoming("1000.0", rank=-5, clip_found=False))["cache"]
        high = _run_handle_prefetch_result({}, _incoming("1000.0", rank=99, clip_found=False))["cache"]
        # Assert: both clamped into [1, 4]
        assert low["42"]["rank"] == 1
        assert high["42"]["rank"] == 4
