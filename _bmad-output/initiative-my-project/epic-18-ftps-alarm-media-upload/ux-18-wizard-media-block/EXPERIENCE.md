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

TLDR: on step 1 the user ticks "joindre une photo ou une vidéo", says **what** to attach (photo, vidéo, or both) and **how** the receiver gets it (an address in the alarm message, or a copy on an FTPS server). The two ways are exclusive: each shows only its own settings. The FTPS server is tested on step 2, next to the SIA test, with its own button and wording. Step 2's advanced options show only what the chosen way needs.

Visual rules: `DESIGN.md`. Mockup: `.working/flow-media-block-2026-11-09.excalidraw` (screens A to G).

## Decisions (user, 2026-11-09)

| Decision | Consequence |
|---|---|
| Photo / vidéo choice moves to the common part of the media card, applies to both transports | Step 2 advanced panel no longer shows the Photo / Vidéo switches |
| The two transports are exclusive in the UI | Under « adresse »: only the Frigate address. Under « FTPS »: only the FTPS settings. Nothing greyed |
| Remote folder has no default | The field is empty, with the help « Laissez vide pour déposer à la racine du compte. » No placeholder suggesting a value that is not applied |
| FTPS test is on step 2, with the SIA test, when the transport is FTPS | No test button on step 1. Two zones on step 2, two buttons with different texts |
| Advanced options show only what the chosen transport needs | See screens E and F |
| Wizard summaries are updated | Step 2 summary gets a « Levée de doute » line; « Configuration active » gets a « Levée de doute » block (screen G) |
| Transport choice and FTPS fields live on step 1 | They are validated before « Suivant » |
| Test checks connection, certificate and login only; it writes nothing | A missing or read-only folder is only found at the first alarm (ERROR + notification, 18.2) |
| « Faire confiance à cette empreinte » fills the field without a second confirmation | The test is relaunched by the user, or by the button itself (see Flows) |
| Password required as soon as FTPS is selected | « Mot de passe FTPS : obligatoire. » |

### Decisions taken by the designer, to confirm

1. **Photo / Vidéo stay locked by the profile** (the earlier decision, ADR-22), now on step 1: greyed with « Fixé par le profil « {nom} ». » and the profile select just above; free in « Personnalisé » and in a profile that declares no media key. If you want them free under FTPS, say so: it changes only the lock rule.
2. **The Frigate address belongs to the « adresse » transport only.** It is the address the monitoring center fetches (`frigate_media_url_template`). In FTPS the daemon reads Frigate's host from the Frigate plugin's own settings, so the field would be misleading there. This differs from the epic note « Frigate address is common to both transports »: 18.4 must then skip the « Frigate address required » check (step 1 and the step 3 safety net) when the transport is FTPS.

## Flows

| Flow | Behaviour |
|---|---|
| Tick the media box | « Que joindre ? » (Photo, Vidéo) and the transport radios appear. At least one of Photo / Vidéo is required. |
| Choose « adresse » | Shows the Frigate address field only. Values typed under FTPS are kept, hidden. |
| Choose « FTPS » | Shows the « Serveur FTPS » sub-card only. Values typed under « adresse » are kept, hidden. |
| Suivant (step 1) | Required: Photo or Vidéo; then, per transport: Frigate address; or server, port (1-65535), user, password. Remote folder optional. Fingerprint, when « auto-signé » is selected, must be 64 hex characters (separators allowed). Errors under the fields and in the banner (screen D). |
| Arrive on step 2 | The SIA test starts as today; with the FTPS transport the FTPS test starts at the same time. Each zone has its own spinner. |
| FTPS test, certificate public | Connect, TLS verified against public authorities, login. Success or a failure naming the step (screen C2). |
| FTPS test, self-signed, no fingerprint | Refusal « Certificat non reconnu » with the presented fingerprint and « Faire confiance à cette empreinte ». The password is **not** sent. The button writes the fingerprint into the equipment settings and relaunches the FTPS test. |
| FTPS test, fingerprint differs from the saved one | « Le certificat a changé », password not sent, same trust button. |
| One test fails | « Suivant » stays disabled; « Ignorer » unblocks it (as today for the SIA test); « Modifier la centrale » returns to step 1 (SIA and FTPS settings). Each test has its own relaunch button. |
| Profile without media (Ajax) | The media box is greyed and unchecked and everything below it is hidden: « Cette centrale ne reçoit ni photo ni vidéo. » |
| Transport « adresse » | No FTPS zone on step 2: a single test, as today. |
| Advanced options, « adresse » | Format of the photo and video addresses, the extension choice, supervision (screen E). |
| Advanced options, FTPS | Supervision only (screen F). Later stories add FTPS-only options there (18.6, 18.8). |

Buttons are disabled while their own test runs; a disabled button looks disabled (grey, no hover), never only the attribute.

## Summaries

| Where | Content |
|---|---|
| Step 2, top | Line 1: « Centrale : {ip}:{port} ({transport}) - Compte : {compte} ». Line 2 (new): « Levée de doute : photo + vidéo, sur le serveur FTPS {hôte}:{port} ({dossier ou « dossier racine »}) » or « … par une adresse dans le message d'alarme » or « Levée de doute : désactivée ». |
| « Configuration active » | New block « Levée de doute » between « Connexion » and « Zones mappées »: what is attached; the way; for FTPS the server, user, folder and certificate (auto-signé + shortened fingerprint); for « adresse » the Frigate address. **Never the password.** |

## Wording (French, vouvoiement)

| Moment | Text |
|---|---|
| What to attach | « Que joindre ? » - « Photo » - « Vidéo » ; error « Choisissez au moins la photo ou la vidéo. » |
| Transport label | « Comment la centrale reçoit-elle la photo ou la vidéo ? » |
| Radio 1 | « Une adresse (URL) dans le message d'alarme » - « La centrale va chercher le média sur votre serveur Frigate. » |
| Radio 2 | « Une copie déposée sur un serveur FTPS » - « Le plugin dépose le média sur votre serveur ; le message d'alarme ne contient pas d'adresse. » |
| Sub-card title | « Serveur FTPS » ; for « adresse »: « Adresse pour la centrale » |
| Fields | « Serveur * », « Port * », « Utilisateur * », « Mot de passe * », « Dossier distant » (help: « Laissez vide pour déposer à la racine du compte. Le dossier doit exister. ») |
| Certificate | « Certificat du serveur » - « Certificat reconnu » (« Serveur avec un certificat d'une autorité publique (Let's Encrypt...). ») / « Certificat auto-signé » + « Empreinte SHA-256 du certificat » |
| Step 1 note | « Le serveur FTPS sera testé à l'étape suivante. » |
| Step 2 zones | « Test de la centrale (SIA) » ; « Test du serveur FTPS » |
| SIA button | « Relancer le test de la centrale » (replaces the current « Relancer le test ») |
| FTPS button | « Relancer le test du serveur FTPS » |
| FTPS hint | « Ce test vérifie : la connexion, le certificat, l'identifiant (aucun fichier n'est écrit). » |
| FTPS running | « Test du serveur FTPS en cours... » |
| FTPS success | « Serveur FTPS joignable » - « Certificat conforme à l'empreinte, identifiant accepté. Le dossier n'est vérifié qu'à la première alarme. » (« Certificat reconnu » for a public one) |
| Step failure | « Échec à l'étape « connexion » » - « Impossible de joindre {hôte}:{port} (connexion refusée). » - « Vérifiez : l'adresse et le port ; que le service FTPS est démarré ; le pare-feu. » Other steps: « sécurité TLS », « identifiants » (« Identifiant ou mot de passe refusé par le serveur. Vérifiez-les à l'étape 1 (« Modifier la centrale »). »), « délai dépassé ». |
| Unknown certificate | « Certificat non reconnu » - « Le serveur présente un certificat qui n'est pas signé par une autorité publique. Comparez l'empreinte ci-dessous avec celle de votre serveur : » then « Le mot de passe n'a pas été envoyé. » then « Faire confiance à cette empreinte » |
| Changed certificate | « Le certificat a changé » - « Le serveur ne présente pas l'empreinte enregistrée. Le mot de passe n'a PAS été envoyé. Si vous avez renouvelé le certificat, faites confiance à la nouvelle empreinte : » |
| Errors, step 1 | « Serveur FTPS : obligatoire. », « Utilisateur FTPS : obligatoire. », « Mot de passe FTPS : obligatoire. », « Port : nombre entre 1 et 65535 requis », « Empreinte SHA-256 : 64 caractères hexadécimaux requis » |
| Advanced options, FTPS | none: the media section is absent |

## Spec corrections (for 18.4 to apply to `wizard-design.md`)

`wizard-design.md` places Photo / Vidéo, the formats and the extension choice in the step 2 advanced panel. Now: Photo / Vidéo are on step 1; the advanced panel shows formats and extension only under the « adresse » transport, and nothing media-related under FTPS. The step 2 button « Relancer le test » becomes « Relancer le test de la centrale ».

## Contracts for the build stories (not decided here)

- 18.4 builds the step 1 fields, the step 2 FTPS zone and the summaries; the FTPS test action comes from 18.7. Until it exists the FTPS zone shows its button disabled with the reason.
- The test action connects without writing and returns the presented fingerprint; the trust button stores it in `ftps_cert_fingerprint` and relaunches the FTPS test.
- The password field shows an obfuscated placeholder when a value is stored and keeps the stored value when left untouched.
- Remove `placeholder="upload"` from the hand-entry card now (done in 18.2 follow-up); no field suggests a default it does not apply.

## Open points

Two designer decisions await confirmation (Decisions taken by the designer, above), and the render itself awaits the user's approval.
