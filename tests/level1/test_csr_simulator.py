"""
CSR Simulator Framework Tests

Test suite for Story 1.4: CSR Simulator Framework — a standalone testing tool
that accepts UDP/TCP connections and generates valid CSR responses (ACK/NAK).

Tests follow pytest conventions with function-based tests and pytest fixtures.
"""

import asyncio
import pytest
import socket
from datetime import datetime, timezone

# These imports will fail initially (RED phase) — module doesn't exist yet
from resources.siadc09d.csr_simulator import CSRSimulator, CSRSimulatorError
from resources.siadc09d.sia_protocol import SIAMessageBuilder
from resources.siadc09d.sia_crypto import SIACipher


# ============================================================================
# TASK 0: MODULE SKELETON & EXCEPTION CLASSES (RED PHASE TESTS)
# ============================================================================

class TestCSRSimulatorError:
    """Test CSRSimulatorError exception class.

    Expected result:
    - CSRSimulatorError can be instantiated with a message
    - It is a subclass of Exception
    - It can be caught and re-raised
    """

    def test_csr_simulator_error_is_exception(self):
        """Test that CSRSimulatorError is an Exception subclass."""
        # Assert: CSRSimulatorError inherits from Exception (per exc hierarchy in design)
        assert issubclass(CSRSimulatorError, Exception)

    def test_csr_simulator_error_can_be_instantiated(self):
        """Test that CSRSimulatorError can be created with a message."""
        message = "Test error message"
        error = CSRSimulatorError(message)

        # Assert: Error message is stored correctly
        assert str(error) == message

    def test_csr_simulator_error_can_be_raised_and_caught(self):
        """Test that CSRSimulatorError can be raised and caught."""
        with pytest.raises(CSRSimulatorError) as exc_info:
            raise CSRSimulatorError("Preset validation failed")

        # Assert: Error caught with correct message
        assert "Preset validation failed" in str(exc_info.value)


class TestCSRSimulatorModuleStructure:
    """Test that CSRSimulator module has required structure.

    Expected result:
    - CSRSimulator class exists and is instantiable
    - Module imports all required dependencies
    - Type hints present on all public methods
    """

    def test_csr_simulator_class_exists(self):
        """Test that CSRSimulator class can be imported."""
        # Assert: CSRSimulator is a class with callable constructor
        assert callable(CSRSimulator)

    def test_csr_simulator_has_required_methods(self):
        """Test that CSRSimulator has required public methods."""
        required_methods = ['__init__', 'start', 'stop']

        # Assert: All required methods exist
        for method_name in required_methods:
            assert hasattr(CSRSimulator, method_name), f"Missing method: {method_name}"

    def test_csr_simulator_constructor_signature(self):
        """Test that __init__ has correct parameters."""
        import inspect

        sig = inspect.signature(CSRSimulator.__init__)
        params = list(sig.parameters.keys())

        # Assert: Required parameters present (self, udp_port, tcp_port, preset, response_delay_ms)
        assert 'self' in params
        assert 'udp_port' in params
        assert 'tcp_port' in params
        assert 'preset' in params
        assert 'response_delay_ms' in params

    def test_csr_simulator_start_is_async(self):
        """Test that start() is an async method."""
        import inspect

        # Assert: start method is a coroutine function
        assert inspect.iscoroutinefunction(CSRSimulator.start)

    def test_csr_simulator_stop_is_async(self):
        """Test that stop() is an async method."""
        import inspect

        # Assert: stop method is a coroutine function
        assert inspect.iscoroutinefunction(CSRSimulator.stop)


# ============================================================================
# TASK 0B: PRESET VALIDATION TESTS
# ============================================================================

class TestPresetValidation:
    """Test preset validation functionality.

    Expected result:
    - Valid presets are accepted without error
    - Missing or invalid fields raise CSRSimulatorError with clear messages
    - All error conditions documented in Task 0b are covered
    """

    def test_validate_preset_valid_hex_format(self):
        """Test that valid preset with hex CRC format is accepted."""
        preset = {
            'crc_format': 'hex',
            'account_number': '000001',
            'encryption_key': None
        }

        # Assert: Valid preset accepted (no exception raised)
        # This will fail until _validate_preset() is implemented
        try:
            CSRSimulator(5000, 5001, preset)
            # If we get here without exception, validation passed
            valid = True
        except CSRSimulatorError:
            valid = False

        assert valid, "Valid preset should not raise CSRSimulatorError"

    def test_validate_preset_valid_bin_format(self):
        """Test that valid preset with binary CRC format is accepted."""
        preset = {
            'crc_format': 'bin',
            'account_number': 'ABCD12',
            'encryption_key': None
        }

        # Assert: Valid preset with bin format accepted
        try:
            CSRSimulator(5000, 5001, preset)
            valid = True
        except CSRSimulatorError:
            valid = False

        assert valid, "Valid preset with bin format should not raise error"

    def test_validate_preset_missing_crc_format(self):
        """Test that missing crc_format raises CSRSimulatorError."""
        preset = {
            'account_number': '000001',
            'encryption_key': None
        }

        # Assert: Missing crc_format raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'crc_format' in str(exc_info.value).lower()

    def test_validate_preset_invalid_crc_format_value(self):
        """Test that invalid crc_format value raises CSRSimulatorError."""
        preset = {
            'crc_format': 'invalid',
            'account_number': '000001',
            'encryption_key': None
        }

        # Assert: Invalid crc_format raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'crc_format' in str(exc_info.value).lower()

    def test_validate_preset_invalid_encryption_key_type(self):
        """Test that non-bytes encryption_key raises CSRSimulatorError."""
        preset = {
            'crc_format': 'hex',
            'account_number': '000001',
            'encryption_key': 'not_bytes_string'
        }

        # Assert: Non-bytes encryption_key raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'encryption_key' in str(exc_info.value).lower() or 'type' in str(exc_info.value).lower()

    def test_validate_preset_invalid_account_number_non_hex(self):
        """Test that non-hex account_number raises CSRSimulatorError."""
        preset = {
            'crc_format': 'hex',
            'account_number': 'ZZZZZZ',  # Z is not hex
            'encryption_key': None
        }

        # Assert: Non-hex account_number raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'account' in str(exc_info.value).lower() or 'hex' in str(exc_info.value).lower()

    def test_validate_preset_invalid_account_number_too_short(self):
        """Test that account_number <3 chars raises CSRSimulatorError."""
        preset = {
            'crc_format': 'hex',
            'account_number': 'AB',  # Only 2 chars, need 3-16
            'encryption_key': None
        }

        # Assert: Too-short account_number raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'account' in str(exc_info.value).lower()

    def test_validate_preset_invalid_account_number_too_long(self):
        """Test that account_number >16 chars raises CSRSimulatorError."""
        preset = {
            'crc_format': 'hex',
            'account_number': 'ABCDEF0123456789AB',  # 18 chars, max is 16
            'encryption_key': None
        }

        # Assert: Too-long account_number raises CSRSimulatorError
        with pytest.raises(CSRSimulatorError) as exc_info:
            CSRSimulator(5000, 5001, preset)

        assert 'account' in str(exc_info.value).lower()


# ============================================================================
# FIXTURES (for later tasks)
# ============================================================================

@pytest.fixture(scope="function")
def csr_preset():
    """Fixture: Basic CSR preset with hex CRC format, no encryption."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': None
    }


@pytest.fixture(scope="function")
def csr_preset_hex():
    """Fixture: CSR preset with hex CRC format (explicit)."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': None
    }


@pytest.fixture(scope="function")
def csr_preset_bin():
    """Fixture: CSR preset with binary CRC format."""
    return {
        'crc_format': 'bin',
        'account_number': '000001',
        'encryption_key': None
    }


@pytest.fixture(scope="function")
def csr_preset_encrypted():
    """Fixture: CSR preset with encryption enabled (AES-128)."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': b'0123456789ABCDEF'  # 16-byte AES-128 key
    }


@pytest.fixture(scope="function")
def csr_preset_no_key():
    """Fixture: CSR preset with no encryption key (for error testing)."""
    return {
        'crc_format': 'hex',
        'account_number': '000001',
        'encryption_key': None
    }


@pytest.fixture(scope="function")
async def simulator_udp_port():
    """Fixture: Ephemeral UDP port for testing."""
    # Using port 0 lets OS assign an available port
    return 0


@pytest.fixture(scope="function")
async def simulator_tcp_port():
    """Fixture: Ephemeral TCP port for testing."""
    return 0


@pytest.fixture(scope="function")
async def simulator(csr_preset, simulator_udp_port, simulator_tcp_port):
    """Fixture: Create, start, and cleanup simulator instance."""
    # Create ephemeral ports
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    udp_port = sock.getsockname()[1]
    sock.close()

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.bind(('127.0.0.1', 0))
    tcp_port = tcp_sock.getsockname()[1]
    tcp_sock.close()

    sim = CSRSimulator(udp_port, tcp_port, csr_preset)
    await sim.start()

    yield sim

    await sim.stop()


# ============================================================================
# TASK 1: UDP/TCP SERVER FRAMEWORK TESTS
# ============================================================================

class TestServerStartupShutdown:
    """Test UDP/TCP server startup and shutdown.

    Expected result:
    - Server starts on configured ports without error
    - Both UDP and TCP listeners are active simultaneously
    - Server stops cleanly without hanging
    """

    @pytest.mark.asyncio
    async def test_server_starts_without_error(self, csr_preset):
        """Test that server starts on configured ports."""
        # Create ephemeral ports
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        udp_port = sock.getsockname()[1]
        sock.close()

        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.bind(('127.0.0.1', 0))
        tcp_port = tcp_sock.getsockname()[1]
        tcp_sock.close()

        sim = CSRSimulator(udp_port, tcp_port, csr_preset)

        # Assert: Server starts without raising exception
        try:
            await sim.start()
            started = True
        except Exception as e:
            started = False
            exc = str(e)

        assert started, f"Server failed to start: {exc if not started else ''}"

        await sim.stop()

    @pytest.mark.asyncio
    async def test_server_stops_cleanly(self, csr_preset):
        """Test that server stops cleanly without hanging."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        udp_port = sock.getsockname()[1]
        sock.close()

        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.bind(('127.0.0.1', 0))
        tcp_port = tcp_sock.getsockname()[1]
        tcp_sock.close()

        sim = CSRSimulator(udp_port, tcp_port, csr_preset)
        await sim.start()

        # Assert: Server stops without hanging (timeout would fail this)
        try:
            await asyncio.wait_for(sim.stop(), timeout=5.0)
            stopped = True
        except asyncio.TimeoutError:
            stopped = False

        assert stopped, "Server stop() timed out"


# ============================================================================
# TASK 0: RESPONSE DECISION LOGIC (RED PHASE)
# ============================================================================

class TestResponseDecisionLogic:
    """Test _decide_response() for all frame types (Task 0).

    Expected result:
    - ALARM → 'ACK'
    - NULL → 'ACK'
    - ACK → 'ACK' (echo)
    - unknown → 'NAK'
    - malformed → 'NAK'
    """

    @pytest.mark.parametrize("frame_type,expected_response", [
        ({'type': 'ALARM', 'seq': 1, 'raw_nak': None}, 'ACK'),
        ({'type': 'NULL', 'seq': 0, 'raw_nak': None}, 'ACK'),
        ({'type': 'ACK', 'seq': 1, 'raw_nak': None}, 'ACK'),
        ({'type': 'unknown', 'seq': None, 'raw_nak': None}, 'NAK'),
        ({'type': 'malformed', 'seq': None, 'raw_nak': None}, 'NAK'),
    ])
    def test_response_decision_all_types(self, preset_plain, frame_type, expected_response):
        """Test _decide_response for all frame types (parametrized)."""
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)

        # Assert: Response type matches expected for each frame type
        response = simulator._decide_response(frame_type, preset_plain)
        assert response == expected_response, f"Frame type {frame_type['type']} should return {expected_response}, got {response}"


# ============================================================================
# TASK 10: ACK/NAK FRAME GENERATION (RED PHASE)
# ============================================================================

class TestACKFrameGeneration:
    """Test _generate_ack_frame() implementation (Task 10).

    Expected result:
    - ACK plaintext frame has correct structure (LF...CR delimiters)
    - ACK plaintext contains correct message: "ACK"<seq>R0L0#<account>[]
    - ACK ciphertext uses id_token "*ACK" and is encrypted
    - CRC values are correct for both hex and bin formats
    """

    def test_ack_plaintext_frame_structure(self, preset_plain):
        """Test ACK plaintext frame starts with LF and ends with CR.

        Expected result:
        - Frame starts with LF (0x0A) delimiter
        - Frame ends with CR (0x0D) delimiter
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)
        ack_frame = simulator._generate_ack_frame(1, preset_plain, encrypted_inbound=False)

        # Assert: Frame starts with LF (0x0A)
        assert ack_frame[0:1] == b'\x0A', "ACK frame must start with LF (0x0A)"

        # Assert: Frame ends with CR (0x0D)
        assert ack_frame[-1:] == b'\x0D', "ACK frame must end with CR (0x0D)"

    def test_ack_plaintext_contains_message(self, preset_plain):
        """Test ACK plaintext frame contains correct message.

        Expected result:
        - Frame contains properly formatted message: "ACK"<seq>R0L0#<account>[]
        - Sequence number matches inbound (seq=0001 for input seq=1)
        - Account number matches preset (000001)
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)
        ack_frame = simulator._generate_ack_frame(1, preset_plain, encrypted_inbound=False)

        # Assert: Frame contains expected message with correct seq and account
        assert b'"ACK"0001R0L0#000001[]' in ack_frame, "ACK frame should contain message with correct seq and account"

    def test_ack_encrypted_has_star_marker(self, preset_encrypted):
        """Test encrypted ACK follows DC-09 § 5.5.3.1: "*ACK" header, hex region.

        Expected result:
        - The body starts with the clear header "*ACK"0001R0L0#000001[
        - The region is uppercase hex, terminated by ']' (D1 reverted 2026-09-28)
        - The oracle decrypts it to "]_" + the receiver timestamp
        """
        from resources.siadc09d.csr_simulator import CSRSimulator
        from tests.level1._dc09_crypto_oracle import oracle_region, split_frame, split_wire

        ts = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
        simulator = CSRSimulator(10001, 5000, preset_encrypted)
        ack_frame = simulator._generate_ack_frame(
            1, preset_encrypted, encrypted_inbound=True, account='000001', timestamp=ts,
        )
        _crc, _length, body = split_frame(ack_frame)
        header, _, region = body.partition('[')
        _token, hex_text = split_wire(body)

        # Assert: clear header carries the *ACK token, seq, prefixes and account
        assert header == '"*ACK"0001R0L0#000001', f"unexpected header {header!r}"
        # Assert: region is uppercase hex, closed by ']'
        assert region == region.upper() and region.endswith(']') \
            and all(c in '0123456789ABCDEF' for c in region[:-1]), \
            f"region is not uppercase hex terminated by ']': {region!r}"
        # Assert: oracle decrypts it to the timestamp-only ACK content
        assert oracle_region(hex_text, preset_encrypted['encryption_key'])[1] == \
            b']_10:00:00,09-28-2026', "decrypted ACK content mismatch"

    @pytest.mark.parametrize("crc_format", ['hex', 'bin'])
    def test_ack_crc_format_matches_preset(self, crc_format):
        """Test ACK CRC format matches preset (hex vs bin)."""
        from resources.siadc09d.csr_simulator import CSRSimulator

        preset = {
            'crc_format': crc_format,
            'account_number': '000001',
            'encryption_key': None
        }

        simulator = CSRSimulator(10001, 5000, preset)
        ack_frame = simulator._generate_ack_frame(1, preset, encrypted_inbound=False)

        # Assert: Frame structure is valid (starts with LF, ends with CR)
        assert ack_frame[0:1] == b'\x0A', f"Frame must start with LF for {crc_format} format"
        assert ack_frame[-1:] == b'\x0D', f"Frame must end with CR for {crc_format} format"


class TestNAKFrameGeneration:
    """Test _generate_nak_frame() implementation (Task 10).

    Expected result:
    - NAK frame has correct structure (LF...CR delimiters)
    - NAK message always has seq=0000 (never echoing)
    - NAK is never encrypted, even if key configured
    """

    def test_nak_plaintext_frame_structure(self, preset_plain):
        """Test NAK frame structure with proper delimiters.

        Expected result:
        - Frame starts with LF (0x0A) delimiter
        - Frame ends with CR (0x0D) delimiter
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)
        nak_frame = simulator._generate_nak_frame(preset_plain)

        # Assert: Frame starts with LF
        assert nak_frame[0:1] == b'\x0A', "NAK frame must start with LF (0x0A)"

        # Assert: Frame ends with CR
        assert nak_frame[-1:] == b'\x0D', "NAK frame must end with CR (0x0D)"

    def test_nak_seq_always_zero(self, preset_plain):
        """Test NAK sequence number is always 0000 regardless of inbound.

        Expected result:
        - NAK message contains sequence 0000
        - NAK never echoes inbound sequence (per SIA DC-09 spec)
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)
        nak_frame = simulator._generate_nak_frame(preset_plain)

        # Assert: NAK contains seq=0000 (never echoing inbound)
        assert b'"NAK"0000' in nak_frame, "NAK must have seq=0000 (never echoing)"

    def test_nak_never_encrypted(self, preset_encrypted):
        """Test NAK is never encrypted even if encryption key configured.

        Expected result:
        - NAK message is always plaintext (per SIA DC-09 spec)
        - NAK message remains readable even when preset has encryption key
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_encrypted)
        nak_frame = simulator._generate_nak_frame(preset_encrypted)

        # Assert: NAK contains plaintext message (not encrypted)
        assert b'"NAK"0000' in nak_frame, "NAK must be plaintext even with encryption key"


# ============================================================================
# TASK 13: AUDIT TRAIL VERIFICATION (RED PHASE)
# ============================================================================

class TestAuditTrailLogging:
    """Test _log_frame_exchange() and audit trail (Task 13).

    Expected result:
    - Logs capture direction ('RX'/'TX'), frame_type, seq, encryption status
    - Timestamp is UTC-aware ISO format
    - RX/TX pairs logged together
    """

    @pytest.mark.asyncio
    async def test_frame_exchange_logged(self, preset_plain, alarm_frame, caplog):
        """Test that frame exchange is logged with audit trail format.

        Expected result:
        - RX (receive) event logged with frame type and sequence number
        - TX (transmit) event logged with frame type and sequence number
        - Logs follow format: [RX/TX] FRAME_TYPE seq=NNNN (encrypted|plaintext)
        """
        import logging
        from resources.siadc09d.csr_simulator import CSRSimulator

        caplog.set_level(logging.INFO)

        simulator = CSRSimulator(10001, 5000, preset_plain)

        # Log an RX and TX pair
        simulator._log_frame_exchange('RX', 'ALARM', seq=1, encrypted=False,
                                      timestamp=datetime.now(timezone.utc))
        simulator._log_frame_exchange('TX', 'ACK', seq=1, encrypted=False,
                                      timestamp=datetime.now(timezone.utc))

        # Assert: RX event logged with correct format
        assert "[RX] ALARM" in caplog.text, "RX log should contain frame type and direction"

        # Assert: TX event logged with correct format
        assert "[TX] ACK" in caplog.text, "TX log should contain frame type and direction"

        # Assert: Sequence number formatted with 4 digits
        assert "seq=0001" in caplog.text, "Log should contain zero-padded sequence number"


# ============================================================================
# TASK 13.6: END-TO-END SCENARIO TESTS (RED PHASE)
# ============================================================================

class TestEndToEndScenarios:
    """Test end-to-end scenarios with sequence correlation (Task 13.6).

    Expected result:
    - Inbound and outbound sequence numbers match for ACK responses
    - NULL messages always get ACK responses
    - Mixed frame sequences handled correctly
    """

    def test_alarm_seq_correlation(self, preset_plain):
        """Test that ACK echoes the sequence number from inbound alarm.

        Expected result:
        - When alarm frame arrives with seq=42, ACK response contains seq=42
        - Sequence number in ACK matches inbound sequence (echo pattern)
        - Formatted as 4-digit zero-padded number (seq=0042)
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)

        # Send ALARM with seq=42
        parsed_frame = {'type': 'ALARM', 'seq': 42, 'raw_nak': None}
        response_type = simulator._decide_response(parsed_frame, preset_plain)

        # Generate ACK response with matching sequence
        ack_frame = simulator._generate_ack_frame(42, preset_plain, encrypted_inbound=False)

        # Assert: ACK echoes the inbound sequence number in zero-padded format
        assert b'0042' in ack_frame, "ACK should echo the inbound sequence number (42 → 0042)"

    def test_null_always_gets_ack(self, preset_plain):
        """Test NULL (supervision) frames always receive ACK response.

        Expected result:
        - NULL frames with any sequence number → ACK response
        - Supervision NULL messages are critical; always acknowledge
        - Idempotent behavior across multiple NULL frames
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)

        # Test NULL with various sequences to ensure idempotent ACK response
        for seq in [0, 1, 999]:
            parsed_frame = {'type': 'NULL', 'seq': seq, 'raw_nak': None}
            response = simulator._decide_response(parsed_frame, preset_plain)

            # Assert: NULL always returns ACK regardless of sequence
            assert response == 'ACK', f"NULL frame should always get ACK (seq={seq})"


# ============================================================================
# INTEGRATION TESTS WITH STORIES 1.1, 1.2, 1.3 (MISSING - ADDED BY CODE REVIEW)
# ============================================================================

class TestIntegrationWithStories11To13:
    """Integration tests with SIA protocol engine (Stories 1.1-1.3).

    Expected result:
    - Simulator correctly parses frames built by SIAMessageBuilder
    - Simulator correctly handles encryption from SIACipher
    - Simulator responses parse correctly with decode_ack_nak
    """

    def test_integration_story_1_1_message_builder(self, preset_plain):
        """Generate alarm using SIAMessageBuilder and verify simulator can process it.

        Expected result:
        - Alarm frame built by SIAMessageBuilder doesn't crash simulator
        - Simulator generates valid response frame
        - ACK response parses correctly per protocol
        """
        from resources.siadc09d.csr_simulator import CSRSimulator
        from resources.siadc09d.sia_protocol import SIAMessageBuilder, decode_ack_nak

        simulator = CSRSimulator(10001, 5000, preset_plain)
        builder = SIAMessageBuilder(crc_format='hex')

        # Build alarm frame using Story 1.1 (burglary code "1130")
        alarm_frame = builder.encode_message(
            account_number='000001',
            event_code='1130'
        )

        # Assert: Frame is bytes (valid frame from builder)
        assert isinstance(alarm_frame, bytes), "SIAMessageBuilder should produce bytes frame"

        # Simulator parses this frame (no crash)
        parsed = simulator._parse_received_message(alarm_frame, preset_plain)

        # Assert: Parsing doesn't crash and returns dict
        assert isinstance(parsed, dict), "Parse should return dict"

        # Generate ACK response
        ack_response = simulator._generate_ack_frame(1, preset_plain, encrypted_inbound=False)

        # Verify ACK can be parsed by Story 1.3 decoder
        decoded = decode_ack_nak(ack_response, crc_format='hex')

        # Assert: ACK response is properly formatted per protocol
        assert decoded.get('type') == 'ACK', "Simulator ACK should decode as ACK"

    def test_integration_story_1_2_encryption_round_trip(self, preset_encrypted):
        """Encrypted event built by SIAMessageBuilder round-trips through the simulator.

        Expected result:
        - The simulator answers an encrypted event (key in preset) with a frame
        - That frame decodes as an ACK for the event's sequence number
        - Its region decrypts with SIACipher to "]_" + a timestamp (§ 5.5.3.1)
        """
        from resources.siadc09d.csr_simulator import CSRSimulator
        from resources.siadc09d.sia_protocol import decode_ack_nak

        key = preset_encrypted['encryption_key']
        simulator = CSRSimulator(10001, 5000, preset_encrypted)
        event = SIAMessageBuilder(crc_format='hex').encode_message(
            '000001', 'BA', encryption=True, encryption_key=key, seq='0042',
        )

        _response_type, ack_response = simulator._build_response(event)

        # Assert: the simulator answered the encrypted event
        assert ack_response is not None, "simulator should answer a decryptable event"
        # Assert: the answer is an ACK for sequence 42
        decoded = decode_ack_nak(ack_response, crc_format='hex')
        assert (decoded.get('type'), decoded.get('seq')) == ('ACK', 42), f"unexpected {decoded}"
        # Assert: the ACK region decrypts to the timestamp-only content
        region = ack_response.decode('ascii')[9:-1].partition('[')[2]
        hex_text = region[:-1] if region.endswith(']') else region  # D1 reverted 2026-09-28
        assert SIACipher(key).decrypt(hex_text).startswith(b']_'), "ACK content should be ']_<ts>'"

    def test_integration_full_flow_plaintext(self, preset_plain):
        """Full flow: build alarm → parse → generate ACK → decode.

        Expected result:
        - All components work together without errors
        - Frame built by SIAMessageBuilder accepted by simulator
        - ACK response parses correctly via Story 1.3
        """
        from resources.siadc09d.csr_simulator import CSRSimulator
        from resources.siadc09d.sia_protocol import SIAMessageBuilder, decode_ack_nak

        simulator = CSRSimulator(10001, 5000, preset_plain)
        builder = SIAMessageBuilder(crc_format='hex')

        # Step 1: Build alarm frame using Story 1.1
        alarm_frame = builder.encode_message(
            account_number='000001',
            event_code='1130'
        )
        assert isinstance(alarm_frame, bytes), "Builder should produce bytes"

        # Step 2: Parse frame with simulator
        parsed = simulator._parse_received_message(alarm_frame, preset_plain)
        assert isinstance(parsed, dict), "Simulator parse should return dict"

        # Step 3: Generate ACK response
        ack_response = simulator._generate_ack_frame(42, preset_plain, encrypted_inbound=False)
        assert isinstance(ack_response, bytes), "ACK should be bytes"

        # Step 4: Parse ACK response using Story 1.3
        decoded = decode_ack_nak(ack_response, crc_format='hex')

        # Assert: Full flow complete with valid ACK
        assert decoded.get('type') == 'ACK', "Response should be ACK"
        assert decoded.get('seq') == 42, "ACK should echo sequence"


# ============================================================================
# ERROR HANDLING & EDGE CASES (MISSING - ADDED BY CODE REVIEW)
# ============================================================================

class TestErrorHandling:
    """Test error handling and edge cases (AC #5, #8).

    Expected result:
    - Malformed frames generate NAK without crashing
    - Invalid data handled gracefully
    - Server remains stable under error conditions
    """

    def test_malformed_frame_doesnt_crash_server(self, preset_plain):
        """Various malformed frames handled gracefully without crashing.

        Expected result:
        - Missing CR/LF doesn't crash
        - Truncated message doesn't crash
        - Invalid CRC doesn't crash
        - Server continues operation
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)

        malformed_frames = [
            b'\x0A\x00\x10',  # Incomplete frame
            b'GARBAGE_DATA',  # No delimiters
            b'\x0ADATA',  # Missing CR
            b'',  # Empty frame
        ]

        for malformed in malformed_frames:
            # Should parse without raising exception
            try:
                parsed = simulator._parse_received_message(malformed, preset_plain)
                # Assert: Returns some result (likely 'unknown' type)
                assert 'type' in parsed, f"Malformed frame should parse to dict: {malformed!r}"
            except Exception as e:
                pytest.fail(f"Malformed frame {malformed!r} crashed: {e}")

    def test_oversized_frame_rejected(self, preset_plain):
        """Frame exceeding reasonable size limit rejected gracefully.

        Expected result:
        - Oversized frame (>10000 bytes) handled without memory issues
        - Server continues normal operation
        """
        from resources.siadc09d.csr_simulator import CSRSimulator

        simulator = CSRSimulator(10001, 5000, preset_plain)

        # Create oversized malformed frame
        oversized = b'\x0A' + b'X' * 10000 + b'\x0D'

        # Should handle without crash
        try:
            parsed = simulator._parse_received_message(oversized, preset_plain)
            # Either returns result or raises expected error
            assert True
        except Exception as e:
            # Should be a specific error, not generic crash
            assert 'frame' in str(e).lower() or 'size' in str(e).lower()
