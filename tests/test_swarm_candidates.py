from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from backend.agents.swarm import ChallengeSwarm
from backend.solver_base import FLAG_CANDIDATE, FLAG_FOUND, SolverResult


def _result(status: str, flag: str) -> SolverResult:
    return SolverResult(
        flag=flag,
        status=status,
        findings_summary="",
        step_count=1,
        cost_usd=0.0,
        log_path="",
    )


def _swarm_for_run(
    *,
    no_submit: bool,
    run_solver: Callable[[str], Awaitable[SolverResult]],
) -> ChallengeSwarm:
    swarm = object.__new__(ChallengeSwarm)
    swarm.model_specs = ["candidate", "confirmed"]
    swarm.no_submit = no_submit
    swarm.cancel_event = asyncio.Event()
    swarm.winner = None
    swarm._run_solver = run_solver  # type: ignore[method-assign]
    return swarm


@pytest.mark.asyncio
async def test_submit_mode_does_not_cancel_race_for_unconfirmed_candidate() -> None:
    async def run_solver(model_spec: str) -> SolverResult:
        if model_spec == "candidate":
            return _result(FLAG_CANDIDATE, "flag{candidate}")
        await asyncio.sleep(0.01)
        return _result(FLAG_FOUND, "flag{confirmed}")

    result = await _swarm_for_run(no_submit=False, run_solver=run_solver).run()

    assert result is not None
    assert result.status == FLAG_FOUND
    assert result.flag == "flag{confirmed}"


@pytest.mark.asyncio
async def test_no_submit_mode_accepts_candidate_as_local_winner() -> None:
    cancelled = asyncio.Event()

    async def run_solver(model_spec: str) -> SolverResult:
        if model_spec == "candidate":
            return _result(FLAG_CANDIDATE, "flag{candidate}")
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
        return _result(FLAG_FOUND, "flag{late}")

    result = await _swarm_for_run(no_submit=True, run_solver=run_solver).run()

    assert result is not None
    assert result.status == FLAG_CANDIDATE
    assert result.flag == "flag{candidate}"
    assert cancelled.is_set()
