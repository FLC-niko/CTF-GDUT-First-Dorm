"""Opt-in live provider smoke tests.

These tests are skipped in normal CI. They make a real model request only when
RUN_PROVIDER_LIVE=1 and the corresponding model/config variables are present.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from pydantic_ai import Agent

from backend.config import Settings
from backend.models import resolve_model, resolve_model_settings


async def _run_tool_smoke(model_spec: str) -> None:
    calls: list[str] = []

    async def provider_smoke_echo(value: str) -> str:
        calls.append(value)
        return "provider-smoke-ok"

    model = resolve_model(model_spec, Settings(), session_id="ctf-agent-live-smoke")
    agent = Agent(
        model,
        model_settings=resolve_model_settings(model_spec),
        tools=[provider_smoke_echo],
    )
    async with asyncio.timeout(120):
        result = await agent.run(
            "Call provider_smoke_echo exactly once with value 'provider-smoke-canary', "
            "then briefly acknowledge the tool result. Do not produce a CTF flag."
        )

    assert calls == ["provider-smoke-canary"]
    assert str(result.output).strip()
    assert result.usage.requests >= 2


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_PROVIDER_LIVE") != "1" or not os.getenv("CPA_SMOKE_MODEL"),
    reason="requires explicit live CPA opt-in and CPA_SMOKE_MODEL",
)
async def test_live_cpa_tool_round_trip() -> None:
    model_spec = os.environ["CPA_SMOKE_MODEL"]
    assert model_spec.startswith(("cpa-responses/", "cpa-chat/"))
    await _run_tool_smoke(model_spec)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_PROVIDER_LIVE") != "1" or not os.getenv("GO_SMOKE_MODEL"),
    reason="requires explicit live OpenCode Go opt-in and GO_SMOKE_MODEL",
)
async def test_live_go_tool_round_trip() -> None:
    model_spec = os.environ["GO_SMOKE_MODEL"]
    assert model_spec.startswith(("go-responses/", "go-chat/", "go-messages/"))
    await _run_tool_smoke(model_spec)
