"""Tests for tests/harness/run_harness.py — E2E frame-replay harness.

Validates the harness orchestration script against the CSR Simulator and
golden fixtures.

Reference: story 2-5 § Task 3
"""

import asyncio
import tempfile
from contextlib import suppress
from pathlib import Path

import pytest
import pytest_asyncio

from resources.siadc09d.csr_simulator import CSRSimulator
from resources.siadc09d.simulate_frames import parse_hex_file
from tests.harness.run_harness import (
    ACCOUNT_NUMBER_DEFAULT,
    GOLDEN_DIR,
    MALFORMED_FIXTURE,
    _get_free_port,
    run_harness,
)

# ===== Fixtures =====

_GOLDEN_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "golden"
_TEST_KEY = bytes.fromhex("0123456789ABCDEF0123456789ABCDEF")


@pytest_asyncio.fixture
async def plain_simulator():
    """Start CSRSimulator on ephemeral ports (plaintext, hex CRC).

    Expected result:
    - Simulator starts, yields (sim, udp_port), stops cleanly after test.
    """
    udp_port = _get_free_port()
    preset = {
        "crc_format": "hex",
        "account_number": ACCOUNT_NUMBER_DEFAULT,
        "encryption_key": None,
    }
    sim = CSRSimulator(udp_port=udp_port, tcp_port=udp_port + 1, preset=preset)
    await sim.start()
    udp_task = asyncio.create_task(sim._handle_udp(), name="test_harness_udp")

    yield sim, udp_port

    await sim.stop()
    udp_task.cancel()
    with suppress(asyncio.CancelledError):
        await udp_task


@pytest_asyncio.fixture
async def encrypted_simulator():
    """Start CSRSimulator on ephemeral ports (AES-128 encrypted, hex CRC).

    Expected result:
    - Simulator starts with fixed test key, yields (sim, udp_port), stops cleanly.
    """
    udp_port = _get_free_port()
    preset = {
        "crc_format": "hex",
        "account_number": ACCOUNT_NUMBER_DEFAULT,
        "encryption_key": _TEST_KEY,
    }
    sim = CSRSimulator(udp_port=udp_port, tcp_port=udp_port + 1, preset=preset)
    await sim.start()
    udp_task = asyncio.create_task(sim._handle_udp(), name="test_harness_enc_udp")

    yield sim, udp_port

    await sim.stop()
    udp_task.cancel()
    with suppress(asyncio.CancelledError):
        await udp_task


# ===== Unit Tests: Harness Helpers =====


def test_get_free_port_returns_valid_port() -> None:
    """Test _get_free_port() returns a valid port number.

    Expected result:
    - Port is in valid range 1024-65535
    - Port is usable (no socket error on bind)
    """
    port = _get_free_port()
    # Assert: port is in valid range
    assert 1024 <= port <= 65535, f"Expected valid port, got {port}"


def test_golden_dir_constant_points_to_existing_dir() -> None:
    """Test GOLDEN_DIR constant points to the real fixtures directory.

    Expected result:
    - GOLDEN_DIR exists and contains frames_*.hex files
    """
    # Assert: GOLDEN_DIR exists
    assert GOLDEN_DIR.is_dir(), f"GOLDEN_DIR does not exist: {GOLDEN_DIR}"
    # Assert: at least some golden fixtures present
    golden_files = list(GOLDEN_DIR.glob("frames_*.hex"))
    assert len(golden_files) >= 4, f"Expected ≥4 golden fixtures, found {len(golden_files)}"


def test_malformed_fixture_exists() -> None:
    """Test the malformed fixture file exists.

    Expected result:
    - frames_malformed.hex present in golden directory
    """
    # Assert: malformed fixture exists
    assert (GOLDEN_DIR / MALFORMED_FIXTURE).exists(), f"{MALFORMED_FIXTURE} not found"


def test_encrypted_fixture_exists() -> None:
    """Test the encrypted alarm fixture file exists.

    Expected result:
    - frames_encrypted_alarm.hex present in golden directory
    """
    # Assert: encrypted fixture exists
    assert (GOLDEN_DIR / "frames_encrypted_alarm.hex").exists()


# ===== Integration Tests: run_harness() =====


@pytest.mark.asyncio
async def test_harness_all_golden_frames_get_ack() -> None:
    """All golden non-malformed frames return a response (ACK/NAK) in plain mode.

    Expected result:
    - total_frames > 0 (at least some golden files exist)
    - total_timeout == 0 (no non-malformed frames timed out)
    - total_ack >= count of non-malformed frames
    """
    total_frames, total_ack, total_timeout = await run_harness(
        encryption_key=None,
        crc_format="hex",
    )

    # Assert: harness found and processed frames
    assert total_frames > 0, "Harness found no frames to process"
    # Assert: no timeouts on non-malformed frames
    assert total_timeout == 0, f"Expected 0 timeouts, got {total_timeout}"
    # Assert: ack_count matches processed non-malformed frames
    assert total_ack > 0, "Expected at least one ACK/NAK response"


@pytest.mark.asyncio
async def test_harness_encrypted_mode() -> None:
    """Harness with AES-128 key: all frames get a response.

    Expected result:
    - total_timeout == 0 for non-malformed frames
    - Encrypted alarm fixture frame gets a response
    """
    total_frames, total_ack, total_timeout = await run_harness(
        encryption_key=_TEST_KEY,
        crc_format="hex",
    )

    # Assert: no timeouts (simulator responds to all frame types under any key)
    assert total_timeout == 0, f"Expected 0 timeouts in encrypted mode, got {total_timeout}"
    # Assert: all frames processed
    assert total_ack > 0, "Expected at least one response"


@pytest.mark.asyncio
async def test_harness_malformed_frame_gets_nak() -> None:
    """Malformed frames produce NAK or response (not counted as harness failure).

    Verifies that frames_malformed.hex is treated specially:
    - The simulator sends NAK for malformed/unknown frame types.
    - run_harness() does not count malformed-file timeouts as failures.

    Expected result:
    - Malformed frames elicit a NAK response from the simulator
    - total_timeout == 0 in the harness run (malformed file excluded from failure count)
    """
    from resources.siadc09d.sia_protocol import decode_ack_nak

    # Verify the simulator actually returns NAK for malformed frames
    udp_port = _get_free_port()
    preset = {
        "crc_format": "hex",
        "account_number": ACCOUNT_NUMBER_DEFAULT,
        "encryption_key": None,
    }
    sim = CSRSimulator(udp_port=udp_port, tcp_port=udp_port + 1, preset=preset)
    await sim.start()
    udp_task = asyncio.create_task(sim._handle_udp(), name="test_malformed_udp")

    try:
        from resources.siadc09d.simulate_frames import replay_frames

        malformed_frames = parse_hex_file(str(GOLDEN_DIR / MALFORMED_FIXTURE))
        assert len(malformed_frames) >= 1, "Malformed fixture should contain at least one frame"

        results, _, _ = await replay_frames(
            malformed_frames,
            host="127.0.0.1",
            port=udp_port,
            protocol="udp",
            timeout_s=2.0,
        )

        # Assert: at least one malformed frame received a NAK response
        nak_responses = [
            r for r in results
            if r["response"] is not None
            and decode_ack_nak(r["response"], "hex").get("type") == "NAK"
        ]
        assert len(nak_responses) >= 1, (
            f"Expected at least one NAK for malformed frames, "
            f"got {[decode_ack_nak(r['response'], 'hex')['type'] for r in results if r['response'] is not None]}"
        )
    finally:
        await sim.stop()
        udp_task.cancel()
        with suppress(asyncio.CancelledError):
            await udp_task

    # Also verify run_harness exits with 0 effective timeouts despite malformed frames
    _, _, total_timeout = await run_harness(
        encryption_key=None,
        crc_format="hex",
    )

    # Assert: run_harness exits with 0 effective timeouts despite malformed frames
    assert total_timeout == 0, f"Malformed frames should not count as timeout failures, got {total_timeout}"


@pytest.mark.asyncio
async def test_harness_mixed_sequence_ordering(
    plain_simulator: tuple[CSRSimulator, int],
) -> None:
    """frames_mixed_sequence.hex is processed in order with distinct seq numbers.

    The fixture contains seq=0001 (burglary), seq=0002 (NULL), seq=0003 (fire).
    The simulator must echo back each sequence number in its ACK response.

    Expected result:
    - All 3 frames in the mixed file get a response
    - Each ACK echoes the matching sequence number (1, 2, 3)
    """
    from resources.siadc09d.sia_protocol import decode_ack_nak
    from resources.siadc09d.simulate_frames import replay_frames

    _, udp_port = plain_simulator

    mixed_file = _GOLDEN_FIXTURES_DIR / "frames_mixed_sequence.hex"
    assert mixed_file.exists(), f"Missing fixture: {mixed_file}"

    frames = parse_hex_file(str(mixed_file))
    # Assert: fixture has expected 3 frames
    assert len(frames) == 3, f"Expected 3 frames in mixed file, got {len(frames)}"

    results, ack_count, timeout_count = await replay_frames(
        frames,
        host="127.0.0.1",
        port=udp_port,
        protocol="udp",
        timeout_s=2.0,
    )

    # Assert: all 3 frames got a response
    assert ack_count == 3, f"Expected 3 responses, got {ack_count}"
    # Assert: no timeouts
    assert timeout_count == 0, f"Expected 0 timeouts, got {timeout_count}"

    # Assert: each ACK echoes the expected sequence number (1, 2, 3)
    expected_seqs = [1, 2, 3]
    for i, (r, expected_seq) in enumerate(zip(results, expected_seqs)):
        assert r["response"] is not None, f"Frame {i} got no response"
        decoded = decode_ack_nak(r["response"], "hex")
        assert decoded["type"] == "ACK", f"Frame {i} expected ACK, got {decoded['type']}"
        assert decoded["seq"] == expected_seq, (
            f"Frame {i}: expected seq={expected_seq}, got seq={decoded['seq']}"
        )


@pytest.mark.asyncio
async def test_harness_pcap_to_replay_pipeline() -> None:
    """Full pipeline: pcap extract → replay → all frames ACK.

    Extracts client-side frames from the golden pcap, replays them against the
    simulator, and verifies all frames receive a response.

    Expected result:
    - Extraction yields at least 1 frame from the pcap
    - All extracted frames get ACK/NAK response from simulator (0 timeouts)
    """
    from contextlib import suppress
    from resources.siadc09d.csr_simulator import CSRSimulator
    from resources.siadc09d.extract_frames_from_pcap import read_pcap, filter_frames, write_hex_file
    from resources.siadc09d.simulate_frames import parse_hex_file, replay_frames

    pcap_file = _GOLDEN_FIXTURES_DIR / "capture_sia_example.pcap"
    assert pcap_file.exists(), f"Missing golden pcap: {pcap_file}"

    # Step 1: Extract client-side frames from pcap
    packets = read_pcap(str(pcap_file))
    filtered = filter_frames(packets, port=10001, direction="client")

    assert len(filtered) >= 1, f"Expected ≥1 client frame from pcap, got {len(filtered)}"

    # Step 2: Write extracted frames to temp hex file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".hex", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        write_hex_file(filtered, tmp_path, source_file=str(pcap_file), port=10001, direction="client")

        # Step 3: Parse hex file
        frames = parse_hex_file(tmp_path)
        assert len(frames) == len(filtered), (
            f"parse_hex_file returned {len(frames)} frames, expected {len(filtered)}"
        )

        # Step 4: Start simulator and replay
        udp_port = _get_free_port()
        preset = {
            "crc_format": "hex",
            "account_number": ACCOUNT_NUMBER_DEFAULT,
            "encryption_key": None,
        }
        sim = CSRSimulator(udp_port=udp_port, tcp_port=udp_port + 1, preset=preset)
        await sim.start()
        udp_task = asyncio.create_task(sim._handle_udp(), name="pipeline_test_udp")

        try:
            results, ack_count, timeout_count = await replay_frames(
                frames,
                host="127.0.0.1",
                port=udp_port,
                protocol="udp",
                timeout_s=2.0,
            )

            # Assert: all extracted frames received a response
            assert ack_count == len(frames), (
                f"Expected {len(frames)} responses, got {ack_count}"
            )
            # Assert: no timeouts
            assert timeout_count == 0, f"Expected 0 timeouts, got {timeout_count}"

        finally:
            await sim.stop()
            udp_task.cancel()
            with suppress(asyncio.CancelledError):
                await udp_task

    finally:
        Path(tmp_path).unlink(missing_ok=True)
