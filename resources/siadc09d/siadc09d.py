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
import errno
import json
import logging
import os
import socket
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

# Diagnostic outcomes of _send_raw_once(), alongside the transport's own
# 'ack' / 'nak' / 'timeout' / 'tcp_drop'. Each names one distinct cause so the
# wizard can tell "nothing listening on that port" from "no answer at all" —
# every one of them used to be reported as a bare timeout.
_FAIL_TIMEOUT = "timeout"
_FAIL_REFUSED = "refused"
_FAIL_DNS = "dns"
_FAIL_UNREACHABLE = "unreachable"
_FAIL_CONNECT_TIMEOUT = "connect_timeout"
_FAIL_NETWORK = "network"
_FAIL_BAD_REPLY = "bad_reply"
_FAIL_INTERNAL = "internal"
_STATUS_TCP_DROP = "tcp_drop"

# SIATransportError carries no error code — the connect-timeout path
# (sia_transport.py § SIATCPTransport.send_frame) raises it without a __cause__,
# so its message is the only discriminator available.
_TRANSPORT_MSG_CONNECT_TIMEOUT = "connect timeout"
_TRANSPORT_MSG_TIMEOUT = "timeout"

# The wizard UI understands exactly four verdicts (desktop/js/siaDC09.js:
# 'ok' → green, 'nak' → orange with Next enabled, anything else → red with Next
# disabled). Adding a status would break it, so the diagnosis goes in `detail`.
_UI_OK = "ok"
_UI_NAK = "nak"
_UI_FAIL = "fail"
_UI_ERROR = "error"

# _send_raw_once() status → (UI verdict, French detail template). Templates may
# only use the placeholders built in run_connection_test()'s `context`.
_TEST_VERDICTS: dict[str, tuple[str, str]] = {
    "ack": (_UI_OK, "ACK reçu en {elapsed_ms}ms"),
    "nak": (
        _UI_NAK,
        "NAK reçu en {elapsed_ms}ms — {endpoint} répond mais refuse la trame "
        "(numéro de compte {account_number} inconnu du récepteur ?)",
    ),
    _FAIL_REFUSED: (
        _UI_FAIL,
        "Connexion refusée par {endpoint} — le port est fermé ou aucun service "
        "n'écoute en {transport}",
    ),
    _FAIL_DNS: (
        _UI_ERROR,
        "Nom d'hôte introuvable : {host} — résolution DNS échouée depuis la "
        "machine Jeedom",
    ),
    _FAIL_UNREACHABLE: (
        _UI_FAIL,
        "Hôte injoignable : {host} — routage ou pare-feu (aucune route depuis "
        "la machine Jeedom)",
    ),
    _FAIL_CONNECT_TIMEOUT: (
        _UI_FAIL,
        "Connexion à {endpoint} impossible après {connect_timeout}s — paquets "
        "filtrés par un pare-feu ou hôte éteint",
    ),
    _FAIL_BAD_REPLY: (
        _UI_FAIL,
        "{endpoint} a répondu en {elapsed_ms}ms mais la réponse est illisible — "
        "vérifier le format CRC (configuré : {crc_format}) et le chiffrement",
    ),
    _STATUS_TCP_DROP: (
        _UI_FAIL,
        "Connexion TCP fermée par {endpoint} avant la réponse",
    ),
    _FAIL_NETWORK: (
        _UI_FAIL,
        "Erreur réseau vers {endpoint} — voir le log siaDC09 pour le détail",
    ),
    _FAIL_INTERNAL: (
        _UI_ERROR,
        "Erreur interne du test de connexion — voir le log siaDC09",
    ),
}

_TEST_VERDICT_TIMEOUT: tuple[str, str] = (
    _UI_FAIL,
    "Pas de réponse de {endpoint} (timeout {timeout}s) — la connexion est "
    "établie mais le récepteur n'a rien renvoyé",
)


def _classify_os_error(exc: OSError) -> str:
    """Map a socket-level error to the diagnostic status naming its cause.

    Args:
        exc: OSError raised by the transport, or wrapped as its __cause__.

    Returns:
        One of the _FAIL_* constants.
    """
    if isinstance(exc, socket.gaierror):
        return _FAIL_DNS
    if isinstance(exc, ConnectionRefusedError) or exc.errno == errno.ECONNREFUSED:
        return _FAIL_REFUSED
    if exc.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ENETDOWN):
        return _FAIL_UNREACHABLE
    return _FAIL_NETWORK


def _classify_transport_error(exc: SIATransportError) -> str:
    """Map a SIATransportError to the diagnostic status naming its cause.

    The transport wraps socket errors with `raise ... from e`, so the original
    OSError — and with it the errno — survives as __cause__.

    Args:
        exc: The SIATransportError raised by start() or send_frame().

    Returns:
        One of the _FAIL_* constants.
    """
    cause = exc.__cause__
    if isinstance(cause, OSError):
        return _classify_os_error(cause)
    message = str(exc).lower()
    if _TRANSPORT_MSG_CONNECT_TIMEOUT in message:
        return _FAIL_CONNECT_TIMEOUT
    if _TRANSPORT_MSG_TIMEOUT in message:
        return _FAIL_TIMEOUT
    return _FAIL_NETWORK


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
        Dict with a 'status' key — 'ack', 'nak', 'tcp_drop' or one of the
        _FAIL_* diagnostic statuses — plus an 'error' key carrying the technical
        cause (exception repr) when the send failed. Callers must map 'status' to
        a UI verdict via _TEST_VERDICTS; 'error' is for the log, not the UI.
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
        status = result["status"]
        # The transport also reports an unparseable reply as 'timeout'
        # (sia_transport.py § _parse_response). A reply that arrived but failed
        # CRC/format validation is a protocol mismatch, not silence — telling the
        # two apart is the whole point of this test.
        if status == _FAIL_TIMEOUT and result.get("raw_response"):
            raw = result["raw_response"] or b""
            return {
                "status": _FAIL_BAD_REPLY,
                "error": f"réponse non décodable ({len(raw)} octets) : {raw!r}",
            }
        return {"status": status}
    except (asyncio.TimeoutError, TimeoutError):
        return {"status": _FAIL_TIMEOUT}
    # SIATransportError inherits from OSError — it must be caught first.
    except SIATransportError as e:
        return {"status": _classify_transport_error(e), "error": repr(e)}
    except OSError as e:
        return {"status": _classify_os_error(e), "error": repr(e)}
    except (ValueError, KeyError, AssertionError, RuntimeError) as e:
        return {"status": _FAIL_INTERNAL, "error": repr(e)}
    finally:
        await t.close()


def _test_verdict(status: str, context: dict[str, object]) -> dict[str, str]:
    """Map an internal test status to the JSON verdict consumed by the UI.

    Args:
        status: Internal status returned by _send_raw_once().
        context: Substitution values for the French detail template.

    Returns:
        Dict with a `status` in {ok, nak, fail, error} — the only values
        desktop/js/siaDC09.js knows how to render — and a `detail` string.
    """
    ui_status, template = _TEST_VERDICTS.get(status, _TEST_VERDICT_TIMEOUT)
    return {"status": ui_status, "detail": template.format(**context)}


async def run_connection_test(config: dict, timeout: int) -> None:
    """Run a standalone connection test and print JSON result to stdout.

    Reads CSR parameters from config dict (or preset JSON if not manual mode).
    Builds a NULL frame, sends it via _send_raw_once(), prints result.

    Args:
        config: Configuration dict from PHP (eqLogic configuration minus encryption_key).
        timeout: Overall test timeout in seconds.
    """
    host = config.get("csr_ip", "")
    try:
        port = int(config.get("csr_port", 0))
    except (ValueError, TypeError):
        port = 0
    transport = config.get("transport", "udp")
    crc_format = config.get("crc_format", "hex")
    encryption_enabled = bool(int(config.get("encryption_enabled", 0)))
    account_number = config.get("account_number", "")
    encryption_key = os.environ.get("SIA_ENCRYPTION_KEY", "")

    if not host or host == "TBD" or not port or not account_number:
        print(json.dumps({
            "status": _UI_ERROR,
            "detail": "Configuration incomplète (IP, port ou numéro de compte manquant)",
        }), flush=True)
        return

    frame = SIAMessageBuilder(
        crc_format="SIA" if crc_format == "hex" else "ADM",
    ).make_supervision_message(
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

    # The technical cause goes to stderr, never to stdout: PHP parses stdout as
    # JSON and logs stderr verbatim (core/ajax/siaDC09.ajax.php § testConnection).
    if result.get("error"):
        print(
            f"test connexion {status} vers {host}:{port} ({transport}) : "
            f"{result['error']}",
            file=sys.stderr, flush=True,
        )

    print(json.dumps(_test_verdict(status, {
        "elapsed_ms": elapsed_ms,
        "endpoint": f"{host}:{port}",
        "host": host,
        "transport": transport.upper(),
        "account_number": account_number,
        "crc_format": crc_format,
        "timeout": timeout,
        "connect_timeout": int(_TEST_CONNECT_TIMEOUT_S),
    })), flush=True)


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
        print(json.dumps({
            "status": _UI_ERROR,
            "detail": f"Erreur de configuration: {e}",
        }), flush=True)
        sys.exit(1)

    try:
        asyncio.run(run_connection_test(
            config=_config,
            timeout=_args.timeout,
        ))
    except Exception:  # pylint: disable=broad-except
        # Process boundary: PHP parses stdout as JSON, so an unexpected crash must
        # still produce a verdict. The traceback goes to stderr, which PHP logs.
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "status": _UI_ERROR,
            "detail": "Erreur interne du test de connexion — voir le log siaDC09",
        }), flush=True)
        sys.exit(1)
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
    _config.add_argument("--retry-count", type=int, default=6)
    _config.add_argument("--reconnect-delay", type=float, default=30.0)
    _config.add_argument("--receiver-prefix", type=str, default="")
    _config.add_argument("--account-prefix", type=str, default="")
    _config.add_argument("--notify-cmd-id", type=int, default=0)
    # Fix #2: parse() must be called before accessing attributes (_args is None otherwise)
    _config.parse()

    _preset = CSRPreset(
        csr_provider="cli",
        schema_version=1,
        host=_config.host,
        port=_config.port,
        account_number=_config.account,
        # Fix #3: PHP passes lowercase 'udp'/'tcp', TransportType enum expects uppercase
        transport=_config.transport.upper(),
        crc_format=_config.crc_format,
        encryption_enabled=_config.encryption_enabled,
        connect_timeout_s=5.0,
        receive_timeout_s=10.0,
        supervision_interval_s=float(_config.supervision_interval),
        reconnect_delay_s=_config.reconnect_delay,
        reconnect_max_attempts=_config.retry_count,
    )

    SIADaemon(preset=_preset, config=_config).run()
