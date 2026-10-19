"""Guard configuration: per-layer on/off switches for ablation studies."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class GuardConfig:
    """Per-layer configuration for the prompt-injection guard.

    Each ``layer_*`` flag can be toggled independently so the eval runner can
    report ablations (each layer alone, and all layers together).
    """

    layer_framing: bool = True
    layer_tool_validator: bool = True
    layer_detector: bool = True
    layer_memory_protection: bool = True
    detector_use_llm: bool = False
    allowed_recipient_domains: tuple[str, ...] = ("company.com",)
    known_calendar_contacts: tuple[str, ...] = field(default_factory=tuple)
    max_recipients: int = 5

    @classmethod
    def from_env(cls) -> GuardConfig:
        """Build a config from GUARD_* environment variables, defaulting to all layers on."""
        return cls(
            layer_framing=_env_bool("GUARD_LAYER_FRAMING", True),
            layer_tool_validator=_env_bool("GUARD_LAYER_TOOL_VALIDATOR", True),
            layer_detector=_env_bool("GUARD_LAYER_DETECTOR", True),
            layer_memory_protection=_env_bool("GUARD_LAYER_MEMORY_PROTECTION", True),
            detector_use_llm=_env_bool("GUARD_DETECTOR_USE_LLM", False),
            allowed_recipient_domains=_env_list(
                "GUARD_ALLOWED_RECIPIENT_DOMAINS", ("company.com",)
            ),
        )

    @classmethod
    def all_off(cls) -> GuardConfig:
        """Return a config with every layer disabled (the ungarded baseline)."""
        return cls(
            layer_framing=False,
            layer_tool_validator=False,
            layer_detector=False,
            layer_memory_protection=False,
        )

    @classmethod
    def only(cls, layer: str) -> GuardConfig:
        """Return a config with exactly one layer on (for ablations)."""
        base = cls.all_off()
        if layer not in {
            "layer_framing",
            "layer_tool_validator",
            "layer_detector",
            "layer_memory_protection",
        }:
            raise ValueError(f"Unknown layer: {layer}")
        return dataclasses.replace(base, **{layer: True})
