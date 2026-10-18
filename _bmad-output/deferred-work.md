- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: RESOLVED 2026-10-18 (not applicable) — stale rp_enabled/supervision_interval on legacy equipment.
  evidence: the plugin has a single auto-equipment, so values cannot carry over between equipments; a reloaded page starts blank and printEqLogic defaults format and rp_interval. Not reproducible by design.
- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: wizard-design.md testConnection code sample (~line 1040) still resolves the removed csr_provider / IMA preset.
  evidence: outside step 1; left stale by the 17-4 rewrite, pre-existing.

## Deferred from: code review of 17-csr-profile-model-and-php-daemon-plumbing (2026-10-18)

- Test-jeedom deploy check for 17-1 (AC5/AC9) never run on the live host: command line must show `--supervision-format 'sia-dcs'`, supervision_state OK, Guard 3e message. Needs a push and a UI run.
- No test cross-checks the command line `deamon_start` builds against the argparse parser (`--supervision-format`, `--rp-enabled`, `--rp-interval`); a misspelled flag would exit 2 although `deamon_info` allowed launch. Fits 17-2/17-3.
- RESOLVED 2026-10-18: misleading supervision NAK wording (found in the 17-5 field run; now "trame refusée par la centrale"): after the NAK re-sends the daemon logs "NAK supervision (strike 1/3) — horodatage rejeté par la centrale", but a bare NAK carries no reason. ioBroker.sia NAKed `"NULL"0000L0#001234[]` with `Incorrect format of data message` (its parser rejects an empty data block), not a timestamp problem. Reword to a neutral "frame refused by the CSR" (and keep the timestamp hint only when the NAK is known to be about it).
