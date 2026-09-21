"""Shared dependency types — avoids circular imports between agents and tools."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.control.knowledge_store import KnowledgeStore
from backend.control.policy_engine import PolicyEngine
from backend.control.state import CompetitionState
from backend.control.strategy_state import ChallengeStrategyState
from backend.control.working_memory import WorkingMemoryStore
from backend.cost_tracker import CostTracker
from backend.platforms.base import CompetitionPlatformClient
from backend.provider_runtime import ProviderRuntimeGovernor
from backend.sandbox import DockerSandbox

if TYPE_CHECKING:
    from backend.message_bus import ChallengeMessageBus

# Type for the deduped submit callback: (flag) -> (display, is_confirmed)
SubmitFn = Callable[[str], Coroutine[Any, Any, tuple[str, bool]]]
ReleasedEnvKey = tuple[str, str, str, str]


@dataclass
class SolverDeps:
    sandbox: DockerSandbox
    ctfd: CompetitionPlatformClient
    challenge_dir: str
    challenge_name: str
    workspace_dir: str
    use_vision: bool
    cost_tracker: CostTracker | None = None
    challenge_ref: Any = None
    confirmed_flag: str | None = None
    message_bus: ChallengeMessageBus | None = None
    model_spec: str = ""
    submit_fn: SubmitFn | None = None  # Deduped flag submission via swarm
    no_submit: bool = False
    notify_coordinator: Callable[[str], Coroutine[Any, Any, None]] | None = None


@dataclass
class CoordinatorDeps:
    ctfd: CompetitionPlatformClient
    cost_tracker: CostTracker
    settings: Any
    model_specs: list[str] = field(default_factory=list)
    challenges_root: str = "challenges"
    no_submit: bool = False
    max_concurrent_challenges: int = 10
    working_memory_store: WorkingMemoryStore = field(default_factory=WorkingMemoryStore)
    knowledge_store: KnowledgeStore = field(default_factory=KnowledgeStore)
    strategy_states: dict[str, ChallengeStrategyState] = field(default_factory=dict)
    policy_engine: PolicyEngine | None = None
    provider_runtime: ProviderRuntimeGovernor | None = None

    msg_port: int = 0  # 0 = auto-pick free port

    # Runtime state
    runtime_state: CompetitionState = field(default_factory=CompetitionState)
    coordinator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    operator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    swarms: dict[str, Any] = field(default_factory=dict)
    swarm_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    released_envs: set[ReleasedEnvKey] = field(default_factory=set)
    challenge_dirs: dict[str, str] = field(default_factory=dict)
    challenge_metas: dict[str, Any] = field(default_factory=dict)
    trace_offsets: dict[str, int] = field(default_factory=dict)
    trace_pending_lines: dict[str, bytes] = field(default_factory=dict)
    trace_file_tokens: dict[str, tuple[int, int]] = field(default_factory=dict)

    challenge_manager: Any = None
    scheduler: Any = None

    def __post_init__(self) -> None:
        if self.policy_engine is None:
            self.policy_engine = PolicyEngine(
                max_concurrent_challenges=self.max_concurrent_challenges,
                bump_cooldown_seconds=60,
                stall_seconds=180,
            )
        if self.provider_runtime is None:
            self.provider_runtime = ProviderRuntimeGovernor.from_settings(self.settings)
        if self.challenge_manager is None:
            from backend.challenge_manager import ChallengeManager
            from backend.persistence import StatePersistence

            state_file = getattr(self.settings, "state_file", "") or "competition_state.json"
            persistence = StatePersistence(state_file)
            self.challenge_manager = ChallengeManager(
                persistence=persistence,
                max_concurrent_challenges=self.max_concurrent_challenges,
            )
        if self.scheduler is None:
            from backend.scheduler import TieredModelConfig, TieredScheduler

            tiered_config = TieredModelConfig.from_settings(self.settings)
            self.scheduler = TieredScheduler(tiered_config)
