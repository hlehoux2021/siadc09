---
title: '18.10 - Refactor sweep'
type: 'refactor'
ticket: '10'
created: '2026-11-10'
status: done
baseline_revision: 'c599132eaab27fdcb13b7f4ef9a4d1c3a2102422'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The epic's upload code carries two `too-many-arguments` pylint disables: `ftps_upload._upload_stream` (6 parameters, deferred from the 18.8 review) and `daemon._run_ftps_upload` (same shape, with `_upload_snapshot` and `_upload_clip` repeating the same four arguments).

**Approach:** Replace each argument group with a small frozen dataclass and drop both disables, with no behaviour change; the level 1 and level 2 suites pass unchanged. The other findings deferred during the epic (AES key and apikey on the command line, media editing in config mode, server retention) are features, not cleanup: they stay in `deferred-work.md`.

</frozen-after-approval>

## Implementation Notes

Oneshot: about 60 changed lines in two files, no public signature changes (`upload_bytes`, `upload_file`, the `on_message` payload), no test calls the private functions.

## Plan Change Log

## Review Triage Log

Quick review (1 lens), no high or medium finding.

- low, patched: `_upload_stream` and `_Transfer` had no Args / Attributes docstring (python-style rule) -- added.
- low, patched: `_Transfer` was defined after `upload_bytes` / `upload_file`, which use it -- moved above `upload_bytes`.
- false: the `when` Args entries in `_upload_clip` / `_upload_snapshot` -- documentation only, harmless.
- false: plan `status` still `in-progress` -- expected until finalize.
- note: the reviewer read `git diff HEAD` (same as the baseline c599132) because the temp diff was outside its allowed directories.
- Deferred findings of the epic stay in `deferred-work.md` (AES key and apikey off the command line, media editing in config mode): features, not cleanup.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/ tests/level2/ -q` -- expected: only the 5 known level 2 failures
- `python3 -m pylint resources/siadc09d/ftps_upload.py` -- expected: no `too-many-arguments`
