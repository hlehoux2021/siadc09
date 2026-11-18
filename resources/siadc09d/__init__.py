"""SIA DC-09 protocol daemon for the Jeedom siaDC09 plugin.

Entry point: siadc09d.py. Design: internal-docs/design/daemon-design.md.

Versioning (architecture.md § Versioning Strategy):
- DAEMON_VERSION mirrors plugin_info/info.json "pluginVersion" and must be
  bumped together with it before every Market publish
  (enforced by tests/level1/test_daemon_version.py)
"""

DAEMON_VERSION: str = "0.1.2"
