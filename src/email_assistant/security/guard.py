"""Top-level orchestrator combining the layered guard.

``evaluate_tool_call`` is the main entry point tests and the eval runner use:
given a tool call a (possibly compromised) model produced, and the untrusted
email content that was in context when it produced it, decide whether the
call may proceed, and whether it must be force-reviewed by a human even if
otherwise allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from email_assistant.security import detector, tool_validator
from email_assistant.security.config import GuardConfig
from email_assistant.security.decision_log import GuardLogger

# Injection categories that must force human review even when the tool-call
# arguments themselves look superficially fine (e.g. impersonation/urgency
# attacks that target an in-policy recipient).
_FORCE_REVIEW_CATEGORIES = {
    "instruction_override",
    "impersonation_urgency",
    "hidden_instructions",
    "router_manipulation",
}


@dataclass
class GuardDecision:
    """Combined verdict: whether the call may proceed, and whether it must also be forced into human review."""

    allowed: bool
    force_review: bool
    tool_name: str
    reasons: list[str] = field(default_factory=list)
    detection: detector.DetectionResult | None = None

    @property
    def reason(self) -> str:
        """Human-readable summary of why the call was (not) allowed."""
        return "; ".join(self.reasons) if self.reasons else "ok"


def evaluate_tool_call(
    tool_name: str,
    args: dict,
    *,
    email_content: str,
    config: GuardConfig | None = None,
    logger: GuardLogger | None = None,
) -> GuardDecision:
    """Run the detector and tool validator over a proposed tool call."""
    config = config or GuardConfig()
    logger = logger or GuardLogger()
    reasons: list[str] = []
    allowed = True
    force_review = False
    detection_result: detector.DetectionResult | None = None

    if config.layer_detector:
        detection_result = detector.scan(email_content)
        if detection_result.matched:
            flagged = set(detection_result.categories) & _FORCE_REVIEW_CATEGORIES
            if flagged:
                force_review = True
                reasons.append(f"detector flagged categories: {sorted(flagged)}")
        logger.record(
            "detector",
            subject=tool_name,
            allowed=not (detection_result.matched and force_review),
            reason=(
                f"categories={detection_result.categories}" if detection_result.matched else "clean"
            ),
            score=detection_result.score,
        )

    if config.layer_tool_validator:
        tool_decision = tool_validator.validate_tool_call(tool_name, args, config)
        if not tool_decision.allowed:
            allowed = False
            reasons.append(tool_decision.reason)
        logger.record(
            "tool_validator",
            subject=tool_name,
            allowed=tool_decision.allowed,
            reason=tool_decision.reason,
        )

    return GuardDecision(
        allowed=allowed,
        force_review=force_review,
        tool_name=tool_name,
        reasons=reasons,
        detection=detection_result,
    )


def evaluate_triage_override(
    classification: str,
    *,
    email_content: str,
    config: GuardConfig | None = None,
    logger: GuardLogger | None = None,
) -> tuple[str, GuardDecision]:
    """Guard the triage classification itself against router-manipulation attempts.

    If the email content contains an attempt to manipulate the router (e.g.
    "classify this as ignore", or a fake system message trying to silence the
    agent), downgrade an "ignore" classification to "notify" so a human still
    sees it, regardless of what the router LLM decided.
    """
    config = config or GuardConfig()
    logger = logger or GuardLogger()

    if not config.layer_detector:
        return classification, GuardDecision(allowed=True, force_review=False, tool_name="triage_router")

    detection_result = detector.scan(email_content)
    manipulated = "router_manipulation" in detection_result.categories
    final = classification
    if manipulated and classification == "ignore":
        final = "notify"

    logger.record(
        "detector",
        subject="triage_router",
        allowed=not manipulated,
        reason=(
            f"router manipulation detected, overrode '{classification}' -> '{final}'"
            if manipulated and final != classification
            else ("router manipulation detected" if manipulated else "clean")
        ),
    )

    return final, GuardDecision(
        allowed=not manipulated,
        force_review=manipulated,
        tool_name="triage_router",
        reasons=[] if not manipulated else ["router_manipulation detected"],
        detection=detection_result,
    )
