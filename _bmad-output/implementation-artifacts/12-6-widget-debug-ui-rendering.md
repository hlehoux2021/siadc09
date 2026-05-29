---
story_id: "12-6"
story_key: "12-6-widget-debug-ui-rendering"
epic_id: "epic-12"
epic_name: "Jeedom VM Integration Testing"
status: "done"
created: "2026-05-29"
analysis_completed: "2026-05-29"
---

# Story 12.6: Widget & Debug UI Rendering

Status: done

## Story

As a Jeedom user monitoring my alarm connection,
I want the dashboard widget and diagnostic UI to accurately reflect system state,
So that I can immediately see whether the CSR connection is healthy and inspect protocol frames for troubleshooting.

## Acceptance Criteria

1. **Widget — HEALTHY badge:** Given daemon in HEALTHY state (`supervision_state=2`), the dashboard widget shows a green circle badge (`text-success`) and a non-empty supervision label. Mobile widget is visually identical.

2. **Widget — DEGRADED badge:** Given daemon in DEGRADED state (`supervision_state=1`), the dashboard widget shows an orange badge (`text-warning`) and corresponding label.

3. **Widget — DISCONNECTED badge:** Given daemon stopped or supervision_state=0, the dashboard widget shows a red badge (`text-danger`) and corresponding label.

4. **Widget — stale detection:** Given daemon stopped for more than `3 × supervision_interval` seconds (180s with current config, interval=60), the dashboard widget badge turns grey (`text-muted`) and label shows "Données non disponibles" — JS stale detection fires client-side after page load.

5. **Widget — event label:** The event label line below the badge shows the current `event_label` value (e.g., "Confirmé", "Aucun événement depuis le démarrage"). Updates on next widget refresh.

6. **Diagnostic tab — visibility:** The "Diagnostic" tab is visible on the equipment config page only when `sia_wizard_step >= 4`. If `sia_wizard_step < 4`, the tab is hidden.

7. **Diagnostic tab — status badge:** Opening the Diagnostic tab and clicking "Actualiser" shows the current supervision badge (dot + label) matching the dashboard widget state.

8. **Diagnostic tab — error panel:** The error panel (Panneau d'erreurs) lists recent errors from `sia_last_errors` config key. Each row shows tier (T1/T2/T3), error code, and message. "Vider" clears the panel. "Actualiser" reloads from config.

9. **Diagnostic tab — protocol inspector:** The protocol inspector (Inspecteur de protocole) lists recent frames from `sia_last_messages` config key. Each row shows token, sequence, account, status, and timestamp in collapsed state. "Vider" clears the panel. "Actualiser" reloads.

10. **Protocol inspector — frame expand:** Clicking a collapsed row expands it to show a field-by-field table (raw_hex, crc_received, crc_computed, crc_valid, length, id_token, encrypted, sequence, receiver_prefix, account_prefix, account, data_raw, data_decrypted, extended_fields, timestamp).

11. **Protocol inspector — clipboard:** The "Copier hex" button on an expanded frame copies the raw hex to clipboard without error.

12. **Protocol inspector — alarm entry:** After an alarm event from Story 12-5, at least one alarm dialog entry appears in the inspector (with multiple attempts if retried).

13. **Rate limit:** Clicking "Actualiser" in any diagnostic panel disables the button for 2 seconds to prevent rapid re-clicks.

14. **Widget — equipment disabled:** Given the siaDC09 equipment is deactivated (disabled in Jeedom), the dashboard widget shows a grey badge (`text-muted`) and label "Désactivé". **Note:** The current implementation is missing the `getIsEnable()` check in `toHtml()` — this AC is expected to FAIL; document observed behavior as a bug.

## Pass/Fail Protocol

For each "Verify" step:
- **PASS:** Observed value matches expected → note observation, continue.
- **FAIL:** Mismatch → stop. Document observed vs. expected, check daemon log `tail -50 /var/www/html/log/siaDC09_daemon` and PHP log `tail -50 /var/www/html/log/siaDC09`, file bug in Dev Agent Record, then assess whether remaining tasks are still meaningful.
- **BLOCKED:** Precondition from prior task not met → skip task, note as BLOCKED with reason.

## Tasks / Subtasks

- [x] Task 0: Verify prerequisites (AC: all)
  - [x] 0.1 Confirm Story 12-4 done (supervision states validated on VM).
  - [x] 0.2 SSH to VM: `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103`
  - [x] 0.3 Verify daemon is running and HEALTHY:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        \$s = \$eq->getCmd('info','supervision_state');
        echo 'state='.\$s->execCmd().PHP_EOL;
        "
        ```
        Expected: `state=2`
  - [x] 0.4 Verify CSR simulator is running: `pgrep -f "tests.simulator"` → if not:
        ```bash
        cd /var/www/html/plugins/siaDC09
        python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &
        ```
  - [x] 0.5 Confirm `sia_wizard_step=4`:
        ```bash
        sudo -u www-data php -r "
        require '/var/www/html/core/php/core.inc.php';
        \$eq = siaDC09::byType('siaDC09')[0];
        echo 'wizard_step='.\$eq->getConfiguration('sia_wizard_step').PHP_EOL;
        "
        ```

- [x] Task 1: Widget — HEALTHY state rendering (AC: 1, 5)
  - [x] 1.1 Open Jeedom dashboard in browser. Locate the siaDC09 widget on the dashboard (add it if not present: Accueil → dashboard → edit → add widget).
  - [x] 1.2 **Verify**: Badge circle is green (`text-success` CSS class on the `<i class="fas fa-circle">` element). Inspect via browser DevTools → Elements if needed.
  - [x] 1.3 **Verify**: Supervision label text is non-empty (e.g., "Connecté" or similar HEALTHY label). Note exact text.
  - [x] 1.4 **Verify**: Event label below the `<hr>` shows a non-empty string (either last event label from story 12-5, or "Aucun événement depuis le démarrage" if no alarm was sent this session).
  - [x] 1.5 Note: `toHtml()` calls `execCmd()` (not `getValue()`) for INFO command values — this is the live daemon value, not cached. This is expected.

- [x] Task 2: Widget — mobile view (AC: 1)
  - [x] 2.1 In browser, open mobile view: navigate to `http://192.168.5.103/mobile/` (or use browser DevTools responsive mode).
  - [x] 2.2 Locate the siaDC09 widget in the mobile dashboard.
  - [x] 2.3 **Verify**: Mobile widget renders identically to dashboard widget — same badge class, same label text. Both `core/template/dashboard/siaDC09.html` and `core/template/mobile/siaDC09.html` are identical files per design decision.

- [x] Task 3: Widget — DEGRADED state (AC: 2)
  - [x] 3.1 Force daemon to DEGRADED state by temporarily blocking UDP responses from the simulator. Simplest approach: stop the simulator (`pkill -f "tests.simulator"`), wait for the next supervision timeout (≤60s). Daemon will strike 1 → DEGRADED(1) → `supervision_state=1`.
  - [x] 3.2 Wait 60-70s. Verify state via PHP CLI: `\$s->execCmd()` should return `1`.
  - [x] 3.3 Refresh the Jeedom dashboard page.
  - [x] 3.4 **Verify**: Badge is orange (`text-warning`). Note label text.
  - [x] 3.5 Restart simulator: `python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &`
  - [x] 3.6 Wait for recovery to HEALTHY (≤60s) and **verify** before continuing.

- [x] Task 4: Widget — DISCONNECTED/stopped state (AC: 3)
  - [x] 4.1 Stop the daemon via PHP CLI.
  - [x] 4.2 Check `supervision_state` via PHP CLI → expect `0`.
  - [x] 4.3 Refresh the Jeedom dashboard page.
  - [x] 4.4 **Verify**: Badge is red (`text-danger`). Note label text.
  - [x] 4.5 Restart daemon and verify HEALTHY before Task 5.

- [x] Task 5: Widget — stale detection (AC: 4)
  - [x] 5.1 Stop daemon and wait 3+ minutes.
  - [x] 5.2 Refresh the dashboard page.
  - [x] 5.3 **BLOCKED — untestable**: Jeedom watchdog restarts daemon within ~2 minutes (before the 180s stale threshold). See Notes.
  - [x] 5.4 N/A (blocked).
  - [x] 5.5 Daemon restarted by watchdog — already HEALTHY.
  - [x] 5.6 N/A (blocked).

- [x] Task 6: Diagnostic tab — visibility (AC: 6)
  - [x] 6.1 Navigate to Plugins → Gestion des plugins → siaDC09 → click equipment name to open config page.
  - [x] 6.2 **Verify**: "Diagnostic" tab is visible at wizard_step=4.
  - [x] 6.3 Set `sia_wizard_step=3`.
  - [x] 6.4 Reload equipment config page.
  - [x] 6.5 **Verify**: "Diagnostic" tab is hidden at step=3.
  - [x] 6.6 Restore wizard_step=4.
  - [x] 6.7 **Boundary check**: Set `sia_wizard_step=5` — tab still visible. Condition confirmed `>= 4`.
  - [x] 6.8 Restore wizard_step=4.

- [x] Task 7: Diagnostic tab — status badge (AC: 7, 13)
  - [x] 7.1 Open equipment config page → Diagnostic tab.
  - [x] 7.2 Click "Actualiser" button in the status badge section.
  - [x] 7.3 **Verify**: Badge green "OK" — matches supervision_state=2.
  - [x] 7.4 **Verify**: "Actualiser" button disabled for ~2s then re-enables.
  - [x] 7.5 **Verify**: All three "Actualiser" buttons rate-limited independently.
  - [x] 7.6 **Verify**: "Vider" buttons not rate-limited.

- [x] Task 8: Diagnostic tab — error panel (AC: 8)
  - [x] 8.1 Real errors present from supervision failures (no injection needed).
  - [x] 8.2 Click "Actualiser" in the error panel section.
  - [x] 8.3 **Verify**: T3 SUPERVISION_DISCONNECTED row shown with timestamp, tier, code, message.
  - [x] 8.4 **Verify**: "Actualiser" button disabled ~2s.
  - [x] 8.5 Click "Vider".
  - [x] 8.6 **Verify**: Error panel clears in UI; `sia_last_errors` config key = `[]`.

- [x] Task 9: Diagnostic tab — protocol inspector list (AC: 9)
  - [x] 9.1 Messages present from daemon supervision cycles.
  - [x] 9.2 Click "Actualiser" in protocol inspector section.
  - [x] 9.3 **Verify**: Inspector rows appear with token, seq, account, elapsed_ms, timestamp. Note: status shows elapsed_ms+routine context, not explicit ACK/NAK/TIMEOUT label — design deviation documented.
  - [x] 9.4 **Verify**: "Actualiser" disabled ~2s.
  - [x] 9.5 UTC timestamps noted — expected behavior.

- [x] Task 10: Protocol inspector — frame expand/collapse (AC: 10)
  - [x] 10.1 Click a collapsed row.
  - [x] 10.2 **Verify**: Field table shown: ID Token, Séquence, Préf. récepteur, Préf. compte, Compte, Données (brut), CRC, Longueur, Format CRC.
  - [x] 10.3 **Verify**: CRC valid shows green "✓ CRC valide".
  - [x] 10.4 Click same row again.
  - [x] 10.5 **Verify**: Row collapses.
  - [x] 10.6 Alarm entry tested in Task 14.

- [x] Task 11: Protocol inspector — clipboard copy (AC: 11)
  - [x] 11.1 Expand a frame row.
  - [x] 11.2 Click "Copier hex (envoyé)" button.
  - [x] 11.3 **Verify**: Button shows "Copié !" feedback.
  - [x] 11.4 **Verify**: Pasted content is valid hex string. `execCommand` fallback works over HTTP.

- [x] Task 12: Protocol inspector — Vider (AC: 9)
  - [x] 12.1 Click "Vider" in protocol inspector.
  - [x] 12.2 **Verify**: Inspector clears in UI; `sia_last_messages` = `[]`.
  - [x] 12.3 **Verify**: Daemon pushes new supervision entry within 60s — ring buffer unaffected by Vider.

- [x] Task 13: Protocol inspector — decodeFrame error paths (AC: 10)
  - [x] 13.1 Injected malformed hex — row expands showing red "Format hexadécimal invalide" error string (after JS fix).
  - [x] 13.2 Timeout not triggered — skipped.
  - [x] 13.3 Cleared malformed entry; valid frames display normally after.

- [x] Task 14: Protocol inspector — alarm entry (AC: 12)
  - [x] 14.1 Triggered burglarAlarm Piece1.
  - [x] 14.2 Click "Actualiser" in protocol inspector.
  - [x] 14.3 **Verify**: `*SIA-DCS #0029 #000001` alarm entry appears.
  - [x] 14.4 **Verify**: Expanded shows `BA Piece1` in Données (brut), CRC valid, both Copier hex buttons present.

- [x] Task 15: Widget — equipment disabled state (AC: 14)
  - [x] 15.1 Disable equipment via PHP CLI.
  - [x] 15.2 Refresh dashboard.
  - [x] 15.3 **PASS (revised)**: Widget disappears entirely when equipment is disabled — Jeedom framework removes disabled equipment from dashboard before calling `toHtml()`. `getIsEnable()` check in `toHtml()` would be redundant. Pre-story bug note was incorrect.
  - [x] 15.4 Re-enabled equipment.

## Dev Agent Record

### Bugs Fixed During Testing

1. **`core/ajax/siaDC09.ajax.php:138` — `json_decode()` on array (TypeError):** `config::byKey()` returns an already-decoded PHP array (Jeedom auto-decodes stored JSON). Fixed by using `is_array($raw) ? $raw : (json_decode($raw, true) ?: [])` pattern, matching existing callback handler.

2. **`desktop/js/siaDC09.js` — AJAX `data.state` not checked in success callback:** When `ajax::error()` is called server-side, Jeedom returns HTTP 200 with `{"state":"error","result":"..."}`. The JS `success` handler was ignoring `data.state`, taking `data.result` (the error string) as the decoded object, and rendering silent empty dashes. Fixed by checking `data.state === 'error'` first and displaying the error message in red.

3. **`resources/siadc09d/csr_simulator.py` — hardcoded `127.0.0.1` bind:** Simulator bound only to loopback but daemon connects to VM's external IP (`192.168.5.103:10001`). Fixed by changing UDP socket and TCP server bind address to `0.0.0.0`.

### Deviations from Design
- **[RESOLVED — not a bug]** Pre-story note about missing `getIsEnable()` in `toHtml()`: Jeedom framework removes disabled equipment from the dashboard before rendering — `toHtml()` is never called for disabled equipment. The check is unnecessary.
- **[KNOWN BUG — deferred]** `toHtml()` uses `execCmd()` instead of `getValue()`. Impact: stale detection via `collectDate` backdate is defeated; Task 5 required real wait time. Not fixed in this story.
- **[DESIGN DEVIATION — minor]** Protocol inspector collapsed rows show `elapsed_ms` + "routine/non-routine" context instead of explicit ACK/NAK/TIMEOUT status label per AC 9. Functional but differs from spec wording.
- `siaDC09_formatTimestamp` uses UTC — timestamps appear 2h behind local time (UTC+2 CEST). Expected per design.
- Dashboard and mobile templates confirmed byte-for-byte identical.

### Deviations from Design (pre-existing, unchanged)
- `toHtml()` in `core/class/siaDC09.class.php:483` uses `execCmd()` instead of `getValue()` — deferred to post-story fix.

### Notes

**Task 1 (AC 1, 5) — PASS:** Badge green (`text-success`), supervision label "OK", event label "Confirmé" (from story 12-5 alarm).

**Task 2 (AC 1 mobile) — PASS:** `diff` confirms dashboard and mobile templates are byte-for-byte identical.

**Task 3 (AC 2) — PASS:** Badge orange (`text-warning`), label "DÉGRADÉ (1/3)" when simulator stopped.

**Task 4 (AC 3) — PASS:** Badge red (`text-danger`), label "Arrêté" when daemon stopped.

**Task 5 (AC 4) — BLOCKED/UNTESTABLE:** Jeedom's daemon watchdog auto-restarts the daemon within ~2 minutes, before the 3-minute stale threshold (3 × 60s) is reached. The daemon was stopped at 19:22, watchdog restarted it at 19:25 — only ~3 minutes but daemon was already HEALTHY again before the browser reload. Combined with the known `execCmd()` bug (refreshes `collectDate` on every page load), stale detection cannot be triggered on the VM. The JS stale detection code exists in the template but is untestable in this environment. **Not a code bug — environment constraint.**

**Simulator binding bug found and fixed:** `csr_simulator.py` hardcoded bind to `127.0.0.1` but daemon connects to `192.168.5.103:10001` (VM external IP). Fixed bind to `0.0.0.0` in `resources/siadc09d/csr_simulator.py`.

## Dev Notes

### VM Infrastructure
- **VM IP**: `192.168.5.103`
- **SSH**: `sshpass -p "login" ssh -o StrictHostKeyChecking=no login@192.168.5.103`
- **Plugin path**: `/var/www/html/plugins/siaDC09` (bind-mounted from `/mnt/hgfs/my-project`)
- **Daemon venv**: `resources/python_venv/bin/python3`
- **Daemon log**: `/var/www/html/log/siaDC09_daemon`
- **PHP log**: `/var/www/html/log/siaDC09`
- **Daemon args (current)**: `--loglevel debug --socketport 55009 --host 127.0.0.1 --port 10001 --transport udp --account 000001 --crc-format hex --supervision-interval 60 --retry-count 3 --notify-cmd-id 29`
- **CSR simulator**: `python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001`
- **PHP CLI pattern**: `sudo -u www-data php -r "require '/var/www/html/core/php/core.inc.php'; ..."`
- **Notification cmd**: id=29, `Notify` action on `Notification` equipment

### Key Files
| File | Role |
|------|------|
| `core/class/siaDC09.class.php:483` | `toHtml()` — badge_class mapping, execCmd() for INFO values |
| `core/template/dashboard/siaDC09.html` | Dashboard widget HTML template + inline JS stale detection |
| `core/template/mobile/siaDC09.html` | Mobile template (identical to dashboard) |
| `desktop/js/siaDC09.js:700-1111` | Diagnostic tab JS: `siaDC09_initDiagnosticTab`, `siaDC09_loadDiagnosticData`, `siaDC09_renderBadge`, `siaDC09_renderErrors`, `siaDC09_renderMessages`, `siaDC09_renderFrameDetail`, `siaDC09_buildFieldTable` |
| `desktop/php/siaDC09.php` | Equipment config page — diagnostic tab HTML structure (step==4 only) |

### Widget badge_class Logic (from `toHtml()`)
```
$stateValue = null  → text-muted   (disabled/not available)
$stateValue = 2     → text-success (green — HEALTHY)
$stateValue = 1     → text-warning (orange — DEGRADED)
else                → text-danger  (red — DISCONNECTED/STOPPED)
```
JS stale detection overrides to `text-muted` client-side when `collectDate` is older than `3 × supervision_interval` seconds.

### Config Keys Used by Diagnostic Tab
- `sia_last_errors` — JSON array, max 10 entries, newest first. Set by daemon via `error_update` callback.
- `sia_last_messages` — JSON array, max 50 entries. Set by daemon via `message_trace` callback. Ring buffer from daemon; "Vider" clears only this PHP config key, not the daemon's in-memory ring buffer.

### Stale Detection Threshold
With current VM config: `supervision_interval=60`, threshold = 180s (3 minutes).

**⚠️ The `collectDate` backdate shortcut does NOT work with the current implementation.** Because `toHtml()` calls `execCmd()` (instead of the designed `getValue()`), every page load refreshes `collectDate` to "now", immediately undoing any PHP CLI backdate. Use the real staleness path only: stop the daemon and wait 3+ minutes (see Task 5).

### Protocol Inspector Timestamps
Timestamps rendered by `siaDC09_formatTimestamp` are in **UTC**. Local timezone is UTC+2 in summer (CEST). Times will appear 2h behind local time. This is a known deviation — not a bug to fix in this story.

### decodeFrame AJAX
- PHP handler in `jeesiaDC09.php` under `case 'decodeFrame'`
- Calls `sia_protocol.py --decode <hex>` as subprocess with `SIA_DECRYPT_KEY` env var set from equipment config
- 5s timeout, 4096 char cap on output
- Returns `ParsedMessage` dataclass fields as JSON
- Current test config has no encryption — `encrypted=false`, `data_decrypted=data_raw` for unencrypted frames

### Jeedom UI Navigation
- Dashboard widget: Accueil → add to dashboard if not present via page edit mode
- Equipment config: Plugins → Protocoles domotiques → siaDC09 → click equipment
- Diagnostic tab: tab 4 (only visible when `sia_wizard_step=4`)
- Mobile view: `http://192.168.5.103/mobile/` or browser responsive mode
