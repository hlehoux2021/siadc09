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
