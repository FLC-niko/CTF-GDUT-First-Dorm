from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import backend.sandbox as sandbox_module
from backend.config import Settings
from backend.prompts import ChallengeMeta
from backend.sandbox import (
    DockerSandbox,
    configure_semaphore,
    resolve_sandbox_profile,
)
from backend.sandbox_factory import create_sandbox


class _FakeContainer:
    def __init__(self, container_id: str, *, fail_start: bool = False) -> None:
        self.id = container_id
        self.fail_start = fail_start
        self.deleted = False

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")

    async def show(self) -> dict[str, str]:
        return {"Id": self.id}

    async def delete(self, *, force: bool) -> None:
        assert force is True
        self.deleted = True


class _FakeContainers:
    def __init__(self, queue: list[_FakeContainer], configs: list[dict[str, Any]]) -> None:
        self.queue = queue
        self.configs = configs

    async def create(self, config: dict[str, Any]) -> _FakeContainer:
        self.configs.append(config)
        return self.queue.pop(0)


class _FakeDocker:
    def __init__(self, queue: list[_FakeContainer], configs: list[dict[str, Any]]) -> None:
        self.containers = _FakeContainers(queue, configs)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_sandbox_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_module, "_lifecycle_semaphore", None)
    monkeypatch.setattr(sandbox_module, "_active_count", 0)


def _install_fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    containers: list[_FakeContainer],
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sandbox_module.aiodocker,
        "Docker",
        lambda: _FakeDocker(containers, configs),
    )
    return configs


@pytest.mark.asyncio
async def test_container_limit_is_held_for_complete_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_docker(
        monkeypatch,
        [_FakeContainer("a" * 64), _FakeContainer("b" * 64)],
    )
    configure_semaphore(1)
    first = DockerSandbox("image", str(tmp_path / "first"))
    second = DockerSandbox("image", str(tmp_path / "second"))

    await first.start()
    second_start = asyncio.create_task(second.start())
    await asyncio.sleep(0)

    assert not second_start.done()

    await first.stop()
    await asyncio.wait_for(second_start, timeout=1)
    assert second.container_id == "b" * 64
    await second.stop()


@pytest.mark.asyncio
async def test_failed_start_releases_lifecycle_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _FakeContainer("a" * 64, fail_start=True)
    healthy = _FakeContainer("b" * 64)
    _install_fake_docker(monkeypatch, [failed, healthy])
    configure_semaphore(1)

    first = DockerSandbox("image", str(tmp_path / "first"))
    with pytest.raises(RuntimeError, match="start failed"):
        await first.start()

    assert failed.deleted is True
    assert first.workspace_dir == ""

    second = DockerSandbox("image", str(tmp_path / "second"))
    await asyncio.wait_for(second.start(), timeout=1)
    await second.stop()


def test_container_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        configure_semaphore(0)


def test_standard_profile_drops_capabilities_and_can_disable_network() -> None:
    sandbox = DockerSandbox(
        "image",
        "/challenge",
        memory_limit="2g",
        cpu_limit=1.5,
        pids_limit=128,
        security_profile="standard",
        network_mode="none",
    )

    config = sandbox._host_config(["/host:/challenge/workspace:rw"])

    assert config["CapDrop"] == ["ALL"]
    assert "CapAdd" not in config
    assert config["SecurityOpt"] == ["no-new-privileges=true"]
    assert config["Memory"] == 2 * 1024 * 1024 * 1024
    assert config["MemorySwap"] == config["Memory"]
    assert config["NanoCpus"] == 1_500_000_000
    assert config["PidsLimit"] == 128
    assert config["NetworkMode"] == "none"
    assert "ExtraHosts" not in config


@pytest.mark.parametrize(
    ("category", "tags", "expected"),
    [
        ("pwn", [], "debug"),
        ("Reverse", [], "debug"),
        ("forensics", [], "forensics"),
        ("misc", ["docker-in-docker"], "nested"),
        ("crypto", [], "standard"),
    ],
)
def test_auto_profile_uses_challenge_facts(
    category: str,
    tags: list[str],
    expected: str,
) -> None:
    assert resolve_sandbox_profile(category, tags) == expected


def test_debug_and_forensics_profiles_only_add_required_access() -> None:
    debug = DockerSandbox("image", "/challenge", security_profile="debug")
    debug_config = debug._host_config([])
    assert debug_config["CapAdd"] == ["SYS_PTRACE"]
    assert debug_config["SecurityOpt"] == [
        "no-new-privileges=true",
        "seccomp=unconfined",
    ]
    assert "Devices" not in debug_config

    forensic = DockerSandbox(
        "image",
        "/challenge",
        security_profile="forensics",
        loop_device="/dev/loop-control",
    )
    forensic_config = forensic._host_config([])
    assert forensic_config["CapAdd"] == ["SYS_ADMIN"]
    assert forensic_config["Devices"] == [
        {
            "PathOnHost": "/dev/loop-control",
            "PathInContainer": "/dev/loop-control",
            "CgroupPermissions": "rwm",
        }
    ]


def test_factory_applies_settings_and_auto_profile() -> None:
    settings = Settings(
        _env_file=None,
        sandbox_image="ctf-sandbox:amd64",
        container_memory_limit="3g",
        container_cpu_limit=3.0,
        container_pids_limit=256,
        sandbox_network_mode="none",
    )
    meta = ChallengeMeta(name="debug-me", category="pwn")

    sandbox = create_sandbox(settings, "/challenge", meta)

    assert sandbox.image == "ctf-sandbox:amd64"
    assert sandbox.memory_limit == "3g"
    assert sandbox.cpu_limit == 3.0
    assert sandbox.pids_limit == 256
    assert sandbox.security_profile == "debug"
    assert sandbox.network_mode == "none"


def test_resource_settings_reject_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="container_cpu_limit"):
        Settings(_env_file=None, container_cpu_limit=0)
    with pytest.raises(ValueError, match="container_pids_limit"):
        Settings(_env_file=None, container_pids_limit=0)
