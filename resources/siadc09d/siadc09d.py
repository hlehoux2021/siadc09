#!/usr/bin/env python3
"""SIA DC-09 Daemon Entry Point.

This script is the CLI entry point called by PHP (both for normal daemon
operation and --test-only connection test mode).

Two modes:
  --test-only: Standalone subprocess — sends one NULL frame, prints JSON result,
               exits. Never initializes Jeedom socket or supervision loop.
  Normal:      Starts the full SIADaemon via jeedomdaemon framework.

Reference: docs/design/wizard-design.md §Task 3.10
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure the package is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siadc09d.sia_protocol import SIAMessageBuilder
from siadc09d.sia_transport import (
    SIABaseTransport,
    SIATransportError,
    SIATCPTransport,
    SIAUDPTransport,
    TransportType,
)

_logger = logging.getLogger(__name__)

_TEST_RECEIVE_TIMEOUT_S: float = 10.0
_TEST_CONNECT_TIMEOUT_S: float = 5.0
_TEST_WIRE_CRC_FORMAT = "hex"


async def _send_raw_once(
    host: str,
    port: int,
    transport: str,
    frame: bytes,
    *,
    timeout: int,
) -> dict[str, str]:
    """Send one SIA frame and return the parsed CSR response status.

    Standalone async function — no SM1 context, no ring buffer, no Jeedom
    callbacks. Opens socket, sends, receives, closes.

    Args:
        host: CSR hostname or IP.
        port: CSR port number.
        transport: "udp" or "tcp" (case-insensitive).
        frame: Complete SIA DC-09 frame bytes.
        timeout: Overall operation timeout in seconds.

    Returns:
        Dict with 'status' key: 'ack', 'nak', or 'timeout'.
    """
    transport_type = TransportType(transport.upper())

    t: SIABaseTransport
    if transport_type == TransportType.UDP:
        t = SIAUDPTransport(
            host=host,
            port=port,
            receive_timeout_s=min(timeout, _TEST_RECEIVE_TIMEOUT_S),
            crc_format=_TEST_WIRE_CRC_FORMAT,
        )
    else:
        t = SIATCPTransport(
            host=host,
            port=port,
            connect_timeout_s=_TEST_CONNECT_TIMEOUT_S,
            receive_timeout_s=min(timeout, _TEST_RECEIVE_TIMEOUT_S),
            crc_format=_TEST_WIRE_CRC_FORMAT,
        )

    try:
        await t.start()
        result = await asyncio.wait_for(t.send_frame(frame), timeout=timeout)
        return {"status": result["status"]}
    except (asyncio.TimeoutError, TimeoutError):
        return {"status": "timeout"}
    except (SIATransportError, OSError):
        return {"status": "timeout"}
    except Exception:
        return {"status": "timeout"}
    finally:
        await t.close()


async def run_connection_test(config: dict, timeout: int) -> None:
    """Run a standalone connection test and print JSON result to stdout.

    Reads CSR parameters from config dict (or preset JSON if not manual mode).
    Builds a NULL frame, sends it via _send_raw_once(), prints result.

    Args:
        config: Configuration dict from PHP (eqLogic configuration minus encryption_key).
        timeout: Overall test timeout in seconds.
    """
    csr_provider = config.get("csr_provider", "")

    if csr_provider != "manual":
        presets_path = Path(__file__).parent / "csr_presets.json"
        try:
            presets_data = json.loads(presets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({
                "status": "error",
                "detail": f"Impossible de charger les presets CSR : {e}",
            }), flush=True)
            return

        preset = None
        for p in presets_data.get("presets", []):
            if p.get("id") == csr_provider:
                preset = p
                break

        if preset is None:
            print(json.dumps({
                "status": "error",
                "detail": f"Preset '{csr_provider}' introuvable dans csr_presets.json",
            }), flush=True)
            return

        host = preset.get("csr_ip", "")
        try:
            port = int(preset.get("csr_port", 0))
        except (ValueError, TypeError):
            port = 0
        transport = preset.get("transport", "udp")
        crc_format = preset.get("crc_format", "hex")
        encryption_enabled = bool(preset.get("encryption_enabled", False))
    else:
        host = config.get("csr_ip", "")
        try:
            port = int(config.get("csr_port", 0))
        except (ValueError, TypeError):
            port = 0
        transport = config.get("transport", "udp")
        crc_format = config.get("crc_format", "hex")
        encryption_enabled = bool(config.get("encryption_enabled", False))

    account_number = config.get("account_number", "")
    encryption_key = os.environ.get("SIA_ENCRYPTION_KEY", "")

    if not host or host == "TBD" or not port or not account_number:
        print(json.dumps({
            "status": "error",
            "detail": "Configuration incomplète (IP, port ou numéro de compte manquant)",
        }), flush=True)
        return

    builder = SIAMessageBuilder(crc_format=crc_format)
    frame = builder.make_supervision_message(
        account_number=account_number,
        encryption=encryption_enabled and bool(encryption_key),
    )

    start_time = time.monotonic()
    result = await _send_raw_once(
        host=host,
        port=port,
        transport=transport,
        frame=frame,
        timeout=timeout,
    )
    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    status = result["status"]
    if status == "ack":
        out = {"status": "ok", "detail": f"ACK reçu en {elapsed_ms}ms"}
    elif status == "nak":
        out = {"status": "nak", "detail": "Réponse inattendue (NAK)"}
    else:
        out = {"status": "fail", "detail": f"Pas de réponse (timeout {timeout}s)"}

    print(json.dumps(out), flush=True)


# ===== --test-only ENTRY POINT =====
# Must come BEFORE the normal daemon start to short-circuit when called by PHP
# for connection testing. Never initializes Jeedom socket or supervision loop.

if "--test-only" in sys.argv:
    import argparse

    _ap = argparse.ArgumentParser()
    _ap.add_argument("--test-only", action="store_true")
    _ap.add_argument("--timeout", type=int, default=15)
    _ap.add_argument("--config", type=str, default="{}")
    _args = _ap.parse_args()

    try:
        _config = json.loads(_args.config)
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"status": "error", "detail": f"Erreur de configuration: {str(e)}"}), flush=True)
        sys.exit(1)

    asyncio.run(run_connection_test(
        config=_config,
        timeout=_args.timeout,
    ))
    sys.exit(0)


# ===== NORMAL DAEMON ENTRY POINT =====
# Production entry point: PHP builds CSRPreset from CLI args passed to this
# script. Full implementation wired in Epic 6 (PHP core) — daemon.py comment
# at line 2018+ documents the expected flow.

if __name__ == "__main__":
    from siadc09d.daemon import SIADaemon
    from siadc09d.presets import CSRPreset
    from jeedomdaemon.base_config import BaseConfig

    _config = BaseConfig()
    _config.add_argument("--host", type=str, required=True)
    _config.add_argument("--port", type=int, required=True)
    _config.add_argument("--transport", type=str, default="UDP")
    _config.add_argument("--account", type=str, required=True)
    _config.add_argument("--crc-format", type=str, default="hex")
    _config.add_argument("--encryption-enabled", action="store_true")
    _config.add_argument("--encryption-key", type=str, default="")
    _config.add_argument("--supervision-interval", type=int, default=60)
    _config.add_argument("--retry-count", type=int, default=3)
    _config.add_argument("--receiver-prefix", type=str, default="")
    _config.add_argument("--account-prefix", type=str, default="")
    _config.add_argument("--notify-cmd-id", type=int, default=0)

    _preset = CSRPreset(
        csr_provider="cli",
        schema_version=1,
        host=_config.host,
        port=_config.port,
        account_number=_config.account,
        transport=_config.transport,
        crc_format=getattr(_config, "crc_format", "hex"),
        encryption_enabled=_config.encryption_enabled,
        connect_timeout_s=5.0,
        receive_timeout_s=10.0,
        supervision_interval_s=float(_config.supervision_interval),
    )

    SIADaemon(preset=_preset, config=_config).run()
