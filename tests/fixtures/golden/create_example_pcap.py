#!/usr/bin/env python3
"""Generate synthetic PCAP fixture for Story 2-4 tests.

Creates `capture_sia_example.pcap` with known SIA DC-09 frames and
`capture_sia_example_extracted.hex` as the golden expected extraction output.

Run from project root:
    python3 tests/fixtures/golden/create_example_pcap.py
"""

import socket
import struct
from datetime import datetime, timezone
from pathlib import Path

import dpkt

# ===== SIA frame payloads (from existing golden hex fixtures) =====

# Burglary alarm — client→server (dst=10001)
FRAME_BURGLARY = bytes.fromhex(
    "0A413434323030333832225349412D444353223030303134433023303031323334"
    "5B23303031323334 7C 313133305D5F31343A32333A34352C30342D30392D323032360D"
    .replace(" ", "")
)

# ACK response — server→client (src=10001)
FRAME_ACK_ALARM = bytes.fromhex(
    "0A30303230303031302241434B223030303120000D"
    .replace(" ", "")
)

# Supervision NULL — client→server (dst=10001)
FRAME_SUPERVISION = bytes.fromhex(
    "0A44413635303032342253494122"
    "2D444353223030303234 4C 3023303031323334"
    "5B23303031323334 7C 303030305D0D"
    .replace(" ", "")
)

# ACK response for supervision — server→client (src=10001)
FRAME_ACK_SUPERVISION = bytes.fromhex(
    "0A30303230303031302241434B223030303220000D"
    .replace(" ", "")
)

# Noise packet — different port (should be filtered out)
FRAME_NOISE = b"\x00\x01\x02\x03\x04\x05"


def _make_udp_ethernet(
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
) -> bytes:
    """Build a complete Ethernet/IP/UDP frame."""
    udp = dpkt.udp.UDP(sport=src_port, dport=dst_port, data=payload)
    udp.ulen = dpkt.udp.UDP.__hdr_len__ + len(payload)

    ip = dpkt.ip.IP(
        src=socket.inet_aton(src_ip),
        dst=socket.inet_aton(dst_ip),
        p=dpkt.ip.IP_PROTO_UDP,
        data=udp,
    )
    ip.len = dpkt.ip.IP.__hdr_len__ + int(udp.ulen)

    eth = dpkt.ethernet.Ethernet(data=ip)
    eth.type = dpkt.ethernet.ETH_TYPE_IP
    eth.src = b"\x00\x11\x22\x33\x44\x55"
    eth.dst = b"\x66\x77\x88\x99\xaa\xbb"

    return bytes(eth)


CLIENT_IP = "192.168.1.50"
SERVER_IP = "10.0.0.1"
SIA_PORT = 10001
CLIENT_PORT = 54321
NOISE_PORT = 9999

# Known capture timestamps (UTC epoch seconds)
TIMESTAMPS = [
    datetime(2026, 5, 21, 14, 23, 45, 123456, tzinfo=timezone.utc).timestamp(),
    datetime(2026, 5, 21, 14, 23, 45, 234567, tzinfo=timezone.utc).timestamp(),
    datetime(2026, 5, 21, 14, 23, 46, 100000, tzinfo=timezone.utc).timestamp(),
    datetime(2026, 5, 21, 14, 23, 46, 200000, tzinfo=timezone.utc).timestamp(),
    datetime(2026, 5, 21, 14, 23, 47, 0, tzinfo=timezone.utc).timestamp(),
    datetime(2026, 5, 21, 14, 23, 47, 50000, tzinfo=timezone.utc).timestamp(),
]

PACKETS = [
    # (src_ip, src_port, dst_ip, dst_port, payload, timestamp_idx)
    (CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, FRAME_BURGLARY, 0),     # client→server, SIA
    (SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, FRAME_ACK_ALARM, 1),    # server→client, SIA
    (CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, FRAME_SUPERVISION, 2),  # client→server, SIA
    (SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, FRAME_ACK_SUPERVISION, 3),  # server→client, SIA
    (CLIENT_IP, 12345, SERVER_IP, NOISE_PORT, FRAME_NOISE, 4),            # noise (different port)
    (SERVER_IP, NOISE_PORT, CLIENT_IP, 12345, FRAME_NOISE, 5),            # noise (different port)
]

OUTPUT_DIR = Path(__file__).parent


def create_pcap() -> Path:
    """Write capture_sia_example.pcap to the golden fixtures directory."""
    pcap_path = OUTPUT_DIR / "capture_sia_example.pcap"
    with open(pcap_path, "wb") as f:
        writer = dpkt.pcap.Writer(f)
        for src_ip, src_port, dst_ip, dst_port, payload, ts_idx in PACKETS:
            eth_bytes = _make_udp_ethernet(src_ip, src_port, dst_ip, dst_port, payload)
            writer.writepkt(eth_bytes, ts=TIMESTAMPS[ts_idx])
    print(f"Created: {pcap_path}")
    return pcap_path


def create_golden_hex() -> Path:
    """Write capture_sia_example_extracted.hex golden reference."""
    hex_path = OUTPUT_DIR / "capture_sia_example_extracted.hex"

    source_file = "capture_sia_example.pcap"
    port = SIA_PORT
    direction = "both"
    extraction_time = "2026-05-21 14:30:00 UTC"

    sia_packets = [
        (CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, FRAME_BURGLARY, 0),
        (SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, FRAME_ACK_ALARM, 1),
        (CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, FRAME_SUPERVISION, 2),
        (SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, FRAME_ACK_SUPERVISION, 3),
    ]

    lines: list[str] = [
        f"# PCAP extraction: {source_file}",
        f"# Filter: port={port}, direction={direction}",
        f"# Extracted: {extraction_time}",
    ]

    for src_ip, src_port, dst_ip, dst_port, payload, ts_idx in sia_packets:
        ts = datetime.fromtimestamp(TIMESTAMPS[ts_idx], tz=timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        dir_label = "client→server" if dst_port == SIA_PORT else "server→client"
        hex_line = " ".join(f"{b:02X}" for b in payload)
        lines.append("#")
        lines.append(
            f"# [{ts_str}] {src_ip}:{src_port} → {dst_ip}:{dst_port} (UDP, {dir_label})"
        )
        lines.append(hex_line)

    with open(hex_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Created: {hex_path}")
    return hex_path


if __name__ == "__main__":
    create_pcap()
    create_golden_hex()
    print("Done.")
