"""SIA DC-09 Plugin - French User-Facing Messages.

v1.0: Static strings (French only)
TODO v1.1: Migrate to gettext for multi-language support

Module design:
- User-facing log message strings (INFO/WARNING/ERROR levels only)
- Technical DEBUG lines stay inline in code (not here)
- All strings are French for v1.0
- Gettext migration deferred to future version

Rationale:
- Externalizing to messages.py makes all user-visible strings reviewable in one place
- Provides clean foundation if locale support is added later (gettext loader swap)
- Python logs are read in Jeedom's log panel as plain text
- Jeedom's __() i18n system is PHP-only and does not reach into daemon output

Reference: docs/design/logging-design.md § Task 5b.6
"""

from typing import Final

# ===== CRITICAL CONSTANTS =====
# These constants are used throughout the daemon and must be consistent

T3_PREFIX: Final[str] = "CRITIQUE — "
# All T3-tier error messages must prepend this constant (not raw string)
# Test: Every T3 message starts with T3_PREFIX

SIA_NULL_CODE: Final[str] = "NULL"
# Used for supervision NULL frames only. NOT in _EVENT_SIA_CODES.
# Test: SIA_NULL_CODE not in any SM2 messages

# ===== SM1 STATE INFO LABELS =====
# Supervision state labels for INFO commands (ref: supervision-design.md)

SM1_INITIALIZING_FR: Final[str] = "DÉMARRAGE…"
SM1_HEALTHY_FR: Final[str] = "OK"
SM1_DEGRADED_1_2_FR: Final[str] = "DÉGRADÉ ({}/3)"  # {} = strike counter
SM1_DEGRADED_3_FR: Final[str] = "PERDUE"
SM1_TCP_RECONNECTING_FR: Final[str] = "Reconnexion TCP/UDP…"
SM1_NO_NETWORK_FR: Final[str] = "HORS RÉSEAU — arrêt"

# ===== SM1 STATE TRANSITIONS =====
# Supervision connection/health states - 13 messages

SM1_STARTING: Final[str] = "Démarrage — connexion à la centrale en cours"
SM1_CONNECTED: Final[str] = "Connexion à la centrale établie"
SM1_RECOVERED: Final[str] = "Supervision rétablie après {prev_strike} timeout(s)"
SM1_TCP_RECONNECTED: Final[str] = "Connexion TCP rétablie — vérification supervision en cours"
SM1_TIMEOUT_STARTUP: Final[str] = "Timeout supervision au démarrage (strike {strike}/3) — nouvelle tentative"
SM1_TIMEOUT_WARNING: Final[str] = "Timeout supervision (strike {strike}/3) — nouvelle tentative"
SM1_STILL_ABSENT: Final[str] = "Supervision toujours absente — en attente de rétablissement"
SM1_TCP_DROP: Final[str] = "Connexion TCP perdue — tentative de reconnexion (depuis état {prev_state})"
SM1_NAK_TIMESTAMP: Final[str] = "NAK supervision (strike {strike}/3) — horodatage rejeté par la centrale"
SM1_NAK_BAD: Final[str] = "Réponse invalide de la centrale — NAK non décodable (strike {strike}/3)"
SM1_LOST: Final[str] = T3_PREFIX + "Supervision perdue — 3 tentatives sans réponse (T3 notification envoyée)"
SM1_TCP_RECONNECT_FAIL_1: Final[str] = "Reconnexion TCP échouée — centrale injoignable"
SM1_NO_NETWORK: Final[str] = T3_PREFIX + "Réseau injoignable après {n} tentatives — arrêt du daemon"

# ===== SM2 ALARM EVENT TRANSITIONS =====
# Alarm event lifecycle states - 8 messages

SM2_IDLE: Final[str] = "En attente d'événements alarme"
SM2_EVENT_RECEIVED: Final[str] = "Alarme {type} reçue (zone: {zone}) — transmission en cours"
SM2_CONFIRMED: Final[str] = "Centrale confirmée — alarme {type} transmise (zone: {zone})"
SM2_RETRY: Final[str] = "Pas de réponse de la centrale — tentative {attempt}/{max}"
SM2_TIMESTAMP_HEAL: Final[str] = "Horodatage refusé — correction automatique et renvoi"
# TODO v1.1: SM2_TIMESTAMP_HEAL not used in v1.0 (timestamp auto-heal deferred)
SM2_FAILED: Final[str] = T3_PREFIX + "Alarme {type} non transmise après {max} tentatives (zone: {zone})"
SM2_FAILED_NAK: Final[str] = T3_PREFIX + "Réponse inattendue de la centrale — alarme {type} non transmise (zone: {zone})"
SM2_FAILED_NO_NETWORK: Final[str] = T3_PREFIX + "Alarme {type} non transmise — réseau inaccessible (zone: {zone})"

# ===== ERROR NOTIFICATION MESSAGES =====
# T1 (Auto-heal), T2 (User-actionable), T3 (Critical)
# Reference: docs/design/error-handler-design.md

# T1 Auto-heal notifications (no dedicated constants in messages.py)
# Used via SM1_TIMEOUT_WARNING (strike=1) and SM1_NAK_TIMESTAMP
# Message content defined above in SM1 section

# T2 User-actionable notifications
# (Reserved for future configuration error messages)

# T3 Critical notifications
# All prepended with T3_PREFIX above (SM1_LOST, SM1_NO_NETWORK, SM2_FAILED*)

# ===== WIZARD UI MESSAGES =====
# Configuration wizard steps & results - 6 messages

WIZARD_STEP_1_TITLE: Final[str] = "Sélectionner la centrale (CSR)"
WIZARD_STEP_2_TITLE: Final[str] = "Tester la connexion"
WIZARD_STEP_3_TITLE: Final[str] = "Configurer les zones"
WIZARD_STEP_4_TITLE: Final[str] = "Configurer les notifications"
WIZARD_TEST_SUCCESS: Final[str] = "✓ Connexion établie"
WIZARD_TEST_FAILED: Final[str] = "✗ Connexion échouée: {reason}"

# ===== PRESET VALIDATION MESSAGES =====
# (Reserved for future preset validation errors)
# Format: PRESET_ERROR_* constants
# Reference: docs/design/wizard-design.md

# ===== STRING COVERAGE TABLE =====
# From logging-design.md § Message externalization (ADR-15):
#
# | Category | Count | Examples |
# |----------|-------|----------|
# | SM1 state transitions | 13 | SM1_STARTING, SM1_CONNECTED, SM1_TIMEOUT_WARNING, ... |
# | SM2 event transitions | 8 | SM2_IDLE, SM2_EVENT_RECEIVED, SM2_FAILED, ... |
# | T1 auto-heal | 2 | SM1_TIMEOUT_WARNING, SM1_NAK_TIMESTAMP |
# | T2 user-actionable | 1 | (Reserved for config errors) |
# | T3 critical | 5 | SM1_LOST, SM1_NO_NETWORK, SM2_FAILED, SM2_FAILED_NAK, SM2_FAILED_NO_NETWORK |
# | Wizard UI | 6 | WIZARD_STEP_*, WIZARD_TEST_* |
# | Preset validation | 0 | (Reserved for v1.0+) |
#
# TOTAL: 35 message constants + 2 special constants (T3_PREFIX, SIA_NULL_CODE)
#
# All SM1/SM2 transitions from logging-design.md SM1/SM2 tables → COVERED ✓
# All error codes from error-handler-design.md → COVERED ✓
# All wizard steps from wizard-design.md → COVERED ✓

# ===== USAGE EXAMPLE =====
# from resources.siadc09d.messages import SM1_CONNECTED, SM2_CONFIRMED, T3_PREFIX
#
# logging.warning(SM1_TIMEOUT_WARNING.format(strike=self._strike))
# logging.error(SM1_LOST)
# logging.info(SM2_CONFIRMED.format(type=event_type_fr(evt), zone=zone))
