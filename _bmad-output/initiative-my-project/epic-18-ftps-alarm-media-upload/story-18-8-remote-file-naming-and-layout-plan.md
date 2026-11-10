---
title: '18.8 - Remote file naming and layout'
type: 'feature'
ticket: '8'
created: '2026-11-10'
status: done
baseline_revision: 'a18f619d37ee6d81a9bba7c1507cffd86d669ef3'
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

**Problem:** Uploads are named `<account>-<event_id>-snapshot.jpg` in one flat folder: nothing says which zone or day a file belongs to, and the layout is undocumented (E18-R2).

**Approach:** A first, simple and documented layout: `<ftps_folder>/<account>/<YYYY-MM-DD>/<HHMMSS>_<zone>_<event_id>.<jpg|mp4>`, folders created on demand.

## Boundaries & Constraints

**Always:** Every variable part goes through `safe_name_part()`; no empty or dots-only component; snapshot and clip of one alarm share date and time.

**Never:** Retention, cleanup or quota on the server (deferred); a configurable layout; touching `probe_connection`, `--test-ftps` or `testFtps` (18.7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Layout | account 001234, zone Salon, 14:05:09 on 2026-11-10 | `001234/2026-11-10`, `140509_Salon_<event>.jpg` | None |
| Deterministic | Same input twice | Same result | None |
| Two zones | Same second, other zone | Different name | None |
| Two times | Other second or other day | Different name or folder | None |
| Same zone, same second | Other event id | Different name | None |
| Hostile or empty parts | `..`, `/`, accents, empty | Safe characters, fallback names, two levels | None |
| Snapshot + clip | One alarm | Same folder and prefix, `.jpg` / `.mp4` | None |
| Tree missing | No account/date folder | `MKD` per missing level, then `STOR` | Step `mkdir` named on failure |
| Tree exists | Second alarm of the day | CWD only, no `MKD` | None |
| Creation race | `MKD` refused, `CWD` then works | Upload goes on | None |
| No directory | Direct caller | Old behavior | None |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/ftps_upload.py` -- `remote_location()` (pure naming), `_enter_directory()`, `directory` argument of `upload_bytes`/`upload_file`/`_upload_stream`
- `resources/siadc09d/daemon.py` -- `_run_ftps_upload` takes one `when`; `_upload_snapshot`/`_upload_clip` use `remote_location` and pass `directory`
- `internal-docs/ftps-test-server.md` -- "Remote file layout" section
- Tests: `tests/level1/test_ftps_remote_layout.py`; adapted `tests/level2/test_ftps_upload_dispatch.py`, `test_ftps_clip_dispatch.py`

## Tasks & Acceptance

**Execution:**
- [x] `resources/siadc09d/ftps_upload.py` -- naming function and directory creation -- one pure, testable rule
- [x] `resources/siadc09d/daemon.py` -- use it at both call sites with a shared time -- snapshot and clip side by side
- [x] `tests/level1/test_ftps_remote_layout.py`, level2 dispatch tests -- one test per matrix row -- proves the matrix
- [x] `internal-docs/ftps-test-server.md` -- layout and deferred retention -- documented

**Acceptance Criteria:**
- Given two alarms of different zones and times, when both upload, then they leave distinct, predictable paths.

## Implementation Notes

- Time is the daemon's local time at alarm handling (`datetime.now().astimezone()`), taken once in `_run_ftps_upload`; not the SIA frame timestamp.
- Directory creation is CWD first, MKD on refusal, CWD again; an MKD refusal is ignored since the following CWD decides. The configured folder itself is still not created.
- Non-ASCII zone labels become `_` (e.g. `Salon é` gives `Salon__`); the event id keeps names unique.
- Existing level2 name assertions were relaxed to regexes (time-dependent). Field check on test-jeedom left to the human.
- Retention/cleanup on the server: deferred, stated in the doc.

## Plan Change Log

## Review Triage Log

Pass 1 (quick): 0 high, 3 medium, 3 low, 1 maybe-false, 1 false/none.

| Verdict | Route | Finding and evidence |
|---|---|---|
| medium | patch | No test for the `mkdir` error row: nothing made `MKD` and `CWD` fail. Added `test_mkdir_failure_names_the_step`. |
| medium | patch | Dots-only assertion read `name.split("_")[1]`, a fragment of the zone, and never the event id. Replaced by `test_empty_or_dots_only_parts_get_a_placeholder` with explicit placeholders. |
| medium | patch | The clip dispatch test never asserted `directory`. Both uploads now checked against one `<account>/<date>` folder. |
| low | rejected | No level 2 test for `zone=None`. Covered at `remote_location()`; the daemon passes the zone through unchanged. |
| low | rejected | `_upload_stream` has 6 parameters behind a pylint disable. `_run_ftps_upload` already does the same; a value object is a refactor for the sweep (18.10). |
| low | rejected | The refused `MKD` text is dropped when the next `CWD` fails. The step name is right; keeping both texts needs new wording. |
| maybe-false | rejected | The time is taken when the upload starts, so near midnight date and `HHMMSS` can differ from the alarm. A documented decision in Implementation Notes; at worst a one-folder shift. |
| false | rejected | Doc example `Salon é` gives `Salon__`: correct. |

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/` -- expected: no new failures vs baseline
- `python3 -m pylint resources/siadc09d/ftps_upload.py` -- expected: no new messages

**Manual checks (if no CLI):**
- On test-jeedom: trigger a BA with the FTPS transport; `ls -R` of the upload folder shows `<account>/<date>/<HHMMSS>_<zone>_<event>.jpg`.
