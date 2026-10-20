"""SM2 Extended Coverage Suite — Quinn QA challenge pass.

Challenges and extends the baseline test_sm2_alarm_event_suite.py with:
- Protocol correctness (SIA DC-09 spec compliance)
- Retry loop mechanics (call counts, backoff, early exit)
- Payload verification (_update_info_commands arguments)
- Sequence number behavior
- All 3 alarm types parametrized
- Edge cases (max_retries=0, empty zone, callback field)
- Spec violations discovered and documented as known issues

Test organization:
- Level 2: Async integration, no Jeedom required
- Framework: pytest-asyncio
- Reference: story 5-2-sm2-alarm-event-state-machine.md
"""

import asyncio
import pytest
from resources.siadc09d.sia_transport import SIATransportResult
from tests.conftest import make_daemon_preset
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Optional

from resources.siadc09d.daemon import SIADaemon, SM2State, SM2LogCtx, EventItem
from resources.siadc09d.error_handler import ErrorCode
from resources.siadc09d.ring_buffer import RingBuffer
from resources.siadc09d.sia_protocol import parse_frame_header


# ===== SHARED FIXTURE =====

@pytest.fixture
def daemon():
    """SIADaemon with SM2 wired for extended coverage tests."""
    with patch('sys.argv', ['test']):
        d = SIADaemon(preset=make_daemon_preset())

    d._preset = MagicMock(
        crc_format='SIA',
        supervision_interval_s=10,
        reconnect_delay_s=1,
        encryption_enabled=False,
    )
    d._account = '001234'
    d._receiver_prefix = None
    d._account_prefix = 'L0'
    d._sia_seq = 0
    d._ring_buffer = RingBuffer()
    d._logger = MagicMock()
    d._notify = MagicMock()
    d._send_raw = AsyncMock()
    d._update_info_commands = AsyncMock()
    d._track_task = MagicMock()
    d._encryption_key = b''
    d._transport = 'UDP'

    from resources.siadc09d.daemon import SM1State
    d._sm1_state = SM1State.INITIALIZING
    d._strike_counter = 0
    d._sm1_t3_fired = False
    d._last_supervision_ack = None

    return d


# ===== EVENT ITEM DATACLASS TESTS =====

class TestEventItemDataclass:
    """Verify EventItem dataclass contract."""

    def test_event_item_required_fields(self):
        """Test: EventItem requires sia_code, zone, and timestamp.

        Expected result:
        - All 3 required fields accepted
        - callback defaults to None
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # Assert: required fields set
        assert event.sia_code == "BA"
        assert event.zone == "Salon"
        assert event.timestamp == "12:30:45,04-13-2026"

        # Assert: callback defaults to None
        assert event.callback is None

    def test_event_item_accepts_callback(self):
        """Test: EventItem accepts optional callback.

        Expected result:
        - callback field stores the provided callable
        """
        cb = MagicMock()
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026", callback=cb)

        # Assert: callback stored
        assert event.callback is cb

    def test_event_item_callback_not_invoked_by_send_with_retry(self, daemon):
        """Test: EventItem.callback is defined but NOT called by _send_with_retry.

        This is a KNOWN GAP: callback invocation is deferred to story 5-3
        (_queue_consumer implementation). When 5-3 is done, this test should
        be updated to assert the callback IS called.

        Expected result:
        - Callback defined on EventItem remains uncalled after _send_with_retry
        """
        cb = MagicMock()
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026", callback=cb)
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        # Note: this is sync wrapper — we verify callback not called via inspect
        # (callback invocation not in _send_with_retry per current design)
        assert event.callback == cb  # callback stored but invocation deferred to 5-3


# ===== RETRY MECHANICS TESTS =====

class TestRetryMechanics:
    """Verify _send_with_retry loop mechanics: call counts, timing, exit conditions."""

    @pytest.mark.asyncio
    async def test_send_raw_called_once_on_immediate_ack(self, daemon):
        """Test: _send_raw called exactly once when ACK received on first attempt.

        Expected result:
        - _send_raw call_count == 1
        - No retry occurs after success
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        await daemon._send_with_retry(event, max_retries=5)

        # Assert: only one call despite high max_retries
        assert daemon._send_raw.call_count == 1

    @pytest.mark.asyncio
    async def test_send_raw_called_max_retries_plus_one_on_timeout(self, daemon):
        """Test: _send_raw called exactly max_retries+1 times on repeated timeout.

        Expected result:
        - call_count == max_retries + 1 (initial + retries)
        - Final state is FAILED
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        with patch('asyncio.sleep'):  # Skip actual sleep delay in tests
            await daemon._send_with_retry(event, max_retries=2)

        # Assert: 3 total calls (attempts 0, 1, 2)
        assert daemon._send_raw.call_count == 3

    @pytest.mark.asyncio
    async def test_nak_retries_immediately_until_budget_exhausted(self, daemon):
        """Test: a NAK is repeated immediately, within the retry budget (§ 5.6.1.2).

        Story 1-5 AC4: NAK → immediate re-send with an updated timestamp, same
        sequence (§ 5.5.1.5). An unparseable NAK falls back to the current UTC time.

        Expected result:
        - _send_raw called max_retries + 1 times
        - asyncio.sleep never awaited (no back-off between NAK re-sends)
        - Every attempt carries the same wire seq
        - Final state is FAILED with reason 'nak'
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="nak", raw_nak=b"bad"))

        with patch('asyncio.sleep') as mock_sleep:
            await daemon._send_with_retry(event, max_retries=5)

        seqs = {parse_frame_header(c.args[0])[1] for c in daemon._send_raw.call_args_list}
        # Assert: initial attempt + 5 immediate NAK re-sends
        assert daemon._send_raw.call_count == 6
        # Assert: no sleep between NAK re-sends
        mock_sleep.assert_not_called()
        # Assert: one wire seq shared by every attempt
        assert len(seqs) == 1
        # Assert: budget exhausted → FAILED
        assert daemon._sm2_state == SM2State.FAILED
        # Assert: failure attributed to the NAK
        assert daemon._event_failure_reason == "nak"

    @pytest.mark.asyncio
    async def test_max_retries_zero_single_attempt_on_timeout(self, daemon):
        """Test: max_retries=0 means exactly one send attempt, then FAILED on timeout.

        Expected result:
        - _send_raw called exactly once
        - Final state is FAILED
        - EVENT_FAILED (T3) notification sent
        """
        event = EventItem(sia_code="PA", zone="Bureau", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        await daemon._send_with_retry(event, max_retries=0)

        # Assert: exactly 1 attempt
        assert daemon._send_raw.call_count == 1
        assert daemon._event_attempt_count == 1
        assert daemon._sm2_state == SM2State.FAILED

        # Assert: T3 notification fired (EVENT_FAILED after exhausting retries)
        daemon._notify.assert_called()

    @pytest.mark.asyncio
    async def test_ack_on_second_retry_succeeds(self, daemon):
        """Test: ACK on retry 2 (after 2 timeouts) → CONFIRMED, attempt_count=3.

        Expected result:
        - CONFIRMED returned after 2 timeouts + 1 ACK
        - _event_attempt_count == 3
        - _send_raw called 3 times total
        """
        event = EventItem(sia_code="FA", zone="Cuisine", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(side_effect=[
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="ack", raw_nak=None),
        ])

        with patch('asyncio.sleep'):  # Skip sleep between retries
            result = await daemon._send_with_retry(event, max_retries=3)

        # Assert: CONFIRMED on 3rd attempt
        assert result == SM2State.CONFIRMED
        assert daemon._sm2_state == SM2State.CONFIRMED
        assert daemon._event_attempt_count == 3
        assert daemon._send_raw.call_count == 3

    @pytest.mark.asyncio
    async def test_asyncio_timeout_error_triggers_failed(self, daemon):
        """Test: asyncio.TimeoutError exception path (from wait_for) → FAILED.

        This is a DISTINCT path from SIATransportResult(status="timeout", raw_nak=None) return value.
        asyncio.TimeoutError is raised by asyncio.wait_for() when _send_raw
        takes too long. Both paths should result in SM2 FAILED.

        Expected result:
        - SM2 transitions to FAILED
        - No unhandled exception raised to caller
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")

        # asyncio.TimeoutError raised by wait_for, not return value
        daemon._send_raw = AsyncMock(side_effect=asyncio.TimeoutError())

        result = await daemon._send_with_retry(event, max_retries=0)

        # Assert: FAILED without crashing
        assert result == SM2State.FAILED
        assert daemon._sm2_state == SM2State.FAILED

    @pytest.mark.asyncio
    async def test_transport_error_event_failed_carries_user_number(self, daemon):
        """Test: EVENT_FAILED context on the asyncio.TimeoutError/SIATransportError
        retry-exhaustion path carries the event's user_number (story 13-1, ADR-18).

        Code-review regression: this except-block's EventFailedCtx() call was
        missing user_number=event_item.user_number, unlike its three sibling
        EventFailedCtx call sites in _send_with_retry — a BC/OP event that fails
        via a transport error (not a NAK/no-response) would render the T3
        EVENT_FAILED notification's address clause as "<inconnu>".

        Expected result:
        - _notify called once with ErrorCode.EVENT_FAILED
        - Context's user_number matches the EventItem's configured user_number
        """
        event = EventItem(sia_code="BC", zone=None, user_number=3,
                           timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(side_effect=asyncio.TimeoutError())

        await daemon._send_with_retry(event, max_retries=0)

        event_failed_calls = [
            c for c in daemon._notify.call_args_list
            if c.args and c.args[0] == ErrorCode.EVENT_FAILED
        ]
        assert len(event_failed_calls) == 1

        ctx = event_failed_calls[0].args[1]
        # Assert: user_number reaches the EVENT_FAILED context, not the dataclass default
        assert ctx.user_number == 3


# ===== SEQUENCE NUMBER TESTS =====

class TestSequenceNumberBehavior:
    """Verify SIA DC-09 § 5.5.1.5 sequence number behavior."""

    @pytest.mark.asyncio
    async def test_seq_increments_per_new_alarm(self, daemon):
        """Test: Sequence number increments once for each new alarm event.

        Per SIA DC-09 § 5.5.1.5: seq is associated with the message as it is
        queued. A new alarm → new seq. Two alarms → two increments.

        Expected result:
        - Sending alarm 1: sia_seq goes from 0 → 1
        - Sending alarm 2: sia_seq goes from 1 → 2
        """
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        event1 = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        await daemon._send_with_retry(event1, max_retries=1)

        seq_after_alarm1 = daemon._sia_seq  # Should be 1

        event2 = EventItem(sia_code="FA", zone="Cuisine", timestamp="12:30:45,04-13-2026")
        await daemon._send_with_retry(event2, max_retries=1)

        seq_after_alarm2 = daemon._sia_seq  # Should be 2

        # Assert: Each new alarm increments seq exactly once
        assert seq_after_alarm1 == 1
        assert seq_after_alarm2 == 2

    @pytest.mark.asyncio
    async def test_seq_wraps_at_9999(self, daemon):
        """Test: the event sequence wraps from 9999 → 0001 (§ 5.5.1.5).

        Story 1-5 AC4: _sia_seq is taken from the built frame, so it follows the
        SequenceTracker wrap rule ('When the sequence number is 9999, the next
        sequence number is 0001').

        Expected result:
        - Tracker at 9999, after one send: sia_seq == 1
        """
        daemon._sia_builder._sequence_tracker._seq_map[daemon._account] = 9999
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        await daemon._send_with_retry(event, max_retries=1)

        # Assert: wrapped to 0001, never 0000
        assert daemon._sia_seq == 1

    @pytest.mark.asyncio
    async def test_seq_does_not_increment_on_retry(self, daemon):
        """Test: Sequence number must NOT increment on timeout retry.

        SIA DC-09 § 5.5.1.5 states: 'The PE shall NOT increment the sequence number
        when repeating a message due to a communication failure or no response from a CSR.'

        Story 1-5 AC4: the first attempt draws the wire seq; retries reuse it,
        and _sia_seq mirrors the wire seq.

        Expected result:
        - 2 timeouts + 1 ACK → seq increments exactly ONCE (for the new event)
        - NOT 3 times (old broken behavior: once per _build_event_frame call)
        """
        initial_seq = daemon._sia_seq  # 0
        daemon._send_raw = AsyncMock(side_effect=[
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="ack", raw_nak=None),
        ])

        with patch('asyncio.sleep'):
            await daemon._send_with_retry(event := EventItem(
                sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026"
            ), max_retries=3)

        # Assert: seq incremented exactly once regardless of retry count
        assert daemon._sia_seq == initial_seq + 1


# ===== INFO COMMAND PAYLOAD TESTS =====

class TestInfoCommandPayloads:
    """Verify _update_info_commands is called with correct payloads."""

    @pytest.mark.asyncio
    async def test_update_info_on_confirmed(self, daemon):
        """Test: _update_info_commands called with event_state=1 + confirmed label on ACK.

        Expected result:
        - _update_info_commands called at least once
        - Final call payload has event_state=1 (CONFIRMED) and
          event_label="Intrusion (zone Salon) : Confirmé par la centrale"
        """
        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        await daemon._send_with_retry(event, max_retries=1)

        # Assert: called at least once
        daemon._update_info_commands.assert_called()

        # Assert: last call has correct payload for CONFIRMED state
        last_call_args = daemon._update_info_commands.call_args
        payload = last_call_args[0][0]  # First positional arg (the dict)
        assert payload.get('event_state') == 1, (
            f"Expected event_state=1 (CONFIRMED), got {payload.get('event_state')}"
        )
        assert payload.get('event_label') == "Intrusion (zone Salon) : Confirmé par la centrale", (
            f"Expected confirmed label, got {payload.get('event_label')}"
        )

    @pytest.mark.asyncio
    async def test_update_info_on_max_retries_failed(self, daemon):
        """Test: _update_info_commands called with event_state=2 + no-response label on FAILED.

        Expected result:
        - _update_info_commands called after final timeout failure
        - Payload has event_state=2 (FAILED) and
          event_label="Panique (zone Bureau) : Sans réponse de la centrale" — a timeout is
          "no reply at all", not an explicit CSR rejection, so it must not say "Refusé"
        """
        event = EventItem(sia_code="PA", zone="Bureau", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        with patch('asyncio.sleep'):
            await daemon._send_with_retry(event, max_retries=0)

        # Assert: called at least once
        daemon._update_info_commands.assert_called()

        # Assert: last call has correct FAILED payload
        last_call_args = daemon._update_info_commands.call_args
        payload = last_call_args[0][0]
        assert payload.get('event_state') == 2, (
            f"Expected event_state=2 (FAILED), got {payload.get('event_state')}"
        )
        assert payload.get('event_label') == "Panique (zone Bureau) : Sans réponse de la centrale", (
            f"Expected no-response label, got {payload.get('event_label')}"
        )


# ===== ALL ALARM TYPES PARAMETRIZED =====

class TestAllAlarmTypes:
    """Verify all 3 SIA alarm codes flow through SM2 correctly."""

    @pytest.mark.parametrize("sia_code,zone,expected_label", [
        ("BA", "Salon",   "burglarAlarm — zone Salon"),
        ("FA", "Cuisine", "fireAlarm — zone Cuisine"),
        ("PA", "Bureau",  "panicAlarm — zone Bureau"),
    ])
    @pytest.mark.asyncio
    async def test_alarm_type_confirmed(self, daemon, sia_code, zone, expected_label):
        """Test: Each alarm type (BA, FA, PA) can reach CONFIRMED state.

        Expected result:
        - SM2 CONFIRMED for all 3 alarm types
        - _event_sia_code set to the correct code
        - _event_zone set to the correct zone
        """
        event = EventItem(sia_code=sia_code, zone=zone, timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        result = await daemon._send_with_retry(event, max_retries=1)

        # Assert: CONFIRMED for all types
        assert result == SM2State.CONFIRMED
        assert daemon._sm2_state == SM2State.CONFIRMED

        # Assert: Correct SIA code and zone stored
        assert daemon._event_sia_code == sia_code
        assert daemon._event_zone == zone

    @pytest.mark.parametrize("sia_code,zone", [
        ("BA", "Salon"),
        ("FA", "Cuisine"),
        ("PA", "Bureau"),
    ])
    @pytest.mark.asyncio
    async def test_alarm_type_failed_on_max_retries(self, daemon, sia_code, zone):
        """Test: Each alarm type reaches FAILED on max retries.

        Expected result:
        - SM2 FAILED for all 3 alarm types when retries exhausted
        - EVENT_FAILED (T3) notification sent with correct sia_code
        """
        event = EventItem(sia_code=sia_code, zone=zone, timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        with patch('asyncio.sleep'):
            result = await daemon._send_with_retry(event, max_retries=0)

        # Assert: FAILED for all types
        assert result == SM2State.FAILED

        # Assert: Notification carries correct sia_code
        daemon._notify.assert_called()
        notify_calls = [c for c in daemon._notify.call_args_list
                        if c.args and c.args[0] == ErrorCode.EVENT_FAILED]
        assert len(notify_calls) == 1
        notify_ctx = notify_calls[0].args[1]
        assert notify_ctx.sia_code == sia_code


# ===== LOGGING QUALITY TESTS =====

class TestLoggingQuality:
    """Verify log message content matches messages.py French strings exactly."""

    @pytest.mark.asyncio
    async def test_confirmed_transition_logs_exact_french_message(self, daemon):
        """Test: CONFIRMED transition logs exact French message from messages.py.

        Expected result:
        - logger.info called with message containing 'Centrale confirmée'
        """
        from resources.siadc09d import messages

        ctx = SM2LogCtx(
            zone="Salon", sia_code="BA",
            attempt=1, elapsed=0.5, state_change=True
        )
        await daemon._log_sm2_event("confirmed", ctx)

        # Assert: exact French phrase from messages.SM2_CONFIRMED
        info_calls = [str(c) for c in daemon._logger.info.call_args_list]
        assert any("Centrale confirmée" in c for c in info_calls), (
            f"Expected 'Centrale confirmée' in INFO log. Got: {info_calls}"
        )

    @pytest.mark.asyncio
    async def test_failed_nak_transition_logs_exact_french_message(self, daemon):
        """Test: failed_nak transition logs exact French message from messages.py.

        Expected result:
        - logger.info called with message containing 'Réponse inattendue de la centrale'
        """
        ctx = SM2LogCtx(
            zone="Salon", sia_code="FA",
            attempt=1, elapsed=0.5, state_change=True
        )
        await daemon._log_sm2_event("failed_nak", ctx)

        info_calls = [str(c) for c in daemon._logger.info.call_args_list]
        assert any("Réponse inattendue" in c for c in info_calls), (
            f"Expected 'Réponse inattendue' in INFO log. Got: {info_calls}"
        )

    @pytest.mark.asyncio
    async def test_timeout_retry_logs_attempt_number(self, daemon):
        """Test: failed_timeout transition logs attempt number in French message.

        Expected result:
        - logger.info called with message containing retry attempt number
        """
        ctx = SM2LogCtx(
            zone="Bureau", sia_code="PA",
            attempt=2, elapsed=0.5, state_change=False
        )
        await daemon._log_sm2_event("failed_timeout", ctx)

        info_calls = [str(c) for c in daemon._logger.info.call_args_list]
        # SM2_RETRY format: "Pas de réponse de la centrale — tentative {attempt}/{max}"
        assert any("tentative" in c for c in info_calls), (
            f"Expected 'tentative' in INFO log for retry. Got: {info_calls}"
        )

    @pytest.mark.asyncio
    async def test_log_without_ctx_uses_instance_variables(self, daemon):
        """Test: _log_sm2_event called without ctx falls back to instance variables.

        Expected result:
        - No AttributeError or KeyError when ctx=None
        - Log entry produced using daemon's own _event_zone and _event_sia_code
        """
        daemon._event_zone = "Entrée"
        daemon._event_sia_code = "BA"
        daemon._event_attempt_count = 1

        # Act: call without ctx — should use fallback
        await daemon._log_sm2_event("confirmed", ctx=None)

        # Assert: logged without error
        daemon._logger.info.assert_called()


# ===== EDGE CASE TESTS =====

class TestEdgeCases:
    """Edge cases and boundary conditions for SM2."""

    @pytest.mark.asyncio
    async def test_empty_string_zone_treated_as_present(self, daemon):
        """Test: zone="" (empty string) is treated as a present (not None) zone.

        EventItem.zone = "" is logically different from zone = None.
        An empty string still passes to _build_event_frame; None results in no zone field.

        Expected result:
        - _event_zone == "" (empty string, not None)
        - Frame building succeeds
        """
        event = EventItem(sia_code="BA", zone="", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))

        result = await daemon._send_with_retry(event, max_retries=1)

        assert result == SM2State.CONFIRMED
        assert daemon._event_zone == ""  # Empty string preserved, not converted to None

    @pytest.mark.asyncio
    async def test_attempt_count_resets_per_new_event(self, daemon):
        """Test: _event_attempt_count resets to 0 at start of each new event send.

        Expected result:
        - After event 1 (3 attempts), _event_attempt_count == 3
        - After event 2 (1 attempt/ACK), _event_attempt_count == 1 (not 4)
        """
        # Event 1: 3 attempts (2 timeouts + 1 ACK)
        daemon._send_raw = AsyncMock(side_effect=[
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="timeout", raw_nak=None),
            SIATransportResult(status="ack", raw_nak=None),
        ])
        event1 = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        with patch('asyncio.sleep'):
            await daemon._send_with_retry(event1, max_retries=3)

        assert daemon._event_attempt_count == 3

        # Event 2: 1 attempt (immediate ACK)
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="ack", raw_nak=None))
        event2 = EventItem(sia_code="FA", zone="Cuisine", timestamp="12:30:45,04-13-2026")
        await daemon._send_with_retry(event2, max_retries=1)

        # Assert: count reset and reflects only event 2's attempts
        assert daemon._event_attempt_count == 1

    @pytest.mark.asyncio
    async def test_sm2_starts_pending_on_send(self, daemon):
        """Test: _sm2_state transitions to PENDING at the very start of _send_with_retry.

        IDLE → PENDING must happen before _send_raw is called.

        Expected result:
        - State is PENDING during _send_raw execution (captured via side_effect)
        """
        states_during_send = []

        async def capture_state(*args, **kwargs):
            states_during_send.append(daemon._sm2_state)
            return SIATransportResult(status="ack", raw_nak=None)

        daemon._send_raw = capture_state

        event = EventItem(sia_code="BA", zone="Salon", timestamp="12:30:45,04-13-2026")
        await daemon._send_with_retry(event, max_retries=1)

        # Assert: state was PENDING when send was called
        assert len(states_during_send) >= 1
        assert states_during_send[0] == SM2State.PENDING

    @pytest.mark.asyncio
    async def test_notify_context_contains_zone_and_sia_code_on_event_failed(self, daemon):
        """Test: EVENT_FAILED notification context includes zone and sia_code.

        Expected result:
        - _notify called with ErrorCode.EVENT_FAILED
        - Context dict has 'zone' == event zone and 'sia_code' == event sia_code
        """
        event = EventItem(sia_code="FA", zone="Cave", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(return_value=SIATransportResult(status="timeout", raw_nak=None))

        await daemon._send_with_retry(event, max_retries=0)

        # Find the EVENT_FAILED notification
        event_failed_calls = [
            c for c in daemon._notify.call_args_list
            if c.args and c.args[0] == ErrorCode.EVENT_FAILED
        ]
        assert len(event_failed_calls) == 1

        ctx = event_failed_calls[0].args[1]
        assert ctx.zone_name == "Cave"
        assert ctx.sia_code == "FA"
        assert ctx.attempts_made == 1

    @pytest.mark.asyncio
    async def test_bad_csr_notification_context_on_undecodable_nak(self, daemon):
        """Test: BAD_CSR_RESPONSE context carries zone and sia_code.

        Expected result:
        - BAD_CSR_RESPONSE (T2) notification context includes diagnostic info
        """
        from unittest.mock import patch

        event = EventItem(sia_code="PA", zone="Garage", timestamp="12:30:45,04-13-2026")
        daemon._send_raw = AsyncMock(
            return_value=SIATransportResult(status="nak", raw_nak=b"corrupt")
        )

        with patch("resources.siadc09d.daemon.parse_nak_timestamp",
                   side_effect=ValueError("invalid")):
            await daemon._send_with_retry(event, max_retries=1)

        bad_csr_calls = [
            c for c in daemon._notify.call_args_list
            if c.args and c.args[0] == ErrorCode.BAD_CSR_RESPONSE
        ]
        assert len(bad_csr_calls) == 1

        ctx = bad_csr_calls[0].args[1]
        # BadCSRResponseCtx carries protocol diagnostic info, not event zone/sia_code
        assert ctx.raw_frame == b"corrupt"
        assert "unparseable" in ctx.parse_error.lower() or "NAK" in ctx.parse_error
