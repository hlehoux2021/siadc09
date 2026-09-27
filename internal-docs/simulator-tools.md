# SIA DC-09 Simulator & Testing Tools

A self-contained toolkit for testing SIA DC-09-2021.17 (Internet Protocol Event Reporting) implementations. No Jeedom installation required.

---

## Overview

The toolkit provides four cooperating tools for end-to-end protocol validation:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SIA DC-09 Tool Suite                         │
├──────────────────┬──────────────────────────────────────────────┤
│  Real Alarm      │  Wireshark capture                          │
│  Panel / Daemon  │  (.pcap file)                               │
└────────┬─────────┘        │                                     │
         │ UDP/TCP          │ ② PCAP Extractor                    │
         │ port 10001       ▼ extract_frames_from_pcap.py         │
         ▼            ┌──────────┐                                │
  ① CSR Simulator ◄───│ .hex     │ ③ Frame Replay                 │
    tests.simulator   │ fixture  │──► simulate_frames.py          │
    (ACK/NAK)         └──────────┘        │                       │
                                          │ ACK/NAK               │
                    ④ Test Harness         │                       │
                    run_harness.py ────────┘ (orchestrates 1–3)   │
└─────────────────────────────────────────────────────────────────┘
```

| Tool | File | Purpose |
|------|------|---------|
| **CSR Simulator** | `tests/simulator/__main__.py` | Listens for SIA frames, responds ACK/NAK |
| **PCAP Extractor** | `resources/siadc09d/extract_frames_from_pcap.py` | Extracts client frames from Wireshark captures |
| **Frame Replay** | `resources/siadc09d/simulate_frames.py` | Replays `.hex` fixture files against any SIA endpoint |
| **Test Harness** | `tests/harness/run_harness.py` | Orchestrates simulator + replay for automated pass/fail |

---

## Quick Start

**One-command automated run** (harness handles simulator lifecycle automatically):

```bash
python3 -m pip install -r tests/requirements-dev.txt
python3 tests/harness/run_harness.py
```

**Manual path** (start simulator and replay tool separately):

```bash
# 1. Clone and install dev dependencies
git clone <repo>
cd <repo>
python3 -m pip install -r tests/requirements-dev.txt

# 2. Start the CSR Simulator on default port 10001
python3 -m tests.simulator

# 3. In a second terminal, replay golden test frames against it
python3 resources/siadc09d/simulate_frames.py \
  --input tests/fixtures/golden/frames_alarm_burglary.hex \
  --port 10001
```

---

## Installation

**Requirements:** Python 3.10+, no Jeedom needed.

```bash
python3 -m pip install -r tests/requirements-dev.txt
```

`tests/requirements-dev.txt` provides:
- `dpkt>=1.9.8` — pcap parsing (PCAP Extractor only)
- `pytest>=7.0` — test runner (Test Harness tests only)

All other functionality uses the Python standard library.

**Verify standalone install:**

```bash
python3 -m tests.simulator --help
python3 resources/siadc09d/simulate_frames.py --help
python3 resources/siadc09d/extract_frames_from_pcap.py --help
python3 tests/harness/run_harness.py --help
```

---

## Tool Reference

### ① CSR Simulator

Simulates a Central Station Receiver — listens on UDP and TCP, responds with ACK for valid frames and NAK for malformed frames.

**Start with defaults (UDP :10001, TCP :5000):**

```bash
python3 -m tests.simulator
```

**Full options:**

```bash
python3 -m tests.simulator \
  --udp-port 10001 \
  --tcp-port 5000 \
  --host 127.0.0.1 \
  --account 001234 \
  --crc-format hex \
  --encryption-key 0123456789ABCDEF0123456789ABCDEF \
  --log-file /tmp/csr_frames.log \
  --log-level DEBUG
```

| Option | Default | Description |
|--------|---------|-------------|
| `--udp-port PORT` | 10001 | UDP listening port |
| `--tcp-port PORT` | 5000 | TCP listening port |
| `--host HOST` | 127.0.0.1 | Bind address |
| `--account ACCOUNT` | 000001 | CSR account number (3–16 hex chars) |
| `--crc-format {hex,bin}` | hex | CRC encoding: 4 ASCII hex chars or 2 binary bytes |
| `--encryption-key KEY` | (none) | AES-128 key as 32 hex chars |
| `--log-file FILE` | (none) | Write frame log to file |
| `--log-level LEVEL` | INFO | DEBUG, INFO, WARNING, or ERROR |

**Response behavior:**

- Valid frames (SIA-DCS, ACK, NULL) → **ACK** with echoed sequence number
- Encrypted inbound (`*SIA-DCS` marker) → **encrypted ACK**
- Malformed/unknown → **NAK** (always plaintext, seq=0000)

See [tests/simulator/README.md](../tests/simulator/README.md) for complete CLI reference.

---

### ② PCAP Extractor

Extracts SIA DC-09 frames from a Wireshark `.pcap` or `.pcapng` capture and writes them as a `.hex` fixture file.

```bash
python3 resources/siadc09d/extract_frames_from_pcap.py \
  capture.pcap \
  --output extracted.hex \
  --port 10001 \
  --direction client
```

| Option | Default | Description |
|--------|---------|-------------|
| `input` | — | Path to `.pcap` / `.pcapng` file (positional) |
| `--output FILE` | — | Output `.hex` file path (required) |
| `--port PORT` | 10001 | SIA DC-09 port to filter |
| `--direction {client,server,both}` | both | `client` = alarm-to-CSR frames only |
| `--verbose` | off | Enable debug logging |

**Direction filter:**

- `client` — captures frames sent *from* the alarm panel to the CSR (what you want to replay)
- `server` — captures ACK/NAK responses *from* the CSR
- `both` — all frames on the port

---

### ③ Frame Replay

Reads a `.hex` fixture file and sends each frame to any SIA endpoint, collecting responses.

```bash
python3 resources/siadc09d/simulate_frames.py \
  --input tests/fixtures/golden/frames_alarm_burglary.hex \
  --port 10001 \
  --protocol udp \
  --timeout 2.0
```

| Option | Default | Description |
|--------|---------|-------------|
| `--input FILE` | — | Hex fixture file path (required) |
| `--port PORT` | — | Destination port (required) |
| `--protocol {udp,tcp}` | udp | Transport protocol |
| `--host HOST` | localhost | Destination host |
| `--delay-between-frames MS` | 0 | Pause between frames in milliseconds |
| `--timeout S` | 2.0 | Response timeout per frame in seconds |
| `--output FILE` | (none) | Save results as JSON |
| `--verbose` | off | Enable debug logging |

Exit codes: `0` = all frames responded, `1` = runtime error, `2` = usage error.

---

### ④ Test Harness

Orchestrates a complete automated pass/fail run: starts the simulator in-process, replays all `tests/fixtures/golden/frames_*.hex` files, and prints a summary table.

```bash
python3 tests/harness/run_harness.py
```

**With options:**

```bash
python3 tests/harness/run_harness.py \
  --crc-format hex \
  --encryption-key 0123456789ABCDEF0123456789ABCDEF \
  --port 10002
```

| Option | Default | Description |
|--------|---------|-------------|
| `--encryption-key KEY` | (none) | AES-128 key as 32 hex chars |
| `--crc-format {hex,bin}` | hex | CRC encoding format |
| `--port PORT` | OS-assigned | UDP port (default: ephemeral) |

**Sample output:**

```
SIA DC-09 Test Harness — crc_format=hex, encrypted=no
Fixtures: tests/fixtures/golden

  [PASS] frames_alarm_burglary.hex            1/1 responses  (0 timeout)  [OK]
  [PASS] frames_alarm_fire.hex                1/1 responses  (0 timeout)  [OK]
  [PASS] frames_encrypted_alarm.hex           1/1 responses  (0 timeout)  [OK]
  [PASS] frames_malformed.hex                 2/3 responses  (1 timeout)  [MALFORMED]
  [PASS] frames_mixed_sequence.hex            3/3 responses  (0 timeout)  [OK]
  [PASS] frames_supervision_null.hex          1/1 responses  (0 timeout)  [OK]

Harness: 8/9 frames passed (8 ACK/NAK, 0 timeout)
```

Exit code `0` = all non-malformed frames responded; `1` = failures. Malformed frames (`frames_malformed.hex`) are excluded from failure counting — timeouts on intentionally invalid frames are expected.

---

## Example Workflow: Testing an Ajax Alarm Panel

This walkthrough captures real SIA DC-09 traffic from an Ajax alarm panel, extracts the frames, and validates them against the simulator.

### Step 1: Capture Traffic with Wireshark

Start Wireshark on the interface your alarm panel uses to reach the CSR. Filter for the SIA port:

```
udp.port == 10001 or tcp.port == 10001
```

Trigger an alarm event from your panel (e.g., open a door sensor). Stop capture and save as `ajax_capture.pcap`.

### Step 2: Extract Client Frames

Extract only the frames sent *from* the alarm panel (client direction):

```bash
python3 resources/siadc09d/extract_frames_from_pcap.py \
  ajax_capture.pcap \
  --output ajax_alarm_frames.hex \
  --port 10001 \
  --direction client \
  --verbose
```

Verify the output:

```bash
cat ajax_alarm_frames.hex
# Should show one or more hex frame lines prefixed with comments
```

### Step 3: Start the Simulator with Matching Config

Match the simulator's account number and encryption key to your panel's CSR configuration:

```bash
python3 -m tests.simulator \
  --udp-port 10001 \
  --account <YOUR_PANEL_ACCOUNT> \
  --encryption-key <YOUR_KEY_IF_ENCRYPTED> \
  --log-level DEBUG
```

For a panel sending plaintext frames:

```bash
python3 -m tests.simulator --udp-port 10001 --account 001234
```

### Step 4: Replay Captured Frames

```bash
python3 resources/siadc09d/simulate_frames.py \
  --input ajax_alarm_frames.hex \
  --port 10001 \
  --protocol udp \
  --verbose
```

### Step 5: Validate Responses

Expected output for a valid alarm panel:

```
Frame 1: sent 62 bytes → ACK received (seq=0001) — 12ms
Frame 2: sent 38 bytes → ACK received (seq=0002) — 8ms
Result: 2/2 frames got response (0 timeout)
```

If you see `timeout` instead of `ACK`:
- Check that the panel's account number matches `--account`
- Verify CRC format (try `--crc-format bin` for binary CRC panels)
- Check encryption key (look for `*SIA-DCS` in the hex output vs `"SIA-DCS"`)

---

## Golden Test Fixtures

Pre-built test frames in `tests/fixtures/golden/` covering all standard scenarios:

| File | Frames | Description |
|------|--------|-------------|
| `frames_alarm_burglary.hex` | 1 | Burglary alarm, event code 1130, account 001234, seq 0001 |
| `frames_alarm_fire.hex` | 1 | Fire alarm, event code 2130 or similar, account 001234 |
| `frames_supervision_null.hex` | 1 | Supervision NULL frame, account 001234, seq 0002 |
| `frames_mixed_sequence.hex` | 3 | Burglary (seq=0001) → NULL (seq=0002) → Fire (seq=0003) |
| `frames_encrypted_alarm.hex` | 1 | Encrypted burglary alarm (`*SIA-DCS` marker), AES-128 key `0123456789ABCDEF0123456789ABCDEF` |
| `frames_malformed.hex` | 3 | Invalid frames: missing LF, unknown token, garbled bytes — expect NAK/timeout |
| `capture_sia_example.pcap` | — | Raw Wireshark capture (UDP, port 10001) for PCAP pipeline testing |
| `capture_sia_example_extracted.hex` | — | Pre-extracted client frames from `capture_sia_example.pcap` |

**Hex file format:** one frame per non-comment line, space-separated bytes, `#` for comments:

```
# Burglary alarm frame
# Event code 1130, account 001234, seq 0001
0A 41 34 34 32 30 30 33 38 22 53 49 41 2D 44 43 53 22 30 30 30 31 4C 30 23 30 30 31 32 33 34 5B 23 30 30 31 32 33 34 7C 31 31 33 30 5D 5F 31 34 3A 32 33 3A 34 35 2C 30 34 2D 30 39 2D 32 30 32 36 0D
```

---

## Programmatic Usage

### Run the Simulator in Tests

```python
import asyncio
from contextlib import suppress
from resources.siadc09d.csr_simulator import CSRSimulator

async def example():
    preset = {
        "crc_format": "hex",
        "account_number": "001234",
        "encryption_key": None,
    }
    sim = CSRSimulator(udp_port=10001, tcp_port=5000, preset=preset)
    await sim.start()

    # IMPORTANT: _handle_udp() is not started by start() — launch it as a task
    udp_task = asyncio.create_task(sim._handle_udp())

    # ... send frames ...

    udp_task.cancel()
    with suppress(asyncio.CancelledError):
        await udp_task
    await sim.stop()
```

### Replay Frames Programmatically

```python
from resources.siadc09d.simulate_frames import parse_hex_file, replay_frames

frames = parse_hex_file("tests/fixtures/golden/frames_alarm_burglary.hex")

results, ack_count, timeout_count = await replay_frames(
    frames,
    host="127.0.0.1",
    port=10001,
    protocol="udp",
    timeout_s=2.0,
)

print(f"{ack_count}/{len(frames)} frames responded ({timeout_count} timeout)")
```

### Extract Frames from Pcap Programmatically

```python
from resources.siadc09d.extract_frames_from_pcap import read_pcap, filter_frames, write_hex_file

packets = read_pcap("capture.pcap")
filtered = filter_frames(packets, port=10001, direction="client")
write_hex_file(filtered, "output.hex", source_file="capture.pcap", port=10001, direction="client")
```

### Run the Full Harness Programmatically

```python
import asyncio
from tests.harness.run_harness import run_harness

total_frames, ack_count, timeout_count = asyncio.run(
    run_harness(
        encryption_key=None,
        crc_format="hex",
    )
)

assert timeout_count == 0, f"Harness failures: {timeout_count} timeouts"
```

### pytest Integration

The harness ships with pytest tests in `tests/level1/test_harness.py`:

```bash
python3 -m pytest tests/level1/test_harness.py -v
```

---

## Protocol Reference

**Full spec:** `internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`

### Frame Structure (§ 5.5)

```
[LF] [CRC] [Length] [Message] [CR]
0x0A  ^^^^   ^^^^   variable  0x0D
```

- **LF** (`0x0A`): start delimiter
- **CRC**: CRC-16 MODBUS over the message bytes
  - Hex format: 4 ASCII hex characters (e.g., `A1B2`)
  - Binary format: 2 bytes little-endian
- **Length**: 4 ASCII hex digits, byte count of message field
- **Message**: `"<id_token>"<seq>R<receiver>L<line>#<account>[<data>]`
- **CR** (`0x0D`): end delimiter

### Message Fields

| Field | Example | Description |
|-------|---------|-------------|
| `id_token` | `"SIA-DCS"` | Frame type; `"*SIA-DCS"` = encrypted |
| `seq` | `0001` | 4-digit sequence number (0001–9999) |
| `receiver` | `R0` | Receiver number |
| `line` | `L0` | Line number |
| `account` | `#001234` | Account number (3–16 hex chars) |
| `data` | `[#001234\|1130]` | Alarm data payload |

### Event Codes

| Code | Description |
|------|-------------|
| `1130` | Burglary alarm |
| `2130` | Fire alarm |
| `0000` | NULL / supervision |

### ACK/NAK Behavior

| Response | When | Sequence |
|----------|------|----------|
| `"ACK"` | Valid frame received | Echoes inbound `seq` |
| `"NAK"` | Malformed or unrecognized frame | Always `0000` |

ACK for encrypted frames uses `"*ACK"` id_token and AES-128-CBC encryption with the same key used on the inbound frame. NAK is always plaintext regardless of encryption configuration.

---

## See Also

- [tests/simulator/README.md](../tests/simulator/README.md) — CSR Simulator CLI complete reference
- `resources/siadc09d/csr_simulator.py` — Simulator library (programmatic API)
- `resources/siadc09d/sia_protocol.py` — Protocol encode/decode
- `resources/siadc09d/sia_crypto.py` — AES-128-CBC encryption
