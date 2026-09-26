---
story_id: "13-4"
story_key: "13-4-arm-disarm-closing-opening-reports"
epic_id: "epic-13"
epic_name: "Alarm Event Vocabulary Extension (v1.1)"
status: "review"
created: "2026-09-26"
---

# Story 13.4: Armement/désarmement — Closing (CL) & Opening (OP)

Complète 13-1 : `disarm` (sur `release`) envoie déjà BC puis OP quand une BA est ouverte, mais
n'envoie **rien** sinon — c'est la branche `else` que cette story remplit avec OP. Elle ajoute
aussi une nouvelle commande `arm` (sur `activationImmediateOk`) pour CL. Voir ADR-18
(`architecture.md:504-530`) et le Sprint Change Proposal du 2026-09-25 (`_bmad-output/
planning-artifacts/sprint-change-proposal-2026-09-25.md:231-247`), qui a déjà tranché la
conception de cette story lors du rescope de 13-1.

## Story

As a monitored Jeedom user,
I want the CSR to know when my system is armed and disarmed, and by which user,
so that it can check openings/closings against my schedule.

## Acceptance Criteria

1. **Given** une nouvelle commande d'action `arm` (« Armement ») câblée sur l'action
   `activationImmediateOk` du plugin alarme, et un `sia_user_number` configuré (défaut 1,
   même config que 13-1)
   **When** le système s'arme avec succès
   **Then** exactement une trame `[#{compte}|CL {user:03d}]` est émise.

2. **And** `arm` n'est **jamais** câblée sur `activationOk` : cette action ne se déclenche que
   si aucun détecteur n'était actif à l'armement, et ne se déclenche **plus du tout** après un
   `activationKo` (porte restée ouverte) — elle manquerait donc l'armement dans ce cas.
   `activationImmediateOk` se déclenche à **chaque** armement réussi, contrairement à
   `activationOk`.

3. **Given** la commande `disarm` (13-1, câblée sur `release`)
   **When** l'utilisateur désarme alors qu'**aucune** BA n'est ouverte (désarmement normal, hors
   contexte d'alarme)
   **Then** `disarm` émet désormais `[#{compte}|OP {user:03d}]`, au lieu de ne rien émettre
   (remplace le `log::add(..., 'debug', ...)` de la branche `else` actuelle,
   `siaDC09Cmd.class.php:119-123`).

4. **And** le comportement existant de `disarm` quand une BA **est** ouverte (BC puis OP, 13-1)
   n'est pas modifié par cette story — seule la branche `else` change.

5. **And** CR n'est jamais utilisé pour l'armement : CR signifie *Recent Closing* (une alarme
   dans les 5 minutes suivant l'armement), pas « armé ». Ce n'est ni testé ni codé dans cette
   story — la commande `arm` n'émet que CL.

6. **And** le champ d'adresse de CL n'est jamais un numéro de zone, et n'est jamais vide — même
   convention d'adressage par `user_number` que BC/OP (13-1, ADR-18).

7. **And** `siaDC09_update()` crée la nouvelle commande `arm` sur les installations existantes,
   sans enregistrement manuel de l'équipement (même mécanisme que 13-1, constat #2 —
   `siaDC09_update()` appelle déjà `postSave()` sur chaque eqLogic `siaDC09`, donc l'ajout de
   `arm` à `$actionCmds` suffit, aucun changement de `install.php` requis).

8. **And** `SiaEventCode` (démon) et `EventFailedCtx.sia_code` (error_handler) acceptent `CL` en
   plus de `BA`/`FA`/`PA`/`BC`/`OP`. `event_label` affiche `Armement (utilisateur 1) : Confirmée
   par la centrale` (même format `{action} (utilisateur N) : {état}` que BC/OP). La notification
   EVENT_FAILED T3 pour un CL non acquitté nomme l'armement, pas une « alarme ».

9. **And** la question ouverte de l'épic (« reporter un armement avec zones dérogées
   [`activationKo`] différemment ou non ») est réglée par construction : `arm` n'est câblée que
   sur `activationImmediateOk`, jamais sur `activationKo`. Un armement avec dérogation reste
   silencieux côté SIA — pas de CL avant l'AC1 de `activationImmediateOk` réel, pas de code
   spécial pour signaler une dérogation. Aucune action supplémentaire n'est nécessaire pour
   clore cette question dans le cadre de cette story.

10. **And** validation en direct sur `test-jeedom.lehoux.net`, compte réel, centrale interne
    `192.168.100.15:10002` : armer puis désarmer (hors contexte d'alarme), lire CL puis OP dans
    l'inspecteur de protocole, dans cet ordre.

## Tasks / Subtasks

- [x] Task 1: PHP — `siaDC09.class.php::postSave()` (`:689-707`) : ajouter `'arm' => ['name' =>
      __('Armement', __FILE__), 'subType' => 'other']` à `$actionCmds` (AC1, AC6, AC7). Pas de
      *Titre* nécessaire (même raisonnement que `disarm`/`alarmReset` — adresse = `user_number`
      configuré, jamais une donnée que le plugin alarme peut fournir).
- [x] Task 2: PHP — `siaDC09Cmd.class.php::execute()` (`:35-140`) :
  - [x] `case 'arm':` — résout `sia_user_number` via `_resolveSiaUserNumber()` (réutilisée telle
        quelle, 13-1), envoie `siaDC09::sendToDaemon(['cmd' => 'arm', 'user_number' =>
        $userNumber])` (AC1). **Déviation par rapport au plan initial** : pas de `'sia_code' =>
        'CL'` dans le payload — voir Dev Notes / Debug Log ci-dessous.
  - [x] `case 'disarm':` (`:111-124`) — remplacer la branche `else` (`log::add(..., 'debug',
        ...)`) par `siaDC09::sendToDaemon(['cmd' => 'disarm', 'user_number' => $userNumber,
        'sia_code' => 'OP'])` (AC3). Branche `if` (AC4) non modifiée.
- [x] Task 3: Démon — `daemon.py` :
  - [x] `SiaEventCode` (`:149`) gagne `'CL'` (AC8).
  - [x] `_USER_ADDRESSED_SIA_CODES` (`:320`) gagne `'CL'` (adressage par `user_number`, AC6).
  - [x] `arm` ajoutée à `_EVENT_SIA_CODES` (`:304`, mapping fixe `cmd → code`) : contrairement à
        `disarm`/`alarmReset`, `arm` n'émet jamais qu'un seul code (`CL`) — pas besoin de
        `_VARIABLE_SIA_CODE_COMMANDS`. `on_message()` (`:2135-2147`) accepte le chemin
        mapping-fixe pour `arm` sans modification.
  - [x] `_event_context_prefix()` et `_build_event_frame()` : les deux tuples en dur `("BC",
        "OP")` remplacés par la constante `_USER_ADDRESSED_SIA_CODES` (déjà étendue à `CL`),
        au lieu d'ajouter `"CL"` en dur à deux endroits (M2 — no magic strings).
- [x] Task 4: Démon — `error_handler.py` :
  - [x] `EventFailedCtx.sia_code` (`:328`) gagne `'CL'`.
  - [x] `event_type_fr('CL')` → `'armement'` (AC8).
  - [x] `build_notification()` : nouvelle branche `elif _event_sia_code == "CL":` (sujet
        `"L'armement"`/`"l'armement"`, pas de `e` d'accord — masculin, comme OP) ; la clause
        d'adresse « utilisateur » étendue à `("BC", "OP", "CL")`.
- [x] Task 5: Tests — niveau 1 PHP réel (`test_burglary_cancel_behavior.py`, exécute le vrai
      `siaDC09Cmd.class.php` via un harnais PHP) : `arm` → CL inconditionnel + `user_number`
      configuré ; `disarm` sans BA ouverte → OP seul (remplace les 4 tests qui attendaient le
      silence de 13-1 — `test_disarm_with_no_open_ba_emits_op`,
      `test_disarm_with_only_fire_or_panic_open_emits_op_not_bc`,
      `test_expired_ba_entry_is_not_treated_as_open`,
      `test_bc_and_op_are_never_recorded_as_open_alarms`) ; `disarm` avec BA ouverte → BC puis OP
      inchangé (AC4, non-régression). Niveau 1 regex (`test_php_eqlogic_stub.py`) : déclaration
      `arm` dans `$actionCmds`, routage `case 'arm'`, absence de `'sia_code'` dans le payload
      PHP d'`arm`. Niveau 2 IPC (`test_ipc_daemon_wiring.py`, TC-IPC7) : `arm` → CL par
      `user_number`, adressage de trame `[#001234|CL 001]`. Niveau 1 `test_error_handler.py` :
      `event_type_fr('CL')`, wording EVENT_FAILED paramétré pour `CL`.
- [x] Task 6: Documentation —
  - [x] Aide assistant étape 3 (`desktop/php/siaDC09.php`) : paragraphe réécrit pour couvrir les
        trois commandes (`disarm`/`alarmReset`/`arm`).
  - [x] `.claude/skills/jeedom-alarm/SKILL.md` : table de câblage étendue à `arm` →
        `activationImmediateOk`, avec l'avertissement explicite « jamais sur `activationOk` ».
  - [x] `docs/design/php-core-design.md` : snippets `disarm` (branche `else`) et `arm` alignés
        sur le code livré ; `$actionCmds` et table de câblage mis à jour.
  - [x] `docs/design/daemon-design.md` : nouvelle section « Arm/Disarm Reporting — Story 13-4
        design decisions » (mapping fixe `arm`, généralisation `_USER_ADDRESSED_SIA_CODES`,
        wording EVENT_FAILED CL).
  - [x] `docs/design/widget-design.md` : ligne `CL` ajoutée au tableau `event_label`, mapping
        SIA→français étendu, `_event_context_prefix()` mis à jour.
  - [x] `docs/design/wizard-design.md` : note « et later CL » corrigée (CL livré).
- [x] Task 7: Validation live sur `test-jeedom.lehoux.net` contre la centrale interne (AC10) —
      via l'API Jeedom (`core/api/jeeApi.php`, clés scopées `plugin=alarm`/`plugin=siaDC09`
      fournies par Herve), après qu'Herve a fait le `git pull`, la sauvegarde de l'équipement
      (commande `arm` créée) et le câblage manuel (confirmé en relisant la config de
      l'eqLogic `alarm` via `type=fullData` : `activationImmediateOk` → cmd `#289#` (`arm`),
      `release` → cmd `#287#` (`disarm`), `raz` → cmd `#288#` (`alarmReset`), tous
      `enable: "1"`). Voir Dev Agent Record pour le détail.

## Dev Notes

- **Ne pas retoucher la branche `if` de `disarm`** (`_hasOpenAlarm('BA')` → BC puis OP, 13-1).
  Cette story ne change que la branche `else`.
- **`arm` est un mapping fixe, `disarm` reste variable.** `disarm` doit rester dans
  `_VARIABLE_SIA_CODE_COMMANDS` (il émet BC+OP *ou* OP selon le contexte) — ne pas essayer de le
  faire basculer vers `_EVENT_SIA_CODES`. `arm`, à l'inverse, n'émet jamais qu'un seul code : le
  mapping fixe existant (`burglarAlarm`/`fireAlarm`/`panicAlarm`) est le bon patron à suivre, pas
  celui de `disarm`/`alarmReset`.
- **`activationImmediateOk` vs `activationOk` — ne pas se tromper de hook.** C'est le point
  bloquant identifié dès le sprint-change-proposal : câbler `arm` sur `activationOk` manquerait
  tout armement précédé d'un `activationKo` (porte ouverte). Le Dev Agent Record de 13-1 et
  `_bmad-output/implementation-artifacts/13-2-burglary-restore-event.md:36-37` documentent déjà
  ce couple de hooks — les relire avant de coder si le comportement du plugin alarme est ambigu.
- **`_resolveSiaUserNumber()`, `_hasOpenAlarm()`, `_purgeOpenAlarms()` sont acquises de 13-1** —
  `arm` n'a besoin que de la première ; les deux autres ne concernent que le cycle BA/BC.
- **AC9 (dérogation à l'armement) est une décision de conception actée dans cette story, pas une
  question ouverte à retransmettre.** Ne pas ajouter de code ou de SIA code supplémentaire pour
  les dérogations — `arm`/`activationImmediateOk` seul couvre l'AC.
- Invoquer `/jeedom-alarm` si le comportement exact d'`activationImmediateOk`/`activationOk`/
  `activationKo` doit être revérifié dans `alarm.class.php` au moment du code (le skill couvre
  les zones/modes/triggers du plugin alarme).

### Project Structure Notes

- Mêmes fichiers que 13-1 : `core/class/siaDC09.class.php`, `core/class/siaDC09Cmd.class.php`,
  `resources/siadc09d/daemon.py`, `resources/siadc09d/error_handler.py`,
  `desktop/php/siaDC09.php`, `.claude/skills/jeedom-alarm/SKILL.md`, les quatre design docs. Pas
  de nouveau fichier attendu.
- `plugin_info/install.php` (`siaDC09_update()`) n'a besoin d'**aucun** changement — implémentée
  en 13-1 comme une boucle générique sur `postSave()`, elle couvre `arm` automatiquement dès
  qu'il est ajouté à `$actionCmds`.

### References

- [Source: _bmad-output/planning-artifacts/sprint-change-proposal-2026-09-25.md#4.2 (Story 13.4 block, lignes 231-247)]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 13.4 (lignes 2251-2270)]
- [Source: _bmad-output/planning-artifacts/architecture.md#ADR-18 (lignes 504-530)]
- [Source: core/class/siaDC09Cmd.class.php#execute() (lignes 35-140), notamment le case 'disarm' (lignes 111-124)]
- [Source: core/class/siaDC09.class.php#postSave() (lignes 688-707)]
- [Source: resources/siadc09d/daemon.py — SiaEventCode (149), _EVENT_SIA_CODES (304), _VARIABLE_SIA_CODE_COMMANDS (317), _USER_ADDRESSED_SIA_CODES (320)]
- [Source: resources/siadc09d/error_handler.py — EventFailedCtx.sia_code (328), event_type_fr()]
- [Source: _bmad-output/implementation-artifacts/13-1-burglary-restore-cancel-events.md — conception et Dev Agent Record de référence pour `_resolveSiaUserNumber`/`_hasOpenAlarm`/`_purgeOpenAlarms`, et pour le mécanisme de validation live via l'API Jeedom]
- [Source: _bmad-output/implementation-artifacts/13-2-burglary-restore-event.md#lignes 36-37 (table activationOk/activationImmediateOk/activationKo)]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (bmad-dev-story workflow)

### Debug Log References

- Task 2 (`arm`, déviation) : le plan initial de la story proposait d'envoyer
  `'sia_code' => 'CL'` explicitement dans le payload PHP d'`arm`, par analogie avec
  `disarm`/`alarmReset`. En codant Task 3, ça aurait rendu `arm` incohérent avec son propre
  mécanisme choisi (mapping fixe `_EVENT_SIA_CODES`, comme `burglarAlarm`/`fireAlarm`/
  `panicAlarm`) : soit le `sia_code` envoyé par PHP est ignoré (payload trompeur — le lecteur
  croit qu'il compte), soit `arm` bascule dans `_VARIABLE_SIA_CODE_COMMANDS` (perd l'avantage
  du mapping fixe pour une commande qui n'a justement qu'un seul code possible). Retiré
  `'sia_code'` du payload PHP : `arm` suit exactement le même patron que `burglarAlarm` (le
  nom de la commande suffit, le démon connaît le code). Un test dédié
  (`test_arm_sends_user_number_unconditionally`) vérifie l'absence de `'sia_code'` dans le
  payload, pour que cette décision ne régresse pas silencieusement.
- Task 3 : plutôt que d'ajouter `"CL"` en dur aux deux tuples `("BC", "OP")` existants
  (`_event_context_prefix()`, `_build_event_frame()`), les deux ont été remplacés par la
  constante `_USER_ADDRESSED_SIA_CODES` (déjà présente depuis 13-1, déjà étendue à `CL` pour
  Task 3.1) — un seul endroit à faire évoluer si un futur code utilisateur-adressé apparaît
  (13-3 : FC/PC restent zone-adressés donc non concernés).
- Task 5 : 4 tests de `test_burglary_cancel_behavior.py` écrits par 13-1 attendaient
  explicitement le silence de `disarm` sans BA ouverte (`out["sent"] == []` / log debug) —
  comportement que cette story remplace par l'émission d'OP (AC3). Réécrits pour affirmer OP
  seul (jamais BC) au lieu du silence, plutôt que supprimés, pour garder la couverture des cas
  qu'ils ciblaient (table vide, FA/PA seuls sans BA, entrée BA expirée, non-réenregistrement
  après un premier disarm).
- Suite complète après chaque tâche : `tests/level1` (1221 passed, 2 failed — baseline
  inchangée, sans rapport avec 13-4), `tests/level2` (351 passed, 6 failed — baseline
  inchangée), `tests/level2_5` (77 passed, 1 failed — baseline inchangée). `find core/
  desktop/ -name "*.php" | xargs -n1 php -l` : aucune erreur. `pylint resources/siadc09d/` :
  8.85/10 (identique à la baseline pré-13-4).
- Task 7 (validation live, 2026-09-26) : premier essai bloqué — `supervision_state` = 0
  (« ARRÊTÉ ») sur `test-jeedom.lehoux.net` : le démon siaDC09 n'était pas démarré (piège déjà
  connu — cf. mémoire projet « daemon down looks like frozen label »). Alarme remise à l'état
  désarmé propre, script `/tmp` avec les clés API supprimé. Après qu'Herve a redémarré le
  démon : `supervision_state` est resté à `1` (« Connexion en cours d'initialisation ») pendant
  ~55s avant de passer à `2` (« Connexion OK ») — délai de démarrage de supervision déjà
  documenté (D-42, `daemon_supervision_startup_delay`), pas un bug de cette story. Une fois
  `HEALTHY` : armement → `event_label` = « Armement (utilisateur 1) : Confirmée par la
  centrale » (t≈0.04s, CL acquitté) ; désarmement sans BA ouverte → « Désarmement (utilisateur
  1) : Confirmée par la centrale » (t≈0.05s, OP seul, jamais BC). État final `enable=0`/
  `state=0` — aucun nettoyage supplémentaire nécessaire. Mécanisme d'accès identique à 13-1 :
  clés API scopées par plugin, jamais la clé core ; aucune clé écrite sur disque au-delà d'un
  script `/tmp` supprimé après usage.

### Completion Notes List

- Tasks 1-5 closes. `arm` (Armement, `subType other`) ajoutée à `postSave()` et à
  `execute()` — envoie CL inconditionnellement, adressé par `sia_user_number`, sans jamais
  transmettre son propre `sia_code` (mapping fixe côté démon, comme `burglarAlarm`/
  `fireAlarm`/`panicAlarm`). `disarm`'s branche `else` (13-1) envoie désormais OP au lieu de
  rien (AC3) ; sa branche `if` (BC puis OP, 13-1) est inchangée (AC4). Démon : `SiaEventCode`
  et `_USER_ADDRESSED_SIA_CODES` gagnent `CL` ; `_EVENT_SIA_CODES` gagne `'arm' → 'CL'` ;
  `_event_context_prefix()`/`_build_event_frame()` généralisés via la constante partagée.
  `error_handler.py` : `event_type_fr('CL')`, wording EVENT_FAILED dédié à CL (« L'armement »,
  accord masculin comme OP), clause d'adresse utilisateur étendue à CL. Aucune régression sur
  les trois suites de tests. Documentation (aide assistant, `jeedom-alarm/SKILL.md`, quatre
  design docs) réconciliée avec le code livré (Task 6). Task 7 close (2026-09-26) : validation
  live sur `test-jeedom.lehoux.net` — armement confirmé CL, désarmement sans BA ouverte confirmé
  OP seul, après un premier essai bloqué par le démon arrêté (résolu par Herve). Toutes les
  tâches et tous les AC sont couverts. Statut : ready-for-dev → review.

### File List

- `core/class/siaDC09.class.php` — `$actionCmds` gagne `'arm'` (`subType other`)
- `core/class/siaDC09Cmd.class.php` — `case 'arm'` ajouté ; `case 'disarm'`'s branche `else`
  envoie désormais OP au lieu de logguer en debug
- `resources/siadc09d/daemon.py` — `SiaEventCode` gagne `'CL'` ; `_EVENT_SIA_CODES` gagne
  `'arm' → 'CL'` ; `_USER_ADDRESSED_SIA_CODES` gagne `'CL'` ; `_event_context_prefix()` et
  `_build_event_frame()` généralisés à `_USER_ADDRESSED_SIA_CODES` (au lieu de tuples en dur
  `("BC", "OP")`) ; docstring `OnMessageParams` mise à jour
- `resources/siadc09d/error_handler.py` — `EventFailedCtx.sia_code` gagne `'CL'` ;
  `event_type_fr()` gagne `'CL' → 'armement'` ; `build_notification()` gagne la branche `CL`
  (sujet, objet, accord, clause d'adresse)
- `tests/level1/test_burglary_cancel_behavior.py` — 2 nouveaux tests (`arm` → CL inconditionnel
  + `user_number` configuré) ; 4 tests réécrits (silence de 13-1 → OP de 13-4 pour
  `test_disarm_with_no_open_ba_emits_op`, `test_disarm_with_only_fire_or_panic_open_emits_op_not_bc`,
  `test_expired_ba_entry_is_not_treated_as_open`, `test_bc_and_op_are_never_recorded_as_open_alarms`)
- `tests/level1/test_php_eqlogic_stub.py` — fixture `arm_body` ; 3 nouveaux tests (`arm`
  déclarée dans `$actionCmds`, routée dans `execute()`, envoie `user_number` sans `sia_code`) ;
  `test_disarm_silent_and_logs_debug_when_no_open_alarm` renommé/réécrit en
  `test_disarm_sends_op_when_no_open_alarm`
- `tests/level1/test_error_handler.py` — `test_event_type_fr_maps_closing_report` ; cas `CL`
  ajouté au test paramétré EVENT_FAILED
- `tests/level2/test_ipc_daemon_wiring.py` — TC-IPC7 (`test_on_message_arm_enqueues_cl_with_user_number`) ;
  `test_build_event_frame_bc_and_op_address_by_user_number` étendu au cas CL
- `desktop/php/siaDC09.php` — aide assistant étape 3 réécrite pour les trois commandes
- `.claude/skills/jeedom-alarm/SKILL.md` — table de câblage étendue à `arm`
- `docs/design/php-core-design.md` — snippets `disarm`/`arm`, `$actionCmds`, table de câblage
- `docs/design/daemon-design.md` — nouvelle section « Arm/Disarm Reporting — Story 13-4 »
- `docs/design/widget-design.md` — ligne `CL`, mapping SIA→français, `_event_context_prefix()`
- `docs/design/wizard-design.md` — note « et later CL » corrigée

## Change Log

| Date | Description |
|------|-------------|
| 2026-09-26 | Story créée (contexte déjà largement conçu par le rescope de 13-1 / sprint-change-proposal-2026-09-25.md) |
| 2026-09-26 | Tasks 1-6 closes. `arm` (Armement, mapping fixe → CL) ajoutée ; `disarm`'s branche `else` envoie désormais OP (13-4 AC3) au lieu du silence de 13-1. Démon et error_handler généralisés à CL via `_USER_ADDRESSED_SIA_CODES`. 4 tests de 13-1 réécrits (silence → OP), 2+3 tests ajoutés (arm). Aucune régression (baseline inchangée : level1 2, level2 6, level2.5 1 échecs pré-existants). Documentation (assistant, skill, 4 design docs) réconciliée avec le code livré. Commit `ba780fe` + push sur `master` |
| 2026-09-26 | **Task 7 close.** Validation live sur `test-jeedom.lehoux.net`, compte réel, centrale interne réelle, via l'API Jeedom (clés scopées par plugin). Câblage manuel d'Herve confirmé par lecture de la config (`activationImmediateOk`→`arm`, `release`→`disarm`, `raz`→`alarmReset`, tous actifs). Premier essai bloqué par le démon arrêté (`supervision_state=0`) — résolu par Herve, délai de démarrage de supervision habituel (~55s) observé avant `HEALTHY`. Armement confirmé CL (`event_label` = "Armement (utilisateur 1) : Confirmée par la centrale") ; désarmement sans BA ouverte confirmé OP seul. État final propre. Statut : ready-for-dev → review |
