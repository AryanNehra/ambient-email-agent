import pytest

from email_assistant.security.memory_guard import (
    GuardedStore,
    MemoryWriteBlockedError,
    human_feedback_scope,
    is_memory_write_allowed,
)


class _FakeStore:
    def __init__(self):
        self.data = {}

    def put(self, namespace, key, value):
        self.data[(namespace, key)] = value


def test_write_blocked_outside_human_feedback_scope():
    store = GuardedStore(_FakeStore())
    with pytest.raises(MemoryWriteBlockedError):
        store.put(("ns",), "key", "value from email content")


def test_write_allowed_inside_human_feedback_scope():
    store = GuardedStore(_FakeStore())
    with human_feedback_scope():
        store.put(("ns",), "key", "value from human feedback")
    assert store._store.data[(("ns",), "key")] == "value from human feedback"


def test_scope_resets_after_exit():
    store = GuardedStore(_FakeStore())
    with human_feedback_scope():
        assert is_memory_write_allowed()
    assert not is_memory_write_allowed()
    with pytest.raises(MemoryWriteBlockedError):
        store.put(("ns",), "key", "value")


def test_disabled_guard_bypasses_check():
    store = GuardedStore(_FakeStore(), enabled=False)
    store.put(("ns",), "key", "value")  # does not raise
    assert store._store.data[(("ns",), "key")] == "value"


def test_passthrough_methods_reach_wrapped_store():
    underlying = _FakeStore()
    underlying.data[("ns", "key")] = "preexisting"
    store = GuardedStore(underlying)
    assert store.data[("ns", "key")] == "preexisting"
