"""
CLI wrapper for CSR Simulator.

Provides a standalone command-line interface for the CSRSimulator protocol test tool.
Reuses the CSRSimulator class from Story 1.4 (resources.siadc09d.csr_simulator) and
adds CLI argument parsing, configuration loading, and graceful lifecycle management.

This is a development testing tool — not part of the production daemon.
"""

import asyncio
import argparse
import logging
import signal
import sys
from typing import Optional

from resources.siadc09d.csr_simulator import CSRSimulator


# CLI Constants
DEFAULT_UDP_PORT = 10001
DEFAULT_TCP_PORT = 5000
DEFAULT_LISTEN_HOST = "127.0.0.1"
SIMULATOR_VERSION = "1.0"

# Module logger
logger = logging.getLogger(__name__)


def parse_arguments(args: list[str]) -> argparse.Namespace:
    """
    Parse command-line arguments for CSR simulator CLI.

    Args:
        args: List of command-line arguments (typically sys.argv[1:])

    Returns:
        Parsed arguments namespace with all configured options

    Raises:
        SystemExit: If arguments are invalid or --help/--version provided
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m tests.simulator",
        description="Standalone CSR Simulator for testing SIA DC-09 protocol integration",
    )

    # Add version argument
    parser.add_argument(
        "--version",
        action="version",
        version=f"CSR Simulator {SIMULATOR_VERSION}",
    )

    # Add port arguments
    parser.add_argument(
        "--udp-port",
        type=int,
        default=DEFAULT_UDP_PORT,
        help=f"UDP port to listen on (default: {DEFAULT_UDP_PORT})",
    )

    parser.add_argument(
        "--tcp-port",
        type=int,
        default=DEFAULT_TCP_PORT,
        help=f"TCP port to listen on (default: {DEFAULT_TCP_PORT})",
    )

    # Add host argument
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_LISTEN_HOST,
        help=f"Host/IP address to listen on (default: {DEFAULT_LISTEN_HOST})",
    )

    # Add CRC format argument
    parser.add_argument(
        "--crc-format",
        type=str,
        choices=["hex", "bin"],
        default="hex",
        help="CRC encoding format: hex (4 ASCII chars) or bin (2 bytes) (default: hex)",
    )

    # Add account argument
    parser.add_argument(
        "--account",
        type=str,
        default="000001",
        help="Account number (3-16 hex characters, default: 000001)",
    )

    # Add optional encryption key argument
    parser.add_argument(
        "--encryption-key",
        type=str,
        default=None,
        help="AES-128 encryption key as 32-char hex string (optional)",
    )

    # Add optional log file argument
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Log frame exchanges to file (optional)",
    )

    # Add log level argument
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    return parser.parse_args(args)


def validate_config(args: argparse.Namespace) -> dict:
    """
    Validate CLI arguments and build CSRSimulator preset configuration.

    Args:
        args: Parsed command-line arguments from parse_arguments()

    Returns:
        Preset dict with keys:
        - crc_format: 'hex' or 'bin'
        - account_number: 3-16 hex character string
        - encryption_key: None or 16-byte AES-128 key as bytes

    Raises:
        ValueError: If any configuration value is invalid
    """
    preset: dict = {}

    # Validate and store CRC format
    if args.crc_format not in ("hex", "bin"):
        raise ValueError(f"Invalid crc_format: '{args.crc_format}' (must be 'hex' or 'bin')")
    preset["crc_format"] = args.crc_format

    # Validate port ranges
    if not (1 <= args.udp_port <= 65535):
        raise ValueError(f"UDP port out of range: {args.udp_port} (must be 1-65535)")
    if not (1 <= args.tcp_port <= 65535):
        raise ValueError(f"TCP port out of range: {args.tcp_port} (must be 1-65535)")

    # Validate and store account number
    if not isinstance(args.account, str):
        raise ValueError(f"account_number must be string, got {type(args.account).__name__}")

    if len(args.account) < 3 or len(args.account) > 16:
        raise ValueError(
            f"account_number must be 3-16 characters, got {len(args.account)} (value: '{args.account}')"
        )

    # Validate hex format
    try:
        int(args.account, 16)
    except ValueError:
        raise ValueError(f"account_number must be valid hex characters, got '{args.account}'")

    preset["account_number"] = args.account

    # Validate and convert encryption key
    if args.encryption_key is not None:
        try:
            # Convert hex string to bytes
            key_bytes = bytes.fromhex(args.encryption_key)

            # Validate key length (16 bytes for AES-128, 24 for AES-192, 32 for AES-256)
            if len(key_bytes) not in (16, 24, 32):
                raise ValueError(
                    f"Encryption key must be 16, 24, or 32 bytes ({len(key_bytes)} bytes provided)"
                )

            preset["encryption_key"] = key_bytes
        except ValueError as e:
            if "non-hexadecimal" in str(e) or "invalid literal" in str(e):
                raise ValueError(f"Encryption key must be valid hex string: {args.encryption_key}") from e
            raise
    else:
        preset["encryption_key"] = None

    return preset


async def async_main(args: list[str]) -> None:
    """
    Async entry point for simulator lifecycle.

    Parses arguments, validates configuration, creates and manages CSRSimulator.
    Handles graceful shutdown on SIGINT/SIGTERM signals.

    Args:
        args: Command-line arguments (typically sys.argv[1:])

    Raises:
        ValueError: If configuration validation fails
        CSRSimulatorError: If simulator startup fails
    """
    # Parse arguments
    parsed_args = parse_arguments(args)

    # Setup logging based on --log-level
    log_level = parsed_args.log_level
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Validate configuration and build preset
    preset = validate_config(parsed_args)

    # Create simulator instance
    simulator = CSRSimulator(
        udp_port=parsed_args.udp_port,
        tcp_port=parsed_args.tcp_port,
        preset=preset,
    )

    # Setup graceful shutdown on signals
    def signal_handler(signum: int, frame: object) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down...")
        raise KeyboardInterrupt()

    loop = asyncio.get_event_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, signal_handler, sig, None)

    try:
        # Start simulator
        logger.info(f"Starting CSR Simulator on UDP:{parsed_args.udp_port}, TCP:{parsed_args.tcp_port}")
        await simulator.start()

        # Log startup message
        logger.info(
            f"CSR Simulator running - "
            f"UDP:{parsed_args.udp_port} TCP:{parsed_args.tcp_port} "
            f"CRC:{preset['crc_format']} Account:{preset['account_number']}"
        )

        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown initiated...")
    finally:
        # Graceful shutdown
        await simulator.stop()
        logger.info("CSR Simulator stopped")


def main() -> None:
    """
    Synchronous entry point for CLI.

    Parses arguments and delegates to async_main via asyncio.run().
    """
    try:
        asyncio.run(async_main(sys.argv[1:]))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
