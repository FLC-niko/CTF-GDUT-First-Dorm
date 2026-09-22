"""Dynamic tiered scheduler for Fast, Expert, and Racing solvers.

Directs challenges to the appropriate model tier based on triage results,
past attempts, token budgets, and concurrency constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.challenge_manager import ChallengeEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TieredModelConfig:
    fast_models: tuple[str, ...] = ()
    expert_models: tuple[str, ...] = ()
    racing_models: tuple[str, ...] = ()
    fast_timeout_s: int = 300
    expert_timeout_s: int = 900
    racing_timeout_s: int = 1800

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        available_models: list[str] | tuple[str, ...] = (),
    ) -> TieredModelConfig:
        """Build explicit roles without inferring capability from model names.

        Comma-separated role settings take precedence.  When they are omitted,
        CLI order is only a conservative operational fallback: first model for
        Fast, second (or first) for Expert, and the complete configured set for
        Racing.  Benchmark results should eventually replace this fallback.
        """

        available = tuple(dict.fromkeys(str(model) for model in available_models if model))

        def configured(name: str) -> tuple[str, ...]:
            raw = str(getattr(settings, name, "") or "")
            return tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))

        fast = configured("scheduler_fast_models")
        expert = configured("scheduler_expert_models")
        racing = configured("scheduler_racing_models")
        allowed = set(available)
        for role, models in (("fast", fast), ("expert", expert), ("racing", racing)):
            unknown = [model for model in models if model not in allowed]
            if unknown:
                raise ValueError(
                    f"Scheduler {role} models must also be present in --models: {unknown}"
                )

        if available:
            fast = fast or available[:1]
            expert = expert or available[1:2] or available[:1]
            racing = racing or available
        return cls(
            fast_models=fast,
            expert_models=expert,
            racing_models=racing,
            fast_timeout_s=int(getattr(settings, "scheduler_fast_timeout_seconds", 300)),
            expert_timeout_s=int(getattr(settings, "scheduler_expert_timeout_seconds", 900)),
            racing_timeout_s=int(getattr(settings, "scheduler_racing_timeout_seconds", 1800)),
        )


class TieredScheduler:
    """Assigns solver models, concurrency limits, and timeouts by challenge tier."""

    def __init__(self, config: TieredModelConfig) -> None:
        self.config = config

    def select_models(self, entry: ChallengeEntry) -> list[str]:
        """Select models based on current tier and history."""
        if entry.tier == "fast":
            models = list(self.config.fast_models[:1])
        elif entry.tier == "expert":
            models = list(self.config.expert_models[:1])
        elif entry.tier == "racing":
            models = list(self.config.racing_models)
        else:
            models = list(self.config.fast_models[:1])

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
