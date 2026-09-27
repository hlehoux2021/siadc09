#!/usr/bin/env python3
"""End-to-end test harness for SIA DC-09 frame replay against the CSR Simulator.

Orchestrates a complete test run:
  1. Starts CSRSimulator in-process on an ephemeral port.
  2. Discovers all golden hex fixtures (tests/fixtures/golden/frames_*.hex).
  3. Replays each file via replay_frames() and captures ACK/NAK/timeout.
  4. Prints a summary table.
  5. Exits 0 if all non-malformed frames got a response; 1 on failures.

Usage::

    python3 tests/harness/run_harness.py
    python3 tests/harness/run_harness.py --encryption-key 0123456789ABCDEF0123456789ABCDEF
    python3 tests/harness/run_harness.py --crc-format bin --port 10002

Reference: internal-docs/simulator-tools.md § "Test Harness"
"""

import argparse
import asyncio
import logging
import socket
import sys
from contextlib import suppress
from pathlib import Path
from typing import Literal

# Support running from project root without installation
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resources.siadc09d.csr_simulator import CSRSimulator, CSRSimulatorPreset  # pylint: disable=wrong-import-position,import-error
from resources.siadc09d.sia_protocol import decode_ack_nak  # pylint: disable=wrong-import-position,import-error
from resources.siadc09d.simulate_frames import parse_hex_file, replay_frames  # pylint: disable=wrong-import-position,import-error

# ===== Constants =====

GOLDEN_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "golden"
FRAME_FILE_PATTERN = "frames_*.hex"
MALFORMED_FIXTURE = "frames_malformed.hex"
ACCOUNT_NUMBER_DEFAULT = "001234"
CRC_FORMAT_DEFAULT = "hex"
TIMEOUT_S = 2.0
RESPONSE_DELAY_MS = 0

EXIT_OK = 0
EXIT_FAILURE = 1


# ===== Harness Logic =====


def _find_golden_files(golden_dir: Path) -> list[Path]:
    """Return sorted list of frames_*.hex files in golden_dir.

    Args:
        golden_dir: Directory containing golden fixtures.

    Returns:
        Sorted list of hex fixture paths.
    """
    return sorted(golden_dir.glob(FRAME_FILE_PATTERN))


def _get_free_port() -> int:
    """Return an OS-assigned free port.

    Returns:
        Available TCP/UDP port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def run_harness(  # pylint: disable=too-many-locals
    *,
    encryption_key: bytes | None = None,
    crc_format: Literal["hex", "bin"] = CRC_FORMAT_DEFAULT,
    port: int | None = None,
) -> tuple[int, int, int]:
    """Run the end-to-end harness against all golden fixtures.

    Starts simulator in-process, replays every frames_*.hex file, and
    prints a per-file result line plus a final summary.

    Args:
        encryption_key: Optional AES-128 key bytes (16 bytes). None = plaintext.
        crc_format: CRC encoding format — ``"hex"`` or ``"bin"``.
        port: UDP port for the simulator. None → OS-assigned ephemeral port.

    Returns:
        Tuple ``(total_frames, ack_count, timeout_count)`` where ``ack_count``
        counts only frames that received an ACK (NAK responses are counted
        separately in the printed summary).
    """
    udp_port = port if port is not None else _get_free_port()

    preset: CSRSimulatorPreset = {
        "crc_format": crc_format,
        "account_number": ACCOUNT_NUMBER_DEFAULT,
        "encryption_key": encryption_key,
    }

    simulator = CSRSimulator(udp_port=udp_port, tcp_port=udp_port + 1, preset=preset)
    await simulator.start()

    # _handle_udp() is not started by sim.start() — must be launched as a task.
    udp_task = asyncio.create_task(simulator._handle_udp(), name="harness_udp_recv")  # pylint: disable=protected-access

    golden_files = _find_golden_files(GOLDEN_DIR)
    if not golden_files:
        print(f"WARNING: no fixtures found in {GOLDEN_DIR}")
        await simulator.stop()
        udp_task.cancel()
        with suppress(asyncio.CancelledError):
            await udp_task
        return 0, 0, 0

    total_frames = 0
    total_ack = 0
    total_nak = 0
    total_timeout = 0

    try:
        for fixture_path in golden_files:
            frames = parse_hex_file(str(fixture_path))
            if not frames:
                continue

            results, _, timeout_count = await replay_frames(
                frames,
                host="127.0.0.1",
                port=udp_port,
                protocol="udp",
                timeout_s=TIMEOUT_S,
                delay_ms=RESPONSE_DELAY_MS,
            )

            ack_count = sum(
                1 for r in results
                if r["response"] is not None
                and decode_ack_nak(r["response"], crc_format).get("type") == "ACK"
            )
            nak_count = sum(
                1 for r in results
                if r["response"] is not None
                and decode_ack_nak(r["response"], crc_format).get("type") == "NAK"
            )

            # Malformed fixtures are expected to produce responses too (NAK),
            # but we count non-responses (timeout) only as failures for non-malformed files.
            is_malformed = fixture_path.name == MALFORMED_FIXTURE

            label = "MALFORMED" if is_malformed else "OK"
            status = "PASS" if (is_malformed or timeout_count == 0) else "FAIL"

            print(
                f"  [{status}] {fixture_path.name:<42}  "
                f"{ack_count} ACK  {nak_count} NAK  "
                f"({timeout_count} timeout)  [{label}]"
            )

            total_frames += len(frames)
            total_ack += ack_count
            total_nak += nak_count
            total_timeout += (0 if is_malformed else timeout_count)

    finally:
        await simulator.stop()
        udp_task.cancel()
        with suppress(asyncio.CancelledError):
            await udp_task

    print(
        f"\nHarness: {total_ack}/{total_frames} frames passed "
        f"({total_ack} ACK, {total_nak} NAK, {total_timeout} timeout)"
    )

    return total_frames, total_ack, total_timeout


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end harness: replay all golden SIA frames against the CSR Simulator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--encryption-key",
        metavar="HEX",
        help="AES-128 encryption key as 32 hex chars (e.g. 0123456789ABCDEF0123456789ABCDEF)",
    )
    parser.add_argument(
        "--crc-format",
        choices=["hex", "bin"],
        default=CRC_FORMAT_DEFAULT,
        help=f"CRC encoding format (default: {CRC_FORMAT_DEFAULT})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="UDP port for simulator (default: OS-assigned ephemeral port)",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for CLI invocation."""
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args()

    encryption_key: bytes | None = None
    if args.encryption_key:
        raw = args.encryption_key.replace(" ", "")
        if len(raw) != 32:
            print(f"ERROR: --encryption-key must be exactly 32 hex chars, got {len(raw)}")
            sys.exit(EXIT_FAILURE)
        try:
            encryption_key = bytes.fromhex(raw)
        except ValueError:
            print(f"ERROR: --encryption-key is not valid hex: {args.encryption_key!r}")
            sys.exit(EXIT_FAILURE)

    print(f"SIA DC-09 Test Harness — crc_format={args.crc_format}, "
          f"encrypted={'yes' if encryption_key else 'no'}")
    print(f"Fixtures: {GOLDEN_DIR}")
    print()

    _, _, total_timeout = asyncio.run(
        run_harness(
            encryption_key=encryption_key,
            crc_format=args.crc_format,
            port=args.port,
        )
    )

    sys.exit(EXIT_OK if total_timeout == 0 else EXIT_FAILURE)


if __name__ == "__main__":
    main()
