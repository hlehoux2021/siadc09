# Story 17-5: Field validation per profile

Status: review (evidence recorded 2026-10-18)

## Evidence

### Part A: test receiver (ioBroker.sia, 192.168.100.15:10002, account 001234, encryption off)

| Case | Config | Result |
|------|--------|--------|
| 1 | format `sia-dcs`, 60 s | Supervision frame ACKed about every 60 s |
| 2 | format `none`, RP on, 60 s | `RP0000` ACKed every 60 s (seq 0001, 0002), label "Connexion OK", `supervision_state` 2 |
| 3 | format `null`, 60 s | NAKed on the initial send and both re-sends, strike 1/3. Receiver log: `Incorrect format of data message` (its parser rejects the empty `[]` data block). Receiver limitation, not a timestamp/account/encryption issue |

Note: the first connection test NAK came from the receiver account having encryption enabled (left over from AES tests), not from the plugin.

### Part B: real Scutum receiver (profile `scutum`, TCP, account 27099)

Run 2026-10-18, 17:44:40 to 17:54:41 UTC (19:44 to 19:54 local), 11 RP frames.

- Daemon: `RP0000` sent every 60 s (17:44:40, then 17:45:41 ... 17:54:41), sequences 0001 to 0011 consecutive, every frame ACKed on attempt 1, `supervision_state` 2, label "Connexion OK" each time.
- Scutum extranet: 10 lines "Test Cyclique RP0000" from 19:44:40 to 19:53:41, one per minute with no gap (the 11th frame, 19:54:41, was not in the pasted extract).
- No link alarm reported.

### Verdict

Scutum profile validated for at least 10 minutes. Not covered: observation beyond 10 minutes (missing-test alarm threshold unknown), NULL format at Scutum, Ajax profile on a real hub (ajax and scutum presets are identical).

## Follow-ups

- Misleading NAK wording recorded in `deferred-work.md`.
