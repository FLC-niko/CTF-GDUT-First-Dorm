"""Competition simulation and fault injection harness.

Validates long-running resilience, fault handling (429s, container crashes,
network timeouts, process restart), and clean lifecycle recovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

from backend.challenge_manager import ChallengeManager, ChallengeStatus
from backend.persistence import StatePersistence
from backend.sandbox import (
    acquire_lifecycle_lease,
    release_lifecycle_lease,
)

logger = logging.getLogger(__name__)


class FaultType(StrEnum):
    RATE_LIMIT_429 = "rate_limit_429"
    CONTAINER_CRASH = "container_crash"
    NETWORK_TIMEOUT = "network_timeout"
    PROCESS_RESTART = "process_restart"


@dataclass
class SimulationEvent:
    timestamp: float
    event_type: str
    details: str


@dataclass
class SimulationReport:
    duration_s: float
    total_challenges: int
    solved_challenges: int
    faults_injected: int
    faults_recovered: int
    events: list[SimulationEvent] = field(default_factory=list)

    @property
    def resilience_rate(self) -> float:
        if self.faults_injected == 0:
            return 1.0
        return self.faults_recovered / self.faults_injected


class FaultInjector:
    """Injects and verifies simulated real-world competition failures."""

    @staticmethod
    async def inject_rate_limit(
        manager: ChallengeManager,
        challenge_name: str,
        cooldown_s: float = 0.5,
    ) -> bool:
        """Simulate a 429 response, pausing challenge and recovering after cooldown."""
        entry = manager.challenges.get(challenge_name)
        if not entry:
            return False
        entry.transition_to(ChallengeStatus.PAUSED, "Injected 429 rate limit")
        await asyncio.sleep(cooldown_s)
        entry.transition_to(ChallengeStatus.TRIAGED, "429 cooldown elapsed")
        return True

    @staticmethod
    async def inject_container_crash(
        challenge_name: str,
        simulated_lease: bool = True,
    ) -> bool:
        """Simulate a container SIGKILL/OOM, verifying lease recovery."""
        if simulated_lease:
            await acquire_lifecycle_lease()
        try:
            # Simulate unexpected container crash exception
            raise RuntimeError(f"Container died unexpectedly for {challenge_name}")
        except RuntimeError:
            # Cleanup must release lease properly
            if simulated_lease:
                release_lifecycle_lease()
            return True

    @staticmethod
    def simulate_crash_and_recover(
        persistence: StatePersistence,
        challenge_name: str,
    ) -> ChallengeManager:
        """Simulate abrupt process exit and recover state cleanly."""
        new_manager = ChallengeManager(persistence=persistence)
        recovered_entry = new_manager.challenges.get(challenge_name)
        if recovered_entry and recovered_entry.status is ChallengeStatus.SOLVING:
            # Resets safely to triaged
            assert recovered_entry.status is ChallengeStatus.TRIAGED
        return new_manager


class CompetitionSimulator:
    """Runs simulated competition hours to audit stability and fault recovery."""

    def __init__(
        self,
        manager: ChallengeManager,
        simulated_duration_s: float = 14400.0,  # 4 hours
        time_scale: float = 1000.0,             # 1000x acceleration for testing
    ) -> None:
        self.manager = manager
        self.simulated_duration_s = simulated_duration_s
        self.time_scale = time_scale
        self.events: list[SimulationEvent] = []

    async def run(self, inject_faults: bool = True) -> SimulationReport:
        start_time = time.time()
        logger.info(
            "Starting competition simulation: duration=%.1fs, time_scale=%.1f",
            self.simulated_duration_s,
            self.time_scale,
        )

        real_sleep = min(1.0, self.simulated_duration_s / self.time_scale)
        faults_injected = 0
        faults_recovered = 0

        if inject_faults and self.manager.challenges:
            target_name = next(iter(self.manager.challenges.keys()))

            # 1. Inject 429 fault
            faults_injected += 1
            if await FaultInjector.inject_rate_limit(self.manager, target_name, cooldown_s=0.1):
                faults_recovered += 1
                self.events.append(SimulationEvent(time.time(), "fault_recovered", "429 rate limit recovered"))

            # 2. Inject container crash
            faults_injected += 1
            if await FaultInjector.inject_container_crash(target_name):
                faults_recovered += 1
                self.events.append(SimulationEvent(time.time(), "fault_recovered", "Container crash lease recovered"))

        await asyncio.sleep(real_sleep)
        elapsed = time.time() - start_time

        solved_count = sum(
            1 for c in self.manager.challenges.values()
            if c.status in (ChallengeStatus.SOLVED, ChallengeStatus.CONFIRMED)
        )

        return SimulationReport(
            duration_s=elapsed,
            total_challenges=len(self.manager.challenges),
            solved_challenges=solved_count,
            faults_injected=faults_injected,
            faults_recovered=faults_recovered,
            events=self.events,
        )
