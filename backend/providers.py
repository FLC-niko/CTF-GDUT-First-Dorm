"""Provider registry and model descriptors.

This module describes routing facts only.  It deliberately does not probe remote
endpoints or infer a protocol, role, or capability from a model's display name.
Runtime adapters are added separately once their wire protocols are verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.config import Settings


class ProviderProtocol(StrEnum):
    """Wire/runtime protocol used by a provider adapter."""

    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    NATIVE_CLI = "native_cli"
    BEDROCK_CONVERSE = "bedrock_converse"
    GOOGLE_GENERATIVE = "google_generative"


class ModelRole(StrEnum):
    """Scheduler role assigned by configuration or benchmark evidence."""

    UNASSIGNED = "unassigned"
    FAST = "fast"
    EXPERT = "expert"
    RACING = "racing"


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Static provider routing metadata without credentials."""

    name: str
    protocol: ProviderProtocol
    base_url_setting: str | None = None
    api_key_setting: str | None = None
    fixed_base_url: str | None = None
    requires_base_url: bool = True
    runtime_adapter_available: bool = False
    solver_streaming: bool = False
    subscription_backed: bool = False
    legacy: bool = False

    def configured_base_url(self, settings: Settings) -> str:
        if self.fixed_base_url is not None:
            return self.fixed_base_url
        if self.base_url_setting is None:
            return ""
        return str(getattr(settings, self.base_url_setting, "") or "")

    def credential_configured(self, settings: Settings) -> bool:
        if self.api_key_setting is None:
            return True
        return bool(getattr(settings, self.api_key_setting, ""))


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A model ID plus explicit scheduling metadata.

    Capabilities default to unknown.  They must be populated from verified
    provider metadata or benchmark/configuration evidence, never name matching.
    """

    provider: str
    model_id: str
    role: ModelRole = ModelRole.UNASSIGNED
    capabilities: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def parse(cls, value: str) -> ModelSpec:
        provider, separator, model_id = value.partition("/")
        if not separator or not provider or not model_id:
            raise ValueError("Model spec must use the form 'provider/model-id'")
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(f"Unknown provider: {provider}")
        return cls(provider=provider, model_id=model_id)


_PROVIDERS = {
    # CPA/Go aliases are intentionally protocol-specific; model IDs never choose a protocol.
    "cpa-responses": ProviderSpec(
        name="cpa-responses",
        protocol=ProviderProtocol.RESPONSES,
        base_url_setting="cpa_responses_base_url",
        api_key_setting="cpa_api_key",
        runtime_adapter_available=True,
        solver_streaming=True,
    ),
    "cpa-chat": ProviderSpec(
        name="cpa-chat",
        protocol=ProviderProtocol.CHAT_COMPLETIONS,
        base_url_setting="cpa_chat_base_url",
        api_key_setting="cpa_api_key",
        runtime_adapter_available=True,
    ),
    "go-chat": ProviderSpec(
        name="go-chat",
        protocol=ProviderProtocol.CHAT_COMPLETIONS,
        base_url_setting="opencode_go_chat_base_url",
        api_key_setting="opencode_go_api_key",
        runtime_adapter_available=True,
        subscription_backed=True,
    ),
    "go-messages": ProviderSpec(
        name="go-messages",
        protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
        base_url_setting="opencode_go_messages_base_url",
        api_key_setting="opencode_go_api_key",
        runtime_adapter_available=True,
        subscription_backed=True,
    ),
    "go-responses": ProviderSpec(
        name="go-responses",
        protocol=ProviderProtocol.RESPONSES,
        base_url_setting="opencode_go_responses_base_url",
        api_key_setting="opencode_go_api_key",
        runtime_adapter_available=True,
        solver_streaming=True,
        subscription_backed=True,
    ),
    # Existing aliases remain registered exactly as the current runtime routes them.
    "azure": ProviderSpec(
        name="azure",
        protocol=ProviderProtocol.RESPONSES,
        base_url_setting="azure_openai_endpoint",
        api_key_setting="azure_openai_api_key",
        runtime_adapter_available=True,
        solver_streaming=True,
        legacy=True,
    ),
    "zen": ProviderSpec(
        name="zen",
        protocol=ProviderProtocol.CHAT_COMPLETIONS,
        fixed_base_url="https://opencode.ai/zen/v1",
        api_key_setting="opencode_zen_api_key",
        runtime_adapter_available=True,
        legacy=True,
    ),
    "bedrock": ProviderSpec(
        name="bedrock",
        protocol=ProviderProtocol.BEDROCK_CONVERSE,
        requires_base_url=False,
        runtime_adapter_available=True,
        legacy=True,
    ),
    "google": ProviderSpec(
        name="google",
        protocol=ProviderProtocol.GOOGLE_GENERATIVE,
        api_key_setting="gemini_api_key",
        requires_base_url=False,
        runtime_adapter_available=True,
        legacy=True,
    ),
    "claude-sdk": ProviderSpec(
        name="claude-sdk",
        protocol=ProviderProtocol.NATIVE_CLI,
        requires_base_url=False,
        runtime_adapter_available=True,
        legacy=True,
    ),
    "codex": ProviderSpec(
        name="codex",
        protocol=ProviderProtocol.NATIVE_CLI,
        requires_base_url=False,
        runtime_adapter_available=True,
        legacy=True,
    ),
}

PROVIDER_REGISTRY: Mapping[str, ProviderSpec] = MappingProxyType(_PROVIDERS)


def get_provider_spec(name: str) -> ProviderSpec:
    """Return a registered provider or raise a stable configuration error."""
    try:
        return PROVIDER_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name}") from exc
