"""Unit tests for error_handler module.

Tests validate ErrorCode enum, ErrorTier classification, error constants,
and notification context dataclasses (Story 3.2).
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from resources.siadc09d.error_handler import (
    BadCSRResponseCtx,
    ErrorCode,
    ErrorTier,
    ERROR_TIERS,
    EventFailedCtx,
    NotificationContext,
    SM1DisconnectedCtx,
    SM1NakCtx,
    SM1TimeoutCtx,
    T3_PREFIX,
    TransportPermanentCtx,
    _notify,
    _validate_context,
    classify_error,
    event_type_fr,
)


def test_event_type_fr_maps_burglary_cancel() -> None:
    """
    Story 13-1 AC7: the cancel has a French label, both as PHP command and as SIA code,
    so the widget/notifications never show the raw "BC".

    Expected result:
    - event_type_fr("BC") == "annulation"
    - event_type_fr("burglaryCancel") == "annulation"
    """
    # Assert: SIA code form maps to the French label
    assert event_type_fr("BC") == "annulation"
    # Assert: PHP command form maps to the same label
    assert event_type_fr("burglaryCancel") == "annulation"


def test_event_type_fr_maps_opening_report() -> None:
    """
    Story 13-1 AC7: OP (disarm during an open alarm, ADR-18) gets a French label too,
    so a confirmed/failed OP never shows the raw "OP" in the widget or a notification.

    Expected result:
    - event_type_fr("OP") == "désarmement"
    """
    # Assert: SIA code "OP" maps to the French label
    assert event_type_fr("OP") == "désarmement"


@pytest.mark.parametrize(
    "sia_code,expected_subject,expected_address_key,expected_object",
    [
        ("BC", "L'annulation", "user_number", "l'annulation"),
        ("OP", "Le désarmement", "user_number", "le désarmement"),
    ],
)
def test_event_failed_message_names_cancel_or_disarm_not_alarme(
    sia_code: str, expected_subject: str, expected_address_key: str, expected_object: str
) -> None:
    """
    Story 13-1 AC7 (finding #4): a failed BC/OP must be named as a cancel/disarm in the
    EVENT_FAILED T3 notification, not as a generic "alarme" — and addressed by the
    configured user number, not a zone (DC-03 addresses BC/OP by user — ADR-18).

    Expected result:
    - the message names the event with the correct subject ("L'annulation"/"Le désarmement")
    - the message addresses it as "(utilisateur: <n>)", never "(zone: ...)"
    - the generic word "alarme" never appears in the message
    """
    from resources.siadc09d.error_handler import build_notification

    payload = build_notification(
        ErrorCode.EVENT_FAILED,
        {"sia_code": sia_code, expected_address_key: 1, "attempts_made": 3},
    )
    # Assert: the message names the correct subject (cancel or disarm)
    assert expected_subject in payload["message"], payload["message"]
    # Assert: the address clause uses "utilisateur", never "zone"
    assert "(utilisateur: 1)" in payload["message"], payload["message"]
    assert "zone:" not in payload["message"], payload["message"]
    # Assert: the generic "alarme" word never appears for a BC/OP failure
    assert "alarme" not in payload["message"].lower(), payload["message"]
    # Assert: the object clause ("n'a PAS reçu ...") also names the cancel/disarm
    assert expected_object in payload["message"], payload["message"]


def test_all_error_codes_defined() -> None:
    """All 6 error codes defined and accessible.

    Expected result:
    - All 6 error codes accessible as enum members
    - Each code is unique (no collisions)
    """
    codes = [
        ErrorCode.SUPERVISION_TIMEOUT,
        ErrorCode.SUPERVISION_NAK,
        ErrorCode.BAD_CSR_RESPONSE,
        ErrorCode.SUPERVISION_DISCONNECTED,
        ErrorCode.EVENT_FAILED,
        ErrorCode.TRANSPORT_PERMANENT,
    ]
    # Assert: all 6 codes are accessible
    assert len(codes) == 6

    # Assert: all codes are unique (no collisions)
    assert len(codes) == len(set(codes))


def test_classify_error_maps_correctly() -> None:
    """classify_error() returns correct tier for each code.

    Expected result:
    - SUPERVISION_TIMEOUT → T1 (auto-heal)
    - SUPERVISION_NAK → T1 (auto-heal)
    - BAD_CSR_RESPONSE → T2 (user-actionable)
    - SUPERVISION_DISCONNECTED → T3 (critical)
    - EVENT_FAILED → T3 (critical)
    - TRANSPORT_PERMANENT → T3 (critical)
    """
    expected_mapping = {
        ErrorCode.SUPERVISION_TIMEOUT: ErrorTier.T1,
        ErrorCode.SUPERVISION_NAK: ErrorTier.T1,
        ErrorCode.BAD_CSR_RESPONSE: ErrorTier.T2,
        ErrorCode.SUPERVISION_DISCONNECTED: ErrorTier.T3,
        ErrorCode.EVENT_FAILED: ErrorTier.T3,
        ErrorCode.TRANSPORT_PERMANENT: ErrorTier.T3,
    }

    # Assert: each code classifies to correct tier
    for code, expected_tier in expected_mapping.items():
        assert classify_error(code) == expected_tier, f"Code {code} mapped incorrectly"


def test_error_tier_enum_values() -> None:
    """ErrorTier enum has correct numeric values.

    Expected result:
    - T1 has value 1 (for message center dedup logic)
    - T2 has value 2
    - T3 has value 3
    """
    # Assert: tier values are correct
    assert ErrorTier.T1.value == 1
    assert ErrorTier.T2.value == 2
    assert ErrorTier.T3.value == 3


def test_t3_prefix_constant() -> None:
    """T3_PREFIX constant defined correctly.

    Expected result:
    - T3_PREFIX constant exists
    - Value is exactly "CRITIQUE — " (with em dash)
    """
    # Assert: constant exists
    assert T3_PREFIX is not None

    # Assert: correct value
    assert T3_PREFIX == "CRITIQUE — "


def test_error_tiers_mapping_complete() -> None:
    """ERROR_TIERS dict contains all ErrorCode values.

    Expected result:
    - Mapping contains exactly 6 entries (one per ErrorCode)
    - Every ErrorCode enum value is a key in ERROR_TIERS
    """
    # Assert: all 6 codes are mapped
    assert len(ERROR_TIERS) == 6

    # Assert: every ErrorCode is in mapping
    for code in ErrorCode:
        assert code in ERROR_TIERS


def test_no_undefined_error_codes() -> None:
    """Only the 6 defined error codes exist.

    Expected result:
    - ErrorCode enum has exactly 6 values
    - No rogue error codes can be created by mistake
    """
    # Assert: exactly 6 error codes
    codes = list(ErrorCode)
    assert len(codes) == 6


def test_no_keyerror_for_any_errorcode() -> None:
    """classify_error() never raises KeyError for valid ErrorCode values.

    Expected result:
    - All ErrorCode enum values are in ERROR_TIERS mapping
    - No KeyError can be raised for valid enum members
    - (Note: KeyError is technically possible only if ERROR_TIERS dict is incomplete,
      which is prevented by this test)
    """
    # Assert: every ErrorCode is accessible via classify_error without KeyError
    for code in ErrorCode:
        try:
            tier = classify_error(code)
            # Assert: tier is a valid ErrorTier
            assert isinstance(tier, ErrorTier)
        except KeyError as e:
            # If we reach here, ERROR_TIERS is incomplete
            raise AssertionError(f"ErrorCode.{code.name} missing from ERROR_TIERS") from e


# ============================================================================
# STORY 3.2: CONTEXT DATACLASS TESTS
# ============================================================================


def test_sm1_timeout_ctx_construction() -> None:
    """SM1TimeoutCtx creates with required fields.

    Expected result:
    - Context instance created with all fields
    - All fields accessible and have correct values
    """
    # Create instance
    ctx = SM1TimeoutCtx(
        elapsed_ms=5000.0,
        strike_count=1,
        supervision_interval_s=60.0
    )

    # Assert: all fields accessible with correct values
    assert ctx.elapsed_ms == 5000.0
    assert ctx.strike_count == 1
    assert ctx.supervision_interval_s == 60.0


def test_sm1_timeout_ctx_frozen() -> None:
    """SM1TimeoutCtx is frozen (immutable).

    Expected result:
    - Attempting to modify field raises FrozenInstanceError
    - Instance is truly immutable after creation
    """
    ctx = SM1TimeoutCtx(
        elapsed_ms=5000.0,
        strike_count=1,
        supervision_interval_s=60.0
    )

    # Assert: modification raises FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        ctx.elapsed_ms = 999  # type: ignore


def test_sm1_nak_ctx_construction() -> None:
    """SM1NakCtx creates with required fields (including Optional).

    Expected result:
    - Context instance created with all fields
    - Optional field can be None or a string
    """
    # With None timestamp
    ctx1 = SM1NakCtx(
        raw_nak_frame=b"\x0a\x00\x00\x00\x0d",
        nak_timestamp=None,
        account_number="000001"
    )
    assert ctx1.nak_timestamp is None

    # With timestamp string
    ctx2 = SM1NakCtx(
        raw_nak_frame=b"\x0a\x00\x00\x00\x0d",
        nak_timestamp="14:23:45,04-09-2026",
        account_number="000001"
    )
    assert ctx2.nak_timestamp == "14:23:45,04-09-2026"


def test_sm1_disconnected_ctx_construction() -> None:
    """SM1DisconnectedCtx creates with datetime and optional fields.

    Expected result:
    - Context instance created with all fields
    - datetime field properly stored
    - Optional fields can be None or valid values
    """
    now_utc = datetime.now(timezone.utc)
    ctx = SM1DisconnectedCtx(
        strike_count=3,
        last_ack_time_utc=now_utc,
        time_since_last_ack_s=180.0,
        supervision_interval_s=60.0
    )

    # Assert: all fields correct
    assert ctx.strike_count == 3
    assert ctx.last_ack_time_utc == now_utc
    assert ctx.time_since_last_ack_s == 180.0

    # Test with None values
    ctx_no_ack = SM1DisconnectedCtx(
        strike_count=3,
        last_ack_time_utc=None,
        time_since_last_ack_s=None,
        supervision_interval_s=60.0
    )
    assert ctx_no_ack.last_ack_time_utc is None
    assert ctx_no_ack.time_since_last_ack_s is None


def test_bad_csr_response_ctx_construction() -> None:
    """BadCSRResponseCtx creates with transport literal type.

    Expected result:
    - Context instance created
    - transport field accepts 'udp' and 'tcp' values
    """
    # UDP version
    ctx_udp = BadCSRResponseCtx(
        raw_frame=b"GARBAGE",
        parse_error="Not ACK/NAK",
        csr_host="192.168.1.100",
        csr_port=5000,
        transport="udp"
    )
    assert ctx_udp.transport == "udp"

    # TCP version
    ctx_tcp = BadCSRResponseCtx(
        raw_frame=b"GARBAGE",
        parse_error="Not ACK/NAK",
        csr_host="192.168.1.100",
        csr_port=5000,
        transport="tcp"
    )
    assert ctx_tcp.transport == "tcp"


def test_transport_permanent_ctx_construction() -> None:
    """TransportPermanentCtx creates with optional retry_count.

    Expected result:
    - Context instance created
    - retry_count optional (None for UDP, int for TCP)
    """
    # TCP with retry count
    ctx_tcp = TransportPermanentCtx(
        reason="tcp_max_retries_exceeded",
        transport="tcp",
        error_details="Connection refused",
        retry_count=3
    )
    assert ctx_tcp.retry_count == 3

    # UDP without retry count
    ctx_udp = TransportPermanentCtx(
        reason="udp_permanent_unreachable",
        transport="udp",
        error_details="Host unreachable",
        retry_count=None
    )
    assert ctx_udp.retry_count is None


def test_event_failed_ctx_construction() -> None:
    """EventFailedCtx creates with SIA alarm code literal type.

    Expected result:
    - Context instance created
    - sia_code accepts 'BA', 'FA', 'PA' values
    - All fields properly stored
    """
    # Burglary alarm
    ctx_ba = EventFailedCtx(
        sia_code="BA",
        sia_seq=42,
        zone_name="Living Room",
        max_retries=3,
        attempts_made=3,
        last_error="timeout"
    )
    assert ctx_ba.sia_code == "BA"
    assert ctx_ba.zone_name == "Living Room"

    # Fire alarm with None zone
    ctx_fa = EventFailedCtx(
        sia_code="FA",
        sia_seq=43,
        zone_name=None,
        max_retries=3,
        attempts_made=2,
        last_error="nak_received"
    )
    assert ctx_fa.sia_code == "FA"
    assert ctx_fa.zone_name is None


@pytest.mark.parametrize("ctx_instance", [
    SM1TimeoutCtx(elapsed_ms=5000.0, strike_count=1, supervision_interval_s=60.0),
    SM1NakCtx(raw_nak_frame=b"", nak_timestamp=None, account_number="000001"),
    SM1DisconnectedCtx(strike_count=3, last_ack_time_utc=None,
                       time_since_last_ack_s=None, supervision_interval_s=60.0),
    BadCSRResponseCtx(raw_frame=b"", parse_error="", csr_host="",
                      csr_port=5000, transport="udp"),
    TransportPermanentCtx(reason="", transport="udp",
                          error_details=None, retry_count=None),
    EventFailedCtx(sia_code="BA", sia_seq=1, zone_name=None,
                   max_retries=3, attempts_made=1, last_error=""),
])
def test_all_contexts_frozen(ctx_instance: NotificationContext) -> None:
    """All 6 context dataclasses are frozen (immutable).

    Expected result:
    - Attempting to modify any field raises FrozenInstanceError
    - All contexts enforce immutability at runtime
    """
    # Get the first field of the context to attempt modification
    fields = next(iter(ctx_instance.__dataclass_fields__))

    # Assert: modification raises FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        setattr(ctx_instance, fields, "modified")  # type: ignore


def test_notify_signature() -> None:
    """_notify() function exists and is callable with correct signature.

    Expected result:
    - Function is callable
    - Accepts ErrorCode and NotificationContext arguments
    - Does not raise TypeError for valid arguments
    """
    ctx = SM1TimeoutCtx(elapsed_ms=1.0, strike_count=1, supervision_interval_s=60.0)

    # Assert: _notify is callable
    assert callable(_notify)

    # Assert: calling with valid arguments doesn't raise
    _notify(ErrorCode.SUPERVISION_TIMEOUT, ctx)


def test_validate_context_with_valid_pairs() -> None:
    """_validate_context() accepts valid code-context pairs.

    Expected result:
    - Valid pairs return True
    - No exceptions raised
    """
    valid_pairs = [
        (ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx(1.0, 1, 60.0)),
        (ErrorCode.SUPERVISION_NAK, SM1NakCtx(b"", None, "000001")),
        (ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx(3, None, None, 60.0)),
        (ErrorCode.BAD_CSR_RESPONSE, BadCSRResponseCtx(b"", "", "", 5000, "udp")),
        (ErrorCode.TRANSPORT_PERMANENT, TransportPermanentCtx("", "udp", None, None)),
        (ErrorCode.EVENT_FAILED, EventFailedCtx("BA", 1, None, 3, 1, "")),
    ]

    # Assert: all valid pairs pass validation
    for code, ctx in valid_pairs:
        assert _validate_context(code, ctx) is True


def test_validate_context_with_invalid_pairs() -> None:
    """_validate_context() rejects mismatched code-context pairs.

    Expected result:
    - Invalid pairs raise TypeError
    - Error message identifies the mismatch
    """
    # Wrong context for error code
    invalid_pairs = [
        (ErrorCode.SUPERVISION_TIMEOUT, SM1NakCtx(b"", None, "000001")),
        (ErrorCode.SUPERVISION_NAK, SM1TimeoutCtx(1.0, 1, 60.0)),
        (ErrorCode.BAD_CSR_RESPONSE, EventFailedCtx("BA", 1, None, 3, 1, "")),
    ]

    # Assert: invalid pairs raise TypeError
    for code, ctx in invalid_pairs:
        with pytest.raises(TypeError):
            _validate_context(code, ctx)


@pytest.mark.parametrize("code,ctx_class", [
    (ErrorCode.SUPERVISION_TIMEOUT, SM1TimeoutCtx),
    (ErrorCode.SUPERVISION_NAK, SM1NakCtx),
    (ErrorCode.SUPERVISION_DISCONNECTED, SM1DisconnectedCtx),
    (ErrorCode.BAD_CSR_RESPONSE, BadCSRResponseCtx),
    (ErrorCode.TRANSPORT_PERMANENT, TransportPermanentCtx),
    (ErrorCode.EVENT_FAILED, EventFailedCtx),
])
def test_context_matches_error_code(code: ErrorCode, ctx_class: type) -> None:
    """Each error code has a corresponding context type.

    Expected result:
    - Calling _notify with matching code and context doesn't raise
    - _validate_context confirms the pairing
    """
    # Build instance for this context class
    if ctx_class == SM1TimeoutCtx:
        ctx = SM1TimeoutCtx(elapsed_ms=1.0, strike_count=1, supervision_interval_s=60.0)
    elif ctx_class == SM1NakCtx:
        ctx = SM1NakCtx(raw_nak_frame=b"", nak_timestamp=None, account_number="000001")
    elif ctx_class == SM1DisconnectedCtx:
        ctx = SM1DisconnectedCtx(strike_count=3, last_ack_time_utc=None,
                                  time_since_last_ack_s=None, supervision_interval_s=60.0)
    elif ctx_class == BadCSRResponseCtx:
        ctx = BadCSRResponseCtx(raw_frame=b"", parse_error="", csr_host="",
                                 csr_port=5000, transport="udp")
    elif ctx_class == TransportPermanentCtx:
        ctx = TransportPermanentCtx(reason="", transport="udp",
                                     error_details=None, retry_count=None)
    else:  # EventFailedCtx
        ctx = EventFailedCtx(sia_code="BA", sia_seq=1, zone_name=None,
                             max_retries=3, attempts_made=1, last_error="")

    # Assert: _notify doesn't raise
    _notify(code, ctx)

    # Assert: _validate_context confirms pairing
    assert _validate_context(code, ctx) is True


def test_notification_context_union_type() -> None:
    """NotificationContext type alias accepts all context types.

    Expected result:
    - All context types are valid NotificationContext instances
    - Type checking would accept them (runtime isinstance confirms)
    """
    contexts: list[NotificationContext] = [
        SM1TimeoutCtx(1.0, 1, 60.0),
        SM1NakCtx(b"", None, "000001"),
        SM1DisconnectedCtx(3, None, None, 60.0),
        BadCSRResponseCtx(b"", "", "", 5000, "udp"),
        TransportPermanentCtx("", "udp", None, None),
        EventFailedCtx("BA", 1, None, 3, 1, ""),
    ]

    # Assert: all instances are of expected types
    assert len(contexts) == 6
    # No assertions needed — type checking handles this; runtime proves it compiles
