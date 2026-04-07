# Claude Code Style Rules

## Python Code Style

### Strong Typing Preference

Use precise type hints instead of generic types. Avoid `str`, `int`, `dict` when more specific types are available.

**❌ Avoid: Generic string type loses information**
```python
# Constants without type safety
CRC_FORMAT_SIA = "SIA"
CRC_FORMAT_ADM = "ADM"

def calculate_crc(data: bytes, crc_format: str) -> str:
    if crc_format not in [CRC_FORMAT_SIA, CRC_FORMAT_ADM]:
        raise ValueError(f"CRC format not supported: {crc_format}")
    # ...
```

Problem: Type checker can't catch invalid values like `calculate_crc(data, "INVALID")` at lint time.

**✅ Prefer: Use Literal or Enum for type safety**

Option A — Literal type (for simple string/int enums):
```python
from typing import Literal

CRC_FORMAT_SIA = "SIA"
CRC_FORMAT_ADM = "ADM"

def calculate_crc(data: bytes, crc_format: Literal["SIA", "ADM"]) -> str:
    # Type checker now catches invalid values at lint time
    # ...
```

Option B — Enum class (preferred for more complex enums):
```python
from enum import Enum

class CRCFormat(Enum):
    SIA = "SIA"
    ADM = "ADM"

def calculate_crc(data: bytes, crc_format: CRCFormat) -> str:
    # Type checker enforces CRCFormat.SIA or CRCFormat.ADM only
    # ...
```

**✅ Prefer: Use TypedDict for dict structure**
```python
from typing import TypedDict

class ErrorContext(TypedDict):
    error_code: str
    timestamp: datetime
    account_number: str

def notify_error(context: ErrorContext) -> None:
    # Type checker validates dict structure
    print(context["error_code"])
```

**❌ Avoid:**
```python
def notify_error(context: dict) -> None:
    # No type checking on dict structure
    print(context["error_code"])  # Could KeyError at runtime
```

**✅ Prefer: Use dataclass for complex objects**
```python
from dataclasses import dataclass

@dataclass
class SMTransition:
    from_state: str
    to_state: str
    trigger: str
    timestamp: datetime

def log_transition(transition: SMTransition) -> None:
    # Type checker validates all fields
    # ...
```

**✅ Prefer: Use Union and Optional correctly**
```python
from typing import Optional, Union

# Good: Optional for nullable types
def get_sequence(account: str) -> Optional[str]:
    return sequences.get(account)

# Good: Union for multiple types (use | syntax in Python 3.10+)
def handle_response(data: bytes | str) -> None:
    # ...

# Bad: Avoid Union[X, None] — use Optional[X] instead
def get_sequence(account: str) -> Union[str, None]:  # ❌
    # ...
```

### Variable and Function Naming

- **Constants:** UPPER_SNAKE_CASE (all caps with underscores)
  ```python
  MAX_RETRIES = 3
  SIA_NULL_CODE = "0000"
  DEFAULT_TIMEOUT_SECONDS = 60
  ```

- **Functions/methods:** lower_snake_case
  ```python
  def calculate_crc(data: bytes) -> str:
  def format_timestamp(ts: datetime) -> str:
  ```

- **Classes:** PascalCase
  ```python
  class SequenceManager:
  class SIAProtocolError(Exception):
  ```

- **Private methods/attributes:** prefix with `_`
  ```python
  def _validate_hex(value: str) -> bool:
  self._seq_map = {}
  ```

### Type Hints on All Functions

Every function must have:
- Parameter type hints
- Return type hints
- Exception types in docstring (if applicable)

```python
def encode_message(
    account_number: str,
    event_code: str,
    crc_format: Literal["SIA", "ADM"],
    encryption: bool = False
) -> bytes:
    """
    Encode a complete SIA protocol message frame.

    Args:
        account_number: 3-16 hex ASCII characters
        event_code: 4-digit event code
        crc_format: CRC algorithm ("SIA" or "ADM")
        encryption: Whether to encrypt (default False)

    Returns:
        Complete frame as bytes: LF + CRC + Length + Message + CR

    Raises:
        ValueError: If account_number or event_code invalid
    """
```

### Multiple Inheritance & Explicit Resolution Order

Multiple inheritance is allowed, but **you must explicitly specify the method resolution order** — do not rely on Python's MRO (Method Resolution Order) to resolve ambiguity implicitly.

**✅ Prefer: Explicit method delegation**
```python
class LoggerMixin:
    def log(self, msg: str) -> None:
        print(f"[LOG] {msg}")

class NotifierMixin:
    def notify(self, msg: str) -> None:
        print(f"[NOTIFY] {msg}")

class Daemon(LoggerMixin, NotifierMixin):
    """Daemon inherits from both mixins."""

    def report_status(self, status: str) -> None:
        # Explicitly call both parent methods
        self.log(f"Status: {status}")
        self.notify(f"Status changed: {status}")
```

**✅ Prefer: Call parent via explicit super() with class name (Python 3.x)**
```python
class Base1:
    def process(self, data: str) -> str:
        return f"Base1: {data}"

class Base2:
    def process(self, data: str) -> str:
        return f"Base2: {data}"

class Child(Base1, Base2):
    def process(self, data: str) -> str:
        # Explicitly sequence the calls
        result1 = Base1.process(self, data)
        result2 = Base2.process(self, data)
        return f"{result1} + {result2}"
```

**❌ Avoid: Relying on implicit MRO**
```python
class Child(Base1, Base2):
    def process(self, data: str) -> str:
        # Ambiguous! Which parent's process() is called?
        super().process(data)  # ❌ Relies on MRO, not explicit
```

**✅ Prefer: Use mixin composition instead of multiple inheritance when possible**
```python
from functools import wraps

def with_logging(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

def with_notification(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        print(f"Notifying: {result}")
        return result
    return wrapper

class Daemon:
    @with_logging
    @with_notification
    def report_status(self, status: str) -> str:
        return f"Status: {status}"
```

### Import Organization

```python
# 1. Standard library imports (alphabetical)
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

# 2. Third-party imports (alphabetical)
import pytest

# 3. Local imports (alphabetical)
from resources.siadc09d.error_handler import ErrorCode
from resources.siadc09d.sia_protocol import encode_message
```

No blank line between groups; each group alphabetically sorted.

### Class Design: Document and Initialize All Instance Variables

Every class must:
1. **Document all instance variables** in the `__init__` docstring
2. **Initialize all instance variables** in `__init__` (never add attributes later)
3. **Use type hints** for all instance variables

This prevents `AttributeError` surprises and makes class state explicit.

**❌ Avoid: Attributes added in other methods**
```python
class Daemon:
    def __init__(self, config: dict) -> None:
        self.config = config
        # Missing: _tasks, _sm1_state, _strike_count

    async def on_start(self) -> None:
        self._tasks: set = set()  # ❌ Added here, not in __init__
        self._sm1_state: str = "INITIALIZING"  # ❌ Added here
        self._strike_count: int = 0  # ❌ Added here
```

Problems:
- Type checker can't verify attributes exist
- `AttributeError` if `on_start()` hasn't been called
- Class state unclear from reading `__init__`
- Difficult to trace where attributes come from

**✅ Prefer: All attributes initialized in `__init__`**
```python
class Daemon:
    """Manages SIA protocol daemon lifecycle and state machines."""

    def __init__(self, config: dict) -> None:
        """Initialize daemon with all instance variables.

        Args:
            config: Configuration dict with keys: csr_host, csr_port, etc.

        Instance Variables:
            config: Configuration dictionary
            _tasks: Set of running asyncio tasks
            _sm1_state: Current SM1 (supervision) state
            _strike_count: Current strike counter (0-3)
            _logger: Module logger instance
            _transport: Transport layer (UDP or TCP)
        """
        self.config = config
        self._tasks: set[asyncio.Task] = set()
        self._sm1_state: str = "INITIALIZING"
        self._strike_count: int = 0
        self._logger = logging.getLogger(__name__)
        self._transport: Optional[SIATransport] = None

    async def on_start(self) -> None:
        """Start the daemon.

        Note: All state variables already initialized in __init__.
        This method only modifies existing attributes.
        """
        self._transport = await self._create_transport()
        # ...
```

### Use Dataclass for Simple Value Objects

For simple classes that mainly hold data, use `@dataclass`:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class CSRPreset:
    """Central Station Receiver preset configuration."""
    name: str
    host: str
    port: int
    encryption_key: Optional[str] = None
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        """Validate preset after initialization."""
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port}")
```

Benefits:
- `__init__` generated automatically
- All attributes documented and type-hinted
- Automatically generates `__repr__`, `__eq__`, etc.
- Clear dataclass semantics

### Typed Instance Variables with Defaults

Use class-level annotations for defaults, instance-level for per-object state:

```python
from typing import ClassVar

class SequenceManager:
    """Manages per-account sequence numbers."""

    # Class variable (shared across all instances)
    MAX_SEQUENCE: ClassVar[int] = 9999

    def __init__(self, start_seq: int = 1) -> None:
        """Initialize sequence manager.

        Args:
            start_seq: Starting sequence number (default 1)

        Instance Variables:
            _seq_map: Dict mapping account numbers to current sequence
            _start_seq: Initial sequence number for new accounts
        """
        self._seq_map: dict[str, int] = {}
        self._start_seq: int = start_seq
```

### Docstring Instance Variables Section

When a class has more than 3 instance variables, document them in the `__init__` docstring:

```python
def __init__(self, config: dict) -> None:
    """Initialize Daemon.

    Args:
        config: Configuration dict with keys:
            - csr_host: str
            - csr_port: int
            - encryption_key: Optional[str]

    Instance Variables:
        config: Configuration dict (passed in)
        _sm1_state: Current supervision state ("INITIALIZING", "HEALTHY", etc.)
        _sm2_state: Current event state ("IDLE", "PENDING", etc.)
        _strike_count: Strike counter for supervision failures (0-3)
        _tasks: Set of active asyncio.Task objects
        _last_ack_time: datetime of last ACK, or None
        _ring_buffer: Deque of recent messages (max 50 entries)
        _logger: Module logger for observability
    """
```

---

### Docstring Style

Use Google-style docstrings:

```python
def encode_message(
    account_number: str,
    event_code: str,
    crc_format: Literal["SIA", "ADM"]
) -> bytes:
    """Brief one-line description.

    Longer description explaining what the function does, why, and any
    important context or constraints.

    Args:
        account_number: 3-16 hex ASCII characters
        event_code: 4-digit event code (e.g., "1130" for burglary)
        crc_format: CRC algorithm selector ("SIA" or "ADM")

    Returns:
        Complete frame as bytes: LF + CRC + Length + Message + CR

    Raises:
        ValueError: If account_number is not 3-16 hex chars
        ValueError: If crc_format not in ("SIA", "ADM")

    Reference:
        docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md § 5.5.1
    """
```

### No Magic Numbers or Strings

Every numeric or string constant must be named:

```python
# ❌ Avoid
def validate_sequence(seq: str) -> bool:
    return len(seq) == 4 and seq.isdigit()

# ✅ Prefer
SEQUENCE_LENGTH = 4

def validate_sequence(seq: str) -> bool:
    return len(seq) == SEQUENCE_LENGTH and seq.isdigit()
```

### Error Handling

- **Never silently catch exceptions** (bare `except:`)
- **Catch specific exceptions only**
- **Raise custom exceptions with context**

```python
# ❌ Avoid
try:
    calculate_crc(data)
except:  # Catches everything!
    pass

# ✅ Prefer
try:
    calculate_crc(data)
except ValueError as e:
    logger.error(f"CRC calculation failed: {e}")
    raise
except TypeError as e:
    logger.error(f"Invalid input type: {e}")
    raise SIAProtocolError(f"Cannot calculate CRC: {e}") from e
```

### Async Code Style

- All async functions must be declared with `async def`
- All async calls must use `await`
- Never create untracked tasks (store in `_tasks` set or similar)
- Always use `asyncio.wait_for()` on network operations to prevent hanging

```python
async def send_message(self, frame: bytes) -> None:
    """Send a message with timeout protection."""
    try:
        # ✅ Good: wrap in wait_for to prevent indefinite hang
        await asyncio.wait_for(
            self._transport.send(frame),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.error("Send timed out")
        raise SIATransportError("Send timeout") from None
```

### No TODO Comments Without Context

If you add a TODO, explain what and why:

```python
# ❌ Avoid
# TODO: fix this later

# ✅ Prefer
# TODO (v1.1): Implement auto-heal via NAK timestamp parsing
# Reason: Deferred to v1.1; requires parse_nak_timestamp() helper
```

---

## PHP Code Style

### Type Declarations

Use modern PHP 8+ typed properties and return types:

```php
// ❌ Avoid
public function execute($cmd) {
    return $result;
}

// ✅ Prefer
public function execute(string $cmd): ?string {
    return $result;
}
```

### No Global State

Use dependency injection; avoid global variables or singletons unless absolutely necessary.

### Consistent Naming

- **Methods:** camelCase
- **Constants:** UPPER_SNAKE_CASE or PascalCase (for class constants)
- **Properties:** $camelCase

```php
const DEFAULT_TIMEOUT = 30;

private string $daemonPath;

public function getDaemonInfo(): array {
    // ...
}
```

### Null Safety

Use null coalescing and null-safe operators (PHP 8+):

```php
// ✅ Prefer
$value = $config['key'] ?? $default;
$result = $daemon?->getStatus();
```
