# Config Wizard Design — Jeedom siaDC09 Plugin

**Version:** 0.4
**Date:** 2026-11-06
**Status (story 17.14):** three steps (Centrale / Test + Options avancées / Zones et alertes), layout from the Excalidraw mockup. The "Task breakdown" and "Testing strategy" sections below still name the former four steps (historical); the sections above are current. Earlier: Step 1 rewritten for CSR profiles and periodic-frame options (Story 17.4, ADR-22); daemon stop moved to the JS (Story 17.9)

---

## Overview

The wizard is the **equipment configuration page** (`desktop/php/siaDC09.php`). It guides
the user through 3 steps the first time (story 17.14), then switches to a standard flat config layout once
complete. It is the only configuration interface for the plugin — there is no separate
"wizard page".

**Entry point:** Plugins > Sécurité > Télésurveillance SIA DC-09 → click the
"Télésurveillance" equipment card on the left.

---

## Two display modes

The page has two modes, selected by checking `sia_wizard_step` on load:

| Condition | Mode displayed |
|---|---|
| `sia_wizard_step < 4` (0 = never started) | **Wizard mode** — stepped UI, one section at a time |
| `sia_wizard_step == 4` | **Config mode** — standard Jeedom flat equipment layout |

### Canonical Wizard Step Map

Story 17.14 reduced the wizard to three steps. `sia_wizard_step` holds the step being shown;
`4` stays the "wizard complete" value (JS constant `SIADC09_WIZARD_DONE`, PHP launch guard `< 4`),
written only by « Terminer ». No stored value is migrated (test phase).

| `sia_wizard_step` | Meaning |
|---|---|
| `0` | Not started |
| `1` | Step 1 shown (Centrale + photo/video verification) |
| `2` | Step 2 shown (Test + Options avancées) |
| `3` | Step 3 shown (Zones et alertes) |
| `4` | Configuration mode (wizard complete) |

> **Browser-refresh safety:** on every "Next" click, saving `sia_wizard_step` must be the
> **first statement** before any other side effect (AJAX call, subprocess launch, etc.).
> This ensures the wizard resumes at the correct step if the browser is refreshed mid-flow.

A **"Relancer l'assistant"** button is always visible in the equipment config header,
regardless of mode. It resets the wizard to step 1 with the currently saved values
(never clears config).

If the daemon is running when the user clicks "Relancer l'assistant", a confirmation
dialog is shown:
> "Le démon est en cours d'exécution. L'assistant de connexion requiert que le démon
> soit arrêté. Voulez-vous l'arrêter maintenant ?"

The stop is done by the JS (story 17.9), shared by "Relancer l'assistant" and step 1
"Suivant" (`siaDC09_confirmStopDaemon`). The probe is `jeedom.plugin.getDeamonInfo` (core has
no `deamonInfo` action; a failed probe counts as "not running"). On confirm: the JS sets
`sia_wizard_step` (0 for the restart, 2 for "Suivant") and saves the eqLogic **first**
(step < 4 makes `launchable='nok'`, so the watchdog cannot auto-restart the daemon), then calls
`jeedom.plugin.deamonStop`, then shows step 1 (or 2) in-page, without reloading.
If the save fails, no stop is called (the daemon keeps running with valid config). If the stop
fails, an alert is shown and the button is re-enabled. A cancelled dialog saves and stops
nothing and re-enables the button. If the daemon is not running, the same sequence runs
without the dialog and without the stop.

---

## Wizard steps

| Step | Tab | What the user configures |
|---|---|---|
| 1 | Centrale | Profile, CSR address, account, encryption; photo/video verification (Frigate address) |
| 2 | Test | Live connection test to the CSR; Options avancées (content sent, supervision), unlocked by « Personnalisé » |
| 3 | Zones et alertes | Zone → camera mapping and user number; Jeedom command to call on critical errors; « Terminer » |

Progress is shown by a three-tab stepper at the top of the wizard (`#siaDC09-stepper`, non-clickable,
read-only, the active tab follows `siaDC09_showStep()`).

**Layout (story 17.14).** The layout source of truth is the Excalidraw mockup
`_bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/ux-17-wizard-step-1/.working/flow-wizard-step-1-2026-11-05.excalidraw`
(screens A to D); it wins over DESIGN.md text where they differ. Styles live in `desktop/css/siaDC09.css`:
one framed zone (`.siaDC09-zone`, fill #f8f9fa) per topic with its title, the label above its field,
related fields on one row (`.siaDC09-row`), one lock caption per locked panel, and the Options avancées
dashed bar (`.siaDC09-advbar`) above its content. Jeedom forces a grey `a:hover` color
(`--linkHover-color`), unreadable in the Light theme: the plugin CSS overrides link and button hover
colors with id selectors.

---

## Step 1 — Centrale de télésurveillance

### Profile selection

A `csr_profile` select (`data-l2key="csr_profile"`) offers the profiles of
`core/config/csr_presets.json` (Ajax, Vesta, FoxStream; Scutum was retired, see "Retired profile: Scutum") plus **Personnalisé** (empty value). The options
are built server-side from `siaDC09::getCsrProfiles()`, and the same array is handed to JS with
`sendVarToJS('siaDC09_csrProfiles', ...)`. Profile names stay PHP/JS-side (ADR-22): the daemon
only receives the resolved values through `deamon_start()`.

- A profile fills the **advanced fields** from its preset and locks them. A preset that omits a key
  (e.g. `supervision_interval`) leaves that field untouched.
- **Personnalisé** unlocks the fields and keeps the current values.
- Equipment saved before this step existed has no `csr_profile`: it opens on Personnalisé, shows
  its current values, unlocked. Absent `supervision_format` shows `sia-dcs` and absent
  `rp_interval` shows 60 (the daemon-side defaults).

### Fields

All fields are always rendered and bound via `data-l2key`.

| Field | HTML binding | Notes |
|---|---|---|
| Profil de la centrale | `csr_profile` | '' = Personnalisé |
| Adresse IP | `csr_ip` | |
| Port | `csr_port` | 1–65535 |
| Transport | `transport` | udp / tcp |
| Numéro de compte | `account_number` | 3–16 hex chars |
| Chiffrer les échanges / Clé AES | `encryption_enabled` / `encryption_key` | 32, 48 or 64 hex chars; the key field shows only while the box is checked |

Step 1 holds two framed zones: « Votre centrale de télésurveillance » and « Levée de doute photo / vidéo »
(`media_enabled`, Frigate address). The profile help sits to the right of the select. No Options avancées bar
on step 1; its summary line points to the Test step.

**Options avancées** now live on step 2 (Test): a dashed bar `#bt_siaDC09_toggleAdvanced` (folded: « Options
avancées : contenu envoyé, supervision de la liaison » plus a muted hint; open: « Options avancées (cliquer
pour replier) ») with the panel `#siaDC09-advanced` BELOW it (user decision 2026-11-06, not as screen B first
drew it). The supervision fields below carry the class `siaDC09-profile-field` and are the ones a profile locks:

| Field | HTML binding | Notes |
|---|---|---|
| Message de vie (trame de supervision) | `supervision_format` | none / sia-dcs / null |
| Toutes les (secondes) | `supervision_interval` | |
| Test cyclique (RP) | `rp_enabled` | checkbox |
| Toutes les (secondes) | `rp_interval` | 60–86400 |
| Tentatives de reconnexion | `retry_count` | reconnection attempts; not a profile field |
| Délai de reconnexion (s) | `reconnect_delay` | not a profile field |

> **Locking:** `disabled` controls may be skipped by Jeedom's `getValues()` serialisation, so
> inputs use `readonly`; selects, checkboxes and radios use `pointer-events:none`, `tabindex=-1` and `aria-disabled="true"`.
> All locked fields are therefore still saved.

**Story 17.11 rework of the advanced panel.** `#siaDC09-advanced` has two sub-sections, each with a heading:

- **Contenu envoyé avec l'alarme (photo / vidéo)**: photo and video (`media_snapshot_enabled`, `media_clip_enabled`) each with a format select labelled « Video Verification Link (V) » / « URL Multimedia Direct (U) » (stored values stay `V` / `U`), then the extension choice. `media_single_tag` stays the saved key (a hidden checkbox); two radios (`.siaDC09-ext-radio`) drive it: « une seule extension pour les deux liens » (`[Vhttps://monsite/..../snapshot.jpg https://monsite/..../clip.mp4]`, a space between URLs) and « une extension par lien » (`[V…snapshot.jpg][V…clip.mp4]`), with the letter of the current format. These examples are the bytes of `SIAMessageBuilder._format_media_tags`. The choice is always visible; when photo and video are not both sent with the same format it is greyed, unselected, with the reason « Disponible seulement si photo et vidéo sont envoyées avec le même format. » (`#siaDC09-media-single-tag-help`).
- **Supervision de la liaison**: intro « Votre alarme signale régulièrement à la centrale qu'elle fonctionne. », then supervision format and interval, RP and RP interval.

A profile locks the fields it declares; locked fields stay visible and readable (grey fill #e9ecef, grey border and text, set by `.siaDC09-locked` / `.siaDC09-field-locked`) and expose `readonly` (text/number inputs) or `aria-disabled="true"` (others). ONE caption for the whole panel (`#siaDC09-lock-caption`, top of the panel): « Fixé par le profil « {nom} ». Choisissez « Personnalisé » pour le modifier. », followed by the action « Passer en Personnalisé » (`#bt_siaDC09_goCustom`). In Personnalisé there is no caption and nothing is locked. A profile that declares no media key (Ajax) leaves the content fields editable (decision 2026-11-06). Folding the panel never changes a value.

**Personnalisé from the Test step (story 17.14).** « Passer en Personnalisé » sets the profile select to Personnalisé and fires the same `change` handler as choosing it on step 1: fields unlock, values are kept, no preset is modified. The test does NOT rerun by itself (user decision): only « Relancer le test » validates the advanced options (`siaDC09_validateAdvanced()`, errors in `#siaDC09-step2-errors`, panel opens), saves the form (the test reads the saved config) and reruns the test.

The orange NULL warning (`#siaDC09-null-warning`) is removed: the cause of a refusal is not known to be specific to the NULL format.

### Validation before "Suivant"

- `account_number` non-empty, 3–16 hex chars
- If `encryption_enabled`: `encryption_key` non-empty, 32, 48 or 64 hex chars
- `csr_ip` non-empty; `csr_port` numeric, 1–65535
- Media on: Frigate address non-empty

Errors go to `#siaDC09-step1-errors`; no advance when validation fails. The two periodic-frame rules
(supervision `none` with RP off refused; RP on with a period outside 60–86400 s refused) moved to the Test
step (`siaDC09_validateAdvanced()`, run before every test); they are the JS twin of
`siaDC09::periodicFrameConfigError()`.

### Data flow

eqLogic config is the single source of truth. The profile fills the form; the standard Jeedom save
writes the resolved values (and `csr_profile`, used only to restore the selector) to eqLogic.
`csr_presets.json` is read PHP-side only, never by the daemon.

### On "Suivant"

Validation, then `sia_wizard_step = 2` and a save, then the wizard advances to step 2.

---

## Step 2 — Test de connexion

### Layout

```
+-----------------------------------------------------------+
|  Connexion à tester :                                     |
|  CSR : xxx.xxx.xxx.xxx:5000  (UDP)  Chiffrement : activé  |
+-----------------------------------------------------------+
|                                                           |
|   [spinner]  Test en cours...                             |
|                                                           |
+-----------------------------------------------------------+
|  [> Options avancées : contenu envoyé, supervision]       |
+-----------------------------------------------------------+
|  [← Modifier la centrale] [Relancer le test] [Ignorer] [Suivant →] |
+-----------------------------------------------------------+
```

Order on the page: summary, result, Options avancées bar (and panel), buttons. Screen C of the mockup is
the failed state; screen B the unfolded panel. « Suivant » is `btn-success`; when inert it is grey and dashed.

The CSR summary is computed from the saved config (read-only display, not input fields).

### Auto-trigger

The test fires **automatically** on arriving at step 2, without any user action. The spinner
and "Test en cours..." message appear immediately.

### `test_connection.py` exit contract

```
exit 0  →  stdout: "success"
exit 1  →  stdout: "failure"  or  "timeout"
```

No free-form stderr is surfaced to PHP. `set_time_limit(30)` must precede the `exec()`
call. The subprocess may use `asyncio.run()` internally — "synchronous" means PHP `exec()`
blocks; the subprocess is free to use any Python async pattern.

### Result display

| Subprocess output | UI |
|---|---|
| exit 0, stdout `"success"` | Green banner: "Connexion établie — ACK reçu" |
| exit 0, stdout `"failure"` | Orange banner: "Connexion établie mais réponse inattendue (NAK)" |
| exit 1, stdout `"timeout"` | Red banner: "Pas de réponse de la centrale — vérifiez l'adresse IP, le port et votre réseau" |
| exit 1, stdout `"failure"` | Red banner: "Connexion échouée — vérifiez l'adresse IP, le port et votre réseau" |
| Subprocess error (non-zero + unexpected output) | Red banner: "Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés" |

**Failure view (Story 17.12, EXPERIENCE.md "Step 2 states").** Every red result also shows the message
that was sent (`sent`: type, account, transport). A DUH (`outcome: "duh"`) reads: « La centrale de
télésurveillance a reçu le message de test, mais l'a refusé (DUH). », the sent message, « Vérifiez : - que
le profil choisi correspond bien à votre centre de télésurveillance ; - que le numéro de compte ({compte})
est celui que le centre a enregistré pour vous. », « Puis relancez le test. » Exactly these two checks: the
profile is never named as if it were the center, and there is no advice to change the supervision format or
to switch to « Personnalisé » (a profile locks those settings).

> The "exit contract" above predates the JSON verdict: `--test-only` prints a JSON verdict on stdout; its
> stderr (plaintext frame, technical cause) is relayed to the plugin log by PHP.

### Button behavior

| Button | Behavior |
|---|---|
| "← Modifier la centrale" | Returns to step 1 with every value kept, saves nothing, and resets step 1 buttons (`showStep(1)`). Live in every step 2 state, including while the test runs: the run is abandoned and its late answer is ignored (run token). Replaces "stepper non-clickable, no way back". |
| "Relancer le test" | Validates the advanced options, saves the form, then re-triggers the auto-test flow. The only way to start a new test after the first (switching to Personnalisé never reruns it). |
| "Ignorer" | Advances to step 3 WITHOUT testing; shows an inline warning: "Connexion non testée — le plugin ne pourra pas transmettre d'alarmes si la connexion échoue." |
| "Suivant →" | Only available after exit 0 (`"success"` or `"failure"`/NAK). Blocked (greyed) if test is pending or timed out (exit 1 `"timeout"`). Advances to step 3. If the last result was `"failure"` (NAK), a confirmation dialog is shown before advancing. |

### testConnection flow (Option A — standalone subprocess)

The production daemon **must be stopped** before the connection test runs. "Relancer
l'assistant" guarantees this (see above). The test is performed by spawning a short-lived
Python subprocess in `--test-only` mode — it connects to the CSR, sends one NULL
supervision frame, captures the response, writes JSON to stdout, then exits.

```
JS                     PHP (ajax.php)              Subprocess (--test-only)   CSR
|                           |                          |                        |
|-- testConnection -------->|                          |                        |
|                           |-- python3 siadc09d.py -->|                        |
|                           |     --test-only          |-- NULL frame --------->|
|                           |                          |<--- ACK/NAK/timeout ---|
|                           |<-- JSON (stdout) --------|                        |
|<-- {status, detail} ------|                          |                        |
```

- PHP uses `exec()` to spawn the subprocess synchronously (blocks until subprocess exits)
- Subprocess timeout: **15 seconds** (configured via `--timeout` argument)
- AJAX call returns a single response — no polling required
- The subprocess reads CSR config from the eqLogic config JSON passed as `--config`

**Preconditions enforced by the wizard:**
- The daemon must be stopped (guaranteed by the JS stop sequence of "Relancer l'assistant" and step 1 "Suivant")
- Step 1 must have been saved before reaching step 2 (config available on disk)

---

## Step 3 — Zones et alertes (zone 1: Vos zones d'alarme)

Story 17.14 merged the former steps 3 and 4 into one page with two framed zones and one « Terminer » button (`#bt_step3Finish`). « Terminer » checks the Frigate address and the notification target, serialises the zone table, writes `sia_wizard_step = 4` and reloads into config mode. There is no « Suivant » on this step and no `#siaDC09-step4` element.

### Zone source

Zones are loaded exclusively from the **Jeedom alarm plugin** via `getZones` AJAX call.
The call reads the alarm eqLogic configuration (`getConfiguration('zones', [])`) and
returns the zone names.

If the alarm plugin is not found or returns no zones, the wizard shows the canonical
helper message — it never crashes or silently skips:

```
+-----------------------------------------------------------+
|  [!] Aucune zone détectée — configurez d'abord votre     |
|  plugin alarme.                                           |
+-----------------------------------------------------------+
```

The "Suivant" button is still available — the user can proceed with an empty mapping.

### Table layout

Zones are loaded as read-only rows. The user cannot add or remove rows.

```
+-----+--------------------+----------------------------------+----------------------------------+
| N°  | Zone d'alarme      | Action caméra  (optionnel)       | URL média  (optionnel)           |
+-----+--------------------+----------------------------------+----------------------------------+
|  1  | Salon              | [Caméra Salon > Snapshot      ▼] | [Caméra Salon > URL flux      ▼] |
|  2  | Chambre parents    | [(aucune)                     ▼] | [(aucune)                     ▼] |
|  3  | Entrée             | [Caméra Entrée > Snapshot     ▼] | [(aucune)                     ▼] |
|  4  | Garage             | [(aucune)                     ▼] | [(aucune)                     ▼] |
+-----+--------------------+----------------------------------+----------------------------------+
```

- **N°**: read-only `<td>`, the zone's **order number** — its 1-based position in the list
  returned by `getZones`, i.e. the order the user sees in the alarm plugin. This is the
  number transmitted to the CSR (see "Zone number in the SIA frame" below). It is
  displayed so the user can tell the CSR which physical zone each number designates.
- **Zone d'alarme**: read-only `<td>`, text from alarm plugin
- **Action caméra**: `<select>` populated with commands of generic type `CAMERA_TAKE`.
  First option: `(aucune)` (value `""`). Other options: `Caméra Salon > Snapshot` etc.
- **URL média**: `<select>` populated with commands of generic type `CAMERA_URL`.
  First option: `(aucune)` (value `""`).

Both dropdowns are populated by a **single** `getCameraCommands` AJAX call that returns
two lists (CAMERA_TAKE commands + CAMERA_URL commands) in one round trip.

### `sia_zone_mappings` storage

The mapping is stored as a JSON array in the `sia_zone_mappings` config key:
`$this->getConfiguration('sia_zone_mappings', [])`.

```json
[
  {"zone_number": 1, "zone_name": "Salon",           "camera_action_cmd_id": 42,   "media_url_cmd_id": 43},
  {"zone_number": 2, "zone_name": "Chambre parents", "camera_action_cmd_id": null,  "media_url_cmd_id": null},
  {"zone_number": 3, "zone_name": "Entrée",          "camera_action_cmd_id": 44,   "media_url_cmd_id": null},
  {"zone_number": 4, "zone_name": "Garage",          "camera_action_cmd_id": null,  "media_url_cmd_id": null}
]
```

`zone_number` is **persisted**, not recomputed at send time: the alarm plugin can reorder
or delete zones, and a number already declared to the CSR must not silently shift to a
different physical zone. On save, rows keep the number they were displayed with; a zone
seen for the first time takes `max(existing) + 1`, so numbers are stable and never reused.
Legacy configurations written before this evolution have no `zone_number` — they are
renumbered by table position the first time step 3 is saved.

### Zone number in the SIA frame

What the alarm plugin passes in the action's *Titre* is the zone **label** (`#zone#` →
`$zone['name']`), never a number — the alarm plugin's zone model is
`{name, actions, actionsImmediate, triggers}`, it has no identifier at all. So the label is
resolved against this table:

| Case | Frame |
|------|-------|
| Label matches a `zone_name` (case-insensitive, trimmed) | `[#001234|Nri1/BA001]` — the matched `zone_number`, zero-padded to 3 digits |
| No match, or empty title | `[#001234|Nri1/BA]` — **no zone field at all**, plus a warning in the log |

The label is never transmitted. Rationale: a CSR indexes incidents by zone number; a free
text label is not actionable for an operator and is not what the DC-09 Annex B examples
show (`[#1234|NFA129]`, Contact ID `[#1234|1130 02 065]` — hence the 3-digit padding).

The label is still carried in the IPC payload and stays in the logs, the notification
context (`zone_name`) and the protocol inspector — it is dropped from the **frame** only,
so diagnosability is unchanged.

The zone table is managed by `printEqLogic()` (populate from saved config) and
`saveEqLogic()` (serialize table rows back to `sia_zone_mappings` before save).

### Numéro utilisateur SIA — *(added 2026-09-25, Story 13.1)*

Below the zone table, one numeric field:

```
Numéro utilisateur SIA : [ 001 ]
Déclarez ce numéro à votre centrale de télésurveillance comme étant l'utilisateur Jeedom.
```

Stored as `sia_user_number` (int, 1-999, default `1`). Unlike the zone table, this is a
**single configured value**, not something read from the alarm plugin: the alarm plugin never
forwards the Jeedom user (`user_login`/`user_id`) to its actions
(`alarm.class.php:639-670`), so there is no per-user source to read from. It addresses every
DC-03 user-addressed code (`BC`, `OP`, and `CL` — story 13-4) — see `php-core-design.md`,
"Disarm During an Alarm", and ADR-18 (`architecture.md`).

### On "Suivant"

Saves the current `sia_zone_mappings` and `sia_user_number` via standard save, advances to
the Alertes zone (same page). No mandatory validation — empty mapping is allowed; `sia_user_number` defaults to `1`.

---

## Step 3 (zone 2) — Alertes critiques (former step 4)

### Layout

```
+-----------------------------------------------------------+
|  En cas de problème grave (supervision perdue, alarme     |
|  non transmise), le plugin doit prévenir quelqu'un.       |
|                                                           |
|  Type de notification : [Commande d'un équipement    |v]  |
|                                                           |
|  -- kind = cmd -------------------------------------------|
|  Commande de notification :                               |
|  [#[Salon][Téléphone][Envoyer SMS]       ] [Rechercher]   |
|  (hidden: sia_notify_cmd_id = 42)                         |
|                                                           |
|  -- kind = internal --------------------------------------|
|  Action interne :       [scenario — lancer un scénario|v] |
|  Scénario à lancer :    [[Sécurité][Alerte télésurv.] |v] |
|                                                           |
|  [Terminer]                                               |
+-----------------------------------------------------------+
```

### Notification target kind

`sia_notify_kind` selects between two mutually exclusive targets. **An empty value means
`cmd`** — installations configured before the internal-action option existed carry no
`sia_notify_kind` and must keep working on their `sia_notify_cmd_id` alone.

| Kind | Config keys | Executed by |
|------|-------------|-------------|
| `cmd` | `sia_notify_cmd_id`, `sia_notify_cmd_human` | `cmd::byId($id)->execCmd(['title', 'message'])` |
| `internal` | `sia_notify_internal`, `sia_notify_scenario_id` | a per-keyword core API — see below |

The `<select>`s of the unselected kind are hidden by `siaDC09_toggleNotifyTarget()`, but
their values stay in the DOM and are saved: switching kind back and forth does not lose the
other target.

### Command picker (kind = `cmd`)

Uses the **standard Jeedom command search modal** (`jeedom.cmd.getSelectModal()`),
filtered for `type: 'action', subType: 'message'` — only commands accepting a
`title` + `message` payload (SMS, Telegram, push, e-mail). Switches, sliders and info
commands never appear in the modal; a `help-block` under the field says so, because the
filter is otherwise invisible to the user.

Two bound fields:
- Visible text input (read-only): stores the human-readable form
  `data-l2key="sia_notify_cmd_human"` — **display only; never passed to daemon, never
  used in logic**
- Hidden input: stores the command ID
  `data-l2key="sia_notify_cmd_id"` — used by the daemon notification handler

The search button opens the modal. On selection:
```javascript
jeedom.cmd.getSelectModal(
    {cmd: {type: 'action', subType: 'message'}},
    function(result) {
        // result.human  → "#[Object][Equipment][Command]#"
        // result.cmd.id → command ID integer
    }
);
```

### Internal actions (kind = `internal`)

A Jeedom internal action is a **scenario-expression keyword, not a command id**, so
`cmd::byId()` cannot execute it. Each supported keyword is dispatched to its own core API by
`siaDC09::_runNotifyInternal()`:

| `sia_notify_internal` | Extra config | Execution |
|-----------------------|--------------|-----------|
| `message` | — | `message::add(__CLASS__, "$title : $message")`, skipped when the caller already posted to the message centre (`$messageCenterDone`) |
| `scenario` | `sia_notify_scenario_id` | `scenario::byId($id)->launch(__CLASS__, "$title : $message")` |

The scenario `<select>` is rendered **server-side** from `scenario::all()` /
`getHumanName()` in `desktop/php/siaDC09.php` — no AJAX endpoint, the page is already
admin-only.

Adding a keyword means four edits: an `<option>` at step 4, a `NOTIFY_INTERNAL_*` constant,
a `case` in `_runNotifyInternal()` and — if it needs a target — a config key plus a check in
`_hasNotifyTarget()`. An unknown keyword logs a warning and drops the alert.

### Validation before "Terminer"

`siaDC09_validateNotifyTarget()` checks the fields of the selected kind only, and shows the
error matching the missing one:

- kind `cmd`, no `sia_notify_cmd_id` → "Veuillez sélectionner une commande. Vous pouvez
  toujours utiliser la messagerie Jeedom."
- kind `internal`, no `sia_notify_internal` → "Veuillez choisir l'action interne à exécuter."
- `sia_notify_internal = scenario`, no `sia_notify_scenario_id` → "Veuillez choisir le
  scénario à lancer."

No advance until the selected kind is complete. The same rule is enforced server-side by
`siaDC09::_hasNotifyTarget()` (guard 6 of `deamon_info()`), which refuses to start a daemon
that could not raise an alert.

### On "Terminer"

1. Validates the selected notification target
2. Triggers standard Jeedom save
3. Sets `sia_wizard_step = 4` (via save)
4. Page reloads in **config mode** (standard flat layout)

> No daemon start is triggered here by the wizard itself. The daemon is still stopped at
> this point (the wizard required it). Jeedom's runtime watchdog (which runs every minute)
> will see `state='nok'`, `launchable='ok'`, `auto=1` and call `deamon_start()`
> automatically within ~60 seconds — **the user does not need to start it manually**.
>
> After wizard completion, `postSave()` only manages commands — it does **not** restart
> the daemon on config changes. If the user modifies config in config mode while the daemon
> is running, they must restart the daemon manually from the Jeedom plugin manager.

---

## Post-wizard: config mode layout

Once `sia_wizard_step == 4`, the equipment config panel shows the standard Jeedom layout:

```
[Relancer l'assistant]

=== Connexion ===
IP: xxx.xxx.xxx.xxx    Port: 5000 (UDP)
Compte: XXXXXX            Chiffrement: activé    Supervision: 60s

=== Zones mappées ===
Salon → Caméra Salon (Snapshot) | URL flux
Chambre → (aucune) | (aucune)
...

=== Notifications critiques ===
Commande: #[Salon][Téléphone][Envoyer SMS]#

=== Commandes ===
[standard Jeedom #table_cmd]
```

All values are shown in read-only display cards (not form inputs) with an "Edit" button per
section that re-opens the relevant wizard step directly. This is a v1.x improvement —
in v1.0, "Relancer l'assistant" is the only edit path.

---

## File structure

```
desktop/
├── php/
│   └── siaDC09.php          ← Wizard + config mode HTML (Component 3)
└── js/
    └── siaDC09.js           ← Wizard navigation + AJAX + table logic (Component 3)

core/ajax/
└── siaDC09.ajax.php         ← AJAX endpoints (extended in Component 3)
```

---

## Configuration keys used by Component 3

All stored in `eqLogic->getConfiguration()`. Fields introduced by the wizard:

| Key | Type | Set in step |
|---|---|---|
| `csr_profile` | string | Step 1 (profile id, '' = Personnalisé; replaces the removed `csr_provider`) |
| `csr_ip` | string | Step 1 |
| `csr_port` | int | Step 1 |
| `transport` | string | Step 1 |
| `account_number` | string | Step 1 |
| `encryption_enabled` | bool | Step 1 |
| `encryption_key` | string | Step 1 |
| `supervision_interval` | int | Step 1 |
| `retry_count` | int | Step 1 |
| `sia_zone_mappings` | array | Step 3 |
| `sia_user_number` | int (1-999) | Step 3 — Story 13.1, default `1` |
| `sia_notify_kind` | string | Step 3 (Alertes) — `cmd` \| `internal`; empty means `cmd` |
| `sia_notify_cmd_id` | int | Step 3 (Alertes) (kind `cmd`) |
| `sia_notify_cmd_human` | string | Step 3 (Alertes) (kind `cmd`, display only) |
| `sia_notify_internal` | string | Step 3 (Alertes) (kind `internal`) — `message` \| `scenario` |
| `sia_notify_scenario_id` | int | Step 3 (Alertes) (`sia_notify_internal = scenario`) |
| `sia_wizard_step` | int | Updated at each step completion |

---

## AJAX endpoint specifications

### `testConnection`

**Direction:** JS → PHP → subprocess (synchronous, single round-trip)

```
Request:  POST action=testConnection
Response: {status: "ok"|"fail"|"nak"|"error", detail: "<human-readable string>",
           outcome: "<internal status, e.g. ack|duh|timeout>",
           sent: {type: "SIA-DCS", account: "001234", transport: "UDP"}}
```

`sent` (Story 17.12) is the plaintext summary of the test message: frame type, account, transport. It
never carries frame bytes (they may be encrypted) nor the key. It is absent when nothing was sent
(incomplete configuration, bad AES key). `outcome: "duh"` marks an expected refusal: PHP logs the
subprocess stderr of a DUH at WARNING, any other stderr at ERROR. The running daemon's SM1_DUH level is
unrelated and unchanged.

PHP implementation (see Task 3.6 for full code). No caching, no polling endpoint.

### `getZones`

**Direction:** JS → PHP → alarm plugin eqLogic

```
Request:  GET action=getZones
Response: {zones: ["Salon", "Chambre parents", "Entrée", "Garage"]}
          or {error: "alarm_plugin_not_found"}
          or {error: "no_zones_configured"}
```

**PHP implementation:**
```php
$alarmEqLogics = eqLogic::byType('alarm');
if (empty($alarmEqLogics)) {
    ajax::success(['error' => 'alarm_plugin_not_found']);
}
$zones = $alarmEqLogics[0]->getConfiguration('zones', []);
$names = array_column($zones, 'name');
ajax::success(['zones' => $names]);
```

> ⚠️ The alarm plugin's internal data structure must be verified at integration time.
> `getConfiguration('zones')` is the assumed key — adapt if different.

### `getCameraCommands`

**Direction:** JS → PHP → cmd query by generic type

```
Request:  GET action=getCameraCommands
Response: {
    camera_take: [
        {id: 42, label: "Caméra Salon > Snapshot"},
        {id: 44, label: "Caméra Entrée > Snapshot"}
    ],
    camera_url: [
        {id: 43, label: "Caméra Salon > URL flux"},
    ]
}
```

**PHP implementation:**
```php
// cmd::byGenericType(string $type) is the correct Jeedom API for genericType lookup.
// cmd::byValue() searches by command value field — wrong for this use case.
$takeCmds = cmd::byGenericType('CAMERA_TAKE');
$urlCmds  = cmd::byGenericType('CAMERA_URL');

$format = function($cmd) {
    return [
        'id'    => $cmd->getId(),
        'label' => $cmd->getEqLogic()->getName() . ' > ' . $cmd->getName(),
    ];
};
ajax::success([
    'camera_take' => array_map($format, $takeCmds),
    'camera_url'  => array_map($format, $urlCmds),
]);
```

---

## JS architecture (`desktop/js/siaDC09.js`)

### Mandatory Jeedom function

```javascript
function addCmdToTable(_cmd) {
    // Standard Jeedom template — auto-created commands shown read-only
    if (!isset(_cmd)) { var _cmd = {configuration: {}}; }
    var tr = '<tr class="cmd">';
    tr += '<td><input class="cmdAttr form-control input-sm" data-l1key="id" style="display:none;">';
    tr += '<span class="cmdAttr" data-l1key="name"></span></td>';
    tr += '<td><span class="cmdAttr" data-l1key="type"></span> / ';
    tr += '<span class="cmdAttr" data-l1key="subType"></span></td>';
    tr += '</tr>';
    $('#table_cmd tbody').append(tr);
    $('#table_cmd tbody tr:last').setJeeValues(_cmd, '.cmdAttr');
}
```

### `printEqLogic(_eqLogic)` hook

Called by `plugin.template.js` when the equipment is loaded. Handles:
1. Determine display mode from `_eqLogic.configuration.sia_wizard_step`
2. If wizard mode: show step `Math.max(1, sia_wizard_step)`, hide config section
3. If config mode: hide wizard section, populate config summary cards
4. Set the profile selector from `_eqLogic.configuration.csr_profile` and apply it (`siaDC09_applyProfile`)
5. Populate zone table from `_eqLogic.configuration.sia_zone_mappings`
6. Populate the notification summary from the selected kind — `sia_notify_cmd_human`, or the
   internal action / scenario name (`siaDC09_notifyTargetLabel()`)

### `saveEqLogic(_eqLogic)` hook

Called by `plugin.template.js` before save (and explicitly from `siaDC09_nextStep()`). Handles:
1. Serialize zone table rows into `_eqLogic.configuration.sia_zone_mappings` JSON array — **only when on step 3 or config mode** (zone table is loaded). At steps 1 and 2 the table is empty; writing it would overwrite a previously saved mapping with an empty array.
2. Update `sia_wizard_step` to the current step (if in wizard mode)

### Wizard navigation

```javascript
function siaDC09_showStep(n) {
    $('.wizard-step').hide();
    $('#wizard-step-' + n).show();
    siaDC09_updateProgressBar(n);
    if (n === 2) { siaDC09_runConnectionTest(); }
}

function siaDC09_nextStep() {
    var current = siaDC09_currentStep();
    if (!siaDC09_validateStep(current)) return;
    // Save via jeedom.eqLogic.save() with explicit callback — do NOT use .trigger('click')
    // followed by siaDC09_showStep() inline. The save is an async AJAX call; showStep(2)
    // immediately calls siaDC09_runConnectionTest(), which reads config from DB.
    // Advancing before the save commits means the test runs against stale credentials.
    var eqLogic = $('.eqLogicAttr').getJeeValues('.eqLogicAttr')[0];
    saveEqLogic(eqLogic);  // run the plugin's own saveEqLogic hook to prepare the object
    jeedom.eqLogic.save({
        eqLogic: eqLogic,
        error: function(error) {
            jeedom.showAlert({message: error.message, level: 'danger'});
        },
        success: function() {
            siaDC09_showStep(current + 1);
        }
    });
}
```

### Zone table management

```javascript
function siaDC09_loadZoneTable(zones, zoneMapping, cameraCommands) {
    var tbody = $('#siaDC09_zone_table tbody');
    tbody.empty();
    var mapping = zoneMapping || [];
    // Highest number already assigned — a zone unknown to the saved mapping takes the next one,
    // so a number already declared to the CSR never shifts to another zone.
    var nextNumber = mapping.reduce(function(max, m) {
        return Math.max(max, parseInt(m.zone_number, 10) || 0);
    }, 0);
    zones.forEach(function(zoneName, index) {
        var saved = mapping.find(function(m) {
            return m.zone_name === zoneName;
        }) || {};
        // Legacy mappings have no zone_number: fall back to table position.
        var zoneNumber = parseInt(saved.zone_number, 10) || 0;
        if (!zoneNumber) {
            zoneNumber = mapping.length === 0 ? index + 1 : ++nextNumber;
        }
        var row = siaDC09_buildZoneRow(zoneNumber, zoneName, saved, cameraCommands);
        tbody.append(row);
    });
}
```

`siaDC09_buildZoneRow()` renders the number as a read-only `<td>` **and** carries it in a
`data-zone-number` attribute on the row, which is what `saveEqLogic` reads back — the
displayed text is for the user, the attribute is the contract.

### testConnection (single call — no polling)

```javascript
function siaDC09_runConnectionTest() {
    siaDC09_setTestUI('pending');
    // Single AJAX call — PHP blocks until subprocess exits (up to 15 s subprocess
    // timeout + PHP overhead). jQuery's default AJAX timeout is 0 (infinite), so
    // an explicit timeout is required. Use 35 000 ms (35 s > PHP set_time_limit(30))
    // so the JS layer can produce a clean timeout message rather than relying on the
    // server to drop the connection abruptly (which fires the error callback with no
    // useful status and produces the wrong user message).
    jeedom.ajax({
        action:  'testConnection',
        plugin:  'siaDC09',
        timeout: 35000,
        success: function(data) {
            siaDC09_setTestUI(data.status, data.detail);
        },
        error: function(xhr, status) {
            if (status === 'timeout') {
                siaDC09_setTestUI('fail',
                    'Pas de réponse de la centrale — vérifiez l\'adresse IP, le port et votre réseau');
            } else {
                siaDC09_setTestUI('error',
                    'Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés');
            }
        }
    });
}
```

---

## Task breakdown — Component 3

### Task 3.1 — `desktop/php/siaDC09.php` skeleton

**What:** The full page HTML. Auth check, `sendVarToJS`, equipment header (name + enable +
visible + "Relancer l'assistant" button), wizard section (hidden in config mode),
config summary section (hidden in wizard mode), `#table_cmd`, mandatory
`plugin.template.js` include at the very end.

**Two root divs inside the eqLogic panel:**
- `#siaDC09-wizard` (shown when `sia_wizard_step < 4`)
- `#siaDC09-config-summary` (shown when `sia_wizard_step == 4`)

Both are rendered server-side. JS controls visibility on `printEqLogic()`.

---

### Task 3.2 — Step 1 HTML + JS: CSR profile & credentials

**What:** Profile selector (Ajax / Vesta / FoxStream / Personnalisé), connection fields, collapsed "Options avancées" panel (always rendered).

**HTML fields** use `class="eqLogicAttr" data-l1key="configuration" data-l2key="..."`.

**JS behaviors:**
- Profile select change → `siaDC09_applyProfile()` fills and locks (or unlocks) the advanced fields
- Encryption checkbox toggle → show/hide `encryption_key` field
- Profile "Personnalisé" → unlock the advanced fields, keeping their current values
- Inline validation on "Suivant"

---

### Task 3.3 — Step 2 HTML + JS: connection test

**What:** CSR summary display (read from JS after `printEqLogic`), test result area,
auto-trigger on step arrival, "Relancer le test" / "Ignorer" / "Suivant" buttons.

**JS behaviors:**
- `siaDC09_showStep(2)` always calls `siaDC09_runConnectionTest()`
- `siaDC09_runConnectionTest()` sends a single AJAX call (`action=testConnection`) and
  displays the result when it returns — no polling, no cache
- "Suivant" enabled only after status `ok` or `nak`. If `nak`, `jeeDialog.confirm()` before advance.
- "Ignorer" always advances, appends inline warning banner to step 3
- "Relancer le test" re-runs `siaDC09_runConnectionTest()`

> The AJAX call may take up to 15 seconds (subprocess timeout). The spinner remains visible
> during this time. An explicit `timeout: 35000` is set on the call — jQuery's default is
> `0` (infinite), which would leave the user waiting forever if PHP drops the connection
> without a response (e.g., on `set_time_limit` expiry).

---

### Task 3.4 — Step 3 HTML + JS: zone table

**What:** Table container, zone row template (hidden), alarm-not-found warning banner
(hidden by default).

**JS behaviors (in `printEqLogic`):**
1. Call `getCameraCommands` AJAX → build option lists for both selects
2. Call `getZones` AJAX → if error, show warning banner, keep "Suivant" enabled
3. On success: call `siaDC09_loadZoneTable(zones, savedMapping, cameraCommands)`
4. Rehydrate saved selections from `sia_zone_mappings` config

**`saveEqLogic` hook:**
- Guard: only serialize when `siaDC09_currentStep() >= 3` (or in config mode). At steps 1–2 the zone table is not loaded — skip writing `sia_zone_mappings` to avoid overwriting a previously saved mapping with an empty array.
- Read each table row: `zone_number` (`data-zone-number` attribute, integer),
  `zone_name` (text), `camera_action_cmd_id` (select value),
  `media_url_cmd_id` (select value)
- Build array and write to `_eqLogic.configuration.sia_zone_mappings`

---

### Task 3.5 — Step 4 HTML + JS: critical notifications

**What:** Explanatory text, kind selector, command picker (display input + hidden ID input +
search button), internal-action + scenario selects, "Terminer" button.

**HTML:**
```html
<select class="eqLogicAttr form-control" id="siaDC09_notifyKind"
        data-l1key="configuration" data-l2key="sia_notify_kind">
    <option value="cmd">{{Commande d'un équipement (SMS, Telegram, push…)}}</option>
    <option value="internal">{{Action interne Jeedom}}</option>
</select>

<!-- kind = cmd -->
<div class="form-group siaDC09-notify-cmd">
    <div class="input-group">
        <input type="text"
               class="eqLogicAttr form-control"
               data-l1key="configuration"
               data-l2key="sia_notify_cmd_human"
               readonly
               placeholder="{{Sélectionnez une commande de notification}}" />
        <span class="input-group-btn">
            <a class="btn btn-default cursor" id="siaDC09_searchNotifyCmd">
                <i class="fas fa-list-alt"></i>
            </a>
        </span>
    </div>
    <input type="hidden"
           class="eqLogicAttr"
           data-l1key="configuration"
           data-l2key="sia_notify_cmd_id" />
    <span class="help-block">{{… type « action », sous-type « message » …}}</span>
</div>

<!-- kind = internal -->
<div class="form-group siaDC09-notify-internal">
    <select class="eqLogicAttr form-control" id="siaDC09_notifyInternal"
            data-l1key="configuration" data-l2key="sia_notify_internal">
        <option value="">{{Choisissez une action}}</option>
        <option value="message">{{message — ajouter au centre de messages Jeedom}}</option>
        <option value="scenario">{{scenario — lancer un scénario}}</option>
    </select>
</div>
<div class="form-group siaDC09-notify-scenario">
    <select class="eqLogicAttr form-control" id="siaDC09_notifyScenario"
            data-l1key="configuration" data-l2key="sia_notify_scenario_id">
        <option value="">{{Choisissez un scénario}}</option>
        <?php foreach ($scenarios as $notifyScenario): ?>
        <option value="<?= (int) $notifyScenario->getId() ?>"><?= htmlspecialchars($notifyScenario->getHumanName()) ?></option>
        <?php endforeach; ?>
    </select>
</div>
```

`$scenarios = scenario::all()` is computed in the PHP header of `desktop/php/siaDC09.php`.

**JS — command picker:**
```javascript
$('#siaDC09_searchNotifyCmd').on('click', function() {
    jeedom.cmd.getSelectModal(
        {cmd: {type: 'action', subType: 'message'}},
        function(result) {
            $('input[data-l2key="sia_notify_cmd_human"]').val(result.human);
            $('input[data-l2key="sia_notify_cmd_id"]').val(result.cmd.id);
        }
    );
});
```

**JS — kind toggle:** `siaDC09_showStep(4)` calls `siaDC09_initNotifyTarget()` (defaults an
empty kind to `cmd`, then toggles); `change` on `#siaDC09_notifyKind` /
`#siaDC09_notifyInternal` calls `siaDC09_toggleNotifyTarget()`, which shows
`.siaDC09-notify-cmd`, `.siaDC09-notify-internal` and `.siaDC09-notify-scenario` according to
the selection and hides the three step-4 error divs.

**"Terminer" button:**
- Calls `siaDC09_validateNotifyTarget()`; on failure, the inline red message matching the
  missing field (no `jeeDialog`)
- Calls `siaDC09_setWizardStep(4)` then triggers standard save
- Page reloads → `printEqLogic` sees `sia_wizard_step == 4` → switches to config mode

---

### Task 3.6 — `siaDC09.ajax.php`: `testConnection`

**What:** One AJAX action. PHP spawns a short-lived subprocess synchronously and returns
the test result directly — no cache, no polling endpoint.

```php
if (init('action') == 'testConnection') {
    // Use the non-creating variant — testConnection only reads config.
    // If the equipment doesn't exist (stale tab, mid-wizard reinstall), return an
    // explicit error rather than silently creating bare equipment with empty config.
    $eqLogic = siaDC09::_getAutoEquipmentSafe();
    if (!$eqLogic) {
        ajax::success([
            'status' => 'error',
            'detail' => 'Équipement introuvable — rechargez la page et recommencez l\'assistant.',
        ]);
    }

    // Strip encryption_key before passing config as CLI arg — key must never appear
    // in argv (visible in ps aux). Inject it via env var instead, same pattern as
    // deamon_start(). The subprocess reads SIA_ENCRYPTION_KEY from os.environ.
    $configData = $eqLogic->getConfiguration();
    $encKey     = $configData['encryption_key'] ?? '';
    unset($configData['encryption_key']);
    $config     = json_encode($configData);
    $envPrefix  = 'SIA_ENCRYPTION_KEY=' . escapeshellarg($encKey) . ' ';

    // Use the same venv-aware python binary as deamon_start() — critical on Debian 12
    // where pip3 packages are installed inside Jeedom's virtualenv, not system python3.
    $python3 = method_exists('system', 'getCmdPython3')
        ? system::getCmdPython3(__CLASS__)
        : 'python3 ';

    // Build subprocess command. --test-only causes the daemon to run one NULL frame,
    // write a JSON result to stdout, then exit (timeout: 15 s).
    // Use escapeshellarg() per argument (not escapeshellcmd()) to correctly handle
    // paths with spaces and avoid shell metacharacter ambiguity.
    $script  = realpath(__DIR__ . '/../../resources/siadc09d/siadc09d.py');
    $cmd     = $python3 . escapeshellarg($script)
             . ' --test-only'
             . ' --timeout 15'
             . ' --config ' . escapeshellarg($config);

    $output  = [];
    $retCode = 0;
    exec($envPrefix . $cmd . ' 2>/dev/null', $output, $retCode);

    $raw = implode('', $output);
    $result = json_decode($raw, true);

    if (!$result || !isset($result['status'])) {
        ajax::success([
            'status' => 'error',
            'detail' => 'Impossible de lancer le test — vérifiez que Python 3 et les dépendances sont installés',
        ]);
    }

    // result from subprocess: {status: "ok"|"fail"|"nak", detail: "<human string>"}
    ajax::success($result);
}
```

---

### Task 3.7 — `siaDC09.ajax.php`: `getZones`

**What:** Reads zone names from alarm plugin eqLogic.

```php
if (init('action') == 'getZones') {
    $alarmEqLogics = eqLogic::byType('alarm');
    if (empty($alarmEqLogics)) {
        ajax::success(['error' => 'alarm_plugin_not_found']);
    }
    $zones = $alarmEqLogics[0]->getConfiguration('zones', []);
    if (empty($zones)) {
        ajax::success(['error' => 'no_zones_configured']);
    }
    ajax::success(['zones' => array_column($zones, 'name')]);
}
```

> ⚠️ `getConfiguration('zones')` structure must be verified against the alarm plugin
> source at integration time. The `name` key on each zone element is assumed.

---

### Task 3.8 — `siaDC09.ajax.php`: `getCameraCommands`

**What:** Returns CAMERA_TAKE and CAMERA_URL commands in one call.

```php
if (init('action') == 'getCameraCommands') {
    $format = function($cmd) {
        return [
            'id'    => (int) $cmd->getId(),
            'label' => $cmd->getEqLogic()->getName() . ' > ' . $cmd->getName(),
        ];
    };
    ajax::success([
        'camera_take' => array_map($format, cmd::byGenericType('CAMERA_TAKE')),
        'camera_url'  => array_map($format, cmd::byGenericType('CAMERA_URL')),
    ]);
}
```

---

### Task 3.9 — ~~`siaDC09::message()` extension: `test_result` type~~

**Removed (Option A).** With the subprocess approach, the test result is returned
synchronously from `exec()` in Task 3.6. The daemon never sends a `test_result`
message — no `message()` handler is needed for this flow.

---

### Task 3.10 — Daemon: `--test-only` entry point

**What:** A standalone execution mode in `siadc09d.py`. When invoked with `--test-only`,
the process connects to the CSR, sends one NULL supervision frame, writes a JSON
result to **stdout**, and exits. It does **not** start the supervision loop, does not
open the Jeedom socket, and does not write to the Jeedom log.

**CLI signature:**
```
python3 siadc09d.py --test-only --timeout <seconds> --config '<json>'
```

**Entry point in `siadc09d.py`:**
```python
if '--test-only' in sys.argv:
    import argparse, asyncio, json as _json, sys as _sys
    _ap = argparse.ArgumentParser()
    _ap.add_argument('--test-only', action='store_true')
    _ap.add_argument('--timeout',   type=int, default=15)
    _ap.add_argument('--config',    type=str, default='{}')
    _args = _ap.parse_args()

    asyncio.run(run_connection_test(
        config  = _json.loads(_args.config),
        timeout = _args.timeout,
    ))
    _sys.exit(0)
```

```python
async def run_connection_test(config: dict, timeout: int) -> None:
    """Send a NULL frame to the CSR, write JSON result to stdout, exit."""
    import time, json as _json, pathlib
    # Resolve CSR params — mirrors SIADaemon.__init__() exactly (F9 fix).
    # For preset mode, load from csr_presets.json rather than trusting the
    # eqLogic-stored values, which may be stale if the preset file was updated.
    csr_provider = config.get('csr_provider', 'manual')
    if csr_provider != 'manual':
        presets_path = pathlib.Path(__file__).parent / 'csr_presets.json'
        with open(presets_path) as f:
            presets_data = _json.load(f)
        preset = next(
            (p for p in presets_data['presets'] if p['id'] == csr_provider), None
        )
        if preset is None:
            print(_json.dumps({'status': 'error',
                'detail': f"Preset '{csr_provider}' introuvable dans csr_presets.json"}),
                flush=True)
            return
        csr_ip    = preset['csr_ip']
        csr_port  = int(preset['csr_port'])
        transport = preset['transport']
    else:
        csr_ip    = config.get('csr_ip')
        csr_port  = int(config.get('csr_port', 5000))
        transport = config.get('transport', 'udp')
    account = config.get('account_number', '')
    # Encryption key: read from SIA_ENCRYPTION_KEY env var (same as deamon_start())

    start = time.monotonic()
    frame = sia_protocol.encode_null(account, sequence=1, ...)
    result = await _send_raw_once(csr_ip, csr_port, transport, frame, timeout=timeout)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if result['status'] == 'ack':
        out = {'status': 'ok',  'detail': f'ACK reçu en {elapsed_ms}ms'}
    elif result['status'] == 'nak':
        out = {'status': 'nak', 'detail': 'Réponse inattendue (NAK)'}
    else:
        out = {'status': 'fail', 'detail': f'Pas de réponse (timeout {timeout}s)'}

    print(json.dumps(out), flush=True)
```

> `_send_raw_once()` is a thin async wrapper (open socket → send → receive → close)
> that shares the same UDP/TCP send logic as `SIADaemon._send_raw()` but is
> standalone (no SM1 context, no retry loop).

---

## CSR Presets Configuration File

**Location:** `core/config/csr_presets.json` (ADR-22, Story 17.1)

Read by PHP only (`siaDC09::getCsrProfiles()`). The daemon never reads it and never receives a
profile name: `deamon_start` passes the resolved `supervision_format`, `supervision_interval`,
`rp_enabled` and `rp_interval` values. The wizard receives the profiles through
`sendVarToJS('siaDC09_csrProfiles', ...)`.

### Format

```json
{
  "schema_version": 1,
  "profiles": {
    "ajax": { "label": "Ajax", "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60 }
  }
}
```

A profile may omit a key (e.g. `supervision_interval`); the wizard then leaves that field untouched.

### Alarm media keys (Story 17.8)

A profile may also carry the story 17.7 media keys: `media_snapshot_enabled`, `media_clip_enabled`
(0/1), `media_snapshot_format`, `media_clip_format` (`U` or `V`) and `media_single_tag` (0/1).
The wizard fills them **and locks them** (Story 17.10, ADR-22 amendment), and the media URL template is never a profile key.
A profile may also declare `media_enabled` (0/1), the default of the photo/video box on step 1: Vesta and FoxStream 1
(the retired Scutum preset used 0, see "Retired profile: Scutum"). The box itself is never
locked. A profile that declares no media key (Ajax) leaves the box greyed and unchecked, with the caption
« Cette centrale ne reçoit ni photo ni vidéo. ».

| Profile | Media | Supervision | RP |
|---|---|---|---|
| `vesta` (Vesta, Climax) | snapshot + clip, `U`, one tag | `sia-dcs` every 30 s | every 120 s |
| `foxstream` (FoxStream, FoxBox) | snapshot + clip, `V`, one tag | `null` (DC-09 NULL frame) every 30 s | every 120 s |

The 30 s and 120 s values are test values.

### Adding a profile

1. Add an entry under `profiles` in `csr_presets.json`.
2. No PHP, JS or daemon change: the selector is built from the file.

### Retired profile: Scutum

The `scutum` preset was removed from `core/config/csr_presets.json` (the wizard no longer offers it). Its
configuration is kept here as the reference for the Scutum CSR (observed behaviour: `internal-docs/ajax.md`).
To re-create it: add the entry below under `profiles` (step 2 above needs no code change), or choose
**Personnalisé** and set the same values by hand.

```json
"scutum": { "label": "Scutum", "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60,
            "media_enabled": 0, "media_snapshot_enabled": 0, "media_clip_enabled": 1,
            "media_snapshot_format": "V", "media_clip_format": "V", "media_single_tag": 1 }
```

| Setting | Value | Why |
|---|---|---|
| `supervision_format` | `none` | on-demand transmitter like Ajax: no `NULL` frame; Scutum supervises it with the RP |
| `rp_enabled` / `rp_interval` | 1 / 60 s | the RP "Test Cyclique" is what Scutum uses to see the transmitter alive |
| `media_enabled` | 0 | the photo/video box off by default (to be tested with the CSR) |
| snapshot / clip | snapshot off, clip on, both format `V`, one tag | video only, in the `V` extension |

Behaviour of an equipment saved with `csr_profile` = `scutum` after the removal: the profile is unknown, so the
wizard treats it as **Personnalisé** (fields unlocked, saved values kept).

---

## Testing strategy for Component 3

| Test | How |
|---|---|
| Step 1 profile | Select Ajax → verify advanced fields pre-filled and read-only |
| Step 1 Personnalisé | Select Personnalisé → verify advanced fields become editable, values kept |
| Step 1 reload saved config | Save manual config, reload page → verify "Personnalisé" selected, saved values shown |
| Step 1 validation | Leave account empty, click Suivant → verify error shown, no advance |
| Step 2 auto-trigger | Arrive at step 2 → verify spinner appears immediately, subprocess test fires |
| Step 2 ACK result | Subprocess returns ACK → green banner, "Suivant" enabled |
| Step 2 NAK result | Subprocess returns NAK → orange banner, "Suivant" enabled with confirm dialog |
| Step 2 timeout result | Subprocess returns timeout → red banner, "Suivant" disabled |
| Step 2 subprocess error | Python missing or deps broken → red banner with install hint |
| Step 2 Ignorer | Click Ignorer → verify advance + warning banner in step 3 |
| Step 2 Suivant blocked | While test in-flight → verify Suivant is disabled |
| Step 2 Suivant on NAK | Test returns NAK → jeeDialog.confirm() shown before advance |
| Relancer assistant — daemon running | Click "Relancer l'assistant" while daemon is running → confirmation dialog shown, daemon stopped, wizard resets to step 1 |
| Relancer assistant — daemon stopped | Click "Relancer l'assistant" while daemon is stopped → wizard resets to step 1 immediately |
| Step 3 alarm plugin found | Install alarm plugin with zones → verify table populated correctly |
| Step 3 alarm plugin missing | No alarm plugin → verify warning banner, Suivant still available |
| Step 3 sia_zone_mappings save | Select camera for Salon, save → reload → verify selection preserved |
| Step 3 zone numbers | 4 zones → N° column shows 1..4; save → reload → same numbers |
| Step 3 zone number stability | Delete zone 2 in the alarm plugin, reload step 3 → zones 3 and 4 keep their numbers (no renumbering) |
| Zone number in frame | Trigger alarm with title `#zone#` on a mapped zone → frame carries `BA 00N`, never the label |
| Unmapped zone | Trigger with a title matching no zone → frame carries no zone field, warning logged, alarm still sent |
| Step 4 Terminer without cmd | Click Terminer with no command → verify inline error, no advance |
| Step 4 command picker | Click search button → jeedom.cmd.getSelectModal opens, selection fills fields |
| Post-wizard config mode | After Terminer → verify wizard hidden, config summary shown |
| Relancer l'assistant | Click button in config mode → verify wizard shows at step 1 with saved values |


## Story 17.7 - Alarm media in the wizard

The advanced options of step 1 carry the media block: `media_snapshot_enabled` / `media_clip_enabled` (checkboxes), `media_snapshot_format` / `media_clip_format` (U or V), `media_single_tag` (checkbox), and the `frigate_media_url_template` field (moved from step 3). The one-tag option is unchecked when both media are on with different formats; since Story 17.11 it is shown as the extension choice described in Step 1. Absent keys load as snapshot on, clip on, V, V, one tag.

**Story 17.10 amendment.** The five content fields are profile fields (locked by a profile that declares media; editable in Personnalisé). The Frigate address left the advanced panel for the card « Levée de doute photo / vidéo » (`#siaDC09-media-card`), above « Options avancées »: the checkbox `media_enabled` (« Joindre une photo ou une vidéo à l'alarme (levée de doute) », absent = on, set explicitly by the JS on load) and the required address « Adresse de votre serveur Frigate * » (`#siaDC09-media-url-group`, shown only while the box is checked, value kept when hidden). Step 1 « Suivant » refuses a checked box with an empty address (field error + banner, key `frigate_media_url_template`); step 3 keeps the same check as a safety net. With `media_enabled=0` PHP sends no `media` to the daemon and does not send `prefetchEvent` (no Frigate prefetch, no forced capture). `deamon_info()` Guard 3f (`siaDC09::mediaConfigError()`) refuses an empty address only when `media_enabled` is explicitly stored as 1, so equipment saved before the key keeps launching; the wizard writes the key on save.

## Story 18.4 - Step 1 media choice and transport

Spec source: `_bmad-output/initiative-my-project/epic-18-ftps-alarm-media-upload/ux-18-wizard-media-block/EXPERIENCE.md`.

**Photo / Vidéo moved to step 1.** The card « Levée de doute photo / vidéo » (`#siaDC09-media-card`) holds, once the box `media_enabled` is ticked (`#siaDC09-media-body`): « Que joindre ? » (`media_snapshot_enabled`, `media_clip_enabled`, still profile fields: grey with one caption `#siaDC09-media-lock-note` « Fixé par le profil « {nom} ». », free in Personnalisé), then the transport radios « Une adresse (URL) dans le message d'alarme » / « Une copie déposée sur un serveur FTPS ». The step 2 advanced panel no longer shows the Photo / Vidéo switches; its formats and extension choice (`#siaDC09-zone-content`) show only under the address transport. A profile without media (Ajax) greys and unchecks the box and hides everything below it.

**Transport.** `media_transport` is a hidden `eqLogicAttr` input holding `url` or `ftps` (Jeedom saves a radio as 0/1, so the radios `.siaDC09-transport-radio` drive the hidden field). Absent or empty means `url` (« adresse »). The Frigate address group `#siaDC09-media-url-group` exists only under `url`; under `ftps` step 1 shows only the note « Les réglages du serveur FTPS se font à l'étape suivante, dans les options avancées. ».

**Validation.** Step 1 « Suivant » (`siaDC09_mediaConfigErrors()`): Photo or Vidéo required (« Photo / vidéo : choisissez au moins l'une des deux. », key `media_snapshot_enabled`); the Frigate address required under `url` only. The step 3 safety net and PHP `deamon_info()` Guard 3f skip the address check under `ftps`.

**`ftps_enabled` is derived.** It is no longer stored or shown: the FTPS upload is on exactly when `media_transport == ftps`, decided in one place, `siaDC09::isFtpsTransport()`, used by `deamon_start()` and `siaDC09Cmd::_ftpsTransportActive()`.

**Interim.** Until story 18.11 moves the FTPS settings to the step 2 advanced panel, the hand-entry card `#siaDC09-ftps-card` (« Serveur FTPS ») stays on step 1, shown only under FTPS. 18.11 removes it, adds the single test button and the step 2 rules (EXPERIENCE.md « Spec corrections »).

**Summaries.** Step 2 line 2 « Levée de doute : … » (`siaDC09_mediaSummaryLine()`) and a « Levée de doute » block in « Configuration active » (`#siaDC09-summary-media`), never showing the password.
