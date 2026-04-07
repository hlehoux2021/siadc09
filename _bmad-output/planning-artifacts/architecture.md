---
stepsCompleted: [1, 2, 3, 4, 5]
inputDocuments:
  - '_bmad-output/planning-artifacts/prd.md'
  - '_bmad-output/brainstorming/brainstorming-session-2026-02-17.md'
  - 'docs/design/daemon-design.md'
  - 'docs/design/php-core-design.md'
  - 'docs/design/wizard-design.md'
  - 'docs/design/supervision-design.md'
  - 'docs/design/error-handler-design.md'
  - 'docs/design/logging-design.md'
  - 'docs/design/debug-ui-design.md'
  - 'docs/design/widget-design.md'
  - 'docs/experimentation.md'
workflowType: 'architecture'
project_name: 'my-project'
user_name: 'Herve'
date: '2026-03-31'
elicitationState:
  step: 2
  method: 'self-consistency-validation'
  pendingFindings: []
  resolvedFindings: [F1-moot, F2, F3, F4, F5]
  adrsCompleted: [ADR-01, ADR-02, ADR-03, ADR-04, ADR-05, ADR-06, ADR-07, ADR-08, ADR-09, ADR-10, ADR-11, ADR-12, ADR-13, ADR-14, ADR-15, ADR-16]
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

---

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

The plugin delivers 12 functional capabilities across four domains:

1. **Protocol Engine** — SIA DC-09-2021 message construction, AES-128 CBC encryption/decryption,
   ACK/NAK parsing, UDP and TCP transport
2. **State Machines** — SM1 (connection/supervision: INITIALIZING → HEALTHY → DEGRADED →
   TCP_RECONNECTING → NO_NETWORK) and SM2 (alarm event: IDLE → PENDING → CONFIRMED/FAILED)
3. **Jeedom Integration** — PHP eqLogic/cmd scaffolding, daemon IPC (JSON callbacks),
   auto-created equipment, INFO commands, dependency manager
4. **User Experience** — 4-step zero-jargon wizard, zone mapping table, supervision health
   widget, 3-tier error notifications, Diagnostic debug tab

**Non-Functional Requirements:**

| NFR | Requirement | Architectural Driver |
|-----|-------------|----------------------|
| Zero silent failures | Every undelivered alarm → critical notification within ACK timeout | Error handler must intercept all failure paths |
| Supervision lag ≤ 1 interval | State change reflected in INFO commands immediately | SM1 transitions must update Jeedom synchronously |
| Non-technical usability | Wizard uses domain language only (French, no protocol jargon) | CSR presets in JSON; wizard never exposes protocol params |
| Protocol compliance | Full SIA DC-09-2021: encryption, timestamps, supervision NULL | Fixed external standard — no design latitude |
| Python 3.10+ / Debian 12+ | Platform floor declared in info.json | `|` union syntax, `datetime.now(timezone.utc)`, asyncio patterns |
| Encryption key security | Key scrubbed from PHP scope after exec() | Key lifecycle is a cross-cutting security constraint |
| CSR extensibility | Community presets without modifying transport core | Preset architecture: csr_provider key + JSON config files |
| Clean install | Jeedom dependency manager, no manual steps | packages.json all-object format, venv-aware pip (F3/R3) |

**Scale & Complexity:**

- Primary domain: Embedded platform plugin (Python asyncio daemon + PHP plugin core)
- Complexity level: **High**
- Estimated architectural components: 9 (protocol, crypto, simulator, daemon core, PHP core,
  wizard, supervision, error handler, widget)

### Technical Constraints & Dependencies

- **Platform:** Jeedom 4.5+, PHP 8.x, Python 3.10+, Debian 12+
- **Daemon framework:** `jeedom-daemon-py` (`jeedomdaemon` pip package) — asyncio base class,
  JSON callback protocol, dependency_info sentinel
- **External protocol:** SIA DC-09-2021 (fixed; spec at `docs/SIA-DC-09-...`)
- **Single CSR, no failover:** v1.0 architecture assumes one CSR endpoint; multi-CSR deferred to v1.5
- **No epics/stories yet:** Architecture is derived from PRD + 8 component design documents;
  implementation stories to be created post-architecture

### Cross-Cutting Concerns Identified

1. **PHP/Python IPC boundary** — JSON callback protocol, payload schema, error propagation
   direction, encryption key lifecycle
2. **Zero silent failures** — propagates into every layer: protocol ACK/NAK, SM1/SM2
   transitions, error handler tiers, notification dispatch, widget staleness detection
3. **SIA DC-09-2021 compliance** — timestamp handling, CRC format (preset-configured), encrypted
   frame format, supervision NULL — spans protocol module, daemon core, supervision loop
4. **State machine consistency** — SM1 and SM2 share transport layer; TCP reconnection
   in SM1 must re-queue in-flight SM2 events; PriorityQueue tie-breaking
5. **Encryption key security** — key scrubbing at PHP/daemon boundary; key exposure
   limited to length-only in debug UI and logs
6. **Structured logging** — dual-line pattern (French INFO + English DEBUG), messages.py
   externalization, ring buffer, routine supervision throttle — spans all Python modules
7. **CSR preset extensibility** — csr_presets.json architecture must not bleed preset
   specifics into the transport core

---

## Architectural Decisions Surfaced

### ADR-01 — PHP/Python IPC Boundary Design

**Decision:** Push callbacks, daemon-authoritative, persistent config keys survive restarts. PHP renders last-known-good state when daemon is stopped.

| Option | Pro | Con |
|--------|-----|-----|
| Push callbacks (chosen) | Daemon authoritative; PHP is passive | PHP must tolerate stale state gracefully |
| Pull polling | PHP controls timing | Polling interval = latency + DB hammering |
| Shared DB state | No IPC needed | Race conditions; no real-time semantics |

---

### ADR-02 — Dual State Machine Independence vs Coupling

**Decision:** Independent SMs coordinated via PriorityQueue. SM1 triggers SM2 re-queue on TCP_RECONNECTING only. No SM1 state reference in SM2 logic.

| Option | Pro | Con |
|--------|-----|-----|
| Fully independent (chosen) | Clean separation; no cross-SM blocking | Requires explicit re-queue on TCP reconnect |
| SM1 gates SM2 | Simpler failure semantics | SM2 starved during DEGRADED; safety risk |
| Single unified SM | One codebase | State explosion; unmaintainable |

---

### ADR-03 — CSR Preset Extensibility Mechanism

**Decision:** JSON presets in `resources/siadc09d/presets/`, validated at startup against a fixed schema. Add `schema_version` field from v1.0 for forward compatibility.

| Option | Pro | Con |
|--------|-----|-----|
| JSON presets (chosen) | Zero-code extension; community-friendly | Schema must be stable; versioning needed |
| Hardcoded in Python | No schema risk | Community cannot add presets without fork |
| Plugin subclass per CSR | Type-safe extension | Too complex for community contributors |

---

### ADR-04 — Zero Silent Failures Enforcement Point

**Decision:** SM2 owns the invariant. Error handler owns dispatch policy (tiers, deduplication, channel selection). PHP persists outcome state across restarts.

**`_notify()` call pattern:** `_notify()` is a **synchronous wrapper** on the daemon class — `def _notify(self, code, ctx)` — that internally calls `_track_task(self._dispatch_notify(code, ctx), f"notify_{code.name}")`. `_dispatch_notify()` is the private `async def` that performs the actual dual-channel dispatch. Call sites across SM1 and SM2 use `self._notify(code, ctx)` without `await` or explicit task management. This encapsulates GC safety and exception visibility (via done-callback) at the source, without cluttering call sites with `_track_task()`.

| Option | Pro | Con |
|--------|-----|-----|
| SM2 owns enforcement (chosen) | Protocol logic stays in protocol layer | Error handler is passive — cannot add policy |
| Error handler owns enforcement | Centralized policy | Must inspect SM state — tight coupling |
| PHP enforces via polling | Simple | Latency; misses in-process failures |

---

### ADR-05 — Asyncio Task Lifecycle Management

**Decision:** All tasks created via `_track_task(coro: Coroutine, name: str)`. `_tasks: set[asyncio.Task]` initialized in `__init__`. Done-callbacks log exceptions. `on_stop()` cancels and awaits all.

**`_notify()` encapsulation:** `_notify()` is itself a synchronous wrapper that calls `_track_task()` internally (see ADR-04). Call sites never call `_track_task()` directly for notifications — `_notify()` is the single entry point. This means the "no bare `create_task()`" rule from ADR-05 is enforced structurally, not by convention.

| Option | Pro | Con |
|--------|-----|-----|
| `_track_task()` + set (chosen) | Full lifecycle control; exceptions surface | Slightly more boilerplate per task |
| Fire-and-forget | Zero boilerplate | Silent failures; GC risk; undebuggable |
| `asyncio.gather()` at top level | Simple cancellation | Doesn't work for dynamically spawned tasks |

---

### ADR-06 — CRC Format as Preset Configuration *(revised 2026-03-31)*

**Decision:** `crc_format` is a field in the CSR preset JSON (`"crc_format": "hex"` for IMA Protect, `"crc_format": "bin"` for Lupusec-based CSRs). Loaded from `self._preset['crc_format']` in `on_start()`. Fail fast if missing or invalid. No runtime detection, no `_crc_format_locked` flag, no `detect_crc_format()` function.

**Rationale:** The daemon is the *sender* (panel role) — it chooses the CRC format; the CSR receives it. Format is a CSR characteristic known at configuration time. `detect_crc_format()` applies to receivers (CSR role, as in ioBroker.sia), not senders.

| Option | Pro | Con |
|--------|-----|-----|
| Preset config field (chosen) | Known at startup; zero detection complexity | Preset schema must include `crc_format` |
| Runtime auto-detect from ACK | Works without config | Sender role cannot detect from own outbound frames |
| Hardcoded `'hex'` | Zero complexity | Breaks `'bin'`-only CSRs (Lupusec) |

**Design doc impact applied:** `detect_crc_format()` removed from `sia_protocol.py` spec; `_crc_format_locked` removed from daemon; CRC format contract section in `daemon-design.md` rewritten; NOTE in `supervision-design.md` removed.

---

### ADR-07 — Encryption Key Lifecycle at PHP/Daemon Boundary

**Decision:** Key scrubbed from PHP immediately after `exec()`. Daemon holds cipher context only — no key string after init. Debug UI shows length only. Logs never contain key value.

| Option | Pro | Con |
|--------|-----|-----|
| Scrub after exec() + length-only display (chosen) | Key never persists in PHP; minimal exposure | Daemon cannot rotate key without restart |
| Store in Jeedom config (encrypted) | Survives UI without re-entry | Config storage is readable by Jeedom admin |
| Environment variable | No CLI arg exposure | Jeedom doesn't support env-per-equipment |

---

### ADR-08 — Supervision Loop Timing and Ring Buffer Throttle

**Decision:** Ring buffer routine push throttled to 10-minute minimum interval. State-changing events (strikes, transitions, T3) always write immediately. INFO commands unaffected by throttle. Staleness threshold = 3× `supervision_interval` from equipment config (not hardcoded). Rationale: 3 missed supervision cycles is a clear sign of a frozen daemon loop; consistent with the PHP cron5 watchdog threshold.

| Option | Pro | Con |
|--------|-----|-----|
| Throttled ring buffer (10 min) + real-time INFO (chosen) | Low DB writes; display still real-time | Ring buffer doesn't capture every ACK |
| Write every ACK | Full audit trail | 1,440 DB writes/day; Jeedom DB bloat |
| No routine ring buffer writes | Zero DB overhead | No supervision history at all |

---

### ADR-09 — Daemon Startup Failure Policy (`on_start()`)

**Decision:** `on_start()` fails fast on config/preset validation errors only. Network unreachability is deferred to SM1. Failure writes to daemon log and surfaces via `isConnect()` returning false.

| Option | Pro | Con |
|--------|-----|-----|
| Fail-fast on config errors only (chosen) | Clear error surface; no zombie daemon | Must distinguish config vs network errors at startup |
| Always fail-fast (including network) | Simple policy | Daemon unusable on transient network loss |
| Graceful degradation | Daemon always "starts" | Silent failures; confusing UI state |

---

### ADR-10 — `testConnection` Isolation Model

**Decision:** `testConnection` is a standalone Python subprocess (`test_connection.py`). Synchronous `exec()` from PHP with `set_time_limit(30)`. JSON result on stdout: `{success, error_code?, raw_response?}`.

**Daemon-stop flow:** `testConnection` may be triggered even when the daemon is running. PHP checks `isConnect()` first; if the daemon is active, the wizard displays a warning and requests user confirmation before calling `daemon_stop()`. Connection fields remain populated in JS throughout the sequence (no data loss). After the test, the daemon stays stopped — it only restarts at final wizard step 4 validation.

| Option | Pro | Con |
|--------|-----|-----|
| Standalone subprocess + JSON stdout (chosen) | No daemon dependency; no SM1 interference | Must replicate minimal protocol stack |
| IPC to running daemon | Reuses daemon's protocol stack | Daemon must be running; SM1 interference risk |
| PHP-native socket | No Python overhead | Cannot reuse AES-128/SIA encoding logic |

---

### ADR-11 — SM1 Strike Counter vs Discrete DEGRADED Sub-states

**Decision:** Single DEGRADED state. `_strike: int` (1–3, capped). `_supervision_value()` pure function of strike. `_sm1_t3_fired: bool` prevents repeated T3.

**Reset points — both `_strike_counter` and `_sm1_t3_fired` reset to 0/False in two places:**
1. **ACK received** — normal recovery path
2. **TCP reconnect succeeded** (`TCP_RECONNECTING → INITIALIZING`) — prevents stale strike=3 from poisoning the fresh INITIALIZING state, and ensures the next DEGRADED(strike=3) cycle fires T3 again

| Option | Pro | Con |
|--------|-----|-----|
| Single DEGRADED + counter (chosen) | Clean; counter drives all outputs; no sub-state transitions | Counter must be explicitly reset on ACK |
| DEGRADED_1/2/3 sub-states | Explicit in state diagram | Transition logic duplicated; state explosion |
| DEGRADED with separate T3 timer | Decoupled notification | Two mechanisms to maintain for same behavior |

---

### ADR-12 — PriorityQueue Tie-breaking for Equal-Priority Items

**Decision:** `asyncio.PriorityQueue[tuple[int, int, float, QueueItem]]`. All puts use `(priority, next(self._seq), time.monotonic(), item)`. `_seq = itertools.count()` initialized in `__init__`.

| Option | Pro | Con |
|--------|-----|-----|
| 4-tuple with `count()` tie-breaker (chosen) | No TypeError; FIFO within priority; typed | Slightly more verbose queue puts |
| 3-tuple (priority, timestamp, payload) | Simpler | Float timestamp collisions possible; payload still compared |
| 2-tuple (priority, payload) | Minimal | TypeError on equal priority; untypeable |

---

### ADR-13 — TCP Connect Timeout Enforcement

**Decision:** `asyncio.wait_for(open_connection(...), timeout=preset.connect_timeout_s)` with fallback default of 10s. `asyncio.TimeoutError` caught in `_send_raw()`, socket closed, treated as strike trigger.

| Option | Pro | Con |
|--------|-----|-----|
| `wait_for()` + explicit socket close (chosen) | No indefinite hang; SM1 progresses; resource-safe | Timeout value must be tuned per CSR |
| Bare `open_connection()` | Zero complexity | Hangs indefinitely on filtered ports |
| OS-level TCP timeout (default ~2min) | No code change | 2-minute stall per attempt; supervision degraded |

---

### ADR-14 — SM2 State Transition Model (IDLE Role)

**Decision:** SM2 IDLE entered once at init only. CONFIRMED/FAILED transition directly to PENDING on next alarm trigger. `event_state=0` means "no alarm since daemon start" — never reset on subsequent cycles. `event_state` and `event_label` persist across daemon restarts.

| Option | Pro | Con |
|--------|-----|-----|
| IDLE = startup-only (chosen) | Meaningful `event_state=0`; simpler transitions | IDLE must be clearly documented as non-recurring |
| IDLE = resting state | Symmetric state machine | `event_state=0` loses its "never triggered" meaning |
| No IDLE (start in PENDING) | Minimal states | Cannot distinguish "never triggered" from "in-progress" |

---

### ADR-15 — User-Facing String Externalization Strategy

**Decision:** All French user-facing strings in `resources/siadc09d/messages.py` as module-level constants. Zero French strings elsewhere. `# TODO v1.1: gettext` comment in `messages.py` header. DEBUG strings inline in calling code.

| Option | Pro | Con |
|--------|-----|-----|
| `messages.py` flat constants (chosen) | Zero build complexity; single migration point | Not translatable until refactored |
| gettext from v1.0 | Future-proof | Build complexity; no immediate benefit |
| Inline strings | Zero abstraction | French scattered everywhere; unmigrateable |

---

### ADR-16 — Widget Rendering Strategy

**Decision:** `toHtml()` renders Bootstrap 3 panel with `supervision_state` color badge and staleness warning. Same template for desktop and mobile. JS-side staleness detection: `collectDate` older than 3× `supervision_interval` → grey badge + "Données non disponibles". No custom PHP stale check (unreachable in zombie scenario — `preToHtml()` serves cached HTML). No custom JS beyond the one-shot stale check.

| Option | Pro | Con |
|--------|-----|-----|
| PHP `toHtml()` + Bootstrap 3 panel (chosen) | Jeedom-stable; same template desktop+mobile | Refreshes only on dashboard reload (Jeedom default) |
| JS event listeners | Real-time updates | Version-fragile; mobile inconsistent |
| Jeedom tile (default) | Zero code | No supervision-specific display |

---

## Self-Consistency Validation — In Progress

*Method applied: Self-Consistency Validation across ADRs 01–16. Five findings identified, reviewed one by one.*

### F1 — ADR-06: First-frame CRC provisional default
**Status: MOOT** — Resolved by rewriting ADR-06. CRC format is loaded from preset at startup; no provisional default needed as the value is known before any frame is sent.

### F2 — ADR-10: testConnection daemon-stop flow
**Status: RESOLVED** — ADR-10 amended: wizard checks `isConnect()` and warns user if daemon active; user confirms before `daemon_stop()`; JS fields preserved throughout; daemon stays stopped after test.

### F3 — ADR-04 × ADR-05: `_notify()` call pattern
**Status: RESOLVED** — `_notify()` is a synchronous wrapper (`def`) that internally calls `_track_task(self._dispatch_notify(...), name)`. `_dispatch_notify()` is the `async def` implementation. All call sites use plain `self._notify(code, ctx)` — no `await`, no explicit `_track_task`. ADR-04 and ADR-05 updated.

### F4 — ADR-08 × ADR-16: Staleness threshold correction (2× → 3×)
**Status: RESOLVED** — ADR-08 and ADR-16 had a typo: said 2× but all design docs consistently use 3×. Both ADRs corrected to 3× `supervision_interval`, consistent with design docs and PHP cron5 watchdog.

### F5 — ADR-11: Strike reset at TCP_RECONNECTING → INITIALIZING
**Status: RESOLVED** — ADR-11 amended: both `_strike_counter` and `_sm1_t3_fired` reset at TCP reconnect success (in addition to ACK). Pseudocode in daemon-design.md `_tcp_reconnect_loop()` updated; supervision-design.md note was already correct.

---

## Starter Template Evaluation

### Primary Technology Domain

Embedded platform plugin (Python asyncio daemon + PHP Jeedom plugin core).
Standard web/mobile/API starters do not apply.

### Selected Starter: Jeedom Plugin Template

**Location:** `/Users/herve.lehoux/Dev/plugin-template`

**Rationale:** The canonical Jeedom plugin template provides the mandatory directory structure and PHP scaffolding required by the Jeedom platform. No web framework, bundler, or package manager is involved. The Python daemon layer is built on the `jeedomdaemon` pip package (asyncio base class).

**Architectural Decisions Provided by Starter:**

**Directory Structure:**
- `core/class/` — PHP eqLogic/cmd class
- `core/php/` — AJAX routing shim
- `desktop/php/` — equipment config page
- `plugin_info/` — `info.json`, `packages.json`, `install.php`
- `resources/siadc09d/` — Python daemon files

**Language & Runtime:**
- PHP 8.x (Jeedom plugin core)
- Python 3.10+ (daemon, `jeedomdaemon` pip package)
- Debian 12+ platform floor declared in `info.json`

**Not provided by starter (fully covered in component design documents):**
- Python daemon architecture, SM1/SM2 state machines, PriorityQueue
- SIA DC-09 protocol engine, AES-128 crypto, CSR simulator
- Error handler, logging, debug UI, widget

---

## Core Architectural Decisions

### Testing Strategy

**Framework:** pytest + pytest-asyncio (`asyncio_mode = "auto"`, function-scoped event loop, versions pinned). `jeedomdaemon` version pinned. Environment variable `JEEDOM_TEST_VERSION` selects Jeedom instance for Level 3 tests. Sentinel event loop test verifies asyncio configuration on every run.

**Contract-Driven Pyramid — 4 levels + Level 2.5:**

#### Level 1 — Unit Tests (pure Python, no I/O)

Target: protocol correctness and string externalization.

| Test | What it verifies |
|------|-----------------|
| Protocol encode/decode round-trip | SIA DC-09 frame integrity |
| `make_timestamp()` format | No `_` separator; timezone-aware |
| `crc_format` schema validation | Case-sensitive; rejects unknown values |
| `messages.py` French-only check | Zero non-French user-facing strings |
| `_EVENT_SIA_CODES` completeness | Every alarm type has a SIA code |
| Golden frame fixtures | Real Ajax Hub frames decode correctly; tagged `@pytest.mark.golden_frames` |

Golden frames stored as `.bin` files in `tests/fixtures/golden/`. `tests/fixtures/README.md` documents origin (Ajax Hub firmware version, capture method).

#### Level 2 — Daemon Integration Tests (asyncio, no Jeedom)

Target: SM1/SM2 transitions, task lifecycle, supervision loop behavior.

| Test | What it verifies |
|------|-----------------|
| SM1/SM2 full transition sequences | Correct state after each trigger |
| Strike → DEGRADED → ACK → HEALTHY | `_strike_counter` + `_sm1_t3_fired` reset |
| TCP_RECONNECTING strike/flag reset | Both flags reset on reconnect success |
| Interleaving scenario | Alarm during supervision; both complete correctly |
| `on_start()` fail-fast | Real malformed preset JSON → daemon exits with error |
| Shared sequence counter | `_seq` monotone under concurrent queue puts |
| `_dispatch_notify()` exception path | Exception logged; daemon does not crash |
| Ring buffer throttle | Mocked time; routine entry suppressed within 10-min window |
| IDLE startup-only invariant | SM2 never re-enters IDLE after first alarm |

**Async drain rule:** After triggering a state transition, tests call `await asyncio.gather(*daemon._tasks)` (task join) — never `await asyncio.sleep(0)`. Time-dependent tests inject a `time_mock` fixture; no `sleep()` in assertions.

**Simulator fixture:** CSR simulator on port 0 (OS-assigned). Fixture teardown calls `subprocess.kill()` — no graceful close, prevents port leak.

#### Level 2.5 — IPC Contract Tests (PHP/Python boundary)

Target: JSON callback schema integrity across PHP and Python sides.

**Recording shim** (not silent mock): a thin Python shim records every callback the daemon emits. Assertions check shape, types, and field presence — not just "was it called." `json.dumps()` type checking enforced: all field values serialized and verified round-trip.

**Schema fixture:** `tests/fixtures/ipc_schema.py` defines the canonical callback schemas with `# schema_version` comment header. Any callback shape change requires updating this fixture — enforced by a maintenance checklist note in the fixture file.

Covered callbacks: `info_update`, `error_update`, `message_center`, `notify`, `message_trace`.

#### Level 3 — PHP Integration Tests (requires Jeedom instance)

Target: Jeedom API integration, eqLogic lifecycle, cross-restart persistence.

Tagged `@pytest.mark.requires_jeedom`. `jeedom_client` pytest fixture creates and tears down equipment via Jeedom REST API.

| Test | What it verifies |
|------|-----------------|
| `preRemove()` | Equipment deleted → daemon stopped, config keys cleared |
| `getDiagnosticData` structure | All required keys present and correctly typed |
| `deamon_info()` with missing `notify_cmd` | Returns safe error; does not crash Jeedom |
| Cross-restart `last_errors` persistence | Errors written before stop, readable after restart |

#### Level 4 — Manual Acceptance Tests

- Full 4-step wizard end-to-end (IMA Protect preset)
- Widget staleness detection (supervisor stopped, wait 3× interval)
- Real hardware: Ajax Hub → CSR simulator golden frame capture
- PHP encryption key injection (cannot automate; requires live Jeedom)
- TCP half-open recovery (network partitioned mid-supervision)

**Accepted risks:**
- No independent encode validator (SIA DC-09 reference implementation unavailable)
- PHP encryption key injection path covered at Level 4 only
- TCP half-open scenario covered at Level 4 only
- Simulator ACK delay does not replicate real CSR RTT jitter — Level 4 required for timing validation

---

### Versioning Strategy

**Decision:** Single `info.json` version — no PHP/daemon runtime version handshake. Plugin PHP and daemon deploy as an atomic unit via Jeedom Market. The only realistic mismatch path (partial update) is caught by Jeedom's update integrity and Python/PHP import failures before the daemon starts.

**`DAEMON_VERSION` constant:** Manually-maintained string at the top of the daemon main file (e.g., `DAEMON_VERSION = "1.0.0"`). Must be updated alongside `info.json` before every Market publish (pre-release checklist item).

**Observability:**
- `on_start()` emits `INFO: Starting daemon version {DAEMON_VERSION}`
- `deamon_info()` response includes a `daemon_version` string field
- `getDiagnosticData` includes `daemon_version`

**IPC contract tracking:** `# schema_version` comment in `tests/fixtures/ipc_schema.py` tracks callback contract changes for developers and CI. Not enforced at runtime — developer-facing only.

**Level 1 test:** Assert `DAEMON_VERSION == json.load(open("plugin_info/info.json"))["version"]` — catches manual sync drift in CI before it reaches users.

| Option | Pro | Con |
|--------|-----|-----|
| Single `info.json` version (chosen) | Minimum complexity; atomic deployment model makes handshake unnecessary | Manual `DAEMON_VERSION` sync required |
| Plugin version + IPC schema version runtime handshake | Runtime detection of mismatch | Adds code to solve a problem the platform already handles |
| Full semver with compatibility matrix | Future-proof | Significant complexity; no benefit for atomic deployment |

---

### CI/CD Pipeline

**Decision:** GitHub Actions, two-job split. All levels including Level 3 on every push to main repo branches. Market release gated on both jobs passing on `main`.

#### `fast` job — GitHub-hosted runner (`ubuntu-22.04`)

Covers Levels 1 + 2 + 2.5. Runs on every push including fork PRs.

- `actions/setup-python` pinned to `python-version: "3.10"`
- Pre-test static analysis: `ruff` (linting) + `mypy` (type checking)
- pip cache keyed on `requirements-test.txt` hash
- `concurrency` group: cancel in-flight runs on new push to same branch

#### `integration` job — self-hosted runner (`[self-hosted, linux, arm64]`)

Covers Level 3. Runs on main repo pushes only (not fork PRs).

- **Runner:** Raspberry Pi 5, Debian 12 — matches production deployment target exactly
- `timeout-minutes: 30` — prevents indefinite blocking if runner is offline (systemd auto-restart configured)
- `pytest --timeout=60` per test — detects slow Jeedom API interactions
- `JEEDOM_TEST_URL` env var: base URL of the test Jeedom instance
- `JEEDOM_TEST_APIKEY` env var: API key for the test Jeedom instance
- Jeedom auto-update **disabled** on test instance — version pinned for test stability

**Session-scoped cleanup fixture (runs at session start):**
1. Call `daemon_stop()` for any running test daemon
2. Delete all equipment matching prefix `siadc09_test_*`
3. Clear global Jeedom message center state

This prevents orphan daemon processes and global state bleed between test sessions.

#### Release gate

| Branch type | `fast` required | `integration` required |
|-------------|----------------|----------------------|
| Feature branch | ✅ | ❌ |
| `main` | ✅ | ✅ (Market release blocked until passing) |
| Fork PR | ✅ (GitHub-hosted only) | ❌ |

#### Infrastructure documentation

`docs/ci-setup.md` — runner installation procedure + Jeedom test instance rebuild steps. Recovery runbook for Pi hardware failure.

**Pre-release checklist (not automated in v1.0):**
- Update `DAEMON_VERSION` constant to match `info.json` version
- Validate plugin zip structure against Jeedom Market mandatory file list

**Deferred:** Multi-version Jeedom matrix testing (defer to v1.1); automated Market zip structure CI step (checklist first, automate if missed once).

---

## Implementation Patterns & Consistency Rules

**Purpose:** Rules that prevent two AI agents implementing different tasks from making incompatible choices. Every rule below has a corresponding failure mode that motivated it.

---

### Naming Patterns

**Python (daemon, protocol, tests):**

| Element | Convention | Example |
|---------|-----------|---------|
| Modules, functions, methods, variables | `snake_case` | `_send_raw`, `supervision_loop` |
| Classes | `PascalCase` | `SM1State`, `QueueItem` |
| Module-level constants | `UPPER_SNAKE_CASE` | `DAEMON_VERSION`, `_EVENT_SIA_CODES` |
| Enum values | `UPPER_CASE` | `SM1State.HEALTHY`, `ErrorCode.EVENT_FAILED` |
| Type aliases | `PascalCase` | `NotifyCtx`, `SM1Trigger` |

**PHP (plugin core, wizard, widget):**
- Methods: `camelCase` · Classes: `PascalCase` · Jeedom config keys: `snake_case`

**IPC callback types** — exhaustive list; agents must not invent new ones without following the new-callback-type protocol:
`info_update` · `error_update` · `message_center` · `notify` · `message_trace`

`ipc_schema.py` is the authoritative source for callback schemas. The list above must mirror it; if they diverge, `ipc_schema.py` wins.

**IPC payload fields:** `snake_case`. No `None` values — omit absent fields entirely. No Python `bool` — use integers `0`/`1` for boolean-like values.

**Task names:** `f"notify_{code.name}"` · `"supervision_loop"` · `"reconnect_loop"` · `f"alarm_{self._sia_seq}"`

**Logger instantiation:** `logging.getLogger(__name__)` everywhere except the daemon entry point file, which uses `logging.getLogger("siadc09d")` explicitly.

**Sequence counter names:**
- `_sia_seq: int` — SIA message sequence number (1–999, wraps)
- `_queue_seq: itertools.count` — PriorityQueue tie-breaker (unbounded, explicit type annotation)

---

### Structure Patterns

| Artifact | Location |
|----------|----------|
| Python daemon modules | `resources/siadc09d/` |
| CSR preset JSON files | `resources/siadc09d/presets/` |
| French user-facing strings | `resources/siadc09d/messages.py` |
| PHP plugin core | `core/class/` |
| Config wizard + debug tab | `desktop/php/siaDC09.php` |
| All tests | `tests/` |
| Shared fixtures | `tests/fixtures/` |
| Golden frame `.bin` files | `tests/fixtures/golden/` (read-only; tests never write here) |
| IPC schema fixture | `tests/fixtures/ipc_schema.py` |
| CI runner setup docs | `docs/ci-setup.md` |

All tests invoked from project root. `make_queue_item()`, `make_error_entry()`, and context dataclasses are defined in `error_handler.py` and imported from there — no local redefinitions. Log helpers `_log_sm1_supervision()` and `_log_sm2_event()` defined in a single canonical module; all other modules import from there.

---

### Communication Patterns (IPC)

**Callback payload — flat JSON, `type` field at top level:**
```json
{"type": "info_update", "supervision_state": 2, "supervision_label": "Opérationnel"}
```
Never a nested envelope `{"type": "...", "data": {...}}`. Never include fields with `None` value. Never use `true`/`false` — use `1`/`0`.

**PHP field access:** `isset($data['field'])` — never `empty()`.

**`_send_callback(payload)` wraps the framework's `send_to_jeedom()`.** It is defensive: catches all exceptions, logs ERROR, returns — never re-raises. Failure to deliver a callback is non-fatal to daemon operation.

**New IPC callback type protocol:** (1) add to `ipc_schema.py`, (2) add PHP handler. Patterns list updated as documentation.

**New daemon command type protocol:** (1) add to daemon command dispatcher (logs WARNING + ignores unknown types), (2) add PHP `sendToDaemon()` caller, (3) add Level 2 test. `sendToDaemon()` is the exclusive PHP→daemon channel.

**`test_connection.py` output contract:** entire execution in `try/except`; only `print(json.dumps(result))` to stdout; all warnings redirected to stderr; `sys.exit(0)`; error response uses primitive types only. Never `print(str(result))`.

---

### Process Patterns — Enforcement Rules

#### Asyncio Task Management

**`_track_task(coro: Coroutine, name: str)` is the only valid task creation path:**
```python
# CORRECT
self._track_task(some_coro(), "descriptive_name")

# FORBIDDEN
asyncio.create_task(some_coro())  # untracked: GC risk + silent exception loss
```

**Done-callback in `_track_task()`:**
- Calls `self._tasks.discard(task)` as final step — prevents unbounded set growth
- Silently accepts `CancelledError` (expected shutdown signal)
- Logs all other exceptions at ERROR

**`asyncio.PriorityQueue` puts — always `put_nowait()` with 4-tuple:**
```python
self._queue.put_nowait((priority, next(self._queue_seq), time.monotonic(), item))
```

#### State Machine Transitions

**Always `await` transition methods directly — never wrap in `_track_task()`:**
```python
# CORRECT — sequential foreground step
await self._transition_sm1(SM1State.HEALTHY, ctx)

# FORBIDDEN — direct assignment skips all side effects
self._sm1_state = SM1State.HEALTHY

# FORBIDDEN — fire-and-forget makes timing undefined
self._track_task(self._transition_sm1(...), "name")

# FORBIDDEN — missing await drops coroutine silently
self._transition_sm1(SM1State.HEALTHY, ctx)
```

**Canonical `_transition_sm1()` ordering:**
1. Update `self._sm1_state`
2. Reset `_strike_counter` and/or `_sm1_t3_fired` if applicable
3. `self._update_info_commands()` — `def` (sync), never `async def`, never awaited
4. `self._log_sm1_supervision(ctx)` — never raw `self._logger` calls for SM transitions
5. `self._notify(code, ctx)` if required
6. `self.stop()` — **NO_NETWORK only**, after `_notify()`

**`_strike_counter` and `_sm1_t3_fired` are exclusively owned by `_transition_sm1()`.** No other code touches them directly.

**Canonical `_transition_sm2()` ordering:**
1. Update `self._sm2_state`
2. Update event fields from `ctx`: `_event_sia_code`, `_event_zone`, `_event_seq`
3. `self._update_info_commands()`
4. `self._log_sm2_event(ctx)` — `SM2LogCtx.elapsed = 0.0` for IDLE→PENDING
5. `self._notify(ErrorCode.EVENT_FAILED, ctx)` — EVENT_FAILED only

**`_event_sia_code`, `_event_zone`, `_event_seq` are exclusively owned by `_transition_sm2()`.** Never set externally.

**`_supervision_value()` and `_supervision_label()` are pure functions** — no side effects, no state mutation, no I/O. Called independently by `_update_info_commands()`.

**Log helpers raise `ValueError` on unknown `(old, new)` state pairs** — fail loud (ADR-03). Level 1 test maintains an exhaustive valid-pairs constant derived from the SM state diagram; new state = test fails if constant not updated.

#### Notification Pattern

```python
# CORRECT — synchronous wrapper, no await
self._notify(ErrorCode.SUPERVISION_DISCONNECTED, ctx)

# FORBIDDEN — breaks the sync-wrapper contract
await self._notify(...)

# FORBIDDEN — bypasses encapsulation
self._track_task(self._dispatch_notify(...), "name")

# FORBIDDEN — _notify() must be def, never async def
async def _notify(self, code, ctx): ...
```

**`_dispatch_notify()` is `async def`.** It sends to BOTH channels independently — each wrapped in its own `try/except`. Never short-circuits. Failure of one channel never prevents the other.

**Per-ErrorCode context requirements:**

| ErrorCode | Required context |
|-----------|-----------------|
| `SUPERVISION_TIMEOUT` | `SM1TimeoutCtx` |
| `SUPERVISION_NAK` | `SM1NakCtx` |
| `BAD_CSR_RESPONSE` | `SM1NakCtx` |
| `SUPERVISION_DISCONNECTED` | `None` acceptable |
| `EVENT_FAILED` | `EventFailedCtx` |
| `TRANSPORT_PERMANENT` | `None` acceptable |

**Context dataclasses are `@dataclass(frozen=True)`** — immutable after creation. Use `dataclasses.replace(ctx, field=new_val)` for derived contexts. All defined in `error_handler.py`; imported from there; no local redefinitions. Use `NotifyCtx` type alias — never re-expand the union inline.

#### SIA Sequence Counter

```python
# Correct ordering: encode → send → increment
frame = encode_message(..., seq=self._sia_seq, crc_format=self._preset["crc_format"])
await self._send_raw(frame)          # raises on timeout/error
self._sia_seq = (self._sia_seq + 1) % 10000  # wraps 9999 → 0000
```

`_sia_seq` initialized to `0` in `__init__`. First frame uses `0000`; wraps to `0000` after `9999`. Never incremented on send failure — retry uses the same sequence number (correct per SIA DC-09). Format string: `f"{self._sia_seq:04d}"` — always 4 digits, never 5.

#### `_send_raw()` Contract

- Returns `None` → ACK received
- Returns `bytes` → NAK received
- Raises exception → timeout or network error (never returns `None` for errors)
- Catches `asyncio.TimeoutError` (ADR-13) and converts to raised exception
- Catches `ValueError` from `encode_message()` → logs ERROR, returns without sending, **no strike increment** (internal error, not CSR communication failure)

`decode_message()` always raises `ValueError` on malformed input — never returns `None`. Callers use `try/except ValueError`.

#### Queue Items

**`QueueItem` TypedDict** — defined in daemon module:
```python
class QueueItem(TypedDict):
    type: str
    payload: bytes
    sia_code: str
    zone: str | None
    attempt: int          # starts at 1 for first send
    callback: Callable[[bool], None] | None  # sync, receives success: bool
```

**`make_queue_item(...)` is the only valid construction path** — used in production code AND test fixtures. Never construct the dict directly (TypedDict not runtime-enforced). `attempt` starts at `1`; incremented before re-queuing; check: `attempt > max_attempts`. `callback` is sync — not a coroutine.

#### `last_errors` Entries

**`make_error_entry(...)` factory in `error_handler.py`** — only valid construction path:
```python
{"code": str, "message": str, "timestamp": str,  # ISO 8601
 "context": dict | None, "count": int}            # all 5 fields mandatory
```

#### `on_stop()` Sequence

1. Call `_update_info_commands()` directly (explicit exception to transition rule — terminal state)
2. Cancel all tasks: `for task in self._tasks: task.cancel()`
3. `await asyncio.gather(*self._tasks, return_exceptions=True)`

**No `await` of any kind between steps 1 and 2.** asyncio single-threaded guarantee only holds without yield points.

**SM2 drain:** in-flight QueueItems resolved via `callback(False)` — without calling `_notify()`. Daemon is terminating; T3 delivery not guaranteed in shutdown path. PHP infers state from `supervision_state=0` + `event_state=3`.

**Terminal `info_update` delivery is best-effort** — if framework already torn down, `_send_callback()` catches the exception and logs. Accepted risk.

**Supervision loop checks framework stop flag at top of each iteration** — exits cleanly after `self.stop()` is called.

#### `messages.py` Rules

- Static strings only — **no format placeholders** (`%`, `.format()`, f-strings). Dynamic values built inside helper functions.
- Organized by domain sections: `# SM1 transitions` · `# SM2 transitions` · `# Error notifications` · `# Preset validation`
- Import style: `import messages` then `messages.CONSTANT` or named imports. Never `from messages import *`.
- Preset validation errors use `messages.py` constants — human-readable French for each missing/invalid preset field.

#### Preset Validation

`schema_version` validated against whitelist `[1]` in `on_start()`. Unknown version = fail-fast with `messages.py` error. `crc_format` accessed with explicit `KeyError` catch → `messages.py` error. `on_start()` does not read `event_state`/`event_label` from Jeedom config — SM2 always starts in IDLE.

#### PHP Patterns

**`preRemove()` ordering:** (1) `daemon_stop()`, (2) ring buffer config key cleanup. Jeedom handles `eqLogic` removal after `preRemove()` returns.

**`getDiagnosticData` mandatory fields** — all 7 always present with type-safe defaults:
`daemon_version: str` · `supervision_state: int` · `supervision_label: str` · `event_state: int` · `event_label: str` · `last_errors: []` · `last_messages: []`

Never override signal handlers — `jeedomdaemon` framework handles SIGTERM and calls `on_stop()`.

#### Type & Style Rules

```python
# CORRECT
datetime.now(timezone.utc)    # never datetime.utcnow()
str | None                    # never Optional[str]
int | str                     # never Union[int, str]
encode_message(..., crc_format=self._preset["crc_format"])  # keyword-only, no default
```

---

### Anti-Pattern Quick Reference

| Anti-pattern | Correct pattern |
|---|---|
| `asyncio.create_task(coro)` | `self._track_task(coro, "name")` |
| `await self._notify(code, ctx)` | `self._notify(code, ctx)` |
| `async def _notify(...)` | `def _notify(...)` (sync wrapper) |
| `self._sm1_state = SM1State.X` | `await self._transition_sm1(SM1State.X, ctx)` |
| `self._track_task(self._transition_sm1(...), ...)` | `await self._transition_sm1(...)` |
| `logger.info("Supervision perdue")` | `logger.info(messages.SUPERVISION_LOST)` |
| `messages.CONSTANT % args` | Static string in messages.py; f-string in helper |
| `{"type": "info_update", "data": {...}}` | `{"type": "info_update", field: value, ...}` |
| `Optional[str]` / `Union[X, Y]` | `str \| None` / `X \| Y` |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` |
| Plain `dict` as notify context | `@dataclass(frozen=True)` from `error_handler.py` |
| Mutate context after `_notify()` | `dataclasses.replace(ctx, field=new_val)` |
| `self._strike_counter += 1` directly | Inside `_transition_sm1()` only |
| `put_nowait((priority, item))` | `put_nowait((priority, next(_queue_seq), time.monotonic(), item))` |
| `QueueItem({...})` directly | `make_queue_item(...)` factory |
| `{"code": ..., "message": ...}` directly | `make_error_entry(...)` factory |
| `empty($data['field'])` in PHP | `isset($data['field'])` |
| `logging.getLogger("daemon")` | `logging.getLogger(__name__)` |
| `from messages import *` | `import messages` or named imports |
| `_send_raw()` raises `TimeoutError` | Caught inside `_send_raw()`; raises local exception |
| `decode_message()` returns `None` | Raises `ValueError` |
| Load `event_state` from config in `on_start()` | SM2 always starts in IDLE |
| `(self._sia_seq % 999) + 1` | `(self._sia_seq + 1) % 10000` — 4-digit wrap 9999→0000 |
| `asyncio.TaskGroup(...)` | `_track_task()` for each coroutine independently |
| `except Exception:` swallowing `CancelledError` | Typed `except (SIATransportError, SIAProtocolError):` or re-raise `BaseException` |
| `logging.basicConfig()` in daemon modules | Never — `jeedomdaemon` framework owns handler setup |
| Direct `deamon_stop()` from business logic | Only from `deactivate()`, `preRemove()`, `postSave()`, wizard confirm flow |
| `getConfiguration('key')` without default | `getConfiguration('sia_key', $typed_default)` |
| `isConnect()` as AJAX guard | `isConnect('admin')` |
| `$cmd->execute($options)` without parent | `parent::execute($options)` first, then plugin logic |
| Hardcoded French in `toHtml()` | `__('key', __FILE__)` i18n call |
| Clear `sia_last_errors` on daemon start | Persists across restarts; cleared only in `preRemove()` |
| Exponential backoff on TCP reconnect | Fixed `reconnect_delay_s` (preset field, default 5 s) |
| Sleep between alarm retries | No sleep — life-safety, prompt ACK expected |

---

### Exception Hierarchy (`sia_protocol.py`)

Two named exception classes replace generic `ValueError`/`OSError` for all protocol and transport failures:

```python
class SIATransportError(OSError):
    """Network/socket failure — TCP timeout, UDP timeout, socket closed."""

class SIAProtocolError(ValueError):
    """SIA DC-09 protocol violation — malformed frame, decode failure."""
```

- `_send_raw_tcp()` / `_send_raw_udp()` raise `SIATransportError` on all transport failures
- `encode_message()` / `decode_message()` raise `SIAProtocolError` on malformed data
- Call sites catch by type — never catch bare `Exception` for protocol/transport errors
- Both defined in `sia_protocol.py`; imported from there everywhere

---

### CSRPreset Dataclass (`presets.py`)

```python
@dataclass(frozen=True, slots=True)
class CSRPreset:
    csr_provider: str
    schema_version: int
    host: str
    port: int
    account_number: str
    transport: str             # "tcp" | "udp"
    crc_format: str            # "hex" | "bin"
    connect_timeout_s: float
    receive_timeout_s: float
    supervision_interval_s: float
```

`SUPPORTED_SCHEMA_VERSION: int = 1` — module constant in `presets.py`. `on_start()` raises `SIAProtocolError` if `preset.schema_version != SUPPORTED_SCHEMA_VERSION`. Constructs via `CSRPreset(**preset_dict)` — dataclass `__init__` catches missing fields at construction time.

**Schema mismatch policy:** ERROR log + `supervision_state=0` + clean stop. Watchdog must not restart in a tight loop on bad config.

**`presets.py` vs `presets/` distinction:**
- `presets.py` (module) — holds `CSRPreset` dataclass + `SUPPORTED_SCHEMA_VERSION` constant
- `presets/` (subdirectory under `resources/siadc09d/`) — holds preset JSON files (e.g. `ima_protect.json`)

Wizard "Personnaliser" writes `schema_version` to the equipment config key at copy time — version check is against config key value, not the JSON file.

---

### Transport Layer Dispatch

`_send_raw(frame: bytes) -> bytes | None` dispatches to `_send_raw_tcp()` or `_send_raw_udp()` based on `self._preset.transport`. **Only `_queue_consumer` may call `_send_raw()`** — any other call site is an architectural violation.

**`_send_raw_tcp()` rules:**
- `asyncio.wait_for(open_connection(...), timeout=preset.connect_timeout_s)` — never bare `open_connection()`
- Response read: `asyncio.wait_for(reader.read(...), timeout=preset.receive_timeout_s)`
- `finally:` block closes writer unconditionally — even on exception
- Not reentrant — single-caller-at-a-time; `asyncio.StreamWriter`/`StreamReader` owned exclusively within the method; no concurrent reader task

**`_send_raw_udp()` rules:**
- Uses a **persistent** `asyncio.DatagramTransport` created in `on_start()`, closed in `on_stop()` — never per-send socket creation (avoids ephemeral port exhaustion)
- Implemented via `_SIADatagramProtocol(asyncio.DatagramProtocol)` with an `asyncio.Future` reply gate: `datagram_received()` sets the future; `_send_raw_udp()` awaits it with `asyncio.wait_for(..., timeout=preset.receive_timeout_s)`
- One `asyncio.Future` per send; replaced after each reply

---

### `last_messages` Entries

**`make_message_entry(...)` factory in daemon module** — only valid construction path:
```python
{"type":      str,           # "alarm" | "supervision"
 "timestamp": str,           # ISO 8601, timezone-aware
 "sia_code":  str,
 "zone":      str | None,    # alarm only
 "attempt":   int | None,    # alarm only
 "result":    str}           # "ack" | "nak" | "timeout"
```
All 6 fields mandatory; use `None` for absent optional fields — do not omit keys.

`sia_last_messages` — max 50 entries, newest first. Routine supervision: latest entry replaces previous (ring buffer, not appended). Alarm event retries: ONE entry with nested `attempts` array.

---

### Zone Mapping Defensive Patterns

`zone_mappings` schema per entry:
```python
{"zone_name":      str,           # mandatory
 "camera_cmd_id":  int | None,    # optional
 "media_url":      str | None}    # optional
```
`None` and missing key are equivalent — agents must not treat them differently.

**Runtime lookup — always defensive:**
```python
mapping = next((z for z in self._zone_mappings if z["zone_name"] == zone_name), None)
```
Unmapped zone: alarm frame sent without camera/media, WARNING logged. Daemon never crashes on unmapped zone.

**Wizard Step 3 empty state:** if no alarm plugin zones detected, show helper message ("Aucune zone détectée — configurez d'abord votre plugin alarme") — never raise or silently skip.

---

### Shutdown & Cancellation Discipline

**`on_stop()` sequence (updated):**
1. `_update_info_commands()` — direct call (terminal state exception to transition rule)
2. Queue drain: `while not self._queue.empty(): self._queue.get_nowait()`
3. `for task in self._tasks: task.cancel()`
4. `await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=5.0)` — hard 5 s ceiling; `asyncio.TimeoutError` logged and ignored

**`CancelledError` discipline:**
- `asyncio.CancelledError` is `BaseException`, not `Exception`
- `except Exception:` in daemon coroutines must never silently swallow `CancelledError`
- Use typed `except (SIATransportError, SIAProtocolError):` or add `except BaseException: raise`
- `asyncio.TaskGroup` is **forbidden** — incompatible with `_track_task()` lifecycle model
- `asyncio.gather(..., return_exceptions=True)` is **mandatory** in `on_stop()` — never bare `gather()`

---

### Retry & Backoff Policy

| Scenario | Policy | Rationale |
|----------|--------|-----------|
| Alarm retries | No sleep between retries (up to `MAX_ALARM_ATTEMPTS: int = 3`) | Life-safety; DC-09 expects prompt ACK |
| Supervision strikes | Accumulate at normal `supervision_interval_s` — no eager retry | Protocol-correct per DC-09 |
| TCP reconnect | Fixed `reconnect_delay_s` sleep (preset field, default 5 s) | CSR is always-on; exponential backoff is anti-pattern here |

`MAX_ALARM_ATTEMPTS: int = 3` — module-level constant in daemon module. Retry check: `item["attempt"] > MAX_ALARM_ATTEMPTS`. Exponential backoff and per-retry sleep for alarms are **forbidden**.

---

### T1 Error Auto-Resolve

When SM1 transitions to `HEALTHY` (ACK received after DEGRADED), T1 errors (`SUPERVISION_TIMEOUT`, `SUPERVISION_NAK`) are auto-resolved: remove all T1-tier entries from `sia_last_errors` before pushing the updated `error_update` callback.

`sia_last_errors` **persists across daemon restarts** — PHP reads it at page load; cleared only in `preRemove()`.

---

### `messages.py` Extended Rules

**`T3_PREFIX` constant:**
```python
T3_PREFIX: Final[str] = "CRITIQUE — "
```
All T3-tier notification messages prepend this prefix. Level 1 test: assert every T3 message starts with `T3_PREFIX`. Never hardcode the prefix string at call sites.

**`SIA_NULL_CODE` constant:**
```python
SIA_NULL_CODE: Final[str] = "NULL"
```
Used for supervision frames only. `SIA_NULL_CODE` is **not** in `_EVENT_SIA_CODES`. Level 1 test: assert `SIA_NULL_CODE not in _EVENT_SIA_CODES`.

**Domain section headers:**
```python
# --- SM1 transitions ---
# --- SM2 transitions ---
# --- Error notifications (T1 / T2 / T3) ---
# --- Preset validation ---
# --- Wizard UI ---
```

**Zero imports rule:** `messages.py` has no imports (stdlib `typing.Final` only if needed). It is always the first module in the creation/import chain — no circular dependency risk.

`_supervision_label()` and `_event_label()` return constants from `messages.py` — never construct label strings inline.

---

### Canonical File Creation Order

To avoid circular imports, agents must create files in this order:

1. `messages.py` — zero imports; pure constants
2. `error_handler.py` — imports `messages`
3. `presets.py` — imports `messages`
4. `sia_protocol.py` + `sia_crypto.py` — imports `messages`
5. `daemon.py` — imports all above
6. PHP layer — no Python imports

Each file's imports only reach back in this chain.

---

### PHP Extended Patterns

#### Config Key Namespace

All plugin-owned config keys use the `sia_` prefix (e.g. `sia_last_errors`, `sia_last_messages`, `sia_wizard_step`, `sia_zone_mappings`). Jeedom framework keys are never overwritten.

`getConfiguration()` always called with a typed default matching the value type:
```php
$this->getConfiguration('sia_wizard_step', 0)      // int default for int key
$this->getConfiguration('sia_zone_mappings', [])   // array default for JSON array
$this->getConfiguration('sia_host', '')            // string default for string key
```

#### Config Key Registry

| Key | Type | Default | Writer | Reader |
|-----|------|---------|--------|--------|
| `sia_wizard_step` | int | `0` | PHP | PHP |
| `sia_last_errors` | JSON array | `[]` | daemon | PHP |
| `sia_last_messages` | JSON array | `[]` | daemon | PHP |
| `sia_zone_mappings` | JSON array | `[]` | PHP | PHP + daemon |
| `sia_supervision_state` | int | `0` | daemon | PHP |
| `sia_supervision_label` | str | `''` | daemon | PHP |
| `sia_event_state` | int | `0` | daemon | PHP |
| `sia_event_label` | str | `''` | daemon | PHP |
| `sia_notify_cmd_id` | int | `0` | PHP | PHP |
| `sia_notify_cmd_human` | str | `''` | PHP | PHP (display only) |

`*_human` keys are display-only companions — never passed to daemon, never used in logic.

#### `deamon_` Prefix Trap

Jeedom uses the historical misspelling `deamon_` (not `daemon_`) for all framework hook methods: `deamon_start()`, `deamon_stop()`, `deamon_info()`, `deamon_running()`. The correct spelling `daemon_start()` is **silently ignored** — no error, no execution.

`deamon_stop()` / `deamon_start()` called only from: `postSave()` (restart-required changes), `preRemove()`, `deactivate()`, wizard connection test (after user confirmation). Never called from business logic.

**Restart-required config keys** (`postSave()` restart guard checks only these):
`sia_host` · `sia_port` · `sia_transport` · `sia_account_number` · `sia_encryption_key` · `sia_supervision_interval_s`

#### AJAX Guard

All AJAX-facing PHP methods: `if (!jeedom::isConnect('admin')) { throw new Exception('Unauthorized'); }`

#### `notify_cmd_id` Two-Layer Validation

1. Wizard Step 4: `jeedom.cmd.getSelectModal()` ensures user selects a real command — saves `sia_notify_cmd_id`
2. `_notify()` PHP handler: re-validates `sia_notify_cmd_id > 0` before calling `cmd::byId()` — defensive guard against stale config

#### `activate()` / `deactivate()` Lifecycle

```php
public function deactivate(): void {
    if ($this->deamon_running()) { $this->deamon_stop(); }
}
public function activate(): void {
    // do NOT auto-start daemon — watchdog or user starts explicitly
}
```

`toHtml()` — when `getIsEnable() === 0`: render grey "Désactivé" badge; ignore `supervision_state` entirely.

#### Other PHP Rules

- `returnStateTime = 30`, `returnStateValue = 0` on all commands — prevents stuck PENDING if daemon stops mid-execution
- `dependancy_info()` **never throws** — always returns `['state' => ..., 'progression' => ...]`
- `cmd::execute()` subclass override always calls `parent::execute($options)` **first**
- All commands: `isVisible = 0` — display via widget only, not in Jeedom dashboard command list
- `install.php` contains dependency installation only — no plugin logic, no config mutation
- `toHtml()` contains no hardcoded French strings — all user-facing text via `__('key', __FILE__)` i18n calls
- `info.json`: `"require": {"jeedom": ">=4.5"}`, `"os": {"min": 12}`

#### Wizard Step Map (canonical)

| `sia_wizard_step` | Meaning |
|-------------------|---------|
| `0` | Not started |
| `1` | Preset selection complete |
| `2` | Connection test complete |
| `3` | Zone mapping complete |
| `4` | Configuration mode (wizard complete) |

Wizard "Next": saves `sia_wizard_step` as the **first statement** before any side effect — browser-refresh safe.

#### `test_connection.py` Exit Contract

```
exit 0  →  stdout: "success"
exit 1  →  stdout: "failure"  or  "timeout"
```
No free-form stderr surfaced to PHP. `set_time_limit(30)` mandatory before `exec()` call. The subprocess may use `asyncio.run()` internally — "synchronous" means PHP `exec()` blocks; the subprocess is free to use any Python async pattern.

---

### Error Context Schema Table

| ErrorCode | Dataclass | Required fields | Optional fields |
|-----------|-----------|-----------------|-----------------|
| `SUPERVISION_TIMEOUT` | `SM1TimeoutCtx` | `strike: int`, `interval_s: float` | — |
| `SUPERVISION_NAK` | `SM1NakCtx` | `strike: int`, `raw_nak: bytes` | `parsed_ts: datetime \| None` |
| `BAD_CSR_RESPONSE` | `SM1NakCtx` | `strike: int`, `raw_nak: bytes` | `parsed_ts: datetime \| None` |
| `SUPERVISION_DISCONNECTED` | `None` | — | — |
| `EVENT_FAILED` | `EventFailedCtx` | `zone: str \| None`, `sia_code: str`, `attempts: int` | — |
| `TRANSPORT_PERMANENT` | `TransportPermanentCtx` | `transport: str` | `last_error: str \| None` |

`ErrorContext = SM1TimeoutCtx | SM1NakCtx | EventFailedCtx | TransportPermanentCtx | None`

All context dataclasses: `@dataclass(frozen=True, slots=True)`. Defined in `error_handler.py`; imported from there everywhere. `_notify()` signature: `def _notify(self, code: ErrorCode, ctx: ErrorContext) -> None`.

---

### Callback Contract Table

Single authoritative reference for all `_send_callback()` payload shapes:

| `type` | Required keys | Optional keys | PHP consumer |
|--------|---------------|---------------|--------------|
| `info_update` | `supervision_state`, `supervision_label`, `event_state`, `event_label` | — | `deamon_callback()` |
| `error_update` | `last_errors` (JSON array) | — | `deamon_callback()` |
| `message_center` | `level`, `message` | `action` | `deamon_callback()` |
| `notify` | `cmd_id`, `message` | — | `deamon_callback()` |
| `message_trace` | `last_messages` (JSON array) | — | `deamon_callback()` |

New callback types require: (1) add to this table, (2) add to `ipc_schema.py`, (3) add PHP handler. Order is mandatory.

---

### eqLogic Lifecycle Map

| Hook | Triggered by | Plugin actions |
|------|--------------|----------------|
| `preInsert()` | Equipment creation (before save) | Validate unique `account_number` |
| `postInsert()` | Equipment creation (after save) | Auto-create all INFO commands |
| `postSave()` | Any save | Restart daemon if restart-required keys changed |
| `activate()` | Equipment enabled | No-op (watchdog starts daemon) |
| `deactivate()` | Equipment disabled | `deamon_stop()` if running |
| `preRemove()` | Equipment deletion | `deamon_stop()` + clear `sia_last_errors` / `sia_last_messages` |

---

### Extended Testing Patterns

#### Additional Level 1 Tests

| Test | What it verifies |
|------|-----------------|
| `_sia_seq` wrap: 9999 → 0000 | `(9999 + 1) % 10000 == 0` |
| `_sia_seq` zero-pad: seq=0 → `"0000"` | 4-digit format string always |
| `SIA_NULL_CODE not in _EVENT_SIA_CODES` | Supervision NULL not treated as alarm code |
| Every T3 message starts with `T3_PREFIX` | Prefix constant applied at all T3 sites |
| `DAEMON_VERSION == info.json["version"]` | Version sync not drifted (CI regression guard) |
| Boundary-value context dataclasses | Each `ErrorCode` → `make_error_entry()` → valid JSON with all required keys |
| `SIATransportError` / `SIAProtocolError` importable | Exception hierarchy intact |
| `messages.py` has zero imports | No circular dependency risk |

#### Additional Level 2 Tests

| Test | What it verifies |
|------|-----------------|
| `on_stop()` during SM2=SENDING | `_send_callback(False)` fires; no `_notify()`; `_tasks` empty post-stop |
| `_tasks` empty after `on_stop()` | No task leaks |
| UDP ACK path | `datagram_received()` → `_send_raw_udp()` returns `None` |
| UDP timeout path | No `datagram_received()` → `SIATransportError` raised |
| TCP / UDP parameterized (`transport` fixture) | SM1/SM2 sequence correct for both transports |
| Schema mismatch in `on_start()` | `SIAProtocolError` raised; `supervision_state=0` set |
| `caplog` for SM transition log lines | Every SM1/SM2 transition emits expected log lines |
| `asyncio.wait_for(gather, timeout=5.0)` ceiling | Hard shutdown ceiling respected |

#### Additional Level 3 Tests

| Test | What it verifies |
|------|-----------------|
| `toHtml()` with stubbed `sia_last_errors` | Rendered HTML contains expected error entries |
| `isVisible=0` on all commands | No commands appear in dashboard command list |
| PHP i18n keys round-trip | All `__('key', __FILE__)` keys exist in `core/i18n/fr_FR.json` |
| `dependancy_info()` never throws | Returns valid array under all mock states |

#### Test Infrastructure Rules

- `conftest.py` at `tests/` root for project-wide fixtures; sub-`conftest.py` per level (`tests/level2/conftest.py`)
- `asyncio_mode = "auto"` in `pyproject.toml` `[tool.pytest.ini_options]`
- All custom markers registered in `pyproject.toml`: `golden_frames`, `requires_jeedom`, `slow`
- Golden frames in `tests/fixtures/golden/` — read-only; tests never write here
- `caplog` (pytest built-in) for all log assertion tests — never mock the logger directly

---

### Pattern Compliance Checklist

#### Automated (CI — `fast` job)

- [ ] `ruff` passes (includes `DTZ003` — `datetime.utcnow()` banned)
- [ ] `mypy` passes
- [ ] `DAEMON_VERSION == info.json["version"]` (Level 1)
- [ ] `messages.py` zero imports (Level 1)
- [ ] Every T3 message starts with `T3_PREFIX` (Level 1)
- [ ] `SIA_NULL_CODE not in _EVENT_SIA_CODES` (Level 1)
- [ ] `_sia_seq` wrap 9999→0000 (Level 1)
- [ ] All `ErrorCode` contexts serialize to valid JSON with required keys (Level 1)

#### Manual (pre-release)

- [ ] No hardcoded French strings outside `messages.py` (Python) or i18n files (PHP)
- [ ] No `encryption_key` value in any log output — run with test key, grep logs
- [ ] All new `sendToJeedom()` callback types in Callback Contract Table + `ipc_schema.py`
- [ ] All new config keys in Config Key Registry table
- [ ] Restart-required key list in `postSave()` matches Config Key Registry
- [ ] Wizard Step Map integers match `sia_wizard_step` values in PHP
- [ ] `SUPPORTED_SCHEMA_VERSION` matches latest preset JSON `schema_version` field
- [ ] `jeedomdaemon` version in `packages.json` matches version used in Level 2 tests
