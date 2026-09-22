---
story_id: "13-1"
story_key: "13-1-burglary-restore-cancel-events"
epic_id: "epic-13"
epic_name: "Alarm Event Vocabulary Extension (v1.1)"
status: "ready-for-dev"
created: "2026-09-17"
---

# Story 13.1: Burglary Cancel (BC) — corrélation par zone côté plugin

> **Rescopée le 2026-09-18.** La story couvrait BR **et** BC. BR est retirée et transférée à la
> story **13-2** (parquée, `backlog`) : le plugin alarme n'émet **aucun** événement « détecteur
> revenu à la normale », donc BR n'a pas de source. La clé `13-1-burglary-restore-cancel-events`
> est conservée pour ne pas casser `sprint-status.yaml` ni l'historique (même précédent que
> 12-5 → 12-7). La décision de conception n° 1 committée en `bfb2445` est **renversée** :
> la corrélation zone n'est pas l'affaire de la centrale, c'est la nôtre.

Status: ready-for-dev — Task 1 (conception) **close** (`613b0fe`) : les trois sections sont
réécrites en « Burglary Cancel (BC) », conformes à la décision de l'utilisateur du 2026-09-18.
Reste Tasks 2-9 (code, tests, doc, validation terrain).

## Story

As a monitored Jeedom user,
I want the plugin to report the end of an intrusion (BC) **on the same zones that alarmed**,
So that the CSR closes every open zone of the incident instead of keeping them open until an
operator calls.

## Contexte — pourquoi la corrélation nous revient

Le fait décisif, établi sur la source amont (`jeedom/plugin-alarm`, `core/class/alarm.class.php`,
master) :

| Côté | Action alarme | Cardinalité | Zone fournie |
|------|---------------|-------------|--------------|
| Déclenchement | `outbreak` (`:605`), `outbreakImmediate` (`:583`), `actions` / `actionsImmediate` de zone via `doZoneAction()` | **une fois par zone déclenchée** (garde `:601`, avec `splitZone = 1`) | **oui** — `#zone#` = `$zone['name']` |
| Réinitialisation | `raz` (`:712`), `razImmediate` (`:707`), `release` (`:703`) | **une seule fois pour l'équipement** | **non** — `#mode#` seulement (et `raz`/`razImmediate` en `:818`/`:822` ne passent **aucune** option) |

Soit **N BA en entrée, 1 événement de réinitialisation sans zone en sortie**. DC-09 n'offre par
ailleurs aucun champ de référence arrière (grep « restoral »/« cancel » dans
`docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` : zéro occurrence) : le numéro de zone
est la **seule** clé de corrélation transportable, et le numéro de séquence n'est qu'un
discriminant de doublon (§ 5.5.1.5).

Conséquence : **sans mémoire de notre côté, un BC ne peut pas correspondre aux BA émis.** C'est
l'option A retenue par l'utilisateur : nous mémorisons les alarmes émises par zone, et le
déclencheur global unique produit un BC par zone encore ouverte.

Le plugin alarme possède l'information (cache `trigger_zone`, écrit en `:602`, vidé en `:714-715`
donc **après** que `raz` ait tiré) mais ne la transmet pas — d'où l'option A plutôt qu'une lecture
opportuniste de son cache (voir « Options écartées »).

### Emplacement de la mémoire — décidé le 2026-09-18 : A-PHP

Deux variantes de l'option A. **A-PHP est retenue** (arbitrage utilisateur du 2026-09-18) ;
A-démon reste documentée pour que le choix soit traçable.

| | **A-PHP** (retenue) | A-démon |
|---|---|---|
| Support | cache eqLogic (`setCache`/`getCache`, Redis) | `dict` en mémoire dans `daemon.py` |
| Survit au redémarrage du démon | **oui** — dont le redémarrage *volontaire* introduit par la 7-2 (self-stop sur `NO_NETWORK` → watchdog Jeedom) | non |
| Conflit de merge | aucun : `siaDC09Cmd.class.php` n'est sous édition par personne | `daemon.py` = point chaud (7-2 / 12-4 / 12-5 / 12-7) |
| Chirurgie SM2 | **aucune** — un BC est un événement ordinaire de plus | table + cycle de vie à greffer dans SM2 |
| Numéro de zone | déjà résolu ici (`_resolveZoneNumber()`, 8-2) | à re-transporter |
| Moment de l'enregistrement | à l'**émission** (pas à l'ACK) | possible à l'ACK |
| Testable | PHP niveau 1 / 2.5, sans asyncio | niveau 2 asyncio |

Le seul avantage d'A-démon est de connaître l'ACK. Il ne pèse pas : la politique du plugin est
**ne jamais supprimer une trame**, donc un BC de trop est bénin et un BC manquant est le cas
dangereux. Enregistrer à l'émission est donc le bon côté de l'erreur.

## Conception retenue (option A, variante A-PHP)

### Déclencheur — une seule commande globale

`burglaryCancel` — « Annulation intrusion », ACTION / `subType message`, `isVisible 0`,
`returnStateTime 30` / `returnStateValue 0`, créée idempotemment par `postSave()`. L'utilisateur la
câble sur l'action **`raz`** du plugin alarme (et/ou `razImmediate`). Aucun tag n'est requis dans le
*Titre*.

Un *Titre* **non vide** reste une dérogation mono-zone explicite (zone saisie littéralement,
chemin 8-2 inchangé) ; un *Titre* **vide** déclenche l'éventail depuis la table.

### Table des alarmes ouvertes

Cache eqLogic `sia_open_alarms`, dictionnaire clé → entrée :

- **clé** = `sia_code . '|' . ($zone_number !== null ? $zone_number : 'account')`
  — déduplique nativement les BA répétés sur une même zone, et fait s'effondrer toutes les zones
  non résolues sur **une** entrée « compte » (sinon deux libellés inconnus produiraient deux BC
  sans zone, c'est-à-dire deux doublons sur le fil) ;
- **entrée** = `['sia_code' => 'BA'|'FA'|'PA', 'zone' => <libellé|null>, 'zone_number' => <int|null>, 'ts' => <timestamp>]`.

La table est **bornée par construction** : `3 codes × (N zones + 1)`. Un plafond dur
(`OPEN_ALARMS_MAX`) reste en garde contre un cache corrompu, avec éviction de la **plus ancienne
par `ts`** — jamais « le premier du dictionnaire », l'ordre d'insertion n'étant pas un contrat.
Un TTL (`OPEN_ALARMS_TTL`) protège le cas où aucune réinitialisation n'arrive jamais (plugin alarme
désactivé en pleine alarme).

**Point d'écriture** : branche `burglarAlarm` / `fireAlarm` / `panicAlarm` de
`siaDC09Cmd::execute()`, juste après `siaDC09::sendToDaemon()`.

### Éventail sur annulation

Sur `burglaryCancel` avec *Titre* vide :

1. lire `sia_open_alarms` ;
2. pour chaque entrée de code **`BA`**, émettre un BC portant **le même `zone_number`** que le BA
   qu'il clôt, dans l'ordre d'insertion ;
3. vider la table, en journalisant en `debug` les entrées `FA`/`PA` abandonnées — **`BC` ne clôt
   que des `BA`** ; les entrées incendie/panique sont mémorisées pour les futurs `FC`/`PC`
   (story 13-3 potentielle) mais ne doivent jamais être fermées par un BC ;
4. **table vide** (annulation en doublon, cache vidé, démon ou Redis redémarré) → émettre
   **exactement un** `[#001234|BC]` au niveau du compte avec un `warning`. Jamais zéro trame.

Chaque BC suit le chemin EVENT normal (priorité 0, PENDING → CONFIRMED/FAILED, retries) : N appels
`sendToDaemon()` indiscernables d'une alarme ordinaire.

### Démon — modifications minimales

- `SiaEventCode = Literal['BA', 'FA', 'PA', 'BC']` (`daemon.py:144`) ;
- `_EVENT_SIA_CODES` (`:256`) gagne `"burglaryCancel": "BC"` ;
- `error_handler.py` : `sia_code: Literal[...]` et la table `event_type` → libellé français
  (`:328`, `:366`) gagnent `BC` → `annulation` ;
- table de libellés SM2 : `BC` → `Annulation` ;
- `_build_event_frame()` (`:1556`) est **déjà générique** sur `sia_code` et `zone_number` :
  aucune modification.

Pas de nouvel état SM2, pas de table dans le démon, pas de nouvelle sémantique de file.

### `event_state` — inchangé

0/1/2/3 conservés (axe « état de transmission », orthogonal au type d'événement) ; l'annulation
passe par `event_label`. Cette décision (n° 2 de `bfb2445`) **survit** au renversement de la
décision n° 1 : elle ne dépendait pas de l'hypothèse de corrélation.

### Options écartées

- **B — lire le cache `trigger_zone` du plugin alarme.** Techniquement faisable (il est encore
  peuplé quand notre commande tourne) mais c'est un couplage à l'état interne d'un plugin tiers,
  sans contrat ni test amont.
- **C — un BC sans zone ferme tout le compte.** Dépend du comportement de la centrale ; à vérifier
  sur `192.168.100.15:10002` comme validation (Task 9), pas comme mécanisme.
- **D — BR depuis le retour à la normale du détecteur.** Hors périmètre → story 13-2.
- **`reenableTrigger` (`:547`) comme source de BR.** Passe bien `#zone#` mais sa sémantique est
  « un capteur en défaut à l'armement est revenu à la normale », et il peut tirer sans qu'aucune
  alarme n'ait eu lieu. Ce n'est pas un rétablissement.

## Dépendance

Numéro de zone livré par l'évolution 8-2 (`zone_number` dans `sia_zone_mappings`, résolu par
`siaDC09Cmd::_resolveZoneNumber()`) : un BC doit porter **le même** numéro que le BA qu'il clôt, et
le libellé n'est pas une clé de corrélation utilisable.

## Acceptance Criteria

1. **Conception corrigée :** les trois sections `## Restoral events (BR / BC)` ajoutées par
   `bfb2445` à `daemon-design.md`, `widget-design.md` et `php-core-design.md` sont **réécrites**
   (pas complétées) : décision n° 1 renversée, emplacement et cycle de vie de la table documentés,
   BR retiré et renvoyé vers 13-2.

2. **Commande exposée :** `burglaryCancel` (« Annulation intrusion ») est créée idempotemment par
   `postSave()` en ACTION / `message`, `isVisible 0`, `returnStateTime 30` / `returnStateValue 0`,
   et la documentation plugin indique « à câbler sur l'action *Remise à zéro* (`raz`) du plugin
   alarme, sans tag dans le Titre ».

3. **Mémorisation :** toute alarme émise (`burglarAlarm` / `fireAlarm` / `panicAlarm`) crée ou
   rafraîchit une entrée `(sia_code, zone_number|account)` dans `sia_open_alarms`, avec dédoublonnage
   vérifié, éviction de la plus ancienne par `ts` au-delà de `OPEN_ALARMS_MAX`, et expiration par
   `OPEN_ALARMS_TTL`.

4. **Éventail :** un `burglaryCancel` à *Titre* vide, après N BA sur N zones distinctes, émet
   **exactement N** BC portant les N mêmes numéros de zone ; la table est ensuite vide ; les entrées
   `FA`/`PA` présentes ne produisent aucune trame et sont journalisées en `debug`.

5. **Repli jamais muet :** table vide → **exactement une** trame `[#001234|BC]` sans champ zone,
   plus un `warning`. Zéro trame est un échec de l'AC.

6. **Dérogation mono-zone :** un *Titre* non vide émet un unique BC pour cette zone (chemin 8-2
   inchangé) et retire l'entrée correspondante sans toucher aux autres.

7. **Démon :** `SiaEventCode`, `_EVENT_SIA_CODES` et `error_handler.py` acceptent `BC` ;
   `event_state` conserve 0/1/2/3 ; `event_label` affiche le format riche
   `Annulation — Salon — HH:MM:SS — Confirmé par la centrale`.

8. **Trames correctes sur la vraie centrale :** `[#001234|BA 001]` puis `[#001234|BC 001]` tous deux
   acquittés (ACK) par `192.168.100.15:10002` en TCP, compte `001234`.

9. **Validation terrain multi-zones :** sur `test-jeedom.lehoux.net` (192.168.100.40), via
   **l'IHM Jeedom réelle** et non par réflexion de code — déclencher deux zones, réinitialiser une
   fois, lire les deux BC et leurs numéros dans l'inspecteur de protocole.

## Tasks / Subtasks

- [x] Task 1: Réécrire les trois sections de conception de `bfb2445` (AC1) — décision n° 1 renversée,
      A-PHP documentée face à A-démon, BR renvoyé à 13-2
- [ ] Task 2: `burglaryCancel` dans `postSave()` + nouveau cas dans `siaDC09Cmd::execute()` (AC2, AC6)
- [x] Task 3: Table `sia_open_alarms` — écriture, clé, dédoublonnage, `OPEN_ALARMS_MAX`, TTL (AC3)
- [ ] Task 4: Éventail N BC + purge + `debug` sur `FA`/`PA` + repli compte avec `warning` (AC4, AC5)
- [ ] Task 5: Démon — `SiaEventCode`, `_EVENT_SIA_CODES`, `error_handler.py`, libellé `Annulation` (AC7)
- [ ] Task 6: `_event_label_from_sm2()` au format riche (divergence préexistante, cf. note ci-dessous) (AC7)
- [ ] Task 7: Tests — PHP unitaire sur la table (dédoublonnage, éviction, TTL, éventail, repli,
      dérogation), niveau 1 construction de trame BC, niveau 2.5 charge utile IPC
- [ ] Task 8: Documentation plugin + note de câblage dans `.claude/skills/jeedom-alarm/SKILL.md`
- [ ] Task 9: Validation IHM sur `test-jeedom` contre la centrale interne (AC8, AC9)

> **Divergence préexistante reprise de `bfb2445` :** `daemon.py::_event_label_from_sm2()` (`:656`)
> renvoie `Inactif`/`En cours`/`Confirmé`/`Échoué` alors que les deux docs de conception spécifient
> le format riche. L'AC7 n'a de sens qu'au format riche → Task 6 ferme cette divergence pour **tous**
> les états SM2, et ajoute la ligne `event_label` que l'onglet diagnostic jette aujourd'hui.

## Séquencement

Bien plus léger qu'avant la réduction de périmètre, parce qu'A-PHP sort du point chaud :

| Task | Touche | Attend |
|---|---|---|
| Tasks 1, 3, 4, 7 (PHP) | `siaDC09Cmd.class.php`, tests | rien — aucun agent n'édite ce fichier |
| Task 2 | `siaDC09.class.php` (`postSave()`) | **10-3** (éditions non committées en cours) |
| Tasks 5, 6 | `daemon.py` (quelques lignes), `error_handler.py` | 12-5, 7-2, 12-4, 12-7 |
| Tasks 8, 9 | doc, validation terrain | les précédentes |

## Dev Notes

- **Ne pas commencer par l'extension du `Literal`.** Ajouter `'BC'` fait compiler et construit la
  trame, ce qui masque toute la question de corrélation jusqu'à ce que la centrale garde des zones
  ouvertes en production.
- Les trois tags (`#mode#`, `#alarm_trigger#`, `#zone#`) sont **non documentés dans l'IHM du plugin
  alarme** (`desktop/php/alarm.php` et `desktop/js/alarm.js` : zéro référence) → la documentation
  plugin doit détailler le câblage.
- `#zone#` vaut le **libellé** (`$zone['name']`), jamais un numéro : le modèle de zone est
  `{name, actions, actionsImmediate, triggers}` (`desktop/js/alarm.js:232-238`), la position dans le
  tableau n'est ni persistée ni exposée.
- `doAction()` (`:639`) ignore toute action dont la commande appartient à l'équipement alarme
  lui-même (`$this->getId() == $cmd->getEqLogic_id()` → `continue`). Sans effet pour nous, mais cela
  contraint le câblage utilisateur.
- **Divergence doc/code relevée le 2026-09-18 — cosmétique, mais à corriger (Task 1).**
  `php-core-design.md:529-556` décrit un `$commandsSpec` unique de 7 entrées portant des `order`
  1-7. Le `postSave()` livré (`core/class/siaDC09.class.php:622-665`) est structuré autrement :

  | | doc (`php-core-design.md:529-556`) | code livré (`siaDC09.class.php:622-665`) |
  |---|---|---|
  | structure | un tableau `$commandsSpec` (7 entrées) | deux tableaux `$actionCmds` (3) + `$infoCmds` (4) |
  | `order` | 1 à 7 | **absent** — aucun appel `setOrder()` |
  | `event_state` | `Transmission alarme` | `État alarme` |
  | `supervision_label` | `Supervision détail` | `Supervision` |
  | `event_label` | `Dernier événement` | `Alarme` |
  | `returnStateTime`/`returnStateValue` | sur les 7 | **sur les 7** — vérifié (`:638-639`, `:660-661`) |

  Aucune conséquence fonctionnelle : le garde-fou anti-`PENDING` bloqué (`event_state = 3` figé si
  le démon tombe en pleine alarme) est bien en place. Deux corollaires quand même :
  `burglaryCancel` n'a **pas** d'`order` à choisir — il suffit d'une ligne de plus dans
  `$actionCmds` — et la Task 1 doit aligner la doc sur le code (ou l'inverse), parce qu'un document
  de conception qui ne décrit pas le code livré est un piège pour le prochain développeur qui s'y
  fie. C'est aussi ce qui invalide le constat « `order` 8/9 » de la revue adverse, retiré.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (bmad-dev-story workflow, persona Amelia)

### Debug Log References

- Task 3 : cycle red-green-refactor sur `_recordOpenAlarm()` — 8 tests RED ajoutés dans
  `tests/level1/test_php_eqlogic_stub.py`, GREEN obtenu par l'écriture dans
  `siaDC09Cmd.class.php` (clé `sia_code|zone_number|account`, dédoublonnage, éviction par `ts`
  au-delà de `OPEN_ALARMS_MAX`, purge TTL), `php -l` propre.
- Vérification de non-régression complète : `python3 -m pytest tests/level1/ -q` → 49 échecs,
  tous confinés à trois fichiers étrangers à ce Task : `test_diagnostic_js_dom.py` (47 —
  `node_modules`/`jsdom` absent de ce worktree), `test_wizard_config_key_consistency.py::test_csr_provider_key_in_python`
  et `test_connection_test.py::test_run_connection_test_preset_crc_format_used` (1 chacun — même
  lacune préexistante côté démon : `"csr_provider"` absent de `resources/siadc09d/siadc09d.py`,
  sans lien avec `siaDC09Cmd.class.php`). Aucun des 8 tests ciblés du Task 3 n'est dans cette liste.

### Completion Notes

- **Task 3 clôturé (AC3).** `_recordOpenAlarm()` mémorise chaque `burglarAlarm`/`fireAlarm`/`panicAlarm`
  émis dans le cache eqLogic `sia_open_alarms`, à l'émission (juste après `sendToDaemon()`), avec
  dédoublonnage par clé, éviction de la plus ancienne par `ts` au-delà de `OPEN_ALARMS_MAX` (90) et
  purge par `OPEN_ALARMS_TTL` (86400s). 8 tests niveau 1 (source-validation, sans interpréteur PHP)
  couvrent l'écriture, la clé, le dédoublonnage, l'éviction et le TTL.
- Régression vérifiée : les 49 échecs de la suite `tests/level1/` sont préexistants/environnementaux
  (voir Debug Log) et n'ont aucun rapport avec cette modification.

### File List

- `core/class/siaDC09Cmd.class.php` — MODIFIED (ajout de `_recordOpenAlarm()` et des constantes
  `OPEN_ALARMS_MAX`/`OPEN_ALARMS_TTL`/`OPEN_ALARMS_SIA_CODES`)
- `tests/level1/test_php_eqlogic_stub.py` — MODIFIED (8 tests ajoutés pour la table `sia_open_alarms`)

## Change Log

| Date | Description |
|------|-------------|
| 2026-09-17 | Story créée depuis les constats de l'Epic 12 — support BR/BC avec trois questions de conception bloquantes |
| 2026-09-18 | Task 1 / AC1 close (`bfb2445`) : trois questions répondues dans les docs de conception (toujours émettre, table non persistée ; `event_state` inchangé ; zone saisie dans le *Titre*) |
| 2026-09-18 | **Story rescopée après revue adverse et arbitrage utilisateur.** Constat : le plugin alarme fournit la zone au déclenchement mais la réinitialisation est un événement global **sans zone** (N BA en → 1 réinit. out), et BR n'a aucune source. Décision : **option A** — mémoriser les alarmes émises par zone et produire un BC par zone ouverte ; variante **A-PHP** (cache eqLogic) spécifiée, A-démon documentée et écartée. BR **transféré à la story 13-2** (parquée `backlog`). La décision n° 1 de `bfb2445` est renversée → Task 1 rouverte, les trois sections de conception sont à **réécrire**. Statut in-progress → ready-for-dev, ACs et Tasks refondus. Retrait aussi d'un constat erroné de la revue adverse : les `order` 8/9 n'existent pas, `postSave()` n'utilise aucun `order` |
| 2026-09-18 | Task 3 / AC3 close : table `sia_open_alarms` (écriture, clé, dédoublonnage, `OPEN_ALARMS_MAX`, TTL) implémentée dans `siaDC09Cmd.class.php` via `_recordOpenAlarm()`, 8 tests niveau 1 ajoutés ; régression vérifiée (49 échecs préexistants/environnementaux, sans rapport) |
