- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: Legacy equipment may show stale rp_enabled/supervision_interval values if Jeedom setValues skips absent keys (unverified, medium).
  evidence: printEqLogic only defaults supervision_format and rp_interval; settle by opening a legacy equipment after another in the test-jeedom UI run.
- source_plan: `_bmad-output/plan-17-4-wizard-profile-choice-and-advanced-options.md`
  summary: wizard-design.md testConnection code sample (~line 1040) still resolves the removed csr_provider / IMA preset.
  evidence: outside step 1; left stale by the 17-4 rewrite, pre-existing.
