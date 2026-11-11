---
epic: epic-18-ftps-alarm-media-upload
date: 2026-11-11
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Rétrospective — Epic 18, envoi FTPS des médias d'alarme

## Epic summary

- 12 tickets sur 12 en `done` (`tickets.py status`), aucun `pending_tickets`, aucun ticket resté à `built`.
- Les tickets: 18.1 serveur de test, 18.2 traceur (clés PHP vers daemon, photo), 18.3 maquette, 18.4 assistant étape 1, 18.5 clip, 18.6 robustesse et secret, 18.7 test de connexion, 18.8 arborescence distante, 18.9 validation terrain, 18.10 balayage de refactorisation, 18.11 assistant étape 2 (réglages), 18.12 assistant étape 2 (bouton de test).
- Plage de code relue: `git diff bca9d30..HEAD` sur `ftps_upload.py`, `daemon.py`, `siadc09d.py`, `frigate_prefetch.py`, `messages.py`, `siaDC09.ajax.php`, `siaDC09.class.php`, `siaDC09Cmd.class.php`, `siaDC09.php`, `siaDC09.js`, `siaDC09.css`, `scripts/ftps_probe.py`. La plage est celle de l'ensemble de l'epic, pas une plage par plan.
- Preuves disponibles: fichier d'epic, fiches et plans, diff, tests, journal du daemon collé par Herve pour 18.9, journal de session de cette session.
- Preuves absentes: aucune trace écrite de la photo ni des cas négatifs (serveur arrêté, certificat changé, média manquant) pour 18.9; Herve n'a pas conservé de journaux.
- Limites de l'analyse: la passe `git_evidence.py` par plan et les vues agrégées par script (delta d'architecture, carte de duplication) n'ont pas été exécutées. Les vues agrégées ont été remplacées par la relecture des trois lentilles, sans mesure de taille de fichier. Les trois lentilles ont relu par inspection, sans rien exécuter.

## Findings

Les constats viennent de trois relectures indépendantes (adversariale = ADV, cas limites = EDGE, trous de vérification = VG). Deux ont été revérifiés dans le code par moi (marqués **vérifié**). Les autres sont des rapports de sous-agents, à reconfirmer avant d'ouvrir un ticket.

### A. Échecs invisibles pour l'utilisateur (Done when 2)

| # | Constat | Source | Disposition |
|---|---------|--------|-------------|
| A1 | Si la clé de cache Frigate manque ou a expiré (TTL 120 s), ou si l'hôte Frigate manque, `_resolveFtpsUpload` ne fait qu'un `warning` et la trame part sans média. Aucune notification. Le cas le plus courant (pas d'événement Frigate récent) est invisible. | `siaDC09Cmd.class.php` `_resolveFtpsUpload`; `daemon.py` ~3078-3103 (ADV3, EDGE3) | À corriger |
| A2 | Empreinte invalide: `_read_ftps_settings` renvoie `FtpsSettings()`, l'envoi est désactivé avec un simple avertissement, et la trame a déjà perdu sa balise U/V. | `daemon.py:610-624` (ADV4, EDGE2) | À corriger |
| A3 | **Vérifié.** Écart de normalisation: le JS accepte `[\s:-]` (`siaDC09.js:501`), Python ne retire que `:` et l'espace (`ftps_upload.py:95`). Une empreinte saisie avec des tirets passe l'assistant et est rejetée par le daemon, donc A2 se déclenche. | `siaDC09.js:501`, `ftps_upload.py:95` (EDGE2) | À corriger (une ligne: `re.sub(r"[\s:-]", "", text)`) |
| A4 | Aucune garde `deamon_info` pour hôte, utilisateur, mot de passe ou port vides sous FTPS. Seul le JS de l'assistant contrôle. | `siaDC09.class.php:268-277, 378-399` (ADV5, EDGE4) | À corriger |
| A5 | Port hors 1-65535 non contrôlé côté daemon; `OverflowError` n'est pas dans `_FTP_ERRORS` (`ftps_upload.py:38`), la tâche meurt sans notification. | `daemon.py:605-607`, `siadc09d.py` (EDGE1, ADV15) | À corriger |
| A6 | `_run_ftps_upload` n'isole que `FtpsUploadError` et `TimeoutError`: toute autre exception du volet photo saute le clip et n'envoie aucun message. Le docstring promet l'inverse. | `daemon.py:~640-655` (ADV9, EDGE10, VG5) | À corriger |
| A7 | Un seul `logical_id` (`ftps_upload`) pour photo et vidéo, jamais effacé après un succès. | `daemon.py:259, 762` (ADV10) | À différer |
| A8 | Changement de transport ou de réglages: lus au démarrage seulement. Entre l'enregistrement et le redémarrage, la trame perd la balise et rien n'est envoyé. | `siaDC09.class.php:378`, `daemon.py:~3098` (ADV16) | À différer, à documenter |

### B. Intégrité des fichiers envoyés (Done when 1)

| # | Constat | Source | Disposition |
|---|---------|--------|-------------|
| B1 | Corps tronqué accepté: la boucle lit `resp.read(CLIP_CHUNK_BYTES)` sans comparer le total à `Content-Length`; le commentaire « a truncated body is rejected » (ligne 283) n'est vrai que si `read(amt)` lève une exception, ce que `http.client` ne fait pas pour une lecture bornée. Vérifié: aucune comparaison dans le fichier. Le comportement exact de `read(amt)` reste à confirmer par un test. | `frigate_prefetch.py:275-283, 144` (ADV1, EDGE5) | À corriger, test d'abord |
| B2 | Événement encore en cours: `clip_wait_s` renvoie 0 quand `end_time` est absent (ligne 219), le premier 200 est gardé: clip partiel envoyé et journalisé « fait ». C'est l'inconnue « le clip est-il prêt » de l'epic, restée ouverte. | `frigate_prefetch.py:207-221, 316-323` (ADV2, EDGE6) | À corriger |
| B3 | Fichier distant partiel laissé après un abandon (`STOR` direct sur le nom final, pas de `.part` ni `DELE`). Un surveillant côté serveur peut le lire incomplet. | `ftps_upload.py:293-327` (ADV7) | À corriger |
| B4 | Échéance du clip = 30 s + durée du clip, indépendante de la taille (plafond 200 Mo): coupure systématique sur une liaison montante lente. | `daemon.py:664`, `ftps_upload.py:~31` (ADV8) | À différer, à mesurer sur le terrain |
| B5 | Photo: une seule tentative, pas de nouvel essai si la photo n'est pas encore disponible (404), contrairement au clip. | `daemon.py:690-707` (EDGE7) | À différer |
| B6 | Pas de limite de concurrence ni de dédoublonnage par `event_id`; fichiers `sia-clip-*.mp4` orphelins après un arrêt brutal. | `daemon.py:~3076-3100`, `frigate_prefetch.py:~320-333` (ADV11) | À différer |
| B7 | Nom distant: le libellé de zone perd ses accents (« Séjour » devient « S_jour »), collisions possibles; l'heure est celle du début de la tâche, pas de l'événement. La trame ne référence pas le fichier (décision de l'epic), donc la corrélation repose sur ce nom. | `ftps_upload.py:116-141`, `daemon.py:611` (ADV13) | À différer, décision à rouvrir |

### C. Sécurité (Done when 3)

| # | Constat | Source | Disposition |
|---|---------|--------|-------------|
| C1 | Le mot de passe reste dans `/proc/<pid>/environ` du daemon: `os.environ.pop` ne change que la copie Python. Le commentaire et la revendication de 18.6 sont donc trop forts. Exact par construction pour un processus lancé par `exec` avec `putenv`. | `daemon.py:~606-612`, `siaDC09.class.php:~388-394` (ADV14) | À corriger en documentation; option d'un fichier 0600 ou stdin à différer |
| C2 | Le bouton « Faire confiance » est identique pour `changed` (empreinte épinglée qui ne correspond plus) et `untrusted`. Un clic remplace l'épingle. | `siaDC09.js:~929-939` (ADV12) | À corriger: confirmation explicite pour `changed` |
| C3 | L'épinglage n'est vérifié que sur le canal de contrôle; le contexte reste `CERT_NONE` pour le canal de données. À relativiser: une session TLS réutilisée est exigée par la plupart des serveurs. | `ftps_upload.py:161-168, 360-369` (EDGE9) | À accepter, à noter |
| C4 | Si une exception survient entre `putenv` et le `try` (par ex. `log::add`), le mot de passe reste dans l'environnement PHP. | `siaDC09.class.php:392-442` (EDGE12) | À corriger (déplacer le `try`) |
| C5 | Deuxième `SIADaemon` dans le même processus: le mot de passe a déjà été retiré de l'environnement. Concerne surtout les tests. | `daemon.py:595-628` (EDGE11) | À accepter |

### D. Vérification (Done when 4)

| # | Constat | Source | Disposition |
|---|---------|--------|-------------|
| D1 | **Le critère 4 n'est pas rempli tel qu'écrit**: il n'existe pas de fixture FTPS locale. Les tests niveau 1 patchent `ftplib.FTP_TLS` avec un `MagicMock`; le double de blocage est une paire de sockets sans TLS. Poignée de main TLS, `PROT P`, empreinte d'un vrai certificat DER, et la branche `unwrap()` ne sont jamais exercés; la preuve réelle est le seul passage terrain (18.9), sans journal pour la photo et les cas négatifs. | `ftps_upload.py:343-386`; `tests/level1/test_ftps_upload.py:57-117`; `tests/ftps_stall_fake.py:40-100` (VG1, ADV18) | Accepté par Herve (2026-11-11): les tests actuels suffisent, pas de fixture FTPS locale. Écart au critère 4 enregistré. |
| D2 | La politique TLS (`CERT_REQUIRED` par défaut, `CERT_NONE` avec épinglage) n'est pas verrouillée par un test sur le chemin d'envoi. | `ftps_upload.py:161-168`; `test_ftps_upload.py:266-277` (VG2) | À corriger |
| D3 | Le contrat PHP vers daemon (`ftps_upload`: types de `snapshot` et `clip`, clés) n'est vérifié que par présence de texte dans la source PHP. Le daemon lit `clip is True`: un entier ou la chaîne `"0"` désactiverait silencieusement le clip. | `siaDC09Cmd.class.php:151-177`; `daemon.py:3076-3103`; `test_php_ftps_keys.py:123-153` (VG3) | À corriger |
| D4 | La gestion du mot de passe dans `testFtps` (masquage de stderr, liste blanche, `finally`) n'est vérifiée que par expression régulière sur la source. | `siaDC09.ajax.php:100-122`; `test_wizard_php_structure.py:671-696` (VG4) | À différer |
| D5 | Le test de connexion s'arrête après `login`: pas de `PROT P`, de `cwd(dossier)` ni d'écriture. Le vert « joignable » n'assure pas qu'une alarme réelle réussira. Choix documenté en 18.7. | `ftps_upload.py:~493-530` (ADV6) | À différer: au moins `PROT P` et `cwd` |
| D6 | Le JS exige un mot de passe, le backend non (`FtpsSettings.complete`). Frontière non verrouillée entre 18.4/18.11/18.12 et 18.2/18.7. | `siaDC09.js:497-498`, `ftps_upload.py:72-75` (VG6) | À accepter si voulu, sinon aligner |
| D7 | « Auto-signé » avec champ vide passe la validation, est enregistré comme mode CA, puis rechargé comme « reconnu ». | `siaDC09.js:~468-505` (ADV17) | À corriger |

### E. Constats écartés ou relativisés

- `conn.unwrap()` non protégé (EDGE8): c'est le comportement de `ftplib.storbinary` de la bibliothèque standard. **Vérifié**: même appel nu à `ftps_upload.py:323`. Accepté.
- `testConnection` ne journalise plus stderr au niveau erreur (EDGE, suppression): à surveiller, pas un défaut démontré.
- Le « bouclage » demandé par l'épinglage de certificat sur le canal de données (C3) dépend du serveur; non démontré.

### F. Ce qui a été vérifié et tient (VG)

- Un serveur lent ou bloqué ne retarde pas la trame et l'échec est notifié: `test_ftps_upload_dispatch.py:132, 248`; `test_ftps_clip_dispatch.py:347`.
- L'échéance est appliquée dans `_store` avec de vrais sockets: `test_ftps_upload.py:326, 394`.
- Le mot de passe est épuré des erreurs, des journaux du daemon, de la trace de débogage et de l'environnement après lecture: `test_ftps_upload.py:108, 212`; `test_ftps_upload_dispatch.py:159, 210, 281`.
- Nettoyage du fichier temporaire du clip, plafond de taille, nouvel essai: `test_ftps_clip_dispatch.py:121-186, 328`.
- Création de l'arborescence distante et échec de `mkd`: `test_ftps_remote_layout.py:121, 166`.

## Behavior verification

- Exécuté en début de session: les quatre niveaux de tests. Seuls les échecs de référence connus restent (niveau 2: 5, niveau 2.5: 1, niveau 3: 1), aucun lié à l'epic.
- Validation terrain par Herve sur test-jeedom contre un vrai serveur vsftpd (FTPS explicite, port 21, certificat auto-signé épinglé): clip reçu, trame acquittée, journal du daemon collé et résumé dans la section Evidence de la fiche 18.9. **Non observé**: la photo, le serveur arrêté, le certificat modifié, le média manquant.
- Aucune des corrections proposées ci-dessus n'a été appliquée ni testée dans cette rétrospective.

## Previous-retro follow-through

Aucune rétrospective antérieure n'existe dans l'arbre (aucun fichier `*-retrospective.md` dans les dossiers d'epic 17 et 18): rien à suivre.

## Action items

Propositions à appliquer par la boucle de développement normale; aucune n'est appliquée. Propriétaire: Herve (décide), agent de développement (exécute).

1. **Remonter à l'utilisateur chaque échec de la branche PHP et de la lecture des réglages** (A1, A2, A5): notification `message_center` depuis le chemin « pas de média » et « réglages invalides ». Corriger en même temps la normalisation d'empreinte (A3, `re.sub(r"[\s:-]", "", text)`).
2. **Garde au démarrage du daemon sous FTPS** (A4): hôte, utilisateur, mot de passe, port 1-65535 et format d'empreinte, avec `OverflowError` ajouté aux erreurs gérées (A5).
3. **Isoler le volet photo du volet clip** (A6): `try/except Exception` autour de chacun, avec `_report_ftps_failure`.
4. **Vérifier la taille reçue contre `Content-Length`** (B1) et **attendre la fin d'un événement en cours** (B2). Écrire d'abord le test avec un serveur HTTP local qui coupe la connexion (leçon: tests avant essai terrain).
5. **Envoyer sous un nom `.part` puis renommer** (B3).
6. ~~Fixture FTPS locale en niveau 1~~ **Abandonnée par Herve (2026-11-11)**: les tests actuels suffisent (D1 accepté). Reste D2: assertions sur `verify_mode` et `check_hostname` des deux branches de `_build_context`, sans serveur.
7. **Test d'intégration du contrat PHP vers daemon** (D3), ou normalisation des types côté daemon (accepter 0/1 et "0"/"1").
8. **Confirmation explicite pour « Faire confiance » sur `changed`** (C2), champ obligatoire pour « auto-signé » (D7), déplacer le `try` après `putenv` (C4).
9. **Corriger le commentaire et la revendication de 18.6 sur l'environnement** (C1): le secret reste lisible dans `/proc/<pid>/environ`.
10. **Rejouer 18.9 avec preuve conservée**: photo, serveur arrêté, certificat changé, média manquant; garder les journaux dans la fiche (processus: la prochaine validation terrain conserve ses journaux au fil de l'eau).
11. **À différer, tracés dans le suivi des reports**: A7, A8, B4-B7, D4-D6.

Leçons de processus:
- Le critère « tests contre une fixture locale » du Done when a été satisfait par des mocks sans que personne ne le relève avant cette relecture; à l'inception, écrire le critère de façon vérifiable (« un test lance un serveur FTPS réel en boucle locale »).
- Les échecs de la branche PHP et de la lecture des réglages sont tombés dans une zone qu'aucun ticket ne possédait: 18.2 (clés), 18.6 (robustesse) et 18.8 (arborescence) supposaient chacun que la notification existait déjà ailleurs.

## Decision records

Candidats proposés (aucun écrit; chacun demande l'accord de Herve):

| Décision | Plan | Pourquoi candidat |
|----------|------|-------------------|
| Épinglage de l'empreinte SHA-256 sur le canal de contrôle seul, contexte `CERT_NONE` | 18.6 / 18.2 | Difficile à revenir, surprenant sans contexte, vrai compromis |
| Envoi indépendant de la trame, sans référence au fichier, corrélation par l'heure et la zone | notes de l'epic (2026-11-09) | Déjà dans l'epic, mais les constats B7 montrent que le nom distant porte la corrélation |

Aucun fichier `adr-*.md` n'a été écrit dans cette rétrospective.

## Acceptance verdict

**accepted-with-open-items**, critères déclarés. Les 12 tickets sont terminés.

| Critère | Statut | Preuve |
|---------|--------|--------|
| 1. Vrai serveur: photo et clip déposés, trame acquittée | Partiel | Clip et trame observés sur le terrain (18.9); photo non documentée |
| 2. Serveur arrêté ou lent: trame dans les délais, échec journalisé et montré | Partiel | Délai et notification testés pour les échecs dans la tâche (VG); échecs avant la tâche (A1, A2, A5) seulement journalisés |
| 3. Mot de passe absent des journaux, de l'interface de débogage et de la trame | Rempli, avec une réserve | Tests de purge (VG, section F); reste lisible dans `/proc/<pid>/environ` (C1) |
| 4. Tests niveaux 1 et 2 contre une fixture FTPS locale; assistant et test vérifiés sur test-jeedom | Partiel, écart accepté par Herve (2026-11-11) | Assistant et test vérifiés sur test-jeedom; pas de fixture FTPS locale, tests à base de doubles jugés suffisants (D1) |

Les points ouverts (A1-A6, B1-B3, D1-D3) sont des défauts de robustesse et de preuve, non des échecs de la fonction principale; aucun ne fait échouer le critère 1. La décision d'accepter reste à Herve, qui peut la durcir en « rejected » s'il considère D1 bloquant.

## Open questions

- B1: `HTTPResponse.read(amt)` lève-t-il vraiment sans `IncompleteRead` sur un corps coupé? Un test avec un serveur local le tranche.
- B2: Frigate sert-il un clip partiel ou une erreur pour un événement en cours? Non observé.
- B4: la liaison montante réelle de l'installation rend-elle l'échéance trop courte? À mesurer sur un clip réel.
- B7: la corrélation par l'heure et la zone suffit-elle pour le récepteur? Réponse du côté du poste de surveillance.
- Herve accepte-t-il D6 (mot de passe obligatoire dans l'assistant mais pas dans le backend)?
