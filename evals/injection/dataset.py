"""Loader for the prompt-injection attack + benign-control dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASES_PATH = Path(__file__).parent / "cases.jsonl"


@dataclass
class Case:
    """One attack or benign-control case from cases.jsonl."""

    id: str
    category: str
    is_benign: bool
    email: dict[str, str]
    attack_goal: str
    expected_safe_behavior: str
    malicious_tool_call: dict[str, Any] | None
    memory_write_attempt: bool

    @property
    def email_content(self) -> str:
        """Render the email as plain text, the way the detector scans it."""
        e = self.email
        return f"From: {e['author']}\nTo: {e['to']}\nSubject: {e['subject']}\n\n{e['email_thread']}"


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    """Load all cases from a cases.jsonl file."""
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            cases.append(
                Case(
                    id=raw["id"],
                    category=raw["category"],
                    is_benign=raw["is_benign"],
                    email=raw["email"],
                    attack_goal=raw["attack_goal"],
                    expected_safe_behavior=raw["expected_safe_behavior"],
                    malicious_tool_call=raw.get("malicious_tool_call"),
                    memory_write_attempt=raw.get("memory_write_attempt", False),
                )
            )
    return cases
