"""Logging & Observability Infrastructure — Logger Configuration.

v1.0: Single root logger with dual-line pattern (French user + English technical).

Module design:
- Single root logger (all modules use logging.getLogger(__name__))
- Framework (jeedom-daemon-py) sets root logger via Utils.init_logger(--loglevel)
- This module provides helper and configuration ON TOP, does NOT override framework setup
- asyncio logger pinned to WARNING to prevent debug spam
- Python CRITICAL level mapped to ERROR for Jeedom compatibility (no CRITICAL display level)

Dual-line logging pattern:
- INFO/WARNING/ERROR lines: User-friendly French text, significant operational events
- DEBUG lines: Technical English detail with structured KEY: field=val format
- Routine supervision ACK cycles: DEBUG only (prevent INFO spam at normal operation)
- State machine events: Always dual-line (one French, one DEBUG)

Privacy rules for logs:
- account_number: Always shown (actionable)
- encryption_key: NEVER shown in logs (not even key length)
- Raw ciphertext bytes: DEBUG only (safe, unusable without key)
- CSR IP:port: Always shown
- Zone name: Always shown

Reference: internal-docs/design/logging-design.md § Tasks 5b.1–5b.3

Module functions:
- _get_logger(name: str) -> logging.Logger
  Returns a logger for the given module name. Framework is responsible for
  handlers, level, and formatter. This function just provides consistent access.

Example usage:
    from resources.siadc09d.logging_config import _get_logger
    logger = _get_logger(__name__)
    logger.info("User-friendly message in French")
    logger.debug("Technical detail in English | key=value")

Type hints and no circular imports:
- Only imports: logging (standard library)
- Zero daemon module imports (avoid circular dependencies)
- All functions type-hinted for safety (built-in str, logging.Logger — no typing needed)
"""

import logging

# Pin asyncio logger to WARNING at import time to prevent debug spam from asyncio internals.
# Framework (jeedom-daemon-py) may set root to DEBUG; asyncio must stay quiet regardless.
logging.getLogger("asyncio").setLevel(logging.WARNING)


def _get_logger(name: str) -> logging.Logger:
    """Get or create a logger for the given module name.

    This is a simple wrapper around logging.getLogger() that ensures consistent
    logger access across all daemon modules. The framework (jeedom-daemon-py)
    is responsible for configuring the root logger via Utils.init_logger(--loglevel).
    This function does NOT override framework configuration.

    Args:
        name: Module name (typically __name__), supports dotted package names
              (e.g., "resources.siadc09d.daemon")

    Returns:
        Configured logging.Logger instance inherited from root logger config

    Raises:
        TypeError: If name is not a string

    Note:
        - Returns the same logger instance for the same name (Python logging caching)
        - Logging level set by framework via root logger (not here)
        - Handlers provided by framework (jeedom-daemon-py Utils.init_logger)
        - This function respects framework setup and doesn't modify it
    """
    if not isinstance(name, str):
        raise TypeError(f"Logger name must be string, got {type(name).__name__}")

    return logging.getLogger(name)
