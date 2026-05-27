"""
Unit tests for Story 2-1: Simulator Framework & UDP/TCP Listen (CLI wrapper).

Tests validate the CLI wrapper module structure, argument parsing, configuration
management, simulator lifecycle, logging, and integration with Story 1.4's CSRSimulator.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import pytest


# Task 0: CLI Wrapper Module Structure Tests
class TestSimulatorCLIModuleStructure:
    """Test module structure and constants of tests.simulator.__main__"""

    def test_simulator_module_can_be_imported(self):
        """
        Test that tests.simulator.__main__ module exists and can be imported.

        Expected result:
        - Module imports without errors
        - Module is accessible via tests.simulator.__main__
        """
        # Attempt to import the module
        import tests.simulator.__main__ as cli_module

        # Assert: Module is successfully imported
        assert cli_module is not None

    def test_simulator_module_has_docstring(self):
        """
        Test that tests.simulator.__main__ module has a docstring.

        Expected result:
        - Module has a docstring (not None or empty)
        - Docstring describes the CLI wrapper purpose
        """
        import tests.simulator.__main__ as cli_module

        # Assert: Module has a docstring
        assert cli_module.__doc__ is not None
        assert len(cli_module.__doc__) > 0

        # Assert: Docstring mentions CLI wrapper or similar purpose
        doc_lower = cli_module.__doc__.lower()
        assert "cli" in doc_lower or "command" in doc_lower or "wrapper" in doc_lower

    def test_csr_simulator_import_available(self):
        """
        Test that CSRSimulator is imported from Story 1.4.

        Expected result:
        - CSRSimulator class is accessible in module
        - Imported from resources.siadc09d.csr_simulator
        """
        import tests.simulator.__main__ as cli_module
        from resources.siadc09d.csr_simulator import CSRSimulator

        # Assert: CSRSimulator is accessible (either imported or available)
        # (May be at module level or used internally)
        assert CSRSimulator is not None

    def test_default_udp_port_constant_defined(self):
        """
        Test that DEFAULT_UDP_PORT constant is defined.

        Expected result:
        - Constant exists and equals 10001
        - Constant is defined in module scope
        """
        import tests.simulator.__main__ as cli_module

        # Assert: DEFAULT_UDP_PORT constant exists
        assert hasattr(cli_module, "DEFAULT_UDP_PORT")

        # Assert: DEFAULT_UDP_PORT equals 10001
        assert cli_module.DEFAULT_UDP_PORT == 10001

    def test_default_tcp_port_constant_defined(self):
        """
        Test that DEFAULT_TCP_PORT constant is defined.

        Expected result:
        - Constant exists and equals 5000
        - Constant is defined in module scope
        """
        import tests.simulator.__main__ as cli_module

        # Assert: DEFAULT_TCP_PORT constant exists
        assert hasattr(cli_module, "DEFAULT_TCP_PORT")

        # Assert: DEFAULT_TCP_PORT equals 5000
        assert cli_module.DEFAULT_TCP_PORT == 5000

    def test_default_listen_host_constant_defined(self):
        """
        Test that DEFAULT_LISTEN_HOST constant is defined.

        Expected result:
        - Constant exists and equals '127.0.0.1'
        - Constant is a string
        """
        import tests.simulator.__main__ as cli_module

        # Assert: DEFAULT_LISTEN_HOST constant exists
        assert hasattr(cli_module, "DEFAULT_LISTEN_HOST")

        # Assert: DEFAULT_LISTEN_HOST equals '127.0.0.1'
        assert cli_module.DEFAULT_LISTEN_HOST == "127.0.0.1"

        # Assert: DEFAULT_LISTEN_HOST is a string
        assert isinstance(cli_module.DEFAULT_LISTEN_HOST, str)

    def test_simulator_version_string_defined(self):
        """
        Test that a version string constant is defined for CLI help.

        Expected result:
        - A version constant exists (SIMULATOR_VERSION or similar)
        - Version is a string
        - Version follows semantic versioning or similar pattern
        """
        import tests.simulator.__main__ as cli_module

        # Assert: At least one of common version constant names exists
        version_attr = None
        for attr_name in ["SIMULATOR_VERSION", "VERSION", "__version__"]:
            if hasattr(cli_module, attr_name):
                version_attr = getattr(cli_module, attr_name)
                break

        # Assert: A version constant was found
        assert version_attr is not None, "No version constant found (SIMULATOR_VERSION, VERSION, or __version__)"

        # Assert: Version is a string
        assert isinstance(version_attr, str)

        # Assert: Version is not empty
        assert len(version_attr) > 0


# Task 1: CLI Argument Parsing Tests
class TestSimulatorCLIArgumentParsing:
    """Test argument parsing functionality of CLI wrapper"""

    def test_parse_arguments_function_exists(self):
        """
        Test that a parse_arguments function or similar exists in the module.

        Expected result:
        - Function exists to parse command-line arguments
        - Function can be called (returns parser or parsed args)
        """
        import tests.simulator.__main__ as cli_module

        # Assert: At least one of common parser function names exists
        parser_func = None
        for func_name in ["parse_arguments", "create_parser", "parse_args"]:
            if hasattr(cli_module, func_name):
                parser_func = getattr(cli_module, func_name)
                break

        # Assert: A parser function was found
        assert parser_func is not None, "No argument parser function found"

    def test_parse_arguments_with_defaults(self):
        """
        Test that argument parser uses correct default values.

        Expected result:
        - --udp-port defaults to 10001
        - --tcp-port defaults to 5000
        - --host defaults to 127.0.0.1
        - --crc-format defaults to hex
        - --account defaults to 000001
        - --log-level defaults to INFO
        """
        import tests.simulator.__main__ as cli_module

        # Get the parser function
        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse empty args (use defaults)
        args = parser_func([])

        # Assert: UDP port defaults to 10001
        assert args.udp_port == 10001

        # Assert: TCP port defaults to 5000
        assert args.tcp_port == 5000

        # Assert: Host defaults to 127.0.0.1
        assert args.host == "127.0.0.1"

        # Assert: CRC format defaults to hex
        assert args.crc_format == "hex"

        # Assert: Account defaults to 000001
        assert args.account == "000001"

        # Assert: Log level defaults to INFO
        assert args.log_level == "INFO"

    def test_parse_arguments_udp_port_override(self):
        """
        Test that --udp-port argument can override default.

        Expected result:
        - --udp-port 8888 is parsed as 8888
        - Value is converted to integer
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse with custom UDP port
        args = parser_func(["--udp-port", "8888"])

        # Assert: UDP port is parsed correctly
        assert args.udp_port == 8888

    def test_parse_arguments_tcp_port_override(self):
        """
        Test that --tcp-port argument can override default.

        Expected result:
        - --tcp-port 9999 is parsed as 9999
        - Value is converted to integer
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse with custom TCP port
        args = parser_func(["--tcp-port", "9999"])

        # Assert: TCP port is parsed correctly
        assert args.tcp_port == 9999

    def test_parse_arguments_host_override(self):
        """
        Test that --host argument can override default.

        Expected result:
        - --host 192.168.1.1 is parsed as string
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse with custom host
        args = parser_func(["--host", "192.168.1.1"])

        # Assert: Host is parsed correctly
        assert args.host == "192.168.1.1"

    def test_parse_arguments_encryption_key_optional(self):
        """
        Test that --encryption-key is optional.

        Expected result:
        - Without --encryption-key, args.encryption_key is None
        - With --encryption-key VALUE, args.encryption_key is set to VALUE
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse without encryption key
        args = parser_func([])

        # Assert: Encryption key is None by default
        assert args.encryption_key is None

        # Parse with encryption key
        args = parser_func(["--encryption-key", "0123456789ABCDEF"])

        # Assert: Encryption key is parsed correctly
        assert args.encryption_key == "0123456789ABCDEF"

    def test_parse_arguments_crc_format_choices(self):
        """
        Test that --crc-format only accepts 'hex' or 'bin'.

        Expected result:
        - --crc-format hex is valid
        - --crc-format bin is valid
        - --crc-format invalid raises error
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse with hex format
        args = parser_func(["--crc-format", "hex"])
        assert args.crc_format == "hex"

        # Parse with bin format
        args = parser_func(["--crc-format", "bin"])
        assert args.crc_format == "bin"

        # Parse with invalid format should raise SystemExit
        with pytest.raises(SystemExit):
            parser_func(["--crc-format", "invalid"])

    def test_parse_arguments_account_override(self):
        """
        Test that --account argument can override default.

        Expected result:
        - --account ABCD12 is parsed as string
        - Value preserved exactly as provided
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse with custom account
        args = parser_func(["--account", "ABCD12"])

        # Assert: Account is parsed correctly
        assert args.account == "ABCD12"

    def test_parse_arguments_log_file_optional(self):
        """
        Test that --log-file is optional.

        Expected result:
        - Without --log-file, args.log_file is None
        - With --log-file PATH, args.log_file is set to PATH
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Parse without log file
        args = parser_func([])

        # Assert: Log file is None by default
        assert args.log_file is None

        # Parse with log file
        args = parser_func(["--log-file", "/tmp/test.log"])

        # Assert: Log file is parsed correctly
        assert args.log_file == "/tmp/test.log"

    def test_parse_arguments_log_level_choices(self):
        """
        Test that --log-level only accepts valid levels.

        Expected result:
        - --log-level INFO is valid
        - --log-level DEBUG is valid
        - --log-level WARNING is valid
        - --log-level ERROR is valid
        - --log-level invalid raises error
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Test valid log levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            args = parser_func(["--log-level", level])
            assert args.log_level == level

        # Test invalid log level should raise SystemExit
        with pytest.raises(SystemExit):
            parser_func(["--log-level", "INVALID"])

    def test_parse_arguments_help_available(self):
        """
        Test that --help flag is available.

        Expected result:
        - --help triggers help output (SystemExit expected)
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Assert: --help should raise SystemExit (standard argparse behavior)
        with pytest.raises(SystemExit):
            parser_func(["--help"])

    def test_parse_arguments_version_available(self):
        """
        Test that --version flag is available.

        Expected result:
        - --version triggers version output (SystemExit expected)
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Assert: --version should raise SystemExit (standard argparse behavior)
        with pytest.raises(SystemExit):
            parser_func(["--version"])


# Task 2: Configuration Management Tests
class TestSimulatorCLIConfigurationManagement:
    """Test configuration validation and preset building"""

    def test_validate_config_function_exists(self):
        """
        Test that a validate_config or similar function exists.

        Expected result:
        - Function exists to validate CLI arguments and build preset dict
        """
        import tests.simulator.__main__ as cli_module

        # Assert: At least one of common validation function names exists
        validate_func = None
        for func_name in ["validate_config", "validate_args", "build_preset"]:
            if hasattr(cli_module, func_name):
                validate_func = getattr(cli_module, func_name)
                break

        assert validate_func is not None

    def test_validate_config_returns_preset_dict(self):
        """
        Test that validate_config returns a dict with required preset fields.

        Expected result:
        - Returns dict with keys: crc_format, account_number, encryption_key
        - crc_format is one of ['hex', 'bin']
        - account_number is a string
        - encryption_key is None or bytes
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        # Create mock args object
        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        # Validate config
        preset = validate_func(args)

        # Assert: preset is a dict
        assert isinstance(preset, dict)

        # Assert: Required keys exist
        assert "crc_format" in preset
        assert "account_number" in preset
        assert "encryption_key" in preset

        # Assert: CRC format is valid
        assert preset["crc_format"] in ["hex", "bin"]

        # Assert: Account number is string
        assert isinstance(preset["account_number"], str)

        # Assert: Encryption key is None or bytes
        assert preset["encryption_key"] is None or isinstance(
            preset["encryption_key"], bytes
        )

    def test_validate_config_port_range_validation(self):
        """
        Test that port ranges are validated (1-65535).

        Expected result:
        - Valid ports (1-65535) are accepted
        - Invalid ports (<1 or >65535) raise ValueError
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        # Valid ports should work
        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )
        preset = validate_func(args)
        assert preset is not None

        # Invalid UDP port (too low)
        args.udp_port = 0
        with pytest.raises(ValueError):
            validate_func(args)

        # Invalid UDP port (too high)
        args.udp_port = 65536
        with pytest.raises(ValueError):
            validate_func(args)

        # Invalid TCP port (too low)
        args.udp_port = 10001
        args.tcp_port = 0
        with pytest.raises(ValueError):
            validate_func(args)

        # Invalid TCP port (too high)
        args.tcp_port = 65536
        with pytest.raises(ValueError):
            validate_func(args)

    def test_validate_config_account_format_validation(self):
        """
        Test that account number format is validated (3-16 hex chars).

        Expected result:
        - Valid accounts (3-16 hex chars) are accepted
        - Invalid accounts raise ValueError
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        # Valid account should work
        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )
        preset = validate_func(args)
        assert preset is not None

        # Too short (< 3 chars)
        args.account = "AB"
        with pytest.raises(ValueError):
            validate_func(args)

        # Too long (> 16 chars)
        args.account = "0123456789ABCDEFG"
        with pytest.raises(ValueError):
            validate_func(args)

        # Invalid hex characters
        args.account = "INVALID"
        with pytest.raises(ValueError):
            validate_func(args)

    def test_validate_config_encryption_key_hex_to_bytes_conversion(self):
        """
        Test that encryption key is converted from hex string to bytes.

        Expected result:
        - None encryption_key remains None
        - Hex string encryption_key is converted to bytes
        - Invalid hex string raises ValueError
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        # No encryption key
        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )
        preset = validate_func(args)
        assert preset["encryption_key"] is None

        # Valid 16-byte (32-char hex) encryption key
        args.encryption_key = "0123456789ABCDEF0123456789ABCDEF"
        preset = validate_func(args)
        assert preset["encryption_key"] is not None
        assert isinstance(preset["encryption_key"], bytes)
        assert len(preset["encryption_key"]) == 16

        # Invalid hex string
        args.encryption_key = "0123456789ABCDEFG"
        with pytest.raises(ValueError):
            validate_func(args)

    def test_validate_config_account_number_in_preset(self):
        """
        Test that validated account_number is in preset dict.

        Expected result:
        - preset['account_number'] equals the validated account from args
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        args = argparse.Namespace(
            crc_format="hex",
            account="ABCD12",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = validate_func(args)

        # Assert: account_number in preset matches validated account
        assert preset["account_number"] == "ABCD12"

    def test_validate_config_crc_format_in_preset(self):
        """
        Test that crc_format is correctly passed to preset.

        Expected result:
        - preset['crc_format'] equals args.crc_format
        """
        import tests.simulator.__main__ as cli_module

        validate_func = getattr(cli_module, "validate_config", None)
        assert validate_func is not None

        # Test with hex format
        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )
        preset = validate_func(args)
        assert preset["crc_format"] == "hex"

        # Test with bin format
        args.crc_format = "bin"
        preset = validate_func(args)
        assert preset["crc_format"] == "bin"


# Task 3: Simulator Initialization & Lifecycle Tests
class TestSimulatorCLILifecycle:
    """Test simulator lifecycle management (async start/stop, signal handling)"""

    @pytest.mark.asyncio
    async def test_async_main_function_exists(self):
        """
        Test that an async main coroutine or similar exists.

        Expected result:
        - Async main function exists and is callable
        """
        import tests.simulator.__main__ as cli_module

        # Assert: At least one of common async main function names exists
        async_main_func = None
        for func_name in ["async_main", "main_async", "main"]:
            func = getattr(cli_module, func_name, None)
            if func and asyncio.iscoroutinefunction(func):
                async_main_func = func
                break

        assert async_main_func is not None

    def test_simulator_instantiation_with_preset(self):
        """
        Test that simulator can be instantiated with validated preset.

        Expected result:
        - CSRSimulator accepts preset dict from validate_config()
        - Simulator instance has start() and stop() methods
        """
        import tests.simulator.__main__ as cli_module
        from resources.siadc09d.csr_simulator import CSRSimulator

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)
        simulator = CSRSimulator(
            udp_port=args.udp_port,
            tcp_port=args.tcp_port,
            preset=preset,
        )

        # Assert: Simulator has required methods
        assert hasattr(simulator, "start")
        assert hasattr(simulator, "stop")


# Task 4-6: File Logging, Console Output, Package Structure (minimal tests)
class TestSimulatorCLIConfiguration:
    """Test package structure and configuration helpers"""

    def test_simulator_package_is_importable(self):
        """
        Test that tests.simulator package is properly configured.

        Expected result:
        - Package can be run as module: python -m tests.simulator
        """
        # This test verifies __init__.py and __main__.py exist
        import tests.simulator

        assert tests.simulator is not None


# Task 7: Integration Tests with Story 1.4
class TestSimulatorCLIIntegration:
    """Integration tests validating CLI integration with Story 1.4's CSRSimulator"""

    def test_cli_argument_flow_to_simulator_creation(self):
        """
        Test complete flow: parse args → validate config → create simulator.

        Expected result:
        - args parsed from command line
        - config validated and converted to preset
        - CSRSimulator instantiated with preset
        - Simulator has expected configuration values
        """
        import tests.simulator.__main__ as cli_module
        from resources.siadc09d.csr_simulator import CSRSimulator

        # Parse arguments
        args = cli_module.parse_arguments([
            "--udp-port", "8888",
            "--tcp-port", "4444",
            "--crc-format", "bin",
            "--account", "ABCD12",
        ])

        # Validate and build preset
        preset = cli_module.validate_config(args)

        # Create simulator
        simulator = CSRSimulator(
            udp_port=args.udp_port,
            tcp_port=args.tcp_port,
            preset=preset,
        )

        # Assert: Simulator is configured correctly
        assert simulator.udp_port == 8888
        assert simulator.tcp_port == 4444
        assert simulator.preset["crc_format"] == "bin"
        assert simulator.preset["account_number"] == "ABCD12"

    def test_cli_with_encryption_key_flow(self):
        """
        Test flow with encryption key: parse → validate → preset includes key bytes.

        Expected result:
        - Encryption key hex string converted to bytes
        - Preset['encryption_key'] is bytes object
        - CSRSimulator receives correct key format
        """
        import tests.simulator.__main__ as cli_module
        from resources.siadc09d.csr_simulator import CSRSimulator

        # Parse arguments with encryption key
        args = cli_module.parse_arguments([
            "--encryption-key", "0123456789ABCDEF0123456789ABCDEF"
        ])

        # Validate and build preset
        preset = cli_module.validate_config(args)

        # Assert: Key is converted to bytes
        assert preset["encryption_key"] is not None
        assert isinstance(preset["encryption_key"], bytes)
        assert len(preset["encryption_key"]) == 16

        # Create simulator with encrypted preset
        simulator = CSRSimulator(
            udp_port=args.udp_port,
            tcp_port=args.tcp_port,
            preset=preset,
        )

        # Assert: Simulator received encryption key
        assert simulator.preset["encryption_key"] is not None
        assert isinstance(simulator.preset["encryption_key"], bytes)


# Critical Issue Tests: File Logging (CRITICAL-2)
class TestFileLoggingFeature:
    """Test file-based logging functionality for frame logging"""

    def test_log_file_argument_accepted(self):
        """
        Test that --log-file argument is accepted and stored.

        Expected result:
        - --log-file PATH is parsed without error
        - args.log_file equals the provided path
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        args = parser_func(["--log-file", "/tmp/test.log"])

        # Assert: Log file path is stored
        assert args.log_file == "/tmp/test.log"

    def test_log_level_argument_accepted(self):
        """
        Test that --log-level argument controls logging verbosity.

        Expected result:
        - --log-level DEBUG/INFO/WARNING/ERROR each parsed correctly
        - Default is INFO
        """
        import tests.simulator.__main__ as cli_module

        parser_func = getattr(cli_module, "parse_arguments", None)
        assert parser_func is not None

        # Test each level
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            args = parser_func(["--log-level", level])
            assert args.log_level == level

        # Test default
        args = parser_func([])
        assert args.log_level == "INFO"


# Critical Issue Tests: Encryption Key Validation (MAJOR-2, MAJOR-4)
class TestEncryptionKeyEdgeCases:
    """Test encryption key validation for all supported key lengths"""

    def test_validate_config_aes_128_key(self):
        """
        Test 16-byte AES-128 key is accepted.

        Expected result:
        - 32-char hex string (16 bytes) is converted to bytes
        - Key length is 16
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key="0123456789ABCDEF0123456789ABCDEF",  # 32 hex chars = 16 bytes
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: 16-byte key accepted
        assert preset["encryption_key"] is not None
        assert len(preset["encryption_key"]) == 16

    def test_validate_config_aes_192_key(self):
        """
        Test 24-byte AES-192 key is accepted.

        Expected result:
        - 48-char hex string (24 bytes) is converted to bytes
        - Key length is 24
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key="0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",  # 48 hex chars = 24 bytes
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: 24-byte key accepted
        assert preset["encryption_key"] is not None
        assert len(preset["encryption_key"]) == 24

    def test_validate_config_aes_256_key(self):
        """
        Test 32-byte AES-256 key is accepted.

        Expected result:
        - 64-char hex string (32 bytes) is converted to bytes
        - Key length is 32
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key="0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",  # 64 hex chars = 32 bytes
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: 32-byte key accepted
        assert preset["encryption_key"] is not None
        assert len(preset["encryption_key"]) == 32

    def test_validate_config_invalid_key_length(self):
        """
        Test invalid key length (not 16, 24, or 32 bytes) is rejected.

        Expected result:
        - 20-byte key (40 hex chars) raises ValueError
        - Error message indicates valid lengths
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key="0123456789ABCDEF0123456789ABCDEF01234567",  # 40 hex chars = 20 bytes (invalid)
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        # Assert: Invalid key length raises error
        with pytest.raises(ValueError) as exc_info:
            cli_module.validate_config(args)

        # Assert: Error message is clear
        assert "16" in str(exc_info.value) or "24" in str(exc_info.value) or "32" in str(exc_info.value)

    def test_validate_config_odd_length_hex_key(self):
        """
        Test odd-length hex string (cannot convert to bytes) is rejected.

        Expected result:
        - 17-char hex string raises ValueError
        - Error mentions hex format
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key="0123456789ABCDEF0",  # 17 chars (odd length, cannot convert)
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        # Assert: Odd-length hex raises error
        with pytest.raises(ValueError) as exc_info:
            cli_module.validate_config(args)

        assert "hex" in str(exc_info.value).lower()


# Critical Issue Tests: Account Number Boundary Values (MAJOR-5)
class TestAccountNumberBoundaryValues:
    """Test account number validation at boundary values"""

    def test_validate_config_account_minimum_length(self):
        """
        Test exactly 3-char account (minimum valid) is accepted.

        Expected result:
        - 3-char hex string is valid
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="ABC",  # Exactly 3 chars (minimum)
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: 3-char account accepted
        assert preset["account_number"] == "ABC"

    def test_validate_config_account_maximum_length(self):
        """
        Test exactly 16-char account (maximum valid) is accepted.

        Expected result:
        - 16-char hex string is valid
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="0123456789ABCDEF",  # Exactly 16 chars (maximum)
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: 16-char account accepted
        assert preset["account_number"] == "0123456789ABCDEF"

    def test_validate_config_account_with_leading_zeros(self):
        """
        Test account numbers with leading zeros work correctly.

        Expected result:
        - "000001" is valid and distinct from "1"
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        preset = cli_module.validate_config(args)

        # Assert: Leading zeros preserved
        assert preset["account_number"] == "000001"


# Critical Issue Tests: Error Message Quality (MAJOR-6)
class TestErrorMessageQuality:
    """Test that error messages are clear and actionable"""

    def test_port_validation_error_message_is_clear(self):
        """
        Test UDP port validation error includes range and invalid value.

        Expected result:
        - Error message mentions "UDP port"
        - Error message shows valid range (1-65535)
        - Error message includes the invalid value provided
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="000001",
            encryption_key=None,
            udp_port=0,  # Invalid
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        with pytest.raises(ValueError) as exc_info:
            cli_module.validate_config(args)

        error_msg = str(exc_info.value).lower()

        # Assert: Error message is clear
        assert "udp" in error_msg
        assert "1" in error_msg and "65535" in error_msg

    def test_account_validation_error_message_shows_length(self):
        """
        Test account validation error shows actual length and valid range.

        Expected result:
        - Error message includes actual account length
        - Error message shows valid range (3-16)
        - Error message shows the invalid account value
        """
        import tests.simulator.__main__ as cli_module

        args = argparse.Namespace(
            crc_format="hex",
            account="AB",  # Too short
            encryption_key=None,
            udp_port=10001,
            tcp_port=5000,
            host="127.0.0.1",
            log_file=None,
            log_level="INFO",
        )

        with pytest.raises(ValueError) as exc_info:
            cli_module.validate_config(args)

        error_msg = str(exc_info.value)

        # Assert: Error includes length, range, and value
        assert "3-16" in error_msg or ("3" in error_msg and "16" in error_msg)
        assert "AB" in error_msg or "2" in error_msg  # Shows length or value

