# Analyse des trames Ajax ↔ Scutum

Analyse des captures réseau d'un hub Ajax qui dialogue avec le centre de télésurveillance Scutum. Elle sert de référence réelle pour comparer les trames du plugin SIA DC-09.

## Captures

| Fichier | Contenu | Statut |
|---|---|---|
| `capture-ajax-idle.pcapng` | Hub au repos (mode idle) | Analysée (ci-dessous) |
| `capture-ajax-armement-desarmemnt.pcapng` | Armement / désarmement | Analysée (voir plus bas) |
| `capture-ajax-armement-alarme-desarmement.pcapng` | Armement, alarme intrusion (BA/BR), désarmement | Analysée (voir plus bas) |
| `capture-ajax-idle-cycle.pcapng` | Repos sur 2 min 20 s, avec coupure secteur | Analysée (voir plus bas) |
| `capture-ajax-A.pcapng` | Hub en « Connectez-vous sur demande », repos ~7 min puis armement / désarmement | Analysée (voir plus bas) |
| `capture-ajax-b.pcapng` | Hub en connexion permanente, intervalle ping 5 min, repos puis armement / désarmement | Analysée (voir plus bas) |

## Environnement de la capture idle

- Hub Ajax: 192.168.20.29
- Récepteur Scutum: 194.250.35.75, port TCP 10657
- Compte (transmetteur): `27099`
- Transport: TCP. Sur cette capture, une nouvelle connexion par message.
- Outil: `tcpdump` (tshark absent). CRC et longueurs recalculés en Python (CRC-16, polynôme 0xA001): tous corrects.

## Résultat principal

La capture idle ne contient **aucune trame `SIA-DCS`**. Elle contient seulement des trames de supervision `NULL` du hub et leurs `ACK` de Scutum.

## Trames extraites

Chaque trame est encadrée par LF (`0x0a`) au début et CR (`0x0d`) à la fin. Les heures locales sont en UTC+2, les horodatages dans les trames en UTC.

| Heure locale | Sens | Trame |
|---|---|---|
| 22:28:33 | hub → Scutum | `58520028"NULL"0000L0#27099[]_20:28:33,10-16-2026` |
| 22:28:33 | Scutum → hub | `12C80013"ACK"0000L0#27099[]` |
| 22:28:44 | hub → Scutum | `D4AC0028"NULL"0000L0#27099[]_20:28:44,10-16-2026` |
| 22:28:44 | Scutum → hub | `12C80013"ACK"0000L0#27099[]` |

## Observations

### Format de la supervision (hub → Scutum)

`<CRC>0028"NULL"0000L0#27099[]_HH:MM:SS,MM-DD-YYYY`

- Jeton `"NULL"` (pas `"SIA-DCS"`).
- Séquence `0000`.
- `L0` présent, pas de `R`.
- Compte `27099` sur 5 chiffres, **sans bourrage**. Scutum le reconnaît, donc l'hypothèse d'un bourrage sur 6 caractères est écartée.
- Bloc de données vide: `[]`.
- Horodatage `_HH:MM:SS,MM-DD-YYYY` en UTC, 20 caractères, avec le `_` initial. Ce n'est pas la forme `[H…]`.

### Format de l'ACK (Scutum → hub)

`<CRC>0013"ACK"0000L0#27099[]`

- Écho de la séquence, du préfixe `L0` et du compte.
- Pas d'horodatage, pas de `R`.
- Il apparaît deux fois par session, à environ 250 ms d'écart. Je l'interprète comme une retransmission TCP, pas comme deux ACK applicatifs. Confirmé dans la capture arm/disarm: les deux segments ont le même numéro de séquence TCP.

### Cycle de connexion

1. Le hub ouvre une connexion TCP (ports sources 49241, puis 49242).
2. Il envoie une trame de 50 octets.
3. Scutum répond par un ACK de 29 octets.
4. Scutum ferme (FIN) environ 5 s plus tard, puis le hub ferme.

Ce n'est pas une connexion permanente. Les deux NULL à 11 s d'intervalle sont le rythme normal de supervision d'Ajax: voir la capture du cycle plus bas.

## Capture armement / désarmement

Même hub, même Scutum, même compte 27099. Durée: environ 33 s (22:30:02 à 22:30:35 local). La capture commence au milieu d'une connexion (port 49249, fermeture seulement). Elle contient 3 connexions complètes (ports 49250, 49251, 49252). CRC et longueurs de toutes les trames recalculés: corrects.

### Trames SIA-DCS (hub → Scutum)

| Heure locale | Connexion | Trame | Événement |
|---|---|---|---|
| 22:30:08 | 49250 | `2D9F003C"SIA-DCS"0009L0#27099[#27099\|Nri1/CL501]_20:30:07,10-16-2026` | CL: armement |
| 22:30:19 | 49251 | `E92E003C"SIA-DCS"0010L0#27099[#27099\|Nri1/OP501]_20:30:18,10-16-2026` | OP: désarmement |
| 22:30:22 | 49251 | `61DE003C"SIA-DCS"0011L0#27099[#27099\|Nri1/CL501]_20:30:21,10-16-2026` | CL |
| 22:30:33 | 49252 | `29E8003C"SIA-DCS"0012L0#27099[#27099\|Nri1/OP501]_20:30:32,10-16-2026` | OP |
| 22:30:34 | 49252 | `BDFC003C"SIA-DCS"0013L0#27099[#27099\|Nri1/CL501]_20:30:33,10-16-2026` | CL |

Chaque connexion contient aussi un `NULL` en premier (`C26F0028`, `57790028`, `0D660028`, mêmes caractéristiques que la capture idle). Les ACK de Scutum répètent la séquence de l'événement: `8EE60013"ACK"0009L0#27099[]`, `D1350013"ACK"0010…`, `2D310013"ACK"0011…`, `693E0013"ACK"0012…`, `953A0013"ACK"0013…`. Ils sont toujours émis deux fois (retransmission TCP, même numéro de séquence TCP: confirmé).

### Format des événements

`<CRC>003C"SIA-DCS"<seq>L0#27099[#27099|Nri1/<code>501]_<horodatage UTC>`

- **Bloc de données:** `[#compte|N` + `ri1` + `/` + code + adresse `]`. Le compte `27099` est répété dans le bloc, comme dans l'Annexe B de la spec.
- **`ri1`:** champ optionnel DC-03 `ri` (area / partition 1), présent sur tous les événements. Le séparateur `/` sépare ce champ du code, comme dans l'exemple `Nri1/CL001` de la spec.
- **Code + adresse:** `CL501` à l'armement, `OP501` au désarmement. Pour CL/OP, l'adresse DC-03 est un numéro d'utilisateur: `501` serait l'utilisateur qui a armé ou désarmé (à confirmer, le numéro n'a pas été comparé à la configuration du hub). Il est identique pour les 5 événements.
- **Pas de champ `id`, ni `ti`.** L'utilisateur est porté par l'adresse seule.
- **Séquence:** 0009 à 0013, un compteur global qui continue d'une connexion à l'autre. Le `NULL` reste en `0000`. La séquence 0001-0008 a eu lieu avant le début de la capture.
- **`L0`, pas de `R`, 5 chiffres sans bourrage, timestamp UTC** comme pour le NULL. Longueur `003C` (60) pour tous les événements.
- **Horodatage:** celui de l'émission (en secondes). Pour le premier événement, il est identique à celui du NULL envoyé juste avant (20:30:07).

### Cycle de connexion

1. Connexion TCP, envoi du `NULL`, ACK de Scutum.
2. Environ 0,75 à 1 s plus tard, envoi de l'événement sur la même connexion, ACK.
3. Les événements suivants peuvent partir sur la même connexion (49251: OP puis CL 3 s plus tard, 49252: idem).
4. Scutum ferme (FIN) environ 5 s après son dernier ACK.

Un événement n'attend donc pas la connexion suivante. Le hub ouvre une connexion par événement ou groupe d'événements proches, et la termine par le NULL initial.

## Capture armement / alarme / désarmement

Fichier `capture-ajax-armement-alarme-desarmement.pcapng`, 22:55:09 à 22:55:34 local. Deux connexions (ports 49394 et 49395). CRC et longueurs de toutes les trames recalculés: corrects.

| Heure locale | Connexion | Trame | Événement |
|---|---|---|---|
| 22:55:09 | 49394 | `B4C00028"NULL"0000L0#27099[]_20:55:09,10-16-2026` | supervision |
| 22:55:12 | 49394 | `04D9003C"SIA-DCS"0043L0#27099[#27099\|Nri1/CL501]_20:55:12,10-16-2026` | CL: armement |
| 22:55:17 | 49394 | `D21F003A"SIA-DCS"0044L0#27099[#27099\|Nri1/BA1]_20:55:17,10-16-2026` | BA: alarme intrusion |
| 22:55:28 | 49395 | `353A0028"NULL"0000L0#27099[]_20:55:28,10-16-2026` | supervision |
| 22:55:28 | 49395 | `4006003A"SIA-DCS"0045L0#27099[#27099\|Nri1/BR1]_20:55:28,10-16-2026` | BR: rétablissement intrusion |
| 22:55:32 | 49395 | `6486003C"SIA-DCS"0046L0#27099[#27099\|Nri1/OP501]_20:55:32,10-16-2026` | OP: désarmement |

Chaque trame est acquittée par `"ACK"<seq>L0#27099[]` (émis deux fois, retransmission TCP).

Observations:
- **BA et BR:** `[#27099|Nri1/BA1]` et `[#27099|Nri1/BR1]`. Même `ri1` que CL/OP, code puis adresse `1`.
- **Adresse de BA/BR non bourrée:** `1`, pas `001`. L'adresse n'est pas écrite sur 3 chiffres (la longueur de la trame, `003A`, soit 58, est inférieure à celle de CL/OP, `003C`, soit 60). Pour CL/OP, l'adresse `501` fait 3 chiffres parce que l'utilisateur est 501, pas à cause d'un bourrage. Le plugin envoie `NBA001` (bourré sur 3), ce qui n'est pas ce que fait Ajax.
- **Zone ou point:** pour BA/BR, DC-03 dit adresse = zone ou point. Ajax envoie donc la zone 1, sans bourrage.
- **BR après BA, pas de BC:** BR (rétablissement de la zone) suit BA environ 11 s plus tard, sur la connexion suivante, puis OP 4 s après. Ajax n'envoie aucun `BC`. `BR` (zone revenue au repos) et `BC` (alarme annulée par un utilisateur) n'ont pas le même sens. Le plugin envoie `BC` (avec `OP` au désarmement, `BC` seul via alarmReset), pas `BR`. On ne sait pas ce qui déclenche le BR d'Ajax (fin de sirène, zone au repos ou désarmement): il faudrait une capture avec désarmement pendant l'alarme.
- **Séquence:** 0043 à 0046, la suite du compteur global, sans reprise à zéro.
- **Un NULL ouvre chaque connexion**, comme dans les captures précédentes.

Journal extranet de cette séquence (heure locale, source `IP`):

| Heure | Code affiché | Libellé | Colonne détail | Trame |
|---|---|---|---|---|
| 22:55:33 | `OP0001` | Mise Hors Service par U0501 | – | `…0046…OP501` |
| 22:55:28 | `BR0001` | FIN INTRUSION | `***** Zone 0001 Non Connue *****` | `…0045…BR1` |
| 22:55:17 | `BA0001` | INTRUSION | `***** Zone 0001 Non Connue *****` | `…0044…BA1` |
| 22:55:12 | `CL0001` | Mise En Service par U0501 | – | `…0043…CL501` |

- **BA = INTRUSION, BR = FIN INTRUSION:** Scutum reconnaît les deux codes. Les horaires correspondent aux trames, sauf le OP: affiché 22:55:33 pour une trame émise à 22:55:32 (une seconde d'écart, probablement l'heure d'enregistrement par Scutum).
- **« Zone 0001 Non Connue »:** Scutum a lu l'adresse `1` comme la zone 1, qui n'est pas déclarée sur le compte 27099. Le libellé de l'événement n'en dépend pas, mais la zone n'est pas reliée à un nom.
- **`0001` dans `BA0001`:** pour CL/OP, le `0001` est `ri1` (l'adresse 501 est affichée à part, `U0501`). Pour BA/BR, `0001` peut être `ri1` ou la zone 1, les deux valent 1 ici. L'annexe ci-dessous (BC du plugin, sans `ri`, affiché `BC0001`) indique que pour les codes adressés par zone, Scutum affiche la zone dans ce champ. Donc `BA0001` serait la zone 1. C'est une inférence.
- **Conséquence pour le plugin:** `NBA001` serait lu comme zone 1 (`001` vaut 1 une fois converti), donc probablement équivalent à `BA1` pour la zone. Je n'ai pas de preuve que Scutum accepte l'adresse bourrée, ni de trace d'un BA du plugin.

## Capture du cycle de supervision

Fichier `capture-ajax-idle-cycle.pcapng`, 23:34:13 à 23:36:33 local (2 min 20 s), hub au repos avec une coupure puis un rétablissement de l'alimentation. 15 connexions (ports 49620 à 49633, plus la fin de 49619). CRC et longueurs de toutes les trames recalculés: corrects.

### Trames SIA-DCS

| Heure locale | Trame | Événement |
|---|---|---|
| 23:34:29 | `F642003A"SIA-DCS"0086L0#27099[#27099\|Nri0/AR0]_21:34:29,10-16-2026` | AR: secteur rétabli |
| 23:35:10 | `8FA2003D"SIA-DCS"0087L0#27099[#27099\|Nri0/RP0000]_21:35:10,10-16-2026` | RP: test cyclique |
| 23:36:12 | `A3B0003D"SIA-DCS"0088L0#27099[#27099\|Nri0/RP0000]_21:36:12,10-16-2026` | RP: test cyclique |

Tous les autres messages sont des `NULL` (`"NULL"0000L0#27099[]_ts`), un par connexion.

Journal extranet de la même période:

| Heure | Code affiché | Libellé | Colonne détail | Trame |
|---|---|---|---|---|
| 23:36:12 | `RP0000` | Test Cyclique | – | `…0088…Nri0/RP0000` |
| 23:35:10 | `RP0000` | Test Cyclique | – | `…0087…Nri0/RP0000` |
| 23:34:29 | `AR0000` | Rétablissement Électricité | `***** Zone 0000 Non Connue *****` | `…0086…Nri0/AR0` |
| 23:34:08 | `RP0000` | Test Cyclique | – | avant le début de la capture |
| 23:34:07 | `AT0000` | COUPURE ELECTRICITE | `***** Zone 0000 Non Connue *****` | avant le début de la capture |

### Ce que la capture établit

- **Le « Test Cyclique » est un événement `RP`, pas un `NULL`.** Les horaires correspondent à la seconde. Les `NULL` ne sont jamais affichés par Scutum.
- **Format du RP:** `[#27099|Nri0/RP0000]`. Partition `ri0`, adresse `0000` sur 4 chiffres (DC-03: adresse « Unused » pour RP). Séquence prise sur le compteur global des événements (0087, 0088), comme les autres codes.
- **RP toutes les 62 s** (23:34:08, 23:35:10, 23:36:12). Il part sur la connexion en cours, juste après son `NULL`.
- **Événements système en partition 0:** `AR` (et probablement `AT`, non capturé) partent avec `ri0` et l'adresse `0`, non bourrée. Scutum les reconnaît (« Rétablissement Électricité »). La partition 0 n'empêche donc pas un code d'être reconnu. Le « CODE INCONNU » de CL/OP du plugin ne s'explique donc pas par la seule valeur 0: il viendrait de l'absence du champ `ri`, ou de la paire CL/OP avec la partition 0. L'essai avec `ri1` l'a confirmé: voir l'annexe « essai avec `ri1` ».
- **Cycle de connexion:** le hub ouvre une connexion, envoie un `NULL`, reçoit l'ACK. Scutum ferme environ 5,1 s après son dernier ACK. Le hub ouvre la suivante environ 5,0 s après cette fermeture. Le cycle fait donc 10,2 à 10,5 s. Ce n'est pas un intervalle fixe, c'est « 5 s après la fermeture ». Le hub reste ainsi presque toujours connecté.
- **NULL répété à 23:36:12:** dans la connexion 49631, le hub a envoyé deux fois le même `NULL` (même CRC, même horodatage, numéros de séquence TCP différents: c'est une répétition applicative, pas une retransmission TCP), 0,4 s après le premier ACK. Scutum a répondu par un ACK à chacun. La cause est inconnue (cas isolé sur 15 connexions).

## Capture A: mode « Connectez-vous sur demande »

Fichier `capture-ajax-A.pcapng`, 13:38:32 à 13:46:14 local le 17/10/26 (7 min 42 s). Réglages du hub: « Connectez-vous sur demande » activé; intervalle ping du centre de télésurveillance 1 min et rapport de test périodique activé (confirmés par vous). 11 connexions (ports 49800 à 49810), un message par connexion.

| Heure locale | Trame | Événement |
|---|---|---|
| 13:38:33 | `B8A4003A"SIA-DCS"0119L0#27099[#27099\|Nri0/AT0]_11:38:36,10-17-2026` | AT: coupure secteur |
| 13:38:44 | `CA58003A"SIA-DCS"0120L0#27099[#27099\|Nri0/AR0]_11:38:47,10-17-2026` | AR: secteur rétabli |
| 13:39:17 | `6B6E003D"SIA-DCS"0121L0#27099[#27099\|Nri0/RP0000]_11:39:20,10-17-2026` | RP |
| 13:40:22 | `…0122…Nri0/RP0000…` | RP |
| 13:41:27 | `…0123…Nri0/RP0000…` | RP |
| 13:42:32 | `…0124…Nri0/RP0000…` | RP |
| 13:43:37 | `…0125…Nri0/RP0000…` | RP |
| 13:44:42 | `…0126…Nri0/RP0000…` | RP |
| 13:45:11 | `B3B7003C"SIA-DCS"0127L0#27099[#27099\|Nri1/CL501]_11:45:14,10-17-2026` | CL: armement, utilisateur 501 |
| 13:45:46 | `8273003D"SIA-DCS"0128L0#27099[#27099\|Nri0/RP0000]_11:45:49,10-17-2026` | RP |
| 13:46:09 | `0472003C"SIA-DCS"0129L0#27099[#27099\|Nri1/OP501]_11:46:12,10-17-2026` | OP: désarmement, utilisateur 501 |

Chaque ACK de Scutum (`"ACK"<seq>L0#27099[]`, même séquence que la trame) est émis deux fois, comme dans les captures précédentes.

### Ce que la capture établit

- **Aucun `NULL` en mode à la demande.** Le hub n'envoie que des événements et des RP. La supervision de la liaison repose alors uniquement sur le RP.
- **Une connexion par message, fermée par Scutum.** Le hub ouvre la connexion, envoie sa trame 0,4 à 0,9 s plus tard, reçoit l'ACK. Scutum envoie le FIN 5,0 s après son ACK (constant sur les 11 connexions); le hub ne ferme jamais le premier, il répond au FIN.
- **RP toutes les ~65 s.** Les connexions RP s'ouvrent ~59,3 s après la fermeture de la précédente, puis la trame part ~0,7 s plus tard. Le temporisateur d'1 min semble donc compté à partir de la fin de l'échange précédent, pas sur une horloge fixe (déduit). En mode permanent, le RP revenait toutes les 62 s.
- **Un événement ne décale pas le RP.** Le CL de 13:45:11 n'a pas repoussé le RP suivant (13:45:46, 64 s après celui de 13:44:42).
- **Séquence globale continue (0119 à 0129)**, RP compris. Adresse non bourrée (`CL501`, `AT0`).
- **AT/AR en début de capture:** coupure et retour secteur (même trames que dans la capture du cycle), sans doute liés à la manipulation du hub lors du changement de réglage. Cause non vérifiée.
- **Horodatage:** les trames portent 3 s de plus que l'horloge de la machine de capture (11:38:36 contre 11:38:33 UTC). Dans les captures du 16/10 les deux coïncidaient. L'écart vient de l'une des deux horloges; non tranché.

### Extranet Scutum pour la capture A

| Heure | Code affiché | Libellé |
|---|---|---|
| 13:38:33 | `AT0000` | COUPURE ELECTRICITE, `***** Zone 0000 Non Connue *****` |
| 13:38:44 | `AR0000` | Retablissement Electricite, `***** Zone 0000 Non Connue *****` |
| 13:39:17 à 13:54:25 | `RP0000` | Test Cyclique, toutes les 65 s (15 occurrences) |
| 13:45:11 | `CL0001` | Mise En Service par U0501 |
| 13:46:09 | `OP0001` | Mise Hors Service par U0501 |

- Les heures de l'extranet sont celles de réception: elles coïncident avec la capture, pas avec l'horodatage des trames (+3 s).
- **Aucune alarme de liaison** chez Scutum alors qu'aucun `NULL` n'est émis: le RP suffit à Scutum pour superviser un transmetteur à la demande (pour ce compte du moins).
- Les RP continuent après la fin de la capture (13:46:14) au même rythme, jusqu'à 13:54:25.

## Capture B: mode permanent, intervalle ping 5 min

Fichier `capture-ajax-b.pcapng`, 13:59:49 à 14:05:22 local le 17/10/26 (5 min 33 s). Réglages du hub: connexion maintenue (« Connectez-vous sur demande » désactivé), intervalle ping du centre de télésurveillance passé à 5 min (2 min n'est pas proposé par le réglage), rapport de test périodique activé. 33 connexions (ports 49824 à 49856), 41 `NULL`.

| Heure locale | Connexion | Trames du hub |
|---|---|---|
| 13:59:49 à 14:05:22 | toutes | `"NULL"0000L0#27099[]_ts` dès l'ouverture |
| 14:00:40, 14:01:11, 14:01:42, 14:02:13, 14:02:44, 14:03:15, 14:03:46, 14:04:17 | une sur trois environ | le même `NULL` (même horodatage, même CRC) renvoyé 0,49 s après le premier ACK |
| 14:04:39 | 49852 | `NULL`, puis 1,3 s après `"SIA-DCS"0144L0#27099[#27099\|Nri0/RP0000]` |
| 14:05:00 | 49854 | `NULL`, puis `"SIA-DCS"0145…[#27099\|Nri1/CL501]` |
| 14:05:12 | 49855 | `NULL`, puis `"SIA-DCS"0146…[#27099\|Nri1/OP501]` |

### Ce que la capture établit

- **Le rythme des `NULL` ne dépend pas de l'intervalle ping.** Une connexion toutes les 10,4 s en moyenne (10,2 à 11,5 s), comme à 1 min: Scutum ferme 5,0 s après son ACK, le hub rouvre ~5,0 s plus tard et envoie un `NULL` à chaque ouverture. Le « `NULL` toutes les 10 s » n'est pas un réglage: c'est la reconnexion immédiate du mode permanent, cadencée par la fermeture de Scutum.
- **Un second `NULL` toutes les ~31 s** sur la connexion ouverte. C'est un nouveau segment TCP (le numéro de séquence avance), donc un envoi applicatif du hub, pas une retransmission TCP. Il n'arrive que si la connexion est ouverte à ce moment-là. Hypothèse: un temporisateur de maintien de ~30 s propre au hub, indépendant des reconnexions et de l'intervalle ping (déduit, non documenté).
- **Le doublon de l'ACK de Scutum est une retransmission TCP** (même numéro de séquence, ~0,23 s après). Ce n'est pas un second ACK applicatif.
- **Un seul RP en 5 min 33 s** (14:04:39, séquence 0144), cohérent avec un intervalle de 5 min. La capture est trop courte pour mesurer la période (il faudrait deux RP); le journal de l'extranet la donnera.
- **RP et événements passent sur la connexion ouverte, après son `NULL`.** Le hub n'ouvre pas de connexion dédiée: il attend la connexion suivante ou utilise celle qui est ouverte.
- **Séquence:** 0129 en fin de capture A, 0144 au premier RP de la capture B. 14 numéros (0130 à 0143) ont été émis entre les deux captures sans être capturés: au moins les 8 RP de l'extranet après 13:46:14, le reste non identifié (RP suivants, `YG` du changement de réglage?). Le compteur continue d'un mode à l'autre.
- **Horodatage:** +3,7 s par rapport à l'horloge de capture (12:00:44 contre 12:00:40 UTC).

### Modèle Ajax déduit des captures A et B

| | À la demande | Permanent |
|---|---|---|
| `NULL` | aucun | à chaque ouverture de connexion, plus un renvoi toutes les ~30 s si la connexion est encore ouverte |
| RP | toutes les « intervalle ping » (1 min → 65 s mesurées) | idem (1 RP vu avec 5 min, période exacte à mesurer) |
| Connexion | ouverte pour chaque message, fermée par le CSR | rouverte ~5 s après chaque fermeture par le CSR |
| Événements | une connexion par événement | sur la connexion ouverte, après le `NULL` |
| Supervision de liaison côté CSR | par le RP | par les `NULL` et le RP |

## Correspondance avec l'extranet Scutum

Journal de l'extranet Scutum pour la même période (heure locale, source `IP`):

| Heure | Code affiché | Libellé | Trame correspondante |
|---|---|---|---|
| 22:30:34 | `CL0001` | Mise En Service par U0501 | `…0013…[#27099\|Nri1/CL501]` |
| 22:30:33 | `OP0001` | Mise Hors Service par U0501 | `…0012…[#27099\|Nri1/OP501]` |
| 22:30:22 | `CL0001` | Mise En Service par U0501 | `…0011…[#27099\|Nri1/CL501]` |
| 22:30:19 | `OP0001` | Mise Hors Service par U0501 | `…0010…[#27099\|Nri1/OP501]` |
| 22:30:08 | `CL0001` | Mise En Service par U0501 | `…0009…[#27099\|Nri1/CL501]` |
| 22:29:57 | `RP0000` | Test Cyclique | non capturé |
| 22:28:55 | `RP0000` | Test Cyclique | non capturé |
| 22:27:53 | `RP0000` | Test Cyclique | non capturé |
| 22:26:51 | `RP0000` | Test Cyclique | non capturé |

Ce que cela établit:
- **Les 5 horaires correspondent** aux 5 trames capturées.
- **`ri1` devient le `0001` du code affiché** (`CL0001`, `OP0001`): c'est la partition 1. Sans `ri`, Scutum afficherait probablement `0000` (à vérifier).
- **L'adresse `501` est un numéro d'utilisateur**: Scutum affiche `U0501`. Cela confirme la lecture DC-03 (CL et OP: adresse = utilisateur).
- **CL = « Mise En Service », OP = « Mise Hors Service »**: Scutum interprète ces deux codes.
- **Les `NULL` n'apparaissent pas** dans le journal, seulement les événements.
- **« Test Cyclique » (`RP0000`)** revient toutes les 62 s environ (22:26:51, 22:27:53, 22:28:55, 22:29:57). C'est un événement `RP` (test périodique) distinct des `NULL`. Ces trames-là ne sont pas dans les captures, mais la capture du cycle (plus bas) relève le format: `[#27099|Nri0/RP0000]`.

### Autres événements émis par l'Ajax (extranet, hors captures)

| Heure | Code affiché | Libellé | Colonne détail | Cause |
|---|---|---|---|---|
| 22:24:45 | `AR0000` | Rétablissement Électricité | `***** Zone 0000 Non Connue *****` | `AR` (AC power restored), émis par le hub |
| 22:24:46 | `YG0000` | CODE INCONNU | – | `YG` (changement de paramètres), émis lors de la saisie des infos du centre de surveillance |
| 22:53:32 | `XC0001` | RETABLISSEMENT SUPERVISION | `***** Zone 0001 Non Connue *****` | `XC`, émis par l'Ajax: retour à la normale de la force du signal d'un module |

- Les trames correspondantes n'ont pas été capturées: leur format exact n'est pas relevé.
- `XC0001`: la zone 1 est affichée dans le champ à 4 chiffres, comme pour `BA0001`, ce qui va dans le sens de « les codes adressés par zone affichent la zone dans ce champ ». Selon vos recherches, `XL` est émis quand un module est « perdu » (force du signal trop faible) et Scutum le gère. `XC` correspond au retour à la normale (force du signal de nouveau normale). `XC` n'est pas dans la table DC-03 standard (vérifié par vous dans la table du dépôt): probablement une extension d'Ajax pour signaler ce retour. Scutum la reconnaît quand même.
- `AR` est reconnu (« Rétablissement Électricité ») avec la partition/adresse `0000`. Scutum signale en plus « Zone 0000 Non Connue » : le code est adressé par zone, et la zone 0 n'est pas déclarée sur le compte. Ce n'est pas bloquant pour le libellé.
- `YG` n'a pas de libellé chez Scutum (« CODE INCONNU »). Un code inconnu de Scutum n'est donc pas forcément un défaut de format: pour CL/OP du plugin, le même libellé venait de l'absence de `ri` (confirmé par l'essai avec `ri1`), alors qu'ici c'est le code lui-même qui est inconnu.

## Comparaison avec le plugin

| Point | Ajax | Plugin (état actuel) |
|---|---|---|
| Supervision | `"NULL"0000L0#27099[]_ts` | `"SIA-DCS"…[#acct\|0000]` en clair (décision D-86) |
| Compte | non bourré | non bourré |
| Horodatage | `_HH:MM:SS,MM-DD-YYYY` UTC | identique |
| Armement | `[#27099\|Nri1/CL501]` | `[#acct\|NCL001]` (utilisateur 001, sans `ri`) |
| Désarmement | `[#27099\|Nri1/OP501]` | `[#acct\|NOP001]` (idem) |
| Intrusion | `[#27099\|Nri1/BA1]` | `[#acct\|NBA001]` (sans `ri`) |
| Test cyclique | `[#27099\|Nri0/RP0000]`, période = intervalle ping (1 min → 62 à 65 s) | absent |
| Mode à la demande | aucun `NULL`, supervision par le RP seul | sans objet (supervision obligatoire) |
| Séquence | globale, 0001 à 9999; `NULL` toujours en 0000 | à vérifier dans le daemon |
| Champ `ri` | `ri1` (alarme), `ri0` (système: RP, AR) | non implémenté |
| Adresse | non bourrée (`BA1`) | bourrée sur 3 chiffres (`BA001`): accepté, voir l'annexe |
| Connexion TCP (permanent) | `NULL` puis événement(s), fermeture par Scutum ~5 s après, reconnexion 5 s après; `NULL` renvoyé toutes les ~30 s si la connexion est ouverte | une connexion par trame, fermée par le plugin juste après l'ACK |
| Connexion TCP (à la demande) | une connexion par message, fermée par Scutum 5 s après l'ACK | une connexion par trame, fermée par le plugin |

Écarts établis par les essais (annexes):
- **`ri` manquant:** c'est la cause du « CODE INCONNU » de CL/OP (confirmé).
- **Adresse bourrée et numéro d'utilisateur:** sans effet, Scutum les accepte (confirmé pour `BA001` et `U0001`).
- **Supervision, RP et connexion TCP:** écarts avec Ajax, sans défaut constaté chez Scutum. À aligner selon la directive « se comporter comme Ajax ».

## Annexe: trace extranet d'un CL envoyé par le plugin

Extranet Scutum, événement envoyé par le plugin actuel (trame `[#27099|NCL001]`, sans `ri`):

| Heure | Source | Code affiché | Libellé |
|---|---|---|---|
| 16/10/26 18:05:24 | IP | `CL0000` | CODE INCONNU par U0001 |
| 16/10/26 18:06:30 | IP | `OP0000` | CODE INCONNU par U0001 |

Le OP (trame `[#27099|NOP001]`) donne le même résultat que le CL.

Lecture, à comparer avec Ajax (`CL0001` « Mise En Service par U0501 », `OP0001` « Mise Hors Service par U0501 »):
- **Adresse:** `001` est bien lue comme utilisateur (`U0001`). L'interprétation DC-03 est correcte.
- **Partition:** `0000` au lieu de `0001`, ce qui confirme que l'absence de `ri` donne la partition 0.
- **Libellé:** « CODE INCONNU » au lieu de « Mise En Service ». Scutum ne reconnaît pas les couples `CL`/`OP` + partition `0000`, alors que les mêmes codes avec la partition `0001` sont reconnus. **Confirmé par l'essai du 16/10/26 à 23:46:** avec `Nri1/CL001` et `Nri1/OP001`, Scutum affiche « Mise En Service » et « Mise Hors Service par U0001 » (annexe « essai avec `ri1` »).

### Annexe: essai avec `ri1` (script `scripts/sia_csr_probe.py`)

Le 16/10/26 à 23:46, une session façon Ajax (`NULL`, puis CL et OP sur la même connexion) envoyée depuis le Mac de développement:

```
23:46:03.243 -> C10B0028"NULL"0000L0#27099[]_21:46:03,10-16-2026
23:46:03.281 <- 12C80013"ACK"0000L0#27099[]
23:46:04.287 -> 4E43003C"SIA-DCS"0001L0#27099[#27099|Nri1/CL001]_21:46:04,10-16-2026
23:46:04.332 <- EECC0013"ACK"0001L0#27099[]
23:46:05.335 -> 408E003C"SIA-DCS"0002L0#27099[#27099|Nri1/OP001]_21:46:05,10-16-2026
23:46:05.422 <- AAC30013"ACK"0002L0#27099[]
   CSR closed the connection after 5.0 s
```

Extranet:

| Heure | Code affiché | Libellé |
|---|---|---|
| 23:46:05 | `OP0001` | Mise Hors Service par U0001 |
| 23:46:04 | `CL0001` | Mise En Service par U0001 |

**Confirmé:** avec `ri1`, CL et OP du plugin sont reconnus. Sans `ri`, ils donnaient `CL0000`/`OP0000` « CODE INCONNU ». La cause était donc l'absence du champ `ri`. Le reste du format (adresse `001` bourrée pour un utilisateur, séquence 0001, session `NULL` + événements, fermeture par Scutum après 5,0 s) est accepté tel quel.

Deuxième essai à 23:48, BA avec l'adresse non bourrée puis bourrée, une session chacun:

```
23:48:03.484 -> 5AD0003A"SIA-DCS"0001L0#27099[#27099|Nri1/BA1]_21:48:03,10-16-2026
23:48:03.566 <- EECC0013"ACK"0001L0#27099[]
   CSR closed the connection after 5.0 s
23:48:09.760 -> F073003C"SIA-DCS"0001L0#27099[#27099|Nri1/BA001]_21:48:09,10-16-2026
23:48:09.852 <- EECC0013"ACK"0001L0#27099[]
   CSR closed the connection after 5.1 s
```

(chaque événement précédé d'un `NULL` acquitté). Extranet:

| Heure | Code affiché | Libellé | Colonne détail |
|---|---|---|---|
| 23:48:09 | `BA0001` | INTRUSION | `***** Zone 0001 Non Connue *****` |
| 23:48:03 | `BA0001` | INTRUSION | `***** Zone 0001 Non Connue *****` |

**Confirmé:** `BA1` et `BA001` sont lus de la même façon (zone 1). Le bourrage sur 3 chiffres du plugin est accepté, il n'y a pas à le changer. Le champ à 4 chiffres de `BA0001` est bien la zone (ici égale à la partition, 1). La même séquence 0001 sur deux sessions successives a été acquittée normalement: Scutum ne rejette pas un numéro de séquence répété.

### Annexe: BC du plugin

Extranet Scutum, `BC` envoyé par le plugin (trame supposée `[#27099|NBC001]`, sans `ri`; la trame réelle n'a pas été relevée):

`BC0001 ACQUITTEMENT ALARME ***** Zone 0001 Non Connue *****`

- Scutum reconnaît le code (« Acquittement alarme »).
- Il lit l'adresse `001` comme une **zone**, alors que CL et OP donnent « par U0001 » pour la même adresse. Scutum traite donc `BC` comme un code adressé par zone.
- La table DC-03 du dépôt donne `BC` adressé par utilisateur, et le daemon s'y conforme (`_USER_ADDRESSED_SIA_CODES`). La table DC-03 (PDF Peoplecall, vérifié) confirme: `BC` Burglary Cancel, adresse « User ». C'est donc Scutum qui a sa propre lecture. Le libellé reste juste, seule la mention de zone est fausse. Le plugin ne change pas.
- Le champ à 4 chiffres (`0001`) vient ici de l'adresse, pas de `ri` (sans `ri`, CL donne `0000`).

### Annexe: validation réelle du plugin avec `ri1` (17/10/26)

Plugin à `d35ec5a` déployé sur test-jeedom.lehoux.net, numéro d'utilisateur SIA réglé à 501. Séquence pilotée depuis Jeedom: armement, alarme intrusion zone 2, désarmement. Extranet Scutum:

| Heure | Code | Libellé | Détail |
|---|---|---|---|
| 11:17:28 | `OP0001` | Mise Hors Service par U0501 | - |
| 11:17:28 | `BC0501` | ACQUITTEMENT ALARME | `***** Zone 0501 Non Connue *****` |
| 11:16:36 | `BA0002` | INTRUSION | `***** Zone 0002 Non Connue *****` |
| 11:15:25 | `CL0001` | Mise En Service par U0501 | - |

- Tous les codes sont reconnus, plus aucun « CODE INCONNU ».
- CL et OP s'affichent comme chez l'Ajax: partition `0001`, puis « par U0501 ».
- BA porte la zone (`0002`).
- BC garde la lecture propre à Scutum: l'adresse utilisateur (501) est affichée comme une zone (voir l'annexe précédente). C'est sans effet sur le fonctionnement.

## À faire

Directive: aligner le plugin sur le comportement d'Ajax, reconnu par les CSR. Les particularités d'un CSR passeront ensuite par des options.

1. **Fait et validé en réel chez Scutum le 17/10/26 (branche `fix/sia-dcs-n-prefix`, annexe ci-dessus):** `ri` dans le bloc de données de chaque événement (CL, OP, BA, BC) → `[#acct|Nri1/CL001]`. La partition est la constante `SIA_AREA_NUMBER = 1` du daemon, pas un paramètre: un seul équipement siaDC09, donc une seule partition. La supervision ne porte pas de `ri`.
2. En réflexion: test cyclique `Nri0/RP0000` toutes les 62 s.
3. En réflexion: supervision par un vrai `NULL` (`"NULL"0000L0#acct[]_ts`).
4. En réflexion: transport TCP avec `NULL` puis événement(s) sur la même connexion, fermeture laissée au CSR, reconnexion 5 s après.

Les points 2 à 4 sont repris le 17/10/26 dans l'Epic 17 (profils de comportement par CSR, en cours de Correct Course). Ils deviennent des options du wizard, pré-réglées par profil, plutôt qu'un changement du comportement par défaut, qui reste celui validé sur le serveur de test (D-86). Les captures A et B (modèle Ajax ci-dessus) en fixent les paramètres.

Décision du 17/10/26: deux trames à distinguer. La trame de supervision (`NULL` ou `"SIA-DCS"` à bloc vide) ne sert qu'au maintien de la connexion TCP en mode permanent. Le test cyclique (`RP`) est émis dans les deux modes. Le mode permanent est reporté: aucun CSR à disposition ne l'accepte, et un CSR qui sert des milliers de clients n'a pas intérêt à maintenir autant de connexions. Ajax fonctionne dans les deux modes; le profil Ajax du plugin sera donc à la demande.

Reste à mesurer: la période du RP avec l'intervalle ping à 5 min (journal de l'extranet de la capture B).
