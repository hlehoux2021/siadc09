---
title: 'Gestion de la réponse DUH (SIA DC-09 § 5.5.3.3 / § 5.6.1.3) et log de la trame du test wizard'
type: 'feature'
ticket: "6"
created: '2026-11-03'
status: "in-review"
baseline_revision: 'f053858c1c491304e86c9c030440c802d1eaf2fc'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 1
context:
  - '{project-root}/.claude/rules/python-style.md'
  - '{project-root}/internal-docs/design/daemon-design.md'
  - '{project-root}/internal-docs/design/supervision-design.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Un CSR réel (194.51.213.114:5390 TCP, compte 4596) répond `\nA8080012"DUH"0001L0#4596[]\r` à la trame `"SIA-DCS"0001L0#4596[#4596|0000]` (ACK sur une trame NULL). Le décodeur ne connaît que ACK/NAK : le DUH devient `unknown`, puis `timeout`, puis `bad_reply` ("réponse illisible, vérifier CRC et chiffrement", faux), et le daemon le compte comme « NAK non décodable ».

**Approach:** Reconnaître DUH de bout en bout (décodeur, transport, test wizard, daemon), avec un verdict wizard qui oriente vers le format NULL. Logger en debug la trame envoyée par le test (clair uniquement).

## Boundaries & Constraints

**Always:** DUH jamais chiffré ; seq conservé ; statuts UI limités à ok/nak/fail/error (siaDC09.js) ; test écrit avant tout essai live ; règles .claude/rules/python-style.md.
Daemon (décision § 5.6.1.3 « déclarer l'échec immédiatement ») : un DUH est un refus déterministe, donc aucun renvoi. Supervision/RP : 1 strike, notification T2 BAD_CSR_RESPONSE, log dédié. Événement alarme : pas de retry, SM2 FAILED avec `_event_failure_reason="nak"` (libellé « refusé » existant).

**Never:** logger une trame chiffrée ou la clé ; changer le défaut `supervision_format` ni les profils ; modifier le comportement ACK/NAK existant ; toucher à PHP/JS ; `git push`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| DUH valide | `\nA8080012"DUH"0001L0#4596[]\r` | `decode_ack_nak` → type `DUH`, seq 1, raw_nak None ; transport → status `duh` | — |
| DUH CRC faux | même trame, CRC altéré | `unknown` (inchangé) | bad_reply |
| Wizard, DUH | transport `duh` | verdict `fail`, détail FR : CSR joignable, trame refusée (DUH), essayer le format NULL / vérifier compte et préfixe | — |
| Wizard, trame claire | test dont le verdict n'est pas ok (décision humaine 2026-11-04 : PHP logge tout stderr en erreur) | stderr : trame envoyée en hex/ASCII | trame chiffrée : jamais loguée |
| Supervision/RP DUH | status `duh` | pas de renvoi, strike +1, T2, log « DUH » ; RP : « Refusé par la centrale » | — |
| Événement DUH | status `duh` | pas de retry, SM2 FAILED reason `nak`, T2 | — |

</frozen-after-approval>

## Code Map

- `resources/siadc09d/sia_protocol.py` -- `DUH_TOKEN` (l.54, inutilisé) ; `AckNakResponse.type` (l.119) ; `_parse_ack_nak_type_and_seq` (~l.825) ; `decode_ack_nak` (~l.885).
- `resources/siadc09d/sia_transport.py` -- `SIATransportResult.status` Literal (l.~51) ; `_parse_response` (l.104-122) ; docstrings.
- `resources/siadc09d/siadc09d.py` -- `_TEST_VERDICTS` (l.78), `_send_raw_once` (l.177-247), `run_connection_test` (l.302-) ; `_FAIL_BAD_REPLY` (message à rendre neutre : pas de CRC/chiffrement affirmé).
- `resources/siadc09d/daemon.py` -- supervision l.1138-1196, `_handle_supervision_nak` l.1274, `_log_sm1_supervision` l.1505-1650 (events), envoi événement l.1714-1800, RP l.2162-2206. Hot-spot de merge : `git status`/`git log` avant édition.
- `resources/siadc09d/messages.py` -- constantes FR SM1/SM2 (ajouter `SM1_DUH`).
- `tests/level1/test_sia_protocol_ack_nak.py`, `tests/level1/test_connection_test.py` (l.218 test `bad_reply` à garder) ; daemon : `tests/level2/test_supervision_loop_integration.py`, `tests/level2/test_sm2_alarm_event_suite.py`.
- `internal-docs/design/daemon-design.md`, `supervision-design.md`, `docs/` (troubleshooting) -- documenter DUH.
- À ne pas changer : `desktop/js/siaDC09.js`, `core/`, `csr_presets`, `build` des trames.

## Tasks & Acceptance

**Execution:**
- [ ] `resources/siadc09d/sia_protocol.py` -- ajouter type `DUH` (Literal, constante `DUH_RESPONSE`) reconnu par token `DUH` ; seq conservé -- le CRC reste validé
- [ ] `resources/siadc09d/sia_transport.py` -- statut `duh` (+ `raw_response`) dans `_parse_response` et le Literal -- ne plus confondre avec timeout
- [ ] `resources/siadc09d/siadc09d.py` -- verdict `duh` (fail) ; message `bad_reply` sans accusation CRC/chiffrement ; log stderr DEBUG de la trame envoyée si non chiffrée -- orienter l'utilisateur
- [ ] `resources/siadc09d/messages.py` + `resources/siadc09d/daemon.py` -- branche `duh` pour supervision, RP et événement (voir Always) ; `_handle_supervision_duh` ; type de log `duh` -- pas de renvoi
- [ ] `tests/level1/*` et `tests/level2/*` -- tests avec la trame exacte (décodage, CRC altéré, transport, verdict, absence de log chiffré, supervision, RP, événement)
- [ ] `internal-docs/design/*.md`, `docs/*` -- documenter DUH et la ligne de dépannage ; `_bmad-output/initiative-my-project/archive-v6/sprint-status.yaml` -- ajouter la story et recalculer le summary depuis `development_status`

**Acceptance Criteria:**
- Given la trame DUH exacte, when décodée, then type `DUH` seq 1.
- Given un CSR répondant DUH, when le wizard teste, then verdict `fail` mentionnant DUH et le format NULL, sans parler de CRC.
- Given une trame chiffrée, when le test s'exécute, then aucune trame ni clé dans les logs.
- Given un DUH en supervision, when reçu, then un seul envoi, strike +1, aucun libellé « NAK non décodable ».
- Given `python3 -m pytest tests/level1/` et `python3 -m pylint resources/siadc09d/`, then aucun nouvel échec par rapport à la baseline mesurée avant modification.

## Implementation Notes

## Plan Change Log

- 2026-11-04, review finding 1 (intent_gap): `siaDC09.ajax.php` logs any stderr at error level, so the always-on DEBUG frame line polluted the Jeedom log on every successful test. Human chose "log only on failure"; matrix row amended. Known-bad state avoided: frame logged on a successful test. KEEP: DUH decoder/transport/daemon changes, verdict text, bad_reply neutral wording, all tests except the two frame-log ones, which now assert failure-only logging.

## Review Triage Log

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | Wizard `DEBUG` stderr line becomes an error-level Jeedom log on every unencrypted test | medium | intent_gap | `core/ajax/siaDC09.ajax.php:103-104` logs any non-empty stderr at `error` level; the frozen matrix requires stderr DEBUG while Never forbids touching PHP, so the plan cannot settle it |
| 2 | `bad_reply`/troubleshooting text points to a log of the received frame that does not exist | false | rejected | `_send_raw_once` (siadc09d.py:238-243) puts the raw bytes in `error`, which `run_connection_test` prints to stderr (l.395-400) and PHP logs; DUH message does not point to a log |
| 2b | Frame printed twice (repr + hex) | false | rejected | Plan asks for "hex/ASCII"; both are intended |
| 3 | `SM2_FAILED_DUH` missing from T2/T3 comment tables; `_log_sm1_supervision` docstring stale | low | rejected | Cosmetic; moot under loopback |
| 4 | Weak assertions in the wizard DUH test; no test of the real `duh` French log text | low | rejected | Behavior is covered by matrix tests; fix adds tests only, no defect met in use |
| 5 | English doc not updated | false | rejected | `en_US` is partial per `info.json`; plan scoped docs to troubleshooting row |
| 6 | sprint-status counters unverified | false | rejected | Recomputed from `development_status`: 6 backlog + 1 ready-for-dev + 7 review + 54 done = 68 |

## Design Notes

DUH = « reçu et correct, mais je ne le traite pas » (§ 5.5.3.3) : renvoyer la même trame donnerait la même réponse, d'où l'échec immédiat. Le NULL standard (§ 5.5.2.1) est la voie de contournement pour ce CSR ; aucun changement de défaut ici.

## Verification

**Commands:**
- `python3 -m pytest tests/level1/` -- expected: aucun nouvel échec vs baseline
- `python3 -m pytest tests/level2/` -- expected: idem
- `python3 -m pylint resources/siadc09d/` -- expected: pas de nouveau message

**Manual checks (if no CLI):**
- Wizard étape 2 sur le CSR 194.51.213.114:5390 : `sia-dcs` → échec DUH explicite ; `null` → ACK.


## Acceptance criteria (epics.md)

**Given** the exact DUH frame above
**When** it is decoded
**Then** the type is `DUH` with sequence 1. With an altered CRC it stays `unknown`. A DUH is never encrypted.

**And** when the wizard tests a CSR that answers DUH, the verdict is `fail`. The detail says the CSR is reachable and
refused the frame (DUH), and suggests the `null` format and checking account and prefix. It does not mention CRC.
The `bad_reply` message no longer claims a CRC or encryption problem.

**And** after a failed wizard test with encryption off, the clear sent frame is written to stderr. A passing test
writes nothing, because PHP logs any stderr at error level. An encrypted frame and the key are never logged.

**And** on supervision or RP a DUH is never re-sent (§ 5.6.1.3, deterministic refusal): one strike, T2
`BAD_CSR_RESPONSE`, a dedicated `duh` log line (never "NAK non décodable"). RP shows "Refusé par la centrale".

**And** on an alarm event a DUH is not retried: SM2 goes to FAILED with failure reason `nak` (existing "refusé" label)
and T2.

**And** the default `supervision_format`, the profiles, PHP and JS are unchanged.

**And** field check on the CSR above: `sia-dcs` fails with the DUH verdict, `null` is ACKed. Not yet done.

## Prior builds

### Prior build: 17-6-duh-response-handling.md

#### Story 17-6: DUH response handling

Status: review (implemented 2026-11-04, commit 19fb318 local, not pushed; field check on the real CSR pending)

Evolution, not a fix: DUH handling was not planned when epic 17 started. Build record: `_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/story-17-6-duh-response-handling-plan.md` (ticket `17-6-duh-response-handling`, status `built`, baseline `f053858`).

##### Story

As a user whose CSR refuses the `sia-dcs` supervision frame,
I want the plugin to recognise a DUH answer and tell me what it means,
So that I am steered to the `null` format instead of being told the reply is unreadable.

Trigger: a real CSR (194.51.213.114:5390 TCP, account 4596) answered `\nA8080012"DUH"0001L0#4596[]\r` to `"SIA-DCS"0001L0#4596[#4596|0000]`. The decoder only knew ACK/NAK, so the reply became `unknown`, then `timeout`, then `bad_reply` ("check CRC and encryption", wrong), and the daemon counted a "NAK non décodable".

##### Acceptance Criteria

1. Decoding the exact DUH frame gives type `DUH`, sequence 1. With an altered CRC it stays `unknown`. A DUH is never encrypted.
2. Wizard, CSR answering DUH: verdict `fail`; the detail says the CSR is reachable and refused the frame (DUH), suggests the `null` format and checking account and prefix; no mention of CRC. The `bad_reply` message no longer claims a CRC or encryption problem.
3. Wizard, failed test with encryption off: the clear sent frame (repr + hex) goes to stderr. A passing test writes nothing (PHP logs any stderr at error level, `core/ajax/siaDC09.ajax.php:96-104`). An encrypted frame and the key are never logged.
4. Supervision and RP: a DUH is never re-sent (§ 5.6.1.3, deterministic refusal). One strike, T2 `BAD_CSR_RESPONSE`, dedicated `duh` log line (never "NAK non décodable"). RP label "Refusé par la centrale".
5. Alarm event: a DUH is not retried. SM2 goes to FAILED with failure reason `nak` (existing "refusé" label), T2 sent.
6. Default `supervision_format`, profiles, PHP and JS unchanged. ACK/NAK behaviour unchanged.
7. Field check on the real CSR: `sia-dcs` fails with the DUH verdict, `null` is ACKed. **Not done.**

##### Evidence

###### Implementation (commit 19fb318, local)

| Area | Change |
|------|--------|
| `sia_protocol.py` | `DUH_RESPONSE`; `AckNakResponse.type` includes `DUH`; token `DUH` recognised, CRC still validated |
| `sia_transport.py` | status `duh` (with `raw_response`) |
| `siadc09d.py` | `duh` verdict (fail); neutral `bad_reply`; failure-only clear-frame log |
| `daemon.py` | `_handle_supervision_duh`; supervision and RP branch on `duh`; `_send_with_retry` `duh` branch (no retry, SM2 FAILED reason `nak`, transition `failed_duh`); log event `duh` |
| `messages.py` | `SM1_DUH`, `SM2_FAILED_DUH` |
| Docs | `daemon-design.md`, `supervision-design.md`, `docs/fr_FR/index.md` troubleshooting rows. `docs/en_US` not updated (partial language) |

###### Tests (2026-11-04)

| Suite | Result |
|-------|--------|
| `tests/level1/` | 1465 passed |
| 11 matrix tests (decode, bad CRC, transport, verdict, encrypted frame never logged, ACK silent, supervision, RP, event) | passed |
| `tests/level2/` subset | 112 passed, 1 failed: `test_update_info_commands_full_payload_healthy`, known baseline failure |
| `pylint resources/siadc09d/` | about 6 more messages than master (long lines, too many branches in `_send_rp`): "no new pylint message" is not strictly met |

###### Review (quick, 1 iteration)

Finding 1 (intent gap): the always-on DEBUG frame line became an error-level Jeedom log on every successful test. Decision (Herve, 2026-11-04): log only on failure. Matrix row amended in the plan; other findings rejected (see the plan's Review Triage Log).

##### Verdict

Code complete and reviewed. Not closed until the field check (AC 7) is run on the real CSR.

##### Follow-ups

- Field check on 194.51.213.114:5390: `sia-dcs` gives the DUH verdict, `null` is ACKed.
- Push 19fb318 (not pushed).
- Optional: pylint cleanup in `_send_rp`; English doc row.
