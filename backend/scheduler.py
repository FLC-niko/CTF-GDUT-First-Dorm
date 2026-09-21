"""Dynamic tiered scheduler for Fast, Expert, and Racing solvers.

Directs challenges to the appropriate model tier based on triage results,
past attempts, token budgets, and concurrency constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.challenge_manager import ChallengeEntry, ChallengeStatus
from backend.models import DEFAULT_MODELS

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TieredModelConfig:
    fast_models: tuple[str, ...] = ("codex/gpt-5.4-mini",)
    expert_models: tuple[str, ...] = ("codex/gpt-5.4",)
    racing_models: tuple[str, ...] = (
        "codex/gpt-5.4",
        "cpa-responses/gemini-2.5-pro",
        "go-messages/deepseek-r1",
    )
    fast_timeout_s: int = 300
    expert_timeout_s: int = 900
    racing_timeout_s: int = 1800

    @classmethod
    def from_settings(cls, settings: Any) -> TieredModelConfig:
        configured_models = tuple(getattr(settings, "models", ()) or ())
        if not configured_models:
            configured_models = tuple(DEFAULT_MODELS)

        # Distribute configured models into fast, expert, and racing tiers
        fast = [m for m in configured_models if any(s in m.lower() for s in ("mini", "flash", "small", "lite", "7b", "8b"))]
        expert = [m for m in configured_models if m not in fast]

        if not fast:
            fast = list(configured_models[:1])
        if not expert:
            expert = list(configured_models[:1])

        racing = list(dict.fromkeys(expert + fast))
        return cls(
            fast_models=tuple(fast),
            expert_models=tuple(expert),
            racing_models=tuple(racing),
        )


class TieredScheduler:
    """Assigns solver models, concurrency limits, and timeouts by challenge tier."""

    def __init__(self, config: TieredModelConfig) -> None:
        self.config = config

    def select_models(self, entry: ChallengeEntry) -> list[str]:
        """Select models based on current tier and history."""
        if entry.tier == "fast":
            models = [self.config.fast_models[0]]
        elif entry.tier == "expert":
            models = [self.config.expert_models[0]]
        elif entry.tier == "racing":
            models = list(self.config.racing_models)
        else:
            models = [self.config.fast_models[0]]

        logger.info(
            "Scheduler dispatch for '%s': tier=%s, models=%s",
            entry.name,
            entry.tier,
            models,
        )
        return models

    def get_timeout_s(self, entry: ChallengeEntry) -> int:
        if entry.tier == "fast":
            return self.config.fast_timeout_s
        if entry.tier == "expert":
            return self.config.expert_timeout_s
        return self.config.racing_timeout_s

