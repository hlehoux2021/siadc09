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

Uses **Jeedom Bootstrap 3 panel** conventions.

```html
<div class="eqLogic-widget allowReorder #eqType#"
     data-eqLogic_id="#id#"
     data-version="#version#"
     data-supervision-interval="#supervision_interval#">

  <div class="panel panel-default" style="margin-bottom:0;">

    <!-- Header: equipment name + link to config -->
    <div class="panel-heading cursor"
         onclick="jeedomUtils.loadPage('#eqLink#')"
         style="padding:5px 8px;">
      <i class="fas fa-tower-broadcast" style="margin-right:4px;"></i>
      <span style="font-weight:bold;font-size:0.95em;">#name#</span>
    </div>

    <div class="panel-body" style="padding:8px 10px;">

      <!-- Section 1: Supervision badge + label -->
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:5px;">
        <i class="fas fa-circle #badge_class#" style="font-size:0.75em;"></i>
        <span style="font-size:0.9em;">#supervision_label#</span>
      </div>

      <hr style="margin:4px 0;" />

      <!-- Section 2: Last alarm event -->
      <div style="font-size:0.8em;color:#555;word-break:break-word;">
        #event_label#
      </div>

    </div>
  </div>

</div>
```

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

Added to `siaDC09.class.php`. Uses `$cmd->getValue()` (last stored value from DB)
rather than `execCmd()` to avoid re-querying the device.

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

    $stateValue = ($supervisionStateCmd) ? intval($supervisionStateCmd->getValue()) : null;
    $labelValue = ($supervisionLabelCmd) ? $supervisionLabelCmd->getValue()          : '';
    $eventValue = ($lastEventStatusCmd)  ? $lastEventStatusCmd->getValue()           : '';

    // Note: stale detection is NOT performed here (see Task 6.4).
    // PHP-side stale detection via collectDate is unreachable when preToHtml()
    // serves cached HTML — which is exactly the zombie daemon scenario.
    // Stale detection is handled client-side in siaDC09.js after tile render.

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

    $replace['#event_label#'] = htmlspecialchars(
        $eventValue ?: 'Aucun événement depuis le démarrage'
    );

    // Embed supervision interval so JS stale check (Task 6.4) can read it from
    // the tile's data-supervision-interval attribute without an extra AJAX call.
    $replace['#supervision_interval#'] = (int)$this->getConfiguration('supervision_interval', 60);

    return $this->postToHtml(
        $_version,
        template_replace($replace, getTemplate('core', $_version, 'siaDC09', 'siaDC09'))
    );
}
```

**`$cmd->getValue()` vs `execCmd()`:** For INFO commands, `getValue()` returns the last
value stored in the DB by `checkAndUpdateCmd()`. `execCmd()` goes through the full
execution path. `getValue()` is the correct choice for display — it reads exactly what
`checkAndUpdateCmd()` wrote, without side effects.

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
                    .text('Données non disponibles');
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

**Decision: same layout as dashboard.**

`core/template/mobile/siaDC09.html` is identical to the dashboard template. Bootstrap 3
panels are fluid width and render correctly on mobile without changes. No separate layout
is needed for v1.0.

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
| HTML structure | Bootstrap 3 `panel` + `panel-body` | Jeedom convention; consistent with other plugin tiles |
| Badge color | Bootstrap 3 `text-success/warning/danger/muted` | Framework-native, no extra CSS file needed |
| State source | `supervision_state` + `supervision_label` INFO commands | All SM1 states (including STOPPED) are encoded in these commands — no separate daemon PID check needed |
| Value read method | `$cmd->getValue()` | Last DB-stored value; correct for display; no re-query side effects |
| Stale detection | JS-side, one-shot after tile render via `jeedom.cmd.getStatsByEqLogicId` | PHP stale check in `toHtml()` is unreachable when `preToHtml()` serves cached HTML (zombie scenario) |
| Stale threshold | `3 × supervision_interval` | Consistent with cron5 watchdog threshold |
| Live update | Standard Jeedom `cmd::update` → `toHtml()` re-call | No polling; instant update on SM1/SM2 transition |
| JS daemon state events | **Removed** | APIs (`jeedom.config.byKeys`, `pluginDaemonStateChange`) are non-standard and unverified; `toHtml()` derives state from INFO commands |
| JS stale check | One-shot after render, no polling | Reaches the zombie case that PHP `toHtml()` cannot; cron5 provides the real-time safety net |
| Mobile template | Same as dashboard | Fluid Bootstrap panel renders correctly on mobile without changes |
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
