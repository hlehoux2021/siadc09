# siaDC09 — Developer Guide

This guide is the map, not the territory: it tells you where things are and how the pieces talk to each other, and links to the design documents for the details. Read the [admin guide](admin-guide.md) first for the runtime picture (config keys, daemon lifecycle, logs).

## Contents

1. [Repository map](#repository-map)
2. [Runtime flow](#runtime-flow)
3. [IPC contracts](#ipc-contracts)
4. [CSR configuration](#csr-configuration)
5. [Internationalisation](#internationalisation)
6. [Tests and tooling](#tests-and-tooling)
7. [Versioning and release](#versioning-and-release)
8. [Known gaps and discrepancies](#known-gaps-and-discrepancies)

---

## Repository map

| Path | What lives there | Design doc |
|------|------------------|------------|
| `core/class/siaDC09.class.php` | eqLogic: command creation (`postSave`), daemon lifecycle (`deamon_info/start/stop`), `sendToDaemon()`, callback dispatch, widget `toHtml()`, `cron5` freshness watchdog, notification routing | [php-core-design.md](../internal-docs/design/php-core-design.md) |
| `core/class/siaDC09Cmd.class.php` | cmd `execute()`: zone and user resolution, Frigate media resolution, BC/OP decisions for disarm/alarmReset, prefetch dispatch | [php-core-design.md](../internal-docs/design/php-core-design.md) |
| `core/ajax/siaDC09.ajax.php` | Wizard and diagnostic endpoints (`testConnection` spawns `siadc09d.py --test-only`, errors/inspector reads) | [wizard-design.md](../internal-docs/design/wizard-design.md), [debug-ui-design.md](../internal-docs/design/debug-ui-design.md) |
| `core/php/jeesiaDC09.php` | Daemon → PHP HTTP callback entry point (API-key checked) | [php-core-design.md](../internal-docs/design/php-core-design.md) |
| `core/template/` | Dashboard/mobile widget | [widget-design.md](../internal-docs/design/widget-design.md) |
| `desktop/php/siaDC09.php`, `desktop/js/siaDC09.js` | Equipment page: wizard, Configuration active panel, diagnostic tab | [wizard-design.md](../internal-docs/design/wizard-design.md), [debug-ui-design.md](../internal-docs/design/debug-ui-design.md) |
| `core/i18n/*.json` | Translations of `__()` / `{{…}}` strings | [below](#internationalisation) |
| `plugin_info/` | `info.json`, `packages.json`, `install.php` (upgrade hook re-runs `postSave`), icon | [admin-guide.md](admin-guide.md) |
| `resources/siadc09d/siadc09d.py` | Entry point: CLI args → `CSRPreset` → `SIADaemon`; `--test-only` single-shot mode | [daemon-design.md](../internal-docs/design/daemon-design.md) |
| `resources/siadc09d/daemon.py` | `SIADaemon(BaseDaemon)`: `on_start/on_message/on_stop`, SM1 supervision loop, SM2 event queue and consumer, callbacks | [daemon-design.md](../internal-docs/design/daemon-design.md), [supervision-design.md](../internal-docs/design/supervision-design.md) |
| `resources/siadc09d/sia_protocol.py` | Frame build/parse, CRC-16, timestamps, ACK/NAK/DUH decoding | [SIA DC-09 spec](../internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md) |
| `resources/siadc09d/sia_transport.py` | UDP and TCP transports, TCP reconnection | [daemon-design.md](../internal-docs/design/daemon-design.md) |
| `resources/siadc09d/sia_crypto.py` | `SIACipher` (AES-CBC) — **not wired into production yet**, see [gaps](#known-gaps-and-discrepancies) | — |
| `resources/siadc09d/error_handler.py` | T1/T2/T3 classification, notification texts, error codes | [error-handler-design.md](../internal-docs/design/error-handler-design.md) |
| `resources/siadc09d/frigate_prefetch.py` | Forced Frigate event + best-event polling and ranking | ADR-17 in `architecture.md` |
| `resources/siadc09d/messages.py` | French INFO/WARNING/ERROR log messages | [logging-design.md](../internal-docs/design/logging-design.md) |
| `resources/siadc09d/logging_config.py` | Log setup; INFO French / DEBUG English | [logging-developer-guide.md](../internal-docs/logging-developer-guide.md) |
| `resources/siadc09d/presets.py` | `CSRPreset` dataclass, built from CLI args | [below](#csr-configuration) |
| `resources/siadc09d/ring_buffer.py` | Bounded buffers behind the diagnostic lists | [debug-ui-design.md](../internal-docs/design/debug-ui-design.md) |
| `resources/siadc09d/csr_simulator.py`, `simulate_frames.py`, `extract_frames_from_pcap.py` | Dev tools: fake receiver, frame generator, pcap extractor | [simulator-tools.md](../internal-docs/simulator-tools.md) |

Architecture decisions (ADR-1 … ADR-18) are in `_bmad-output/planning-artifacts/architecture.md`.

## Runtime flow

1. **Start.** PHP `deamon_start()` passes the whole configuration as CLI arguments (see the [admin guide table](admin-guide.md#configuration-keys)). `siadc09d.py` builds a frozen `CSRPreset` and runs `SIADaemon`. `on_start()` logs `Démon SIA DC-09 version <DAEMON_VERSION>`, opens the transport and starts the supervision loop and the queue consumer.
2. **Supervision (SM1).** Every `supervision_interval` seconds a NULL frame is queued. States (`SM1State`): INITIALIZING → HEALTHY ⇄ DEGRADED (strikes 1-3; the third is "Connexion perdue"); in TCP also TCP_RECONNECTING → NO_NETWORK ("Hors Réseau", terminal: the daemon exits and Jeedom's watchdog restarts it). Each transition sends `info_update`.
3. **Events (SM2).** The Alarm plugin runs a siaDC09 action command → `siaDC09Cmd::execute()` resolves the zone number (from `#zone#` via `sia_zone_mappings`), the user number and the media URL, then calls `sendToDaemon()`. The daemon queues the event with priority over supervision, frames it, sends it, and waits up to 10 s for the ACK, with 3 retries 1 s apart (`MAX_RETRY_DEFAULT`). Each state (PENDING / ACK / NAK / FAILED) is reported through `info_update` and `message_trace`; failures go through the error handler.
4. **Errors.** `error_handler.py` maps each failure to T1/T2/T3 and emits `message_center`, `notify` and `error_update` callbacks. PHP routes `notify` to the step-4 target.
5. **Frigate prefetch.** `prefetchEvent` (zone IMMEDIATE action) starts a tracked background task that creates a forced 30 s Frigate event labelled `alarm`, polls the camera's events every 2 s for up to 25 s, ranks them person > other label > manual > none, and reports each improvement with `prefetch_result`. PHP caches the best result for 120 s (monotonic by `run_id`); the next alarm on the zone reads the cache and adds `media_url`. An alarm never waits for the prefetch.

## IPC contracts

### PHP → daemon (`sendToDaemon`, JSON over TCP `127.0.0.1:<socketport>`)

Every message carries `apikey` and `cmd`. Typed as `OnMessageParams` in `daemon.py`.

| `cmd` | Extra keys | SIA code |
|-------|------------|----------|
| `burglarAlarm` / `fireAlarm` / `panicAlarm` | `zone` (label or null), `zone_number` (int or null), optional `media_url` | BA / FA / PA (fixed map `_EVENT_SIA_CODES`) |
| `disarm` | `user_number`, `sia_code` ∈ {`BC`, `OP`} — one message per frame; PHP sends BC then OP when a burglary is open, OP alone otherwise | from payload |
| `alarmReset` | `user_number`, `sia_code` = `BC` (only when a burglary is open) | from payload |
| `arm` | `user_number` | CL (fixed) |
| `prefetchEvent` | `zone`, `camera_eqlogic_id`, `camera_name`, `frigate_host`, `run_id` | none (no frame) |

`testConnection` is **not** an IPC message: the AJAX endpoint spawns a separate `siadc09d.py --test-only --timeout 15 --config <json>` process, which sends one NULL frame and prints a JSON verdict on stdout (`_TEST_VERDICTS` in `siadc09d.py`).

### Daemon → PHP (HTTP POST to `jeesiaDC09.php`, dispatched in `siaDC09::` callback switch)

| `type` | Purpose | PHP effect |
|--------|---------|------------|
| `info_update` | Supervision / event state and labels | `checkAndUpdateCmd()` on `supervision_state`, `supervision_label`, `event_state`, `event_label` |
| `message_center` | T1+ message | `message::add('siaDC09', …)` |
| `notify` | T2/T3 notification | Routed to `sia_notify_*` target (cmd, message centre or scenario) |
| `error_update` | Add a T2/T3 entry, or resolve a T1 (`resolve_t1`, `code`) | `sia_last_errors` ring (10) / message removal |
| `message_trace` | One protocol exchange (sent/received hex, decoded fields) | `sia_last_messages` ring (50); routine supervision coalesced into one row |
| `prefetch_result` | Best Frigate event so far for a `run_id` | Prefetch cache (monotonic replace rule, 120 s TTL) |

The contract is enforced on both sides by `tests/level2_5/test_callback_schema.py` and `tests/level2_5/test_ipc_integration.py`. Change it in one place only together with those tests and `php-core-design.md`.

## CSR configuration

Step 1 of the wizard has a single mode: manual entry of the receiver's IP, port, transport, account number, encryption and supervision parameters. There used to be a built-in "IMA Protect" preset card next to it (`resources/siadc09d/csr_presets.json`, a `siaDC09-preset-card` in `desktop/php/siaDC09.php`, `siaDC09_selectCard()`/`siaDC09_fillFromPreset()` in `desktop/js/siaDC09.js`); it was removed (D-84, 2026-09-27) because IMA Protect is not the first target CSR. The daemon side was never preset-aware — it always builds its `CSRPreset` from CLI arguments (`csr_provider="cli"`) regardless of how the wizard filled the form.

If a preset mechanism is reintroduced later, `git log` for the D-84 commit shows what to re-add (catalogue file, PHP card loop, JS fill/readonly logic, provider label in the Configuration summary, matching tests).

## Internationalisation

**PHP/JS.** French is the source language. Strings go through `__('…', __FILE__)` in PHP and `{{…}}` in PHP templates and JS. `core/i18n/fr_FR.json` is an identity map keyed by section `plugins/siaDC09/<relative path>`:

- `__()` keys are the **runtime** string (PHP escapes resolved);
- `{{…}}` keys are the **raw** text between the braces, because Jeedom translates the raw file/buffer.

A missing key falls back to the source text, so a gap is never a runtime error. `tests/level1/test_i18n_roundtrip.py` fails on a missing or orphan key. There is no automatic translation. `en_US.json` is maintained by hand and covers only part of the strings (22 of 169 at 1.0), so English users see mostly French. When you add a string, add it to `fr_FR.json`, and to `en_US.json` if you can translate it.

**Daemon.** Log messages live in `resources/siadc09d/messages.py` (`# TODO v1.1: gettext`). **Not every user-visible daemon string is there yet.** Inventory for the gettext migration:

| File | Strings |
|------|---------|
| `error_handler.py` | Notification titles and bodies (≈ lines 387-503), `event_type_fr` labels |
| `daemon.py` | Event labels (≈ 800-804), SM2 status/label texts (≈ 1338, 1373, 1405), stop label (≈ 2410) |
| `siadc09d.py` | `_TEST_VERDICTS` connection-test verdicts (≈ 73-117) |
| `sia_transport.py` | One user-facing error text (≈ 229) |

PHP-side hard-coded French outside `__()`/`{{…}}`: the Configuration active summary in `desktop/js/siaDC09.js` (≈ 667-755) and some warnings in `siaDC09Cmd.class.php`. Tracked in `_bmad-output/implementation-artifacts/deferred-work.md`.

## Tests and tooling

| Level | Folder | Scope | Run |
|-------|--------|-------|-----|
| 1 | `tests/level1/` | Sync unit tests: protocol, CRC, crypto, PHP/JS structure (via stubs/regex), i18n, Market files | `python3 -m pytest tests/level1/` |
| 2 | `tests/level2/` | Async daemon: SM1/SM2, transports, queue, prefetch | `python3 -m pytest tests/level2/` |
| 2.5 | `tests/level2_5/` | IPC contract (callback schema, wizard config) | `python3 -m pytest tests/level2_5/` |
| 3 | `tests/level3/` | Live Jeedom required (`requires_jeedom`) | `pytest -m requires_jeedom` |

- Dev dependencies: `python3 -m pip install -r tests/requirements-dev.txt`.
- Rules (`.claude/rules/testing.md`): pytest only; each test has a docstring with an **Expected result** list and an `# Assert:` comment per assert; async tests join `daemon._tasks` instead of sleeping.
- Lint: `python3 -m pylint resources/siadc09d/`; PHP syntax: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`.
- CSR simulator: `python3 -m tests.simulator` (see [tests/simulator/README.md](../tests/simulator/README.md) and [simulator-tools.md](../internal-docs/simulator-tools.md)) — for provoked failures (NAK, silence, garbage). It is **not** a substitute for a real receiver.
- CI: `.github/workflows/checkPHP.yml` (PHP lint). There is no Python CI job; run the suites locally before pushing.

## Versioning and release

- `plugin_info/info.json` `pluginVersion` and `resources/siadc09d/__init__.py` `DAEMON_VERSION` must be equal (`tests/level1/test_daemon_version.py`). Bump both, plus `docs/fr_FR/changelog.md` (the only changelog, in French), in one commit.
- `packages.json` pins every pip3 dependency to an exact version (`test_packages_json_pip3_all_pinned`).
- Market and GitHub release steps: [market-submission-checklist.md](../internal-docs/market-submission-checklist.md).

## Known gaps and discrepancies

Behaviour that differs from what the UI or the design docs suggest. IDs refer to `_bmad-output/implementation-artifacts/deferred-work.md`.

| Area | Gap |
|------|-----|
| **Encryption** | `SIACipher` is never called in production and `_encryption_key` is unused. With encryption on, supervision frames get the `*` marker but a plaintext body (`daemon.py` ≈ 957, `siadc09d.py` ≈ 287); event frames are always built with `encryption=False` (`daemon.py` ≈ 1765). |
| CRC format | `crc_format = bin` is accepted but ignored on send: the daemon always emits ASCII hex CRC. |
| Retries | Alarm retries are fixed (`MAX_RETRY_DEFAULT = 3`, i.e. 4 attempts, 10 s timeout, 1 s apart); `retry_count` only drives TCP reconnection. An alarm NAK is not retried. |
| Missing UI | `crc_format`, `receiver_prefix`, `account_prefix`, `socketport` have no field. |
| Daemon lifecycle | Config changes need a restart (D-40); first supervision after one interval (D-42). The "stop daemon" confirmation dialogs do not actually stop it. |
| Event label | Single last-event slot (D-67). |
| Alarm vocabulary | No BR restore (story 13-2), no FC/PC cancels (13-3); arm/disarm edge cases D-63, D-64, D-66, D-69, D-70, D-72, D-74. |
| Diagnostics | `[V…]` media block not decoded in the inspector (D-80); elapsed ms 0 for alarms (D-2); AJAX failure only toasts (D-44); times shown in UTC; colour-only status (D-47). |
| Frigate | D-53, D-54, D-60, D-78, D-79; `info_detect_person` can stay stuck at 1. |
| Environment | Python path with spaces (D-26). |
| Texts | Some notifications hard-code a monitoring-centre name; daemon strings outside `messages.py` (see [i18n](#internationalisation)). |
| Validation | TCP / unencrypted / hex CRC validated against a real test receiver (keep-alive, BA with zone, BC/OP/CL, Frigate `[V…]`). UDP validated against the simulator only; real-receiver error-path validation (story 12-7) not executed. |
