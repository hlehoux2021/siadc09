"""
CSR behaviour profile file tests (Story 17.1, ADR-22).

core/config/csr_presets.json holds one entry per CSR profile. It is read PHP-side
only (siaDC09::getCsrProfiles()); the daemon receives resolved values and never
reads the file nor sees a profile name.

Reference: _bmad-output/planning-artifacts/epics.md § Epic 17 (profile table)
Reference: _bmad-output/planning-artifacts/architecture.md § ADR-22
"""

import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PROFILES_FILE = _PROJECT_ROOT / "core/config/csr_presets.json"
_DAEMON_DIR = _PROJECT_ROOT / "resources/siadc09d"

_ALLOWED_PROFILE_KEYS = {
    "label", "supervision_format", "supervision_interval", "rp_enabled", "rp_interval",
}

# Epic 17 table: Ajax and Scutum are both on-demand, no supervision frame, RP every 60 s.
_EXPECTED_PROFILES = {
    "ajax": {"label": "Ajax", "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60},
    "scutum": {"label": "Scutum", "supervision_format": "none", "rp_enabled": 1, "rp_interval": 60},
}


@pytest.fixture(scope="module")
def profiles_doc() -> dict:
    assert _PROFILES_FILE.exists(), f"Profile file not found: {_PROFILES_FILE}"
    return json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))


def test_profiles_file_schema_version(profiles_doc: dict) -> None:
    """
    The profile file parses and declares schema_version 1 (AC1).

    Expected result:
    - schema_version == 1 (the only version getCsrProfiles() accepts)
    - a `profiles` object is present
    """
    # Assert: schema version supported by siaDC09::getCsrProfiles()
    assert profiles_doc["schema_version"] == 1
    # Assert: profiles object present
    assert isinstance(profiles_doc["profiles"], dict)


@pytest.mark.parametrize("name", sorted(_EXPECTED_PROFILES))
def test_profile_matches_epic_table(profiles_doc: dict, name: str) -> None:
    """
    Ajax and Scutum carry the Epic 17 table values (AC1).

    Expected result:
    - the profile exists with exactly the expected keys and values
      (supervision_interval omitted: irrelevant with supervision_format "none")
    """
    # Assert: profile values as per the Epic 17 table
    assert profiles_doc["profiles"][name] == _EXPECTED_PROFILES[name]


def test_profile_keys_are_known_config_keys(profiles_doc: dict) -> None:
    """
    Every profile key is a label or an equipment config key 17.1 plumbs (AC1).
    "Personnalisé" is not an entry: it means "no profile".

    Expected result:
    - no key outside {label, supervision_format, supervision_interval, rp_enabled, rp_interval}
    - no "custom"/"personnalise" entry
    """
    for name, profile in profiles_doc["profiles"].items():
        unknown = set(profile) - _ALLOWED_PROFILE_KEYS
        # Assert: only known keys
        assert not unknown, f"profile {name!r} has unknown keys {sorted(unknown)}"
        # Assert: French label present
        assert profile.get("label"), f"profile {name!r} has no label"
    # Assert: "Personnalisé" is not a profile entry
    assert not {"custom", "personnalise", "personnalisé"} & set(profiles_doc["profiles"])


def test_no_profile_without_periodic_frame(profiles_doc: dict) -> None:
    """
    No profile is the invalid combination supervision "none" + RP off (AC7),
    which deamon_info() Guard 3e would refuse.

    Expected result:
    - every profile with supervision_format "none" has rp_enabled truthy
    """
    for name, profile in profiles_doc["profiles"].items():
        if profile.get("supervision_format") == "none":
            # Assert: RP carries the periodic frame
            assert profile.get("rp_enabled"), f"profile {name!r}: none + RP off"


def test_daemon_never_reads_profile_file() -> None:
    """
    The daemon never reads the profile file (AC2, ADR-22).

    Expected result:
    - no file under resources/siadc09d/ mentions csr_presets
    """
    offenders = [
        str(p.relative_to(_PROJECT_ROOT))
        for p in _DAEMON_DIR.rglob("*")
        if p.is_file() and p.suffix in {".py", ".json", ".txt", ".sh"}
        and "csr_presets" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    # Assert: profile resolution stays PHP-side
    assert not offenders, f"daemon files reference csr_presets: {offenders}"
