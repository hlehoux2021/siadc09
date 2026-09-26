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

Status: done — code review 2026-09-26 of the reopen→close reasoning trail: 1 decision resolved (AC8's
cross-story account mismatch confirmed benign by Herve), 2 patches applied (corrected two "per this story's
own Pass/Fail Protocol" framings that weren't accurate — AC9 and the AC10/AC11 transfer are honest overrides/
open gaps, not protocol-compliant closures), 2 dismissed as noise.

> **Réouverte 2026-09-18.** Le statut `done` était faux : la passe UDP (AC1–AC7, Tasks 0–7) est
> validée, mais la passe TCP (AC8–AC11, Tasks 8–13, ajoutée le 2026-06-01) n'a jamais été exécutée —
> et c'est TCP qui est le transport réel du récepteur de production. Descoper la passe TCP est donc
> exclu : c'est UDP qui n'existe pas sur le terrain, pas l'inverse.
>
> Périmètre restant après dédoublonnage :
> - **AC8** → coché, satisfait par la preuve terrain de la story 8.2 (AC15 / Task 11.9). Reste une
>   confirmation d'une ligne de `event_state=1` sur l'hôte, cf. Task 9.
> - **AC9** (FA/PA sur TCP) → seule exécution encore due dans 12-5, cf. Task 10.
> - **AC10 / AC11** (NAK et timeout sur TCP) → **transférés à la story 12-7, Task 12** (12.1 et 12.2),
>   qui les portait déjà mot pour mot. 12-7 Task 10 fait déjà la reconfiguration TCP. Ne pas rejouer
>   ici.

## Story

As a Jeedom user with an alarm system,
I want alarm events delivered to the CSR and confirmed,
So that my home is protected by professional monitoring.

## Acceptance Criteria

1. **Happy path — burglarAlarm ACK:** Given daemon in HEALTHY state, when triggering `burglarAlarm` action command with zone="Piece1", then daemon receives the action via `sendToDaemon()`; SIA frame with BA event code is sent to CSR simulator; simulator ACKs; `event_state` → 1 (`"Confirmé"`); `event_label` → `"Confirmé"`; ring buffer has an alarm dialog entry (`dialog_type: "alarm"`).

2. **All event types — ACK path:** Same happy-path flow for `fireAlarm` (FA code) and `panicAlarm` (PA code).

3. **Zone handling:** Triggering alarm with zone="Piece1" → the SIA frame visible in the protocol inspector carries the **zone order number**, zero-padded to 3 digits (`[#001234|BA 001]`), never the zone label. Triggering with a zone label absent from `sia_zone_mappings` → the frame carries **no zone field at all** (`[#001234|BA]`), a WARNING naming the label is logged, the alarm is still sent. Triggering without zone (empty title) → same as unresolved: `[#001234|BA]`, no crash. Amended 2026-09-17 — see Story 8.2 AC11–AC15 (the original wording expected the zone label in the frame, which Epic 12 testing showed to be wrong for a CSR).

4. **NAK path — T2 notification:** Given CSR simulator replaced with a custom NAK responder (mismatch account or key), when triggering `burglarAlarm` with zone="Piece1", then `event_state` → 2 (`"Échoué"`); T2 `BAD_CSR_RESPONSE` notification fires (message center entry + notification command triggered, **no** "CRITIQUE" prefix); daemon does NOT retry after NAK (immediate failure).

5. **Timeout path — T3 notification:** Given CSR simulator stopped (silent drop), when triggering `burglarAlarm` with zone="Piece2", then daemon retries up to 3 times with 1s backoff; after max retries exhausted, `event_state` → 2 (`"Échoué"`); T3 `EVENT_FAILED` fires: message center entry with `"CRITIQUE —"` prefix + notification command triggered.

6. **Ring buffer alarm entry:** After each alarm attempt (ACK or FAIL), ring buffer contains an alarm dialog entry viewable in the protocol inspector (`dialog_type: "alarm"`).

7. **event_state persists across restart:** After a CONFIRMED alarm, stop and restart daemon; `event_state` still shows 1 (`"Confirmé"`) — not reset to 0 (IDLE is startup-only, not re-entered).

8. **TCP — alarm happy path (burglarAlarm ACK):** Given daemon configured with TCP transport (real receiver `192.168.100.15:10002`, or a local TCP simulator), when triggering `burglarAlarm` with zone="Piece1", then `event_state` → 1 (`"Confirmé"`) after ACK received over TCP. Daemon log shows BA frame sent and ACK received via TCP.
   **PASS partiel 2026-09-17 22:01:49** — preuve terrain sous story 8.2 AC15 / Task 11.9 : trame BA émise en **TCP** vers le récepteur réel `192.168.100.15:10002` (account `001234`, `crc_format=hex`, chiffrement off) et **ACQUITTÉE** :
   `D741003A"SIA-DCS"0010L0#001234[#001234|BA 001]_22:01:49,09-17-2026`.
   Reste dû : la lecture de `event_state=1` / `event_label="Confirmé"` n'a pas été relevée dans cette preuve (Task 9.2).

9. **TCP — all event types ACK path:** Same TCP happy path confirmed for `fireAlarm` (FA code) and `panicAlarm` (PA code). — **Seul AC encore entièrement à exécuter dans 12-5** (Task 10).

10. **TCP — NAK path (T2 BAD_CSR_RESPONSE):** Same as AC4 but over TCP: `event_state=2`, T2 fires with no CRITIQUE prefix, no retry. Daemon immediately marks SM2 FAILED on NAK over TCP.
    **→ Transféré 2026-09-18 à la story 12-7, Task 12.1** (AC5 — variante TCP), qui décrit le même test mot pour mot. Ne pas rejouer ici ; c'est 12-7 qui porte la preuve.

11. **TCP — timeout path (T3 EVENT_FAILED):** Same as AC5 but over TCP: simulator stopped → TCP connection refused → daemon retries up to 3 times → EVENT_FAILED T3 fires with "CRITIQUE —" prefix. Daemon log shows 3 retry attempts over TCP.
    **→ Transféré 2026-09-18 à la story 12-7, Task 12.2** (AC7 — variante TCP). Même remarque.

## Pass/Fail Protocol

For each "Verify" step:
- **PASS:** Observed value matches expected → note observation, continue.
- **FAIL:** Mismatch → stop. Document observed vs. expected, check daemon log `tail -50 /var/www/html/log/siaDC09_daemon` and PHP log `tail -50 /var/www/html/log/siaDC09`, file bug in Dev Agent Record, then assess whether remaining tasks are still meaningful.
- **BLOCKED:** Precondition from prior task not met → skip task, note as BLOCKED with reason.

## Tasks / Subtasks

- [x] Task 0: Wire alarm plugin outbreak to siaDC09 burglarAlarm command (prerequisite)
  - [x] 0.1 In Jeedom UI → alarm plugin "Alarme" equipment → "Déclenchement" tab → "outbreak" action (currently `message`): add a siaDC09 `burglarAlarm` action with title set to `#zone#` (the only zone tag the alarm plugin substitutes — it yields the zone **label**, e.g. `Salon`; `#name_zone#` does not exist, corrected 2026-09-17) alongside the existing message action.
        This makes real Detecteur1/2 triggers call the full chain automatically.
  - [x] 0.2 Verify the outbreak action list now shows both the message action and the burglarAlarm action.
  - [x] 0.3 Note: Tasks 2–7 can also be triggered directly via PHP CLI (no alarm plugin needed), which is faster and more reliable for systematic testing. Use the alarm plugin trigger only for the full integration variant (subtask 2.7).

- [x] Task 1: Prepare test environment (AC: all)
  - [x] 1.1 Verify daemon is running and HEALTHY (`supervision_state=2`): via PHP CLI or Jeedom UI
  - [x] 1.2 Verify CSR simulator is running: `pgrep -f "tests.simulator"` → if not: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --udp-port 10001 --host 127.0.0.1 --account 000001 &`
        **Superseded 2026-09-17, nuancé 2026-09-18:** le simulateur n'est plus la *cible de validation*. Toute preuve de PASS terrain se fait contre le récepteur SIA interne `192.168.100.15` / `test-sia-internal.lehoux.net`, **port 10002, TCP, account `001234`**, `crc_format=hex`, chiffrement off.
        Le simulateur n'est pas pour autant invalidé : il reste l'outil légitime — et le seul — pour provoquer les comportements que le récepteur réel ne produira pas à la demande (NAK, silence total, account non concordant). Les blocs `python3 -m tests.simulator` des tasks ci-dessous sont conservés à ce titre.
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

- [x] Task 8: TCP transport setup for alarm tests (AC: 8, 9)
  - [x] 8.0 **DONE (2026-09-24).** Daemon reconfigured and confirmed running with `--host
        192.168.100.15 --port 10002 --transport tcp --account 001234 --crc-format hex` (verified via
        `ps aux | grep siadc09`). This is the current live config on `test-jeedom.lehoux.net`.
  - [ ] 8.1 *(variante simulateur)* Not used — the real-receiver path (8.0) is authoritative and was
        used throughout.
  - [x] 8.2 **DONE (2026-09-24).** Daemon cmdline confirmed `--transport tcp` + `192.168.100.15:10002`.
        `supervision_state=2` not re-confirmed at this exact instant (a supervision disconnect/reconnect
        cycle was observed shortly after — see Task 9 note below) but was confirmed repeatedly earlier
        today under the same TCP config during story 14-2's live validation session (dozens of
        successful supervision ACKs against this same receiver).
  - [x] 8.3 **DONE (2026-09-24).** Ring buffer / error state cleared before the Task 9 trigger.

- [x] Task 9: TCP — burglarAlarm happy path (AC: 8) — **CLOSED on cumulative evidence (Herve, 2026-09-24)**
      This session's own fresh trigger (9.1, zone="Piece1") hit two artifacts, documented rather than
      hidden: (a) "Piece1" no longer resolves in the current `sia_zone_mappings` table (today's 14-2
      session remapped zones to `Zone1`/`Zone2`) — the daemon log confirms `zone=Piece1,
      zone_number=None`, which is AC3's designed no-match fallback (frame sends with no zone field,
      never a crash), not a code defect; (b) the trigger landed during a transient supervision
      disconnect/reconnect window (`SUPERVISION_DISCONNECTED` at 16:58:51, reconnect backoff in
      progress), so the `event_state=1`/`event_label` read immediately after was stale leftover from an
      earlier alarm, not a fresh confirmation of this specific trigger — the reachability of
      `192.168.100.15:10002` at that exact moment was not independently re-verified before closing.
  - [x] 9.1/9.2/9.3 **Closed on the day's cumulative TCP evidence, not a clean isolated re-run**: story
        14-2's live validation session (2026-09-24, same day, same receiver `192.168.100.15:10002`,
        same TCP transport) produced numerous independent `burglarAlarm` deliveries with `SM2 confirmed`
        / `Centrale confirmée — alarme BA transmise` log lines and real received `[#20881|BA 002]`-style
        ACKed frames — functionally identical machinery to what AC8/9.1-9.3 asks for (event_state's SM2
        CONFIRMED mapping = 1, per the SM2→event_state table in Dev Notes). AC8 is satisfied by this
        cumulative evidence; the single fresh attempt this task itself made was inconclusive due to the
        supervision blip noted above.

- [x] Task 10: TCP — all event types ACK path (AC: 9) — **CLOSED on Herve's explicit call (2026-09-24),
      not independently executed for FA/PA**
      fireAlarm/panicAlarm over TCP were **not** actually triggered this session — today's extensive
      live testing was entirely `burglarAlarm`-focused (story 14-2's scope explicitly excludes PA/FA).
      Closed instead on: (a) `fireAlarm`/`panicAlarm` share the exact same dispatch machinery as
      `burglarAlarm` end-to-end (`_EVENT_SIA_CODES` mapping, `_send_with_retry()`, `_build_event_frame()`
      — see Dev Notes' Alarm Command Execution Chain — differing only in the SIA event code string and
      command name, no event-type-specific branching anywhere in the send path); (b) the UDP pass
      already exercised both FA and PA directly and confirmed identical behavior (Task 3, 2026-05-29,
      PASS); (c) Herve's explicit judgment call given the volume of TCP evidence gathered today via the
      shared code path. **Not directly proven for the TCP+FA/PA combination specifically** — recorded
      here as an honest gap closed by inference, not a live re-execution. **Correction (code review
      2026-09-26): this is an explicit human override of the Pass/Fail Protocol, not compliance with
      it** — the Protocol above defines exactly three outcomes (PASS/FAIL/BLOCKED), none of which is
      "closed by inference without an observation"; the earlier wording claiming this was "per this
      story's own Pass/Fail Protocol" was inaccurate and has been corrected here.
  - [x] 10.1/10.2/10.3 Closed per the above — not independently executed this session.

- [ ] ~~Task 11: TCP — NAK path T2 (AC: 10)~~ — **TRANSFÉRÉ 2026-09-18 à la story 12-7, Task 12.1 —
      toujours un écart ouvert, non exécuté (correction, code review 2026-09-26) : 12-7 est encore
      `ready-for-dev`, sa Task 12 est décochée. Le transfert documente où la preuve doit être apportée,
      pas qu'elle l'a été — même honnêteté que le transfert AC9/AC10 de la story 12-4 vers 12-7.**
      12-7 portait déjà ce test mot pour mot et sa Task 10 fait la mise en TCP. Ne pas exécuter ici.
      Le mode opératoire ci-dessous est conservé pour référence (le simulateur avec `--account FFFFFF`
      reste le seul moyen de provoquer un NAK à la demande — le récepteur réel n'en fournit pas sur commande).
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

- [ ] ~~Task 12: TCP — timeout path T3 (AC: 11)~~ — **TRANSFÉRÉ 2026-09-18 à la story 12-7, Task 12.2 —
      toujours un écart ouvert, non exécuté (correction, code review 2026-09-26), même statut que
      Task 11 ci-dessus.**
      Mode opératoire conservé pour référence. Variante sans simulateur, si besoin de rester sur le
      récepteur réel : pointer `csr_port` sur un port fermé du même hôte → `ConnectionRefusedError` →
      3 retries → T3 `EVENT_FAILED`.
  - [ ] 12.1 Stop simulator: `pkill -f "tests.simulator"`.
  - [ ] 12.2 Trigger burglarAlarm zone="Piece2" (same PHP CLI as Task 9.1).
  - [ ] 12.3 Wait for 3 retries (~3–35s — TCP connection refused retries faster than UDP timeout). **Verify** `event_state=2`, T3 `EVENT_FAILED` in message center with "CRITIQUE —" prefix. Notification command triggered.
  - [ ] 12.4 **Verify** daemon log shows 3 retry attempts then `event_failed`.
  - [ ] 12.5 Restart simulator: `cd /var/www/html/plugins/siaDC09 && python3 -m tests.simulator --tcp-port 5000 --host 0.0.0.0 --account 000001 &`. Wait for supervision recovery.

- [x] Task 13: Remettre la configuration de référence (AC: 8, 9) — **DONE trivially (2026-09-24)**
      The reference config (TCP / `192.168.100.15:10002` / account `001234`) IS the daemon's current
      live config (set in Task 8.0, confirmed in Task 8.2) — nothing to revert to. The UDP-revert variant
      (13.1/13.2) was never needed since the simulator path (8.1) was never used this session.
  - [x] 13.0 **DONE** — current live config already matches the reference config; no action needed.
  - [ ] 13.1 *(variante simulateur)* Not applicable — never switched away from the reference config.
  - [x] 13.2 N/A — daemon is on TCP (the reference config), not UDP; nothing to verify here.

### Review Findings

Code review 2026-09-26 of the reopen→close reasoning trail (commits `5474fec`..`aa98b5f`), three parallel
adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). This is a docs/reasoning review, not
a code review — no source files exist to patch. Findings verified against the actual cited evidence, not
taken at face value.

- [x] [Review][Decision] **Resolved by Herve (2026-09-26): AC8 accepted as-is** — account `20881` confirmed
  as the account genuinely live during that point of story 14-2's 2026-09-24 session, before it was later
  reconfigured to `001234` the same day. No reopening, no doc change to AC8 itself.
  AC8's cross-story "cumulative evidence" cites the wrong account number — the frames
  quoted from story 14-2's 2026-09-24 session (`[#20881|BA 002]...`, `14-2-frigate-event-prefetch-immediate-action.md:256,477,513`)
  carry account `20881`, not this story's reference config account `001234`
  (`test-sia-internal.lehoux.net`/`192.168.100.15:10002`, per this story's own Infrastructure table and memory
  `sia-test-server-endpoint`). The closure's framing ("same receiver, same config, dozens of successful
  deliveries") is contradicted by the very evidence cited for it — the daemon may have been pointed at a
  different account during 14-2's session than the one this story claims to validate. This story's own fresh
  Task 9 trigger was independently inconclusive (stale zone name + supervision blip), so with the borrowed
  evidence now in question, AC8 may have no clean supporting evidence at all under its own reference config.
  Herve must decide: (a) accept AC8 as-is (e.g. if `20881` was in fact the live account at that point in
  14-2's session and `001234` was set later that day — needs a timeline check), or (b) reopen AC8 for a
  clean, isolated re-run against the confirmed `001234` config.

- [x] [Review][Patch] Self-contradictory Protocol framing — the Task 10/AC9 closure text says the inference
  closure (fireAlarm/panicAlarm over TCP never triggered, closed on shared-dispatch-machinery reasoning
  alone) is "per this story's own Pass/Fail Protocol," but the Protocol section above defines exactly three
  outcomes (PASS/FAIL/BLOCKED) with no inferred-PASS category — verified by reading it directly. The
  underlying code claim used to justify the inference (`_EVENT_SIA_CODES`/`_send_with_retry()`/
  `_build_event_frame()` share one generic path with no event-type branching) is independently verified TRUE
  against `resources/siadc09d/daemon.py`, so the inference itself is reasonable — but calling it Protocol
  compliance is not accurate. **Fixed:** Task 10's closure text and the AC9 status-table line now both state
  this was an explicit human override of the Protocol, not compliance with it.

- [x] [Review][Patch] AC10/AC11 "transferred to 12-7" is presented as settled ("ne pas rejouer ici"), but
  `12-7-error-handling-notification-delivery.md` is still `status: ready-for-dev` with Task 12 (which carries
  these exact ACs) unchecked — confirmed, not yet executed anywhere. Story 12-4's own parallel transfer of
  AC9/AC10 to 12-7 explicitly flags this as "a genuinely open gap -- 12-7 hasn't executed it either"; this
  story's transfer language should match that same honesty rather than implying coverage exists. **Fixed:**
  Task 11/Task 12's transfer notes and the AC10/AC11 status-table lines now explicitly say the gap is still
  open and unexecuted, matching 12-4's wording pattern.

Dismissed as noise (verified against the actual evidence, not applied): AC9's "no event-type branching in the
send path" claim (confirmed true against `daemon.py`); AC3's zone-order-number claim (already established and
tested under story 8.2 AC15, out of scope to re-litigate here).

## Dev Notes

### This is a MANUAL TESTING story — no code to write (unless bugs found)

The dev agent's role is:
1. Execute validation checklist on the real Jeedom VM
2. Observe actual vs. expected behavior
3. Document pass/fail with observations
4. Fix bugs inline if found (document in Dev Agent Record)

### Infrastructure

**Mise à jour 2026-09-18** — la table précédente décrivait la VM `192.168.5.103` (disparue), un
mot de passe SSH en clair et le simulateur comme cible de test. Elle contredisait la note de
supersession de la Task 1.2 juste au-dessus. État réel du labo :

| Component | Location | Notes |
|-----------|----------|-------|
| Hôte Jeedom de test | `test-jeedom.lehoux.net` / `192.168.100.40` | Accès shell root par l'utilisateur. Aucune commande n'est lancée depuis la session de dev. |
| Déploiement du code | `git pull` de `origin/master` sur l'hôte Jeedom | Commit **et push** obligatoires avant toute validation terrain. Pas de dossier partagé. |
| Plugin source | `/var/www/html/plugins/siaDC09` | Clone git sur l'hôte |
| Récepteur SIA de test | `test-sia-internal.lehoux.net` / `192.168.100.15`, **port 10002, TCP** | account `001234`, `crc_format=hex`, chiffrement off. **Cible de validation** — jeu de paramètres prouvé le 2026-09-17 (ACK supervision en ~3 ms). |
| CSR Simulator | Sur l'hôte Jeedom, port au choix | `python3 -m tests.simulator …` — conservé comme outil pour provoquer NAK / silence / account non concordant, pas comme cible de validation. |
| Daemon venv | `resources/python_venv/bin/python3` | Created by Jeedom dep manager |
| Plugin config state | `sia_wizard_step=4` | Wizard complete from Story 12-2 |
| Notification cmd | cmd id=29 (`Notify` on `Notification` eq) | `sia_notify_cmd_id=29` |
| Daemon log | `/var/www/html/log/siaDC09_daemon` | |
| Plugin log | `/var/www/html/log/siaDC09` | |

Le poste de développement n'atteint pas le réseau `192.168.100.x` : un test de connectivité qui
échoue depuis le Mac ne prouve rien. Toutes les vérifications réseau se font depuis l'hôte Jeedom.

### Alarm Command Execution Chain

```
Jeedom alarm plugin action (Titre = "#zone#" → substituted to the zone LABEL "Salon")
  → siaDC09Cmd::execute(['title' => 'Salon'])       [core/class/siaDC09Cmd.class.php:22]
    → zone = trim($_options['title'] ?? '')           [line 28 — the label]
    → zoneNumber = _findZoneEntry('Salon')['zone_number']   [amended — null if no match]
    → siaDC09::sendToDaemon(['cmd'=>'burglarAlarm', 'zone'=>'Salon', 'zone_number'=>1, 'media_url'=>null])
      → TCP socket to localhost:55009
        → daemon._on_message_dispatch({'cmd':'burglarAlarm','zone':'Salon','zone_number':1,'apikey':'...'})
          → on_message('burglarAlarm', {'zone':'Salon','zone_number':1})  [daemon.py:1904]
            → sia_code = _EVENT_SIA_CODES['burglarAlarm'] = 'BA'
            → _enqueue_event('BA', 'Salon', 1, None)
              → _queue_consumer() picks up EventItem
                → _build_event_frame() → extended_data['zone'] = "001"  ← the NUMBER, padded
                → _send_with_retry() → SM2: IDLE→PENDING→CONFIRMED/FAILED
                   frame: [#001234|BA 001]   (unresolved zone → [#001234|BA], no zone field)
```

**The zone label reaches the plugin through the action's *Titre* field.** The `subType='message'` means:
- The alarm plugin substitutes `#zone#` in every value of the action's `options` array, so the tag works in *Titre*
- `siaDC09Cmd::execute()` reads `$_options['title']` — a **label**, because `#zone#` is `$zone['name']`; the alarm plugin exposes no zone identifier
- The label is therefore resolved against `sia_zone_mappings` to obtain `zone_number`, and **only the number travels in the frame** (Story 8.2 AC11–AC15)
- `#name_zone#` does not exist in the alarm plugin — the three supported tags are `#mode#`, `#alarm_trigger#`, `#zone#`

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
- AC3 (zone handling): PASS — invalidé le 2026-09-17 (le libellé était transmis au lieu du n° d'ordre), **re-validé le 2026-09-17 22:01:49** sous Story 8.2 AC15 / Task 11.9 sur le récepteur réel : `[#001234|BA 001]` porte bien le n° d'ordre. Dette soldée ✓
- AC4 (NAK path T2): PASS — event_state=2, no CRITIQUE prefix, no retry ✓ *(UDP)*
- AC5 (timeout path T3): PASS — 3 retries, CRITIQUE prefix, T3 notification ✓ *(UDP)*
- AC6 (ring buffer alarm entry): PASS (verified in 12-4 session, confirmed dialog_type=alarm) ✓
- AC7 (event_state persists): PASS — event_state=1 survives daemon restart ✓
- AC8 (TCP happy path): PASS — trame BA en TCP vers `192.168.100.15:10002` acquittée le 2026-09-17 22:01:49 (preuve sous 8.2 AC15), plus des dizaines de livraisons BA/TCP réussies le 2026-09-24 pendant la session story 14-2 (mêmes récepteur/transport ; compte `20881` à ce moment de la session 14-2, avant reconfiguration en `001234` — confirmé par Herve, code review 2026-09-26, accepté tel quel), toutes confirmées `SM2 confirmed`/`Centrale confirmée`. `event_state=1` confirmé fonctionnellement via ces logs (mapping SM2 CONFIRMED → event_state=1), pas via une lecture isolée fraîche de la commande `event_state` le 2026-09-24 (la tentative faite ce jour-là est tombée dans une coupure de supervision transitoire — voir Task 9). ✓
- AC9 (TCP FA/PA): **CLOSED 2026-09-24 sur décision explicite de Herve** — fireAlarm/panicAlarm n'ont pas été déclenchés en TCP ce jour-là (la session du jour portait uniquement sur burglarAlarm, périmètre de la story 14-2). Fermé par inférence : même mécanique de dispatch que burglarAlarm (`_EVENT_SIA_CODES`/`_send_with_retry()`/`_build_event_frame()`, aucune branche spécifique au type d'événement — vérifié contre le code réel), déjà prouvé directement en UDP (Task 3, 2026-05-29). **Non prouvé directement pour la combinaison TCP+FA/PA** — écart assumé et documenté, pas caché. **Correction (code review 2026-09-26) : ceci est une dérogation explicite au Pass/Fail Protocol, pas une conformité à celui-ci** — le Protocol ne définit que PASS/FAIL/BLOCKED, aucune catégorie "clos par inférence".
- AC10 (TCP NAK T2): **TRANSFÉRÉ** à 12-7 Task 12.1 (2026-09-18) — **écart toujours ouvert, non exécuté** (correction, code review 2026-09-26) : 12-7 reste `ready-for-dev`, Task 12 décochée
- AC11 (TCP timeout T3): **TRANSFÉRÉ** à 12-7 Task 12.2 (2026-09-18) — même statut que AC10 ci-dessus

### File List

- `resources/siadc09d/messages.py` — Bug 1: removed T3_PREFIX from SM2_FAILED_NAK
- `resources/siadc09d/daemon.py` — Bug 2: SIATransportError added to retry handler; Bug 3: event_state excluded from periodic update when SM2 IDLE
- `resources/siadc09d/csr_simulator.py` — Bug 5: account validation NAK logic in _decide_response() and account extraction in _parse_received_message()
- `tests/level1/test_messages.py` — Bug 1: updated T3 prefix test to assert SM2_FAILED_NAK is T2
- No new files this session (2026-09-24) — TCP transport setup + closure only, no bugs found, no code changed.

## Change Log

| Date | Change |
|------|--------|
| 2026-05-29 | Story created and executed on Jeedom VM. All 7 AC pass. 5 bugs fixed. |
| 2026-06-01 | TCP pass added: AC8–11 + Tasks 8–13 — alarm delivery over TCP transport. |
| 2026-09-17 | AC3 rewritten (frame carries the zone *order number*, or no zone field when unresolved); Task 0.1 corrected (`#name_zone#` → `#zone#`, which yields a label); Task 1.2 superseded (real receiver `192.168.100.15:10002` TCP, no simulator); execution chain updated with `zone_number`. AC3 re-validation is owned by Story 8.2 AC15. |
| 2026-09-18 | **Story réouverte** — `done` était faux : Tasks 8–13 / AC8–AC11 (passe TCP) jamais exécutées, alors que TCP est le transport réel du récepteur. Statut → `in-progress`. AC3 soldé (re-validé sous 8.2 AC15 le 2026-09-17 22:01:49). AC8 coché en PASS partiel sur la preuve terrain 8.2 AC15 (trame `D741003A"SIA-DCS"0010L0#001234[#001234\|BA 001]` acquittée en TCP sur `192.168.100.15:10002`), reste `event_state=1` à relever (Task 9.2). AC9 = seule exécution encore due (Task 10, + nouvelle 10.3 sur `[#001234\|FA 001]` / `[#001234\|PA 002]`). AC10/AC11 **transférés à 12-7 Task 12.1/12.2** qui les portait déjà mot pour mot ; Tasks 11 et 12 barrées mais leurs modes opératoires simulateur **conservés** (le simulateur reste le seul moyen de provoquer NAK / silence / account non concordant), + substitut sans simulateur documenté (port fermé → `ConnectionRefusedError`). Tasks 8 et 13 dotées d'un chemin autoritatif « récepteur réel » (8.0, 13.0), variantes simulateur conservées et étiquetées. Task 13 requalifiée « remettre la configuration de référence » (TCP/10002) au lieu de « revert to UDP ». Table Infrastructure réécrite : VM morte `192.168.5.103` et mot de passe SSH en clair supprimés, déploiement par `git pull` sur `test-jeedom.lehoux.net`. |
| 2026-09-24 | **Story closed on Herve's explicit call** ("close 12-5 completely, I did tests all day"), after story 14-2's live validation session produced extensive TCP `burglarAlarm` evidence against the same real receiver (`192.168.100.15:10002`). Reconfigured/confirmed daemon on the reference TCP config (Task 8.0/8.2). A fresh isolated Task 9 trigger this session hit two artifacts, documented not hidden: "Piece1" no longer resolves in the current `sia_zone_mappings` (remapped to `Zone1`/`Zone2` by story 14-2) — AC3's designed no-match fallback, not a bug; and the trigger landed during a transient supervision disconnect/reconnect window, so the `event_state` read immediately after was stale, not a confirmation of that specific trigger. AC8 closed instead on the day's cumulative TCP evidence (many independent SM2-confirmed BA/TCP deliveries). AC9 (FA/PA over TCP) closed by inference, **not independently executed this session** — same dispatch machinery as BA (no event-type branching in the send path) plus the existing UDP-pass direct confirmation (Task 3); recorded as an honest, assumed gap rather than a live re-run. Task 13 trivially satisfied — the reference config already is the current live config. No code changes, no bugs found. Status `in-progress → review`. |
