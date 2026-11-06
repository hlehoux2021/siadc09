---
name: siaDC09 wizard step 1
description: Visual delta for the siaDC09 wizard (step 1 and the step 2 failure view) on top of the stock Jeedom desktop Bootstrap theme. No new palette, no new typeface.
status: draft
sources:
  - ../../../../internal-docs/design/wizard-design.md
  - ../../architecture-my-project/architecture-my-project.md
  - ../epic-17-csr-behaviour-profiles.md
updated: 2026-11-05
components:
  section-card:
    note: Bootstrap panel (well). Title in a heading level 4, no icon. One card per topic.
  field-locked:
    note: Existing .siaDC09-locked look, kept - input readonly or select without pointer events, opacity 0.6, grey fill. Always paired with lock-caption.
  lock-caption:
    note: Small muted text under the section, "Fixé par le profil « <nom du profil> »". Muted text class, 12-13px.
  field-error:
    note: Bootstrap has-error on the form group, red border 2px, message in help-block directly under the field.
  banner-error:
    note: Bootstrap alert-danger, full card width, above the Suivant button. Heading line plus one bullet per error.
  banner-test-failure:
    note: Bootstrap alert-danger on step 2, contains the sent-message box and the "Vérifiez" list.
  sent-message-box:
    note: Monospace, grey fill, selectable text, one line for the raw frame and one muted line for its decoded summary.
  button-primary:
    note: Existing btn btn-success "Suivant" (green, as in the current wizard).
  button-disabled:
    note: Same button with class disabled AND aria-disabled=true AND tabindex=-1. Must look disabled (grey, no hover), never only the attribute.
  button-secondary:
    note: btn btn-default, used for "Modifier la centrale", "Relancer le test", "Ignorer".
  expander-advanced:
    note: Existing "Options avancées" toggle, full-width dashed bar with a chevron (right when folded, down when open).
---

# siaDC09 wizard step 1 - Design Spine

TLDR: the wizard keeps the stock Jeedom look. What changes is **structure**: three clearly separated cards on step 1, one folded expert panel, locked fields that explain themselves, and errors that always show next to the faulty field and in one banner.

## Brand & Style

The wizard is a page of Jeedom's equipment configuration, used by someone who installs an alarm monitoring, not by an engineer. It must look like Jeedom, not like a new product. No palette, no typeface and no icon set is introduced. Everything below is hierarchy and grouping.

## Colors

No new color. Meaning only comes from Bootstrap semantic classes already used by Jeedom:

| Meaning | Where | Class |
|---|---|---|
| Action to take | "Suivant" | success (green), as today |
| Refused / error | field in error, banner, test refusal | danger (red) |
| Locked by a profile | locked fields | grey fill plus muted text, never red or orange |
| Neutral secondary action | "Modifier la centrale", "Relancer le test", "Ignorer" | default |

Orange (warning) is **not used** on step 1: the former NULL warning is removed, because the cause of a refusal is not known to be specific to the NULL format.

## Typography

Inherits the Jeedom body font. Two rules only: card titles use the heading level used by the other Jeedom config pages, and the sent test message (step 2) uses the monospace stack so that it can be read out to a monitoring operator character by character.

## Layout & Spacing

Step 1 is one column, in this order, each in its own card with the standard Bootstrap panel spacing:

| Order | Card | Always visible content |
|---|---|---|
| 1 | Votre centrale de télésurveillance | Profil, adresse IP, port, transport, numéro de compte, chiffrement (clé AES when checked) |
| 2 | Levée de doute photo / vidéo | One checkbox; when checked, the Frigate server address |
| 3 | Options avancées (folded) | Contents sent with the alarm, then Supervision de la liaison |

Under the cards, in this order: error banner (only after a refusal), then the button row with "Suivant" aligned right. Related fields share a row (adresse, port, transport on one line; photo and vidéo formats on one line). A label sits above its field. Help text is muted and sits under the field it explains, never in a tooltip.

Inside the folded panel, two sub-sections, each introduced by a heading and one plain sentence:

- **Contenu envoyé avec l'alarme (photo / vidéo)** - what the alarm sends and how.
- **Supervision de la liaison** - "Votre alarme signale régulièrement à la centrale qu'elle fonctionne."

## Shapes

Stock Bootstrap radii. No custom shape.

## Components

| Component | Visual rules |
|---|---|
| section-card | One topic per card. Title only; no decoration. |
| field-locked | Used in a profile. Grey, not editable, still readable and selectable. The profile's lock-caption is shown once per card or sub-section, not per field. |
| lock-caption | Text: « Fixé par le profil « {nom} ». Choisissez « Personnalisé » pour le modifier. » In the Personnalisé profile there is no caption and no locked look. |
| field-error | Red border and message under the field. The message names the field and says what is wanted. |
| banner-error | Title "Impossible de continuer :" then one line per error, same wording as under the fields. |
| button-disabled | Grey and inert-looking. Applies to every wizard button that is disabled, not only "Suivant". |
| sent-message-box | Shown only in a step 2 refusal or failure: the raw frame, and a muted line "Type : … Compte : … Transport : …". |
| expander-advanced | Folds by default. Opens by itself when it contains an error. The user may fold it again. |

## Do's and Don'ts

| Do | Don't |
|---|---|
| Show locked values: the user has the right to read them | Hide a technical setting because it looks technical |
| Pair every lock with a caption that says why | Grey a field with no explanation |
| Make a disabled button look disabled | Rely on the `disabled` attribute alone on a link |
| Put the error next to the field and in the banner | Fail silently, or only in the browser console |
| Use the official labels "Video Verification Link" and "URL Multimedia Direct" | Show a bare letter "U" or "V" as the only label |
| Keep technical words inside the folded panel | Put protocol vocabulary on the first screen |
| Say "la centrale de télésurveillance" for the real CSR | Use a profile name (FoxStream, Vesta...) as if it named the monitoring center |
