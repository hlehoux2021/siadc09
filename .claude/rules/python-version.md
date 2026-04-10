# Python Version Convention

## Rule

Always use `python3` instead of bare `python` for all commands and scripts.

## Why

- **Platform consistency**: Jeedom requires Python 3.10+ (Debian 12+ ships Python 3.11)
- **Explicit versioning**: `python3` guarantees the correct interpreter, avoiding unexpected behavior if `python` (v2) exists on the system
- **Project standard**: All code in this project targets Python 3.10+ (enforced via `info.json`)

## Application

- **CLI commands**: `python3 script.py` (not `python script.py`)
- **Shebang lines**: `#!/usr/bin/env python3`
- **Poetry/venv**: Poetry automatically uses `python3`; explicitly invoke `python3 -m pip` if needed
- **Tests**: `python3 -m pytest tests/`
- **Bash tools**: When a tool requires Python, invoke as `python3 -m toolname`

## Examples

✅ **Correct:**
```bash
python3 -m pytest tests/level1/
python3 resources/siadc09d/sia_protocol.py
```

❌ **Avoid:**
```bash
python -m pytest tests/level1/
python resources/siadc09d/sia_protocol.py
```

---

## Implementation Notes

- This rule applies to all Claude Code interactions in this project
- When Claude suggests a command, it should use `python3` by default
- No env variable aliases needed—explicit is better than implicit
