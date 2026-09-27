---
story_id: "13-1"
story_key: "13-1-burglary-restore-cancel-events"
epic_id: "epic-13"
epic_name: "Alarm Event Vocabulary Extension (v1.1)"
status: "done"
created: "2026-09-17"
---

# Story 13.1: Désarmement pendant une alarme — Burglary Cancel (BC) + Opening Report (OP)

> **Rescopée le 2026-09-25** (`sprint-change-proposal-2026-09-25.md`). Le tableau des codes
> DC-03 (p. 4) montre que **BC s'adresse par numéro d'utilisateur, jamais par zone** :
> « Burglary Cancel — alarm has been cancelled by authorized user / User number ». L'éventail
> par zone (Tasks 2-4 précédentes) n'était donc **pas conforme DC-03** dès le départ. Le périmètre
> s'étend en même temps sur demande d'Herve : le plugin doit aussi rapporter **OP** (désarmement)
> quand une alarme intrusion était ouverte, et couvrir le **second** chemin de fin d'alarme du
> plugin alarme — une remise à zéro (`raz`) sans désactivation, qui laisse le système armé. Deux
> commandes remplacent `burglaryCancel` : **`disarm`** (câblée sur `release`) et **`alarmReset`**
> (câblée sur `raz`). CL (armement) et OP-sur-désarmement-normal partent vers la nouvelle story
> **13-4** (backlog) ; FC/PC (incendie/panique) partent vers **13-3** (backlog). `burglaryCancel`
> n'a jamais été livré — aucune migration n'est nécessaire. Voir ADR-18 (`architecture.md`).

Status: done — Tasks 1-10 closes le 2026-09-25. Task 10 (validation live sur
`test-jeedom.lehoux.net` contre la centrale interne, AC8) exécutée via l'API Jeedom
(`core/api/jeeApi.php`, clés scopées par plugin), pas par clic manuel — voir Dev Agent Record.
Code review 2026-09-26 : 4 patches appliqués et testés (validation de plage `sia_user_number`,
isolation try/catch dans `siaDC09_update()`, rejet daemon d'une adresse manquante pour BC/OP/CL,
bug `dict.get`/`None` dans la notification EVENT_FAILED), 5 items différés, 3 rejetés comme bruit.
0 régression.

## Story

As a monitored Jeedom user,
I want disarming my alarm while a burglary alarm is open to tell the CSR that user N cancelled
it and disarmed the system,
So that the operator stops the emergency procedure instead of calling the police.

## Contexte — pourquoi l'adressage change

Le tableau DC-03 (`internal-docs/SIA Codes – Complete DC-03 Event Code List _ Peoplecall Cloud.pdf`,
p. 4) :

| Code | Nom | Champ d'adresse |
|---|---|---|
| BA | Burglary Alarm | Zone ou point |
| **BC** | **Burglary Cancel — annulé par un utilisateur autorisé** | **Numéro d'utilisateur** |

`[#001234|BC 003]` signifie donc « annulé par l'**utilisateur 3** », jamais « zone 3 fermée ».
Herve a confirmé sur le tableau complet (la copie du dépôt ne va que jusqu'à BC, pages 1-4) que
CL (armement) et OP (désarmement) s'adressent de la même façon, par numéro d'utilisateur ; OR
(« Disarm From Alarm ») n'est **pas** retenu — Herve a choisi BC + OP à la place.

Le plugin alarme (`~/dev-hlx/plugin-alarm/core/class/alarm.class.php`) ne transmet **jamais**
l'identité Jeedom (`user_login`/`user_id`) à ses actions (`doAction()`, `:639-670` : seuls
`#mode#`/`#alarm_trigger#` sont substitués). Le numéro d'utilisateur SIA est donc une **valeur
configurée** (`sia_user_number`, assistant étape 3, défaut `1`), pas une donnée lue.

### Les deux chemins de fin d'alarme (`:697-717`, `:812-832`)

L'onglet « Réinitialisation » (`raz`) est un point d'accroche d'action, pas une commande.

| Situation | Ce que le plugin exécute | État final |
|---|---|---|
| **Désactiver pendant que l'alarme sonne** | « Désactivation OK » (`release`), **puis** « Réinitialisation » (`raz`) | désarmé |
| **Changement de mode pendant que l'alarme sonne** | « Réinitialisation » (`raz`) **seule**, sans `release` | **reste armé** |

Conséquence : une intrusion peut être annulée **sans** désarmer. `BC` part donc de deux façons :
apparié à `OP` sur un désarmement, ou seul sur une réinitialisation par changement de mode.
**Deux commandes, une par point d'accroche.** Comme `release` s'exécute avant `raz`
(`alarm.class.php:703-712`), la première des deux à agir purge la table `sia_open_alarms` et la
seconde la trouve vide — jamais de `BC` en double.

## Conception retenue

### Deux commandes, chacune sur son point d'accroche

| logicalId | name | type | subType | isVisible | SIA code(s) | Câblée sur |
|---|---|---|---|---|---|---|
| `disarm` | `Désarmement` | action | other | 0 | `BC`+`OP`, ou rien | `release` (« Désactivation OK ») |
| `alarmReset` | `Réinitialisation alarme` | action | other | 0 | `BC`, ou rien | `raz` (« Réinitialisation ») |

Créées idempotemment par `postSave()`, même `returnStateTime 30` / `returnStateValue 0` que les
actions alarme. `subType other` : ni l'une ni l'autre n'a besoin d'un *Titre* — l'adresse est
`sia_user_number`, une valeur configurée, jamais quelque chose que le plugin alarme peut fournir.

`burglaryCancel` est retiré de `$actionCmds`. Jamais livré, donc pas de migration.

### `disarm` (sur `release`)

Si `sia_open_alarms` a une entrée `BA` ouverte : émet `[#{compte}|BC {user:03d}]` puis
`[#{compte}|OP {user:03d}]`, dans cet ordre, puis purge la table. Sinon : n'émet **rien**
(l'`OP` du désarmement normal part vers la story 13-4) et journalise en `debug`.

### `alarmReset` (sur `raz`)

Si `sia_open_alarms` a encore une entrée `BA` ouverte (cas : réinitialisation par changement de
mode, sans `release`) : émet `[#{compte}|BC {user:03d}]` puis purge la table. Sinon (cas normal :
`disarm` a déjà purgé) : n'émet **rien**.

### La table `sia_open_alarms` — rôle réduit

Support, clé, forme d'entrée, bornage (`OPEN_ALARMS_MAX`), TTL : **inchangés** de la conception
précédente (cache eqLogic `sia_open_alarms`, Redis-backed). Son rôle se réduit à un oracle
« une `BA` est-elle ouverte ? » — plus de fan-out, plus de dérogation mono-zone, plus de repli
compte : les deux commandes purgent toujours la table entière sur un `BC`, puisqu'il n'existe
qu'une seule alarme intrusion ouverte possible par construction du plugin alarme (un équipement,
un état armé/désarmé). Les entrées `FA`/`PA` restent mémorisées pour la future story 13-3.

### `siaDC09_update()` doit atteindre les installations existantes (constat #2)

`postSave()` ne s'exécute qu'à l'enregistrement de l'équipement (installation neuve, ou
ré-enregistrement manuel). À la **mise à jour** du plugin, Jeedom appelle `siaDC09_update()`, pas
`postSave()` : une installation existante qui ne ré-enregistre jamais son équipement ne recevrait
donc jamais `disarm`/`alarmReset`. `siaDC09_update()` doit parcourir chaque eqLogic `siaDC09` et
appeler `postSave()` sur chacun.

### Câblage requis (documentation plugin, Task 9)

| Action plugin alarme | Notre commande | Pourquoi |
|---|---|---|
| *Désactivation OK* (`release`) | `Désarmement` (`disarm`) | voit chaque désarmement ; émet BC→OP si une BA est ouverte |
| *Réinitialisation* (`raz`) | `Réinitialisation alarme` (`alarmReset`) | voit la réinitialisation par changement de mode que `release` n'a pas exécutée |

**Câbler les deux.** Un installateur qui n'en câble qu'une perd l'autre cas — la réinitialisation
par changement de mode (sans `release`) si seul `disarm` est câblé, ou l'annulation du
désarmement normal si seul `alarmReset` est câblé.

### Options écartées

- **Éventail par zone (conception précédente).** Non conforme DC-03 : `BC` s'adresse par
  utilisateur, jamais par zone.
- **BC sans adresse.** DC-09 légal, mais une centrale peut le rejeter ou le mal classer.
- **Lire `lastExecutionUser`** (cache du noyau Jeedom). Couple le plugin à l'état interne d'un
  autre plugin ; un désarmement déclenché par scénario y lit `system`.
- **CR pour l'armement.** CR signifie *Recent Closing* (alarme dans les 5 minutes suivant
  l'armement), pas « armé ».

## Acceptance Criteria

> **ACs de la conception précédente (éventail par zone), abandonnées le 2026-09-25 —
> conservées ici pour traçabilité, ~~barrées~~, remplacées par la liste ci-dessous :**
>
> 1. ~~Conception corrigée : les trois sections `## Restoral events (BR / BC)` sont réécrites~~
> 2. ~~Commande `burglaryCancel` créée par `postSave()`, câblée sur `raz`~~
> 3. ~~Mémorisation : toute alarme émise crée/rafraîchit une entrée dans `sia_open_alarms`~~
> 4. ~~Éventail : N BA sur N zones distinctes → exactement N BC portant les mêmes numéros~~
> 5. ~~Repli jamais muet : table vide → exactement une trame `[#001234|BC]` sans zone~~
> 6. ~~Dérogation mono-zone : un *Titre* non vide émet un unique BC pour cette zone~~
> 7. ~~Démon : `SiaEventCode`/`_EVENT_SIA_CODES`/`error_handler.py` acceptent `BC`~~
> 8. ~~Trames correctes sur la vraie centrale : BA puis BC acquittés~~
> 9. ~~Validation terrain multi-zones sur `test-jeedom.lehoux.net`~~

**Nouvelles ACs (2026-09-25) :**

1. **Given** une commande d'action `disarm` (« Désarmement ») câblée sur l'action `release` du
   plugin alarme, et un `sia_user_number` configuré (défaut 1)
   **When** l'utilisateur désarme alors qu'au moins une `BA` envoyée par siaDC09 est encore
   ouverte (`sia_open_alarms`)
   **Then** exactement deux trames sont émises, dans cet ordre : `[#{compte}|BC {user:03d}]`
   puis `[#{compte}|OP {user:03d}]`, et la table des alarmes ouvertes est purgée.

2. **And** quand aucune `BA` n'est ouverte, `disarm` n'émet **aucune** trame (l'`OP` normal est
   la story 13-4) et journalise en `debug`.

3. **Given** une commande d'action `alarmReset` (« Réinitialisation alarme ») câblée sur
   l'action `raz` (« Réinitialisation ») du plugin alarme
   **When** l'alarme est réinitialisée par un changement de mode pendant qu'elle sonne (pas de
   `release`, le système reste armé) et qu'une `BA` est ouverte
   **Then** exactement une trame `[#{compte}|BC {user:03d}]` est émise, et la table est purgée.

4. **And** lors d'une Désactivation normale pendant une alarme (`release` puis `raz`),
   `alarmReset` trouve la table déjà purgée par `disarm` et n'émet **rien** : la séquence
   complète produit exactement BC puis OP, jamais un second BC.

5. **And** le champ d'adresse n'est jamais un numéro de zone, et n'est jamais vide.

6. **And** `siaDC09_update()` crée les deux nouvelles commandes sur les installations existantes,
   sans enregistrement manuel de l'équipement (constat #2).

7. **And** `SiaEventCode`, `_EVENT_SIA_CODES` et `error_handler.py` acceptent `BC` et `OP`.
   `event_label` affiche `Annulation (utilisateur 1) : Confirmée par la centrale`, et
   l'équivalent pour `OP`. La notification EVENT_FAILED T3 nomme une annulation/désarmement
   échoué, pas une « alarme » (constat #4).

8. **And** les deux trames sont acquittées (ACK) par `192.168.100.15:10002` en TCP, compte
   `001234`, depuis la vraie IHM Jeedom sur `test-jeedom.lehoux.net`. Deux vérifications, lues
   dans l'inspecteur de protocole : déclencher une zone puis désarmer (attendre BA, BC, OP) ;
   déclencher une zone puis changer de mode (attendre BA, BC).

## Tasks / Subtasks

- [x] Task 1: Réécrire les sections de conception (`daemon-design.md`, `php-core-design.md`,
      `widget-design.md`, `wizard-design.md`) pour l'adressage par utilisateur et les deux
      commandes — **fait au niveau du Sprint Change Proposal 2026-09-25**, relu et corrigé pour
      cohérence avec le code réellement livré (Tasks 2-9) : snippets `disarm`/`alarmReset`
      alignés sur `_resolveSiaUserNumber()`/`_purgeOpenAlarms()` réels, tableau `event_label`
      corrigé au format ` : {état}` effectivement produit par `_event_label_from_sm2()`, note sur
      la déviation `_EVENT_SIA_CODES`/`_VARIABLE_SIA_CODE_COMMANDS` ajoutée
- [x] Task 2: `disarm` et `alarmReset` dans `postSave()` (`$actionCmds`, `subType other`) +
      config `sia_user_number` + champ assistant étape 3 (AC1-AC6)
- [x] Task 3: Table `sia_open_alarms` — écriture, clé, dédoublonnage, `OPEN_ALARMS_MAX`, TTL.
      **Acquise, rôle réduit** : oracle « une BA est-elle ouverte ? », plus de fan-out ni de
      dérogation mono-zone à retirer du code existant
- [x] Task 4: `disarm` → BC puis OP si BA ouverte, sinon rien (AC1, AC2) ; `alarmReset` → BC si
      BA ouverte, sinon rien (AC3, AC4) ; test de la séquence `release` puis `raz` (exactement
      BC, OP, jamais un second BC)
- [x] Task 5: Démon — `SiaEventCode` gagne `OP` (BC déjà présent), `_EVENT_SIA_CODES` pour
      `disarm`/`alarmReset`, `user_number` dans `EventItem` et l'adresse de trame (AC5, AC7)
- [x] Task 6: `siaDC09_update()` parcourt les eqLogic existants et appelle `postSave()` (AC6,
      constat #2)
- [x] Task 7: Libellé EVENT_FAILED T3 nomme l'annulation/désarmement, pas « alarme » (AC7,
      constat #4)
- [x] Task 8: Tests — retirer les tests d'éventail/dérogation/repli devenus sans objet, écrire
      les tests `disarm`/`alarmReset` (BC+OP, BC seul, séquence release-puis-raz, silence sans
      BA), niveau 1 construction de trame, niveau 2 charge utile IPC (`user_number`)
- [x] Task 9: Documentation plugin (aide assistant étape 3) + note de câblage
      `.claude/skills/jeedom-alarm/SKILL.md` — insister sur « câbler les deux commandes »
- [x] Task 10: Validation live sur `test-jeedom` contre la centrale interne (AC8) — exécutée via
      l'API Jeedom (`core/api/jeeApi.php`), après `git pull` + câblage manuel par Herve. Voir
      Dev Agent Record pour le détail des scénarios et des preuves

### Review Findings

Code review 2026-09-26 (`300b02a..ed8af11`, code+tests only — internal-docs/design excluded from this pass),
three parallel adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). All findings
verified against the actual code, not taken at face value.

- [x] [Review][Patch] `_resolveSiaUserNumber()` had no range validation [`core/class/siaDC09Cmd.class.php`] — the wizard field has `min="1" max="999"` (DC-03 Annex B: 3 zero-padded digits) but that's HTML-only; a saved 0/negative/>999 value would reach `f"{n:03d}"` on the daemon side unclamped. **Fixed:** clamp to 1-999, fallback to the existing default (1) otherwise. New parametrized test `test_disarm_falls_back_to_one_when_sia_user_number_out_of_range` (0, -1, 1000, 9999).
- [x] [Review][Patch] `siaDC09_update()` had no try/catch around `postSave()` [`plugin_info/install.php`] — one misbehaving eqLogic would throw and abort migration for every other siaDC09 eqLogic on the same instance, on every future plugin update. **Fixed:** each `postSave()` call is now isolated in its own try/catch, logging and continuing. New test `test_install_php_update_hook_isolates_each_eqlogic`.
- [x] [Review][Patch] AC5 gap — daemon didn't enforce "address field is never empty" at the IPC boundary [`resources/siadc09d/daemon.py`, `on_message()`] — a missing/unparsable `user_number` for a user-addressed code (BC/OP/CL) just logged a warning and enqueued the frame anyway with no address field, unlike an invalid `sia_code`, which is already rejected outright. Confirmed unreachable from today's only real caller (PHP always resolves a valid default) but latent and untested. **Fixed:** reject (warn + drop), same as the `sia_code` validation. New tests `test_on_message_rejects_bc_with_missing_user_number`, `test_on_message_rejects_bc_with_unparsable_user_number`.
- [x] [Review][Patch] `f"{user_number:03d}"` had no bounds check in `_build_event_frame()` [`resources/siadc09d/daemon.py`] — defense in depth alongside the two fixes above, in case a future caller bypasses both. **Fixed:** omit the address field entirely for an out-of-range value (same as `None`), never format one unchecked. New test `test_build_event_frame_omits_address_for_out_of_range_user_number`.
- [x] [Review][Patch] `context.get('user_number', '<inconnu>')` never actually falls back [`resources/siadc09d/error_handler.py:435`] — `EventFailedCtx.user_number` defaults to `None` and `to_dict()` always includes the key, so `dict.get(key, default)`'s default never triggers (it only applies when the key is *absent*, not when its value is `None`) — a BC/OP/CL failure notified before `user_number` was ever resolved rendered the literal text "(utilisateur: None)" in a French user-facing notification. **Fixed:** explicit `is not None` check. New test `test_event_failed_message_shows_inconnu_not_none_when_user_number_is_none`.

Deferred (real, pre-existing pattern or accepted design characteristic, not newly actionable — appended to `deferred-work.md`): two `sendToDaemon()` calls (BC then OP) with no atomicity and unconditional purge regardless of send success (pre-existing fire-and-forget local-socket IPC, identical pattern used by every command in the plugin, not fixable within this story); a theoretical concurrent disarm/alarmReset race producing a double BC (mitigated today by the alarm plugin's own documented release-before-raz ordering guarantee, same risk class as 14-2's D-52/D-53); the global `sia_user_number` meaning every household member disarms under the same SIA address (a disclosed Jeedom-platform limitation — the alarm plugin never exposes which user disarmed — not something this story could fix); debug-only logging collapsing two distinct "no open alarm" states for `alarmReset`; hardcoded French grammatical-gender flags in `build_notification()`, fragile for a future SIA code.

Dismissed as noise (verified false against the actual code): "`_hasOpenAlarm`/`_purgeOpenAlarms` assume at most one open alarm, contradicted by per-zone keying" — false: DC-03 deliberately carries no zone info for BC/OP (ADR-18), so collapsing every open per-zone BA entry into one account-level BC is the correct, intended design, not a bug; "`_EVENT_SIA_CODES` phrasing vs. the shipped `_VARIABLE_SIA_CODE_COMMANDS` design" — already disclosed and justified in this story's own Dev Notes, not a hidden deviation; "`burglaryCancel` legacy alias is unverified dead code" — it's a French-label lookup entry for the SIA code `"BC"`, not code invoked by name, no functional risk.

## Dépendance

Le retrait de l'éventail par zone rend la story indépendante de `zone_number`/
`_resolveZoneNumber()` côté 8-2 — les deux commandes n'utilisent plus aucune résolution de zone.
La seule dépendance nouvelle est la config `sia_user_number` (assistant étape 3, Task 2).

## Dev Notes

- **Ne pas partir du code existant en le retouchant.** `burglaryCancel`, `_fanOutBurglaryCancel()`,
  `_closeOpenAlarm()` mono-zone et le repli compte n'ont plus de raison d'être — ils s'appuyaient
  sur une adresse-zone non conforme DC-03. Les garder « au cas où » créerait deux façons
  concurrentes d'émettre un BC.
- `_loadOpenAlarms()` reste utile tel quel : c'est la lecture de la table, indépendante de ce
  qu'on en fait ensuite (avant : fan-out ; maintenant : test « une BA est-elle ouverte ? »).
- Le test de séquence `release` puis `raz` (AC4) est le seul test réellement nouveau côté
  logique : il fixe notre dépendance à l'ordre d'exécution du plugin alarme, documentée dans
  ADR-18. S'il casse un jour, c'est que le plugin alarme a changé cet ordre.
- **Historique de conception antérieur** (l'éventail par zone, l'analyse `bfb2445`, l'arbitrage
  A-PHP vs A-démon du 2026-09-18) reste dans le Change Log ci-dessous pour traçabilité, mais ne
  décrit plus le code à écrire.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (bmad-dev-story workflow, persona Amelia)

### Debug Log References

> **Entrées antérieures au rescope du 2026-09-25 retirées de cette section** — elles décrivaient
> l'implémentation de l'éventail par zone (`_recordOpenAlarm()`, `_fanOutBurglaryCancel()`,
> `burglaryCancel`), remplacée. Voir le Change Log pour l'historique complet. Les entrées Task 3
> (table `sia_open_alarms`) restent valables : la table est acquise sans changement de code.

- Task 3 (acquise, 2026-09-18/2026-09-25) : cycle red-green-refactor sur `_recordOpenAlarm()` —
  8 tests niveau 1 dans `test_php_eqlogic_stub.py`, clé `sia_code|zone_number|account`,
  dédoublonnage, éviction par `ts` au-delà de `OPEN_ALARMS_MAX`, purge TTL. `php -l` propre.
- Tasks 2/4 (2026-09-25) : retrait de `case 'burglaryCancel'`, `_fanOutBurglaryCancel()`,
  `_closeOpenAlarm()` de `siaDC09Cmd.class.php` ; ajout de `case 'disarm'`/`case 'alarmReset'`,
  `_hasOpenAlarm()`, `_purgeOpenAlarms()`, `_resolveSiaUserNumber()`. `_recordOpenAlarm()`/
  `_loadOpenAlarms()`/`_openAlarmKey()` inchangées (Task 3 acquise). Tests rouges d'abord
  (`tests/level1/test_burglary_cancel_behavior.py` réécrit intégralement, `tests/level1/
  test_php_eqlogic_stub.py` — nouveaux fixtures `disarm_body`/`alarm_reset_body`), puis code
  minimal, puis vérifiés verts (11 + 82 tests).
- Task 5 (2026-09-25) : `daemon.py` — `SiaEventCode` gagne `'OP'`. Ambiguïté résolue par
  jugement (documentée dans `daemon-design.md`, section "Consequences for the rest of
  Component 1") : `_EVENT_SIA_CODES` reste un dict fixe `cmd → code` pour `burglarAlarm`/
  `fireAlarm`/`panicAlarm` seulement — `disarm`/`alarmReset` en sont délibérément absents, car
  PHP envoie un `sendToDaemon()` par trame avec son propre `sia_code` (BC puis OP pour
  `disarm`), ce qu'un mapping fixe 1-code-par-commande ne peut pas exprimer. `on_message()` lit
  `params['sia_code']` pour ces deux commandes via un nouvel ensemble
  `_VARIABLE_SIA_CODE_COMMANDS`, validé contre `_USER_ADDRESSED_SIA_CODES = {'BC','OP'}`.
  `EventItem`/`OnMessageParams`/`EventQueuePayload` gagnent `user_number`. `_build_event_frame()`
  adresse par `user_number` (zero-paddé) pour BC/OP, par `zone_number` sinon.
  `_event_context_prefix()` gagne la branche `(utilisateur N)` pour BC/OP, `_event_user_number`
  ajouté à `__init__`/`_send_with_retry()`/la branche NO_NETWORK immédiate.
- Task 6 (2026-09-25) : `siaDC09_update()` (`plugin_info/install.php`, stub vide déjà présent)
  implémentée — `foreach (eqLogic::byType('siaDC09') as $eqLogic) { $eqLogic->postSave(); }`.
- Task 7 (2026-09-25) : `error_handler.py` — `EventFailedCtx.sia_code` élargi à `Literal['BA',
  'FA','PA','BC','OP']`, nouveau champ optionnel `user_number` (défaut `None`, sites d'appel
  BA/FA/PA inchangés). `event_type_fr('OP') == 'désarmement'`. `build_notification()` :
  wording EVENT_FAILED calculé dynamiquement par `sia_code` (sujet + accord de genre + clause
  d'adresse « utilisateur » vs « zone ») — vérifié manuellement (`build_notification(...)`) puis
  couvert par 3 nouveaux tests paramétrés dans `test_error_handler.py`.
- Task 8 (2026-09-25) : `tests/level1/test_burglary_cancel_behavior.py` réécrit (11 tests :
  BC+OP ordonnés, silence+debug sans BA, BC seul sur alarmReset, séquence release-puis-raz,
  user_number configuré/défaut, FA/PA n'ouvrent rien, TTL, cache JSON-string, non-réenregistrement
  du BC/OP). `test_php_eqlogic_stub.py` : tests d'éventail/dérogation retirés, 7 nouveaux tests
  structurels sur `disarm`/`alarmReset`. `test_error_handler.py` : `event_type_fr('OP')` + wording
  EVENT_FAILED (3 tests paramétrés). `test_ipc_daemon_wiring.py` TC-IPC6 : 5 nouveaux tests
  (`disarm`→BC, `disarm`→OP, `alarmReset`→BC, `sia_code` invalide ignoré + warning, frame BC/OP
  adressée par `user_number`). `test_sm2_alarm_event_suite.py` : label BC/OP au format
  `(utilisateur N)`, `_event_user_number` dans `test_sm2_instance_vars_exist`.
- Suite complète après chaque tâche : `tests/level1` (1187 passed, 2 failed — baseline inchangée),
  `tests/level2` (348 passed avant Task 8 final, 6 failed — baseline inchangée),
  `tests/level2_5` (76 passed, 1 failed — baseline inchangée). Total final : 1611 passed / 9
  failed (2+6+1), identique à la baseline connue avant cette session. `find core/ desktop/
  -name "*.php" | xargs -n1 php -l` : aucune erreur. `pylint resources/siadc09d/` : 8.85/10
  (baseline 8.84/10).

### Completion Notes

> **Notes antérieures au rescope retirées** (Tasks 2, 4, 5, 7, 8 de la conception par zone) —
> le code qu'elles décrivaient est à remplacer, pas à conserver. Voir Change Log.

- **Task 3 reste clôturée (AC3 de la conception précédente, rôle inchangé).** `_recordOpenAlarm()`
  mémorise chaque `burglarAlarm`/`fireAlarm`/`panicAlarm` émis dans `sia_open_alarms`, à
  l'émission, avec dédoublonnage, éviction par `ts`, purge par TTL. Réutilisée telle quelle comme
  oracle « une BA est-elle ouverte ? ».
- **Tasks 1, 2, 4-9 rouvertes** au rescope du 2026-09-25 : le code `burglaryCancel`/éventail/
  dérogation existant doit être retiré et remplacé par `disarm`/`alarmReset`.
- **Tasks 1-9 closes (2026-09-25, cette session).** `disarm`/`alarmReset` remplacent
  `burglaryCancel` de bout en bout : PHP (`postSave()`, `execute()`, `siaDC09_update()`,
  assistant étape 3), démon (`SiaEventCode`, dispatch `on_message()` à code variable,
  `_build_event_frame()` adressé par `user_number`), `error_handler.py` (wording EVENT_FAILED,
  `event_type_fr('OP')`), documentation (design docs Task 1 réconciliés post-implémentation,
  `.claude/skills/jeedom-alarm/SKILL.md`). Ambiguïté de design résolue par jugement documentée
  dans `daemon-design.md` (`_EVENT_SIA_CODES` ne gagne pas d'entrées `disarm`/`alarmReset` — un
  nouvel ensemble `_VARIABLE_SIA_CODE_COMMANDS` fait lire `sia_code` depuis le payload IPC à la
  place, un mapping fixe ne pouvant exprimer BC-puis-OP sous le même nom de commande). Aucune
  régression : 1611 tests passés / 9 échecs, identique à la baseline (2 niveau 1, 6 niveau 2, 1
  niveau 2.5) sur les trois suites. Task 10 (validation IHM réelle) reste hors de portée de cette
  session — nécessite un `git push` et une session avec Herve sur `test-jeedom.lehoux.net`.
- **Task 10 close (2026-09-25), validée en direct via l'API Jeedom, pas par clic manuel.**
  Après le `git push`/`pull` et le câblage manuel par Herve (`disarm`→`release`,
  `alarmReset`→`raz`, confirmé en relisant `config['release']`/`config['raz']` de l'eqLogic
  `alarm` via `core/api/jeeApi.php?type=fullData`), trois scénarios exécutés contre la vraie
  centrale interne, compte réel, avec nettoyage complet après chacun (désarmement + remise à
  zéro des deux détecteurs virtuels) :
  - **AC1 (disarm, BA ouverte → BC puis OP) :** `burglarAlarm` forcé, puis `released` appelé ;
    interrogation à haute fréquence (session HTTP persistante, sans délai entre lectures) de
    `event_state`/`event_label` a capturé les deux transitions dans l'ordre :
    `t=0.035s → "Annulation (utilisateur 1) : Confirmée par la centrale"` puis
    `t=0.052s → "Désarmement (utilisateur 1) : Confirmée par la centrale"` — BC puis OP,
    17 ms d'écart, les deux réellement acquittés par la centrale.
  - **AC3/AC4 (alarmReset, réinitialisation par changement de mode) :** chaîne physique réelle
    — équipement armé, détecteur virtuel `Detecteur2` mis à 1, délai de déclenchement réel
    observé (~31s) avant que `Statut` (état sonnant du plugin alarme) passe à 1 — puis rappel
    de la **même** action de mode (« Standard ») pendant que l'alarme sonnait, sans passer par
    `released`. Résultat : `event_label` = `"Annulation (utilisateur 1) : Confirmée par la
    centrale"` (BC seul), et **`Actif` (`enable`) est resté à `1`** pendant que `Statut`
    retombait à `0` — preuve directe que le système est resté armé (chemin `alarmReset`, pas
    `disarm`).
  - **AC2 (disarm, aucune BA ouverte → rien) :** armement puis `released` immédiat, sans alarme
    entre les deux. `event_label` inchangé avant/après — aucune trame envoyée.
  - **Non testé en direct, par construction :** la survie d'une entrée `FA`/`PA` concurrente au
    travers d'un `_purgeOpenAlarms('BA')` (le bug corrigé cette session) — rien ne lit encore
    cette mémoire côté API tant que la story 13-3 n'existe pas, donc rien n'est observable de
    l'extérieur ; couvert uniquement par le test de régression PHP
    (`test_disarm_with_ba_and_fire_open_purges_only_ba`). De même, la création des commandes par
    `siaDC09_update()` (constat #2) n'a pas été déclenchée de façon isolée — les commandes
    étaient déjà présentes après le `pull`+sauvegarde d'Herve, ce qui ne distingue pas
    `postSave()` d'un enregistrement manuel de `siaDC09_update()` d'une mise à jour de plugin ;
    couvert par les tests PHP unitaires seulement.
  - **Mécanisme d'accès :** clés API scopées par plugin (`plugin=alarm`, `plugin=siaDC09`),
    jamais la clé core, conformément à la préférence d'Herve. Découverte des identifiants de
    commandes réels via `type=fullData` (lecture seule) ; déclenchements via `type=cmd&id=<id>`
    (`execCmd()` réel — même chemin qu'un clic dans l'IHM ou qu'un capteur physique). Aucune
    clé n'a été écrite sur disque au-delà d'un script `/tmp` supprimé en fin de session.

### File List

- `core/class/siaDC09Cmd.class.php` — `case 'burglaryCancel'`, `_fanOutBurglaryCancel()`,
  `_closeOpenAlarm()` retirés ; `case 'disarm'`, `case 'alarmReset'`, `_hasOpenAlarm()`,
  `_purgeOpenAlarms()`, `_resolveSiaUserNumber()` ajoutés. `_recordOpenAlarm()`/
  `_loadOpenAlarms()`/`_openAlarmKey()`/constantes `OPEN_ALARMS_*` inchangés (Task 3 acquise)
- `core/class/siaDC09.class.php` — `$actionCmds` : `burglaryCancel` → `disarm`+`alarmReset`
  (`subType other`)
- `plugin_info/install.php` — `siaDC09_update()` implémentée (itère `eqLogic::byType('siaDC09')`,
  appelle `postSave()` sur chacun)
- `core/i18n/en_US.json` — clé `"Annulation intrusion"` remplacée par `"Désarmement"` /
  `"Réinitialisation alarme"`
- `desktop/php/siaDC09.php` — champ assistant étape 3 `sia_user_number` (numérique, 1-999,
  défaut 1) ; paragraphe d'aide « Annulation » réécrit pour `disarm`/`alarmReset`, avertissement
  explicite « câbler les deux »
- `resources/siadc09d/daemon.py` — `SiaEventCode` gagne `'OP'` ; `_EVENT_SIA_CODES` perd
  `burglaryCancel` ; nouveaux `_VARIABLE_SIA_CODE_COMMANDS`/`_USER_ADDRESSED_SIA_CODES` ;
  `EventItem`/`OnMessageParams`/`EventQueuePayload` gagnent `user_number` ; `on_message()` lit
  `sia_code` depuis le payload pour `disarm`/`alarmReset` ; `_build_event_frame()` adresse par
  `user_number` pour BC/OP ; `_event_context_prefix()`/`__init__`/`_send_with_retry()`/branche
  NO_NETWORK gagnent `_event_user_number` ; 4 sites `EventFailedCtx(...)` gagnent `user_number`
- `resources/siadc09d/error_handler.py` — `EventFailedCtx.sia_code` élargi (`+'OP'`), nouveau
  champ `user_number` (défaut `None`) ; `event_type_fr()` gagne `'OP' → 'désarmement'` ;
  `build_notification()` : wording EVENT_FAILED dynamique par `sia_code` (sujet, genre, adresse
  utilisateur/zone) ; `_context_to_dict()` (EventFailedCtx branch) transmet `user_number`
- `.claude/skills/jeedom-alarm/SKILL.md` — note de câblage réécrite pour `disarm`+`alarmReset`,
  tableau des deux hooks, avertissement « câbler les deux »
- `tests/level1/test_burglary_cancel_behavior.py` — réécrit intégralement (11 tests
  `disarm`/`alarmReset`, table TTL/JSON-string conservée)
- `tests/level1/test_php_eqlogic_stub.py` — tests d'éventail/dérogation retirés ; 7 nouveaux
  tests structurels (`disarm_body`/`alarm_reset_body` fixtures, `_hasOpenAlarm`/
  `_purgeOpenAlarms`, ordre BC avant OP, `user_number`, silences debug)
- `tests/level1/test_error_handler.py` — `event_type_fr('OP')` + 2 tests paramétrés sur le
  wording EVENT_FAILED BC/OP. Code review 2026-09-26 : `test_event_failed_message_shows_inconnu_not_none_when_user_number_is_none`
- `core/class/siaDC09Cmd.class.php` — Code review 2026-09-26 : `_resolveSiaUserNumber()` clamp
  1-999
- `plugin_info/install.php` — Code review 2026-09-26 : `postSave()` isolé par try/catch dans
  `siaDC09_update()`
- `resources/siadc09d/daemon.py` — Code review 2026-09-26 : `on_message()` rejette `user_number`
  manquant/invalide pour un code adressé utilisateur ; `_build_event_frame()` garde-fou de plage
  0-999 avant `f"{n:03d}"`
- `resources/siadc09d/error_handler.py` — Code review 2026-09-26 : correction du bug
  `dict.get(key, default)`/`None` sur la clause d'adresse EVENT_FAILED
- `tests/level1/test_burglary_cancel_behavior.py` — Code review 2026-09-26 : test paramétré
  `test_disarm_falls_back_to_one_when_sia_user_number_out_of_range` (0, -1, 1000, 9999)
- `tests/level1/test_install_php.py` — Code review 2026-09-26 :
  `test_install_php_update_hook_isolates_each_eqlogic`
- `tests/level2/test_ipc_daemon_wiring.py` — Code review 2026-09-26 :
  `test_on_message_rejects_bc_with_missing_user_number`,
  `test_on_message_rejects_bc_with_unparsable_user_number`,
  `test_build_event_frame_omits_address_for_out_of_range_user_number`
- `tests/level2/test_ipc_daemon_wiring.py` — TC-IPC6 réécrit (`disarm`→BC, `disarm`→OP,
  `alarmReset`→BC, `sia_code` invalide, frame adressée par `user_number`)
- `tests/level2/test_sm2_alarm_event_suite.py` — label BC/OP au format `(utilisateur N)`,
  `_event_user_number` dans `test_sm2_instance_vars_exist`
- `internal-docs/design/php-core-design.md` — snippets `disarm`/`alarmReset` alignés sur le code réel
  (Task 1 réconciliation)
- `internal-docs/design/daemon-design.md` — note de déviation `_EVENT_SIA_CODES`/
  `_VARIABLE_SIA_CODE_COMMANDS` ; wording EVENT_FAILED documenté (Task 1 réconciliation)
- `internal-docs/design/widget-design.md` — tableau `event_label` corrigé au format réel (Task 1
  réconciliation)

## Change Log

| Date | Description |
|------|-------------|
| 2026-09-17 | Story créée depuis les constats de l'Epic 12 — support BR/BC avec trois questions de conception bloquantes |
| 2026-09-18 | Task 1 / AC1 close (`bfb2445`) : trois questions répondues dans les docs de conception (toujours émettre, table non persistée ; `event_state` inchangé ; zone saisie dans le *Titre*) |
| 2026-09-18 | **Story rescopée après revue adverse et arbitrage utilisateur.** BR transféré à la story 13-2 (parquée). Option A (mémoriser les alarmes par zone, éventail sur réinitialisation), variante A-PHP retenue. ACs et Tasks refondus |
| 2026-09-18 | Task 3 / AC3 close : table `sia_open_alarms` implémentée dans `siaDC09Cmd.class.php` via `_recordOpenAlarm()`, 8 tests niveau 1 ajoutés |
| 2026-09-25 | Task 6 close sans objet + AC7 amendée (format `event_label` livré par la 10-3, format riche) |
| 2026-09-25 | Tasks 2, 4, 5, 7, 8 closes : commande `burglaryCancel`, éventail N BC, `BC` accepté par le démon, 20 tests ajoutés. Reste Task 9 (validation IHM) |
| 2026-09-25 | **Story rescopée une seconde fois** (`sprint-change-proposal-2026-09-25.md`), après relecture du tableau DC-03 complet : `BC` s'adresse par **numéro d'utilisateur**, jamais par zone — l'éventail par zone livré le même jour n'était pas conforme DC-03. Périmètre étendu sur demande d'Herve : ajout d'`OP` (désarmement pendant une alarme) et de la commande `alarmReset` (câblée sur `raz`, pour le cas réinitialisation-par-changement-de-mode sans désarmement, découvert lors de cette relecture). `burglaryCancel`, l'éventail, la dérogation mono-zone et le repli compte sont retirés (jamais livrés en dehors de cette session, aucune migration). CL et l'OP du désarmement normal partent vers la nouvelle story 13-4 (backlog) ; FC/PC vers la 13-3 (backlog). Nouvel ADR-18. Tasks 1, 2, 4-9 rouvertes ; Task 3 (table `sia_open_alarms`) reste acquise, rôle réduit. Nouvelle Task 10 (validation IHM, remplace l'ancienne Task 9) |
| 2026-09-25 | **Tasks 1-9 closes** (rescope de code, cette session). `burglaryCancel`/`_fanOutBurglaryCancel()`/`_closeOpenAlarm()` retirés de `siaDC09Cmd.class.php` ; `disarm`/`alarmReset` ajoutés (PHP : `postSave()`, `execute()` avec `_hasOpenAlarm()`/`_purgeOpenAlarms()`/`_resolveSiaUserNumber()` ; config `sia_user_number` assistant étape 3 ; démon : `SiaEventCode` + `'OP'`, dispatch `on_message()` à `sia_code` variable via `_VARIABLE_SIA_CODE_COMMANDS` — déviation documentée dans `daemon-design.md`, `_EVENT_SIA_CODES` n'exprimait pas BC-puis-OP sous un même nom de commande —, adresse `user_number` dans `_build_event_frame()`/`_event_context_prefix()` ; `error_handler.py` : `event_type_fr('OP')`, wording EVENT_FAILED nommant l'annulation/désarmement au lieu d'« alarme », adressé par utilisateur (constat #4) ; `siaDC09_update()` implémentée (constat #2) ; documentation assistant + `.claude/skills/jeedom-alarm/SKILL.md` réécrites, insistant sur le câblage des deux commandes ; design docs (Task 1) relus et corrigés pour cohérence avec le code livré. Tests : `test_burglary_cancel_behavior.py` réécrit (11 tests), `test_php_eqlogic_stub.py` (7 tests structurels remplacent les tests d'éventail), `test_error_handler.py` (+3 tests), `test_ipc_daemon_wiring.py` TC-IPC6 réécrit (5 tests), `test_sm2_alarm_event_suite.py` (labels BC/OP). Aucune régression : 1611 passed / 9 failed, identique à la baseline (2/6/1) sur level1/level2/level2.5. `php -l` propre sur tout `core/`+`desktop/`. `pylint resources/siadc09d/` : 8.85/10. Task 10 (validation IHM réelle) reste ouverte — hors de portée de cette session |
| 2026-09-25 | **Correction post-implémentation.** `_purgeOpenAlarms()` videait la table `sia_open_alarms` **entière** sur un BC, y compris les entrées `FA`/`PA` concurrentes — contraire à l'intention documentée (« FA/PA restent mémorisées pour la story 13-3 ») et non couverte par un test. `_purgeOpenAlarms(string $siaCode)` retire désormais uniquement les entrées du code passé (`'BA'` aux deux points d'appel) ; un test de régression ajouté (`test_disarm_with_ba_and_fire_open_purges_only_ba`) couvre le cas BA+FA concurrents. Aucune régression (1188 passed / 2 niveau 1, 6 niveau 2, 1 niveau 2.5 — identique à la baseline, un test de plus qu'avant) |
| 2026-09-25 | **Commit + push** (`16aaef1` docs, `1c5a36b` code+tests) sur `master`, sur demande explicite d'Herve. Puis **Task 10 close** : validation live sur `test-jeedom.lehoux.net` (compte réel, centrale interne réelle), exécutée par l'agent directement via l'API Jeedom (`core/api/jeeApi.php`, clés scopées par plugin fournies par Herve) après qu'Herve a fait le `git pull`, la sauvegarde de l'équipement (commandes `disarm`/`alarmReset` créées) et le câblage manuel (`disarm`→`release`, `alarmReset`→`raz`). AC1 capturé avec horodatage précis (BC confirmé à t=0.035s, OP à t=0.052s, 17ms d'écart, session HTTP à interrogation continue) ; AC3/AC4 confirmé via la chaîne physique réelle (capteur virtuel → délai de déclenchement réel ~31s → `Statut` sonnant) avec preuve directe que le système reste armé (`Actif` reste à 1) pendant la réinitialisation ; AC2 confirmé (rien envoyé sans alarme ouverte). Nettoyage complet après chaque scénario (désarmement, détecteurs à 0). La survie d'une entrée `FA`/`PA` concurrente (le bug corrigé ci-dessus) et la création des commandes par `siaDC09_update()` spécifiquement ne sont pas observables via cette API et restent couvertes par les seuls tests unitaires PHP. Statut : in-progress → review |
| 2026-09-26 | Code review (`/bmad-code-review`, diff `300b02a..ed8af11` scopé code+tests, 3 couches adversariales). 4 patches appliqués et testés : `_resolveSiaUserNumber()` clampé 1-999 (aucune validation serveur n'existait, seul le `min`/`max` HTML) ; `siaDC09_update()` isole désormais chaque `postSave()` dans son propre try/catch (une erreur sur un équipement n'abortait plus la migration des autres) ; `daemon.py::on_message()` rejette maintenant un `user_number` manquant/invalide pour un code adressé utilisateur (BC/OP/CL) au lieu d'envoyer silencieusement une trame sans adresse (comblait un écart AC5 latent) — plus un garde-fou de plage 0-999 en défense en profondeur dans `_build_event_frame()` ; correction d'un bug `dict.get(key, default)`/`None` dans `error_handler.py` qui affichait littéralement "(utilisateur: None)" dans une notification EVENT_FAILED. 3 de ces items recoupent des constats déjà notés en différé sous 13-4 (D-65/D-68/D-71) — désormais marqués résolus dans `deferred-work.md`. 5 nouveaux items différés (D-72 à D-76 : atomicité BC/OP, course concurrente disarm/alarmReset, adresse utilisateur globale, log debug-only, genre grammatical français codé en dur). 3 rejetés comme bruit après vérification contre le code réel. 7 nouveaux tests, 0 régression (baseline exacte : level1 2, level2 6, level2_5 1). Statut : review → done |
