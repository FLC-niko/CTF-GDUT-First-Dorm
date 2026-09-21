from __future__ import annotations

from pathlib import Path

import pytest

from backend.prompts import ChallengeMeta
from backend.workers import (
    WorkerRegistry,
    WorkerRequirements,
    WorkerSpec,
    WorkerTransport,
    load_worker_registry,
    normalize_arch,
    requirements_for_challenge,
)


def _worker(
    name: str,
    arch: str,
    transport: WorkerTransport,
    *,
    profiles: frozenset[str] = frozenset({"standard", "debug", "forensics"}),
) -> WorkerSpec:
    return WorkerSpec(
        name=name,
        transport=transport,
        os="linux",
        arch=arch,
        native_arch=arch,
        image=f"ctf-sandbox:{arch}",
        security_profiles=profiles,
        ssh_host="worker-alias" if transport is WorkerTransport.SSH else "",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("x86_64", "amd64"),
        ("x86-64", "amd64"),
        ("AMD64", "amd64"),
        ("aarch64", "arm64"),
        ("arm64", "arm64"),
    ],
)
def test_arch_aliases_are_normalized(raw: str, expected: str) -> None:
    assert normalize_arch(raw) == expected


def test_pwn_prefers_native_amd64_without_hardcoding_a_host() -> None:
    local_arm = _worker("mac-arm", "arm64", WorkerTransport.LOCAL)
    remote_amd = _worker("linux-x86", "amd64", WorkerTransport.SSH)
    registry = WorkerRegistry([local_arm, remote_amd])

    requirements = requirements_for_challenge(ChallengeMeta(category="pwn"))

    assert requirements.required_arch is None
    assert requirements.preferred_arch == "amd64"
    assert registry.select(requirements) == remote_amd


def test_explicit_arch_tag_is_a_hard_requirement() -> None:
    local_arm = _worker("mac-arm", "arm64", WorkerTransport.LOCAL)
    remote_amd = _worker("linux-x86", "amd64", WorkerTransport.SSH)
    registry = WorkerRegistry([local_arm, remote_amd])

    requirements = requirements_for_challenge(
        ChallengeMeta(category="misc", tags=["arch:arm64"])
    )

    assert requirements.required_arch == "arm64"
    assert registry.select(requirements) == local_arm


def test_local_worker_wins_when_capabilities_are_equal() -> None:
    local = _worker("local", "amd64", WorkerTransport.LOCAL)
    remote = _worker("remote", "amd64", WorkerTransport.SSH)
    registry = WorkerRegistry([remote, local])

    selected = registry.select(WorkerRequirements(required_arch="amd64"))

    assert selected == local


def test_native_worker_wins_over_local_emulation() -> None:
    emulated_local = WorkerSpec(
        name="apple-silicon-emulation",
        transport=WorkerTransport.LOCAL,
        os="linux",
        arch="amd64",
        native_arch="arm64",
        image="ctf-sandbox:amd64",
    )
    native_remote = _worker("native-linux", "amd64", WorkerTransport.SSH)
    registry = WorkerRegistry([emulated_local, native_remote])

    selected = registry.select(WorkerRequirements(preferred_arch="amd64"))

    assert not emulated_local.is_native
    assert native_remote.is_native
    assert selected == native_remote


def test_worker_profile_must_cover_challenge_requirement() -> None:
    standard_only = _worker(
        "standard",
        "arm64",
        WorkerTransport.LOCAL,
        profiles=frozenset({"standard"}),
    )
    registry = WorkerRegistry([standard_only])

    with pytest.raises(RuntimeError, match="profile=debug"):
        registry.select(WorkerRequirements(security_profile="debug"))


def test_worker_config_rejects_embedded_password(tmp_path: Path) -> None:
    config = tmp_path / "workers.yml"
    config.write_text(
        """
version: 1
workers:
  - name: remote
    transport: ssh
    os: linux
    arch: amd64
    image: ctf-sandbox:amd64
    ssh_host: worker.example
    password: forbidden
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not contain credentials"):
        load_worker_registry(config)


def test_worker_config_loads_generic_ssh_alias(tmp_path: Path) -> None:
    config = tmp_path / "workers.yml"
    config.write_text(
        """
version: 1
workers:
  - name: remote-amd64
    transport: ssh
    os: linux
    arch: x86_64
    image: ctf-sandbox:amd64
    max_concurrency: 2
    ssh_host: ctf-amd64
    ssh_user: solver
    remote_root: /srv/ctf-agent
""".strip(),
        encoding="utf-8",
    )

    worker = load_worker_registry(config).workers[0]

    assert worker.arch == "amd64"
    assert worker.native_arch == "amd64"
    assert worker.is_native
    assert worker.ssh_host == "ctf-amd64"
    assert worker.ssh_user == "solver"
    assert worker.docker_platform == "linux/amd64"
