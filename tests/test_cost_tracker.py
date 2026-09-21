from __future__ import annotations

from pydantic_ai.usage import RunUsage

from backend.cost_tracker import CostTracker


def test_subscription_provider_preserves_reported_usage_without_inventing_cost() -> None:
    tracker = CostTracker()

    tracker.record(
        "challenge/go-chat/model",
        RunUsage(input_tokens=120, output_tokens=30),
        "model",
        provider_spec="go-chat",
    )

    recorded = tracker.by_agent["challenge/go-chat/model"]
    assert recorded.usage.input_tokens == 120
    assert recorded.usage.output_tokens == 30
    assert recorded.usage_estimated is False
    assert recorded.billing_basis == "subscription"
    assert recorded.cost_usd == 0.0


def test_missing_provider_usage_is_marked_estimated() -> None:
    tracker = CostTracker()

    tracker.record(
        "challenge/go-chat/model",
        RunUsage(),
        "model",
        provider_spec="go-chat",
    )

    assert tracker.by_agent["challenge/go-chat/model"].usage_estimated is True
