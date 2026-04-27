# Story 6.5: Jeedom Dependency Manager & Installation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a plugin maintainer,
I want clean installation and dependency management,
So that users can install via Jeedom Market without manual steps.

## Acceptance Criteria

1. **`plugin_info/info.json` corrected** — `require` kept as bare string `"4.5"` (expert confirmed: bare string still works and is safer for backward compatibility). `name` updated to canonical `"Télésurveillance SIA DC-09"`. `description.fr_FR` updated to canonical French description. `maxDependancyInstallTime` corrected to `10` (not `60`).

2. **`plugin_info/packages.json` cleaned** — Remove empty stubs (`pre-install: {}`, `npm: {}`, `yarn: {}`, `plugin: {}`, `post-install: {}`). Final content: `apt: {"python3-pip": {}}` + `pip3: {"jeedomdaemon": {"reinstall": true}, "pycryptodome": {}}`. This is **Method 1** (packages.json-only) — Jeedom handles pip install automatically into its venv on Debian 12.

3. **`dependancy_info()` simplified for Method 1** — With packages.json handling installation, `dependancy_info()` only needs the sentinel file check. However, the sentinel is no longer written by `install_dep.sh` (which doesn't exist in Method 1) — it must be written by `packages.json`'s `post-install` script or removed in favor of the `lastDependancyInstallTime` check alone. **Expert clarification:** Keep the sentinel as a secondary check. Add a minimal `post-install` script that writes it, OR rely solely on `lastDependancyInstallTime`. Must still be wrapped in `try/catch`.

4. **No `dependancy_install()` needed** — Method 1 means Jeedom's core handles installation from `packages.json`. No `dependancy_install()` override, no `install_dep.sh`. The reference plugin (aiodemo) confirms: no `dependancy_install()` method when using Method 1.

5. **Remove `dependancy_info()` entirely OR simplify** — The reference plugin (aiodemo) has **no** `dependancy_info()` at all — the Jeedom core wrapper handles everything when `hasDependency: true` is set in `info.json` and `packages.json` exists. If we keep a custom `dependancy_info()`, it should only add the sentinel check as a bonus guard. The current skeleton with just `.install_ok` is wrong because nothing writes that file in Method 1.

6. **`plugin_info/install.php` updated** — `siaDC09_remove()` should no longer delete `.install_ok` if we drop the sentinel pattern. If we keep it, the sentinel write must come from somewhere in Method 1. **Simplest approach: drop the sentinel entirely**, let Jeedom's `lastDependancyInstallTime` be the sole dependency-state mechanism (matching aiodemo).

7. **`preRemove()` in `siaDC09.class.php` verified** — Must stop daemon before equipment removal. Already implemented in Story 6.3 — verify unchanged.

8. **PHP structural tests** — Tests adapted for Method 1:
   - No `dependancy_install()` test (method doesn't exist)
   - No `install_dep.sh` test (file doesn't exist)
   - `test_dependancy_info_simplified()` — if kept, verify it has `try/catch` wrapping

9. **`info.json` structural tests** — Add `tests/level1/test_info_json.py`:
   - `test_info_json_require_is_string()` — `require` value is a string (not object — expert confirmed bare string is correct)
   - `test_info_json_has_dependency_flags()` — `hasDependency` and `hasOwnDeamon` are `true`
   - `test_info_json_os_min_is_12()` — `os.min == 12`
   - `test_info_json_max_dependancy_install_time()` — `maxDependancyInstallTime == 10`

10. **`packages.json` structural test** — Add `tests/level1/test_packages_json.py`:
    - `test_packages_json_has_pip3_jeedomdaemon()` — `pip3.jeedomdaemon` present
    - `test_packages_json_has_pip3_pycryptodome()` — `pip3.pycryptodome` present
    - `test_packages_json_no_empty_stubs()` — no empty `{}` values at top level (except inside pip3/apt entries)

11. **Full test suite passes** — All new tests pass, no regressions.

---

## Tasks / Subtasks

### Task 1: Fix `plugin_info/info.json` (AC1)

- [x] **1.1** Keep `require` as `"4.5"` (bare string — expert confirmed correct and backward-compatible)
- [x] **1.2** Update `name` to `"Télésurveillance SIA DC-09"` (canonical name per design doc Task 2.1)
- [x] **1.3** Update `description.fr_FR` to `"Transmission d'alarmes vers centrale de télésurveillance via protocole SIA DC-09"` (canonical per design doc)
- [x] **1.4** Update `maxDependancyInstallTime` from `60` to `10` (expert confirmed: 10 min is plenty for 2 pip packages)
- [x] **1.5** Preserve all other fields: `hasDependency: true`, `hasOwnDeamon: true`, `os.min: 12`, `category: "security"`, `language`, `compatibility`

---

### Task 2: Clean `plugin_info/packages.json` (AC2)

- [x] **2.1** Remove empty stub sections: `pre-install: {}`, `npm: {}`, `yarn: {}`, `plugin: {}`, `post-install: {}`
- [x] **2.2** Keep `apt: {"python3-pip": {}}` — needed before pip3 runs on fresh Debian installs
- [x] **2.3** Keep `pip3` section with `jeedomdaemon: {"reinstall": true}` (ensures upgrades apply) and `pycryptodome: {}` — all-object format

Final content:
```json
{
  "apt": {
    "python3-pip": {}
  },
  "pip3": {
    "jeedomdaemon": {"reinstall": true},
    "pycryptodome": {}
  }
}
```

---

### Task 3: Remove `dependancy_info()` from `siaDC09.class.php` (AC4, AC5)

- [x] **3.1** Delete the current `dependancy_info()` method entirely from `siaDC09.class.php`
- [x] **3.2** With `hasDependency: true` in `info.json` and `packages.json` present, Jeedom's core wrapper handles dependency checking automatically (confirmed by aiodemo reference — no `dependancy_info()` override)
- [x] **3.3** Verify: `deamon_info()` does NOT call `dependancy_info()` (it must not — the Jeedom core wrapper adds it automatically)

---

### Task 4: Remove sentinel references from `install.php` (AC6)

- [x] **4.1** Read `plugin_info/install.php` — `siaDC09_remove()` currently deletes `.install_ok`
- [x] **4.2** Remove the `.install_ok` sentinel deletion from `siaDC09_remove()` — no sentinel file exists in Method 1
- [x] **4.3** Keep the PID file cleanup and `system::kill('siadc09d.py')` — those are still needed for daemon cleanup on plugin removal

---

### Task 5: Verify `preRemove()` in `siaDC09.class.php` (AC7)

- [x] **5.1** Read `preRemove()` — verify it calls `deamon_stop()` + clears ring buffer config keys
- [x] **5.2** Already implemented in Stories 6.3/6.4 — no changes needed

---

### Task 6: Create `tests/level1/test_info_json.py` (AC9)

- [x] **6.1** Create new test file `tests/level1/test_info_json.py`
- [x] **6.2** Add `test_info_json_exists()` — `plugin_info/info.json` file present
- [x] **6.3** Add `test_info_json_valid_json()` — file parses as valid JSON
- [x] **6.4** Add `test_info_json_require_is_string()` — `require` is `str` (not dict — bare string is correct per expert)
- [x] **6.5** Add `test_info_json_has_dependency_flags()` — `hasDependency` is `True` and `hasOwnDeamon` is `True`
- [x] **6.6** Add `test_info_json_os_min_is_12()` — `os["min"] == 12`
- [x] **6.7** Add `test_info_json_max_dependancy_install_time()` — `maxDependancyInstallTime == 10`
- [x] **6.8** Add `test_info_json_category_is_security()` — `category == "security"`
- [x] **6.9** Add `test_info_json_id_matches_plugin()` — `id == "siaDC09"`

---

### Task 7: Create `tests/level1/test_packages_json.py` (AC10)

- [x] **7.1** Create new test file `tests/level1/test_packages_json.py`
- [x] **7.2** Add `test_packages_json_exists()` — `plugin_info/packages.json` file present
- [x] **7.3** Add `test_packages_json_has_pip3_jeedomdaemon()` — `pip3.jeedomdaemon` key present
- [x] **7.4** Add `test_packages_json_has_pip3_pycryptodome()` — `pip3.pycryptodome` key present
- [x] **7.5** Add `test_packages_json_no_empty_stubs()` — no top-level keys with empty `{}` except inside `apt`/`pip3` entries
- [x] **7.6** Add `test_packages_json_has_apt_python3_pip()` — `apt.python3-pip` key present

---

### Task 8: Update PHP structural tests (AC8)

- [x] **8.1** Add `test_no_dependancy_info_override()` to `test_php_eqlogic_stub.py`:
  - Verify `dependancy_info` method does NOT exist in `siaDC09.class.php` (core handles it via packages.json)
- [x] **8.2** Add `test_no_dependancy_install_override()`:
  - Verify `dependancy_install` method does NOT exist (Method 1 — core handles install)
- [x] **8.3** Add `test_deamon_info_does_not_call_dependancy_info()` to verify `deamon_info()` body does NOT contain `dependancy_info` (core wrapper adds it automatically)

---

### Task 9: Run tests (AC11)

- [x] **9.1** `python3 -m pytest tests/level1/test_info_json.py -v --tb=short` — all pass
- [x] **9.2** `python3 -m pytest tests/level1/test_packages_json.py -v --tb=short` — all pass
- [x] **9.3** `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short` — all pass
- [x] **9.4** `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/ -q --tb=short` — no new regressions

---

## Dev Notes

### Critical: Method 1 (packages.json) — NOT Method 2 (procedural)

**Expert validation (Jeedom plugin skill)** confirmed: the reference plugin (aiodemo) uses Method 1 exclusively:
- `packages.json` declares `pip3` deps
- Jeedom core handles install automatically (into venv on Debian 12)
- No `dependancy_info()` override in the class
- No `dependancy_install()` override
- No `install_dep.sh`

The design doc (php-core-design.md Task 2.8) specifies Method 2 (procedural sentinel pattern). **This story overrides the design doc for dependency management** — the expert confirmed that Method 1 is correct and Method 2 is redundant when `packages.json` exists.

### Critical: `require` Format — Keep Bare String

The design doc says `{"jeedom": ">=4.5"}` (object). Expert confirmed: bare string `"4.5"` is the original format, still supported by all Jeedom versions, and **safer for backward compatibility**. Object format is newer but not mandatory. Keep `"4.5"`.

### Critical: `dependancy_info()` Must Be REMOVED, Not Just Simplified

The current `dependancy_info()` checks for `.install_ok` sentinel file. With Method 1, **nothing writes this file** — `packages.json` uses Jeedom's internal mechanism (`lastDependancyInstallTime`). Keeping `dependancy_info()` with the sentinel check would **always return `'nok'`** because the sentinel never gets created. The method must be removed entirely.

### `install.php` — Remove Sentinel Cleanup

`siaDC09_remove()` currently deletes `.install_ok`. Since the sentinel file no longer exists in Method 1, this `unlink` call would just silently fail (`@unlink` suppresses the error). Remove it for cleanliness — but it's harmless either way.

### What Already Exists

| Artifact | Status | Action |
|----------|--------|--------|
| `plugin_info/info.json` | Exists — needs fixes | Fix name, description, maxDependancyInstallTime |
| `plugin_info/packages.json` | Exists — needs cleanup | Remove empty stubs |
| `plugin_info/install.php` | Exists — needs fix | Remove `.install_ok` unlink from `siaDC09_remove()` |
| `siaDC09::dependancy_info()` | Exists — **REMOVE** | Method 1 — core handles it |
| `siaDC09::dependancy_install()` | Missing — **DO NOT ADD** | Method 1 — core handles it |
| `resources/siadc09d/install_dep.sh` | Missing — **DO NOT CREATE** | Method 1 — core handles it |
| `siaDC09::preRemove()` | Exists — correct | Verify only |

### File Structure

```
Modified files (Story 6.5):
  plugin_info/info.json                          ← Fix name, description, maxDependancyInstallTime
  plugin_info/packages.json                      ← Remove empty stubs
  plugin_info/install.php                        ← Remove .install_ok unlink from siaDC09_remove()
  core/class/siaDC09.class.php                   ← Remove dependancy_info() method
  tests/level1/test_php_eqlogic_stub.py          ← Add 3 structural tests (no dependancy overrides)

New files (Story 6.5):
  tests/level1/test_info_json.py                 ← 8 info.json contract tests
  tests/level1/test_packages_json.py             ← 5 packages.json contract tests

Unchanged (verified only):
  core/class/siaDC09.class.php (preRemove)       ← Already correct from Stories 6.3/6.4
```

### References

- [Source: docs/design/php-core-design.md § Task 2.1 — info.json spec]
- [Source: docs/design/php-core-design.md § Task 2.2 — packages.json spec]
- [Source: docs/design/php-core-design.md § Task 2.8 — dependancy_info() spec (OVERRIDDEN by Method 1)]
- [Source: core/class/aiodemo.class.php — reference plugin has NO dependancy_info/install overrides]
- [Source: plugin_info/info.json — current state with fields to fix]
- [Source: plugin_info/packages.json — current state with empty stubs]
- [Source: Jeedom plugin expert skill — confirmed Method 1, bare string require, sudo pattern]

---

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.6 (1M context)

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Fixed `info.json`: `name` → canonical, `description.fr_FR` → canonical, `maxDependancyInstallTime` 60→10. Kept `require: "4.5"` bare string per expert.
- Cleaned `packages.json`: removed 5 empty template stubs. Final: `apt: {python3-pip}` + `pip3: {jeedomdaemon, pycryptodome}`.
- Removed `dependancy_info()` from `siaDC09.class.php` — Method 1 (packages.json), core handles it. Reference: aiodemo has no override.
- Removed `.install_ok` sentinel deletion from `install.php` `siaDC09_remove()` — sentinel doesn't exist in Method 1.
- Verified `preRemove()` unchanged: `deamon_stop()` + ring buffer cleanup.
- Created `tests/level1/test_info_json.py` — 12 contract tests (id, require format, flags, os.min, timeout, category, name, description, licence, author).
- Created `tests/level1/test_packages_json.py` — 7 contract tests (valid JSON, existence, pip3 deps, apt dep, no stubs, object format).
- Created `tests/level1/test_install_php.py` — 6 contract tests (existence, 3 hooks, daemon cleanup, no sentinel).
- Added 3 PHP structural tests: `test_no_dependancy_info_override`, `test_no_dependancy_install_override`, `test_deamon_info_does_not_call_dependancy_info`.
- Regression: 820 passed, 8 pre-existing failures unchanged.

### File List

- `plugin_info/info.json` — Fixed name, description, maxDependancyInstallTime
- `plugin_info/packages.json` — Removed empty stubs
- `plugin_info/install.php` — Removed .install_ok sentinel from siaDC09_remove()
- `core/class/siaDC09.class.php` — Removed dependancy_info() method
- `tests/level1/test_info_json.py` — **NEW** — 12 info.json contract tests
- `tests/level1/test_packages_json.py` — **NEW** — 7 packages.json contract tests
- `tests/level1/test_install_php.py` — **NEW** — 6 install.php structural tests
- `tests/level1/test_php_eqlogic_stub.py` — Added 3 Story 6.5 structural tests
- `docs/design/php-core-design.md` — Task 2.8 Method 2 override banner + file structure fix
- `_bmad-output/planning-artifacts/architecture.md` — Updated 3 stale sentinel/dependancy_info references

### Change Log

- 2026-04-27: Story 6.5 created — Jeedom Dependency Manager & Installation
- 2026-04-27: Story 6.5 rewritten after expert validation — switched to Method 1 (packages.json only)
- 2026-04-27: Story 6.5 implemented — Method 1 cleanup, removed dependancy_info/sentinel, 16 new tests
- 2026-04-27: QA challenge — added 12 tests (name, description, licence, author, valid JSON, pip3 format, install.php hooks/cleanup/sentinel guard)
- 2026-04-27: Adversarial review — F1 design doc Task 2.8 override banner, F2 architecture.md updated (3 refs), F3 Market URLs added, F5/F6 file list + completion notes corrected, F8 jeedomdaemon reinstall flag noted, F10 link stubs removed
- 2026-04-27: Code review — M1 en_US.json install.php section added, L1 story task 2.3 reinstall flag corrected; status → done
