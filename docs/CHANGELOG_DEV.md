# Development changelog

## 2026-09-20 — M0.5 Linux/amd64 sandbox baseline

- Verified Docker Desktop uses a Linux/x86_64 daemon and that `ubuntu:22.04` reports `x86_64` under `--platform linux/amd64`.
- Built the unchanged `sandbox/Dockerfile.sandbox` as `ctf-sandbox:amd64`; all 16 stages completed.
- Smoke-tested architecture, Python, Sage, GDB, radare2, pwntools, flatter, stegseek, and CADO-NFS.
- Confirmed `DockerSandbox.image` is already configurable through CLI/settings/solver construction; no production sandbox configuration change was needed.
- Added an opt-in real-Docker integration test for container startup, read-only challenge mounts, workspace bind mounts, tool execution, cancellation, and cleanup.
- Verification: Docker integration `1 passed`; full suite `191 passed, 1 skipped, 1 warning`; `ruff check backend tests` passed.
- Existing baseline: `ruff check .` still reports 15 issues in `pull_challenges.py`; deliberately left outside M0.5.
- Platform risk: Windows-hosted QEMU arm64 still fails at `ldconfig` with exit 139, while native amd64 succeeds; Apple Silicon arm64 remains a required pre-competition gate.
- Scope guard: no provider, policy, platform, frontend, paid API, fallback, or flag-submission changes.
