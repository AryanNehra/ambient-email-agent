import pytest

from email_assistant.security.config import GuardConfig
from email_assistant.security.tool_validator import validate_tool_call

CONFIG = GuardConfig(allowed_recipient_domains=("company.com",), max_recipients=5)


def test_write_email_to_allowed_domain_is_allowed():
    decision = validate_tool_call(
        "write_email", {"to": "colleague@company.com", "subject": "Hi", "content": "..."}, CONFIG
    )
    assert decision.allowed


def test_write_email_to_disallowed_domain_is_blocked():
    decision = validate_tool_call(
        "write_email", {"to": "attacker@evil.com", "subject": "Hi", "content": "..."}, CONFIG
    )
    assert not decision.allowed
    assert "allowed domains" in decision.reason


def test_write_email_with_unexpected_argument_is_blocked():
    decision = validate_tool_call(
        "write_email",
        {"to": "colleague@company.com", "subject": "Hi", "content": "...", "bcc": "attacker@evil.com"},
        CONFIG,
    )
    assert not decision.allowed
    assert "unexpected arguments" in decision.reason


def test_schedule_meeting_blocks_external_attendee():
    decision = validate_tool_call(
        "schedule_meeting",
        {
            "attendees": ["lance@company.com", "external@unverified.co"],
            "subject": "Sync",
            "duration_minutes": 30,
            "preferred_day": "2026-02-02",
            "start_time": 10,
        },
        CONFIG,
    )
    assert not decision.allowed


def test_schedule_meeting_blocks_too_many_recipients():
    attendees = [f"person{i}@company.com" for i in range(CONFIG.max_recipients + 1)]
    decision = validate_tool_call(
        "schedule_meeting",
        {
            "attendees": attendees,
            "subject": "All hands",
            "duration_minutes": 30,
            "preferred_day": "2026-02-02",
            "start_time": 10,
        },
        CONFIG,
    )
    assert not decision.allowed
    assert "max_recipients" in decision.reason


@pytest.mark.parametrize("tool_name", ["check_calendar_availability", "Question", "Done"])
def test_read_only_tools_always_allowed(tool_name):
    decision = validate_tool_call(tool_name, {"anything": "goes"}, CONFIG)
    assert decision.allowed
