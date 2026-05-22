"""Tests for PCAP frame extractor CLI tool (Story 2-4).

Covers:
- Task 7: PCAP parsing (read_pcap)
- Task 8: Frame filtering (filter_frames)
- Task 9: Hex file writing (write_hex_file)
- Task 10: Integration — end-to-end pipeline
- Task 11: CLI argument parsing
"""

import io
import socket
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import dpkt
import pytest

from resources.siadc09d.extract_frames_from_pcap import (
    DEFAULT_PORT,
    DIRECTION_BOTH,
    DIRECTION_CLIENT,
    DIRECTION_SERVER,
    PacketInfo,
    filter_frames,
    main,
    read_pcap,
    write_hex_file,
)
from resources.siadc09d.simulate_frames import parse_hex_file

# ===== Shared constants =====

CLIENT_IP = "192.168.1.50"
SERVER_IP = "10.0.0.1"
SIA_PORT = 10001
CLIENT_PORT = 54321
NOISE_PORT = 9999

PAYLOAD_A = b"\x0A\x41\x42\x43\x0D"  # Minimal SIA-like frame
PAYLOAD_B = b"\x0A\x30\x30\x41\x43\x4B\x0D"  # Minimal ACK-like frame
PAYLOAD_NOISE = b"\x00\x01\x02\x03"

GOLDEN_DIR = Path("tests/fixtures/golden")
EXAMPLE_PCAP = GOLDEN_DIR / "capture_sia_example.pcap"
EXAMPLE_HEX = GOLDEN_DIR / "capture_sia_example_extracted.hex"


# ===== PCAP builder helpers =====


def _udp_eth(
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
) -> bytes:
    """Build a complete Ethernet/IP/UDP frame bytes."""
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


def _tcp_eth(
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
) -> bytes:
    """Build a complete Ethernet/IP/TCP frame bytes."""
    tcp = dpkt.tcp.TCP(sport=src_port, dport=dst_port, data=payload)
    ip = dpkt.ip.IP(
        src=socket.inet_aton(src_ip),
        dst=socket.inet_aton(dst_ip),
        p=dpkt.ip.IP_PROTO_TCP,
        data=tcp,
    )
    ip.len = len(ip)
    eth = dpkt.ethernet.Ethernet(data=ip)
    eth.type = dpkt.ethernet.ETH_TYPE_IP
    eth.src = b"\x00\x11\x22\x33\x44\x55"
    eth.dst = b"\x66\x77\x88\x99\xaa\xbb"
    return bytes(eth)


def _write_pcap(path: str, packets: list[tuple[bytes, float]]) -> None:
    """Write a pcap file with given packets and timestamps."""
    with open(path, "wb") as f:
        writer = dpkt.pcap.Writer(f)
        for eth_bytes, ts in packets:
            writer.writepkt(eth_bytes, ts=ts)


def _write_pcapng(path: str, packets: list[tuple[bytes, float]]) -> None:
    """Write a pcapng file with given packets (uses dpkt pcapng Writer)."""
    with open(path, "wb") as f:
        writer = dpkt.pcapng.Writer(f)
        for eth_bytes, ts in packets:
            writer.writepkt(eth_bytes, ts=ts)


# ============================================================================
# Task 7: Unit Tests — PCAP Parsing
# ============================================================================


def test_read_pcap_valid_file(tmp_path: Path) -> None:
    """Read a pcap with known packets, verify packet fields.

    Expected result:
    - Returns list with correct number of PacketInfo objects
    - Timestamps, IPs, ports, payloads match expected values
    """
    ts1 = 1716300000.123456
    ts2 = 1716300001.234567
    pcap_file = str(tmp_path / "test.pcap")
    _write_pcap(
        pcap_file,
        [
            (_udp_eth(CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, PAYLOAD_A), ts1),
            (_udp_eth(SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, PAYLOAD_B), ts2),
        ],
    )

    result = read_pcap(pcap_file)

    # Assert: two PacketInfo objects returned
    assert len(result) == 2

    # Assert: first packet fields match
    pkt0 = result[0]
    assert pkt0.src_ip == CLIENT_IP
    assert pkt0.src_port == CLIENT_PORT
    assert pkt0.dst_ip == SERVER_IP
    assert pkt0.dst_port == SIA_PORT
    assert pkt0.protocol == "udp"
    assert pkt0.payload == PAYLOAD_A

    # Assert: timestamp is UTC-aware and close to expected
    assert pkt0.timestamp.tzinfo is not None
    assert abs(pkt0.timestamp.timestamp() - ts1) < 0.01

    # Assert: second packet fields match
    pkt1 = result[1]
    assert pkt1.payload == PAYLOAD_B


def test_read_pcap_pcapng_format(tmp_path: Path) -> None:
    """Read a pcapng file, verify same parsing works.

    Expected result:
    - pcapng format parsed correctly, same number of packets returned
    """
    pcapng_file = str(tmp_path / "test.pcapng")
    _write_pcapng(
        pcapng_file,
        [(_udp_eth(CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, PAYLOAD_A), 1.0)],
    )

    result = read_pcap(pcapng_file)

    # Assert: packet parsed from pcapng
    assert len(result) == 1
    assert result[0].payload == PAYLOAD_A


def test_read_pcap_file_not_found() -> None:
    """Read a non-existent file, verify FileNotFoundError raised.

    Expected result:
    - FileNotFoundError raised with descriptive message
    """
    with pytest.raises(FileNotFoundError, match="no_such_file.pcap"):
        read_pcap("/tmp/no_such_file.pcap")


def test_read_pcap_invalid_file(tmp_path: Path) -> None:
    """Read a non-pcap file, verify ValueError raised.

    Expected result:
    - ValueError raised with descriptive message
    """
    bad_file = tmp_path / "garbage.pcap"
    bad_file.write_text("this is not a pcap file at all\n")

    with pytest.raises(ValueError):
        read_pcap(str(bad_file))


def test_read_pcap_skips_empty_payload(tmp_path: Path) -> None:
    """Read a pcap with TCP SYN packets (no payload), verify they are excluded.

    Expected result:
    - Packets with empty payload (SYN/ACK) not included in result
    - Only packets with actual payload returned
    """
    ts_syn = 1.0
    ts_data = 2.0
    pcap_file = str(tmp_path / "test_tcp.pcap")

    # Build TCP SYN (no payload)
    tcp_syn = dpkt.tcp.TCP(sport=CLIENT_PORT, dport=SIA_PORT, data=b"", flags=dpkt.tcp.TH_SYN)
    ip_syn = dpkt.ip.IP(
        src=socket.inet_aton(CLIENT_IP),
        dst=socket.inet_aton(SERVER_IP),
        p=dpkt.ip.IP_PROTO_TCP,
        data=tcp_syn,
    )
    ip_syn.len = len(ip_syn)
    eth_syn = dpkt.ethernet.Ethernet(data=ip_syn)
    eth_syn.type = dpkt.ethernet.ETH_TYPE_IP
    eth_syn.src = b"\x00\x11\x22\x33\x44\x55"
    eth_syn.dst = b"\x66\x77\x88\x99\xaa\xbb"

    _write_pcap(
        pcap_file,
        [
            (bytes(eth_syn), ts_syn),
            (_tcp_eth(CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, PAYLOAD_A), ts_data),
        ],
    )

    result = read_pcap(pcap_file)

    # Assert: SYN packet excluded; only the data packet returned
    assert len(result) == 1
    assert result[0].payload == PAYLOAD_A


# ============================================================================
# Task 8: Unit Tests — Frame Filtering
# ============================================================================


def _make_packets() -> list[PacketInfo]:
    """Build a mix of client→server, server→client, and noise packets."""
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return [
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_A),
        PacketInfo(ts, SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, "udp", PAYLOAD_B),
        PacketInfo(ts, CLIENT_IP, 12345, SERVER_IP, NOISE_PORT, "udp", PAYLOAD_NOISE),
        PacketInfo(ts, SERVER_IP, NOISE_PORT, CLIENT_IP, 12345, "udp", PAYLOAD_NOISE),
    ]


def test_filter_frames_both_directions() -> None:
    """Filter with direction=both, verify all SIA packets kept and noise excluded.

    Expected result:
    - 2 SIA packets returned (client→server + server→client)
    - 2 noise packets (different port) excluded
    """
    packets = _make_packets()
    result = filter_frames(packets, SIA_PORT, DIRECTION_BOTH)

    # Assert: only SIA port packets kept
    assert len(result) == 2
    assert result[0].payload == PAYLOAD_A
    assert result[1].payload == PAYLOAD_B


def test_filter_frames_client_only() -> None:
    """Filter with direction=client, verify only dst_port==SIA_PORT kept.

    Expected result:
    - Only client→server packet returned
    """
    packets = _make_packets()
    result = filter_frames(packets, SIA_PORT, DIRECTION_CLIENT)

    # Assert: only the client→server packet returned
    assert len(result) == 1
    assert result[0].dst_port == SIA_PORT
    assert result[0].payload == PAYLOAD_A


def test_filter_frames_server_only() -> None:
    """Filter with direction=server, verify only src_port==SIA_PORT kept.

    Expected result:
    - Only server→client packet returned
    """
    packets = _make_packets()
    result = filter_frames(packets, SIA_PORT, DIRECTION_SERVER)

    # Assert: only the server→client packet returned
    assert len(result) == 1
    assert result[0].src_port == SIA_PORT
    assert result[0].payload == PAYLOAD_B


def test_filter_frames_no_match() -> None:
    """Filter with port that no packets use, verify empty result.

    Expected result:
    - Empty list returned when no packets match filter
    """
    packets = _make_packets()
    result = filter_frames(packets, 8888, DIRECTION_BOTH)

    # Assert: empty list when no packets match
    assert result == []


def test_filter_frames_preserves_order(tmp_path: Path) -> None:
    """Filter preserves chronological order of packets.

    Expected result:
    - Output order matches input order (timestamps ascending)
    """
    ts_base = 1716300000.0
    ts_values = [ts_base + i for i in range(3)]
    packets = [
        PacketInfo(
            datetime.fromtimestamp(ts_values[i], tz=timezone.utc),
            CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp",
            bytes([i]),
        )
        for i in range(3)
    ]
    result = filter_frames(packets, SIA_PORT, DIRECTION_BOTH)

    # Assert: order preserved (payload bytes match original indices)
    assert len(result) == 3
    for i, pkt in enumerate(result):
        assert pkt.payload == bytes([i])


# ============================================================================
# Task 9: Unit Tests — Hex File Writing
# ============================================================================


def test_write_hex_file_format(tmp_path: Path) -> None:
    """Write 2 packets, verify hex format and comment structure.

    Expected result:
    - Uppercase space-separated hex bytes per frame
    - Comment lines with timestamps present before each frame
    - Header metadata block at top of file
    """
    ts = datetime(2026, 5, 21, 14, 23, 45, 123456, tzinfo=timezone.utc)
    packets = [
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_A),
        PacketInfo(ts, SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, "udp", PAYLOAD_B),
    ]
    out_file = str(tmp_path / "output.hex")

    count = write_hex_file(packets, out_file, source_file="test.pcap")

    # Assert: returns correct frame count
    assert count == 2

    content = Path(out_file).read_text(encoding="utf-8")

    # Assert: header block present
    assert "# PCAP extraction: test.pcap" in content
    assert "# Filter: port=" in content
    assert "# Extracted:" in content

    # Assert: hex bytes are uppercase space-separated
    expected_a = " ".join(f"{b:02X}" for b in PAYLOAD_A)
    assert expected_a in content

    # Assert: timestamp comment present
    assert "2026-05-21 14:23:45.123456" in content


def test_write_hex_file_compatible_with_simulate_frames(tmp_path: Path) -> None:
    """Write hex file then parse with simulate_frames.parse_hex_file, verify byte-for-byte match.

    Expected result:
    - parse_hex_file returns frames identical to original payloads
    - This is the critical compatibility test
    """
    ts = datetime(2026, 5, 21, 0, 0, 0, tzinfo=timezone.utc)
    packets = [
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_A),
        PacketInfo(ts, SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, "udp", PAYLOAD_B),
    ]
    out_file = str(tmp_path / "compat.hex")
    write_hex_file(packets, out_file)

    # Assert: parse_hex_file can read the output and returns identical bytes
    parsed = parse_hex_file(out_file)
    assert len(parsed) == 2
    assert parsed[0] == PAYLOAD_A
    assert parsed[1] == PAYLOAD_B


def test_write_hex_file_creates_parent_dirs(tmp_path: Path) -> None:
    """Write to a nested path that doesn't exist, verify directories created.

    Expected result:
    - Parent directories created automatically
    - File written successfully
    """
    nested_path = str(tmp_path / "a" / "b" / "c" / "output.hex")
    ts = datetime(2026, 5, 21, 0, 0, 0, tzinfo=timezone.utc)
    packets = [PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_A)]

    write_hex_file(packets, nested_path)

    # Assert: file was created at nested path
    assert Path(nested_path).exists()


def test_write_hex_file_returns_count(tmp_path: Path) -> None:
    """Verify return value equals number of frames written.

    Expected result:
    - Return value matches len(packets)
    """
    ts = datetime(2026, 5, 21, 0, 0, 0, tzinfo=timezone.utc)
    packets = [
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_A),
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", PAYLOAD_B),
        PacketInfo(ts, CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, "udp", b"\xFF\xFE"),
    ]
    out_file = str(tmp_path / "count.hex")

    count = write_hex_file(packets, out_file)

    # Assert: returned count equals number of packets written
    assert count == 3


# ============================================================================
# Task 10: Integration Tests — End-to-End Pipeline
# ============================================================================


def test_extract_from_example_pcap_matches_golden() -> None:
    """Extract from example pcap, compare output to golden file (content-level).

    Expected result:
    - Extracted frames match golden reference byte-for-byte (same payloads)
    - SIA packets only (4 frames), noise packets excluded
    """
    if not EXAMPLE_PCAP.exists():
        pytest.skip("Golden PCAP not found; run create_example_pcap.py first")

    packets = read_pcap(str(EXAMPLE_PCAP))
    filtered = filter_frames(packets, DEFAULT_PORT, DIRECTION_BOTH)

    # Assert: 4 SIA packets, noise filtered out
    assert len(filtered) == 4

    # Assert: payloads match golden hex file
    golden_frames = parse_hex_file(str(EXAMPLE_HEX))
    assert len(golden_frames) == 4
    for extracted, golden in zip(filtered, golden_frames):
        assert extracted.payload == golden, (
            f"Payload mismatch: got {extracted.payload.hex()} "
            f"expected {golden.hex()}"
        )


def test_full_pipeline_pcap_to_replay(tmp_path: Path) -> None:
    """Extract frames from pcap → hex file, then parse back with simulate_frames.

    Expected result:
    - Complete extract→write→parse pipeline produces frames identical to pcap payloads
    """
    ts = 1716300000.0
    pcap_file = str(tmp_path / "pipeline.pcap")
    _write_pcap(
        pcap_file,
        [
            (_udp_eth(CLIENT_IP, CLIENT_PORT, SERVER_IP, SIA_PORT, PAYLOAD_A), ts),
            (_udp_eth(SERVER_IP, SIA_PORT, CLIENT_IP, CLIENT_PORT, PAYLOAD_B), ts + 0.1),
            (_udp_eth(CLIENT_IP, 9999, SERVER_IP, 8080, PAYLOAD_NOISE), ts + 0.2),
        ],
    )
    hex_file = str(tmp_path / "pipeline.hex")

    # Extract and write
    packets = read_pcap(pcap_file)
    filtered = filter_frames(packets, SIA_PORT, DIRECTION_BOTH)
    count = write_hex_file(filtered, hex_file)

    # Assert: 2 frames extracted (noise excluded)
    assert count == 2

    # Assert: simulate_frames can parse the output and frames are identical
    replayed = parse_hex_file(hex_file)
    assert len(replayed) == 2
    assert replayed[0] == PAYLOAD_A
    assert replayed[1] == PAYLOAD_B


# ============================================================================
# Task 11: CLI Tests — Argument Parsing
# ============================================================================


def test_cli_missing_input(capsys: pytest.CaptureFixture) -> None:
    """Run CLI with no arguments, verify exit code 2 (usage error).

    Expected result:
    - SystemExit raised with code 2
    """
    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", ["extract_frames_from_pcap.py"]):
            main()

    # Assert: usage error exit code
    assert exc_info.value.code == 2


def test_cli_missing_output(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Run CLI with input but no --output, verify exit code 2.

    Expected result:
    - SystemExit raised with code 2
    """
    dummy = tmp_path / "dummy.pcap"
    dummy.write_bytes(b"x")

    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", ["extract_frames_from_pcap.py", str(dummy)]):
            main()

    # Assert: usage error exit code
    assert exc_info.value.code == 2


def test_cli_invalid_direction(tmp_path: Path) -> None:
    """Run CLI with invalid --direction value, verify exit code 2.

    Expected result:
    - SystemExit raised with code 2
    """
    dummy = tmp_path / "dummy.pcap"
    dummy.write_bytes(b"x")
    out = str(tmp_path / "out.hex")

    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", [
            "extract_frames_from_pcap.py", str(dummy), "-o", out, "--direction", "INVALID"
        ]):
            main()

    # Assert: argparse rejects invalid direction choice
    assert exc_info.value.code == 2


def test_cli_invalid_port(tmp_path: Path) -> None:
    """Run CLI with port=0 (out of range), verify exit code 2.

    Expected result:
    - SystemExit raised with code 2
    """
    dummy = tmp_path / "dummy.pcap"
    dummy.write_bytes(b"x")
    out = str(tmp_path / "out.hex")

    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", [
            "extract_frames_from_pcap.py", str(dummy), "-o", out, "--port", "0"
        ]):
            main()

    # Assert: port 0 rejected (out of 1-65535 range)
    assert exc_info.value.code == 2


def test_cli_help(capsys: pytest.CaptureFixture) -> None:
    """Run CLI with --help, verify usage is displayed.

    Expected result:
    - SystemExit raised with code 0
    - Output contains option descriptions
    """
    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", ["extract_frames_from_pcap.py", "--help"]):
            main()

    # Assert: help exits with code 0
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    # Assert: help output contains key options
    assert "--output" in captured.out or "--output" in captured.err
    assert "--port" in captured.out or "--port" in captured.err
    assert "--direction" in captured.out or "--direction" in captured.err


def test_cli_default_values(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Run CLI on a valid pcap with no port/direction args, verify defaults applied.

    Expected result:
    - port defaults to 10001
    - direction defaults to both
    - Extraction runs successfully with exit code 0
    """
    ts = 1716300000.0
    pcap_file = str(tmp_path / "test.pcap")
    out_file = str(tmp_path / "out.hex")
    _write_pcap(
        pcap_file,
        [(_udp_eth(CLIENT_IP, CLIENT_PORT, SERVER_IP, DEFAULT_PORT, PAYLOAD_A), ts)],
    )

    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", [
            "extract_frames_from_pcap.py", pcap_file, "-o", out_file
        ]):
            main()

    # Assert: default port (10001) and direction (both) produce successful extraction
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    # Assert: success message mentions the defaults
    assert f"port={DEFAULT_PORT}" in captured.out
    assert f"direction={DIRECTION_BOTH}" in captured.out
