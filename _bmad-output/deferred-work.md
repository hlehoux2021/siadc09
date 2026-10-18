- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: Legacy equipment may show stale rp_enabled/supervision_interval values if Jeedom setValues skips absent keys (unverified, medium).
  evidence: printEqLogic only defaults supervision_format and rp_interval; settle by opening a legacy equipment after another in the test-jeedom UI run.
- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: wizard-design.md testConnection code sample (~line 1040) still resolves the removed csr_provider / IMA preset.
  evidence: outside step 1; left stale by the 17-4 rewrite, pre-existing.

## Deferred from: code review of 17-csr-profile-model-and-php-daemon-plumbing (2026-10-18)

- Test-jeedom deploy check for 17-1 (AC5/AC9) never run on the live host: command line must show `--supervision-format 'sia-dcs'`, supervision_state OK, Guard 3e message. Needs a push and a UI run.
- No test cross-checks the command line `deamon_start` builds against the argparse parser (`--supervision-format`, `--rp-enabled`, `--rp-interval`); a misspelled flag would exit 2 although `deamon_info` allowed launch. Fits 17-2/17-3.
