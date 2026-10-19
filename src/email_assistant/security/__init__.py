"""Layered prompt-injection guard: framing, tool-call validation, detection, and memory protection."""

from email_assistant.security.config import GuardConfig
from email_assistant.security.decision_log import GuardLogger
from email_assistant.security.framing import frame_untrusted
from email_assistant.security.guard import (
    GuardDecision,
    evaluate_tool_call,
    evaluate_triage_override,
)
from email_assistant.security.memory_guard import (
    GuardedStore,
    MemoryWriteBlockedError,
    human_feedback_scope,
    is_memory_write_allowed,
)

__all__ = [
    "GuardConfig",
    "GuardLogger",
    "frame_untrusted",
    "GuardDecision",
    "evaluate_tool_call",
    "evaluate_triage_override",
    "GuardedStore",
    "MemoryWriteBlockedError",
    "human_feedback_scope",
    "is_memory_write_allowed",
]
