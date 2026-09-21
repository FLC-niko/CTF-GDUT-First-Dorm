"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings

AllSolvedPolicy = Literal["wait", "exit", "idle"]
WriteupMode = Literal["off", "confirmed", "solved"]
SandboxSecurityProfile = Literal["auto", "standard", "debug", "forensics", "nested"]
SandboxNetworkMode = Literal["bridge", "none"]


class Settings(BaseSettings):
    # Competition platform
    platform: str = "ctfd"
    platform_url: str = ""
    lingxu_event_id: int = 0
    lingxu_cookie: str = ""
    lingxu_cookie_file: str = ""

    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Provider-specific (optional, for Bedrock/Azure/Zen fallback)
    aws_region: str = "us-east-1"
    aws_bearer_token: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    opencode_zen_api_key: str = ""

    # Explicit protocol routes. Model IDs are supplied separately and are never
    # inferred from display names.
    cpa_responses_base_url: str = ""
    cpa_chat_base_url: str = ""
    cpa_api_key: str = ""
    opencode_go_chat_base_url: str = "https://opencode.ai/zen/go/v1"
    # Anthropic SDK appends /v1/messages itself; its client base omits /v1.
    opencode_go_messages_base_url: str = "https://opencode.ai/zen/go"
    opencode_go_responses_base_url: str = "https://opencode.ai/zen/go/v1"
    opencode_go_api_key: str = ""

    # Provider resource governance. Zero token budgets mean disabled. Paid API
    # fallback is opt-in because subscriptions and metered APIs are separate.
    cpa_max_concurrency: int = 2
    cpa_soft_token_budget: int = 0
    cpa_hard_token_budget: int = 0
    opencode_go_max_concurrency: int = 2
    opencode_go_soft_token_budget: int = 0
    opencode_go_hard_token_budget: int = 0
    provider_rate_limit_cooldown_seconds: int = 60
    allow_paid_api_fallback: bool = False

    # Infra
    sandbox_image: str = "ctf-sandbox"
    max_concurrent_challenges: int = 10
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "4g"
    container_cpu_limit: float = 2.0
    container_pids_limit: int = 512
    sandbox_security_profile: SandboxSecurityProfile = "auto"
    sandbox_network_mode: SandboxNetworkMode = "bridge"
    sandbox_loop_device: str = ""
    worker_config_file: str = ""
    local_worker_arch: str = ""
    max_concurrent_containers: int = 2
    all_solved_policy: AllSolvedPolicy = "wait"
    all_solved_idle_seconds: int = 300
    writeup_mode: WriteupMode = "off"
    writeup_dir: str = "writeups"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "validate_assignment": True,
    }

    @model_validator(mode="after")
    def validate_all_solved_idle_seconds(self) -> Settings:
        if self.all_solved_policy == "idle" and self.all_solved_idle_seconds <= 0:
            raise ValueError(
                "all_solved_idle_seconds must be greater than 0 when all_solved_policy is idle"
            )
        return self

    @model_validator(mode="after")
    def validate_provider_limits(self) -> Settings:
        for name in ("cpa_max_concurrency", "opencode_go_max_concurrency"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than 0")
        for prefix in ("cpa", "opencode_go"):
            soft = getattr(self, f"{prefix}_soft_token_budget")
            hard = getattr(self, f"{prefix}_hard_token_budget")
            if soft < 0 or hard < 0:
                raise ValueError(f"{prefix} token budgets must be non-negative")
            if soft and hard and soft > hard:
                raise ValueError(f"{prefix}_soft_token_budget cannot exceed hard budget")
        if self.provider_rate_limit_cooldown_seconds < 0:
            raise ValueError("provider_rate_limit_cooldown_seconds must be non-negative")
        if self.container_cpu_limit <= 0:
            raise ValueError("container_cpu_limit must be greater than 0")
        if self.container_pids_limit <= 0:
            raise ValueError("container_pids_limit must be greater than 0")
        if self.max_concurrent_containers <= 0:
            raise ValueError("max_concurrent_containers must be greater than 0")
        return self
