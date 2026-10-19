"""Layer 3: heuristic prompt-injection detector.

Deterministic regex/keyword checks, with normalization for common obfuscation
tricks (HTML comments, zero-width characters, base64 blobs). An optional
LLM-classifier mode exists behind ``GuardConfig.detector_use_llm`` but is not
used in offline tests or CI -- offline mode only uses the heuristics below.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field

ZERO_WIDTH_CHARS = "​‌‍⁠﻿"

_INSTRUCTION_OVERRIDE_PATTERNS = [
    r"\bignore (?:all |any )?(?:previous|prior|above|the) instructions\b",
    r"\bdisregard (?:all |any )?(?:previous|prior|above) (?:instructions|rules)\b",
    r"\bnew instructions?\s*:",
    r"\byou are now\b",
    r"\bact as (?:if you are|an?)\b",
    r"\bsystem\s*:\s*",
    r"\byour (?:new|real|true) (?:task|goal|instructions?) (?:is|are)\b",
]

_EXFILTRATION_PATTERNS = [
    r"\bforward (?:all|every|this) (?:emails?|mail|messages?) to\b",
    r"\bsend (?:a )?copy (?:of (?:all|every)?\s*)?(?:emails?|this) to\b",
    r"\bbcc\b.{0,30}@",
    r"\bexfiltrat",
]

_IMPERSONATION_URGENCY_PATTERNS = [
    r"\burgent(?:ly)?\b.{0,40}\b(?:wire|transfer|gift card|credentials|password)\b",
    r"\bthis is (?:the )?ceo\b",
    r"\bdo not (?:tell|notify|inform) anyone\b",
    r"\bact immediately\b",
    r"\bkeep this confidential\b.{0,40}\b(?:send|transfer|wire)\b",
]

_MEMORY_POISONING_PATTERNS = [
    # Deliberately requires a trust/approval-delegation word, not bare "always", so that
    # ordinary preference statements ("remember that I always want X") aren't flagged --
    # see evals/injection/cases.jsonl BEN-05 for the control case this guards against.
    r"\bremember that\b.{0,80}\b(?:always (?:trust|approve)|auto[- ]?approve|auto[- ]?trust|never question)\b",
    r"\bupdate your (?:preferences|memory)\b.{0,40}\b(?:auto[- ]?approve|always trust)\b",
    r"\bfrom now on,? (?:always|automatically)\b",
]

_ROUTER_MANIPULATION_PATTERNS = [
    r"\bclassify this (?:email|message) as\b",
    r"\bmark this as (?:ignore|notify|resolved|spam)\b",
    r"\btriage(?:_email)? *\( *[\"']?(ignore|notify|respond)\b",
]

_CATEGORY_PATTERNS = {
    "instruction_override": _INSTRUCTION_OVERRIDE_PATTERNS,
    "data_exfiltration": _EXFILTRATION_PATTERNS,
    "impersonation_urgency": _IMPERSONATION_URGENCY_PATTERNS,
    "memory_poisoning": _MEMORY_POISONING_PATTERNS,
    "router_manipulation": _ROUTER_MANIPULATION_PATTERNS,
}

_COMPILED_CATEGORY_PATTERNS = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in _CATEGORY_PATTERNS.items()
}

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BASE64_BLOB_RE = re.compile(r"\b(?:[A-Za-z0-9+/]{24,}={0,2})\b")


@dataclass
class DetectionResult:
    """Outcome of scanning untrusted text for prompt-injection indicators."""

    matched: bool
    categories: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)
    hidden_instruction_techniques: list[str] = field(default_factory=list)
    score: float = 0.0


def _strip_zero_width(text: str) -> str:
    for ch in ZERO_WIDTH_CHARS:
        text = text.replace(ch, "")
    return text


def _decode_suspicious_base64(text: str) -> tuple[str, bool]:
    """Append the decoded text of any base64-looking blob so patterns can match it too."""
    found_decodable = False
    decoded_chunks = []
    for match in _BASE64_BLOB_RE.finditer(text):
        blob = match.group(0)
        try:
            decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
            decoded_text = decoded.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if decoded_text.isprintable() and len(decoded_text) > 8:
            decoded_chunks.append(decoded_text)
            found_decodable = True
    return "\n".join(decoded_chunks), found_decodable


def _normalize(text: str) -> tuple[str, list[str]]:
    """Strip common obfuscation so patterns still match the underlying text."""
    techniques: list[str] = []

    html_comments = _HTML_COMMENT_RE.findall(text)
    if html_comments:
        techniques.append("html_comment")
    # Keep comment contents visible to the matcher (that's often where the attack text is),
    # just drop the comment delimiters.
    normalized = _HTML_COMMENT_RE.sub(lambda m: m.group(0)[4:-3], text)

    if any(ch in normalized for ch in ZERO_WIDTH_CHARS):
        techniques.append("zero_width_chars")
    normalized = _strip_zero_width(normalized)

    decoded, found_b64 = _decode_suspicious_base64(normalized)
    if found_b64:
        techniques.append("base64")
        normalized = f"{normalized}\n{decoded}"

    return normalized, techniques


def scan(text: str) -> DetectionResult:
    """Scan untrusted text for prompt-injection indicators.

    Deterministic, offline, no network or LLM calls.
    """
    normalized, techniques = _normalize(text or "")

    categories: list[str] = []
    matched_patterns: list[str] = []
    for category, patterns in _COMPILED_CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(normalized):
                categories.append(category)
                matched_patterns.append(pattern.pattern)
                break

    if techniques:
        categories.append("hidden_instructions")

    matched = bool(categories)
    # Simple score: more distinct categories / techniques -> higher confidence.
    score = min(1.0, 0.4 * len(set(categories)) + 0.2 * len(techniques)) if matched else 0.0

    return DetectionResult(
        matched=matched,
        categories=sorted(set(categories)),
        matched_patterns=matched_patterns,
        hidden_instruction_techniques=techniques,
        score=score,
    )
