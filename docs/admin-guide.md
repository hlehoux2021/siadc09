# siaDC09 — Administrator Guide

For the person who installs and maintains the plugin on a Jeedom box: what runs on the box, how to back it up and restore it, and how upgrades work. For day-to-day use (wizard, Alarm plugin wiring, status indicators, troubleshooting), see the French [user guide](fr_FR/index.md).

## Contents

1. [What runs on the box](#what-runs-on-the-box)
2. [Configuration](#configuration)
3. [Daemon](#daemon)
4. [Logs](#logs)
5. [Backup and restore](#backup-and-restore)
6. [Upgrade path](#upgrade-path)
7. [Security notes](#security-notes)

---

## What runs on the box

| Component | Role |
|-----------|------|
| PHP plugin (`plugins/siaDC09/`) | Equipment, commands, configuration wizard, widget, diagnostic tab, daemon start/stop, 5-minute freshness watchdog |
| Python daemon | Sends the SIA DC-09 frames: supervision, periodic test, alarm events, error handling, Frigate photo retrieval, optional FTP/FTPS photo upload |
| Python virtual environment | Managed by Jeedom; dependencies are installed from the plugin's dependency panel |

There is exactly **one** siaDC09 equipment (created automatically, "Télésurveillance"). The daemon talks to **one** receiver, with no failover.

**Network:** the box must be able to open an outbound connection to the receiver's IP and port (TCP or UDP). Nothing is exposed inbound. The daemon and the plugin talk to each other on the box only (local port `55009` by default). Photos and videos depend on the transport chosen in the wizard:

- **Address (URL):** the *monitoring centre* must be able to reach the Frigate address entered in the wizard. That is your reverse-proxy and firewall concern, not the plugin's.
- **FTPS:** the box must also be able to open an outbound FTP/FTPS connection (port 21 by default) to the monitoring centre's server. The wizard has a connection test for both the receiver and the FTP(S) server (see the [FTP/FTPS page](fr_FR/media-ftps.md)).

## Configuration

All settings are entered in the plugin's three-step wizard (1 Centrale, 2 Test, 3 Zones et alertes), described in the [user guide](fr_FR/index.md#lassistant-de-configuration) and stored in the Jeedom database with the equipment. There is nothing to edit by hand in normal use.

- **Restart the daemon after any change.** The daemon reads its settings once, when it starts.
- **Local port.** If another plugin already uses port `55009`, change the plugin's `socketport` setting with `config::save('socketport', <port>, 'siaDC09')`, then restart the daemon. There is no interface field for it.
- **Daemon auto-management** is the standard Jeedom one (`autoStartDeamon`, on by default).

## Daemon

The daemon refuses to start, with a message that points to the wizard step to fix, while the configuration is incomplete or inconsistent:

- the wizard is not finished;
- the receiver address, port, transport or account number is missing or invalid;
- the periodic frames are inconsistent (for example no supervision frame and no periodic test, or a periodic-test interval outside 60 to 86400 seconds);
- photo/video by address is enabled without a Frigate address;
- encryption is enabled without a valid key;
- no critical-notification target is configured.

Dependencies are checked by Jeedom, not by the plugin.

Jeedom's watchdog restarts a crashed daemon when auto-management is on. In TCP, when every reconnection attempt fails, the daemon shows "Hors Réseau" and stops; the watchdog then restarts it.

**Freshness watchdog.** Every 5 minutes, if the daemon is running but the supervision state has not been updated for more than three supervision intervals, the plugin sends "siaDC09 — Démon bloqué" to the critical-notification target (at most once every 30 minutes).

**Startup delay.** The first supervision frame goes out one full interval after start, so the widget stays orange for about one interval.

## Logs

| Log | Content |
|-----|---------|
| `siaDC09` | PHP side: daemon launch, command execution, callbacks, watchdog |
| `siaDC09_daemon` | Daemon: startup line `Démon SIA DC-09 version X.Y.Z`, state transitions, frames, errors |
| Dependency log | Dependency installation, from the plugin's dependency panel |

INFO, WARNING and ERROR lines are in French; DEBUG lines are in English and include the hex frames. Set the plugin log level to **Debug** before reproducing an issue to get the technical detail. The AES key and the FTPS password are never logged.

## Backup and restore

siaDC09 has no export format of its own; it relies on the standard **Jeedom backup** (Settings → System → Backups), which contains:

- the **database**: the siaDC09 equipment and all its settings (including the AES key, the FTPS password and the zone table), its commands, and the plugin settings;
- the **plugin files** under `plugins/siaDC09/`.

The Python virtual environment is not something to restore: reinstall the dependencies after a restore.

**Restore on the same or a new box:**

1. Restore the Jeedom backup (Settings → System → Backups → Restore).
2. Open the plugin configuration page and **reinstall the dependencies**; wait for OK.
3. Check the equipment page: the **Configuration active** panel should show your receiver, media transport, zones and notification target.
4. Start the daemon and confirm **Connexion OK** on the widget within about two supervision intervals.
5. The Alarm plugin keeps its references to the siaDC09 commands only if their IDs are unchanged (full restore). If you rebuilt the equipment by hand instead, the plugin rewires the Alarm plugin automatically from the configuration screen ([user guide](fr_FR/index.md#câbler-le-plugin-alarme)). Re-check the step-3 notification target, since it is stored as a command or scenario ID.

**What a backup does not cover:** the zone-number ↔ zone-name table registered at the monitoring centre. Keep a copy of step 3 (or the Configuration active panel) with your monitoring-centre paperwork.

Because the backup contains the AES key, the FTPS password and the monitoring-centre account in clear, store backups as carefully as those secrets.

## Upgrade path

The plugin is an early-tester version (0.1.0), installed from its Git repository; the Market comes later. An upgrade is therefore a repository update (pull the new version into `plugins/siaDC09/`), then:

1. Jeedom picks up the new files in **Plugin management**; run the update from there if it proposes one.
2. Jeedom creates any new command. Existing settings are untouched, and an equipment saved before a setting existed keeps its previous behaviour.
3. If the dependencies changed, Jeedom reinstalls them.
4. **Restart the daemon** (Jeedom normally does it after a plugin update). Check that `siaDC09_daemon` logs the new `Démon SIA DC-09 version X.Y.Z`: this is how you confirm the running daemon matches the installed plugin.
5. Read the [changelog](fr_FR/changelog.md) for any change that affects your setup.

## Security notes

- **Encryption is implemented but not validated against a real receiver.** With encryption enabled, supervision and alarm frames are AES-encrypted per DC-09-2021 § 5.4. It is covered by automated tests only; no real receiver has confirmed it. Check with the monitoring centre before enabling it.
- **UDP.** The UDP transport has only been tested against a simulator, not a real UDP receiver. TCP has been validated against a real receiver.
- **Key format.** The AES key must be 32, 48 or 64 **hexadecimal** digits (AES-128/192/256). With encryption on and a missing or malformed key, the daemon refuses to start, and a daemon already running sends nothing (never a plaintext fallback). The form some panels use, where the key is the ASCII characters of a text, is not supported yet.
- **Secrets are not encrypted in Jeedom.** The AES key and the FTPS password are stored unencrypted in the equipment settings, so they appear in clear in every Jeedom backup. The AES key is also visible to any local user who can list the processes on the box. Neither is written to the logs.
- **FTP without TLS.** The *FTP sans TLS* option sends the password and the images in clear on the network, and does not verify the server certificate. Prefer FTPS, with the certificate fingerprint pinned.
- **Frigate address.** Only literal placeholders (`<user>`, `<pass>`, `<token>`) may be stored. The monitoring centre substitutes the real credentials on its side. Never put a real password in this address: it travels in every alarm frame.
- **Access to the daemon.** The plugin and the daemon talk on the box only, and the callback from the daemon is accepted only with the plugin's API key.
