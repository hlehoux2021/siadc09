"""CSR preset configuration dataclass.

Defines the CSRPreset frozen dataclass used by the daemon to store CSR
connection parameters. Preset values are loaded from JSON config at startup
and passed to transport constructors.

Reference: internal-docs/design/daemon-design.md § CSRPreset dataclass
"""

from dataclasses import dataclass
from typing import Literal, get_args
from .sia_transport import CrcFormat, TransportType

SUPPORTED_SCHEMA_VERSION: int = 1

# Periodic keep-alive frame format (ADR-22, Story 17.1). "sia-dcs" is today's
# "SIA-DCS"…[#acct|0000] frame; "none" disables it (an RP cyclic test must then
# be active); "null" is the DC-09 NULL frame (sending behaviour lands in 17.2).
SupervisionFormat = Literal["none", "sia-dcs", "null"]
SUPERVISION_FORMATS: tuple[str, ...] = get_args(SupervisionFormat)
SUPERVISION_FORMAT_DEFAULT: SupervisionFormat = "sia-dcs"

# RP cyclic test interval bounds, in seconds, inclusive. Mirrored by
# siaDC09::RP_INTERVAL_MIN_S / RP_INTERVAL_MAX_S in core/class/siaDC09.class.php
# (deamon_info Guard 3e) — keep both sides in sync.
RP_INTERVAL_MIN_S: int = 60
RP_INTERVAL_MAX_S: int = 86400
# Mirrored by siaDC09::RP_INTERVAL_DEFAULT_S.
RP_INTERVAL_DEFAULT_S: int = 60

# Sender-side CRC formats. "bin" was removed on 2026-10-17 (Story 17.1, ADR-06
# note): the builder never encoded it. The receiver side (simulator, decoder)
# still accepts "bin" via CrcFormat.
SENDER_CRC_FORMATS: tuple[str, ...] = ("hex",)


@dataclass(frozen=True, slots=True)
class CSRPreset:
    """Central Station Receiver preset configuration.

    Frozen (immutable) dataclass — all field values are constant for the
    daemon's lifetime. Constructed from JSON preset dict in on_start().

    The `transport` field accepts a raw string from JSON config ("UDP" or "TCP")
    and converts it to TransportType in __post_init__() — this is the single
    string-to-enum conversion boundary. All code beyond CSRPreset uses
    TransportType.*, never raw strings.

    Raises:
        ValueError: If transport string is not 'UDP' or 'TCP' (via TransportType(value)).
        ValueError: If reconnect_max_attempts < 1 or reconnect_delay_s < 0.
        ValueError: On an invalid crc_format / periodic-frame combination
            (see __post_init__).
    """
    csr_provider: str
    schema_version: int
    host: str
    port: int
    account_number: str
    transport: TransportType  # type: ignore[assignment]  # __post_init__ converts str → TransportType
    crc_format: CrcFormat
    encryption_enabled: bool
    connect_timeout_s: float
    receive_timeout_s: float
    supervision_interval_s: float
    reconnect_delay_s: float = 30.0
    reconnect_max_attempts: int = 6
    # Story 17.1: stored only — the daemon does not act on them yet (17.2/17.3).
    supervision_format: SupervisionFormat = SUPERVISION_FORMAT_DEFAULT
    rp_enabled: bool = False
    rp_interval_s: float = float(RP_INTERVAL_DEFAULT_S)

    def __post_init__(self) -> None:
        """Validate and convert preset fields after initialization.

        Converts transport from raw config string to TransportType enum.
        Uses object.__setattr__ because frozen=True prevents direct assignment.

        Raises:
            ValueError: If crc_format is not 'hex' (sender side, Story 17.1).
            ValueError: If supervision_format is not one of SUPERVISION_FORMATS.
            ValueError: If supervision_format is 'none' and RP is disabled
                (no periodic frame at all).
            ValueError: If RP is enabled and rp_interval_s is outside
                [RP_INTERVAL_MIN_S, RP_INTERVAL_MAX_S]. Not checked when RP is
                disabled: a stored but unused interval must not block startup.
        """
        if not isinstance(self.transport, TransportType):
            object.__setattr__(self, 'transport', TransportType(self.transport))
        if self.crc_format not in SENDER_CRC_FORMATS:
            raise ValueError(
                f"crc_format must be one of {SENDER_CRC_FORMATS}, got {self.crc_format!r}"
            )
        if self.supervision_format not in SUPERVISION_FORMATS:
            raise ValueError(
                f"supervision_format must be one of {SUPERVISION_FORMATS}, "
                f"got {self.supervision_format!r}"
            )
        if self.supervision_format == "none" and not self.rp_enabled:
            raise ValueError(
                "supervision_format='none' requires rp_enabled=True "
                f"(no periodic frame), got rp_enabled={self.rp_enabled!r}"
            )
        if self.rp_enabled and not RP_INTERVAL_MIN_S <= self.rp_interval_s <= RP_INTERVAL_MAX_S:
            raise ValueError(
                f"rp_interval_s must be within [{RP_INTERVAL_MIN_S}, {RP_INTERVAL_MAX_S}] "
                f"when rp_enabled, got {self.rp_interval_s!r}"
            )
        if self.reconnect_max_attempts < 1:
            raise ValueError(
                f"reconnect_max_attempts must be >= 1, got {self.reconnect_max_attempts}"
            )
        if self.reconnect_delay_s < 0:
            raise ValueError(f"reconnect_delay_s must be >= 0, got {self.reconnect_delay_s}")
