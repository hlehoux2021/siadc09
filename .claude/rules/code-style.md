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

### Classes vs Functions: When to Use Each

Python supports both OOP and functional styles. While you have a preference for classes and methods, there are clear boundaries where each approach excels. This section provides a decision framework.

#### ✅ **Use FUNCTIONS for:**

**1. Pure, Stateless Operations**

No instance state needed. Same inputs always produce same outputs. Reason: simplicity, composability, mathematical clarity.

```python
# ✓ GOOD: Stateless cryptography functions
def encrypt_message(plaintext: bytes, key: bytes) -> bytes:
    """Pure function: f(data, key) → ciphertext (deterministic)."""
    validate_encryption_key(key)
    padded = _apply_pkcs7_padding(plaintext)
    # ... encrypt ...
    return ciphertext

# Usage: No object lifecycle, no initialization
ciphertext = encrypt_message(plaintext, key)
recovered = decrypt_message(ciphertext, key)
```

**Project example:** `sia_crypto.py` — each encryption is independent of others.

**2. Utility Functions & Helpers**

Formatting, validation, transformation used across multiple unrelated classes. Reason: reusable, no conceptual object.

```python
def calculate_crc(data: bytes, crc_format: Literal["SIA", "ADM"]) -> int:
    """Pure calculation. No state, no side effects."""
    # ...

def format_timestamp(ts: datetime) -> str:
    """Pure formatting utility."""
    # ...
```

**3. Module-Level Factories**

Create and return configured objects with minimal setup logic.

```python
def create_default_csr_preset() -> CSRPreset:
    """Factory: returns a configured preset."""
    return CSRPreset(
        name="IMA Protect",
        host="csr.example.com",
        port=5000,
        encryption_key=b"0123456789ABCDEF"
    )
```

---

#### ✅ **Use CLASSES for:**

**1. Stateful Objects (PRIMARY REASON)**

Instance variables track state across method calls. Reason: clear object semantics, encapsulation, lifecycle management.

```python
# ✓ GOOD: Stateful protocol builder
class SIAMessageBuilder:
    """Manages per-account sequence numbers and message encoding."""
    
    def __init__(self, crc_format: Literal["SIA", "ADM"]) -> None:
        self._seq_map: dict[str, int] = {}  # State: sequences per account
        self._crc_format = crc_format
    
    def encode_message(self, account: str, event_code: str) -> bytes:
        """Increments sequence for this account."""
        seq = self._seq_map.get(account, 0) + 1
        self._seq_map[account] = seq
        # ... encode with sequence ...
        return frame
```

**Project example:** `SIAMessageBuilder` needs per-account sequence tracking.

**2. Behavioral Objects (Related Methods)**

Multiple methods work together on shared state. Reason: cohesion, encapsulation.

```python
# ✓ GOOD: Cohesive behavior around transport state
class SIATransport:
    """Manages UDP/TCP connection lifecycle."""
    
    def __init__(self, host: str, port: int) -> None:
        self._socket: Optional[socket.socket] = None
        self._is_connected = False
    
    async def connect(self) -> None:
        """Open connection."""
        self._socket = await asyncio.open_connection(...)
        self._is_connected = True
    
    async def send(self, data: bytes) -> None:
        """Send data over active connection."""
        if not self._is_connected:
            raise TransportError("Not connected")
        self._socket.sendall(data)
    
    async def disconnect(self) -> None:
        """Close connection."""
        if self._socket:
            self._socket.close()
        self._is_connected = False
```

**3. Configuration & Contracts (Even Without State)**

Data + optional validation logic. Use `@dataclass` for simplicity.

```python
# ✓ GOOD: Config object with validation
@dataclass
class CSRPreset:
    """Central Station Receiver preset configuration."""
    name: str
    host: str
    port: int
    encryption_key: Optional[bytes] = None
    timeout_seconds: int = 60
    
    def __post_init__(self) -> None:
        """Validate preset after initialization."""
        if not (1 <= self.port <= 65535):
            raise ValueError(f"Invalid port: {self.port}")
```

**4. Error Handling & Context**

Custom exceptions for domain-specific errors. TypedDict or dataclass for error context.

```python
# ✓ GOOD: Domain-specific exception
class AESKeyError(Exception):
    """Raised when encryption key validation fails."""
    pass

# ✓ GOOD: Error context with type safety
@dataclass
class EventFailedContext:
    event_code: str
    account_number: str
    reason: str
    timestamp: datetime
```

---

#### 🎯 **Classes Without State: When They're Better**

You may ask: "Why use a class if there's no state?" Here are 10 cases:

**Case 1: Semantic Intent / Conceptual Entities**

A class declares: "This is a THING, not just an operation."

```python
# ❌ LESS CLEAR: Functions scattered in module
def calculate_crc_sia(data: bytes) -> int: ...
def calculate_crc_adm(data: bytes) -> int: ...
crc = calculate_crc_sia(frame)  # Which algorithm is this?

# ✅ BETTER: Classes make intent explicit
class SIACRCFormat:
    """CRC-16 MODBUS (SIA DC-09 variant)."""
    @staticmethod
    def calculate(data: bytes) -> int:
        # Polynomial 0xA001, specific to SIA
        ...

class ADMCRCFormat:
    """Different CRC variant (ADM protocol)."""
    @staticmethod
    def calculate(data: bytes) -> int: ...

crc = SIACRCFormat.calculate(frame)  # Obviously SIA algorithm
```

**Case 2: Polymorphism / Strategy Pattern**

Different implementations of the same contract. Reason: extensibility without modifying code.

```python
# ❌ PROBLEM: Conditional function logic
def send_frame(frame: bytes, transport_type: Literal["UDP", "TCP"], **kwargs) -> None:
    if transport_type == "UDP":
        socket.sendto(frame, ...)
    elif transport_type == "TCP":
        socket.send(frame)

# ✅ BETTER: Classes with polymorphism
class Transport(ABC):
    @abstractmethod
    def send(self, frame: bytes) -> None: pass

class UDPTransport(Transport):
    def send(self, frame: bytes) -> None:
        socket.sendto(frame, (self.host, self.port))

class TCPTransport(Transport):
    def send(self, frame: bytes) -> None:
        socket.send(frame)

# No conditionals, extensible
transport: Transport = UDPTransport("example.com", 5000)
transport.send(frame)
```

**Case 3: Protocol/Interface Compliance**

Python protocols expect specific methods (`__iter__`, `__enter__`, `__next__`).

```python
# ❌ AWKWARD: Functions don't fit iterator protocol
def create_frame_iterator(frames_list):
    # Can't use in for loops naturally
    ...

# ✅ BETTER: Iterator class
class FrameIterator:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.index = 0
    
    def __iter__(self):
        return self
    
    def __next__(self) -> bytes:
        if self.index >= len(self.frames):
            raise StopIteration
        frame = self.frames[self.index]
        self.index += 1
        return frame

for frame in FrameIterator(frames):  # Works naturally
    send(frame)
```

**Case 4: Context Manager Protocol**

Resource management with `with` statement. Reason: automatic cleanup, exception-safe.

```python
# ❌ AWKWARD: Manual resource management
socket = connect_to_csr("csr.example.com", 5000)
try:
    send_frame(socket, frame)
finally:
    socket.close()  # Easy to forget!

# ✅ BETTER: Context manager class
class CSRConnection:
    def __init__(self, host: str, port: int) -> None:
        self.socket: Optional[socket.socket] = None
    
    def __enter__(self) -> socket.socket:
        self.socket = connect_tcp(self.host, self.port)
        return self.socket
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.socket:
            self.socket.close()

with CSRConnection("csr.example.com", 5000) as socket:
    send_frame(socket, frame)
# Socket auto-closed, even on exception
```

**Case 5: Method Chaining / Fluent API**

Readable DSL-style code. Reason: readability, discoverability.

```python
# ❌ AWKWARD: Nested function calls
frame = build_frame(
    set_account(set_sequence(set_event_code(create_frame(), "1130"), 1), "001234")
)

# ✅ BETTER: Fluent API with classes
class FrameBuilder:
    def __init__(self) -> None:
        self.frame_data = {}
    
    def event_code(self, code: str) -> "FrameBuilder":
        self.frame_data["event_code"] = code
        return self
    
    def sequence(self, seq: int) -> "FrameBuilder":
        self.frame_data["sequence"] = seq
        return self
    
    def account(self, account: str) -> "FrameBuilder":
        self.frame_data["account"] = account
        return self
    
    def build(self) -> bytes:
        return encode_frame(self.frame_data)

# Readable, chainable
frame = (
    FrameBuilder()
    .event_code("1130")
    .sequence(1)
    .account("001234")
    .build()
)
```

**Case 6: Namespacing / Avoiding Module Pollution**

Group related functions without polluting namespace.

```python
# ❌ PROBLEM: Module cluttered with prefixed functions
def calculate_crc_sia(data: bytes) -> int: ...
def validate_crc_sia(data: bytes, expected_crc: int) -> bool: ...
def format_crc_sia(crc_int: int) -> str: ...
def parse_crc_sia(crc_str: str) -> int: ...
def calculate_crc_adm(data: bytes) -> int: ...
# ... 20+ functions starting with calculate_, validate_, format_ ...

# ✅ BETTER: Classes namespace the operations
class SIACRCFormat:
    @staticmethod
    def calculate(data: bytes) -> int: ...
    
    @staticmethod
    def validate(data: bytes, expected: int) -> bool: ...
    
    @staticmethod
    def format(crc_int: int) -> str: ...
    
    @staticmethod
    def parse(crc_str: str) -> int: ...

# Usage: Clear intent, no namespace pollution
SIACRCFormat.calculate(data)
```

**Case 7: Testability / Mockability**

Classes are easier to mock and test in isolation.

```python
# ❌ HARDER TO MOCK: Function with external dependency
def send_to_csr(frame: bytes, csr_host: str) -> None:
    response = requests.post(f"http://{csr_host}:5000", data=frame)

# Requires monkeypatching requests module

# ✅ EASIER TO MOCK: Class with dependency injection
class CSRClient:
    def __init__(self, csr_host: str) -> None:
        self.csr_host = csr_host
        self.http_client = requests
    
    def send(self, frame: bytes) -> Response:
        return self.http_client.post(f"http://{self.csr_host}:5000", data=frame)

# Dependency injection for testing
def test_send_to_csr():
    mock_http = Mock()
    client = CSRClient("localhost")
    client.http_client = mock_http
    
    client.send(frame)
    mock_http.post.assert_called_once()
```

**Case 8: Factory Methods / Alternative Constructors**

Create instances in multiple ways with clear intent.

```python
# ❌ AWKWARD: Functions with naming confusion
def create_csr_from_config(config_dict) -> tuple[str, int, Optional[bytes]]:
    return (config_dict["host"], config_dict["port"], config_dict.get("key"))

def create_csr_from_env() -> tuple[str, int, Optional[bytes]]:
    return (os.getenv("CSR_HOST"), int(os.getenv("CSR_PORT")), os.getenv("CSR_KEY"))

host, port, key = create_csr_from_config(cfg)  # What do these mean?

# ✅ BETTER: Factory methods on class
@dataclass
class CSRPreset:
    host: str
    port: int
    encryption_key: Optional[bytes] = None
    
    @classmethod
    def from_config_dict(cls, config: dict) -> "CSRPreset":
        return cls(
            host=config["host"],
            port=config["port"],
            encryption_key=config.get("key")
        )
    
    @classmethod
    def from_environment(cls) -> "CSRPreset":
        return cls(
            host=os.getenv("CSR_HOST", "localhost"),
            port=int(os.getenv("CSR_PORT", "5000")),
            encryption_key=os.getenv("CSR_KEY")
        )

preset = CSRPreset.from_config_dict(cfg)  # Clear intent, type safe
preset = CSRPreset.from_environment()
```

**Case 9: Future Extensibility**

Classes are easier to extend without breaking callers.

```python
# Function approach: adding new parameter breaks all callers
def encode_message(account, event_code, crc_format):  # v1
    ...

# Later: need encryption parameter
def encode_message(account, event_code, crc_format, encryption=False):  # v2 (breaking)

# Class approach: add methods without breaking callers
class SIAMessage:
    def __init__(self, account: str, event_code: str) -> None:
        self.account = account
        self.event_code = event_code
    
    def encode(self, crc_format: Literal["SIA", "ADM"]) -> bytes:  # v1
        ...

# Later: add encryption support without breaking existing code
class SIAMessage:
    def encode_encrypted(self, crc_format: Literal["SIA", "ADM"], key: bytes) -> bytes:  # v2 (backward compatible)
        ...
```

**Case 10: Explicit Intent / Domain Modeling**

The class name itself documents what the code does.

```python
# ❌ VAGUE: Generic function name
def process_data(data: bytes, account: str, event: str) -> bytes:
    # What does "process" mean?
    ...

# ✅ CLEAR: Specific class name
class SIAEventMessage:
    """Represents a single SIA protocol event message."""
    
    def __init__(self, account: str, event_code: str) -> None:
        self.account = account
        self.event_code = event_code
    
    def encode(self) -> bytes:
        """Encode to SIA protocol frame."""
        ...
    
    def to_json(self) -> dict:
        """Convert to JSON representation."""
        ...

message = SIAEventMessage("001234", "1130")
frame = message.encode()  # Domain intent is explicit
```

---

#### 🏆 **Decision Checklist**

Ask yourself in this order:

1. **Does it need instance state?**
   - YES → Use a class
   - NO → Continue to question 2

2. **Is it part of a polymorphic hierarchy?** (Multiple implementations of same interface)
   - YES → Use abstract class with subclasses
   - NO → Continue to question 3

3. **Does it implement a protocol?** (`__iter__`, `__enter__`, `__next__`, etc.)
   - YES → Use a class
   - NO → Continue to question 4

4. **Will it be chained or fluently configured?**
   - YES → Use a class (builder pattern)
   - NO → Continue to question 5

5. **Is it a domain concept?** (CRCFormat, Message, CSRPreset)
   - YES → Use a class (semantic intent)
   - NO → Continue to question 6

6. **Will it have multiple construction paths?**
   - YES → Use a class with factory methods
   - NO → Continue to question 7

7. **Is it a pure, mathematical operation?** (encrypt, format, calculate)
   - YES → Use a function
   - NO → Use a class

---

#### 📊 **Decision Summary**

```
┌─ Needs State?
│  ├─ YES → Class
│  └─ NO → Ask next question
│
├─ Polymorphic / Protocol / Fluent API / Domain Concept?
│  ├─ YES → Class
│  └─ NO → Continue
│
└─ Pure Operation / Utility?
   ├─ YES → Function
   └─ NO → Class (default to OOP for behavior)
```

---

#### 📋 **Project Examples**

| Module | Approach | Reason |
|--------|----------|--------|
| **sia_crypto.py** | ✅ Functions | Pure cryptography (stateless) |
| **sia_protocol.py** | ✅ Class `SIAMessageBuilder` | Stateful: maintains sequence per account |
| **error_handler.py** | ✅ Enum/Dataclass | Configuration contract (no state) |
| **daemon.py** (future) | ✅ Class `Daemon` | Stateful: tracks SM1/SM2 state, lifecycle |
| **transport.py** (future) | ✅ Class `SIATransport` | Stateful: connection lifecycle |

---

#### ⚠️ **Anti-Patterns to Avoid**

**❌ DON'T: Class with only static methods (use functions instead)**
```python
# BAD: Class with no instance state or polymorphism
class CryptoUtils:
    @staticmethod
    def encrypt(plaintext: bytes, key: bytes) -> bytes: ...
    
    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes) -> bytes: ...

# GOOD: Just use functions
def encrypt(plaintext: bytes, key: bytes) -> bytes: ...
def decrypt(ciphertext: bytes, key: bytes) -> bytes: ...
```

**❌ DON'T: Function with 6+ parameters (probably needs a class)**
```python
# BAD: Too many parameters
def process_message(plaintext, key, crc_fmt, receiver, account, prefix, encryption, timestamp):
    # ...

# GOOD: Use a dataclass or class
@dataclass
class MessageConfig:
    crc_format: Literal["SIA", "ADM"]
    receiver: str
    account: str
    prefix: str
    encryption: bool
    timestamp: Optional[str]

def process_message(plaintext: bytes, key: bytes, config: MessageConfig) -> bytes: ...
```

**❌ DON'T: Stateless class without polymorphism or protocol (use functions)**
```python
# BAD: No reason to be a class
class Validator:
    def validate_key(self, key: bytes) -> bool:
        return len(key) == 16

# GOOD: Just a function
def validate_key(key: bytes) -> bool:
    return len(key) == 16
```

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

### No `hasattr()` Guards on `self`

Never use `hasattr(self, 'name')` to guard against a missing attribute or method on the current instance.

**Why:** If an attribute is missing on `self`, the class is incomplete — `__init__` should have initialized it. A `hasattr` guard silently swallows the `AttributeError` that would have exposed the design gap during testing. The bug then surfaces silently in production as a no-op.

**❌ Avoid:**
```python
async def _log_event(self) -> None:
    if hasattr(self, '_ring_buffer'):           # ❌ hides missing __init__ setup
        await self._ring_buffer.push(...)
    if hasattr(self, '_update_info_commands'):  # ❌ hides unimplemented interface
        await self._update_info_commands()
```

**✅ Prefer: initialize everything in `__init__`, use explicit stubs for deferred implementations**
```python
def __init__(self) -> None:
    self._ring_buffer: RingBuffer = RingBuffer()            # always present
    self._update_info_commands = self._info_commands_stub   # stub, never missing

async def _info_commands_stub(self, data: dict | None = None) -> None:
    """Stub: full implementation in Epic 6."""
    pass
```

This way, a missing attribute raises `AttributeError` immediately and loudly — caught in tests, not silently ignored in production.

**Exception:** `hasattr()` is acceptable when inspecting third-party or framework objects you do not own, where optional attribute presence is an intentional part of their API contract.

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
