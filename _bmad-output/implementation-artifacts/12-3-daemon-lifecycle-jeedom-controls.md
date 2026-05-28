---
story_id: "12-3"
story_key: "12-3-daemon-lifecycle-jeedom-controls"
epic_id: "epic-12"
epic_name: "Jeedom VM Integration Testing"
status: "ready-for-dev"
created: "2026-05-27"
analysis_completed: "2026-05-27"
---

# Story 12.3: Daemon Lifecycle & Jeedom Controls

Status: ready-for-dev

## Story

As a Jeedom administrator,
I want the daemon to start, stop, and restart reliably via Jeedom UI,
So that I can manage the monitoring service without SSH access.

## Acceptance Criteria

1. **Given** daemon is running (green status in Jeedom), **When** clicking "Stop" in daemon management panel, **Then** daemon process terminates cleanly (no orphan processes) and `supervision_state` updates to 0 ("ARRÊTÉ").

2. **And** clicking "Start" relaunches daemon: process visible in `ps aux | grep siadc09`, supervision loop begins immediately, `supervision_state` → 2 ("Sain") after first ACK within 60s.

3. **And** clicking "Restart" performs stop + start atomically — same result as manual stop then start.

4. **And** Jeedom watchdog recovery: kill daemon process with `kill -9 <pid>` → Jeedom detects daemon death within ~60s watchdog interval → automatically restarts daemon → `supervision_state` recovers to 2 after restart.

5. **And** config change behavior: change a config value (e.g., `supervision_interval`) → save equipment → `postSave()` restarts daemon with new config → verify new config active (changed interval visible in logs or supervision timing).

6. **And** daemon log accessible via Jeedom UI (Analyse → Logs → `siaDC09_daemon`) — log entries visible and filterable.

7. **And** no zombie processes after repeated start/stop cycles (10+ cycles) — `ps aux | grep siadc09` shows at most one process after final start.

## Tasks / Subtasks

- [ ] Task 1: Start/Stop/Restart via Jeedom UI (AC: 1, 2, 3)
  - [ ] 1.1 Navigate to Plugins → Plugin Management → siaDC09 plugin config page (or use Jeedom daemon panel)
  - [ ] 1.2 With daemon already running (from Story 12-2), click "Stop" → verify daemon terminates within 5s: `ps aux | grep siadc09` shows no process
  - [ ] 1.3 Verify `supervision_state` command value changes to 0 and `supervision_label` = "ARRÊTÉ" — check in Jeedom equipment page or `cmd::byLogicalId('supervision_state')` via AJAX
  - [ ] 1.4 Click "Start" → verify daemon process appears within 10s: `ps aux | grep siadc09` shows `siadc09d.py` with correct args
  - [ ] 1.5 Verify supervision loop starts: check Jeedom equipment page — `supervision_state` → 1 ("DÉMARRAGE…") immediately, then → 2 ("Sain") after first ACK (within 60s max, typically <5s with local simulator)
  - [ ] 1.6 Check Jeedom daemon log (`siaDC09_daemon`) for startup line: "Démarrage démon siaDC09"
  - [ ] 1.7 Click "Restart" button → verify stop + start occurs atomically (process restarts, `supervision_state` cycles 0→1→2)
  - [ ] 1.8 Verify daemon PID changes after restart (new process, not same PID) — `cat /tmp/jeedom/siaDC09/daemon.pid` before and after

- [ ] Task 2: Watchdog recovery from kill -9 (AC: 4)
  - [ ] 2.1 Get current daemon PID: `cat /tmp/jeedom/siaDC09/daemon.pid`
  - [ ] 2.2 Kill daemon forcefully: `sudo kill -9 <pid>`
  - [ ] 2.3 Verify process is dead: `ps aux | grep siadc09` shows no process
  - [ ] 2.4 Wait up to 90s for Jeedom watchdog (runs every ~60s) to detect `state='nok'` and call `deamon_start()` automatically
  - [ ] 2.5 Verify daemon restarts automatically — no manual intervention
  - [ ] 2.6 Verify `supervision_state` recovers to 2 ("Sain") after watchdog restart
  - [ ] 2.7 Check Jeedom log (`siaDC09`) for watchdog restart message (Jeedom core writes "Démon du plugin XXX redémarré" style message)
  - [ ] 2.8 Verify Jeedom failure counter reset — no "Impossible de lancer le démon" in message center after single kill

- [ ] Task 3: Config change triggers daemon restart (AC: 5)
  - [ ] 3.1 Note current `supervision_interval` value (default 60s) — visible in config mode (wizard step=4)
  - [ ] 3.2 Change `supervision_interval` to a different value (e.g., 30) in plugin config page
  - [ ] 3.3 Save equipment (click "Save") → verify `postSave()` is called
  - [ ] 3.4 Verify daemon restarts: PID changes; check `siaDC09_daemon` log for restart entries
  - [ ] 3.5 Verify new `supervision_interval` is passed to daemon via CLI arg: check `siaDC09` log for the launch command line (`Lancement démon: ... --supervision-interval 30`)
  - [ ] 3.6 Restore `supervision_interval` to 60 and save (to avoid affecting subsequent stories)
  - [ ] 3.7 **Note:** `postSave()` calls `deamon_stop()` then `deamon_start()` only when daemon is running — if daemon was stopped before save, it stays stopped; Jeedom watchdog handles restart

- [ ] Task 4: Daemon log accessibility (AC: 6)
  - [ ] 4.1 With daemon running, navigate to Analyse → Logs in Jeedom UI
  - [ ] 4.2 Verify log `siaDC09_daemon` appears in the log list
  - [ ] 4.3 Open log — verify Python daemon startup messages are visible (level=info: "Démarrage démon siaDC09", "Démon prêt — supervision initiale planifiée")
  - [ ] 4.4 Verify loglevel=error mode (default from Story 12-2 config) shows no log entries unless errors occur
  - [ ] 4.5 Change log level to "debug" via Jeedom plugin config → restart daemon → verify verbose Python logs appear (supervision NULL send/ACK cycle)
  - [ ] 4.6 Reset log level to "error" for subsequent stories

- [ ] Task 5: No zombie processes after 10+ cycles (AC: 7)
  - [ ] 5.1 Write a quick test loop — stop and start daemon 10 times via Jeedom UI (or directly via CLI simulation):
    ```bash
    for i in $(seq 1 10); do
      php -r "require '/var/www/html/core/php/core.inc.php'; siaDC09::deamon_stop(); sleep(2); siaDC09::deamon_start(); sleep(3);"
    done
    ```
  - [ ] 5.2 After 10 cycles, verify `ps aux | grep siadc09` shows exactly one process
  - [ ] 5.3 Verify no defunct/zombie processes: `ps aux | grep Z` shows no siaDC09-related zombies
  - [ ] 5.4 Check `/tmp/jeedom/siaDC09/daemon.pid` contains a valid PID matching the running process
  - [ ] 5.5 Verify `supervision_state=2` after final start (daemon in HEALTHY state)

## Dev Notes

### This is a MANUAL TESTING story — no code to write (unless bugs found)

This story validates that the existing daemon lifecycle controls work correctly on the real Jeedom instance from Story 12-2. The dev agent's role is to:
1. Execute the validation checklist step by step
2. Observe actual behavior and compare against expected
3. Document results (pass/fail with observations)
4. File bug fixes inline if issues are found during testing

### Infrastructure (from Stories 12-1 and 12-2)

| Component | Location | Notes |
|-----------|----------|-------|
| Jeedom | `/var/www/html/` on Debian 12 VM | Plugin at `plugins/siaDC09` via bind mount |
| Plugin source | `/mnt/hgfs/my-project` | Host shared folder (VMware) |
| CSR Simulator | Same VM, localhost:10001 (UDP) | `python3 -m tests.simulator --udp-port 10001 --account 000001` |
| Daemon venv | `resources/python_venv/` | Created by Jeedom dep manager (Story 12-1) |
| Plugin config state | `sia_wizard_step=4` | Wizard complete from Story 12-2 |
| PID file | `/tmp/jeedom/siaDC09/daemon.pid` | Written by daemon at startup |

**Important:** CSR simulator must be running for supervision ACKs to succeed. Start it before Task 1: `python3 -m tests.simulator --udp-port 10001 --account 000001`

### Daemon Lifecycle — How It Works

**Start (`deamon_start()`):** `core/class/siaDC09.class.php:171`
1. Calls `deamon_stop()` first (ensures no leftover process)
2. Reads eqLogic config, builds CLI args (host, port, transport, account, crc-format, encryption, supervision-interval, retry-count, notify-cmd-id)
3. Executes: `<python3_venv> siadc09d.py <args> >> <daemon_log> 2>&1 &`
4. Polls `deamon_info()['state']` up to 10s waiting for PID file to appear
5. Returns `false` and logs error if daemon doesn't start within 10s

**Stop (`deamon_stop()`):** `core/class/siaDC09.class.php:248`
1. Reads PID from `/tmp/jeedom/siaDC09/daemon.pid` → `system::kill($pid)` (sends SIGTERM)
2. `sleep(1)` → `system::kill('siadc09d.py')` (kill any lingering processes by name)
3. `sleep(1)` — total 2s guaranteed wait

**On SIGTERM:** `jeedomdaemon` base class catches SIGTERM, calls our `on_stop()` which:
1. Sends `{type: info_update, supervision_state: 0, supervision_label: 'ARRÊTÉ'}` to PHP
2. Drains PriorityQueue
3. Cancels all tracked asyncio tasks (5s hard timeout)
4. Exits cleanly

**Watchdog (`deamon_info()`):** Returns `state='ok'` if PID file exists and process is alive (`posix_getsid()`). Returns `launchable='ok'` if all 6 guards pass (equipment, wizard_step≥4, csr_ip, csr_port, transport, supervision_interval, account_number format, encryption_key if enabled, notify_cmd_id).

**Jeedom built-in watchdog:** Runs every ~60s. Calls `deamon_info()`. If `state='nok' AND auto=1 AND launchable='ok'` → calls `deamon_start()`. After 3 consecutive failures → writes to Jeedom message center and stops retrying.

**postSave():** `core/class/siaDC09.class.php:529` — saves equipment + commands. When daemon is running, calls `deamon_stop()` then `deamon_start()` to apply new config. This is the intended config-change restart path.

### Key Config Keys Used by deamon_start()

| eqLogic config key | CLI arg | Notes |
|--------------------|---------|-------|
| `csr_ip` | `--host` | Required — Guard 3 |
| `csr_port` | `--port` | Required — Guard 3b |
| `transport` | `--transport` | `udp` or `tcp` — Guard 3c |
| `account_number` | `--account` | 3–16 hex chars — Guard 4 |
| `crc_format` | `--crc-format` | Default `hex` |
| `encryption_enabled` | `--encryption-enabled` | Flag, bool |
| `encryption_key` | `--encryption-key` | Via env var `SIA_ENCRYPTION_KEY` in PHP |
| `supervision_interval` | `--supervision-interval` | Default 60 |
| `retry_count` | `--retry-count` | Default 3 |
| `sia_notify_cmd_id` | `--notify-cmd-id` | Required — Guard 6 |
| `receiver_prefix` | `--receiver-prefix` | Optional |
| `account_prefix` | `--account-prefix` | Optional |

**Note:** The design doc uses `notify_cmd_id` but the implemented code uses `sia_notify_cmd_id` (with `sia_` prefix) — use the implemented config key.

### supervision_state INFO Command Behavior

| Daemon state | `supervision_state` value | `supervision_label` string |
|---|---|---|
| INITIALIZING (startup) | 1 | `DÉMARRAGE…` |
| HEALTHY (ACK received) | 2 | `OK` |
| DEGRADED strike 1–2 | 1 | `DÉGRADÉ (N/3)` |
| DEGRADED strike 3 | 0 | `PERDUE` |
| STOPPED (on_stop() fired) | 0 | `ARRÊTÉ` |

The `supervision_state` value is pushed by the daemon via `send_to_jeedom()` callback → `jeesiaDC09.php` → `checkAndUpdateCmd()`.

### Verifying supervision_state in Jeedom

From the Jeedom UI:
- Equipment page (config mode, step=4) shows current `supervision_state` value
- Jeedom → Analyse → Historique: select `supervision_state` command to see value history

From CLI (as www-data or with access to Jeedom PHP):
```bash
php -r "
require '/var/www/html/core/php/core.inc.php';
\$eqLogic = siaDC09::byType('siaDC09')[0];
\$cmd = \$eqLogic->getCmd('info', 'supervision_state');
echo 'value=' . \$cmd->execCmd() . ' collectDate=' . \$cmd->getCollectDate() . PHP_EOL;
"
```

### postSave() Restart Behavior

`postSave()` at line 529 saves commands and, if daemon is currently running, restarts it:
```php
// (simplified)
if (self::isConnect()) {
    self::deamon_stop();
    self::deamon_start();
}
```
`isConnect()` checks `launchable='ok' AND state='ok'` — so a save while daemon is stopped does NOT start the daemon (watchdog handles it later).

### What NOT To Do

- Do NOT test with daemon stopped and wizard_step < 4 — re-run wizard if needed (config preserved)
- Do NOT kill daemon with SIGKILL (`kill -9`) to test normal stop behavior — use Jeedom UI "Stop" button (sends SIGTERM via `system::kill()`)
- Do NOT test zombie detection (cron5 + freshness check) in this story — that belongs to Story 12-4 (supervision loop & strike recovery)
- Do NOT change `csr_ip` or `account_number` during Task 3 — only change `supervision_interval` to avoid breaking the connection test

### References

- [Source: core/class/siaDC09.class.php:60–270] — `deamon_info()`, `deamon_start()`, `deamon_stop()`, `cron5()`, `_checkSupervisionFreshness()`, `isConnect()`
- [Source: core/class/siaDC09.class.php:529] — `postSave()` daemon restart on config change
- [Source: docs/design/supervision-design.md] — SM1 state→supervision_state mapping table, watchdog mechanism, Group A lifecycle tasks
- [Source: docs/design/supervision-design.md#Task A.1] — `on_start()` code: pushes INITIALIZING, starts tasks, enqueues first supervision
- [Source: docs/design/supervision-design.md#Task A.2] — `on_stop()` code: pushes STOPPED, drains queue, cancels tasks
- [Source: docs/design/supervision-design.md#Task C.2] — `deamon_info()` guard chain (6 guards)
- [Source: docs/design/supervision-design.md#Task C.3] — `cron5()` — freshness check only (no restart logic)
- [Source: _bmad-output/implementation-artifacts/12-2-wizard-flow-connection-test.md] — prior story infrastructure, bugs fixed, daemon auto-start confirmation
- [Source: _bmad-output/implementation-artifacts/12-1-manual-plugin-installation-dependency-setup.md] — VM infrastructure, bind mount, venv location

### Previous Story Intelligence (12-2)

Key learnings from Story 12-2 that apply here:
- **Bind mount**: Plugin files at `/var/www/html/plugins/siaDC09` via `mount --bind /mnt/hgfs/my-project /var/www/html/plugins/siaDC09` — NOT a symlink
- **Python3 path**: Resolved via `system::getCmdPython3('siaDC09')` → `resources/python_venv/bin/python3`
- **deamon_info() state** shows `nok` when checked as non-www-data shell user — not a bug; PHP always runs as www-data
- **Wizard restart race fix**: `sia_wizard_step=0` is saved BEFORE `deamon_stop()` — ensures `launchable=nok` is set atomically, preventing watchdog from restarting daemon mid-wizard
- **notify_cmd_id**: Story 12-2 used stub `notify_cmd_id=999` (no real notification command on VM) — this is fine for lifecycle testing; Task 3/4/5 do not require the notification to actually fire

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (eu.anthropic.claude-sonnet-4-6)

### Debug Log References

### Completion Notes List

### File List
