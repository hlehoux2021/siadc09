---
story_id: "12-2"
story_key: "12-2-wizard-flow-connection-test"
epic_id: "epic-12"
epic_name: "Jeedom VM Integration Testing"
status: "ready-for-dev"
created: "2026-05-26"
analysis_completed: "2026-05-26"
---

# Story 12.2: Wizard Flow & Connection Test

Status: ready-for-dev

## Story

As a Jeedom user,
I want to complete the 4-step configuration wizard on a real Jeedom instance,
So that the plugin is configured and ready to monitor.

## Acceptance Criteria

1. **Given** plugin enabled and equipment page opened, **When** wizard starts (step < 4), **Then** Step 1 displays IMA Protect and Personnalisé preset cards.

2. **And** selecting "IMA Protect" auto-fills CSR parameters (host=127.0.0.1 for local simulator, port=10001, transport=udp).

3. **And** account number and encryption key fields are editable.

4. **And** Step 2 "Suivant" button triggers connection test: `test_connection.py` subprocess (via `siadc09d.py --test-only`) runs with configured params, sends supervision NULL to local CSR simulator, receives ACK → displays "✓ Connexion établie — ACK reçu en Xms".

5. **And** timeout/error → displays French error message with "Relancer le test" button.

6. **And** Step 3 displays zone mapping table: zones loaded from alarm plugin (if installed), camera action selector works, media URL field editable (optional).

7. **And** Step 4 notification command selector: modal opens, user selects a notification command, human-readable name displayed next to selector, cannot proceed without selection.

8. **And** wizard completion saves all config to equipment (`sia_wizard_step = 4`).

9. **And** after Step 4: Jeedom watchdog detects `state='nok', launchable='ok', auto=1` and starts daemon automatically within ~60s; supervision loop begins.

10. **And** "Relancer l'assistant" restarts wizard cleanly (resets to step 1 with saved values, does not clear config).

## Tasks / Subtasks

- [ ] Task 1: CSR Simulator Setup (prerequisite for all tests) (AC: 4, 5)
  - [ ] 1.1 Start CSR simulator on VM: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --account 000001` — verify "CSR Simulator running" logged
  - [ ] 1.2 Verify simulator listens on UDP port 10001: `ss -ulnp | grep 10001`
  - [ ] 1.3 Test raw connectivity: send a UDP packet from the VM to 127.0.0.1:10001 to confirm no firewall blocks

- [ ] Task 2: Step 1 — Preset selection (AC: 1, 2, 3)
  - [ ] 2.1 Navigate to equipment page → verify wizard mode displays (step < 4)
  - [ ] 2.2 Verify two cards visible: "IMA Protect" (blue highlight by default) and "Personnalisé"
  - [ ] 2.3 Verify IMA Protect selected: CSR fields auto-filled from `csr_presets.json` data-attributes — check IP, port, transport, encryption_enabled, supervision_interval, retry_count all populated
  - [ ] 2.4 Override IP to `127.0.0.1` and port to `10001` (for local simulator) — account_number and encryption_key are editable even in preset mode
  - [ ] 2.5 Fill account_number (e.g., `000001`) — matches simulator account
  - [ ] 2.6 Click "Suivant" → verify step 1 validation passes (no red errors)
  - [ ] 2.7 Verify wizard saves `sia_wizard_step=2` to eqLogic before advancing
  - [ ] 2.8 Test "Personnalisé" card: click → verify CSR fields become editable (no readonly), "Personnaliser" button hidden, `csr_provider` set to `manual`
  - [ ] 2.9 Test validation: empty account_number → red error; invalid port → red error; fix → advance works

- [ ] Task 3: Step 2 — Connection test (AC: 4, 5)
  - [ ] 3.1 Verify step 2 auto-triggers test on arrival (spinner + "Test en cours..." displayed)
  - [ ] 3.2 Verify CSR summary shows configured IP:port (transport) and account
  - [ ] 3.3 Verify AJAX calls `plugins/siaDC09/core/ajax/siaDC09.ajax.php` with `action=testConnection`
  - [ ] 3.4 Verify PHP spawns `siadc09d.py --test-only --timeout 15 --config '<json>'` with correct config
  - [ ] 3.5 With simulator running: verify green banner "ACK reçu en Xms" appears
  - [ ] 3.6 Verify "Suivant" button becomes enabled after success
  - [ ] 3.7 Click "Relancer le test" → verify test re-runs (spinner reappears, new result)
  - [ ] 3.8 Stop simulator, click "Relancer le test" → verify red banner "Pas de réponse" after ~15s timeout
  - [ ] 3.9 Verify "Suivant" disabled on timeout (exit 1)
  - [ ] 3.10 Verify "Ignorer" button advances to step 3 with yellow warning banner at top
  - [ ] 3.11 Restart simulator for subsequent tests

- [ ] Task 4: Step 3 — Zone mapping (AC: 6)
  - [ ] 4.1 Verify step 3 loads zones via `getZones` AJAX call
  - [ ] 4.2 If alarm plugin installed with zones: verify zone names appear as read-only rows
  - [ ] 4.3 If alarm plugin not installed or no zones: verify warning "Aucune zone détectée" displayed + "Suivant" still available
  - [ ] 4.4 Verify camera action dropdown populated via `getCameraCommands` AJAX (CAMERA_TAKE generic type)
  - [ ] 4.5 Verify media URL dropdown populated (CAMERA_URL generic type)
  - [ ] 4.6 Select a camera for one zone, leave others empty — verify "Suivant" works with partial mapping
  - [ ] 4.7 Click "Suivant" → verify `sia_zone_mappings` saved to eqLogic configuration as JSON array

- [ ] Task 5: Step 4 — Notification command (AC: 7, 8)
  - [ ] 5.1 Verify step 4 shows notification command picker
  - [ ] 5.2 Click search button → verify `jeedom.cmd.getSelectModal({cmd: {type: 'action', subType: 'message'}})` opens
  - [ ] 5.3 Select a notification command (e.g., a message/push command) → verify human-readable name displayed in input
  - [ ] 5.4 Verify "Terminer" button blocked (error shown) if no command selected
  - [ ] 5.5 With command selected, click "Terminer" → verify `sia_wizard_step=4` saved
  - [ ] 5.6 Verify page reloads in config mode (summary view with connection/zones/notification sections)

- [ ] Task 6: Post-wizard daemon auto-start (AC: 9)
  - [ ] 6.1 After wizard completion, verify `deamon_info()` returns `launchable='ok'` (all guards pass)
  - [ ] 6.2 Wait up to 60s for Jeedom watchdog to detect `state='nok', launchable='ok', auto=1` and call `deamon_start()`
  - [ ] 6.3 Verify daemon process starts: `ps aux | grep siadc09d`
  - [ ] 6.4 Verify supervision loop begins: first NULL sent to simulator, ACK received
  - [ ] 6.5 Verify `supervision_state` command updates to 2 ("Sain")
  - [ ] 6.6 Check daemon log (`siaDC09_daemon`) for startup entries

- [ ] Task 7: Restart wizard flow (AC: 10)
  - [ ] 7.1 With daemon running, click "Relancer l'assistant"
  - [ ] 7.2 Verify confirmation dialog: "Le démon est en cours d'exécution. Il sera arrêté. Continuer ?"
  - [ ] 7.3 Confirm → verify `sia_wizard_step=0` saved first, then wizard reloads at step 1
  - [ ] 7.4 Verify previous config values are preserved (fields pre-filled with saved values)
  - [ ] 7.5 Verify daemon stopped (no process running)
  - [ ] 7.6 Complete wizard again to step 4 → verify clean completion and daemon restarts

## Dev Notes

### This is a MANUAL TESTING story — no code to write

This story validates that the existing wizard code works correctly on a real Jeedom instance. The dev agent's role is to:
1. Set up the CSR simulator on the VM
2. Execute the validation checklist step by step through the Jeedom UI
3. Document results (pass/fail with observations)
4. File bugs or fix issues discovered during validation

### Infrastructure (from Story 12-1)

| Component | Location | Notes |
|-----------|----------|-------|
| Jeedom | `/var/www/html/` on Debian 12 VM | Plugin at `plugins/siaDC09` via bind mount |
| Plugin source | `/mnt/hgfs/my-project` | Host shared folder (VMware) |
| CSR Simulator | Same VM, localhost:10001 (UDP) | `python3 -m tests.simulator --udp-port 10001` |
| Daemon venv | `resources/python_venv/` | Created by Jeedom dep manager (Story 12-1) |

### Key Prerequisite: IMA Protect Preset Override

The IMA Protect preset in `csr_presets.json` contains the real IMA Protect server IP. For local testing, you MUST override the IP and port fields in the wizard UI to point to the local simulator (`127.0.0.1:10001`). The account_number field is always editable — use `000001` to match the simulator default.

### Connection Test Flow (what happens under the hood)

1. JS calls `plugins/siaDC09/core/ajax/siaDC09.ajax.php` with `action=testConnection`
2. PHP reads eqLogic config, strips `encryption_key` into env var `SIA_ENCRYPTION_KEY`
3. PHP spawns: `<python3> siadc09d.py --test-only --timeout 15 --config '<json>'`
4. Python (`run_connection_test()`) reads config, builds NULL frame, sends to CSR via `_send_raw_once()`
5. Returns JSON: `{"status": "ok", "detail": "ACK reçu en 5ms"}` or `{"status": "fail", ...}`
6. PHP returns result to JS → JS shows colored banner

### Expected test_connection behavior with local simulator

- Simulator default: responds ACK to any valid NULL frame
- Encryption disabled for simplicity: IMA Protect preset has `encryption_enabled=true` but local simulator may not have the key configured. Either: (a) disable encryption in wizard, or (b) configure simulator with matching key via `--encryption-key`
- Recommended approach: use "Personnalisé" mode or override IMA Protect fields — set `encryption_enabled` unchecked for first test, then test encrypted path separately

### Daemon Auto-Start Mechanism

After wizard completion (`sia_wizard_step=4`), the daemon is NOT started by the wizard JS code. Instead:
- `deamon_info()` guard chain now passes (equipment exists, wizard_step=4, CSR IP/port set, transport valid)
- Jeedom's runtime watchdog (runs every ~60s) sees `state='nok', launchable='ok', auto=1`
- Watchdog calls `deamon_start()` automatically
- User does NOT need to click "Start" manually

### Key Files

| File | Role |
|------|------|
| `desktop/php/siaDC09.php` | Wizard HTML (steps 1-4 + config mode) |
| `desktop/js/siaDC09.js` | Wizard navigation, validation, AJAX calls |
| `core/ajax/siaDC09.ajax.php` | AJAX endpoints: testConnection, getZones, getCameraCommands |
| `resources/siadc09d/siadc09d.py` | `--test-only` entry point for connection test |
| `resources/siadc09d/csr_presets.json` | IMA Protect preset values |
| `core/class/siaDC09.class.php` | `deamon_info()` guard chain, `deamon_start()` |

### Previous Story Intelligence (12-1)

Key learnings from Story 12-1 that apply here:
- **Bind mount, not symlink**: Plugin files are at `/var/www/html/plugins/siaDC09` via `mount --bind` (not symlink — symlinks break `__DIR__` resolution)
- **Python3 path**: Jeedom resolves via `system::getCmdPython3('siaDC09')` → `resources/python_venv/bin/python3`
- **Venv directory**: Jeedom uses `python_venv/` not `venv/`
- **deamon_info guard**: Before wizard completion, returns `launchable='nok'` with message about incomplete wizard. After step 4, all guards should pass.
- **7 commands created**: burglarAlarm, fireAlarm, panicAlarm, supervision_state, supervision_label, event_state, event_label — all present from auto-equipment creation

### What NOT To Do

- Do NOT modify `csr_presets.json` to change IMA Protect IP for testing — override in the wizard UI
- Do NOT start the daemon manually before completing the wizard — let the watchdog handle it
- Do NOT test encrypted connection without configuring the simulator with the same key
- Do NOT skip checking the Jeedom log after each step — PHP errors may be silent in UI
- Do NOT assume the alarm plugin is installed — test both paths (zones found / no zones)

### References

- [Source: docs/design/wizard-design.md] — Full wizard design spec (steps, validation, data flow)
- [Source: desktop/php/siaDC09.php] — Wizard HTML implementation
- [Source: desktop/js/siaDC09.js] — Wizard JS logic
- [Source: core/ajax/siaDC09.ajax.php] — AJAX endpoints (testConnection, getZones, getCameraCommands)
- [Source: resources/siadc09d/siadc09d.py:98-188] — `run_connection_test()` and `_send_raw_once()`
- [Source: tests/simulator/__main__.py] — CSR Simulator CLI (`python3 -m tests.simulator`)
- [Source: core/class/siaDC09.class.php:60-120] — `deamon_info()` guard chain

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

| Date | Change |
|------|--------|
| 2026-05-26 | Story created — ready for VM integration testing |
