"""Wraps the course's existing LLM-as-judge (RESPONSE_CRITERIA_SYSTEM_PROMPT +
CriteriaGrade structured output from tests/test_response.py) so the
calibration analysis reuses the real rubric rather than inventing a new one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from email_assistant.eval.prompts import RESPONSE_CRITERIA_SYSTEM_PROMPT

# A paraphrased rephrasing of the same instructions as RESPONSE_CRITERIA_SYSTEM_PROMPT,
# used only for the rubric-wording-sensitivity bias probe (evals/judge_calibration/analyze.py).
# The underlying per-item rubric criteria (bullet points) are never altered -- only this
# wrapper's wording changes.
RESPONSE_CRITERIA_SYSTEM_PROMPT_PARAPHRASED = """You're acting as a quality reviewer for an AI email assistant that acts on a user's behalf.

You'll be shown an email the assistant received, its full response (including any tools it
called, like write_email, schedule_meeting, check_calendar_availability, or done), and a
checklist of requirements the response needs to satisfy.

Go through the checklist point by point. A response only passes if it satisfies every single
point -- partial credit doesn't count. For each point, quote the part of the response that
makes you confident it was (or wasn't) met. If even one point fails, the overall result is
'False'.

Be consistent and strict; this output feeds into automated test reporting."""


@dataclass
class JudgeResult:
    label: str  # "pass" | "fail"
    justification: str


class Judge(Protocol):
    def grade(self, *, agent_response: str, criteria: str) -> JudgeResult: ...


class FakeJudge:
    """Deterministic stand-in for offline tests: looks up a fixed verdict per
    item id, or falls back to a keyword heuristic if the id isn't registered."""

    def __init__(self, verdicts: dict[str, str] | None = None):
        self._verdicts = verdicts or {}

    def grade_item_id(self, item_id: str, *, agent_response: str, criteria: str) -> JudgeResult:
        if item_id in self._verdicts:
            label = self._verdicts[item_id]
        else:
            label = "fail" if "no action" in agent_response.lower() else "pass"
        return JudgeResult(label=label, justification=f"fake judge verdict for {item_id}")


class CriteriaGradeJudge:
    """The real judge: an LLM with structured output, as used in tests/test_response.py."""

    def __init__(self, model: str = "openai:gpt-4o", *, system_prompt: str = RESPONSE_CRITERIA_SYSTEM_PROMPT):
        from langchain.chat_models import init_chat_model
        from pydantic import BaseModel, Field

        class CriteriaGrade(BaseModel):
            grade: bool = Field(description="Does the response meet the provided criteria?")
            justification: str = Field(description="Justification for the grade.")

        self._llm = init_chat_model(model).with_structured_output(CriteriaGrade)
        self._system_prompt = system_prompt

    def grade(self, *, agent_response: str, criteria: str) -> JudgeResult:
        result = self._llm.invoke(
            [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"\n\n Response criteria: {criteria} \n\n "
                        f"Assistant's response: \n\n {agent_response} \n\n "
                        "Evaluate whether the assistant's response meets the criteria and "
                        "provide justification for your evaluation."
                    ),
                },
            ]
        )
        return JudgeResult(label="pass" if result.grade else "fail", justification=result.justification)
