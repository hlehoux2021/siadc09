# Widget Design — Jeedom siaDC09 Plugin

**Version:** 0.2
**Date:** 2026-03-12
**Status:** Draft — full redesign after adversarial review (F6); all Component 6 decisions confirmed

---

## Overview

Component 6 defines the **dashboard tile** for the auto-created siaDC09 equipment.
The tile is the primary at-a-glance view for the night-time emergency use case: the user
receives an alarm notification, opens Jeedom on their phone, and needs to immediately
understand (1) whether the CSR link is working and (2) whether the alarm was transmitted.

**Widget type:** PHP `toHtml()` override on the `siaDC09` eqLogic class, with HTML
template files in `core/template/dashboard/` and `core/template/mobile/`.

This is the standard Jeedom mechanism for custom equipment tiles. The tile is
server-rendered. When any INFO command value changes via `checkAndUpdateCmd()`, Jeedom
fires a `cmd::update` websocket event and the dashboard refreshes the tile by re-calling
`toHtml()` via AJAX. No custom JS widget function is required.

> **Architecture correction (v0.2):** The previous design (v0.1) used `addCmdToObject` —
> a function that does not exist in Jeedom's API. `addCmdToTable` is for the equipment
> config page command table only. Custom dashboard tiles use `toHtml()`.

The tile has **two sections:**
1. **Supervision section** — CSR connection health (green / orange / red badge + label)
2. **Last event section** — last alarm event type, zone, time, and CSR result

---

## File structure additions (Component 6)

```
core/
├── class/
│   └── siaDC09.class.php      ← toHtml() added here (Task 6.1 + 6.3)
└── template/
    ├── dashboard/
    │   └── siaDC09.html       ← Dashboard tile template (Task 6.2)
    └── mobile/
        └── siaDC09.html       ← Mobile tile template (Task 6.6 — same layout)
```

No new commands are created by this component. `addCmdToTable` in `desktop/js/siaDC09.js`
remains as-is — it is for the equipment config page command table, not for the widget.

---

## Task 6.1 — Widget type: PHP `toHtml()` override

**Decision: PHP `toHtml()` + HTML template (Jeedom standard for custom equipment tiles).**

The `siaDC09` eqLogic class overrides `toHtml($_version = 'dashboard')`. The method:

1. Calls `preToHtml($_version)` first — returns cached HTML if tile hasn't changed;
   otherwise returns the standard `$replace` array with Jeedom placeholders
   (`#id#`, `#name#`, `#version#`, `#eqLink#`, `#eqType#`, etc.)
2. Reads current INFO command values
3. Maps `supervision_state` value to a Bootstrap 3 CSS color class
4. Adds custom placeholders to `$replace`
5. Loads and substitutes the HTML template via `getTemplate()`

**Live update mechanism:** `checkAndUpdateCmd()` → Jeedom fires `cmd::update` websocket
event → dashboard JS detects command update on this eqLogic → re-requests the tile HTML
→ `toHtml()` is called again → tile re-renders with current values.

No custom JS wiring is needed. Standard Jeedom handles the update cycle.

---

## Task 6.2 — HTML template `core/template/dashboard/siaDC09.html`

> **Amendment (2026-10-20, story 10-1 correction):** the tile follows the **stock Jeedom
> eqLogic widget markup** (jeedom/core `core/template/{dashboard,mobile}/eqLogic.html`), not a
> Bootstrap `panel`. The v0.2 panel markup left the tile full-width and not resizable in
> dashboard edit mode, with a banner unlike the standard widgets.

Dashboard root: `class="eqLogic eqLogic-widget allowResize allowReorder #custom_layout# #eqType# siaDC09 #category#"`,
`style="width:#width#;height:#height#;#style#"`, plus the standard `data-eqType`,
`data-eqLogic_id`, `data-eqLogic_uid`, `data-version`, `data-translate-category`,
`data-category`, `data-tags` attributes (all placeholders come from `preToHtml()`), and
`data-supervision-interval`. Name banner: `<div class="widget-name">` with the alert icon,
`<a href="#eqLink#">#name_display#</a>` and `.object_name`. Body: plain padded `<div>` with the
badge + label, a rule, then the event line (`.siaDC09-badge`, `.siaDC09-label`,
`.siaDC09-event` — selectors the inline live-refresh script relies on).

The **mobile** root follows the stock mobile markup instead: no `allowResize`, no fixed
width/height (`style="#style#"`), banner in `<center><span class="widget-name">`. The body
and inline script are shared (a level-1 test keeps them identical).

> **Amendment (2026-10-20, story 10-1 visual redesign — SM1 B + SM2 B):** the body is now
> a round badge with a pictogram + label (+ sub-label) and a "Dernier événement" card. No
> hard-coded greys: colors come from `text-success/warning/danger/muted` (the badge ring and
> icon use `currentColor`) and `opacity`, so light and dark themes both work. Rendering is done
> by the inline script from the label texts (no daemon change). Icons use Font Awesome 5 names (what Jeedom 4.5 ships; FA6 names such as fa-circle-check render nothing).
>
> **SM1** — `supervision_state` is 0/1/2 only, so the icon is picked from the `supervision_label`
> text (`daemon.py _supervision_label()`), the state only gives the color:
>
> | Label | Icon | Color |
> |---|---|---|
> | Connexion OK | `fa-check-circle` | green |
> | …initialisation | `fa-spinner fa-pulse` | orange |
> | Connexion dégradée (N/3) | `fa-exclamation-triangle` (counter in sub-label) | orange |
> | Connexion perdue | `fa-unlink` | red |
> | Tentative de reconnexion… | `fa-sync-alt fa-spin` | red |
> | Hors Réseau | `fa-plug` | red |
> | Clé de chiffrement invalide | `fa-key` | red |
> | ARRÊTÉ | `fa-stop-circle` | red |
> | stale (JS) | `fa-clock` | grey |
> | désactivé | `fa-pause-circle` | grey |
>
> An unknown label falls back to an icon by state color. A live label or state push clears the
> stale view.
>
> **SM2** — `event_label` (`{Type} (zone N|utilisateur N) : {état}`) is split on `" : "`.
> Head: type icon (`intrusion fa-user-secret`, `incendie fa-fire`, `panique fa-bell`,
> `armement fa-lock`, `désarmement fa-lock-open`, `annulation fa-undo`) + type + zone/user.
> Status line: `En cours` `fa-spinner fa-pulse` orange · `Confirmée` `fa-check-circle` green ·
> `Refusé` `fa-ban` red · `Sans réponse` `fa-times-circle` red · `Non transmise` `fa-key` red.
> An idle or unparseable label ("Inactif", "Aucun événement…") shows the raw text, dimmed.
> The full label stays in `data-raw` on `.siaDC09-event`; `event_state` is not needed, so no
> `event_state` callback was added.
>
> **Event time** (browser side): from the `event_label` collectDate — the live push's
> `collectDate`, else the `event_label` entry of the `byId(getCmdState)` call. `< 1 min` "à
> l'instant" · `< 60 min` "il y a N min" · same day "il y a N h" · yesterday "hier HH:MM" ·
> older "JJ/MM HH:MM:SS". The text is refreshed every 30 s while the tile is in the page.
>
> **Precise time:** relative texts carry the clock time appended ("il y a 5 min · 14:32:07"); "hier" and the older format include seconds ("hier 14:32:07", "18/09 14:32:07").
>
> **SM1 time:** under the label, same format, from the `supervision_state` collectDate (render: `byId`; live: push `collectDate`). Every supervision frame and RP cyclic test ACK pushes the state (daemon `_send_rp` / `_send_supervision`), so it shows when the link was last seen alive; RP never touches SM2.

### Badge CSS classes (Bootstrap 3)

| `supervision_state` | CSS class | Color |
|---|---|---|
| `2` (HEALTHY) | `text-success` | Green |
| `1` (DEGRADED 1–2, INITIALIZING) | `text-warning` | Orange |
| `0` (DEGRADED 3, TCP_RECONNECTING, NO_NETWORK, STOPPED) | `text-danger` | Red |
| stale (PHP-only detection) | `text-muted` | Grey |
| null (commands not yet created) | `text-muted` | Grey |

The `supervision_label` string distinguishes states within the same badge color — e.g.
`"ARRÊTÉ"` and `"PERDUE"` both map to red but have different labels.

> **HEALTHY label is `"OK"` (static).** If the tile should display a "last seen at HH:MM"
> timestamp for HEALTHY state, read `$supervisionStateCmd->getCollectDate()` directly —
> `collectDate` is updated by `checkAndUpdateCmd()` on every call regardless of value
> change, making it the correct "last push" timestamp without any extra DB write.

---

## Task 6.3 — `toHtml()` PHP implementation

Added to `siaDC09.class.php`. Uses `$cmd->execCmd()`, NOT `getValue()`.

> **Correction (2026-09-25, story 10-3 code review):** this section previously claimed
> `getValue()` was correct and `execCmd()` should be avoided — that was verified WRONG
> against Jeedom core source (`cmd.class.php`): `cmd::event()`, which the daemon's
> `checkAndUpdateCmd()` calls on every push, only writes to the cmd *cache*
> (`setCache()`); it never touches the `value` column `getValue()` reads. For a
> non-historized INFO command, `getValue()` is frozen at cmd-creation time forever.
> `execCmd()` (for `type == 'info'`) reads exactly the cache `event()` writes — it is
> the correct live accessor, with no disabled-equipment-throw risk for `type == 'info'`
> (that guard only applies to `type == 'action'`). This caused a real live bug (frozen
> badge on a freshly created equipment) once already — see memory
> `jeedom-info-cmd-execcmd-vs-getvalue`. Do not revert this a third time.

```php
public function toHtml($_version = 'dashboard') {
    $replace = $this->preToHtml($_version);
    if (!is_array($replace)) {
        return $replace; // served from cache — no re-render needed
    }

    // --- Read INFO commands ---
    $supervisionStateCmd = $this->getCmd('info', 'supervision_state');
    $supervisionLabelCmd = $this->getCmd('info', 'supervision_label');
    $lastEventStatusCmd  = $this->getCmd('info', 'event_label');

    $stateValue = ($supervisionStateCmd) ? intval($supervisionStateCmd->execCmd()) : null;
    $labelValue = ($supervisionLabelCmd) ? $supervisionLabelCmd->execCmd()          : '';
    $eventValue = ($lastEventStatusCmd)  ? $lastEventStatusCmd->execCmd()           : '';

    // Note: stale detection is NOT performed here (see Task 6.4).
    // PHP-side stale detection via collectDate is unreachable when preToHtml()
    // serves cached HTML — which is exactly the zombie daemon scenario.
    // Stale detection is handled client-side in siaDC09.js after tile render.

    // --- Check if equipment is disabled ---
    // If getIsEnable() === 0 (equipment deactivated), render grey badge with "Désactivé" label.
    // This overrides all supervision_state values.
    if ($this->getIsEnable() === 0) {
        $replace['#badge_class#']         = 'text-muted';
        $replace['#supervision_label#']   = htmlspecialchars(__('Désactivé', __FILE__));
    } else {
        // --- Map state to badge class ---
        if ($stateValue === null) {
            $replace['#badge_class#']         = 'text-muted';
            $replace['#supervision_label#']   = htmlspecialchars('—');
        } elseif ($stateValue === 2) {
            $replace['#badge_class#']         = 'text-success';
            $replace['#supervision_label#']   = htmlspecialchars($labelValue ?: '—');
        } elseif ($stateValue === 1) {
            $replace['#badge_class#']         = 'text-warning';
            $replace['#supervision_label#']   = htmlspecialchars($labelValue ?: '—');
        } else { // 0 — includes STOPPED, DEGRADED(3), TCP_RECONNECTING, NO_NETWORK
            $replace['#badge_class#']         = 'text-danger';
            $replace['#supervision_label#']   = htmlspecialchars($labelValue ?: '—');
        }
    }

    $replace['#event_label#'] = htmlspecialchars(
        $eventValue ?: __('Aucun événement depuis le démarrage', __FILE__)
    );

    // Embed supervision interval so JS stale check (Task 6.4) can read it from
    // the tile's data-supervision-interval attribute without an extra AJAX call.
    $replace['#supervision_interval#'] = (int)$this->getConfiguration('sia_supervision_interval', 60);

    return $this->postToHtml(
        $_version,
        template_replace($replace, getTemplate('core', $_version, 'siaDC09', 'siaDC09'))
    );
}
```

**`$cmd->getValue()` vs `execCmd()`:** for a non-historized INFO command, `getValue()` is
frozen at cmd-creation time forever — `cmd::event()` (called by `checkAndUpdateCmd()` on
every daemon push) only writes the cache, never the `value` column `getValue()` reads.
`execCmd()` (for `type == 'info'`) reads exactly that cache, with no side effects and no
disabled-equipment-throw risk (that guard is `type == 'action'`-only) — it is the correct
choice for display. See memory `jeedom-info-cmd-execcmd-vs-getvalue`.

---

## Task 6.4 — Stale detection (JS-side, one-shot after tile render)

**Decision: stale detection in `siaDC09.js`, executed once after the tile is rendered.**

PHP-side stale detection in `toHtml()` is structurally unreachable for the zombie daemon
scenario: when the daemon freezes, no `checkAndUpdateCmd()` is called, no `cmd::update`
WebSocket event fires, and `preToHtml()` serves the cached green HTML indefinitely —
`toHtml()` is never invoked, so the PHP stale check never runs.

The fix: a lightweight JS function runs once per tile render (triggered by the standard
Jeedom `cmd::update` or page-load hook). It fetches `supervision_state.collectDate` via
AJAX and, if stale, overwrites the badge color and label in-place on the already-rendered
tile.

```javascript
function siaDC09_checkStaleness(eqLogicId, supervisionInterval) {
    jeedom.cmd.getStatsByEqLogicId({
        id: eqLogicId,
        success: function(cmds) {
            var stateCmd = cmds.find(function(c) {
                return c.logicalId === 'supervision_state';
            });
            if (!stateCmd || !stateCmd.collectDate) return;
            var staleSince = (Date.now() - new Date(stateCmd.collectDate).getTime()) / 1000;
            if (staleSince > supervisionInterval * 3) {
                $('#eqLogic' + eqLogicId + ' .siaDC09-badge')
                    .removeClass('text-success text-warning text-danger')
                    .addClass('text-muted');
                $('#eqLogic' + eqLogicId + ' .siaDC09-label')
                    .text('<?php echo __("Données non disponibles", __FILE__); ?>');
            }
        }
    });
}
```

`supervisionInterval` is embedded by `toHtml()` as a `data-supervision-interval` attribute
on the tile root element, so the JS can read it without an extra AJAX call.

**When stale is detected:**

| Condition | `supervision_label` display | Badge |
|---|---|---|
| `collectDate` absent | _(no override — commands not yet populated)_ | as rendered |
| `staleSince > 3 × supervision_interval` | `Données non disponibles` | Grey (`text-muted`) |
| All other cases | _(no override — PHP-rendered value stands)_ | Green / Orange / Red |

**Call site** — the function is invoked from the standard Jeedom page-load and
`cmd::update` hooks in `desktop/js/siaDC09.js`. `supervisionInterval` is read
from the `data-supervision-interval` attribute injected by `toHtml()`:

```javascript
// Called once on page load and once per cmd::update for this eqLogic
$(document).on('cmd::update', function(event, updates) {
    updates.forEach(function(update) {
        var $tile = $('[data-eqLogic_id="' + update.eqLogic_id + '"]');
        if (!$tile.length) return;
        var interval = parseInt($tile.data('supervision-interval'), 10) || 60;
        siaDC09_checkStaleness(update.eqLogic_id, interval);
    });
});
// On initial page load
$('[data-eqlogic_id]').filter(function() {
    return $(this).hasClass('siaDC09');
}).each(function() {
    var id       = $(this).data('eqlogic_id');
    var interval = parseInt($(this).data('supervision-interval'), 10) || 60;
    siaDC09_checkStaleness(id, interval);
});
```

**Scope:** fires once on page load and once on each `cmd::update` event for this eqLogic.
No background polling. The `cron5()` watchdog (Task C.4, supervision-design.md) remains the
primary safety mechanism — it sends SMS/push regardless of what the tile shows.

**Assumption: daemon keeps `collectDate` fresh during TCP_RECONNECTING.** During a TCP
reconnect cycle, no supervision frames are sent — `collectDate` would otherwise go stale
within `3 × supervision_interval`. To prevent a false stale warning while the daemon is
alive and reconnecting, `_tcp_reconnect_loop()` calls `_update_info_commands()` after each
failed attempt (~every 10s). See daemon-design.md Task 1.2.

---

## Task 6.5 — Command visibility

All 7 commands are set `isVisible = 0` in `_ensureCommands()` (Task 2.4):

```php
// In _ensureCommands() — isVisible = 0 for all:
['logicalId' => 'burglarAlarm',         ..., 'isVisible' => 0],
['logicalId' => 'fireAlarm',            ..., 'isVisible' => 0],
['logicalId' => 'panicAlarm',           ..., 'isVisible' => 0],
['logicalId' => 'supervision_state',    ..., 'isVisible' => 0],
['logicalId' => 'event_state', ..., 'isVisible' => 0],
['logicalId' => 'supervision_label',    ..., 'isVisible' => 0],
['logicalId' => 'event_label',    ..., 'isVisible' => 0],
```

`toHtml()` renders all display. Individual command widgets are not shown (no Jeedom default
command rows on the tile).

Commands remain accessible in Jeedom scenarios via standard command picker — only the
tile display is suppressed.

---

## Task 6.6 — Mobile template

**Decision: same body as dashboard, stock mobile root and banner.**

`core/template/mobile/siaDC09.html` shares the dashboard body and inline script; only the root
element and name banner follow the stock mobile markup (see Task 6.2 amendment).

---

## `event_label` — display format (unchanged from daemon-design.md)

The daemon formats `event_label` as a complete, user-readable string. The template
displays it verbatim in the last event section.

| SM2 state | `event_label` value |
|---|---|
| IDLE (never fired) | `Aucun événement depuis le démarrage` |
| PENDING | `Intrusion — Salon — envoi en cours (tentative 1/3)` |
| CONFIRMED | `Intrusion — Salon — 14:32:11 — Confirmé par la centrale` |
| FAILED (timeout) | `Intrusion — Salon — 14:32:11 — Échec (3 tentatives)` |
| FAILED (NAK) | `Intrusion — Salon — 14:32:11 — Réponse inattendue de la centrale` |
| FAILED (NO_NETWORK) | `Intrusion — Salon — 14:32:11 — Échec — réseau inaccessible` |

The string wraps naturally in the tile (`word-break:break-word`). No PHP-side string
splitting is needed.

> **v1.1 (Story 13.1):** `BC` and `OP` add rows to this table (`Annulation`, `Désarmement`)
> without changing the template or `event_state`. `BR` has no source event and is out of scope
> (story 13-2, parked) — see "Disarm During an Alarm" at the end of this document.

---

## Impact on other components

### `desktop/js/siaDC09.js` — no JS widget function for dashboard

`addCmdToTable(_cmd)` remains as the only widget function in the JS file — it is for
the equipment config page command table, as required by Jeedom. No `addCmdToObject`,
`printEqLogic`, or custom tile JS is added for the dashboard widget; `toHtml()` handles
all rendering.

### `php-core-design.md` — `_ensureCommands()` visibility update

All 7 commands must have `isVisible = 0` (already noted in Task 2.4; confirmed here).

---

## Design decisions summary

| Decision | Choice | Rationale |
|---|---|---|
| Widget type | PHP `toHtml()` + HTML template | Standard Jeedom mechanism for custom equipment tiles; server-rendered, cache-aware, no custom JS needed |
| Template location | `core/template/dashboard/siaDC09.html` | Standard Jeedom path for plugin equipment templates |
| HTML structure | Stock Jeedom eqLogic widget root + `widget-name` banner (amended 2026-10-20) | Resizable in edit mode, standard banner; the earlier Bootstrap `panel` was non-conformant |
| Badge color | Bootstrap 3 `text-success/warning/danger/muted` | Framework-native, no extra CSS file needed |
| State source | `supervision_state` + `supervision_label` INFO commands | All SM1 states (including STOPPED) are encoded in these commands — no separate daemon PID check needed |
| Value read method | `$cmd->execCmd()` | Reads the cache `checkAndUpdateCmd()` writes on every push; `getValue()` is frozen forever for non-historized INFO commands (see correction in Task 6.3) |
| Stale detection | JS-side, one-shot after tile render via `jeedom.cmd.getStatsByEqLogicId` | PHP stale check in `toHtml()` is unreachable when `preToHtml()` serves cached HTML (zombie scenario) |
| Stale threshold | `3 × supervision_interval` | Consistent with cron5 watchdog threshold |
| Live update | Standard Jeedom `cmd::update` → `toHtml()` re-call | No polling; instant update on SM1/SM2 transition |
| JS daemon state events | **Removed** | APIs (`jeedom.config.byKeys`, `pluginDaemonStateChange`) are non-standard and unverified; `toHtml()` derives state from INFO commands |
| JS stale check | One-shot after render, no polling | Reaches the zombie case that PHP `toHtml()` cannot; cron5 provides the real-time safety net |
| Mobile template | Shared body, stock mobile root/banner | Mobile root has no fixed size or resize class |
| Action command visibility | `isVisible = 0` | Available in scenarios; not shown on tile |
| INFO command visibility | `isVisible = 0` | `toHtml()` renders them; individual command rows would duplicate content |

---

## Testing strategy for Component 6

| Test | How |
|---|---|
| Normal state — healthy | SM1=HEALTHY → verify green `text-success` badge + correct label |
| Supervision degraded | Force strike=1 → verify orange `text-warning` badge |
| Supervision lost | Force strike=3 → verify red `text-danger` badge + `"PERDUE"` label |
| Daemon stopped | Stop daemon (sets `supervision_state=0, label="ARRÊTÉ"`) → verify red badge + `"ARRÊTÉ"` label |
| Stale detection | Set `collectDate` older than `3 × supervision_interval` → reload dashboard → verify grey `text-muted` badge + `"Données non disponibles"` |
| No event yet | SM2=IDLE, never fired → verify `"Aucun événement depuis le démarrage"` in grey event section |
| Alarm confirmed | SM2→CONFIRMED → verify `event_label` shows confirmed string |
| Alarm failed (timeout) | SM2→FAILED → verify red failure string in event section |
| Live update — no reload | Trigger alarm while tile visible → verify tile updates via websocket without page reload |
| Mobile tile | Open mobile view → verify same layout renders correctly |
| Tile caching | Call `toHtml()` twice without cmd update → verify second call returns cached HTML (same string) |
| Action commands hidden | Open Jeedom dashboard → verify no burglarAlarm/fireAlarm/panicAlarm buttons on tile |
| preToHtml cache invalidation | Change `supervision_state` value → verify tile re-renders (cache invalidated) |

---

## Disarm During an Alarm — Story 13.1 design decisions

**Status:** rewritten 2026-09-25 (Sprint Change Proposal, `sprint-change-proposal-2026-09-25.md`).
**Supersedes** the section this replaces (BC shown with a zone label). DC-03 addresses `BC`
(and, in this rescope, `OP`) by **user number**, never a zone — see `php-core-design.md`,
"Disarm During an Alarm", and ADR-18 (`architecture.md`). BR (Burglary Restoral) has no source
event in the alarm plugin and is out of scope — story **13-2** (parked).

### Decision 2 (unchanged) — `event_state` keeps its four values; BC/OP show up in `event_label`

This decision did not depend on the zone-correlation hypothesis that was reversed, so it
survives unmodified. **No new numeric values.** `event_state` stays `0/1/2/3` and applies to
`BC`/`OP` unchanged — a `BC` whose ACK arrives sets `event_state = 1`, exactly like a `BA`. The
*kind* of the last event is carried by `event_label`.

`event_state` measures **delivery status**, not event kind. The two are orthogonal axes and
adding new numeric values would collapse them, with three concrete costs:

1. **It breaks every existing scenario trigger.** The documented contract is
   `event_state == 1` → "last transmission confirmed", `== 2` → "failed"
   (`php-core-design.md`, "Scenario use examples"). A confirmed `BC`/`OP` landing on a new value
   would stop matching a user's "transmission OK" scenario.
2. **It would be invisible anyway.** Nothing renders `event_state` today: the dashboard and
   mobile templates interpolate `#event_label#` only, `toHtml()` reads `event_label` for the
   event section (`supervision_state` drives the badge), and
   `siaDC09_loadDiagnosticData()` in `desktop/js/siaDC09.js` consumes
   `supervision_state`, `supervision_label`, `errors` and `messages` — it drops both
   `event_state` and `event_label`. New values would add scenario breakage with no UI gain.
3. **The `returnStateValue = 0` auto-revert is calibrated on "3 = in progress".** A new
   terminal value would need its own reasoning about the 30-minute reset; `1`/`2` already
   have it.

`BC`/`OP`/`CL` are therefore expressed through the SIA code → French label map, extended in
the same change: `BA → Intrusion`, `FA → Incendie`, `PA → Panique`, **`BC → Annulation`**,
**`OP → Désarmement`**, **`CL → Armement`** (story 13-4).

### `event_label` rows added by Story 13.1

> **Note de conception 2026-09-25 (Task 1, reconciliation post-implémentation).** La première
> version de ce tableau (séparateur em-dash, horodatage, compteur de tentatives) ne correspondait
> à aucun format réellement livré : `_event_context_prefix()`/`_event_label_from_sm2()`
> (`daemon.py`) produisent depuis la story 10-3 le format `"{Type} (zone {zone}) : {état}"` — pas
> d'horodatage, séparateur ` : `. Ce tableau est corrigé pour refléter ce format réel, simplement
> étendu à `"{Type} (utilisateur {n}) : {état}"` pour `BC`/`OP` (l'AC7 de la story, écrite après
> vérification du code livré, utilise déjà ce format).

| Event / SM2 state | `event_label` |
|---|---|
| `BC` PENDING | `Annulation (utilisateur 1) : En cours` |
| `BC` CONFIRMED | `Annulation (utilisateur 1) : Confirmée par la centrale` |
| `BC` FAILED (NAK) | `Annulation (utilisateur 1) : Refusé par la centrale` |
| `BC` FAILED (timeout) | `Annulation (utilisateur 1) : Sans réponse de la centrale` |
| `OP` CONFIRMED | `Désarmement (utilisateur 1) : Confirmée par la centrale` |
| `CL` CONFIRMED | `Armement (utilisateur 1) : Confirmée par la centrale` |

The label always shows the configured user number — never a zone segment, and never omitted:
unlike `zone_number`, `user_number` has no "unresolved" case. A disarm during an open alarm
produces exactly two rows in quick succession (`BC` then `OP`, via `disarm`); a mode-change
reset produces exactly one (`BC`, via `alarmReset`); a normal disarm outside any alarm context
produces exactly one (`OP` alone, via `disarm`'s `else` branch — story 13-4); an arm produces
exactly one (`CL`, via `arm` — story 13-4) — each an ordinary, independent SM2 event with its
own label.

### What AC7 actually requires

| Surface | Change needed |
|---|---|
| `event_state` numeric values | **none** — 0/1/2/3 unchanged |
| Badge classes / `supervision_state` mapping | **none** |
| `core/template/{dashboard,mobile}/siaDC09.html` | **none** — `#event_label#` is rendered verbatim |
| `toHtml()` | **none** — reads `event_label` as-is |
| Daemon `_event_context_prefix()` | branches on `sia_code`: `"(utilisateur {n})"` for `BC`/`OP`/`CL` (story 13-4 adds `CL` via `_USER_ADDRESSED_SIA_CODES`, replacing the original hardcoded `("BC", "OP")` tuple) via a new `_event_user_number` instance var, `"(zone {zone})"` for `BA`/`FA`/`PA` unchanged |
| Diagnostic tab (`desktop/js/siaDC09.js`) | display `event_label` (and `event_state`), which `siaDC09_loadDiagnosticData()` currently discards although `getDiagnosticData` already returns both — **not done by this story**, left as a pre-existing gap outside Story 13.1's scope |

### Deferred — numeric `event_type` command

If a user ever needs a scenario to trigger on "the cancellation was transmitted", the clean
extension is a **separate** numeric INFO command `event_type`
(`0` aucun, `1` intrusion, `2` incendie, `3` panique, `4` annulation, `5` désarmement — and a
slot reserved for `6` rétablissement if story 13-2 is ever unparked) alongside the unchanged
`event_state`. Two orthogonal commands, no breakage. Deferred to v1.2 — it is not needed by
Story 13.1.
