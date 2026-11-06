---
name: siaDC09 wizard step 1
status: draft
sources:
  - ../../../../internal-docs/design/wizard-design.md
  - ../../architecture-my-project/architecture-my-project.md
  - ../epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
updated: 2026-11-05
---

# siaDC09 wizard step 1 - Experience Spine

TLDR: step 1 asks for a connection and one yes/no choice (photo/video verification). Everything technical lives in a folded panel, locked by the chosen profile and unlocked only by "Personnalisé". A refusal always says why, next to the field and in one banner. Step 2 never leaves the user stuck: a failed test shows the message that was sent and a way back.

Visual rules live in `DESIGN.md`. This file wins over `wizard-design.md` on every point it covers once the build is done (the contradictions it corrects are listed in "Spec corrections").

## Foundation

| Item | Value |
|---|---|
| Surface | Jeedom desktop web, equipment page of the siaDC09 plugin. No mobile version. |
| UI system | Jeedom's Bootstrap theme and `jeedom.js` helpers; `DESIGN.md` specifies only the delta. |
| User | A non-technical person who installs their alarm monitoring from instructions given by their monitoring company. |
| Expert | The same person or an integrator using the profile "Personnalisé". Same screens, nothing locked. |
| Language | French. Plugin strings go through `{{...}}`. |
| Dependencies named to the user | Frigate (video server), the monitoring company ("centrale de télésurveillance"). |

## Information Architecture

| Surface | Reached from | Purpose |
|---|---|---|
| Step 1 - Centrale | Wizard start, "Relancer l'assistant", "← Modifier la centrale" | Connect to the monitoring center, decide on photo/video verification |
| Step 1 advanced panel | Chevron bar on step 1; opens itself on an error inside it | What the alarm sends, and supervision |
| Step 2 - Test | "Suivant" on step 1 | Check the connection with a real test message |
| Step 2 failure view | A refused or failed test | Diagnose; go back to fix; or skip |

Steps 3 and 4 are unchanged by this run, except that the step 3 media check stays as a safety net (see "Validation").

## Voice and Tone

French, vouvoiement, plain words. Technical terms only inside the folded panel. Never blame the user. Never name a profile as if it were the monitoring center.

| Moment | Text |
|---|---|
| Profile help | « Le profil règle pour vous les options de votre centrale. « Personnalisé » : vous réglez tout vous-même. » |
| Lock caption | « Fixé par le profil « {nom} ». Choisissez « Personnalisé » pour le modifier. » |
| Media checkbox | « Joindre une photo ou une vidéo à l'alarme (levée de doute) » |
| Media help | « Le télésurveilleur peut ainsi voir ce qui a déclenché l'alarme. » |
| Media checkbox, profile without media | « Cette centrale ne reçoit ni photo ni vidéo. » (checkbox greyed and unchecked) |
| Frigate field label | « Adresse de votre serveur Frigate * » |
| Frigate error | « Adresse du serveur Frigate : obligatoire quand la levée de doute est activée. » |
| Frigate hint | « Exemple : https://frigate.maison.fr » |
| Banner title | « Impossible de continuer : » |
| Account error | « Numéro de compte : 3 à 16 caractères hexadécimaux requis » |
| Address error | « Adresse IP de la centrale requise » |
| Port error | « Port : nombre entre 1 et 65535 requis » |
| AES errors | « Clé AES requise quand le chiffrement est activé » ; « Clé AES : 32, 48 ou 64 caractères hexadécimaux requis » |
| Periodic frames error | « Au moins une trame périodique est requise : activez la supervision ou le test cyclique (RP) » |
| RP interval error | « Intervalle RP : nombre entre 60 et 86400 secondes requis » |
| Media format help | « Formats possibles : Video Verification Link (V) / URL Multimedia Direct (U) » |
| Extension choice | « Quand photo ET vidéo ont le même format : ( ) une seule extension pour les deux liens [Vhttps://monsite/..../snapshot.jpg https://monsite/..../clip.mp4] ( ) une extension par lien [Vhttps://monsite/..../snapshot.jpg][Vhttps://monsite/..../clip.mp4] » |
| Supervision intro | « Votre alarme signale régulièrement à la centrale qu'elle fonctionne. » |
| Step 2 refusal (DUH) | « La centrale de télésurveillance a reçu le message de test, mais l'a refusé (DUH). » then the sent message, then « Vérifiez : - que le profil choisi correspond bien à votre centre de télésurveillance ; - que le numéro de compte ({compte}) est celui que le centre a enregistré pour vous. » then « Puis relancez le test. » |
| Step 2 no answer | « Pas de réponse de la centrale - vérifiez l'adresse IP, le port et votre réseau » (unchanged) |
| Step 2 NAK | « Connexion établie mais réponse inattendue (NAK) » (unchanged) |

The refusal text carries exactly the two suggestions above. No advice to change the supervision format, no advice to switch to "Personnalisé".

## Component Patterns

### Profile selector
Lists the profiles of `csr_presets.json` plus "Personnalisé". Choosing a profile fills **and locks** every key it declares (ADR-22): supervision format and interval, RP and its interval, and the media keys. A key a profile does not declare is left untouched. "Personnalisé" unlocks everything and keeps the current values. There is no banner announcing an expert mode.

### Photo / video verification card
| Element | Behavior |
|---|---|
| Checkbox "Joindre une photo ou une vidéo" | A **user choice**, stored in `media_enabled`. Never locked by a profile. Unchecked and greyed when the profile declares no media (see "Profiles and media"). |
| Frigate address | Shown only when the checkbox is checked. Required. Stored in `frigate_media_url_template`. |
| Summary line | Muted: « Ce qui est envoyé (photo, vidéo, format) est fixé par le profil : voir les options avancées. » In "Personnalisé": « ... se règle dans les options avancées. » |

### Contents sent with the alarm (inside the advanced panel)
| Field | In a profile | In Personnalisé |
|---|---|---|
| Photo (sent / not sent) | Locked | Editable |
| Video (sent / not sent) | Locked | Editable |
| Format of the photo link | Locked | Editable: Video Verification Link (V) / URL Multimedia Direct (U) |
| Format of the video link | Locked | Editable |
| One extension for both links / one extension per link | Locked | Editable; the one-extension choice is only offered when photo and video are both sent with the same format |

The one-extension choice is **visible** whenever the panel is open. When its condition is not met (a single content, or mixed formats), it stays visible, greyed, with the muted reason « Disponible seulement si photo et vidéo sont envoyées avec le même format. » The user never has to wonder where the option went.

### Supervision card (inside the advanced panel)
Supervision format, supervision interval, cyclic test (RP) checkbox, RP interval. Locked in a profile, editable in "Personnalisé". The orange NULL warning is removed.

### Banner and field errors
One validation function returns **all** errors at once. Each error is shown under its field (field in error) and listed in the banner. The first faulty field receives focus. If a faulty field is inside the advanced panel, the panel opens.

### Buttons
| Button | Rule |
|---|---|
| Suivant (step 1) | Always clickable in appearance unless a save is in flight. A click always produces either a move to step 2 or a visible refusal. |
| Any disabled wizard button | Looks disabled (class `disabled`, `aria-disabled`, `tabindex=-1`) and is inert. |
| Buttons disabled during an async call | Re-enabled in **every** outcome (success, error, cancelled dialog). A view that is shown again (`showStep`) resets its own buttons. |

## State Patterns

### Step 1 states
| State | Appearance |
|---|---|
| Profile chosen | Fields of the profile locked with lock-caption; media checkbox user-controlled |
| Personnalisé | No lock, no caption, no banner |
| Legacy equipment (no `csr_profile`) | Opens on Personnalisé with its saved values; absent `media_enabled` reads as **on** (previous behavior) |
| Media checked, Frigate address empty | Field in error after a click on "Suivant", banner lists it |
| Media unchecked | Frigate field hidden; its value is kept in the form, not erased |
| Refusal | Banner above the buttons, field in error, focus on the first faulty field |
| Saving | "Suivant" shows a spinner and ignores further clicks; back to normal on any outcome |

### Step 2 states
| State | Appearance | Buttons |
|---|---|---|
| Testing | Spinner « Test en cours... » | « ← Modifier la centrale » available; « Relancer le test », « Ignorer » and « Suivant » inert |
| Success (ACK) | Green banner « Connexion établie - ACK reçu » | Suivant enabled |
| NAK | Orange banner, confirm before continuing (unchanged) | Suivant enabled |
| Refusal (DUH) | Red banner with the sent message and the two checks | Modifier la centrale, Relancer, Ignorer enabled; Suivant disabled and grey |
| No answer / error | Red banner (unchanged texts) | Same as DUH |

## Interaction Primitives

- Choosing a profile applies it immediately; the panel does not open by itself unless it holds an error.
- Folding or unfolding the advanced panel never loses a value.
- « ← Modifier la centrale » goes back to step 1 with every value kept, saves nothing new, and resets the wizard step so that step 1 buttons are live. A late answer of a test the user left is ignored.
- « Relancer l'assistant » (from config mode or step 2 flow) stops the daemon first, then shows step 1 with buttons reset.
- The step 1 « Suivant » and « Relancer l'assistant » ask for confirmation when the daemon runs, and **really stop it** when the user confirms.

## Accessibility Floor

- Every field has a visible label. An error is announced: the banner has `role="alert"`; each field in error references its message with `aria-describedby`.
- A locked field exposes its state (`readonly` or `aria-disabled="true"`), and the caption is associated with it.
- Meaning never relies on color alone: errors carry an icon and text, locks carry a caption.
- Everything is reachable and operable by keyboard; disabled links leave the tab order.
- Text keeps the contrast of the Jeedom theme; locked fields stay readable at opacity 0.6 (their text is not conveyed by color only).

## Validation

The step 1 rules, evaluated together on "Suivant". The JS twin of the PHP checks keeps the same wording.

| Rule | Source |
|---|---|
| Account 3 to 16 hex characters | wizard-design.md |
| IP not empty | wizard-design.md |
| Port 1 to 65535 | wizard-design.md |
| AES key present, 32/48/64 hex when encryption is on | wizard-design.md |
| Supervision `none` with RP off refused; RP interval 60 to 86400 when RP on | ADR-22 (`periodicFrameConfigError`) |
| **New:** Frigate address not empty when `media_enabled` is on | this run, correction of bug B2 |

The step 3 check on an empty Frigate address stays as a safety net for equipment saved outside the wizard. The same rule is also enforced server-side when starting the daemon (existing "deferred" item to be scheduled).

## Profiles and media

| Profile | Media keys in `csr_presets.json` | Checkbox |
|---|---|---|
| Vesta (Climax) | U, snapshot + clip, one extension | Available, on by default |
| FoxStream (FoxBox) | V, snapshot + clip, one extension | Available, on by default |
| Scutum | to add: **video only, format V** (`media_snapshot_enabled` 0, `media_clip_enabled` 1, both formats V), flagged "à tester" | Available, **off by default** |
| Ajax | none | Greyed: « Cette centrale ne reçoit ni photo ni vidéo. » (decided: only Scutum is authorized) |
| Personnalisé | n/a | Available; contents and formats editable |

A profile enables the checkbox by **declaring** its media keys. A profile that declares none keeps it greyed.

## Key Flows

### 1. Marc installs his monitoring (FoxStream)
1. Marc, 58, opens the plugin with the instructions from his monitoring company in hand.
2. He picks « FoxStream (FoxBox) ». The advanced options fill and lock; the caption says why.
3. He types the IP, the port, the account number.
4. The card « Levée de doute photo / vidéo » shows the box checked. He types his Frigate address.
5. He clicks « Suivant ». The daemon is stopped if it ran; the settings are saved; the test starts.
6. **Climax:** the banner turns green, « Suivant » lights up.

### 2. The monitoring center refuses (DUH)
1. At step 2 the banner is red: the center received the test message and refused it.
2. Marc sees the exact message sent and the two checks. He calls his provider: wrong profile.
3. He clicks « ← Modifier la centrale ».
4. **Climax:** step 1 is back with all his values and a live « Suivant ». He picks the right profile and goes on.

### 3. Forgotten Frigate address
1. Marc leaves the box checked and the Frigate field empty, then clicks « Suivant ».
2. **Climax:** the field turns red with its message, the banner says « Impossible de continuer », the focus lands on the field. Nothing is saved, nothing is silent.

### 4. An integrator tunes a custom setup
1. He picks « Personnalisé ». Nothing is locked, there is no caption.
2. He opens the advanced options, sets the formats and chooses one extension per link.
3. **Climax:** he sees the real shape of the extensions in the examples before saving.

### 5. Marc relaunches the assistant
1. From step 2, Marc clicks « Relancer l'assistant ». The daemon is stopped for real.
2. **Climax:** step 1 appears and « Suivant » works on the first click (bug B1 would have made it inert).

## Spec corrections

| `wizard-design.md` / ticket text | Correction |
|---|---|
| 17.7: media options are « not profile fields » | They are profile-declared keys, locked by the profile (ADR-22). Only `media_enabled` and the Frigate address are user choices. |
| 17.8: media « filled but not locked » | Filled **and locked**. |
| Step 1 field table | Adds the card « Levée de doute photo / vidéo »; the media block leaves the advanced panel's top level. |
| « stepper non-clickable » with no way back from step 2 | « ← Modifier la centrale » added. |
| « Relancer l'assistant » sets step 0 then calls `deamon_stop()` | Stop actually called by the JS (today the dialog promises it and nothing runs: bug B3). |
| Null warning `#siaDC09-null-warning` | Removed. |
| Step 3 owns the empty-URL check | Step 1 owns it; step 3 is a safety net. |

## Build contracts (for the stories, not for the UI)

| Item | Detail |
|---|---|
| New key | `media_enabled` (0/1); absent = 1; 0 means PHP sends no media to the daemon. |
| Presets | Add media keys to `scutum`: video only, format V (to test). `ajax` unchanged. |
| `testConnection` | Returns the sent frame and its decoded summary (type, account, transport) so the refusal view can show them. Today the frame only reaches the log through stderr. |
| Logging | An expected DUH is logged at WARNING, not ERROR. |
| Tests | jsdom scenario: click « Suivant », save succeeds, relaunch, click again must validate; step 2 « Modifier la centrale »; `showStep` resets buttons; a banner with every error at once. |

## Open items

| Item | Status |
|---|---|
| Ajax keeps the checkbox greyed | Confirmed by Herve 2026-11-05 |
| Scutum off by default, video only in V | Confirmed 2026-11-05, to test |
| A Frigate address is only checked for being non-empty | Confirmed 2026-11-05. A URL containing `]` or `|` would break a frame (known risk in the design docs); a format check stays a future option |
| « ← Modifier la centrale » stays available during a running test | Confirmed 2026-11-05; the late answer is discarded |

Status stays `draft` until Herve has read both spines in full.
