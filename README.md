# siaDC09 — SIA DC-09 remote monitoring for Jeedom

> **Jeedom plugin that reports alarms to a monitoring centre (CSR) over the SIA DC-09 Internet protocol**

> 🧪 **Status: early-tester version.** Not released yet (no Market listing, no GitHub release). This documentation is for early testers; behaviour and settings can still change.

siaDC09 turns a Jeedom box into an alarm transmitter. When the official Jeedom **Alarm** plugin triggers, siaDC09 sends a SIA DC-09-2021 frame to the monitoring centre's receiver (any SIA DC-09 compatible CSR), waits for its ACK, retries, and raises a critical notification if the alarm could not be delivered. It also sends periodic supervision frames so the monitoring centre knows the link is alive, and can attach a Frigate snapshot/clip link to each alarm.

## Features

- **SIA DC-09-2021 transmitter**: SIA-DCS framing, CRC-16, sequence numbers, timestamps, ACK/NAK/DUH handling, over **TCP or UDP**
- **Alarm vocabulary (intrusion only)**: burglary (BA), burglary cancel (BC), open/close (OP/CL) with zone and user numbers. Fire and panic are postponed
- **Link supervision**: periodic keep-alive frame (none, SIA-DCS or NULL format), optional cyclic test (RP), degraded/lost detection, TCP reconnection with back-off
- **Tiered error handling**: T1 (self-healing) / T2 (check) / T3 (critical) notifications to any Jeedom message command, the message centre, or a scenario
- **Guided setup**: 3-step wizard (Centre, Test, Zones and alerts) with the monitoring-centre settings, live SIA and FTPS tests, zone numbering, Alarm plugin linking and notification target
- **Diagnostics**: dashboard widget, last-errors list and a protocol inspector that decodes every exchanged frame
- **Photo/video verification (optional)**: forced capture and best-event lookup at trigger time (Frigate). The centre receives the media either through an address (URL) in the alarm frame, or through a copy uploaded to your FTPS server (FTP without TLS is possible but discouraged), photo burst included. Alarms are never delayed by media
- **Async Python daemon** built on [`jeedomdaemon`](https://pypi.org/project/jeedomdaemon/)

## Quick Links

- 📘 [Guide utilisateur (FR)](docs/fr_FR/index.md) — installation, wizard, Alarm plugin wiring, status indicators, troubleshooting
- 📷 [Conseils Frigate (FR)](docs/fr_FR/frigate.md) — exposing Frigate to the CSR, recordings, tracked objects and labels
- 🖼️ [Photo/video by FTPS (FR)](docs/fr_FR/media-ftps.md) — uploading media to your own FTPS server instead of exposing Frigate
- 🛠️ [Admin guide (EN)](docs/admin-guide.md) — configuration keys, backup/restore, upgrades
- 📋 [Changelog (FR)](docs/fr_FR/changelog.md)
- 🐛 [Issues](https://github.com/hlehoux2021/siadc09/issues)

## Known Limitations

- **Encryption** is implemented to DC-09-2021 § 5.4 (AES-CBC, 128/192/256-bit keys) and checked against encrypted frames from real panels, but it is **not yet validated against a real receiver**. The field-validated configuration is still **TCP, unencrypted, hex CRC**.
- The AES key is entered as **hex**: 32, 48 or 64 hex digits (128, 192 or 256 bits). Some panels use the ASCII bytes of a key text instead; that form is not supported yet.
- **UDP** has only been exercised against a CSR simulator, not against a real receiver.
- **FTPS / FTP media upload:** FTP without TLS sends the password and the images in clear text, and the FTPS password is stored in the plugin configuration like the AES key.
- **No permanent TCP connection**: TCP is opened on demand (the cyclic test is supported, a permanent link is not).
- One receiver (no backup receiver), one equipment, one SIA user number.
- Alarm retries are fixed (4 attempts); the "Retries" setting only applies to TCP reconnection. A NAK is answered by an immediate re-send with an updated timestamp, within those 4 attempts.
- Intrusion only: no fire/panic alarms, no restore codes (BR).
- Configuration changes require a daemon restart; the first supervision frame is sent one interval after start.
- Daemon and notification messages are French only (`messages.py`; gettext is planned).

## Disclaimer

siaDC09 is an independent open-source project, **not certified** by the SIA, by any monitoring centre or by an alarm standard body, and is provided under the AGPL **without warranty**. It forwards the decisions of the Jeedom Alarm plugin; it does not replace a certified alarm panel. Before relying on it, run a coordinated test with your monitoring centre (warn them first) and keep the critical notification wired to a channel you actually watch.

## Credits

- Scaffolding started from the [aiodemo](https://github.com/mips2648/jeedom-aiodemo) plugin template by **Mips2648**, and uses his [`jeedomdaemon`](https://github.com/Mips2648/jeedom-daemon-py) Python library
- Many thanks to **Sagitaz** and **Noodom**, authors of the Jeedom [Frigate plugin](https://github.com/sagitaz/plugin-frigate), on which the alarm media feature relies
- Protocol: SIA DC-09-2021 *Internet Protocol Event Reporting* (Security Industry Association; the specification is not redistributed here)

---

## Installation

### Prerequisites

**Hardware / service:**
- A Jeedom box (Smart, Atlas, Raspberry Pi, Docker or DIY)
- A monitoring-centre contract that accepts SIA DC-09, with the receiver IP/port, transport, account number (and AES key if required)

**Software:**
- Jeedom core **4.5+** on Debian **12+**
- The official Jeedom **Alarm** plugin (zones already configured)
- Optional: the **Frigate** plugin, for alarm media

**Dependencies** (installed by Jeedom from `plugin_info/packages.json`, in the plugin's Python venv):
- `jeedomdaemon==1.2.9` — daemon framework
- `cryptography==43.0.3` — AES primitives

### From the Jeedom Market (future)

> ⏳ **Not available yet**: siaDC09 is not published on the Jeedom Market. The steps below describe how installation *will* work once it is; until then, use the [manual install](#manual-install-from-github).

1. *(future)* **Plugins → Plugin management → Market**, search *SIA DC-09*, install and activate.
2. *(future)* On the plugin configuration page, click **Relancer** under *Dépendances* and wait for **OK**.
3. *(future)* Open **Plugins → Sécurité → Télésurveillance SIA DC-09** and run the wizard (below).

### Manual install (from GitHub)

This is currently the only way to install the plugin. Clone the repository and symlink it into the Jeedom plugin directory under the plugin ID:

```bash
git clone https://github.com/hlehoux2021/siadc09.git
ln -s "$PWD/siadc09" /var/www/html/plugins/siaDC09
chown -h www-data:www-data /var/www/html/plugins/siaDC09
```

Then activate it in **Plugin management**, click **Relancer** under *Dépendances* on the plugin configuration page and wait for **OK**, and open **Plugins → Sécurité → Télésurveillance SIA DC-09** to run the wizard.
## Configuration

The equipment is created automatically; everything is set through the 3-step wizard. Full walkthrough: [guide utilisateur](docs/fr_FR/index.md#lassistant-de-configuration).

| Step | What you set | Main keys (`eqLogic` configuration) |
|------|--------------|--------------------------------------|
| 1 — Centre (*Centrale*) | Receiver address, transport, account, AES encryption. Photo/video verification: enable it, choose photo and/or video, and how the centre receives it: an address (URL) to your Frigate server, or a copy uploaded to an FTPS server | `csr_ip`, `csr_port`, `transport`, `account_number`, `encryption_enabled`, `encryption_key`, `media_enabled`, `media_transport`, `media_snapshot_enabled`, `media_clip_enabled`, `frigate_media_url_template` (URL transport only) |
| 2 — Test | Live SIA test (supervision frame, shows ACK / NAK / failure cause) and, under FTPS, an FTPS test (connection, certificate, login; no file is written). **Advanced options**: link format (V/U) and single-tag choice, FTPS server, supervision frame format and interval, cyclic test (RP), TCP reconnection | `media_snapshot_format`, `media_clip_format`, `media_single_tag`, `ftps_host`, `ftps_port`, `ftps_user`, `ftps_password`, `ftps_folder`, `ftps_plain`, `ftps_cert_fingerprint`, `supervision_format`, `supervision_interval`, `rp_enabled`, `rp_interval`, `retry_count`, `reconnect_delay` |
| 3 — Zones and alerts | Alarm equipment to link, SIA zone number and optional Frigate camera per Alarm zone, SIA user number; who receives critical notifications | `alarm_eqlogic_id`, `sia_zone_mappings`, `sia_user_number`, `sia_notify_kind`, `sia_notify_cmd_id`, `sia_notify_internal`, `sia_notify_scenario_id` |


The **Lier au plugin Alarme** button of step 3 wires the siaDC09 action commands (*Alarme intrusion*, *Désarmement*, *Réinitialisation alarme*, *Armement*, *Prefetch événement Frigate*) into the Alarm plugin with **Titre = `#zone#`** — see [Câbler le plugin Alarme](docs/fr_FR/index.md#câbler-le-plugin-alarme). A daemon restart is needed after any change; see the [admin guide](docs/admin-guide.md#configuration).

## Architecture

```
Jeedom Alarm plugin ──cmd──▶ siaDC09 (PHP: eqLogic/cmd, AJAX, cron watchdog)
                                 │  JSON over TCP socket (127.0.0.1:55009)
                                 ▼
                         siadc09d (Python asyncio daemon)
                          SM1 supervision · SM2 events · error handler
                                 │  SIA DC-09 over TCP/UDP
                                 ▼
                         Monitoring-centre receiver (CSR)
      daemon ──HTTP callback (jeesiaDC09.php)──▶ PHP: info cmds, notifications, diagnostics
```

- **PHP plugin** (`core/`, `desktop/`): equipment and commands, wizard, widget, diagnostic tab, daemon lifecycle and a 5-minute freshness watchdog.
- **Daemon** (`resources/siadc09d/`): protocol encoding/decoding, transports, supervision (SM1) and event (SM2) state machines, tiered error handler, Frigate media prefetch, best-effort FTPS/FTP media upload (`ftps_upload.py`).

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.html), as declared in `plugin_info/info.json`.
