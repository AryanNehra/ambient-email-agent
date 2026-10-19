"""Structured logging of every guard decision: what was checked, why, and the outcome."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("email_assistant.security")
logger.addHandler(logging.NullHandler())  # library default: silent unless the host app configures a handler


@dataclass
class Decision:
    """A single guard layer's verdict on one subject (a tool call or email)."""

    layer: str
    subject: str
    allowed: bool
    reason: str
    extra: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Flatten the decision (including its extra fields) into a plain dict."""
        return {
            "layer": self.layer,
            "subject": self.subject,
            "allowed": self.allowed,
            "reason": self.reason,
            "timestamp": self.timestamp,
            **self.extra,
        }


class GuardLogger:
    """Collects decisions in-memory (for tests/eval runs).

    Also emits them via the standard logging module.
    """

    def __init__(self):
        """Start with an empty, in-memory decision log."""
        self._decisions: list[Decision] = []

    def record(
        self, layer: str, subject: str, allowed: bool, reason: str, **extra: Any
    ) -> Decision:
        """Record a decision, append it in-memory, and emit it via stdlib logging."""
        decision = Decision(layer=layer, subject=subject, allowed=allowed, reason=reason, extra=extra)
        self._decisions.append(decision)
        level = logging.INFO if allowed else logging.WARNING
        logger.log(level, "guard_decision", extra={"guard_decision": decision.to_dict()})
        return decision

    @property
    def decisions(self) -> list[Decision]:
        """Return the decisions recorded so far, in order."""
        return list(self._decisions)

    def as_dicts(self) -> list[dict[str, Any]]:
        """Return all recorded decisions as plain dicts, e.g. for JSON output."""
        return [d.to_dict() for d in self._decisions]

    def clear(self) -> None:
        """Discard all recorded decisions."""
        self._decisions.clear()
