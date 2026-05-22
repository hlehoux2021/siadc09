#!/usr/bin/env python3
"""CLI tool to extract SIA DC-09 frames from Wireshark pcap captures.

Reads a `.pcap` or `.pcapng` file, filters packets by SIA DC-09 port and
direction, and writes a hex dump file compatible with simulate_frames.py.

Usage:
    python3 extract_frames_from_pcap.py capture.pcapng -o frames.hex
    python3 extract_frames_from_pcap.py capture.pcap -o frames.hex --port 10001 --direction client
"""

import argparse
import logging
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import dpkt

# ===== Constants =====

DEFAULT_PORT = 10001
DIRECTION_CLIENT = "client"
DIRECTION_SERVER = "server"
DIRECTION_BOTH = "both"
PORT_MIN = 1
PORT_MAX = 65535
PROTOCOL_UDP = "udp"
PROTOCOL_TCP = "tcp"

logger = logging.getLogger(__name__)


# ===== Domain Types =====


@dataclass
class PacketInfo:
    """Represents a single captured network packet.

    Attributes:
        timestamp: Packet capture time (UTC).
        src_ip: Source IP address.
        src_port: Source port number.
        dst_ip: Destination IP address.
        dst_port: Destination port number.
        protocol: Transport protocol, "udp" or "tcp".
        payload: Raw application-layer payload bytes (the SIA frame).
    """

    timestamp: datetime
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    protocol: str
    payload: bytes


# ===== Task 2: PCAP Reader =====


def read_pcap(filepath: str) -> list[PacketInfo]:
    """Read a pcap or pcapng file and extract all packets with payloads.

    Auto-detects format: tries pcapng first (modern Wireshark default),
    falls back to classic pcap. Handles IPv4 only (IPv6 out of scope for v1.0).
    Skips TCP packets with no payload (SYN, FIN, ACK-only handshake packets).

    Args:
        filepath: Path to the `.pcap` or `.pcapng` file.

    Returns:
        List of PacketInfo objects, one per captured packet with a payload.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a valid pcap or pcapng.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {filepath}")

    packets: list[PacketInfo] = []

    try:
        with open(filepath, "rb") as f:
            reader = _open_reader(f)
            for ts, buf in reader:
                packet = _parse_packet(ts, buf)
                if packet is not None:
                    packets.append(packet)
    except (dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError, dpkt.dpkt.PackError) as exc:
        raise ValueError(f"Invalid pcap/pcapng file: {filepath}: {exc}") from exc
    except ValueError:
        raise
    except OSError as exc:
        raise OSError(f"Failed to read pcap file: {filepath}: {exc}") from exc

    logger.debug("Read %d packets with payload from %s", len(packets), filepath)
    return packets


def _open_reader(f: IO[bytes]) -> dpkt.pcap.Reader | dpkt.pcapng.Reader:
    """Open a pcap or pcapng reader, auto-detecting format.

    Args:
        f: Open seekable binary file object.

    Returns:
        A dpkt Reader instance (pcapng or pcap).

    Raises:
        ValueError: If the file is neither a valid pcap nor pcapng.
    """
    try:
        reader = dpkt.pcapng.Reader(f)
        logger.debug("Detected pcapng format")
        return reader
    except (ValueError, dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError, dpkt.dpkt.PackError):
        pass

    try:
        f.seek(0)
        reader = dpkt.pcap.Reader(f)
        logger.debug("Detected pcap format")
        return reader
    except (ValueError, dpkt.dpkt.NeedData) as exc:
        raise ValueError(f"File is neither a valid pcap nor pcapng: {exc}") from exc


def _parse_packet(ts: float, buf: bytes) -> PacketInfo | None:
    """Parse a single raw packet buffer into a PacketInfo.

    Args:
        ts: Capture timestamp (Unix epoch seconds, float).
        buf: Raw packet bytes (Ethernet frame).

    Returns:
        PacketInfo if the packet has an IPv4 TCP/UDP payload, None otherwise.
    """
    try:
        eth = dpkt.ethernet.Ethernet(buf)
    except (dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError):
        return None

    if not isinstance(eth.data, dpkt.ip.IP):
        return None

    ip = eth.data
    try:
        src_ip = socket.inet_ntoa(ip.src)
        dst_ip = socket.inet_ntoa(ip.dst)
    except OSError:
        return None

    capture_time = datetime.fromtimestamp(ts, tz=timezone.utc)

    transport = ip.data
    if isinstance(transport, dpkt.udp.UDP):
        protocol, src_port, dst_port, payload = (
            PROTOCOL_UDP, transport.sport, transport.dport, bytes(transport.data)
        )
    elif isinstance(transport, dpkt.tcp.TCP):
        protocol, src_port, dst_port, payload = (
            PROTOCOL_TCP, transport.sport, transport.dport, bytes(transport.data)
        )
    else:
        return None

    if not payload:
        return None

    return PacketInfo(
        timestamp=capture_time,
        src_ip=src_ip,
        src_port=src_port,
        dst_ip=dst_ip,
        dst_port=dst_port,
        protocol=protocol,
        payload=payload,
    )


# ===== Task 3: Frame Filter =====


def filter_frames(
    packets: list[PacketInfo],
    port: int,
    direction: str,
) -> list[PacketInfo]:
    """Filter packets by SIA DC-09 port and direction.

    Args:
        packets: List of PacketInfo from read_pcap().
        port: SIA DC-09 port to match against (src or dst depending on direction).
        direction: One of:
            - "client": keep only packets where dst_port == port (client → server)
            - "server": keep only packets where src_port == port (server → client)
            - "both": keep all packets where port appears on either side

    Returns:
        Filtered list in original chronological order.
    """
    result: list[PacketInfo] = []
    for pkt in packets:
        if direction == DIRECTION_CLIENT and pkt.dst_port == port:
            result.append(pkt)
        elif direction == DIRECTION_SERVER and pkt.src_port == port:
            result.append(pkt)
        elif direction == DIRECTION_BOTH and port in (pkt.src_port, pkt.dst_port):
            result.append(pkt)
    return result


# ===== Task 4: Hex File Writer =====


def write_hex_file(
    packets: list[PacketInfo],
    output_path: str,
    *,
    source_file: str = "",
    port: int = DEFAULT_PORT,
    direction: str = DIRECTION_BOTH,
) -> int:
    """Write filtered packets to a hex dump file compatible with simulate_frames.py.

    Output format:
        # PCAP extraction: capture.pcapng
        # Filter: port=10001, direction=both
        # Extracted: 2026-05-21 14:30:00 UTC
        #
        # [2026-05-21 14:23:45.123456] 192.168.1.1:54321 → 10.0.0.1:10001 (UDP, client→server)
        0A 41 34 ...
        #
        # [2026-05-21 14:23:45.234567] 10.0.0.1:10001 → 192.168.1.1:54321 (UDP, server→client)
        0A 30 30 ...

    Args:
        packets: Filtered list of PacketInfo objects to write.
        output_path: Destination file path.
        source_file: Original pcap filename for the header comment (display only).
        port: Filter port used, included in header comment.
        direction: Filter direction used, included in header comment.

    Returns:
        Number of frames written.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    extraction_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# PCAP extraction: {source_file}\n")
        f.write(f"# Filter: port={port}, direction={direction}\n")
        f.write(f"# Extracted: {extraction_time}\n")

        for pkt in packets:
            ts_str = pkt.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            dir_label = _direction_label(pkt, port)
            f.write("#\n")
            f.write(
                f"# [{ts_str}] {pkt.src_ip}:{pkt.src_port}"
                f" → {pkt.dst_ip}:{pkt.dst_port}"
                f" ({pkt.protocol.upper()}, {dir_label})\n"
            )
            hex_line = " ".join(f"{b:02X}" for b in pkt.payload)
            f.write(f"{hex_line}\n")

    logger.debug("Wrote %d frames to %s", len(packets), output_path)
    return len(packets)


def _direction_label(pkt: PacketInfo, port: int) -> str:
    """Compute human-readable direction label for a packet.

    Args:
        pkt: The packet to label.
        port: The SIA port used for filtering.

    Returns:
        "client→server" or "server→client" or "unknown".
    """
    if pkt.dst_port == port:
        return "client→server"
    if pkt.src_port == port:
        return "server→client"
    return "unknown"


# ===== Task 5: CLI Entry Point =====


def main() -> None:
    """CLI entry point for PCAP frame extraction."""
    parser = argparse.ArgumentParser(
        description="Extract SIA DC-09 frames from Wireshark pcap captures"
    )
    parser.add_argument(
        "input",
        help="Path to .pcap or .pcapng file",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output hex file path",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"SIA DC-09 port to filter (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--direction", "-d",
        choices=[DIRECTION_CLIENT, DIRECTION_SERVER, DIRECTION_BOTH],
        default=DIRECTION_BOTH,
        help="Direction filter: client, server, or both (default: both)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    if not PORT_MIN <= args.port <= PORT_MAX:
        parser.error(f"Port must be between {PORT_MIN} and {PORT_MAX}")

    try:
        packets = read_pcap(args.input)
        filtered = filter_frames(packets, args.port, args.direction)
        count = write_hex_file(
            filtered,
            args.output,
            source_file=Path(args.input).name,
            port=args.port,
            direction=args.direction,
        )
        print(
            f"Extracted {count} frames from {Path(args.input).name}"
            f" (port={args.port}, direction={args.direction}) → {args.output}"
        )
        sys.exit(0)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except OSError as exc:
        logger.error("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
