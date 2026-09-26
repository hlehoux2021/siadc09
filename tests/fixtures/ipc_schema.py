# schema_version = 1
#
# Canonical IPC callback schemas for the siaDC09 daemon→PHP protocol.
# This file is the authoritative source for callback field contracts.
# Any callback shape change requires updating this file first.
"""IPC callback schema definitions for siaDC09 daemon↔PHP protocol."""
from typing import Final


# --- Callback type identifiers (exhaustive, no additions without protocol) ---

CALLBACK_TYPES: Final[list[str]] = [
    "info_update",
    "message_center",
    "notify",
    "error_update",
    "message_trace",
    "prefetch_result",
]


# --- Required fields per callback type ---

REQUIRED_FIELDS: Final[dict[str, list[str]]] = {
    # info_update: only "type" is required — all 4 data fields are optional per send.
    # Daemon may send supervision-only or event-only partial updates.
    "info_update": ["type"],
    "message_center": ["type", "message", "logical_id"],
    "notify": ["type", "title", "message"],
    "error_update": ["type"],
    "message_trace": ["type", "dialog"],
    # prefetch_result (Story 14-2, ADR-17 Amendment 3; extended by 14-3, then 14-4): "found"
    # and "clip_found" are always sent as int 0/1 (never a Python bool — _send_callback()
    # drops any payload containing one) and "event_id" is always sent, as "" on a miss.
    # Story 14-4 (ADR-17 Amendment 4) adds "rank" (int, 1=person/2=other/3=manual/4=none)
    # and "run_id" (the numeric string PHP generated and owns, echoed back verbatim) — PHP's
    # cache now replaces an entry only per the run_id/rank monotonic rule, not on every
    # callback unconditionally (superseded 14-2 AC5's "always overwrite").
    "prefetch_result": [
        "type", "camera_eqlogic_id", "found", "event_id", "clip_found", "rank", "run_id",
    ],
}

ERROR_ENTRY_REQUIRED_FIELDS: Final[list[str]] = [
    "code", "message", "timestamp", "context", "count",
]

DIALOG_REQUIRED_FIELDS: Final[list[str]] = [
    "dialog_type", "routine",
]


# --- Sample payloads for testing ---

SAMPLE_INFO_UPDATE: Final[dict] = {
    "type": "info_update",
    "supervision_state": 2,
    "supervision_label": "Opérationnel",
    "event_state": 0,
    "event_label": "Inactif",
}

SAMPLE_INFO_UPDATE_PARTIAL: Final[dict] = {
    "type": "info_update",
    "supervision_state": 1,
    "supervision_label": "Dégradé",
}

SAMPLE_MESSAGE_CENTER: Final[dict] = {
    "type": "message_center",
    "message": "Supervision perdue — 3 tentatives échouées",
    "logical_id": "SUPERVISION_DISCONNECTED",
}

SAMPLE_NOTIFY: Final[dict] = {
    "type": "notify",
    "title": "CRITIQUE — Supervision perdue",
    "message": "Le récepteur ne répond plus depuis 3 cycles de supervision.",
}

SAMPLE_ERROR_UPDATE: Final[dict] = {
    "type": "error_update",
    "code": "BAD_CSR_RESPONSE",
    "message": "Réponse CSR illisible",
    "timestamp": "2026-04-27T14:30:00+00:00",
    "context": {"raw_hex": "0A1B2C"},
    "count": 1,
}

SAMPLE_ERROR_UPDATE_NULL_CONTEXT: Final[dict] = {
    "type": "error_update",
    "code": "SUPERVISION_TIMEOUT",
    "message": "Pas de réponse du CSR",
    "timestamp": "2026-04-27T14:32:00+00:00",
    "context": None,
    "count": 1,
}

SAMPLE_ERROR_UPDATE_RESOLVE: Final[dict] = {
    "type": "error_update",
    "resolve_t1": 1,
}

SAMPLE_MESSAGE_TRACE: Final[dict] = {
    "type": "message_trace",
    "dialog": {
        "dialog_type": "supervision",
        "routine": 1,
        "timestamp": "2026-04-27T14:30:00+00:00",
        "request_hex": "0A1B2C3D",
        "response_hex": "4E5F6A7B",
        "elapsed_ms": 42,
    },
}

SAMPLE_MESSAGE_TRACE_ALARM: Final[dict] = {
    "type": "message_trace",
    "dialog": {
        "dialog_type": "alarm",
        "routine": 0,
        "timestamp": "2026-04-27T14:31:00+00:00",
        "request_hex": "AABB",
        "response_hex": "CCDD",
        "elapsed_ms": 120,
    },
}

SAMPLE_PREFETCH_RESULT_HIT: Final[dict] = {
    "type": "prefetch_result",
    "camera_eqlogic_id": 42,
    "found": 1,
    "event_id": "1790193165.543115-0e6wzj",
    "clip_found": 1,
    "rank": 1,
    "run_id": "1790193160.123456",
}

SAMPLE_PREFETCH_RESULT_MISS: Final[dict] = {
    "type": "prefetch_result",
    "camera_eqlogic_id": 42,
    "found": 0,
    "event_id": "",
    "clip_found": 0,
    "rank": 4,
    "run_id": "1790193160.123456",
}
