"""Capability-based sandbox worker registry.

Worker selection is based on declared transport and container platform. Hostnames,
credentials, and competition-specific machine names stay in operator config.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from backend.sandbox import SANDBOX_PROFILES, resolve_sandbox_profile


class WorkerTransport(StrEnum):
    LOCAL = "local"
    SSH = "ssh"


def normalize_arch(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "x86-64": "amd64",
        "x64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported worker architecture: {value}") from exc


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    name: str
    transport: WorkerTransport
    os: str
    arch: str
    image: str
    native_arch: str = ""
    max_concurrency: int = 1
    security_profiles: frozenset[str] = frozenset(SANDBOX_PROFILES)
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_port: int = 22
    ssh_identity_file: str = ""
    ssh_control_path: str = ""
    remote_root: str = "/tmp/ctf-agent"
    loop_device: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Worker name must not be empty")
        object.__setattr__(self, "os", self.os.strip().lower())
        if self.os != "linux":
            raise ValueError("Solver containers currently require worker os='linux'")
        object.__setattr__(self, "arch", normalize_arch(self.arch))
        object.__setattr__(
            self,
            "native_arch",
            normalize_arch(self.native_arch or self.arch),
        )
        if not self.image:
            raise ValueError(f"Worker '{self.name}' must declare an image")
        if self.max_concurrency <= 0:
            raise ValueError("Worker max_concurrency must be greater than 0")
        unknown_profiles = set(self.security_profiles) - SANDBOX_PROFILES
        if unknown_profiles:
            raise ValueError(f"Unknown worker security profiles: {sorted(unknown_profiles)}")
        if self.transport is WorkerTransport.SSH:
            if not self.ssh_host:
                raise ValueError(f"SSH worker '{self.name}' must declare ssh_host")
            if not 1 <= self.ssh_port <= 65535:
                raise ValueError("ssh_port must be between 1 and 65535")
            if not self.remote_root.startswith("/"):
                raise ValueError("remote_root must be an absolute POSIX path")

    @property
    def docker_platform(self) -> str:
        return f"{self.os}/{self.arch}"

    @property
    def is_native(self) -> bool:
        """Whether the configured image architecture matches the worker hardware."""
        return self.arch == self.native_arch


@dataclass(frozen=True, slots=True)
class WorkerRequirements:
    os: str = "linux"
    required_arch: str | None = None
    preferred_arch: str | None = None
    security_profile: str = "standard"


def _tag_value(tags: list[str] | tuple[str, ...], prefix: str) -> str | None:
    for tag in tags:
        key, separator, value = tag.partition(":")
        if separator and key.strip().lower() == prefix:
            return value.strip()
    return None


def requirements_for_challenge(meta: Any, configured_profile: str = "auto") -> WorkerRequirements:
    tags = list(getattr(meta, "tags", ()) or ())
    explicit_arch = _tag_value(tags, "arch")
    required_arch = normalize_arch(explicit_arch) if explicit_arch else None
    category = str(getattr(meta, "category", "") or "")
    preferred_arch = None
    if required_arch is None and category.strip().lower() in {
        "pwn",
        "reverse",
        "reversing",
        "re",
        "binary",
    }:
        preferred_arch = "amd64"
    return WorkerRequirements(
        required_arch=required_arch,
        preferred_arch=preferred_arch,
        security_profile=resolve_sandbox_profile(category, tags, configured_profile),
    )


class WorkerRegistry:
    def __init__(self, workers: list[WorkerSpec] | tuple[WorkerSpec, ...]) -> None:
        if not workers:
            raise ValueError("At least one sandbox worker must be configured")
        names = [worker.name for worker in workers]
        if len(set(names)) != len(names):
            raise ValueError("Worker names must be unique")
        self.workers = tuple(workers)

    def select(self, requirements: WorkerRequirements) -> WorkerSpec:
        candidates = [
            worker
            for worker in self.workers
            if worker.os == requirements.os
            and requirements.security_profile in worker.security_profiles
            and (
                requirements.required_arch is None
                or worker.arch == requirements.required_arch
            )
        ]
        if not candidates:
            required = requirements.required_arch or "any"
            raise RuntimeError(
                "No sandbox worker satisfies "
                f"os={requirements.os} arch={required} profile={requirements.security_profile}"
            )

        def rank(worker: WorkerSpec) -> tuple[int, int, int]:
            preferred = int(
                requirements.preferred_arch is not None
                and worker.arch == requirements.preferred_arch
            )
            native = int(worker.is_native)
            local = int(worker.transport is WorkerTransport.LOCAL)
            return preferred, native, local

        return max(candidates, key=rank)


def _worker_from_mapping(raw: dict[str, Any]) -> WorkerSpec:
    normalized_keys = {str(key).strip().lower() for key in raw}
    forbidden = {"password", "ssh_password", "api_key", "token"} & normalized_keys
    if forbidden:
        raise ValueError(
            "Worker config must not contain credentials; use SSH agent/config or an identity file"
        )
    profiles = raw.get("security_profiles", SANDBOX_PROFILES)
    return WorkerSpec(
        name=str(raw.get("name", "")),
        transport=WorkerTransport(str(raw.get("transport", "local"))),
        os=str(raw.get("os", "linux")).lower(),
        arch=str(raw.get("arch", "")),
        native_arch=str(raw.get("native_arch", raw.get("arch", ""))),
        image=str(raw.get("image", "")),
        max_concurrency=int(raw.get("max_concurrency", 1)),
        security_profiles=frozenset(str(item) for item in profiles),
        ssh_host=str(raw.get("ssh_host", "")),
        ssh_user=str(raw.get("ssh_user", "")),
        ssh_port=int(raw.get("ssh_port", 22)),
        ssh_identity_file=str(raw.get("ssh_identity_file", "")),
        ssh_control_path=str(raw.get("ssh_control_path", "")),
        remote_root=str(raw.get("remote_root", "/tmp/ctf-agent")),
        loop_device=str(raw.get("loop_device", "")),
    )


def load_worker_registry(path: str | Path) -> WorkerRegistry:
    config_path = Path(path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if data.get("version") != 1:
        raise ValueError("Worker config version must be 1")
    raw_workers = data.get("workers")
    if not isinstance(raw_workers, list):
        raise ValueError("Worker config must contain a workers list")
    return WorkerRegistry([_worker_from_mapping(raw) for raw in raw_workers])


def local_worker_from_settings(settings: Any) -> WorkerSpec:
    configured_arch = str(getattr(settings, "local_worker_arch", "") or "")
    native_arch = platform.machine()
    image_arch = configured_arch or native_arch
    return WorkerSpec(
        name="local",
        transport=WorkerTransport.LOCAL,
        os="linux",
        arch=image_arch,
        native_arch=native_arch,
        image=str(getattr(settings, "sandbox_image", "ctf-sandbox")),
        max_concurrency=int(getattr(settings, "max_concurrent_containers", 1)),
    )


def registry_from_settings(settings: Any) -> WorkerRegistry:
    config_path = str(getattr(settings, "worker_config_file", "") or "")
    if config_path:
        return load_worker_registry(config_path)
    return WorkerRegistry([local_worker_from_settings(settings)])
