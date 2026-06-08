---
story_id: "11-1"
story_key: "11-1-protocol-conformance-capture-compare-ajax-frames"
epic_id: "epic-11"
epic_name: "End-to-End Testing & Market Preparation"
status: "ready-for-dev"
created: "2026-06-01"
analysis_completed: "2026-06-01"
---

# Story 11.1: Protocol Conformance — Capture & Compare Ajax Frames

Status: ready-for-dev

## Story

As a protocol engineer,
I want to verify our daemon generates frames identical to Ajax,
So that both systems interoperate with CSRs identically.

## Acceptance Criteria

1. **Given** Ajax alarm system configured to send SIA DC-09 frames to CSR Simulator (port 10001), **When** capturing Wireshark/tcpdump traffic during a burglary, fire, panic, and supervision cycle, **Then** SIA frames extracted using `extract_frames_from_pcap.py` and saved to `test_data/protocol_conformance/ajax_burglary.hex`, `ajax_fire.hex`, `ajax_panic.hex`, `ajax_supervision.hex`.

2. **And** our plugin daemon (running on Jeedom VM) generates frames for the same 4 scenarios (burglarAlarm zone="Piece1", fireAlarm zone="Piece1", panicAlarm zone="Piece1", supervision NULL). Captured frames saved to `test_data/protocol_conformance/our_burglary.hex`, `our_fire.hex`, `our_panic.hex`, `our_supervision.hex`.

3. **And** frame comparison executed via `test_data/protocol_conformance/compare_frames.py ajax_frame our_frame → match|mismatch`:
   - Message **length** field matches (hex-encoded, identical byte count)
   - **Account number** matches in both frames (`account` field in `ParsedMessage`)
   - **Event code** matches (`data_raw` field: `BA` / `FA` / `PA` / `NULL`)
   - **CRC** is valid in both frames (`crc_valid=True` from `decode()`)
   - **id_token** matches (both `SIA-DCS` or both `*SIA-DCS` for encrypted)
   - Sequence number field present and non-zero in both frames
   - Both frames accepted by CSR Simulator with ACK response (not NAK/timeout)

4. **And** any frame differences are documented in `test_data/protocol_conformance/conformance_report.md`:
   - **Timestamp precision** — Ajax and our daemon may use slightly different timestamp skew; document observed delta in seconds
   - **Receiver/account prefix** (`receiver_prefix`, `account_prefix`) — note if Ajax sends `R0L0#` and we send `L0#` (prefix format variation)
   - **Zone field format in data block** — Ajax may omit zone name or use different syntax in `[#{account}|{event_code} {zone}]`
   - **CRC format** — hex (4 ASCII chars) vs binary (2 raw bytes); note which each uses

5. **And** test data stored in `test_data/protocol_conformance/` (created by this story).

6. **And** `compare_frames.py` runs without error against both golden hex files from CSR Simulator (`tests/fixtures/golden/`) and real Ajax captures.

---

## Tasks / Subtasks

- [ ] Task 1: Capture Ajax frames via Wireshark (AC: 1)
  - [ ] 1.1 Configure Ajax alarm system to send to CSR Simulator: set receiver IP to Jeedom VM IP (10.75.11.110 or localhost), port 10001, UDP transport.
  - [ ] 1.2 Start CSR Simulator on Jeedom VM: `python3 -m tests.simulator --udp-port 10001 --host 0.0.0.0 --account 000001`
  - [ ] 1.3 Start Wireshark/tcpdump capture on Jeedom VM NIC: `sudo tcpdump -i eth0 -w /tmp/ajax_capture.pcapng udp port 10001`
  - [ ] 1.4 Trigger events on Ajax panel: burglary alarm, fire alarm, panic alarm. Also wait for one supervision NULL (typically sent every 60–300s depending on Ajax config).
  - [ ] 1.5 Stop capture. Extract frames: `python3 -m resources.siadc09d.extract_frames_from_pcap /tmp/ajax_capture.pcapng -o /tmp/ajax_all.hex --port 10001 --direction client`
  - [ ] 1.6 Split into per-event files (`ajax_burglary.hex`, `ajax_fire.hex`, `ajax_panic.hex`, `ajax_supervision.hex`) by inspecting the event codes in each hex line using `decode()`. Save to `test_data/protocol_conformance/`. Create the directory first: `mkdir -p test_data/protocol_conformance/`.

- [ ] Task 2: Capture our daemon frames (AC: 2)
  - [ ] 2.1 On Jeedom VM, start CSR Simulator (same as Task 1.2).
  - [ ] 2.2 Start `tcpdump` capture as in Task 1.3.
  - [ ] 2.3 Trigger events via Jeedom: burglarAlarm (zone="Piece1"), fireAlarm (zone="Piece1"), panicAlarm (zone="Piece1"). Wait for one supervision NULL frame.
  - [ ] 2.4 Extract frames: same `extract_frames_from_pcap` command → `/tmp/our_all.hex`
  - [ ] 2.5 Split into `our_burglary.hex`, `our_fire.hex`, `our_panic.hex`, `our_supervision.hex`. Save to `test_data/protocol_conformance/`.

- [ ] Task 3: Create `compare_frames.py` script (AC: 3, 6)
  - [ ] 3.1 Create `test_data/protocol_conformance/compare_frames.py`
  - [ ] 3.2 Script signature: `compare_frames.py <ajax_hex_file> <our_hex_file>` — reads first frame from each file, calls `decode()` on each, prints structured comparison table, exits 0 on match, 1 on mismatch
  - [ ] 3.3 Comparison fields: `id_token` (must match), `account` (must match), `data_raw` event code substring (`BA`/`FA`/`PA`/`NULL`), `crc_valid` (both True), `length_declared` (must match), `encrypted` flag (must match)
  - [ ] 3.4 Differences table in report: `receiver_prefix`, `account_prefix`, full `data_raw` (zone field), `timestamp_str` (delta in seconds if parseable)
  - [ ] 3.5 Output format (stdout):
    ```
    === Frame Comparison: ajax_burglary.hex vs our_burglary.hex ===
    [MATCH] id_token     : SIA-DCS
    [MATCH] account      : 000001
    [MATCH] event_code   : BA
    [MATCH] crc_valid    : True
    [MATCH] length       : 37
    [DIFF]  data_raw     : Ajax=[#000001|BA Piece1]  Ours=[#000001|BA Piece1]
    [INFO]  timestamp_Δs : 0.3s
    [INFO]  recv_prefix  : Ajax=''  Ours=''
    === VERDICT: MATCH (conformant) ===
    ```
  - [ ] 3.6 Verify script runs against the golden pcap fixture without error:
    ```bash
    # Smoke test with in-repo golden fixture (not real Ajax — just validates the script logic)
    python3 test_data/protocol_conformance/compare_frames.py \
      tests/fixtures/golden/capture_sia_example_extracted.hex \
      tests/fixtures/golden/capture_sia_example_extracted.hex
    ```
    Expected: all `[MATCH]`, exit 0.

- [ ] Task 4: Run frame comparison for all 4 event types (AC: 3)
  - [ ] 4.1 `python3 compare_frames.py ajax_burglary.hex our_burglary.hex` → note result
  - [ ] 4.2 `python3 compare_frames.py ajax_fire.hex our_fire.hex` → note result
  - [ ] 4.3 `python3 compare_frames.py ajax_panic.hex our_panic.hex` → note result
  - [ ] 4.4 `python3 compare_frames.py ajax_supervision.hex our_supervision.hex` → note result
  - [ ] 4.5 For each `[DIFF]` line, note the difference in the conformance report.

- [ ] Task 5: Verify both frame sets accepted by CSR Simulator (AC: 3)
  - [ ] 5.1 Replay Ajax frames through CSR Simulator using `simulate_frames.py`:
    ```bash
    python3 -m resources.siadc09d.simulate_frames \
      --input test_data/protocol_conformance/ajax_burglary.hex \
      --port 10001 --protocol udp
    ```
    Expected: `[RX ... ACK ...]` for each frame (no TIMEOUT, no NAK).
  - [ ] 5.2 Repeat for `ajax_fire.hex`, `ajax_panic.hex`, `ajax_supervision.hex`.
  - [ ] 5.3 Repeat all 4 for our `our_*.hex` files. All must ACK.
  - [ ] 5.4 If any frame gets NAK: inspect raw hex with `decode()` in Python REPL and document in conformance report.

- [ ] Task 6: Write conformance report (AC: 4, 5)
  - [ ] 6.1 Create `test_data/protocol_conformance/conformance_report.md` with:
    - **Test Date**: (today's date)
    - **Ajax firmware version**: (read from Ajax panel settings)
    - **Our plugin version**: (read from `info.json`)
    - **Comparison Matrix** — one row per event type:
      | Event | id_token | account | event_code | crc_valid | length | verdict |
      |-------|----------|---------|------------|-----------|--------|---------|
    - **Differences Found**: list each `[DIFF]` from Task 4 (timestamp delta, prefix, zone format)
    - **Conformance Verdict**: PASS / PARTIAL / FAIL with justification
    - **Impact Assessment**: note if any difference would cause CSR rejection in production
  - [ ] 6.2 If all mandatory fields match (id_token, account, event_code, crc_valid, length): verdict = PASS
  - [ ] 6.3 If minor differences (timestamp, prefix): verdict = PARTIAL — document and confirm CSR still ACKs

- [ ] Task 7: Run full test suite — verify no regressions (AC: all)
  - [ ] 7.1 `python3 -m pytest tests/level1/ -v` — all pass
  - [ ] 7.2 `python3 -m pytest tests/level2/ tests/level2_5/ -v` — all pass
  - [ ] 7.3 `python3 -m pytest tests/level3/ -v` — all pass
  - [ ] 7.4 `find core/ desktop/ -name "*.php" | xargs -n1 php -l` — all pass

---

## Dev Notes

### Story Nature: Manual + Scripted Capture

This story is **hybrid**: it requires hands-on hardware access (Ajax panel + Wireshark on VM) for Tasks 1–2, and Python scripting for the comparison tool in Task 3. Tasks 3–7 can be completed independently of the hardware capture if golden test data already exists.

If the Ajax panel is not available, **Tasks 1–2 can be skipped** and the comparison validated against CSR Simulator-generated frames only. Document the limitation in the conformance report.

### Key File: `compare_frames.py`

This is the primary deliverable. It must:
- Import from `resources.siadc09d.sia_protocol` using project-relative imports:
  ```python
  import sys
  from pathlib import Path
  sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root
  from resources.siadc09d.sia_protocol import decode, ParsedMessage
  from resources.siadc09d.simulate_frames import parse_hex_file
  ```
- Read only the **first frame** from each hex file (subsequent frames may be supervision retries)
- Use `decode(frame.hex(), key=None)` — no decryption for conformance (unencrypted IMA Protect preset)
- Call `parse_hex_file(path)` (from `simulate_frames.py`) to read hex files — do NOT reinvent hex parsing

### Existing Tools to Reuse

| Tool | Module | Use |
|------|--------|-----|
| Hex file parser | `simulate_frames.parse_hex_file(filepath)` → `list[bytes]` | Read `.hex` files |
| Frame decoder | `sia_protocol.decode(raw_hex, key=None)` → `ParsedMessage` | Parse all fields |
| PCAP extractor | `extract_frames_from_pcap.py` (CLI) | Extract from Wireshark capture |
| Frame replayer | `simulate_frames.py` (CLI) | Verify frames ACK against simulator |

**DO NOT** re-implement hex parsing, CRC computation, or frame decoding — all exist.

### `ParsedMessage` Fields Used in Comparison

```python
# All fields available after decode():
msg.id_token          # "SIA-DCS" (without encrypted marker)
msg.encrypted         # False (unencrypted IMA Protect preset)
msg.sequence          # int — sequence number
msg.account           # "000001" — must match between Ajax and ours
msg.data_raw          # "[#000001|BA Piece1]" — full data block
msg.receiver_prefix   # "" or "R0" — informational
msg.account_prefix    # "L0" — informational
msg.timestamp_str     # "_HH:MM:SS,MM-DD-YYYY" — will differ (always)
msg.length_declared   # int — must match
msg.crc_valid         # bool — must be True for both
```

### Event Code Extraction from `data_raw`

The data block `[#000001|BA Piece1]` contains the event code after `|`. Extract it:
```python
import re

def extract_event_code(data_raw: str) -> str | None:
    """Extract event code (BA/FA/PA/NULL/0000) from data block."""
    m = re.search(r'\|([A-Z]+|\d+)', data_raw)
    return m.group(1) if m else None
```

For supervision frames, `data_raw` is `[#000001|0000]` — event code is `"0000"` (SIA_NULL_CODE).

### Frame Directory Layout

```
test_data/                        # NEW — created by this story
└── protocol_conformance/
    ├── ajax_burglary.hex          # Captured Ajax burglary frame
    ├── ajax_fire.hex              # Captured Ajax fire frame
    ├── ajax_panic.hex             # Captured Ajax panic frame
    ├── ajax_supervision.hex       # Captured Ajax supervision NULL
    ├── our_burglary.hex           # Our daemon burglary frame
    ├── our_fire.hex               # Our daemon fire frame
    ├── our_panic.hex              # Our daemon panic frame
    ├── our_supervision.hex        # Our daemon supervision NULL
    ├── compare_frames.py          # Comparison script (PRIMARY DELIVERABLE)
    └── conformance_report.md      # Written findings
```

**Note:** `test_data/` is at the project root (same level as `tests/`, `resources/`, `core/`). It is NOT inside `tests/` because it contains real capture artifacts, not pytest test files.

### Splitting Raw Captures into Per-Event Files

After extracting all frames to a single `.hex` file (one frame per line), split by inspecting the event code:
```python
from resources.siadc09d.sia_protocol import decode
from resources.siadc09d.simulate_frames import parse_hex_file
import re

frames = parse_hex_file("/tmp/ajax_all.hex")
for frame in frames:
    msg = decode(frame.hex())
    m = re.search(r'\|([A-Z]+|\d+)', msg.data_raw)
    code = m.group(1) if m else "UNKNOWN"
    print(f"  code={code}  seq={msg.sequence}  hex={frame.hex()[:20]}...")
```

Map: `BA` → burglary, `FA` → fire, `PA` → panic, `0000` → supervision.

### What to Document When Differences Are Found

Acceptable differences (PARTIAL PASS):
- **Timestamp** — always differs (wall-clock time). Document delta; confirm < 5s is fine.
- **Sequence number** — independent counters per system. Don't compare sequence values, only that both are non-zero.
- **Zone name** — Ajax sends its own zone label; ours uses Jeedom zone config. Document if different.
- **Receiver prefix** — Ajax may send `R0L0#` while ours sends `L0#` (no receiver prefix by default). Document.

Blockers (FAIL):
- **id_token mismatch** — both must be `SIA-DCS`; encrypted marker (`*`) must agree
- **account mismatch** — must be identical
- **event code mismatch** — `BA`/`FA`/`PA`/`0000` must match
- **CRC invalid** — `crc_valid=False` on either frame means a protocol bug

### Previous Story Context (11-3 Learnings Applied)

From Story 11-3 dev notes:
- `decode()` is in `sia_protocol.py` — `ParsedMessage` dataclass, import `from resources.siadc09d.sia_protocol import decode`
- `parse_hex_file()` is in `simulate_frames.py` — returns `list[bytes]`
- Frame discrimination: supervision uses `|0000]` in data block; alarm uses `|BA]` / `|FA]` / `|PA]`
- `_EVENT_SIA_CODES` in `daemon.py`: `{"burglarAlarm": "BA", "fireAlarm": "FA", "panicAlarm": "PA"}`
- `simulate_frames.py` replay CLI is the correct tool to verify CSR ACKs — no need to write a custom sender

### Testing Rules for `compare_frames.py`

The script itself is **not a pytest test file** — it is a CLI comparison tool. However, add a minimal pytest smoke test in `tests/level1/` to verify the script's logic in isolation (no real captures needed):

```python
# tests/level1/test_compare_frames.py  (NEW — minimal)
# Smoke test: compare_frames logic using the golden fixture
# tests/fixtures/golden/capture_sia_example_extracted.hex
```

Use the golden fixture at `tests/fixtures/golden/capture_sia_example_extracted.hex` as both ajax_frame and our_frame for the unit test — they will match trivially (same file), confirming the script mechanics work without real Ajax captures.

### Deferred Issues (do not address in this story)

- **D-32** (golden hex timestamp hardcoded in create_golden_hex) — pre-existing, unrelated
- **D-33** (non-Ethernet link layers drop silently) — pre-existing; if capture uses `-i lo` add `--direction both`
- **D-34** (zero-frames exits 0) — pre-existing; check frame count after extraction

---

## Dev Agent Record

### Agent Model Used

(to be filled by dev agent)

### Completion Notes List

(to be filled)

### File List

- `test_data/protocol_conformance/compare_frames.py` (new)
- `test_data/protocol_conformance/conformance_report.md` (new)
- `test_data/protocol_conformance/ajax_burglary.hex` (new — captured, may be empty placeholder if Ajax unavailable)
- `test_data/protocol_conformance/ajax_fire.hex` (new)
- `test_data/protocol_conformance/ajax_panic.hex` (new)
- `test_data/protocol_conformance/ajax_supervision.hex` (new)
- `test_data/protocol_conformance/our_burglary.hex` (new)
- `test_data/protocol_conformance/our_fire.hex` (new)
- `test_data/protocol_conformance/our_panic.hex` (new)
- `test_data/protocol_conformance/our_supervision.hex` (new)
- `tests/level1/test_compare_frames.py` (new — smoke test only)

## Change Log

| Date | Change |
|------|--------|
| 2026-06-01 | Created story for Epic 11.1 |
