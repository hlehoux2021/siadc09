# Conseils Frigate pour la télésurveillance

> 🧪 Version de test : ces conseils ont été vérifiés avec **Frigate 0.17** et le plugin Jeedom **Frigate**. Revérifiez-les si vous utilisez une autre version.

siaDC09 peut ajouter à chaque trame d'alarme un lien vers une **photo** et une **vidéo** Frigate de l'événement. L'opérateur de la centrale ouvre ce lien depuis sa console. Cette page explique comment régler Frigate pour que ce lien fonctionne, reste sûr et pointe vers une image utile. Le câblage côté Jeedom est décrit dans le [guide utilisateur](index.md#photos-et-vidéos-frigate-optionnel).

**Sommaire**

1. [Comment siaDC09 choisit l'image](#comment-siadc09-choisit-limage)
2. [Deux accès différents à Frigate](#deux-accès-différents-à-frigate)
3. [Exposer Frigate à la centrale](#exposer-frigate-à-la-centrale)
4. [Objets suivis et labels](#objets-suivis-et-labels)
5. [Photos (snapshots)](#photos-snapshots)
6. [Enregistrements et durée de conservation](#enregistrements-et-durée-de-conservation)
7. [Caméras et zones](#caméras-et-zones)
8. [Délais](#délais)
9. [Exemple de configuration](#exemple-de-configuration)
10. [Vérifications](#vérifications)

---

## Comment siaDC09 choisit l'image

Dès que le capteur déclenche, la commande **Prefetch événement Frigate** (action immédiate) lance, sur la caméra de la zone :

1. **Une capture forcée** : siaDC09 crée dans Frigate un événement manuel de **30 s**, avec enregistrement, sous le label `alarm`. Il obtient ainsi une image de la caméra même si Frigate n'a encore rien détecté.
2. **Une recherche des vrais événements** de la caméra pendant **25 s** au plus : les événements détectés par Frigate, **de n'importe quel label**, commencés au plus tôt **30 s avant** le déclenchement et qui ont une photo.
3. **Un classement**, du meilleur au moins bon :

| Rang | Source | Remarque |
|------|--------|----------|
| 1 | Événement réel avec le label `person` | Le plus récent. La recherche s'arrête dès qu'il a aussi sa vidéo |
| 2 | Événement réel d'un autre label (`car`, `dog`…) | Le plus récent |
| 3 | La capture forcée `alarm` | Image de la caméra au moment du déclenchement, sans détection |
| — | Rien | L'alarme part **sans lien média** |

Au moment où l'alarme est envoyée, siaDC09 joint le meilleur résultat trouvé jusque-là. La photo est toujours jointe ; la vidéo ne l'est que si Frigate l'a déjà prête.

**La photo ne retarde et ne bloque jamais l'alarme.** Si Frigate est injoignable ou lent, l'alarme part quand même, sans média.

## Deux accès différents à Frigate

siaDC09 utilise Frigate par **deux chemins distincts** :

| Qui | Adresse utilisée | Pour quoi |
|-----|------------------|-----------|
| Le démon siaDC09, sur votre réseau | L'**adresse et le port configurés dans le plugin Frigate** de Jeedom | Créer la capture forcée et chercher les événements |
| La centrale, depuis Internet | L'**URL media Frigate** saisie à l'étape 3 de l'assistant | Afficher la photo et la vidéo |

**Côté Jeedom (réseau local).** La capture forcée exige le rôle `admin` de Frigate. Frigate l'accorde d'office sur son port interne non authentifié (**5000**), et siaDC09 n'envoie jamais d'identifiants à Frigate. Si le plugin Frigate pointe vers le port authentifié (**8971**), la capture forcée est refusée : siaDC09 écrit un avertissement dans le log et continue avec les vrais événements seulement (rangs 1 et 2). Pour avoir la capture forcée, le plugin Frigate doit donc utiliser le port 5000, **joignable uniquement depuis votre réseau local**.

**Côté centrale (Internet).** La centrale ouvre des adresses de la forme :

```
<URL media>/api/events/<id de l'événement>/snapshot.jpg
<URL media>/api/events/<id de l'événement>/clip.mp4
```

Il faut donc un accès depuis Internet, **authentifié**, à ces deux chemins. C'est l'objet de la section suivante.

## Exposer Frigate à la centrale

Frigate donne accès à vos caméras, et à l'intérieur de votre maison. Exposez-le avec prudence :

- **N'exposez jamais le port 5000 sur Internet.** Il n'a aucune authentification et donne le rôle `admin` à tout le monde.
- **Passez par un reverse-proxy en HTTPS** (Caddy, Nginx, Traefik, Nginx Proxy Manager…), avec un certificat valide (Let's Encrypt). Ne redirigez pas un port de votre box directement vers Frigate.
- **Exigez une authentification** : soit l'authentification de Frigate (port 8971), soit celle du reverse-proxy. Ne laissez pas l'accès anonyme.
- **Créez un compte dédié à la centrale**, avec le rôle `viewer` (lecture seule) si vous utilisez l'authentification de Frigate. Ne lui donnez pas votre compte administrateur : vous pourrez ainsi lui retirer l'accès sans toucher au vôtre.
- **Limitez ce qui est exposé.** Si votre reverse-proxy le permet, n'ouvrez à la centrale que les chemins `/api/events/*/snapshot.jpg` et `/api/events/*/clip.mp4`, pas l'interface complète ni le flux en direct.
- **Filtrez par adresse IP** si la centrale vous communique les adresses d'où elle se connecte.
- **Tenez Frigate et le reverse-proxy à jour.**

**Les identifiants ne sont jamais stockés dans siaDC09.** L'URL media contient des **marqueurs littéraux** à la place des identifiants, par exemple :

```
https://<user>:<pass>@frigate.example.org/
https://frigate.example.org/?accesstoken=<token>
```

Choisissez la forme que votre reverse-proxy accepte. Vous communiquez les vrais identifiants à la centrale par un autre moyen ; c'est elle qui remplace les marqueurs. **N'écrivez jamais un vrai mot de passe dans l'URL media** : elle part en clair dans chaque trame d'alarme.

## Objets suivis et labels

Frigate ne crée un événement réel que pour les objets qu'il **suit** (`objects.track`). Ce sont ces événements qui donnent les meilleures images (rangs 1 et 2).

- **Suivez au moins `person`**. C'est le label préféré de siaDC09.
- Ajoutez les autres objets pertinents pour votre site (`car`, `dog`, `cat`…). N'importe lequel donne une image plus utile que la capture forcée.
- Les labels de `objects.track` doivent exister dans le **modèle de détection** (COCO en standard : `person`, `car`, `dog`…). Un label inconnu, par exemple « personne », est **ignoré sans message d'erreur**.
- **N'ajoutez pas `alarm` à `objects.track`.** Ce n'est pas un objet du modèle : Frigate le supprimerait de la liste. Le label `alarm` n'est utilisé que pour les événements manuels de siaDC09, et Frigate l'accepte tel quel.
- Réglez les **filtres** (`objects.filters` : `min_score`, `threshold`, surfaces minimale et maximale) pour éviter les fausses détections. Une fausse détection récente, par exemple un chat pris pour une personne, peut être choisie à la place d'une bonne image.

On distingue deux types d'événements : **détectés** (`object`) et **manuels** (`api`). siaDC09 ne classe comme « réels » que les premiers ; ses propres captures forcées ne sont que le rang 3.

## Photos (snapshots)

- **Activez les snapshots** (`snapshots.enabled: true`), globalement ou pour chaque caméra reliée à une zone. **Un événement sans photo est ignoré** par siaDC09.
- Pour une image lisible par un opérateur : `clean_copy: true`. Vous pouvez désactiver `bounding_box` (le cadre de détection) et `timestamp` ; les deux conviennent.
- **Durée de conservation** : la centrale doit pouvoir ouvrir le lien **pendant son traitement de l'alarme, et plus tard** en cas de litige. Réglez `snapshots.retain` en conséquence, label par label. La clé `objects` accepte aussi `alarm`, pour garder les captures forcées :

```yaml
snapshots:
  enabled: true
  clean_copy: true
  retain:
    default: 7
    objects:
      person: 15
      alarm: 15
```

## Enregistrements et durée de conservation

La vidéo jointe (`clip.mp4`) n'existe que si Frigate **enregistre** la caméra :

- **Activez l'enregistrement** (`record.enabled: true`) sur chaque caméra reliée à une zone.
- **Les captures forcées `alarm` sont toujours classées en « alertes »** par Frigate, quel que soit `review.alerts.labels`. Leur vidéo suit donc `record.alerts.retain`.
- Les événements réels ne sont des **alertes** que si leur label figure dans `review.alerts.labels` (par défaut `person` et `car`). Sinon ce sont des **détections**, conservées selon `record.detections.retain`, souvent plus court. Mettez dans `review.alerts.labels` les labels qui comptent pour la télésurveillance.
- Donnez à `record.alerts.retain.days` une durée cohérente avec celle des photos, par exemple 15 jours.
- `pre_capture` et `post_capture` (quelques secondes) permettent de voir ce qui précède et suit l'événement.

La vidéo d'une capture forcée n'est complète qu'après les 30 s de l'événement. Juste après le déclenchement, elle est **partielle**, voire pas encore disponible. C'est pourquoi siaDC09 ne joint le lien vidéo que si Frigate indique qu'elle est prête. Quand l'opérateur l'ouvre un peu plus tard, elle est complète.

## Caméras et zones

- **Une caméra par zone**, cadrée **serré sur l'accès protégé** de la zone (porte, fenêtre, portail), plutôt qu'un plan large de tout le jardin. La recherche ne remonte que 30 s avant le déclenchement : un cadrage serré donne un événement qui correspond vraiment à l'intrusion.
- Le nom de caméra utilisé est celui de **Frigate** (repris par le plugin Frigate lors de la création de l'équipement caméra). Si vous renommez une caméra dans Frigate, vérifiez que l'équipement caméra du plugin Frigate porte bien le nouveau nom, puis refaites l'étape 3 de l'assistant.
- Une caméra partagée entre deux zones fonctionne. Si les deux zones déclenchent en même temps, le résultat de la dernière recherche remplace le précédent.

## Délais

- Le **Prefetch** doit être câblé en **action immédiate** : il part au premier capteur, pendant le délai de déclenchement de l'alarme.
- La recherche dure **25 s au plus**. Avec un délai de déclenchement de l'alarme **d'au moins 20 à 30 s**, siaDC09 a le temps de trouver un événement réel. Avec un délai plus court, l'alarme part avec le meilleur résultat du moment, souvent la capture forcée.
- Le résultat reste valable **2 minutes**. Si l'alarme part plus de 2 minutes après le premier capteur, elle part sans média.

## Exemple de configuration

Extrait à adapter, pour une caméra `entree` reliée à une zone :

```yaml
objects:
  track: [person, car, dog, cat]
  filters:
    person:
      min_score: 0.65
      threshold: 0.8

snapshots:
  enabled: true
  clean_copy: true
  retain:
    default: 7
    objects:
      person: 15
      alarm: 15

record:
  enabled: true
  alerts:
    pre_capture: 5
    post_capture: 5
    retain:
      days: 15
      mode: all
  detections:
    retain:
      days: 7
      mode: motion

review:
  alerts:
    labels: [person, car]

cameras:
  entree:
    # ffmpeg, detect… selon votre installation
    snapshots:
      enabled: true
    record:
      enabled: true
```

## Vérifications

Avant de compter sur les médias, faites un essai coordonné avec votre centrale :

1. Déclenchez la zone (en prévenant la centrale). Dans Frigate, vérifiez qu'un événement **`alarm`** apparaît sur la caméra de la zone. S'il manque, regardez le log `siaDC09_daemon` : un refus de création veut dire que le plugin Frigate n'utilise pas le port 5000.
2. Vérifiez le lien envoyé. L'inspecteur de protocole de l'onglet **Diagnostic** n'affiche pas encore le bloc média de la trame. En niveau de log **Debug**, le log `siaDC09` indique l'URL média résolue (`résolu media_url=…`).
3. Ouvrez vous-même ce lien **depuis l'extérieur de votre réseau** (téléphone en 4G par exemple), en remplaçant les marqueurs par les identifiants de la centrale : la photo doit s'afficher, et l'accès sans identifiants doit être refusé.
4. Demandez à la centrale de confirmer qu'elle voit la photo et la vidéo depuis sa console.
