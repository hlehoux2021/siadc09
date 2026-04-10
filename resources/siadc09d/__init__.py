"""SIA DC-09 Protocol Daemon — Python Implementation

This package contains the complete SIA DC-09-2021 protocol implementation
for the Jeedom siaDC09 plugin daemon.

Module Organization:
- error_handler.py (Story 3.1) — Error classification (ErrorCode, ErrorTier, ERROR_TIERS)
- messages.py (Story 4.1) — User-facing message strings
- sia_protocol.py (Epic 1) — Protocol message builder and encoder
- sia_crypto.py (Epic 1) — AES-128-CBC encryption and CRC-16 MODBUS
- csr_simulator.py (Epic 1) — CSR protocol simulator for testing
- daemon.py (Epic 5) — Daemon core with SM1/SM2 state machines

Module Exports:
- Public exports deferred to Story 3.4+ (keep foundation layer independent per architecture)
- Story 3.3 defines the interfaces; Story 3.4 will integrate with daemon core
"""
