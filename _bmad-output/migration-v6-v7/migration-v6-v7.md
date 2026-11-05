---
type: migration
title: Migration BMad v6 vers v7 (module method)
status: approved
created: 2026-11-05
---

# Migration v6 vers v7

Etat: **approuve le 2026-11-05, execution en cours**. Avant l'approbation, seuls la sauvegarde et ce fichier avaient ete ecrits.

## Sauvegarde

`.v6-v7-migration-backup-20261105-1209/` : copie de `_bmad/` et de `_bmad-output/` (92 fichiers), contenu verifie identique a la source, `.gitignore` contenant `*`. Jamais commitee ni editee.

## Questions et reponses

| Question | Reponse | Raison |
|---|---|---|
| Sources | planning = `_bmad-output/planning-artifacts/`, implementation = `_bmad-output/implementation-artifacts/`, plus les fichiers a la racine de `_bmad-output/` | precision de Herve : du contenu existe a la racine |
| Workspace / depot separe | Non (defaut) | dossier de sortie reste dans le depot du projet |
| Stories en cours (review, ready-for-dev, epics in-progress) | Migrer maintenant | statuts convertis, voir tableau |
| Fiches des stories backlog non demarrees | Replier dans l'entree, fichier vers `archive-v6/` | defaut |
| Fichiers hors planification a la racine | Rattacher a l'initiative | voir "Fichiers hors cadre" |
| Initiative | `initiative-my-project` | `core.project_name = my-project`, un seul PRD |

## Cible

```
_bmad-output/
  initiative-my-project/              <- planning-artifacts/ renomme
    initiative-my-project.md          (enveloppe, nouveau)
    tickets.toml                      (un [[epic]] par epic, ordre de epics.md)
    prd/                              prd.md -> prd-my-project/prd-my-project.md
    architecture/                     architecture.md -> architecture-my-project/architecture-my-project.md
    implementation-readiness-report-2026-04-07/  et  ...-2026-05-04/   (un dossier chacun)
    sprint-change-proposal-2026-09-25/, -2026-10-02/, -2026-10-17/, -2026-10-17-csr-profiles/
    requirements-14-4-frigate-forced-capture-2026-09-26/
    deferred-work.md                  (voir "Conflit deferred-work")
    epic-<slug>/ x17                  (enveloppe + tickets.toml + plans + retros)
    archive-v6/                       (epics.md, sprint-status.yaml, fiches repliees)
  backlog/                            (cree, avec .gitkeep)
  archive/                            (cree, avec .gitkeep)
  migration-v6-v7/migration-v6-v7.md  (ce fichier)
```

Les noms de dossiers de documents gardent leurs dates. Les dossiers de documents plats (`prd.md`, `architecture.md`) prennent le nom du projet comme le demande le guide.

## Epics

| N | Slug | Statut v7 | Remarque |
|---|---|---|---|
| 1 | epic-protocol-engine | in-progress | 1-5 en review (reouverte D-81) |
| 2 | epic-csr-simulator | done | |
| 3 | epic-error-handler | done | |
| 4 | epic-logging-observability | done | |
| 5 | epic-daemon-core-state-machines | done | |
| 6 | epic-php-plugin-core-ipc | done | |
| 7 | epic-supervision-health-monitoring | done | retro `epic-7-retro-2026-05-07.md` |
| 8 | epic-configuration-wizard-csr-presets | done | |
| 9 | epic-debug-ui-diagnostics-panel | done | |
| 10 | epic-dashboard-widget | done | |
| 11 | epic-e2e-testing-market-preparation | in-progress | 11-1 annulee (remplacee par epic 17) |
| 12 | epic-jeedom-vm-integration-testing | in-progress | 12-7 ready-for-dev |
| 13 | epic-alarm-event-vocabulary | in-progress | |
| 14 | epic-camera-snapshot-attachment | done | |
| 15 | epic-configurable-sia-content-formats | annulee 2026-10-17 | pas d'entree dans sprint-status, voir "A confirmer" |
| 16 | epic-multi-csr-failover | pas de ligne status (backlog) | non planifie |
| 17 | epic-csr-behaviour-profiles | in-progress | 17-1 a 17-6 en review |

## Stories : statuts

| v6 | v7 | Stories |
|---|---|---|
| done | done | 1-1 a 1-4, 1-6, 2-*, 3-*, 4-*, 5-*, 6-*, 7-*, 8-*, 9-*, 10-*, 11-3, 11-4, 12-1 a 12-6, 13-1, 13-4, 14-* |
| review | in-review | 1-5, 17-1, 17-2, 17-3, 17-4, 17-5, 17-6 |
| ready-for-dev | ready-for-dev | 12-7 |
| backlog | entree seule (fiche repliee si elle existe) | 11-2, 12-8, 13-2, 13-3, 16-1, 16-2 |

Un plan v7 est ecrit pour chaque story done ou in-review ayant une fiche (`story-<slug>-plan.md`). Aucune baseline de revision n'est devinee : chaque plan sans baseline fiable est liste dans le rapport.

## Fichiers hors cadre (a la racine de `_bmad-output/`)

| Fichier ou dossier | Destination | Raison |
|---|---|---|
| `plan-17-2-configurable-supervision-frame.md` | `epic-csr-behaviour-profiles/story-configurable-supervision-frame-plan.md` si fusionnable avec la fiche 17-2, sinon `Prior builds` du plan | enregistrement de build /bmad-build |
| `plan-17-3-rp-cyclic-test.md`, `plan-17-4-wizard-profile-choice-and-advanced-options.md` | meme regle, epic 17 | |
| `plan-duh-response-handling.md` | epic 17, rattache a 17-6 (`ticket: 17-6-duh-response-handling`) | |
| `plan-10-1-widget-jeedom-conformance.md`, `plan-10-1-widget-sm1-sm2-redesign.md` | epic 10, rattaches a la story 10-1 | |
| `plan-diagnostic-tab-refresh.md` | epic 9 (diagnostic) a confirmer | aucune story ne le cite |
| `qa-reports/` | `initiative-my-project/qa-reports/` | evidence, deplace tel quel |
| `walkthrough-17-2/` | `epic-csr-behaviour-profiles/walkthrough-17-2/` | evidence de 17-2 |
| `brainstorming/` | reste en place | appartient a aucune initiative (guide) |
| `implementation-artifacts/tests/` | `initiative-my-project/tests/` | resumes de generation de tests, deplaces tels quels |
| `implementation-artifacts/10-1.md`, `10-2.md` | traites comme fiches 10-1 et 10-2 | noms hors schema, a verifier |

## Conflit deferred-work

Deux fichiers portent ce nom :

| Fichier | Taille | Contenu |
|---|---|---|
| `implementation-artifacts/deferred-work.md` | 73 Ko | registre D-xx historique |
| `deferred-work.md` (racine) | 2,5 Ko | sorties des builds /bmad-build (source_plan: 17-4, 10-1) |

Proposition : le gros fichier va a `initiative-my-project/deferred-work.md` (regle du guide, inchange) ; le petit va a `initiative-my-project/deferred-work-builds.md`, renomme parce que deux fichiers ne peuvent pas partager un nom. A confirmer.

## Decisions (Herve, 2026-11-05)

1. Petit deferred-work : `deferred-work-builds.md`. Approuve.
2. `plan-diagnostic-tab-refresh.md` : rattache a l'epic 9 (diagnostic). Approuve.
3. Epic 15 (annule) : conserve comme epic `dropped`, avec sa fiche `15-1-pluggable-sia-content-formats.md` en plan `dropped`.
4. Fiche 11-1 (annulee) : conservee comme plan `dropped`, note "remplacee par l'epic 17".
5. Plan approuve le 2026-11-05.

## Ecarts assumes a l'execution

- `requirements-14-4-frigate-forced-capture-2026-09-26.md` n'est pas dans la table des documents : il reste a plat dans l'initiative (non reconnu), pas de dossier.
- Dependances entre epics (`**Dependencies:**` de epics.md) : notees dans les Notes de chaque epic, pas ecrites en `after`. Un `after` bloquerait les tickets de l'epic 17 tant que l'epic 1 est `in-progress` (1-5 en review), ce qui n'a pas de sens pour un historique.
- Les sections "Done when" des epics sont redigees depuis la ligne `Testing:` de epics.md et le statut ; elles ne sont pas confirmees une par une avec Herve (a relire).
- Sortie 'Outcome' d'un epic : reprise de son objectif (goal) de epics.md.
- Stories sans `### Story` dans epics.md (1-4, 13-2) : entrees ecrites depuis leur fiche, `id` conserve.
- Plusieurs enregistrements pour une meme story (10-1 : fiche + 2 plans ; 17-6 : fiche + plan-duh) : un seul plan, les autres sous `## Prior builds` et leurs fichiers dans `archive-v6/` ; pour 17-6 le plan est `plan-duh-response-handling.md` (il porte la baseline `f053858`).

## Configuration

- `_bmad/custom/config.user.toml` (nouveau) : `[core] active_initiative = "initiative-my-project"`.
- Rien d'autre dans `_bmad/`. `planning_artifacts` et `implementation_artifacts` ne sont pas touches.
- `core.output_folder` reste `{project-root}/_bmad-output`.

## References hors du magasin (listees, jamais modifiees)

A completer a l'ecriture des liens : `CLAUDE.md` du projet (Key References), `internal-docs/design/*.md`, memoire de l'assistant (`MEMORY.md` et notes citant `sprint-status.yaml` ou `epics.md`).

## Depot

Le depot existe deja. Un commit de l'etat courant avant l'etape 6, puis un commit par etape ; la sauvegarde n'est jamais stagee. Jamais de push.

## Verification

Les 12 items de la checklist de `migration-1.toml` seront executes et leurs resultats consignes ici. Aucun resultat pour l'instant.
