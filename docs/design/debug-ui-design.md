# Debug UI Design — Jeedom siaDC09 Plugin

**Version:** 0.1
**Date:** 2026-03-06
**Status:** Draft — all Component 5c decisions confirmed

---

## Overview

Component 5c adds a **"Diagnostic" tab** to the equipment config page (`desktop/php/siaDC09.php`).
It is a third tab alongside the standard Jeedom "Equipement" and "Commandes" tabs.

The Diagnostic tab aggregates three independent panels, each with its own refresh and clear
controls:

1. **Status badge** — live supervision health from INFO commands
2. **Error panel** — last actionable errors from `last_errors` (Component 5a)
3. **Protocol inspector** — last 50 SIA dialogs from `last_messages` (Component 5b)

No new Jeedom commands are created by this component. All data is read from equipment
configuration keys or existing INFO commands already defined in Components 2, 5a, and 5b.

**Tab location:** `desktop/php/siaDC09.php`, rendered only when `step == 4`
(wizard complete, same condition as the main config view in Component 3).

---

## Task 5c.1 — Status badge

### Purpose

Provides an at-a-glance health indicator at the top of the Diagnostic tab. Reflects the
current state of the daemon/CSR connection without requiring any additional command or
polling mechanism beyond what already exists.

### Data source

Reads two existing INFO commands (Component 2):
- `supervision_state` (numeric): `0` = problem, `1` = impaired, `2` = HEALTHY
- `supervision_label` (string): human-readable current state

No new command is needed.

### Badge rendering

| `supervision_state` | Color | Meaning |
|---|---|---|
| `2` | Green | HEALTHY — supervision active |
| `1` | Orange | Dégradé — supervision impaired (DEGRADED strike 1–2, INITIALIZING) |
| `0` | Red | Problème — supervision lost (DEGRADED strike 3, TCP_RECONNECTING, NO_NETWORK) |

The `supervision_label` string is displayed inline next to the badge dot.

```html
<!-- Rendered example -->
<div id="siaDC09_statusBadge">
  <span class="badge badge-lg" id="siaDC09_badgeDot">●</span>
  <span id="siaDC09_badgeLabel">Connexion à la centrale établie</span>
</div>
```

### Refresh

The badge is populated once on tab load via a single `eqLogic::byId` AJAX call that
fetches `supervision_state` and `supervision_label`. It does not auto-poll. The user
refreshes the full tab by navigating away and back, or by clicking the "Actualiser"
button in any sub-panel (which re-fetches all data including the badge).

---

## Task 5c.2 — Error panel

### Purpose

Shows the last actionable errors stored by Component 5a in the `last_errors` configuration
key. Helps the user understand current error state without opening Jeedom logs.

### Data source

`last_errors` plugin-level config key — `config::byKey('last_errors', __CLASS__, '[]')` —
JSON array, max 10 entries, newest first (Component 5a). Stored at plugin level to avoid
triggering `postSave()` on every write. Each entry is an error object as defined in
`error-handler-design.md`.

### Display

A simple vertical list. Each row:
- Timestamp (local, `HH:MM:SS`)
- Tier badge: `T1` (auto-heal, blue) / `T2` (user-actionable, orange) / `T3` (infrastructure, red)
- Error title (French, from `error_handler.py` context)
- Short description

Empty state: `Aucune erreur enregistrée` (grey italic text).

### Controls

```
[Actualiser]   [Vider]
```

- **Actualiser:** re-fetches `last_errors` from `eqLogic::getConfiguration` via AJAX and
  re-renders the list.
- **Vider:** calls an AJAX handler that sets `last_errors` to `[]` on the eqLogic, then
  re-renders (empty state).

---

## Task 5c.3 — Protocol inspector

### Purpose

Shows the last 50 SIA protocol dialogs (request + response pairs) from the `last_messages`
ring buffer (Component 5b). Allows the user to trace exact protocol exchanges for debugging
and support.

### Data source

`last_messages` plugin-level config key — `config::byKey('last_messages', __CLASS__, '[]')` —
JSON array, max 50 entries, newest first (Component 5b). Stored at plugin level to avoid
triggering `postSave()` on every supervision cycle.

### Row layout: collapsed list + inline expand

Each dialog is a collapsed row by default. Clicking a row expands it inline.

**Collapsed row — alarm event:**
```
[→] SIA-DCS  seq=0007  acct=1234  [BA — Salon]  ✓ confirmé    14:32:11
```

**Collapsed row — supervision (routine):**
```
[→] NULL     seq=0012  acct=1234  [supervision]  ✓ ACK          14:33:00
```

**Collapsed row — supervision (non-routine, timeout):**
```
[→] NULL     seq=0013  acct=1234  [supervision]  ✗ timeout      14:34:00
```

**Columns:**
| Column | Content |
|---|---|
| Direction icon | `[→]` sent, `[←]` received (always `→` for PE-initiated dialogs) |
| Token | `SIA-DCS`, `*SIA-DCS`, `NULL`, `*NULL`, `XNM` |
| Seq | 4-digit sequence number |
| Account | account number |
| Context | alarm event type + zone name, or `[supervision]` |
| Status | `✓ confirmé`, `✗ timeout`, `✗ réponse inattendue (NAK)`, `✗ échec` |
| Time | local timestamp of first send |

**Expanded row — field table:**

The expanded area shows a field-by-field decoded breakdown of the frame, produced by
`sia_protocol.decode()` (see Impact on Component 0 below).

```
┌─ Requête (tentative 1/1) ──────────────────────────────────────────┐
│ Champ         Valeur                                                 │
│ LF            0x0A                                                   │
│ CRC           B368  (valide)                                         │
│ Longueur      0040  (64 octets)                                      │
│ Token         "SIA-DCS"                                              │
│ Chiffrement   non                                                    │
│ Séquence      0007                                                   │
│ Préf. récept. (absent)                                               │
│ Préf. compte  L0                                                     │
│ Compte        #1234                                                  │
│ Données       #1234|BA Salon                                         │
│ Horodatage    _14:32:11,03-06-2026                                   │
│ CR            0x0D                                                   │
│                                            [Copier les octets bruts] │
└────────────────────────────────────────────────────────────────────┘
┌─ Réponse (241 ms) ─────────────────────────────────────────────────┐
│ Champ         Valeur                                                 │
│ LF            0x0A                                                   │
│ CRC           C4A2  (valide)                                         │
│ Longueur      002B  (43 octets)                                      │
│ Token         "ACK"                                                  │
│ Séquence      0007                                                   │
│ Préf. récept. (absent)                                               │
│ Préf. compte  L0                                                     │
│ Compte        #1234                                                  │
│ Données       (vide)                                                 │
│                                            [Copier les octets bruts] │
└────────────────────────────────────────────────────────────────────┘
```

**Encrypted frame:** decrypted using the configured key. The field table shows the
decrypted plaintext fields identically to a non-encrypted frame. An indicator line
`Chiffrement  AES-128-CBC  (déchiffré)` replaces the `non` value.

**Alarm event with retries:** the expanded area shows one request/response block per
attempt, labeled `Tentative 1/3`, `Tentative 2/3`, etc.

**"Copier les octets bruts" button:** copies the raw hex string of that frame to the
clipboard (`navigator.clipboard.writeText(hexStr)`). No inline hex display.

### `sia_protocol.decode()` — ParsedMessage

The field-by-field rendering is produced by a new `decode()` function in
`sia_protocol.py` (Component 0 — see impact section). The JS inspector does not contain
parsing logic; it calls an AJAX endpoint that returns a pre-decoded structure.

```python
@dataclass
class ParsedMessage:
    raw_hex: str
    crc_received: str
    crc_computed: str
    crc_valid: bool
    length_declared: int
    length_actual: int
    id_token: str              # e.g. "SIA-DCS", "*SIA-DCS", "ACK", "NAK"
    encrypted: bool
    aes_blocks: int | None     # populated if encrypted
    sequence: str
    receiver_prefix: str | None
    account_prefix: str
    account: str
    data_raw: str              # hex string if encrypted and no key; plaintext otherwise
    data_decrypted: str | None # populated when encrypted and key provided
    extended_fields: list[tuple[str, str]]  # [(identifier, content), ...]
    timestamp: str | None
```

`decode(raw_bytes: bytes, key: bytes | None = None) -> ParsedMessage`

- If `key` is `None` and message is encrypted: `data_raw` = hex string of ciphertext,
  `data_decrypted = None`.
- If `key` is provided and message is encrypted: decrypt then populate `data_decrypted`;
  `data_raw` still holds the original hex.

The dialogs stored in `last_messages` already contain `raw_hex_req` / `raw_hex` (response)
fields. The PHP AJAX handler calls `decode()` on-demand (not pre-decoded at storage time)
via a dedicated AJAX action `decodeFrame` that invokes `sia_protocol.decode()` server-side.

> **Implementation note (v1.0):** `decodeFrame` AJAX action passes the raw hex string and
> (if encryption is enabled) the key to a Python subprocess call. **The encryption key is
> passed as an environment variable, NOT as a command-line argument**, to prevent key
> exposure in process listings (`ps aux`). The subprocess reads `SIA_DECRYPT_KEY` from the
> environment and exits after returning JSON to stdout.
> Example: `env SIA_DECRYPT_KEY=<key> python3 sia_protocol.py --decode <hex>`
>
> **Subprocess constraints:**
> - **Timeout:** 5 seconds. If the subprocess does not respond within 5s, the AJAX handler
>   returns `{"error": "decode_timeout"}`.
> - **Max input size:** The hex string is capped at **4096 characters** (~2048 raw bytes)
>   before being passed to the subprocess. Oversized input returns
>   `{"error": "decode_failed", "detail": "Frame too large"}` without spawning a process.
> - **Error response format:** On any decode failure (malformed frame, bad hex, CRC mismatch,
>   etc.), the subprocess exits with a JSON object:
>   `{"error": "decode_failed", "detail": "<human-readable reason>"}`
>   The PHP handler forwards this to the JS inspector, which displays the detail string
>   in place of the field table.

### Controls

```
[Actualiser]   [Vider]
```

- **Actualiser:** re-fetches `last_messages` and re-renders the list.
- **Vider:** AJAX call sets `last_messages` to `[]`, re-renders (empty state).

Empty state: `Aucun échange SIA enregistré` (grey italic text).

---

## Task 5c.4 — Polling / refresh mechanism

**Decision: manual only for all panels.**

No background polling while the tab is open. Each panel has its own "Actualiser" button.
The status badge is also refreshed whenever any "Actualiser" button is clicked (single
AJAX call fetches all data: badge + errors + messages together).

Rationale: the Diagnostic tab is opened deliberately for troubleshooting, not for
continuous monitoring. The `supervision_state` INFO command and the Jeedom dashboard widget
(Component 6) serve the continuous monitoring need.

---

## Task 5c.5 — Clear buttons

**Decision: separate "Vider" button per panel.**

| Panel | Button | Action |
|---|---|---|
| Error panel | `Vider` | `config::save('last_errors', '[]', __CLASS__)` |
| Protocol inspector | `Vider` | `config::save('last_messages', '[]', __CLASS__)` |

No global "Tout effacer". Clearing errors does not clear the inspector and vice versa.

Each clear action uses `config::save()` (plugin-level) — no eqLogic save, no `postSave()`
triggered. The daemon's in-memory ring buffer is **not** cleared — only the persisted
config key is reset. New dialogs from the daemon will repopulate `last_messages` as they arrive.

---

## Tab integration in `siaDC09.php`

The Diagnostic tab is added after the "Commandes" tab, visible only when `step == 4`.

```html
<!-- Tab header (added alongside existing tabs) -->
<li role="presentation">
  <a href="#diagnosticTab" aria-controls="diagnosticTab" role="tab" data-toggle="tab">
    <i class="fas fa-stethoscope"></i> Diagnostic
  </a>
</li>

<!-- Tab content -->
<div role="tabpanel" class="tab-pane" id="diagnosticTab">
  <!-- 5c.1 Status badge -->
  <div class="panel panel-default" id="siaDC09_statusPanel"> ... </div>

  <!-- 5c.2 Error panel -->
  <div class="panel panel-default" id="siaDC09_errorsPanel">
    <div class="panel-heading">
      Dernières erreurs
      <button class="btn btn-xs btn-default pull-right" id="siaDC09_errorsRefresh">Actualiser</button>
      <button class="btn btn-xs btn-danger pull-right" id="siaDC09_errorsClear">Vider</button>
    </div>
    <div class="panel-body" id="siaDC09_errorsList"> ... </div>
  </div>

  <!-- 5c.3 Protocol inspector -->
  <div class="panel panel-default" id="siaDC09_inspectorPanel">
    <div class="panel-heading">
      Inspecteur de protocole
      <button class="btn btn-xs btn-default pull-right" id="siaDC09_inspectorRefresh">Actualiser</button>
      <button class="btn btn-xs btn-danger pull-right" id="siaDC09_inspectorClear">Vider</button>
    </div>
    <div class="panel-body" id="siaDC09_inspectorList"> ... </div>
  </div>
</div>
```

---

## Impact on Component 0 (`sia_protocol.py`)

A new task is added to Component 0:

**Task 0.5 — `decode()` function**

Add `decode(raw_bytes: bytes, key: bytes | None = None) -> ParsedMessage` to
`sia_protocol.py`. This is the symmetric counterpart of the existing message builder.

- Parse LF, CRC (hex or binary format), length, ID token, encryption flag, sequence,
  optional receiver prefix, account prefix, account, data block(s), optional extended
  data fields, optional timestamp, CR.
- Validate CRC (compute and compare against declared value).
- Validate declared length against actual message string length.
- If `encrypted=True` and `key` is provided: delegate to `sia_crypto.decrypt()` then
  re-parse the data block.
- Expose as CLI: `python sia_protocol.py --decode <hex_string>` outputs JSON for PHP consumption.
  If decryption is needed, the key is read from the `SIA_DECRYPT_KEY` environment variable
  (never accepted as a CLI argument to prevent exposure in process listings).

This task has no impact on existing Component 0 tasks (message builder, CRC, crypto).

---

## Design decisions summary

| Decision | Choice | Rationale |
|---|---|---|
| Tab location | Separate "Diagnostic" tab in equipment page | Clean separation from config; Jeedom convention |
| Tab visibility | Only when `step == 4` (wizard complete) | No diagnostic until fully configured |
| Status badge data source | Existing `supervision_state` + `supervision_label` INFO commands | No new command needed |
| Raw hex display | Not shown inline — clipboard copy button only | 150–360 hex chars is unreadable; clipboard is actionable |
| Encrypted frame view | Decrypted using configured key → same field table as unencrypted | Key is available; full structure is useful for debugging |
| Decode logic location | `sia_protocol.py` — new `decode()` function | Protocol parsing belongs in the protocol component, not the UI |
| Inspector row UX | Collapsed list + inline expand | Compact overview; detail on demand |
| Refresh mechanism | Manual ("Actualiser") for all panels | Diagnostic tab is opened deliberately; no background polling needed |
| Clear buttons | Separate "Vider" per panel | Independent data lifecycles; no accidental global wipe |
| Clear scope | Config key only (`last_errors`, `last_messages`); ring buffer not reset | Daemon continues logging; new data populates naturally |

---

## Testing strategy for Component 5c

| Test | How |
|---|---|
| Badge green | Daemon running, SM1=HEALTHY → verify badge dot is green, label correct |
| Badge orange | Force DEGRADED strike=1 → verify badge orange |
| Badge red | Force DEGRADED strike=3 → verify badge red |
| Error panel — populated | Inject 3 errors into `last_errors` → verify 3 rows rendered |
| Error panel — empty state | `last_errors = []` → verify `Aucune erreur enregistrée` shown |
| Error panel — Actualiser | Modify `last_errors` externally → click Actualiser → verify UI updated |
| Error panel — Vider | Click Vider → verify `last_errors = []` in config + UI shows empty state |
| Inspector — alarm event row collapsed | 1 alarm dialog in `last_messages` → verify collapsed row shows token/seq/account/status |
| Inspector — alarm event expand | Click row → verify field table with all decoded fields |
| Inspector — encrypted frame | Encrypted alarm dialog → verify field table shows decrypted plaintext + `AES-128-CBC (déchiffré)` indicator |
| Inspector — clipboard button | Click "Copier les octets bruts" → verify clipboard contains raw hex string |
| Inspector — alarm with retries | Dialog with 3 attempts → verify 3 request/response blocks in expanded view |
| Inspector — routine supervision | 1 routine supervision dialog → verify collapsed row shows supervision context |
| Inspector — empty state | `last_messages = []` → verify `Aucun échange SIA enregistré` |
| Inspector — Actualiser | Modify `last_messages` externally → click Actualiser → verify UI updated |
| Inspector — Vider | Click Vider → verify `last_messages = []` in config + UI shows empty state; daemon ring buffer continues |
| decode() — unencrypted | Pass known frame hex → verify all fields match expected values, CRC valid |
| decode() — encrypted + key | Pass encrypted frame hex with key → verify decrypted data field correct |
| decode() — encrypted no key | Pass encrypted frame hex, no key → verify `data_raw` = hex, `data_decrypted = None` |
| decode() — CRC mismatch | Flip one byte → verify `crc_valid = False` |
| decode() — CLI JSON output | `python sia_protocol.py --decode <hex>` → verify valid JSON with all fields |
| Tab hidden in wizard mode | `step < 4` → verify Diagnostic tab not rendered |
