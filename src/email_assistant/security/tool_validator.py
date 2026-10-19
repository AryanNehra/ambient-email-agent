"""Layer 2: deterministic tool-call validator.

Runs before any tool executes (regardless of what the LLM decided) and checks
the call's arguments against a fixed policy: recipient allow-list, max
recipients, no unexpected/extra arguments, and (for scheduling) attendees
drawn only from known contacts or the allow-listed domain. This layer does
not depend on the LLM "deciding" to be safe -- it blocks policy-violating
calls even if a compromised model emitted them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from email_assistant.security.config import GuardConfig

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_EXPECTED_ARGS = {
    "write_email": {"to", "subject", "content"},
    "schedule_meeting": {"attendees", "subject", "duration_minutes", "preferred_day", "start_time"},
}


@dataclass
class ToolCallDecision:
    """Whether a single tool call passes the deterministic policy checks."""

    allowed: bool
    tool_name: str
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """Human-readable summary of why the call was (not) allowed."""
        return "; ".join(self.reasons) if self.reasons else "ok"


def _extract_recipients(value: Any) -> list[str]:
    if isinstance(value, str):
        return _EMAIL_RE.findall(value)
    if isinstance(value, (list, tuple)):
        recipients: list[str] = []
        for item in value:
            recipients.extend(_extract_recipients(item))
        return recipients
    return []


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def _check_unexpected_args(tool_name: str, args: dict) -> list[str]:
    expected = _EXPECTED_ARGS.get(tool_name)
    if expected is None:
        return []
    unexpected = set(args) - expected
    if unexpected:
        return [f"unexpected arguments for {tool_name}: {sorted(unexpected)}"]
    return []


def _check_recipients(
    tool_name: str, recipients: list[str], config: GuardConfig
) -> list[str]:
    reasons = []
    if len(recipients) > config.max_recipients:
        reasons.append(
            f"{tool_name} targets {len(recipients)} recipients, exceeds max_recipients={config.max_recipients}"
        )
    disallowed = [r for r in recipients if _domain(r) not in config.allowed_recipient_domains]
    if disallowed:
        reasons.append(
            f"{tool_name} targets recipient(s) outside allowed domains {config.allowed_recipient_domains}: {disallowed}"
        )
    return reasons


def validate_tool_call(
    tool_name: str, args: dict, config: GuardConfig | None = None
) -> ToolCallDecision:
    """Validate a tool call's arguments against policy.

    Only ``write_email`` and ``schedule_meeting`` carry side effects that can
    reach outside the user's control (sending content, booking a meeting with
    other people); other tools (``check_calendar_availability``, ``Question``,
    ``Done``) are read-only/informational and are always allowed.
    """
    config = config or GuardConfig()
    reasons: list[str] = []

    if tool_name == "write_email":
        reasons += _check_unexpected_args(tool_name, args)
        recipients = _extract_recipients(args.get("to"))
        if not recipients:
            reasons.append("write_email call has no parseable recipient address")
        else:
            reasons += _check_recipients(tool_name, recipients, config)

    elif tool_name == "schedule_meeting":
        reasons += _check_unexpected_args(tool_name, args)
        attendees = args.get("attendees") or []
        recipients = _extract_recipients(attendees)
        if not recipients:
            reasons.append("schedule_meeting call has no parseable attendee addresses")
        else:
            reasons += _check_recipients(tool_name, recipients, config)
            if config.known_calendar_contacts:
                unknown = [
                    r for r in recipients if r.lower() not in {
                        c.lower() for c in config.known_calendar_contacts
                    }
                ]
                if unknown:
                    reasons.append(f"schedule_meeting includes unknown contacts: {unknown}")

    return ToolCallDecision(allowed=not reasons, tool_name=tool_name, reasons=reasons)
