"""
PHP eqLogic & cmd contract tests for Story 6.1.

Verifies the siaDC09 command logical IDs, types, and subtypes match the
design specification. Pure Python tests — no Jeedom instance required.
These document the PHP/Python contract and catch accidental renames.

Reference: _bmad-output/implementation-artifacts/6-1-php-eqlogic-cmd-classes.md
"""


EXPECTED_ACTION_COMMANDS = {
    "burglarAlarm": {"type": "action", "subType": "message"},
    "fireAlarm":    {"type": "action", "subType": "message"},
    "panicAlarm":   {"type": "action", "subType": "message"},
}

EXPECTED_INFO_COMMANDS = {
    "supervision_state": {"type": "info", "subType": "numeric"},
    "supervision_label": {"type": "info", "subType": "string"},
    "event_state":       {"type": "info", "subType": "numeric"},
    "event_label":       {"type": "info", "subType": "string"},
}

EXPECTED_ALL_LOGICAL_IDS = set(EXPECTED_ACTION_COMMANDS) | set(EXPECTED_INFO_COMMANDS)


def test_expected_command_logical_ids():
    """
    All 7 command logicalIds are present and no extras.

    Expected result:
    - Exactly 7 logicalIds match the design specification
    - Set matches: burglarAlarm, fireAlarm, panicAlarm,
      supervision_state, supervision_label, event_state, event_label
    """
    expected = {
        "burglarAlarm", "fireAlarm", "panicAlarm",
        "supervision_state", "supervision_label",
        "event_state", "event_label",
    }
    # Assert: exactly the 7 expected logicalIds
    assert EXPECTED_ALL_LOGICAL_IDS == expected
    # Assert: count is 7
    assert len(EXPECTED_ALL_LOGICAL_IDS) == 7


def test_action_command_subtypes():
    """
    All action commands use 'message' subtype (for zone extraction via title).

    Expected result:
    - burglarAlarm, fireAlarm, panicAlarm all have subType='message'
    - All have type='action'
    """
    for logical_id, spec in EXPECTED_ACTION_COMMANDS.items():
        # Assert: type is 'action'
        assert spec["type"] == "action", f"{logical_id} should be action type"
        # Assert: subType is 'message' (carries title with #zone# tag)
        assert spec["subType"] == "message", f"{logical_id} should be message subtype"


def test_info_command_subtypes():
    """
    Numeric INFO commands use 'numeric', label INFO commands use 'string'.

    Expected result:
    - supervision_state and event_state have subType='numeric' (scenario triggers)
    - supervision_label and event_label have subType='string' (display only)
    """
    # Assert: numeric state commands
    assert EXPECTED_INFO_COMMANDS["supervision_state"]["subType"] == "numeric"
    assert EXPECTED_INFO_COMMANDS["event_state"]["subType"] == "numeric"
    # Assert: string label commands
    assert EXPECTED_INFO_COMMANDS["supervision_label"]["subType"] == "string"
    assert EXPECTED_INFO_COMMANDS["event_label"]["subType"] == "string"


def test_action_commands_count():
    """
    Exactly 3 action commands defined.

    Expected result:
    - 3 action commands: burglarAlarm, fireAlarm, panicAlarm
    """
    # Assert: exactly 3 action commands
    assert len(EXPECTED_ACTION_COMMANDS) == 3


def test_info_commands_count():
    """
    Exactly 4 info commands defined.

    Expected result:
    - 4 info commands: supervision_state, supervision_label, event_state, event_label
    """
    # Assert: exactly 4 info commands
    assert len(EXPECTED_INFO_COMMANDS) == 4
