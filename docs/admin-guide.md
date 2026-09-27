# siaDC09 — Administrator Guide

For the person who installs and maintains the plugin on a Jeedom box: where the configuration lives, how to back it up and restore it, and how upgrades work. For day-to-day use (wizard, Alarm plugin wiring, status indicators, troubleshooting), see the French [user guide](fr_FR/index.md). For the code, see the [developer guide](developer-guide.md).

## Contents

1. [Components on the box](#components-on-the-box)
2. [Configuration keys](#configuration-keys)
3. [Daemon lifecycle](#daemon-lifecycle)
4. [Logs](#logs)
5. [Backup and restore](#backup-and-restore)
6. [Upgrade path](#upgrade-path)
7. [Security notes](#security-notes)

---

## Components on the box

| Component | Location | Role |
|-----------|----------|------|
| PHP plugin | `/var/www/html/plugins/siaDC09/` (`core/`, `desktop/`, `plugin_info/`) | Equipment, commands, wizard, widget, diagnostic tab, daemon start/stop, 5-minute freshness watchdog (`cron5`) |
| Python daemon | `resources/siadc09d/siadc09d.py` | SIA DC-09 transmitter: supervision, events, error handling, Frigate prefetch |
| Python venv | managed by Jeedom (`system::getCmdPython3`) | `jeedomdaemon==1.2.9`, `cryptography==43.0.3` from `plugin_info/packages.json` |
| PID file | `jeedom::getTmpFolder('siaDC09')/daemon.pid` | Used by `deamon_info()` to report the daemon state |
| Local IPC | TCP `127.0.0.1:<socketport>` (default `55009`) | PHP → daemon JSON commands |
| Callback | `core/php/jeesiaDC09.php` over the internal Jeedom URL | Daemon → PHP updates, authenticated with the plugin API key |

There is exactly **one** siaDC09 equipment (created automatically, "Télésurveillance"). The daemon talks to **one** receiver.

**Network:** the box must be able to open an outbound connection to the receiver's IP/port (TCP or UDP). Nothing is exposed inbound. If Frigate media is used, the *monitoring centre* must be able to reach the Frigate URL entered in the wizard — that is your reverse-proxy/firewall concern, not the plugin's.

## Configuration keys

### Equipment configuration (`eqLogic->getConfiguration()`)

All set by the wizard; stored in the Jeedom database with the equipment.

| Key | Default | Wizard step | Meaning | Passed to daemon as |
|-----|---------|-------------|---------|---------------------|
| `csr_ip` | `''` | 1 | Receiver IP. Must not be empty or `TBD` | `--host` |
| `csr_port` | `0` | 1 | Receiver port, 1-65535 | `--port` |
| `transport` | `udp` | 1 | `udp` or `tcp` | `--transport` |
| `account_number` | `''` | 1 | 3-16 hex chars | `--account` |
| `encryption_enabled` | `false` | 1 | Encryption flag — see [Security notes](#security-notes) | `--encryption-enabled` |
| `encryption_key` | `''` | 1 | AES key, 32/48/64 hex chars; required when encryption is enabled | `--encryption-key` |
| `supervision_interval` | `60` | 1 | Seconds between supervision frames; also drives the stale-widget and watchdog thresholds (3 × interval) | `--supervision-interval` |
| `retry_count` | `6` | 1 | **TCP reconnection** attempts before "Hors Réseau" (does not change alarm retries, which are fixed at 4 attempts) | `--retry-count` |
| `reconnect_delay` | `30` | 1 | Base TCP reconnection delay, seconds | `--reconnect-delay` |
| `crc_format` | `hex` | — (no UI) | `hex` or `bin`. **The daemon always sends ASCII hex CRC** regardless | `--crc-format` |
| `receiver_prefix` | `''` | — (no UI) | Optional SIA receiver number (`R…`) | `--receiver-prefix` |
| `account_prefix` | `''` | — (no UI) | Optional account prefix (`L…`) | `--account-prefix` |
| `sia_zone_mappings` | `[]` | 3 | Alarm zone name → SIA zone number and optional Frigate camera. Numbers are stable: a zone keeps its number, new zones get the next free one | resolved by PHP, sent with each command |
| `frigate_media_url_template` | `''` | 3 | Public Frigate URL **with literal placeholders** (`<user>`, `<pass>`, `<token>`) — never a real credential | resolved by PHP, sent with each command |
| `sia_user_number` | — | 3 | 1-999, user number for OP/CL/BC | resolved by PHP, sent with each command |
| `sia_notify_kind` | `''` | 4 | `cmd` (a Jeedom message action) or `internal` | — |
| `sia_notify_cmd_id` | `0` | 4 | Target command ID when `kind = cmd` | `--notify-cmd-id` |
| `sia_notify_internal` | `''` | 4 | `message` (message centre) or `scenario` | — |
| `sia_notify_scenario_id` | `0` | 4 | Target scenario when `internal = scenario` | — |
| `sia_wizard_step` | `0` | all | Wizard progress; the daemon is not launchable before the wizard is finished | — |

The daemon reads its settings **once, at start**. Any change needs a daemon restart (deferred item D-40).

`crc_format`, `receiver_prefix` and `account_prefix` have no UI field. They only change through a direct database edit or a future UI; leave them at their defaults unless the monitoring centre asks otherwise.

### Plugin configuration (`config::byKey(..., 'siaDC09')`)

| Key | Default | Meaning |
|-----|---------|---------|
| `socketport` | `55009` | Local daemon IPC port. No UI field: change it with `config::save('socketport', <port>, 'siaDC09')` only if another plugin already uses 55009, then restart the daemon |
| `autoStartDeamon` | `1` | Standard Jeedom daemon auto-management |
| `sia_last_errors` | `[]` | JSON, last 10 T2/T3 errors shown in the diagnostic tab |
| `sia_last_messages` | `[]` | JSON, last 50 protocol exchanges shown in the protocol inspector |
| `_freshness_alert_ts` | `0` | Timestamp of the last "Démon bloqué" alert (rate limit: one per 30 min) |

### Commands (logical IDs)

Action: `burglarAlarm`, `fireAlarm`, `panicAlarm`, `prefetchEvent` (subType `message`, Titre = `#zone#`), `disarm`, `alarmReset`, `arm` (subType `other`).
Info: `supervision_state` (0/1/2), `supervision_label`, `event_state` (0/1/2/3), `event_label`.

Commands are (re)created by `postSave()`, and by `siaDC09_update()` on every plugin upgrade, so an upgrade adds new commands without the equipment being re-saved.

## Daemon lifecycle

`deamon_info()` reports **not launchable** — with a message pointing to the wizard step to fix — while any of these is true:

1. the wizard is not finished;
2. `csr_ip` is empty or `TBD`, or `csr_port` / `account_number` is invalid;
3. encryption is enabled without a key;
4. no critical-notification target is configured (step 4).

Dependencies are checked by the Jeedom core wrapper, not by the plugin.

`deamon_start()` builds the command line from the keys above (the AES key is redacted in the `siaDC09` log line), starts `siadc09d.py` in the venv and waits up to 10 s for the PID file. Jeedom's watchdog restarts a crashed daemon when auto-management is on. In TCP, when all reconnection attempts fail the daemon reports "Hors Réseau" and exits; the watchdog then restarts it.

**Watchdog (`cron5`).** Every 5 minutes, if the daemon is running but `supervision_state` has not been updated for more than 3 × `supervision_interval`, the plugin sends "siaDC09 — Démon bloqué" to the step-4 target (at most once per 30 minutes).

**Startup delay.** The first supervision frame goes out one full interval after start, so the widget stays orange for about one interval (D-42).

## Logs

| Log | Content |
|-----|---------|
| `siaDC09` | PHP side: daemon launch (key redacted), command execution, callback handling, watchdog |
| `siaDC09_daemon` | Daemon: startup line `Démon SIA DC-09 version X.Y.Z`, state transitions, frames, errors |
| `siaDC09_update` / dependency log | Dependency installation |

INFO, WARNING and ERROR lines are in French; DEBUG lines are in English and include the hex frames. Set the plugin log level to **Debug** before reproducing an issue to get the technical detail. The AES key is never logged.

## Backup and restore

siaDC09 has no export format of its own; it relies on the standard **Jeedom backup** (Settings → System → Backups), which contains:

- the **database** — the siaDC09 equipment and its configuration (every key in the equipment table above, including `encryption_key` and the zone mappings), its commands, and the plugin configuration keys;
- the **plugin files** under `plugins/siaDC09/`.

The Python venv is not something to restore: reinstall the dependencies after a restore.

**Restore on the same or a new box:**

1. Restore the Jeedom backup (Settings → System → Backups → Restore).
2. Open the plugin configuration page and **reinstall the dependencies**; wait for OK.
3. Check the equipment page: the **Configuration active** panel should show your receiver, zones and notification target.
4. Start the daemon and confirm **Connexion OK** on the widget within about 2 supervision intervals.
5. The Alarm plugin keeps its references to the siaDC09 commands only if their IDs are unchanged (full restore). If you rebuilt the equipment by hand instead, re-wire the Alarm plugin actions ([user guide](fr_FR/index.md#câbler-le-plugin-alarme)) and re-check the step-4 target, since it is stored as a command or scenario ID.

**What a backup does not cover:** the zone-number ↔ zone-name table registered at the monitoring centre. Keep a copy of step 3 (or the Configuration active panel) with your monitoring-centre paperwork.

Because the backup contains the AES key and the monitoring-centre account in clear, store backups as carefully as the key itself.

## Upgrade path

1. The Market publishes a new version. Jeedom offers the update in **Plugin management**; install it.
2. Jeedom runs `siaDC09_update()`, which calls `postSave()` on the equipment and creates any new command. Existing configuration is untouched.
3. If `packages.json` changed, Jeedom reinstalls the dependencies (`jeedomdaemon` is marked `reinstall`).
4. **Restart the daemon** (Jeedom normally does it after a plugin update). Check that `siaDC09_daemon` logs the new `Démon SIA DC-09 version X.Y.Z`: this is how you confirm the running daemon matches the installed plugin.
5. Read the [changelog](fr_FR/changelog.md) for new Alarm-plugin wiring (for example, a new command to add to a zone action).

### Version discipline (maintainer)

Two numbers must move together before every Market publish:

- `plugin_info/info.json` → `pluginVersion`
- `resources/siadc09d/__init__.py` → `DAEMON_VERSION`

`tests/level1/test_daemon_version.py` fails if they differ or if either is not `MAJOR.MINOR.PATCH`. Update the changelog (`docs/fr_FR/changelog.md`, French only) in the same commit. The publishing steps are in the [Market submission checklist](../internal-docs/market-submission-checklist.md).

## Security notes

- **Encryption is not effective yet.** `encryption_enabled` only adds the `*` marker to supervision frames; their body is plaintext and alarm frames are always sent unencrypted. Do not rely on it for confidentiality, and check with the monitoring centre before enabling it — a receiver that requires AES will likely reject the frames.
- **AES key storage.** `encryption_key` is stored **unencrypted** in the equipment configuration (it is not declared in `$_encryptConfigKey`), so it is included in clear in every Jeedom backup. It is also passed on the daemon's **command line** (`--encryption-key`), so any local user who can list processes on the box can read it. It is redacted from the Jeedom log.
- **Frigate URL.** Only literal placeholders (`<user>`, `<pass>`, `<token>`) may be stored. The monitoring centre substitutes the real credentials on its side. Never put a real password in `frigate_media_url_template`: it travels in every alarm frame.
- **Callback authentication.** `jeesiaDC09.php` accepts only requests carrying the plugin API key; the IPC socket listens on `127.0.0.1` only.
