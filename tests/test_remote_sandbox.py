from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

import pytest

import backend.remote_sandbox as remote_module
import backend.sandbox as sandbox_module
from backend.config import Settings
from backend.prompts import ChallengeMeta
from backend.remote_sandbox import RemoteDockerSandbox, _challenge_archive
from backend.sandbox import ExecResult
from backend.sandbox_factory import create_sandbox
from backend.workers import WorkerSpec, WorkerTransport


def _remote_worker(**overrides: Any) -> WorkerSpec:
    values: dict[str, Any] = {
        "name": "amd64-worker",
        "transport": WorkerTransport.SSH,
        "os": "linux",
        "arch": "amd64",
        "image": "ctf-sandbox:amd64",
        "max_concurrency": 1,
        "ssh_host": "ctf-amd64",
        "ssh_user": "solver",
        "remote_root": "/tmp/ctf-agent",
    }
    values.update(overrides)
    return WorkerSpec(**values)


@pytest.fixture(autouse=True)
def _reset_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_module, "_lifecycle_semaphore", None)
    monkeypatch.setattr(remote_module, "_worker_semaphores", {})


def test_challenge_archive_contains_only_synced_inputs(tmp_path: Path) -> None:
    challenge = tmp_path / "challenge"
    (challenge / "distfiles").mkdir(parents=True)
    (challenge / "metadata.yml").write_text("name: sync-test\n", encoding="utf-8")
    (challenge / "distfiles" / "input.bin").write_bytes(b"input")
    (challenge / "private-note.txt").write_text("do-not-sync", encoding="utf-8")

    archive_data = _challenge_archive(str(challenge))

    with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as archive:
        names = set(archive.getnames())
    assert "metadata.yml" in names
    assert "distfiles/input.bin" in names
    assert "private-note.txt" not in names


def test_remote_create_command_uses_worker_capabilities_not_host_constants(
    tmp_path: Path,
) -> None:
    challenge = tmp_path / "challenge"
    (challenge / "distfiles").mkdir(parents=True)
    (challenge / "metadata.yml").write_text("name: remote\n", encoding="utf-8")
    sandbox = RemoteDockerSandbox(
        worker=_remote_worker(loop_device="/dev/loop-control"),
        challenge_dir=str(challenge),
        security_profile="debug",
        network_mode="none",
    )
    sandbox._remote_run_dir = "/tmp/ctf-agent/run-test"

    command = sandbox._docker_create_command()

    assert "ctf-sandbox:amd64" in command
    assert "--cap-add SYS_PTRACE" in command
    assert "SYS_ADMIN" not in command
    assert "--network none" in command
    assert "host.docker.internal" not in command
    assert "/tmp/ctf-agent/run-test/challenge/distfiles" in command
    assert "/dev/loop-control" not in command


@pytest.mark.asyncio
async def test_remote_start_synchronizes_before_container_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = tmp_path / "challenge"
    (challenge / "distfiles").mkdir(parents=True)
    (challenge / "metadata.yml").write_text("name: remote\n", encoding="utf-8")
    (challenge / "distfiles" / "input.txt").write_text("payload", encoding="utf-8")
    sandbox = RemoteDockerSandbox(_remote_worker(), str(challenge))
    calls: list[tuple[str, bytes | None]] = []

    async def fake_ssh(
        command: str,
        *,
        input_data: bytes | None = None,
        timeout: int = 60,
    ) -> ExecResult:
        del timeout
        calls.append((command, input_data))
        if "image inspect" in command:
            return ExecResult(0, "linux/amd64\n", "")
        if "mktemp -d" in command:
            return ExecResult(0, "/tmp/ctf-agent/run-abcd", "")
        if command.startswith("tar -xzf"):
            assert input_data is not None
            with tarfile.open(fileobj=io.BytesIO(input_data), mode="r:gz") as archive:
                assert "distfiles/input.txt" in archive.getnames()
            return ExecResult(0, "", "")
        if "docker create" in command:
            return ExecResult(0, "container-id\n", "")
        return ExecResult(0, "container-id\n", "")

    monkeypatch.setattr(sandbox, "_ssh", fake_ssh)

    await sandbox.start()

    assert sandbox.container_id == "container-id"
    assert sandbox.workspace_dir == "/tmp/ctf-agent/run-abcd/challenge/workspace"
    commands = [command for command, _ in calls]
    prepare_command = next(command for command in commands if "mktemp -d" in command)
    assert 'chmod 0711 "$run_dir"' in prepare_command
    assert 'chmod 0777 "$run_dir/challenge/workspace"' in prepare_command
    assert next(i for i, command in enumerate(commands) if command.startswith("tar -xzf")) < next(
        i for i, command in enumerate(commands) if "docker create" in command
    )

    await sandbox.stop()
    assert any("docker rm -f" in command for command, _ in calls)
    assert any("rm -rf" in command for command, _ in calls)


@pytest.mark.asyncio
async def test_platform_mismatch_releases_worker_and_global_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = tmp_path / "challenge"
    challenge.mkdir()
    sandbox = RemoteDockerSandbox(_remote_worker(), str(challenge))

    async def wrong_platform(
        command: str,
        *,
        input_data: bytes | None = None,
        timeout: int = 60,
    ) -> ExecResult:
        del command, input_data, timeout
        return ExecResult(0, "linux/arm64\n", "")

    monkeypatch.setattr(sandbox, "_ssh", wrong_platform)

    with pytest.raises(RuntimeError, match="platform mismatch"):
        await sandbox.start()

    assert sandbox._global_lease is False
    assert sandbox._worker_lease is False


def test_factory_selects_remote_amd64_for_pwn(tmp_path: Path) -> None:
    config = tmp_path / "workers.yml"
    config.write_text(
        """
version: 1
workers:
  - name: local-arm
    transport: local
    os: linux
    arch: arm64
    image: ctf-sandbox:arm64
  - name: remote-x86
    transport: ssh
    os: linux
    arch: amd64
    image: ctf-sandbox:amd64
    ssh_host: ctf-amd64
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, worker_config_file=str(config))

    sandbox = create_sandbox(settings, str(tmp_path), ChallengeMeta(category="pwn"))

    assert isinstance(sandbox, RemoteDockerSandbox)
    assert sandbox.worker.name == "remote-x86"
