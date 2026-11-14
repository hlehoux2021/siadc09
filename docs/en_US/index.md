# SIA DC-09 monitoring plugin (siaDC09)

> Reports Jeedom Alarm plugin alarms to a monitoring centre over the SIA DC-09 Internet protocol.

The full user guide is currently written in French: **[Guide utilisateur](../fr_FR/index.md)**. The plugin UI is in French too.

In short:

1. Install the plugin — *(future)* from the Jeedom Market; it is **not published there yet**, so for now use the [manual install from GitHub](https://github.com/hlehoux2021/siadc09#manual-install-from-github). Then install its dependencies from the plugin configuration page.
2. Open **Plugins → Security → Télésurveillance SIA DC-09** and complete the 3-step wizard: monitoring centre (receiver IP/port, TCP or UDP, account number), connection test, then zones (optional Frigate camera per zone) and critical-alert target.
3. In step 3 (zones and alerts), pick your Alarm equipment and press **"Lier au plugin Alarme"**: siaDC09 writes its own commands (arm, disarm, alarm reset, and, in the **Déclenchement** tab, *Alarme intrusion* and, when a zone has a camera, *Prefetch événement Frigate*, both with Titre `#zone#`) into that equipment, idempotently. Close the Alarm equipment page first. "Délier du plugin Alarme" (next to "Relancer l'assistant") removes only siaDC09's entries. Intrusion only.
4. Start the daemon and check that the widget shows **Connexion OK**. Run a coordinated test with your monitoring centre.

**Before enabling encryption**: AES encryption is implemented (hexadecimal key, 128/192/256 bits; a missing or invalid key blocks all sending, never a fallback in clear), but it has not been validated against a real receiver. The field-validated setup is TCP, unencrypted. UDP has only been tested with a simulator.

More: [README and known limitations](https://github.com/hlehoux2021/siadc09#readme) · [Administrator guide](https://github.com/hlehoux2021/siadc09/blob/master/docs/admin-guide.md) · [Changelog (French)](../fr_FR/changelog.md)
