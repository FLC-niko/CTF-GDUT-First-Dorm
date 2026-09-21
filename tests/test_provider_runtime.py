from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.usage import RunUsage

from backend.agents.swarm import _quota_fallback_spec
from backend.config import Settings
from backend.provider_runtime import (
    ProviderCircuitOpenError,
    ProviderErrorKind,
    ProviderLimits,
    ProviderRuntimeGovernor,
    classify_provider_error,
)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": "bad key"}, ProviderErrorKind.AUTH),
        (404, {"error": "model not found"}, ProviderErrorKind.MODEL_NOT_FOUND),
        (404, {"error": "route not found"}, ProviderErrorKind.PROTOCOL_MISMATCH),
        (429, {"error": "rate limit"}, ProviderErrorKind.RATE_LIMIT),
        (429, {"error": "insufficient_quota"}, ProviderErrorKind.QUOTA),
        (400, {"error": "unsupported endpoint"}, ProviderErrorKind.PROTOCOL_MISMATCH),
        (500, {"error": "upstream"}, ProviderErrorKind.PROVIDER_ERROR),
    ],
)
def test_provider_error_taxonomy(
    status: int,
    body: object,
    expected: ProviderErrorKind,
) -> None:
    error = ModelHTTPError(status, "test-model", body)

    assert classify_provider_error(error) is expected


@pytest.mark.asyncio
async def test_provider_concurrency_limit_is_enforced() -> None:
    governor = ProviderRuntimeGovernor(limits={"opencode-go": ProviderLimits(max_concurrency=1)})
    active = 0
    peak = 0
    release = asyncio.Event()

    async def worker(provider: str) -> None:
        nonlocal active, peak
        async with governor.slot(provider):
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1

    first = asyncio.create_task(worker("go-chat"))
    await asyncio.sleep(0)
    second = asyncio.create_task(worker("go-messages"))
    await asyncio.sleep(0)

    assert peak == 1
    release.set()
    await asyncio.gather(first, second)


def test_hard_token_budget_opens_circuit_and_soft_budget_is_reported() -> None:
    governor = ProviderRuntimeGovernor(
        limits={
            "cpa-chat": ProviderLimits(
                max_concurrency=2,
                soft_token_budget=10,
                hard_token_budget=20,
            )
        }
    )

    governor.record_usage("cpa-chat", RunUsage(input_tokens=12, output_tokens=9))

    state = governor.snapshot()["cpa"]
    assert state["used_tokens"] == 21
    assert state["soft_budget_reached"] is True
    assert state["circuit_reason"] == "hard_token_budget"
    with pytest.raises(ProviderCircuitOpenError, match="hard_token_budget"):
        governor.check_available("cpa-chat")


def test_quota_error_opens_circuit() -> None:
    governor = ProviderRuntimeGovernor(limits={})

    governor.record_error("go-chat", ProviderErrorKind.QUOTA)

    with pytest.raises(ProviderCircuitOpenError, match="quota"):
        governor.check_available("go-chat")


def test_paid_quota_fallback_is_disabled_by_default() -> None:
    assert _quota_fallback_spec("codex/gpt-5.4") is None
    assert _quota_fallback_spec("codex/gpt-5.4", allow_paid=True) == "azure/gpt-5.4"


def test_provider_budget_settings_validate_ranges() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        Settings(
            _env_file=None,
            opencode_go_soft_token_budget=101,
            opencode_go_hard_token_budget=100,
        )
