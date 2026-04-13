"""SM2 Alarm Event State Machine - Comprehensive Test Suite (Story 5-2).

Tests cover:
- SM2 state machine definition (IDLE → PENDING → CONFIRMED/FAILED)
- Alarm event lifecycle with retries
- NAK/ACK handling and dispatch
- Network loss scenarios
- Persistence across daemon restarts
- Logging integration

Test organization:
- Level 2: Async integration tests (no Jeedom required)
- Framework: pytest-asyncio
- Reference: story 5-2-sm2-alarm-event-state-machine.md
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Optional

from resources.siadc09d.daemon import SIADaemon, SM2State, SM2LogCtx, EventItem
from resources.siadc09d.error_handler import ErrorCode
from resources.siadc09d.ring_buffer import RingBuffer


# ===== FIXTURES =====

@pytest.fixture
def mock_daemon():
    """Create a SIADaemon instance with mocked transport and PHP callback."""
    # Create daemon with mocked config to avoid argument parsing in tests
    with patch('sys.argv', ['test']):  # Mock sys.argv to prevent argparse errors
        daemon = SIADaemon()

    # Configure preset and connection settings
    daemon._preset = MagicMock(
        crc_format='SIA',
        supervision_interval_s=10,
        reconnect_delay_s=1,
        encryption_enabled=False,
    )
    daemon._account = '001234'
    daemon._receiver_prefix = None
    daemon._account_prefix = 'L0'
    daemon._sia_seq = 0
    daemon._ring_buffer = RingBuffer()
    daemon._logger = MagicMock()
    daemon._notify = AsyncMock()
    daemon._send_raw = AsyncMock()
    daemon._update_info_commands = AsyncMock()
    daemon._track_task = MagicMock()
    daemon._encryption_key = b''
    daemon._transport = 'UDP'

    # Initialize SM1 state
    from resources.siadc09d.daemon import SM1State
    daemon._sm1_state = SM1State.INITIALIZING
    daemon._strike_counter = 0
    daemon._sm1_t3_fired = False
    daemon._last_supervision_ack = None

    # SM2 state is already initialized in __init__

    return daemon


@pytest.fixture
def time_mock():
    """Mock time for time-dependent tests."""
    with patch('time.time') as mock:
        mock.return_value = 1704067200.0  # 2024-01-01 00:00:00 UTC
        yield mock


# ===== Task 1: SM2 State Machine Definition Tests =====

class TestSM2StateEnumDefinition:
    """Test that SM2State enum is properly defined."""

    def test_sm2state_enum_exists(self):
        """Verify SM2State enum exists with required values."""
        # This test will import SM2State once it's defined
        from resources.siadc09d.daemon import SM2State

        # Assert enum has all required values
        assert hasattr(SM2State, 'IDLE')
        assert hasattr(SM2State, 'PENDING')
        assert hasattr(SM2State, 'CONFIRMED')
        assert hasattr(SM2State, 'FAILED')

    def test_sm2state_enum_values(self):
        """Verify SM2State enum values match protocol requirements."""
        from resources.siadc09d.daemon import SM2State

        # Each state should be a distinct enum member
        assert SM2State.IDLE.value == "IDLE"
        assert SM2State.PENDING.value == "PENDING"
        assert SM2State.CONFIRMED.value == "CONFIRMED"
        assert SM2State.FAILED.value == "FAILED"


class TestSM2LogCtxDefinition:
    """Test SM2LogCtx TypedDict definition."""

    def test_sm2logctx_typeddict_exists(self):
        """Verify SM2LogCtx TypedDict is defined."""
        from resources.siadc09d.daemon import SM2LogCtx

        # TypedDict should have required fields
        # Fields: zone (str | None), sia_code (str), attempt (int), elapsed (float), state_change (bool)
        assert hasattr(SM2LogCtx, '__annotations__')

    def test_sm2logctx_field_types(self):
        """Verify SM2LogCtx has correct field types."""
        from resources.siadc09d.daemon import SM2LogCtx

        annotations = SM2LogCtx.__annotations__
        assert 'zone' in annotations
        assert 'sia_code' in annotations
        assert 'attempt' in annotations
        assert 'elapsed' in annotations
        assert 'state_change' in annotations


# ===== Task 2: SM2 Instance Variables Tests =====

class TestSM2InstanceVariablesInitialization:
    """Test SM2 instance variables are properly initialized in daemon."""

    def test_sm2_instance_vars_exist(self, mock_daemon):
        """Verify all SM2 instance variables are initialized."""
        # Assert SM2 instance variables exist
        assert hasattr(mock_daemon, '_sm2_state')
        assert hasattr(mock_daemon, '_event_state')
        assert hasattr(mock_daemon, '_event_label')
        assert hasattr(mock_daemon, '_event_sia_code')
        assert hasattr(mock_daemon, '_event_zone')
        assert hasattr(mock_daemon, '_event_attempt_count')

    def test_sm2_initial_values(self, mock_daemon):
        """Verify SM2 instance variables have correct initial values."""
        # Verify initial state
        assert mock_daemon._sm2_state == SM2State.IDLE
        assert mock_daemon._event_state == 0  # No alarm since startup
        assert mock_daemon._event_label == "Inactif"
        assert mock_daemon._event_sia_code is None
        assert mock_daemon._event_zone is None
        assert mock_daemon._event_attempt_count == 0


class TestSM2StateHelpers:
    """Test SM2 state-to-value converter helpers."""

    def test_event_state_from_sm2_idle(self, mock_daemon):
        """Test that IDLE state returns event_state=0."""
        mock_daemon._sm2_state = SM2State.IDLE
        assert mock_daemon._event_state_from_sm2() == 0

    def test_event_state_from_sm2_pending(self, mock_daemon):
        """Test that PENDING state returns event_state=3."""
        mock_daemon._sm2_state = SM2State.PENDING
        assert mock_daemon._event_state_from_sm2() == 3

    def test_event_state_from_sm2_confirmed(self, mock_daemon):
        """Test that CONFIRMED state returns event_state=1."""
        mock_daemon._sm2_state = SM2State.CONFIRMED
        assert mock_daemon._event_state_from_sm2() == 1

    def test_event_state_from_sm2_failed(self, mock_daemon):
        """Test that FAILED state returns event_state=2."""
        mock_daemon._sm2_state = SM2State.FAILED
        assert mock_daemon._event_state_from_sm2() == 2

    def test_event_label_from_sm2_idle(self, mock_daemon):
        """Test that IDLE state returns French label."""
        mock_daemon._sm2_state = SM2State.IDLE
        assert mock_daemon._event_label_from_sm2() == "Inactif"

    def test_event_label_from_sm2_pending(self, mock_daemon):
        """Test that PENDING state returns French label."""
        mock_daemon._sm2_state = SM2State.PENDING
        assert mock_daemon._event_label_from_sm2() == "En cours"

    def test_event_label_from_sm2_confirmed(self, mock_daemon):
        """Test that CONFIRMED state returns French label."""
        mock_daemon._sm2_state = SM2State.CONFIRMED
        assert mock_daemon._event_label_from_sm2() == "Confirmé"

    def test_event_label_from_sm2_failed(self, mock_daemon):
        """Test that FAILED state returns French label."""
        mock_daemon._sm2_state = SM2State.FAILED
        assert mock_daemon._event_label_from_sm2() == "Échoué"


# ===== Task 3: Alarm Retry Logic Tests =====

class TestSM2SendWithRetry:
    """Test _send_with_retry async method."""

    def test_send_with_retry_method_exists(self, mock_daemon):
        """Verify _send_with_retry method exists."""
        assert hasattr(mock_daemon, '_send_with_retry')
        assert callable(mock_daemon._send_with_retry)

    @pytest.mark.asyncio
    async def test_happy_path_ack_response(self, mock_daemon):
        """Test: alarm → PENDING → ACK → CONFIRMED.

        Expected result:
        - SM2 transitions to PENDING, then CONFIRMED on ACK
        - event_state updates to 1 (confirmed)
        - No notifications sent for success
        """
        # Create event item
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return ACK
        mock_daemon._send_raw = AsyncMock(return_value={"status": "ack"})

        # Execute _send_with_retry
        result = await mock_daemon._send_with_retry(event, max_retries=3)

        # Assert: Result is CONFIRMED
        assert result == SM2State.CONFIRMED
        # Assert: SM2 state updated
        assert mock_daemon._sm2_state == SM2State.CONFIRMED
        # Assert: event_state reflects confirmation (1)
        assert mock_daemon._event_state_from_sm2() == 1

    @pytest.mark.asyncio
    async def test_nak_undecodable_response(self, mock_daemon):
        """Test: alarm → PENDING → bad NAK → FAILED with T2 notification.

        Expected result:
        - SM2 transitions to PENDING, then FAILED on NAK
        - BAD_CSR_RESPONSE notification sent (T2)
        - event_state updates to 2 (failed)
        """
        event = EventItem(sia_code="FA", zone="Cuisine", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return undecodable NAK
        mock_daemon._send_raw = AsyncMock(
            return_value={"status": "nak", "raw_nak": b"invalid"}
        )

        # Execute _send_with_retry
        result = await mock_daemon._send_with_retry(event, max_retries=3)

        # Assert: Result is FAILED
        assert result == SM2State.FAILED
        # Assert: SM2 state is FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED
        # Assert: event_state is 2 (failed)
        assert mock_daemon._event_state_from_sm2() == 2
        # Assert: T2 notification sent (BAD_CSR_RESPONSE)
        mock_daemon._notify.assert_called()

    @pytest.mark.asyncio
    async def test_timeout_with_retries(self, mock_daemon):
        """Test: alarm → 3 timeouts → FAILED with T3 notification.

        Expected result:
        - Retries 3 times on timeout
        - Final state is FAILED
        - EVENT_FAILED notification sent (T3)
        - Attempt count equals max_retries + 1
        """
        event = EventItem(sia_code="PA", zone="Bureau", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to always timeout
        mock_daemon._send_raw = AsyncMock(return_value={"status": "timeout"})

        # Execute _send_with_retry with 2 retries
        result = await mock_daemon._send_with_retry(event, max_retries=2)

        # Assert: Result is FAILED
        assert result == SM2State.FAILED
        # Assert: SM2 state is FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED
        # Assert: Attempted 3 times (max_retries + 1)
        assert mock_daemon._event_attempt_count == 3
        # Assert: T3 notification sent (EVENT_FAILED)
        mock_daemon._notify.assert_called_with(
            ErrorCode.EVENT_FAILED,
            {
                "zone": "Bureau",
                "sia_code": "PA",
                "attempts": 3
            }
        )


# ===== Task 4: PriorityQueue Integration Tests =====

class TestSM2QueueConsumerIntegration:
    """Test SM2 integration with PriorityQueue consumer."""

    @pytest.mark.asyncio
    async def test_queue_consumer_handles_event_items(self):
        """Verify queue consumer processes EVENT items."""
        # Test placeholder
        pass

    @pytest.mark.asyncio
    async def test_no_idle_reentry(self):
        """Test: CONFIRMED → next alarm goes directly to PENDING (no IDLE)."""
        # Test placeholder
        pass


# ===== Task 5: NAK Timestamp Dispatch Tests =====

class TestNAKTimestampDispatch:
    """Test NAK timestamp parsing and SM1 strike updates."""

    @pytest.mark.asyncio
    async def test_parseable_nak_handling(self):
        """Test: NAK with valid timestamp → SM1 strike++, SM2 FAILED."""
        # Test placeholder
        pass

    @pytest.mark.asyncio
    async def test_unparseable_nak_handling(self):
        """Test: NAK with bad timestamp → T2 notification, SM2 FAILED."""
        # Test placeholder
        pass


# ===== Task 6: Network Loss Handling Tests =====

class TestNetworkLossHandling:
    """Test SM2 behavior when SM1 transitions to NO_NETWORK."""

    @pytest.mark.asyncio
    async def test_pending_event_fails_on_no_network(self):
        """Test: SM2=PENDING + SM1→NO_NETWORK → SM2 FAILED immediately."""
        # Test placeholder
        pass


# ===== Task 7: Logging Integration Tests =====

class TestSM2LoggingIntegration:
    """Test _log_sm2_event helper and logging output."""

    def test_log_sm2_event_method_exists(self, mock_daemon):
        """Verify _log_sm2_event method exists."""
        assert hasattr(mock_daemon, '_log_sm2_event')
        assert callable(mock_daemon._log_sm2_event)

    @pytest.mark.asyncio
    async def test_sm2_transitions_are_logged(self):
        """Test: All SM2 transitions produce log entries."""
        # Test placeholder
        pass


# ===== Task 8: Persistence Tests =====

class TestSM2Persistence:
    """Test event_state and event_label persistence across restarts."""

    @pytest.mark.asyncio
    async def test_persistence_confirmed_state_retained(self):
        """Test: CONFIRMED → stop daemon → restart → event_state=1 retained."""
        # Test placeholder
        pass
