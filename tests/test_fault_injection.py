"""Tests for competition simulation and fault injection resilience."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.challenge_manager import ChallengeManager, ChallengeStatus
from backend.persistence import StatePersistence
from backend.prompts import ChallengeMeta
from backend.sandbox import configure_semaphore
from backend.simulation import CompetitionSimulator, FaultInjector


@pytest.mark.asyncio
async def test_fault_injection_429_recovery(tmp_path: Path) -> None:
    state_file = tmp_path / "sim_state.json"
    persistence = StatePersistence(state_file)
    manager = ChallengeManager(persistence=persistence)

    meta = ChallengeMeta(name="crypto_chall", category="crypto")
    entry = manager.register_challenge(tmp_path, meta)
    entry.status = ChallengeStatus.SOLVING

    # Inject 429 and verify transition to paused, then recovery
    success = await FaultInjector.inject_rate_limit(manager, "crypto_chall", cooldown_s=0.05)
    assert success is True
    assert entry.status is ChallengeStatus.TRIAGED


@pytest.mark.asyncio
async def test_fault_injection_container_crash_lease_recovery() -> None:
    configure_semaphore(2)

    # Incur container crash and confirm lease is released cleanly without hang
    success = await FaultInjector.inject_container_crash("pwn_crash", simulated_lease=True)
    assert success is True


def test_fault_injection_abrupt_process_exit_recovery(tmp_path: Path) -> None:
    state_file = tmp_path / "sim_state.json"
    persistence = StatePersistence(state_file)
    manager = ChallengeManager(persistence=persistence)

    meta = ChallengeMeta(name="rev_crash", category="reverse")
    entry = manager.register_challenge(tmp_path, meta)
    entry.status = ChallengeStatus.SOLVING
    entry.candidate_flag = "flag{partial_recovered}"
    manager.save_state()

    # Re-initialize manager simulating restart after process SIGKILL
    recovered_mgr = FaultInjector.simulate_crash_and_recover(persistence, "rev_crash")
    recovered = recovered_mgr.challenges["rev_crash"]

    # In-flight solving challenge resets to triaged so it can be picked up cleanly
    assert recovered.status is ChallengeStatus.TRIAGED
    # Candidate flag remains intact
    assert recovered.candidate_flag == "flag{partial_recovered}"


@pytest.mark.asyncio
async def test_simulated_competition_hours(tmp_path: Path) -> None:
    state_file = tmp_path / "sim_state.json"
    persistence = StatePersistence(state_file)
    manager = ChallengeManager(persistence=persistence)

    for i in range(3):
        meta = ChallengeMeta(name=f"chal_{i}", category="misc")
        manager.register_challenge(tmp_path / f"c_{i}", meta)

    sim = CompetitionSimulator(
        manager=manager,
        simulated_duration_s=14400.0,  # 4 hours
        time_scale=50000.0,           # fast time scale for unit test
    )
    report = await sim.run(inject_faults=True)

    assert report.total_challenges == 3
    assert report.faults_injected >= 2
    assert report.faults_recovered == report.faults_injected
    assert report.resilience_rate == 1.0

