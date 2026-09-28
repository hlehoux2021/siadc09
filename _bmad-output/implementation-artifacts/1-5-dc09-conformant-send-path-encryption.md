# Story 1.5: DC-09-Conformant AES Encryption on the Send Path

Status: review

**Sources:**
- D-81 (`deferred-work.md`) and D-85 (seq on retries, now in scope).
- SIA DC-09-2021 (`internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`): § 5.4.3-5.4.7, § 5.5.1.2, § 5.5.1.3, § 5.5.1.5, § 5.5.1.9, § 5.5.2.1, § 5.5.3.1, § 5.5.3.2, § 5.6.1.2, § 5.6.2.4, Annex F.5.
- `internal-docs/design/daemon-design.md:146-162, 229-236, 346-374`.
- Third-party encrypted frames, each decrypted and CRC-checked on 2026-09-27; see "External test vectors".

Corrects story 1.2 (`1-2-aes-128-cbc-encryption-module.md`). Its random-IV and PKCS#7 ACs contradict the spec. Its 128-bit-only AC was under-featured rather than non-conformant: § 5.4.5.2 lets the PE manufacturer choose the key length, and only the CSR must support all three (§ 5.4.5.1).

## Story

As a Jeedom user whose monitoring station (CSR) requires DC-09 encryption,
I want the plugin to actually encrypt alarm and supervision frames as DC-09 specifies,
so that an encrypting receiver accepts my frames instead of rejecting a `*` marker over plaintext.

## Background: what is wrong today

1. `SIAMessageBuilder.encode_message(encryption=True)` (`sia_protocol.py:192-261`) only turns `"SIA-DCS"` into `"*SIA-DCS"`. No AES is applied.
2. `SIACipher` (`sia_crypto.py`) does not follow the spec:
   - it pads the tail with PKCS#7 (the spec wants a random front pad plus `|`, § 5.4.4);
   - it returns raw bytes (the spec wants hex ASCII, § 5.4.7);
   - it accepts only 16-byte keys.
3. The daemon converts the key with `_enc_key_str.encode()` (`daemon.py:447-448`). But the UI stores it as hex: `desktop/js/siaDC09.js:128-129` checks for 32, 48 or 64 hex characters. The daemon never reads `_encryption_key` anyway.
4. Event frames are hard-coded `encryption=False  # No encryption in v1.0` (`daemon.py:1767`). Supervision frames get the marker only (`daemon.py:959`).
5. `_build_event_frame` passes `timestamp=None` when parsing fails, so no timestamp goes out. An encrypted frame must carry one (§ 5.5.1.9).
6. The inspector trace takes its id_token from `preset.encryption_enabled` (`daemon.py:1327/1364/1395/1427/1873`), not from the frame that was sent.
7. The CSR simulator is not a real encrypting receiver, so every encrypted round-trip through it passes on a non-conformant format and proves nothing:
   - it never decrypts inbound frames;
   - it encrypts its whole ACK with the PKCS#7 cipher (`csr_simulator.py:518-560`);
   - it classifies only `SIA-DCS` tokens, so it NAKs a `*NULL`;
   - it looks for NULL vs ALARM (`'0000'`) and for the account in the raw data block, which is ciphertext when encrypted;
   - its NAK is `"NAK"0000R0L0A0[]` with no timestamp, while § 5.5.3.2 is `"NAK"0000R0L0#0[]<timestamp>`.
8. `SIAProtocolDecoder._parse_message_fields` (`sia_protocol.py:~1009`) needs a `]` after `[`. Real encrypted frames have no `]` after the hex (see D1), so they fail to parse.
9. Today a NAK sends an event straight to FAILED, and a supervision NAK only adds a strike (`daemon.py:1049-1112`). § 5.6.1.2 says to repeat the message immediately with an updated timestamp.
10. The wire seq increments on every `encode_message` call (`SequenceTracker.next_seq`, `sia_protocol.py:238`), so retries go out with a new seq. § 5.5.1.5 says "The PE shall not increment the sequence number when repeating a message", and F.5 shows the NAK retry with the "same sequence" (D-85).
11. An `AESKeyError` raised by the send path escapes every except-list. `_send_with_retry` and `_send_supervision:960` only catch `(SIAProtocolError, AESEncryptionError)`. The event then stays PENDING, with no FAILED status and no notification.

## External test vectors (found and verified 2026-09-27)

Each vector below was decrypted locally with AES-CBC and a zero IV. Its CRC (CRC-16/ARC) and declared length were recomputed over the wire body, meaning from the first `"` to the end of the hex, excluding LF, CRC+len and CR.

| ID | Source | Origin | Key bytes | Plaintext (decrypted) | CRC/len |
|---|---|---|---|---|---|
| V1 | pysiaalarm commit fc0fcfb, `tests/run_re.py` | **Real PE** (Ajax hub, account EA1984) | ASCII `3BD7E66AA9E2F190` (16 bytes) | `v\nV\xb5\x02\xc0\xab\|#EA1984\|Nri0/RP0000]_16:57:20,08-11-2020` | `85DF`/`0078` match **without** a `]` after the hex |
| V2 | pysiaalarm commit 894f8d6 | Real PE (same Ajax hub) | same | `…\|#EA1984\|Nri0/YG0]_12:56:10,07-17-2020` | match |
| V4 | DC09Gen online generator (quoted in ioBroker.sia and node-red-contrib-sia-ultimate) | Independent third-party encoder | hex `0123456789ABCDEF0123456789ABCDEF` | `ppppppppppppp\|12345A\|NFA129]_13:14:15,02-15-2006` | not quoted |
| V5 | Spec § 5.4.7 (Annex B.4 has the same ciphertext) | Spec author | **16 zero bytes** | `ppppppppp\|#1234\|1140 00 007]_22:49:34,01-22-2012` | spec's `4B89`/`007B` match **no** variant |
| V6 | pysiaalarm commit be4301b | Unknown third-party generator | ASCII `AAAAAAAAAAAAAAAA` | `ppppppppppp]_18:24:52,07-05-2020` (`*NULL`, **no `\|`**) | `76D8`/`0055` match without a `]` after the hex |
| V7 | gosia `parse_test.go:346-367` @f76a848 | Real receiver `*ACK` (vendor unknown) | hex `0123456789ABCDEF0123456789ABCDEF` | `OKKTDDFXWNX]_13:41:10,04-30-2026` (**no `\|`**) | match |
| S1 | Swissdotnet sia-dc-09-library @7437ae5, `ParsingStandardTest.java:180` | The library SIA itself promotes (circular for us, but independent) | hex `ABCD`×8 | `<random binary>\|]_13:43:09,06-22-2015` (`*NULL` **with `\|`**) | match |

Frames, verbatim:

```
V1 85DF0078"*SIA-DCS"4480L0#EA1984[83F153789366885D5F83DD5A8D19F691DE6602D5D71342E244C040C5D10D89040444068312750F38DF7E63AD3DE8AD5A
V2 021A0078"*SIA-DCS"0764L0#EA1984[E759F1FE2FDBAF5B30AED69378DF87CF9DA82AA9292D0661E3EBA6DF2AD55AEA4D91968EE8460EC206B8AEAD69B33BCB
V4 "*SIA-DCS"9876R579BDFL789ABC#12345A[209c9d400b655df7a26aecb6a887e7ee6ed8103217079aae7cbd9dd7551e96823263460f7ef0514864897ae9789534f1
V5 "*ADM-CID"0001L0#1234[371baac130fe81508f556e6fd2ccfd8826e9ba186f0fb674bb87c079484e546dff35532aa285936a00c27b6feb053f68]
V6 76D80055"*NULL"0000R0L0#AAAB[B4BC8B40D0E6D959D6BEA78E88CC0B2155741A3C44FBB96D476A3E557CAD64D9
V7 C1B30052"*ACK"0001L0#1001[FFAC5F1A3794837779D9C95762764263A68961C08ABD2942B4607F2321BF554A
S1 CAC10064"*NULL"0000RC0FFDL1234#080027E62A64[70D7DC480FA7DC0DE428CE02447BA2E2981A161EA14CB780D2CD917208059E11
```

A survey of 16 open-source implementations (2026-09-27; clones in `/tmp/siaresearch/`) found:
- **All of them** use a zero IV and put hex after `[` up to CR, with no `]` after it. Only artis101 requires a `]`, and it fails on real traffic.
- **NAK is always plaintext.**
- **Pipe `|` in an empty ACK/NULL:**
  - Present in Swissdotnet (default), gosia, ioBroker and RoslynServer2.
  - Absent in pysiaalarm, fioletoven, AjaxBridge, V6 and V7.
  - RoslynServer2 rejects plaintext without a `|`; the rest accept both forms.
- **Pad bytes:**
  - Two open ABUS Secvest issues (node-red-contrib-sia-ultimate #6, ioBroker.sia #31) report the panel rejecting a receiver's encrypted ACK whose pad bytes were PKCS#7-like or zero. The cause is unverified.
  - Spec-style pad bytes (random, excluding `|[]`) are the safe choice.

What they establish:
- The encrypted region is `pad|` + data (its own `]` included) + extended data + timestamp, and nothing is prepended.
- The pad is 1-16 bytes, a full 16 when the content is already aligned. Real panels use random **binary** pad bytes, including 0x0A and bytes ≥ 0x80.
- Real panels send **no `]` after the hex**, and CRC/length cover the hex.
- The hex may be upper or lower case.
- Receivers see keys in two forms. Real Ajax hubs use the key string's **ASCII bytes**. DC09Gen and the spec example use **hex-decoded** bytes.
- At least one third-party `*NULL` encoder leaves out the `|`, even though § 5.4.4.3 requires it.
- The spec's CRC and length values are wrong everywhere, in every example frame, encrypted or not, so never use them as oracles. B.4 is labelled `*SIA-DCS` but decrypts to the ADM-CID payload.

## Acceptance Criteria

### AC1 — `SIACipher` rewritten to § 5.4.4-5.4.7

- **Keys:**
  - 16, 24 or 32-byte keys select AES-128, AES-192 or AES-256.
  - Any other length raises `AESKeyError`, and the error message never contains the key.
- **Cipher:** AES-CBC with a 16-byte zero IV (§ 5.4.6). Nothing is prepended to the ciphertext.
- **Encrypt** takes the plaintext region content as `bytes`:
  - Callers encode `str` content as ASCII, like the unencrypted path does. `pad_len` is computed on those bytes.
  - It builds `pad + b"|" + content`, with `pad_len = 16 - (len(b"|" + content) % 16)`. That makes `pad_len` 16, not 0, when the length is already aligned.
  - Pad bytes come from `secrets`, over printable ASCII 0x20-0x7E minus `|` (0x7C), `[` (0x5B) and `]` (0x5D). This is a conformant subset of § 5.4.4.2. It is chosen because some receivers decode the plaintext as text (ioBroker uses utf-8, pysiaalarm uses ascii-ignore).
  - It returns **uppercase hex ASCII** (§ 5.4.7).
  - The pad source is injectable (constructor or keyword arg) so tests are deterministic. Production uses `secrets`.
- **Decrypt** takes hex, in either case:
  - Non-hex input, odd length, or a byte length that isn't a multiple of 16 raises `AESDecryptionError`.
  - The pad is stripped at the **byte** level before any text decoding, up to and including the first `0x7C`.
  - If there is no `|`, it falls back to stripping up to (but not including) the first `]`. That covers `*NULL`/`*ACK` regions written literally from the § 5.5.2.1/5.5.3.1 templates, as in V6. If there is no `]` either, it raises `AESDecryptionError`.
  - It returns the region content as `bytes`. Callers decode it as windows-1252 with `errors="replace"`.
- PKCS#7 is removed completely. The `encrypt_frame`/`decrypt_frame` aliases follow the new semantics or are removed, with every caller updated.
- Docstrings cite § 5.4.3-5.4.7, replacing the wrong § 5.5.1.10.

### AC2 — `encode_message()` encrypts when asked

- New keyword arguments:
  - `encryption_key: bytes | None = None`;
  - `seq: str | None = None`, an explicit sequence number that bypasses `SequenceTracker`. This is for retries (AC4).
- With `encryption=True`, a missing key raises `AESKeyError`. A marker-only frame must no longer be possible.
- **Plaintext region** = `data_field[1:]` (drop the leading `[`, keep its closing `]`) + extended-data fields + timestamp (§ 5.4.3).
- **Wire message** = `"*SIA-DCS"` + seq + `[R…][L…]#acct` + `[` + hex. There is **no closing `]`** (Decision D1).
- CRC and length are computed on the wire form (§ 5.5.1.2). The existing `_frame()` path is reused.
- **Length limit:** a wire message over 0xFFF (4095) characters raises `SIAProtocolError` in both modes (§ 5.5.1.3, "0" + 3 hex digits). Today `_calculate_length` would emit a malformed 5-character field. Encryption doubles the region, so a long `[V…]` media URL gets there twice as fast.
- **Timestamp:**
  - With `timestamp=None` and `encryption=True`, the current UTC time is used, because it is mandatory (§ 5.5.1.9).
  - The unencrypted path keeps today's behaviour exactly: `None` means no timestamp.
- The unencrypted output is byte-for-byte unchanged. Existing golden frames `frames_*` other than `frames_encrypted_*` must still match.
- **Encrypted supervision:** `make_supervision_message(encryption=True, encryption_key=…)` builds an encrypted Null Message per § 5.5.2.1 (Decision D2):

  ```
  "*NULL"0000<Rrcvr><Lpref>#acct[<hex>
  ```

  - The plaintext region is `pad|` + `]` + timestamp. The `|` is required ("shall appear in all encrypted messages", § 5.4.4.3), even though the template shows only `[<pad>]`.
  - The seq is the literal `0000` and does not consume a `SequenceTracker` number.
  - The timestamp is mandatory.
  - The token, `*NULL` or the `*SIA-DCS…|0000` fallback, is a single module constant (see D2 and AC11).
- `make_supervision_message(encryption=False)` is unchanged: `"SIA-DCS"…[#acct|0000]` (D-86).

### AC3 — Daemon uses the key and encrypts events

- **Key validation:** `SIADaemon.__init__` validates and decodes the key once (`daemon.py:447-448`).
  - Accepted: `re.fullmatch(r"(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{48}|[0-9A-Fa-f]{64})", key.strip())`, then `bytes.fromhex`.
  - Rejected: internal whitespace and a `0x` prefix.
- **When `preset.encryption_enabled` is true and the key is invalid:**
  - The daemon logs an error **without** the key value.
  - It never falls back silently to plaintext.
  - Events short-circuit before `encode_message` and go to FAILED with a new `_event_failure_reason` value, `'config'`. That value gets its own `_event_label_from_sm2` wording, and `EventFailedCtx.last_error='encryption_key'`.
  - Supervision does not send. It sets a visible SM1 state and notification. A silent `return` would leave a stale "OK" label.
- **Defence in depth:** `AESKeyError` is added to the except-lists of `_send_with_retry`, `_build_event_frame` and `_send_supervision`, so an event can never stay PENDING.
- **Event frames:** `_build_event_frame` passes `encryption=self._preset.encryption_enabled, encryption_key=self._encryption_key`. The `encryption=False` override at `daemon.py:1767` is removed.
- **Timestamps:** each encrypted attempt is rebuilt with a fresh UTC timestamp, adjusted by the in-call NAK offset (AC4), so it fits the CSR window. The spec window is +20/-40 s (§ 5.5.1.9), and ioBroker's default is ±10 s. The event's own time stays in the SM2/inspector records. Unencrypted attempts keep today's timestamp logic.
- `_send_supervision` passes the key.

### AC4 — NAK retry and seq handling (§ 5.6.1.2, § 5.5.1.5, F.5)

- **Scope:** § 5.6.1.2 is unconditional. On a NAK, the PE **shall** immediately repeat the message a limited number of times with an updated timestamp. This applies to events **and** supervision, in both modes.
- **Events:**
  - A NAK triggers an immediate re-send within the existing `max_retries` budget, with no 1 s sleep. NAK and timeout attempts share that budget.
  - The frame is rebuilt with an updated timestamp. It comes from the NAK when `parse_nak_timestamp` returns one within ±24 h of local UTC; otherwise the current UTC time is used and a WARN is logged. The NAK is unauthenticated and never encrypted (§ 5.5.3.2).
  - Within one `_send_with_retry` call, the offset `nak_ts - now` is kept and applied to every later attempt of that event. Nothing is persisted across events.
  - An unencrypted frame that had no timestamp gets one on the NAK retry.
- **Seq (D-85 fix):**
  - Every attempt of one event reuses the wire seq of its first attempt: `encode_message(seq=…)`. The first attempt draws from `SequenceTracker`; retries don't.
  - `_sia_seq`, used by traces and notifications, is taken from the built frame, so it equals the wire seq.
- **When the budget is used up:**
  - The event goes to FAILED with reason `'nak'`.
  - T2 `BAD_CSR_RESPONSE` and the notification fire **once**, after the final attempt, not on each intermediate NAK.
  - The SM2 label wording is unchanged.
- **Supervision:**
  - A NAK on the supervision frame triggers up to 2 immediate re-sends with an updated timestamp (same NAK timestamp rules).
  - A strike is only added, via the existing `_handle_supervision_nak` path, if every attempt is NAKed.
  - The `0000` seq of `*NULL` is unchanged.
- **Tests:**
  - Existing tests that pin "NAK → FAILED after one attempt" or "supervision NAK → strike" are updated, not deleted.
  - Level2 tests use a simulator mode that NAKs once and then ACKs. They run encrypted and unencrypted, for an event and for supervision.
  - They assert: the same wire seq on both attempts; no sleep between the two sends; a single T2 when the budget is used up; `retries_left=0` then NAK → FAILED `'nak'` after one attempt; NAK / timeout / NAK / ACK → CONFIRMED.

### AC5 — PHP guard and decode path validate the key

- `deamon_info` guard 5 (`core/class/siaDC09.class.php:188-195`) checks, when encryption is enabled, that the trimmed key is hex of length 32, 48 or 64. This mirrors `desktop/js/siaDC09.js:128-129`.
- The launch-blocking message tells the user what is wrong without echoing the key.
- The decode path in `core/ajax/siaDC09.ajax.php:238` drops the `ctype_xdigit ? key : bin2hex` ASCII fallback. It passes the key only when it is valid hex, so the inspector never decodes with a key the daemon would reject.
- `deamon_start` passing and log redaction (`siaDC09.class.php:244-268`) are unchanged.

### AC6 — Connection test really encrypts

- `run_connection_test` (`siadc09d.py:255-300`) validates `SIA_ENCRYPTION_KEY` with the AC3 rule and passes it to `encode_message`.
- Encryption enabled with a missing or invalid key gives a clear verdict (a new or existing `_TEST_VERDICTS` entry), not a marker-only frame.

### AC7 — Inspector shows what was really sent

- Trace id_tokens (`daemon.py:1327/1364/1395/1427/1873`) and trace `sequence` come from the frame actually built, not from `preset.encryption_enabled` or `_sia_seq`. For `*NULL` the sequence is `0000`.
- `SIAProtocolDecoder.decode(raw_hex, key)`:
  - decrypts `*SIA-DCS` and `*NULL` wire frames with the new cipher;
  - `data_raw` keeps the wire content (hex);
  - the existing `ParsedMessage.data_decrypted` field carries the decrypted region;
  - the account/code/zone/timestamp fields are parsed from the plaintext;
  - `encrypted=True` is reported.
- A wrong key or corrupt ciphertext gives a clean decode error, not a traceback. Neither the key nor the pad appears in the output.
- `_parse_message_fields` accepts `[` + hex with no closing `]`, which is the real-panel form (D1), and still accepts `[hex]`.
- `__main__ --decode` with `SIA_ENCRYPTION_KEY` keeps working (`sia_protocol.py` CLI; PHP `core/ajax/siaDC09.ajax.php:215-245`).

### AC8 — CSR simulator behaves like an encrypting receiver

- **Inbound frames:**
  - For a `*`-marked frame (`*SIA-DCS` or `*NULL`), the simulator decrypts the region with its configured key.
  - It classifies NULL vs ALARM and extracts the account **from the decrypted plaintext**.
  - It recognises the `NULL`/`*NULL` tokens.
  - On a decryption failure it discards the frame silently: no ACK and no NAK (§ 5.6.2.4).
- **Encrypted ACK:** on success it answers with a spec-format encrypted ACK (§ 5.5.3.1):

  ```
  "*ACK"<seq><rpref><lpref>#<acct>[<hex of pad|]_HH:MM:SS,MM-DD-YYYY>
  ```

  CRC and length are computed over the wire form.
- **NAK and DUH:**
  - Both stay unencrypted.
  - The NAK follows the § 5.5.3.2 template: `"NAK"0000R0L0#0[]_HH:MM:SS,MM-DD-YYYY`.
- **NAK-once mode:** the simulator NAKs the first frame, whether event or `*NULL`, and ACKs the retry. The NAK timestamp skew is configurable, and a variant with no timestamp covers the UTC-now fallback (needed for AC4).
- **Timestamp window:** encrypted frames get an optional window check. It is configurable, with a default of +20/-40 s, and NAKs frames that fall outside the window.
- **Buffer:** the UDP receive buffer is at least 4200 bytes, so long encrypted frames aren't truncated.
- `decode_ack_nak` still classifies `*ACK` as ACK. The PE does not need to decrypt the ACK body, because the spec requires no PE-side validation (see D-94).

### AC9 — Tests prove conformance against independent evidence

- **External vectors** (level1, from the table above): our `SIACipher.decrypt` and the `SIAProtocolDecoder` each decrypt and parse V1, V2, V4, V5, V6 and S1. `SIACipher.decrypt` also handles V7, an ACK with no `|`.
  - V1/V2/V6 use the ASCII key bytes as given. V4/V5 use hex-decoded keys.
  - For V1/V2/V6, the CRC and length the tests compute over the body equal the declared ones.
  - This is the only evidence that doesn't come from our own reading of the spec. Every vector is stored with its source URL/commit in a fixture header.
- **Independent oracle** (level1): a test helper built directly on `cryptography` primitives, not on `SIACipher`. It decrypts frames produced by `encode_message` and asserts:
  - the plaintext starts with `pad|`, and the pad avoids `| [ ]`;
  - the total length is a multiple of 16, and the pad is 16 when the content is aligned;
  - the content equals the expected `#acct|code…]…_timestamp`;
  - the wire message has no `]` after the hex;
  - 16, 24 and 32-byte keys are all covered.
  - **Oracle self-check:** it decrypts V1 and V5 correctly.
- **ioBroker port** (level1): a small Python port of ioBroker.sia's decrypt and parse path parses our event frames.
  - That path is: payload regex `\[(.+)`, `aes-{128|192|256}-cbc` with zero IV, pad removed at `indexOf('|')`, then `"(.+?)?\](\[(.*?)\])?(_(.+)){0,1}"`.
  - ioBroker cannot parse `*NULL` at all: its token switch only handles `SIA-DCS`/`ADM-CID`. The port's test therefore covers events only and records this limitation.
- **Deterministic vector:** a fixed key and an injected pad give a fixed hex string.
  - It replaces `tests/fixtures/golden/frames_encrypted_alarm.hex`, which is PKCS#7-based (ciphertext `E5BD0B70…`).
  - `tests/level1/test_harness.py` is updated.
  - The vector's origin is documented. It is a regression guard only, not evidence.
- `tests/level1/test_sia_crypto.py` (39 tests, PKCS#7-based) is rewritten for the new semantics, not deleted wholesale. Round-trip, key-length, bad-input and pad-alphabet tests are kept.
- **Other tests** that depended on PKCS#7 or marker-only frames are updated. Known files:
  - `test_protocol_decode.py`, `test_csr_simulator.py`, `test_connection_test.py`;
  - level2 `test_sm2_frame_building.py` and `test_sm1_extended_suite.py`;
  - level3 e2e;
  - `tests/conftest.py:93` (`preset_encrypted`) and `:201` (`test_cipher`).
- **Leak test:** during an encrypted send, the test captures daemon logs, inspector traces, the connection-test output and the reprs of `config` and key errors. It checks that the key hex never appears.
- **Boundary test:** the length guard is checked at 4095 (OK) and 4096 (raises), encrypted and plain.
- **Regressions:** compare against the known baseline, not against zero failures:
  - level1: 2 failures
  - level2: 6 failures
  - level2_5: 1 failure

  No new failures are allowed.

### AC10 — Docs tell the truth

- The "encryption not implemented" limitation is replaced in:
  - `README.md:32`
  - `docs/admin-guide.md:149`
  - `docs/developer-guide.md:135`
  - `docs/fr_FR/index.md:236`
  - `docs/fr_FR/changelog.md` (new entry)
- The replacement text depends on AC11:
  - if AC11 passes: "implemented and validated against <receiver>";
  - otherwise: "implemented to DC-09-2021 § 5.4 and checked against real-panel encrypted frames, **not yet validated against a real receiver**".
- The docs say explicitly that the key is entered as **hex** (32/48/64 digits = 128/192/256 bits). Some panels, Ajax for example, use the key text's ASCII bytes instead, and ASCII-key entry is not supported yet (D-93).
- Follow the public-docs editorial rules: early-tester framing, no IMA, a single French changelog.
- `daemon-design.md` is updated where it differs from the implementation, notably the missing `]` after the hex (D1) and the NAK retry.
- D-81 and D-85 in `deferred-work.md` are marked resolved, with a pointer to this story. D-81 is marked as partially resolved while AC11 is open.

### AC11 — Live validation against a real receiver (later session)

- Herve's call on 2026-09-27: live tests happen in a **separate session after implementation**. The dev session delivers AC1-AC10 and moves the story to review with AC11 open.
- Whether the receiver supports encryption, and which key form it uses, is still unknown.
- Target: the real receiver `192.168.100.15:10002` over TCP, account `001234`, through `test-jeedom.lehoux.net`. Code arrives by `git pull`, so push first.
- **Validate in this order,** so that a failure can be attributed to the right cause:
  1. an encrypted **event**;
  2. then an encrypted supervision `*NULL`.
- **Record explicitly:**
  - whether the receiver ACKs an event with no `]` after the hex;
  - whether it ACKs `*NULL`, and if not, switch the D2 constant to the `*SIA-DCS…|0000` fallback and retry;
  - whether its key is hex or ASCII (D-93);
  - the shape of its `*ACK`.
- If the receiver has no encryption support or no key is available, mark the task **BLOCKED**:
  - do not claim validation;
  - never use the simulator as a substitute.
- Validation goes through the Jeedom UI or API, not reflection.

## Decisions (reviewed with Herve 2026-09-27; D1 revised after the challenge the same day)

- **D1 — No `]` after the hex.**
  - This reverses the first call ("close"), which relied on the § 5.4.7 and B.4 examples showing `[<hex>]`.
  - The challenge found that those examples carry wrong CRC and length values, like every example frame in the spec.
  - The § 5.4.3 text says encryption "ends just before the terminating `<CR>`". Read literally, nothing unencrypted comes after the hex.
  - Every third-party frame found omits the `]`: real Ajax hubs (V1/V2), the ioBroker test panel, DC09Gen (V4), the `*NULL` generator (V6), Swissdotnet's library, and ioBroker's own `*ACK`. The Ajax CRCs and lengths only match without it.
  - The decoder and simulator accept both forms. The emitted form lives in one constant, so reverting is one line if AC11 shows the receiver wants `]`.
- **D2 — Encrypted supervision uses `"*NULL"`.**
  - § 5.5.2: the PE "shall transmit the Null Message each time the supervision interval elapses". § 5.5.2.1 defines `NULL`/`*NULL`/`XNM`/`*XNM`. An event frame carrying code `0000` is not a Null Message.
  - The plaintext is `pad|]_ts`, per § 5.4.4.3. Swissdotnet also includes the `|`, while the V6 generator omits it.
  - Risk: ioBroker cannot parse `*NULL`, and some real receivers may not either. The token is therefore a single constant, with the `*SIA-DCS…[pad|#acct|0000]_ts` fallback, and AC11 checks it after the event.
  - Unencrypted supervision keeps `"SIA-DCS"…[#acct|0000]`, as validated in the field (D-86).
- **D3 — The retry timestamp is UTC "now" plus the in-call NAK offset**, not the event time.
  - § 5.5.1.9: the timestamp "indicates when the event was queued for transmission". ioBroker rejects anything more than 10 s out.
  - The event time stays in the SM2 state and the inspector.
- **D4 — Keys are hex only, in this story.**
  - § 5.4.5.3 discourages ASCII-phrase keys.
  - Real Ajax hubs use ASCII key bytes, though, and a 32-character ASCII key that happens to be all hex would be read as AES-128 here and AES-256 there. That would show up as silence (§ 5.6.2.4).
  - An ASCII-key option is D-93.
  - When encryption is on and every attempt times out, the FAILED log line mentions a possible key or format mismatch.

## Out of Scope

- Switching **unencrypted** supervision to `"NULL"` (D-86).
- `XNM`/`*XNM`.
- Persisting a clock offset across events.
- ASCII-key entry (D-93).
- PE-side validation of the `*ACK`: decrypting it and checking its seq, account and timestamp (D-94).
- Restarting the daemon when the encryption settings change, and `[ ]` characters in `media_url` (D-95).
- The connection test retrying after a NAK (D-95).
- Key storage and CLI exposure (ADR-07).
- `[K…]` key change and `[A…]` authentication hash.

## Tasks / Subtasks

- [x] **Task 1: rewrite `SIACipher` (AC1, AC9)**
  - [x] 1.1 Add the external-vector fixtures and the independent oracle helper. Write the new `test_sia_crypto.py` tests first (TDD), including V1/V2/V4/V5/V6.
  - [x] 1.2 Implement: key sizes, front pad + `|`, hex output, byte-level pad strip with the `]` fallback, injectable pad source.
  - [x] 1.3 Remove PKCS#7. Update or remove the aliases and every caller (`grep -rn "encrypt_frame\|decrypt_frame\|SIACipher" resources/ tests/`).
- [x] **Task 2: `encode_message` encryption (AC2, AC9)**
  - [x] 2.1 Tests: oracle decryption with 16/24/32-byte keys; with and without zone; with `[V…]`; with and without a timestamp; no `]` after the hex; explicit `seq=`; the length guard.
  - [x] 2.2 Implement the region split, the `[`+hex wire form, the mandatory timestamp, the missing-key error, `seq=` and the 0xFFF guard.
  - [x] 2.3 Replace the golden `frames_encrypted_alarm.hex`. Update `test_harness.py`.
  - [x] 2.4 ioBroker port helper, and its test on event frames.
  - [x] 2.5 Encrypted supervision: `"*NULL"0000…` with plaintext `pad|]_ts`, and the token constant with its fallback.
- [x] **Task 3: daemon wiring (AC3, AC4, AC7)**
  - [x] 3.1 Key validation in `__init__`; the `'config'` failure reason and label; the SM1 state and notification; `AESKeyError` in the except-lists.
  - [x] 3.2 `_build_event_frame`: remove the override, pass the key, apply fresh UTC + offset when encrypting, pass the explicit seq.
  - [x] 3.3 `_send_supervision`: pass the key; NAK retry (up to 2) before adding a strike.
  - [x] 3.4 `_send_with_retry`: NAK → immediate retry; NAK timestamp sanity check and offset; the same seq across attempts; a single T2 when the budget is used up. Update the tests that pin the old behaviour.
  - [x] 3.5 Take the trace id_token and sequence from the built frame.
- [x] **Task 4: decoder (AC7)**
  - [x] 4.1 `_parse_message_fields`: accept `[hex` with no `]` (and `[hex]`).
  - [x] 4.2 `decode()` with the new cipher; `data_decrypted`; clean errors; `--decode` CLI.
- [x] **Task 5: simulator (AC8)**
  - [x] 5.1 Inbound decrypt; `*NULL` recognition; classification and account from the plaintext; silent discard.
  - [x] 5.2 Spec-format `*ACK`; spec NAK template with timestamp; buffer ≥ 4200.
  - [x] 5.3 NAK-once mode (skew and no-timestamp variants); optional timestamp window.
- [x] **Task 6: PHP and connection test (AC5, AC6)**
  - [x] 6.1 Guard 5 key-format check; remove the `bin2hex` fallback in the decode ajax; run `php -l`.
  - [x] 6.2 `run_connection_test`: validate the key and add a verdict for a bad or missing key.
- [x] **Task 7: test suite sweep (AC9)**
  - [x] 7.1 Update the dependent level1/level2/level3 tests and the conftest fixtures.
  - [x] 7.2 Add the key-leak test and the boundary test.
  - [x] 7.3 Run level1/level2/level2_5 and compare against the baseline (2/6/1). Run pylint.
- [ ] **Task 8: live validation (AC11)**: later session. **Open by design** (Herve, 2026-09-27): the story goes to review with AC11 open.
- [x] **Task 9: docs and tracking (AC10)**: update the README and docs, `daemon-design.md`, D-81/D-85 (resolved or partial), D-93..D-95, and the memory note.

### Review Findings

Code review 2026-09-28, scoped to Group 1 (core implementation: `sia_crypto.py`, `sia_protocol.py`, `daemon.py`, `siadc09d.py`, `csr_simulator.py`, `error_handler.py`, `messages.py`, `__init__.py`). Groups 2-4 (PHP/docs/tracking, level1 tests, level2/level3 tests + fixtures) not yet reviewed — follow-up runs needed.

- [x] [Review][Patch] `_decrypt_region()` decodes strictly as ASCII behind a printable-ASCII gate, contradicting AC1's "callers decode it as windows-1252 with `errors="replace"`" [resources/siadc09d/sia_protocol.py:955-976] — also affects AC7 (inspector) and AC8 (simulator classification, via `decode()`). **Fixed 2026-09-28**: now decodes as windows-1252 with `errors='replace'`; sanity check kept to `]` presence + trailing timestamp regex (charset-independent). `_PRINTABLE_ASCII` removed (was unused elsewhere). level1 tests unaffected (`test_protocol_decode.py` already expected windows-1252).
- [x] [Review][Patch] `_trace_header()` returns `"sequence"` as `str` on the success path (parsed from the wire) but as `int` on the fallback/default path, an inconsistent type in the JSON trace/notification payload [resources/siadc09d/daemon.py:1026-1043]. **Fixed 2026-09-28**: return type narrowed to `dict[str, str]`, `seq` cast with `str(seq)` on both paths. Updated `test_nak_retry_and_key_config.py::test_trace_header_falls_back_to_defaults` (was pinning the old `int` fallback).
- [x] [Review][Patch] `_fail_event_config()` reports `sia_seq=self._sia_seq` in `EventFailedCtx`, but nothing was built or sent on this path (encryption config error) — the value is stale from whatever the previous event set [resources/siadc09d/daemon.py:1866-1899]. **Reclassified to defer 2026-09-28, not fixed**: found on inspection that the exact same pattern (`sia_seq=self._sia_seq` reported when `attempts_made=0`, nothing sent) already exists at `daemon.py:2253` for the pre-existing NO_NETWORK-dequeue failure path — this is a shared, pre-existing convention, not something story 1-5 introduced in isolation. Fixing `_fail_event_config` alone would make it inconsistent with that other path instead of consistent with it. A correct fix needs a decision on what `sia_seq` should mean when zero attempts were made (e.g. widen `EventFailedCtx.sia_seq` to `int | None` and fix both call sites together), which is beyond this diff. Filed as D-102 in `deferred-work.md`.
- [x] [Review][Patch] `_enter_encryption_config_error()` uses a local `from . import messages` import instead of module scope, with no circular-import reason found [resources/siadc09d/daemon.py:963-973]. **Fixed 2026-09-28**: `ENCRYPTION_KEY_INVALID`/`ENCRYPTION_KEY_INVALID_TITLE` added to the existing top-level `from .messages import (...)` block, matching every other message constant's style; the local import and `messages.` prefix removed.
- [x] [Review][Defer] Three independent `"encryption_key"` sentinel constants (`ENCRYPTION_KEY_LOGICAL_ID`, `EVENT_FAILED_ENCRYPTION_KEY`, `_FAIL_ENCRYPTION_KEY`) with no shared import — a rename/typo in one wouldn't be caught by the others [resources/siadc09d/daemon.py:209, resources/siadc09d/error_handler.py:132, resources/siadc09d/siadc09d.py:57] — deferred, pre-existing pattern in the codebase.
- [x] [Review][Defer] `SIACipher.decrypt()`'s own sanity check is minimal (presence of `|` or `]`); the sole current caller (`_decrypt_region`) adds the real validation, so a future direct caller would not be protected [resources/siadc09d/sia_crypto.py:166-192] — deferred, no current caller is actually exposed.
- [x] [Review][Defer] `csr_simulator.py`'s `_generate_ack_frame()` declares `receiver_prefix="R0"`/`account_prefix="L0"` defaults that are unreachable on the encrypted-ACK branch, since its only caller always overrides them there [resources/siadc09d/csr_simulator.py:655-696] — deferred, test-tool only.
- [x] [Review][Defer] `_generate_ack_frame()` falls back to the preset's own account when the parsed inbound account is falsy, which could echo the wrong account for a malformed/empty account field [resources/siadc09d/csr_simulator.py:655-696] — deferred, test-tool only, and an empty account is already a spec violation by the sender.
- [x] [Review][Defer] `_parse_encrypted_message()` can default-classify a decrypted region with no `|` separator as `'ALARM'`, if it happens to pass `_decrypt_region`'s ASCII+`]`+timestamp-regex gates [resources/siadc09d/csr_simulator.py:594-650] — deferred, requires an improbable coincidence and is test-tool only.
- [x] [Review][Defer] `make_supervision_message()`'s encrypted `*NULL` branch silently ignores any explicit `seq=` argument (always hardcodes `NULL_MESSAGE_SEQ`) — harmless today since the one caller's retried value already is `"0000"`, but a latent trap for a future caller that assumes `seq=` is honored [resources/siadc09d/sia_protocol.py:308-342] — deferred, no current caller exposed.

Code review 2026-09-28, scoped to Group 2 (PHP + docs + tracking: `core/class/siaDC09.class.php`, `core/ajax/siaDC09.ajax.php`, `core/i18n/fr_FR.json`, `README.md`, `docs/admin-guide.md`, `docs/developer-guide.md`, `docs/fr_FR/index.md`, `docs/fr_FR/changelog.md`, `internal-docs/design/daemon-design.md`, plus the tracking files touched by dev-story/code-review bookkeeping). Groups 3-4 (level1 tests, level2/level3 tests + fixtures) not yet reviewed — follow-up runs needed.

- [x] [Review][Patch] The decode AJAX handler silently fell through to an unencrypted decode with no error when the stored `encryption_key` was non-empty but rejected by `isValidEncryptionKey()` (malformed hex, or an ASCII-passphrase key per D-93) [core/ajax/siaDC09.ajax.php:234-240] — unlike guard 5's specific message for the same condition on daemon launch. **Fixed 2026-09-28**: added an explicit `ajax::error()` branch before the decode, worded "Clé de chiffrement stockée invalide — reconfigurez-la (étape 1)"; added the string to `fr_FR.json`.
- [x] [Review][Patch] `docs/fr_FR/index.md`'s encryption-key bullet said only "le démon refuse de démarrer et rien n'est envoyé," missing the "already running" case that `docs/admin-guide.md`'s equivalent English bullet already covers ("a daemon already running sends nothing") — read in isolation this looked like a doc-vs-daemon-design.md contradiction (a fresh launch is blocked by the PHP guard; a daemon already running instead enters `SM1State.CONFIG_ERROR` and just stops sending — two different, both-true layers, admin-guide.md already distinguishes them, fr_FR/index.md didn't). **Fixed 2026-09-28**: added the matching clause to `docs/fr_FR/index.md` for parity with the English doc.
- [x] [Review][Defer] AES key passed to the decode/test-connection helper subprocess via an env var on the `exec()` command line — readable via `/proc/<pid>/environ` while the short-lived subprocess runs. Pre-existing pattern predating this diff; D-95(d) only tracks the long-running daemon's `--encryption-key` CLI-argv exposure, not this env-var path. Filed as D-103.
- [x] [Review][Defer] `isValidEncryptionKey()`'s docblock claims "same rule as" Python's `parse_hex_key()`, with no shared constant or cross-language test enforcing that equivalence [core/class/siaDC09.class.php:381]. Filed as D-104.
- [x] [Review][Defer] The French guard-5 message ("32, 48 ou 64 caractères hexadécimaux attendus") is hand-written, not generated from `ENCRYPTION_KEY_HEX_LENGTHS` — a future change to the accepted lengths could desync the message from the actual check. Consistent with the file's existing pattern elsewhere (e.g. the account-number message is equally hand-written). Filed as D-104 (same item, message + docblock equivalence share one root cause).
- [x] [Review][Defer] `testConnection`'s AJAX action builds `SIA_ENCRYPTION_KEY` from the raw stored key with no `isValidEncryptionKey()` gate at all [core/ajax/siaDC09.ajax.php:36-61], unlike the decode handler which now has one. Pre-existing code, not touched by this diff. Verified low-risk: `siadc09d.py --test-only`'s own `parse_hex_key()` call already catches a malformed key and returns a clean `encryption_key` verdict (AC6) — no insecure fallback, just an inconsistency in which AJAX action applies the guard. Filed as D-105.
- [x] [Review][Defer] `getConfiguration('encryption_key')` returning a non-string (a corrupted config row) isn't defended against before reaching `isValidEncryptionKey(?string $key)`. Consistent with every other config read in the same file trusting `getConfiguration()`'s return shape; not a risk unique to this diff. No separate filing — covered by the general "trust `getConfiguration()`" convention, not worth a dedicated D-number.

Code review 2026-09-28, scoped to Group 3 (level1 tests: `test_sia_crypto.py`, `test_sia_protocol.py`, `test_protocol_decode.py`, `test_csr_simulator.py`, `test_connection_test.py`, plus the new `_dc09_crypto_oracle.py`, `test_sia_protocol_encryption.py`, `test_csr_simulator_encryption.py`, `test_php_encryption_key_guard.py`). Group 4 (level2/level3 tests + fixtures) not yet reviewed — a follow-up run needed. This pass reviewed test quality/coverage, not the production code (Groups 1-2).

- [x] [Review][Patch] `test_length_guard_at_0xfff`'s encrypted case only asserted a loose 32-char window (`last_ok > MAX_MESSAGE_LENGTH - 32`), not the single-character-precise boundary its docstring and Task 7.2 promised — real AES-CBC ciphertext hex only grows in 32-char (16-byte block) steps, so growing plaintext one byte at a time structurally can't land exactly on 4095 [tests/level1/test_sia_protocol_encryption.py:148-172]. Found independently by all three review layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor) — the strongest-converged finding of this pass. **Fixed 2026-09-28**: corrected the docstring to stop overclaiming precision it structurally can't have, and added `test_length_boundary_exact_encrypted`, which stubs `SIACipher.encrypt` (via `monkeypatch`) to return a hex string exactly as long as its input — bypassing AES block quantization entirely — so the guard's own arithmetic is checked at single-character precision for the encrypted path too, matching `test_length_boundary_exact_plain`.
- [x] [Review][Patch] `test_decrypt_error_never_contains_key_or_pad`'s docstring claimed the error text carries "no key and no plaintext," but only the key was actually asserted absent [tests/level1/test_sia_crypto.py:301-308]. **Fixed 2026-09-28**: added an assertion that the decrypted garbage (computed independently via the oracle's `oracle_aes_decrypt`, since `decrypt()` never returns it — it raised) is also absent from the error text.
- [x] [Review][Patch] `test_decrypt_with_wrong_key_fails_cleanly` used a weak either/or assertion ("raises, or returns something different") that can't distinguish a correctly-hardened decrypt path from a subtly broken one [tests/level1/test_sia_crypto.py:287-292]. Verified empirically the outcome is genuinely non-deterministic with the fixture's production random pad (≈1/3 return garbage instead of raising, over 2000 runs) — the either/or wasn't a shortcut, the test as originally written needed it. **Fixed 2026-09-28**: switched to a fixed pad source (`_fixed_pad`, already defined in the file) to make the outcome deterministic, then asserted the single resulting branch (`AESDecryptionError`, with its exact message) precisely instead.
- [x] [Review][Patch] `test_undecryptable_frame_discarded_silently` only covered an encrypted alarm event with a wrong/missing key, not an encrypted `*NULL` supervision frame with the same condition [tests/level1/test_csr_simulator_encryption.py:122-135]. **Fixed 2026-09-28**: parametrized over both `_event()` and `_null()` (both helpers already existed in the file), so § 5.6.2.4's silent-discard guarantee is now checked for both frame types.
- [x] [Review][Patch] `test_default_pad_is_random_and_never_uses_delimiters`'s `assert len(set(pads)) > 1` over 50 samples would still pass for a badly non-uniform generator producing only two distinct values, despite the docstring's "random" claim [tests/level1/test_sia_crypto.py:176-192]. **Fixed 2026-09-28**: tightened to `>= 45` (measured 50/50 distinct in practice with the real `secrets`-based generator; confirmed stable across repeated runs) — a meaningfully stronger bar without becoming flaky.
- [x] [Review][Defer] The "independent" `iobroker_parse_event` oracle helper is a hand-written regex reimplementation of ioBroker.sia's TypeScript parser, not an import of the actual third-party library — it can encode the same misunderstanding of the source it's meant to independently check. The AES-level independence (raw `cryptography` primitives, never `SIACipher`) is real and was separately confirmed by the Acceptance Auditor; this finding is specifically about the one frame-string-parsing helper. Filed as D-106.
- [x] [Review][Defer] The external test vectors (V1/V2/V4/V5/V6/V7/S1) are manually transcribed hex/plaintext with no automated fetch or checksum against their sources; a transcription error would make the two tests that check against this same hand-typed ground truth agree on a wrong answer rather than catching each other's mistake. Filed as D-106 (same root cause: "independent" data entry isn't independently verified either).
- [x] [Review][Defer] `KEY_192`/`KEY_256` test keys are built by repeating an 8-byte pattern 3-4 times rather than distinct key material; low real risk since AES's key schedule doesn't depend on key "entropy" for correctness testing, but worth tidying. Filed as D-107.
- [x] [Review][Defer] The widely-reused 32-hex-digit test key (`"0123456789ABCDEF0123456789ABCDEF"`, hardcoded across 6+ test files) is syntactically indistinguishable from a real production AES-128 key — a copy-paste-into-real-config risk with no obviously-fake marker. Fixing it well means touching every file that uses it, which is more test churn than this review pass should do unilaterally; needs a naming convention decision (e.g. an `AAAA…`-style obviously-fake pattern, or a `TEST_ONLY_` prefix) rather than a silent one-off rename. Filed as D-107 (same item, test key hygiene).
- [x] [Review][Defer] `test_run_connection_test_encryption_bad_key_blocks_send` asserts the exact French UI string `"clé AES" in out["detail"]` inside a test that's ostensibly about daemon-side key-guard logic, coupling it to exact translated wording that an unrelated copy edit could break. Filed as D-108.
- [x] [Review][Defer] `test_php_key_rule_matches_parse_hex_key` — the one test guaranteeing PHP's `isValidEncryptionKey()` and Python's `parse_hex_key()` can't drift apart — is entirely skipped via `@pytest.mark.skipif(shutil.which("php") is None, ...)`. Low practical risk in this project specifically (no Python CI job exists per the developer guide; `php -l` already assumes a local PHP install; a Jeedom-plugin dev machine realistically always has PHP), but the safety net is silent, not loud, if that ever stops being true. Filed as D-108 (same item, cross-language test fragility).
- [x] [Review][Defer] `SIACipher.decrypt()`'s final `AESDecryptionError` branch (neither `|` nor `]` in the decrypted plaintext) has no dedicated test with a correct key. `csr_simulator._parse_encrypted_message()` also has no test for the case where a wrong-key decrypt succeeds (doesn't raise) and happens to contain a `|` or `]`, so it isn't classified as DISCARD. Both require deliberately searching for a low-probability ciphertext/key collision to construct; genuine defense-in-depth gaps, not blocking. Filed as D-109.
- [x] [Review][Defer] `isValidEncryptionKey(null)` (PHP's actual `?string` null, not just an empty string) isn't tested against Python's `parse_hex_key(None)` for equivalence. Filed as D-109 (same item, PHP/Python key-guard cross-check completeness).

Code review 2026-09-28, scoped to Group 4 (the last group: level2 async daemon tests — `test_daemon_integration.py`, `test_sm2_extended_coverage.py`, `test_supervision_loop_integration.py`, the new `test_nak_retry_and_key_config.py` — and level3 fixtures/e2e — `conftest.py`, `test_full_workflow_e2e.py`, `test_supervision_e2e.py` — plus the golden `frames_encrypted_alarm.hex` fixture and `tests/harness/run_harness.py`). **This closes out the 4-group review of the full story 1-5 diff.**

- [x] [Review][Patch] AC4's "no sleep between NAK retries" and "encrypted case exhausts the same way" assertions were verified for the event path (`TestEventNakRetry`) but missing for the supervision path (`TestSupervisionNakRetry`) — no test patched/asserted on `asyncio.sleep` there, and only the unencrypted exhaustion + the encrypted heal-on-first-retry cases were covered, not encrypted exhaustion [tests/level2/test_nak_retry_and_key_config.py:281-327]. **Fixed 2026-09-28**: added `with patch("asyncio.sleep") as mock_sleep: ... mock_sleep.assert_not_called()` to both `TestSupervisionNakRetry` tests, and parametrized `test_nak_every_resend_single_strike` over `encrypted` (was unencrypted-only), asserting every attempt stays `*NULL`/`0000` even when NAKed.
- [x] [Review][Patch] `_nak_offset`'s ±24 h sanity boundary (D3) had no test at the exact edge — only a 1 h skew (well inside, heals) and a 2-day skew (well outside, ignored) were exercised [tests/level2/test_nak_retry_and_key_config.py:149-186]. **Fixed 2026-09-28**: added `test_nak_offset_24h_boundary_precise`, calling `daemon._nak_offset()` directly with NAK frames built at 24h−1s and 24h+1s skew (via the simulator's own `_generate_nak_frame`), isolating the boundary check from a full send/retry round-trip. Since `_nak_offset` is the single shared implementation behind both the event and supervision NAK paths, this one direct test covers the boundary for both callers.
- [x] [Review][Defer] Hardcoded AES key `0123456789ABCDEF0123456789ABCDEF` duplicated across this group's files too (the new `test_nak_retry_and_key_config.py`, the golden `.hex` fixture's header comment, and the level3 E2E key constant), extending the group-3 finding (D-107) rather than a new root cause. No separate filing.
- [x] [Review][Defer] Several test-hygiene notes, none blocking: tests reach 3 attributes deep into private internals to seed sequence state (`daemon._sia_builder._sequence_tracker._seq_map[...]`); the `_wire()` helper calls `sim._build_response()` synchronously with no comment establishing it isn't a coroutine; a throwaway `CSRSimulator` is built just to call its private `_generate_nak_frame()`; a log-message substring check (`"more than 24 h"`) is brittle to copy edits; `TestKeyNeverLeaks` calls `_wire()` twice on the same daemon without an explicit reset between calls (works today, undocumented as intentional). Filed as D-110.
- [x] [Review][Defer] `_daemon(encrypted=True)` without an explicit `config=` bypasses config parsing entirely (`daemon._encryption_key = _KEY` set directly), and most `TestEventNakRetry`/`TestTraceHeader` setups use that shortcut — only `TestInvalidKeyBlocksSending` actually exercises the real `BaseConfig` → `parse_hex_key()` path. This is a reasonable test-isolation choice (NAK-retry mechanics vs. key-parsing mechanics are different concerns, and the integration point is covered at least once), not a true gap, but the split isn't documented anywhere a reader would notice it. Filed as D-111.
- [x] [Review][Defer] `test_happy_path_encrypted` and `TestKeyNeverLeaks` assert `sent_tokens == {"*NULL", "*SIA-DCS"}` — a *set* of distinct id_tokens, which can't detect duplicate/spurious sends of the same token (e.g. three supervision frames instead of one), and doesn't inspect the wire bytes for actual AES-ciphertext structure (hex shape, no `]` after it) — "both frames go out encrypted" is established only indirectly, via the simulator's own decrypt-or-discard behavior and SM1/SM2 reaching HEALTHY/CONFIRMED. A reasonable end-to-end proxy, but not a direct structural assertion. Filed as D-112.
- [x] [Review][Defer] No script or test in this group's files cross-checks the golden fixture's own header-comment claims (stated CRC, stated ciphertext hex, stated plaintext) against its actual hex bytes — though the test-relevant data (the raw bytes themselves) IS already verified against production `encode_message()` output by `test_deterministic_golden_vector` in group 3 (`tests/level1/test_sia_protocol_encryption.py`), so this is specifically about the human-readable comments drifting, not the bytes that tests actually check. Low priority. Filed as D-112 (same item, golden-fixture documentation drift).
- [x] [Review][Defer] `run_harness.py` folds "correctly discarded because no key" (§ 5.6.2.4) and "malformed frame" into the same `timeout_expected=True` bucket for PASS purposes — a harness run against a genuinely broken decrypt path that times out for the wrong reason (e.g. a hung transport) would look identical to "working as designed." Filed as D-113.
- [x] [Review][Defer] `tests/level3/conftest.py`'s minimal `BaseConfig` for the encrypted E2E daemon only registers `--encryption-key`, not the full argument set `siadc09d.py` registers in production. Verified low-risk: `SIADaemon.__init__` reads the other config-backed fields (`receiver_prefix`, `account_prefix`) via `getattr(config, name, default)`, which returns the same default a genuinely-unset value would — no silent wrong value, just a narrower stub than production's real wiring. No filing needed.
- [x] [Review][Dismiss] `csr_sim` mutating its `preset` in place with no explicit teardown, flagged as a possible cross-test leak — verified `@pytest_asyncio.fixture` defaults to function scope, so each test gets its own fresh simulator instance; not a real risk.
- [x] [Review][Dismiss] `TestTraceHeader` setting `daemon._last_sent_frame` directly instead of through a real send, flagged as not exercising production's own assignment of that attribute — this is a standard, legitimate unit-test-in-isolation pattern for `_trace_header()`'s own parsing/fallback logic; the real assignment is exercised indirectly by every other test that sends a real frame and checks the resulting `_sia_seq`/trace payload.
- [x] [Review][Dismiss] The golden fixture's "front pad 'p' injected for determinism" comment, flagged as suspicious/"reverse-engineered from the implementation" — verified this is necessary and sound: production's real pad is random (`secrets`-based), so any golden fixture of an encrypted frame has to fix the pad deliberately to get reproducible ciphertext bytes at all. Not a red flag.

**Deferred items not fixed in this review, listed above but requiring more than a follow-up run to close:** concurrent/racing NAK-retry calls sharing daemon state (event vs. supervision paths), CONFIG_ERROR transitioning mid-run rather than only at startup, a mixed NAK-then-timeout sequence where the deciding failure is the timeout not the NAK, and the notified-once flag across multiple supervision cycles — all genuine gaps, all requiring new test infrastructure (concurrency harness, or exercising a key-rotation path the current daemon design doesn't really have) rather than a small patch. Filed as D-114.

## Dev Notes

### Files to change: current state and what must be preserved

- **`resources/siadc09d/sia_crypto.py`**
  - Today: `SIACipher(key)` accepts exactly 16 bytes (`KEY_SIZE = 16`), with `IV = b'\x00'*16`. `encrypt()` pads with PKCS#7 and returns raw bytes.
  - Errors: `AESKeyError`, `AESEncryptionError`, `AESDecryptionError`.
  - Preserve: the class and exception names, which are imported in `daemon.py`, `sia_protocol.py` and `csr_simulator.py`.
  - `cryptography` is pinned in `plugin_info/packages.json`. It is 43.0.3 there but 42.0.8 in the local venv; both support AES-192/256 CBC.
- **`resources/siadc09d/sia_protocol.py`**
  - `encode_message` is at 192-261. It builds `id_token + seq + account_id_str + data_field + extended_data_field [+ timestamp_str]`.
  - `_format_timestamp(None)` returns `None`.
  - `SequenceTracker.next_seq` (238) increments on every call.
  - `_calculate_length` (334) has no overflow guard.
  - `ParsedMessage.data_decrypted` already exists (842, 907-921).
  - `_parse_message_fields` is around 1009.
  - Preserve the unencrypted output byte for byte.
- **`resources/siadc09d/daemon.py`**
  - Key: 447-448.
  - `_send_supervision`: 926 (959/960).
  - `_handle_supervision_nak`: 1049-1112.
  - Traces: 1327/1364/1395/1427/1873.
  - `_send_with_retry`: 1441, with `_sia_seq` at 1474. An event NAK fires T2 at 1527-1537.
  - `_build_event_frame`: around 1706, with the override at 1767.
  - This file is the merge hot-spot, so keep the changes surgical.
- **`resources/siadc09d/siadc09d.py`**: `run_connection_test` 255-300, CLI 370-410, `_TEST_VERDICTS` 73-117.
- **`resources/siadc09d/csr_simulator.py`**: `_parse_received_message`, `_decide_response`, `_generate_ack_frame` (518-560), `_generate_nak_frame`, `recvfrom(1024)`.
- **`core/class/siaDC09.class.php`**: guard 5 is at 188-195; `deamon_start` is at 244-268.
- **`core/ajax/siaDC09.ajax.php`**: the connection test is at 30-65 (env var `SIA_ENCRYPTION_KEY`); decode is at 215-245, with the `bin2hex` fallback at 238.

### Byte-level worked example (orientation, not a vector)

- The region `#1234|BA 001]_12:00:00,09-27-2026` is 33 bytes. With the `|` it is 34, so `pad_len` = 14.
- The encrypted input is 48 bytes, giving 96 hex characters.
- Wire: `"*SIA-DCS"0001L0#1234[<96 hex>`, 118 characters, so the length field is `0076`.

### Testing standards

- Put the oracle, the ioBroker port and the external vectors in a level1 helper module (for example `tests/level1/_dc09_crypto_oracle.py`) so level2 can reuse them.
- When a live run shows a gap, write the level1/level2 test before retrying live.

### References

- Spec § 5.4.3-5.4.7, § 5.5.1.2/3/5/9, § 5.5.2, § 5.5.2.1, § 5.5.3.1, § 5.5.3.2, § 5.6.1.2, § 5.6.2.1, § 5.6.2.4, F.5.
- `internal-docs/design/daemon-design.md:146-162, 229-236, 346-374`.
- `_bmad-output/planning-artifacts/architecture.md` ADR-07.
- `_bmad-output/planning-artifacts/epics.md` Story 1.2 (superseded) and Story 1.5.
- pysiaalarm: https://github.com/eavanvalkenburg/pysiaalarm (commits fc0fcfb, 894f8d6, be4301b).
- ioBroker.sia: https://github.com/schmupu/ioBroker.sia, and the fork https://github.com/hlehoux2021/ioBroker.sia, `src/lib/sia.ts`.
- Swissdotnet: https://github.com/Swissdotnet/sia-dc-09-library.
- DC09Gen: http://s545463982.onlinehome.us/DC09Gen/.

## Dev Agent Record

### Agent Model Used

Claude Opus 5.5 (`eu.anthropic.claude-opus-5-5`), Claude Code, 2026-09-27 → 2026-09-28.

### Debug Log References

- Baseline re-measured on a clean `c151d69` worktree (`/tmp/baseline-wt`). Failures were level1 0, level2 5, level2_5 1, level3 2. The "2/6/1" in Task 7.3 was stale: D-84 had already removed the two level1 csr_provider failures.
- The first level3 fixture attempt patched `sys.argv` with `--encryption-key`. SIADaemon's default `BaseConfig` rejected it (SystemExit 2) and the run hung. Fixed by passing a parsed `BaseConfig` through `config=`, the same pattern as the level2 `_key_config`.

### Completion Notes List

- **AC1-AC10 delivered; AC11 (Task 8) open by design.** Nothing here claims that encryption was validated against a real receiver.
- **Final results vs. baseline:**

  | Suite | Result | Failures |
  |---|---|---|
  | level1 | 1331 passed | 0 |
  | level2 | 374 passed | 5, the baseline set |
  | level2_5 | 79 passed | 1, baseline |
  | level3 | 26 passed | 1, baseline `test_alarm_retry_exhaustion_sm2_failed` |

  `test_happy_path_encrypted`, failing on baseline, now passes. `php -l` is clean. Pylint went from 8.88 to 8.90. The new messages are of kinds that already exist: line-too-long at 101-121 characters, complexity counts, and C0413 from the existing `siadc09d.py` sys.path pattern. I did not rewrap lines, to avoid churn in the `daemon.py` hot-spot.
- **Cipher (Task 1):**
  - `SIACipher` was rewritten to § 5.4.4-5.4.7: 16/24/32-byte keys, a front pad of printable ASCII (no `|` `[` `]`) followed by `|`, uppercase hex out.
  - Decrypt strips the pad at byte level, with a `]` fallback for `*NULL`/`*ACK` built from templates that omit the `|`.
  - PKCS#7 was removed. `repr()` shows only the key size.
  - `parse_hex_key` accepts 32/48/64 hex digits and never echoes the input.
  - It is checked against the independent oracle `tests/level1/_dc09_crypto_oracle.py` (raw `cryptography`, not `SIACipher`) and against the V1/V2/V4/V5/V6 external vectors.
- **Protocol (Task 2):**
  - `encode_message` encrypts the region after `[`, writes `[` + hex with no `]` after it (D1, constant `ENCRYPTED_REGION_TERMINATOR = ""`), and requires a timestamp.
  - It takes an explicit `seq=` and applies the 0xFFF length guard to the encrypted form.
  - Encrypted supervision is `"*NULL"0000` with plaintext `pad|]_ts` (D2, a single token constant).
  - The 4095/4096 length-guard boundary test was written in Task 2.1 (`test_sia_protocol_encryption.py`), so Task 7.2 reused it.
- **Daemon (Task 3):**
  - The key is parsed once in `__init__`.
  - With encryption on and a missing or invalid key, SM1 enters the new `SM1State.CONFIG_ERROR` ("Clé de chiffrement invalide", `supervision_state` 0). Nothing is sent, and there is no plaintext fallback.
  - `ErrorCode` admits no new codes without a design review, so the once-per-run notification goes straight through the `message_center` + `notify` callbacks (`_enter_encryption_config_error`).
  - A NAK gets an immediate re-send with the same seq (D-85 fixed) and a timestamp from the NAK, trusted within ±24 h (`NAK_TIMESTAMP_SANITY`), else UTC now plus a WARN (`_nak_offset`, D3). The re-send counts in the same budget of 4 attempts.
  - A NULL NAK gets up to `SUPERVISION_NAK_RESENDS` = 2 re-sends before a strike.
  - The inspector trace takes the token and seq from the built frame (`_trace_header`).
- **Decoder, simulator, PHP (Tasks 4-6):**
  - The decoder accepts both `[hex` and `[hex]`.
  - The simulator decrypts inbound frames and silently discards frames it cannot decrypt (§ 5.6.2.4), so tests must give it the same key. It answers with a spec-format `*ACK` and a timestamped NAK, and has NAK-once modes.
  - PHP guard 5 checks the key format (`isValidEncryptionKey`). The decode ajax `bin2hex` fallback was removed. The connection test returns a verdict for a bad or missing key.
- **Tests (Task 7):**
  - level3 root causes:
    1. The simulator NAK now carries a timestamp, so the daemon re-sends. The two NAK tests that pin `BAD_CSR_RESPONSE` now set `sim._nak_with_timestamp = False`.
    2. The encrypted E2E tests ran the simulator with no key, so it discarded every frame. They now share `E2E_ENCRYPTION_KEY`, and the fixture builds a real `BaseConfig`.
  - `test_happy_path_encrypted` asserts through a `_send_raw` spy that both `*NULL` and `*SIA-DCS` went out.
  - The new `TestKeyNeverLeaks` sends encrypted NULLs and events at DEBUG through a NAK and a re-send, then checks that the key (upper and lower case) and a bad key are absent from:
    - logs;
    - callbacks;
    - the ring buffer;
    - `repr(config)`;
    - the `AESKeyError` message.
- **Docs (Task 9):**
  - README, the admin, developer and fr_FR guides, and the changelog now say "implemented to § 5.4, checked against real-panel frames, not yet validated against a real receiver". They state that keys are hex only (D-93) and describe the NAK re-send.
  - `daemon-design.md`:
    - no `]` after the hex;
    - the pad/`|` structure;
    - the real `sia_crypto` API, where it used to say stub;
    - the NAK re-send with same seq, replacing "v1.1 auto-heal";
    - `CONFIG_ERROR`.
  - deferred-work: D-81 partial (AC11), D-85 resolved, and a note on D-95(d).
- **Known, not fixed here:** the key is still visible in `ps` through `--encryption-key` on the daemon command line. AC5 keeps this path unchanged, and it is tracked in D-95(d)/ADR-07. The leak test does not cover the process list.
- **For AC11 (live session):**
  - Push first.
  - Validate an encrypted event before `*NULL`.
  - Record whether the receiver wants a `]` after the hex (one constant to revert), whether it accepts `*NULL` (D2 fallback constant), and whether its key is hex or ASCII (D-93). A mismatch shows up as silence, not a NAK.

### File List

**Daemon (modified):**
- `resources/siadc09d/__init__.py`
- `resources/siadc09d/sia_crypto.py`
- `resources/siadc09d/sia_protocol.py`
- `resources/siadc09d/daemon.py`
- `resources/siadc09d/siadc09d.py`
- `resources/siadc09d/csr_simulator.py`
- `resources/siadc09d/error_handler.py`
- `resources/siadc09d/messages.py`

**PHP (modified):**
- `core/class/siaDC09.class.php`
- `core/ajax/siaDC09.ajax.php`
- `core/i18n/fr_FR.json`

**Tests (new):**
- `tests/level1/_dc09_crypto_oracle.py`
- `tests/level1/test_sia_protocol_encryption.py`
- `tests/level1/test_csr_simulator_encryption.py`
- `tests/level1/test_php_encryption_key_guard.py`
- `tests/level2/test_nak_retry_and_key_config.py`

**Tests (modified):**
- `tests/level1/test_sia_crypto.py`
- `tests/level1/test_sia_protocol.py`
- `tests/level1/test_protocol_decode.py`
- `tests/level1/test_csr_simulator.py`
- `tests/level1/test_connection_test.py`
- `tests/level2/test_daemon_integration.py`
- `tests/level2/test_sm2_extended_coverage.py`
- `tests/level2/test_supervision_loop_integration.py`
- `tests/level3/conftest.py`
- `tests/level3/test_full_workflow_e2e.py`
- `tests/level3/test_supervision_e2e.py`
- `tests/fixtures/golden/frames_encrypted_alarm.hex`
- `tests/harness/run_harness.py`

**Docs and tracking (modified):**
- `README.md`
- `docs/admin-guide.md`
- `docs/developer-guide.md`
- `docs/fr_FR/index.md`
- `docs/fr_FR/changelog.md`
- `internal-docs/design/daemon-design.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/planning-artifacts/epics.md`: challenge phase, where Story 1.2 was marked superseded.

## Change Log

| Date | Change |
|---|---|
| 2026-09-27 | Story created from D-81 and challenged: D1 reversed to no `]` after the hex; D-85 folded into AC4. |
| 2026-09-28 | Dev complete: AC1-AC10 implemented and tested, Tasks 1-7 and 9 done. Task 8 / AC11 (live validation) left open by design. Status → review. |
| 2026-09-28 | Code review, 4 groups (core implementation; PHP+docs+tracking; level1 tests; level2/level3 tests+fixtures): 12 patches applied, 19 items deferred (D-96..D-114), 0 decision-needed, several false positives verified and dismissed. 0 test regressions across all four groups (level1 1334, level2 374 baseline-only fails, level2_5 79 baseline-only fail, level3 26-27). Status stays `review`: Task 8 / AC11 remains open by design, unaffected by this review. |
