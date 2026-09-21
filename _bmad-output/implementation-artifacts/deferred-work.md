# Deferred Work

## Deferred from: code review of 6-6-php-core-integration-ipc-tests (2026-05-04)

- **D-1: Docstring schema inconsistency** — `error_handler.py` docstrings for `message_center` and `notify` list more fields (tier, title, timestamp, context, critical) than the authoritative `ipc_schema.py` samples. Should update the docstrings to match the canonical schema or vice versa.
- **D-2: SM2 elapsed_ms always 0** — All `SM2LogCtx` instances are constructed with `elapsed=0.0` at every call site in `_send_with_retry`. Actual TCP/UDP round-trip time is measured but never captured into the context. PHP protocol inspector will always show `elapsed_ms: 0` for alarm events.
- **D-3: Dual `_tcp_reconnect_loop` risk** — ~~FIXED in Story 7.2~~ — state regression guard added to `_handle_supervision_tcp_drop()` + D-3 guard in `_update_sm1_from_strike()`.
- **D-4: Dual tier classification paths** — `_error_tier()` in `daemon.py` uses `classify_error()` from `error_handler.py`, while `build_notification()` has its own inline `tier_map`. Two authoritative sources for the same mapping. Should consolidate to a single source to prevent divergence.
- **D-5: `prev_strike` misreputed at NAK cap** — In `_handle_supervision_nak()`, when the strike counter is already at `STRIKE_CAP` (3), `prev_strike = self._strike_counter - 1` evaluates to 2 even though the strike did not actually increment. Affects only the logging context (not sent to PHP).

## Deferred from: code review of 7-1-supervision-loop-strike-management-info-updates (2026-05-05)

- **D-6: `_update_info_commands` None-filter changes IPC contract** — `payload = {k: v for k, v in data.items() if v is not None}` silently strips None keys. No current caller passes intentional None values, but semantics changed from prior `dict(data)`. Could break future code that relies on sending explicit null to PHP to clear a field.

## Deferred from: code review of 7-2-tcp-stall-detection-reconnect-ring-buffer-logging (2026-05-05)

- **D-7: Queue consumer gate tests use `asyncio.sleep(0)`** — `test_queue_consumer_gate_blocks_during_tcp_reconnecting` and `test_queue_consumer_gate_multiple_items_all_consumed_after_recovery` rely on repeated `asyncio.sleep(0)` loops to drive the consumer, violating testing.md's rule to never use `sleep(0)`. Structural constraint: the consumer task cannot be `asyncio.gather()`-joined mid-run while still needing to observe intermediate state.
- **D-8: Asymmetric guard strategies between `_handle_supervision_tcp_drop` and `_update_sm1_from_strike`** — `_handle_supervision_tcp_drop` guards on `SM1State` membership, while `_update_sm1_from_strike` guards on task name presence in `_tasks`. A window exists where these disagree (e.g., state=TCP_RECONNECTING but completed task removed from `_tasks`). Unlikely to trigger in practice; a dedicated `_reconnect_task: asyncio.Task | None` field would unify the logic.

## Deferred from: code review of 7-3-supervision-integration-testing (2026-05-05)

- **D-9: AC3 no per-strike intermediate assertion** — `test_ac3_udp_strike_escalation_timeout` only asserts that both SUPERVISION_TIMEOUT and SUPERVISION_DISCONNECTED appeared, not that SUPERVISION_TIMEOUT fired specifically at strike=1. Tightening would require artificial timing control that conflicts with the async-native design.
- **D-10: AC13 sim missing encryption key** — `csr_sim` fixture creates simulator without an encryption key, so simulator always NAKs encrypted frames. `test_ac13_encrypted_supervision_marker_sent` tests only the frame marker, not E2E ACK. Full E2E encrypted supervision test depends on completing the encryption path in the daemon (documented as deferred work).
- **D-11: PHP `cron5()` restart sequencing concern** — `cron5()` calls `deamon_info()` then `_checkSupervisionFreshness()`. If the freshness check triggers a restart, the next `cron5()` call will restart cleanly. No double-call in current flow, but sequencing between freshness-triggered restart and the regular 5-min cron could produce a brief observation window where daemon state is transitional.

## Deferred from: code review of 8-2-wizard-steps-3-4-zone-mapping (2026-05-11)

- **D-12: Migration — existing eqLogics with old `wizard_step` key** — Any equipment created before the `wizard_step`→`sia_wizard_step` rename in `siaDC09.class.php` will be treated as step 0 (config mode) on `printEqLogic`, forcing a wizard restart. Pre-existing issue; no real users exist in v1.0 yet.
- **D-13: Orphan subprocess on PHP timeout in `testConnection`** — If PHP's `set_time_limit` fires during the `exec()` call to `siadc09d.py --test-only`, the request dies but the Python subprocess may continue running. Self-terminates on its own timeout; harmless in v1.0 single-user context.

## Deferred from: code review of 8-3-wizard-integration-testing (2026-05-11)

- **D-14: `test_sia_wizard_step_set_via_data_l2key_attribute` uses `[^}]*` regex** — Fragile if `siaDC09_setWizardStep()` gains nested braces. Should replace with `_extract_js_handler()` brace-depth approach if function body grows.
- **D-15: `TransportType` ValueError propagates out of `run_connection_test`** — An invalid transport string from a malformed preset causes an uncaught exception, so PHP receives a traceback instead of a JSON error object. Pre-existing production code gap; fix in production code, not in tests.
- **D-16: Account number `"0"` rejected by falsy `not account_number` guard** — Single-digit `"0"` is theoretically valid but blocked. Whitespace-only string `" "` passes the guard and produces a malformed SIA frame. Pre-existing.
- **D-17: Preset mode + `encryption_enabled=true` + missing key untested** — The IMA Protect preset ships with `encryption_enabled=true`; if the user has not set `SIA_ENCRYPTION_KEY`, the test sends unencrypted to a CSR expecting encrypted (NAK). This edge case is not covered by the current test suite.
- **D-18: OSError branch of preset file loading untested** — `except (OSError, json.JSONDecodeError)` in `run_connection_test()` is only exercised for the JSONDecodeError path; missing-file / permission-denied path has no test.
- **D-19: Encryption test does not assert frame was encrypted** — `test_run_connection_test_encryption_sends_frame` only asserts `_send_raw_once` was called; does not verify `make_supervision_message` was called with `encryption=True`. A logic inversion in the `encryption_enabled and bool(key)` guard would not be caught.
- **D-20: TCP timeout budget exhaustion** — When `timeout < _TEST_CONNECT_TIMEOUT_S` (5 s), the full budget is consumed by TCP connect and `send_frame` always times out. Architectural pre-existing issue in production code.

## Deferred from: code review of 9-1-status-badge-error-panel (2026-05-18)

- **D-21: `shown.bs.tab` direct binding** — `$('a[href="#diagnosticTab"]').on('shown.bs.tab', ...)` at file-load time may bind to zero elements if the PHP partial is injected after JS parse. Safer as delegated: `$(document).on('shown.bs.tab', 'a[href="#diagnosticTab"]', ...)`. Pre-existing pattern; consistent with other direct bindings in same file.
- **D-22: `_siaDC09_decodeCache` unbounded growth** — Cache accumulates all decoded frames with no eviction. On a long-running page with many protocol dialogs, memory grows indefinitely. Should add a max-entries cap (e.g. 100). 9-2 scope — track for 9-2 review.
- **D-23: Inspector detail panel orphaned on re-render while decode AJAX in-flight** — If user clicks Actualiser while a decode request is pending, `renderMessages` calls `empty()` on the list, destroying the `$detail` reference captured in the AJAX closure. Decode result is painted into a detached node. 9-2 scope — track for 9-2 review.
- **D-24: `siaDC09_copyHexFallback` — textarea not removed if `select()` throws** — `$ta.remove()` is called after `execCommand('copy')` but `$ta` is not cleaned up if `$ta[0].select()` throws. Harmless in practice but leaves a hidden textarea in the DOM. 9-2 scope — track for 9-2 review.

## Deferred from: code review of 9-2-protocol-inspector-hex-viewer-decryption (2026-05-19)

- **D-25: `execCmd()` on disabled equipment in `getDiagnosticData`** — ~~WITHDRAWN 2026-09-21~~ — the original concern was itself mistaken: `cmd::execCmd()` (Jeedom core) returns early for `type == 'info'` (`cmd.class.php:1270-1282`) *before* the disabled-equipment throw path, which only exists for `type == 'action'`. execCmd() cannot throw for these 4 info cmds. A same-day fix briefly switched to `getValue()` on this mistaken premise, which broke the Diagnostic tab for real (permanently frozen state, field-confirmed) — `getValue()` never reflects the daemon's live pushes for non-historized info cmds, since `cmd::event()` only writes to the cmd cache, never the DB `value` column. Reverted back to `execCmd()` in both `getDiagnosticData` and `toHtml()` (widget) the same day.
- **D-26: `$python3` not shell-escaped in `decodeFrame` subprocess command** — `system::getCmdPython3()` return value concatenated directly into shell command without `escapeshellarg()`. If interpreter path contains spaces (venv), command breaks. Pre-existing: same unescaped pattern in `testConnection` action. Fix: wrap `$python3` with `escapeshellarg()` at both call sites.
- **D-27: `raw_response=raw` on timeout branch in `_parse_response()`** — Docstring says `raw_response=None` on timeout, but code passes the raw (potentially garbled) bytes. Low impact for inspector use. Fix: set `raw_response=None` on timeout branch to match docstring contract.
- **D-28: CRC format runtime detection in `decode()` contradicts ADR-06** — `decode()` infers `crc_format` from `len(crc_bytes)` (4=hex, 2=bin). ADR-06 establishes crc_format as a preset config field, not runtime-detected. Acceptable for display-only inspector; no operational impact.

## Deferred from: code review of 9-3-diagnostic-tab-integration-testing (2026-05-19)

- **D-29: `_siaDC09_decodeCache` not reset on full diagnostic reload** — AC 1 specifies the decode cache should reset to `{}` on each call to `siaDC09_loadDiagnosticData()`. Currently the cache is only cleared in `inspectorClear`'s success callback (line 852). Requires a production code change in `siaDC09_loadDiagnosticData` (story 9-2 code). Deferred: testing-only story scope cannot modify production code.
- **D-30: Fixture `SAMPLE_MESSAGE_TRACE` / `SAMPLE_MESSAGE_TRACE_ALARM` missing `id_token`, `sequence`, `account` fields** — The daemon now emits these three fields in every message_trace dialog (added in 9-2 review P3). Fixture samples do not include them, so regressions dropping these fields would go undetected in `test_diagnostic_ipc.py`. JS renderer has fallback defaults so no crash; purely a contract coverage gap.
- **D-31: `DIALOG_REQUIRED_FIELDS` defined in `ipc_schema.py` but never imported in `test_diagnostic_ipc.py`** — The constant (`["dialog_type", "routine"]`) is unused in the test file. Tests use ad-hoc field lists instead. Should import and extend `DIALOG_REQUIRED_FIELDS` with JS-accessed fields (`id_token`, `sequence`, `account`, `timestamp`, `elapsed_ms`) and drive assertions from it.

## Deferred from: code review of 2-5-test-harness-standalone-documentation (2026-05-21)

- **D-38: `_handle_udp()` called as protected method** — all harness/test files call `simulator._handle_udp()` directly; fix requires adding a public `start_udp_handler()` method to `CSRSimulator`. Pre-existing API gap, out of story scope.
- **D-39: TOCTOU race in `_get_free_port()`** — port freed between UDP probe and simulator bind; inherited pattern from `conftest.py`. Fix requires `CSRSimulator` to accept port=0 and expose the actual bound port via a property.

## Deferred from: code review of 2-4-pcap-frame-extractor-tool (2026-05-21)

- **D-32: Golden hex `# Extracted:` timestamp hardcoded** — `create_golden_hex()` writes a fixed timestamp `"2026-05-21 14:30:00 UTC"` while `write_hex_file()` uses `datetime.now()`. Any visual diff of a fresh extraction against the golden reference always shows a spurious header mismatch. Non-breaking — integration test only compares payload bytes.
- **D-33: Non-Ethernet link layers silently drop all packets** — `_parse_packet()` assumes `DLT_EN10MB` (Ethernet). Captures taken with `tcpdump -i lo` (DLT_NULL) or on WiFi in monitor mode produce zero output with no diagnostic message. Common dev workflow failure mode; scope is limited to adding a `logging.warning()` for non-Ethernet packets.
- **D-34: Zero-frames output exits with code 0** — Wrong-port filter silently produces an empty hex file with exit 0. Consider `sys.exit(1)` with a warning when `count == 0` to make this visible in scripts.
- **D-35: `eth.type` set post-construction in `_make_udp_ethernet`** — dpkt may auto-infer `type` at construction time; post-assignment could be silently ignored in future dpkt versions. Tests pass currently. Low risk.
- **D-36: `dpkt>=1.9.8` has no upper bound** — A future dpkt 2.x could break pcapng detection or the `dpkt.dpkt.*` exception hierarchy. Pin to `dpkt>=1.9.8,<2` when dpkt 2.x is released.
- **D-37: TCP branch of `_parse_packet` untested by integration tests** — No TCP packet in the golden fixture; the TCP code path is only covered by unit tests with synthetic in-memory packets.

## Deferred from: code review of 7-2-tcp-stall-detection-reconnect-ring-buffer-logging (2026-09-21)

- **D-40: Daemon restart required for `retry_count`/`reconnect_delay` config changes to take effect** — Changing an eqLogic's `retry_count` or `reconnect_delay` does not restart the running daemon subprocess (`postSave()` has no `deamon_start()` call), so it keeps stale CLI args until a manual restart. Pre-existing pattern across every config field in this plugin (host, port, account, etc. have the same limitation), not introduced by the Task 10 amendment.
- **D-41: `_REQUIRED_PRESET_FIELDS` in `test_csr_presets_json.py` only exercised against one preset** — The new `reconnect_delay` requirement (added for story 7-2 AC20) is only checked against the `ima_protect` entry; not proven to generalize if `csr_presets.json` gains a second preset. No current impact — the file has exactly one preset.
- **D-42: First supervision NULL delayed one full interval at daemon startup** — `_supervision_loop()` (`daemon.py:1945-1964`) does `while True: await asyncio.sleep(interval); ... await self._enqueue_supervision()` — the sleep is at the TOP of the loop, before the first enqueue, so the first supervision NULL fires one whole `supervision_interval_s` (60s default) after `on_start()`, not immediately. Observed 2026-09-17 on host SM1 (`on_start` at 21:53:08, first NULL only at 21:54:08). Confirmed pure instruction-order bug, not a spec requirement — SIA DC-09 § 5.5.2 sets a MAXIMAL interval, not a minimal pre-wait; firing at t≈0 is spec-conforming. **Verbally authorized by Herve** ("ok met le dans 7_2 je suis ok avec le fonctionnement") in a prior session, but never formalized into story 7-2 as an AC/Task, so it was never implemented and 7-2/epic-7 are now closed without it. Fix: start-of-loop one-shot enqueue at daemon start only (NOT generalized to every INITIALIZING transition — would double-emit on reconnect). Needs a new story/amendment to land; not reopened tonight per Herve's 2026-09-21 decision (track only).
