# SIA DC-09 Jeedom Plugin

SIA DC-09-2021.17 protocol implementation (Internet Protocol Event Reporting).

## Commands
- Test (Python): `python3 -m pytest tests/level1/`
- Lint (Python): `python3 -m pylint resources/siadc09d/`
- Syntax check (PHP): `php -l core/class/siaDC09.class.php`
- Syntax check all PHP: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`

## Architecture
- Daemon: `resources/siadc09d/` (Python async)
- Plugin: `core/` + `desktop/` (PHP/JS, Jeedom framework)

## Key References (read on demand, not pre-loaded)
- Protocol spec: `internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`
- Architecture decisions: `_bmad-output/planning-artifacts/architecture.md`
- PRD (product goals): `_bmad-output/planning-artifacts/prd.md`
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Epics: `_bmad-output/planning-artifacts/epics.md`

## Domain Skills (invoke for expert questions)
- `/sia-dc09-expert` — protocol format, CRC, encryption, timestamps, ACK/NAK
- `/jeedom-plugin` — plugin structure, eqLogic/cmd, daemon framework, Market
- `/jeedom-alarm` — alarm plugin zones, modes, triggers, scenario integration
- `/jeedom-camera` — camera URLs, RTSP, snapshots, Synology integration

## Design Docs (load the relevant one for the task)
| Component | File |
|-----------|------|
| Daemon core + protocol | `internal-docs/design/daemon-design.md` |
| PHP plugin core | `internal-docs/design/php-core-design.md` |
| Supervision & health | `internal-docs/design/supervision-design.md` |
| Error handler | `internal-docs/design/error-handler-design.md` |
| Logging | `internal-docs/design/logging-design.md` |
| Config wizard | `internal-docs/design/wizard-design.md` |
| Widget | `internal-docs/design/widget-design.md` |
| Debug UI | `internal-docs/design/debug-ui-design.md` |
