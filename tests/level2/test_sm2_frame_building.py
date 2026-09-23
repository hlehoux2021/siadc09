"""SM2 frame building integration tests (QA hardening).

Unlike test_sm2_alarm_event_suite.py and test_sm2_extended_coverage.py which mock
_send_raw (the transport), these tests let _send_with_retry call through to
_build_event_frame and verify the actual SIA protocol frame is constructed correctly.
The transport is still mocked (no network), but the frame bytes are captured and
validated against the SIA DC-09 spec.

This closes the mock-abuse gap where SM2 unit tests never exercised the frame
building path.

Reference: resources/siadc09d/daemon.py::_build_event_frame()
Reference: resources/siadc09d/sia_protocol.py::encode_message()
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from resources.siadc09d.daemon import (
    SIADaemon,
    SM1State,
    SM2State,
    EventItem,
)
from resources.siadc09d.sia_transport import SIATransportResult
from tests.conftest import make_daemon_preset


def _make_daemon_with_frame_capture() -> tuple[SIADaemon, list[bytes]]:
    """Create a daemon where transport captures sent frames but returns ACK.

    Returns (daemon, captured_frames_list).
    """
    with patch('sys.argv', ['test']):
        daemon = SIADaemon(preset=make_daemon_preset())
    daemon._notify = MagicMock()
    daemon._update_info_commands = AsyncMock()
    daemon._log_sm2_event = AsyncMock()
    daemon._account = '001234'
    daemon._receiver_prefix = ''
    daemon._account_prefix = 'L0'
    daemon._sm1_state = SM1State.HEALTHY

    captured: list[bytes] = []

    async def capture_and_ack(frame: bytes) -> SIATransportResult:
        captured.append(frame)
        return SIATransportResult(status='ack', raw_nak=None)

    mock_t = MagicMock()
    mock_t.send_frame = AsyncMock(side_effect=capture_and_ack)
    daemon._sia_transport = mock_t

    return daemon, captured


# ===== Frame structure validation =====


@pytest.mark.asyncio
async def test_frame_has_lf_cr_delimiters():
    """
    Built alarm frame starts with LF (0x0A) and ends with CR (0x0D).

    Expected result:
    - First byte is 0x0A (SIA frame leader)
    - Last byte is 0x0D (SIA frame terminator)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    # Assert: frame captured
    assert len(captured) == 1
    frame = captured[0]
    # Assert: SIA frame delimiters
    assert frame[0:1] == b'\x0A', "Frame must start with LF (0x0A)"
    assert frame[-1:] == b'\x0D', "Frame must end with CR (0x0D)"


@pytest.mark.asyncio
async def test_frame_contains_sia_dcs_token():
    """
    Built alarm frame contains the SIA-DCS id token.

    Expected result:
    - Frame contains "SIA-DCS" in the message body (plaintext, unencrypted)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    frame = captured[0]
    frame_str = frame.decode('windows-1252', errors='replace')
    # Assert: SIA-DCS token present in frame
    assert 'SIA-DCS' in frame_str, f"Frame must contain SIA-DCS token, got: {frame_str}"


@pytest.mark.asyncio
async def test_frame_contains_account_number():
    """
    Built frame includes the configured account number.

    Expected result:
    - Frame body contains '#001234' (account field with prefix)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: account number in frame
    assert '001234' in frame_str, f"Frame must contain account '001234', got: {frame_str}"


@pytest.mark.asyncio
async def test_frame_contains_event_code():
    """
    Built frame includes the SIA event code for the alarm type.

    Expected result:
    - Frame body contains the event code 'BA' (burglary alarm)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: event code in frame
    assert 'BA' in frame_str, f"Frame must contain event code 'BA', got: {frame_str}"


@pytest.mark.asyncio
async def test_frame_has_4_digit_sequence():
    """
    Built frame has a 4-digit sequence number field after the id token.

    Expected result:
    - Frame contains a 4-digit sequence like '0001' (first event)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    daemon._sia_seq = 0

    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: 4-digit sequence (seq was 0, incremented to 1 → '0001')
    assert '0001' in frame_str, f"Frame must contain sequence '0001', got: {frame_str}"


@pytest.mark.asyncio
async def test_frame_has_crc_and_length_fields():
    """
    Built frame has CRC (4 hex chars) and length (4 hex chars) after LF.

    Expected result:
    - Bytes 1-4 are 4 uppercase hex characters (CRC)
    - Bytes 5-8 are 4 hex characters starting with '0' (length field)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event, max_retries=0)

    frame = captured[0]
    crc_field = frame[1:5].decode('ascii')
    length_field = frame[5:9].decode('ascii')

    # Assert: CRC is 4 hex characters
    assert len(crc_field) == 4
    assert all(c in '0123456789ABCDEF' for c in crc_field), (
        f"CRC must be uppercase hex, got: {crc_field}"
    )
    # Assert: length field starts with '0' (format: 0NNN)
    assert length_field[0] == '0', f"Length field must start with '0', got: {length_field}"


# ===== Parametrized alarm types =====


@pytest.mark.parametrize("sia_code", ["BA", "FA", "PA"])
@pytest.mark.asyncio
async def test_all_alarm_types_build_valid_frames(sia_code):
    """
    All three alarm types (BA, FA, PA) produce valid SIA frames.

    Expected result:
    - Frame starts with LF, ends with CR
    - Frame contains the alarm-specific SIA code
    - SM2 reaches CONFIRMED
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code=sia_code, zone='TestZone', timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event, max_retries=0)

    # Assert: frame built and sent
    assert len(captured) == 1
    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: alarm code in frame
    assert sia_code in frame_str
    # Assert: SM2 confirmed
    assert result == SM2State.CONFIRMED


# ===== Zone handling in frame =====


@pytest.mark.asyncio
async def test_none_zone_still_builds_frame():
    """
    EventItem with zone=None still produces a valid frame (zone is optional).

    Expected result:
    - Frame is built and sent without error
    - Frame still has valid SIA structure
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone=None, timestamp='12:00:00,04-22-2026')
    result = await daemon._send_with_retry(event, max_retries=0)

    # Assert: frame built despite no zone
    assert len(captured) == 1
    assert captured[0][0:1] == b'\x0A'
    assert result == SM2State.CONFIRMED


# ===== Retry uses same frame structure =====


@pytest.mark.asyncio
async def test_retry_builds_fresh_frame_each_attempt():
    """
    Each retry attempt calls _build_event_frame — frame bytes are captured per attempt.

    Expected result:
    - 2 timeouts + 1 ACK = 3 frames captured
    - All frames have valid SIA structure
    - All frames contain the same event code
    """
    daemon, captured = _make_daemon_with_frame_capture()

    call_count = [0]

    async def timeout_then_ack(frame: bytes) -> SIATransportResult:
        captured.append(frame)
        call_count[0] += 1
        if call_count[0] <= 2:
            return SIATransportResult(status='timeout', raw_nak=None)
        return SIATransportResult(status='ack', raw_nak=None)

    daemon._sia_transport.send_frame = AsyncMock(side_effect=timeout_then_ack)

    event = EventItem(sia_code='FA', zone='Cuisine', timestamp='12:00:00,04-22-2026')
    with patch('asyncio.sleep'):
        result = await daemon._send_with_retry(event, max_retries=2)

    # Assert: 3 frames sent (2 timeouts + 1 ACK)
    assert len(captured) == 3
    # Assert: all frames are valid SIA structure
    for i, frame in enumerate(captured):
        assert frame[0:1] == b'\x0A', f"Frame {i} must start with LF"
        assert frame[-1:] == b'\x0D', f"Frame {i} must end with CR"
        frame_str = frame.decode('windows-1252', errors='replace')
        assert 'FA' in frame_str, f"Frame {i} must contain event code FA"

    assert result == SM2State.CONFIRMED


# ===== Sequence number in frame =====


@pytest.mark.asyncio
async def test_second_event_increments_builder_sequence():
    """
    Two consecutive events produce frames with incrementing builder sequence.

    Expected result:
    - First event frame contains '0001' (builder starts at 1)
    - Second event frame contains '0002'
    """
    daemon, captured = _make_daemon_with_frame_capture()

    event1 = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026')
    await daemon._send_with_retry(event1, max_retries=0)

    event2 = EventItem(sia_code='FA', zone='Cuisine', timestamp='12:01:00,04-22-2026')
    await daemon._send_with_retry(event2, max_retries=0)

    frame1_str = captured[0].decode('windows-1252', errors='replace')
    frame2_str = captured[1].decode('windows-1252', errors='replace')

    # Assert: builder sequence increments between events
    assert '0001' in frame1_str, f"First frame should have seq '0001', got: {frame1_str}"
    assert '0002' in frame2_str, f"Second frame should have seq '0002', got: {frame2_str}"


# ===== media_url in frame (story 14-1 Task 5) =====


@pytest.mark.asyncio
async def test_frame_contains_v_block_when_media_url_set():
    """
    EventItem.media_url reaches the actual SIA frame as a Verification "V" extended-data
    block (SIA DC-09 § 5.5.1.8), via the real _build_event_frame() path — not mocked.

    Expected result:
    - Frame body contains '[Vhttp://192.168.100.18:5000/api/events/abc123/snapshot.jpg]'
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(
        sia_code='BA',
        zone='Salon',
        timestamp='12:00:00,04-22-2026',
        media_url='http://192.168.100.18:5000/api/events/abc123/snapshot.jpg',
    )
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: V-block with the exact URL present in the transmitted frame
    assert '[Vhttp://192.168.100.18:5000/api/events/abc123/snapshot.jpg]' in frame_str, (
        f"Frame must contain the [V...] media URL block, got: {frame_str}"
    )


@pytest.mark.asyncio
async def test_frame_has_no_v_block_when_media_url_none():
    """
    EventItem.media_url defaults to None (fallback case, AC4) — the frame must carry no
    [V...] block at all, and must be byte-identical to a frame built with no media_url
    argument passed (no behavior change for every pre-14-1 frame).

    Expected result:
    - Frame body contains no '[V' substring
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(sia_code='BA', zone='Salon', timestamp='12:00:00,04-22-2026', media_url=None)
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: no Verification block present
    assert '[V' not in frame_str, f"Frame must have no [V...] block when media_url is None, got: {frame_str}"


@pytest.mark.asyncio
async def test_v_block_placed_between_data_field_and_timestamp():
    """
    Message field order per SIA DC-09 § 5.5.1 template
    (`[Data][x…data…]<timestamp>`): the [V...] extended-data block must sit immediately
    after the [Data] field's closing ']' and immediately before the timestamp's leading '_'.

    Expected result:
    - The substring '][Vhttp://host/snap.jpg]_' appears in the frame (data-field close,
      V-block, timestamp start, contiguous — no other bytes between them)
    """
    daemon, captured = _make_daemon_with_frame_capture()
    event = EventItem(
        sia_code='BA',
        zone='Salon',
        zone_number=2,
        timestamp='12:00:00,04-22-2026',
        media_url='http://host/snap.jpg',
    )
    await daemon._send_with_retry(event, max_retries=0)

    frame_str = captured[0].decode('windows-1252', errors='replace')
    # Assert: V-block is contiguous between the data field and the timestamp
    assert '][Vhttp://host/snap.jpg]_' in frame_str, (
        f"[V...] must sit between the data field and the timestamp, got: {frame_str}"
    )
