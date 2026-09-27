# siaDC09 — Télésurveillance SIA DC-09 pour Jeedom

> **Jeedom plugin that reports alarms to a monitoring centre (CSR) over the SIA DC-09 Internet protocol**

> 🧪 **Status: early-tester version.** Not released yet (no Market listing, no GitHub release). This documentation is for early testers; behaviour and settings can still change.

siaDC09 turns a Jeedom box into an alarm transmitter. When the official Jeedom **Alarm** plugin triggers, siaDC09 sends a SIA DC-09-2021 frame to the monitoring centre's receiver (any SIA DC-09 compatible CSR), waits for its ACK, retries, and raises a critical notification if the alarm could not be delivered. It also sends periodic supervision frames so the monitoring centre knows the link is alive, and can attach a Frigate snapshot/clip link to each alarm.

## Features

- **SIA DC-09-2021 transmitter**: SIA-DCS framing, CRC-16, sequence numbers, timestamps, ACK/NAK/DUH handling, over **TCP or UDP**
- **Alarm vocabulary**: burglary (BA), fire (FA), panic (PA), burglary cancel (BC), open/close (OP/CL) with zone and user numbers
- **Link supervision**: periodic keep-alive frames, degraded/lost detection, TCP reconnection with back-off
- **Tiered error handling**: T1 (self-healing) / T2 (check) / T3 (critical) notifications to any Jeedom message command, the message centre, or a scenario
- **Guided setup**: 4-step wizard with the monitoring-centre settings, a live connection test, zone numbering and notification target
- **Diagnostics**: dashboard widget, last-errors list and a protocol inspector that decodes every exchanged frame
- **Frigate media (optional)**: forced capture and best-event lookup at trigger time; the alarm frame carries a media URL template — alarms are never delayed by media
- **Async Python daemon** built on [`jeedomdaemon`](https://pypi.org/project/jeedomdaemon/)

## Quick Links

- 📘 [Guide utilisateur (FR)](docs/fr_FR/index.md) — installation, wizard, Alarm plugin wiring, status indicators, troubleshooting
- 📷 [Conseils Frigate (FR)](docs/fr_FR/frigate.md) — exposing Frigate to the CSR, recordings, tracked objects and labels
- 🛠️ [Admin guide (EN)](docs/admin-guide.md) — configuration keys, backup/restore, upgrades
- 👩‍💻 [Developer guide (EN)](docs/developer-guide.md) — code map, IPC contracts, adding a CSR preset, tests
- 📋 [Changelog (FR)](docs/fr_FR/changelog.md)
- 📜 [SIA DC-09-2021 specification (text)](internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md)
- 🐛 [Issues](https://github.com/hlehoux2021/siadc09/issues)

## Known Limitations

- **Encryption is not implemented yet.** Enabling it only adds the `*` marker to supervision frames — their body stays plaintext — and alarm frames are always sent unencrypted. A receiver that requires AES will most likely reject them. The field-validated configuration is **TCP, unencrypted, hex CRC**.
- **UDP** has only been exercised against the bundled CSR simulator, not against a real receiver.
- One receiver (no backup receiver), one equipment, one SIA user number.
- Alarm retries are fixed (4 attempts); the "Retries" setting only applies to TCP reconnection. An alarm NAK is not retried.
- No restore codes (BR) and no fire/panic-specific cancel codes yet.
- Configuration changes require a daemon restart; the first supervision frame is sent one interval after start.
- Daemon and notification messages are French only (`messages.py`; gettext is planned).

The full list, with the tracking IDs, is in the [developer guide](docs/developer-guide.md#known-gaps-and-discrepancies).

## Disclaimer

siaDC09 is an independent open-source project, **not certified** by the SIA, by any monitoring centre or by an alarm standard body, and is provided under the AGPL **without warranty**. It forwards the decisions of the Jeedom Alarm plugin; it does not replace a certified alarm panel. Before relying on it, run a coordinated test with your monitoring centre (warn them first) and keep the critical notification wired to a channel you actually watch.

## Credits

- Scaffolding started from the [aiodemo](https://github.com/mips2648/jeedom-aiodemo) plugin template by **Mips2648**, and uses his [`jeedomdaemon`](https://github.com/Mips2648/jeedom-daemon-py) Python library
- Many thanks to **Sagitaz** and **Noodom**, authors of the Jeedom [Frigate plugin](https://github.com/sagitaz/plugin-frigate), on which the alarm media feature relies
- Protocol: SIA DC-09-2021 *Internet Protocol Event Reporting* (Security Industry Association)

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

Then activate it in **Plugin management**, click **Relancer** under *Dépendances* on the plugin configuration page and wait for **OK**, and open **Plugins → Sécurité → Télésurveillance SIA DC-09** to run the wizard. The development test suite needs `tests/requirements-dev.txt`.

## Configuration

The equipment is created automatically; everything is set through the wizard. Full walkthrough: [guide utilisateur](docs/fr_FR/index.md#lassistant-de-configuration).

| Step | What you set | Main keys (`eqLogic` configuration) |
|------|--------------|--------------------------------------|
| 1 — CSR | Receiver address, transport, account, encryption, supervision interval, TCP retries/back-off | `csr_ip`, `csr_port`, `transport`, `account_number`, `encryption_enabled`, `encryption_key`, `supervision_interval`, `retry_count`, `reconnect_delay` |
| 2 — Test | Live supervision frame to the CSR, shows ACK / NAK / failure cause | — |
| 3 — Zones | SIA zone number and optional Frigate camera per Alarm zone, media URL template, SIA user number | `sia_zone_mappings`, `frigate_media_url_template`, `sia_user_number` |
| 4 — Alerts | Who receives critical notifications | `sia_notify_kind`, `sia_notify_cmd_id`, `sia_notify_internal`, `sia_notify_scenario_id` |

Then wire the siaDC09 action commands (*Alarme intrusion*, *Désarmement*, *Réinitialisation alarme*, *Armement*, *Prefetch événement Frigate*) into the Alarm plugin, with **Titre = `#zone#`** — see [Câbler le plugin Alarme](docs/fr_FR/index.md#câbler-le-plugin-alarme). All keys are described in the [admin guide](docs/admin-guide.md#configuration-keys).

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
- **Daemon** (`resources/siadc09d/`): protocol encoding/decoding, transports, supervision (SM1) and event (SM2) state machines, tiered error handler, Frigate media prefetch.

Details: [developer guide](docs/developer-guide.md) and the design documents in [internal-docs/design/](internal-docs/design/) ([daemon](internal-docs/design/daemon-design.md), [PHP core](internal-docs/design/php-core-design.md), [supervision](internal-docs/design/supervision-design.md), [error handler](internal-docs/design/error-handler-design.md), [logging](internal-docs/design/logging-design.md), [wizard](internal-docs/design/wizard-design.md), [widget](internal-docs/design/widget-design.md), [debug UI](internal-docs/design/debug-ui-design.md)).

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.html), as declared in `plugin_info/info.json`.
