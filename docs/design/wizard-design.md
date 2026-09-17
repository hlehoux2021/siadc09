# Config Wizard Design — Jeedom siaDC09 Plugin

**Version:** 0.2
**Date:** 2026-04-03
**Status:** Updated — aligned with architecture.md (sia_ prefix, canonical step map, exit contract)

---

## Overview

The wizard is the **equipment configuration page** (`desktop/php/siaDC09.php`). It guides
the user through 4 steps the first time, then switches to a standard flat config layout once
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

| `sia_wizard_step` | Meaning |
|---|---|
| `0` | Not started |
| `1` | Preset selection complete |
| `2` | Connection test complete |
| `3` | Zone mapping complete |
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

On confirm: PHP sets `sia_wizard_step = 0` **first** (makes `launchable='nok'` immediately
visible to Jeedom's watchdog — prevents auto-restart during wizard), then calls
`siaDC09::deamon_stop()`, then reloads the page at step 1.
If the `sia_wizard_step` save fails, the daemon is still running with valid config (no harm —
do not proceed to stop). If the daemon is already stopped, the button sets `sia_wizard_step = 0`
and reloads immediately.

---

## Wizard steps

| Step | Title | What the user configures |
|---|---|---|
| 1 | Votre opérateur | Provider selection + account number + encryption key (and all CSR fields) |
| 2 | Test de connexion | Live connection test to the CSR |
| 3 | Vos zones d'alarme | Zone → camera action + media URL mapping |
| 4 | Alertes critiques | Jeedom command to call on critical errors |

Progress is shown as a horizontal stepper at the top (non-clickable, read-only).

---

## Step 1 — Votre opérateur

### Provider selection

Two cards side by side. No badges.

```
+---------------------+    +---------------------+
|                     |    |                     |
|    IMA Protect      |    |    Personnalisé     |
|                     |    |                     |
+---------------------+    +---------------------+
        (selected)
```

- Selecting a card sets the hidden `csr_provider` field (`ima_protect` or `manual`).
- On page load, the **saved** `csr_provider` determines which card is pre-selected.
  If no config saved yet, "IMA Protect" is pre-selected and fields pre-filled with preset.

### "Personnaliser" button

Visible only when "IMA Protect" card is active. When clicked:
- Switches card selection to "Personnalisé"
- Sets `csr_provider` to `manual`
- Copies current pre-filled values into the now-editable fields
- No data is lost — the user starts from the preset as a base

### Fields

All fields are **always rendered** in the DOM and always bound via `data-l2key` so they
are saved to eqLogic on every save. Editability depends on mode:
- "IMA Protect" active → CSR fields are **read-only** (`readonly` attribute, not `disabled`)
- "Personnalisé" active → all fields are **editable**

> **`readonly` not `disabled`:** `disabled` inputs are excluded from form submission.
> `readonly` inputs submit normally. This ensures CSR field values are always persisted
> to eqLogic by the standard save, regardless of mode.

| Field | HTML binding | IMA Protect preset | Notes |
|---|---|---|---|
| `csr_provider` | `data-l2key="csr_provider"` (hidden) | `ima_protect` | Card selection writes this |
| Adresse IP / Nom de domaine | `data-l2key="csr_ip"` | _(from csr_presets.json)_ | `readonly` in preset mode |
| Port | `data-l2key="csr_port"` | _(from csr_presets.json)_ | `readonly` in preset mode |
| Transport | `data-l2key="transport"` | _(from csr_presets.json)_ | `readonly` in preset mode |
| Numéro de compte | `data-l2key="account_number"` | _(empty, user fills)_ | Always editable — subscriber-specific |
| Chiffrement | `data-l2key="encryption_enabled"` | _(from csr_presets.json)_ | `readonly` in preset mode |
| Clé de chiffrement (AES) | `data-l2key="encryption_key"` | _(empty, user fills)_ | Always editable — subscriber-specific; visible only if encryption enabled; 32/48/64 hex chars (AES-128/192/256) |
| Intervalle supervision | `data-l2key="supervision_interval"` | _(from csr_presets.json)_ | `readonly` in preset mode |
| Nombre de tentatives | `data-l2key="retry_count"` | _(from csr_presets.json)_ | `readonly` in preset mode |

> **Note:** `account_number` and `encryption_key` are always editable even in
> "IMA Protect" mode — they are subscriber-specific values that the preset cannot know.

### Validation before "Suivant"

- `account_number` non-empty, 3–16 hex chars
- If `encryption_enabled`: `encryption_key` non-empty, **32, 48, or 64 hex chars** (AES-128 / AES-192 / AES-256 respectively — per section 5.4.5, CSR must support all three lengths)
- `csr_ip` non-empty
- `csr_port` numeric, 1–65535

Errors shown inline (red border + message under the field). No advance if validation fails.

### Data flow

**eqLogic config is the single source of truth** for all CSR parameters. After step 1 is
saved, eqLogic always contains fully resolved values regardless of whether the user chose
a preset or entered values manually.

**How preset values reach eqLogic:** PHP renders the step 1 page by reading `csr_presets.json`
server-side and pre-filling all CSR fields (`csr_ip`, `csr_port`, etc.) with the preset
values. Those fields carry `data-l2key` bindings and `readonly` attribute — they submit
their values on save just like editable fields. The standard Jeedom save writes them to
eqLogic directly. No server-side resolution step is needed.

`csr_provider` is saved to eqLogic to allow the wizard to restore the correct card
selection on page reload, and to control whether the "Personnaliser" button is shown.
It is not used by the daemon.

`csr_presets.json` is read **only** at wizard page render time — it is never read by the
daemon or by `deamon_start()`.

| `csr_provider` | CSR field values come from | Daemon reads from |
|---|---|---|
| Any preset ID | PHP pre-fills from `csr_presets.json` → saved to eqLogic | eqLogic |
| `"manual"` | User fills form fields → saved to eqLogic | eqLogic |

> **Adding a new preset:** add an entry to `csr_presets.json` and add a card in the
> wizard PHP. No daemon changes, no guard changes.

### On "Suivant"

Standard Jeedom save is triggered (`eqLogicAction[data-action="save"]` click), then
the wizard advances to step 2.

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
|  [Relancer le test]          [Ignorer]    [Suivant →]     |
+-----------------------------------------------------------+
```

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

### Button behavior

| Button | Behavior |
|---|---|
| "Relancer le test" | Re-triggers the same auto-test flow |
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
- The daemon must be stopped (guaranteed by "Relancer l'assistant" daemon-stop flow)
- Step 1 must have been saved before reaching step 2 (config available on disk)

---

## Step 3 — Vos zones d'alarme

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
| Label matches a `zone_name` (case-insensitive, trimmed) | `[#001234|BA 001]` — the matched `zone_number`, zero-padded to 3 digits |
| No match, or empty title | `[#001234|BA]` — **no zone field at all**, plus a warning in the log |

The label is never transmitted. Rationale: a CSR indexes incidents by zone number; a free
text label is not actionable for an operator and is not what the DC-09 Annex B examples
show (`[#1234|FA 129]`, Contact ID `[#1234|1130 02 065]` — hence the 3-digit padding).

The label is still carried in the IPC payload and stays in the logs, the notification
context (`zone_name`) and the protocol inspector — it is dropped from the **frame** only,
so diagnosability is unchanged.

The zone table is managed by `printEqLogic()` (populate from saved config) and
`saveEqLogic()` (serialize table rows back to `sia_zone_mappings` before save).

### On "Suivant"

Saves the current `sia_zone_mappings` via standard save, advances to step 4.
No mandatory validation — empty mapping is allowed.

---

## Step 4 — Alertes critiques

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
Opérateur: IMA Protect    IP: xxx.xxx.xxx.xxx    Port: 5000 (UDP)
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
| `csr_provider` | string | Step 1 |
| `csr_ip` | string | Step 1 |
| `csr_port` | int | Step 1 |
| `transport` | string | Step 1 |
| `account_number` | string | Step 1 |
| `encryption_enabled` | bool | Step 1 |
| `encryption_key` | string | Step 1 |
| `supervision_interval` | int | Step 1 |
| `retry_count` | int | Step 1 |
| `sia_zone_mappings` | array | Step 3 |
| `sia_notify_kind` | string | Step 4 — `cmd` \| `internal`; empty means `cmd` |
| `sia_notify_cmd_id` | int | Step 4 (kind `cmd`) |
| `sia_notify_cmd_human` | string | Step 4 (kind `cmd`, display only) |
| `sia_notify_internal` | string | Step 4 (kind `internal`) — `message` \| `scenario` |
| `sia_notify_scenario_id` | int | Step 4 (`sia_notify_internal = scenario`) |
| `sia_wizard_step` | int | Updated at each step completion |

---

## AJAX endpoint specifications

### `testConnection`

**Direction:** JS → PHP → subprocess (synchronous, single round-trip)

```
Request:  POST action=testConnection
Response: {status: "ok"|"fail"|"nak"|"error", detail: "<human-readable string>"}
```

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
4. Set active provider card based on `_eqLogic.configuration.csr_provider`
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

### Task 3.2 — Step 1 HTML + JS: provider selection & credentials

**What:** Provider cards, all form fields (always rendered), "Personnaliser" button.

**HTML fields** use `class="eqLogicAttr" data-l1key="configuration" data-l2key="..."`.

**JS behaviors:**
- Card click → update `csr_provider` hidden input + toggle field editability
- Encryption checkbox toggle → show/hide `encryption_key` field
- "Personnaliser" button → switch to manual mode, copy current field values, enable editing
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

**Location:** `resources/siadc09d/csr_presets.json`

Loaded by the daemon at startup to resolve CSR parameters for preset providers.
Also read by the PHP wizard (via `file_get_contents`) to populate read-only fields
for preset providers.

### Format

```json
{
  "version": 1,
  "presets": [
    {
      "id": "ima_protect",
      "label": "IMA Protect",
      "csr_ip": "TBD",
      "csr_port": 5000,
      "transport": "udp",
      "encryption_enabled": true,
      "supervision_interval": 60,
      "retry_count": 3
    }
  ]
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Matches `csr_provider` eqLogic config value |
| `label` | string | Display label for the wizard card |
| `csr_ip` | string | CSR IP or FQDN |
| `csr_port` | int | UDP/TCP port |
| `transport` | `"udp"` \| `"tcp"` | Protocol transport |
| `encryption_enabled` | bool | Whether AES encryption is required |
| `supervision_interval` | int (seconds) | Supervision NULL interval |
| `retry_count` | int | Max event send retries |

### Daemon usage

In `SIADaemon.__init__()`:

```python
csr_provider = self.get_config('csr_provider', 'manual')
if csr_provider != 'manual':
    try:
        with open(PRESETS_PATH) as f:
            presets_data = json.load(f)
        preset = next(
            (p for p in presets_data['presets'] if p['id'] == csr_provider),
            None
        )
        if preset is None:
            self._logger.error(
                f"Preset '{csr_provider}' introuvable dans csr_presets.json — "
                f"vérifiez la configuration ou mettez à jour le plugin."
            )
            self.stop()
            return
    except (FileNotFoundError, json.JSONDecodeError) as e:
        self._logger.error(
            f"Impossible de lire csr_presets.json : {e} — "
            f"réinstallez le plugin."
        )
        self.stop()
        return
    self._csr_ip   = preset['csr_ip']
    self._csr_port = preset['csr_port']
    # ... etc.
else:
    self._csr_ip   = self.get_config('csr_ip')
    self._csr_port = int(self.get_config('csr_port'))
    # ... etc.
# Always subscriber-specific:
self._account = self.get_config('account_number')
self._enc_key = os.environ.get('SIA_ENCRYPTION_KEY', '')
```

### Community contribution path

The file format and location are documented here for community contributions. To add a
new preset:
1. Add a new entry to `csr_presets.json`
2. Add a card to the Step 1 wizard UI (`desktop/php/siaDC09.php`)
3. Open a PR — no daemon code changes required

In v1.0, only the `ima_protect` preset is included. Additional presets (Sicur, Telematec,
etc.) are out of scope for v1.0 but the file structure is designed for extensibility.

---

## Testing strategy for Component 3

| Test | How |
|---|---|
| Step 1 IMA Protect preset | Select IMA Protect card → verify fields pre-filled and disabled |
| Step 1 Personnaliser | Click "Personnaliser" → verify fields become editable with preset values copied |
| Step 1 reload saved config | Save manual config, reload page → verify "Personnalisé" card selected, saved values shown |
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
