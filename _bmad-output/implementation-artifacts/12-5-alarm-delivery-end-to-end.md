---
story_id: "12-5"
story_key: "12-5-alarm-delivery-end-to-end"
epic_id: "epic-12"
epic_name: "Jeedom VM Integration Testing"
status: "done"
created: "2026-05-29"
analysis_completed: "2026-05-29"
---

# Story 12.5: Alarm Delivery End-to-End

Status: done

## Story

As a Jeedom user with an alarm system,
I want alarm events delivered to the CSR and confirmed,
So that my home is protected by professional monitoring.

## Acceptance Criteria

1. **Happy path — burglarAlarm ACK:** Given daemon in HEALTHY state, when triggering `burglarAlarm` action command with zone="Piece1", then daemon receives the action via `sendToDaemon()`; SIA frame with BA event code is sent to CSR simulator; simulator ACKs; `event_state` → 1 (`"Confirmé"`); `event_label` → `"Confirmé"`; ring buffer has an alarm dialog entry (`dialog_type: "alarm"`).

2. **All event types — ACK path:** Same happy-path flow for `fireAlarm` (FA code) and `panicAlarm` (PA code).

3. **Zone handling:** Triggering alarm with zone="Piece1" → zone appears in SIA frame visible in protocol inspector. Triggering without zone (empty title) → frame still valid, zone field null/empty, no crash.

4. **NAK path — T2 notification:** Given CSR simulator replaced with a custom NAK responder (mismatch account or key), when triggering `burglarAlarm` with zone="Piece1", then `event_state` → 2 (`"Échoué"`); T2 `BAD_CSR_RESPONSE` notification fires (message center entry + notification command triggered, **no** "CRITIQUE" prefix); daemon does NOT retry after NAK (immediate failure).

5. **Timeout path — T3 notification:** Given CSR simulator stopped (silent drop), when triggering `burglarAlarm` with zone="Piece2", then daemon retries up to 3 times with 1s backoff; after max retries exhausted, `event_state` → 2 (`"Échoué"`); T3 `EVENT_FAILED` fires: message center entry with `"CRITIQUE —"` prefix + notification command triggered.

6. **Ring buffer alarm entry:** After each alarm attempt (ACK or FAIL), ring buffer contains an alarm dialog entry viewable in the protocol inspector (`dialog_type: "alarm"`).

7. **event_state persists across restart:** After a CONFIRMED alarm, stop and restart daemon; `event_state` still shows 1 (`"Confirmé"`) — not reset to 0 (IDLE is startup-only, not re-entered).

8. **TCP — alarm happy path (burglarAlarm ACK):** Given daemon configured with TCP transport and local TCP simulator, when triggering `burglarAlarm` with zone="Piece1", then `event_state` → 1 (`"Confirmé"`) after ACK received over TCP. Daemon log shows BA frame sent and ACK received via TCP.

9. **TCP — all event types ACK path:** Same TCP happy path confirmed for `fireAlarm` (FA code) and `panicAlarm` (PA code).

10. **TCP — NAK path (T2 BAD_CSR_RESPONSE):** Same as AC4 but over TCP: `event_state=2`, T2 fires with no CRITIQUE prefix, no retry. Daemon immediately marks SM2 FAILED on NAK over TCP.

11. **TCP — timeout path (T3 EVENT_FAILED):** Same as AC5 but over TCP: simulator stopped → TCP connection refused → daemon retries up to 3 times → EVENT_FAILED T3 fires with "CRITIQUE —" prefix. Daemon log shows 3 retry attempts over TCP.

## Pass/Fail Protocol

For each "Verify" step:
- **PASS:** Observed value matches expected → note observation, continue.
- **FAIL:** Mismatch → stop. Document observed vs. expected, check daemon log `tail -50 /var/www/html/log/siaDC09_daemon` and PHP log `tail -50 /var/www/html/log/siaDC09`, file bug in Dev Agent Record, then assess whether remaining tasks are still meaningful.
- **BLOCKED:** Precondition from prior task not met → skip task, note as BLOCKED with reason.

## Tasks / Subtasks

- [x] Task 0: Wire alarm plugin outbreak to siaDC09 burglarAlarm command (prerequisite)
  - [x] 0.1 In Jeedom UI → alarm plugin "Alarme" equipment → "Déclenchement" tab → "outbreak" action (currently `message`): add a siaDC09 `burglarAlarm` action with title set to `#name_zone#` (zone macro) alongside the existing message action.
        This makes real Detecteur1/2 triggers call the full chain automatically.
  - [x] 0.2 Verify the outbreak action list now shows both the message action and the burglarAlarm action.
  - [x] 0.3 Note: Tasks 2–7 can also be triggered directly via PHP CLI (no alarm plugin needed), which is faster and more reliable for systematic testing. Use the alarm plugin trigger only for the full integration variant (subtask 2.7).

- [x] Task 1: Prepare test environment (AC: all)
  - [x] 1.1 Verify daemon is running and HEALTHY (`supervision_state=2`): via PHP CLI or Jeedom UI
  - [x] 1.2 Verify CSR simulator is running: `pgrep -f "tests.simulator"` → if not: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &`
  - [x] 1.3 Confirm wizard config: `sia_wizard_step=4`, account `000001`, `sia_notify_cmd_id` set to a real notification command — **cmd id=29** (`Notify` action on `Notification` equipment)
  - [x] 1.4 Set daemon log level to DEBUG via Jeedom UI (Plugins → siaDC09 → log level → "Debug" → save → restart daemon)
  - [x] 1.5 Clear ring buffer and error state: via Jeedom diagnostic tab "Vider" buttons, or PHP CLI: `config::save('sia_last_messages','[]','siaDC09'); config::save('sia_last_errors','[]','siaDC09');`
  - [x] 1.6 Note initial `event_state` value (likely 0 or last value from Story 12-4)

- [x] Task 2: Happy path — burglarAlarm with zone (AC: 1, 3, 6)
  - [x] 2.1 Trigger `burglarAlarm` action command with zone="Piece1" via PHP CLI:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$cmd = \$eq->getCmd('action', 'burglarAlarm');
        \$cmd->execCmd(['title' => 'Piece1']);
        echo 'done' . PHP_EOL;
        "
        ```
  - [x] 2.2 Verify `event_state` → 3 (`"En cours"`) immediately, then → 1 (`"Confirmé"`) after ACK (should take <1s with local simulator): PASS
  - [x] 2.3 Verify `event_label` → `"Confirmé"`: PASS
  - [x] 2.4 Check daemon log for BA frame sent and ACK received: PASS — `SM2 confirmed: zone=Piece1, sia=BA`
  - [x] 2.5 Check ring buffer has alarm entry (`dialog_type: "alarm"`): PASS (verified in Story 12-4 session)
  - [x] 2.6 Open protocol inspector in Jeedom diagnostic tab → expand alarm frame → verify zone="Piece1" appears in field breakdown: PASS
  - [x] 2.7 Full integration test via real alarm trigger: PASS — alarm plugin outbreak fixed (zone array added to mode config), burglarAlarm fires with zone="Piece1", event_state=1

- [x] Task 3: All event types — ACK path (AC: 2)
  - [x] 3.1 Trigger `fireAlarm` with zone="Piece1": verify `event_state`→1, `event_label`→`"Confirmé"`, FA code in daemon log: PASS
  - [x] 3.2 Trigger `panicAlarm` with zone="Piece2": verify `event_state`→1, `event_label`→`"Confirmé"`, PA code in daemon log: PASS

- [x] Task 4: Zone handling edge case (AC: 3)
  - [x] 4.1 Trigger `burglarAlarm` with empty title (no zone): `$cmd->execCmd(['title' => ''])` → verify daemon does NOT crash, frame sent, ACK received, `event_state`→1: PASS
  - [x] 4.2 Confirm daemon log shows `zone=None` (not an error): PASS — `on_message: cmd=burglarAlarm → sia_code=BA, zone=None`

- [x] Task 5: NAK path — T2 BAD_CSR_RESPONSE (AC: 4)
  - [x] 5.1 Stop normal simulator: `pkill -f "tests.simulator"`
  - [x] 5.2 Start simulator with mismatched account to trigger NAK:
        ```bash
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account FFFFFF &
        ```
        (daemon uses account 000001 → mismatch → simulator NAKs)
  - [x] 5.3 Trigger `burglarAlarm` with zone="Piece1" (PHP CLI as in Task 2.1)
  - [x] 5.4 Verify `event_state` → 2 (`"Échoué"`) quickly (no retry on NAK — immediate failure): PASS
  - [x] 5.5 Verify T2 in message center (no "CRITIQUE —" prefix): PASS — `[bad_csr_response] La centrale a renvoyé une réponse...` (no CRITIQUE prefix)
  - [x] 5.6 Verify notification command was triggered: PASS — daemon log shows `type: notify` dispatch
  - [x] 5.7 Verify **no retry** in daemon log (NAK → immediate SM2 FAILED, not 3 retries): PASS — `attempt=1` only in log
  - [x] 5.8 Restore simulator with correct account
  - [x] 5.9 Wait for supervision recovery: `supervision_state`→2: PASS

- [x] Task 6: Timeout path — T3 EVENT_FAILED (AC: 5)
  - [x] 6.1 Stop CSR simulator: `pkill -f "tests.simulator"` (silent drop → timeout on alarm frames)
  - [x] 6.2 Trigger `burglarAlarm` with zone="Piece2" (PHP CLI as in Task 2.1)
  - [x] 6.3 Wait for 3 retries + timeouts (each attempt = `receive_timeout_s` + 1s backoff; default ~10s per attempt → ~35s total)
  - [x] 6.4 Verify `event_state` → 2 (`"Échoué"`) after max retries: PASS — ConnectionRefusedError retried 3× then T3
  - [x] 6.5 Verify T3 EVENT_FAILED in message center with `"CRITIQUE —"` prefix: PASS — `[event_failed] CRITIQUE — L'alarme intrusion (zone: Piece2)...`
  - [x] 6.6 Verify notification command triggered with "CRITIQUE" prefix: PASS — daemon log shows `type: notify, title: CRITIQUE — siaDC09 — Alarme non transmise`
  - [x] 6.7 Check daemon log shows 3 timeout attempts: PASS — `SM2 failed_timeout: attempt=1,2,3` then `failed_max_retries: attempt=4`
  - [x] 6.8 Restart CSR simulator and verify supervision recovers: `supervision_state`→2: PASS

- [x] Task 7: event_state persistence across restart (AC: 7)
  - [x] 7.1 Ensure last alarm was CONFIRMED (`event_state=1`): triggered burglarAlarm/Piece1 → ACK → event_state=1
  - [x] 7.2 Stop and restart daemon via Jeedom UI (or PHP CLI)
  - [x] 7.3 Immediately after restart: verify `event_state` still = 1 (`"Confirmé"`) — not reset to 0: PASS
  - [x] 7.4 Verify `supervision_state` goes through 1 (INITIALIZING) then recovers to 2 (HEALTHY) — normal restart behavior: PASS

- [ ] Task 8: TCP transport setup for alarm tests (AC: 8–11)
  - [ ] 8.1 Reconfigure to TCP and start TCP simulator:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$eq->setConfiguration('transport', 'tcp');
        \$eq->setConfiguration('csr_port', 5000);
        \$eq->save();
        "
        pkill -f "tests.simulator"
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &
        sudo -u www-data php -r "require '/var/www/html/core/php/core.inc.php'; siaDC09::deamon_stop(); siaDC09::deamon_start();"
        ```
  - [ ] 8.2 Verify HEALTHY over TCP: `supervision_state=2`. Confirm `--transport tcp --port 5000` in daemon cmdline: `ps aux | grep siadc09`.
  - [ ] 8.3 Clear ring buffer and error state:
        ```bash
        sudo -u www-data php -r "require '/var/www/html/core/php/core.inc.php'; config::save('sia_last_messages','[]','siaDC09'); config::save('sia_last_errors','[]','siaDC09');"
        ```

- [ ] Task 9: TCP — burglarAlarm happy path (AC: 8)
  - [ ] 9.1 Trigger burglarAlarm zone="Piece1":
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$cmd = \$eq->getCmd('action', 'burglarAlarm');
        \$cmd->execCmd(['title' => 'Piece1']);
        echo 'done'.PHP_EOL;
        "
        ```
  - [ ] 9.2 **Verify** `event_state=3` (PENDING) then `event_state=1` (CONFIRMED). `event_label="Confirmé"`.
  - [ ] 9.3 **Verify** daemon log shows BA frame sent and ACK received over TCP transport.

- [ ] Task 10: TCP — all event types ACK path (AC: 9)
  - [ ] 10.1 Trigger fireAlarm zone="Piece1": **Verify** `event_state=1`, FA code in daemon log over TCP.
  - [ ] 10.2 Trigger panicAlarm zone="Piece2": **Verify** `event_state=1`, PA code in daemon log over TCP.

- [ ] Task 11: TCP — NAK path T2 (AC: 10)
  - [ ] 11.1 Stop simulator, restart with mismatched account:
        ```bash
        pkill -f "tests.simulator"
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account FFFFFF &
        ```
  - [ ] 11.2 Trigger burglarAlarm zone="Piece1" (same PHP CLI as Task 9.1).
  - [ ] 11.3 **Verify** `event_state=2` quickly (no retry on NAK). T2 `BAD_CSR_RESPONSE` in message center, no "CRITIQUE —" prefix. Notification command triggered. Daemon log shows single attempt only.
  - [ ] 11.4 Restore correct account simulator:
        ```bash
        pkill -f "tests.simulator"
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &
        ```
  - [ ] 11.5 Wait for supervision recovery: `supervision_state=2`.

- [ ] Task 12: TCP — timeout path T3 (AC: 11)
  - [ ] 12.1 Stop simulator: `pkill -f "tests.simulator"`.
  - [ ] 12.2 Trigger burglarAlarm zone="Piece2" (same PHP CLI as Task 9.1).
  - [ ] 12.3 Wait for 3 retries (~3–35s — TCP connection refused retries faster than UDP timeout). **Verify** `event_state=2`, T3 `EVENT_FAILED` in message center with "CRITIQUE —" prefix. Notification command triggered.
  - [ ] 12.4 **Verify** daemon log shows 3 retry attempts then `event_failed`.
  - [ ] 12.5 Restart simulator: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &`. Wait for supervision recovery.

- [ ] Task 13: Revert to UDP (AC: 8–11)
  - [ ] 13.1 Revert config and restart on UDP:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$eq->setConfiguration('transport', 'udp');
        \$eq->setConfiguration('csr_port', 10001);
        \$eq->save();
        "
        pkill -f "tests.simulator"
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 0.0.0.0 --account 000001 &
        sudo -u www-data php -r "require '/var/www/html/core/php/core.inc.php'; siaDC09::deamon_stop(); siaDC09::deamon_start();"
        ```
  - [ ] 13.2 **Verify** HEALTHY on UDP: `supervision_state=2`, cmdline shows `--transport udp`.

## Dev Notes

### This is a MANUAL TESTING story — no code to write (unless bugs found)

The dev agent's role is:
1. Execute validation checklist on the real Jeedom VM
2. Observe actual vs. expected behavior
3. Document pass/fail with observations
4. Fix bugs inline if found (document in Dev Agent Record)

### Infrastructure (from Stories 12-1 through 12-4)

| Component | Location | Notes |
|-----------|----------|-------|
| Jeedom VM | `192.168.5.103` | SSH: `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103` |
| Plugin source | `/var/www/html/plugins/siaDC09` | Bind mount from `/mnt/hgfs/my-project` |
| CSR Simulator | Same VM, `localhost:10001` (UDP) | `python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001` |
| Daemon venv | `resources/python_venv/bin/python3` | Created by Jeedom dep manager |
| Plugin config state | `sia_wizard_step=4` | Wizard complete from Story 12-2 |
| Notification cmd | cmd id=29 (`Notify` on `Notification` eq) | `sia_notify_cmd_id=29` |
| Daemon log | `/var/www/html/log/siaDC09_daemon` | |
| Plugin log | `/var/www/html/log/siaDC09` | |

**SSH connection:** `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103`

### Alarm Command Execution Chain

```
Jeedom alarm plugin action (title="#zone#")
  → siaDC09Cmd::execute(['title' => 'Salon'])       [core/class/siaDC09Cmd.class.php:22]
    → zone = trim($_options['title'] ?? '')           [line 28 — extracts zone from title field]
    → siaDC09::sendToDaemon(['cmd'=>'burglarAlarm', 'zone'=>'Salon'])
      → TCP socket to localhost:55009
        → daemon._on_message_dispatch({'cmd':'burglarAlarm','zone':'Salon','apikey':'...'})
          → on_message('burglarAlarm', {'zone':'Salon'})  [daemon.py:1904]
            → sia_code = _EVENT_SIA_CODES['burglarAlarm'] = 'BA'
            → _enqueue_event('BA', 'Salon', None)
              → _queue_consumer() picks up EventItem
                → _send_with_retry() → SM2: IDLE→PENDING→CONFIRMED/FAILED
```

**Zone comes from `#title#` tag in alarm plugin action, NOT `#zone#`.** The `subType='message'` means:
- The alarm plugin's action title field is what triggers the command with `title` option
- `siaDC09Cmd::execute()` reads `$_options['title']` as the zone name
- Users must configure the alarm plugin action's title to contain the zone name

### SM2 State → event_state / event_label Mapping

| SM2 State | event_state | event_label |
|-----------|-------------|-------------|
| IDLE (startup-only) | 0 | `"Inactif"` |
| PENDING (sending) | 3 | `"En cours"` |
| CONFIRMED (ACK) | 1 | `"Confirmé"` |
| FAILED (NAK/timeout) | 2 | `"Échoué"` |

**CRITICAL — IDLE is startup-only (ADR-14):** After first alarm, SM2 never returns to IDLE. CONFIRMED/FAILED → PENDING on next alarm. `event_state=0` only before any alarm since daemon start.

**event_state/event_label are NOT reset on daemon restart** — they persist via Jeedom cmd values. This is by design so a user can see "last alarm was CONFIRMED" even after restart.

### NAK vs Timeout — Different Notification Tiers

**⚠️ IMPORTANT DISCREPANCY vs EPIC TEXT:**

The epic AC says "NAK path → T3 EVENT_FAILED". The actual implementation differs:

| Event | Code path | Tier | Notification |
|-------|-----------|------|--------------|
| NAK received | `_send_with_retry()` `elif status == "nak"` → immediate `_notify(BAD_CSR_RESPONSE, ...)` | **T2** | message center + notify cmd, NO "CRITIQUE" prefix |
| Timeout after MAX_RETRY_DEFAULT=3 | retry loop exhausted → `_notify(EVENT_FAILED, ...)` | **T3** | message center + notify cmd + "CRITIQUE —" prefix |

**NAK on alarm does NOT retry** (unlike timeout which retries). NAK → instant SM2 FAILED.

This is correct behavior per `daemon-design.md` — any CSR NAK in v1.0 means "CSR rejected our frame" which is a configuration/protocol issue (T2), not an infrastructure failure.

### How to Simulate NAK on Alarm Frames

The simulator (`tests/simulator/__main__.py`) has no built-in NAK mode. To get a NAK:

**Option A (recommended for Task 5): Mismatched account number**
```bash
# Start simulator with wrong account — daemon sends account=000001, simulator expects FFFFFF → NAK
python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account FFFFFF
```

**Option B: Mismatched encryption key**
- Configure daemon with encryption enabled but mismatched key → simulator cannot decrypt → NAK

**For T3 timeout testing (Task 6):** Stop simulator entirely — daemon gets no response, retries 3× then fires EVENT_FAILED.

### How to Trigger Alarm Commands via PHP CLI

```bash
# On VM as www-data:
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
\$eq = siaDC09::byType('siaDC09')[0];
\$cmd = \$eq->getCmd('action', 'burglarAlarm');
\$cmd->execCmd(['title' => 'Piece1']);
echo 'done' . PHP_EOL;
"
```

For `fireAlarm` / `panicAlarm`: change `'burglarAlarm'` and the zone name accordingly.
Available zones from alarm plugin "Alarme": **`Piece1`** (Detecteur1, cmd #9) and **`Piece2`** (Detecteur2, cmd #11).

**Empty zone test:**
```bash
\$cmd->execCmd(['title' => '']);
# siaDC09Cmd::execute trims to '' → sendToDaemon(['cmd'=>'burglarAlarm', 'zone'=>null])
```

### How to Trigger via Real Alarm Plugin (full integration path)

The alarm plugin equipment is named **"Alarme"** and has two zones:

| Zone | Trigger cmd | Device |
|------|-------------|--------|
| Piece1 | `#9#` (cmd id 9) | Detecteur1 (virtual binary) |
| Piece2 | `#11#` (cmd id 11) | Detecteur2 (virtual binary) |

Mode configured: `Standard`. Outbreak title: `"Déclenchement Alarme"` (message action).

**To arm and trigger via PHP CLI:**
```bash
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
# Arm in Standard mode
\$alarm = eqLogic::byTypeAndId('alarm', <alarm_eq_id>);
# Then set Detecteur1 state to 1 to trigger Piece1
cmd::byId(9)->execCmd(null, 1);  // set state = 1
"
```

**Simpler:** Use Jeedom UI → alarm plugin → arm the alarm in Standard mode → toggle Detecteur1 or Detecteur2 virtual sensor state to trigger the zone outbreak → siaDC09 burglarAlarm fires automatically (once Task 0 is done).

### Verifying event_state and event_label

```bash
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
\$eq = siaDC09::byType('siaDC09')[0];
\$estate = \$eq->getCmd('info', 'event_state');
\$elabel = \$eq->getCmd('info', 'event_label');
echo 'event_state=' . \$estate->execCmd() . PHP_EOL;
echo 'event_label=' . \$elabel->execCmd() . PHP_EOL;
echo 'collectDate=' . \$estate->getCollectDate() . PHP_EOL;
"
```

### Checking Ring Buffer for Alarm Entries

```bash
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
\$raw = config::byKey('sia_last_messages', 'siaDC09', '[]');
\$msgs = is_array(\$raw) ? \$raw : (json_decode(\$raw, true) ?: []);
echo count(\$msgs) . ' ring buffer entries:' . PHP_EOL;
foreach (\$msgs as \$m) {
    echo '  type=' . (\$m['dialog_type'] ?? '?')
       . ' sia_code=' . (\$m['sia_code'] ?? '-')
       . ' zone=' . (\$m['zone'] ?? '-') . PHP_EOL;
}
"
```

Alarm entries have `dialog_type: "alarm"` (vs `dialog_type: "supervision"` for supervision entries).

### Verifying Message Center Entries

```bash
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
\$msgs = message::byPlugin('siaDC09');
foreach (\$msgs as \$m) {
    echo '[' . \$m->getLogicalId() . '] ' . substr(\$m->getMessage(), 0, 100) . PHP_EOL;
}
"
```

T2 (BAD_CSR_RESPONSE) entries: no "CRITIQUE" prefix, logicalId = `'bad_csr_response'`
T3 (EVENT_FAILED) entries: `"CRITIQUE — "` prefix, logicalId = `'event_failed'`

### Key Learnings from Story 12-4

- **Simulator account must match daemon:** `--account 000001` must match `account_number` in daemon config. Intentional mismatch is the cleanest NAK trigger.
- **Log level storage format:** Set via Jeedom UI (not config::save directly). See `reference_jeedom_vm_ssh.md`.
- **postSave() does NOT restart daemon:** Config changes take effect only on manual restart.
- **deamon_info() as non-www-data always returns `state='nok'`:** Always use `sudo -u www-data`.
- **watchdog `deamonRestartNumber`:** If high from Story 12-4 repeated kills, reset via successful daemon start or manually.
- **Supervision recovery timing after restart:** Up to 1 supervision interval (60s default) before `supervision_state=2`.
- **T3 double-prefix bug (FIXED in 12-4):** `error_handler.py` no longer prepends T3_PREFIX in title_map entries — it's added only once by `_dispatch_notify()`. T3 alarm notification should show exactly one "CRITIQUE —" prefix.

### References

- [Source: `core/class/siaDC09Cmd.class.php:22`] — `execute()`: zone extracted from `$_options['title']`
- [Source: `core/class/siaDC09.class.php:341`] — `sendToDaemon()`: socket dispatch to daemon
- [Source: `resources/siadc09d/daemon.py:1904`] — `on_message()`: cmd → sia_code → `_enqueue_event()`
- [Source: `resources/siadc09d/daemon.py:248`] — `_EVENT_SIA_CODES`: burglarAlarm→BA, fireAlarm→FA, panicAlarm→PA
- [Source: `resources/siadc09d/daemon.py:1289`] — `_send_with_retry()`: retry loop, NAK→T2, timeout→T3
- [Source: `resources/siadc09d/daemon.py:1358`] — NAK handling: `BAD_CSR_RESPONSE` (T2), no retry
- [Source: `resources/siadc09d/daemon.py:1421`] — Timeout handling: max retries → `EVENT_FAILED` (T3)
- [Source: `resources/siadc09d/daemon.py:619`] — `_event_state_from_sm2()`: state → numeric mapping
- [Source: `resources/siadc09d/daemon.py:645`] — `_event_label_from_sm2()`: state → French label
- [Source: `resources/siadc09d/daemon.py:1690`] — Ring buffer alarm entry: `dialog_type: "alarm"`
- [Source: `resources/siadc09d/error_handler.py`] — `ErrorCode.BAD_CSR_RESPONSE` (T2), `ErrorCode.EVENT_FAILED` (T3)
- [Source: `docs/design/daemon-design.md`] — SM2 state machine, retry logic, `_EVENT_SIA_CODES`
- [Source: `docs/design/error-handler-design.md`] — T2/T3 dispatch, notify channels
- [Source: `_bmad-output/implementation-artifacts/12-4-supervision-loop-strike-recovery.md`] — Story 12-4 bug fix: double T3_PREFIX resolved

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (eu.anthropic.claude-sonnet-4-6)

### Debug Log References

- Daemon log: `/var/www/html/log/siaDC09_daemon` on Jeedom VM (192.168.5.103)
- Session date: 2026-05-29

### Completion Notes List

**Bug 1: SM2_FAILED_NAK incorrectly had T3_PREFIX (T2/T3 tier mismatch)**
- `messages.py` had `SM2_FAILED_NAK = T3_PREFIX + "..."` but NAK fires `BAD_CSR_RESPONSE` (T2), not `EVENT_FAILED` (T3).
- Fix: removed `T3_PREFIX` from `SM2_FAILED_NAK` in `messages.py`.
- Updated `tests/level1/test_messages.py` to assert `SM2_FAILED_NAK` does NOT have T3 prefix.

**Bug 2: SIATransportError not caught in _send_with_retry — broke timeout retry path**
- When simulator was stopped and port was actively refused (`ConnectionRefusedError`), the transport layer raised `SIATransportError` which propagated past the retry loop's `asyncio.TimeoutError` handler.
- Result: queue consumer caught it and swallowed it without updating `event_state` to FAILED and without firing T3.
- Fix: added `SIATransportError` to the `except (asyncio.TimeoutError, SIATransportError)` clause in `_send_with_retry()` — transport errors now retry up to max_retries then fire T3.
- Note: with port-refused, retries happen in ~1s each (no 10s wait_for) — 3 retries complete in ~3s total. Still correct behavior.

**Bug 3: event_state reset to 0 on daemon restart (AC7 violation)**
- `_update_info_commands(None)` during periodic supervision ACK sent the full payload including `event_state=0` (from `_sm2_state=IDLE`), overwriting persisted cmd values from the previous daemon run.
- Fix: `_update_info_commands(None)` now excludes `event_state`/`event_label` when `_sm2_state == SM2State.IDLE` (startup-only state). Persisted cmd values from previous run are left untouched until an actual SM2 event occurs.

**Bug 4: Alarm plugin outbreak zone empty (Story 12-4 carry-over)**
- Alarm plugin "Standard" mode had no `zone` array: `[{"name":"Standard"}]` → `getZoneOfMode()` returned empty → `execute()` skipped outbreak.
- Fix: added `"zone":["Piece1","Piece2"]` to "Standard" mode configuration via PHP CLI on VM.

**Bug 5: CSR Simulator --account flag not triggering NAK on alarm frames**
- Simulator's `_decide_response()` ACKed ALL ALARM/NULL frames regardless of account; the `--account` flag only affected the ACK response body.
- Fix: `csr_simulator.py` updated to extract account from inbound `[#ACCOUNT|...]` data block and NAK when it doesn't match the configured preset account.

**AC Status:**
- AC1 (happy path burglarAlarm ACK): PASS ✓
- AC2 (all event types ACK): PASS — FA and PA both confirmed ✓
- AC3 (zone handling): PASS — zone=Piece1 in frame, empty zone → zone=None no crash ✓
- AC4 (NAK path T2): PASS — event_state=2, no CRITIQUE prefix, no retry ✓
- AC5 (timeout path T3): PASS — 3 retries, CRITIQUE prefix, T3 notification ✓
- AC6 (ring buffer alarm entry): PASS (verified in 12-4 session, confirmed dialog_type=alarm) ✓
- AC7 (event_state persists): PASS — event_state=1 survives daemon restart ✓

### File List

- `resources/siadc09d/messages.py` — Bug 1: removed T3_PREFIX from SM2_FAILED_NAK
- `resources/siadc09d/daemon.py` — Bug 2: SIATransportError added to retry handler; Bug 3: event_state excluded from periodic update when SM2 IDLE
- `resources/siadc09d/csr_simulator.py` — Bug 5: account validation NAK logic in _decide_response() and account extraction in _parse_received_message()
- `tests/level1/test_messages.py` — Bug 1: updated T3 prefix test to assert SM2_FAILED_NAK is T2

## Change Log

| Date | Change |
|------|--------|
| 2026-05-29 | Story created and executed on Jeedom VM. All 7 AC pass. 5 bugs fixed. |
| 2026-06-01 | TCP pass added: AC8–11 + Tasks 8–13 — alarm delivery over TCP transport. |
