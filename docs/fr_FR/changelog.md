# Changelog plugin Télésurveillance SIA DC-09

> **IMPORTANT**
>
> Après chaque mise à jour, vérifiez dans le log `siaDC09_daemon` la ligne `Démon SIA DC-09 version X.Y.Z` : elle confirme que le démon qui tourne est bien celui de la version installée. Pensez à redémarrer le démon si ce n'est pas le cas.

# Version de test — premiers testeurs (non publiée)

Version de pré-diffusion, destinée aux premiers testeurs. Ce n'est pas une version publiée : elle n'est disponible ni sur le Market ni comme release GitHub, et son contenu peut encore changer. Pas de version antérieure : il n'y a rien à migrer.

- Transmission des alarmes du plugin Alarme vers une centrale de télésurveillance, protocole **SIA DC-09-2021**, en **TCP ou UDP** : intrusion (BA), incendie (FA), panique (PA), avec le numéro de zone.
- Désarmement (BC + OP), réinitialisation (BC) et armement (CL), adressés par numéro d'utilisateur SIA.
- **Supervision** du lien : trames périodiques, états OK / dégradé / perdu, reconnexion TCP automatique.
- **Alertes** à trois niveaux (T1, T2, T3) vers une commande de notification, le centre de messages ou un scénario ; surveillance du démon toutes les 5 minutes (« Démon bloqué »).
- **Assistant de configuration** en 4 étapes : paramètres de la centrale, test de connexion en direct, numérotation des zones, destinataire des alertes.
- **Widget** Télésurveillance (supervision + dernière alarme) et **onglet Diagnostic** : dernières erreurs et inspecteur de protocole.
- **Frigate** (optionnel) : capture forcée au déclenchement et lien photo/vidéo joint à l'alarme ; l'alarme n'attend jamais la photo.
- Documentation utilisateur, administrateur et développeur ; traduction française complète de l'interface.
- **Chiffrement AES** conforme à DC-09-2021 (§ 5.4) pour la supervision et les alarmes, clé de 128, 192 ou 256 bits saisie en hexadécimal. Une clé absente ou invalide bloque tout envoi (jamais d'envoi en clair). Pas encore validé avec un vrai récepteur.
- Une trame refusée par la centrale (NAK) est renvoyée immédiatement avec un horodatage mis à jour.

Limitations connues de cette version de test : voir la [documentation](index.md#limitations-connues), notamment : **chiffrement AES pas encore validé avec un vrai récepteur**, UDP testé uniquement avec un simulateur.
