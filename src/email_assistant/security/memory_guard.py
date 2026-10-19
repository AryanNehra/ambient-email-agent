"""Layer 4: memory-write protection.

Memory updates (user/triage/response/calendar preferences) must only ever be
triggered by an explicit human-feedback event -- never as a side effect of
reading email content. ``human_feedback_scope`` marks the one place that is
true; ``GuardedStore`` refuses writes made outside that scope.

This module is a standalone, independently-testable primitive. Whether it is
threaded into a particular graph's store is a wiring decision made by the
graph; see the test suite for a characterization test that verifies the
course's existing ``email_assistant_hitl_memory.py`` only ever calls
``store.put`` from branches gated on human feedback.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_human_feedback_active: ContextVar[bool] = ContextVar("human_feedback_active", default=False)


class MemoryWriteBlockedError(RuntimeError):
    """Raised when a memory write is attempted outside a human-feedback scope."""


@contextmanager
def human_feedback_scope():
    """Mark the current block as triggered by a genuine human-feedback event."""
    token = _human_feedback_active.set(True)
    try:
        yield
    finally:
        _human_feedback_active.reset(token)


def is_memory_write_allowed() -> bool:
    """Return whether the current context is inside a human_feedback_scope()."""
    return _human_feedback_active.get()


def assert_memory_write_allowed(trigger_source: str = "unknown") -> None:
    """Raise MemoryWriteBlockedError unless inside a human_feedback_scope()."""
    if not is_memory_write_allowed():
        raise MemoryWriteBlockedError(
            f"Memory write blocked: triggered outside human_feedback_scope "
            f"(trigger_source={trigger_source!r}). Memory may only be updated in "
            f"direct response to human feedback, never from email content."
        )


class GuardedStore:
    """Wraps a BaseStore so ``.put`` only succeeds inside ``human_feedback_scope()``.

    All other methods (``.get``, ``.search``, ...) pass through unchanged.
    """

    def __init__(self, store: Any, *, enabled: bool = True):
        """Wrap ``store``; set ``enabled=False`` to disable the check (ablations)."""
        self._store = store
        self._enabled = enabled

    def put(self, namespace, key, value, *args, **kwargs):
        """Write to the wrapped store, enforcing the human-feedback-scope check first."""
        if self._enabled:
            assert_memory_write_allowed(trigger_source="guarded_store.put")
        return self._store.put(namespace, key, value, *args, **kwargs)

    def __getattr__(self, name):
        """Delegate any other attribute/method access to the wrapped store."""
        return getattr(self._store, name)
