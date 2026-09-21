"""Offline, redacted environment diagnostics for CTF Agent."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import click

from backend.config import Settings
from backend.providers import ModelSpec, get_provider_spec
from backend.workers import WorkerTransport, registry_from_settings


class DiagnosticStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    category: str
    name: str
    status: DiagnosticStatus
    detail: str


_CONFIGURED_PROVIDERS = (
    "cpa-responses",
    "cpa-chat",
    "go-chat",
    "go-messages",
    "go-responses",
    "azure",
    "zen",
    "google",
)


def _base_url_state(value: str) -> tuple[bool, str]:
    """Validate a base URL without ever returning the original value."""
    if not value:
        return False, "missing"
    try:
        parsed = urlsplit(value)
        # Accessing .port validates malformed port values.
        _ = parsed.port
    except ValueError:
        return False, "invalid"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "invalid"
    if parsed.username is not None or parsed.password is not None:
        return False, "userinfo-forbidden"
    if parsed.query or parsed.fragment:
        return False, "query-or-fragment-forbidden"
    return True, "configured"


def collect_provider_checks(settings: Settings) -> list[DiagnosticCheck]:
    """Inspect configuration presence only; no provider request is sent."""
    checks: list[DiagnosticCheck] = []
    for provider_name in _CONFIGURED_PROVIDERS:
        spec = get_provider_spec(provider_name)
        base_url = spec.configured_base_url(settings)
        if spec.requires_base_url:
            url_ok, url_state = _base_url_state(base_url)
        else:
            url_ok, url_state = True, "not-required"
        key_ok = spec.credential_configured(settings)

        if base_url and not url_ok:
            status = DiagnosticStatus.ERROR
            detail = f"protocol={spec.protocol.value}; endpoint={url_state}; credential=<redacted>"
        elif url_ok and key_ok:
            status = DiagnosticStatus.OK
            adapter = "available" if spec.runtime_adapter_available else "pending"
            endpoint = "configured" if spec.requires_base_url else "not-required"
            detail = (
                f"protocol={spec.protocol.value}; endpoint=<{endpoint}>; "
                f"credential=<configured>; adapter={adapter}"
            )
        elif (spec.requires_base_url and url_ok) or key_ok:
            status = DiagnosticStatus.WARNING
            detail = (
                f"protocol={spec.protocol.value}; "
                f"endpoint=<{url_state}>; "
                f"credential=<{('configured' if key_ok else 'missing')}>"
            )
        else:
            status = DiagnosticStatus.MISSING
            endpoint = "missing" if spec.requires_base_url else "not-required"
            detail = f"protocol={spec.protocol.value}; endpoint=<{endpoint}>; credential=<missing>"

        checks.append(
            DiagnosticCheck(
                category="provider",
                name=provider_name,
                status=status,
                detail=detail,
            )
        )
    return checks


def collect_model_checks(model_specs: Sequence[str]) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    for raw_spec in model_specs:
        try:
            model = ModelSpec.parse(raw_spec)
            provider = get_provider_spec(model.provider)
        except ValueError:
            checks.append(
                DiagnosticCheck(
                    category="model",
                    name="invalid-model-spec",
                    status=DiagnosticStatus.ERROR,
                    detail="expected a registered provider and a non-empty model ID",
                )
            )
            continue

        adapter = "available" if provider.runtime_adapter_available else "pending"
        checks.append(
            DiagnosticCheck(
                category="model",
                name=model.provider,
                status=DiagnosticStatus.OK,
                detail=(
                    f"model-id=<preserved>; role={model.role.value}; "
                    f"protocol={provider.protocol.value}; adapter={adapter}"
                ),
            )
        )
    return checks


def collect_host_checks() -> list[DiagnosticCheck]:
    current = sys.version_info
    python_ok = current >= (3, 14)
    return [
        DiagnosticCheck(
            category="host",
            name="python",
            status=DiagnosticStatus.OK if python_ok else DiagnosticStatus.WARNING,
            detail=f"{current.major}.{current.minor}.{current.micro}; requires >=3.14",
        ),
        DiagnosticCheck(
            category="host",
            name="platform",
            status=DiagnosticStatus.OK,
            detail=f"{platform.system() or 'unknown'}/{platform.machine() or 'unknown'}",
        ),
    ]


def collect_worker_checks(settings: Settings) -> list[DiagnosticCheck]:
    """Validate worker routing without connecting to SSH or Docker endpoints."""
    try:
        registry = registry_from_settings(settings)
    except (OSError, TypeError, ValueError) as exc:
        return [
            DiagnosticCheck(
                category="worker",
                name="registry",
                status=DiagnosticStatus.ERROR,
                detail=f"invalid worker configuration ({type(exc).__name__})",
            )
        ]

    checks: list[DiagnosticCheck] = []
    for worker in registry.workers:
        transport_detail = worker.transport.value
        if worker.transport is WorkerTransport.SSH:
            transport_detail += "; endpoint=<configured>; auth=<external>"
        checks.append(
            DiagnosticCheck(
                category="worker",
                name=worker.name,
                status=DiagnosticStatus.OK,
                detail=(
                    f"transport={transport_detail}; platform={worker.docker_platform}; "
                    f"execution={'native' if worker.is_native else 'emulated'}; "
                    f"image=<configured>; concurrency={worker.max_concurrency}; "
                    f"profiles={','.join(sorted(worker.security_profiles))}"
                ),
            )
        )
    return checks


def collect_docker_checks(
    settings: Settings,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
) -> list[DiagnosticCheck]:
    """Inspect local Docker state with fixed, read-only commands."""
    docker = which("docker")
    if docker is None:
        return [
            DiagnosticCheck(
                category="docker",
                name="daemon",
                status=DiagnosticStatus.MISSING,
                detail="Docker CLI not found",
            )
        ]

    try:
        version = run(
            [docker, "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return [
            DiagnosticCheck(
                category="docker",
                name="daemon",
                status=DiagnosticStatus.WARNING,
                detail="Docker daemon unavailable or timed out",
            )
        ]

    if version.returncode != 0:
        return [
            DiagnosticCheck(
                category="docker",
                name="daemon",
                status=DiagnosticStatus.WARNING,
                detail="Docker daemon unavailable",
            )
        ]

    daemon_detail = version.stdout.strip() or "available (architecture unavailable)"
    checks = [
        DiagnosticCheck(
            category="docker",
            name="daemon",
            status=DiagnosticStatus.OK,
            detail=daemon_detail,
        )
    ]

    try:
        image = run(
            [
                docker,
                "image",
                "inspect",
                settings.sandbox_image,
                "--format",
                "{{.Os}}/{{.Architecture}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        image = None

    if image is not None and image.returncode == 0:
        image_detail = image.stdout.strip() or "present (architecture unavailable)"
        image_status = DiagnosticStatus.OK
    else:
        image_detail = "configured sandbox image not found locally"
        image_status = DiagnosticStatus.MISSING
    checks.append(
        DiagnosticCheck(
            category="docker",
            name="sandbox-image",
            status=image_status,
            detail=image_detail,
        )
    )
    return checks


def build_doctor_report(
    settings: Settings,
    model_specs: Sequence[str] = (),
) -> list[DiagnosticCheck]:
    """Build the complete offline report."""
    return [
        *collect_host_checks(),
        *collect_provider_checks(settings),
        *collect_model_checks(model_specs),
        *collect_worker_checks(settings),
        *collect_docker_checks(settings),
    ]


@click.command()
@click.option(
    "--model",
    "model_specs",
    multiple=True,
    help="检查模型规格的 provider/protocol 路由；不会请求模型接口",
)
@click.option("--json-output", is_flag=True, help="输出机器可读 JSON")
def doctor(model_specs: tuple[str, ...], json_output: bool) -> None:
    """离线检查 provider、宿主和 Docker 配置；不发送任何网络请求。"""
    checks = build_doctor_report(Settings(), model_specs)
    if json_output:
        click.echo(json.dumps([asdict(check) for check in checks], ensure_ascii=False))
    else:
        click.echo("CTF Agent doctor (offline, secrets redacted)")
        for check in checks:
            click.echo(f"[{check.status.value:7}] {check.category}/{check.name}: {check.detail}")

    if any(check.status is DiagnosticStatus.ERROR for check in checks):
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    doctor()
