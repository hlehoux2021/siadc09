"""
IPC callback schema contract tests for Stories 6.3+.

Validates that the canonical schemas in tests/fixtures/ipc_schema.py are
internally consistent, that sample payloads conform to them, and that all
payloads survive JSON round-trip without data loss or type corruption.

These are pure Python validators — no running daemon or Jeedom instance required.

Reference: _bmad-output/planning-artifacts/architecture.md § Communication Patterns
Reference: _bmad-output/implementation-artifacts/6-3-json-callback-ipc-protocol.md
"""
import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.ipc_schema import (
    CALLBACK_TYPES,
    DIALOG_REQUIRED_FIELDS,
    ERROR_ENTRY_REQUIRED_FIELDS,
    REQUIRED_FIELDS,
    SAMPLE_ERROR_UPDATE,
    SAMPLE_ERROR_UPDATE_NULL_CONTEXT,
    SAMPLE_ERROR_UPDATE_RESOLVE,
    SAMPLE_INFO_UPDATE,
    SAMPLE_INFO_UPDATE_PARTIAL,
    SAMPLE_MESSAGE_CENTER,
    SAMPLE_MESSAGE_TRACE,
    SAMPLE_MESSAGE_TRACE_ALARM,
    SAMPLE_NOTIFY,
    SAMPLE_PREFETCH_RESULT_HIT,
    SAMPLE_PREFETCH_RESULT_MISS,
)

ALL_SAMPLES: list[dict] = [
    SAMPLE_INFO_UPDATE,
    SAMPLE_INFO_UPDATE_PARTIAL,
    SAMPLE_MESSAGE_CENTER,
    SAMPLE_NOTIFY,
    SAMPLE_ERROR_UPDATE,
    SAMPLE_ERROR_UPDATE_NULL_CONTEXT,
    SAMPLE_ERROR_UPDATE_RESOLVE,
    SAMPLE_MESSAGE_TRACE,
    SAMPLE_MESSAGE_TRACE_ALARM,
    SAMPLE_PREFETCH_RESULT_HIT,
    SAMPLE_PREFETCH_RESULT_MISS,
]


# ── Schema internal consistency ──────────────────────────────────────────────


def test_callback_types_list_matches_required_fields_keys() -> None:
    """
    CALLBACK_TYPES list and REQUIRED_FIELDS dict must cover exactly the same
    set of callback type identifiers.

    Expected result:
    - Every entry in CALLBACK_TYPES has a matching key in REQUIRED_FIELDS
    - No extra keys in REQUIRED_FIELDS beyond CALLBACK_TYPES
    """
    # Assert: CALLBACK_TYPES and REQUIRED_FIELDS keys are identical sets
    assert set(CALLBACK_TYPES) == set(REQUIRED_FIELDS.keys()), (
        f"CALLBACK_TYPES {CALLBACK_TYPES} does not match "
        f"REQUIRED_FIELDS keys {list(REQUIRED_FIELDS.keys())}"
    )


def test_all_required_fields_lists_are_nonempty() -> None:
    """
    Every callback type must declare at least one required field ('type' at minimum).

    Expected result:
    - No REQUIRED_FIELDS entry is an empty list
    """
    for cb_type, fields in REQUIRED_FIELDS.items():
        # Assert: each callback type has at least one required field
        assert len(fields) > 0, (
            f"REQUIRED_FIELDS['{cb_type}'] is empty — at minimum 'type' is required"
        )


def test_every_required_fields_list_includes_type() -> None:
    """
    The 'type' field is the routing discriminator for all callbacks. Every
    callback type must include it as a required field.

    Expected result:
    - 'type' appears in every REQUIRED_FIELDS entry
    """
    for cb_type, fields in REQUIRED_FIELDS.items():
        # Assert: 'type' is always a required field
        assert "type" in fields, (
            f"REQUIRED_FIELDS['{cb_type}'] missing 'type' — "
            "all callbacks must include the routing discriminator"
        )


# ── info_update schema ───────────────────────────────────────────────────────


def test_info_update_schema_valid_full() -> None:
    """
    A full info_update payload with all 4 state fields is valid.

    Expected result:
    - All required fields present
    - supervision_state and event_state are int
    - supervision_label and event_label are str
    """
    payload = SAMPLE_INFO_UPDATE
    for field in REQUIRED_FIELDS["info_update"]:
        # Assert: each required field present
        assert field in payload, f"Missing required field '{field}' in info_update"
    # Assert: numeric fields are int
    assert isinstance(payload["supervision_state"], int)
    assert isinstance(payload["event_state"], int)
    # Assert: label fields are str
    assert isinstance(payload["supervision_label"], str)
    assert isinstance(payload["event_label"], str)


def test_info_update_schema_partial() -> None:
    """
    A partial info_update with only supervision fields is valid — event fields
    may be absent since only present fields trigger checkAndUpdateCmd().

    Expected result:
    - Required fields present (just 'type')
    - Supervision fields present, event fields absent
    """
    payload = SAMPLE_INFO_UPDATE_PARTIAL
    for field in REQUIRED_FIELDS["info_update"]:
        # Assert: required fields present
        assert field in payload, f"Missing required field '{field}'"
    # Assert: partial — event fields absent
    assert "event_state" not in payload
    assert "event_label" not in payload
    # Assert: supervision fields present
    assert "supervision_state" in payload
    assert "supervision_label" in payload


# ── message_center schema ────────────────────────────────────────────────────


def test_message_center_required_fields() -> None:
    """
    message_center requires type, message, and logical_id. Missing logical_id
    would break Jeedom's dedup counter.

    Expected result:
    - All 3 required fields present in sample
    - A payload missing logical_id fails validation
    """
    payload = SAMPLE_MESSAGE_CENTER
    for field in REQUIRED_FIELDS["message_center"]:
        # Assert: all required fields present
        assert field in payload, f"Missing required field '{field}'"
    # Assert: missing logical_id is detectable
    incomplete = {k: v for k, v in payload.items() if k != "logical_id"}
    missing = [f for f in REQUIRED_FIELDS["message_center"] if f not in incomplete]
    assert "logical_id" in missing, "Should detect missing logical_id"


# ── notify schema ────────────────────────────────────────────────────────────


def test_notify_required_fields() -> None:
    """
    notify requires type, title, and message for the execCmd call.

    Expected result:
    - All 3 required fields present in sample
    - Missing title or message is detectable
    """
    payload = SAMPLE_NOTIFY
    for field in REQUIRED_FIELDS["notify"]:
        # Assert: all required fields present
        assert field in payload, f"Missing required field '{field}'"
    # Assert: missing title is detectable
    no_title = {k: v for k, v in payload.items() if k != "title"}
    assert "title" not in no_title
    # Assert: missing message is detectable
    no_msg = {k: v for k, v in payload.items() if k != "message"}
    assert "message" not in no_msg


# ── error_update schema ──────────────────────────────────────────────────────


def test_error_update_all_five_fields_mandatory() -> None:
    """
    When error_update includes a new error entry (has 'code' field), all 5
    error entry fields must be present: code, message, timestamp, context, count.

    Expected result:
    - SAMPLE_ERROR_UPDATE contains all 5 error entry fields
    - Each field has the correct type
    """
    payload = SAMPLE_ERROR_UPDATE
    for field in ERROR_ENTRY_REQUIRED_FIELDS:
        # Assert: each error entry field is present
        assert field in payload, (
            f"Missing error entry field '{field}' in error_update payload"
        )
    # Assert: correct types
    assert isinstance(payload["code"], str)
    assert isinstance(payload["message"], str)
    assert isinstance(payload["timestamp"], str)
    assert isinstance(payload["count"], int)
    # Assert: context is dict or None
    assert payload["context"] is None or isinstance(payload["context"], dict)


def test_error_update_resolve_t1_payload() -> None:
    """
    A resolve-only error_update has resolve_t1 flag but no error entry fields.
    This is valid — it only clears T1 entries.

    Expected result:
    - resolve_t1 is present and is int (not bool)
    - Error entry fields (code, message, etc.) are absent
    """
    payload = SAMPLE_ERROR_UPDATE_RESOLVE
    # Assert: resolve flag present as int
    assert "resolve_t1" in payload
    assert isinstance(payload["resolve_t1"], int), (
        f"resolve_t1 should be int (0/1), got {type(payload['resolve_t1']).__name__}"
    )
    # Assert: no error entry fields (this is a resolve-only payload)
    assert "code" not in payload


# ── message_trace schema ─────────────────────────────────────────────────────


def test_message_trace_dialog_structure() -> None:
    """
    message_trace must contain a 'dialog' dict with at least 'dialog_type'
    and 'routine' fields for PHP routing (routine replacement vs prepend).

    Expected result:
    - 'dialog' key present and is a dict
    - dialog contains dialog_type (str) and routine (int)
    """
    payload = SAMPLE_MESSAGE_TRACE
    # Assert: dialog field present
    assert "dialog" in payload
    assert isinstance(payload["dialog"], dict)
    dialog = payload["dialog"]
    for field in DIALOG_REQUIRED_FIELDS:
        # Assert: each dialog required field present
        assert field in dialog, f"Missing dialog field '{field}'"
    # Assert: correct types
    assert isinstance(dialog["dialog_type"], str)
    assert isinstance(dialog["routine"], int)


def test_message_trace_alarm_is_non_routine() -> None:
    """
    An alarm dialog has routine=0, meaning it gets prepended (not replaced).

    Expected result:
    - routine field is 0 (not a routine supervision entry)
    - dialog_type is 'alarm'
    """
    dialog = SAMPLE_MESSAGE_TRACE_ALARM["dialog"]
    # Assert: alarm dialogs are non-routine
    assert dialog["routine"] == 0
    # Assert: dialog type identifies as alarm
    assert dialog["dialog_type"] == "alarm"


# ── Cross-cutting contract tests ─────────────────────────────────────────────


def test_all_payloads_json_round_trip() -> None:
    """
    All sample payloads must survive JSON serialization and deserialization
    without data loss. This catches non-serializable types.

    Expected result:
    - json.dumps() + json.loads() produces an identical payload for each sample
    """
    for i, payload in enumerate(ALL_SAMPLES):
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        # Assert: round-trip preserves all data
        assert deserialized == payload, (
            f"JSON round-trip failed for sample {i}: {payload}"
        )


def _contains_none_value(obj: object) -> bool:
    """Recursively check if any dict value is None."""
    if isinstance(obj, dict):
        for v in obj.values():
            if v is None:
                return True
            if _contains_none_value(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _contains_none_value(item):
                return True
    return False


def test_no_none_values_in_non_context_fields() -> None:
    """
    Architecture mandate: no None values in payloads — omit absent fields entirely.
    Exception: 'context' field in error_update is explicitly nullable.

    Expected result:
    - No None values in any sample except the 'context' field of error_update
    """
    for i, payload in enumerate(ALL_SAMPLES):
        for key, value in payload.items():
            if key == "context":
                continue
            # Assert: no None values outside of 'context'
            assert not _contains_none_value(value), (
                f"Sample {i} field '{key}' contains None — "
                "architecture mandates omitting absent fields"
            )


def test_no_boolean_values_use_integers() -> None:
    """
    Architecture mandate: no Python bool values in IPC payloads.
    Use integers 0/1 for boolean-like values instead.

    Expected result:
    - No field value is of type bool in any sample payload
    """
    def _check_no_booleans(obj: object, path: str) -> None:
        if isinstance(obj, bool):
            raise AssertionError(
                f"Boolean found at {path} — use int 0/1 instead"
            )
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _check_no_booleans(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                _check_no_booleans(item, f"{path}[{idx}]")

    for i, payload in enumerate(ALL_SAMPLES):
        # Assert: no boolean values anywhere in the payload tree
        _check_no_booleans(payload, f"sample[{i}]")


def test_error_update_null_context_round_trip() -> None:
    """
    error_update with context=None must survive JSON round-trip. JSON encodes
    None as null, which must decode back to None — not be silently dropped.

    Expected result:
    - json.dumps() + json.loads() preserves the null context field
    - The 'context' key is still present after deserialization (not omitted)
    """
    payload = SAMPLE_ERROR_UPDATE_NULL_CONTEXT
    serialized = json.dumps(payload)
    deserialized = json.loads(serialized)
    # Assert: context key survives round-trip
    assert "context" in deserialized, (
        "context field was dropped during JSON round-trip — "
        "null context must be preserved, not omitted"
    )
    # Assert: context value is None after round-trip
    assert deserialized["context"] is None, (
        f"context should be None after round-trip, got {deserialized['context']}"
    )


def test_each_callback_type_has_at_least_one_sample() -> None:
    """
    Every callback type in CALLBACK_TYPES must have at least one sample
    payload in ALL_SAMPLES. This prevents adding a new type to the schema
    without providing test data.

    Expected result:
    - For each type in CALLBACK_TYPES, at least one sample has that type value
    """
    covered_types = {p["type"] for p in ALL_SAMPLES}
    for cb_type in CALLBACK_TYPES:
        # Assert: each callback type has at least one sample
        assert cb_type in covered_types, (
            f"Callback type '{cb_type}' has no sample payload in ALL_SAMPLES — "
            "add a SAMPLE_* constant to ipc_schema.py"
        )


def test_all_samples_have_type_field() -> None:
    """
    Every callback payload must include a 'type' field at the top level.
    This is the routing discriminator for PHP's switch statement.

    Expected result:
    - Every sample in ALL_SAMPLES has a 'type' key
    - The type value is one of CALLBACK_TYPES
    """
    for i, payload in enumerate(ALL_SAMPLES):
        # Assert: type field exists
        assert "type" in payload, f"Sample {i} missing 'type' field"
        # Assert: type value is a known callback type
        assert payload["type"] in CALLBACK_TYPES, (
            f"Sample {i} type '{payload['type']}' not in CALLBACK_TYPES"
        )


# ── Story 6.4 — info_update partial and zero-value contract ────────────────


def test_info_update_partial_payload_valid() -> None:
    """
    The daemon may send partial info_update payloads containing only supervision
    fields (when SM1 transitions) or only event fields (when SM2 transitions).
    Both partial forms must be valid per the IPC contract.

    Expected result:
    - Payload with only supervision_state + supervision_label is valid
    - Payload with only event_state + event_label is valid
    - Neither partial payload is rejected by the schema
    """
    supervision_only = {
        "type": "info_update",
        "supervision_state": 2,
        "supervision_label": "Connexion OK",
    }
    event_only = {
        "type": "info_update",
        "event_state": 1,
        "event_label": "Intrusion (zone 3) : Confirmée par la centrale",
    }
    # Assert: supervision-only partial update has type and supervision fields
    assert supervision_only["type"] == "info_update"
    assert "supervision_state" in supervision_only
    # Assert: event fields absent in supervision-only update
    assert "event_state" not in supervision_only

    # Assert: event-only partial update has type and event fields
    assert event_only["type"] == "info_update"
    assert "event_state" in event_only
    # Assert: supervision fields absent in event-only update
    assert "supervision_state" not in event_only

    # Assert: both survive JSON round-trip cleanly
    assert json.loads(json.dumps(supervision_only)) == supervision_only
    assert json.loads(json.dumps(event_only)) == event_only


def test_info_update_zero_values_not_dropped() -> None:
    """
    supervision_state=0 and event_state=0 must not be dropped by JSON serialization
    or by PHP's empty() check. Zero is a valid and meaningful value:
    - supervision_state=0 means 'problem' (red badge)
    - event_state=0 means 'no alarm since daemon start'

    Expected result:
    - Zero integer values survive JSON round-trip
    - The value 0 is present (not None, not omitted)
    """
    payload = {
        "type": "info_update",
        "supervision_state": 0,
        "supervision_label": "Problème",
        "event_state": 0,
        "event_label": "Inactif",
    }
    roundtripped = json.loads(json.dumps(payload))
    # Assert: zero values survive round-trip (supervision_state=0 means problem)
    assert roundtripped["supervision_state"] == 0, (
        "supervision_state=0 must not be dropped (means 'problem' — red badge)"
    )
    # Assert: event_state=0 survives (means no alarm since start)
    assert roundtripped["event_state"] == 0, (
        "event_state=0 must not be dropped (means 'no alarm since start')"
    )
    # Assert: values are present, not None
    assert payload["supervision_state"] is not None, (
        "Zero must not be None — PHP isset(0) is true, empty(0) would fail"
    )


# ── prefetch_result schema (Story 14-2, ADR-17 Amendment 3; extended by 14-4) ───


def test_prefetch_result_required_fields() -> None:
    """
    prefetch_result requires type, camera_eqlogic_id, found, event_id, clip_found (Story
    14-3), and rank/run_id (Story 14-4, ADR-17 Amendment 4) — PHP's _handlePrefetchResult()
    keys its per-camera cache entry and applies its run_id/rank monotonic replace rule on
    every message.

    Expected result:
    - All 7 required fields present in both the hit and miss samples
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        for field in REQUIRED_FIELDS["prefetch_result"]:
            # Assert: all required fields present
            assert field in payload, f"Missing required field '{field}' in {payload}"


def test_prefetch_result_found_is_always_int_never_bool() -> None:
    """
    _send_callback() (daemon.py) drops any payload containing a Python bool value —
    "found" must always be sent as int 0/1, on both a hit and a miss.

    Expected result:
    - found is exactly int, never bool, in both samples
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        # Assert: strict int check — `isinstance(True, int)` is True in Python, so this
        # must reject bool explicitly, not just check isinstance(..., int)
        assert type(payload["found"]) is int, f"found must be int, not bool: {payload}"
    assert SAMPLE_PREFETCH_RESULT_HIT["found"] == 1
    assert SAMPLE_PREFETCH_RESULT_MISS["found"] == 0


def test_prefetch_result_clip_found_is_always_int_never_bool() -> None:
    """
    Story 14-3 (AC1): "clip_found" follows the exact same int-not-bool convention as
    "found" — _send_callback() drops the entire payload if any value is a Python bool.

    Expected result:
    - clip_found is exactly int, never bool, in both samples
    - hit sample has clip_found=1, miss sample has clip_found=0
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        # Assert: strict int check, same reasoning as the "found" field above
        assert type(payload["clip_found"]) is int, f"clip_found must be int, not bool: {payload}"
    assert SAMPLE_PREFETCH_RESULT_HIT["clip_found"] == 1
    assert SAMPLE_PREFETCH_RESULT_MISS["clip_found"] == 0


def test_prefetch_result_miss_still_carries_event_id_key() -> None:
    """
    AC5: a miss must still be an explicit, present message (event_id="") — never an
    omitted key — so PHP always overwrites the per-camera cache entry and never keeps
    a stale hit from an earlier, unrelated trigger on the same camera.

    Expected result:
    - SAMPLE_PREFETCH_RESULT_MISS has event_id present as an empty string, not omitted
    """
    # Assert: event_id key is present (not omitted) even on a miss
    assert "event_id" in SAMPLE_PREFETCH_RESULT_MISS
    # Assert: empty string, the daemon's explicit "no event" sentinel
    assert SAMPLE_PREFETCH_RESULT_MISS["event_id"] == ""


def test_prefetch_result_survives_json_roundtrip() -> None:
    """
    Expected result:
    - both samples survive JSON round-trip without data loss or type corruption
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        roundtripped = json.loads(json.dumps(payload))
        # Assert: exact equality after round-trip
        assert roundtripped == payload
        # Assert: found survives as int, not coerced to bool/string
        assert type(roundtripped["found"]) is int


def test_prefetch_result_rank_is_always_int_never_bool() -> None:
    """
    Story 14-4 (ADR-17 Amendment 4): "rank" (1=person/2=other/3=manual/4=none) follows the
    same int-not-bool convention as "found"/"clip_found".

    Expected result:
    - rank is exactly int, never bool, in both samples
    - hit sample has rank=1 (person), miss sample has rank=4 (none)
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        # Assert: strict int check, same reasoning as the "found" field above
        assert type(payload["rank"]) is int, f"rank must be int, not bool: {payload}"
    assert SAMPLE_PREFETCH_RESULT_HIT["rank"] == 1
    assert SAMPLE_PREFETCH_RESULT_MISS["rank"] == 4


def test_prefetch_result_run_id_is_a_nonempty_string() -> None:
    """
    Story 14-4: "run_id" is the numeric string PHP generated (microtime(true)) and owns —
    the daemon only ever echoes it back verbatim, never generates or parses it itself.

    Expected result:
    - run_id is a non-empty str in both samples, present even on a miss (same "never
      omitted" convention as event_id)
    """
    for payload in (SAMPLE_PREFETCH_RESULT_HIT, SAMPLE_PREFETCH_RESULT_MISS):
        # Assert: run_id is a non-empty string, never omitted
        assert isinstance(payload["run_id"], str) and payload["run_id"], (
            f"run_id must be a non-empty str: {payload}"
        )
