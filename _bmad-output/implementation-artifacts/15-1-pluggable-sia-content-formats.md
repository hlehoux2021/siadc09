# Story 15.1: Pluggable SIA Content Formats — SIA-DCS (default) + "IP" `#KEY=VALUE`

Status: cancelled — 2026-10-17, never merged to master; see "Cancellation" below

<!-- Created 2026-10-01 from Herve's request. Not derived from an existing epics.md entry: Epic 15 is registered by this story. -->

## Cancellation — 2026-10-17

Cancelled by Herve on 2026-10-17, via the AC1 exit ("if the answer is that it is the receiver's display: stop"). None of the story's code reached master. The full history (commits e0fde55, 17d56cb) is kept on the local branch `story/15-1-pluggable-sia-content-formats`.

**Why.** The "IP" example is not a wire format. It reads as the receiver software's display (Aremis, account 20881) of a standard SIA-DCS data block:

| IP field | SIA-DCS element | Value in the example |
|---|---|---|
| `SITE` | account `#acct` | `20881` |
| `ETAT` | event code | `BA` |
| `POINT` | address after the code | `129` |
| `ZONE` | DC-03 area `ri`, padded to 4 digits | `0008` |

So `#PROT=SIA#ETAT=BA#POINT=129#ZONE=0008#SITE=20881` corresponds to `[#20881|Nri8/BA129]`. This also explains the "POINT ≠ ZONE" puzzle in AC4: the two are different SIA fields, and the area was the one the plugin was not sending.

The actual gap was the missing `N` / `ri<area>/` prefix in the data block. Branch `fix/sia-dcs-n-prefix` fixed it on master (merge 273bf75): every event is now sent as `[#acct|Nri1/<code><addr>]`, with the area set by the daemon constant `SIA_AREA_NUMBER = 1`. It was field-validated at Scutum on 2026-10-17, where CL/OP/BA/BC are all recognised and "CODE INCONNU" is gone (`internal-docs/ajax.md`).

**Not confirmed by Aremis itself.** The mapping above is deduced from the example and from the Scutum result. Task 0 was never answered by the centrale. An optional probe against Aremis would settle it (`scripts/sia_csr_probe.py ... --event Nri1/BA001`), run by Herve.

**What survives elsewhere.** ADR-19 is withdrawn, and Epic 15 is kept in `epics.md` as a cancelled stub. Epic 16 (multi-CSR failover, ADR-20) was scaffolded on this branch on 2026-10-02 and was brought to master on its own; its `content_format` references were dropped.

## Story

As a Jeedom user whose monitoring centre expects a different message-content layout than the DC-09 SIA-DCS data block,
I want to choose the SIA frame's content format per equipment in the wizard,
so that the plugin can report to a CSR that only understands its own "IP" `#KEY=VALUE` layout, without changing anything for existing SIA-DCS setups.

## Background — what is known, what is not

**Two content formats identified so far:**

| Format | Status | Example data content |
|---|---|---|
| `sia-dcs` | implemented, DC-09 § 5.5.1.7 / Annex B, field-validated against `192.168.100.15:10002` | `[#20881\|BA 002]` (14-2 live evidence) |
| `ip` | only **one example** given by Herve's centrale (2026-10-01), verbatim: | `#PROT=SIA#ETAT=BA#POINT=129#ZONE=0008#SITE=20881#IP=..........#TTA=00` |

`ADM-CID` is **not implemented**: only the constant `ADM_CID_TOKEN` exists (`sia_protocol.py:45`) and a ported ioBroker test oracle (`tests/level1/_dc09_crypto_oracle.py:88`). It is out of scope here, but the abstraction built by this story must let it be added later as a third format without touching the frame envelope.

**The "IP" format is not a DC-09 / Annex H token.** Annex H lists only `SIA-DCS`, `ADM-CID`, `NULL`, `XNM`, `ACK`, `NAK`, `DUH`, `RSP`. The `#KEY=VALUE` layout is proprietary to the centrale (sia-dc09-expert analysis, 2026-10-01).

**Field-by-field reading of the single example (hypotheses, not facts):**

| Key | Example | Most likely source in our model | Confidence |
|---|---|---|---|
| `PROT` | `SIA` | constant | high |
| `ETAT` | `BA` | `EventItem.sia_code` | high |
| `SITE` | `20881` | `account_number` — 20881 is the account that was live on the real receiver during 14-2 (2026-09-24) | high |
| `POINT` | `129` | detector/point number — but we only have **one** address number (`zone_number`, or `user_number` for BC/OP/CL) | **unknown** |
| `ZONE` | `0008` | 4-digit zero-padded — partition/area? or our zone order number? | **unknown** |
| `IP` | `..........` | masked: PE source IP? left as literal dots? receiver-filled? | **unknown** |
| `TTA` | `00` | no idea (type of transmission? test flag?) | **unknown** |

**Critical unknown — is this even a wire format?** `PROT=SIA` and `IP=` (a PE does not normally know the source IP the receiver sees) suggest this might be the **receiver software's own normalized export/display** of a frame it received, not what the PE must send. Our real frames on account 20881 were `[#20881|BA 002]`, which does not map cleanly to `POINT=129`/`ZONE=0008`, so this cannot be decided from the repo. If it is a receiver-side rendering, the `ip` formatter (Tasks 4–5) is not needed at all. Task 0 resolves this before any IP-specific code.

## Acceptance Criteria

1. **AC1 — Task 0 gate.** The questions in Task 0 are answered by the centrale (via Herve) and recorded verbatim in this file's Dev Agent Record before Tasks 4–5 start. If the answer is "it is our receiver's display of a normal SIA-DCS frame", Tasks 4–5 are dropped, the `ip` option is not added, and the story closes on Tasks 1–3 + 6 only (abstraction refactor, no UI choice) or is cancelled at Herve's call.
2. **AC2 — Content formatter abstraction.** `sia_protocol.py` builds the message content through a single formatter selected by a `ContentFormat` value (`Literal["sia-dcs", "ip"]`, constants `CONTENT_FORMAT_SIA_DCS`, `CONTENT_FORMAT_IP`). The frame envelope (LF, CRC, `0LLL`, token, seq, `Rrcvr`/`Lpref`/`#acct`, timestamp, CR, encryption) stays in one place and is shared by all formats.
3. **AC3 — SIA-DCS byte-identical.** With `content_format="sia-dcs"` (and when the key is absent), every frame `encode_message()` / `make_supervision_message()` produces is **byte-identical** to the pre-story output, encrypted and unencrypted, with and without `zone`/`media_url`/timestamp/receiver prefix. Proven by golden-frame tests captured from the current code **before** the refactor (Task 1).
4. **AC4 — IP formatter.** With `content_format="ip"`, an alarm event for account `20881`, code `BA`, and the address values Task 0 defines, produces content whose `#KEY=VALUE` part equals the centrale's example **exactly** (key order, zero-padding, separators), and sits in the envelope Task 0 defines. The example string is the test oracle, copied verbatim; it is never regenerated from our own code.
5. **AC5 — Supervision and BC/OP/CL under IP.** Supervision and user-addressed codes (BC/OP/CL, ADR-18) follow the rule Task 0 records. Default if the centrale gives no rule: supervision stays the current SIA-DCS NULL-code frame, and BC/OP/CL put `user_number` where BA puts its address.
6. **AC6 — Encryption.** `ip` + `encryption_enabled` is rejected unless Task 0 confirms the centrale decrypts it: the wizard (step 1 validation) blocks it with a French message, and `deamon_info()` adds a guard that keeps the daemon `nok`. No `*`-prefixed IP frame is ever sent unconfirmed.
7. **AC7 — Wizard choice.** Step 1 (`desktop/php/siaDC09.php`, `#siaDC09-step1`) shows a `<select data-l2key="content_format">` labelled `{{Format du contenu}}`, with `sia-dcs` **first** so equipment saved before this story shows it on reload. Options: `SIA-DCS (norme DC-09)` and `IP (champs séparés par #)`. One help line under it, in the style of 7754a6b/ba6962a (no re-explaining). The step 2 summary and the config-mode summary (`siaDC09.js:~590-610`) show the chosen format.
8. **AC8 — Config plumbing.** `deamon_start()` passes `--content-format` from `content_format` (default `sia-dcs`). `deamon_info()` gets a guard (`sia-dcs`/`ip` only, empty = `sia-dcs`, same pattern as Guard 3c). `siadc09d.py` adds the argument (default `sia-dcs`). `CSRPreset` gets a `content_format: ContentFormat = CONTENT_FORMAT_SIA_DCS` field validated in `__post_init__`. `_build_event_frame()` and `_send_supervision()` pass it through. `run_connection_test` reads it from the `--config` dict (default `sia-dcs`).
9. **AC9 — Existing equipment unaffected.** An equipment with no `content_format` key starts the daemon, passes all guards, and sends SIA-DCS frames identical to before, with no re-run of the wizard.
10. **AC10 — i18n, tests, lint.** Every new string is in `core/i18n/fr_FR.json` (`test_i18n_roundtrip.py` green). The key lists in `test_wizard_config_key_consistency.py` and `test_wizard_php_structure.py` include `content_format`. Full level1 run shows no new failures against a baseline measured at the start of the session (memory: never copy the old baseline). `pylint resources/siadc09d/` and `php -l` are clean.
11. **AC11 — Live validation.** On `test-jeedom.lehoux.net`, against the real receiver `192.168.100.15:10002`: (a) a SIA-DCS BA is still ACKed (regression), (b) with `ip` selected, a BA is ACKed **and the centrale confirms the event displayed correctly on their side** (an ACK alone does not prove they parsed the content). Validated through the UI as well as the API (memory `jeedom-ui-validation-over-reflection`). If the centrale cannot confirm (b), record it as an open gap, not a PASS.

## Tasks / Subtasks

- [ ] **Task 0 — Resolve the IP format with the centrale (AC1). BLOCKING for Tasks 4–5.** Herve asks the centrale and pastes the answers verbatim into the Dev Agent Record:
  - [ ] 0.1 Is `#PROT=SIA#ETAT=…` what the **transmitter (PE) must send**, or how **their receiver software displays** a frame it received? (If the latter: stop, see AC1.)
  - [ ] 0.2 The **complete raw frame** around it, ideally a real capture: is there a DC-09 envelope (`<LF>crc0LLL"token"seq L0#acct[...]_timestamp<CR>`)? Which token (`"SIA-DCS"`? something else)? Inside `[...]`, or the bare string? Does it replace `#acct|BA 002` or follow it?
  - [ ] 0.3 What are `POINT` and `ZONE` (detector vs. zone/partition)? Widths and padding (`129` vs `0129`, `0008`)?
  - [ ] 0.4 `IP=`: what value is expected (PE's LAN IP, public IP, empty, literal dots)? `TTA=`: meaning and possible values?
  - [ ] 0.5 Expected response: a standard DC-09 `"ACK"seq…` frame? NAK behaviour?
  - [ ] 0.6 Supervision (link test) in this format, or standard SIA-DCS/NULL? BC/OP/CL (disarm, arm, reset) examples?
  - [ ] 0.7 Encryption supported with this format?
  - [ ] 0.8 Is the field order fixed? Are unknown keys tolerated? Is a timestamp expected?
  - [ ] 0.9 Update AC4/AC5/AC6 and Task 4 with the answers before coding them (story amendment, dated).
- [x] **Task 1 — Golden frames first (AC3). Red before refactor.**
  - [x] 1.1 New `tests/level1/test_content_format_golden.py`: capture the current `encode_message()` and `make_supervision_message()` output for a matrix: {no zone, zone `002`, zone + `media_url` with snapshot+clip} × {unencrypted with fixed timestamp, unencrypted without timestamp, encrypted with fixed pad via `pad_source` and fixed timestamp} × {with/without `R` receiver prefix}. Store the bytes as literals in the test (hex), generated **once** from master before any change.
  - [x] 1.2 Same tests also pass `content_format="sia-dcs"` explicitly. Both must be identical to the literals.
- [x] **Task 2 — Formatter abstraction in `sia_protocol.py` (AC2, AC3).**
  - [x] 2.1 Add `ContentFormat = Literal["sia-dcs", "ip"]` and the two constants next to the token constants (`sia_protocol.py:43-49`).
  - [x] 2.2 Extract today's `_format_data_field` + `_format_extended_data_field` (`sia_protocol.py:491-544`) behind one internal content-building entry point keyed by `ContentFormat`. Keep both methods' behaviour and their 14-1/14-3 docstrings intact. Prefer a small strategy (a dict of format → callable, or one private method per format) over a class hierarchy: the builder is already the stateful class (`.claude/rules/python-style.md`).
  - [x] 2.3 `encode_message()` (`sia_protocol.py:238`) and `make_supervision_message()` (`:309`) get `content_format: ContentFormat = CONTENT_FORMAT_SIA_DCS`. The encrypted branch keeps building `region = <content after '['> + extended + timestamp` (§ 5.4.3). Do not touch `ENCRYPTED_REGION_TERMINATOR` / `ENCRYPTED_SUPERVISION_TOKEN` (1-5 D1/D2, field-tuned against ioBroker).
  - [x] 2.4 An unknown `content_format` raises `SIAProtocolError`. It is never silently treated as SIA-DCS.
  - [x] 2.5 Task 1 tests green, unchanged.
- [x] **Task 3 — Plumbing PHP → CLI → preset → builder (AC8, AC9).**
  - [x] 3.1 `presets.py`: add the `content_format` field with default, validated in `__post_init__` (ValueError on unknown, same style as `transport`). It must come after the existing defaulted fields (dataclass ordering).
  - [x] 3.2 `siadc09d.py:397-429`: `--content-format` (default `sia-dcs`), passed to `CSRPreset`. Add a regression in `test_daemon_startup_regressions.py` (the "Fix #N" pattern): missing flag → `sia-dcs`.
  - [x] 3.3 `daemon.py`: `_build_event_frame()` (`:1913`, call at `:1984`) and `_send_supervision()` (`:1050`, call at `:1092`) pass `self._preset.content_format`.
  - [x] 3.4 `siadc09d.py:263` `run_connection_test`: read `content_format` from the config dict, default `sia-dcs`, pass to `make_supervision_message` (`:305`). (Currently a no-op there since supervision always stays SIA-DCS per AC5 — wired for symmetry/future-proofing.)
  - [x] 3.5 `siaDC09.class.php`: `deamon_start()` adds `--content-format` after `--crc-format` (`:246`), escaped with `escapeshellarg`, default `'sia-dcs'`. `deamon_info()` adds Guard 3e (unknown value, empty tolerated) and Guard 3f (AC6: blocks `ip` + encryption) after Guard 3c. Empty or missing → OK (treated as `sia-dcs`). Anything else → `nok` with a French message pointing to step 1.
  - [x] 3.6 Tests: `test_php_eqlogic_stub.py` (CLI flag escaping + Guard 3e/3f), `test_wizard_config_key_consistency.py` (`_CSR_KEYS_IN_PYTHON_CONFIG` — `_CSR_CONFIG_KEYS`/`_JS_STEP1_FIELDS` deferred to Task 5, the wizard field doesn't exist yet), `test_daemon_startup_regressions.py` (CLI default, preset validation/default), `tests/level2/test_sm2_frame_building.py` (preset `content_format` reaches the real frame end to end via `_send_with_retry`). Also fixed 7 pre-existing `_preset = MagicMock(...)` test fixtures across `tests/level2/` that didn't set `content_format` — a bare `MagicMock()` attribute access returns another `MagicMock`, which fails the `content_format ==` checks in `_build_content_blocks` and raised `SIAProtocolError`, previously masked because nothing read that attribute. Added `fr_FR.json` entries for the two new Guard 3e/3f messages (sorted into the existing `class.php` section; also fixed a pre-existing ordering slip while re-sorting).
- [x] **Task 4 — IP formatter (AC4, AC5). Only after Task 0.** AC4 is **not fully met**: see honesty note below.
  - [x] 4.1 Oracle test first: `tests/level1/test_content_format_ip.py` with the centrale's example **verbatim** as a constant. `test_ip_content_matches_known_fields_from_oracle_example` asserts exact equality for PROT/ETAT/POINT/SITE/TTA. `test_ip_content_does_not_yet_match_full_oracle_example` **documents, rather than hides, that ZONE does not match** (oracle: POINT=129 ≠ ZONE=0008, two independent values; our `EventItem` model only carries one address value per event — Task 0.3 is still open). AC4's "equals the centrale's example exactly" is therefore only partially satisfied — honestly, not by relaxing the assertion.
  - [x] 4.2 Implemented `_format_ip_content()` / `_build_content_blocks()` (`sia_protocol.py`). Padding stays where it was: `daemon.py` zero-pads the single address value to 3 digits before it ever reaches `extended_data["zone"]`, same as SIA-DCS (Task 1's golden frames are untouched — confirms no byte-level change to the sia-dcs path). The `ip` formatter additionally left-pads that same 3-digit value to 4 for `ZONE`, which is admittedly just a guess at the width, not a real second value (see 4.1 caveat).
  - [x] 4.3 Supervision: `make_supervision_message()` ignores `content_format` and always sends the SIA-DCS NULL frame (AC5 default rule, documented in its docstring; Task 0.6 unanswered). BC/OP/CL: verified manually that `_build_event_frame()` already puts `user_number` into the same `extended_data["zone"]` key BA/FA/PA use for their zone, so the `ip` formatter picks it up unchanged (`#POINT=005#ZONE=0005` for a BC with user 5) — no code change needed, just confirmed by inspection.
  - [x] 4.4 Every key the formatter writes is a named constant (`IP_FORMAT_PROTOCOL`, `IP_FORMAT_TTA_DEFAULT`). Values containing `#` or `=` raise `SIAProtocolError` (`IP_CONTENT_RESERVED_CHARS`), tested in `test_ip_content_rejects_reserved_characters`.
- [x] **Task 5 — Wizard UI (AC6, AC7). Only after Task 0 confirms the `ip` option exists.**
  - [x] 5.1 `siaDC09.php` step 1: the select after `transport` (now before `account_number`), `sia-dcs` first, plus a one-line `{{...}}` help text.
  - [x] 5.2 `siaDC09.js`: `siaDC09_validateStep1` blocks `ip` + encryption with a French message (0.7 unanswered — stayed conservative). The step 2 summary and the config summary show the format. Read with `|| 'sia-dcs'`, the same fallback idiom as `transport`.
  - [x] 5.3 `deamon_info()` guard for `ip` + encryption (AC6) — done in Task 3 (Guard 3f), ahead of this task since the PHP-side guard didn't depend on the UI existing.
  - [x] 5.4 `fr_FR.json`: new strings added to the `desktop/php/siaDC09.php` and `desktop/js/siaDC09.js` sections, codepoint-sorted (the `class.php` Guard 3e/3f strings were already added in Task 3). `en_US.json` stays partial (memory `translations-workflow-broken`) — no entries added there, consistent with existing practice.
  - [x] 5.5 Tests: `test_wizard_php_structure.py` (`_STEP1_CONFIG_FIELDS` + new `test_content_format_sia_dcs_option_is_first`), `test_wizard_js_logic.py` (new `test_validate_step1_blocks_ip_format_with_encryption`), `test_wizard_config_key_consistency.py` (`_CSR_CONFIG_KEYS`/`_JS_STEP1_FIELDS` completed from Task 3's deferral), `test_i18n_roundtrip.py` green.
- [x] **Task 6 — Docs (AC2, AC8).**
  - [x] 6.1 `architecture.md`: new **ADR-19 — Pluggable message content formats**. Content is a strategy, the envelope is shared, SIA-DCS stays the default, ADM-CID can be added later the same way, and the IP format is proprietary (not Annex H) and provisional.
  - [x] 6.2 `internal-docs/design/daemon-design.md` (added a story-15-1 note on `encode_message()`'s current signature pointing to ADR-19 — the surrounding section already described a stale pre-1-5 signature, not corrected here, out of scope) and `wizard-design.md` (step 1 field table + config-key table).
  - [x] 6.3 Public docs: `docs/fr_FR/index.md` (step 1 table row + Limitations connues bullet) and `docs/fr_FR/changelog.md` (one bullet under the early-tester version), following `public-docs-editorial-rules` (early-tester framing, no IMA, single FR changelog).
- [x] **Task 7 — Regression, lint, live (AC10, AC11). Live validation (7.4) NOT done — see below.**
  - [x] 7.1 Baseline measured at session start: level1 1334 passed/0 failed (clean). Measured again mid-session for level2/level2_5/level3 by temporarily stashing only the code changes (not the pre-existing unrelated `.claude/` edits): 7 pre-existing failures (`test_connection_test_async.py` x4, `test_supervision_loop_integration.py` x1, `test_ipc_integration.py` x1, `test_full_workflow_e2e.py` x1 — the last one proved flaky, absent on a later run), 482-483 passed. Final combined run (level1+level2+level2_5): 1826 passed, exactly the 6 non-flaky pre-existing failures, 0 new regressions. 35 new tests added across the two new files + the files touched.
  - [x] 7.2 `python3 -m pylint resources/siadc09d/sia_protocol.py resources/siadc09d/presets.py resources/siadc09d/siadc09d.py`: compared against a clean-master baseline run the same way — all pre-existing (W1203, R0913/R0914/R0902/R0911/R0912/R0915, C0301, C0413, etc., all metric-threshold warnings already present before this story). Two new C0301 (line-too-long) introduced by my own new lines were fixed by wrapping/shortening. `find core/ desktop/ -name "*.php" | xargs -n1 php -l`: clean, no syntax errors.
  - [ ] 7.3 Commit and push — not yet done (awaiting Herve's go-ahead per session norms).
  - [ ] 7.4 Live validation on `test-jeedom.lehoux.net` against `192.168.100.15:10002` — **not done this session**. Needs: (a) regression check that a SIA-DCS BA still ACKs, (b) switching an equipment to `content_format=ip`, sending a BA, and getting the centrale to confirm the event displayed correctly on their side (an ACK alone doesn't prove they parsed `#PROT=SIA#ETAT=BA...`). Given AC4's own honesty note (ZONE doesn't match the one example we have), (b) is expected to need a real round-trip with the centrale before it can be called anything more than "sent and ACKed."

## Dev Notes

### Current state of the files this story touches

- **`sia_protocol.py`.**
  - `encode_message()` (`:238-307`) hard-codes `SIA_DCS_TOKEN` in both branches (`:301`, `:305`).
  - Content comes from `_format_data_field()` (`:491-516`), which produces `[#acct|CODE]` or `[#acct|CODE zone]`, and `_format_extended_data_field()` (`:519-544`), which produces `[V…]` from `media_url`.
  - The encrypted region is `data_field[1:] + extended + timestamp` (`:304`).
  - `make_supervision_message()` (`:309-362`) delegates to `encode_message()` with code `0000`, except for the dormant `*NULL` branch.
  - **Preserve:** 1-5 D1/D2 constants and comments (`:75-105`), `pad_source` injection, per-account `SequenceTracker`, explicit `seq` for retries (D-85), the `MAX_MESSAGE_LENGTH` check.
- **`daemon.py`.**
  - `_build_event_frame()` (`:1913-2000`) is the single place that builds `extended_data` (`zone` 3-digit padded from `zone_number`, or from `user_number` for `_USER_ADDRESSED_SIA_CODES`, plus `media_url`) and the timestamp policy (encrypted = now + nak_offset).
  - `_send_supervision()` (`:1050`, call `:1092-1100`).
  - The preset is `self._preset`, and the builder is created once (`:475-477`).
- **`presets.py`.** `CSRPreset` is a frozen dataclass with slots, and `transport` is converted in `__post_init__`.
- **`siadc09d.py`.** `BaseConfig` args are at `:397-412` and the preset is built at `:414-429` (with the comments on Fix #2 and #3). The `run_connection_test` dict path starts at `:263` and reads keys at `:277-286`.
- **`siaDC09.class.php`.** There is no `preSave`, so validation lives in the `deamon_info()` guards (`:98-221`). `deamon_start()` builds the CLI (`:223-301`). Optional keys with no UI (`receiver_prefix`, `account_prefix`, `crc_format`) are passed with defaults: follow that pattern.
- **Wizard.** The wizard *is* the equipment page; there is no modal.
  - Step 1 is `siaDC09.php:132-203`. Values are saved by the generic `getValues('.eqLogicAttr')` and restored by `setValues` in `plugin.template.js`.
  - A select with a missing key shows its first option, which is why `sia-dcs` must come first (AC7/AC9).
  - The `csr_provider` preset cards described in `wizard-design.md` were removed by D-84 (memory `d-84-ima-protect-removed-from-code`). Do not resurrect them to carry the format.

### Guardrails

- **Don't reinvent the envelope.** CRC, length, seq, account fields, timestamp and encryption already exist and are field-tuned. The IP format changes the content only, unless Task 0.2 says the envelope itself differs, in which case amend the story first.
- **Don't trust the spec's example CRC/length values** (1-5 Dev Notes: they're wrong everywhere). Use the centrale's real captures or our own CRC function on a known string.
- **The protocol inspector** (`decode()` / `_parse_message_fields`, `sia_protocol.py:1009+`) needs no change for IP content inside `[...]`: it shows it raw in `data_raw`. D-80 (only the first bracket is parsed) is a separate, pre-existing gap. Note it, don't fix it here.
- **CSR simulator** (`csr_simulator.py:519-580`) classifies by token. If Task 0 keeps `"SIA-DCS"` as the token, it should ACK IP content unchanged. Verify this with one level2 test instead of assuming it. The simulator is a tool, not validation (memory `udp-simulator-not-real-validation`).
- **`media_url` under IP:** whether `[V…]` is appended is part of 0.2/0.8. Default: not appended for `ip` (unknown to the centrale), with a DEBUG log line.
- **Account:** `SITE=20881` is a 5-digit decimal value, while DC-09 `#acct` is 3–16 hex characters. It passes `_validate_hex`, so no new validation is needed, but don't add a decimal-only check.

### Testing standards

- TDD: Task 1 goes red to green against literals before Task 2. Task 4.1's oracle is the centrale's string, never our own output.
- Level1 for pure protocol and source-structure checks (PHP and JS are tested by reading their source, the existing pattern). Level2 for daemon wiring.
- Commands: `python3 -m pytest tests/level1/`, `python3 -m pylint resources/siadc09d/`, and `php -l`.

### Project Structure Notes

- No new modules: the formatter lives in `sia_protocol.py`, the protocol layer. A separate `content_formats.py` is acceptable only if the IP formatter grows beyond ~60 lines. Justify it in Completion Notes if so.
- Config key name: `content_format` (snake_case, like `transport` and `crc_format`). CLI flag: `--content-format`.
- Parallel agents: `daemon.py` is the merge hot-spot (memory `parallel-agents-daemon-conflict`). Keep its diff to the two call sites.

### References

- [Source: internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1.4 (ID token), § 5.5.1.7 (data), § 5.4.3 (encrypted region), Annex H (tokens)]
- [Source: resources/siadc09d/sia_protocol.py:43-49, 238-362, 491-544]
- [Source: resources/siadc09d/daemon.py:1050-1100, 1913-2000]
- [Source: resources/siadc09d/presets.py, resources/siadc09d/siadc09d.py:263-311, 397-429]
- [Source: core/class/siaDC09.class.php:98-301]
- [Source: desktop/php/siaDC09.php:132-203; desktop/js/siaDC09.js:110-200, 590-610]
- [Source: _bmad-output/implementation-artifacts/1-5-dc09-conformant-send-path-encryption.md: D1/D2, spec oracles unreliable]
- [Source: _bmad-output/implementation-artifacts/14-2-frigate-event-prefetch-immediate-action.md:256: live `[#20881|BA 002]` frame]
- [Source: _bmad-output/planning-artifacts/architecture.md: ADR-18 (user-addressed codes)]

## Dev Agent Record

### Agent Model Used

### Task 0 — Centrale answers (verbatim)

Answered by Herve 2026-10-01 (not yet relayed to the centrale — these are Herve's own answers from what he already has):

- **0.1 (wire vs. display):** "c'est l'exemple de format de trame qu'ils m'ont fourni." — the centrale gave this as the frame format itself, i.e. this is claimed to be what the transmitter (PE) must send, not a receiver-side display. Treated as a wire format for planning purposes, but still only one example with no raw capture (0.2) to confirm the envelope around it.
- **0.5 (ACK):** standard DC-09 ACK already confirmed working in this project (existing SIA-DCS ACK evidence, e.g. 14-2 live validation). Not yet confirmed specifically for an `ip`-content frame, since none has been sent live yet.
- **0.2, 0.3, 0.4 (raw envelope, POINT/ZONE meaning and widths, IP/TTA meaning):** unknown for now. Herve has not asked the centrale yet.
- **0.6, 0.7, 0.8 (supervision/BC-OP-CL under IP, encryption support, field order/unknown-keys tolerance):** not asked.

**Deep-research agent findings (2026-10-01, web search — see session for sources):** no documented "IP-DCS" token or protocol exists anywhere reachable (DC-07 Annex H, vendor docs, forums, general web search) — the exact field combination (`PROT=`, `ETAT=`, `POINT=`, `ZONE=`, `SITE=`, `TTA=`) returns zero indexed matches on multiple search engines. GitHub/grep.app code search could not be completed (auth-walled/rate-limited in that session) — a real gap, not a confirmed "nothing exists." The one structural argument the agent found: DC-07/DC-09 protocol tokens are bare quoted strings (`"SIA-DCS"`), never `KEY=VALUE` sequences, which is weak but real evidence that **this layout may be the centrale's own receiver-side log/display convention rather than a wire format the transmitter must produce** — in tension with Herve's own answer to 0.1 below (the centrale told him this IS the frame format). Neither claim is confirmed; this is exactly what 0.2 (a full raw capture) would settle. Recommendation from the research: ask the centrale what software produced this string, and whether it's literally the wire protocol or a line from their own event log, before trusting Task 4's formatter further.

**Decision (Herve, 2026-10-01): proceed to the next step without waiting for 0.2-0.4/0.6-0.8.** Tasks 1-3 (golden frames, formatter abstraction, plumbing) are unblocked as planned. Task 4 (IP formatter) proceeds on the one example we have, treating it as the literal wire content with the sia-dcs envelope (LF/CRC/length/token/CR unchanged, `"SIA-DCS"` token, content block replacing `#acct|CODE`) as the working assumption — amend this story the moment real answers arrive, since POINT/ZONE/IP/TTA semantics (and therefore how our EventItem fields map into them) are still a guess. Task 5 (wizard UI) and AC6 (encryption gate) stay conservative: block `ip` + encryption until 0.7 is answered.

### Debug Log References

- Mid-session, `git stash` on the whole working tree picked up two pre-existing, unrelated `.claude/` modifications that were already dirty at session start; the subsequent `git stash pop` failed because the sandbox denies writes to `.claude/settings.json`/`.claude/hooks/`. No work was lost — the stash was recovered via `git checkout stash@{0} -- <my files>` + `git stash drop`, scoped to only the files this story touched. Repeated the stash dance twice more (narrower, excluding the `.claude/` paths) specifically to measure a clean-master baseline for the level2/2.5/3 pre-existing-failure count and the pylint pre-existing-warning count, each time restored cleanly. No files were lost or corrupted; verified via `git status`/`git diff --stat` after each restore.
- Found and fixed a real latent-test-fragility issue (not a story bug, but caused by this story's new code): 7 test fixtures in `tests/level2/` mock `daemon._preset = MagicMock(...)` without listing every attribute the daemon reads. Before this story, `content_format` wasn't read, so the gap was invisible. After wiring `self._preset.content_format` into `_build_event_frame`/`_send_supervision`, those fixtures returned a bare `MagicMock` for it, which fails the `==` checks in `_build_content_blocks()` and raises `SIAProtocolError`, silently converting every one of those tests' alarm sends to `SM2State.FAILED`. Fixed by adding `content_format='sia-dcs'` to each fixture.

### Completion Notes List

- 2026-10-01: Story created by the create-story workflow from Herve's request. Epic 15 registered by this story. Only one IP example is available; Task 0 gates the IP-specific work.
- 2026-10-01: Dev-story session (Tasks 1-7, all but 7.3/7.4). TDD throughout: golden frames captured from master before any refactor (Task 1), formatter abstraction built behind `content_format` (Task 2, byte-identical for `sia-dcs` — proven, not assumed), full PHP→CLI→preset→daemon plumbing (Task 3), the `ip` formatter with an honestly-incomplete oracle match (Task 4 — see AC4 note), wizard UI + validation + i18n (Task 5), ADR-19 + design docs + public FR docs (Task 6), full regression + lint + PHP syntax clean against a freshly-measured baseline (Task 7.1/7.2).
- **AC4 is only partially met, by design, not by oversight.** The centrale's one example proves `POINT` and `ZONE` are independent values (`129` vs `0008`), but our `EventItem` model carries only one address value per event. The current `_format_ip_content()` derives both from that single value — correct for `POINT`, a documented guess for `ZONE`. `tests/level1/test_content_format_ip.py::test_ip_content_does_not_yet_match_full_oracle_example` records this as an open gap rather than relaxing the acceptance criterion or hiding the mismatch. Task 0.3 (ask the centrale what the two values actually mean) must be answered before this can honestly be called done.
- **AC11 (live validation) was not attempted this session** — no live host access in this session's tool set. Flagged in Task 7.4 as the next concrete step: a regression check (SIA-DCS still ACKs) plus an `ip`-format send with the centrale's own confirmation that they parsed it (an ACK alone is not evidence of that, since any receiver that just checks CRC/length would ACK garbage content).
- Status set to `review`, not `done` — Task 7.3 (commit/push) and 7.4 (live validation) are open, and AC4/AC11 are explicitly incomplete. Recommend code-review proceeds on the committed diff once pushed, but closure of this story should wait for at least AC11(a).

### File List

**Core protocol / daemon:**
- `resources/siadc09d/sia_protocol.py` — `ContentFormat` type, `CONTENT_FORMAT_SIA_DCS`/`CONTENT_FORMAT_IP`/`IP_FORMAT_*` constants, `_build_content_blocks()`, `_format_ip_content()`, `content_format` param on `encode_message()`/`make_supervision_message()`
- `resources/siadc09d/presets.py` — `CSRPreset.content_format` field + validation
- `resources/siadc09d/siadc09d.py` — `--content-format` CLI arg, `run_connection_test()` reads/passes it
- `resources/siadc09d/daemon.py` — `_build_event_frame()`/`_send_supervision()` pass `self._preset.content_format`

**PHP plugin:**
- `core/class/siaDC09.class.php` — Guard 3e/3f in `deamon_info()`, `--content-format` in `deamon_start()`
- `core/i18n/fr_FR.json` — new strings for Guard 3e/3f and the wizard field, re-sorted
- `desktop/php/siaDC09.php` — step 1 `content_format` select
- `desktop/js/siaDC09.js` — validation, step 2 summary, config summary

**Tests (new):**
- `tests/level1/test_content_format_golden.py` — AC3 byte-identical golden frames
- `tests/level1/test_content_format_ip.py` — IP format oracle (honest partial match)

**Tests (modified):**
- `tests/conftest.py` — `make_daemon_preset(content_format=...)`
- `tests/level1/test_daemon_startup_regressions.py`, `test_php_eqlogic_stub.py`, `test_wizard_config_key_consistency.py`, `test_wizard_js_logic.py`, `test_wizard_php_structure.py`
- `tests/level2/test_sm2_frame_building.py` — end-to-end preset→frame content-format test
- `tests/level2/test_frigate_prefetch_dispatch.py`, `test_priority_queue_basic.py`, `test_queue_consumer_integration.py`, `test_sm1_extended_suite.py`, `test_sm2_alarm_event_suite.py`, `test_sm2_extended_coverage.py`, `test_supervision_queue_integration.py` — added `content_format='sia-dcs'` to `_preset = MagicMock(...)` fixtures (latent fragility fix, see Debug Log)

**Docs:**
- `_bmad-output/planning-artifacts/architecture.md` — ADR-19
- `_bmad-output/planning-artifacts/epics.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml` — Epic 15 / Story 15-1 registration and status
- `internal-docs/design/daemon-design.md`, `internal-docs/design/wizard-design.md`
- `docs/fr_FR/index.md`, `docs/fr_FR/changelog.md`

## Change Log

| Date | Change |
|---|---|
| 2026-10-01 | Story created (new → ready-for-dev). Epic 15 registered. |
| 2026-10-17 | Story cancelled (AC1 exit: the "IP" example is the receiver display of `[#20881|Nri8/BA129]`); real gap fixed by `fix/sia-dcs-n-prefix`. Story file kept on master as the record; code stays on the local 15-1 branch. |
