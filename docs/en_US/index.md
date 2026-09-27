# SIA DC-09 monitoring plugin (siaDC09)

> Reports Jeedom Alarm plugin alarms to a monitoring centre over the SIA DC-09 Internet protocol.

The full user guide is currently written in French: **[Guide utilisateur](../fr_FR/index.md)**. The plugin UI is in French too.

In short:

1. Install the plugin — *(future)* from the Jeedom Market; it is **not published there yet**, so for now use the [manual install from GitHub](https://github.com/hlehoux2021/siadc09#manual-install-from-github). Then install its dependencies from the plugin configuration page.
2. Open **Plugins → Security → Télésurveillance SIA DC-09** and complete the 4-step wizard: monitoring centre (receiver IP/port, TCP or UDP, account number), live connection test, zone numbering (and optional Frigate camera per zone), and critical-alert target.
3. In the Alarm plugin, add the siaDC09 commands: *Alarme intrusion* (or fire/panic) to the trigger actions with **Titre = `#zone#`** (preferably the global ones on the "Déclenchement" tab, which cover every zone), *Désarmement* to "Désactivation OK", *Réinitialisation alarme* to "Réinitialisation", *Armement* to the immediate activation actions, and optionally *Prefetch événement Frigate* to the immediate trigger actions (global or per zone) with Titre `#zone#`.
4. Start the daemon and check that the widget shows **Connexion OK**. Run a coordinated test with your monitoring centre.

**Before enabling encryption**: in this early-tester version, AES encryption is not effective (supervision frames are only flagged, alarm frames are sent in clear). The field-validated setup is TCP, unencrypted.

More: [README and known limitations](https://github.com/hlehoux2021/siadc09#readme) · [Administrator guide](https://github.com/hlehoux2021/siadc09/blob/master/docs/admin-guide.md) · [Developer guide](https://github.com/hlehoux2021/siadc09/blob/master/docs/developer-guide.md) · [Changelog (French)](../fr_FR/changelog.md)
