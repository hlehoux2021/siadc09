---
paths: "**/*.py"
---
# Python Style

## Typing
- All functions: param types + return type. Use `X | Y` syntax (3.10+)
- `Literal`/`Enum` for constrained strings, `TypedDict` for structured dicts, `@dataclass` for value objects
- No bare `str`/`int`/`dict` when narrower types exist

## Naming
- Constants: `UPPER_SNAKE_CASE` | Functions: `lower_snake_case` | Classes: `PascalCase` | Private: `_prefix`

## Imports
Three groups alphabetically sorted (stdlib → third-party → local), no blank lines between groups.

## Classes vs Functions
- Function: pure stateless ops, utility helpers
- Class: stateful, polymorphic, protocol, domain concept, builder, DI
- Anti-patterns: static-only class → functions; 6+ params function → dataclass

## Class Design
- ALL instance vars in `__init__`, all type-hinted, `ClassVar` for class constants
- No `hasattr(self, ...)` — init all attrs upfront
- `@dataclass` + `__post_init__` for value objects

## Inheritance
- Multiple inheritance: explicitly delegate calls (no implicit MRO)
- Prefer mixin classes over decorator functions for cross-cutting concerns

## Error Handling
- Never bare `except:` — catch specific exceptions, raise with `from e`
- No magic numbers/strings — name every constant

## Async
- Always `await` async calls
- Untracked tasks forbidden — store in `_tasks` set with done callbacks
- Network ops: always `asyncio.wait_for()` with timeout

## Docstrings
Google-style: summary + Args/Returns/Raises. TODOs must include context and reason.
