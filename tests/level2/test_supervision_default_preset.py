"""Story 17.1 AC9: a default CSRPreset keeps today's supervision frame and cadence.

The periodic-frame fields (supervision_format, rp_enabled, rp_interval_s) are
stored by the daemon but not acted on until Stories 17.2/17.3. A daemon built
from a preset that leaves them at their defaults must run one supervision loop
at supervision_interval_s and send the unchanged "SIA-DCS"…[#acct|0000] frame.

Test level: Level 2 (async, mocked transport, no Jeedom required)
Reference: SIA DC-09-2021 § 5.5.2 Supervision Message; D-86 (SIA-DCS keep-alive)
"""
import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import SIADaemon
from tests.conftest import make_daemon_preset

_ACCOUNT = "001234"
_LOOP_CYCLES = 2
# Differs from the rp_interval_s default (60 s) so a loop driven by RP would be caught.
_SUPERVISION_INTERVAL_S = 45.0


def _make_default_daemon(supervision_interval_s: float | None = None) -> SIADaemon:
    """SIADaemon whose preset leaves the 17.1 fields at their defaults.

    Args:
        supervision_interval_s: Override of the preset supervision interval; None keeps it.

    Returns:
        A daemon with mocked transport and Jeedom callbacks.
    """
    preset = make_daemon_preset()
    if supervision_interval_s is not None:
        preset = dataclasses.replace(preset, supervision_interval_s=supervision_interval_s)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = _ACCOUNT
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()
    transport = MagicMock()
    transport.start = AsyncMock()
    transport.close = AsyncMock()
    transport.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = transport
    return daemon


def test_default_preset_periodic_fields() -> None:
    """
    The preset used by the daemon tests carries the 17.1 defaults.

    Expected result:
    - supervision_format "sia-dcs", rp_enabled False, rp_interval_s 60.0
    """
    preset = make_daemon_preset()
    # Assert: defaults equal today's behaviour
    assert (preset.supervision_format, preset.rp_enabled, preset.rp_interval_s) == ("sia-dcs", False, 60.0)


@pytest.mark.asyncio
async def test_default_preset_supervision_cadence_unchanged() -> None:
    """
    _supervision_loop() sleeps exactly supervision_interval_s between enqueues.

    Scenario: asyncio.sleep is replaced by a recorder (no wall-clock wait); the
    loop is cancelled after two enqueues.

    Expected result:
    - every sleep is supervision_interval_s (45 s, distinct from the 60 s rp_interval_s default)
    - one SUPERVISION enqueue per sleep
    """
    daemon = _make_default_daemon(supervision_interval_s=_SUPERVISION_INTERVAL_S)
    # Assert: 17.1 fields still at their defaults, RP interval distinct from supervision
    assert daemon._preset.rp_interval_s != _SUPERVISION_INTERVAL_S
    sleeps: list[float] = []
    enqueues: list[int] = []
    done = asyncio.Event()

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def spy_enqueue() -> None:
        enqueues.append(1)
        if len(enqueues) >= _LOOP_CYCLES:
            done.set()
            raise asyncio.CancelledError

    daemon._enqueue_supervision = spy_enqueue
    with patch("resources.siadc09d.daemon.asyncio.sleep", record_sleep):
        with pytest.raises(asyncio.CancelledError):
            await daemon._supervision_loop()

    # Assert: loop stopped after the expected number of cycles
    assert done.is_set()
    # Assert: cadence is the supervision interval, unchanged
    assert sleeps == [_SUPERVISION_INTERVAL_S] * _LOOP_CYCLES
    # Assert: one enqueue per interval
    assert len(enqueues) == _LOOP_CYCLES


@pytest.mark.asyncio
async def test_default_preset_supervision_frame_unchanged() -> None:
    """
    _send_supervision() sends the unchanged SIA-DCS keep-alive frame (D-86).

    Expected result:
    - exactly one frame sent on ACK
    - frame carries "SIA-DCS" and the [#<acct>|0000] data block, not *NULL / RP
    """
    daemon = _make_default_daemon()

    await daemon._send_supervision()

    send_frame = daemon._sia_transport.send_frame
    # Assert: one frame sent (ACK on first attempt)
    assert send_frame.await_count == 1
    frame: bytes = send_frame.await_args.args[0]
    # Assert: SIA-DCS keep-alive token
    assert b'"SIA-DCS"' in frame
    # Assert: unchanged data block
    assert f"[#{_ACCOUNT}|0000]".encode() in frame
