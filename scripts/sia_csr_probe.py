#!/usr/bin/env python3
"""SIA DC-09 CSR probe: send hand-built SIA-DCS frames the way an Ajax hub does.

Standalone investigation tool (see internal-docs/ajax.md). Not part of the shipped
siaDC09 plugin or daemon — run manually to check how a real CSR (e.g. Scutum) displays
a data block before changing the plugin's encoder.

Session shape copied from the Ajax captures: one TCP connection, a NULL frame first
("NULL"0000L0#acct[]_ts), then each event on the same connection, each one waiting for
its ACK, then wait for the CSR to close the connection (Scutum does it ~5 s after the
last ACK).

Dry-run by default: frames are only printed. Nothing is sent without --send.

Usage:
    python3 scripts/sia_csr_probe.py --account 27099
    python3 scripts/sia_csr_probe.py --account 27099 --host 194.250.35.75 --port 10657 --send
    python3 scripts/sia_csr_probe.py --account 27099 --event Nri1/CL001 --event Nri1/BA1 --send
    python3 scripts/sia_csr_probe.py --account 27099 --event 'Nri1/BA1##[Vhttps://h/s.jpg]'
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "resources" / "siadc09d"))
from sia_protocol import _compute_crc_modbus  # noqa: E402  (reuse the plugin's CRC)

LF = b"\x0a"
CR = b"\x0d"
DEFAULT_EVENTS = ["Nri1/CL001", "Nri1/OP001"]
DEFAULT_SEQ_START = 1
ACK_TIMEOUT_S = 10.0
CLOSE_WAIT_S = 15.0
EVENT_GAP_S = 1.0
EXTENDED_SEPARATOR = "##"


def utc_timestamp() -> str:
    """Return the DC-09 timestamp, leading underscore included (_HH:MM:SS,MM-DD-YYYY)."""
    return datetime.now(timezone.utc).strftime("_%H:%M:%S,%m-%d-%Y")


def build_frame(core: str) -> bytes:
    """Wrap a message core as LF + CRC + length + core + CR (§ 5.5.1)."""
    body = core.encode("ascii")
    return LF + f"{_compute_crc_modbus(body):04X}{len(body):04X}".encode("ascii") + body + CR


def null_frame(account: str) -> bytes:
    """Ajax-style supervision frame: "NULL"0000L0#acct[]_ts."""
    return build_frame(f'"NULL"0000L0#{account}[]{utc_timestamp()}')


def split_event(spec: str) -> tuple[str, str]:
    """Split an --event value into (data, extended block); "DATA##[Vurl]" -> ("DATA", "[Vurl]")."""
    data, _, extended = spec.partition(EXTENDED_SEPARATOR)
    return data, extended


def event_frame(account: str, seq: int, spec: str) -> bytes:
    """SIA-DCS event frame: "SIA-DCS"seqL0#acct[#acct|data]<extended>_ts."""
    data, extended = split_event(spec)
    return build_frame(
        f'"SIA-DCS"{seq:04d}L0#{account}[#{account}|{data}]{extended}{utc_timestamp()}'
    )


def show(direction: str, raw: bytes) -> None:
    """Print one frame with a local wall-clock time, LF/CR stripped."""
    text = raw.strip(LF + CR).decode("ascii", errors="replace")
    print(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {direction} {text}", flush=True)


def read_frame(sock: socket.socket) -> bytes | None:
    """Read up to and including CR. Return None if the peer closed first."""
    buf = b""
    while not buf.endswith(CR):
        chunk = sock.recv(1)
        if not chunk:
            return None
        buf += chunk
    return buf


def send_and_wait_ack(sock: socket.socket, frame: bytes) -> bool:
    """Send one frame and print the reply. Return False if the connection closed."""
    show("->", frame)
    sock.sendall(frame)
    reply = read_frame(sock)
    if reply is None:
        print("   connection closed by the CSR before any reply", flush=True)
        return False
    show("<-", reply)
    return True


def wait_for_close(sock: socket.socket) -> None:
    """Wait for the CSR to close the connection, printing anything else it sends."""
    start = time.monotonic()
    sock.settimeout(CLOSE_WAIT_S)
    try:
        while True:
            reply = read_frame(sock)
            if reply is None:
                elapsed = time.monotonic() - start
                print(f"   CSR closed the connection after {elapsed:.1f} s", flush=True)
                return
            show("<-", reply)
    except socket.timeout:
        print(f"   CSR did not close within {CLOSE_WAIT_S:.0f} s, closing from our side",
              flush=True)


def main() -> int:
    """Parse arguments, print the frames, and send them when --send is given."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--account", required=True,
                        help="account number, as given by the CSR (e.g. 27099)")
    parser.add_argument("--host", default="194.250.35.75")
    parser.add_argument("--port", type=int, default=10657)
    parser.add_argument("--event", action="append", dest="events",
                        help=f"data after '|', repeatable (default: {' '.join(DEFAULT_EVENTS)}); "
                             "append '##' + a verbatim bracket block to add an extended "
                             "block, e.g. 'Nri1/BA1##[Vhttps://h/snapshot.jpg]'")
    parser.add_argument("--seq-start", type=int, default=DEFAULT_SEQ_START,
                        help="first event sequence number")
    parser.add_argument("--no-null", action="store_true", help="do not send the NULL frame first")
    parser.add_argument("--send", action="store_true", help="really send (default: dry run)")
    args = parser.parse_args()
    events = args.events or DEFAULT_EVENTS

    if not args.send:
        print("DRY RUN (add --send to transmit). Timestamps will be regenerated at send time.")
        if not args.no_null:
            show("->", null_frame(args.account))
        for i, data in enumerate(events):
            show("->", event_frame(args.account, args.seq_start + i, data))
        return 0

    print(f"Connecting to {args.host}:{args.port}", flush=True)
    with socket.create_connection((args.host, args.port), timeout=ACK_TIMEOUT_S) as sock:
        if not args.no_null and not send_and_wait_ack(sock, null_frame(args.account)):
            return 1
        for i, data in enumerate(events):
            time.sleep(EVENT_GAP_S)
            if not send_and_wait_ack(sock, event_frame(args.account, args.seq_start + i, data)):
                return 1
        wait_for_close(sock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
