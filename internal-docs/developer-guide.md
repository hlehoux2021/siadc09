# siaDC09 — Developer Guide

This guide is the map, not the territory: it tells you where things are and how the pieces talk to each other. Detailed design notes and the protocol specification live in the source repository and are not published with this documentation. The configuration keys, the daemon launch checks and the security mechanisms are in [Runtime reference](#runtime-reference) below; the published [admin guide](../docs/admin-guide.md) only keeps what an administrator needs.

The plugin covers intrusion reporting only (burglary alarm, arm/disarm). It is currently distributed to early testers.

## Contents

1. [Repository map](#repository-map)
2. [Runtime flow](#runtime-flow)
3. [IPC contracts](#ipc-contracts)
4. [Adding a CSR profile](#adding-a-csr-profile)
5. [Internationalisation](#internationalisation)
6. [Tests and tooling](#tests-and-tooling)
7. [Versioning](#versioning)
8. [Known gaps and discrepancies](#known-gaps-and-discrepancies)
9. [Runtime reference](#runtime-reference) — configuration keys, launch checks, command line, security mechanisms (moved from the admin guide)

---

## Repository map

| Path | What lives there |
|------|------------------|
| `core/class/siaDC09.class.php` | eqLogic: command creation (`postSave`), daemon lifecycle (`deamon_info/start/stop`), `sendToDaemon()`, callback dispatch, widget `toHtml()`, `cron5` freshness watchdog, notification routing, CSR profile loading (`CSR_PROFILES_FILE`) |
| `core/class/siaDC09Cmd.class.php` | cmd `execute()`: zone and user resolution, Frigate media resolution, BC/OP decisions for disarm/alarmReset, prefetch dispatch |
| `core/ajax/siaDC09.ajax.php` | AJAX endpoints: `getWidgetDates`, `testConnection` (spawns `siadc09d.py --test-only`), `testFtps` (spawns `siadc09d.py --test-ftps`), `getZones`, `linkAlarm` / `getAlarmLinkState` / `unlinkAlarm` (automatic wiring with the Alarm plugin), `getFrigateCameras`, `getDiagnosticData`, `decodeFrame`, `clearDiagnosticData` |
| `core/php/jeesiaDC09.php` | Daemon → PHP HTTP callback entry point (API-key checked) |
| `core/config/csr_presets.json` | CSR behaviour profiles (Ajax, Vesta, FoxStream); read by PHP only. See [Adding a CSR profile](#adding-a-csr-profile) |
| `core/template/` | Dashboard/mobile widget |
| `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` | Equipment page: wizard, profile select, Configuration active panel, diagnostic tab |
| `core/i18n/*.json` | Translations of `__()` / `{{…}}` strings, see [below](#internationalisation) |
| `plugin_info/` | `info.json`, `packages.json`, `install.php` (upgrade hook re-runs `postSave`), icon |
| `resources/siadc09d/siadc09d.py` | Entry point with three modes: daemon (CLI args → `CSRPreset` → `SIADaemon`), `--test-only` (single NULL frame), `--test-ftps` (FTP/FTPS connection probe) |
| `resources/siadc09d/daemon.py` | `SIADaemon(BaseDaemon)`: `on_start/on_message/on_stop`, SM1 supervision loop, RP cyclic test, SM2 event queue and consumer, media handling, FTP(S) upload, photo series, callbacks |
| `resources/siadc09d/sia_protocol.py` | Frame build/parse, CRC-16, timestamps, ACK/NAK/DUH decoding |
| `resources/siadc09d/sia_transport.py` | UDP and TCP transports, TCP reconnection |
| `resources/siadc09d/sia_crypto.py` | `SIACipher` (AES-CBC, § 5.4) and `parse_hex_key`; not validated against a real receiver, see [gaps](#known-gaps-and-discrepancies) |
| `resources/siadc09d/ftps_upload.py` | FTP/FTPS upload of snapshots, clips and photo series (`FtpsSettings`, `upload_bytes/many/file`, `probe_connection`, remote location, server certificate fingerprint) |
| `resources/siadc09d/error_handler.py` | T1/T2/T3 classification, notification texts, error codes |
| `resources/siadc09d/frigate_prefetch.py` | Forced Frigate event, best-event polling and ranking, clip wait, photo series capture |
| `resources/siadc09d/messages.py` | French INFO/WARNING/ERROR log messages |
| `resources/siadc09d/logging_config.py` | Log setup; INFO French / DEBUG English |
| `resources/siadc09d/presets.py` | `CSRPreset` dataclass built from CLI arguments: supervision format (`none` / `sia-dcs` / `null`), RP cyclic test (`rp_enabled`, `rp_interval_s`, bounded 60-86400 s), sender CRC format (hex only), cross-field validation |
| `resources/siadc09d/ring_buffer.py` | Bounded buffers behind the diagnostic lists |
| `resources/siadc09d/csr_simulator.py`, `simulate_frames.py`, `extract_frames_from_pcap.py` | Dev tools: fake receiver, frame generator, pcap extractor |
| `tests/` | `level1` … `level3` suites, `simulator/` (fake CSR), `harness/` and `fixtures/` (JS/DOM harness), `render/` (wizard rendering), `ftps_stall_fake.py` (stalling FTPS server for tests) |

## Runtime flow

1. **Start.** PHP `deamon_start()` passes the whole configuration as CLI arguments (see the [configuration keys table](#configuration-keys); CLI arguments are listed under [IPC contracts](#ipc-contracts)). `siadc09d.py` builds a frozen `CSRPreset` and runs `SIADaemon`. `on_start()` logs `Démon SIA DC-09 version <DAEMON_VERSION>`, opens the transport and starts the supervision loop, the RP loop (if enabled) and the queue consumer.
2. **Supervision (SM1) and RP cyclic test.** At least one periodic frame must be configured. The periodic frame has three formats (`--supervision-format`): `sia-dcs` (default, a SIA-DCS NULL-style frame), `null` (a plain NULL frame, used by the FoxStream profile) and `none` (no supervision frame, used by the Ajax profile together with RP). Independently, the RP cyclic test (`--rp-enabled`, `--rp-interval`, 60-86400 s) sends the cyclic test event; a DUH answer is handled as a receiver refusal. States (`SM1State`): INITIALIZING → HEALTHY ⇄ DEGRADED (strikes 1-3; the third is "Connexion perdue"); in TCP also TCP_RECONNECTING → NO_NETWORK ("Hors Réseau", terminal: the daemon exits and Jeedom's watchdog restarts it). Each transition sends `info_update`. The daemon opens the connection per exchange or keeps it as the transport requires; a permanent TCP mode is not implemented (see gaps).
3. **Events (SM2).** The Alarm plugin runs a siaDC09 action command → `siaDC09Cmd::execute()` resolves the zone number (from `#zone#` via `sia_zone_mappings`), the user number and the media, then calls `sendToDaemon()`. The daemon queues the event with priority over supervision, frames it, sends it, and waits up to 10 s for the ACK, with 3 retries 1 s apart (`MAX_RETRY_DEFAULT`). Each state (PENDING / ACK / NAK / FAILED) is reported through `info_update` and `message_trace`; failures go through the error handler.
4. **Media.** An alarm frame can carry media links: snapshot and/or clip, as `U` (direct multimedia URL) or `V` (video verification link) blocks. `media` is a list of such entries; `media_single_tag` groups all URLs in one tag instead of one tag each (profile-dependent). The transport of the media is either `url` (links to the Frigate host) or FTP/FTPS: the daemon downloads the snapshot or clip from Frigate and uploads it (`ftps_upload`), then the frame carries the resulting location. Upload progress and failures are reported with `message_center` / `notify` callbacks tagged with a `logical_id`. `media_url` is the older single-URL mechanism, kept for compatibility.
5. **Errors.** `error_handler.py` maps each failure to T1/T2/T3 and emits `message_center`, `notify` and `error_update` callbacks. PHP routes `notify` to the configured target.
6. **Frigate prefetch and photo series.** `prefetchEvent` (zone IMMEDIATE action) starts a tracked background task that creates a forced Frigate event labelled `alarm` (`MANUAL_EVENT_DURATION_S`), polls the camera's events (`PREFETCH_POLL_INTERVAL_S` up to `PREFETCH_MAX_WAIT_S`), ranks them person > other label > manual > none, and reports each improvement with `prefetch_result` (including `clip_found`). PHP caches the best result (monotonic by `run_id`); the next alarm on the zone reads the cache and builds its media. With FTP(S) active and `burst` set, the daemon also captures a series of photos (`BURST_INTERVAL_S` apart) held in memory per `run_id` for `BURST_TTL_S`; the series is sent alone, each photo named by its capture time. An alarm never waits for the prefetch.

## IPC contracts

### PHP → daemon (`sendToDaemon`, JSON over TCP `127.0.0.1:<socketport>`)

Every message carries `apikey` and `cmd`. Typed as `OnMessageParams` in `daemon.py`.

| `cmd` | Extra keys | SIA code |
|-------|------------|----------|
| `burglarAlarm` | `zone` (label or null), `zone_number` (int or null), optional `media` (list), `media_single_tag`, `ftps_upload` (dict: `frigate_host`, `event_id`, `run_id`, `snapshot`, `clip`), legacy `media_url` | BA (fixed map `_EVENT_SIA_CODES`) |
| `disarm` | `user_number`, `sia_code` ∈ {`BC`, `OP`}: one message per frame; PHP sends BC then OP when a burglary is open, OP alone otherwise | from payload |
| `alarmReset` | `user_number`, `sia_code` = `BC` (only when a burglary is open) | from payload |
| `arm` | `user_number` | CL (fixed) |
| `prefetchEvent` | `zone`, `camera_eqlogic_id`, `camera_name`, `frigate_host`, `run_id`, optional `burst` (true starts the photo series) | none (no frame) |

`fireAlarm` / `panicAlarm` still exist in the code (FA / PA) but are not part of the product: the plugin is intrusion only. A removal task is planned.

Daemon start-up arguments (`siadc09d.py`): `--host`, `--port`, `--transport`, `--account`, `--crc-format` (hex only), `--encryption-enabled`, `--encryption-key`, `--ftps-enabled`, `--ftps-host`, `--ftps-port`, `--ftps-user`, `--ftps-folder`, `--ftps-cert-fingerprint`, `--ftps-plain` (plain FTP instead of FTPS), `--supervision-interval`, `--supervision-format`, `--rp-enabled`, `--rp-interval`, `--retry-count`, `--reconnect-delay`, `--receiver-prefix`, `--account-prefix`, `--notify-cmd-id`.

`testConnection` and `testFtps` are **not** IPC messages: the AJAX endpoint spawns a separate `siadc09d.py --test-only --timeout 15 --config <json>` (one NULL frame, JSON verdict on stdout, `_TEST_VERDICTS`) or `siadc09d.py --test-ftps --config <json>` (FTP/FTPS connection probe, JSON result).

### Daemon → PHP (HTTP POST to `jeesiaDC09.php`, dispatched in `siaDC09::` callback switch)

| `type` | Purpose | PHP effect |
|--------|---------|------------|
| `info_update` | Supervision / event state and labels | `checkAndUpdateCmd()` on `supervision_state`, `supervision_label`, `event_state`, `event_label` |
| `message_center` | T1+ message; FTP(S) upload messages carry `logical_id` (`ftps_upload`) so a new one replaces the previous | `message::add('siaDC09', …)` |
| `notify` | T2/T3 notification (also `logical_id` for uploads) | Routed to the `sia_notify_*` target (cmd, message centre or scenario) |
| `error_update` | Add a T2/T3 entry, or resolve a T1 (`resolve_t1`, `code`) | `sia_last_errors` ring / message removal |
| `message_trace` | One protocol exchange (sent/received hex, decoded fields) | `sia_last_messages` ring; routine supervision coalesced into one row |
| `prefetch_result` | Best Frigate event so far for a `run_id`, with `clip_found` (0/1) | Prefetch cache (monotonic replace rule, TTL) |

The contract is enforced on both sides by `tests/level2_5/test_callback_schema.py` and `tests/level2_5/test_ipc_integration.py`. Change it in one place only together with those tests.

## Adding a CSR profile

A CSR profile pre-fills and locks a set of behaviour settings for a known receiver family. Profiles live in `core/config/csr_presets.json` (despite the file name these are behaviour profiles, not connection presets: no host, port or account). Shipped profiles: `ajax`, `vesta`, `foxstream`; an empty choice means "Custom" (nothing locked).

Key points:

- **PHP/JS only.** The file is read by PHP (`siaDC09::CSR_PROFILES_FILE`) and applied by the equipment page. The chosen profile id is stored in the equipment configuration key `csr_profile`. The daemon never reads the file and never knows the profile: it only receives the resulting CLI arguments and builds its `CSRPreset` from them. A test enforces this invariant.
- **Schema.** `schema_version` plus `profiles.<id>` with `label` and any of `supervision_format`, `supervision_interval`, `rp_enabled`, `rp_interval`, and the media keys (`media_enabled`, `media_snapshot_enabled`, `media_clip_enabled`, `media_snapshot_format`, `media_clip_format`, `media_single_tag`, `media_transport`). Keys present in a profile are applied and locked in the wizard; absent keys stay editable.

To add a profile:

1. Add an entry under `profiles` in `core/config/csr_presets.json`, using only valid values (supervision format ∈ `none`/`sia-dcs`/`null`; RP interval 60-86400 s; at least one periodic frame).
2. Add the matching option to the profile `<select id="siaDC09-csr-profile">` (in `desktop/php/siaDC09.php`) and its label to the i18n files if the label is translated.
3. Extend `tests/level1/test_csr_presets_json.py` (schema, value ranges, locked keys).
4. Validate the values against the real receiver before shipping them: a profile is a claim about that receiver's behaviour.
5. No daemon change is needed. If you need a new daemon setting, add the CLI argument and the `CSRPreset` field first, then the profile key.

## Internationalisation

**PHP/JS.** French is the source language. Strings go through `__('…', __FILE__)` in PHP and `{{…}}` in PHP templates and JS. `core/i18n/fr_FR.json` is an identity map keyed by section `plugins/siaDC09/<relative path>`:

- `__()` keys are the **runtime** string (PHP escapes resolved);
- `{{…}}` keys are the **raw** text between the braces, because Jeedom translates the raw file/buffer.

A missing key falls back to the source text, so a gap is never a runtime error. `tests/level1/test_i18n_roundtrip.py` fails on a missing or orphan key. There is no automatic translation. `en_US.json` is maintained by hand and covers only part of the strings, so English users see mostly French. When you add a string, add it to `fr_FR.json`, and to `en_US.json` if you can translate it.

**Daemon.** Log messages live in `resources/siadc09d/messages.py`. Not every user-visible daemon string is there yet; the remaining ones are:

| File | Strings |
|------|---------|
| `error_handler.py` | Notification titles and bodies, `event_type_fr` labels |
| `daemon.py` | Event labels, SM2 status/label texts, stop label |
| `siadc09d.py` | `_TEST_VERDICTS` connection-test verdicts |
| `sia_transport.py` | One user-facing error text |

PHP-side hard-coded French outside `__()`/`{{…}}`: the Configuration active summary in `desktop/js/siaDC09.js` and some warnings in `siaDC09Cmd.class.php`.

## Tests and tooling

| Level | Folder | Scope | Run |
|-------|--------|-------|-----|
| 1 | `tests/level1/` | Sync unit tests: protocol, CRC, crypto, FTPS, CSR profile JSON, PHP/JS structure (via stubs/regex), wizard DOM tests, i18n | `python3 -m pytest tests/level1/` |
| 2 | `tests/level2/` | Async daemon: SM1/SM2, RP cyclic test, transports, queue, prefetch, FTPS upload | `python3 -m pytest tests/level2/` |
| 2.5 | `tests/level2_5/` | IPC contract (callback schema, wizard config) | `python3 -m pytest tests/level2_5/` |
| 3 | `tests/level3/` | Live Jeedom required (`requires_jeedom`) | `pytest -m requires_jeedom` |

- Dev dependencies: `python3 -m pip install -r tests/requirements-dev.txt`. The DOM tests (`tests/harness/`, `tests/render/`) additionally rely on a JS runtime; check the test files for the exact requirement.
- Known failures exist on a clean checkout; re-measure the baseline before attributing a failure to your change.
- Rules: pytest only; each test has a docstring with an **Expected result** list and an `# Assert:` comment per assert; async tests join `daemon._tasks` instead of sleeping.
- Lint: `python3 -m pylint resources/siadc09d/`; PHP syntax: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`.
- CSR simulator: `python3 -m tests.simulator`, for provoked failures (NAK, silence, garbage). It is **not** a substitute for a real receiver. `tests/ftps_stall_fake.py` plays the same role for FTPS.
- CI: `.github/workflows/checkPHP.yml` (PHP lint). There is no Python CI job; run the suites locally before pushing.

## Versioning

- `plugin_info/info.json` `pluginVersion` and `resources/siadc09d/__init__.py` `DAEMON_VERSION` must be equal (`tests/level1/test_daemon_version.py`). Bump both, plus `docs/fr_FR/changelog.md` (the only changelog, in French), in one commit.
- `packages.json` pins every pip3 dependency to an exact version (`test_packages_json_pip3_all_pinned`).

## Known gaps and discrepancies

Behaviour that differs from what the UI or the design suggests.

| Area | Gap |
|------|-----|
| **Encryption** | Implemented to DC-09-2021 § 5.4: `*NULL` supervision and `*SIA-DCS` events, AES-CBC zero IV, 16/24/32-byte keys given as hex. Checked against real-panel encrypted frames and an independent oracle, **not validated against a real receiver**. ASCII-bytes keys are not supported. |
| **FTP/FTPS** | Validated only against a test server; not confirmed against production receivers. Photo/clip delivery and `[V…]` verification links depend on the CSR and are not confirmed in real conditions for every profile. |
| **UDP** | Validated against the simulator only, never against a real receiver. Real-receiver error-path validation is not done. |
| **Multi-CSR / failover** | Not implemented: one equipment talks to one receiver. Only scaffolding exists. |
| **Configurable SIA formats** | Abandoned: the plugin emits the fixed formats described above. |
| **Permanent TCP mode** | Deferred. A supervision frame (keep-alive) is not the RP cyclic test, and the Ajax profile works on demand. |
| Retries | Alarm retries are fixed (`MAX_RETRY_DEFAULT = 3`, i.e. 4 attempts, 10 s timeout, 1 s apart); `retry_count` only drives TCP reconnection. A NAK triggers an immediate re-send with the same seq and an updated timestamp (§ 5.6.1.2), counted in the same budget; a NULL NAK gets up to 2 re-sends before a strike. |
| Daemon lifecycle | Config changes need a restart; the first supervision frame comes one full interval after start. |
| Event label | Single last-event slot. |
| Alarm vocabulary | Intrusion only. `fireAlarm` / `panicAlarm` commands are still created by the code and are to be removed. Some arm/disarm edge cases remain open. |
| Diagnostics | Elapsed ms 0 for alarms; AJAX failure only toasts; times shown in UTC; colour-only status. The inspector may not decode every `[V…]` media variant. |
| Frigate | `info_detect_person` can stay stuck at 1 after the person left. |
| Environment | Python path with spaces. |
| Texts | Some notifications hard-code a monitoring-centre name; daemon strings outside `messages.py` (see [i18n](#internationalisation)). |

## Runtime reference

Moved here from the published admin guide, which keeps only what an administrator needs.

### Components on the box

| Component | Location | Role |
|-----------|----------|------|
| PHP plugin | `/var/www/html/plugins/siaDC09/` (`core/`, `desktop/`, `plugin_info/`) | Equipment, commands, wizard, widget, diagnostic tab, daemon start/stop, 5-minute freshness watchdog (`cron5`) |
| Python daemon | `resources/siadc09d/siadc09d.py` | SIA DC-09 transmitter: supervision, periodic test frame (RP), events, error handling, Frigate prefetch, optional FTP/FTPS photo upload |
| Python venv | managed by Jeedom (`system::getCmdPython3`) | `jeedomdaemon==1.2.9`, `cryptography==43.0.3` from `plugin_info/packages.json` |
| PID file | `jeedom::getTmpFolder('siaDC09')/daemon.pid` | Used by `deamon_info()` to report the daemon state |
| Local IPC | TCP `127.0.0.1:<socketport>` (default `55009`) | PHP → daemon JSON commands |
| Callback | `core/php/jeesiaDC09.php` over the internal Jeedom URL | Daemon → PHP updates, authenticated with the plugin API key |

### Configuration keys

#### Equipment configuration (`eqLogic->getConfiguration()`)

All set by the wizard (three steps: 1 Centrale, 2 Test, 3 Zones et alertes); stored in the Jeedom database with the equipment. "Advanced" means the *Options avancées* area of step 2.

| Key | Default | Wizard step | Meaning | Passed to daemon as |
|-----|---------|-------------|---------|---------------------|
| `csr_profile` | — | 1 | Receiver profile (Ajax, Vesta, FoxStream, or custom). Selecting one pre-fills supervision, periodic test and media settings. PHP only: the daemon receives the resolved values | — |
| `csr_ip` | `''` | 1 | Receiver IP. Must not be empty or `TBD` | `--host` |
| `csr_port` | `0` | 1 | Receiver port, 1-65535 | `--port` |
| `transport` | `udp` | 1 | `udp` or `tcp` | `--transport` |
| `account_number` | `''` | 1 | 3-16 hex chars | `--account` |
| `encryption_enabled` | `false` | 1 | Encryption flag | `--encryption-enabled` |
| `encryption_key` | `''` | 1 | AES key, 32/48/64 hex chars; required when encryption is enabled | `--encryption-key` |
| `supervision_format` | `sia-dcs` | 2 (advanced) | Supervision frame: `sia-dcs`, `null` or `none` (no supervision frame at all) | `--supervision-format` |
| `supervision_interval` | `60` | 2 (advanced) | Seconds between supervision frames; also drives the stale-widget and watchdog thresholds (3 × interval). Not used when `supervision_format` is `none` | `--supervision-interval` |
| `rp_enabled` | `0` | 2 (advanced) | Enable the periodic test frame (RP) | `--rp-enabled` |
| `rp_interval` | `60` | 2 (advanced) | Seconds between RP frames, 60-86400 (checked only when RP is enabled) | `--rp-interval` |
| `retry_count` | `6` | 2 (advanced) | **TCP reconnection** attempts before "Hors Réseau" (does not change alarm retries, which are fixed at 4 attempts) | `--retry-count` |
| `reconnect_delay` | `30` | 2 (advanced) | Base TCP reconnection delay, seconds | `--reconnect-delay` |
| `crc_format` | `hex` | — (no UI) | `hex` only (`bin` was removed). Any other value makes the daemon not launchable | `--crc-format` |
| `receiver_prefix` | `''` | — (no UI) | Optional SIA receiver number (`R…`) | `--receiver-prefix` |
| `account_prefix` | `''` | — (no UI) | Optional account prefix (`L…`) | `--account-prefix` |
| `sia_zone_mappings` | `[]` | 3 | Alarm zone name → SIA zone number and optional Frigate camera. Numbers are stable: a zone keeps its number, new zones get the next free one | resolved by PHP, sent with each command |
| `alarm_eqlogic_id` | — | 3 | ID of the Alarm plugin equipment the plugin writes its commands into (automatic wiring) | — |
| `media_enabled` | `1` (when absent) | 1 | Master switch: attach a photo/video to intrusion alarms | resolved by PHP |
| `media_transport` | `url` | 1 | `url` (U/V tag with a Frigate link in the frame) or `ftps` (no tag; the daemon uploads the Frigate snapshot to an FTP(S) server) | selects the `--ftps-*` options |
| `frigate_media_url_template` | `''` | 1 | Public Frigate URL **with literal placeholders** (`<user>`, `<pass>`, `<token>`) — never a real credential. Required only with the `url` transport | resolved by PHP, sent with each command |
| `media_snapshot_enabled` / `media_clip_enabled` | `1` / `1` | 1 | Send the snapshot / clip URL in intrusion alarm frames. Both off: no media tag | `media` list in the command payload |
| `media_snapshot_format` / `media_clip_format` | `V` / `V` | 2 (advanced) | Tag letter per media, `U` or `V` (Vesta profile uses U, FoxStream V). Only for the `url` transport | `media[].format` |
| `media_single_tag` | `1` | 2 (advanced) | One tag with both URLs space-separated (only when both formats are equal) or one tag per URL | `media_single_tag` |
| `ftps_host` | `''` | 2 (advanced) | FTP(S) server, `ftps` transport only | `--ftps-host` |
| `ftps_port` | `21` | 2 (advanced) | FTP(S) port | `--ftps-port` |
| `ftps_user` | `''` | 2 (advanced) | FTP(S) account | `--ftps-user` |
| `ftps_password` | `''` | 2 (advanced) | FTP(S) password. Stored in clear in the database (so in backups); handed to the daemon through the `SIA_FTPS_PASSWORD` environment variable, never as an argument | env `SIA_FTPS_PASSWORD` |
| `ftps_folder` | `''` | 2 (advanced) | Destination folder on the server | `--ftps-folder` |
| `ftps_plain` | `0` | 2 (advanced) | Plain FTP without TLS. The password then travels unencrypted on the network | `--ftps-plain` |
| `ftps_cert_fingerprint` | `''` | 2 (advanced) | Pin the server certificate by fingerprint; ignored when `ftps_plain` is on | `--ftps-cert-fingerprint` |
| `sia_user_number` | — | 3 | 1-999, user number for OP/CL/BC | resolved by PHP, sent with each command |
| `sia_notify_kind` | `''` | 3 | `cmd` (a Jeedom message action) or `internal` | — |
| `sia_notify_cmd_id` | `0` | 3 | Target command ID when `kind = cmd` | `--notify-cmd-id` |
| `sia_notify_internal` | `''` | 3 | `message` (message centre) or `scenario` | — |
| `sia_notify_scenario_id` | `0` | 3 | Target scenario when `internal = scenario` | — |
| `sia_wizard_step` | `0` | all | Wizard progress; it reaches `4` once the three steps are finished, and the daemon is not launchable before that | — |

- Under the `ftps` transport the alarm frame carries **no U/V tag**: the photo goes to the FTP(S) server and the monitoring centre matches it by account and time. The Frigate URL is then not required.
- When `supervision_format` is `none` (Ajax-type profile) no supervision frame is sent, so the interval is ignored; at least one periodic frame must remain, so `rp_enabled` has to be on.
- Equipment saved before a key existed keeps the previous behaviour through the defaults above.
- The daemon reads its settings **once, at start**. Any change needs a daemon restart (deferred item D-40).
- `crc_format`, `receiver_prefix` and `account_prefix` have no UI field; they only change through a direct database edit.

#### Plugin configuration (`config::byKey(..., 'siaDC09')`)

| Key | Default | Meaning |
|-----|---------|---------|
| `socketport` | `55009` | Local daemon IPC port. No UI field: change it with `config::save('socketport', <port>, 'siaDC09')` only if another plugin already uses 55009, then restart the daemon |
| `autoStartDeamon` | `1` | Standard Jeedom daemon auto-management |
| `sia_last_errors` | `[]` | JSON, last 10 T2/T3 errors shown in the diagnostic tab |
| `sia_last_messages` | `[]` | JSON, last 50 protocol exchanges shown in the protocol inspector |
| `_freshness_alert_ts` | `0` | Timestamp of the last "Démon bloqué" alert (rate limit: one per 30 min) |

#### Commands (logical IDs)

Action: `burglarAlarm`, `prefetchEvent` (subType `message`, Titre = `#zone#`), `disarm`, `alarmReset`, `arm` (subType `other`). Info: `supervision_state` (0/1/2), `supervision_label`, `event_state` (0/1/2/3), `event_label`. Commands are (re)created by `postSave()`, and by `siaDC09_update()` on every plugin upgrade. The plugin writes its commands into the Alarm plugin equipment itself (key `alarm_eqlogic_id`).

### Daemon launch checks and start

`deamon_info()` reports **not launchable** — with a message pointing to the wizard step to fix — while any of these is true:

1. the wizard is not finished (`sia_wizard_step` below 4);
2. `csr_ip` is empty or `TBD`, or `csr_port` / `transport` / `account_number` is invalid;
3. `crc_format` is not `hex`;
4. the supervision interval is not positive (unless `supervision_format` is `none`);
5. the periodic frames are inconsistent: unknown `supervision_format`, `none` with RP disabled, or RP enabled with an interval outside 60-86400 s;
6. photo/video is explicitly enabled with the `url` transport but no Frigate address is set (not checked under `ftps`);
7. encryption is enabled without a valid key;
8. no critical-notification target is configured (step 3).

Dependencies are checked by the Jeedom core wrapper, not by the plugin.

`deamon_start()` builds the command line from the keys above (the AES key and the FTPS password are redacted in the `siaDC09` log line; the FTPS password goes through the `SIA_FTPS_PASSWORD` environment variable, the AES key stays on the command line), starts `siadc09d.py` in the venv and waits up to 10 s for the PID file. Jeedom's watchdog restarts a crashed daemon when auto-management is on. In TCP, when all reconnection attempts fail the daemon reports "Hors Réseau" and exits; the watchdog then restarts it.

**Watchdog (`cron5`).** Every 5 minutes, if the daemon is running but `supervision_state` has not been updated for more than 3 × `supervision_interval`, the plugin sends "siaDC09 — Démon bloqué" to the step-3 notification target (at most once per 30 minutes).

**Startup delay.** The first supervision frame goes out one full interval after start, so the widget stays orange for about one interval (D-42).

### Security mechanisms

- **Encryption.** With `encryption_enabled`, supervision (`*NULL`) and alarm (`*SIA-DCS`) frames are AES-CBC encrypted per DC-09-2021 § 5.4. Covered by automated tests only; no real receiver has confirmed it. `encryption_key` must be 32, 48 or 64 hex digits; with a missing or malformed key the daemon refuses to start, and a running daemon sends nothing (no plaintext fallback). The ASCII-bytes key form some panels use is not supported.
- **AES key storage.** `encryption_key` is stored unencrypted in the equipment configuration (not declared in `$_encryptConfigKey`), so it is in every Jeedom backup. It is also passed on the daemon's command line (`--encryption-key`), readable by any local user who can list processes. It is redacted from the Jeedom log.
- **FTPS password.** `ftps_password` is stored unencrypted in the equipment configuration, so it is in every backup. It reaches the daemon through `SIA_FTPS_PASSWORD`, not the command line, and is redacted from the Jeedom log.
- **Callback authentication.** `jeesiaDC09.php` accepts only requests carrying the plugin API key; the IPC socket listens on `127.0.0.1` only.
