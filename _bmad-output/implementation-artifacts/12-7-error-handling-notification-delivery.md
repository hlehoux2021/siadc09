---
story_id: "12-7"
story_key: "12-7-error-handling-notification-delivery"
epic_id: "epic-12"
epic_name: "Jeedom VM Integration Testing"
status: "ready-for-dev"
created: "2026-05-29"
analysis_completed: "2026-05-29"
---

# Story 12.7: Error Handling & Notification Delivery

Status: ready-for-dev

## Story

As a Jeedom user,
I want errors properly classified and delivered through Jeedom's message center and configured notification command,
So that I am informed of issues proportionally to their severity, with no spam and no silent failures.

## Acceptance Criteria

1. **T1 SUPERVISION_TIMEOUT — message center only:** Given daemon HEALTHY, when CSR simulator is stopped (silent drop) so that strike escalates to 1, then a Jeedom message center entry is created with `logicalId=supervision_timeout`, French French text matches `SM1_TIMEOUT_WARNING` template (`"Timeout supervision (strike 1/3) — nouvelle tentative"` style), AND the configured notification command (`sia_notify_cmd_id`) is **NOT** triggered (no SMS/push event in the notification cmd's event log/log file).

2. **T1 SUPERVISION_TIMEOUT dedup (occurrence counter):** Given the daemon is in DEGRADED state from AC1, when 4 additional supervision timeouts occur (strikes 2, 3, and beyond strike-3 cap), then the message center still shows **exactly one** `supervision_timeout` entry whose Jeedom occurrence counter (`occurrences` column in `messages` DB table) increments — not 5 separate entries. Verifying via `message::all('siaDC09')` PHP CLI returns a single row with logicalId=`supervision_timeout`.

3. **T1 SUPERVISION_NAK — message center only:** Given daemon HEALTHY and CSR simulator started with mismatched account (`--account FFFFFF`) so each supervision NULL receives a NAK, when 1 supervision cycle elapses, then a message center entry is created with `logicalId=supervision_nak`, French text matches `SM1_NAK_TIMESTAMP` template (`"NAK supervision (strike N/3) — horodatage rejeté par la centrale"`), AND the notification command is **NOT** triggered. (Note: `SM1NakCtx.parsed_ts` may be None if the simulator's NAK has no timestamp; this is acceptable — the v1.1 timestamp auto-heal is not the focus here.)

4. **T1 auto-resolve on HEALTHY recovery:** Given `sia_last_errors` contains T1 entries from AC1/AC3 paths (verified before recovery), when the simulator is restored with the correct account so the next ACK fires SM1→HEALTHY, then `sia_last_errors` no longer contains any entry whose `code` is `supervision_timeout` or `supervision_nak` (T2/T3 entries, if any, are preserved).

5. **T2 BAD_CSR_RESPONSE — message center + notification, no CRITIQUE prefix:** Given simulator running with mismatched account on the alarm path (`burglarAlarm` triggers an alarm frame that the simulator NAKs because of account mismatch), when the alarm action is fired, then a message center entry appears with `logicalId=bad_csr_response`, the message text starts with `"La centrale a renvoyé une réponse"` (no `CRITIQUE —` prefix in either the title or the message body), AND the configured notification command IS triggered exactly once (verified in `notify` cmd execution log).

6. **T3 SUPERVISION_DISCONNECTED — message center + notification + CRITIQUE prefix, fires once:** Given daemon HEALTHY, when the simulator is stopped and 3 consecutive supervision timeouts occur, then the message center entry for `logicalId=supervision_disconnected` exists and starts with `"CRITIQUE — "`, the configured notification command IS triggered, the title passed to the notify cmd starts with `"siaDC09 — CRITIQUE — "` (or `"siaDC09 — "` followed by `T3_PREFIX` per the dispatch rule), AND `_sm1_t3_fired` prevents re-firing — additional supervision cycles do not produce a second `supervision_disconnected` message center entry (occurrence counter does NOT increment beyond what was set when T3 first fired).

7. **T3 EVENT_FAILED — message center + notification + CRITIQUE prefix:** Given daemon HEALTHY (or DEGRADED — but with the simulator down so all alarm sends time out), when `burglarAlarm` is triggered with zone="Piece1" and all 3 retry attempts time out, then a message center entry appears with `logicalId=event_failed`, the message starts with `"CRITIQUE —"`, includes `"intrusion"` (French label for burglarAlarm) and `"Piece1"` and `"3 tentative(s)"`, AND the notification command is triggered exactly once (no per-retry spam).

8. **T3 → notification command title contains CRITIQUE:** For both AC6 and AC7, the `title` field of the `notify` callback payload sent to PHP contains the substring `"CRITIQUE"`. This is verified by either (a) inspecting the notification command's recorded title in its event log, or (b) tailing the daemon log at DEBUG level to see the outgoing `notify` callback JSON.

9. **error_update populates `sia_last_errors` for T2/T3, not T1:** After AC5/AC6/AC7 paths run, `config::byKey('sia_last_errors', 'siaDC09')` returns a JSON array containing entries for `bad_csr_response`, `supervision_disconnected`, `event_failed` (newest first, max 10) — each entry has all 5 keys (`code`, `message`, `timestamp`, `context`, `count`). After AC1/AC3 (T1 only), the T1 entries are NOT present in `sia_last_errors` (T1 is message_center only, no error_update).

10. **All error messages are in French:** Every message_center entry created during this story (AC1, AC3, AC5, AC6, AC7) has its `message` text and `title` text in French — no English fragments, no untranslated `ErrorCode` enum names, no `{placeholder}` literals visible (all `.format()` substitutions resolved).

11. **TRANSPORT_PERMANENT — T3, TCP-only, daemon self-stops:** Given daemon configured with TCP transport and TCP reconnect loop exhausted (NO_NETWORK state), then a message center entry is created with `logicalId=transport_permanent`, message starts with `"CRITIQUE — "` (T3_PREFIX), AND the configured notification command IS triggered, AND the title in the `notify` callback payload contains `"CRITIQUE"` (AC8 equivalent for TCP), AND the daemon process exits cleanly (`pgrep -f siadc09d` → no output, PID file absent or stale). Jeedom watchdog then restarts the daemon.

## Pass/Fail Protocol

For each "Verify" step:
- **PASS:** Observed value matches expected → note observation, continue.
- **FAIL:** Mismatch → stop. Document observed vs. expected, check daemon log `tail -100 /var/www/html/log/siaDC09_daemon` and PHP log `tail -100 /var/www/html/log/siaDC09`, file bug in Dev Agent Record, then assess whether remaining tasks are still meaningful.
- **BLOCKED:** Precondition from prior task not met → skip, note as BLOCKED with reason.

## Tasks / Subtasks

- [ ] Task 0: Prepare environment (AC: all)
  - [ ] 0.1 SSH to VM: `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103`
  - [ ] 0.2 Verify daemon HEALTHY (`supervision_state=2`) and CSR simulator running with `--account 000001`. If not: start simulator: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &`
  - [ ] 0.3 Verify `sia_notify_cmd_id` is set (cmd id=29 — `Notify` action on `Notification` equipment, per Story 12-5). If unset, configure it in wizard step 4.
  - [ ] 0.4 Set daemon log level to DEBUG (so `notify` callback payloads are visible in `siaDC09_daemon`). Restart daemon.
  - [ ] 0.5 Clear baseline state to avoid contamination from prior stories:
        - `config::save('sia_last_errors', '[]', 'siaDC09')`
        - `config::save('sia_last_messages', '[]', 'siaDC09')`
        - Clear message center for plugin: `message::removeAll('siaDC09')` (or `DELETE FROM message WHERE plugin='siaDC09'` via `mysql_utils.sh`)
        - Clear the `Notification` equipment's event log/history if accessible, OR note its current entry count as a baseline
  - [ ] 0.6 Confirm wizard config: `sia_wizard_step=4`, account `000001`, transport=`udp`.

- [ ] Task 1: T1 SUPERVISION_TIMEOUT — message center only (AC: 1)
  - [ ] 1.1 Stop CSR simulator: `pkill -f "tests.simulator"` — confirm dead via `pgrep -f tests.simulator` (no output).
  - [ ] 1.2 Wait for strike=1 (~60s, one supervision interval). Confirm via PHP CLI: `supervision_state=1`, `supervision_label="DÉGRADÉ (1/3)"`.
  - [ ] 1.3 **Verify** message center has one new entry for plugin `siaDC09` with `logicalId='supervision_timeout'`. PHP CLI:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$msgs = message::all('siaDC09');
        foreach (\$msgs as \$m) {
          echo 'logicalId='.\$m->getLogicalId().' occ='.\$m->getOccurrences().' msg='.\$m->getMessage().PHP_EOL;
        }
        "
        ```
  - [ ] 1.4 **Verify** the message text matches the `SM1_TIMEOUT_WARNING` shape (contains `"Timeout supervision"`, `"strike 1/3"`, `"nouvelle tentative"` substrings). All-French. No `{strike}` literal placeholder.
  - [ ] 1.5 **Verify** notification command `sia_notify_cmd_id` was NOT triggered: check the `Notify` equipment's event log/history — entry count unchanged from baseline (Task 0.5). If the notification cmd writes to its own log/file, compare timestamps. If unsure, also confirm via daemon log (`tail -200 /var/www/html/log/siaDC09_daemon | grep "type.*notify"`) — there must be no `notify` callback entries since the simulator was stopped, only `message_center` and `error_update` entries (and `error_update` is sent only for T2/T3, so absent for T1).

- [ ] Task 2: T1 dedup — occurrence counter increments (AC: 2)
  - [ ] 2.1 With simulator still stopped, wait through strike=2 (~120s mark) and strike=3 (~180s mark) and one cycle beyond strike-3 cap (~240s mark). Confirm via PHP CLI: `supervision_state=0`, `supervision_label="PERDUE"` at the end.
  - [ ] 2.2 **Verify** message center has still **exactly one** entry for `logicalId='supervision_timeout'` (i.e. dedup worked):
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$rows = array_filter(message::all('siaDC09'),
          fn(\$m) => \$m->getLogicalId()==='supervision_timeout');
        echo 'count='.count(\$rows).PHP_EOL;
        foreach (\$rows as \$m) echo 'occ='.\$m->getOccurrences().PHP_EOL;
        "
        ```
        Expected: `count=1`. The `occ` value should reflect Jeedom's occurrence counter (≥2) — note exact value but the absolute number depends on Jeedom's increment behavior.
  - [ ] 2.3 **Verify** still no notification command triggered (T1 dedup MUST not also de-spam the notify cmd because nothing was sent in the first place — same baseline check as 1.5).

- [ ] Task 3: T3 SUPERVISION_DISCONNECTED — fires once with CRITIQUE prefix (AC: 6, 8)
  - [ ] 3.1 The daemon is now in DEGRADED(strike=3) — so T3 should already have fired during Task 2. **Verify** message center has one entry for `logicalId='supervision_disconnected'`:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$rows = array_filter(message::all('siaDC09'),
          fn(\$m) => \$m->getLogicalId()==='supervision_disconnected');
        echo 'count='.count(\$rows).PHP_EOL;
        foreach (\$rows as \$m) {
          echo 'occ='.\$m->getOccurrences().' msg='.\$m->getMessage().PHP_EOL;
        }
        "
        ```
        Expected: `count=1`, message starts with `"CRITIQUE — "`, contains `"Supervision perdue"` (or matching `SM1_LOST` template).
  - [ ] 3.2 **Verify** the notification command WAS triggered. Check via:
        - The `Notify` equipment's event log/history — entry count increased by exactly 1 since Task 0.5 baseline.
        - Daemon log: `tail -300 /var/www/html/log/siaDC09_daemon | grep -A2 '"type":"notify"'` — confirm one `notify` callback was sent. The `title` field in the JSON payload should contain `"CRITIQUE"` (verifying AC8 — T3 title contains CRITIQUE).
  - [ ] 3.3 **Verify** T3 fires only once: stay in strike=3 state for one more supervision cycle (~60s additional). Re-check 3.1 — `count` MUST still be 1 and the message center entry's `occurrences` MUST NOT have incremented to imply re-firing. Confirm `_sm1_t3_fired=True` semantics via daemon log: should NOT see another `notify` callback entry for `supervision_disconnected`.
  - [ ] 3.4 **Verify** `sia_last_errors` contains an entry whose `code='supervision_disconnected'` (5-key contract: `code`, `message`, `timestamp`, `context`, `count`):
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$raw = config::byKey('sia_last_errors', 'siaDC09', '[]');
        \$arr = is_array(\$raw) ? \$raw : (json_decode(\$raw, true) ?: []);
        foreach (\$arr as \$e) echo 'code='.(\$e['code']??'').' keys='.implode(',', array_keys(\$e)).PHP_EOL;
        "
        ```

- [ ] Task 4: T1 auto-resolve on HEALTHY recovery (AC: 4)
  - [ ] 4.1 Note `sia_last_errors` content before recovery (from Task 3.4) — should contain T3 `supervision_disconnected` (NO T1 entries — T1 never went to error_update).
  - [ ] 4.2 Restart simulator with correct account: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &`
  - [ ] 4.3 Wait for daemon to recover to HEALTHY (`supervision_state=2`, `supervision_label="OK"`) — typically ≤90s.
  - [ ] 4.4 **Verify** `sia_last_errors` no longer contains any `code` value of `supervision_timeout` or `supervision_nak`. The T3 `supervision_disconnected` entry MAY still be present (T2/T3 only cleared by user via "Vider"). Confirm via the same PHP CLI as 3.4.
  - [ ] 4.5 Note: the daemon sends `error_update` with `resolve_t1: 1` on HEALTHY transition — expect daemon DEBUG log line confirming this dispatch.
  - [ ] 4.6 Wait for `_sm1_t3_fired` reset (set to `False` by HEALTHY transition). This will be re-tested in Task 5.

- [ ] Task 5: T3 fires AGAIN after recovery + new disconnect (AC: 6 cont.)
  - [ ] 5.1 Stop simulator again: `pkill -f "tests.simulator"`.
  - [ ] 5.2 Wait through 3 strikes again (~180s).
  - [ ] 5.3 **Verify** message center has **two** distinct firings of `supervision_disconnected`:
        - Either Jeedom's occurrence counter incremented to a new higher value AND `lastDate` updated, OR
        - The single entry's `occurrences` column shows a new increment matching the new firing.
        - The notification command's event log shows a NEW notification (count+1 from end-of-Task-3 baseline).
        - This confirms `_sm1_t3_fired` was reset on HEALTHY in Task 4 and re-fired here.
  - [ ] 5.4 Restore simulator with correct account, verify recovery to HEALTHY.

- [ ] Task 6: T1 SUPERVISION_NAK + simulator NAK path (AC: 3)
  - [ ] 6.1 Stop normal simulator, restart with mismatched account so supervision NULL gets NAK'd:
        ```bash
        pkill -f "tests.simulator"
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account FFFFFF &
        ```
  - [ ] 6.2 Wait for one supervision cycle (~60s). Daemon's account is `000001`; simulator expects `FFFFFF` → NAK on each supervision NULL.
  - [ ] 6.3 **Verify** message center has a new entry with `logicalId='supervision_nak'`. Message text contains `"NAK supervision"`, `"strike"`, `"horodatage rejeté"` (matching `SM1_NAK_TIMESTAMP`) — all-French.
  - [ ] 6.4 **Verify** notification command was NOT triggered for this T1 (count unchanged from Task 5 end).
  - [ ] 6.5 **Note:** at strike=3, depending on whether the daemon code path for NAK at strike=3 routes to `BAD_CSR_RESPONSE` (T2) or stays as NAK-T1 + SUPERVISION_DISCONNECTED (T3), document the actual observed behavior. (Per error-handler-design.md, undecodable-NAK at any strike → `BAD_CSR_RESPONSE` T2; parseable-timestamp-NAK → T1 then T3 at strike=3. The simulator's NAK frame has no timestamp → likely undecodable path → T2.)
  - [ ] 6.6 Restore simulator with correct account, verify HEALTHY recovery.

- [ ] Task 7: T2 BAD_CSR_RESPONSE — alarm NAK path (AC: 5, 9)
  - [ ] 7.1 Stop simulator, restart with mismatched account `--account FFFFFF` (same setup as Task 6 — alarm frame to `000001` will be NAK'd).
  - [ ] 7.2 Wait for daemon supervision recovery to be irrelevant (NAK on supervision creates noise but does not block the test). Let supervision settle in DEGRADED.
  - [ ] 7.3 Trigger alarm via PHP CLI:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$cmd = \$eq->getCmd('action', 'burglarAlarm');
        \$cmd->execCmd(['title' => 'Piece1']);
        echo 'done'.PHP_EOL;
        "
        ```
  - [ ] 7.4 **Verify** SM2 → FAILED quickly (NAK = no retry, immediate fail). `event_state=2`, `event_label="Échoué"`.
  - [ ] 7.5 **Verify** message center has `logicalId='bad_csr_response'` entry. Message starts with `"La centrale a renvoyé une réponse"`. No `"CRITIQUE — "` prefix anywhere in the title or message.
  - [ ] 7.6 **Verify** notification command WAS triggered (count+1 since Task 6 baseline). The `title` passed to the notify cmd does NOT contain `"CRITIQUE"` (T2 uses the plain `title` from the build_notification table — `"siaDC09 — Réponse incompréhensible de la centrale"`).
  - [ ] 7.7 **Verify** `sia_last_errors` now contains a `bad_csr_response` entry (newest first, all 5 keys present).

- [ ] Task 8: T3 EVENT_FAILED — alarm timeout path (AC: 7, 8, 9)
  - [ ] 8.1 Stop simulator entirely: `pkill -f "tests.simulator"` (silent drop → alarm frames time out).
  - [ ] 8.2 Trigger alarm via PHP CLI:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$cmd = \$eq->getCmd('action', 'burglarAlarm');
        \$cmd->execCmd(['title' => 'Piece1']);
        echo 'done'.PHP_EOL;
        "
        ```
  - [ ] 8.3 Wait for 3 retries to time out (~30–35s total based on `receive_timeout_s + 1s backoff` × 3).
  - [ ] 8.4 **Verify** `event_state=2`, `event_label="Échoué"`.
  - [ ] 8.5 **Verify** message center has `logicalId='event_failed'` entry. Message starts with `"CRITIQUE —"`. Message contains French label `"intrusion"` (from `event_type_fr('burglarAlarm')`), zone `"Piece1"`, and `"3 tentative(s)"` (or `"3 tentatives"`). All-French.
  - [ ] 8.6 **Verify** notification command WAS triggered exactly once (count+1 since Task 7 baseline) — NOT 3 times (no per-retry spam). The `title` passed to the notify cmd contains `"CRITIQUE"` (matches AC8).
  - [ ] 8.7 **Verify** `sia_last_errors` now contains an `event_failed` entry.
  - [ ] 8.8 Restart simulator with correct account, verify HEALTHY recovery and supervision returns to OK.

- [ ] Task 9: French language audit (AC: 10)
  - [ ] 9.1 Dump all current message center entries for `siaDC09` and the `sia_last_errors` config:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        echo '=== messages ==='.PHP_EOL;
        foreach (message::all('siaDC09') as \$m) {
          echo \$m->getLogicalId().' | '.\$m->getMessage().PHP_EOL;
        }
        echo '=== last_errors ==='.PHP_EOL;
        \$raw = config::byKey('sia_last_errors', 'siaDC09', '[]');
        \$arr = is_array(\$raw) ? \$raw : (json_decode(\$raw, true) ?: []);
        foreach (\$arr as \$e) echo \$e['code'].' | '.\$e['message'].PHP_EOL;
        "
        ```
  - [ ] 9.2 **Verify** every message and title is in French. No English fragments (e.g., no `"Connection lost"`, no `"timeout"` in user-facing text — only as a substring inside `"Timeout"` which is part of accepted French technical vocabulary, OK). No `ErrorCode` enum names visible (e.g., no `"SUPERVISION_TIMEOUT"` in the message body — only valid as `code=` field). No literal `{strike}` / `{retry_count}` / `{transport}` / `{csr_address}` placeholders — all `.format()` substitutions must have resolved.
  - [ ] 9.3 **Verify** the `Notify` equipment's event log entries are also in French (titles + messages).

- [ ] Task 10: TCP setup + TRANSPORT_PERMANENT test (AC: 11)
  - [ ] 10.1 Reconfigure to TCP:
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
  - [ ] 10.2 Verify HEALTHY over TCP: `supervision_state=2`, cmdline includes `--transport tcp --port 5000`. Note daemon PID.
  - [ ] 10.3 Set daemon log level to DEBUG. Note baseline message center entry count.
  - [ ] 10.4 Stop simulator: `pkill -f "tests.simulator"`. Wait for strike escalation → TCP_RECONNECTING (~180s). Confirm `supervision_label` starts with "Reconnexion TCP" via PHP CLI.
  - [ ] 10.5 Keep simulator stopped and wait for TCP reconnect loop to exhaust all attempts → daemon enters NO_NETWORK and exits. Monitor:
        ```bash
        watch -n 10 'pgrep -f siadc09d && echo running || echo STOPPED'
        ```
  - [ ] 10.6 **Verify** daemon exits: `pgrep -f siadc09d` → no output.
  - [ ] 10.7 **Verify** message center has `logicalId='transport_permanent'` entry:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$rows = array_filter(message::all('siaDC09'),
          fn(\$m) => \$m->getLogicalId()==='transport_permanent');
        echo 'count='.count(\$rows).PHP_EOL;
        foreach (\$rows as \$m) {
          echo 'occ='.\$m->getOccurrences().' msg='.substr(\$m->getMessage(),0,80).PHP_EOL;
        }
        "
        ```
        Expected: `count=1`, message starts with `"CRITIQUE — "`.
  - [ ] 10.8 **Verify** notification command WAS triggered (count+1 from Task 0.5 baseline). Daemon log: `tail -500 /var/www/html/log/siaDC09_daemon | grep -A2 '"type":"notify"'` — confirm a `notify` callback was sent with title containing `"CRITIQUE"`.
  - [ ] 10.9 **Verify** `sia_last_errors` contains `transport_permanent` entry (5-key contract):
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$raw = config::byKey('sia_last_errors', 'siaDC09', '[]');
        \$arr = is_array(\$raw) ? \$raw : (json_decode(\$raw, true) ?: []);
        foreach (\$arr as \$e) echo 'code='.(\$e['code']??'').' keys='.implode(',', array_keys(\$e)).PHP_EOL;
        "
        ```
  - [ ] 10.10 Start simulator before watchdog restarts daemon:
        ```bash
        cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &
        ```
  - [ ] 10.11 Wait for watchdog to restart daemon (~90s). **Verify** daemon restarts and recovers to HEALTHY over TCP.

- [ ] Task 11: TCP pass — T1 SUPERVISION_TIMEOUT and T3 SUPERVISION_DISCONNECTED (AC: 1, 6 — TCP variant)
  - [ ] 11.1 Daemon is HEALTHY over TCP (from Task 10.11). Clear message center: `sudo -u www-data php -r "require '/var/www/html/core/php/core.inc.php'; message::removeAll('siaDC09');"`
  - [ ] 11.2 Stop simulator: `pkill -f "tests.simulator"`. Wait for strike=1 (~60s). **Verify** `supervision_state=1`, `supervision_label="DÉGRADÉ (1/3)"`. Message center `supervision_timeout` entry appears, notification NOT triggered.
  - [ ] 11.3 Wait for strike=3 (~180s). **Verify** `supervision_state=0`, `supervision_label="Reconnexion TCP…"` (TCP_RECONNECTING — NOT "PERDUE"). T3 `supervision_disconnected` fires with "CRITIQUE —" prefix and notification command triggered.
  - [ ] 11.4 Restart simulator: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &`. Wait for HEALTHY recovery.

- [ ] Task 12: TCP pass — T2 BAD_CSR_RESPONSE and T3 EVENT_FAILED (AC: 5, 7 — TCP variant)
  - [ ] 12.1 T2 NAK path (TCP): restart simulator with mismatched account `--account FFFFFF`. Trigger burglarAlarm zone="Piece1" via PHP CLI. **Verify** `event_state=2`, T2 `bad_csr_response` in message center (no CRITIQUE), notification triggered. Restore correct account.
  - [ ] 12.2 T3 timeout path (TCP): stop simulator entirely. Trigger burglarAlarm zone="Piece2". Wait for 3 retries. **Verify** `event_state=2`, T3 `event_failed` with "CRITIQUE —" prefix, notification triggered. Restart simulator and verify HEALTHY.

- [ ] Task 13: Revert to UDP
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
  - [ ] 13.2 **Verify** HEALTHY on UDP: `supervision_state=2`.

- [ ] Task 14: Final cleanup
  - [ ] 14.1 Restore simulator running with correct account.
  - [ ] 14.2 Confirm daemon HEALTHY (`supervision_state=2`).
  - [ ] 14.3 Optionally clear test artifacts: `config::save('sia_last_errors','[]','siaDC09')` and message center entries via the `Vider` button in the diagnostic tab — this is operator preference, not a hard requirement.

## Dev Notes

### This is a MANUAL TESTING story — no code to write (unless bugs found)

The dev agent's role:
1. Execute validation checklist on the real Jeedom VM via SSH + PHP CLI.
2. Observe actual vs. expected behavior across all three tiers (T1/T2/T3).
3. Document pass/fail with concrete observations (PHP CLI output, log excerpts).
4. Fix bugs inline if found (document in Dev Agent Record).

If a bug is found that requires daemon or PHP code changes, fix it in the existing files (`resources/siadc09d/error_handler.py`, `resources/siadc09d/daemon.py`, `resources/siadc09d/messages.py`, `core/class/siaDC09.class.php`). Do NOT add abstractions, do NOT refactor, do NOT add tests beyond what's needed to verify the fix.

### Infrastructure (from Stories 12-1 through 12-6)

| Component | Location | Notes |
|---|---|---|
| Jeedom VM | `192.168.5.103` | SSH: `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103` |
| Plugin source | `/var/www/html/plugins/siaDC09` | Bind mount from `/mnt/hgfs/my-project` |
| CSR Simulator | Same VM, `localhost:10001` (UDP) | `python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001` |
| Daemon venv | `resources/python_venv/bin/python3` | |
| Notification cmd | id=29 (`Notify` action on `Notification` eq) | `sia_notify_cmd_id=29` |
| Daemon log | `/var/www/html/log/siaDC09_daemon` | DEBUG level needed for `notify` callback visibility |
| Plugin log | `/var/www/html/log/siaDC09` | |
| Plugin config state | `sia_wizard_step=4`, account=`000001`, transport=`udp` | |

**SSH:** see memory reference `reference_jeedom_vm_ssh.md`. Non-production test VM only.

### 3-Tier Error Model — Authoritative Reference

(From `docs/design/error-handler-design.md` — read this file fully if any AC is unclear.)

| Tier | Codes | Channels | CRITIQUE prefix | error_update | Dedup |
|---|---|---|---|---|---|
| T1 | `SUPERVISION_TIMEOUT`, `SUPERVISION_NAK` | message_center only | No | No | Jeedom occurrence counter on logicalId |
| T2 | `BAD_CSR_RESPONSE` | message_center + notify + error_update | No | Yes | Jeedom dedup + notify-queue plugin dedup on title |
| T3 | `SUPERVISION_DISCONNECTED`, `EVENT_FAILED`, `TRANSPORT_PERMANENT` | message_center + notify + error_update | Yes (in message body and notify title) | Yes | Per-firing flags (`_sm1_t3_fired`) + Jeedom dedup |

**Key flow:** daemon `_notify(code, ctx)` → `_dispatch_notify` → 3 channels:
- `message_center` callback → PHP `siaDC09::message()` case `'message_center'` → `message::add(__CLASS__, message, '', logical_id)`
- `notify` callback (T2/T3 only) → PHP case `'notify'` → `cmd::byId(sia_notify_cmd_id)->execCmd(['title'=>$title, 'message'=>$message])`
- `error_update` callback (T2/T3 only) → PHP case `'error_update'` → prepend to `sia_last_errors` (max 10, newest first), 5 mandatory keys (`code`, `message`, `timestamp`, `context`, `count`)

T1 auto-resolve on HEALTHY: daemon sends `error_update` with `resolve_t1: 1` flag → PHP filters out entries whose `code ∈ {supervision_timeout, supervision_nak}`.

### Key Files (read-only for this story unless fixing a bug)

| File | Role |
|---|---|
| `resources/siadc09d/error_handler.py` | `ErrorCode`, `ErrorTier`, `ERROR_TIERS`, `T3_PREFIX="CRITIQUE — "`, `build_notification()`, context dataclasses (`SM1TimeoutCtx`, `SM1NakCtx`, `BadCSRResponseCtx`, `SM1DisconnectedCtx`, `EventFailedCtx`, `TransportPermanentCtx`), `event_type_fr()` |
| `resources/siadc09d/daemon.py:319+,383+,495+` | `_notify()` synchronous wrapper, `_dispatch_notify()` async dispatch (3 channels, each in its own try/except) |
| `resources/siadc09d/daemon.py:781,948,958,1006,1121,1379,1437,1482,1512,1532,1825` | `_notify(ErrorCode.X, …)` call sites — supervision timeout/NAK/disconnected, transport_permanent, event_failed, bad_csr_response |
| `resources/siadc09d/daemon.py:907-908` | `error_update` with `resolve_t1: 1` on HEALTHY transition |
| `resources/siadc09d/messages.py` | French message templates: `T3_PREFIX`, `SM1_TIMEOUT_WARNING`, `SM1_NAK_TIMESTAMP`, `SM1_LOST` (T3), `SM2_FAILED` (T3), `SM2_FAILED_NAK` (T2). The actual message body returned by `build_notification()` is composed from these templates per the message catalog in error-handler-design.md §"Message catalog". |
| `core/class/siaDC09.class.php:374` | `case 'message_center'` — `message::add(__CLASS__, $message, '', $logical_id)` |
| `core/class/siaDC09.class.php:384` | `case 'notify'` — guards on `sia_notify_cmd_id`, `cmd::byId()`, then `execCmd(['title','message'])`; failures logged not propagated |
| `core/class/siaDC09.class.php:411` | `case 'error_update'` — handles `resolve_t1` flag (filter out T1 codes) OR prepends a new entry; `array_slice(…, 0, 10)` cap |

### Verifying a Notification Was Triggered

The notification command (`sia_notify_cmd_id=29`) is the `Notify` action on the `Notification` equipment. To verify it fired:

**Option A (preferred): Check the `Notify` equipment's history/event log via Jeedom UI or PHP CLI.** The `Notification` equipment likely records each `execCmd()` invocation. Note the entry count before and after each task — entry count delta = number of times the cmd was triggered.

**Option B: Daemon DEBUG log.** With log level=DEBUG, `_dispatch_notify()` logs every callback dispatch. Search for `"type":"notify"` in `/var/www/html/log/siaDC09_daemon`:
```bash
tail -500 /var/www/html/log/siaDC09_daemon | grep -B1 -A3 '"type":"notify"'
```
Each `notify` JSON payload corresponds to one notification command trigger. The `title` field in the JSON is the title passed to `execCmd()`.

**Option C: PHP log.** If the `notify` callback dispatcher logs anything (e.g., on failure), `tail /var/www/html/log/siaDC09 | grep -i notify`.

### Jeedom Message Center API — Concrete Calls

```php
// List all messages for the plugin
$msgs = message::all('siaDC09');
foreach ($msgs as $m) {
    $m->getLogicalId();   // 'supervision_timeout', 'bad_csr_response', etc.
    $m->getOccurrences(); // increments on duplicate logicalId+plugin
    $m->getMessage();     // user-facing text
    $m->getDate();        // first seen
    $m->getLastDate();    // last increment
}

// Clear all messages for the plugin
message::removeAll('siaDC09');
```

### Triggering Alarm Commands via PHP CLI

```bash
sudo -u www-data php -r "
require '/var/www/html/core/php/core.inc.php';
\$eq = siaDC09::byType('siaDC09')[0];
\$cmd = \$eq->getCmd('action', 'burglarAlarm');
\$cmd->execCmd(['title' => 'Piece1']);
echo 'done'.PHP_EOL;
"
```

`title` is the zone name (per `siaDC09Cmd::execute()` extracts `$_options['title']` → daemon `zone` field).

### Simulating CSR Behaviors

| Goal | Method |
|---|---|
| ACK (normal) | Simulator running with matching account `--account 000001` |
| Silent drop / timeout | `pkill -f "tests.simulator"` — daemon receives no response |
| NAK (account mismatch) | Simulator running with `--account FFFFFF` while daemon uses `000001` |
| NAK (encryption mismatch) | Configure daemon with encryption + wrong key, simulator without — not used in this story |
| Garbled response | Not directly supported by simulator. If an AC requires it, fall back to documenting behavior or use `nc` to send hand-crafted bytes — out of scope for this story. |

### Dedup Mechanics (Important for AC2 + AC6)

**Jeedom `message::add(plugin, message, action, logical_id)`** stores rows in the `message` table. When called again with the same `(plugin, logical_id)` pair, Jeedom finds the existing row and increments its `occurrences` column rather than creating a new row. This is what produces the "T1 dedup" behavior.

**`_sm1_t3_fired` flag** in the daemon prevents `_notify(SUPERVISION_DISCONNECTED)` from firing more than once while the daemon stays in DEGRADED(strike=3). Reset to `False` on:
1. ACK received → SM1→HEALTHY (daemon.py around line 880–910)
2. TCP reconnect success → SM1→INITIALIZING (TCP only — not exercised here)

**Notification queue plugin dedup** is the responsibility of the configured notification command. The current test setup uses a simple `Notify` virtual cmd that does NOT dedup — every `execCmd()` is a separate notification. This is fine for our verification: we count `execCmd` invocations directly.

### What This Story Does NOT Test

- **Encryption-related NAK paths:** Encryption is disabled in current VM config — not tested.
- **`_send_raw()` OS-level errors** (EAGAIN/ECONNRESET/EPIPE) — these are absorbed as `{status: 'timeout'}` per design — already covered by the timeout-path testing in Task 8.
- **`_queue_consumer()` SM1=NO_NETWORK at dequeue → `EVENT_FAILED`** — UDP has no NO_NETWORK state.

### Previous Story Intelligence (12-4, 12-5, 12-6 takeaways)

**From 12-4:**
- T1 fires at `strike=1` only (single alert, not at strike=2 — implementation decision); T3 fires at strike=3.
- `_sm1_t3_fired` reset on ACK was verified: stop simulator → T3 → restart → T3 fires again on next disconnect (Task 4.6 in 12-4). This story re-validates that flow with extra dedup checks (Task 5).
- `cron5()` freshness check fires its own message center entry (`"ALERTE siaDC09 : Le démon est actif mais ne répond plus depuis Ns"`) — this is unrelated to the T1/T2/T3 system and should NOT appear in this story's task results unless the daemon is frozen with SIGSTOP (don't trigger this here).

**From 12-5:**
- BAD_CSR_RESPONSE on alarm path was verified — message starts with `"La centrale a renvoyé une réponse"`, no CRITIQUE prefix, notify cmd triggered exactly once (no retry on NAK).
- EVENT_FAILED on alarm timeout path was verified — message contains `"CRITIQUE —"`, French label `"intrusion"`, zone, retry count.
- `event_state` persists across daemon restart (not relevant here, but knowing the SM2 state model helps when interpreting `event_state` values).

**From 12-6:**
- Diagnostic tab error panel (`Vider`/`Actualiser`) is the visual surface for `sia_last_errors`. This story validates the underlying data, not the UI (UI was 12-6).
- `Vider` in the error panel only clears `sia_last_errors` config, NOT message center entries. To clear message center, use `message::removeAll('siaDC09')`.
- `csr_simulator.py` was patched in 12-6 to bind `0.0.0.0` (was `127.0.0.1`) — already in `master`; do not re-fix.

### Bugs Found in 12-6 That May Impact This Story

| Bug (12-6) | Status | Impact on 12-7 |
|---|---|---|
| `siaDC09.ajax.php:138` `json_decode()` on array | Fixed in 12-6 | None — only affects diagnostic panel |
| `desktop/js/siaDC09.js` AJAX `data.state` not checked | Fixed in 12-6 | None |
| `csr_simulator.py` hardcoded `127.0.0.1` bind | Fixed in 12-6 | None — already running fine |

### Anti-Patterns to Avoid

- **Do not edit `error_handler.py`, `daemon.py`, or `messages.py` unless a bug is found.** All design has been frozen across 11 adversarial reviews — random tweaks risk regression.
- **Do not introduce a `--drop-ack-count` or `--mode=nak-always` flag in the simulator.** It does not exist (per 12-4 Dev Notes: "epic AC mentioned it but it's a proposed behavior, not implemented"). Use `pkill` for timeouts and account-mismatch for NAKs.
- **Do not trust epic AC text verbatim.** Where 12-7 epic AC says "T2 → BAD_CSR_RESPONSE on supervision-NAK," the implementation may route undecodable supervision NAKs to T2 (BAD_CSR_RESPONSE) and parseable timestamp-NAKs to T1 (SUPERVISION_NAK). Document the actual path observed (Task 6.5).
- **Do not re-test what 12-4/12-5 already verified.** Focus on the *delta*: dedup mechanics (AC2), T1 auto-resolve (AC4), T3 re-fire after recovery (AC5), French audit (AC9), error_update payload contract (AC9).

### Reference Files

- `docs/design/error-handler-design.md` — full 3-tier model + message catalog + privacy rules
- `docs/design/logging-design.md` — message externalization rules
- `docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` §5.5.3.2 — NAK protocol semantics
- `_bmad-output/implementation-artifacts/12-4-supervision-loop-strike-recovery.md` — supervision/T1/T3 supervision context
- `_bmad-output/implementation-artifacts/12-5-alarm-delivery-end-to-end.md` — alarm/T2/T3 event context
- `_bmad-output/implementation-artifacts/12-6-widget-debug-ui-rendering.md` — diagnostic UI surface for `sia_last_errors`

### Project Structure Notes

- This story does not create or move files. All work happens against the existing daemon/PHP code on the VM. If a bug fix is required, edit the existing source file in-place (bind-mounted from the local repo so changes take effect immediately on daemon restart).

### Testing Standards Summary

This is a Level 3 (`tests/level3/`) integration test executed manually on the real Jeedom VM. No automated test suite is added or modified by this story. If a bug is fixed, add or extend a Level 1 unit test in `tests/level1/test_error_handler.py` or similar, per the testing rule "pytest only, simple assert, mandatory docstring + assert comments."

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Debug Log References

(to be filled by dev agent)

### Completion Notes List

(to be filled by dev agent — one bullet per AC, with PASS/FAIL/BLOCKED and observation)

### File List

(empty unless bug fixes required)
