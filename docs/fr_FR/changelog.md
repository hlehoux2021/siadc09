# Changelog plugin Télésurveillance SIA DC-09

> **IMPORTANT**
>
> Après chaque mise à jour, vérifiez dans le log `siaDC09_daemon` la ligne `Démon SIA DC-09 version X.Y.Z` : elle confirme que le démon qui tourne est bien celui de la version installée. Pensez à redémarrer le démon si ce n'est pas le cas.

# Version de test — premiers testeurs (non publiée)

Version de pré-diffusion, destinée aux premiers testeurs. Ce n'est pas une version publiée : elle n'est disponible ni sur le Market ni comme release GitHub, et son contenu peut encore changer. Pas de version antérieure : il n'y a rien à migrer.

**Transmission des alarmes**

- Transmission des alarmes du plugin Alarme vers une centrale de télésurveillance, protocole **SIA DC-09-2021**, en **TCP ou UDP** : alarme d'intrusion (BA) avec le numéro de zone. Le plugin ne gère que l'intrusion.
- Armement (CL), désarmement (BC + OP) et réinitialisation (BC), adressés par numéro d'utilisateur SIA.
- Une trame refusée par la centrale (NAK) est renvoyée immédiatement avec un horodatage mis à jour.
- Trames conformes à l'annexe B de DC-09 et à DC-03 (préfixe `N`, partition `ri1`) : reconnues par un centre de télésurveillance exigeant, qui affichait auparavant « CODE INCONNU » pour l'armement et le désarmement.
- **Chiffrement AES** conforme à DC-09-2021 (§ 5.4) pour la supervision et les alarmes, clé de 128, 192 ou 256 bits saisie en hexadécimal. Une clé absente ou invalide bloque tout envoi (jamais d'envoi en clair). Pas encore validé avec un vrai récepteur.

**Assistant de configuration**

- **Assistant de configuration en 3 étapes** : Centrale, Test, Zones et alertes. Le test est lancé à la demande, avec un résultat par test ; « Suivant » n'apparaît qu'après succès (sinon « Ignorer »), et « Modifier la centrale » ramène à l'étape 1. Les options avancées se trouvent à l'étape 2.
- **Supervision configurable** (aucune, SIA-DCS ou NULL) avec sa période, **test cyclique (RP)** avec sa période, reconnaissance des réponses DUH de la centrale.
- Reconnexion TCP automatique en cas de coupure. Pas de connexion TCP permanente.

**Alarme Jeedom**

- **Câblage automatique du plugin Alarme** : boutons « Lier » et « Délier », commandes Armement, Désarmement, Réinitialisation et Alarme intrusion, Prefetch Frigate.
- **Alertes** à trois niveaux (T1, T2, T3) vers une commande de notification, le centre de messages ou un scénario ; surveillance du démon toutes les 5 minutes (« Démon bloqué »).
- **Widget** Télésurveillance (supervision et dernier événement) et **onglet Diagnostic** : dernières erreurs et inspecteur de protocole.

**Levée de doute photo / vidéo (Frigate, optionnel)**

- Capture forcée au déclenchement ; photo, vidéo, ou les deux, jointes à l'alarme. L'alarme n'attend jamais le média.
- **Par adresse (URL)** : lien de format U (URL Multimedia Direct) ou V (Video Verification Link), une extension commune ou une par lien.
- **Par dépôt FTP/FTPS** : serveur FTPS (certificat reconnu ou auto-signé épinglé par son empreinte), FTP sans TLS en option avec avertissement, test de connexion FTPS, fichiers nommés `compte_zone_horodatage_image`, rafale de 5 photos. Indépendant de la trame : l'échec d'un dépôt n'empêche jamais l'alarme de partir. Voir la page [Dépôt FTP/FTPS](media-ftps.md).

**Documentation**

- Documentation utilisateur en français, avec un résumé en anglais ; interface en français.

Limitations connues de cette version de test : voir la [documentation](index.md#limitations-connues), notamment : **chiffrement AES pas encore validé avec un vrai récepteur**, UDP testé uniquement avec un simulateur, un seul récepteur (pas de récepteur de secours).
