# Test Generation Summary — Epic 8: Configuration Wizard & CSR Presets

**Date:** 2026-05-11
**Framework:** pytest (levels 1, 2, 2.5)
**Approach:** Source-validation (L1), async integration (L2), IPC contract validation (L2.5)

## Generated Tests

### PHP Page Structure Validation
- [x] `tests/level1/test_wizard_php_structure.py` — 47 tests
  - Wizard step div IDs and class markers
  - data-l2key bindings for all config fields
  - Preset card data attributes (data-provider, data-preset-*)
  - Step 2 connection test UI elements (spinner, result, buttons)
  - Step 3 zone table structure (table, tbody, nozone warning)
  - Step 4 notification command picker (fields, buttons, error div)
  - Navigation buttons across all steps
  - Config summary display areas
  - JS/template inclusion and Jeedom page skeleton

### Cross-Component Config Key Consistency
- [x] `tests/level1/test_wizard_config_key_consistency.py` — 52 tests
  - CSR keys consistent across PHP data-l2key ↔ Python config.get()
  - CSR keys consistent across PHP ↔ JS selectors
  - Preset fields: JSON ↔ PHP rendering ↔ JS fillFromPreset()
  - Wizard state key (sia_wizard_step) in PHP ↔ JS
  - Notification keys (sia_notify_cmd_id/human) in PHP ↔ JS
  - Zone mappings key in JS save ↔ summary
  - AJAX actions: JS callers ↔ PHP handlers
  - csr_provider key across all three layers
  - Supervision keys (supervision_interval, retry_count) in PHP ↔ Python CLI
  - encryption_key env-var security pattern

### JavaScript Wizard Logic Validation
- [x] `tests/level1/test_wizard_js_logic.py` — 40 tests
  - Step 1 validation rules (account hex, IP/TBD, port range, AES key)
  - Navigation state machine (show/hide, step triggers)
  - Connection test flow (spinner, button states, NAK handling, timeout)
  - Zone table serialization (step 3 save, step < 3 delete, data attributes)
  - Step 4 notification command picker (modal, filter, validation)
  - printEqLogic wizard/config mode switching
  - Config summary population
  - Jeedom framework integration (save API, type, restart, daemon check)

### AJAX Endpoint Contract Validation
- [x] `tests/level1/test_wizard_ajax_contracts.py` — 39 tests
  - Security guards (admin auth, exception throw, ajax::init)
  - testConnection: equipment loading, missing equipment handling, encryption key security, escapeshellarg injection prevention, flags, time limit, error handling
  - getZones: alarm plugin loading, missing plugin/zones error responses, zone name extraction
  - getCameraCommands: generic type queries, response shape, label format, null filtering
  - Global error handling (try/catch, unknown action, ajax::success consistency)

## Coverage Summary

| Source File | Tests | Coverage Focus |
|---|---|---|
| `desktop/php/siaDC09.php` | 99 | HTML structure + data bindings |
| `desktop/js/siaDC09.js` | 92 | Logic patterns + validation rules |
| `core/ajax/siaDC09.ajax.php` | 39 | Security + contracts + error handling |
| `resources/siadc09d/siadc09d.py` | 52 | Config key reads (cross-component) |
| `resources/siadc09d/csr_presets.json` | 6 | Preset field presence |

**Total new tests:** 178
**Total test suite (level 1):** 821 (was 643 before this session)
**All passing:** Yes (7.68s)

## Existing Tests (pre-session baseline: 96 tests)

| File | Tests | Focus |
|---|---|---|
| `test_connection_test.py` | 16 | Python _send_raw_once() + run_connection_test() |
| `test_csr_presets_json.py` | 14 | JSON schema validation |
| `test_php_eqlogic_stub.py` | 66 | PHP class methods + JS handler patterns |

## Testing Pattern

All new tests use the **source-validation** pattern: read source files as text, assert structural properties via string matching or regex. This catches:
- Renamed/removed HTML IDs or data attributes
- Broken cross-layer contracts (PHP saves key X, Python reads key Y)
- Missing validation rules or error handling branches
- Security guard removal

No Jeedom instance, browser, or network required.

---

## Level 2 — Async Integration Tests (session 2026-05-11)

### Connection Test Async Integration
- [x] `tests/level2/test_connection_test_async.py` — 22 tests
  - FakeTransport (implements SIABaseTransport) for realistic async testing
  - Transport lifecycle: start → send_frame → close sequence enforced
  - Resource cleanup: close() always called (start failure, send error, timeout)
  - Timeout enforcement via asyncio.wait_for() (real sleep-based delay)
  - NAK status propagation from transport result
  - Transport selection: parametrized UDP/TCP, case-insensitive
  - Constructor params: host/port/crc_format/timeout pass-through
  - Concurrent independence: gather() with separate transports, timeout isolation
  - Error classification: OSError, SIATransportError, unexpected → all map to timeout
  - run_connection_test integration: frame building, preset mode, elapsed_ms, encryption, no stdout leaks

---

## Level 2.5 — IPC Contract Validation (session 2026-05-11)

### Wizard Config → Daemon IPC
- [x] `tests/level2_5/test_wizard_config_ipc.py` — 17 tests
  - on_start() initial callback: emits info_update, supervision_state=1 (INITIALIZING)
  - on_start() omits event_state/event_label (retained across restarts)
  - SM1/SM2 initial state assertions (INITIALIZING, IDLE)
  - Preset → transport creation: UDP/TCP selection, crc_format pass-through
  - on_stop() terminal callback: supervision_state=0 (STOPPED), no event_state
  - First supervision IPC: ACK → HEALTHY (state=2), timeout → DEGRADED (state=1)
  - Wizard config preset mapping: host, port, transport, account, crc_format, interval
  - Payload contract: no booleans, 'type' field required, supervision_state is int in [0,2]

---

## Updated Coverage Summary

| Level | Source Focus | Tests | File |
|---|---|---|---|
| L1 | PHP page structure | 47 | `test_wizard_php_structure.py` |
| L1 | Config key consistency | 52 | `test_wizard_config_key_consistency.py` |
| L1 | JS wizard logic | 40 | `test_wizard_js_logic.py` |
| L1 | AJAX contracts | 39 | `test_wizard_ajax_contracts.py` |
| L2 | Connection test async | 22 | `test_connection_test_async.py` |
| L2.5 | Wizard config IPC | 17 | `test_wizard_config_ipc.py` |

**Total new tests (this epic):** 217 (178 L1 + 22 L2 + 17 L2.5)
**Total test suite:** 1198 tests, all passing (13.72s)

## Next Steps
- Run tests in CI pipeline
- Add edge case tests for preset JSON with multiple providers (when v1.1 adds more)
- Level 3 tests (live Jeedom) for full E2E wizard flow validation
