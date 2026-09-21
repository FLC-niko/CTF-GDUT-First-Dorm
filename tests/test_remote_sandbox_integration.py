"""Opt-in lifecycle acceptance for an SSH-backed Docker worker."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from backend.config import Settings
from backend.prompts import ChallengeMeta
from backend.remote_sandbox import RemoteDockerSandbox
from backend.sandbox import configure_semaphore
from backend.sandbox_factory import create_sandbox


def _enabled() -> bool:
    return os.getenv("RUN_REMOTE_DOCKER_INTEGRATION", "").lower() in {
        "1",
        "true",
        "yes",
    }


@pytest.mark.skipif(
    not _enabled(),
    reason="set RUN_REMOTE_DOCKER_INTEGRATION=1 to run the SSH worker test",
)
@pytest.mark.asyncio
async def test_remote_worker_sync_exec_cancel_and_cleanup(tmp_path: Path) -> None:
    config_path = os.environ["WORKER_CONFIG_FILE"]
    expected_arch = os.getenv("REMOTE_SANDBOX_ARCH", "x86_64")
    challenge = tmp_path / "challenge"
    distfiles = challenge / "distfiles"
    distfiles.mkdir(parents=True)
    (distfiles / "input.txt").write_text("remote-mounted-read-only\n", encoding="utf-8")
    (challenge / "metadata.yml").write_text("name: remote-smoke\n", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        worker_config_file=config_path,
        container_memory_limit="2g",
        container_cpu_limit=1.0,
        container_pids_limit=128,
    )
    meta = ChallengeMeta(name="remote-smoke", category="pwn", tags=["arch:amd64"])
    configure_semaphore(1)
    sandbox = create_sandbox(settings, str(challenge), meta)
    assert isinstance(sandbox, RemoteDockerSandbox)
    container_id = ""
    remote_run_dir = ""

    try:
        await sandbox.start()
        container_id = sandbox.container_id
        remote_run_dir = sandbox._remote_run_dir

        mounted = await sandbox.exec(
            "uname -m; cat /challenge/distfiles/input.txt; cat /challenge/metadata.yml"
        )
        assert mounted.exit_code == 0
        assert expected_arch in mounted.stdout
        assert "remote-mounted-read-only" in mounted.stdout
        assert "name: remote-smoke" in mounted.stdout

        readonly = await sandbox.exec("echo forbidden > /challenge/distfiles/input.txt")
        assert readonly.exit_code != 0

        created = await sandbox.exec("printf remote-ok > /challenge/workspace/result.txt")
        assert created.exit_code == 0
        assert await sandbox.read_file("/challenge/workspace/result.txt") == "remote-ok"

        running = asyncio.create_task(sandbox.exec("sleep 30"))
        await asyncio.sleep(0.2)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        await sandbox.stop()

    assert container_id
    assert remote_run_dir
    assert sandbox._container_id == ""
    assert sandbox._remote_run_dir == ""
