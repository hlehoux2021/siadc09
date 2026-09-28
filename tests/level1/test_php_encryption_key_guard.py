"""PHP encryption-key validation: guard 5 and the decode ajax (story 1-5 AC5).

isValidEncryptionKey() is extracted from core/class/siaDC09.class.php and run
with the php CLI against the same cases as parse_hex_key(), so PHP and the
daemon cannot drift apart. The guard and the ajax path are checked in source.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from resources.siadc09d.sia_crypto import AESKeyError, parse_hex_key
from tests.level1.test_php_eqlogic_stub import _extract_method_body

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_PHP_CLASS_FILE = _PROJECT_ROOT / "core/class/siaDC09.class.php"
_PHP_AJAX_FILE = _PROJECT_ROOT / "core/ajax/siaDC09.ajax.php"
_PHP_TIMEOUT_S = 10

_KEY_CASES: list[str] = [
    "0123456789ABCDEF0123456789ABCDEF",            # 32 hex → AES-128
    "0123456789abcdef0123456789abcdef01234567",    # 40 hex → rejected
    "0123456789ABCDEF" * 3,                        # 48 hex → AES-192
    "0123456789ABCDEF" * 4,                        # 64 hex → AES-256
    "  0123456789ABCDEF0123456789ABCDEF  ",        # surrounding spaces trimmed
    "0123456789ABCDEF 0123456789ABCDEF",           # internal space rejected
    "0x0123456789ABCDEF0123456789ABCDEF",          # 0x prefix rejected
    "0123456789ABCDEF0123456789ABCDEZ",            # non-hex digit
    "my-secret-passphrase-1234567890ab",           # ASCII phrase (D-93)
    "0123456789ABCDEF0123456789ABCDE",             # 31 hex
    "",                                            # missing
]


def _python_accepts(key: str) -> bool:
    """True when the daemon's parse_hex_key() accepts the key."""
    try:
        parse_hex_key(key)
    except AESKeyError:
        return False
    return True


def _php_accepts(keys: list[str]) -> list[bool]:
    """Run the extracted isValidEncryptionKey() over keys with the php CLI."""
    source = _PHP_CLASS_FILE.read_text(encoding="utf-8")
    body = _extract_method_body(source, "isValidEncryptionKey")
    lengths = re.search(r"const ENCRYPTION_KEY_HEX_LENGTHS\s*=\s*(\[[^\]]*\]);", source)
    assert body and lengths, "isValidEncryptionKey or ENCRYPTION_KEY_HEX_LENGTHS missing"
    script = (
        "class siaDC09 { const ENCRYPTION_KEY_HEX_LENGTHS = " + lengths.group(1) + ";"
        " public static function isValidEncryptionKey(?string $key): bool {" + body + "} }"
        " $keys = json_decode(stream_get_contents(STDIN), true);"
        " echo json_encode(array_map(fn($k) => siaDC09::isValidEncryptionKey($k), $keys));"
    )
    out = subprocess.run(
        ["php", "-r", script], input=json.dumps(keys), capture_output=True, text=True,
        check=True, timeout=_PHP_TIMEOUT_S,
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("php") is None, reason="php CLI not installed")
def test_php_key_rule_matches_parse_hex_key() -> None:
    """
    PHP and the daemon accept exactly the same keys.

    Expected result:
    - for every case, isValidEncryptionKey() == parse_hex_key() succeeds
    - 32/48/64 hex digits (trimmed) accepted; 40, 31, spaces, 0x, non-hex, phrase, empty rejected
    """
    php = _php_accepts(_KEY_CASES)

    # Assert: PHP verdict equals the daemon verdict for every case
    assert php == [_python_accepts(k) for k in _KEY_CASES]
    # Assert: the three AES sizes are accepted (sanity on the case list itself)
    assert php[0] and php[2] and php[3]


def test_guard5_uses_key_rule_without_echoing_key() -> None:
    """
    deamon_info guard 5 validates the format and never interpolates the key.

    Expected result:
    - guard 5 calls self::isValidEncryptionKey()
    - no launchable_message concatenates $encKey
    """
    body = _extract_method_body(_PHP_CLASS_FILE.read_text(encoding="utf-8"), "deamon_info")
    messages = re.findall(r"launchable_message'\]\s*=\s*([^;]*);", body)

    # Assert: format check present
    assert "self::isValidEncryptionKey(" in body
    # Assert: key never part of a launch message
    assert messages and all("$encKey" not in m for m in messages)


def test_decode_ajax_has_no_ascii_key_fallback() -> None:
    """
    The decode ajax passes only a valid hex key, never bin2hex of a phrase.

    Expected result:
    - no bin2hex in the ajax file
    - SIA_ENCRYPTION_KEY set behind siaDC09::isValidEncryptionKey()
    """
    source = _PHP_AJAX_FILE.read_text(encoding="utf-8")

    # Assert: ASCII fallback removed
    assert "bin2hex" not in source
    # Assert: key gated by the shared rule
    assert re.search(r"siaDC09::isValidEncryptionKey\(\$encKey\)\)\s*\{\s*\n[^\n]*SIA_ENCRYPTION_KEY", source)
