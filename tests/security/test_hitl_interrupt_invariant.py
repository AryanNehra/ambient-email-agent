"""Integration test: even a fully compromised model cannot get write_email or
schedule_meeting to execute without passing through the HITL interrupt first.

This is a structural property of email_assistant_hitl.py's graph (the course
code), not something our guard module adds -- we test it here because the
guard's "always force HITL for send/schedule" claim in the threat model
depends on it, and because the compromised-model scenario is exactly what
evals/injection/cases.jsonl's malicious_tool_call entries represent.
"""

import uuid

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

import email_assistant.email_assistant_hitl as hitl_module
from email_assistant.security.config import GuardConfig
from email_assistant.security.guard import evaluate_tool_call
from evals.injection.dataset import load_cases

FULL_GUARD = GuardConfig(
    layer_framing=True, layer_tool_validator=True, layer_detector=True, layer_memory_protection=True
)

TOOL_CALL_CASES = [c for c in load_cases() if not c.is_benign and c.malicious_tool_call is not None]


class _FakeRouterResult:
    classification = "respond"
    reasoning = "fake router always sends to response agent"


@pytest.fixture
def compromised_graph(monkeypatch):
    """A compiled email_assistant_hitl graph where both LLMs are monkeypatched
    to always emit a given malicious tool call, simulating a model that has
    been fully fooled by the injected email content."""

    def _build(tool_call: dict):
        monkeypatch.setattr(hitl_module, "llm_router", _StubInvoke(_FakeRouterResult()))
        fake_ai_message = AIMessage(
            content="",
            tool_calls=[{**tool_call, "id": "call_1", "type": "tool_call"}],
        )
        monkeypatch.setattr(hitl_module, "llm_with_tools", _StubInvoke(fake_ai_message))
        checkpointer = MemorySaver()
        return hitl_module.overall_workflow.compile(checkpointer=checkpointer)

    return _build


class _StubInvoke:
    def __init__(self, return_value):
        self._return_value = return_value

    def invoke(self, _messages):
        return self._return_value


@pytest.mark.parametrize("case", TOOL_CALL_CASES, ids=[c.id for c in TOOL_CALL_CASES])
def test_compromised_model_tool_call_pauses_at_hitl_interrupt(compromised_graph, case):
    call = case.malicious_tool_call
    graph = compromised_graph({"name": call["name"], "args": call["args"]})
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = graph.invoke({"email_input": case.email}, config=thread_config)

    # The tool must never have executed -- the graph is paused mid-flight,
    # waiting on human approval, regardless of what the (compromised) model asked for.
    assert "__interrupt__" in result
    state = graph.get_state(thread_config)
    assert state.next == ("response_agent",)

    # And independently, our deterministic guard agrees this call should be blocked --
    # i.e. even if a human reviewer rubber-stamped it, the validator would still refuse.
    decision = evaluate_tool_call(
        call["name"], call["args"], email_content=case.email_content, config=FULL_GUARD
    )
    assert not decision.allowed or decision.force_review
