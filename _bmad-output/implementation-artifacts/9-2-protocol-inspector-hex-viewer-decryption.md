# Story 9.2: Protocol Inspector — Hex Viewer & Decryption

Status: done

## Story

As a Jeedom user diagnosing SIA DC-09 communication issues,
I want to see decoded SIA protocol frames in the Diagnostic tab's protocol inspector panel,
So that I can verify the exact data being sent/received without needing terminal access.

## Acceptance Criteria

1. **Given** Diagnostic tab opened with messages data, **When** inspector panel renders, **Then** each SIA dialog is shown as a collapsed row with: direction icon (→ sent / ← received), id_token, sequence number, account, context label, status badge, and time.

2. **Given** a collapsed row, **When** user clicks it, **Then** it expands inline to show a field-by-field table (Champ / Valeur columns) with all decoded frame fields.

3. **Given** an expanded row for an encrypted frame, **When** decryption succeeds, **Then** the expanded view shows `Chiffrement AES-128-CBC (déchiffré)` indicator and the decrypted data fields.

4. **Given** an expanded row, **When** user clicks "Copier hex", **Then** the raw hex string is copied to clipboard via `navigator.clipboard.writeText()`.

5. **Given** a dialog with multiple retry attempts, **When** expanded, **Then** each attempt is labeled "Tentative X/Y" in its own sub-block.

6. **Given** an expanded row, **When** CRC validation runs during decode, **Then** display CRC status: ✓ (green) if valid, ✗ (red) if invalid, with received vs computed values shown.

7. **Given** Diagnostic tab, **When** user clicks "Actualiser" on inspector panel, **Then** `getDiagnosticData` is called and messages list re-rendered. (Already wired from 9-1.)

8. **Given** Diagnostic tab, **When** user clicks "Vider" on inspector panel, **Then** `clearDiagnosticData` with `target=messages` clears the list. (Already wired from 9-1.)

9. **Given** a message row with `raw_hex` field, **When** user clicks expand, **Then** `decodeFrame` AJAX is called to decode the hex and render field table from the response.

10. **Given** `decodeFrame` called with hex > 4096 chars or subprocess timeout > 5s, **Then** an error message is shown inline ("Trame trop longue" or "Délai dépassé").

## Tasks / Subtasks

- [x] Task 1 — Add `decode()` function and `ParsedMessage` dataclass to `sia_protocol.py` (AC: 2, 3, 6)
  - [x] 1.1 Define `ParsedMessage` dataclass (`frozen=True`, immutable value object per python-style rules) with fields: raw_hex, crc_received, crc_computed, crc_valid, crc_format, length_declared, length_actual, id_token, encrypted, sequence, receiver_prefix, account_prefix, account, data_raw, data_decrypted, extended_fields, timestamp_str. ALL fields must be JSON-serializable natively (str, int, bool, None, list, dict) — no Enum, datetime, or custom objects.
  - [x] 1.2 Implement `decode(raw_hex: str, key: bytes | None = None) -> ParsedMessage` — accepts hex string, converts internally via `bytes.fromhex(raw_hex)`, then parses. Raises `SIAProtocolError` on malformed input.
  - [x] 1.3 Reuse `_extract_frame_components()` for frame structure detection (hex vs binary CRC)
  - [x] 1.4 Reuse `_validate_crc()` / `_compute_crc_modbus()` for CRC validation
  - [x] 1.5 Parse message string: extract id_token, sequence, receiver_prefix, account_prefix, account, data block, extended fields, timestamp
  - [x] 1.6 If key provided and frame is encrypted (`#` id_token prefix): decrypt via `SIACipher(key).decrypt()`, populate `data_decrypted`
  - [x] 1.7 Add `--decode <hex>` CLI mode to `sia_protocol.py` `if __name__ == '__main__'` block — reads `SIA_ENCRYPTION_KEY` env var (same name as testConnection for consistency), outputs JSON to stdout

- [x] Task 2 — Enrich daemon `message_trace` callbacks with raw hex (AC: 1, 9)
  - [x] 2.0 **PREREQUISITE — Modify `SIATransportResult` in `sia_transport.py`**: Add `raw_response: bytes | None` field. Currently only `raw_nak` exists (None for ACK). The transport's `_parse_response()` must store the full raw response bytes BEFORE parsing, so both ACK and NAK raw frames are available to the daemon. Update `_parse_response()` to set `raw_response=raw` for all cases (ack, nak, timeout→None).
  - [x] 2.1 In `_log_sm1_supervision()` "ack" branch: add `request_hex` (from `self._last_sent_frame.hex()`) and `response_hex` (from `result['raw_response'].hex()`) to dialog dict
  - [x] 2.2 In `_log_sm1_supervision()` "timeout" branch: add `request_hex` (from `self._last_sent_frame.hex()`) — no response_hex (timed out)
  - [x] 2.3 In `_log_sm1_supervision()` "nak_timestamp"/"nak_bad" branches: rename `raw_hex` to `response_hex` for consistency, add `request_hex` (from `self._last_sent_frame.hex()`)
  - [x] 2.4 In `_log_sm2_event()`: add `request_hex` (alarm frame hex) and `response_hex` (ACK/NAK hex from `result['raw_response']` if received) to dialog dict
  - [x] 2.5 Store the last sent frame bytes as `self._last_sent_frame: bytes` in `_send_raw()` before calling transport, so callbacks can read it as hex

- [x] Task 3 — Add `decodeFrame` AJAX action in `siaDC09.ajax.php` (AC: 9, 10)
  - [x] 3.1 Add `decodeFrame` action block before the final `throw`
  - [x] 3.2 Read `hex` parameter (required, string), validate length ≤ 4096 chars
  - [x] 3.3 Read encryption key from eqLogic config: `$eqLogic->getConfiguration('encryption_key', '')` (no `sia_` prefix — eqLogic config is already scoped to the equipment instance)
  - [x] 3.4 Build subprocess command: `python3 resources/siadc09d/sia_protocol.py --decode <hex>`
  - [x] 3.5 Pass key via env var: `SIA_ENCRYPTION_KEY=<key>` prefix (same env var name as `testConnection` for consistency; only if key non-empty)
  - [x] 3.6 Execute with `exec()`, capture output, 10s `set_time_limit()` guard
  - [x] 3.7 Parse JSON output, return decoded fields via `ajax::success()`
  - [x] 3.8 On error (timeout, invalid hex, subprocess failure): `ajax::error()` with French message

- [x] Task 4 — Implement JS: collapsed row rendering for messages (AC: 1)
  - [x] 4.1 Add `siaDC09_renderMessages(messages)` function — builds collapsed rows or empty state
  - [x] 4.2 Each row: direction icon (→), context label (dialog_type + routine flag), status badge (elapsed_ms), time (HH:MM:SS)
  - [x] 4.3 Row structure: clickable `<div class="sia-msg-row">` with `data-request-hex` and `data-response-hex` attributes
  - [x] 4.4 Status badges: green `label-success` for ACK/routine, orange `label-warning` for NAK/timeout, red `label-danger` for multi-retry alarms

- [x] Task 5 — Implement JS: expand/collapse and field table (AC: 2, 3, 5, 6, 9)
  - [x] 5.1 Click handler on `.sia-msg-row` toggles `.sia-msg-detail` div below it
  - [x] 5.2 On first expand: call `decodeFrame` AJAX with the row's `data-request-hex`
  - [x] 5.3 Render field table from decoded JSON: `<table class="table table-condensed table-bordered">` with Champ/Valeur columns
  - [x] 5.4 Fields to display: id_token, sequence, receiver_prefix, account_prefix, account, data_raw, data_decrypted (if encrypted), crc_received, crc_computed, crc_valid (✓/✗), timestamp, extended_fields, length, crc_format
  - [x] 5.5 If encrypted and decrypted: show `<span class="label label-info">Chiffrement AES-128-CBC (déchiffré)</span>`
  - [x] 5.6 CRC display: `<span style="color:#5cb85c">✓ CRC valide</span>` or `<span style="color:#d9534f">✗ CRC invalide</span>` with received/computed values
  - [x] 5.7 Multiple attempts: wrap each in a sub-block `<div class="sia-attempt">` labeled "Tentative X/Y"
  - [x] 5.8 Cache decoded result in `_siaDC09_decodeCache` variable to avoid re-calling AJAX on re-expand

- [x] Task 6 — Implement JS: clipboard copy button (AC: 4)
  - [x] 6.1 Add "Copier hex (envoyé)"/"Copier hex (reçu)" buttons in expanded view
  - [x] 6.2 On click: `navigator.clipboard.writeText(hexString)` with "Copié !" feedback for 1500ms
  - [x] 6.3 Fallback for older browsers: `document.execCommand('copy')` with hidden textarea

- [x] Task 7 — Wire `siaDC09_renderMessages()` into existing `siaDC09_loadDiagnosticData()` (AC: 7)
  - [x] 7.1 In `siaDC09_loadDiagnosticData()` success handler, call `siaDC09_renderMessages(result.messages || [])` after badge and errors
  - [x] 7.2 Confirm Actualiser/Vider buttons still work correctly (already wired from 9-1)

- [x] Task 8 — Write Level 1 tests (AC: all)
  - [x] 8.1 Test: `decode()` function returns correct ParsedMessage for known good frame hex
  - [x] 8.2 Test: `decode()` handles encrypted frame with valid key
  - [x] 8.3 Test: `decode()` returns crc_valid=False for corrupted CRC
  - [x] 8.4 Test: `decode()` handles malformed input gracefully (returns error, no crash)
  - [x] 8.5 Test: CLI `--decode` mode outputs valid JSON to stdout
  - [x] 8.6 Test: PHP syntax check passes for modified files
  - [x] 8.7 Test: `decodeFrame` AJAX action structure (verify hex param, length guard)
  - [x] 8.8 Test: JS message row rendering has correct CSS classes and data attributes
  - [x] 8.9 Test: JS field table contains expected French labels (Champ/Valeur)
  - [x] 8.10 Test: JS clipboard copy button exists in expanded view template

- [x] Task 9 — Run full regression suite and PHP syntax checks

## Dev Notes

### Architecture Constraints

- **Single AJAX call for list:** `getDiagnosticData` already returns `messages` array (story 9-1). No new list endpoint needed — just render the data. [Source: docs/design/debug-ui-design.md#Task-5c.4]
- **Separate AJAX for decode:** `decodeFrame` is a NEW endpoint called per-row on expand. It invokes a Python subprocess to decode a single hex frame. [Source: docs/design/debug-ui-design.md#Task-5c.3]
- **Subprocess security:** Key passed via `SIA_ENCRYPTION_KEY` env var (same as testConnection), never in argv. Hex input sanitized (`ctype_xdigit()`). `set_time_limit(10)` + `exec()` (standard Jeedom pattern). 4096 char max. [Source: docs/design/debug-ui-design.md § subprocess constraints]
- **No auto-refresh:** All panels are manual-only. No polling. [Source: docs/design/debug-ui-design.md#Task-5c.4]
- **Bootstrap 3:** Jeedom 4.x. Use `panel`, `table-condensed`, `label-*` classes. [Source: story 9-1 dev notes]
- **Inspector panel already exists:** Story 9-1 created the panel shell with Actualiser/Vider buttons already wired. This story fills in the content rendering. [Source: story 9-1 file list]

### Existing Code to Extend (DO NOT reinvent)

**`resources/siadc09d/sia_protocol.py`** (765 lines):
- `_extract_frame_components()` (line 444): Extracts CRC, length, message from raw bytes. Detects hex vs binary CRC format. Returns `(crc_bytes, message_str, length_bytes, trailing_byte)` or None.
- `_validate_crc()` (line 541): Validates CRC given crc_bytes, message_str, crc_format. Returns bool.
- `_compute_crc_modbus()` (line 576): Computes CRC-16 MODBUS over data bytes.
- `decode_ack_nak()` (line 660): Parses ACK/NAK response — reference for message string parsing pattern.
- Imports at top include: `struct`, `dataclass`, `datetime`, `SIACipher` from sia_crypto.

**`resources/siadc09d/sia_crypto.py`** (359 lines):
- `SIACipher(key: bytes)` class — constructor takes 16-byte key
- `decrypt(ciphertext: bytes) -> bytes` — AES-128-CBC, fixed zero IV, PKCS#7 unpadding
- Raises `AESDecryptionError` on failure (bad key, bad padding)

**`resources/siadc09d/sia_transport.py`** (Task 2.0 prerequisite):
- `SIATransportResult` (line 42): TypedDict with `status` + `raw_nak`. Must add `raw_response: bytes | None` field.
- `_parse_response()` (line 101): Parses raw CSR bytes into result. Must store raw bytes in new field BEFORE parsing.
- `send_frame()` implementations (UDP line ~84, TCP line ~229): Both call `_parse_response()` — no change needed there.

**`resources/siadc09d/daemon.py`** (1680+ lines):
- `_send_raw()` (line 381): Calls `self._sia_transport.send_frame(frame)`. Add `self._last_sent_frame = frame` before transport call.
- `_log_sm1_supervision()` (line 1109): Emits `message_trace` callbacks for supervision events. Currently does NOT include `request_hex` or `response_hex` (except NAK which has `raw_hex`).
- `_log_sm2_event()` (line 1560): Emits `message_trace` for alarm events. Currently does NOT include any hex fields.
- `SM1AckLogCtx` (line 82): Already has `raw_hex: str | None` — currently set to `None` for ACK. After Task 2.0 it can be populated.

**`core/ajax/siaDC09.ajax.php`** (175 lines):
- Existing actions: `testConnection` (line ~29), `getZones`, `getCameraCommands`, `getDiagnosticData` (line ~120), `clearDiagnosticData` (line ~158).
- Pattern for subprocess: see `testConnection` — uses `exec()` with env var prefix.
- Add `decodeFrame` BEFORE the final `throw new Exception(...)` at line 171.

**`desktop/js/siaDC09.js`** (859 lines):
- `siaDC09_loadDiagnosticData()` (line ~760): Calls `getDiagnosticData` AJAX, currently renders badge + errors but NOT messages.
- Inspector Actualiser button (line 807): Already calls `siaDC09_loadDiagnosticData()`.
- Inspector Vider button (line 838): Already calls `clearDiagnosticData` with `target=messages`.
- Add new rendering functions AFTER the existing Vider handler (end of file).

**`desktop/php/siaDC09.php`** (414 lines):
- Inspector panel HTML already exists (lines 397-406). No HTML changes needed — rendering is purely JS-driven.

### Data Structures

**`sia_last_messages`** JSON array (max 50, newest first) — current format from daemon callbacks:
```json
[{
  "dialog_type": "supervision",
  "routine": 1,
  "timestamp": "2026-05-18T14:30:00+00:00",
  "elapsed_ms": 245
}]
```

**After Task 2 enrichment** — format with hex fields added:
```json
[{
  "dialog_type": "supervision",
  "routine": 1,
  "timestamp": "2026-05-18T14:30:00+00:00",
  "elapsed_ms": 245,
  "request_hex": "0A43210054...",
  "response_hex": "0A12340024..."
}]
```

NAK dialogs (already have `raw_hex`, will be renamed to `response_hex`):
```json
[{
  "dialog_type": "supervision",
  "routine": 0,
  "timestamp": "2026-05-18T14:32:11+00:00",
  "elapsed_ms": 1023,
  "request_hex": "0A43210054...",
  "response_hex": "0A56780024..."
}]
```

Alarm dialogs (after enrichment — single attempt, confirmed):
```json
[{
  "dialog_type": "alarm",
  "routine": 0,
  "timestamp": "2026-05-18T14:35:22+00:00",
  "elapsed_ms": 890,
  "request_hex": "0A43210078...",
  "response_hex": "0A12340024...",
  "attempts": [{"request_hex": "0A43210078...", "response_hex": "0A12340024...", "elapsed_ms": 890}]
}]
```

Alarm dialogs (with retries — for AC 5 "Tentative X/Y" rendering):
```json
[{
  "dialog_type": "alarm",
  "routine": 0,
  "timestamp": "2026-05-18T14:35:22+00:00",
  "elapsed_ms": 4200,
  "request_hex": "0A43210078...",
  "response_hex": "0A12340024...",
  "attempts": [
    {"request_hex": "0A43210078...", "response_hex": "", "elapsed_ms": 2000},
    {"request_hex": "0A43210078...", "response_hex": "", "elapsed_ms": 2000},
    {"request_hex": "0A43210078...", "response_hex": "0A12340024...", "elapsed_ms": 200}
  ]
}]
```
**Note:** Per logging-design.md, alarm events use "ONE dialog entry with nested attempts array". The top-level `request_hex`/`response_hex` reflect the final attempt. JS renders each `attempts[]` entry as "Tentative X/Y" sub-block.

**`ParsedMessage` dataclass** (new, in sia_protocol.py):
```python
@dataclass(frozen=True)
class ParsedMessage:
    raw_hex: str
    crc_received: str      # hex string e.g. "B368" (for JS display as "0x${val}")
    crc_computed: str      # hex string e.g. "B368"
    crc_valid: bool
    crc_format: str        # "hex" or "bin" (str, not Literal — must be JSON-serializable)
    length_declared: int
    length_actual: int
    id_token: str          # e.g. "SIA-DCS", "NULL", "ACK", "NAK" (no asterisk — that's the encrypted marker)
    encrypted: bool
    sequence: int
    receiver_prefix: str   # e.g. "R0" or "" if absent
    account_prefix: str    # e.g. "L0"
    account: str
    data_raw: str          # raw data block content
    data_decrypted: str | None  # decrypted content (None if not encrypted or no key)
    extended_fields: dict[str, str]  # parsed extended data fields
    timestamp_str: str | None  # raw timestamp string from frame
```
**JSON-serializable constraint:** ALL field types are str/int/bool/None/dict — `dataclasses.asdict(result)` then `json.dumps()` works without custom encoders.

**`decode()` function signature:**
```python
def decode(raw_hex: str, key: bytes | None = None) -> ParsedMessage:
    """Decode a SIA DC-09 frame from its hex representation.

    Converts hex string to bytes internally via bytes.fromhex(), then reuses
    _extract_frame_components() and _validate_crc() for parsing.

    Args:
        raw_hex: Hex string of the complete frame (LF + CRC + Length + Message + CR).
                 Must be valid hex (even length, 0-9a-fA-F chars only).
        key: Optional 16-byte AES key for decryption.

    Returns:
        ParsedMessage with all parsed fields (all JSON-serializable).

    Raises:
        SIAProtocolError: If frame cannot be parsed (malformed structure, bad hex).
                          Note: CRC mismatch does NOT raise — sets crc_valid=False instead.
    """
    raw = bytes.fromhex(raw_hex)  # ValueError → caught and re-raised as SIAProtocolError
    components = _extract_frame_components(raw)
    if components is None:
        raise SIAProtocolError("Malformed frame structure")
    # ... parse fields from components ...
```
**Design doc reconciliation:** `debug-ui-design.md` defines `decode(raw_bytes: bytes, ...)` but the PHP subprocess passes hex via CLI arg. This function accepts `str` (hex) as the public API; the `bytes.fromhex()` conversion is internal. This is the canonical interface for both CLI and any future direct Python callers.

### Message String Parsing

The message string inside a SIA frame follows this pattern (per SIA DC-09 § 5.5):
```
"id_token"seq#account[data]_timestamp
```

Examples:
- `"*SIA-DCS"0001R0L0#1234[#1234|Nri1/YA001]_14:30:00,05-18-2026`
- `"*NULL"0042R0L0#9876[]`
- `"*ACK"0001R0L0#1234[]`
- `"#1234"0001R0L0#1234[encrypted_block]` (encrypted, id_token starts with `#`)

Parsing steps:
1. Strip outer quotes around id_token: find first `"` and matching `"`
2. Extract sequence number (4 digits after id_token closing quote)
3. Extract receiver prefix (e.g. `R0`) — text before `L` or `#`
4. Extract account prefix (e.g. `L0`) — text from `L` to `#`
5. Extract account number — text from `#` to `[`
6. Extract data block — content between `[` and `]`
7. Extract timestamp — content after `_` (if present)
8. If id_token starts with `#`: frame is encrypted → data block is ciphertext (hex)

### CLI `--decode` Mode

```python
if __name__ == '__main__':
    import sys
    import json
    import os

    if len(sys.argv) >= 3 and sys.argv[1] == '--decode':
        hex_input = sys.argv[2]
        key_hex = os.environ.get('SIA_ENCRYPTION_KEY', '')  # Same env var as testConnection
        key = bytes.fromhex(key_hex) if key_hex else None
        try:
            result = decode(hex_input, key)  # decode() accepts str hex directly
            print(json.dumps(dataclasses.asdict(result)))
        except (SIAProtocolError, ValueError) as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
```

### PHP `decodeFrame` Action Pattern

```php
if (init('action') == 'decodeFrame') {
    $hex = init('hex');
    if (empty($hex)) {
        ajax::error(__('Paramètre hex manquant', __FILE__));
        return;
    }
    if (strlen($hex) > 4096) {
        ajax::error(__('Trame trop longue (max 4096 caractères)', __FILE__));
        return;
    }
    if (!ctype_xdigit($hex)) {
        ajax::error(__('Format hexadécimal invalide', __FILE__));
        return;
    }

    $eqLogics = eqLogic::byType('siaDC09');
    if (empty($eqLogics)) {
        ajax::error(__('Aucun équipement siaDC09 trouvé', __FILE__));
        return;
    }
    $eqLogic = $eqLogics[0];

    // Key stored as 'encryption_key' (no sia_ prefix — eqLogic config is already scoped)
    // Same pattern as testConnection action (line ~37 in this file)
    $encKey = $eqLogic->getConfiguration('encryption_key', '');
    $pythonPath = realpath(__DIR__ . '/../../resources/siadc09d/sia_protocol.py');

    if (method_exists('system', 'getCmdPython3')) {
        $python3 = system::getCmdPython3('siaDC09');
    } else {
        $python3 = 'python3 ';
    }
    $cmd = $python3 . escapeshellarg($pythonPath) . ' --decode ' . escapeshellarg($hex);

    // Same env var name as testConnection: SIA_ENCRYPTION_KEY
    $envPrefix = '';
    if (!empty($encKey)) {
        $envPrefix = 'SIA_ENCRYPTION_KEY=' . escapeshellarg(bin2hex($encKey)) . ' ';
    }

    set_time_limit(10);
    exec($envPrefix . $cmd . ' 2>/dev/null', $output, $retCode);

    if ($retCode !== 0 || empty($output)) {
        ajax::error(__('Erreur de décodage de la trame', __FILE__));
        return;
    }

    $decoded = json_decode(implode('', $output), true);
    if ($decoded === null) {
        ajax::error(__('Réponse invalide du décodeur', __FILE__));
        return;
    }
    if (isset($decoded['error'])) {
        ajax::error($decoded['error']);
        return;
    }
    ajax::success($decoded);
}
```

### JS Row Layout (collapsed)

```html
<div class="sia-msg-row" data-request-hex="0A43..." data-response-hex="0A12..."
     style="cursor:pointer; padding:6px 10px; border-bottom:1px solid #eee;">
  <span class="sia-direction" style="font-family:monospace;">→</span>
  <span class="sia-token label label-default">*NULL</span>
  <span class="sia-seq text-muted">#0042</span>
  <span class="sia-account">#1234</span>
  <span class="sia-context text-muted">supervision routine</span>
  <span class="sia-status label label-success" style="margin-left:8px;">245ms</span>
  <span class="sia-time pull-right text-muted">14:30:00</span>
</div>
```

### JS Expanded View (field table)

```html
<div class="sia-msg-detail" style="padding:10px 10px 10px 25px; background:#f9f9f9; border-bottom:1px solid #ddd;">
  <div style="margin-bottom:8px;">
    <button class="btn btn-xs btn-default sia-copy-hex" data-hex="0A43...">Copier hex</button>
    <span class="label label-info" style="margin-left:5px;">Chiffrement AES-128-CBC (déchiffré)</span>
  </div>
  <table class="table table-condensed table-bordered" style="margin-bottom:5px;">
    <thead><tr><th>Champ</th><th>Valeur</th></tr></thead>
    <tbody>
      <tr><td>ID Token</td><td><code>*SIA-DCS</code></td></tr>
      <tr><td>Séquence</td><td>0042</td></tr>
      <tr><td>Préfixe récepteur</td><td>R0</td></tr>
      <tr><td>Préfixe compte</td><td>L0</td></tr>
      <tr><td>Compte</td><td>1234</td></tr>
      <tr><td>Données (brut)</td><td><code>Nri1/YA001</code></td></tr>
      <tr><td>Données (déchiffré)</td><td><code>BA01</code></td></tr>
      <tr><td>Champs étendus</td><td>zone=Salon</td></tr>
      <tr><td>Horodatage</td><td>14:30:00,05-18-2026</td></tr>
      <tr><td>CRC</td><td><span style="color:#5cb85c">✓ CRC valide</span> (reçu: 0x4321, calculé: 0x4321)</td></tr>
      <tr><td>Longueur</td><td>déclarée: 84 / réelle: 84</td></tr>
    </tbody>
  </table>
</div>
```

### Daemon Enrichment — Storing Last Sent Frame

In `_send_raw()` (daemon.py line 381), store the frame BEFORE calling transport:

```python
async def _send_raw(self, frame: bytes) -> SIATransportResult:
    self._last_sent_frame = frame  # Store for message_trace callbacks
    if self._sia_transport is None:
        raise SIATransportError("Transport not initialized — on_start() not called")
    return await self._sia_transport.send_frame(frame)
```

**Note:** `_last_sent_frame` must be initialized in `__init__()` as `self._last_sent_frame: bytes = b""` (python-style rule: ALL instance vars in `__init__`).

Then in `_log_sm1_supervision()`, access it as:
```python
"request_hex": self._last_sent_frame.hex() if self._last_sent_frame else "",
```

For the response, after Task 2.0, `SIATransportResult['raw_response']` provides the raw ACK/NAK bytes. Pass through the existing ctx dicts to `_log_sm1_supervision()`.

### Transport Layer Change (Task 2.0 — PREREQUISITE)

**Problem:** `SIATransportResult` (in `sia_transport.py:42-48`) currently only stores `raw_nak: bytes | None` which is `None` for ACK responses. The daemon cannot provide `response_hex` for ACK frames without this change.

**Fix:** Add `raw_response: bytes | None` to `SIATransportResult`:
```python
class SIATransportResult(TypedDict):
    status: Literal['ack', 'nak', 'timeout', 'tcp_drop']
    raw_nak: bytes | None      # Keep for backward compat (used by decode_ack_nak callers)
    raw_response: bytes | None  # NEW: full raw response bytes (ACK or NAK); None on timeout/tcp_drop
```

In `_parse_response()` (sia_transport.py), store `raw` before parsing:
```python
def _parse_response(self, raw: bytes) -> SIATransportResult:
    result = sia_protocol.decode_ack_nak(raw, crc_format=self._crc_format)
    if result['type'] == 'ACK':
        return SIATransportResult(status='ack', raw_nak=None, raw_response=raw)
    elif result['type'] == 'NAK':
        return SIATransportResult(status='nak', raw_nak=result['raw_nak'], raw_response=raw)
    else:
        return SIATransportResult(status='timeout', raw_nak=None, raw_response=raw)
```

### SM1AckLogCtx — No Change Needed

`SM1AckLogCtx` already has `raw_hex: str | None` (currently set to `None`). After Task 2.0, populate it from `result['raw_response'].hex()`:
```python
"raw_hex": result['raw_response'].hex() if result.get('raw_response') else None,
```

SM1NakLogCtx already has `raw_hex: str` — keep it, use as `response_hex` in the callback.

### Testing Strategy

**Level 1 tests only** (no Jeedom instance required):
- Python unit tests for `decode()` and `ParsedMessage`: `tests/level1/test_protocol_decode.py`
- PHP syntax: `find core/ desktop/ -name "*.php" | xargs -n1 php -l`
- JS pattern tests: `tests/level1/test_inspector_js_logic.py` (grep/regex on JS source)
- AJAX structure test: `tests/level1/test_diagnostic_tab.py` (extend existing)

Test vectors for `decode()`:
- Use `encode_message()` to build known frames, then verify `decode()` round-trips correctly
- Test with NULL supervision frame (simplest)
- Test with encrypted frame + valid key
- Test with corrupted CRC (flip a bit)
- Test with malformed hex (odd length, non-hex chars)

### Scope Boundaries

**IN SCOPE (this story):**
- `SIATransportResult` enhancement in `sia_transport.py` (add `raw_response` field)
- `ParsedMessage` dataclass + `decode()` function in `sia_protocol.py`
- CLI `--decode` mode for subprocess invocation
- `decodeFrame` AJAX endpoint
- JS collapsed row rendering (`siaDC09_renderMessages`)
- JS expand/collapse with field table
- JS clipboard copy
- Daemon `message_trace` enrichment with `request_hex` + `response_hex`
- Level 1 tests

**OUT OF SCOPE (story 9-3):**
- Integration testing with live daemon
- End-to-end flow: send supervision → see decoded frame in panel
- Performance testing with 50-entry message list

### Previous Story Learnings (from 9-1)

- Inspector panel HTML already exists — do NOT recreate it
- Actualiser/Vider buttons already wired to `loadDiagnosticData()`/`clearDiagnosticData(messages)` — do NOT rewire
- `siaDC09_loadDiagnosticData()` already fetches `messages` in its response — just need to add rendering call
- Follow `siaDC09_` prefix naming convention for all new JS functions
- jQuery event delegation for dynamic elements: `$('#siaDC09_inspectorList').on('click', '.sia-msg-row', fn)`
- PHP `system::getCmdPython3()` for Python path (not hardcoded `python3`)
- Test patterns: regex-based source analysis in `tests/level1/`
- Always verify PHP syntax after changes

### Project Structure Notes

- Transport result type: `resources/siadc09d/sia_transport.py` — add `raw_response` field to `SIATransportResult`, update `_parse_response()`
- Python decode function: `resources/siadc09d/sia_protocol.py` — add at end, before `if __name__`
- Daemon enrichment: `resources/siadc09d/daemon.py` — modify `_send_raw()`, `_log_sm1_supervision()` and `_log_sm2_event()`
- AJAX handler: `core/ajax/siaDC09.ajax.php` — new `decodeFrame` action before final `throw`
- JS functions: `desktop/js/siaDC09.js` — append after existing Vider handler
- Tests: `tests/level1/test_protocol_decode.py` (new), extend `tests/level1/test_diagnostic_tab.py`

### References

- [Source: docs/design/debug-ui-design.md — Task 5c.3 (Protocol Inspector)]
- [Source: resources/siadc09d/sia_protocol.py — _extract_frame_components, _validate_crc, _compute_crc_modbus]
- [Source: resources/siadc09d/sia_crypto.py — SIACipher.decrypt()]
- [Source: resources/siadc09d/daemon.py — _log_sm1_supervision(), _log_sm2_event(), _send_raw()]
- [Source: _bmad-output/implementation-artifacts/9-1-status-badge-error-panel.md — inspector panel shell, button wiring]
- [Source: core/ajax/siaDC09.ajax.php — existing AJAX pattern, getDiagnosticData already returns messages]
- [Source: desktop/js/siaDC09.js — siaDC09_loadDiagnosticData(), inspector button handlers]

## File List

### New Files
- `tests/level1/test_protocol_decode.py` — Level 1 tests for `decode()` and CLI `--decode` mode
- `tests/level1/test_inspector_js_logic.py` — Level 1 tests for JS inspector rendering and clipboard

### Modified Files
- `resources/siadc09d/sia_protocol.py` — Added `ParsedMessage` dataclass, `decode()` function, `_parse_message_fields()` helper, `if __name__ == '__main__'` CLI block
- `resources/siadc09d/sia_transport.py` — Added `raw_response: bytes | None` to `SIATransportResult`; updated `_parse_response()` and `tcp_drop` return in `SIATCPTransport.send_frame()`
- `resources/siadc09d/daemon.py` — Added `self._last_sent_frame: bytes`; updated `_send_raw()`, `_log_sm1_supervision()`, `_log_sm2_event()`, `_send_with_retry()`
- `core/ajax/siaDC09.ajax.php` — Added `decodeFrame` AJAX action
- `desktop/js/siaDC09.js` — Added `siaDC09_renderMessages()`, `siaDC09_renderFrameDetail()`, `siaDC09_buildHexButtons()`, `siaDC09_buildFieldTable()`, clipboard handler, `_siaDC09_decodeCache`; updated `siaDC09_loadDiagnosticData()` to call `siaDC09_renderMessages()`
- `tests/level1/test_diagnostic_tab.py` — Added `TestDecodeFrameAjax` class (7 tests)

## Dev Agent Record

### Completion Notes

All 9 tasks implemented and passing. 928 level-1 tests pass (0 regressions). Key implementation decisions:

1. **CRC format auto-detection in `decode()`**: Rather than requiring a `crc_format` parameter, the function inspects `crc_bytes` length (4 bytes = hex, 2 bytes = binary), consistent with `_extract_frame_components()`.

2. **Lazy `sia_crypto` import in `decode()`**: The import `from .sia_crypto import SIACipher, AESDecryptionError` is inside the function body (only executed when `encrypted=True` and `key is not None`) to avoid circular dependencies since `daemon.py` imports both modules.

3. **`_log_sm2_event()` response_hex threading**: Rather than adding to `SM2LogCtx` TypedDict (would require updating all callers), added an optional `response_hex: str | None = None` keyword parameter directly to the function signature.

4. **Corrupted CRC test vector**: Flips bit in message body (position 10, not CRC bytes) to avoid CRC bytes becoming non-ASCII, which triggers a different `SIAProtocolError` instead of returning `crc_valid=False`.

### Review Findings

- [x] [Review][Patch] Encrypted marker: `_parse_message_fields()` line 938 — `encrypted = raw_token.startswith('#') or raw_token.startswith('*')` is wrong; `#` is the account separator (e.g. `#1234`), not an encryption marker. Fix: `encrypted = raw_token.startswith('*')` only. [resources/siadc09d/sia_protocol.py:938]
- [x] [Review][Patch] JS timestamp UTC: `siaDC09_formatTimestamp()` uses `d.getHours()` (local time); daemon emits UTC ISO strings. Fix: replace `getHours()`/`getMinutes()`/`getSeconds()` with `getUTCHours()`/`getUTCMinutes()`/`getUTCSeconds()`. [desktop/js/siaDC09.js:785-787]
- [x] [Review][Patch] AC 1 incomplete: `siaDC09_renderMessages()` collapsed row shows `sia-token` label ('alarme'/'supervision'), context, badge, and time — but missing id_token (e.g. "SIA-DCS"), sequence (#0042), and account (#1234) which AC 1 explicitly requires. Added daemon trace fields + JS row rendering. [desktop/js/siaDC09.js:902-906]
- [x] [Review][Patch] Tab binding not delegated: `$('a[href="#diagnosticTab"]').on('shown.bs.tab', ...)` at line 795 uses direct binding at parse time. If the anchor is not yet in DOM (deferred PHP injection), the handler is never registered. Fix: `$(document).on('shown.bs.tab', 'a[href="#diagnosticTab"]', ...)`. [desktop/js/siaDC09.js:795]
- [x] [Review][Patch] Odd-length hex not rejected: `decodeFrame` validates `ctype_xdigit($hex)` but not `strlen($hex) % 2 === 0`. An odd-length hex string passes PHP validation but causes `bytes.fromhex()` to raise a `ValueError` in Python, returning a non-JSON error. Fix: add `if (strlen($hex) % 2 !== 0)` check after the `ctype_xdigit` check. [core/ajax/siaDC09.ajax.php:169]
- [x] [Review][Defer] `execCmd()` on disabled equipment: `getDiagnosticData` calls `$stateCmd->execCmd()` on info commands (lines 127-136). On disabled equipment, `execCmd()` may throw, propagating as AJAX error instead of returning empty diagnostic data. Fix: use `getValue()` instead of `execCmd()`. Pre-existing pattern from story 9-1. [core/ajax/siaDC09.ajax.php:127] — deferred, pre-existing
- [x] [Review][Defer] `$python3` not shell-escaped in `decodeFrame`: `$python3 = system::getCmdPython3('siaDC09')` is concatenated directly into the shell command without `escapeshellarg()`. If interpreter path contains spaces, command breaks. Pre-existing: same unescaped pattern in `testConnection` action (line 58). [core/ajax/siaDC09.ajax.php:194] — deferred, pre-existing
- [x] [Review][Defer] `raw_response=raw` on timeout branch: `_parse_response()` passes garbled/timed-out bytes as `raw_response` on timeout; docstring says `None` on timeout but code passes the raw bytes. Low impact for inspector (timeout dialog won't have decodable hex). [resources/siadc09d/sia_transport.py:122] — deferred, pre-existing
- [x] [Review][Defer] CRC format runtime detection contradicts ADR-06: `decode()` detects `crc_format` from `len(crc_bytes)` at runtime, while ADR-06 establishes it as a preset config field. Acceptable for display-only decode; no operational impact. [resources/siadc09d/sia_protocol.py] — deferred, display-only context

## Change Log

- 2026-05-18: Story 9-2 implemented — Protocol Inspector Hex Viewer & Decryption (all 9 tasks complete, 928 tests pass)
- 2026-05-19: Code review findings added — 5 patches, 4 deferred
