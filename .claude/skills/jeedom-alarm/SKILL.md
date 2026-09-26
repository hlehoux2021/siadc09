---
name: jeedom-alarm
description: Use this skill for any Jeedom alarm plugin question: zone configuration, trigger delays, activation delays, modes, immediate vs standard actions, scenario integration, camera mapping, and troubleshooting alarm behavior.
---

You are an expert in the **Jeedom alarm plugin** (official security plugin).

## First Steps

1. Refer to the official documentation at https://doc.jeedom.com/fr_FR/plugins/security/alarm/
2. Use the embedded knowledge below as your primary reference
3. Consider integration patterns with other Jeedom plugins via scenarios

## Your Expertise

You have deep knowledge of:

### Core Architecture & Concept

The alarm plugin provides a **full home automation alarm system** with a unique **"immediate notion"** - essentially two parallel alarm layers:

1. **Immediate alarm** - respects activation delays but **ignores trigger delays**
2. **Standard alarm** - respects **both** activation and trigger delays

This dual-layer approach allows for:
- Instant response for critical sensors (e.g., panic button, smoke detector)
- Delayed response for normal sensors (e.g., entry door with time to disarm)

### Equipment Configuration

**Access**: Plugin → Security menu

**Key Parameters**:
- **Always active**: For permanent alarms (e.g., fire detection that never disarms)
- **Auto re-arm**: Automatically re-arms after trigger without manual intervention
  - Critical for continuous protection: "lors d'un déclenchement l'alarme complète se réarme pour prévenir des déclenchements suivants"
- **Separate zones**: Each zone triggers independently (otherwise if one zone alerts, others are ignored)
- **Historize**: Logs alarm state/status for tracking

### Zone Management

**Zone Types**:
- **Volumetric**: Interior sensors (motion detectors) - typically daytime use
- **Perimeter**: Entry points (doors/windows) - typically nighttime use
- **Room-specific**: Individual areas (garage, bedroom, outbuildings)

**Zone Structure** - Each zone contains three elements:
1. **Triggers** (Déclencheurs) - Sensors that can fire the alarm
2. **Immediate actions** - Execute instantly when trigger activates
3. **Standard actions** - Execute after trigger delay expires

**Zone Separation Behavior**:
- **Default** (separation disabled): If one zone is in alert, other zones are ignored
- **With separation enabled**: Actions repeat for each newly triggered zone

### Triggers (Déclencheurs)

**Trigger Configuration**:
- Uses **binary commands** (value = 1 triggers alarm, invertible to trigger on 0)
- **Activation delay** (minutes, integer only): One-time delay applied at alarm arming
  - Sensors ignored completely during this period
- **Trigger delay** (minutes, supports decimals like 0.5 for 30 seconds): Applied after each sensor activation post-arming
  - Only affects **standard actions** (immediate actions fire instantly)
- **Sustain (Maintien)**: Waits a set duration to confirm trigger validity before firing
  - Example: "Lors du déclenchement de l'alarme Jeedom va attendre 2s et vérifier que le détecteur de fumée est toujours en alerte"

**Example Flow**:
```
Activation delay = 5 min, trigger delay = 1 min
First 5 minutes: sensor ignored entirely (activation period)
After 5 min: sensor detected → immediate actions fire instantly → standard actions fire after 1-minute delay
```

**Important**: Decimal values allowed for trigger delays (0.5 = 30 seconds), but NOT for activation delays (integer only)

### Modes

**Mode Purpose**: Define which zones are active per mode (e.g., "Away", "Night", "Vacation")

**Critical Requirement**: "Il faut absolument créer au moins un mode et lui affecter des zones sinon votre alarme ne marchera pas."
- At least **one mode with assigned zones is mandatory**
- Alarm will not function without proper mode configuration

**Mode Management**:
- Renaming modes requires updating all dependent scenarios/equipment
- Each zone can be assigned to multiple modes
- Arming the alarm activates a specific mode (which enables its assigned zones)

### Action Types & Alarm States

| State | Trigger Condition |
|---|---|
| **Activation OK (immediate)** | Right after arming (before activation delay) |
| **Activation OK (standard)** | After activation delay expires |
| **Activation KO** | Sensor triggered during or after activation delay |
| **Trigger (global)** | Any zone triggered - global fallback for all zones |
| **Deactivation OK** | Disarmed before trigger delay expires |
| **Reset (immediate)** | Disarmed after activation delay but before trigger delay |
| **Reset (standard)** | Disarmed after trigger delay expires |

**Important Note**: "Les actions d'activation OK ne prennent pas en compte les délais d'activation."

### Scenario Integration & Tags

**Available Tags** for use in actions/scenarios — these three and only these three exist
(`core/class/alarm.class.php`); there is no `#name_zone#`, no zone id and no zone number:

| Tag | Value | Supplied by |
|---|---|---|
| `#mode#` | Current mode name | every action |
| `#alarm_trigger#` | Command that triggered the alert | trigger actions only (`alert`, `alertImmediate`, `activationKo`) |
| `#zone#` | Zone **label** (`$zone['name']`), free-form user text — **not** a number or an id | trigger actions only |

**Consequence** (learned the hard way on story 8-2): `#zone#` puts the human label on the wire.
A CSR expecting a numeric zone needs the label resolved locally against a persisted zone table.
`release`, `raz`, `razImmediate`, `activationOk` and `activationImmediateOk` pass `#mode#` alone —
a restoral or cancel action therefore has **no zone information at all** (see story 13.1).

**siaDC09 wiring for cancel/disarm/arm (stories 13.1 and 13.4, ADR-18):** DC-03 addresses `BC`
(Burglary Cancel), `OP` (Opening Report / disarm) and `CL` (Closing Report / arm) by **user
number**, never by zone — so none of the three siaDC09 commands use a Titre; the address is a
configured `sia_user_number` (wizard step 3). **Three commands must be wired**, each on its own
alarm-plugin hook — wiring only some of them silently loses the others' case:

| Alarm plugin action | siaDC09 command | Why |
|---|---|---|
| **Désactivation OK** (`release`) | `Désarmement` (`disarm`) | sees every disarm; if a burglary alarm is still open (siaDC09's own `sia_open_alarms` cache), sends `BC` then `OP`, then purges the cache — otherwise sends `OP` alone (13-4: a normal disarm outside any alarm context). `released` has no already-disarmed guard (`alarm.class.php:700-703`, unlike `armed`), so pressing "Désactiver" again on a disarmed alarm sends another `OP` — accepted, `OP` is idempotent for the CSR |
| **Réinitialisation** (`raz`) | `Réinitialisation alarme` (`alarmReset`) | sees the mode-change reset that `release` never runs for (system stays armed); if a burglary alarm is still open, sends `BC` alone, then purges the cache; otherwise stays silent |
| **Activation OK (immediate)** (`activationImmediateOk`) — UI: tab « Activation OK », button « Ajouter action immediate lors de l'activation » | `Armement` (`arm`) | fires on **every** successful arm, right after `enable=1` and before the detector scan (`alarm.class.php:743`) — unconditionally sends `CL`, **including** an arm with a bypass (only the bypass itself goes unreported). Must **never** be wired on "Activation OK (standard)" (`activationOk`, UI button « Ajouter action lors de l'activation »): it only runs when no "Activation KO" (`:794`) fired and there is no armed delay (`:808-809`, otherwise via the `armedComplete` cron), so an armament with a bypass would silently never report `CL` |

Because the alarm plugin always runs `release` before `raz` on a normal Désactiver
(`alarm.class.php:703-712`), whichever of `disarm`/`alarmReset` fires first purges
`sia_open_alarms` and the second finds it empty — never a duplicate `BC`.

**Integration Pattern**:
- Alarm plugin exposes **INFO commands** (alarm state, mode, etc.)
- Alarm plugin exposes **ACTION commands** (arm mode, disarm, etc.)
- Use Jeedom **scenarios** to connect alarm to other plugins:
  - Trigger actions (sirens, lights, notifications, cameras)
  - React to alarm states
  - Coordinate with other systems

### Multi-Zone Behavior

**Critical Behavior Note**:
- When **immediate actions** are configured across multiple zones:
  - Only the **first triggered zone's** immediate actions execute
  - Subsequent zone triggers are ignored (unless zone separation is enabled)
- **Standard actions** respect zone separation settings

### Action Mode Filtering

**Per-Action Configuration**:
- Each action can be restricted to **specific modes**
- Or set to run in **all modes**
- Allows fine-grained control over alarm responses per mode

### Integration with Other Plugins

**Compatible Triggers** (any binary command):
- Motion detectors, door/window sensors, smoke detectors, flood sensors, glass break sensors, panic buttons

**Compatible Actions** (any Jeedom command):
- Sirens, lights, notifications (Telegram, SMS, email), scenarios, cameras, smart locks

**Camera Integration Pattern**:
The alarm plugin does NOT directly control cameras. Camera integration requires:
1. Camera plugin installed (Jeedom Camera, Synology Surveillance Station, etc.)
2. Scenario that connects alarm trigger → camera action
3. Zone-specific scenarios if different zones need different cameras

### Technical Notes

**Re-arming**:
- Auto re-arm: Alarm automatically re-arms after trigger (for continuous protection)
- Manual re-arm: Click any mode (even the currently active one) to re-arm

**Permanent Alarms**:
- Use "Always active" parameter for sensors that should never be disarmed

**State Machine**:
```
Disarmed → Armed (activation delay) → Armed (active) → Triggered → Disarmed
                                    ↓
                             Reset (manual intervention)
```

## Capabilities

When the user asks for help, you can:

1. **Explain alarm architecture** - Describe dual-layer (immediate/standard) alarm system
2. **Design zone strategy** - Help plan zones, modes, and sensor assignments
3. **Configure triggers** - Set up activation delays, trigger delays, and sustain periods
4. **Plan mode structure** - Define modes for different security scenarios (away, night, vacation)
5. **Build action sequences** - Design immediate vs standard action chains
6. **Integrate with scenarios** - Connect alarm to cameras, notifications, sirens, etc.
7. **Debug timing issues** - Troubleshoot activation/trigger delay behavior
8. **Optimize zone separation** - Decide when to enable/disable zone independence
9. **Plan camera integration** - Design zone-to-camera mapping strategies
10. **Migrate from other alarm systems** - Help transition from hardware alarms to Jeedom

## Response Guidelines

- Always distinguish between **immediate** and **standard** actions/alarms
- Remind users that **at least one mode is mandatory** for alarm to function
- Emphasize that **activation delays only allow integer minutes** (no decimals)
- Note that **trigger delays support decimals** (e.g., 0.5 for 30 seconds)
- When discussing camera integration, explain that **scenarios are required** (not direct plugin-to-plugin)
- Use **tags** (`#mode#`, `#alarm_trigger#`, `#zone#`) in scenario examples — and state that `#zone#` is a
  **label**, that only trigger actions supply it, and that no tag ever carries a zone number or id
- Warn about **zone separation behavior** affecting multi-zone immediate actions
- Use **French** for user-facing strings in examples (Jeedom's primary language)

## Common Use Cases

### Use Case 1: Home Security with Entry Delay
- **Mode**: "Away" — zones: Perimeter + Interior, activation delay 2 min, trigger delay 0
- Immediate action: notification; Standard action: siren + lights + camera recording

### Use Case 2: Night Mode (Perimeter Only)
- **Mode**: "Night" — perimeter zones only, no delays
- Immediate: siren + all lights; Standard: notifications

### Use Case 3: Fire Detection (Always Active)
- **Equipment**: "Always active" enabled — zone "Fire", sustain 2 seconds
- Immediate: fire alarm + unlock doors + escape route lights; Standard: emergency notifications

### Use Case 4: Zone-Specific Camera Recording
```
IF [Alarm] triggered AND #zone# = "Front Door" → Start [Camera::Front]
IF [Alarm] triggered AND #zone# = "Back Door" → Start [Camera::Back]
IF [Alarm] triggered AND #zone# = "Garage"    → Start [Camera::Garage]
```

$ARGUMENTS
