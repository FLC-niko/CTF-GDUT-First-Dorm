"""Model resolution for protocol-explicit providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import boto3
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from backend.providers import ProviderProtocol, get_provider_spec

if TYPE_CHECKING:
    from backend.config import Settings

# Default model specs — claude-sdk and codex providers use the new solver backends
DEFAULT_MODELS: list[str] = [
    "codex/gpt-5.4",
    "codex/gpt-5.4-mini",
    "codex/gpt-5.3-codex",
]

# Context window sizes (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "us.anthropic.claude-opus-4-6-v1": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.3-codex": 1_000_000,
    "gpt-5.3-codex-spark": 128_000,
    "gemini-3-flash-preview": 1_000_000,
}

# Models that support vision
VISION_MODELS: set[str] = {
    "us.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-6",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gemini-3-flash-preview",
}


def _required_setting(value: str, provider: str, setting_name: str) -> str:
    if not value:
        raise ValueError(f"Provider '{provider}' requires {setting_name}")
    return value


def _go_headers(session_id: str | None) -> dict[str, str]:
    return {
        "x-opencode-session": session_id or str(uuid4()),
        "User-Agent": "ctf-agent/0.1",
    }


def resolve_model(
    spec: str,
    settings: Settings,
    *,
    session_id: str | None = None,
    http_client: Any | None = None,
) -> Model:
    """Resolve a 'provider/model_id' spec to a Pydantic AI Model."""
    provider = provider_from_spec(spec)
    model_id = model_id_from_spec(spec)
    match provider:
        case "bedrock":
            if settings.aws_bearer_token:
                return BedrockConverseModel(
                    model_id,
                    provider=BedrockProvider(
                        api_key=settings.aws_bearer_token,
                        region_name=settings.aws_region,
                    ),
                )
            else:
                session = boto3.Session()
                client = session.client("bedrock-runtime", region_name=settings.aws_region)
                return BedrockConverseModel(
                    model_id,
                    provider=BedrockProvider(bedrock_client=client),
                )
        case "azure":
            return OpenAIResponsesModel(
                model_id,
                provider=OpenAIProvider(
                    base_url=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_api_key,
                ),
            )
        case "zen":
            return OpenAIChatModel(
                model_id,
                provider=OpenAIProvider(
                    base_url="https://opencode.ai/zen/v1",
                    api_key=settings.opencode_zen_api_key,
                ),
            )
        case "google":
            return GoogleModel(
                model_id,
                provider=GoogleProvider(api_key=settings.gemini_api_key),
            )
        case "claude-sdk" | "codex":
            raise ValueError(
                f"Provider '{provider}' uses its own solver backend, not Pydantic AI. "
                f"resolve_model() should not be called for {spec}."
            )
        case "cpa-responses" | "cpa-chat":
            provider_spec = get_provider_spec(provider)
            base_url = _required_setting(
                provider_spec.configured_base_url(settings), provider, "a base URL"
            )
            api_key = _required_setting(settings.cpa_api_key, provider, "CPA_API_KEY")
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=0,
                http_client=http_client,
            )
            model_provider = OpenAIProvider(openai_client=client)
            if provider_spec.protocol is ProviderProtocol.RESPONSES:
                return OpenAIResponsesModel(model_id, provider=model_provider)
            return OpenAIChatModel(model_id, provider=model_provider)
        case "go-responses" | "go-chat":
            provider_spec = get_provider_spec(provider)
            base_url = _required_setting(
                provider_spec.configured_base_url(settings), provider, "a base URL"
            )
            api_key = _required_setting(
                settings.opencode_go_api_key, provider, "OPENCODE_GO_API_KEY"
            )
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                default_headers=_go_headers(session_id),
                max_retries=0,
                http_client=http_client,
            )
            model_provider = OpenAIProvider(openai_client=client)
            if provider_spec.protocol is ProviderProtocol.RESPONSES:
                return OpenAIResponsesModel(model_id, provider=model_provider)
            return OpenAIChatModel(model_id, provider=model_provider)
        case "go-messages":
            provider_spec = get_provider_spec(provider)
            base_url = _required_setting(
                provider_spec.configured_base_url(settings), provider, "a base URL"
            )
            api_key = _required_setting(
                settings.opencode_go_api_key, provider, "OPENCODE_GO_API_KEY"
            )
            client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url,
                default_headers=_go_headers(session_id),
                max_retries=0,
                http_client=http_client,
            )
            return AnthropicModel(
                model_id,
                provider=AnthropicProvider(anthropic_client=client),
            )
        case _:
            provider_spec = get_provider_spec(provider)
            if not provider_spec.runtime_adapter_available:
                raise ValueError(
                    f"Provider '{provider}' is registered for protocol "
                    f"'{provider_spec.protocol.value}', but its runtime adapter is not "
                    "implemented yet. Run ctf-doctor to inspect offline configuration."
                )
            raise ValueError(f"Provider '{provider}' has no Pydantic AI model adapter")


def resolve_model_settings(spec: str) -> ModelSettings:
    """Get provider-specific model settings with caching enabled."""
    provider = spec.split("/", 1)[0]
    match provider:
        case "bedrock":
            return BedrockModelSettings(
                max_tokens=128_000,
                bedrock_cache_instructions=True,
                bedrock_cache_tool_definitions=True,
                bedrock_cache_messages=True,
            )
        case "azure":
            return OpenAIResponsesModelSettings(
                max_tokens=128_000,
                openai_reasoning_effort="medium",
                openai_reasoning_summary="auto",
                openai_truncation="auto",
            )
        case "zen":
            # Zen remains on the chat-completions-compatible path for now.
            return OpenAIChatModelSettings(
                max_tokens=128_000,
            )
        case "google":
            return GoogleModelSettings(
                max_tokens=64_000,
                google_thinking_config={
                    "thinking_level": "high",
                    "include_thoughts": True,
                },
            )
        case "cpa-responses":
            return OpenAIResponsesModelSettings()
        case "cpa-chat":
            return OpenAIChatModelSettings()
        case "go-responses":
            return OpenAIResponsesModelSettings(extra_headers={"User-Agent": "ctf-agent/0.1"})
        case "go-chat":
            return OpenAIChatModelSettings(extra_headers={"User-Agent": "ctf-agent/0.1"})
        case "go-messages":
            return AnthropicModelSettings(extra_headers={"User-Agent": "ctf-agent/0.1"})
        case _:
            return ModelSettings(max_tokens=128_000)


def model_id_from_spec(spec: str) -> str:
    """Extract just the model ID from a spec (strips effort suffix)."""
    provider, separator, remainder = spec.partition("/")
    if not separator:
        return spec
    parts = remainder.split("/")
    if provider in {"claude-sdk", "codex"} and parts[-1] in {
        "low",
        "medium",
        "high",
        "max",
    }:
        parts.pop()
    return "/".join(parts)


def provider_from_spec(spec: str) -> str:
    """Extract the provider from a spec."""
    return spec.split("/", 1)[0]


def effort_from_spec(spec: str) -> str | None:
    """Extract effort level from a spec like 'claude-sdk/claude-opus-4-6/max'."""
    parts = spec.split("/")
    if len(parts) >= 3 and parts[2] in ("low", "medium", "high", "max"):
        return parts[2]
    return None


def supports_vision(spec: str) -> bool:
    """Check if a model spec supports vision."""
    return model_id_from_spec(spec) in VISION_MODELS


def context_window(spec: str) -> int:
    """Get context window size for a model spec."""
    return CONTEXT_WINDOWS.get(model_id_from_spec(spec), 200_000)
