"""Step 1 sub-zones: the dashed frame means "fixed by the profile" (story 18.4 review, 2026-11-09)."""

import re
from pathlib import Path

_CSS = (Path(__file__).parent.parent.parent / "desktop/css/siaDC09.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """Body of the first CSS rule whose selector is exactly `selector`."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", _CSS)
    assert match, f"{selector} rule not found"
    return match.group(1)


def test_subzone_is_dashed_only_when_the_profile_locks_it() -> None:
    """
    An editable sub-zone must not look fixed.

    Expected result:
    - the base .siaDC09-subzone rule has no dashed border
    - the -locked variant carries the dashed border and the grey fill
    """
    base = _rule("#siaDC09-wizard .siaDC09-subzone")
    locked = _rule("#siaDC09-wizard .siaDC09-subzone-locked")
    # Assert: editable means no dashed border
    assert "dashed" not in base
    # Assert: locked means dashed and grey
    assert "dashed" in locked and "background" in locked
