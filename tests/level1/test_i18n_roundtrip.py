"""
i18n roundtrip tests for Story 11.4 (AC4, AC5).

Every French source string the siaDC09 PHP/JS code hands to Jeedom's translate
engine must have a key in core/i18n/fr_FR.json, under the same per-file section
Jeedom looks it up in (translate::exec, core/class/translate.class.php):

- ``__('text', __FILE__)`` in PHP -> key is the *runtime* string (PHP escapes
  resolved), section is ``plugins/siaDC09/<relative path>``.
- ``{{text}}`` in a PHP template or JS file -> translate::exec runs on the raw
  file content, so the key is the *raw* text between the braces.

fr_FR is an identity mapping (French is the source language). Jeedom falls back
to the source text when a key is missing or empty, so a missing key is never a
runtime error — this test exists so fr_FR.json can't silently drift behind the
code, and so the other language files have a complete key list to translate.

Reference: _bmad-output/implementation-artifacts/11-4-documentation-i18n-market-submission.md
"""
import json
import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
FR_FILE = _PROJECT_ROOT / "core/i18n/fr_FR.json"
PLUGIN_ID = "siaDC09"

# Every siaDC09-owned file that carries translatable strings.
SOURCE_FILES = [
    "core/class/siaDC09.class.php",
    "core/class/siaDC09Cmd.class.php",
    "core/ajax/siaDC09.ajax.php",
    "core/php/jeesiaDC09.php",
    "plugin_info/install.php",
    "plugin_info/configuration.php",
    "desktop/php/siaDC09.php",
    "desktop/js/siaDC09.js",
]

_BRACES_RE = re.compile(r"{{(.*?)}}", re.S)
_SINGLE_RE = re.compile(r"__\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*__FILE__")
_DOUBLE_RE = re.compile(r'__\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*__FILE__')


def _unescape_single(s: str) -> str:
    return re.sub(r"\\([\\'])", r"\1", s)


def _unescape_double(s: str) -> str:
    return re.sub(r'\\([\\"$])', r"\1", s)


def extract_strings(rel_path: str) -> set:
    """Return the set of translate keys Jeedom will look up for this file."""
    content = (_PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
    keys = set()
    if rel_path.endswith(".php"):
        keys |= {_unescape_single(m) for m in _SINGLE_RE.findall(content)}
        keys |= {_unescape_double(m) for m in _DOUBLE_RE.findall(content)}
    keys |= {m for m in _BRACES_RE.findall(content) if m.strip()}
    return keys


def section_name(rel_path: str) -> str:
    return f"plugins/{PLUGIN_ID}/{rel_path}"


@pytest.fixture(scope="module")
def fr() -> dict:
    return json.loads(FR_FILE.read_text(encoding="utf-8"))


def test_fr_fr_json_exists() -> None:
    """
    info.json declares fr_FR as a supported language; its i18n file must exist.

    Expected result:
    - core/i18n/fr_FR.json is a file
    """
    # Assert: file present
    assert FR_FILE.is_file(), "core/i18n/fr_FR.json is missing"


def test_fr_fr_json_is_object_of_objects(fr: dict) -> None:
    """
    Jeedom expects {section: {source: translation}} with string values.

    Expected result:
    - top level is a non-empty object
    - every section is an object of str -> str
    """
    # Assert: non-empty top-level object
    assert isinstance(fr, dict) and fr
    for section, entries in fr.items():
        # Assert: section is an object
        assert isinstance(entries, dict), section
        for key, value in entries.items():
            # Assert: string key and value
            assert isinstance(key, str) and isinstance(value, str), (section, key)


def test_extractor_finds_strings_in_every_translated_file() -> None:
    """
    Guard against a broken regex making the roundtrip test pass vacuously.

    Expected result:
    - the class, the desktop page and the desktop JS each yield at least one key
    """
    for rel in ["core/class/siaDC09.class.php", "desktop/php/siaDC09.php", "desktop/js/siaDC09.js"]:
        # Assert: extractor found strings
        assert extract_strings(rel), f"no translatable strings extracted from {rel}"


def test_extractor_resolves_php_single_quote_escape() -> None:
    """
    __('Vous n\\'êtes…') is looked up by its runtime value, not its source escape.

    Expected result:
    - the extracted key contains a bare apostrophe
    """
    keys = extract_strings("core/php/jeesiaDC09.php")
    # Assert: PHP escape resolved
    assert "Vous n'êtes pas autorisé à effectuer cette action" in keys


@pytest.mark.parametrize("rel_path", SOURCE_FILES)
def test_every_source_string_has_fr_fr_key(fr: dict, rel_path: str) -> None:
    """
    Every translatable source string has a key in its file's fr_FR section.

    Expected result:
    - files with strings have a section named plugins/siaDC09/<path>
    - no extracted string is missing from that section
    """
    expected = extract_strings(rel_path)
    if not expected:
        return
    section = fr.get(section_name(rel_path))
    # Assert: section present
    assert section is not None, f"fr_FR.json has no section for {section_name(rel_path)}"
    missing = sorted(expected - set(section))
    # Assert: no missing key
    assert not missing, f"{rel_path}: {len(missing)} string(s) missing from fr_FR.json: {missing[:10]}"


def test_fr_fr_is_identity_mapping(fr: dict) -> None:
    """
    French is the source language.

    Expected result:
    - each fr_FR value equals its key
    """
    for section, entries in fr.items():
        for key, value in entries.items():
            # Assert: identity mapping
            assert value == key, f"{section}: {key!r} -> {value!r}"


def test_fr_fr_has_only_siadc09_sections(fr: dict) -> None:
    """
    No stale aiodemo template sections, no sections for files that no longer exist.

    Expected result:
    - every section starts with plugins/siaDC09/ and names an existing file
    """
    for section in fr:
        # Assert: plugin-scoped section
        assert section.startswith(f"plugins/{PLUGIN_ID}/"), section
        rel = section[len(f"plugins/{PLUGIN_ID}/"):]
        # Assert: file still exists
        assert (_PROJECT_ROOT / rel).is_file(), f"fr_FR.json section for missing file {rel}"


def test_fr_fr_has_no_orphan_keys(fr: dict) -> None:
    """
    Keys no longer present in the source are dead weight for translators.

    Expected result:
    - every fr_FR key is still extracted from its source file
    """
    for section, entries in fr.items():
        rel = section[len(f"plugins/{PLUGIN_ID}/"):]
        orphans = sorted(set(entries) - extract_strings(rel))
        # Assert: no orphan
        assert not orphans, f"{rel}: orphan keys {orphans[:10]}"
