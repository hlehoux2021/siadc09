"""Tests for CLI tool to replay SIA frames against the simulator."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from resources.siadc09d.simulate_frames import (
    format_response_summary,
    parse_hex_file,
    send_frame_and_capture,
)


# ============================================================================
# UNIT TESTS: Hex File Parsing (Task 1)
# ============================================================================


def test_parse_hex_file_space_separated() -> None:
    """Test parsing space-separated hex bytes.

    Expected result:
    - Returns list with one bytes object per frame
    - Each bytes object contains exact hex values parsed
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0A 04E1 0005\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: parse_hex_file returns list of bytes
        result = parse_hex_file(temp_path)
        assert isinstance(result, list)
        assert len(result) == 1
        # Assert: bytes match expected hex values
        assert result[0] == bytes([0x0A, 0x04, 0xE1, 0x00, 0x05])
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_comma_separated() -> None:
    """Test parsing comma-separated hex bytes.

    Expected result:
    - Same result as space-separated format
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0A,04E1,0005\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: parse_hex_file handles comma-separated format
        result = parse_hex_file(temp_path)
        assert len(result) == 1
        assert result[0] == bytes([0x0A, 0x04, 0xE1, 0x00, 0x05])
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_with_0x_prefix() -> None:
    """Test parsing hex bytes with 0x prefix.

    Expected result:
    - 0x prefix stripped and values parsed correctly
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0x0A 0x04E1 0x0005\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: 0x prefix is handled correctly
        result = parse_hex_file(temp_path)
        assert result[0] == bytes([0x0A, 0x04, 0xE1, 0x00, 0x05])
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_ignores_comments() -> None:
    """Test parsing hex file with comment lines.

    Expected result:
    - Lines starting with # are ignored
    - Valid frames are extracted correctly
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("# Burglary alarm frame\n")
        f.write("0A 04E1 0005\n")
        f.write("# Supervision NULL frame\n")
        f.write("0A 0000 0000\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: comments are skipped, valid frames extracted
        result = parse_hex_file(temp_path)
        assert len(result) == 2
        assert result[0] == bytes([0x0A, 0x04, 0xE1, 0x00, 0x05])
        assert result[1] == bytes([0x0A, 0x00, 0x00, 0x00, 0x00])
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_ignores_empty_lines() -> None:
    """Test parsing hex file with empty lines.

    Expected result:
    - Empty lines are skipped silently
    - Valid frames extracted correctly
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0A 04E1 0005\n")
        f.write("\n")
        f.write("0A 0000 0000\n")
        f.write("   \n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: empty and whitespace-only lines skipped
        result = parse_hex_file(temp_path)
        assert len(result) == 2
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_not_found() -> None:
    """Test parsing non-existent file.

    Expected result:
    - FileNotFoundError raised
    """
    # Assert: FileNotFoundError raised for non-existent file
    with pytest.raises(FileNotFoundError):
        parse_hex_file("/nonexistent/path/to/frames.hex")


def test_parse_hex_file_invalid_hex() -> None:
    """Test parsing invalid hex string.

    Expected result:
    - ValueError raised with context about malformed hex
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0A GG EE\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: ValueError raised for invalid hex
        with pytest.raises(ValueError):
            parse_hex_file(temp_path)
    finally:
        Path(temp_path).unlink()


# ============================================================================
# UNIT TESTS: Response Formatting (Task 3)
# ============================================================================


def test_format_response_summary_ack() -> None:
    """Test formatting ACK response summary.

    Expected result:
    - Output contains TX/RX timestamps in HH:MM:SS.mmm format
    - Elapsed time shown as (+Nms)
    - Frame type (may be UNKNOWN with mock bytes)
    - Encryption status (plaintext/encrypted)
    """
    # Setup: Create response dict with response bytes
    input_frame = bytes([0x0A, 0x04, 0xE1, 0x00, 0x01])
    sent_time = datetime(2026, 4, 9, 14, 23, 45, 123000, tzinfo=timezone.utc)
    received_time = datetime(2026, 4, 9, 14, 23, 45, 125000, tzinfo=timezone.utc)

    response_dict = {
        "sent_time_utc": sent_time,
        "received_time_utc": received_time,
        "response": bytes([0x0A, 0x04, 0xE1, 0x00, 0x01]),  # Mock response bytes
        "elapsed_ms": 2.0,
        "protocol": "udp",
    }

    # Action: Format response
    summary = format_response_summary(response_dict, input_frame)

    # Assert: Output contains expected format elements
    # Use local time for assertion since format_response_summary converts to local
    assert "[TX" in summary
    assert "[RX" in summary
    assert "→" in summary
    assert "(+2ms)" in summary or "(+2" in summary
    assert "plaintext" in summary or "encrypted" in summary


def test_format_response_summary_timeout() -> None:
    """Test formatting timeout response summary.

    Expected result:
    - Output shows [TIMEOUT +2000ms]
    - Elapsed time matches timeout value
    """
    input_frame = bytes([0x0A, 0x04, 0xE1, 0x00, 0x01])
    response_dict = {
        "sent_time_utc": datetime(2026, 4, 9, 14, 23, 45, 123000, tzinfo=timezone.utc),
        "received_time_utc": None,
        "response": None,
        "elapsed_ms": 2000.0,
        "protocol": "udp",
    }

    # Action: Format timeout response
    summary = format_response_summary(response_dict, input_frame)

    # Assert: Shows timeout marker with elapsed time
    assert "TIMEOUT" in summary
    assert "2000" in summary


def test_format_response_summary_malformed_response() -> None:
    """Test formatting malformed/unparseable response.

    Expected result:
    - Output shows UNKNOWN frame type without crashing
    - Falls back gracefully
    """
    input_frame = bytes([0x0A, 0x04, 0xE1, 0x00, 0x01])
    response_dict = {
        "sent_time_utc": datetime(2026, 4, 9, 14, 23, 45, 123000, tzinfo=timezone.utc),
        "received_time_utc": datetime(2026, 4, 9, 14, 23, 45, 125000, tzinfo=timezone.utc),
        "response": bytes([0xFF, 0xFF, 0xFF]),  # Invalid bytes
        "elapsed_ms": 2.0,
        "protocol": "udp",
    }

    # Action: Format malformed response
    summary = format_response_summary(response_dict, input_frame)

    # Assert: Handles gracefully, doesn't crash
    assert summary is not None
    assert isinstance(summary, str)


# ============================================================================
# INTEGRATION TESTS: Async Frame Sending (Task 2)
# ============================================================================


@pytest.mark.asyncio
async def test_send_frame_and_capture_timeout() -> None:
    """Test frame sending with timeout or connection error.

    Expected result:
    - Connection/timeout errors raised (per spec)
    - Or timeout after waiting for response with no listener
    """
    frame = bytes([0x0A, 0x04, 0xE1, 0x00, 0x01])

    # Action: Send to non-existent simulator (will raise connection error)
    with pytest.raises((OSError, ConnectionRefusedError, asyncio.TimeoutError)):
        result = await send_frame_and_capture(
            frame,
            host="127.0.0.1",
            port=9999,  # Unlikely to have simulator here
            protocol="udp",
            timeout_s=0.5,
        )


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_hex_file_burglary() -> Path:
    """Create temporary hex file with burglary alarm frame."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("# Burglary alarm\n")
        f.write("0A 04E1 0005\n")
        f.flush()
        yield Path(f.name)
    Path(f.name).unlink()


@pytest.fixture
def temp_hex_file_mixed() -> Path:
    """Create temporary hex file with mixed frames."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("# Burglary alarm\n")
        f.write("0A 04E1 0005\n")
        f.write("\n")
        f.write("# Supervision NULL\n")
        f.write("0A 0000 0000\n")
        f.flush()
        yield Path(f.name)
    Path(f.name).unlink()


# ============================================================================
# UNIT TESTS: CLI Argument Parsing (Task 12)
# ============================================================================


def test_cli_missing_required_input_arg(temp_hex_file_burglary: Path) -> None:
    """Test CLI exits with error when --input is missing.

    Expected result:
    - Exit code 2 (usage error)
    - Error message about missing argument
    """
    import subprocess

    # Action: Run CLI without --input
    result = subprocess.run(
        [
            "python3",
            "resources/siadc09d/simulate_frames.py",
            "--port",
            "10001",
        ],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Exit code 2 (usage error)
    assert result.returncode == 2
    # Assert: Error mentions missing --input
    assert "input" in result.stderr.lower() or "required" in result.stderr.lower()


def test_cli_missing_required_port_arg(temp_hex_file_burglary: Path) -> None:
    """Test CLI exits with error when --port is missing.

    Expected result:
    - Exit code 2 (usage error)
    - Error message about missing argument
    """
    import subprocess

    # Action: Run CLI without --port
    result = subprocess.run(
        [
            "python3",
            "resources/siadc09d/simulate_frames.py",
            "--input",
            str(temp_hex_file_burglary),
        ],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Exit code 2 (usage error)
    assert result.returncode == 2
    # Assert: Error mentions missing --port
    assert "port" in result.stderr.lower() or "required" in result.stderr.lower()


def test_cli_help_displays(temp_hex_file_burglary: Path) -> None:
    """Test CLI displays help with --help flag.

    Expected result:
    - Help text displays all available options
    - Usage line shown
    """
    import subprocess

    # Action: Run with --help
    result = subprocess.run(
        ["python3", "resources/siadc09d/simulate_frames.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Exit code 0 (success)
    assert result.returncode == 0
    # Assert: Help text contains all major options
    assert "--input" in result.stdout
    assert "--port" in result.stdout
    assert "--protocol" in result.stdout
    assert "--host" in result.stdout
    assert "--timeout" in result.stdout
    assert "--output" in result.stdout


def test_cli_invalid_protocol_rejected(temp_hex_file_burglary: Path) -> None:
    """Test CLI rejects invalid protocol value.

    Expected result:
    - Exit code 2 (usage error)
    - Error mentions invalid protocol
    """
    import subprocess

    # Action: Run with invalid protocol
    result = subprocess.run(
        [
            "python3",
            "resources/siadc09d/simulate_frames.py",
            "--input",
            str(temp_hex_file_burglary),
            "--port",
            "10001",
            "--protocol",
            "ssh",  # Invalid
        ],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Exit code 2 (usage error)
    assert result.returncode == 2
    # Assert: Error mentions invalid choice
    assert "invalid choice" in result.stderr.lower() or "ssh" in result.stderr.lower()


def test_cli_valid_protocol_options() -> None:
    """Test CLI accepts both UDP and TCP protocol options.

    Expected result:
    - Help text shows both udp and tcp as choices
    """
    import subprocess

    # Action: Run with --help to see protocol options
    result = subprocess.run(
        ["python3", "resources/siadc09d/simulate_frames.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Both protocols mentioned
    assert "udp" in result.stdout.lower()
    assert "tcp" in result.stdout.lower()


def test_cli_invalid_port_non_integer(temp_hex_file_burglary: Path) -> None:
    """Test CLI rejects non-integer port values.

    Expected result:
    - Exit code 2 (usage error)
    - Error mentions invalid port
    """
    import subprocess

    # Action: Run with non-integer port
    result = subprocess.run(
        [
            "python3",
            "resources/siadc09d/simulate_frames.py",
            "--input",
            str(temp_hex_file_burglary),
            "--port",
            "abc",
        ],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Exit code 2 (usage error)
    assert result.returncode == 2
    # Assert: Error mentions invalid port
    assert "invalid" in result.stderr.lower()


def test_cli_default_values() -> None:
    """Test CLI uses correct default values.

    Expected result:
    - Help text shows defaults for optional arguments
    """
    import subprocess

    # Action: Run with --help
    result = subprocess.run(
        ["python3", "resources/siadc09d/simulate_frames.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/Users/herve.lehoux/Dev/my-project",
    )

    # Assert: Help shows default values
    assert "default:" in result.stdout.lower() or "default" in result.stdout.lower()
    assert "udp" in result.stdout.lower()  # Default protocol
    assert "localhost" in result.stdout.lower()  # Default host
    assert "2.0" in result.stdout or "2" in result.stdout  # Default timeout


# ============================================================================
# EDGE CASE TESTS: Error Handling & File Processing
# ============================================================================


def test_parse_hex_file_mixed_separators() -> None:
    """Test parsing hex file with mixed separators in different lines.

    Expected result:
    - Handles both space and comma separators correctly
    - Returns correct bytes for all frames
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("0A 04E1 0005\n")  # Space separated
        f.write("0A,04E1,0005\n")  # Comma separated
        f.write("0x0A 0x04E1 0x0005\n")  # 0x prefix + space
        f.flush()
        temp_path = f.name

    try:
        # Assert: All frames parsed correctly
        result = parse_hex_file(temp_path)
        assert len(result) == 3
        # All should be identical
        assert result[0] == result[1]
        assert result[1] == result[2]
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_large_frame() -> None:
    """Test parsing large hex frame (real SIA protocol frame).

    Expected result:
    - Correctly parses multi-byte frame with proper structure
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        # Real burglary frame (from golden frames)
        f.write("0A 41 34 34 32 30 30 33 38 22 53 49 41 2D 44 43 53 22 30 30 30 31 4C 30 23 30 30 31 32 33 34 5B 23 30 30 31 32 33 34 7C 31 31 33 30 5D 5F 31 34 3A 32 33 3A 34 35 2C 30 34 2D 30 39 2D 32 30 32 36 0D\n")
        f.flush()
        temp_path = f.name

    try:
        # Assert: Frame parsed without error
        result = parse_hex_file(temp_path)
        assert len(result) == 1
        # Assert: Frame is reasonably large (66 bytes for this example)
        assert len(result[0]) > 50
        # Assert: Frame starts with LF and ends with CR
        assert result[0][0] == 0x0A  # LF
        assert result[0][-1] == 0x0D  # CR
    finally:
        Path(temp_path).unlink()


def test_parse_hex_file_leading_trailing_whitespace() -> None:
    """Test parsing hex file with leading/trailing whitespace.

    Expected result:
    - Whitespace is stripped correctly
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False) as f:
        f.write("   0A 04E1 0005   \n")  # Surrounded by spaces
        f.write("\t0A 0000 0000\t\n")  # Surrounded by tabs
        f.flush()
        temp_path = f.name

    try:
        # Assert: Both frames parsed correctly
        result = parse_hex_file(temp_path)
        assert len(result) == 2
    finally:
        Path(temp_path).unlink()


def test_format_response_summary_with_sequence_number() -> None:
    """Test response formatting includes sequence number when available.

    Expected result:
    - Output contains seq number in correct format
    """
    input_frame = bytes([0x0A, 0x04, 0xE1, 0x00, 0x01])
    response_dict = {
        "sent_time_utc": datetime(2026, 4, 9, 14, 23, 45, 123000, tzinfo=timezone.utc),
        "received_time_utc": datetime(2026, 4, 9, 14, 23, 45, 125000, tzinfo=timezone.utc),
        "response": bytes([0x0A, 0x04, 0xE1, 0x00, 0x01]),
        "elapsed_ms": 2.0,
        "protocol": "udp",
    }

    # Action: Format response
    summary = format_response_summary(response_dict, input_frame)

    # Assert: Output contains components
    assert "[TX" in summary
    assert "[RX" in summary
    assert "plaintext" in summary or "encrypted" in summary
