from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from backend.config import Settings
from backend.doctor import (
    DiagnosticStatus,
    collect_docker_checks,
    collect_provider_checks,
    collect_worker_checks,
    doctor,
)


class _Completed:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_provider_checks_allow_missing_credentials_without_remote_calls() -> None:
    checks = collect_provider_checks(_settings())
    by_name = {check.name: check for check in checks}

    assert by_name["cpa-responses"].status is DiagnosticStatus.MISSING
    assert by_name["go-chat"].status is DiagnosticStatus.WARNING
    assert "credential=<missing>" in by_name["cpa-responses"].detail


def test_provider_checks_only_report_redacted_configuration_state() -> None:
    secret = "canary-super-secret-key"
    checks = collect_provider_checks(
        _settings(
            cpa_responses_base_url="https://cpa.example.test/v1",
            cpa_api_key=secret,
        )
    )
    rendered = repr(checks)

    assert secret not in rendered
    assert "https://cpa.example.test/v1" not in rendered
    cpa = next(check for check in checks if check.name == "cpa-responses")
    assert cpa.status is DiagnosticStatus.OK
    assert "adapter=available" in cpa.detail


def test_provider_checks_reject_url_userinfo_without_echoing_it() -> None:
    username = "canary-user"
    password = "canary-password"
    checks = collect_provider_checks(
        _settings(
            cpa_chat_base_url=f"https://{username}:{password}@cpa.example.test/v1",
            cpa_api_key="canary-key",
        )
    )
    rendered = repr(checks)

    assert username not in rendered
    assert password not in rendered
    assert "canary-key" not in rendered
    cpa = next(check for check in checks if check.name == "cpa-chat")
    assert cpa.status is DiagnosticStatus.ERROR
    assert "userinfo-forbidden" in cpa.detail


def test_docker_checks_use_read_only_fixed_commands() -> None:
    commands: list[list[str]] = []
    timeouts: list[int] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        timeouts.append(kwargs["timeout"])
        if command[1] == "version":
            return _Completed(0, "linux/amd64\n")
        return _Completed(0, "linux/amd64\n")

    checks = collect_docker_checks(
        _settings(sandbox_image="ctf-sandbox:amd64"),
        which=lambda _: "/usr/local/bin/docker",
        run=fake_run,
    )

    assert [check.status for check in checks] == [DiagnosticStatus.OK, DiagnosticStatus.OK]
    assert commands == [
        [
            "/usr/local/bin/docker",
            "version",
            "--format",
            "{{.Server.Os}}/{{.Server.Arch}}",
        ],
        [
            "/usr/local/bin/docker",
            "image",
            "inspect",
            "ctf-sandbox:amd64",
            "--format",
            "{{.Os}}/{{.Architecture}}",
        ],
    ]
    assert timeouts == [5, 30]


def test_docker_checks_fall_back_to_image_id_when_tag_inspect_fails() -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[1] == "version":
            return _Completed(0, "linux/arm64\n")
        if command[1:3] == ["image", "ls"]:
            return _Completed(0, "sha256:abc123\n")
        if command[3] == "ctf-sandbox:arm64":
            return _Completed(1, "")
        return _Completed(0, "linux/arm64\n")

    checks = collect_docker_checks(
        _settings(sandbox_image="ctf-sandbox:arm64"),
        which=lambda _: "/usr/local/bin/docker",
        run=fake_run,
    )

    assert [check.status for check in checks] == [DiagnosticStatus.OK, DiagnosticStatus.OK]
    assert commands[-2:] == [
        [
            "/usr/local/bin/docker",
            "image",
            "ls",
            "--quiet",
            "--no-trunc",
            "ctf-sandbox:arm64",
        ],
        [
            "/usr/local/bin/docker",
            "image",
            "inspect",
            "sha256:abc123",
            "--format",
            "{{.Os}}/{{.Architecture}}",
        ],
    ]


def test_doctor_json_is_offline_and_redacted(monkeypatch) -> None:
    secret = "doctor-canary-key"
    monkeypatch.setattr(
        "backend.doctor.collect_docker_checks",
        lambda settings: [],
    )

    result = CliRunner().invoke(
        doctor,
        ["--json-output", "--model", "cpa-responses/exact-model-id"],
        env={
            "CPA_RESPONSES_BASE_URL": "https://cpa.example.test/v1",
            "CPA_API_KEY": secret,
        },
    )

    assert result.exit_code == 0
    assert secret not in result.output
    assert "https://cpa.example.test/v1" not in result.output
    report = json.loads(result.output)
    assert any(item["name"] == "cpa-responses" for item in report)
    assert any(item["category"] == "model" for item in report)


def test_worker_checks_are_offline_and_redact_ssh_endpoint(tmp_path: Path) -> None:
    config = tmp_path / "workers.yml"
    host = "private-worker.example.test"
    config.write_text(
        f"""
version: 1
workers:
  - name: x86-worker
    transport: ssh
    os: linux
    arch: amd64
    image: ctf-sandbox:amd64
    ssh_host: {host}
""".strip(),
        encoding="utf-8",
    )

    checks = collect_worker_checks(_settings(worker_config_file=str(config)))

    assert len(checks) == 1
    assert checks[0].status is DiagnosticStatus.OK
    assert host not in repr(checks)
    assert "platform=linux/amd64" in checks[0].detail
    assert "auth=<external>" in checks[0].detail


def test_worker_checks_report_invalid_config_without_exposing_path(tmp_path: Path) -> None:
    missing = tmp_path / "sensitive-worker-name.yml"

    checks = collect_worker_checks(_settings(worker_config_file=str(missing)))

    assert checks[0].status is DiagnosticStatus.ERROR
    assert str(missing) not in repr(checks)


def test_pyproject_exposes_ctf_doctor_script() -> None:
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert 'ctf-doctor = "backend.doctor:doctor"' in pyproject
