"""Provider error classification, budgets, concurrency, and circuit breaking."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx
import httpx2
from pydantic_ai.exceptions import ModelHTTPError

if TYPE_CHECKING:
    from backend.config import Settings


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    MODEL_NOT_FOUND = "model_not_found"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"


def _error_text(exc: BaseException) -> str:
    body = getattr(exc, "body", "")
    return f"{body} {exc}".lower()


def classify_provider_error(exc: BaseException) -> ProviderErrorKind:
    """Map SDK/Pydantic errors to stable, provider-neutral categories."""
    if isinstance(exc, asyncio.CancelledError):
        return ProviderErrorKind.CANCELLED
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx2.TimeoutException)):
        return ProviderErrorKind.TIMEOUT

    status_code = getattr(exc, "status_code", None)
    text = _error_text(exc)
    if status_code in {401, 403}:
        return ProviderErrorKind.AUTH
    if status_code == 429:
        quota_markers = (
            "insufficient_quota",
            "quota",
            "balance",
            "credit",
            "exhausted",
            "usage limit",
        )
        if any(marker in text for marker in quota_markers):
            return ProviderErrorKind.QUOTA
        return ProviderErrorKind.RATE_LIMIT
    if status_code == 404:
        body_text = str(getattr(exc, "body", "")).lower()
        if "model" in body_text:
            return ProviderErrorKind.MODEL_NOT_FOUND
        return ProviderErrorKind.PROTOCOL_MISMATCH
    if status_code in {408, 504}:
        return ProviderErrorKind.TIMEOUT
    if status_code in {400, 405, 415, 422}:
        protocol_markers = (
            "endpoint",
            "protocol",
            "unsupported",
            "not supported",
            "content-type",
            "unknown field",
        )
        if any(marker in text for marker in protocol_markers):
            return ProviderErrorKind.PROTOCOL_MISMATCH
    if isinstance(exc, ModelHTTPError):
        return ProviderErrorKind.PROVIDER_ERROR
    return ProviderErrorKind.PROVIDER_ERROR


class ProviderCircuitOpenError(RuntimeError):
    """Raised before a request when a local provider circuit is open."""

    def __init__(self, provider: str, reason: ProviderErrorKind | str) -> None:
        self.provider = provider
        self.reason = str(reason)
        super().__init__(f"provider '{provider}' circuit open: {self.reason}")


@dataclass(frozen=True, slots=True)
class ProviderLimits:
    max_concurrency: int = 2
    soft_token_budget: int = 0
    hard_token_budget: int = 0


@dataclass(slots=True)
class ProviderState:
    used_tokens: int = 0
    soft_budget_reached: bool = False
    circuit_reason: ProviderErrorKind | str | None = None
    circuit_until: float | None = None


@dataclass
class ProviderRuntimeGovernor:
    """In-process resource guard shared by all swarms in one coordinator."""

    limits: dict[str, ProviderLimits]
    rate_limit_cooldown_seconds: int = 60
    states: dict[str, ProviderState] = field(default_factory=dict)
    _semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> ProviderRuntimeGovernor:
        cpa = ProviderLimits(
            max_concurrency=getattr(settings, "cpa_max_concurrency", 2),
            soft_token_budget=getattr(settings, "cpa_soft_token_budget", 0),
            hard_token_budget=getattr(settings, "cpa_hard_token_budget", 0),
        )
        go = ProviderLimits(
            max_concurrency=getattr(settings, "opencode_go_max_concurrency", 2),
            soft_token_budget=getattr(settings, "opencode_go_soft_token_budget", 0),
            hard_token_budget=getattr(settings, "opencode_go_hard_token_budget", 0),
        )
        return cls(
            limits={
                "cpa": cpa,
                "opencode-go": go,
            },
            rate_limit_cooldown_seconds=getattr(
                settings, "provider_rate_limit_cooldown_seconds", 60
            ),
        )

    @staticmethod
    def _group(provider: str) -> str:
        if provider.startswith("cpa-"):
            return "cpa"
        if provider.startswith("go-"):
            return "opencode-go"
        return provider

    def _state(self, provider: str) -> ProviderState:
        return self.states.setdefault(self._group(provider), ProviderState())

    def _limits(self, provider: str) -> ProviderLimits:
        return self.limits.get(self._group(provider), self.limits.get(provider, ProviderLimits()))

    def _semaphore(self, provider: str) -> asyncio.Semaphore:
        group = self._group(provider)
        return self._semaphores.setdefault(
            group, asyncio.Semaphore(self._limits(provider).max_concurrency)
        )

    def check_available(self, provider: str) -> None:
        state = self._state(provider)
        if state.circuit_reason is None:
            return
        if state.circuit_until is not None and time.monotonic() >= state.circuit_until:
            state.circuit_reason = None
            state.circuit_until = None
            return
        raise ProviderCircuitOpenError(provider, state.circuit_reason)

    @asynccontextmanager
    async def slot(self, provider: str) -> AsyncIterator[None]:
        self.check_available(provider)
        async with self._semaphore(provider):
            self.check_available(provider)
            yield

    def record_usage(self, provider: str, usage: Any) -> None:
        state = self._state(provider)
        token_count = int(getattr(usage, "total_tokens", 0) or 0)
        state.used_tokens += max(0, token_count)
        limits = self._limits(provider)
        if limits.soft_token_budget and state.used_tokens >= limits.soft_token_budget:
            state.soft_budget_reached = True
        if limits.hard_token_budget and state.used_tokens >= limits.hard_token_budget:
            state.circuit_reason = "hard_token_budget"
            state.circuit_until = None

    def record_error(self, provider: str, kind: ProviderErrorKind) -> None:
        state = self._state(provider)
        if kind is ProviderErrorKind.QUOTA:
            state.circuit_reason = kind
            state.circuit_until = None
        elif kind is ProviderErrorKind.RATE_LIMIT:
            state.circuit_reason = kind
            state.circuit_until = time.monotonic() + self.rate_limit_cooldown_seconds

    def reset(self, provider: str) -> None:
        self.states[self._group(provider)] = ProviderState()

    def snapshot(self) -> dict[str, dict[str, int | bool | str | None]]:
        return {
            provider: {
                "used_tokens": state.used_tokens,
                "soft_budget_reached": state.soft_budget_reached,
                "circuit_reason": (
                    str(state.circuit_reason) if state.circuit_reason is not None else None
                ),
            }
            for provider, state in self.states.items()
        }
