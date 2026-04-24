#!/usr/bin/env python3
"""CLI tool for replaying SIA frames against a simulator for protocol testing.

This module reads hex dump files containing frame data and sends them to a running
CSR simulator instance, capturing and displaying responses. Supports both UDP and TCP
protocols with configurable timeouts and delays.

Reference: docs/design/daemon-design.md § "Transport Layer Patterns"
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Handle imports for both direct execution and module import
try:
    from resources.siadc09d.sia_protocol import decode_ack_nak
except (ModuleNotFoundError, ImportError):
    # Support running as script from project root
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from resources.siadc09d.sia_protocol import decode_ack_nak

# ===== Constants =====

TIMEOUT_DEFAULT_S = 2.0
PROTOCOL_UDP = "udp"
PROTOCOL_TCP = "tcp"
HOST_DEFAULT = "localhost"
PORT_MIN, PORT_MAX = 1, 65535
DELAY_DEFAULT_MS = 0
TCP_BUFFER_SIZE_BYTES = 1024

logger = logging.getLogger(__name__)


# ===== Helper Functions =====


def detect_crc_format(frame: bytes) -> str:
    """Detect CRC format (hex or binary) from frame structure.

    Args:
        frame: Raw frame bytes (LF + CRC + ...)

    Returns:
        "hex" if CRC is hex ASCII, "binary" if CRC is raw bytes

    Reference: SIA-DC-09 § 5.5.1.2 CRC format detection
    """
    if len(frame) < 10:
        return "hex"  # Default for short frames

    try:
        # Hex format: CRC bytes 1-4 are ASCII hex, length bytes 5-8 are ASCII hex
        # Binary format: CRC bytes 1-2 are raw, length bytes 3-4 are raw
        crc_and_len = frame[1:9]

        # Check if all bytes are ASCII hex digits (0-9, A-F, a-f)
        for byte_val in crc_and_len:
            if not ((0x30 <= byte_val <= 0x39) or  # 0-9
                    (0x41 <= byte_val <= 0x46) or  # A-F
                    (0x61 <= byte_val <= 0x66)):   # a-f
                return "binary"
        return "hex"
    except Exception:
        return "hex"


# ===== Task 1: Hex File Parser =====


def parse_hex_file(filepath: str) -> list[bytes]:
    """Load and parse hex dump file.

    Returns list of frame bytes, one frame per line.

    Args:
        filepath: Path to `.hex` file with one frame per line

    Returns:
        List of bytes objects, each representing one complete frame

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If hex string is malformed (not valid hex)

    Expected format support:
    - Space-separated: `0x0A 04E1 0005 ...` or `0A 04E1 0005 ...`
    - Comma-separated: `0x0A,04E1,0005,...` or `0A,04E1,0005,...`
    - Comments: Lines starting with `#` are ignored
    - Empty lines: Skipped silently

    Reference:
        SIA-DC-09-2021 § 5.5 — Frame structure reference
    """
    if not Path(filepath).exists():
        raise FileNotFoundError(f"Hex file not found: {filepath}")

    frames: list[bytes] = []

    with open(filepath, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Parse hex values (space or comma separated)
            # Support both "0A" and "0x0A" formats
            try:
                # Normalize separators and handle 0x prefix
                # Replace commas with spaces for uniform parsing
                normalized = line.replace(",", " ")

                # Split and filter empty strings
                hex_strs = [h.strip() for h in normalized.split() if h.strip()]

                if not hex_strs:
                    continue

                # Convert hex strings to bytes (each 2 hex chars = 1 byte)
                frame_bytes: list[int] = []
                for hex_str in hex_strs:
                    # Remove 0x prefix if present
                    if hex_str.startswith("0x") or hex_str.startswith("0X"):
                        hex_str = hex_str[2:]

                    # Validate hex characters
                    if not all(c in "0123456789ABCDEFabcdef" for c in hex_str):
                        raise ValueError(f"Invalid hex characters in '{hex_str}'")

                    # Reject odd-length hex strings (each byte needs exactly 2 hex digits)
                    if len(hex_str) % 2 == 1:
                        raise ValueError(f"Odd-length hex string '{hex_str}' - bytes require exactly 2 hex digits")

                    for i in range(0, len(hex_str), 2):
                        byte_hex = hex_str[i:i+2]
                        byte_val = int(byte_hex, 16)
                        frame_bytes.append(byte_val)

                if frame_bytes:
                    frames.append(bytes(frame_bytes))

            except ValueError as e:
                raise ValueError(
                    f"Line {line_num}: Invalid hex string '{line}': {e}"
                ) from e

    return frames


# ===== Task 2: Async Frame Sending with Response Capture =====


async def send_frame_and_capture(
    frame: bytes,
    host: str,
    port: int,
    protocol: str,
    timeout_s: float = TIMEOUT_DEFAULT_S,
) -> dict[str, Any]:
    """Send frame to simulator and capture response.

    Args:
        frame: Complete frame bytes (LF + CRC + Length + Message + CR)
        host: CSR simulator host
        port: CSR simulator port
        protocol: 'udp' or 'tcp'
        timeout_s: Response wait timeout in seconds (default 2.0s)

    Returns:
        Dict with keys:
        - sent_time_utc: datetime — ISO8601 UTC timestamp when frame was sent
        - received_time_utc: Optional[datetime] — When response received (None if timeout)
        - response: Optional[bytes] — Received frame (None if timeout)
        - elapsed_ms: float — Round-trip time in milliseconds
        - protocol: str — 'udp' or 'tcp' (echo back for logging)

    Network handling:
    - UDP: Send via asyncio.open_datagram_connection(), wait for response on same port
    - TCP: Send via asyncio.open_connection(), wait for response on same socket
    - Timeout: Use asyncio.wait_for(..., timeout=timeout_s) — raise asyncio.TimeoutError if no response
    - Error mapping:
      - asyncio.TimeoutError → Log warning, return received_time_utc=None, response=None, elapsed_ms=timeout_s*1000
      - OSError (connection refused) → Log error, raise
      - Other exceptions → Log and re-raise

    Reference:
        daemon-design.md § "Transport Layer Patterns"
    """
    sent_time_utc = datetime.now(timezone.utc)

    try:
        if protocol == PROTOCOL_UDP:
            # UDP: create a datagram endpoint and send/receive
            loop = asyncio.get_event_loop()

            # Create a future for receiving the response
            response_future: asyncio.Future[tuple[bytes, tuple[str, int]]] = loop.create_future()

            class UDPProtocol(asyncio.DatagramProtocol):
                def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                    # Accept response from any address (datagram source validation happens at network layer)
                    # Note: In production, may want to validate addr matches expected (host, port)
                    if not response_future.done():
                        response_future.set_result((data, addr))

                def error_received(self, exc: Exception) -> None:
                    if not response_future.done():
                        response_future.set_exception(exc)

            transport, _ = await loop.create_datagram_endpoint(
                UDPProtocol, remote_addr=(host, port)
            )

            try:
                transport.sendto(frame)

                # Wait for response with timeout
                response_bytes, _ = await asyncio.wait_for(
                    response_future, timeout=timeout_s
                )

                received_time_utc = datetime.now(timezone.utc)
                elapsed_ms = (received_time_utc - sent_time_utc).total_seconds() * 1000

                return {
                    "sent_time_utc": sent_time_utc,
                    "received_time_utc": received_time_utc,
                    "response": response_bytes,
                    "elapsed_ms": elapsed_ms,
                    "protocol": protocol,
                }
            finally:
                transport.close()

        elif protocol == PROTOCOL_TCP:
            # TCP: open_connection with timeout, send, wait for response
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout_s
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"TCP connection timeout after {timeout_s}s ({host}:{port})"
                )
                return {
                    "sent_time_utc": sent_time_utc,
                    "received_time_utc": None,
                    "response": None,
                    "elapsed_ms": timeout_s * 1000,
                    "protocol": protocol,
                }

            try:
                writer.write(frame)
                await writer.drain()

                # Wait for response with timeout (read up to TCP_BUFFER_SIZE_BYTES, don't assume fixed length)
                response_bytes = await asyncio.wait_for(
                    reader.read(TCP_BUFFER_SIZE_BYTES),
                    timeout=timeout_s,
                )

                received_time_utc = datetime.now(timezone.utc)
                elapsed_ms = (received_time_utc - sent_time_utc).total_seconds() * 1000

                return {
                    "sent_time_utc": sent_time_utc,
                    "received_time_utc": received_time_utc,
                    "response": response_bytes,
                    "elapsed_ms": elapsed_ms,
                    "protocol": protocol,
                }
            finally:
                writer.close()
                await writer.wait_closed()

        else:
            raise ValueError(f"Unsupported protocol: {protocol}")

    except asyncio.TimeoutError:
        # Timeout: return None for response fields
        logger.warning(
            f"Frame send timeout after {timeout_s}s ({protocol} {host}:{port})"
        )
        return {
            "sent_time_utc": sent_time_utc,
            "received_time_utc": None,
            "response": None,
            "elapsed_ms": timeout_s * 1000,
            "protocol": protocol,
        }
    except OSError as e:
        logger.error(f"Connection error ({protocol} {host}:{port}): {e}")
        raise
    except Exception as e:
        logger.error(f"Error sending frame: {e}")
        raise


# ===== Task 3: Response Decoding and Display =====


def format_response_summary(response_dict: dict[str, Any], input_frame: bytes) -> str:
    """Create human-readable summary line for CLI output.

    Inputs:
    - response_dict from send_frame_and_capture() (sent_time, received_time, response, elapsed_ms)
    - input_frame (original frame sent, for reference)

    Output format (one line per frame exchange):
    ```
    [TX 14:23:45.123] → [RX 14:23:45.125 (+2ms)] ACK seq=0001 plaintext
    ```

    Format breakdown:
    - [TX HH:MM:SS.mmm] — Send timestamp (local time for readability)
    - → — Separator
    - [RX HH:MM:SS.mmm (+Nms)] — Receive timestamp + elapsed time
    - Frame type (ACK/NAK/ALARM/UNKNOWN) — decoded from response
    - Optional seq number if parseable
    - Encryption status (plaintext/encrypted)
    - Or [TIMEOUT +2000ms] if no response

    Args:
        response_dict: Dict from send_frame_and_capture()
        input_frame: Original frame sent

    Returns:
        Formatted summary string

    Reference:
        logging-design.md § "Ring Buffer & Audit Trail"
    """
    sent_time = response_dict["sent_time_utc"]
    received_time = response_dict["received_time_utc"]
    response = response_dict["response"]
    elapsed_ms = response_dict["elapsed_ms"]

    # Format TX timestamp (local time)
    tx_time_str = sent_time.astimezone().strftime("%H:%M:%S.%f")[:-3]

    if received_time is None or response is None:
        # Timeout case
        return f"[TX {tx_time_str}] → [TIMEOUT +{int(elapsed_ms)}ms]"

    # Format RX timestamp and elapsed time
    rx_time_str = received_time.astimezone().strftime("%H:%M:%S.%f")[:-3]

    # Try to decode response using decode_ack_nak (auto-detect CRC format)
    try:
        crc_format = detect_crc_format(response)
        decoded = decode_ack_nak(response, crc_format=crc_format)
        frame_type = decoded["type"].upper()
        seq = decoded.get("seq")
    except Exception:
        frame_type = "UNKNOWN"
        seq = None

    # Determine encryption status
    encryption_status = "encrypted" if b"*" in response[:10] else "plaintext"

    # Build summary line
    summary = f"[TX {tx_time_str}] → [RX {rx_time_str} (+{int(elapsed_ms)}ms)] {frame_type}"

    if seq is not None:
        summary += f" seq={seq:04d}"

    summary += f" {encryption_status}"

    return summary


# ===== Task 4: CLI Entry Point Script =====


async def replay_frames(
    frames: list[bytes],
    host: str,
    port: int,
    protocol: str,
    timeout_s: float = TIMEOUT_DEFAULT_S,
    delay_ms: int = DELAY_DEFAULT_MS,
) -> tuple[list[dict[str, Any]], int, int]:
    """Replay all frames against simulator.

    Args:
        frames: List of frame bytes to send
        host: Simulator host
        port: Simulator port
        protocol: 'udp' or 'tcp'
        timeout_s: Response timeout per frame
        delay_ms: Pause between frames in milliseconds

    Returns:
        Tuple (results_list, successful_count, timeout_count)
    """
    results: list[dict[str, Any]] = []
    successful_count = 0
    timeout_count = 0

    for frame_idx, frame in enumerate(frames, 1):
        try:
            result = await send_frame_and_capture(
                frame, host, port, protocol, timeout_s
            )
            results.append(result)

            # Display summary
            summary = format_response_summary(result, frame)
            logger.info(summary)

            if result["received_time_utc"] is None:
                timeout_count += 1
            else:
                successful_count += 1

            # Pause between frames if configured
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

        except Exception as e:
            logger.error(f"Frame {frame_idx}: {e}")
            timeout_count += 1

    return results, successful_count, timeout_count


def _build_json_results(
    frames: list[bytes], results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build JSON results array with frame_type and seq fields.

    Args:
        frames: List of sent frame bytes
        results: List of response dicts from replay_frames()

    Returns:
        List of result objects with all JSON fields populated
    """
    json_results = []
    for i, (frame, result) in enumerate(zip(frames, results)):
        response = result["response"]
        frame_type = None
        seq = None

        # Decode response to extract frame type and sequence number
        if response is not None:
            try:
                crc_format = detect_crc_format(response)
                decoded = decode_ack_nak(response, crc_format=crc_format)
                frame_type = decoded["type"].upper()
                seq = decoded.get("seq")
            except Exception:
                # If decoding fails, leave frame_type and seq as None
                pass

        json_results.append({
            "frame_index": i,
            "sent_hex": frame.hex().upper(),
            "sent_time_utc": result["sent_time_utc"].isoformat(),
            "response_hex": response.hex().upper() if response else None,
            "received_time_utc": (
                result["received_time_utc"].isoformat()
                if result["received_time_utc"]
                else None
            ),
            "elapsed_ms": result["elapsed_ms"],
            "frame_type": frame_type,
            "seq": seq,
            "status": "ok" if result["received_time_utc"] else "timeout",
        })

    return json_results


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Replay SIA frames from hex file against simulator"
    )
    parser.add_argument("--input", required=True, help="Hex dump file path")
    parser.add_argument("--port", type=int, required=True, help="Simulator port")
    parser.add_argument(
        "--protocol",
        choices=["udp", "tcp"],
        default="udp",
        help="Transport protocol (default: udp)",
    )
    parser.add_argument(
        "--host",
        default=HOST_DEFAULT,
        help=f"Simulator host (default: {HOST_DEFAULT})",
    )
    parser.add_argument(
        "--delay-between-frames",
        type=int,
        default=DELAY_DEFAULT_MS,
        help="Pause (ms) between frames (default: 0)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=TIMEOUT_DEFAULT_S,
        help=f"Response timeout (s) (default: {TIMEOUT_DEFAULT_S})",
    )
    parser.add_argument(
        "--output", help="Save results to JSON file"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(levelname)s: %(message)s"
    )

    try:
        # Validate arguments
        if not (PORT_MIN <= args.port <= PORT_MAX):
            logger.error(f"Port must be between {PORT_MIN} and {PORT_MAX}")
            return

        if args.timeout <= 0:
            logger.error("Timeout must be > 0")
            return

        # Load hex file
        logger.info(f"Loading frames from {args.input}...")
        frames = parse_hex_file(args.input)
        logger.info(f"Loaded {len(frames)} frames from {args.input}")

        # Validate frame list is not empty
        if not frames:
            logger.error(f"No valid frames found in {args.input}")
            return

        # Replay frames
        results, successful, timeouts = asyncio.run(
            replay_frames(
                frames,
                args.host,
                args.port,
                args.protocol,
                args.timeout,
                args.delay_between_frames,
            )
        )

        # Summary
        logger.info(f"Completed {successful + timeouts}/{len(frames)} frames ({timeouts} timeouts)")

        # JSON output if requested
        if args.output:
            output_data = {
                "metadata": {
                    "input_file": args.input,
                    "protocol": args.protocol,
                    "host": args.host,
                    "port": args.port,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "total_frames": len(frames),
                    "successful": successful,
                    "timeouts": timeouts,
                },
                "results": _build_json_results(frames, results),
            }

            try:
                with open(args.output, "w") as f:
                    json.dump(output_data, f, indent=2)
                logger.info(f"Results saved to {args.output}")
            except IOError as e:
                logger.error(f"Failed to write JSON output to {args.output}: {e}")
                exit(1)

        # Exit code
        exit_code = 0 if timeouts == 0 else 1
        exit(exit_code)

    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        exit(1)
    except ValueError as e:
        logger.error(f"Error: {e}")
        exit(1)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
