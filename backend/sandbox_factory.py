"""Select and construct local or SSH-backed sandboxes from worker capabilities."""

from __future__ import annotations

from typing import Any

from backend.remote_sandbox import RemoteDockerSandbox
from backend.sandbox import DockerSandbox
from backend.workers import (
    WorkerTransport,
    registry_from_settings,
    requirements_for_challenge,
)


def create_sandbox(
    settings: Any,
    challenge_dir: str,
    meta: Any,
) -> DockerSandbox | RemoteDockerSandbox:
    registry = registry_from_settings(settings)
    requirements = requirements_for_challenge(
        meta,
        getattr(settings, "sandbox_security_profile", "auto"),
    )
    worker = registry.select(requirements)
    common = {
        "challenge_dir": challenge_dir,
        "memory_limit": getattr(settings, "container_memory_limit", "4g"),
        "cpu_limit": getattr(settings, "container_cpu_limit", 2.0),
        "pids_limit": getattr(settings, "container_pids_limit", 512),
        "security_profile": requirements.security_profile,
        "network_mode": getattr(settings, "sandbox_network_mode", "bridge"),
    }
    if worker.transport is WorkerTransport.LOCAL:
        return DockerSandbox(
            image=worker.image,
            loop_device=worker.loop_device
            or getattr(settings, "sandbox_loop_device", ""),
            **common,
        )
    return RemoteDockerSandbox(worker=worker, **common)
