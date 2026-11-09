---
name: siaDC09 wizard media block (FTPS)
status: draft
sources:
  - ../../epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/EXPERIENCE.md
  - ../../../../internal-docs/design/wizard-design.md
  - ../epic-18-ftps-alarm-media-upload.md
updated: 2026-11-09
---

# siaDC09 wizard media block - Experience Spine

TLDR: on step 1 the user ticks "joindre une photo ou une vidéo", says **what** to attach (photo, vidéo, or both) and **how** the receiver gets it (an address in the alarm message, or a copy on an FTPS server). For the address way, step 1 also asks the Frigate address. **Every technical setting of a transport lives on step 2**, in the Options avancées panel, next to the SIA test: the SIA-DCS formats and extension for the address way, the server settings for the FTPS way. The FTPS server is tested on step 2 with its own button and wording. The two ways are exclusive: each shows only its own settings.

Visual rules: `DESIGN.md`. Mockup: `.working/flow-media-block-2026-11-09.excalidraw` (screens A to G).

## Decisions (user, 2026-11-09)

| Decision | Consequence |
|---|---|
| Photo / vidéo choice is in the common part of the media card (step 1), for both transports | The step 2 advanced panel no longer shows the Photo / Vidéo switches |
| The two transports are exclusive in the UI | Only the settings of the selected transport exist on screen; nothing greyed |
| **FTPS technical settings (server, port, user, password, folder, certificate) are in step 2, Options avancées**, like the SIA-DCS technical options | Step 1 has no FTPS field and no FTPS validation. The coherent rule: step 1 = choices, step 2 = technical settings and tests |
| **The Frigate address is not asked in the common zone**: it serves only the address way, so it is shown only there (step 1, card « Adresse pour la centrale ») | Under FTPS nothing about Frigate is asked: the daemon uses the Frigate plugin's own settings. 18.4 must skip the « Frigate address required » check (step 1 and the step 3 safety net) under FTPS |
| Remote folder has no default | Empty field, help « Laissez vide pour déposer à la racine du compte. » No placeholder |
| FTPS test is on step 2, beside the SIA test, with its own button and wording | No test button on step 1 |
| Advanced options show only what the chosen transport needs | Screens C and E |
| Wizard summaries are updated | Step 2 summary line and « Configuration active » (screen G) |
| Test checks connection, certificate and login only; it writes nothing | A missing or read-only folder is only found at the first alarm (ERROR + notification, 18.2) |
| « Faire confiance à cette empreinte » fills the field without a second confirmation | It then relaunches the FTPS test |
| Password required as soon as FTPS is selected | « Mot de passe FTPS : obligatoire. » |

### Decision taken by the designer, to confirm

**Photo / Vidéo stay locked by the profile** (ADR-22 unchanged), now on step 1: greyed with « Fixé par le profil « {nom} ». » and the profile select just above; free in « Personnalisé » and in a profile that declares no media key. The FTPS settings are never profile fields, so they are never locked. If Photo / Vidéo should be free under FTPS, say so: it changes only the lock rule.

## Flows

| Flow | Behaviour |
|---|---|
| Tick the media box | « Que joindre ? » (Photo, Vidéo) and the transport radios appear. At least one of Photo / Vidéo is required. |
| Choose « adresse » | The card « Adresse pour la centrale » shows the Frigate address. |
| Choose « FTPS » | Nothing more on step 1, only a note: « Les réglages du serveur FTPS se font à l'étape suivante, dans les options avancées. » |
| Suivant (step 1) | Required: Photo or Vidéo; under « adresse »: the Frigate address. Errors under the fields and in the banner (screen D). No FTPS validation here. |
| Arrive on step 2, « adresse » | One test (SIA), as today. Advanced options: formats, extension, supervision (screen E). |
| Arrive on step 2, FTPS, settings incomplete | The SIA test starts. The FTPS zone says « Serveur FTPS à renseigner » and its button « Tester le serveur FTPS » is disabled. The Options avancées open by themselves, as they do on an error, showing the « Serveur FTPS » card (screen C). |
| FTPS settings become complete | The FTPS button is enabled. The user presses it (the test does not start by itself on a half-typed form). Values are saved before the test, as for the SIA test. |
| Arrive on step 2, FTPS, settings complete | Both tests start. Each zone has its own spinner. |
| FTPS test, certificate public | Connect, TLS verified, login. Success or a failure naming the step (screen C2). |
| FTPS test, self-signed, no fingerprint | Refusal « Certificat non reconnu » with the presented fingerprint and « Faire confiance à cette empreinte ». The password is **not** sent. The button writes the fingerprint into the Serveur FTPS card and relaunches the FTPS test (screen C1). |
| FTPS test, fingerprint differs from the saved one | « Le certificat a changé », password not sent, same trust button. |
| One test fails | « Suivant » stays disabled; « Ignorer » unblocks it (as today for the SIA test); « Modifier la centrale » returns to step 1 (centrale, photo / vidéo, transport). Each test has its own relaunch button. |
| Terminer (step 3) | Safety net, as for the Frigate address today: under FTPS, server, user and password must be set; under « adresse », the Frigate address. |
| Profile without media (Ajax) | The media box is greyed and unchecked and everything below it is hidden: « Cette centrale ne reçoit ni photo ni vidéo. » |
| Advanced options, FTPS | « Serveur FTPS » card (never locked) and supervision (locked by the profile as today). Later stories add FTPS-only options there (18.6, 18.8). |

A disabled button looks disabled (grey, no hover), never only the attribute.

## Summaries

| Where | Content |
|---|---|
| Step 2, top | Line 1: « Centrale : {ip}:{port} ({transport}) - Compte : {compte} ». Line 2 (new): « Levée de doute : photo + vidéo, sur le serveur FTPS {hôte}:{port} ({dossier ou « dossier racine »}) » / « … sur un serveur FTPS (à renseigner) » / « … par une adresse dans le message d'alarme » / « Levée de doute : désactivée ». |
| « Configuration active » | New block « Levée de doute » between « Connexion » and « Zones mappées » (screen G): what is attached; the way; for FTPS the server, user, folder and certificate (auto-signé + shortened fingerprint); for « adresse » the Frigate address. **Never the password.** |

## Wording (French, vouvoiement)

| Moment | Text |
|---|---|
| What to attach | « Que joindre ? » - « Photo » - « Vidéo » ; error « Choisissez au moins la photo ou la vidéo. » |
| Transport label | « Comment la centrale reçoit-elle la photo ou la vidéo ? » |
| Radio 1 | « Une adresse (URL) dans le message d'alarme » - « La centrale va chercher le média sur votre serveur Frigate. » |
| Radio 2 | « Une copie déposée sur un serveur FTPS » - « Le plugin dépose le média sur votre serveur ; le message d'alarme ne contient pas d'adresse. » |
| Address card | « Adresse pour la centrale » - « Adresse de votre serveur Frigate * » - « Exemple : https://frigate.maison.fr » (existing wording) |
| Step 1 note, FTPS | « Les réglages du serveur FTPS se font à l'étape suivante, dans les options avancées. » |
| FTPS card (step 2 advanced) | « Serveur FTPS » - « Réglages propres à votre installation : jamais fixés par le profil. » Fields « Serveur * », « Port * », « Utilisateur * », « Mot de passe * », « Dossier distant » (help « Laissez vide pour déposer à la racine du compte. Le dossier doit exister. ») ; « Certificat du serveur » : « Certificat reconnu » (« Serveur avec un certificat d'une autorité publique (Let's Encrypt...). ») / « Certificat auto-signé » + « Empreinte SHA-256 du certificat » |
| Step 2 zones | « Test de la centrale (SIA) » ; « Test du serveur FTPS » |
| Buttons | SIA: « Relancer le test de la centrale » (replaces « Relancer le test »). FTPS: « Tester le serveur FTPS » (never run) then « Relancer le test du serveur FTPS » |
| FTPS waiting | « Serveur FTPS à renseigner » - « Complétez les réglages dans les options avancées ci-dessous, puis lancez le test. » - hint « Disponible quand serveur, utilisateur et mot de passe sont renseignés. » |
| FTPS hint | « Ce test vérifie : la connexion, le certificat, l'identifiant (aucun fichier n'est écrit). » |
| FTPS running | « Test du serveur FTPS en cours... » |
| FTPS success | « Serveur FTPS joignable » - « Certificat conforme à l'empreinte, identifiant accepté. Le dossier n'est vérifié qu'à la première alarme. » (« Certificat reconnu » for a public one) |
| Step failure | « Échec à l'étape « connexion » » - « Impossible de joindre {hôte}:{port} (connexion refusée). » - « Vérifiez : l'adresse et le port ; que le service FTPS est démarré ; le pare-feu. » Other steps: « sécurité TLS », « identifiants » (« Identifiant ou mot de passe refusé par le serveur. Corrigez-les dans les options avancées ci-dessous, puis relancez le test. »), « délai dépassé ». |
| Unknown certificate | « Certificat non reconnu » - « Le serveur présente un certificat qui n'est pas signé par une autorité publique. Comparez l'empreinte ci-dessous avec celle de votre serveur : » then « Le mot de passe n'a pas été envoyé. » then « Faire confiance à cette empreinte » |
| Changed certificate | « Le certificat a changé » - « Le serveur ne présente pas l'empreinte enregistrée. Le mot de passe n'a PAS été envoyé. Si vous avez renouvelé le certificat, faites confiance à la nouvelle empreinte : » |
| Step 2 errors (screen D2) | Zone: « Impossible de tester le serveur FTPS : » then « Serveur FTPS : obligatoire. », « Utilisateur FTPS : obligatoire. », « Mot de passe FTPS : obligatoire. » ; also « Port : nombre entre 1 et 65535 requis », « Empreinte SHA-256 : 64 caractères hexadécimaux requis ». Same messages under the fields. |
| Step 1 errors | « Photo / vidéo : choisissez au moins l'une des deux. » ; « Adresse du serveur Frigate : obligatoire quand la levée de doute est activée. » |

## Spec corrections (for 18.4 to apply to `wizard-design.md`)

`wizard-design.md` places Photo / Vidéo, the formats and the extension choice in the step 2 advanced panel. Now: Photo / Vidéo are on step 1; the advanced panel shows formats and extension only under the « adresse » transport, and the « Serveur FTPS » card plus supervision under FTPS. The step 2 button « Relancer le test » becomes « Relancer le test de la centrale ». The Frigate address validation applies to the « adresse » transport only.

## Contracts for the build stories (not decided here)

- 18.4 builds the step 1 changes, the step 2 FTPS zone, the « Serveur FTPS » card in the advanced panel, the auto-open rule, the summaries and the validations; the FTPS test action comes from 18.7. Until it exists the FTPS button stays disabled with the reason.
- The test action connects without writing and returns the presented fingerprint; the trust button stores it in `ftps_cert_fingerprint` and relaunches the FTPS test.
- The password field shows an obfuscated placeholder when a value is stored and keeps the stored value when left untouched.
- No field suggests a default it does not apply (the 18.2 hand-entry card lost its `placeholder="upload"`).

## Open points

One designer decision awaits confirmation (Photo / Vidéo locked by the profile), and the render itself awaits the user's approval.
