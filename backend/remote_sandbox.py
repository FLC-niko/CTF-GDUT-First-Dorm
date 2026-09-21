"""SSH-backed Docker sandbox with explicit challenge attachment synchronization."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import shlex
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from backend.sandbox import (
    CONTAINER_LABEL,
    SANDBOX_PROFILES,
    ExecResult,
    acquire_lifecycle_lease,
    release_lifecycle_lease,
)
from backend.workers import WorkerSpec

logger = logging.getLogger(__name__)

_worker_semaphores: dict[str, tuple[int, asyncio.Semaphore]] = {}


def _worker_semaphore(worker: WorkerSpec) -> asyncio.Semaphore:
    configured = _worker_semaphores.get(worker.name)
    if configured is None:
        semaphore = asyncio.Semaphore(worker.max_concurrency)
        _worker_semaphores[worker.name] = (worker.max_concurrency, semaphore)
        return semaphore
    limit, semaphore = configured
    if limit != worker.max_concurrency:
        raise RuntimeError(
            f"Worker '{worker.name}' concurrency changed from {limit} "
            f"to {worker.max_concurrency} while the process is running"
        )
    return semaphore


def _challenge_archive(challenge_dir: str) -> bytes:
    root = Path(challenge_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Challenge directory not found: {root}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        metadata = root / "metadata.yml"
        distfiles = root / "distfiles"
        if metadata.is_file():
            archive.add(metadata, arcname="metadata.yml", recursive=False)
        if distfiles.is_dir():
            archive.add(distfiles, arcname="distfiles", recursive=True)
    return buffer.getvalue()


@dataclass
class RemoteDockerSandbox:
    """A Docker sandbox whose daemon and bind-mounted files live on an SSH worker."""

    worker: WorkerSpec
    challenge_dir: str
    memory_limit: str = "4g"
    cpu_limit: float = 2.0
    pids_limit: int = 512
    security_profile: str = "standard"
    network_mode: str = "bridge"
    workspace_dir: str = ""
    _container_id: str = field(default="", init=False, repr=False)
    _remote_run_dir: str = field(default="", init=False, repr=False)
    _global_lease: bool = field(default=False, init=False, repr=False)
    _worker_lease: bool = field(default=False, init=False, repr=False)
    _exec_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def container_id(self) -> str:
        if not self._container_id:
            raise RuntimeError("Sandbox not started")
        return self._container_id

    @property
    def _target(self) -> str:
        if self.worker.ssh_user:
            return f"{self.worker.ssh_user}@{self.worker.ssh_host}"
        return self.worker.ssh_host

    def _ssh_args(self) -> list[str]:
        args = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=yes",
            "-p",
            str(self.worker.ssh_port),
        ]
        if self.worker.ssh_identity_file:
            args.extend(["-i", self.worker.ssh_identity_file])
        if self.worker.ssh_control_path:
            args.extend(["-S", self.worker.ssh_control_path])
        args.append(self._target)
        return args

    async def _ssh(
        self,
        command: str,
        *,
        input_data: bytes | None = None,
        timeout: int = 60,
    ) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            *self._ssh_args(),
            command,
            stdin=asyncio.subprocess.PIPE if input_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except TimeoutError:
            process.kill()
            await process.wait()
            return ExecResult(-1, "", "SSH command timed out")
        return ExecResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    def _docker_create_command(self) -> str:
        if self.security_profile not in SANDBOX_PROFILES:
            raise ValueError(f"Unknown sandbox security profile: {self.security_profile}")
        if self.cpu_limit <= 0 or self.pids_limit <= 0:
            raise ValueError("Remote sandbox CPU and PID limits must be greater than 0")
        if self.network_mode not in {"bridge", "none"}:
            raise ValueError("network_mode must be 'bridge' or 'none'")

        challenge_root = f"{self._remote_run_dir}/challenge"
        args = [
            "docker",
            "create",
            "--label",
            f"{CONTAINER_LABEL}=true",
            "--workdir",
            "/challenge",
            "--memory",
            self.memory_limit,
            "--memory-swap",
            self.memory_limit,
            "--cpus",
            str(self.cpu_limit),
            "--pids-limit",
            str(self.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--network",
            self.network_mode,
            "--mount",
            f"type=bind,src={challenge_root}/workspace,dst=/challenge/workspace",
        ]
        if self.network_mode == "bridge":
            args.extend(["--add-host", "host.docker.internal:host-gateway"])
        if self.security_profile == "debug":
            args.extend(["--cap-add", "SYS_PTRACE", "--security-opt", "seccomp=unconfined"])
        elif self.security_profile in {"forensics", "nested"}:
            args.extend(["--cap-add", "SYS_ADMIN", "--security-opt", "seccomp=unconfined"])
            if self.worker.loop_device:
                args.extend(
                    ["--device", f"{self.worker.loop_device}:{self.worker.loop_device}:rwm"]
                )

        metadata = Path(self.challenge_dir) / "metadata.yml"
        distfiles = Path(self.challenge_dir) / "distfiles"
        if metadata.is_file():
            args.extend(
                [
                    "--mount",
                    f"type=bind,src={challenge_root}/metadata.yml,dst=/challenge/metadata.yml,readonly",
                ]
            )
        if distfiles.is_dir():
            args.extend(
                [
                    "--mount",
                    f"type=bind,src={challenge_root}/distfiles,dst=/challenge/distfiles,readonly",
                ]
            )
        args.extend([self.worker.image, "sleep", "infinity"])
        return shlex.join(args)

    async def start(self) -> None:
        if self._container_id:
            return
        await acquire_lifecycle_lease()
        self._global_lease = True
        worker_sem = _worker_semaphore(self.worker)
        try:
            await worker_sem.acquire()
            self._worker_lease = True
            inspect = await self._ssh(
                shlex.join(
                    [
                        "docker",
                        "image",
                        "inspect",
                        self.worker.image,
                        "--format",
                        "{{.Os}}/{{.Architecture}}",
                    ]
                )
            )
            if inspect.exit_code != 0:
                raise RuntimeError("Configured remote sandbox image is unavailable")
            actual_platform = inspect.stdout.strip()
            if actual_platform != self.worker.docker_platform:
                raise RuntimeError(
                    f"Remote image platform mismatch: expected {self.worker.docker_platform}, "
                    f"got {actual_platform or 'unknown'}"
                )

            root = shlex.quote(self.worker.remote_root)
            prepare = await self._ssh(
                "set -eu; "
                f"umask 077; mkdir -p {root}; "
                f"run_dir=$(mktemp -d {root}/run-XXXXXX); "
                'mkdir -p "$run_dir/challenge/workspace"; '
                'chmod 0711 "$run_dir"; chmod 0755 "$run_dir/challenge"; '
                'chmod 0777 "$run_dir/challenge/workspace"; '
                'printf "%s" "$run_dir"'
            )
            if prepare.exit_code != 0 or not prepare.stdout.strip():
                raise RuntimeError("Failed to prepare remote sandbox directory")
            self._remote_run_dir = prepare.stdout.strip()
            self.workspace_dir = f"{self._remote_run_dir}/challenge/workspace"

            archive = _challenge_archive(self.challenge_dir)
            sync = await self._ssh(
                f"tar -xzf - -C {shlex.quote(self._remote_run_dir + '/challenge')}",
                input_data=archive,
                timeout=300,
            )
            if sync.exit_code != 0:
                raise RuntimeError("Failed to synchronize challenge files to remote worker")

            created = await self._ssh(self._docker_create_command())
            if created.exit_code != 0 or not created.stdout.strip():
                raise RuntimeError("Failed to create remote sandbox container")
            self._container_id = created.stdout.strip().splitlines()[-1]
            started = await self._ssh(shlex.join(["docker", "start", self._container_id]))
            if started.exit_code != 0:
                raise RuntimeError("Failed to start remote sandbox container")
        except BaseException:
            await self._cleanup()
            raise

    async def exec(self, command: str, timeout_s: int = 300) -> ExecResult:
        if not self._container_id:
            raise RuntimeError("Sandbox not started")
        wrapped = f"timeout --signal=KILL --kill-after=5 {timeout_s} bash -c {shlex.quote(command)}"
        remote_command = shlex.join(
            ["docker", "exec", self._container_id, "bash", "-c", wrapped]
        )
        async with self._exec_lock:
            return await self._ssh(remote_command, timeout=timeout_s + 30)

    async def read_file_bytes(self, path: str) -> bytes:
        if not self._container_id:
            raise RuntimeError("Sandbox not started")
        command = shlex.join(
            ["docker", "exec", self._container_id, "base64", "-w0", path]
        )
        result = await self._ssh(command, timeout=30)
        if result.exit_code != 0:
            raise FileNotFoundError(f"Unable to read remote container path: {path}")
        return base64.b64decode(result.stdout, validate=True)

    async def read_file(self, path: str) -> str | bytes:
        data = await self.read_file_bytes(path)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data

    async def write_file(self, path: str, content: str | bytes) -> None:
        if not self._container_id:
            raise RuntimeError("Sandbox not started")
        data = content.encode("utf-8") if isinstance(content, str) else content
        command = (
            f"base64 -d | docker exec -i {shlex.quote(self._container_id)} "
            f"sh -c {shlex.quote('cat > ' + shlex.quote(path))}"
        )
        result = await self._ssh(
            command,
            input_data=base64.b64encode(data),
            timeout=30,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Unable to write remote container path: {path}")

    async def copy_from(self, container_path: str, host_path: str) -> None:
        data = await self.read_file_bytes(container_path)
        destination = Path(host_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    async def _cleanup(self) -> None:
        cleanup_error: RuntimeError | None = None
        try:
            if self._container_id:
                await self._ssh(
                    shlex.join(["docker", "rm", "-f", self._container_id]),
                    timeout=30,
                )
                self._container_id = ""
            if self._remote_run_dir:
                expected_prefix = self.worker.remote_root.rstrip("/") + "/run-"
                if not self._remote_run_dir.startswith(expected_prefix):
                    cleanup_error = RuntimeError(
                        "Refusing to remove unexpected remote sandbox path"
                    )
                else:
                    await self._ssh(
                        shlex.join(["rm", "-rf", "--", self._remote_run_dir]),
                        timeout=30,
                    )
                self._remote_run_dir = ""
                self.workspace_dir = ""
        finally:
            if self._worker_lease:
                _worker_semaphore(self.worker).release()
                self._worker_lease = False
            if self._global_lease:
                release_lifecycle_lease()
                self._global_lease = False
        if cleanup_error is not None:
            raise cleanup_error

    async def stop(self) -> None:
        await self._cleanup()
        logger.info("Remote sandbox stopped on worker %s", self.worker.name)
