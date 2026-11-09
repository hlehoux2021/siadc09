---
name: siaDC09 wizard media block (FTPS)
description: Visual delta on the epic 17 wizard for the verification-media block when the way the media reaches the receiver is a choice (address in the frame, or FTPS upload). Same Jeedom Bootstrap theme, no new palette.
status: approved
sources:
  - ../../epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/DESIGN.md
  - ../../../../internal-docs/design/wizard-design.md
  - ../epic-18-ftps-alarm-media-upload.md
updated: 2026-11-09
components:
  media-choice:
    note: "Que joindre ?" with two checkboxes (Photo, Vidéo) on one row, at least one required. Locked look and one caption when the profile declares them.
  transport-choice:
    note: Two radios under the media choice, one label line and one muted sentence each. Exactly one selected; "adresse" is the default.
  transport-subcard:
    note: Dashed-border inner card, white fill, 18px title. Only the card of the selected transport exists in the page; the other is hidden, never greyed.
  cert-choice:
    note: Two radios, "Certificat reconnu" and "Certificat auto-signé". The fingerprint field appears under the second one only.
  test-zone:
    note: Step 2 framed zone titled "Test de la centrale (SIA)" or "Test du serveur FTPS", holding a Bootstrap alert and its own relaunch button.
  fingerprint-box:
    note: Monospace, grey fill #e9ecef, selectable, inside the danger alert; followed by a btn-default "Faire confiance à cette empreinte".
---

# siaDC09 wizard media block - Design Spine

TLDR: step 1 keeps one media card with a common part (what to attach, how it reaches the receiver) and, for the address way only, the Frigate address. Every technical setting lives on step 2, in the Options avancées panel. The FTPS test moves to step 2 as a second result zone beside the SIA test; one button, « Lancer le test » / « Relancer le test », runs every test and nothing runs by itself. The step 2 advanced panel shows only what the chosen way needs. Nothing new in colour, type or shape. The Excalidraw mockup (`.working/`, screens A to H) wins over this text where they differ.

## Colors

No new colour. Bootstrap semantic classes as in epic 17: green for success and the primary button, red for any refusal (a test failure and a certificate refusal alike), grey for locked, blue-grey info only for a neutral note. **No orange**: an unknown or changed certificate is a refusal. Colours come from the Jeedom theme variables and Bootstrap classes, never hard-coded, so the block reads in Dark and Light (story 17.14 lesson).

## Layout & Spacing

| Screen | Content |
|---|---|
| A, step 1, « adresse » | Zone « Levée de doute photo / vidéo »: media checkbox + help, « Que joindre ? » (Photo, Vidéo), transport radios, then the card « Adresse pour la centrale » with the Frigate address. No FTPS field. |
| B, step 1, FTPS | Same common part, the FTPS radio selected, and nothing else but a note: the FTPS settings are on the next step. No Frigate address, no FTPS field, no test. |
| C, step 2, FTPS, first arrival | Summary (two lines), zone « Test de la centrale (SIA) » and zone « Test du serveur FTPS » both « Pas encore testé. », the Options avancées bar open, the dashed card « Serveur FTPS » (server + port, user + password, remote folder empty, certificate radios + fingerprint), the locked supervision zone, then one button row: Modifier la centrale / Lancer le test / Ignorer. |
| C1, step 2, FTPS, after the test | Unknown certificate refusal with the fingerprint box and « Faire confiance à cette empreinte » (no button of its own for a test); advanced panel folded; row: Modifier la centrale / Relancer le test / Ignorer. |
| C2, FTPS test results | Running, success, step failure, identifiers refused, changed certificate. Texts only, no button. |
| D, step 1 refusal | Red borders and messages under the faulty fields (Photo / Vidéo, Frigate address), one « Impossible de continuer : » banner. |
| D2, step 2 refusal | « Lancer le test » pressed with incomplete FTPS settings: nothing runs, red fields in the card, banner « Impossible de lancer le test : ». |
| H, step 2 buttons | The five states of the button row (before test, running, all passed, failed, settings edited). One test button, one right-hand slot (Suivant or Ignorer, never both). |
| E, advanced, « adresse » | Photo / Vidéo address formats, extension choice, supervision. Locked by the profile as in epic 17. |
| G, « Configuration active » | New « Levée de doute » block, never showing the password. |

Labels sit above fields. Help is muted text under the field, never a tooltip. A field that has no default shows no placeholder pretending to be one.

## Components

See the front matter. Reused unchanged from epic 17: section-card, field-locked and its lock caption, field-error, banner-error, button-primary, button-disabled, button-secondary, expander-advanced.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Show only the card of the selected way | Show greyed fields of the other way |
| Keep one test button for every test, and one right-hand button (Suivant after full success, Ignorer otherwise) | Put a relaunch button in each result zone, or show Suivant and Ignorer together |
| Name the failed step in a test failure | Show a bare « Échec » or an error code |
| Show the presented certificate fingerprint in monospace | Ask the user to find it with a command-line tool |
| Say the password was not sent when a certificate is refused | Imply the credentials were tried |
| Keep Photo / Vidéo on step 1 only | Repeat the switches in the advanced panel |
| Leave an optional field empty | Put a grey example that the plugin does not apply |
| **Frame what the profile sets** (Photo, Vidéo, transport) in ONE dashed group « Contenu et mode d'envoi », like the step 2 zones: grey with the single caption inside when the profile fixes it, white when free | Mix locked and editable controls in one undivided zone (user review of 18.4, 2026-11-09) |
| Keep the always-editable controls outside that frame: the « Joindre… » checkbox above it, the « Adresse pour la centrale » card below it | Put an editable field inside the profile-set group |
