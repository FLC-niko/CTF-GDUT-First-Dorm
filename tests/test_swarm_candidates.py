from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from backend.agents.swarm import ChallengeSwarm
from backend.message_bus import ChallengeMessageBus
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


@pytest.mark.asyncio
async def test_cancelling_swarm_cancels_and_waits_for_all_solver_tasks() -> None:
    started = 0
    all_started = asyncio.Event()
    cancelled = 0

    async def run_solver(_model_spec: str) -> SolverResult:
        nonlocal started, cancelled
        started += 1
        if started == 2:
            all_started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled += 1

    swarm = _swarm_for_run(no_submit=True, run_solver=run_solver)
    task = asyncio.create_task(swarm.run())
    await asyncio.wait_for(all_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert swarm.cancel_event.is_set()
    assert cancelled == 2


@pytest.mark.asyncio
async def test_new_solver_receives_findings_from_previous_tier() -> None:
    message_bus = ChallengeMessageBus()
    await message_bus.post("go-chat/fast", "Verified route: decode the response body first.")
    bumps: list[str] = []

    class FakeSolver:
        async def stop(self) -> None:
            return None

        def bump(self, insights: str) -> None:
            bumps.append(insights)

    solver = FakeSolver()
    expected = _result(FLAG_FOUND, "flag{expert}")
    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = type("Meta", (), {"name": "handoff"})()
    swarm.solvers = {}
    swarm.message_bus = message_bus
    swarm._create_solver = lambda _model_spec: solver  # type: ignore[method-assign]

    async def fake_run_solver_loop(_solver, _model_spec):
        return expected, solver

    swarm._run_solver_loop = fake_run_solver_loop  # type: ignore[method-assign]

    result = await swarm._run_solver("cpa-responses/expert")

    assert result is expected
    assert len(bumps) == 1
    assert "go-chat/fast" in bumps[0]
    assert "decode the response body first" in bumps[0]


@pytest.mark.asyncio
async def test_notify_coordinator_publishes_a_tier_handoff_finding() -> None:
    swarm = object.__new__(ChallengeSwarm)
    swarm.meta = type("Meta", (), {"name": "handoff"})()
    swarm.message_bus = ChallengeMessageBus()
    swarm.coordinator_inbox = asyncio.Queue()

    notify = swarm._make_notify_fn("go-chat/fast")
    await notify("Verified parameter: source; candidate CTF{notify-canary}")

    findings = await swarm.message_bus.snapshot()
    assert [(item.model, item.content) for item in findings] == [
        (
            "go-chat/fast",
            "Verified solver finding:\nVerified parameter: source; candidate <redacted-flag>",
        )
    ]
    inbox_message = await swarm.coordinator_inbox.get()
    assert "Verified parameter: source" in inbox_message
    assert "notify-canary" not in inbox_message
