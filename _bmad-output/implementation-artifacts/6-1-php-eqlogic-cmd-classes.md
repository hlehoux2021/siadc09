# Story 6.1: PHP eqLogic & cmd Classes

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a Jeedom plugin developer,
I want eqLogic and cmd classes that extend the Jeedom framework with SIA DC-09 specific behaviour,
So that the plugin integrates properly with Jeedom architecture and can dispatch alarm events to the daemon and receive state callbacks.

## Acceptance Criteria

1. **eqLogic class** — `siaDC09` class in `core/class/siaDC09.class.php` extends Jeedom `eqLogic` with:
   - `deamon_info()`: returns state (ok/nok from PID file), log key (`__CLASS__ . '_daemon'`), and `launchable` (ok if config keys `csr_ip`, `csr_port`, `transport` all non-empty; nok otherwise)
   - `deamon_start()`: builds CLI args from eqLogic config, launches `resources/siadc09d/siadc09d.py` via `exec()&`, waits up to 10s for PID
   - `deamon_stop()`: kills daemon by PID and by script name
   - `sendToDaemon(array $params)`: sends JSON via TCP socket to socketport (reads from config), adds apikey
   - `isConnect()`: returns bool — config valid AND daemon state ok
   - `postSave()`: creates/verifies 7 commands (3 action + 4 info) — never restarts daemon
   - `preRemove()`: stops daemon cleanly
   - `_getAutoEquipmentSafe()`: static helper — returns the single equipment or null (logs error if missing/multiple)
   - `dependancy_info()`: uses sentinel `.install_ok` file pattern (not venv check) — returns `['state' => 'ok']` if file exists

2. **cmd class** — `siaDC09Cmd` class in `core/class/siaDC09Cmd.class.php` (separate file) with `execute()`:
   - `burglarAlarm`: extracts `#zone#` from title via `$_options['title']`; sends `{cmd: 'burglarAlarm', zone: $zone}` to daemon
   - `fireAlarm`: same pattern, sends `{cmd: 'fireAlarm', zone: $zone}`
   - `panicAlarm`: same pattern, sends `{cmd: 'panicAlarm', zone: $zone}`
   - INFO commands: no `execute()` logic needed (updated by daemon callbacks, not user-initiated)

3. **7 commands defined** — `postSave()` creates idempotently (uses `getCmd(type, logicalId)` guard):
   - `burglarAlarm` (action/message, isVisible=0, name="Alarme intrusion")
   - `fireAlarm` (action/message, isVisible=0, name="Alarme incendie")
   - `panicAlarm` (action/message, isVisible=0, name="Alarme panique")
   - `supervision_state` (info/numeric, isVisible=0, name="État supervision")
   - `supervision_label` (info/string, isVisible=0, name="Supervision")
   - `event_state` (info/numeric, isVisible=0, name="État alarme")
   - `event_label` (info/string, isVisible=0, name="Alarme")

4. **Config keys** — `deamon_start()` reads from eqLogic config using `sia_` prefix:
   - `csr_ip`, `csr_port`, `transport`, `account_number`, `encryption_enabled`, `encryption_key`
   - `receiver_prefix`, `account_prefix`, `supervision_interval`, `retry_count`
   - `sia_notify_cmd_id` (for daemon's `--notify-cmd-id` arg)
   - socketport read from plugin-level config (`config::byKey('socketport', __CLASS__, 55009)`)

5. **`deamon_start()` command construction** — matches the pattern from `aiodemo.class.php`:
   - Uses `system::getCmdPython3()` (with `getPython3()` fallback for older Jeedom versions)
   - Daemon log target: `log::getPathToLog(__CLASS__ . '_daemon')`
   - Appends `>> logfile 2>&1 &` for background execution
   - Passes `--callback` using `network::getNetworkAccess('internal', 'proto:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php'`

6. **AJAX file** — `core/ajax/siaDC09.ajax.php` with `isConnect('admin')` guard, `ajax::init()`, and placeholder for future actions.

7. **`info.json`** — updated for plugin identity:
   - `id: "siaDC09"`, `name: "Télésurveillance"`, `require: "4.5"`, `category: "security"`
   - `hasDependency: true`, `hasOwnDeamon: true`, `maxDependancyInstallTime: 60`
   - `"os": {"min": 12}` for Debian 12+ (Python 3.10+)
   - Languages: `["fr_FR", "en_US", "de_DE"]`

8. **`packages.json`** — updated with all Python deps:
   - `pip3: { "jeedomdaemon": {}, "pycryptodome": {} }`

9. **Unit tests** — `tests/level1/test_php_eqlogic_stub.py` (Python stubs only): verifies the `siaDC09` command logical IDs and types match the expected constants. Uses pytest, no Jeedom instance required. (Full PHP integration tests are Story 6.6.)

---

## Tasks / Subtasks

### Task 1: Update `plugin_info/info.json` (AC7)

- [x] **1.1** Change `id` from `"aiodemo"` to `"siaDC09"`
- [x] **1.2** Change `name` from `"AsyncIO Demo"` to `"Télésurveillance"`
- [x] **1.3** Change `require` from `"4.2.0"` to `"4.5"`
- [x] **1.4** Change `category` from `"programming"` to `"security"`
- [x] **1.5** Add `"os": {"min": 12}` field (Debian 12+ for Python 3.10+)
- [x] **1.6** Update `language` array to `["fr_FR", "en_US", "de_DE"]`
- [x] **1.7** Keep `hasDependency: true`, `hasOwnDeamon: true`, `maxDependancyInstallTime: 60`

---

### Task 2: Update `plugin_info/packages.json` (AC8)

- [x] **2.1** Add `"pycryptodome": {}` to `pip3` section alongside existing `jeedomdaemon`
- [x] **2.2** Keep `"python3-pip": {}` in `apt` section
- [x] **2.3** Verify all-object format (not string values) — current file already uses correct format

---

### Task 3: Create `core/class/siaDC09.class.php` — eqLogic class (AC1, AC4, AC5)

- [x] **3.1** Create file with GPL header + `require_once` for `core.inc.php`
- [x] **3.2** Implement `getPython3()` private static method (mirrors aiodemo pattern):
  ```php
  private static function getPython3(): string {
      if (method_exists('system', 'getCmdPython3')) {
          return system::getCmdPython3(__CLASS__);
      }
      return 'python3 ';
  }
  ```
- [x] **3.3** Implement `_getAutoEquipmentSafe()` private static method:
  - Returns single `siaDC09` equipment, or null if none/multiple
  - Logs error if multiple equipment found (should never happen, plugin-centric design)
  - Uses `eqLogic::byType(__CLASS__)` and checks count
- [x] **3.4** Implement `deamon_info()` static method:
  - PID file: `jeedom::getTmpFolder(__CLASS__) . '/daemon.pid'`
  - `state`: 'ok' if PID file exists and `posix_getsid(pid)` succeeds, 'nok' otherwise
  - `log`: `__CLASS__ . '_daemon'`
  - `launchable`: 'ok' if `$eqLogic->getConfiguration('csr_ip', '') != ''` AND `csr_port != 0` AND `transport != ''`; 'nok' otherwise (with `launchable_message`)
  - Uses `_getAutoEquipmentSafe()` to get the equipment
- [x] **3.5** Implement `deamon_start()` static method (AC5):
  - Call `self::deamon_stop()` first
  - Check `deamon_info()['launchable'] != 'ok'` → throw Exception
  - Build `$path = realpath(dirname(__FILE__) . '/../../resources/siadc09d')`
  - Script: `siadc09d.py` (entry point — deferred to Epic 6.6 for full arg wiring)
  - Mandatory args: `--loglevel`, `--socketport`, `--callback`, `--apikey`, `--pid`
  - CSR config args from eqLogic: `--host`, `--port`, `--transport`, `--account`, `--crc-format`
  - Optional: `--encryption-enabled`, `--encryption-key`, `--supervision-interval`, `--retry-count`
  - Log: `__CLASS__ . '_daemon'`; run background: `>> logfile 2>&1 &`
  - Wait loop (10s max) checking PID file
  - On timeout: log error + return false; on success: `message::removeAll(__CLASS__, 'unableStartDeamon')`
- [x] **3.6** Implement `deamon_stop()` static method:
  - Kill by PID file (same pattern as aiodemo)
  - Kill by script name: `system::kill('siadc09d.py')`
  - Two `sleep(1)` calls as per reference pattern
- [x] **3.7** Implement `isConnect()` static method:
  - Returns `(self::deamon_info()['state'] ?? 'nok') == 'ok'`
  - Also checks launchable == 'ok' (config valid)
- [x] **3.8** Implement `sendToDaemon(array $params)` static method:
  - Reads socketport: `config::byKey('socketport', __CLASS__, 55009)`
  - Adds `$params['apikey'] = jeedom::getApiKey(__CLASS__)`
  - Socket send to `127.0.0.1:$socketport` (mirrors aiodemo pattern exactly)
  - Log at DEBUG level
- [x] **3.9** Implement `postSave()` instance method (AC3):
  - Create all 7 commands if they don't exist (`getCmd(type, logicalId)` guard)
  - Use the `new siaDC09Cmd()` constructor for each
  - Set `isVisible(0)` on all commands
  - **DO NOT restart daemon** — config changes take effect on next manual daemon start
  - See Task 5 for full command spec
- [x] **3.10** Implement `preRemove()` instance method:
  - Call `self::deamon_stop()`
  - No config cleanup needed (Jeedom deletes eqLogic config automatically)
- [x] **3.11** Implement `dependancy_info()` static method:
  - Check for `resources/siadc09d/.install_ok` sentinel file
  - Returns `['state' => 'ok', 'nb_try' => 0]` if file exists
  - Returns `['state' => 'nok', 'nb_try' => 0]` if missing
  - **Do NOT implement venv check** — F3/R3 deferred to implementation phase

---

### Task 4: Create `core/class/siaDC09Cmd.class.php` — cmd class (AC2)

- [x] **4.1** Create separate file (not in the same file as eqLogic — per Jeedom convention for this plugin)
  - GPL header + `require_once` for `core.inc.php`
- [x] **4.2** Implement `execute($_options = [])` method:
  ```php
  public function execute($_options = []) {
      $eqLogic = $this->getEqLogic();
      $cmd = $this->getLogicalId();
      switch ($cmd) {
          case 'burglarAlarm':
          case 'fireAlarm':
          case 'panicAlarm':
              // Zone comes from #zone# tag placed in the action command title by alarm plugin
              $zone = trim($_options['title'] ?? '');
              siaDC09::sendToDaemon([
                  'cmd'  => $cmd,
                  'zone' => $zone !== '' ? $zone : null,
              ]);
              break;
          // INFO commands are not user-initiated — no execute() handling needed
      }
  }
  ```
- [x] **4.3** Verify `title` is the correct `$_options` key for `#zone#` tag (per Jeedom `message` subtype: title field carries the message title which is where `#zone#` is placed)

---

### Task 5: Command definitions in `postSave()` (AC3)

Full command spec for the 7 commands created in `postSave()`:

- [x] **5.1** `burglarAlarm` — action/message, isVisible=0, name=`__('Alarme intrusion', __FILE__)`, logicalId=`burglarAlarm`
- [x] **5.2** `fireAlarm` — action/message, isVisible=0, name=`__('Alarme incendie', __FILE__)`, logicalId=`fireAlarm`
- [x] **5.3** `panicAlarm` — action/message, isVisible=0, name=`__('Alarme panique', __FILE__)`, logicalId=`panicAlarm`
- [x] **5.4** `supervision_state` — info/numeric, isVisible=0, name=`__('État supervision', __FILE__)`, logicalId=`supervision_state`, default value=1
- [x] **5.5** `supervision_label` — info/string, isVisible=0, name=`__('Supervision', __FILE__)`, logicalId=`supervision_label`, default value=`'DÉMARRAGE…'`
- [x] **5.6** `event_state` — info/numeric, isVisible=0, name=`__('État alarme', __FILE__)`, logicalId=`event_state`, default value=0
- [x] **5.7** `event_label` — info/string, isVisible=0, name=`__('Alarme', __FILE__)`, logicalId=`event_label`, default value=`'Inactif'`

**Pattern for each command in `postSave()`:**
```php
$cmd = $this->getCmd('action', 'burglarAlarm');
if (!is_object($cmd)) {
    $cmd = new siaDC09Cmd();
    $cmd->setLogicalId('burglarAlarm');
    $cmd->setEqLogic_id($this->getId());
    $cmd->setName(__('Alarme intrusion', __FILE__));
    $cmd->setType('action');
    $cmd->setSubType('message');
    $cmd->setIsVisible(0);
    $cmd->save();
}
```

---

### Task 6: Create `core/ajax/siaDC09.ajax.php` (AC6)

- [x] **6.1** Create file using aiodemo as template
- [x] **6.2** Replace `aiodemo` references with `siaDC09`
- [x] **6.3** Use `isConnect('admin')` guard (NOT bare `isConnect()`)
- [x] **6.4** Call `ajax::init()` after the auth check
- [x] **6.5** Add placeholder comment for future wizard AJAX actions (Steps 3+)
- [x] **6.6** Final `throw new Exception(...)` for unmatched actions (standard pattern)

---

### Task 7: Update `plugin_info/install.php` (AC1 support)

- [x] **7.1** Rename functions from `aiodemo_*` to `siaDC09_*`:
  - `siaDC09_install()`, `siaDC09_update()`, `siaDC09_remove()`
- [x] **7.2** Add `siaDC09_remove()` body: call `siaDC09::deamon_stop()` and delete `.install_ok` sentinel
- [x] **7.3** Keep `siaDC09_install()` and `siaDC09_update()` as empty stubs (dependency install handled by Jeedom's dependency manager)

---

### Task 8: Create `core/i18n/en_US.json` skeleton (AC7 — Market requirement)

- [x] **8.1** Create `core/i18n/en_US.json` with plugin file path as top-level key:
  ```json
  {
    "plugins\/siaDC09\/core\/class\/siaDC09.class.php": {
      "Impossible de lancer le démon": "Unable to start daemon",
      "Veuillez vérifier la configuration": "Please check configuration",
      "Alarme intrusion": "Burglary alarm",
      "Alarme incendie": "Fire alarm",
      "Alarme panique": "Panic alarm",
      "État supervision": "Supervision state",
      "Supervision": "Supervision",
      "État alarme": "Alarm state",
      "Alarme": "Alarm"
    }
  }
  ```

---

### Task 9: Create Python test stubs `tests/level1/test_php_eqlogic_stub.py` (AC9)

- [x] **9.1** Create test file with module docstring referencing Story 6.1
- [x] **9.2** Write `test_expected_command_logical_ids()`: assert that the 7 expected logicalIds match a hard-coded set (documents contract, catches accidental renames)
- [x] **9.3** Write `test_action_command_subtypes()`: assert action commands use `message` subtype
- [x] **9.4** Write `test_info_command_subtypes()`: assert supervision_state/event_state use `numeric`, labels use `string`
- [x] **9.5** Tests are pure Python (no Jeedom needed) — use simple `assert` with documented expected values

---

### Task 10: Run tests (AC9)

- [x] **10.1** Run `python3 -m pytest tests/level1/test_php_eqlogic_stub.py -v --tb=short` — all pass
- [x] **10.2** Run `python3 -m pytest tests/level1/ tests/level2/ -q --tb=short` — no new regressions (pre-existing: 8 failures unchanged)

---

## Dev Notes

### Critical: This is the First PHP File in the Plugin

All existing `.php` files are from the `aiodemo` template plugin (reference/starter). Story 6.1 creates the actual `siaDC09` plugin classes. The aiodemo files remain as **reference only** — do NOT delete them. The new siaDC09 files live alongside them:
- `core/class/siaDC09.class.php` (NEW — eqLogic)
- `core/class/siaDC09Cmd.class.php` (NEW — cmd, separate file)
- `core/ajax/siaDC09.ajax.php` (NEW — AJAX handler)
- `core/i18n/en_US.json` (NEW — Market i18n)
- `plugin_info/info.json` (MODIFIED — identity)
- `plugin_info/packages.json` (MODIFIED — add pycryptodome)
- `plugin_info/install.php` (MODIFIED — rename functions)

### PHP 8 Typing Requirements

Per code-style rules for PHP:
- All method parameters must have type declarations
- All return types must be declared
- Use `?->` for nullable access: `$eqLogic?->getConfiguration('csr_ip', '')`
- No global state — use dependency injection pattern
- Method names `camelCase`, constants `UPPER_SNAKE_CASE`, properties `$camelCase`

### Jeedom Patterns from aiodemo Reference

The `aiodemo.class.php` file is the authoritative reference for Jeedom integration patterns. Key patterns to reuse:

1. **`getPython3()` fallback** — `system::getCmdPython3(__CLASS__)` first, then `'python3 '` fallback
2. **PID file path** — `jeedom::getTmpFolder(__CLASS__) . '/daemon.pid'`
3. **Background exec** — `exec($cmd . ' >> ' . log::getPathToLog(...) . ' 2>&1 &')`
4. **10s startup wait** — `while ($i < 10)` with `sleep(1)` and PID check
5. **Socket send** — `socket_create(AF_INET, SOCK_STREAM, SOL_TCP)` + `socket_connect` + `socket_write`
6. **Command creation guard** — `getCmd(type, logicalId)` → `is_object()` check before `new Cmd()`

### deamon_start() Argument Spec

The daemon `siadc09d.py` expects these CLI arguments (from `jeedomdaemon.BaseDaemon` base + custom):
```
--loglevel DEBUG|INFO|WARNING|ERROR
--socketport <int>      # TCP port for PHP→daemon commands
--callback <url>        # PHP callback endpoint
--apikey <string>       # Jeedom API key
--pid <path>            # PID file path
--host <ip>             # CSR IP address
--port <int>            # CSR port
--transport udp|tcp     # Protocol
--account <hex>         # Account number (3-16 hex chars)
--crc-format hex|bin    # CRC encoding
--encryption-enabled    # Flag (no value, presence = enabled)
--encryption-key <hex>  # 32-char hex (only if encryption-enabled)
--supervision-interval <int>   # seconds
--retry-count <int>
```

> **Note:** The daemon entry point `siadc09d.py` does not exist yet — it will be wired in Story 6.6. `deamon_start()` should build the full command string as specified, but the daemon won't actually run until Story 6.6. That's fine — `deamon_info()` will return `state: nok` until the daemon is wired.

### config key naming — ALL use `sia_` prefix

```php
// Always pass a typed default matching the value type:
$ip   = $eqLogic->getConfiguration('csr_ip',   '');
$port = (int) $eqLogic->getConfiguration('csr_port', 0);
$enc  = (bool) $eqLogic->getConfiguration('encryption_enabled', false);
// Plugin-level (not equipment-level):
$socketport = (int) config::byKey('socketport', __CLASS__, 55009);
```

### sendToDaemon Zone Extraction

The alarm plugin sends the action command with `#zone#` in the **title** field. The `message` subtype in Jeedom action commands passes two `$_options` keys:
- `title`: the message title (this is where `#zone#` substitution happens)
- `message`: the message body (not used for zone)

Always use `$_options['title'] ?? ''` to extract zone. Trim whitespace. Send `null` if empty (not empty string), so the daemon correctly handles `zone: null` in the JSON.

### `postSave()` — Commands Only, No Daemon Restart

Per design decision (php-core-design.md § "Confirmed Design Decisions"):
> "Daemon restart on save: **None** — `postSave()` only manages commands. Config changes take effect on next daemon start."

This matches the z2m/zwavejs pattern. Do NOT call `deamon_stop()`/`deamon_start()` in `postSave()`.

### dependancy_info() Sentinel Pattern

```php
public static function dependancy_info(): array {
    $install_ok = dirname(__FILE__) . '/../../resources/siadc09d/.install_ok';
    if (file_exists($install_ok)) {
        return ['state' => 'ok', 'nb_try' => 0];
    }
    return ['state' => 'nok', 'nb_try' => 0];
}
```
The `.install_ok` file is created by `install_dep.sh` after a successful pip3 install. It will be implemented in Story 6.5. For now, the file won't exist so dependency state will always be 'nok' — that's expected.

### IPC Callback URL Pattern

From aiodemo reference:
```php
network::getNetworkAccess('internal', 'proto:127.0.0.1:port:comp') . '/plugins/siaDC09/core/php/jeesiaDC09.php'
```
Note: `jeesiaDC09.php` (the callback endpoint) is created in Story 6.3. In Story 6.1, just build the callback URL correctly in `deamon_start()` — it will 404 until Story 6.3 creates the file.

### Project Structure Notes

```
New files (Story 6.1):
  core/class/siaDC09.class.php        ← eqLogic class
  core/class/siaDC09Cmd.class.php     ← cmd class (separate file)
  core/ajax/siaDC09.ajax.php          ← AJAX handler
  core/i18n/en_US.json                ← Market i18n skeleton
  tests/level1/test_php_eqlogic_stub.py ← Python contract tests

Modified files (Story 6.1):
  plugin_info/info.json               ← Plugin identity update
  plugin_info/packages.json           ← Add pycryptodome
  plugin_info/install.php             ← Rename aiodemo_ → siaDC09_

Reference files (DO NOT MODIFY):
  core/class/aiodemo.class.php        ← Template reference
  core/ajax/aiodemo.ajax.php          ← Template reference
  core/php/jeeaiodemo.php             ← Template reference (model for Story 6.3)
```

### Pre-existing Test Failures (Not Regressions)

- **Level 2:** `test_tc13_strike_timing_precision` — pre-existing StopIteration from time.monotonic mock
- **Level 1:** 7 tests in `test_error_handler.py` — `_dispatch_notify` NotImplementedError (deferred to Epic 6 Stories 6.3+)

### Cross-Story Dependencies

- **Story 6.2** (Auto-equipment creation): depends on `postSave()` command creation from this story
- **Story 6.3** (IPC callback): creates `core/php/jeesiaDC09.php` — the callback endpoint referenced in `deamon_start()`
- **Story 6.5** (Dependencies): creates `resources/siadc09d/install_dep.sh` and `.install_ok` sentinel
- **Story 6.6** (Integration): creates `resources/siadc09d/siadc09d.py` entry point — daemon won't actually run until then

### SIA DC-09 Protocol References

This story is PHP-only — no protocol encoding/decoding. The daemon (Python) handles all SIA DC-09 framing. PHP only needs to:
1. Pass zone name as a string to the daemon via sendToDaemon()
2. Receive state updates from the daemon via callbacks (Stories 6.3+)

### References

- [Source: internal-docs/design/php-core-design.md § Plugin Identity, File Structure, INFO and ACTION Commands]
- [Source: internal-docs/design/php-core-design.md § Confirmed Design Decisions — deamon_start, postSave, dependancy_info]
- [Source: internal-docs/design/php-core-design.md § Configuration Keys — sia_ prefix table]
- [Source: core/class/aiodemo.class.php — reference implementation for all Jeedom patterns]
- [Source: plugin_info/info.json — current template to be updated]
- [Source: plugin_info/packages.json — current pip3 deps]
- [Source: _bmad-output/planning-artifacts/epics.md § Story 6.1 Acceptance Criteria]
- [Source: _bmad-output/planning-artifacts/architecture.md — PHP 8 type requirements]

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References
- Jeedom plugin skill referenced for PHP patterns (`jeedom-plugin`)
- aiodemo.class.php used as authoritative reference for all Jeedom integration patterns
- CLI arg spec: `--encryption-enabled` is a boolean flag (no value); `--encryption-key` is conditional
- `escapeshellarg()` used on all user-supplied config values in `deamon_start()` to prevent command injection
- `en_US.json`: added siaDC09 entries alongside existing aiodemo entries (reference files preserved)
- `postSave()` uses loop-based command creation to reduce duplication vs. 7 individual blocks

### Completion Notes List
- All 10 tasks, 48 subtasks completed
- All 9 Acceptance Criteria satisfied:
  - AC1: `siaDC09.class.php` with all 9 specified methods (deamon_info, deamon_start, deamon_stop, sendToDaemon, isConnect, postSave, preRemove, _getAutoEquipmentSafe, dependancy_info)
  - AC2: `siaDC09Cmd.class.php` with `execute()` handling burglarAlarm/fireAlarm/panicAlarm + zone extraction from `$_options['title']`
  - AC3: 7 commands created idempotently in postSave() — 3 action/message + 4 info (2 numeric + 2 string), all isVisible=0
  - AC4: All config keys use `sia_` prefix with typed defaults; socketport from plugin-level config
  - AC5: `deamon_start()` builds full CLI with mandatory + CSR + optional args, background exec, 10s PID wait
  - AC6: `siaDC09.ajax.php` with `isConnect('admin')` guard
  - AC7: `info.json` updated (id=siaDC09, name=Télésurveillance, require=4.5, category=security, os.min=12)
  - AC8: `packages.json` updated with pycryptodome
  - AC9: 5 Python contract tests in test_php_eqlogic_stub.py — 596 passed, 8 pre-existing failures unchanged
- No regressions introduced

### Code Review Fixes (2026-04-24)
- **H1:** `deamon_start()` now scrubs `--encryption-key` from log line via `preg_replace` → `[REDACTED]` (privacy rule compliance)
- **H2:** `sendToDaemon()` now handles socket failure gracefully — `@socket_create/@socket_connect` with error logging + early return instead of PHP warnings
- **H3:** `install.php::siaDC09_remove()` uses raw PID+kill pattern instead of `siaDC09::deamon_stop()` — avoids class autoload failure during plugin removal
- **M1:** `deamon_start()` removed redundant null check after `deamon_info()['launchable']=='ok'` guard (comment documents invariant)
- **M2:** Added `--receiver-prefix` and `--account-prefix` CLI args to `deamon_start()` (conditional, only if non-empty)
- **M3:** `postSave()` now sets default values for INFO commands via `checkAndUpdateCmd()` on creation: supervision_state=1, supervision_label='DÉMARRAGE…', event_state=0, event_label='Inactif'

### File List
- `core/class/siaDC09.class.php` (NEW — eqLogic class, ~190 lines)
- `core/class/siaDC09Cmd.class.php` (NEW — cmd class, ~35 lines)
- `core/ajax/siaDC09.ajax.php` (NEW — AJAX handler, ~35 lines)
- `core/i18n/en_US.json` (MODIFIED — added siaDC09 translation entries)
- `plugin_info/info.json` (MODIFIED — plugin identity: siaDC09, security, 4.5, os.min=12)
- `plugin_info/packages.json` (MODIFIED — added pycryptodome to pip3)
- `plugin_info/install.php` (MODIFIED — renamed aiodemo_* → siaDC09_*, added remove body)
- `tests/level1/test_php_eqlogic_stub.py` (NEW — 5 contract tests)
