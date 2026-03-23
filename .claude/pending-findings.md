# Pending Adversarial Review Findings

**Session:** 2026-03-23 — Review 5 (general adversarial review of all 8 design docs)

## All findings resolved ✅

### Applied in first pass (F1–F5)

- **F1** ✅ NAK dispatch table in `daemon-design.md` — replaced with canonical pointer to `supervision-design.md` Task B.2
- **F2** ✅ `event_state`/`event_label` not reset on daemon restart — decision documented; commands renamed from `alarm_delivery_state`/`last_event_status` across all docs
- **F3** ✅ `postSave()` config hash (F8 from R4) — confirmed Option A (no restart); memory corrected
- **F4** ✅ `encode_message()` id_type values undocumented — full Component 0 API surface rewritten with why/what, input tables, return types
- **F5** ✅ Encryption key size + padding model + `*NULL` + `*ACK` — wizard accepts 32/48/64 hex; padding corrected to pseudo-random prefix model; `*NULL` and `*ACK` added to API

### Applied in second pass (F6–F12) — reviewed and validated one by one

- **F6** ✅ Already present — `$envPrefix` + `exec()` pattern in `php-core-design.md` lines 611–617. No change needed.
- **F7** ✅ `transport` added to `supervision_timeout` context table in `error-handler-design.md`. Also: missing `_notify(ErrorCode.SUPERVISION_TIMEOUT, {...})` call site added to `supervision-design.md` Task B.2 timeout path (strikes 1–2 only; strike=3 fires `SUPERVISION_DISCONNECTED` via `_update_sm1_from_strike()`).
- **F8** ✅ JS call site snippet added to `widget-design.md` Task 6.4 — shows how `data-supervision-interval` is read from DOM via `.data()` and passed to `siaDC09_checkStaleness()` on page load and `cmd::update`.
- **F9** ↩️ Reverted. IMA Protect hardcoded preset table in `php-core-design.md` replaced with pointer to `csr_presets.json` and `wizard-design.md` — no values hardcoded in PHP.
- **F10** ✅ `getCmd('info', $logicalId)` → `getCmd(null, $logicalId)` in `_handleInfoUpdate()` in `php-core-design.md`.
- **F11** ✅ Guard already exists in `_queue_consumer()` (daemon-design.md Task 1.7). Explicit note added to `supervision-design.md` Task B.2 documenting guard location and semantics.
- **F12** ✅ `message()` switch in `php-core-design.md` Task 2.6 — each of the four callback types now has its own `break` with a one-line implementation summary and explicit pointer to authoritative source doc.

### Additional finding resolved during F7 review

- **TRANSPORT_TRANSIENT removed** — no viable call site: supervision retries naturally via recurring loop; events retry via `_send_with_retry()`. OS exceptions in `_send_raw()` are caught, logged at WARNING, and returned as `{status: 'timeout'}`. Removed from `error-handler-design.md` (enum, ERROR_TIERS, T1 table, context table, logicalId table, title table, message template, Task 5a.2, Task 5a.5, testing strategy). `daemon-design.md` Task 1.3 updated with OS exception handling spec.

---

## Review 5 complete — no open findings
