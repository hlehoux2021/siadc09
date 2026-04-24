# Code Style Rules

## Python

### Strong Typing

Use precise types. Avoid bare `str`, `int`, `dict` when narrower types exist.

- `Literal["SIA", "ADM"]` or `Enum` instead of `str` for constrained values
- `TypedDict` instead of `dict` for structured dicts
- `@dataclass` for data objects with multiple fields
- `Optional[X]` for nullable (not `Union[X, None]`); use `X | Y` syntax (Python 3.10+)

```python
def calculate_crc(data: bytes, *, crc_format: Literal["SIA", "ADM"]) -> str: ...

class ErrorContext(TypedDict):
    error_code: str
    timestamp: datetime
```

### Naming

| Kind | Convention | Example |
|------|-----------|---------|
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRIES = 3` |
| Functions/methods | `lower_snake_case` | `def calculate_crc():` |
| Classes | `PascalCase` | `class SequenceManager:` |
| Private | `_` prefix | `self._seq_map`, `def _validate():` |

### Type Hints on All Functions

Every function: parameter types + return type. Document exceptions in docstring.

### Multiple Inheritance

Allowed, but **explicitly delegate** method calls — never rely on implicit MRO.

```python
class Child(Base1, Base2):
    def process(self, data: str) -> str:
        result1 = Base1.process(self, data)
        result2 = Base2.process(self, data)
        return f"{result1} + {result2}"
```

**Prefer mixin classes over decorator functions** for cross-cutting concerns. Mixin classes are more discoverable, testable, and composable via inheritance.

```python
class LoggerMixin:
    def log(self, msg: str) -> None:
        print(f"[LOG] {msg}")

class NotifierMixin:
    def notify(self, msg: str) -> None:
        print(f"[NOTIFY] {msg}")

class Daemon(LoggerMixin, NotifierMixin):
    def report_status(self, status: str) -> None:
        self.log(f"Status: {status}")
        self.notify(f"Status changed: {status}")
```

### Import Organization

Three groups, each alphabetically sorted, no blank lines between groups:
1. Standard library
2. Third-party
3. Local

### Classes vs Functions

**Use FUNCTIONS for:**
- Pure stateless operations (same inputs → same outputs): `encrypt()`, `calculate_crc()`
- Utility helpers used across unrelated classes
- Simple module-level factories

**Use CLASSES for:**
- Stateful objects (instance variables track state across calls)
- Behavioral objects (multiple methods on shared state)
- Configuration & contracts (`@dataclass` with validation)
- Polymorphism / strategy pattern (ABC + subclasses)
- Python protocols (`__iter__`, `__enter__`, `__next__`)
- Builder / fluent API patterns
- Namespacing related operations
- Domain concepts (the class name documents intent)
- Dependency injection for testability
- Factory methods / alternative constructors

**Decision checklist** (in order):

1. Needs instance state? → Class
2. Polymorphic hierarchy? → Abstract class + subclasses
3. Python protocol? → Class
4. Fluent API / builder? → Class
5. Domain concept? → Class
6. Multiple construction paths? → Class with factory methods
7. Pure mathematical operation? → Function
8. Default → Class

**Anti-patterns:**
- Class with only static methods → use functions
- Function with 6+ params → extract a dataclass
- Stateless class without polymorphism or protocol → use a function

### Class Design

Every class must:
1. **Initialize ALL instance variables in `__init__`** — never add attributes in other methods
2. **Type-hint** all instance variables
3. **Document** instance variables in `__init__` docstring (when >3 vars)

Use `ClassVar` for class-level constants vs instance-level state.

```python
class SequenceManager:
    MAX_SEQUENCE: ClassVar[int] = 9999

    def __init__(self, start_seq: int = 1) -> None:
        """Initialize sequence manager.

        Args:
            start_seq: Starting sequence number

        Instance Variables:
            _seq_map: Account number → current sequence
            _start_seq: Initial sequence for new accounts
        """
        self._seq_map: dict[str, int] = {}
        self._start_seq: int = start_seq
```

### No `hasattr()` Guards on `self`

Never use `hasattr(self, 'x')` — it hides incomplete `__init__`. Use explicit stubs for deferred implementations instead.

**Exception:** Acceptable on third-party objects where optional attributes are part of their API contract.

### Dataclass for Value Objects

Use `@dataclass` for data-holding classes. Add `__post_init__` for validation.

### Docstring Style

Google-style: one-line summary, then Args / Returns / Raises / Reference sections.

### No Magic Numbers or Strings

Every constant must be named: `SEQUENCE_LENGTH = 4`, not bare `4`.

### Error Handling

- Never bare `except:` — catch specific exceptions only
- Raise custom exceptions with context using `from e`

### Async Code

- Always `await` async calls
- Never create untracked tasks — store in `_tasks` set with done callbacks
- Always wrap network operations in `asyncio.wait_for()` with timeout

### No TODO Without Context

```python
# TODO (v1.1): Implement auto-heal via NAK timestamp parsing
# Reason: Deferred; requires parse_nak_timestamp() helper
```

---

## PHP

- **Type declarations:** PHP 8+ typed properties and return types on all methods
- **No global state:** Use dependency injection
- **Naming:** methods `camelCase`, constants `UPPER_SNAKE_CASE`, properties `$camelCase`
- **Null safety:** Use `??` and `?->` operators
