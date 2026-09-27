# CSR Simulator CLI Tool

Standalone command-line interface for the CSR (Central Station Receiver) Simulator. This tool tests SIA DC-09-2021.17 alarm implementation without connecting to a real CSR.

Built on `CSRSimulator` — a reusable protocol testing framework.

**For the full tool suite** (simulator + frame replay + PCAP extractor + test harness), see [internal-docs/simulator-tools.md](../../internal-docs/simulator-tools.md).

---

## Quick Start

### Basic Usage (Default Ports)

```bash
python3 -m tests.simulator
```

Starts simulator on:
- **UDP:** localhost:10001
- **TCP:** localhost:5000

### Custom Ports

```bash
python3 -m tests.simulator --udp-port 8888 --tcp-port 4444
```

### With Encryption (AES-128)

```bash
python3 -m tests.simulator \
  --encryption-key 0123456789ABCDEF0123456789ABCDEF \
  --crc-format hex
```

### Custom Account Number

```bash
python3 -m tests.simulator --account ABCD12
```

Account numbers must be 3-16 hexadecimal characters.

### Log All Frames to File

```bash
python3 -m tests.simulator \
  --log-file /tmp/csr_frames.log \
  --log-level DEBUG
```

### Full Example (All Options)

```bash
python3 -m tests.simulator \
  --udp-port 10001 \
  --tcp-port 5000 \
  --host 127.0.0.1 \
  --encryption-key 0123456789ABCDEF0123456789ABCDEF \
  --crc-format hex \
  --account 000001 \
  --log-file /tmp/simulator.log \
  --log-level DEBUG
```

---

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--udp-port PORT` | 10001 | UDP listening port |
| `--tcp-port PORT` | 5000 | TCP listening port |
| `--host HOST` | 127.0.0.1 | Listening host/IP address |
| `--crc-format {hex,bin}` | hex | CRC encoding: hex (4 ASCII chars) or bin (2 bytes) |
| `--account ACCOUNT` | 000001 | CSR account number (3-16 hex chars) |
| `--encryption-key KEY` | (none) | AES-128 encryption key (32-char hex string) |
| `--log-file FILE` | (none) | Log frames to file |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | INFO | Logging level |
| `--help` | — | Show help message |
| `--version` | — | Show version |

---

## Configuration Examples

### Testing With Jeedom Daemon

For integration testing with the Jeedom SIA plugin daemon:

```bash
# Terminal 1: Start simulator
python3 -m tests.simulator --udp-port 10001 --tcp-port 5000

# Terminal 2: Test daemon connection
python3 resources/siadc09d/daemon.py \
  --csr-host 127.0.0.1 \
  --csr-port 5000 \
  --csr-protocol tcp
```

### Testing Frame Reception

Create a test client that sends SIA DC-09 frames:

```python
import socket

# Connect to simulator
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b'\x0AAABBCCDD0010"SIA-DCS"0001R0L0#000001[]\x0D', ('127.0.0.1', 10001))
sock.close()
```

### Response Behavior

The simulator automatically responds to incoming frames with ACK or NAK:

#### ACK Response (Valid Frames)

Valid frames receive ACK with echoed sequence number:

```
Inbound:  [ALARM with seq=0042]
Response: [ACK with seq=0042]
```

**ACK responds to:**
- ALARM frames (burglary, fire, panic) → echoes sequence number
- NULL frames (supervision) → always seq=0000 in response
- ACK frames (echo) → echoes sequence number

**Encryption:**
- If inbound was encrypted, ACK response is also encrypted (AES-128 CBC)
- Encryption marker: `*ACK` in plaintext, `ACK` if unencrypted
- Uses preset encryption key if configured

#### NAK Response (Malformed Frames)

Malformed or invalid frames receive NAK:

```
Inbound:  [ALARM with invalid CRC]
Response: [NAK with seq=0000]
```

**NAK responds to:**
- Frames with invalid CRC-16 MODBUS checksum
- Frames with missing/invalid delimiters (LF/CR)
- Frames truncated or incomplete
- Unknown/unparseable frame types

**Encryption:**
- NAK is **never encrypted**, even if key configured (per SIA spec)
- Always plaintext: `NAK0000...`

#### Response Timing

By default, responses are sent immediately (0ms latency). Configure delay:

```bash
# 100ms response delay for network simulation
python3 -m tests.simulator --response-delay 100
```

Log output shows timing:
```
[RX] ALARM seq=0042 (plaintext) 2026-04-09T14:23:45.123456+00:00
[TX] ACK seq=0042 (plaintext) 2026-04-09T14:23:45.124123+00:00
```

### Viewing Frame Logs

```bash
# Monitor log in real-time
tail -f /tmp/csr_frames.log

# Filter for ACK frames only
grep "ACK" /tmp/csr_frames.log

# Count frames per second
cat /tmp/csr_frames.log | wc -l
```

### Frame Format Reference

All frames follow the SIA DC-09-2021 structure:

**Complete Frame:**
```
[LF] + [CRC] + [Length] + [Message] + [CR]
0x0A + {4 hex or 2 bin} + {4 hex} + {variable} + 0x0D
```

**ACK Message Format:**
```
"ACK"<seq>R0L0#<account>[]
```
- **Example:** `"ACK"0042R0L0#000001[]`
- `seq`: 4-digit sequence number from inbound frame
- `account`: CSR account number from preset

**NAK Message Format:**
```
"NAK"0000R0L0A0[]
```
- **Note:** NAK always has seq=0000 (never echoes inbound)
- Never encrypted per SIA spec
- Sent in response to malformed/invalid frames

**CRC Format (Preset-Configured):**

Hex format (default):
```
Frame: 0A + 1A2B + 001C + "ACK"0001... + 0D
       (LF) (4-char hex CRC) (4-char hex len)
```

Binary format:
```
Frame: 0A + [2-byte binary CRC] + 001C + "ACK"0001... + 0D
       (LF) (little-endian CRC) (4-char hex len)
```

Reference: [SIA DC-09-2021 § 5.5.1-5.5.3](../../internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md)

---

## Frame Logging Format

When `--log-file` is specified, frames are logged as:

```
timestamp | direction | frame_type | sequence | encryption | raw_hex
2026-04-09T14:23:45.123456Z | RX | ALARM | 0001 | plaintext | 0AAABBCCDD...
2026-04-09T14:23:45.234567Z | TX | ACK | 0001 | plaintext | 0AAA1234...
```

- **timestamp:** ISO 8601 UTC (timezone-aware)
- **direction:** RX (received) or TX (transmitted)
- **frame_type:** ALARM, ACK, NAK, NULL, or UNKNOWN
- **sequence:** 4-digit sequence number (0001-9999)
- **encryption:** plaintext or encrypted (AES-128)
- **raw_hex:** Complete frame in hexadecimal (including LF/CR delimiters)

---

## Troubleshooting

### "Port already in use"

Another process is using the port. Find and stop it:

```bash
# macOS/Linux
lsof -i :10001

# Kill the process
kill -9 <PID>
```

Or use different ports:

```bash
python3 -m tests.simulator --udp-port 18888 --tcp-port 14444
```

### "Permission denied" on port <1024

Non-root users cannot bind to ports below 1024. Use ports >= 1024 or run with `sudo` (not recommended).

### Invalid encryption key format

Encryption key must be a 32-character hexadecimal string (16 bytes). Valid example:

```bash
# ✅ Valid: 16 bytes = 32 hex chars
python3 -m tests.simulator --encryption-key 0123456789ABCDEF0123456789ABCDEF

# ❌ Invalid: only 16 hex chars (8 bytes, need 16)
python3 -m tests.simulator --encryption-key 0123456789ABCDEF
```

### Invalid account format

Account must be 3-16 hexadecimal characters:

```bash
# ✅ Valid
python3 -m tests.simulator --account ABC  # 3 chars
python3 -m tests.simulator --account 000001  # 6 chars
python3 -m tests.simulator --account ABCDEF0123456789  # 16 chars

# ❌ Invalid
python3 -m tests.simulator --account AB  # Too short
python3 -m tests.simulator --account ABCDEFG  # Non-hex character 'G'
```

### Simulator won't shut down

The simulator listens for SIGINT (Ctrl+C) and SIGTERM signals. Press **Ctrl+C** to gracefully stop.

If Ctrl+C doesn't work:
```bash
# Send SIGTERM from another terminal
kill -TERM <PID>
```

---

## Testing With Real Daemon

Once the Jeedom daemon is implemented (Epic 5), test real-time integration:

```bash
# Terminal 1: Start simulator
python3 -m tests.simulator --log-file /tmp/csr.log --log-level DEBUG

# Terminal 2: Start daemon
python3 resources/siadc09d/daemon.py --csr-host 127.0.0.1 --csr-port 5000

# Terminal 3: Monitor frames
tail -f /tmp/csr.log

# Terminal 4: Send test events via Jeedom API
# (Trigger alarm events manually or via API)
```

---

## Integration With Story 1.4

The CLI wrapper reuses Story 1.4's `CSRSimulator` class:

```python
from resources.siadc09d.csr_simulator import CSRSimulator

# Programmatic usage (for integration tests)
preset = {
    'crc_format': 'hex',
    'account_number': '000001',
    'encryption_key': None
}

simulator = CSRSimulator(udp_port=10001, tcp_port=5000, preset=preset)
await simulator.start()
# ... send frames ...
await simulator.stop()
```

See [Story 1.4 documentation](../../_bmad-output/implementation-artifacts/1-4-csr-simulator-framework.md) for protocol details.

---

## Performance Notes

- **Latency:** Simulator responds to frames with <100ms latency
- **Throughput:** Handles 100+ frames/second on typical hardware
- **Memory:** ~5MB resident memory (minimal)
- **CPU:** <1% idle, spikes during frame reception

---

## Limitations

- **Single CSR:** Only one CSR simulated per instance (multi-CSR failover in v1.5)
- **No stateful responses:** Simulator is stateless; doesn't track alarm history
- **Frame logging overhead:** File logging adds ~10ms per frame

---

## Building With This Tool

Example: Building a test harness for an alarm daemon:

```python
import asyncio
from tests.simulator import async_main as simulator_main
from your_daemon import DaemonClient

async def test_daemon_integration():
    # Start simulator in background
    simulator_task = asyncio.create_task(
        simulator_main(['--udp-port', '10001'])
    )
    
    # Wait for simulator to start
    await asyncio.sleep(0.5)
    
    # Test daemon
    daemon = DaemonClient('127.0.0.1', 5000)
    await daemon.connect()
    
    # Send test frames
    # ... your test logic ...
    
    # Cleanup
    simulator_task.cancel()
```

---

## Related Tools

The simulator is one of four cooperating tools. See [internal-docs/simulator-tools.md](../../internal-docs/simulator-tools.md) for the complete guide.

### Frame Replay

Send `.hex` fixture files to any SIA endpoint (including this simulator):

```bash
python3 resources/siadc09d/simulate_frames.py \
  --input tests/fixtures/golden/frames_alarm_burglary.hex \
  --port 10001 --protocol udp
```

Full reference: [internal-docs/simulator-tools.md § Frame Replay](../../internal-docs/simulator-tools.md#-frame-replay)

### PCAP Extractor

Extract client-side SIA frames from a Wireshark capture:

```bash
python3 resources/siadc09d/extract_frames_from_pcap.py \
  capture.pcap --output frames.hex --port 10001 --direction client
```

Full reference: [internal-docs/simulator-tools.md § PCAP Extractor](../../internal-docs/simulator-tools.md#-pcap-extractor)

### Test Harness

Runs the simulator in-process and replays all golden fixtures for automated pass/fail:

```bash
python3 tests/harness/run_harness.py
python3 tests/harness/run_harness.py --encryption-key 0123456789ABCDEF0123456789ABCDEF
```

Full reference: [internal-docs/simulator-tools.md § Test Harness](../../internal-docs/simulator-tools.md#-test-harness)

---

## Reference

- **Protocol:** SIA DC-09-2021.17 (Internet Protocol Event Reporting)
- **Spec:** `internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`
- **Core Library:** `resources/siadc09d/csr_simulator.py`
- **Full Tool Guide:** [internal-docs/simulator-tools.md](../../internal-docs/simulator-tools.md)
