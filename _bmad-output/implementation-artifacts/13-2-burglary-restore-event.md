---
story_id: "13-2"
story_key: "13-2-burglary-restore-event"
epic_id: "epic-13"
epic_name: "Alarm Event Vocabulary Extension (v1.1)"
status: "backlog"
created: "2026-09-18"
---

# Story 13.2: Burglary Restore (BR) — parquée, faute de source

> **Story parquée délibérément.** Elle n'est pas bloquée par un autre agent ni par une dépendance
> technique : elle est bloquée par l'**absence d'événement source**. Ne pas la passer
> `ready-for-dev` avant qu'une des pistes de la section « Conditions de déparquage » soit levée.
> Transférée depuis la story **13-1** le 2026-09-18, quand 13-1 a été réduite à BC seul.

## Story

As a monitored Jeedom user,
I want the plugin to report that a zone returned to normal (BR) while the incident is still open,
So that the CSR sees which detectors have settled without waiting for the whole alarm to be reset.

## Pourquoi c'est parqué — le plugin alarme n'a pas cet événement

`BR` (*Burglary Restore*) signifie « le détecteur de cette zone est revenu à la normale ». C'est
sémantiquement distinct de `BC` (*Burglary Cancel*, « l'utilisateur a annulé l'alarme ») que traite
la story 13-1.

Revue exhaustive des actions de `jeedom/plugin-alarm` (`core/class/alarm.class.php`, master) :

| Action | Sémantique | Zone | Utilisable pour BR ? |
|--------|------------|------|----------------------|
| `outbreak`, `outbreakImmediate`, `actions`/`actionsImmediate` de zone | déclenchement | oui | non — c'est le BA |
| `release` (`:703`) | fin d'alarme / sirène coupée | **non** (`#mode#`) | non — global, et c'est une fin d'alarme, pas un retour à la normale de capteur |
| `raz` (`:712`), `razImmediate` (`:707`) | remise à zéro | **non** | non — c'est le déclencheur de BC (story 13-1) |
| `activationOk` (`:809`), `activationImmediateOk` | armement réussi | non | non |
| `activationKo` (`:111`, `:794`) | armement impossible | oui (liste) | non — défaut à l'armement |
| `reenableTrigger` (`:547`) | un capteur en défaut **à l'armement** est revenu à la normale | **oui** | **non** — voir ci-dessous |

**Aucune action n'existe pour « un détecteur est revenu à la normale pendant une alarme ».** Le
plugin alarme ne surveille pas le retour à 0 des déclencheurs en cours d'alarme.

### Pourquoi `reenableTrigger` n'est pas un substitut

C'est le seul candidat qui porte `#zone#`, d'où la tentation. Mais il ne tire que lorsqu'un
déclencheur mis en cache dans `disable_trigger` — c'est-à-dire un capteur **déjà en alerte au moment
de l'armement, et donc volontairement exclu de la surveillance** — repasse à 0. Deux défauts
rédhibitoires :

1. sa sémantique est « un capteur en défaut à l'armement est redevenu exploitable », pas
   « un capteur en alarme est revenu à la normale » ;
2. il peut tirer **sans qu'aucune alarme n'ait eu lieu** — l'envoyer en BR fabriquerait un
   rétablissement d'une alarme jamais signalée, exactement l'incohérence protocolaire que la
   story 13-1 s'attache à éviter.

### Rappel protocolaire

DC-09 est un transport : grep de « restoral » / « cancel » dans
`docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md` → **zéro occurrence**, aucun champ de
référence arrière. Le numéro de zone est la seule clé de corrélation transportable (§ 5.5.1.5 : le
numéro de séquence est un discriminant de doublon, pas un identifiant d'événement). Cela n'empêche
pas BR techniquement — la trame `[#001234|BR 001]` se construit avec le code déjà en place — cela
signifie simplement que BR n'a de valeur que s'il porte le **bon** numéro de zone, au **bon** moment.

## Conditions de déparquage

Trois pistes, par ordre de coût croissant. La première levée débloque la story.

1. **Source hors plugin alarme (option D, la plus propre).** Brancher `burglaryRestore` sur le
   retour à la normale du **détecteur lui-même** (commande binaire de l'équipement Z-Wave / Zigbee /
   autre), via un scénario Jeedom ou une action de l'équipement source, avec la zone saisie dans le
   *Titre*. Coût : documentation + un cas dans `siaDC09Cmd::execute()`. Ne dépend d'aucune évolution
   amont. **Piste recommandée si la story est reprise en l'état.**
2. **Surveillance de nos propres déclencheurs.** Le plugin lirait l'état des commandes déclencheuses
   déclarées dans les zones de l'alarme et émettrait BR sur leur retour à 0. Coût réel : nous
   dupliquons la logique de zones du plugin alarme et devenons dépendants de sa configuration
   interne. À n'envisager que si la piste 1 est jugée trop manuelle.
3. **Évolution amont.** Proposer à `jeedom/plugin-alarm` une action `triggerRestore` portant
   `#zone#`, tirée sur le retour à 0 d'un déclencheur en cours d'alarme. Coût : délai indéterminé,
   hors de notre contrôle.

## Ce qui est déjà acquis (à ne pas refaire)

La story 13-1 livre l'essentiel de l'infrastructure, BR n'en réutilise que des morceaux :

- résolution `libellé → zone_number` (`siaDC09Cmd::_resolveZoneNumber()`, story 8-2) ;
- `_build_event_frame()` (`daemon.py:1556`) déjà générique sur `sia_code` + `zone_number` :
  aucune modification de trame nécessaire ;
- le motif d'extension du vocabulaire (`SiaEventCode`, `_EVENT_SIA_CODES`, `error_handler.py`,
  table de libellés) est établi par la story 13-1 — BR n'ajoute qu'une entrée par table ;
- `event_state` conserve 0/1/2/3, le type d'événement passe par `event_label`
  (`BR` → `Rétablissement`) — décision de conception validée en `bfb2445` et non remise en cause.

La table `sia_open_alarms` de la story 13-1 serait par ailleurs la **bonne** source pour valider un
BR (« cette zone a-t-elle réellement alarmé ? ») et pour retirer l'entrée fermée, mais avec la même
politique que 13-1 : un BR non corrélé produit un `warning`, **jamais** une suppression de trame.

## Acceptance Criteria (esquisse — à figer au déparquage)

1. La source de l'événement de rétablissement est documentée et câblable par l'utilisateur, avec la
   piste retenue parmi les trois ci-dessus.
2. `burglaryRestore` (« Rétablissement intrusion ») exposée en ACTION / `message`, `isVisible 0`,
   `returnStateTime 30` / `returnStateValue 0`, créée idempotemment par `postSave()`.
3. Trame `[#001234|BR 001]` acquittée (ACK) par `192.168.100.15:10002` en TCP, compte `001234`.
4. Zone non résolue → `[#001234|BR]` sans champ zone, plus un `warning` — jamais le libellé.
5. BR sur une zone qui n'a jamais alarmé → `warning` et trame **transmise quand même** (politique
   « ne jamais supprimer une trame »), avec un test qui le prouve.
6. Validation par l'**IHM Jeedom réelle** sur `test-jeedom.lehoux.net` (192.168.100.40), pas par
   réflexion de code.

## Change Log

| Date | Description |
|------|-------------|
| 2026-09-18 | Story créée par transfert depuis 13-1, qui est réduite à BC seul. Motif du parking : revue exhaustive de `alarm.class.php` — aucune action n'exprime « un détecteur est revenu à la normale », et `reenableTrigger` n'est pas un substitut valide (sémantique « défaut à l'armement levé », et peut tirer sans alarme). Trois conditions de déparquage consignées, piste 1 (source hors plugin alarme) recommandée |
