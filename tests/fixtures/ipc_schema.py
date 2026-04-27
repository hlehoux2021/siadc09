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
