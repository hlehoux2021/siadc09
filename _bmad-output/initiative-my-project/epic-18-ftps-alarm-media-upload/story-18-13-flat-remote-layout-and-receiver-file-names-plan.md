---
title: '18.13 - Flat remote layout and receiver file names'
type: 'feature'
ticket: '13'
created: '2026-11-13'
status: 'built'
baseline_revision: '5ac6d49c39e16fcb4c57574a03535e57f08793e8'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/.claude/rules/python-style.md'
  - '{project-root}/.claude/rules/testing.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Uploads go into `<account>/<date>/` subfolders and are named `<HHMMSS>_<zone label>_<event id>.<ext>`. The receiver expects flat files named `{UID}_{zone}_{timestamp}_{image}`.

**Approach:** Replace the layout of 18.8: files go at the root of the configured FTPS folder, named `<account>_<zone number, 2 digits>_<Unix epoch seconds>_0001.<jpg|mp4>`, for example `12345678_01_1675938881_0001.jpg`.

## Boundaries & Constraints

**Always:** The account goes through `safe_name_part()`. The snapshot and the clip of one alarm share the same epoch. The zone number is the one the plugin already sends with the alarm (`zone_number`). The image part is the constant `0001`.

**Never:** Touch `probe_connection`, `--test-ftps`, `testFtps`, or the PHP plugin. Create any subfolder. Add retention, cleanup or a configurable layout. Handle a zone with a camera but no number (zones are numbered by design in the wizard).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Layout | account 12345678, zone 1, epoch 1675938881 | `12345678_01_1675938881_0001.jpg`, no directory | None |
| Clip | Same alarm | Same name with `.mp4` | None |
| Zone 3 digits | zone 123 | `..._123_...` | None |
| Two zones | Same second, other zone | Different name | None |
| Same zone, same second | Other event | Same name, later file overwrites | Accepted (user decision) |
| Hostile account | `../x`, empty, accents | Safe characters, `noaccount` placeholder | None |
| Zone number absent | `zone_number` is None | Zone part `00`, no crash | Not handled further |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/ftps_upload.py` -- `remote_location()` (returns a directory and a name today), `_enter_directory()`, the `directory` argument of `upload_bytes`/`upload_file`/`_Transfer`/`_upload_stream` (to delete), constants `NO_ZONE`/`NO_EVENT` (to delete), `NO_ACCOUNT` and `_path_part` (to keep)
- `resources/siadc09d/daemon.py` -- `FtpsAlarmMedia` (add `zone_number`), `_run_ftps_upload` (one `when`), `_upload_snapshot`/`_upload_clip` (two `remote_location` calls and `directory=`), `on_message` around line 3089 (`zone_number` is already a local there)
- `tests/level1/test_ftps_remote_layout.py` -- 12 tests of the 18.8 layout; rewrite for the new rule, drop the mkdir/CWD tests
- `tests/level2/test_ftps_upload_dispatch.py` line 76-78, `tests/level2/test_ftps_clip_dispatch.py` lines 198-208 -- name regex and `directory` assertions
- `internal-docs/ftps-test-server.md` -- section "Remote file layout (ticket 18.8, first version)"
- `internal-docs/design/daemon-design.md` -- mentions the upload; check for the layout
- Do not change: `core/class/siaDC09Cmd.class.php` (already sends `zone_number`)

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/ftps_upload.py` -- `remote_location(account, zone_number, when, extension)` returns one name; delete `_enter_directory`, the `directory` plumbing and the unused constants -- one flat rule, no dead code
- [ ] `resources/siadc09d/daemon.py` -- add `zone_number` to `FtpsAlarmMedia`, pass it from `on_message`, build the name with the shared epoch at both call sites, stop passing `directory` -- snapshot and clip side by side
- [ ] `tests/level1/test_ftps_remote_layout.py`, level 2 dispatch tests -- one test per matrix row, remove the folder tests -- proves the matrix
- [ ] `internal-docs/ftps-test-server.md` (and `daemon-design.md` if it states the layout) -- new layout, the overwrite on same zone and second, the 0001 clip to test in the field -- documented

**Acceptance Criteria:**
- Given two alarms of different zones, when both upload, then two distinct files sit at the root of the FTPS folder and no subfolder is created.
- Given a snapshot and a clip of one alarm, when both upload, then their names differ only by the extension.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Pass 1 (quick): 0 high, 0 medium, 3 low, 3 false/rejected.

| Verdict | Route | Finding and evidence |
|---|---|---|
| low | patch | Hostile-account test never asserted the "no empty or dots-only account part" its docstring promises. Added the assert on the account part. |
| low | patch | Clip dispatch test kept a `folders` list that would pass with `directory=None` still passed. Now asserts `"directory"` is absent from every upload call. |
| low | patch | `remote_location` docstring named `safe_name_part()` for the account; it is `_path_part()`. Wording fixed. |
| false | rejected | Negative `zone_number` not tested: the plan's Never excludes zones without a valid number, and the wizard numbers zones. |
| low | rejected | No dispatch test with two zones: `remote_location` is proven distinct per zone at level 1, and the dispatch passes `zone_number` unchanged. |
| false | rejected | Long test lines may add pylint messages: the plan's pylint command targets `resources/` only, and the 4 messages seen are existing f-string logs. |

## Design Notes

The epoch is `int(when.timestamp())` of the single `datetime.now().astimezone()` already taken in `_run_ftps_upload`; it is timezone-independent. Image number is a module constant so the later series feature has one place to change.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs baseline
- `python3 -m pylint resources/siadc09d/ftps_upload.py resources/siadc09d/daemon.py` -- expected: no new messages

**Manual checks (if no CLI):**
- On test-jeedom: trigger a BA with the FTPS transport; `ls` of the upload folder shows `<account>_<zone>_<epoch>_0001.jpg` and no subfolder.
