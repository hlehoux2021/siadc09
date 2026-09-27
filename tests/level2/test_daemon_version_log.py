"""
Startup version log for Story 11.4 (Task 3.4).

architecture.md § Versioning Strategy → Observability: on_start() emits the
daemon version at INFO, so a support log always says which release produced it.
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d import DAEMON_VERSION
from resources.siadc09d.daemon import SIADaemon
from tests.conftest import make_daemon_preset


@pytest.mark.asyncio
async def test_on_start_logs_daemon_version(caplog: pytest.LogCaptureFixture) -> None:
    """
    on_start() logs the daemon version at INFO level.

    Expected result:
    - An INFO record contains DAEMON_VERSION after on_start()
    """
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=make_daemon_preset())
    daemon.send_to_jeedom = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    with patch("resources.siadc09d.daemon.SIAUDPTransport") as mock_transport_cls:
        mock_transport = MagicMock()
        mock_transport.start = AsyncMock()
        mock_transport.close = AsyncMock()
        mock_transport_cls.return_value = mock_transport
        with caplog.at_level(logging.INFO):
            await daemon.on_start()
    try:
        info_records = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        # Assert: the version appears in an INFO line
        assert any(DAEMON_VERSION in m for m in info_records), info_records
    finally:
        for task in list(daemon._tasks):
            task.cancel()
        await asyncio.gather(*daemon._tasks, return_exceptions=True)
