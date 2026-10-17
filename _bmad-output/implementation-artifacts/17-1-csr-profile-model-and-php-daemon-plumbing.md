---
story_id: "17-1"
story_key: "17-1-csr-profile-model-and-php-daemon-plumbing"
epic_id: "epic-17"
epic_name: "CSR Behaviour Profiles & Periodic Frames"
status: "built"
created: "2026-10-17"
baseline_revision: "737320f9b85d4fdcd2b272b7f95b87e46938cf12"
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
---

# Story 17.1: CSR Profile Model & PHP → Daemon Plumbing

Status: built

First story of Epic 17 (ADR-22). It carries the three new periodic-frame settings from the equipment configuration to
the daemon, validates them, and adds the profile file. **It changes no frame and no cadence.** The supervision loop
keeps sending `"SIA-DCS"…[#acct|0000]` at `supervision_interval_s` whatever the new values are. Sending `null` frames
is 17.2, sending RP is 17.3, and the wizard fields are 17.4. Until 17.4, no user can set the new keys from the UI.

**Requirements:**
- NFR7 (CSR extensibility: one JSON entry per profile);
- NFR4 (supervision keep-alive, now a configurable format);
- FR11, as amended by ADR-22 (CSR profiles replace the IMA preset).

## Story

As a plugin maintainer,
I want the periodic-frame settings carried from the equipment configuration to the daemon, with profiles defined in one
PHP-side file,
So that adding a CSR profile is a JSON entry and the daemon only ever sees resolved values.

## Acceptance Criteria

1. **Profile file.** `core/config/csr_presets.json` exists, with `"schema_version": 1` and a `profiles` object holding
   `ajax` and `scutum`. Each profile has a French `label` and the equipment config keys it sets:
   `supervision_format: "none"`, `rp_enabled: 1`, `rp_interval: 60`. `supervision_interval` is omitted, since
   `none` makes it irrelevant. "Personnalisé" is not an entry: it means "no profile" (17.4).
2. **PHP-only reader.** `siaDC09::getCsrProfiles(): array` reads the file and returns `profiles`. If the file is
   missing or unreadable, or `schema_version` is not 1, it logs at `error` and returns `[]`; it never throws.
   - Nothing under `resources/siadc09d/` reads the file.
   - No profile name or `csr_profile` key appears in the daemon arguments (ADR-22).
3. **`CSRPreset` fields.** `resources/siadc09d/presets.py` gains three fields, with defaults equal to today's
   behaviour:
   - `supervision_format: SupervisionFormat = "sia-dcs"`, where `SupervisionFormat = Literal["none", "sia-dcs", "null"]`;
   - `rp_enabled: bool = False`;
   - `rp_interval_s: float = 60.0`.
4. **Daemon arguments.** `siadc09d.py` accepts three arguments and passes them into `CSRPreset`:
   - `--supervision-format` (`choices` = the three values, default `sia-dcs`);
   - `--rp-enabled` (`store_true`);
   - `--rp-interval` (int, default 60).
5. **PHP passes them.** `deamon_start` reads the equipment config keys `supervision_format` (default `'sia-dcs'`),
   `rp_enabled` (default 0) and `rp_interval` (default 60), and appends the matching arguments.
   - `--supervision-format` is always passed.
   - `--rp-enabled` and `--rp-interval` are passed only when `rp_enabled` is truthy, the same pattern as
     `--encryption-enabled`.
6. **Key consistency.** `tests/level1/test_wizard_config_key_consistency.py` gains `_PERIODIC_FRAME_KEYS =
   ["supervision_format", "rp_enabled", "rp_interval"]`. For each key it checks that:
   - `deamon_start` reads it (`getConfiguration('<key>'` in `core/class/siaDC09.class.php`);
   - `siadc09d.py` accepts it as `--<key-with-hyphens>`.

   Add the `data-l2key` check now, marked `xfail(strict=True, reason="wizard field added by Story 17.4")`, so 17.4
   has to turn it green.
7. **Refusal on invalid combinations, with no restart loop.**
   - `CSRPreset.__post_init__` raises `ValueError` when:
     - `supervision_format == "none"` and `rp_enabled` is false (no periodic frame);
     - `rp_enabled` is true and `rp_interval_s` is outside `60 ≤ x ≤ 86400`;
     - `supervision_format` is not one of the three values.
   - `siadc09d.py` catches it around the `CSRPreset(...)` construction, prints one French line to stderr, and exits
     with code 1. stderr is redirected to the `siaDC09_daemon` log by `deamon_start`. Example line:
     `Configuration refusée : aucune trame périodique active (supervision « none » et test cyclique RP désactivé)`.
   - `deamon_info()` gets a matching guard (Guard 3e) that returns `launchable = nok` with a French
     `launchable_message`. **This guard is what prevents the restart loop:** Jeedom's auto-restart never calls
     `deamon_start` while `launchable` is `nok`.
   - **Clarification of the epic AC (approved by Herve, 2026-10-17):** the RP range is checked only when RP is
     enabled. A stored but unused `rp_interval` must not block the daemon.
   - **Guard 3d** (`supervision_interval > 0`) applies only when `supervision_format !== 'none'`.
8. **`crc_format=bin` decision: removed from the sender side** (Herve, 2026-10-17). The CLI and `CSRPreset` accept
   only `hex`. The receiver-side code (simulator, decoder) keeps `bin`. Details are in Dev Notes § "crc_format=bin".
9. **No behaviour change.** An equipment with none of the new keys set:
   - starts with `--supervision-format 'sia-dcs'` and no RP argument;
   - builds a `CSRPreset` with the defaults;
   - sends exactly the same frames at the same cadence as before this story.

   The existing level-1, level-2 and level-2.5 tests that pin the supervision frame and cadence stay green, with no
   edits.

## Tasks / Subtasks

- [x] Task 1 — `CSRPreset` fields and validation (AC: 3, 7)
  - [x] 1.1 Add the `SupervisionFormat` Literal, plus named constants `RP_INTERVAL_MIN_S = 60` and
        `RP_INTERVAL_MAX_S = 86400`, in `presets.py`.
  - [x] 1.2 Append the three fields **after** `reconnect_max_attempts`. Every field there has a default, and the
        existing `CSRPreset(...)` calls in tests use keywords.
  - [x] 1.3 Extend `__post_init__` with the three checks. Each message names the field and the value.
  - [x] 1.4 Tests in `tests/level1/test_csr_preset_validation.py`:
    - the defaults;
    - each of the three formats is accepted;
    - `none` with RP off is rejected;
    - `none` with RP on is accepted;
    - the RP bounds are inclusive at 60 and 86400, and 59 and 86401 are rejected;
    - an out-of-range `rp_interval_s` with RP off is accepted;
    - an unknown format is rejected.
- [x] Task 2 — Daemon arguments and fail-fast (AC: 4, 7, 9)
  - [x] 2.1 Add the three `_config.add_argument(...)` calls next to `--supervision-interval` in `siadc09d.py:405`.
  - [x] 2.2 Pass them into `CSRPreset(...)` (`siadc09d.py:414-429`). `rp_interval_s=float(_config.rp_interval)`.
  - [x] 2.3 Wrap the construction in `try/except ValueError as e`: one French stderr line, then `sys.exit(1)`.
        Existing transport and reconnect `ValueError`s get the same treatment, which is a free improvement.
  - [x] 2.4 Level-1 test: run `siadc09d.py` as a subprocess with `--supervision-format none` and no
        `--rp-enabled`, plus the minimum required args. Assert exit code 1 and the French line on stderr, with no
        traceback. Check how `tests/level1/test_daemon_startup_regressions.py` launches the entry point and reuse
        its pattern.
- [x] Task 3 — PHP `deamon_start` and `deamon_info` (AC: 5, 7)
  - [x] 3.1 After the `--supervision-interval` block (`siaDC09.class.php:266-269`), add `--supervision-format` with
        `escapeshellarg`. Add `--rp-enabled --rp-interval <int>` only when `rp_enabled` is truthy.
  - [x] 3.2 Guard 3e in `deamon_info()`, right after Guard 3d (`siaDC09.class.php:161-171`):
    - an unknown `supervision_format` → `nok`;
    - `none` with RP off → `nok`;
    - RP on with an interval outside 60-86400 → `nok`.

    Messages point at "étape 1 de l'assistant (Options avancées)". Use class constants for the bounds, mirrored from
    the Python ones.
  - [x] 3.3 Make Guard 3d conditional on `supervision_format !== 'none'`.
  - [x] 3.4 Add the new French strings to `core/i18n/fr_FR.json` if the round-trip test from 11-4 requires them. Run
        it to find out.
- [x] Task 4 — Profile file and PHP reader (AC: 1, 2)
  - [x] 4.1 Create `core/config/csr_presets.json` (shape in Dev Notes). The directory does not exist yet.
  - [x] 4.2 Add `public static function getCsrProfiles(): array` in `siaDC09.class.php`. Use
        `file_get_contents` + `json_decode(..., true)`, check `schema_version === 1`, and log an error and return
        `[]` on any failure. Nothing calls it until 17.4. That is expected; say so in its docblock.
  - [x] 4.3 Level-1 Python test, `tests/level1/test_csr_presets_json.py`:
    - the file parses and `schema_version == 1`;
    - `ajax` and `scutum` exist with the Epic 17 table values;
    - every profile key is in `{label, supervision_format, supervision_interval, rp_enabled, rp_interval}`;
    - no profile is the invalid `none` + RP-off combination;
    - no file under `resources/siadc09d/` contains `csr_presets`, which pins AC2.
  - [x] 4.4 `php -l core/class/siaDC09.class.php`.
- [x] Task 5 — Remove `crc_format=bin` from the sender side (AC: 8)
  - [x] 5.1 Add `choices=["hex"]` to `--crc-format` in `siadc09d.py`. Make `CSRPreset` reject anything other than
        `"hex"`, with a `ValueError` that Task 2.3 already handles.
  - [x] 5.2 Remove the dead `"SIA" if … else "ADM"` mapping: `daemon.py:481` and `siadc09d.py:307` become
        `SIAMessageBuilder(crc_format="SIA")`. Keep the edit to `daemon.py` minimal (see "Parallel work").
  - [x] 5.3 Make `deamon_info()` refuse a stored `crc_format` other than `hex`, with a `launchable_message` that asks
        for the equipment to be re-saved. That keeps a manually edited DB from triggering the restart loop.
  - [x] 5.4 Rework the sender-side tests that pin `bin`. Known on 2026-10-17:
    - `test_daemon_startup_regressions.py:222-293` (Fix #7, `bin`→`ADM` mapping): replace with "CSRPreset rejects
      `bin`" plus "the builder is always `SIA`";
    - `test_wizard_config_ipc.py:303` and `:582` (`_make_wizard_preset(crc_format="bin")`): drop them, or turn them
      into rejection tests;
    - add the `bin` rejection to `test_csr_preset_validation.py`.

    **Do not touch** the receiver-side tests: `conftest.py` `preset_bin_crc` (a `CSRSimulatorPreset`),
    `test_csr_simulator.py`, `test_simulator_cli.py`, `test_sia_protocol_ack_nak.py`,
    `test_ack_nak_assertion_hardening.py`, `test_parse_response_garbled.py` (transport ACK parsing) and
    `tests/harness/`.
  - [x] 5.5 Update the ADR-06 note in `architecture.md`: `bin` removed from the sender side on 2026-10-17 (Story
        17.1), kept on the receiver side.
- [x] Task 6 — Key consistency and regression run (AC: 6, 9)
  - [x] 6.1 Add `_PERIODIC_FRAME_KEYS` and its three parametrized tests (PHP class, Python CLI, and the PHP page as
        `xfail(strict=True)`). Add a `php_class` fixture reading `core/class/siaDC09.class.php`.
  - [x] 6.2 Level-2 test: a daemon built from a default `CSRPreset` keeps one supervision loop at
        `supervision_interval_s`, with frames unchanged. Use an existing supervision-cadence test if one already pins
        this; add one only if none does.
  - [x] 6.3 Run `python3 -m pytest tests/level1/`, `tests/level2/` and `tests/level2_5/`. Compare against the
        baseline measured on clean master before starting (memory: level-1 test baseline failures; re-measure, don't
        copy).
  - [x] 6.4 `python3 -m pylint resources/siadc09d/`, and run `php -l` on every touched PHP file.

## Dev Notes

### What this story does not do

- **No frame change.** `_supervision_loop` (`daemon.py:2304-2324`) and `make_supervision_message` stay as they are.
  The daemon stores `supervision_format`, `rp_enabled` and `rp_interval_s` without acting on them. `null` and `none`
  as sending behaviours belong to 17.2, RP to 17.3.
- **No staleness change.** ADR-08 "3 × the shortest active interval" lives in 17.3, both in the daemon and in PHP
  `_checkSupervisionFreshness` (`siaDC09.class.php:326-328`, which still uses `supervision_interval * 3`).
- **No wizard field, no profile selector, no `csr_profile` key.** These are 17.4.

### Config key names

The equipment config keys follow the existing convention: no `_s` suffix in PHP; the seconds suffix is added on the
Python side, as with `supervision_interval` → `supervision_interval_s`.

| Equipment config key | Daemon argument | `CSRPreset` field | Default |
|---|---|---|---|
| `supervision_format` | `--supervision-format` | `supervision_format` | `sia-dcs` |
| `supervision_interval` (exists) | `--supervision-interval` (exists) | `supervision_interval_s` (exists) | 60 |
| `rp_enabled` | `--rp-enabled` | `rp_enabled` | off |
| `rp_interval` | `--rp-interval` | `rp_interval_s` | 60 |

17.4 must use these exact keys as `data-l2key`. The strict `xfail` test in AC6 enforces it.

### `core/config/csr_presets.json` shape

```json
{
  "schema_version": 1,
  "profiles": {
    "ajax":   { "label": "Ajax",   "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60 },
    "scutum": { "label": "Scutum", "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60 }
  }
}
```

- Values come from the Epic 17 table and `internal-docs/ajax.md` (captures A/B: on-demand, RP at the ping interval,
  60 s minimum on the Ajax side).
- The connection mode is not a profile key. Only on-demand exists today (D-115).
- The profile name ("Scutum") is a CSR name inside a PHP config file. That is fine: the "no CSR named" editorial rule
  applies to the public docs, not to code. Do not add real endpoints or account numbers.
  `internal-docs/telesurveillances.txt` stays out of this file.

### Restart-loop mechanics (AC7)

- Jeedom's daemon auto-mode restarts a stopped daemon only while `deamon_info()['launchable'] === 'ok'`. If only the
  Python side refused, Jeedom would relaunch every cycle, and each run would print one refusal line and exit.
- The PHP Guard 3e makes the combination unlaunchable before `exec`. The Python check is defence in depth, for a
  manual command-line start or a guard that drifts out of sync.
- Keep the two in sync: the same three rules and the same bounds. Name the bounds as constants on both sides.
- Optional: a level-1 test that greps both files for the bound values, in the style of the key-consistency test.

### `crc_format=bin` (AC8) — facts and proposed decision

**Facts, verified 2026-10-17:**
- `daemon.py:481` maps `bin` → `SIAMessageBuilder(crc_format="ADM")`. `SIAMessageBuilder.crc_format`
  (`sia_protocol.py:232`) is stored and **never read**, so outgoing frames always carry the hex SIA CRC.
- The transports pass `crc_format` to `decode_ack_nak()` (`daemon.py:2572/2580`). `bin` changes **ACK parsing**
  only.
- The wizard has no `crc_format` field (no `data-l2key`). `deamon_start` sends the stored value, default `hex`
  (`siaDC09.class.php:246`). No current install can have `bin` short of a manual DB edit.
- The run-connection-test path (`siadc09d.py:306-308`) has the same dead mapping.

**So `bin` today produces a hex-CRC frame and then expects a bin-CRC ACK.** That is worse than either value alone.

**Proposed decision: remove `bin` from the sender side.**
- No CSR in hand needs it. The original reason in ADR-06 was a Lupusec CSR, which was never seen.
- Implementing it is a protocol feature (ADM-CID CRC on encode), not plumbing.
- Keep `bin` on the **receiver side**: `csr_simulator.py`, `simulate_frames.detect_crc_format`, and the `decode()` and
  `decode_ack_nak()` parameters. Those play the CSR role and are tested as such.
- Leave `CrcFormat` in `sia_transport.py` alone if the receiver-side code still uses it. Narrow only what
  `CSRPreset` and the CLI accept.

**Decision: remove** (Herve, 2026-10-17).

### Code locations

| Item | Location |
|---|---|
| `CSRPreset` | `resources/siadc09d/presets.py:17-60` |
| Daemon CLI + `CSRPreset(...)` | `resources/siadc09d/siadc09d.py:392-431` |
| Connection-test path (reads the config dict, not the CLI) | `resources/siadc09d/siadc09d.py:263-344` |
| Builder CRC mapping | `resources/siadc09d/daemon.py:481-482` |
| Supervision loop (unchanged here) | `resources/siadc09d/daemon.py:2304-2324` |
| `deamon_info` guards 3c/3d | `core/class/siaDC09.class.php:152-171` |
| `deamon_start` | `core/class/siaDC09.class.php:223-301` |
| Freshness check (17.3, not here) | `core/class/siaDC09.class.php:326-328` |
| Key-consistency test | `tests/level1/test_wizard_config_key_consistency.py:254-285` (`_SUPERVISION_KEYS` pattern) |
| `CSRPreset` tests | `tests/level1/test_csr_preset_validation.py` (`_make_preset` helper) |
| Other `CSRPreset(...)` builders | `tests/conftest.py`, `tests/level3/conftest.py`, `tests/level2/test_sia_transport_daemon_wiring.py`, `tests/level2_5/test_wizard_config_ipc.py`, `tests/level2_5/test_ipc_integration.py`, `tests/level1/test_daemon_startup_regressions.py` |

Because the new fields have defaults, none of the other builders needs to change. If one breaks, the field order or
default is wrong.

### Parallel work

`daemon.py` is the merge hot spot (memory: parallel agents & daemon conflict). This story barely touches it: at most,
the AC8 removal could simplify the `"SIA" if … else "ADM"` mapping at line 481. Keep that edit minimal, so 17.2 and
17.3 can start right after.

### Testing rules

- Docstring with scenario and expected result, one comment per assert (`.claude/rules/testing.md`).
- Level 1 is sync and has no external dependencies, so the subprocess test in 2.4 must not open a socket. Check that
  `BaseConfig.parse()` plus the `CSRPreset` failure exits before any network setup; the construction is at
  `siadc09d.py:414`, before `SIADaemon(...).run()`.
- Prefer tests over a live trial-and-error loop on test-jeedom. The real check of this story is the full suite plus
  one deploy on test-jeedom, confirming that the daemon starts as before: the log shows `--supervision-format
  'sia-dcs'`, and the widget shows `supervision_state` OK.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic 17 (table at 2618-2624) and #Story 17.1 (2636-2664)]
- [Source: _bmad-output/planning-artifacts/architecture.md#ADR-22 (732-774), #ADR-06 note (184-185), #ADR-08 (204)]
- [Source: _bmad-output/planning-artifacts/sprint-change-proposal-2026-10-17-csr-profiles.md]
- [Source: internal-docs/ajax.md — captures A/B, "Modèle Ajax déduit des captures A et B"]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — D-42, D-86, D-115]

## Dev Agent Record

### Agent Model Used

Claude Opus 5.5 (eu.anthropic.claude-opus-5-5), 2026-10-17.

### Debug Log References

- Baseline measured on clean HEAD 737320f in a detached worktree: level1 1336 passed / 0 failed; level2 5 failed
  (4 × `test_connection_test_async.py::test_send_raw_once_*`, `test_supervision_loop_integration.py::test_update_info_commands_full_payload_healthy`);
  level2_5 1 failed (`test_ipc_integration.py::TestUpdateInfoCommands::test_update_info_commands_emits_info_update`).
- After: level1 1374 passed, 3 xfailed (the strict 17.4 `data-l2key` xfails), 0 failed; level2 380 passed, the same 5
  failures; level2_5 79 passed, the same 1 failure. No new failure.
- `pylint resources/siadc09d/`: no new message class. Only deltas: `R0902` on `CSRPreset` 13→16 attributes, and one
  more `C0413 wrong-import-position` in `siadc09d.py` (the presets import sits after the `sys.path` insert, like the
  module's other package imports).
- `php -l` clean on every PHP file under `core/` and `desktop/`.

### Completion Notes List

- **Task 1.** `presets.py`: `SupervisionFormat` Literal + `SUPERVISION_FORMATS`, `RP_INTERVAL_MIN_S`/`MAX_S`,
  `SENDER_CRC_FORMATS = ("hex",)`. Three fields appended after `reconnect_max_attempts`; `__post_init__` rejects a
  non-hex CRC, an unknown format, `none` + RP off, and RP on outside 60-86400 (inclusive). No other `CSRPreset(...)`
  builder needed changing.
- **Task 2.** `siadc09d.py`: `--supervision-format` (choices), `--rp-enabled`, `--rp-interval`, passed into
  `CSRPreset`. The construction is wrapped in `except ValueError`: one French line on stderr
  (`_preset_refusal_message()`, prefix `Configuration refusée : `), exit 1. Transport/reconnect/CRC `ValueError`s
  get the same treatment, with their technical detail after the French prefix. Subprocess test added to
  `test_daemon_startup_regressions.py` (that file had no subprocess pattern to reuse; it uses `sys.executable` +
  the minimum required args, no socket opened).
- **Task 3.** `deamon_start` always passes `--supervision-format` (escaped) and passes `--rp-enabled --rp-interval`
  only when `rp_enabled` is truthy. Guard 3e is factored into `siaDC09::periodicFrameConfigError()` (pure, public
  static) so a level-1 test runs it with the php CLI against `CSRPreset` over the same cases (same drift-proof
  pattern as `test_php_encryption_key_guard.py`). Bounds are class constants mirrored from Python, with a sync test.
  Guard 3d is skipped when `supervision_format === 'none'`. 6 new strings added to `fr_FR.json` (the 11-4 round-trip
  test required them); `en_US.json` not touched (partial by design).
- **Task 4.** `core/config/csr_presets.json` created (shape from Dev Notes). `siaDC09::getCsrProfiles()` logs at
  `error` and returns `[]` on a missing/unreadable file, invalid JSON, `schema_version !== 1` (strict int), or no
  `profiles` object; executed in tests against the real file and 5 broken variants. No caller until 17.4 (docblock).
- **Task 5.** `--crc-format` has `choices=["hex"]` (argparse exits 2 with its own usage line on `bin`; the PHP guard
  stops it first). `daemon.py` edit is the 3-line mapping only → `SIAMessageBuilder(crc_format="SIA")`; same in the
  connection-test path. `deamon_info()` Guard 3c' refuses a stored `crc_format` other than `hex` ("réenregistrez
  l'équipement"). Sender-side `bin` tests reworked (Fix #7 → "CSRPreset rejects bin" + "builder always SIA";
  `test_wizard_config_ipc.py` transport test now pins `hex`, the wizard-mapping test became a rejection test).
  Receiver-side tests untouched. ADR-06 note added in `architecture.md`.
- **Task 6.** `_PERIODIC_FRAME_KEYS` + `php_class` fixture + 3 parametrized tests (the `data-l2key` one
  `xfail(strict=True)`), plus the RP-bound sync test. No existing level-2 test pinned cadence with a real default
  preset (`test_supervision_queue_integration.py` swaps the preset for a MagicMock), so
  `tests/level2/test_supervision_default_preset.py` was added: defaults, loop sleeps exactly
  `supervision_interval_s`, frame still `"SIA-DCS"…[#001234|0000]`.
- **Not done here:** the deploy check on test-jeedom (log shows `--supervision-format 'sia-dcs'`, widget
  `supervision_state` OK). Code arrives by `git pull`, so it needs a commit + push first; nothing was committed.

### File List

- `core/class/siaDC09.class.php` (modified)
- `core/config/csr_presets.json` (new)
- `core/i18n/fr_FR.json` (modified)
- `resources/siadc09d/presets.py` (modified)
- `resources/siadc09d/siadc09d.py` (modified)
- `resources/siadc09d/daemon.py` (modified — builder CRC line only)
- `tests/level1/test_csr_preset_validation.py` (modified)
- `tests/level1/test_daemon_startup_regressions.py` (modified)
- `tests/level1/test_wizard_config_key_consistency.py` (modified)
- `tests/level1/test_csr_presets_json.py` (new)
- `tests/level1/test_php_periodic_frame_guard.py` (new)
- `tests/level2/test_supervision_default_preset.py` (new)
- `tests/level2_5/test_wizard_config_ipc.py` (modified)
- `_bmad-output/planning-artifacts/architecture.md` (ADR-06 note)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (17-1 → review)

## Review Triage Log

| # | Location | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | `tests/level2/test_supervision_default_preset.py` | Cadence test cannot tell `supervision_interval_s` from `rp_interval_s` | low | `make_daemon_preset()` sets `supervision_interval_s=60.0` and the new `rp_interval_s` default is also 60.0, so a loop switched to `rp_interval_s` still yields `[60.0, 60.0]`. 17.3 touches exactly this loop. | patch |
| 2 | `tests/level1/test_wizard_config_key_consistency.py` + `test_php_periodic_frame_guard.py::test_deamon_start_passes_periodic_frame_args` | AC6 "deamon_start reads it" checked against the whole class file | low | `deamon_info()` Guard 3e already reads all three keys, so the key test passes even if `deamon_start` stops reading them. The companion regexes stop at `escapeshellarg(` / `(int)` and never check the `supervision_format` / `rp_interval` key names. | patch |
| 3 | `core/class/siaDC09.class.php` `periodicFrameConfigError()` | RP bounds written as literals "60 et 86400" in the message | low | True, but the bounds are a spec-level choice unlikely to change, and the fix means a `sprintf` placeholder key plus an i18n change. Rejected: low, unlikely, fix is more than a direct correction. | reject |
| 4 | `resources/siadc09d/presets.py`, `siadc09d.py` | Bare default literals (`"sia-dcs"`, `60`/`60.0`) break `.claude/rules/python-style.md` "no magic numbers" | low | Confirmed at the dataclass defaults and the two `add_argument` defaults. PHP has `SUPERVISION_FORMAT_DEFAULT` / `RP_INTERVAL_DEFAULT_S`; Python has no named counterpart. The `"none"` literal is a member of the `SupervisionFormat` Literal, which the type checker enforces, so it is left as is. | patch |

## Change Log

| Date | Change |
|------|--------|
| 2026-10-17 | Story file created (backlog → ready-for-dev) from Epic 17 / ADR-22, grounded in code reading of presets.py, siadc09d.py, daemon.py, siaDC09.class.php and the key-consistency test. AC5 clarified: RP range checked only when RP is enabled. AC8 decision proposed (remove `bin` on the sender side), pending Herve. |
| 2026-10-17 | Herve approved both: `bin` removed from the sender side (AC8, Task 5 rewritten with the affected tests listed), and the RP range checked only when RP is on (AC7). Checked against the bmad-create-epics-and-stories final-validation criteria: requirement refs added (NFR7, NFR4, FR11 as amended). |
| 2026-10-17 | Dev: Tasks 1-6 implemented (in-progress → review). Guard 3e factored into `siaDC09::periodicFrameConfigError()` and executed against `CSRPreset` in a level-1 parity test; crc_format guard added to `deamon_info()`. No regression vs the re-measured baseline. Test-jeedom deploy check left open (needs a push). |
| 2026-10-17 | Quick review: 4 findings, 3 patched (cadence test now distinguishes `supervision_interval_s` from `rp_interval_s`; `deamon_start` key checks scoped to its body; named `SUPERVISION_FORMAT_DEFAULT` / `RP_INTERVAL_DEFAULT_S` in Python), 1 rejected (RP bounds literal in the PHP message). Suites re-run: level1 green, level2/level2_5 same baseline failures. Status → built. |
