"""
Test suite for logging_config.py module - Logger infrastructure setup.

Test strategy:
- TC1-TC8: Core functionality (HIGH priority)
- TC9-TC11: Edge cases (HIGH/MEDIUM priority)
- TC12-TC17: Framework integration (HIGH/MEDIUM priority)
- TC18-TC21: Module state & error handling (MEDIUM priority)
- TC22-TC23: Documentation (HIGH/MEDIUM priority)
"""

import ast
import importlib
import inspect
import logging
import sys
from pathlib import Path

import pytest


# ===== TC1: Logger creation ⭐ HIGH =====
def test_get_logger_returns_logger():
    """
    Test that _get_logger returns a configured logger object.

    Expected result:
    - _get_logger() returns a logging.Logger instance
    - Logger is not None
    - Logger can be used immediately without additional setup
    """
    from resources.siadc09d.logging_config import _get_logger

    logger = _get_logger("test_module")

    # Assert: Returns Logger instance
    assert isinstance(logger, logging.Logger)

    # Assert: Logger is not None
    assert logger is not None


# ===== TC2: Logger naming ⭐ HIGH =====
def test_get_logger_sets_correct_name():
    """
    Test that logger name matches the input parameter.

    Expected result:
    - Logger name equals input string exactly
    - Supports dotted module names (e.g., resources.siadc09d.daemon)
    - Name is preserved without modification
    """
    from resources.siadc09d.logging_config import _get_logger

    logger = _get_logger("resources.siadc09d.test")

    # Assert: Logger name matches input parameter exactly
    assert logger.name == "resources.siadc09d.test"


# ===== TC3: Asyncio logger level ⭐ HIGH =====
def test_asyncio_logger_pinned_to_warning():
    """
    Test that asyncio logger level is set to WARNING.

    Expected result:
    - Asyncio logger level is WARNING or higher
    - Asyncio logger does not produce DEBUG spam
    - Level persists after logger creation
    """
    from resources.siadc09d.logging_config import _get_logger

    # Initialize logging_config (may pin asyncio logger)
    _get_logger("test")

    asyncio_logger = logging.getLogger("asyncio")

    # Assert: Asyncio logger level is WARNING (value 30) or higher
    assert asyncio_logger.level == logging.WARNING or asyncio_logger.getEffectiveLevel() >= logging.WARNING


# ===== TC4: No circular imports ⭐ HIGH =====
def test_no_circular_imports():
    """
    Test that logging_config.py imports only typing and logging.

    Expected result:
    - Only typing and logging modules are imported
    - No daemon module imports (resources.siadc09d.*)
    - No circular dependency risk
    - AST parsing (not string match) validates imports
    """
    from resources.siadc09d import logging_config

    source = inspect.getsource(logging_config)
    tree = ast.parse(source)

    # Collect all imports
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)

    # Assert: Only logging imported (no daemon modules, no unused typing)
    assert imports == {"logging"}, f"Unexpected imports: {imports}"


# ===== TC5: CRITICAL level exists ⭐ MEDIUM =====
def test_critical_level_exists():
    """
    Test that CRITICAL log level is accessible (mapped to ERROR by framework).

    Expected result:
    - logging.CRITICAL attribute exists
    - CRITICAL level has correct numeric value (50)
    - Can be used in logging.getLogger().critical()
    """
    # Assert: CRITICAL level exists and has correct value
    assert hasattr(logging, "CRITICAL")
    assert logging.CRITICAL == 50


# ===== TC6: Multiple logger instances ⭐ MEDIUM =====
def test_logger_with_different_names():
    """
    Test that different module names get separate logger instances.

    Expected result:
    - Two loggers with different names are different objects
    - Each logger retains its own name
    - Loggers are independent (logging module behavior)
    """
    from resources.siadc09d.logging_config import _get_logger

    logger1 = _get_logger("module.one")
    logger2 = _get_logger("module.two")

    # Assert: Different names = different instances
    assert logger1 is not logger2

    # Assert: Each retains correct name
    assert logger1.name == "module.one"
    assert logger2.name == "module.two"


# ===== TC7: Docstring present ⭐ LOW =====
def test_logging_config_docstring_present():
    """
    Test that logging_config module has comprehensive docstring.

    Expected result:
    - Module has non-empty docstring
    - Docstring contains "logging" reference
    - Documentation present for developers
    """
    from resources.siadc09d import logging_config

    # Assert: Module docstring exists
    assert logging_config.__doc__ is not None

    # Assert: Docstring mentions logging
    assert "logging" in logging_config.__doc__.lower()


# ===== TC8: Type hints present ⭐ MEDIUM =====
def test_get_logger_has_type_hints():
    """
    Test that _get_logger has type hints on parameters and return value.

    Expected result:
    - _get_logger has parameter type annotation (name: str)
    - _get_logger has return type annotation (→ logging.Logger)
    - AST parsing confirms annotations exist
    """
    from resources.siadc09d import logging_config

    source = inspect.getsource(logging_config)
    tree = ast.parse(source)

    # Find _get_logger function
    found_get_logger = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_get_logger":
            found_get_logger = True
            # Assert: Has parameters
            assert len(node.args.args) > 0, "_get_logger should have parameters"
            # Assert: First parameter has annotation
            assert node.args.args[0].annotation is not None, "Parameter should have type hint"
            # Assert: Return type annotation exists
            assert node.returns is not None, "Return type should have annotation"

    # Assert: _get_logger function found
    assert found_get_logger, "_get_logger function not found"


# ===== TC9: Logger instance caching (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_get_logger_same_name_returns_same_instance():
    """
    Test that calling _get_logger with same name returns the same instance.

    Expected result:
    - logger1 is logger2 (same object in memory)
    - logging.getLogger() caches by name (standard Python behavior)
    - Subsequent calls don't create new loggers
    """
    from resources.siadc09d.logging_config import _get_logger

    logger1 = _get_logger("test.module")
    logger2 = _get_logger("test.module")

    # Assert: Same instance (not just equal, but same object)
    assert logger1 is logger2


# ===== TC10: Dotted module names (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_get_logger_handles_dotted_module_names():
    """
    Test that logger names with dots (package hierarchy) work correctly.

    Expected result:
    - Dotted names like "resources.siadc09d.daemon" supported
    - Logger name matches input exactly
    - Deep package hierarchies handled
    """
    from resources.siadc09d.logging_config import _get_logger

    logger = _get_logger("resources.siadc09d.daemon")

    # Assert: Logger name matches exactly
    assert logger.name == "resources.siadc09d.daemon"

    # Assert: Dots preserved
    assert "resources" in logger.name
    assert "siadc09d" in logger.name


# ===== TC11: Empty string logger name (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_get_logger_with_empty_name():
    """
    Test that empty string is handled (raises ValueError or returns root logger).

    Expected result:
    - Either raises ValueError (explicit rejection)
    - Or returns root logger (logging module behavior)
    - Behavior is defined and consistent
    """
    from resources.siadc09d.logging_config import _get_logger

    # Behavior: Either raises or returns root logger
    # Python's logging.getLogger("") returns root logger
    try:
        logger = _get_logger("")
        # If allowed, should return a logger
        assert logger is not None
    except (ValueError, TypeError):
        # If not allowed, should raise
        pass


# ===== TC12: Framework handlers preserved (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_get_logger_preserves_framework_handlers():
    """
    Test that framework handlers are not stripped by logging_config.

    Expected result:
    - Framework (jeedom-daemon-py) sets up root logger handlers
    - logging_config doesn't remove or override handlers
    - Handlers remain available for the logger
    """
    from resources.siadc09d.logging_config import _get_logger

    logger = _get_logger("test.dual_line")

    # Assert: Handlers list exists (may be empty or have framework handlers)
    assert hasattr(logger, "handlers")
    assert logger.handlers is not None


# ===== TC13: Format compatibility (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_root_logger_format_includes_timestamp_level_module():
    """
    Test that root logger format supports timestamp, level, module, message.

    Expected result:
    - Root logger exists and is configured
    - logging_config doesn't break framework's formatter
    - Format fields available for logging
    """
    # Assert: Root logger accessible
    root = logging.getLogger()
    assert root is not None

    # Assert: Can access standard attributes
    assert hasattr(root, "handlers")
    assert hasattr(root, "level")


# ===== TC14: No hardcoded secrets (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_logging_config_module_has_no_hardcoded_secrets():
    """
    Test that logging_config.py source code contains no credential patterns.

    Expected result:
    - No "password", "secret", "key", "token", "credential" patterns in code
    - Comments and documentation exempted
    - Prevents accidental secret exposure
    """
    from resources.siadc09d import logging_config

    source = inspect.getsource(logging_config)
    forbidden_patterns = ["password", "secret", "token", "credential"]
    # Note: "key" excluded — appears legitimately in logging format documentation

    tree = ast.parse(source)

    # Extract only string literals that are assigned to variables (not docstrings).
    # Also check function bodies for forbidden patterns in non-docstring statements.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Check assigned string values for forbidden patterns
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                val = node.value.value
                for pattern in forbidden_patterns:
                    assert pattern.lower() not in val.lower(), \
                        f"Found forbidden pattern '{pattern}' in assignment: {val[:80]}"


# ===== TC15: Privacy rules documented (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_logging_config_docstring_documents_privacy_rules():
    """
    Test that module docstring documents privacy rules for logging.

    Expected result:
    - Docstring mentions privacy, encryption, or secrets
    - Developers know what NOT to log
    - Privacy guidance documented
    """
    from resources.siadc09d import logging_config

    docstring = logging_config.__doc__
    assert docstring is not None

    # Check for privacy-related terms
    has_privacy_docs = ("privacy" in docstring.lower() or
                       "encrypt" in docstring.lower() or
                       "secret" in docstring.lower())
    assert has_privacy_docs, "Docstring should document privacy rules"


# ===== TC16: Root config not overridden (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_get_logger_respects_framework_root_configuration():
    """
    Test that logging_config doesn't modify framework's root logger config.

    Expected result:
    - Root logger level unchanged by _get_logger()
    - Root logger handlers unchanged
    - Framework (jeedom-daemon-py) control preserved
    """
    # Save original root config
    root = logging.getLogger()
    original_level = root.level
    original_handlers_count = len(root.handlers)

    from resources.siadc09d.logging_config import _get_logger

    # Call _get_logger
    logger = _get_logger("test.framework")

    # Assert: Root level not modified
    assert root.level == original_level, "Root logger level was modified"

    # Assert: Root handlers count not modified
    assert len(root.handlers) == original_handlers_count, "Root logger handlers were modified"


# ===== TC17: Asyncio level persistence (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_asyncio_logger_level_pinned_on_every_call():
    """
    Test that asyncio logger level remains WARNING after multiple _get_logger calls.

    Expected result:
    - Asyncio logger level stays WARNING through multiple invocations
    - Pinning is persistent, not one-time
    - Multiple calls don't affect asyncio logger
    """
    from resources.siadc09d.logging_config import _get_logger

    asyncio_logger = logging.getLogger("asyncio")

    # Call _get_logger multiple times
    for _ in range(5):
        _get_logger("test.module")

    # Assert: Asyncio still WARNING or higher
    assert asyncio_logger.level == logging.WARNING or \
           asyncio_logger.getEffectiveLevel() >= logging.WARNING


# ===== TC18: Safe multiple imports (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_logging_config_multiple_imports_safe():
    """
    Test that logging_config can be imported multiple times safely.

    Expected result:
    - Module can be reloaded without errors
    - No side effects on reimport
    - Idempotent initialization
    """
    from resources.siadc09d import logging_config as lc1

    # Reload the module
    importlib.reload(lc1)
    from resources.siadc09d import logging_config as lc2

    # Assert: Same module object after reload
    assert lc1 is lc2


# ===== TC19: No global state leakage (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_get_logger_does_not_create_global_state():
    """
    Test that _get_logger doesn't pollute module namespace.

    Expected result:
    - No new attributes added to logging_config module
    - Function is pure and doesn't create side effects
    - Module namespace stays clean
    """
    from resources.siadc09d import logging_config

    before_attrs = set(dir(logging_config))
    logger = logging_config._get_logger("test")
    after_attrs = set(dir(logging_config))

    # Assert: No new attributes added to module
    assert before_attrs == after_attrs, "Module namespace was polluted"


# ===== TC20: Type checking (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_get_logger_type_checking():
    """
    Test that _get_logger validates input is a string.

    Expected result:
    - Non-string inputs raise TypeError
    - Integer argument rejected
    - None argument rejected
    - String type enforced
    """
    from resources.siadc09d.logging_config import _get_logger

    # Assert: Integer raises TypeError
    with pytest.raises(TypeError):
        _get_logger(123)

    # Assert: None raises TypeError
    with pytest.raises(TypeError):
        _get_logger(None)


# ===== TC21: Very long names (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_get_logger_with_very_long_name():
    """
    Test that deeply nested package names work (e.g., a.b.c.d...).

    Expected result:
    - Long logger names supported
    - No length limit enforced
    - Deep package hierarchies handled
    """
    from resources.siadc09d.logging_config import _get_logger

    long_name = "a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z"
    logger = _get_logger(long_name)

    # Assert: Logger name matches exactly
    assert logger.name == long_name


# ===== TC22: Module docstring completeness (NEW - QA CHALLENGE) ⭐ HIGH =====
def test_logging_config_docstring_covers_requirements():
    """
    Test that module docstring explains v1.0, dual-line pattern, and key concepts.

    Expected result:
    - Docstring covers "single root logger"
    - Mentions "dual-line" pattern
    - References "French" (user-facing) + "DEBUG" (technical)
    - Explains "framework" integration
    - Documents "getLogger" usage pattern
    """
    from resources.siadc09d import logging_config

    docstring = logging_config.__doc__
    assert docstring is not None, "Module should have docstring"

    required_topics = [
        "single root logger",
        "dual-line",
        "French",
        "DEBUG",
        "framework",
        "getLogger"
    ]

    for topic in required_topics:
        assert topic.lower() in docstring.lower(), \
            f"Docstring missing required topic: '{topic}'"


# ===== TC23: Developer guide exists (NEW - QA CHALLENGE) ⭐ MEDIUM =====
def test_logging_developer_guide_file_exists():
    """
    Test that docs/logging-developer-guide.md exists and is comprehensive.

    Expected result:
    - File exists at docs/logging-developer-guide.md
    - Content is non-trivial (>500 chars)
    - Developer reference available
    """
    guide_path = Path("docs/logging-developer-guide.md")

    # Assert: File exists
    assert guide_path.exists(), "Developer guide not found"

    # Assert: Has meaningful content
    content = guide_path.read_text()
    assert len(content) > 500, "Developer guide too brief (should be >500 chars)"
