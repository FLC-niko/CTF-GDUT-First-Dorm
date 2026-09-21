# Development changelog

## 2026-09-21 — M4 sandbox lifecycle, security profiles, and remote worker routing

- Replaced start-only semaphore with full container lifecycle leases (`acquire_lifecycle_lease` / `release_lifecycle_lease`) ensuring limits hold across the entire lifetime of a container and release safely on errors and cancellations.
- Governed default container resources: reduced memory default from 16GB to 4GB, added configurable CPU limits (default 2.0), PIDs limits (default 512), and network mode controls.
- Enforced least-privilege security profiles (`standard`, `debug`, `forensics`, `nested`) via `resolve_sandbox_profile`: containers drop `ALL` capabilities by default, granting `SYS_PTRACE` or `SYS_ADMIN` only when demanded by challenge type or tags.
- Added capability-based `WorkerRegistry` supporting local and SSH workers with platform normalization (`amd64`, `arm64`) and requirement-based routing (e.g. routing Pwn/Reverse to native amd64 workers). Storing passwords or tokens in worker config is strictly forbidden.
- Implemented `RemoteDockerSandbox` with automated challenge attachment tarball synchronization over SSH, isolated run directories, and safe cleanup without dangling containers.
- Unified sandbox creation across `Solver`, `CodexSolver`, and `ClaudeSolver` using `create_sandbox`.
- Extended `ctf-doctor` with offline, secrets-redacted worker configuration diagnostics.
- Added extensive test coverage: `tests/test_sandbox_lifecycle.py`, `tests/test_workers.py`, `tests/test_remote_sandbox.py`, and `tests/test_remote_sandbox_integration.py`.
- Verified with CPython 3.14.7: `263 passed, 4 skipped, 1 warning`; real Docker integration passed on local arm64 daemon; `ruff check backend tests` and `git diff --check` passed.

## 2026-09-21 — Apple Silicon Linux/arm64 sandbox acceptance

- Built `ctf-sandbox:arm64` successfully on the target Mac with an `aarch64` Docker daemon; all 18 Dockerfile steps, CADO-NFS compilation, image export, and unpack completed without QEMU or `ldconfig` failure.
- Added an optional Ubuntu ports mirror plus bounded apt/radare2 network retries. The successful build used USTC HTTPS after the default ports route returned 500/502; no failed tool layer was skipped.
- Inspected the resulting image as `linux/arm64`, ID `sha256:2d6445bd24798e5154ba06a0e6129d23ab824c7ea03817090c040c34d493a629`, size 2233556849 bytes.
- Smoke-tested Python, Sage, GDB, radare2, StegSeek, CADO-NFS, pwntools, angr, Z3, and pyghidra. Flatter completed a real 2x2 lattice reduction with exit code 0.
- Generalized the opt-in Docker integration assertion through `CTF_SANDBOX_ARCH` while retaining `x86_64` as the default. The ARM64 lifecycle test passed: `1 passed in 1.15s`.
- Scope boundary: this validates the Mac ARM64 image for general workloads, not native execution/debugging of x86-64 Pwn/Reverse binaries; those still require a native Linux/amd64 worker.

## 2026-09-21 — M1–M3 provider runtime and safety governance

- Finished the protocol-specific provider routes `cpa-responses`, `cpa-chat`, `go-responses`, `go-chat`, and `go-messages`. Model IDs remain exact configuration values; no model-name heuristic assigns protocol, capability, or Fast/Expert/Racing role.
- Added CPA Responses and Chat Completions runtime adapters, plus OpenCode Go Responses, Chat Completions, and Anthropic Messages adapters. Fake HTTP regressions exercise a complete tool call, tool result, and final-answer turn for all three wire protocols without consuming provider quota.
- OpenCode Go solvers now use an isolated stable session ID per solver, preserve it across that solver's turns, and send `x-opencode-session` plus `User-Agent: ctf-agent/0.1`. The Anthropic client base intentionally omits `/v1` because its SDK appends `/v1/messages`.
- Added provider-neutral error classification, shared per-provider concurrency, soft/hard token budgets, short 429 circuit breaking, persistent quota/hard-budget circuits, and server-reported subscription usage without inventing per-request dollar costs. Potentially metered fallback remains disabled unless explicitly opted in.
- Changed the CLI safety default to `--no-submit`; only an explicit `--submit` enables platform submission. Candidate Flags use `flag_candidate`, platform-confirmed state remains separate, and traces/logs redact Flags, credentials, authorization headers, cookies, and token-like values.
- Default coordinator/model configuration now relies on local Codex only and does not require Claude. Existing Swarm and Coordinator architecture was reused rather than replaced.
- Added opt-in live smoke tests guarded by `RUN_PROVIDER_LIVE=1` and an explicit CPA/Go model selector. The current checkout has no CPA or OpenCode Go credential, so no real provider request has been claimed as successful.
- Verification with CPython 3.14.7 on macOS arm64: `232 passed, 3 skipped, 1 warning`; the skips are two opt-in provider smoke cases and one opt-in Docker integration. The suite includes candidate-versus-confirmed racing coverage; `ruff check backend tests` and `git diff --check` passed.

## 2026-09-21 — M1 provider registry and offline doctor (first slice)

- Aligned from clean `feat/cpa-go-routing` at `6ddad632bb1ba66f408b5a089d927d65bc0aa8f6`; a live read-only query of `origin` (`FLC-niko/CTF-GDUT-First-Dorm`) returned only that branch at the same SHA. M0.5 remains the completed Linux/amd64 baseline and no Provider Registry code existed before this slice.
- Added an immutable registry for existing providers plus explicit `cpa-responses`, `cpa-chat`, `go-chat`, `go-messages`, and `go-responses` routes. Protocol is selected by the provider alias, never inferred from a model name.
- Added `ModelSpec` with exact model-ID preservation, an `unassigned` default role, and unknown-by-default capabilities so Fast/Expert/Racing assignments remain benchmark/configuration decisions.
- Added separate CPA/OpenCode Go settings fields without endpoint defaults. Registered CPA/Go routes fail with an explicit `adapter pending` error until M2/M3 implements and verifies their wire adapters.
- Added `ctf-doctor`, which performs offline host, redacted provider configuration, Docker daemon, and local image checks. It sends no provider/platform request and never prints a credential or complete configured endpoint.
- Added regression coverage for protocol routing, unknown providers, exact model IDs, pending adapters, missing credentials, URL userinfo rejection, secret redaction, and fixed read-only Docker probe commands.
- Verification on macOS arm64 with CPython 3.14.7: focused tests `14 passed, 1 warning`; full suite `205 passed, 1 skipped, 1 warning`; `ruff check backend tests` passed; changed Python files pass `ruff format --check`.
- Existing baseline remains unchanged: `ruff check .` reports the same 15 issues in `pull_challenges.py`. The opt-in real-Docker test was skipped, and local doctor reported the Docker daemon unavailable.
- Scope guard: no paid/model API request, `/models` discovery, platform fetch, flag submission, runtime provider adapter, Swarm/Coordinator rewrite, fallback, or automatic role assignment was added.
- Remaining M1 work: fake HTTP protocol tests, CPA Responses/Chat runtime adapters, provider error taxonomy, optional redacted online discovery, and real credential smoke tests when explicitly configured.

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
