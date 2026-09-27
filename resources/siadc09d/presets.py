"""CSR preset configuration dataclass.

Defines the CSRPreset frozen dataclass used by the daemon to store CSR
connection parameters. Preset values are loaded from JSON config at startup
and passed to transport constructors.

Reference: internal-docs/design/daemon-design.md § CSRPreset dataclass
"""

from dataclasses import dataclass

from .sia_transport import CrcFormat, TransportType

SUPPORTED_SCHEMA_VERSION: int = 1


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

    def __post_init__(self) -> None:
        """Validate and convert preset fields after initialization.

        Converts transport from raw config string to TransportType enum.
        Uses object.__setattr__ because frozen=True prevents direct assignment.
        """
        if not isinstance(self.transport, TransportType):
            object.__setattr__(self, 'transport', TransportType(self.transport))
        if self.reconnect_max_attempts < 1:
            raise ValueError(
                f"reconnect_max_attempts must be >= 1, got {self.reconnect_max_attempts}"
            )
        if self.reconnect_delay_s < 0:
            raise ValueError(f"reconnect_delay_s must be >= 0, got {self.reconnect_delay_s}")
