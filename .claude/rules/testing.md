---
paths: "tests/**/*.py"
---
# Testing Rules

## Framework
- pytest only (`def test_*():`), no unittest.TestCase
- `pytest.fixture` for setup, simple `assert`, no `self.assert*`

## Test Documentation (mandatory 3 elements)
1. **Docstring**: scenario description + expected result as bullet points
2. **Assert comments**: one per assert, referencing expected result

## Organization
- Level 1: `tests/level1/` — sync, no external deps
- Level 2: `tests/level2/` — async, state machine
- Level 2.5: `tests/level2_5/` — IPC contract validation
- Level 3: `tests/level3/` — live Jeedom required

## Async Rules (Level 2+)
- Join tasks: `await asyncio.gather(*daemon._tasks)` — never `await asyncio.sleep(0)`
- Time-dependent: use `time_mock` fixture, no hardcoded sleeps
- Logs: `assert "msg" in caplog.text` — never mock the logger

## Protocol Testing
- Validate against SIA DC-09 spec (include § references in docstrings)
- Golden frames: `@pytest.mark.golden_frames`, store in `tests/fixtures/golden/*.bin`

## Execution
- `python3 -m pytest tests/level1/` for unit tests
- `pytest -m "not requires_jeedom"` to skip slow tests
- Target >95% coverage on core protocol modules (`pytest --cov`)
- Async fixtures must yield and clean up (no orphaned tasks/sockets)
