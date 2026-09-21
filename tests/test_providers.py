from __future__ import annotations

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from backend.config import Settings
from backend.models import resolve_model
from backend.providers import (
    PROVIDER_REGISTRY,
    ModelRole,
    ModelSpec,
    ProviderProtocol,
    get_provider_spec,
)


def test_registry_keeps_cpa_and_go_protocols_explicit() -> None:
    assert get_provider_spec("cpa-responses").protocol is ProviderProtocol.RESPONSES
    assert get_provider_spec("cpa-chat").protocol is ProviderProtocol.CHAT_COMPLETIONS
    assert get_provider_spec("go-chat").protocol is ProviderProtocol.CHAT_COMPLETIONS
    assert get_provider_spec("go-messages").protocol is ProviderProtocol.ANTHROPIC_MESSAGES
    assert get_provider_spec("go-responses").protocol is ProviderProtocol.RESPONSES


def test_new_protocol_routes_have_runtime_adapters() -> None:
    for name in ("cpa-responses", "cpa-chat", "go-chat", "go-messages", "go-responses"):
        assert PROVIDER_REGISTRY[name].runtime_adapter_available is True


def test_model_spec_preserves_model_id_and_does_not_guess_role() -> None:
    model = ModelSpec.parse("cpa-responses/vendor/model-with/slashes")

    assert model.provider == "cpa-responses"
    assert model.model_id == "vendor/model-with/slashes"
    assert model.role is ModelRole.UNASSIGNED
    assert model.capabilities == frozenset()


@pytest.mark.parametrize("value", ["missing-provider", "/model", "cpa-chat/"])
def test_model_spec_rejects_invalid_shape(value: str) -> None:
    with pytest.raises(ValueError, match="provider/model-id"):
        ModelSpec.parse(value)


def test_model_spec_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        ModelSpec.parse("invented/model")


def test_resolve_model_requires_explicit_cpa_configuration() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="requires a base URL"):
        resolve_model("cpa-responses/exact-model-id", settings)


def test_runtime_adapter_types_follow_provider_protocol() -> None:
    settings = Settings(
        _env_file=None,
        cpa_responses_base_url="https://cpa.example.test/v1",
        cpa_chat_base_url="https://cpa.example.test/v1",
        cpa_api_key="test-key",
        opencode_go_api_key="test-key",
    )

    assert isinstance(resolve_model("cpa-responses/exact-id", settings), OpenAIResponsesModel)
    assert isinstance(resolve_model("cpa-chat/exact-id", settings), OpenAIChatModel)
    assert isinstance(resolve_model("go-responses/exact-id", settings), OpenAIResponsesModel)
    assert isinstance(resolve_model("go-chat/exact-id", settings), OpenAIChatModel)
    assert isinstance(resolve_model("go-messages/exact-id", settings), AnthropicModel)
