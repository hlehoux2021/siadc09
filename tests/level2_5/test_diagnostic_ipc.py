"""
Level 2.5 IPC contract tests for Epic 9 diagnostic data flow.

Validates that:
1. error_update callback schema (daemon → PHP) matches the sia_last_errors entry
   structure that getDiagnosticData reads.
2. message_trace callback schema (daemon → PHP) matches the sia_last_messages entry
   structure that getDiagnosticData reads.
3. Config key shapes written by PHP callbacks are consistent with what the AJAX
   reader (getDiagnosticData) expects to JSON-decode.

No running daemon or Jeedom instance required — pure Python schema validation.

Reference: internal-docs/design/debug-ui-design.md § 5c.1, 5c.2, 5c.3, 5c.4, 5c.5
Reference: _bmad-output/implementation-artifacts/9-3-diagnostic-tab-integration-testing.md
Reference: tests/fixtures/ipc_schema.py — canonical callback schemas
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.ipc_schema import (
    ERROR_ENTRY_REQUIRED_FIELDS,
    SAMPLE_ERROR_UPDATE,
    SAMPLE_ERROR_UPDATE_NULL_CONTEXT,
    SAMPLE_MESSAGE_TRACE,
    SAMPLE_MESSAGE_TRACE_ALARM,
)


# ── Task 5.1: error_update → sia_last_errors schema consistency ───────────────


class TestErrorUpdateToLastErrors:
    """
    Verify error_update callback fields match what getDiagnosticData reads from
    sia_last_errors (AC: 7 — error injected → appears in panel after Actualiser).
    """

    def test_error_update_has_all_sia_last_errors_required_fields(self) -> None:
        """
        The error_update sample must contain all fields required in a sia_last_errors
        entry so that getDiagnosticData can surface them without key-error.

        Expected result:
        - code, message, timestamp, context, count all present in SAMPLE_ERROR_UPDATE
        """
        payload = SAMPLE_ERROR_UPDATE
        for field in ERROR_ENTRY_REQUIRED_FIELDS:
            # Assert: each sia_last_errors field present in the error_update payload
            assert field in payload, (
                f"Field '{field}' missing from SAMPLE_ERROR_UPDATE — "
                "getDiagnosticData would fail to render it"
            )

    def test_error_update_code_is_string(self) -> None:
        """
        'code' field must be a string (one of the 6 ErrorCode values).
        getDiagnosticData returns it directly to JS _siaDC09_tierMap lookup.

        Expected result:
        - SAMPLE_ERROR_UPDATE['code'] is a non-empty str
        """
        code = SAMPLE_ERROR_UPDATE["code"]
        # Assert: code is a string
        assert isinstance(code, str)
        # Assert: code is non-empty
        assert len(code) > 0

    def test_error_update_code_is_known_error_code(self) -> None:
        """
        'code' value must be one of the 6 known ErrorCode values that _siaDC09_tierMap
        covers. An unknown code falls back to T1 in the JS tier map (acceptable but
        not ideal — flagged here so new codes are not silently ignored).

        Expected result:
        - SAMPLE_ERROR_UPDATE['code'] in the canonical ErrorCode set
        """
        known_codes = {
            "SUPERVISION_TIMEOUT",
            "SUPERVISION_NAK",
            "BAD_CSR_RESPONSE",
            "SUPERVISION_DISCONNECTED",
            "EVENT_FAILED",
            "TRANSPORT_PERMANENT",
        }
        code = SAMPLE_ERROR_UPDATE["code"]
        # Assert: code is a known ErrorCode value covered by the tier map
        assert code in known_codes, (
            f"'{code}' not in known ErrorCode set — JS tier map will use fallback T1"
        )

    def test_error_update_timestamp_is_iso_string(self) -> None:
        """
        'timestamp' must be an ISO 8601 string with timezone offset.
        siaDC09_formatTimestamp parses it via new Date(isoString).

        Expected result:
        - timestamp is a str containing 'T' (ISO separator) and '+' or 'Z'
        """
        ts = SAMPLE_ERROR_UPDATE["timestamp"]
        # Assert: timestamp is a string
        assert isinstance(ts, str)
        # Assert: ISO 8601 format (contains 'T' date-time separator)
        assert "T" in ts, "timestamp must be ISO 8601 with 'T' separator"
        # Assert: has timezone info ('+HH:MM', '-HH:MM', or 'Z')
        assert re.search(r'[+-]\d{2}:\d{2}$|Z$', ts) is not None, (
            "timestamp must include timezone offset for correct local time display"
        )

    def test_error_update_count_is_positive_integer(self) -> None:
        """
        'count' must be a positive integer — it drives the Jeedom occurrence counter.

        Expected result:
        - SAMPLE_ERROR_UPDATE['count'] is int > 0
        """
        count = SAMPLE_ERROR_UPDATE["count"]
        # Assert: count is an integer
        assert isinstance(count, int)
        # Assert: count is positive (0 would be meaningless)
        assert count > 0

    def test_error_update_context_is_dict_or_none(self) -> None:
        """
        'context' must be a dict or None. getDiagnosticData returns the raw context
        value — other types would break JS rendering.

        Expected result:
        - SAMPLE_ERROR_UPDATE['context'] is dict or None
        """
        ctx = SAMPLE_ERROR_UPDATE["context"]
        # Assert: context is dict or None
        assert ctx is None or isinstance(ctx, dict), (
            f"context must be dict or None, got {type(ctx).__name__}"
        )

    def test_null_context_error_update_survives_json_roundtrip(self) -> None:
        """
        error_update with context=None must survive JSON round-trip.
        PHP config::save() stores JSON — PHP config::byKey() reads it back.

        Expected result:
        - JSON encode + decode preserves context=None as null (not dropped)
        """
        payload = SAMPLE_ERROR_UPDATE_NULL_CONTEXT
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        # Assert: context key preserved after round-trip
        assert "context" in deserialized, "context key must not be dropped in round-trip"
        # Assert: context value is None
        assert deserialized["context"] is None

    def test_error_entry_matches_get_diagnostic_data_reader_shape(self) -> None:
        """
        The error_update entry shape must match what getDiagnosticData returns in
        the 'errors' array. PHP passes through the JSON as-is, so field names must
        match exactly what JS siaDC09_renderErrors expects.

        Expected result:
        - All JS-accessed fields (code, message, timestamp) are present in the payload
        """
        payload = SAMPLE_ERROR_UPDATE
        # Assert: fields JS accesses via err.code, err.message, err.timestamp present
        js_accessed_fields = ["code", "message", "timestamp"]
        for field in js_accessed_fields:
            assert field in payload, (
                f"Field '{field}' missing — JS siaDC09_renderErrors accesses err.{field}"
            )


# ── Task 5.2: message_trace → sia_last_messages schema consistency ─────────────


class TestMessageTraceToLastMessages:
    """
    Verify message_trace callback fields match what getDiagnosticData reads from
    sia_last_messages (AC: 8 — cross-panel consistency test).
    """

    def test_message_trace_dialog_has_required_fields(self) -> None:
        """
        message_trace 'dialog' sub-object must have the fields JS renderMessages reads:
        dialog_type, routine, timestamp, elapsed_ms.

        Expected result:
        - All 4 JS-accessed fields present in SAMPLE_MESSAGE_TRACE['dialog']
        """
        dialog = SAMPLE_MESSAGE_TRACE["dialog"]
        js_accessed_fields = ["dialog_type", "routine", "timestamp", "elapsed_ms"]
        for field in js_accessed_fields:
            # Assert: each JS-accessed field present in dialog object
            assert field in dialog, (
                f"Field '{field}' missing from dialog — siaDC09_renderMessages "
                f"accesses msg.{field}"
            )

    def test_message_trace_dialog_type_is_string(self) -> None:
        """
        'dialog_type' must be a string ('supervision' or 'alarm').
        JS renderMessages uses it to determine badge color and context label.

        Expected result:
        - SAMPLE_MESSAGE_TRACE['dialog']['dialog_type'] is str
        - Value is one of 'supervision' or 'alarm'
        """
        dialog_type = SAMPLE_MESSAGE_TRACE["dialog"]["dialog_type"]
        # Assert: dialog_type is a string
        assert isinstance(dialog_type, str)
        # Assert: value is a known dialog type
        assert dialog_type in ("supervision", "alarm"), (
            f"dialog_type '{dialog_type}' must be 'supervision' or 'alarm'"
        )

    def test_message_trace_routine_is_integer(self) -> None:
        """
        'routine' must be an integer (0 or 1). JS uses it for badge class selection:
        routine=1 → supervision routine, routine=0 → non-routine (alarm).

        Expected result:
        - SAMPLE_MESSAGE_TRACE['dialog']['routine'] is int in {0, 1}
        """
        routine = SAMPLE_MESSAGE_TRACE["dialog"]["routine"]
        # Assert: routine is exactly int (isinstance(True, int) is True in Python)
        assert type(routine) is int, "routine must be int 0/1, not bool or other type"
        # Assert: valid routine value
        assert routine in (0, 1)

    def test_message_trace_elapsed_ms_is_numeric(self) -> None:
        """
        'elapsed_ms' must be a numeric value (int or float).
        JS renderMessages displays it as the badge text: elapsedMs + 'ms'.

        Expected result:
        - elapsed_ms is int or float
        - elapsed_ms >= 0
        """
        elapsed = SAMPLE_MESSAGE_TRACE["dialog"]["elapsed_ms"]
        # Assert: elapsed_ms is numeric
        assert isinstance(elapsed, (int, float)), (
            f"elapsed_ms must be numeric, got {type(elapsed).__name__}"
        )
        # Assert: elapsed_ms is non-negative
        assert elapsed >= 0

    def test_alarm_dialog_is_non_routine(self) -> None:
        """
        An alarm dialog entry must have routine=0 (non-routine).
        JS renderMessages uses this to decide prepend vs replace in ring buffer.

        Expected result:
        - SAMPLE_MESSAGE_TRACE_ALARM['dialog']['routine'] == 0
        - dialog_type == 'alarm'
        """
        dialog = SAMPLE_MESSAGE_TRACE_ALARM["dialog"]
        # Assert: alarm dialogs are non-routine
        assert dialog["routine"] == 0
        # Assert: dialog_type identifies as alarm
        assert dialog["dialog_type"] == "alarm"

    def test_supervision_dialog_is_routine(self) -> None:
        """
        A supervision dialog entry must have routine=1 (routine).
        Routine supervision entries replace the previous entry in the ring buffer.

        Expected result:
        - SAMPLE_MESSAGE_TRACE['dialog']['routine'] == 1
        - dialog_type == 'supervision'
        """
        dialog = SAMPLE_MESSAGE_TRACE["dialog"]
        # Assert: supervision dialogs are routine
        assert dialog["routine"] == 1
        # Assert: dialog_type identifies as supervision
        assert dialog["dialog_type"] == "supervision"

    def test_message_trace_dialog_json_roundtrip(self) -> None:
        """
        message_trace payload must survive JSON round-trip without data loss.
        PHP stores it via config::save() as JSON; getDiagnosticData reads it back.

        Expected result:
        - json.dumps + json.loads produces identical payload
        """
        payload = SAMPLE_MESSAGE_TRACE
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        # Assert: round-trip preserves all data
        assert deserialized == payload


# ── Task 5.3: Config key format consistency ───────────────────────────────────


class TestConfigKeyFormatConsistency:
    """
    Verify the config key structure (sia_last_errors / sia_last_messages) is
    consistent between what the daemon writes and what getDiagnosticData reads (AC: 8).
    """

    def test_sia_last_errors_is_json_array_of_error_entries(self) -> None:
        """
        sia_last_errors config key holds a JSON array of error entry objects.
        getDiagnosticData JSON-decodes it and returns it as 'errors' key.

        Expected result:
        - A list of error_update-shaped dicts round-trips as JSON array
        - Array of 0 entries round-trips cleanly (clear state)
        """
        # Simulate what PHP stores after processing error_update callbacks
        entries = [
            {
                "code": SAMPLE_ERROR_UPDATE["code"],
                "message": SAMPLE_ERROR_UPDATE["message"],
                "timestamp": SAMPLE_ERROR_UPDATE["timestamp"],
                "context": SAMPLE_ERROR_UPDATE["context"],
                "count": SAMPLE_ERROR_UPDATE["count"],
            }
        ]
        # Assert: non-empty array round-trips as JSON
        encoded = json.dumps(entries)
        decoded = json.loads(encoded)
        assert decoded == entries
        # Assert: empty array (clear state) also round-trips
        empty_encoded = json.dumps([])
        empty_decoded = json.loads(empty_encoded)
        assert empty_decoded == []

    def test_sia_last_messages_is_json_array_of_dialog_entries(self) -> None:
        """
        sia_last_messages config key holds a JSON array of dialog objects.
        getDiagnosticData JSON-decodes it and returns it as 'messages' key.

        Expected result:
        - A list of message_trace dialog dicts round-trips as JSON array
        - JS siaDC09_renderMessages accesses entries directly (not nested under 'dialog')
        """
        # PHP stores the dialog sub-object directly (not the outer message_trace wrapper)
        dialog_entry = SAMPLE_MESSAGE_TRACE["dialog"]
        entries = [dialog_entry]
        # Assert: list of dialog objects round-trips
        encoded = json.dumps(entries)
        decoded = json.loads(encoded)
        assert decoded == entries
        # Assert: dialog entry has the required JS-accessed fields
        assert "dialog_type" in decoded[0]
        assert "routine" in decoded[0]
        assert "timestamp" in decoded[0]

    def test_get_diagnostic_data_errors_key_matches_error_update_shape(self) -> None:
        """
        The 'errors' array returned by getDiagnosticData must contain entries with
        the same field names that siaDC09_renderErrors accesses.

        This cross-checks the daemon error_update shape → PHP PHP config key →
        AJAX reader → JS renderer pipeline end-to-end at the schema level.

        Expected result:
        - Error entries have code, message, timestamp (JS-accessed fields)
        - No field renaming between layers
        """
        # Simulate the full pipeline: daemon emits → PHP stores → AJAX reads → JS renders
        daemon_error_update = SAMPLE_ERROR_UPDATE
        php_stored_entry = {
            k: daemon_error_update[k]
            for k in ERROR_ENTRY_REQUIRED_FIELDS
            if k in daemon_error_update
        }
        # Assert: PHP-stored entry has all fields JS renderErrors accesses
        js_render_fields = ["code", "message", "timestamp"]
        for field in js_render_fields:
            assert field in php_stored_entry, (
                f"Field '{field}' lost between daemon → PHP → JS render pipeline"
            )

    def test_get_diagnostic_data_messages_key_matches_message_trace_shape(self) -> None:
        """
        The 'messages' array returned by getDiagnosticData must contain entries with
        the same field names that siaDC09_renderMessages accesses.

        Expected result:
        - Message entries have dialog_type, routine, timestamp, elapsed_ms
        """
        # Simulate the pipeline: daemon dialog → PHP stores dialog object → AJAX returns
        dialog_entry = SAMPLE_MESSAGE_TRACE["dialog"]
        # Assert: each JS-accessed field is present in the stored dialog entry
        js_render_fields = ["dialog_type", "routine", "timestamp", "elapsed_ms"]
        for field in js_render_fields:
            assert field in dialog_entry, (
                f"Field '{field}' missing from dialog entry — "
                f"siaDC09_renderMessages accesses msg.{field}"
            )

    def test_both_config_keys_decode_to_list(self) -> None:
        """
        Both sia_last_errors and sia_last_messages store JSON arrays.
        PHP clears them with '[]' (empty array literal).
        getDiagnosticData calls json_decode(..., true) and checks is_array.

        Expected result:
        - '[]' JSON-decodes to a Python list
        - Non-empty JSON array also decodes to list
        """
        # Assert: '[]' (PHP clear value) decodes to empty list
        cleared = json.loads("[]")
        assert isinstance(cleared, list)
        assert len(cleared) == 0

        # Assert: populated array also decodes to list
        populated = json.dumps([SAMPLE_ERROR_UPDATE])
        decoded = json.loads(populated)
        assert isinstance(decoded, list)
        assert len(decoded) == 1
