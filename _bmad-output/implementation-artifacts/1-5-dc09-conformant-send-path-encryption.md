# Story 1.5: DC-09-Conformant AES Encryption on the Send Path

Status: ready-for-dev

**Sources:** D-81 (`deferred-work.md:149-151`), SIA DC-09-2021 § 5.4.3-5.4.7, § 5.5.1.2, § 5.5.1.9, § 5.5.2.1, § 5.5.3.1, § 5.6.1.2, § 5.6.2.4 (`internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`), `internal-docs/design/daemon-design.md:146-162, 229-236, 346-374`, ioBroker.sia reference (`https://github.com/hlehoux2021/ioBroker.sia`, `src/lib/sia.ts`). Corrects story 1.2 (`1-2-aes-128-cbc-encryption-module.md`), whose ACs (PKCS#7, random IV, 128-bit only) contradict the spec.

## Story

As a Jeedom user whose monitoring station (CSR) requires DC-09 encryption,
I want the plugin to actually encrypt alarm and supervision frames as DC-09 specifies,
so that an encrypting receiver accepts my frames instead of rejecting a `*` marker over plaintext.

## Background: what is wrong today

1. `SIAMessageBuilder.encode_message(encryption=True)` (`sia_protocol.py:192-261`) only turns `"SIA-DCS"` into `"*SIA-DCS"`. No AES is applied.
2. `SIACipher` (`sia_crypto.py`) does not follow the spec:
   - it pads the tail with PKCS#7 (the spec wants a random front pad plus `|`, § 5.4.4);
   - it returns raw bytes (the spec wants hex ASCII, § 5.4.7);
   - it accepts only 16-byte keys (the spec allows 16, 24 or 32, § 5.4.5).
3. The daemon converts the key with `_enc_key_str.encode()` (`daemon.py:447-448`), but the UI stores it as hex (`desktop/js/siaDC09.js:203-209` checks for 32, 48 or 64 hex characters). The daemon never reads `_encryption_key` anyway.
4. Event frames are hard-coded `encryption=False  # No encryption in v1.0` (`daemon.py:1767`). Supervision frames get the marker only (`daemon.py:959`).
5. `_build_event_frame` passes `timestamp=None` when parsing fails, so no timestamp goes out. An encrypted frame must carry one (§ 5.5.1.9).
6. The inspector trace computes the id_token from `preset.encryption_enabled` (`daemon.py:1327/1364/1395/1427/1873`), not from the frame that was sent.
7. The CSR simulator:
   - never decrypts inbound frames (`_detect_encryption_from_frame` detects the marker only);
   - encrypts its whole ACK frame with the PKCS#7 cipher (`csr_simulator.py:518-560`).

   So every simulator round-trip passes on a non-conformant format and proves nothing.
8. `SIAProtocolDecoder._parse_message_fields` (`sia_protocol.py:~1003`) looks for the first `]`. In an encrypted wire frame the data block's own `]` is inside the ciphertext, and the only visible `]` is the closing one after the hex (see Decision D1).

## Acceptance Criteria

### AC1 — `SIACipher` rewritten to § 5.4.4-5.4.7

- Accepts 16, 24 or 32-byte keys, selecting AES-128, AES-192 or AES-256. Any other length raises `AESKeyError`, and the message never contains the key.
- AES-CBC with a 16-byte zero IV (§ 5.4.6). Nothing is prepended to the ciphertext.
- **Encrypt** takes the plaintext region content (`str` or `bytes`, everything after the first `[`, see AC2):
  - it builds `pad + "|" + content`, where `pad_len = 16 - (len("|" + content) % 16)`;
  - `pad_len` is 16, not 0, when the length is already a multiple of 16;
  - pad bytes are drawn from `secrets` over printable ASCII 0x20-0x7E, excluding `|` (0x7C), `[` (0x5B) and `]` (0x5D);
  - it returns **uppercase hex ASCII** (§ 5.4.7);
  - the pad source is injectable (constructor or keyword arg) so tests are deterministic. Production uses `secrets`.
- **Decrypt** takes hex (any case):
  - it rejects non-hex input, odd length, or a byte length that is not a multiple of 16, with `AESDecryptionError`;
  - it strips everything up to and including the **first** `|`;
  - a plaintext with no `|` raises `AESDecryptionError`;
  - it returns the region content.
- PKCS#7 is removed completely. `encrypt_frame`/`decrypt_frame` aliases follow the new semantics or are removed, with every caller updated.
- Docstrings cite § 5.4.3-5.4.7, replacing the wrong § 5.5.1.10.

### AC2 — `encode_message()` encrypts when asked

- New keyword argument `encryption_key: bytes | None = None`.
- With `encryption=True`, a missing key raises `AESKeyError`. A marker-only frame must no longer be possible.
- Plaintext region = `data_field[1:]` (drop the leading `[`, keep its closing `]`) + extended-data fields + timestamp (§ 5.4.3).
- Wire message = `"*SIA-DCS"` + seq + `[R…][L…]#acct` + `[` + hex + `]` (Decision D1).
- CRC and length are computed on the wire form (§ 5.5.1.2). The existing `_frame()` path is reused unchanged.
- With `timestamp=None` and `encryption=True`, the current UTC time is used, because the timestamp is mandatory (§ 5.5.1.9). The unencrypted path keeps today's behaviour exactly: `None` means no timestamp.
- The unencrypted output is byte-for-byte unchanged. Existing golden frames `frames_*` other than `frames_encrypted_*` must still match.
- `make_supervision_message(encryption=True, encryption_key=…)` builds an encrypted Null Message per § 5.5.2.1 (Decision D2):

  ```
  "*NULL"0000<Rrcvr><Lpref>#acct[<hex>]
  ```

  - The plaintext region is `pad|` + `]` + timestamp. The `|` is required in every encrypted message (§ 5.4.4.3), even though the § 5.5.2.1 template only shows `[<pad>]`.
  - The seq field is the literal `0000`, as in the template. It does not consume a `SequenceTracker` number.
  - The timestamp is mandatory.
- `make_supervision_message(encryption=False)` is unchanged: it still sends `"SIA-DCS"…[#acct|0000]` (see D-86).

### AC3 — Daemon uses the key and encrypts events

- `SIADaemon.__init__` decodes the key with `bytes.fromhex(...)` (`daemon.py:447-448`).
- When `preset.encryption_enabled` is true and the key is empty, not hex, or not 16/24/32 bytes:
  - the daemon logs an error **without** the key value;
  - it refuses to send encrypted frames: events go to FAILED with a distinct reason, and supervision does not send.
  - It never falls back silently to plaintext.
- `_build_event_frame` passes `encryption=self._preset.encryption_enabled, encryption_key=self._encryption_key`. The `encryption=False` override at `daemon.py:1767` is removed.
- Each encrypted attempt is rebuilt with a fresh UTC timestamp, which fits the CSR's +20/-40 s window (§ 5.5.1.9). The event's own time stays in the SM2/inspector records. Unencrypted attempts keep today's timestamp logic.
- `_send_supervision` passes the key.

### AC4 — NAK is retried immediately with an updated timestamp (encrypted and unencrypted)

- § 5.6.1.2 is unconditional: on a NAK, the PE **shall** immediately repeat the message a limited number of times, using an updated timestamp. The rule doesn't depend on encryption.
- A conformant CSR only sends a NAK after an encrypted message fails the timestamp test (§ 5.5.3.2, § 5.6.2.1). Some receivers also NAK plaintext frames, and the rule applies to those too.
- Any NAK on an event triggers an immediate re-send within the existing `max_retries` budget, with no 1 s sleep. The frame is rebuilt with an updated timestamp:
  - the timestamp comes from the NAK when `parse_nak_timestamp` returns one;
  - otherwise it is the current UTC time.
- An unencrypted frame that had no timestamp gets one on the NAK retry.
- After the budget is used up, the event goes to FAILED with reason `'nak'`. The SM2 label, error handler and notification are unchanged.
- Today's behaviour (NAK → straight to FAILED, `daemon.py` `_send_with_retry`) is replaced for both modes. Existing tests that pin "NAK → FAILED after one attempt" are updated, not deleted.
- Covered by level2 tests using a simulator mode that NAKs once and then ACKs, run once encrypted and once unencrypted.

### AC5 — PHP guard validates the key

- `deamon_info` guard 5 (`core/class/siaDC09.class.php:188-195`) checks, when encryption is enabled, that the key is hex of length 32, 48 or 64. This mirrors `desktop/js/siaDC09.js:203-209`.
- The launch-blocking message tells the user what is wrong without echoing the key.
- `deamon_start` passing and log redaction (`siaDC09.class.php:244-268`) are unchanged.

### AC6 — Connection test really encrypts

- `run_connection_test` (`siadc09d.py:255-300`) decodes `SIA_ENCRYPTION_KEY` with `bytes.fromhex` and passes it to `encode_message`.
- Encryption enabled with a missing or invalid key gives a clear verdict (a new or existing `_TEST_VERDICTS` entry), not a marker-only frame.

### AC7 — Inspector shows what was really sent

- Trace id_tokens (`daemon.py:1327/1364/1395/1427/1873`) come from the frame actually built, not from `preset.encryption_enabled`.
- `SIAProtocolDecoder.decode(raw_hex, key)`:
  - decrypts a `*SIA-DCS` wire frame with the new cipher and parses the plaintext region;
  - the `data_raw` and timestamp fields show the plaintext;
  - `encrypted=True` is reported.
- A wrong key or corrupt ciphertext gives a clean decode error, not a traceback. Neither the key nor the plaintext pad appears in the output.
- `_parse_message_fields` accepts the encrypted wire form (`[` + hex + `]`, and tolerates a missing closing `]`, see Decision D1). It also accepts the `"*NULL"` and `"NULL"` tokens.
- `__main__ --decode` with `SIA_ENCRYPTION_KEY` keeps working (`sia_protocol.py` CLI; PHP `core/ajax/siaDC09.ajax.php:215-245`).

### AC8 — CSR simulator behaves like an encrypting receiver

- For a `*`-marked frame, the simulator decrypts the region with its configured key.
- On failure it discards the frame silently: no ACK and no NAK (§ 5.6.2.4).
- On success it answers with a spec-format encrypted ACK (§ 5.5.3.1):

  ```
  "*ACK"<seq><rpref><lpref>#<acct>[<hex of pad|]_HH:MM:SS,MM-DD-YYYY>]
  ```

  The encrypted region is `]` + timestamp, framed with CRC and length over the wire form.
- NAK and DUH stay unencrypted.
- An optional mode NAKs the first frame and ACKs the retry (needed for AC4).
- `decode_ack_nak` still classifies `*ACK` as ACK. There is no requirement to decrypt the ACK body.

### AC9 — Tests prove conformance independently of `SIACipher`

- **Independent oracle** (level1): a test helper built directly on `cryptography` primitives (`Cipher(algorithms.AES(key), modes.CBC(b"\0"*16))`), not on `SIACipher`.
  - It decrypts frames produced by `encode_message`.
  - It asserts:
    - the plaintext starts with `pad|`, and the pad avoids `| [ ]`;
    - the total length is a multiple of 16;
    - the pad is 16 bytes when the content is already aligned;
    - the content equals the expected `#acct|code…]…_timestamp`.
  - It covers 16, 24 and 32-byte keys.
- **ioBroker port** (level1): a small Python port of ioBroker.sia's decrypt and parse path, used to parse our frames. That path is: payload regex `\[(.+)`, `aes-{128|192|256}-cbc` with zero IV, pad removed at `indexOf('|')`, then `"(.+?)?\](\[(.*?)\])?(_(.+)){0,1}"`. This is the external reference, noted in D-81.
- **Deterministic vector:** a fixed key and an injected pad give a fixed hex string.
  - It replaces `tests/fixtures/golden/frames_encrypted_alarm.hex`, which is PKCS#7-based (ciphertext `E5BD0B70…`).
  - `tests/level1/test_harness.py` is updated.
  - The vector's origin is documented in a header comment or the test docstring.
- **Annex B.4 is not a usable vector.** The spec gives no key. B.4 (`"*SIA-DCS"`) and the § 5.4.7 example (`"*ADM-CID"`) carry the **same** 96-hex ciphertext for different plaintexts. Both declare length `007B` (123) for a 119-byte message. The examples are illustrative only, so don't try to decrypt them and don't invent a key.
- `tests/level1/test_sia_crypto.py` (39 tests, PKCS#7-based) is rewritten for the new semantics, not deleted wholesale. Round-trip, key-length, bad-input and pad-alphabet tests are kept.
- Other tests that depended on PKCS#7 or marker-only frames are updated. Known files:
  - `test_protocol_decode.py`
  - `test_csr_simulator.py`
  - `test_connection_test.py`
  - level2 `test_sm2_frame_building.py` and `test_sm1_extended_suite.py`
  - level3 e2e
  - `tests/conftest.py:93` (`preset_encrypted`) and `:201` (`test_cipher`)
- **Leak test:** a test captures daemon logs, inspector traces and the connection-test output during an encrypted send and checks that the key hex never appears.
- **Regressions:** compare against the known baseline, not against zero failures:
  - level1: 2 failures
  - level2: 6 failures
  - level2_5: 1 failure

  No new failures are allowed.

### AC10 — Docs tell the truth

- The "encryption not implemented" limitation is replaced in:
  - `README.md:32`
  - `docs/admin-guide.md:150-151`
  - `docs/developer-guide.md:157`
  - `docs/fr_FR/index.md:236`
  - `docs/fr_FR/changelog.md:20` (new entry)
- The replacement text depends on AC11:
  - if AC11 passes: "implemented and validated against <receiver>";
  - otherwise: "implemented to DC-09-2021 § 5.4, **not yet validated against a real receiver**".
- Follow the public-docs editorial rules: early-tester framing, no IMA, a single French changelog.
- `daemon-design.md` is updated where it differs from the implementation, notably on the closing `]` (D1).
- D-81 in `deferred-work.md` is marked resolved, with a pointer to this story. A partial resolution is marked as such if AC11 is blocked.

### AC11 — Live validation against a real receiver (may be BLOCKED)

- Herve's call on 2026-09-27: live tests happen in a **separate session after implementation**. The dev session delivers AC1-AC10 and moves the story to review with AC11 open. Live validation is a later session.
- Whether the receiver supports encryption, and which key it uses, is still unknown.

- Target: the real receiver `192.168.100.15:10002` over TCP, account `001234`, through `test-jeedom.lehoux.net`. Code arrives by `git pull`, so push before validating.
- Steps:
  1. Enable encryption with the key the receiver expects.
  2. Trigger one alarm event and let at least one supervision cycle run.
  3. Record the inspector trace and the receiver's ACK.
- If the receiver has no encryption support or no key is available, mark the task **BLOCKED**:
  - do not claim validation;
  - never use the simulator as a substitute for validation;
  - status may still go to review, with AC11 explicitly open.
- The validation must be done through the Jeedom UI or API, not through reflection-based checks.

## Decisions (reviewed with Herve 2026-09-27)

- **D1 — Close with `]` after the hex (Herve, 2026-09-27).**
  - Both spec examples (§ 5.4.7 and Annex B.4) show `[<hex>]`. This is what we emit.
  - § 5.4.3 says encryption "ends just before the terminating `<CR>`", so the closing `]` is framing and sits outside the encrypted region. The data block's own `]` is encrypted inside the region.
  - ioBroker's regex `\[(.+)` captures the trailing `]` too. Node's `Buffer.from(s, 'hex')` stops at the first non-hex character, so ioBroker tolerates both forms. The ioBroker port in AC9 must reproduce that truncation, not strip the `]` by hand.
  - The decoder and simulator accept both forms. The choice lives in one constant.  - § 5.4.3 puts the data block's `]` inside the encrypted region. The ioBroker regex `\[(.+)` runs to the end of the message, and its ACK is emitted as `[{hex}` with nothing after it.
  - The § 5.4.7 example shows a trailing `]`, which is the ambiguity.
- **D2 — Encrypted supervision uses `"*NULL"` (checked against the spec, 2026-09-27).**
  - § 5.5.2: when supervision is enabled, the PE "shall transmit the Null Message each time the supervision interval elapses".
  - § 5.5.2.1 defines only `NULL`, `*NULL`, `XNM` and `*XNM` for this. An event frame carrying code `0000` is not a Null Message in either mode.
  - Encrypted supervision is new code with no field-validated behaviour to preserve, so it follows the spec: `"*NULL"0000…[<hex of pad|]_ts>]`.
  - Unencrypted supervision keeps `"SIA-DCS"…[#acct|0000]`, because that shape is what the real receiver has ACKed in the field. Moving it to `"NULL"` is D-86. It needs a live check first.
  - The CSR's reply to `*NULL` is an encrypted `*ACK` (§ 5.5.2.1: "the CSR shall acknowledge"). `decode_ack_nak` already classifies it as an ACK.
- **D3 — The fresh timestamp for encrypted retries is UTC "now"**, not the event time. The event time is kept in SM2 state and the inspector.

## Out of Scope

- D-85: the wire sequence number increments on every retry (see `deferred-work.md`). This story must not make it worse. It does not fix it.
- Switching **unencrypted** supervision to `"NULL"` (D-86).
- Using `XNM`/`*XNM` (extended Null Message).
- Persisting a clock offset learned from NAK timestamps.
- Key storage and CLI exposure: the key stays in eqLogic config and on the daemon CLI (ADR-07, `architecture.md`).
- Changes to the IMA preset (D-84).
- Encrypted NULL messages from the CSR side, `[K…]` key-change extended data, and any authentication hash (`[A…]`).

## Tasks / Subtasks

- [ ] **Task 1: rewrite `SIACipher` (AC1, AC9)**
  - [ ] 1.1 Write the independent oracle helper and the new `test_sia_crypto.py` tests first (TDD).
  - [ ] 1.2 Implement key sizes, the front pad + `|`, hex output, and decrypt stripping to the first `|`. Make the pad source injectable.
  - [ ] 1.3 Remove PKCS#7. Update or remove the `encrypt_frame`/`decrypt_frame` aliases and every caller (`grep -rn "encrypt_frame\|decrypt_frame\|SIACipher" resources/ tests/`).
- [ ] **Task 2: `encode_message` encryption (AC2, AC9)**
  - [ ] 2.1 Tests: oracle decryption of `encode_message` output with 16/24/32-byte keys, with and without zone, with a `[V…]` block, and with and without a timestamp.
  - [ ] 2.2 Implement the region split, `[`+hex wire form, CRC/length on the wire form, mandatory timestamp and the missing-key error.
  - [ ] 2.3 Replace the golden `frames_encrypted_alarm.hex` fixture with the deterministic vector. Update `test_harness.py`.
  - [ ] 2.4 Port the ioBroker decrypt/parse logic as a test helper and assert it parses our frames.
  - [ ] 2.5 Encrypted supervision: `"*NULL"0000…` with plaintext `pad|]_ts`, checked against the oracle.
- [ ] **Task 3: daemon wiring (AC3, AC4, AC7)**
  - [ ] 3.1 Decode the key with `bytes.fromhex`, validate it, and log errors without the key.
  - [ ] 3.2 `_build_event_frame`: remove the override, pass the key, and use a fresh UTC timestamp when encrypting.
  - [ ] 3.3 `_send_supervision`: pass the key.
  - [ ] 3.4 `_send_with_retry`: any NAK → immediate retry with the NAK or UTC timestamp, in both modes (AC4). Update the tests that pin NAK → FAILED.
  - [ ] 3.5 Take the trace id_token from the built frame.
- [ ] **Task 4: decoder (AC7)**
  - [ ] 4.1 Make `_parse_message_fields` accept `[hex]` (and tolerate `[hex`), plus the `NULL`/`*NULL` tokens.
  - [ ] 4.2 `decode()` with the new cipher. Clean errors. `--decode` CLI.
- [ ] **Task 5: simulator (AC8)**
  - [ ] 5.1 Inbound decrypt, with silent discard on failure.
  - [ ] 5.2 Spec-format `*ACK` built from `pad|]_ts`.
  - [ ] 5.3 NAK-once-then-ACK mode.
- [ ] **Task 6: PHP and connection test (AC5, AC6)**
  - [ ] 6.1 Guard 5 key-format check. Run `php -l`.
  - [ ] 6.2 `run_connection_test`: `fromhex`, the real key, and a verdict for a bad or missing key.
- [ ] **Task 7: test suite sweep (AC9)**
  - [ ] 7.1 Update the dependent level1/level2/level3 tests and the conftest fixtures.
  - [ ] 7.2 Add the key-leak test.
  - [ ] 7.3 Run `python3 -m pytest tests/level1/`, `tests/level2/` and `tests/level2_5/` and compare against the baseline (2/6/1). Run `python3 -m pylint resources/siadc09d/`.
- [ ] **Task 8: live validation (AC11)**: may be BLOCKED, see AC11.
- [ ] **Task 9: docs and tracking (AC10)**
  - [ ] Update README and docs to match the AC11 outcome.
  - [ ] Update `daemon-design.md`.
  - [ ] Update D-81.
  - [ ] Update the `aes-encryption-not-implemented` memory note.

## Dev Notes

### Files to change: current state and what must be preserved

- **`resources/siadc09d/sia_crypto.py`**
  - Today: `SIACipher(key)` accepts exactly 16 bytes (`KEY_SIZE = 16`), with `IV = b'\x00'*16`. `encrypt()` pads with PKCS#7 and returns raw bytes.
  - Errors: `AESKeyError`, `AESEncryptionError`, `AESDecryptionError`.
  - Preserve: the class and exception names (imported in `daemon.py`, `sia_protocol.py` and `csr_simulator.py`) and the `cryptography` backend. `cryptography` is already declared in `plugin_info/packages.json` (42.0.8 in the venv), so no new dependency is needed.
- **`resources/siadc09d/sia_protocol.py`**
  - `encode_message` is at 192-261. It builds `id_token + seq + account_id_str + data_field + extended_data_field [+ timestamp_str]`.
  - `_format_data_field` returns `[#acct|code]` or `[#acct|code zone]`.
  - `_format_extended_data_field` returns `[V…]`.
  - `_format_timestamp(None)` returns `None`; otherwise it returns `_%H:%M:%S,%m-%d-%Y`.
  - `SequenceTracker.next_seq` increments on **every** `encode_message` call.
  - `decode_ack_nak` strips `*`.
  - `_parse_message_fields` (around line 1003) requires `]`.
  - Preserve: unencrypted output byte-for-byte, and the D-80 behaviour (do not fix D-80 here unless it is trivially adjacent).
- **`resources/siadc09d/daemon.py`**
  - Key: 447-448.
  - `_send_supervision`: 926 (encryption at 959).
  - Traces: 1327/1364/1395/1427/1873.
  - `_send_with_retry`: 1441. `_sia_seq` is incremented once at 1474. Each attempt calls `_build_event_frame` under `wait_for(timeout=10.0)`.
    - NAK → FAILED `'nak'`.
    - Timeout or `SIATransportError` → 1 s sleep, then retry.
    - `SIAProtocolError` or `AESEncryptionError` → FAILED.
  - `_build_event_frame`: around 1706, with the override at 1767.
  - `daemon.py` is the merge hot-spot when agents run in parallel. Keep the changes surgical.
- **`resources/siadc09d/siadc09d.py`**
  - `run_connection_test`: 255-300.
  - CLI args `--encryption-enabled`/`--encryption-key`: 370-410.
  - `_TEST_VERDICTS`: 73-117.
- **`resources/siadc09d/csr_simulator.py`**: `_detect_encryption_from_frame`, and `_generate_ack_frame` at 518-560.
- **`core/class/siaDC09.class.php`**
  - Guard 5: 188-195.
  - `deamon_start`: 244-268. The key is passed via `escapeshellarg` and redacted in the log.
- **`core/ajax/siaDC09.ajax.php`**
  - Connection test: 30-65. The key is passed through the `SIA_ENCRYPTION_KEY` environment variable.
  - Decode: 215-245. It uses `ctype_xdigit ? key : bin2hex`.

### Byte-level worked example (for orientation, not a normative vector)

- Plaintext region for account `1234`, code `BA`, zone `001`, at 12:00:00 UTC on 2026-09-27:

  ```
  #1234|BA 001]_12:00:00,09-27-2026
  ```

  That is 33 bytes. With the `|` it is 34. 34 % 16 = 2, so `pad_len` = 14.
- Encrypted input: 14 pad characters + `|` + region = 48 bytes. The output is 96 hex characters.
- Wire message:

  ```
  "*SIA-DCS"0001L0#1234[<96 hex>]
  ```

  CRC and length are computed on this string.

### Testing standards

- The unit test runner is `python3 -m pytest tests/level1/`. Put the oracle and the ioBroker port in a level1 helper module (for example `tests/level1/_dc09_crypto_oracle.py`) so level2 can reuse them.
- When a live run shows a gap, write the level1/level2 test before retrying live.

### References

- Spec § 5.4.3-5.4.7, § 5.5.1.2, § 5.5.1.9, § 5.5.2, § 5.5.2.1, § 5.5.3.1, § 5.5.3.2, § 5.6.1.2, § 5.6.2.1, § 5.6.2.4, Annex B.4 (illustrative only)
- `internal-docs/design/daemon-design.md:146-162` (encryption design), `:229-236` (encrypted ACK), `:346-374` (cipher API)
- `_bmad-output/planning-artifacts/architecture.md`: ADR-07 (key lifecycle)
- `_bmad-output/planning-artifacts/epics.md:184-204`: Story 1.2. Its ACs are superseded by this story.
- ioBroker.sia `src/lib/sia.ts`: the external reference for decrypt/parse and the ACK shape

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
