"""Story 7.1: Supervision Loop Integration Tests (AC11).

Level 2 tests using mocked transport — call handler methods directly.
Level 3 csr_simulator tests are deferred to Story 7.3.

Reference: _bmad-output/implementation-artifacts/7-1-supervision-loop-strike-management-info-updates.md
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resources.siadc09d.daemon import (
    QUEUE_PRIORITY_EVENT,
    QUEUE_PRIORITY_SUPERVISION,
    QUEUE_TYPE_EVENT,
    QUEUE_TYPE_SUPERVISION,
    SIADaemon,
    SM1State,
    SM2State,
    STRIKE_CAP,
)
from resources.siadc09d.error_handler import ErrorCode
from resources.siadc09d.messages import (
    SM1_DEGRADED_1_2_FR,
    SM1_DEGRADED_3_FR,
    SM1_HEALTHY_FR,
    SM1_INITIALIZING_FR,
    SM1_NO_NETWORK_FR,
    SM1_TCP_RECONNECTING_FR,
)
from resources.siadc09d.sia_protocol import SIATransportError
from resources.siadc09d.sia_transport import TransportType
from tests.conftest import make_daemon_preset


# ===== FIXTURES =====


def _make_daemon(transport: str = "UDP") -> SIADaemon:
    """Create SIADaemon with mocked transport and callbacks for supervision tests.

    Expected result:
    - Daemon has all instance vars initialized (no tasks running)
    - _notify, _log_sm1_supervision, _update_info_commands mocked
    - send_to_jeedom mocked for on_start()/on_stop() push
    """
    preset = make_daemon_preset(transport=transport)
    with patch("sys.argv", ["test"]):
        daemon = SIADaemon(preset=preset)
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm1_supervision = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = "001234"
    daemon._receiver_prefix = ""
    daemon._account_prefix = "L0"
    daemon.send_to_jeedom = AsyncMock()

    mock_t = MagicMock()
    mock_t.start = AsyncMock()
    mock_t.close = AsyncMock()
    mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
    daemon._sia_transport = mock_t
    return daemon


# ===== TC7.2: Healthy ACK → HEALTHY, supervision_state=2 =====


@pytest.mark.asyncio
async def test_healthy_ack_resets_strike_and_sets_healthy():
    """ACK response sets SM1=HEALTHY, strike=0, and triggers info_update with state=2.

    Expected result:
    - _strike_counter == 0
    - SM1 == HEALTHY
    - _update_info_commands called (by _log_sm1_supervision path)
    - No T1/T3 notification fired
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.INITIALIZING
    daemon._strike_counter = 0

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: strike is 0 (healthy)
    assert daemon._strike_counter == 0
    # Assert: SM1 state is HEALTHY
    assert daemon._sm1_state == SM1State.HEALTHY
    # Assert: no T1/T3 notification fired
    daemon._notify.assert_not_called()


# ===== TC7.3: Timeout once → strike=1, DEGRADED, T1 fired =====


@pytest.mark.asyncio
async def test_timeout_strike_1_fires_t1():
    """First timeout increments strike to 1, fires SUPERVISION_TIMEOUT T1.

    Expected result:
    - _strike_counter == 1
    - SM1 == DEGRADED
    - _notify called exactly once with SUPERVISION_TIMEOUT
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: strike incremented to 1
    assert daemon._strike_counter == 1
    # Assert: SM1 is DEGRADED
    assert daemon._sm1_state == SM1State.DEGRADED
    # Assert: T1 notification fired exactly once
    daemon._notify.assert_called_once()
    assert daemon._notify.call_args[0][0] == ErrorCode.SUPERVISION_TIMEOUT


# ===== TC7.4: Timeout twice → strike=2, no second T1 =====


@pytest.mark.asyncio
async def test_timeout_strike_2_no_second_t1():
    """Second timeout increments to strike=2, no additional T1 notification.

    Expected result:
    - _strike_counter == 2
    - SM1 == DEGRADED
    - Only one total T1 notification (from strike=1)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)
    daemon._notify.reset_mock()

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: strike incremented to 2
    assert daemon._strike_counter == 2
    # Assert: SM1 is still DEGRADED
    assert daemon._sm1_state == SM1State.DEGRADED
    # Assert: no second T1 at strike=2
    daemon._notify.assert_not_called()


# ===== TC7.5: Timeout thrice → strike=3, T3 fired once =====


@pytest.mark.asyncio
async def test_timeout_strike_3_fires_t3():
    """Third timeout hits strike=3, fires T3 (SUPERVISION_DISCONNECTED) exactly once.

    Expected result:
    - _strike_counter == 3
    - _sm1_t3_fired == True
    - _notify called with SUPERVISION_DISCONNECTED
    - supervision_value() returns 0
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)
    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)
    daemon._notify.reset_mock()

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: strike capped at 3
    assert daemon._strike_counter == 3
    # Assert: T3 flag set
    assert daemon._sm1_t3_fired is True
    # Assert: T3 notification fired
    daemon._notify.assert_called_once()
    assert daemon._notify.call_args[0][0] == ErrorCode.SUPERVISION_DISCONNECTED
    # Assert: supervision_value is 0 (critical)
    assert daemon._supervision_value() == 0


# ===== TC7.6: ACK after strike=3 → reset to healthy =====


@pytest.mark.asyncio
async def test_ack_after_strike_3_resets_to_healthy():
    """ACK after strike=3 resets strike to 0 and _sm1_t3_fired to False.

    Expected result:
    - _strike_counter == 0
    - _sm1_t3_fired == False
    - SM1 == HEALTHY
    - supervision_value() returns 2
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 3
    daemon._sm1_t3_fired = True

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: strike reset to 0
    assert daemon._strike_counter == 0
    # Assert: T3 flag cleared
    assert daemon._sm1_t3_fired is False
    # Assert: SM1 is HEALTHY
    assert daemon._sm1_state == SM1State.HEALTHY
    # Assert: supervision_value back to 2
    assert daemon._supervision_value() == 2


# ===== TC7.7: T3 fires again after reset cycle =====


@pytest.mark.asyncio
async def test_t3_fires_again_after_reset_cycle():
    """After strike=3→ACK→strike=3 again, T3 fires a second time.

    Expected result:
    - First escalation: T3 fires
    - ACK resets: _sm1_t3_fired = False
    - Second escalation: T3 fires again (not suppressed)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # First escalation to strike=3
    for _ in range(3):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: T3 fired
    t3_calls_1 = [c for c in daemon._notify.call_args_list
                  if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls_1) == 1

    # ACK resets everything
    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)
    assert daemon._sm1_t3_fired is False

    daemon._notify.reset_mock()

    # Second escalation to strike=3
    for _ in range(3):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: T3 fires again (not suppressed)
    t3_calls_2 = [c for c in daemon._notify.call_args_list
                  if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls_2) == 1


# ===== TC7.8: TCP drop → TCP_RECONNECTING, no strike increment =====


@pytest.mark.asyncio
async def test_tcp_drop_enters_tcp_reconnecting():
    """TCP drop transitions to TCP_RECONNECTING immediately, no strike change.

    Expected result:
    - SM1 == TCP_RECONNECTING
    - _strike_counter unchanged (no increment on TCP drop)
    - supervision_value() returns 0
    - _tcp_reconnect_loop task scheduled (in _tasks)
    """
    daemon = _make_daemon(transport="TCP")
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    await daemon._handle_supervision_tcp_drop()

    # Assert: SM1 immediately TCP_RECONNECTING
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    # Assert: strike NOT incremented
    assert daemon._strike_counter == 0
    # Assert: supervision_value is 0
    assert daemon._supervision_value() == 0
    # Assert: reconnect task was scheduled
    task_names = {t.get_name() for t in daemon._tasks}
    assert "tcp_reconnect_loop" in task_names

    # Cleanup: cancel tasks
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== TC7.9: NAK with parseable timestamp → SUPERVISION_NAK T1 =====


@pytest.mark.asyncio
async def test_nak_parseable_timestamp_fires_supervision_nak():
    """NAK with parseable timestamp fires T1 SUPERVISION_NAK (not BAD_CSR_RESPONSE).

    Expected result:
    - _strike_counter incremented
    - _notify called with SUPERVISION_NAK
    - _log_sm1_supervision called with 'nak_timestamp'
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # NAK with parseable timestamp (14 bytes: HH:MM:SS,MM-DD-YYYY format)
    nak_timestamp = b"12:34:56,01-15-2026"
    result = {"status": "nak", "raw_nak": nak_timestamp}

    with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
        mock_parse.return_value = datetime(2026, 1, 15, 12, 34, 56, tzinfo=timezone.utc)
        await daemon._handle_supervision_nak(result, elapsed_ms=100.0)

    # Assert: strike incremented
    assert daemon._strike_counter == 1
    # Assert: SUPERVISION_NAK notification fired (T1, parseable)
    nak_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.SUPERVISION_NAK]
    assert len(nak_calls) == 1
    # Assert: no BAD_CSR_RESPONSE fired
    bad_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.BAD_CSR_RESPONSE]
    assert len(bad_calls) == 0
    # Assert: logged as nak_timestamp
    daemon._log_sm1_supervision.assert_awaited_once()
    assert daemon._log_sm1_supervision.call_args[0][0] == "nak_timestamp"


# ===== TC7.10: NAK with unparseable data → BAD_CSR_RESPONSE T2 =====


@pytest.mark.asyncio
async def test_nak_unparseable_fires_bad_csr_response():
    """NAK with unparseable/empty data fires T2 BAD_CSR_RESPONSE (not SUPERVISION_NAK).

    Expected result:
    - _strike_counter incremented
    - _notify called with BAD_CSR_RESPONSE
    - No SUPERVISION_NAK notification
    - _log_sm1_supervision called with 'nak_bad'
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # NAK with unparseable data
    result = {"status": "nak", "raw_nak": b"\xff\xfe"}

    with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
        mock_parse.side_effect = ValueError("unparseable")
        await daemon._handle_supervision_nak(result, elapsed_ms=100.0)

    # Assert: strike incremented
    assert daemon._strike_counter == 1
    # Assert: BAD_CSR_RESPONSE notification fired (T2)
    bad_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.BAD_CSR_RESPONSE]
    assert len(bad_calls) == 1
    # Assert: no SUPERVISION_NAK fired
    nak_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.SUPERVISION_NAK]
    assert len(nak_calls) == 0
    # Assert: logged as nak_bad
    daemon._log_sm1_supervision.assert_awaited_once()
    assert daemon._log_sm1_supervision.call_args[0][0] == "nak_bad"


# ===== TC7.11: on_start() INITIALIZING push is first send_to_jeedom call =====


@pytest.mark.asyncio
async def test_on_start_initializing_push_is_first_call():
    """on_start() sends INITIALIZING push as first send_to_jeedom call.

    Expected result:
    - First send_to_jeedom call has supervision_state==1, supervision_label=="Connexion en cours d'initialisation"
    - No event_state or event_label keys in payload
    """
    daemon = _make_daemon()

    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        MockT.return_value = mock_t
        await daemon.on_start()

    # Assert: send_to_jeedom was called
    assert daemon.send_to_jeedom.call_count >= 1
    # Assert: first call is the INITIALIZING push
    first_call_payload = daemon.send_to_jeedom.call_args_list[0][0][0]
    assert first_call_payload["supervision_state"] == 1
    assert first_call_payload["supervision_label"] == "Connexion en cours d'initialisation"
    # Assert: event_state/event_label NOT included
    assert "event_state" not in first_call_payload
    assert "event_label" not in first_call_payload

    # Cleanup
    await daemon.on_stop()


# ===== TC7.12: on_stop() STOPPED push emitted =====


@pytest.mark.asyncio
async def test_on_stop_stopped_push_emitted():
    """on_stop() emits STOPPED push with state=0, label="ARRÊTÉ", no event keys.

    Expected result:
    - _send_callback called with supervision_state==0, supervision_label=="ARRÊTÉ"
    - No event_state/event_label in payload
    """
    daemon = _make_daemon()
    daemon._send_callback = AsyncMock()

    await daemon.on_stop()

    # Assert: _send_callback was called at least once
    assert daemon._send_callback.call_count >= 1
    # Assert: first call is the STOPPED push
    first_payload = daemon._send_callback.call_args_list[0][0][0]
    assert first_payload["type"] == "info_update"
    assert first_payload["supervision_state"] == 0
    assert first_payload["supervision_label"] == "ARRÊTÉ"
    # Assert: event_state/event_label NOT included
    assert "event_state" not in first_payload
    assert "event_label" not in first_payload


# =============================================================================
# EXTENDED TESTS (Adversarial Review Gap Coverage)
# =============================================================================


# ===== AR-1: _supervision_value() returns correct values per state =====


@pytest.mark.asyncio
async def test_supervision_value_healthy_returns_2():
    """HEALTHY state → supervision_value() == 2.

    Expected result:
    - _supervision_value() returns 2 when SM1 is HEALTHY
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # Assert: HEALTHY → 2
    assert daemon._supervision_value() == 2


@pytest.mark.asyncio
async def test_supervision_value_degraded_strike_1_returns_1():
    """DEGRADED with strike=1 → supervision_value() == 1 (impaired).

    Expected result:
    - _supervision_value() returns 1 for DEGRADED with strike 1-2
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 1

    # Assert: DEGRADED strike=1 → 1 (impaired)
    assert daemon._supervision_value() == 1


@pytest.mark.asyncio
async def test_supervision_value_degraded_strike_2_returns_1():
    """DEGRADED with strike=2 → supervision_value() == 1 (impaired).

    Expected result:
    - _supervision_value() returns 1 for strike=2
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    # Assert: DEGRADED strike=2 → 1 (impaired)
    assert daemon._supervision_value() == 1


@pytest.mark.asyncio
async def test_supervision_value_degraded_strike_3_returns_0():
    """DEGRADED with strike=3 → supervision_value() == 0 (critical).

    Expected result:
    - _supervision_value() returns 0 for strike=3
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 3

    # Assert: DEGRADED strike=3 → 0 (critical)
    assert daemon._supervision_value() == 0


@pytest.mark.asyncio
async def test_supervision_value_initializing_returns_1():
    """INITIALIZING state → supervision_value() == 1 (impaired).

    Expected result:
    - _supervision_value() returns 1 for INITIALIZING
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.INITIALIZING
    daemon._strike_counter = 0

    # Assert: INITIALIZING → 1
    assert daemon._supervision_value() == 1


@pytest.mark.asyncio
async def test_supervision_value_tcp_reconnecting_returns_0():
    """TCP_RECONNECTING state → supervision_value() == 0 (problem).

    Expected result:
    - _supervision_value() returns 0
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 0

    # Assert: TCP_RECONNECTING → 0
    assert daemon._supervision_value() == 0


@pytest.mark.asyncio
async def test_supervision_value_no_network_returns_0():
    """NO_NETWORK state → supervision_value() == 0 (problem).

    Expected result:
    - _supervision_value() returns 0
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.NO_NETWORK
    daemon._strike_counter = 0

    # Assert: NO_NETWORK → 0
    assert daemon._supervision_value() == 0


# ===== AR-2: _supervision_label() returns correct French labels =====


@pytest.mark.asyncio
async def test_supervision_label_healthy():
    """HEALTHY → "Connexion OK" label from messages.py.

    Expected result:
    - _supervision_label() returns SM1_HEALTHY_FR
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # Assert: uses constant from messages.py
    assert daemon._supervision_label() == SM1_HEALTHY_FR
    assert daemon._supervision_label() == "Connexion OK"


@pytest.mark.asyncio
async def test_supervision_label_degraded_strike_1():
    """DEGRADED(strike=1) → "Connexion dégradée (1/3)" from messages.py format string.

    Expected result:
    - _supervision_label() returns SM1_DEGRADED_1_2_FR.format(1)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 1

    # Assert: formatted label with current strike
    assert daemon._supervision_label() == SM1_DEGRADED_1_2_FR.format(1)
    assert daemon._supervision_label() == "Connexion dégradée (1/3)"


@pytest.mark.asyncio
async def test_supervision_label_degraded_strike_2():
    """DEGRADED(strike=2) → "Connexion dégradée (2/3)" from messages.py format string.

    Expected result:
    - _supervision_label() returns SM1_DEGRADED_1_2_FR.format(2)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    # Assert: formatted label with strike=2
    assert daemon._supervision_label() == SM1_DEGRADED_1_2_FR.format(2)
    assert daemon._supervision_label() == "Connexion dégradée (2/3)"


@pytest.mark.asyncio
async def test_supervision_label_degraded_strike_3():
    """DEGRADED(strike=3) → "Connexion perdue" from messages.py constant.

    Expected result:
    - _supervision_label() returns SM1_DEGRADED_3_FR
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 3

    # Assert: critical lost label
    assert daemon._supervision_label() == SM1_DEGRADED_3_FR
    assert daemon._supervision_label() == "Connexion perdue"


@pytest.mark.asyncio
async def test_supervision_label_initializing():
    """INITIALIZING → "Connexion en cours d'initialisation" from messages.py constant.

    Expected result:
    - _supervision_label() returns SM1_INITIALIZING_FR
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.INITIALIZING
    daemon._strike_counter = 0

    # Assert: startup label
    assert daemon._supervision_label() == SM1_INITIALIZING_FR
    assert daemon._supervision_label() == "Connexion en cours d'initialisation"


@pytest.mark.asyncio
async def test_supervision_label_tcp_reconnecting():
    """TCP_RECONNECTING → "Tentative de reconnexion en cours" from messages.py constant.

    Expected result:
    - _supervision_label() returns SM1_TCP_RECONNECTING_FR
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 0

    # Assert: reconnecting label
    assert daemon._supervision_label() == SM1_TCP_RECONNECTING_FR
    assert daemon._supervision_label() == "Tentative de reconnexion en cours"


@pytest.mark.asyncio
async def test_supervision_label_no_network():
    """NO_NETWORK → "Hors Réseau" from messages.py constant.

    Expected result:
    - _supervision_label() returns SM1_NO_NETWORK_FR
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.NO_NETWORK
    daemon._strike_counter = 0

    # Assert: terminal label
    assert daemon._supervision_label() == SM1_NO_NETWORK_FR
    assert daemon._supervision_label() == "Hors Réseau"


# ===== AR-3: _send_supervision() full flow with SIATransportError =====


@pytest.mark.asyncio
async def test_send_supervision_transport_error_treated_as_timeout():
    """SIATransportError from _send_raw → treated as timeout (strike incremented).

    Expected result:
    - Strike incremented to 1 (timeout path)
    - _update_info_commands called (end of _send_supervision)
    - T1 SUPERVISION_TIMEOUT notification fired
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(return_value=b"\x00\x01")
    daemon._send_raw = AsyncMock(side_effect=SIATransportError("UDP socket error"))

    await daemon._send_supervision()

    # Assert: strike incremented (timeout path)
    assert daemon._strike_counter == 1
    # Assert: _update_info_commands called to push state to PHP
    daemon._update_info_commands.assert_awaited_once()
    # Assert: T1 fired for strike=1
    t1_calls = [c for c in daemon._notify.call_args_list
                if c[0][0] == ErrorCode.SUPERVISION_TIMEOUT]
    assert len(t1_calls) == 1


@pytest.mark.asyncio
async def test_send_supervision_ack_calls_update_info_commands():
    """Full _send_supervision() flow on ACK calls _update_info_commands at end.

    Expected result:
    - _update_info_commands called exactly once
    - SM1 ends in HEALTHY
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(return_value=b"\x00\x01")
    daemon._send_raw = AsyncMock(return_value={"status": "ack", "raw_nak": None})

    await daemon._send_supervision()

    # Assert: _update_info_commands called after handler
    daemon._update_info_commands.assert_awaited_once()
    # Assert: HEALTHY state
    assert daemon._sm1_state == SM1State.HEALTHY


@pytest.mark.asyncio
async def test_send_supervision_timeout_calls_update_info_commands():
    """Full _send_supervision() flow on timeout calls _update_info_commands.

    Expected result:
    - _update_info_commands called exactly once
    - Strike incremented
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(return_value=b"\x00\x01")
    daemon._send_raw = AsyncMock(return_value={"status": "timeout", "raw_nak": None})

    await daemon._send_supervision()

    # Assert: _update_info_commands called
    daemon._update_info_commands.assert_awaited_once()
    # Assert: strike incremented
    assert daemon._strike_counter == 1


# ===== AR-4: NAK at strike=3 fires T3, not T1 =====


@pytest.mark.asyncio
async def test_nak_parseable_at_strike_3_fires_t3_not_t1():
    """Parseable NAK arriving when already at strike=2 → strike=3, T3 fired, NO T1.

    Expected result:
    - _strike_counter == 3
    - T3 (SUPERVISION_DISCONNECTED) fired (via _update_sm1_from_strike)
    - NO SUPERVISION_NAK notification (code: strike_counter < 3 check fails)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    nak_timestamp = b"12:34:56,01-15-2026"
    result = {"status": "nak", "raw_nak": nak_timestamp}

    with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
        mock_parse.return_value = datetime(2026, 1, 15, 12, 34, 56, tzinfo=timezone.utc)
        await daemon._handle_supervision_nak(result, elapsed_ms=100.0)

    # Assert: strike capped at 3
    assert daemon._strike_counter == 3
    # Assert: T3 fired via _update_sm1_from_strike
    t3_calls = [c for c in daemon._notify.call_args_list
                if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls) == 1
    # Assert: NO T1 SUPERVISION_NAK fired (strike_counter >= 3 blocks it)
    nak_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.SUPERVISION_NAK]
    assert len(nak_calls) == 0


@pytest.mark.asyncio
async def test_nak_unparseable_at_strike_3_fires_t3_and_t2():
    """Unparseable NAK at strike=2→3 fires both T3 and T2 (BAD_CSR_RESPONSE).

    Expected result:
    - _strike_counter == 3
    - T3 (SUPERVISION_DISCONNECTED) fired
    - T2 (BAD_CSR_RESPONSE) fired (unparseable always fires T2 regardless of strike)
    - NO T1 fired
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    result = {"status": "nak", "raw_nak": b"\xff\xfe"}

    with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
        mock_parse.side_effect = ValueError("unparseable")
        await daemon._handle_supervision_nak(result, elapsed_ms=100.0)

    # Assert: strike capped at 3
    assert daemon._strike_counter == 3
    # Assert: T3 fired
    t3_calls = [c for c in daemon._notify.call_args_list
                if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls) == 1
    # Assert: T2 BAD_CSR_RESPONSE also fired (unparseable → always fires T2)
    bad_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.BAD_CSR_RESPONSE]
    assert len(bad_calls) == 1
    # Assert: no SUPERVISION_NAK T1
    nak_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.SUPERVISION_NAK]
    assert len(nak_calls) == 0


# ===== AR-5: Ring buffer integration (non-mocked _log_sm1_supervision) =====


@pytest.mark.asyncio
async def test_ack_pushes_routine_entry_to_ring_buffer():
    """ACK → ring buffer push with is_routine=True (may be throttled).

    Expected result:
    - Ring buffer push_supervision_entry called with is_routine=True
    - _send_callback fires message_trace callback
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    # Restore real _log_sm1_supervision (unmock it)
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon)
    daemon._send_callback = AsyncMock()

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: ring buffer received a routine entry
    assert len(daemon._ring_buffer) > 0
    # Assert: _send_callback fired message_trace
    trace_calls = [c for c in daemon._send_callback.call_args_list
                   if c[0][0].get("type") == "message_trace"]
    assert len(trace_calls) >= 1


@pytest.mark.asyncio
async def test_timeout_pushes_immediate_entry_to_ring_buffer():
    """Timeout → ring buffer push with is_routine=False (never throttled).

    Expected result:
    - Ring buffer receives entry immediately (not throttled)
    - message_trace callback fired
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    # Restore real _log_sm1_supervision
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon)
    daemon._send_callback = AsyncMock()

    await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: ring buffer received an entry
    assert len(daemon._ring_buffer) > 0
    # Assert: message_trace callback fired
    trace_calls = [c for c in daemon._send_callback.call_args_list
                   if c[0][0].get("type") == "message_trace"]
    assert len(trace_calls) >= 1


# ===== AR-6: on_start() fail-fast on send_to_jeedom failure =====


@pytest.mark.asyncio
async def test_on_start_fails_fast_when_send_to_jeedom_raises():
    """on_start() propagates exception if send_to_jeedom fails (fail-fast guarantee).

    Expected result:
    - Exception from send_to_jeedom propagates uncaught
    - on_start() does NOT complete (no tasks launched)
    """
    daemon = _make_daemon()
    daemon.send_to_jeedom = AsyncMock(side_effect=ConnectionRefusedError("PHP unreachable"))

    # Assert: exception propagates (not swallowed)
    with pytest.raises(ConnectionRefusedError):
        await daemon.on_start()

    # Assert: no tasks were launched (failed before _track_task calls)
    assert len(daemon._tasks) == 0


@pytest.mark.asyncio
async def test_on_start_fails_fast_on_oserror():
    """on_start() propagates OSError from send_to_jeedom (covers network failures).

    Expected result:
    - OSError propagates through on_start()
    """
    daemon = _make_daemon()
    daemon.send_to_jeedom = AsyncMock(side_effect=OSError("Network is down"))

    # Assert: OSError propagates
    with pytest.raises(OSError, match="Network is down"):
        await daemon.on_start()


# ===== AR-7: on_stop() swallows _send_callback exception =====


@pytest.mark.asyncio
async def test_on_stop_completes_when_send_callback_raises():
    """on_stop() swallows _send_callback exception (best-effort push).

    Expected result:
    - on_stop() completes without raising
    - Transport close still called (cleanup proceeds)
    """
    daemon = _make_daemon()
    daemon._send_callback = AsyncMock(side_effect=OSError("PHP already gone"))

    # Assert: on_stop() completes without raising despite callback failure
    await daemon.on_stop()
    # Assert: transport close still attempted (step 5 reached)
    if daemon._sia_transport is not None:
        daemon._sia_transport.close.assert_awaited()


@pytest.mark.asyncio
async def test_on_stop_swallows_connection_reset():
    """on_stop() swallows ConnectionResetError from callback (PHP shutdown race).

    Expected result:
    - on_stop() does not raise
    """
    daemon = _make_daemon()
    daemon._send_callback = AsyncMock(side_effect=ConnectionResetError("Connection reset"))

    # Assert: no exception escapes
    await daemon.on_stop()


# ===== AR-8: on_start() schedules both tasks =====


@pytest.mark.asyncio
async def test_on_start_launches_queue_consumer_and_supervision_loop():
    """on_start() schedules queue_consumer + supervision_loop in _tasks.

    Expected result:
    - Two tasks in _tasks after on_start()
    - Task names include 'queue_consumer' and 'supervision_loop'
    """
    daemon = _make_daemon()

    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        MockT.return_value = mock_t
        await daemon.on_start()

    # Assert: two tasks launched
    assert len(daemon._tasks) == 2
    # Assert: expected task names
    task_names = {t.get_name() for t in daemon._tasks}
    assert "queue_consumer" in task_names
    assert "supervision_loop" in task_names

    # Cleanup
    await daemon.on_stop()


# ===== AR-9: ACK recovery fires resolve_t1 error_update callbacks =====


@pytest.mark.asyncio
async def test_ack_after_strike_fires_resolve_t1_callbacks():
    """ACK received after prev_strike > 0 fires resolve_t1 error_update callbacks.

    Expected result:
    - Two _send_callback calls with type=error_update and resolve_t1=1
    - One for SUPERVISION_TIMEOUT code, one for SUPERVISION_NAK code
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 1
    # Restore real _log_sm1_supervision to get full behavior
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon)
    daemon._send_callback = AsyncMock()

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: resolve_t1 callbacks were sent
    resolve_calls = [
        c for c in daemon._send_callback.call_args_list
        if c[0][0].get("type") == "error_update" and c[0][0].get("resolve_t1") == 1
    ]
    assert len(resolve_calls) == 2
    # Assert: one for SUPERVISION_TIMEOUT, one for SUPERVISION_NAK
    codes = {c[0][0]["code"] for c in resolve_calls}
    assert ErrorCode.SUPERVISION_TIMEOUT.value in codes
    assert ErrorCode.SUPERVISION_NAK.value in codes


@pytest.mark.asyncio
async def test_ack_with_zero_prev_strike_no_resolve_t1():
    """ACK when prev_strike == 0 does NOT fire resolve_t1 callbacks.

    Expected result:
    - No error_update callbacks with resolve_t1
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon)
    daemon._send_callback = AsyncMock()

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: no resolve_t1 callbacks
    resolve_calls = [
        c for c in daemon._send_callback.call_args_list
        if c[0][0].get("type") == "error_update" and c[0][0].get("resolve_t1") == 1
    ]
    assert len(resolve_calls) == 0


# ===== AR-10: T3 re-escalation sets _sm1_t3_fired back to True =====


@pytest.mark.asyncio
async def test_t3_re_escalation_sets_flag_true_again():
    """After strike=3→ACK→strike=3 again, _sm1_t3_fired is True after second T3.

    Expected result:
    - After second escalation to strike=3: _sm1_t3_fired == True
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    # First escalation
    for _ in range(3):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)
    assert daemon._sm1_t3_fired is True

    # Reset via ACK
    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)
    assert daemon._sm1_t3_fired is False

    # Second escalation
    for _ in range(3):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: flag is True again after second T3
    assert daemon._sm1_t3_fired is True


# ===== AR-11: _send_supervision() returns early on frame build error =====


@pytest.mark.asyncio
async def test_send_supervision_returns_early_on_protocol_error():
    """SIAProtocolError during frame build → _send_supervision returns, no crash.

    Expected result:
    - _send_raw never called (frame build failed)
    - _update_info_commands NOT called (early return)
    - No strike change
    """
    from resources.siadc09d.sia_protocol import SIAProtocolError

    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(
        side_effect=SIAProtocolError("CRC format mismatch")
    )
    daemon._send_raw = AsyncMock()

    await daemon._send_supervision()

    # Assert: _send_raw never called
    daemon._send_raw.assert_not_awaited()
    # Assert: _update_info_commands NOT called (early return before routing)
    daemon._update_info_commands.assert_not_awaited()
    # Assert: no strike change
    assert daemon._strike_counter == 0


# ===== AR-12: Strike cap enforcement =====


@pytest.mark.asyncio
async def test_strike_capped_at_3_on_repeated_timeouts():
    """Strike never exceeds STRIKE_CAP (3) even with more than 3 timeouts.

    Expected result:
    - After 5 timeouts, _strike_counter == 3 (capped)
    - T3 fired only once (dedup flag)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    for _ in range(5):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: capped at STRIKE_CAP
    assert daemon._strike_counter == STRIKE_CAP
    assert daemon._strike_counter == 3
    # Assert: T3 fired exactly once (dedup)
    t3_calls = [c for c in daemon._notify.call_args_list
                if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls) == 1


# ===== AR-13: TCP drop from DEGRADED state preserves strike =====


@pytest.mark.asyncio
async def test_tcp_drop_from_degraded_preserves_strike_counter():
    """TCP drop while already DEGRADED (strike=2) does NOT change strike.

    Expected result:
    - SM1 → TCP_RECONNECTING
    - _strike_counter still 2 (unchanged)
    """
    daemon = _make_daemon(transport="TCP")
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2

    await daemon._handle_supervision_tcp_drop()

    # Assert: state changed to TCP_RECONNECTING
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING
    # Assert: strike not touched
    assert daemon._strike_counter == 2

    # Cleanup
    for task in list(daemon._tasks):
        task.cancel()
    await asyncio.gather(*daemon._tasks, return_exceptions=True)


# ===== AR-14: _update_info_commands builds correct full payload =====


@pytest.mark.asyncio
async def test_update_info_commands_full_payload_healthy():
    """_update_info_commands(None) builds full payload from current SM1/SM2 state.

    Expected result:
    - Payload includes supervision_state, supervision_label, event_state, event_label
    - All values match SM1=HEALTHY / SM2=IDLE
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._sm2_state = SM2State.IDLE
    daemon._send_callback = AsyncMock()
    # Restore real _update_info_commands
    daemon._update_info_commands = SIADaemon._update_info_commands.__get__(daemon)

    await daemon._update_info_commands()

    # Assert: _send_callback called with full payload
    daemon._send_callback.assert_awaited_once()
    payload = daemon._send_callback.call_args[0][0]
    assert payload["type"] == "info_update"
    # Assert: supervision values from HEALTHY state
    assert payload["supervision_state"] == 2
    assert payload["supervision_label"] == "Connexion OK"
    # Assert: event values from IDLE state
    assert payload["event_state"] == 0
    assert payload["event_label"] == "Inactif"


@pytest.mark.asyncio
async def test_update_info_commands_full_payload_degraded_strike_2():
    """_update_info_commands(None) for DEGRADED(strike=2) returns state=1, label="Connexion dégradée (2/3)".

    Expected result:
    - supervision_state == 1
    - supervision_label == "Connexion dégradée (2/3)"
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.DEGRADED
    daemon._strike_counter = 2
    daemon._sm2_state = SM2State.CONFIRMED
    daemon._event_sia_code = "BA"
    daemon._event_zone = "3"
    daemon._send_callback = AsyncMock()
    daemon._update_info_commands = SIADaemon._update_info_commands.__get__(daemon)

    await daemon._update_info_commands()

    payload = daemon._send_callback.call_args[0][0]
    # Assert: impaired state
    assert payload["supervision_state"] == 1
    # Assert: French label with strike count
    assert payload["supervision_label"] == "Connexion dégradée (2/3)"
    # Assert: SM2 CONFIRMED → event_state=1
    assert payload["event_state"] == 1
    # Assert: event label names the alarm + central confirmation
    assert payload["event_label"] == "Intrusion (zone 3) : Confirmée par la centrale"


# =============================================================================
# EDGE CASE TESTS (Edge Case Hunter Review Gap Coverage)
# =============================================================================


# ===== ECH-1: NAK with raw_nak=None (fallback to b"") =====


@pytest.mark.asyncio
async def test_nak_with_raw_nak_none_uses_empty_bytes_fallback():
    """NAK result with raw_nak=None → daemon defaults to b"" (no TypeError on .hex()).

    Expected result:
    - No TypeError or AttributeError
    - BAD_CSR_RESPONSE fired (empty bytes unparseable)
    - Strike incremented
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    result = {"status": "nak", "raw_nak": None}

    with patch("resources.siadc09d.daemon.parse_nak_timestamp") as mock_parse:
        mock_parse.side_effect = ValueError("empty data")
        await daemon._handle_supervision_nak(result, elapsed_ms=100.0)

    # Assert: no crash, strike incremented
    assert daemon._strike_counter == 1
    # Assert: BAD_CSR_RESPONSE fired (unparseable empty data)
    bad_calls = [c for c in daemon._notify.call_args_list
                 if c[0][0] == ErrorCode.BAD_CSR_RESPONSE]
    assert len(bad_calls) == 1


# ===== ECH-2: CancelledError during _send_raw is re-raised (not swallowed) =====


@pytest.mark.asyncio
async def test_send_supervision_cancelled_error_propagates():
    """CancelledError from _send_raw propagates (not treated as timeout).

    Expected result:
    - CancelledError re-raised from _send_supervision
    - Strike NOT incremented (cancellation is not a timeout)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(return_value=b"\x00\x01")
    daemon._send_raw = AsyncMock(side_effect=asyncio.CancelledError())

    # Assert: CancelledError propagates
    with pytest.raises(asyncio.CancelledError):
        await daemon._send_supervision()

    # Assert: strike NOT incremented (not a timeout)
    assert daemon._strike_counter == 0
    # Assert: _update_info_commands NOT called (cancelled before reaching it)
    daemon._update_info_commands.assert_not_awaited()


# ===== ECH-3: on_start() called twice without on_stop() (idempotent restart) =====


@pytest.mark.asyncio
async def test_on_start_twice_cancels_old_tasks():
    """Calling on_start() twice without on_stop() cancels old tasks, creates new ones.

    Expected result:
    - First on_start() creates 2 tasks
    - Second on_start() cancels those, creates 2 fresh tasks
    - No orphaned tasks
    """
    daemon = _make_daemon()

    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock()
        mock_t.close = AsyncMock()
        mock_t.send_frame = AsyncMock(return_value={"status": "ack", "raw_nak": None})
        MockT.return_value = mock_t

        await daemon.on_start()
        first_tasks = set(daemon._tasks)
        assert len(first_tasks) == 2

        await daemon.on_start()
        second_tasks = set(daemon._tasks)

    # Assert: new tasks created (not the same objects)
    assert len(second_tasks) == 2
    assert first_tasks.isdisjoint(second_tasks)
    # Assert: old tasks are cancelled
    for t in first_tasks:
        assert t.cancelled() or t.done()

    # Cleanup
    await daemon.on_stop()


# ===== ECH-4: on_stop() drains pending queue items =====


@pytest.mark.asyncio
async def test_on_stop_drains_queue():
    """on_stop() empties the priority queue (no pending items dispatched after stop).

    Expected result:
    - Queue empty after on_stop()
    - Items not dispatched (no send_raw calls)
    """
    daemon = _make_daemon()
    daemon._send_callback = AsyncMock()

    # Enqueue items manually
    await daemon._queue.put((QUEUE_PRIORITY_EVENT, 0, QUEUE_TYPE_EVENT, {"test": 1}))
    await daemon._queue.put((QUEUE_PRIORITY_SUPERVISION, 1, QUEUE_TYPE_SUPERVISION, {}))
    assert daemon._queue.qsize() == 2

    await daemon.on_stop()

    # Assert: queue drained
    assert daemon._queue.empty()


# ===== ECH-5: TCP drop on UDP daemon (transport mismatch) =====


@pytest.mark.asyncio
async def test_tcp_drop_on_udp_daemon_reconnect_loop_returns_immediately():
    """_handle_supervision_tcp_drop on UDP daemon → reconnect loop exits immediately.

    Expected result:
    - SM1 set to TCP_RECONNECTING (handler doesn't check transport)
    - _tcp_reconnect_loop task scheduled but completes immediately (UDP guard)
    - Task removed from _tasks after completion
    """
    daemon = _make_daemon(transport="UDP")
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0

    await daemon._handle_supervision_tcp_drop()

    # Assert: state set (handler unconditional)
    assert daemon._sm1_state == SM1State.TCP_RECONNECTING

    # Wait for the task to complete (it returns immediately for UDP)
    await asyncio.gather(*daemon._tasks, return_exceptions=True)

    # Assert: task completed and removed from _tasks via done callback
    assert len(daemon._tasks) == 0


# ===== ECH-6: Ring buffer throttle — second routine ACK within 10 min =====


@pytest.mark.asyncio
async def test_ring_buffer_throttles_second_routine_ack():
    """Second routine ACK within 10 minutes is throttled (ring buffer stays at 1 entry).

    Expected result:
    - First ACK → ring buffer length == 1
    - Second ACK (same minute) → ring buffer length still 1 (throttled)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._log_sm1_supervision = SIADaemon._log_sm1_supervision.__get__(daemon)
    daemon._send_callback = AsyncMock()

    result = {"status": "ack", "raw_nak": None}

    # First ACK — always logged (first-ever routine entry)
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)
    first_count = len(daemon._ring_buffer)
    assert first_count == 1

    # Second ACK — should be throttled (within 10-min window)
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)
    second_count = len(daemon._ring_buffer)

    # Assert: still 1 entry (second was throttled)
    assert second_count == 1


# ===== ECH-7: ACK while in TCP_RECONNECTING state =====


@pytest.mark.asyncio
async def test_ack_in_tcp_reconnecting_transitions_to_healthy():
    """ACK received during TCP_RECONNECTING → resets to HEALTHY and clears strike.

    Expected result:
    - SM1 → HEALTHY
    - _strike_counter → 0
    - _sm1_t3_fired → False
    """
    daemon = _make_daemon(transport="TCP")
    daemon._sm1_state = SM1State.TCP_RECONNECTING
    daemon._strike_counter = 2
    daemon._sm1_t3_fired = True

    result = {"status": "ack", "raw_nak": None}
    await daemon._handle_supervision_ack(result, elapsed_ms=50.0)

    # Assert: full reset to HEALTHY
    assert daemon._sm1_state == SM1State.HEALTHY
    assert daemon._strike_counter == 0
    assert daemon._sm1_t3_fired is False
    assert daemon._supervision_value() == 2


# ===== ECH-8: T3 fires with _last_supervision_ack=None (never received ACK) =====


@pytest.mark.asyncio
async def test_t3_context_handles_none_last_supervision_ack():
    """T3 fires when _last_supervision_ack is None (daemon just started, no ACK yet).

    Expected result:
    - T3 fires without crash
    - SM1DisconnectedCtx.time_since_last_ack_s is None (not computed)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.INITIALIZING
    daemon._strike_counter = 0
    daemon._last_supervision_ack = None

    for _ in range(3):
        await daemon._handle_supervision_timeout(elapsed_ms=30000.0)

    # Assert: T3 fired (no crash from None arithmetic)
    t3_calls = [c for c in daemon._notify.call_args_list
                if c[0][0] == ErrorCode.SUPERVISION_DISCONNECTED]
    assert len(t3_calls) == 1
    # Assert: context has time_since_last_ack_s=None
    ctx = t3_calls[0][0][1]
    assert ctx.time_since_last_ack_s is None
    assert ctx.last_ack_time_utc is None


# ===== ECH-9: _send_supervision with _sia_transport=None =====


@pytest.mark.asyncio
async def test_send_supervision_transport_none_raises_transport_error():
    """_send_supervision when _sia_transport=None → SIATransportError → timeout path.

    Expected result:
    - SIATransportError raised internally by _send_raw
    - Caught and treated as timeout (strike incremented)
    - _update_info_commands called
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    daemon._sia_transport = None
    daemon._update_info_commands = AsyncMock()
    daemon._sia_builder = MagicMock()
    daemon._sia_builder.make_supervision_message = MagicMock(return_value=b"\x00\x01")

    await daemon._send_supervision()

    # Assert: treated as timeout (strike incremented)
    assert daemon._strike_counter == 1
    # Assert: _update_info_commands called
    daemon._update_info_commands.assert_awaited_once()


# ===== ECH-10: _update_info_commands swallows _send_callback exception =====


@pytest.mark.asyncio
async def test_update_info_commands_swallows_send_callback_error():
    """_update_info_commands doesn't crash when _send_callback raises (via real impl).

    Expected result:
    - No exception escapes from _update_info_commands
    - Error logged but swallowed (by _send_callback's internal try/except)
    """
    daemon = _make_daemon()
    daemon._sm1_state = SM1State.HEALTHY
    daemon._strike_counter = 0
    # Restore real _update_info_commands
    daemon._update_info_commands = SIADaemon._update_info_commands.__get__(daemon)
    # Make send_to_jeedom raise (this is what _send_callback wraps)
    daemon.send_to_jeedom = AsyncMock(side_effect=OSError("PHP crashed"))

    # Assert: does not raise — _send_callback swallows the error
    await daemon._update_info_commands()


# ===== ECH-11: on_start() transport.start() raises OSError =====


@pytest.mark.asyncio
async def test_on_start_transport_start_failure_propagates():
    """transport.start() raising OSError propagates from on_start() (no orphan tasks).

    Expected result:
    - OSError propagates
    - No tasks launched (transport failed before _track_task)
    - _sia_transport not set
    """
    daemon = _make_daemon()

    with patch("resources.siadc09d.daemon.SIAUDPTransport") as MockT:
        mock_t = MagicMock()
        mock_t.start = AsyncMock(side_effect=OSError("Address already in use"))
        MockT.return_value = mock_t

        with pytest.raises(OSError, match="Address already in use"):
            await daemon.on_start()

    # Assert: no tasks launched (failed before _track_task calls)
    assert len(daemon._tasks) == 0


# ===== ECH-12: on_stop() with CancelledError in _send_callback re-raises =====


@pytest.mark.asyncio
async def test_on_stop_reraises_cancelled_error():
    """on_stop() re-raises CancelledError from _send_callback (never swallowed).

    Expected result:
    - CancelledError propagates from on_stop()
    - This is correct: cancellation must not be silently consumed
    """
    daemon = _make_daemon()
    daemon._send_callback = AsyncMock(side_effect=asyncio.CancelledError())

    # Assert: CancelledError re-raised (explicit in on_stop() except block)
    with pytest.raises(asyncio.CancelledError):
        await daemon.on_stop()
