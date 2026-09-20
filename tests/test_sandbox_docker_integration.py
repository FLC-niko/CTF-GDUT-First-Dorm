"""Opt-in integration coverage for the real Docker sandbox lifecycle."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiodocker
import pytest

from backend.sandbox import DockerSandbox


def _docker_integration_enabled() -> bool:
    return os.getenv("RUN_DOCKER_INTEGRATION", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    not _docker_integration_enabled(),
    reason="set RUN_DOCKER_INTEGRATION=1 to run the real Docker sandbox test",
)
@pytest.mark.asyncio
async def test_real_docker_sandbox_mount_exec_cancel_and_cleanup(tmp_path: Path) -> None:
    image = os.getenv("CTF_SANDBOX_IMAGE", "ctf-sandbox:amd64")
    challenge_dir = tmp_path / "challenge"
    distfiles = challenge_dir / "distfiles"
    distfiles.mkdir(parents=True)
    (distfiles / "input.txt").write_text("mounted-read-only\n", encoding="utf-8")
    (challenge_dir / "metadata.yml").write_text("name: m0.5-smoke\n", encoding="utf-8")

    sandbox = DockerSandbox(
        image=image,
        challenge_dir=str(challenge_dir),
        memory_limit="2g",
    )
    container_id = ""
    workspace_dir = ""

    try:
        await sandbox.start()
        container_id = sandbox.container_id
        workspace_dir = sandbox.workspace_dir

        mounted = await sandbox.exec(
            "uname -m; cat /challenge/distfiles/input.txt; cat /challenge/metadata.yml"
        )
        assert mounted.exit_code == 0
        assert "x86_64" in mounted.stdout
        assert "mounted-read-only" in mounted.stdout
        assert "name: m0.5-smoke" in mounted.stdout

        readonly = await sandbox.exec("echo forbidden > /challenge/distfiles/input.txt")
        assert readonly.exit_code != 0

        created = await sandbox.exec(
            "printf workspace-ok > /challenge/workspace/result.txt; "
            "file /bin/bash; python3 --version"
        )
        assert created.exit_code == 0
        assert await sandbox.read_file(
            "/challenge/workspace/result.txt"
        ) == "workspace-ok"
        assert (Path(workspace_dir) / "result.txt").read_text(encoding="utf-8") == (
            "workspace-ok"
        )

        running = asyncio.create_task(sandbox.exec("sleep 30"))
        await asyncio.sleep(0.2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        await sandbox.stop()

    assert container_id
    assert not Path(workspace_dir).exists()

    docker = aiodocker.Docker()
    try:
        containers = await docker.containers.list(
            all=True,
            filters={"label": ["ctf-agent"]},
        )
        assert container_id not in {container.id for container in containers}
    finally:
        await docker.close()
