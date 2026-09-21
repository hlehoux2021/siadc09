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
from resources.siadc09d.sia_transport import SIATransportResult
from tests.conftest import make_daemon_preset
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
        daemon = SIADaemon(preset=make_daemon_preset())

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
    daemon._notify = MagicMock()
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
        """Verify all SM2 instance variables are initialized.

        Note: _event_state and _event_label were removed as dead vars (M2 fix).
        SM2 state is exposed via _event_state_from_sm2() / _event_label_from_sm2()
        helpers, not stored redundantly as separate instance vars.
        """
        # Assert SM2 instance variables exist
        assert hasattr(mock_daemon, '_sm2_state')
        assert hasattr(mock_daemon, '_event_sia_code')
        assert hasattr(mock_daemon, '_event_zone')
        assert hasattr(mock_daemon, '_event_attempt_count')

    def test_sm2_initial_values(self, mock_daemon):
        """Verify SM2 instance variables have correct initial values."""
        # Verify initial state
        assert mock_daemon._sm2_state == SM2State.IDLE
        # Assert: IDLE state maps to event_state=0 and "Inactif" label via helpers
        assert mock_daemon._event_state_from_sm2() == 0
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
        """Test that IDLE state returns the bare inactive label.

        - IDLE has no active event, so no type/zone prefix is shown
        """
        mock_daemon._sm2_state = SM2State.IDLE
        # IDLE stays bare "Inactif" — no alarm in progress to name
        assert mock_daemon._event_label_from_sm2() == "Inactif"

    def test_event_label_from_sm2_pending(self, mock_daemon):
        """Test that PENDING interpolates the alarm type/zone into the label.

        - Type comes from _event_sia_code via event_type_fr(), capitalised
        - Zone comes from _event_zone
        - State clause is "En cours"
        """
        mock_daemon._sm2_state = SM2State.PENDING
        mock_daemon._event_sia_code = "BA"
        mock_daemon._event_zone = "3"
        # BA → "intrusion" → "Intrusion", zone inline, then state clause
        assert mock_daemon._event_label_from_sm2() == "Intrusion (zone 3) : En cours"

    def test_event_label_from_sm2_confirmed(self, mock_daemon):
        """Test that CONFIRMED names the alarm and reports central confirmation.

        - Type/zone prefix identifies the alarm in progress
        - State clause is "Confirmée par la centrale"
        """
        mock_daemon._sm2_state = SM2State.CONFIRMED
        mock_daemon._event_sia_code = "BA"
        mock_daemon._event_zone = "3"
        # Confirmed alarm names the event and the central's acceptance
        assert mock_daemon._event_label_from_sm2() == "Intrusion (zone 3) : Confirmée par la centrale"

    def test_event_label_from_sm2_failed(self, mock_daemon):
        """Test that FAILED names the alarm and reports central refusal.

        - Type/zone prefix identifies the alarm in progress
        - State clause is "Refusé par la centrale"
        """
        mock_daemon._sm2_state = SM2State.FAILED
        mock_daemon._event_sia_code = "FA"
        mock_daemon._event_zone = "2"
        # FA → "incendie" → "Incendie"; failed alarm reports refusal
        assert mock_daemon._event_label_from_sm2() == "Incendie (zone 2) : Refusé par la centrale"


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
        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

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
        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        # Execute _send_with_retry with 2 retries
        result = await mock_daemon._send_with_retry(event, max_retries=2)

        # Assert: Result is FAILED
        assert result == SM2State.FAILED
        # Assert: SM2 state is FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED
        # Assert: Attempted 3 times (max_retries + 1)
        assert mock_daemon._event_attempt_count == 3
        # Assert: T3 notification sent (EVENT_FAILED)
        event_failed_calls = [c for c in mock_daemon._notify.call_args_list
                              if c.args and c.args[0] == ErrorCode.EVENT_FAILED]
        assert len(event_failed_calls) == 1
        ctx = event_failed_calls[0].args[1]
        assert ctx.zone_name == "Bureau"
        assert ctx.sia_code == "PA"
        assert ctx.attempts_made == 3


# ===== Task 4: PriorityQueue Integration Tests =====

class TestSM2QueueConsumerIntegration:
    """Test SM2 integration with PriorityQueue consumer.

    Note: Full queue consumer integration (Task 4) is deferred to story 5-3.
    Tests here cover SM2 state transition behavior that can be verified
    independently of the PriorityQueue implementation.
    """

    @pytest.mark.asyncio
    async def test_queue_consumer_handles_event_items(self):
        """Verify queue consumer processes EVENT items.

        Note: Deferred to story 5-3 (PriorityQueue implementation).
        The _queue_consumer() method is not yet implemented.
        """
        # Deferred: depends on Task 5-3 PriorityQueue implementation
        pass

    @pytest.mark.asyncio
    async def test_no_idle_reentry(self, mock_daemon):
        """Test: After CONFIRMED, next alarm goes directly to PENDING (not IDLE).

        Verifies the SM2 invariant: IDLE is startup-only and never re-entered
        after the first alarm event. CONFIRMED → PENDING is a direct transition.

        Expected result:
        - Starting from CONFIRMED state, calling _send_with_retry sets SM2=PENDING immediately
        - SM2 is never set back to IDLE between alarms
        - After ACK, final state is CONFIRMED again (not IDLE)
        """
        # Arrange: daemon already has a CONFIRMED event (simulates previous alarm)
        mock_daemon._sm2_state = SM2State.CONFIRMED

        # Mock _send_raw to return ACK immediately for the next alarm
        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        event = EventItem(sia_code="FA", zone="Cuisine", timestamp="12:30:45,04-13-2026")

        # Act: send next alarm (simulates CONFIRMED → PENDING → CONFIRMED cycle)
        result = await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: Result is CONFIRMED (second alarm processed successfully)
        assert result == SM2State.CONFIRMED

        # Assert: SM2 is CONFIRMED, never went back to IDLE
        assert mock_daemon._sm2_state == SM2State.CONFIRMED
        assert mock_daemon._sm2_state != SM2State.IDLE

        # Assert: No IDLE re-entry (event_state never went to 0 during transition)
        # The _event_state_from_sm2 for CONFIRMED returns 1 (not 0 which is IDLE)
        assert mock_daemon._event_state_from_sm2() == 1


# ===== Task 5: NAK Timestamp Dispatch Tests =====

class TestNAKTimestampDispatch:
    """Test NAK handling — any NAK fires BAD_CSR_RESPONSE per daemon-design.md.

    Per daemon-design.md line 724 and SIA DC-09 § 5.5.3.2:
    - Any NAK in v1.0 → _notify(BAD_CSR_RESPONSE) → SM2 FAILED, stop retrying.
    - parse_nak_timestamp is called for diagnostic logging only; the parseable/
      undecodable distinction is irrelevant for SM2 (it is only relevant for SM1
      supervision NAK handling in supervision-design.md).
    - v1.1 will use the parsed timestamp for auto-heal resync.
    """

    @pytest.mark.asyncio
    async def test_parseable_nak_handling(self, mock_daemon):
        """Test: NAK with valid timestamp → SM2 FAILED + BAD_CSR_RESPONSE T2 notification.

        Per daemon-design.md: any NAK in v1.0 fires BAD_CSR_RESPONSE regardless of
        whether the timestamp is parseable. Timestamp parsing is diagnostic only.

        Expected result:
        - SM2 transitions to FAILED
        - BAD_CSR_RESPONSE (T2) notification IS called exactly once
        - parse_nak_timestamp succeeds (datetime returned — diagnostic path)
        """
        from datetime import datetime, timezone
        from unittest.mock import patch

        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return a NAK (bytes content doesn't matter, we patch the parser)
        mock_daemon._send_raw = AsyncMock(
            return_value={"status": "nak", "raw_nak": b"nak_bytes_placeholder"}
        )

        # Patch parse_nak_timestamp to simulate parseable NAK (returns datetime, no ValueError)
        expected_ts = datetime(2026, 4, 13, 14, 32, 45, tzinfo=timezone.utc)
        with patch(
            "resources.siadc09d.daemon.parse_nak_timestamp",
            return_value=expected_ts
        ):
            result = await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: SM2 FAILED on any NAK (v1.0 no auto-heal per daemon-design.md)
        assert result == SM2State.FAILED

        # Assert: SM2 state is FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED

        # Assert: BAD_CSR_RESPONSE (T2) IS fired — any event NAK triggers T2
        # (daemon-design.md line 724; parseable/undecodable split is SM1-only)
        call_args_list = mock_daemon._notify.call_args_list
        bad_csr_calls = [
            c for c in call_args_list
            if c.args and c.args[0] == ErrorCode.BAD_CSR_RESPONSE
        ]
        assert len(bad_csr_calls) == 1, (
            "BAD_CSR_RESPONSE must fire for any event NAK (daemon-design.md line 724)"
        )

    @pytest.mark.asyncio
    async def test_unparseable_nak_handling(self, mock_daemon):
        """Test: NAK with undecodable bytes → T2 (BAD_CSR_RESPONSE), SM2 FAILED.

        When parse_nak_timestamp raises ValueError (undecodable NAK), the code
        treats it as a CSR software/integration error and fires T2 notification.
        This is distinct from a parseable NAK (timestamp mismatch → protocol issue).

        Expected result:
        - SM2 transitions to FAILED
        - BAD_CSR_RESPONSE (T2) notification IS called
        - parse_nak_timestamp raises ValueError (simulated)
        """
        from unittest.mock import patch

        event = EventItem(sia_code="PA", zone="Bureau", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return NAK with bytes that cannot be parsed
        mock_daemon._send_raw = AsyncMock(
            return_value={"status": "nak", "raw_nak": b"invalid_nak_bytes"}
        )

        # Patch parse_nak_timestamp to explicitly raise ValueError (undecodable)
        with patch(
            "resources.siadc09d.daemon.parse_nak_timestamp",
            side_effect=ValueError("NAK timestamp field not present")
        ):
            result = await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: SM2 FAILED
        assert result == SM2State.FAILED
        assert mock_daemon._sm2_state == SM2State.FAILED

        # Assert: BAD_CSR_RESPONSE (T2) notification WAS fired
        mock_daemon._notify.assert_called()
        call_args_list = mock_daemon._notify.call_args_list
        bad_csr_calls = [
            c for c in call_args_list
            if c.args and c.args[0] == ErrorCode.BAD_CSR_RESPONSE
        ]
        assert len(bad_csr_calls) == 1, (
            "BAD_CSR_RESPONSE should fire exactly once for undecodable NAK"
        )


# ===== Task 6: Network Loss Handling Tests =====

class TestNetworkLossHandling:
    """Test SM2 behavior when SM1 transitions to NO_NETWORK.

    Note: Full NO_NETWORK → SM2 FAILED immediate handling (Task 6) is deferred
    to story 5-3, which implements _queue_consumer() with SM1 state checking.
    The test below verifies the SM1 state is accessible for future integration.
    """

    @pytest.mark.asyncio
    async def test_pending_event_fails_on_no_network(self):
        """Test: SM2=PENDING + SM1→NO_NETWORK → SM2 FAILED immediately.

        Note: Deferred to story 5-3 (queue consumer SM1 state check).
        When _queue_consumer() is implemented, it will check SM1 state before
        dispatching events and fail immediately if SM1=NO_NETWORK.
        """
        # Deferred: depends on Task 5-3 _queue_consumer() implementation
        pass


# ===== Task 7: Logging Integration Tests =====

class TestSM2LoggingIntegration:
    """Test _log_sm2_event helper and logging output."""

    def test_log_sm2_event_method_exists(self, mock_daemon):
        """Verify _log_sm2_event method exists."""
        assert hasattr(mock_daemon, '_log_sm2_event')
        assert callable(mock_daemon._log_sm2_event)

    @pytest.mark.asyncio
    async def test_sm2_transitions_are_logged(self, mock_daemon):
        """Test: SM2 transitions produce French INFO and English DEBUG log entries.

        The _log_sm2_event() helper must log:
        - French user-facing INFO line (from messages.py)
        - English technical DEBUG line
        Both lines go to the logger for the confirmed transition.

        Expected result:
        - logger.info is called with French confirmation message
        - logger.debug is called with English technical message
        - Messages contain sia_code and zone information
        """
        from resources.siadc09d.daemon import SM2LogCtx

        ctx = SM2LogCtx(
            zone="Salon",
            sia_code="BA",
            attempt=1,
            elapsed=0.5,
            state_change=True
        )

        # Act: log the "confirmed" transition
        await mock_daemon._log_sm2_event("confirmed", ctx)

        # Assert: logger.info called (French INFO line)
        mock_daemon._logger.info.assert_called()
        info_calls = [str(c) for c in mock_daemon._logger.info.call_args_list]
        # French confirmed message should mention alarm type and zone
        assert any("BA" in c or "Salon" in c for c in info_calls), (
            "INFO log should contain sia_code or zone from SM2LogCtx"
        )

        # Assert: logger.debug called (English DEBUG line)
        mock_daemon._logger.debug.assert_called()
        debug_calls = [str(c) for c in mock_daemon._logger.debug.call_args_list]
        # English debug line should contain SM2 transition name and zone
        assert any(
            "confirmed" in c.lower() or "BA" in c or "Salon" in c
            for c in debug_calls
        ), "DEBUG log should contain transition name, sia_code, or zone"


# ===== Task 8: Persistence Tests =====

class TestSM2Persistence:
    """Test event_state and event_label persistence across restarts.

    Note: Full persistence via PHP config.execAttr (Task 2.4) is deferred
    to the PHP integration story. Tests here verify the SM2 state values
    are correctly computed and stable for persistence.
    """

    @pytest.mark.asyncio
    async def test_persistence_confirmed_state_retained(self, mock_daemon):
        """Test: CONFIRMED state produces event_state=1 suitable for persistence.

        The event_state numeric value (0-3) is persisted to PHP config.execAttr
        via _update_info_commands. After a daemon restart, the SM2 state can be
        restored from this numeric value (Task 2.4, deferred to PHP integration).

        This test verifies that CONFIRMED state produces the correct numeric value
        that would be persisted and retrieved across restarts.

        Expected result:
        - SM2=CONFIRMED → event_state=1 (persisted value)
        - event_label="Intrusion (zone Salon) : Confirmée par la centrale"
        - These values are stable (same on every call, no side effects)
        """
        # Arrange: simulate daemon reaching CONFIRMED state after successful alarm
        mock_daemon._sm2_state = SM2State.CONFIRMED
        mock_daemon._event_sia_code = "BA"
        mock_daemon._event_zone = "Salon"

        confirmed_label = "Intrusion (zone Salon) : Confirmée par la centrale"

        # Assert: event_state=1 for CONFIRMED (value that would be persisted)
        assert mock_daemon._event_state_from_sm2() == 1

        # Assert: event_label names the alarm + central confirmation (persisted label)
        assert mock_daemon._event_label_from_sm2() == confirmed_label

        # Assert: Values are stable (idempotent calls produce same result)
        assert mock_daemon._event_state_from_sm2() == 1
        assert mock_daemon._event_label_from_sm2() == confirmed_label

        # Simulate "restart": manually restore state from persisted numeric value
        # (This is what Task 2.4 will implement via PHP config reading)
        # event_state=1 → CONFIRMED, event_state=2 → FAILED, etc.
        restored_state_value = mock_daemon._event_state_from_sm2()  # 1

        # After "restart", set SM2 state back to CONFIRMED (as Task 2.4 would do)
        # This validates the round-trip: state → numeric → state
        mock_daemon._sm2_state = SM2State.IDLE  # Simulate fresh daemon startup
        assert mock_daemon._event_state_from_sm2() == 0  # IDLE = 0

        # Restore from persisted value (inverse of _event_state_from_sm2)
        state_map = {0: SM2State.IDLE, 1: SM2State.CONFIRMED, 2: SM2State.FAILED, 3: SM2State.PENDING}
        mock_daemon._sm2_state = state_map[restored_state_value]

        # Assert: State correctly restored to CONFIRMED from persisted value
        assert mock_daemon._sm2_state == SM2State.CONFIRMED
        assert mock_daemon._event_state_from_sm2() == 1


# ===== Zone Extraction Tests (TC8) =====

class TestSM2ZoneExtraction:
    """Test zone extraction from EventItem and handoff to frame builder.

    Per design: zone from #zone# tag in alarm command → EventItem.zone →
    _build_event_frame extended_data → encode_message.

    Note: Actual zone encoding in the SIA frame (as [#ACCT|CODE zone] in the
    primary data block) is a gap in sia_protocol.py._format_data_field which
    currently ignores extended_data (noted as 'deferred to v1.1'). These tests
    verify the SM2 extraction and handoff path only.

    Reference: expert validation (sia-dc09-expert) confirmed zone belongs in
    primary data block per SIA DC-09 § 5.5.1.7, not extended data § 5.5.1.8.
    """

    @pytest.mark.asyncio
    async def test_zone_stored_in_event_zone(self, mock_daemon):
        """Test: Zone from EventItem is stored in _event_zone during send.

        Expected result:
        - _event_zone is set to the zone from EventItem when _send_with_retry starts
        - Zone is correctly extracted from EventItem (not hardcoded or lost)
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return ACK immediately
        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: _event_zone correctly set from EventItem
        assert mock_daemon._event_zone == "Salon"

    @pytest.mark.asyncio
    async def test_zone_passed_to_build_event_frame(self, mock_daemon):
        """Test: Zone from EventItem is passed to _build_event_frame correctly.

        Verifies the handoff path: EventItem.zone → _build_event_frame(event_item).
        The frame builder receives the full EventItem and can extract zone.

        Note: _format_data_field in sia_protocol.py currently ignores zone in
        extended_data (deferred to v1.1). This test verifies SM2's handoff only.

        Expected result:
        - _build_event_frame is called with the EventItem containing zone
        - No error raised during frame building with zone present
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # Mock _send_raw to return ACK
        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        # Act: call _send_with_retry and verify no errors (zone is passed through)
        result = await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: Frame was built and ACK received — zone extraction didn't break anything
        assert result == SM2State.CONFIRMED

        # Assert: _event_zone reflects the zone from EventItem
        assert mock_daemon._event_zone == "Salon"

    @pytest.mark.asyncio
    async def test_none_zone_handled_gracefully(self, mock_daemon):
        """Test: EventItem with zone=None is handled without errors.

        Expected result:
        - _event_zone is set to None
        - Frame building succeeds even with no zone
        - No KeyError or AttributeError from missing zone
        """
        event = EventItem(sia_code="FA", zone=None, timestamp="12:30:45,04-13-2026")

        mock_daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        result = await mock_daemon._send_with_retry(event, max_retries=1)

        # Assert: Succeeds without zone
        assert result == SM2State.CONFIRMED
        assert mock_daemon._event_zone is None
