# HuntingBlade M0 架构审计与环境基线

> 审计日期：2026-09-20
> 审计范围：M0 与 M0.5（基线审计、环境检测、Linux/amd64 沙箱验收与 M1 实施清单）
> 结论口径：`实测` 表示命令在本次会话真实执行；`静态确认` 表示从当前源码确认；`阻塞` 表示尚未在目标环境跑通。未执行真实比赛平台抓取、提交、正式赛题探测或 M1 provider 改造。

## 1. 基线与许可

| 项目 | 结果 | 证据 |
|---|---|---|
| checkout | `D:\xxx\CTF\HuntingBlade` | 在空的 `D:\xxx\CTF` 下克隆到独立子目录，没有覆盖既有工程 |
| origin | `https://github.com/D1a0y1bb/HuntingBlade.git` | `git remote get-url origin` |
| upstream SHA | `f4cae4d0ed897ccf3645742dc719b3755ba1ae83` | `git rev-parse HEAD` |
| commit 时间/主题 | `2026-04-07T18:59:49+08:00` / `refactor: 完成 capability layer 收尾` | `git show -s` |
| 工作分支 | `feat/cpa-go-routing` | 新建分支，没有 reset、clean 或丢弃改动 |
| 许可证 | MIT，`Copyright (c) 2026 Veria Labs, Inc.` | 根目录 `LICENSE`；二次开发必须保留许可与版权声明 |
| 上游关系 | 当前 checkout 只配置了 `origin`；README 表明它二开自 `verialabs/ctf-agent` | 没有擅自新增或改写 remote |

本次输入的 `AGENTS.md` 与 `DEVELOPMENT_BRIEF.md` 位于 `C:\Users\10643\Downloads`，已完整阅读；当前上游 checkout 原本不包含这两个文件。本审计将其作为用户约束与规划来源，没有把其中尚未实测的描述当成运行事实。

## 2. 当前开发宿主与比赛 Mac 的边界

用户已确认当前开发/调试环境是 Windows，比赛环境大概率使用 Mac。本次 Codex 会话也实测运行在 Windows 主机；因此下表中的 Windows 数据是当前开发基线，但不能代替比赛用 Apple Silicon 的原生验收。规划书中的 Mac 配置只作为候选目标，不当作本次运行事实。

| 检查项 | 当前会话实测 | 状态 |
|---|---|---|
| 宿主系统 | `Microsoft Windows 10.0.26200` | 实测 |
| 宿主/进程架构 | `x64` / `x64` | 实测 |
| 系统 Python | `3.13.5`，`C:\Python313\python.exe` | 实测；不满足 `pyproject.toml` 的 `>=3.14` |
| uv | 初始缺失；工作区本地安装 `uv 0.12.17` | 实测；没有修改全局 PATH |
| 项目 Python | uv 下载并使用 `CPython 3.14.7`，虚拟环境为 `.venv` | 实测 |
| Docker CLI | `29.1.3`，Windows/amd64 | 实测 |
| Docker daemon | 用户启动后可用：Server `29.1.3`、Linux/x86_64、32 CPU、约 15.2 GiB、`overlayfs` | 实测；这是 Docker Desktop VM，不是目标 Mac |
| buildx / BuildKit | `buildx v0.30.1-desktop.1`、BuildKit `v0.26.2`；注册 binfmt 后 builder 报告支持 `linux/arm64` | 实测 |
| 比赛用 Mac | 大概率使用 Mac；具体型号、macOS 版本、`uname -m`、Docker Desktop 资源限制均未在本会话取得 | 比赛前必须在实际设备再验收 |

### 2.1 依赖快照

`uv sync --all-groups` 成功解析 128 个包、安装 125 个包。主要直接依赖实测为：

- `pydantic-ai 2.46.0`、`pydantic-settings 2.15.0`
- `aiodocker 0.27.0`、`httpx 0.28.1`
- `claude-agent-sdk 0.2.157`、`boto3 1.43.98`
- `genai-prices 0.1.7`、`click 8.5.0`、`rich 15.0.0`
- dev：`pytest 9.1.1`、`pytest-asyncio 1.4.0`、`ruff 0.16.8`、`ty 0.0.82`

依赖风险：

1. 仓库没有受版本控制的 `uv.lock`，而 `.gitignore` 明确忽略它；当前宽松依赖会随时间漂移。
2. 同步时 uv 报告 `pydantic-ai==2.46.0` 不再提供名为 `google`、`openai` 的 extras。当前环境仍因解析链装入了 `openai` 和 `google-genai`，但声明已过时，应在 M1 单独修正并锁定。
3. Dockerfile 中大量 `git clone --depth=1` 和未锁版本的 `pip3 install` 使镜像不可复现。

### 2.2 CPA / Go / 本地 CLI 配置存在性（全部脱敏）

只检查了存在性、配置字段名和非敏感模型名；没有输出 Key、Token、Cookie 或 base URL。

| 项目 | 实测结果 |
|---|---|
| 仓库 `.env` | 不存在 |
| 相关环境变量 | `OPENAI_*`、`AZURE_OPENAI_*`、`GEMINI_API_KEY`、`OPENCODE_*`、`CTFD_TOKEN`、`LINGXU_COOKIE` 均未检测到非空值 |
| Codex CLI | 存在，`codex-cli 0.155.0-alpha.9.2` |
| Codex 本地配置 | `~/.codex/config.toml` 存在，公开模型字段为 `gpt-5.6-sol`；没有 `base_url` 或凭据字段，未发现可归因于 CPA 的 provider 配置 |
| OpenCode CLI | 未安装/未在 PATH |
| OpenCode Go 配置 | 常见 AppData 路径未发现；`~/.config/opencode/opencode.json` 因当前沙箱权限拒绝读取，故不能断言该路径绝对不存在 |
| Claude CLI | 安装了 `2.1.87`，但用户明确没有 Claude 订阅；不得作为默认路径或可用能力 |

结论：本机有 Codex 客户端资产，但本仓库当前没有可识别的 CPA/Go API 配置，也没有可用于真实 provider smoke 的环境变量。M1 必须从脱敏 capability discovery 开始，不能硬编码展示名或猜测协议。

## 3. 源码架构映射

### 3.1 CLI 与配置

- `backend/cli.py`
  - 复用：单题/整场入口、显式重复 `--models`、`--coordinator none|azure|codex|claude`、`--no-submit`、手动导题入口都已存在。
  - 扩展：增加 `ctf doctor`（或等价子命令）、provider capability discovery、全局 solver 槽位/每 provider 槽位、脱敏诊断输出。
  - 修复：默认 coordinator 是 `claude`，默认模型也包含两个 Claude 路线，与“无 Claude 的默认可启动路径”冲突；`--ctfd-token` 与 `--lingxu-cookie` 允许把秘密直接放进命令历史，应降级为不推荐并优先文件/环境变量。
- `backend/config.py`
  - 复用：Pydantic Settings、`.env`、平台与基础 runtime 配置。
  - 扩展：CPA Responses/Chat、Go Chat/Messages/Responses 的分离配置；模型注册表；总 solver 数、每题 solver 数、每 provider 并发、预算、超时、重试与熔断配置。
  - 修复：默认 `max_concurrent_challenges=10`、`container_memory_limit=16g` 不适合规划中的 M1 Pro 16GB 保守基线。

### 3.2 模型解析与 provider

- `backend/models.py`
  - 复用：`provider/model[/effort]` 解析、Pydantic AI provider 构造、模型 settings、vision/context 查询接口。
  - 静态确认：`azure/*` 无条件构造 `OpenAIResponsesModel`；solver 对 `azure` 还专门使用 `run_stream()`。因此只支持 `/v1/chat/completions` 的 CPA 不能直接伪装成 `azure`。
  - 静态确认：`zen/*` 构造 `OpenAIChatModel`，base URL 固定为 `https://opencode.ai/zen/v1`；它不是 OpenCode Go。
  - 缺失：没有 `cpa-responses`、`cpa-chat`、`go-chat`、`go-messages`、`go-responses`；没有 `/models` discovery、协议探测、稳定 `x-opencode-session`、明确 User-Agent、服务端 usage 原样保存或 Go 额度模型。
  - 修复：`DEFAULT_MODELS` 依赖 Claude/Codex 客户端；上下文、vision、价格映射均以静态展示名为主，和“从真实模型 ID/能力表发现”的要求不符。
- `backend/agents/solver.py`
  - 复用：Pydantic AI 工具循环、同一 solver 的 message history、loop detection、trace、usage 记录、统一 `SolverResult`。
  - 扩展：把 provider-specific 的 stream 分支下沉到 adapter；分类错误（401/403/404/429/quota/protocol/timeout）；请求级取消与有限重试；保留原始 usage 并标注 estimated。
  - 修复：`--no-submit` 下只要模型输出 `FlagFound` 就把内部 `_confirmed=True` 并返回 `flag_found`。虽然 lifecycle 的 `confirmed` 字段仍为 false，但命名会让“候选 flag”和“平台确认”混淆。
- `backend/agents/codex_solver.py`、`backend/agents/claude_solver.py`
  - 复用：各自的 subscription-backed solver 适配层、统一 solver protocol、sandbox/tool bridge。
  - 边界：保留以便跟上游同步，但 M1 默认路径不得要求 Claude；Codex CLI 路线也不能替代需要明确协议/usage/并发控制的 CPA API adapter。

### 3.3 Swarm、Coordinator 与 Policy

- `backend/agents/swarm.py`
  - 复用：同题多 solver racing、共享 findings、flag 去重、错误提交冷却、胜出后取消 sibling、统一 solver factory。
  - 扩展：每题选择模型子集、Fast→Expert→Racing 状态、每题最多 solver 数、provider 熔断/退避、quota-aware fallback、可恢复 run 状态。
  - 修复：当前每道题会启动 `model_specs` 中的全部模型；`GAVE_UP/ERROR` 可能持续 bump（错误仅连续 3 次停止），没有 wall-clock/token/request 总预算。
  - 修复：静态 `QUOTA_FALLBACK` 会把 Codex 配额错误自动转到 Azure/Zen，可能产生意外 API 费用；应默认关闭付费 fallback，必须由策略与预算显式授权。
- `backend/agents/coordinator_loop.py`、`backend/agents/coordinator_core.py`
  - 复用：`poller -> runtime snapshot -> working memory -> strategy -> policy -> action executor` 的共享控制链；`none` 是真正的无顶层 LLM 路径；平台确认后自动收尾。
  - 扩展：持久化 challenge/run/evidence/candidate 状态；全局真实 solver semaphore；崩溃恢复；人工 pause/resume/reassign；triage schema 与独立 scheduler。
  - 修复：`_auto_spawn_unsolved` 对未解题逐题启动整套 swarm，放大为“题目 × 模型”；整场模式仍首先依赖 platform client，不是纯本地 challenge registry。
- `backend/control/policy_engine.py`、`backend/control/state.py`
  - 复用：结构化 action、max concurrent challenges、stall/bump、knowledge broadcast、advisor 只提建议而 policy 执行。
  - 扩展：`TriageResult`、`SolveRun`、Evidence、FlagCandidate 状态；跨题公平性；全局/每 provider/每模型槽位与预算；候选/确认状态机；取消与恢复。
  - 修复：当前选题基本按名称排序，策略只控制 swarm 数，不控制真实 solver/容器/模型调用总数，也没有 Fast/Expert/Racing 分层。

### 3.4 Sandbox 与工具

- `backend/sandbox.py`
  - 复用：每 solver 独立容器；`distfiles` 和 metadata 只读挂载；临时 workspace 可写；命令超时；统一 read/write/copy API。
  - 关键缺陷：`configure_semaphore()` 的 semaphore 只包围 `start()`，容器启动后立即释放，因此它限制的是“同时启动容器”的数量，不是“同时存活/运行的容器”数量。CLI 计算的 `max_challenges * len(models)` 也不是全局运行槽位。
  - 关键缺陷：`stop()` 无条件删除临时 workspace，当前没有可靠的 artifact 归档闭环。
  - 安全风险：容器具备 `SYS_ADMIN`、`SYS_PTRACE`、`seccomp=unconfined`、loop device，并可访问 `host.docker.internal`；这是偏调试能力而非强隔离。M1/M3 前至少要明确 threat model，比赛模式应提供更小权限 profile。
  - 资源默认值：每容器 2 CPU，默认 memory 从 Settings 得到 16 GiB；多个 solver 在 16GB Mac 上会直接过量承诺。
- `backend/tools/core.py`、`backend/capabilities/*`
  - 复用：统一工具实现与 capability assembler。
  - 风险：host-side `web_fetch` 只做字符串级私网 IP 检查，没有 DNS 解析后的目标校验；容器内 `bash/curl/nmap` 也没有授权目标 allowlist。正式比赛集成前必须由 policy/runtime 限定目标范围。

### 3.5 手动导入与生命周期

- `backend/challenge_import.py`
  - 复用：参数验证、metadata 生成、附件目录递归、临时目录构建后原子移动。
  - 修复：同 slug 已存在时会先改名为 backup，成功后删除 backup，即默认替换已有题目。应增加显式 `--replace` 或拒绝覆盖，并保护已有 workspace/evidence。
- `backend/solve_lifecycle.py`
  - 复用：result record、submit status、`confirmed`、环境释放、writeup policy。
  - 正确点：只有平台状态为 `correct` / `already_solved` 才令 record 的 `confirmed=true`，且 `--no-submit` 不释放环境。
  - 扩展：SQLite/事件日志持久化、run_id/challenge_id/provider/session/usage/error class、candidate 单独存储、artifact archive。
  - 修复：`backend/tracing.py` 当前会把 tool args/result、模型文本、`finish(flag=...)` 原样写入 JSONL；这可能记录 API 返回、连接秘密和真实 flag，违反脱敏要求。需要集中 redactor、flag secret reference/hash 与受限证据存储。
  - 修复：`deps.results`、working memory、strategy 和 knowledge 主要在内存，重启后不能恢复。

## 4. Mac ARM64 镜像结论

### 已确认

1. `sandbox/Dockerfile.sandbox` 的基础镜像是 `ubuntu:22.04`。
2. `docker buildx imagetools inspect ubuntu:22.04` 实测公开 manifest 包含 `linux/arm64/v8`，本次索引 digest 为 `sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02`，arm64 manifest digest 为 `sha256:1cc7bb38a74c0e126716646e47c0b3c5c139547d386d5ff7a64cf3ea316ca523`。
3. Dockerfile 对 `stegseek`、`radare2`、`flatter`、CADO-NFS 采用源码构建，没有直接安装已知仅 amd64 的 stegseek `.deb`。
4. Docker daemon 启动后，默认 amd64 builder 直接执行 arm64 镜像会在首个 `RUN` 报 `exec /bin/sh: exec format error`；使用 `tonistiigi/binfmt` 注册 arm64 后，构建器能真实执行 aarch64 用户态程序。
5. 跨架构构建已完成第 2 层的 1,196 个 Ubuntu 包（约 1.3 GB，含 SageMath 9.5）、第 3 层的 Podman/Buildah、第 4 层的 radare2 6.2.3 arm64 源码构建，并完成第 5 层 flatter 的 arm64 编译和安装。radare2 构建报告的 target 为 `aarch64-unknown-linux-gnu`，不是误建为 amd64。
6. `docker run --rm --platform linux/arm64 ubuntu:22.04 uname -m` 实测成功并输出 `aarch64`，证明当前 Windows Docker Desktop 在注册 binfmt 后可执行基础 arm64 容器；这仍不是原生 Mac 验收。

### 未确认/阻塞

`docker buildx build --platform linux/arm64 --load -f sandbox/Dockerfile.sandbox -t ctf-sandbox:arm64-audit .` 已真实进入 Dockerfile，但在第 5/16 层的 `cmake --install flatter && ldconfig` 尾部由 QEMU 报 `uncaught target signal 11`，退出码 139。由于 flatter 本身已经编译并安装，失败点更像 x64 主机的 arm64 用户态模拟/`ldconfig` 问题；这是一项有证据的推断，不等同于证明 Dockerfile 在原生 Apple Silicon 可通过。镜像没有成功导出，因而不能执行最终 `docker run` 或真实 `DockerSandbox` smoke。

因此不能声称完整镜像能在 Mac arm64 构建。下列层/能力仍需目标 Mac 实测：

- `angr`、`fpylll`、`torch`、`pyghidra` 等 Python 包的 arm64 wheel/源码构建；
- `stegseek`、CADO-NFS 与 Dockerfile 余下 11 层的构建；
- 原生 arm64 上的 `ldconfig` 是否避开本次 QEMU SIGSEGV；
- 完整构建时间、峰值内存与最终镜像大小；
- `Devices: /dev/loop-control` 在 Docker Desktop VM 中是否存在；
- `SYS_PTRACE`/GDB 在 Apple Silicon 容器中对 x86-64 ELF 的限制。

目标 Mac 的验收命令见第 7 节。Pwn/Reverse 的 x86-64 动态调试在 arm64 镜像成功后仍须单独标记为“不保证”，不能由基础镜像 manifest 推导成功。

## 5. 已运行命令与结果

| 命令（省略仅用于本地缓存的环境变量） | 结果 |
|---|---|
| `git clone https://github.com/D1a0y1bb/HuntingBlade.git D:\xxx\CTF\HuntingBlade` | 首次受失效的全局 `127.0.0.1:7890` Git 代理阻塞；仅本次命令临时清空 proxy 后成功，没有修改全局配置 |
| `git switch -c feat/cpa-go-routing` | 成功 |
| `uv sync --all-groups` | 成功；CPython 3.14.7；125 packages installed；有过时 extras 警告 |
| `uv run pytest -q` | **191 passed, 1 warning, 5.94s**；warning 来自 `google-genai` 使用计划在 Python 3.17 移除的内部类型 |
| `uv run ruff check .` | **失败：15 errors**；全部位于 `pull_challenges.py`，1 个 import sort、14 个 `Optional` → `X | None`，均标记为可自动修复；M0 未顺手改源码 |
| `uv run ruff check backend tests` | **All checks passed**；说明 15 个全仓 lint 问题都在根目录辅助脚本，不在核心 backend/tests |
| `uv run ctf-solve --help` | exit 0；确认 `none|azure|codex|claude`、`--models`、`--no-submit` 等选项存在；首次 Windows 管道输出乱码，设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 后复测中文正常 |
| `uv run ctf-import --help` | exit 0；选项存在；使用同一 UTF-8 环境复测正常 |
| 离线 CLI dispatch smoke：`--coordinator none --models azure/mock-explicit --no-submit --all-solved-policy exit`，`_run_coordinator` 使用 `AsyncMock` | **PASS**；只证明参数与共享 coordinator 分发正确，不是 provider/tool/sandbox e2e |
| `resolve_model('azure/smoke-model', redacted settings)` | **PASS**；运行时类型为 `OpenAIResponsesModel` |
| `docker version` / `docker info` | daemon 启动后成功；Client Windows/amd64，Server Linux/x86_64，32 CPU，约 15.2 GiB |
| `docker buildx imagetools inspect ubuntu:22.04` | 成功；确认基础镜像有 arm64/v8 manifest |
| `docker run --rm --platform linux/arm64 ubuntu:22.04 uname -m` | 成功；输出 `aarch64`，仅代表 Windows Docker Desktop + binfmt/QEMU 预检通过 |
| 首次 `docker buildx build --platform linux/arm64 ...` | 失败；默认 builder 未注册 arm64，首个 `RUN` 报 `exec format error` |
| `docker run --privileged --rm tonistiigi/binfmt --install arm64` | 成功；为本次 Docker Desktop builder 注册 arm64 模拟 |
| 再次 `docker buildx build --platform linux/arm64 --load ...` | **失败：exit 139**；真实完成 apt、Podman、radare2 和 flatter 编译/安装，随后在第 5/16 层 `ldconfig` 遇到 QEMU SIGSEGV；未生成最终镜像 |

## 6. M0 冒烟验收结论

| 验收项 | 状态 | 说明 |
|---|---|---|
| checkout、SHA、许可、分支 | 通过 | 已核实并记录 |
| Python 3.14 + uv sync | 通过（当前 Windows） | 目标 Mac 仍需复验 |
| 基础测试 | 通过 | 191 tests |
| lint | 未通过（上游基线） | 15 个已定位问题，没有伪装为成功 |
| `ctf-solve` / `ctf-import` CLI | 通过 | 帮助命令 exit 0 |
| `azure` 是否固定 Responses | 通过 | 源码、单测、运行时类型三重确认 |
| `--coordinator none` + 显式模型 + `--no-submit` | 部分通过 | 离线分发通过；完整 solver/sandbox 闭环未跑 |
| mock provider → sandbox tool → 本地结果 | 阻塞 | 当前 resolver 没有正式 fake provider；arm64 sandbox 镜像未构建完成 |
| 公开历史练习题闭环 | 阻塞 | arm64 sandbox 镜像未构建完成，且没有选定并导入公开题包；未伪造结果 |
| 真实 CPA GPT/Gemini/Go | 跳过 | 没有可发现的仓库配置/环境变量；未发送真实 API 请求 |
| Mac arm64 完整镜像 build/run | 阻塞 | 当前不是 Mac；x64+QEMU 构建到第 5/16 层后在 `ldconfig` SIGSEGV，原生 Apple Silicon 尚未验收 |

M0 的核心出口已经满足：当前架构的可复用点、待扩展点、已知缺陷、真实命令结果和独立复现路径均已明确。M1 不应在完成目标 Mac Docker 与脱敏 provider discovery 前宣称端到端完成。

## 7. 目标 Mac 的 M0 补验命令

在目标 Mac 仓库根目录运行，任何输出都不得包含秘密值：

```bash
uname -a
uname -m
sw_vers
sysctl -n machdep.cpu.brand_string
uv --version
python3 --version
docker version
docker info --format 'os={{.OSType}} arch={{.Architecture}} cpus={{.NCPU}} memory={{.MemTotal}}'

uv sync --all-groups
uv run pytest -q
uv run ruff check .
uv run ctf-solve --help
uv run ctf-import --help

docker build --platform linux/arm64 \
  -f sandbox/Dockerfile.sandbox \
  -t ctf-sandbox:arm64-m0 .
docker run --rm --platform linux/arm64 ctf-sandbox:arm64-m0 \
  bash -lc 'uname -m; python3 --version; file /bin/bash; r2 -v; sage --version'
```

补验时还应记录 Docker Desktop 的 CPU/内存限制；建议初始约 4 CPU / 6 GiB，而不是让每个容器请求 16 GiB。若 build 失败，记录首个真实失败层、package/architecture 和完整但脱敏的错误，不用跳过失败层后声称支持 arm64。

## 8. M1 详细改造步骤（下一阶段，不在本次 M0 实施）

建议按下面的小提交顺序进行，避免同时改 scheduler、平台和前端。

### M1.1：安全诊断与 provider 配置骨架

1. 新增 `ProviderConfig` / `ModelDescriptor`，把 provider、protocol、base URL、模型 ID、工具/vision/reasoning 能力分开；配置打印只显示 host 或 `<configured>`，永不显示 Key。
2. 新增 `ctf doctor`：检查版本、宿主/容器架构、Docker、镜像、凭据存在性、`/models` 可达性和协议，不进行比赛平台抓取/提交。
3. 配置前缀明确区分 `cpa-responses`、`cpa-chat`、`go-chat`、`go-messages`、可选 `go-responses`；不复用 `azure`/`zen` 语义。
4. 单测覆盖：缺 key、错误 key、URL 中含 userinfo、日志 redaction、模型 ID 原样保留、未知协议拒绝。

验收：无任何 Key 时 doctor 可成功结束并报告 `missing/skipped`；带 fake 配置时日志快照中没有 secret。

### M1.2：CPA Responses 与 Chat adapter

1. 抽出 OpenAI-compatible provider factory；Responses 使用 `OpenAIResponsesModel`，Chat 使用 `OpenAIChatModel`，禁止按模型展示名猜协议。
2. `/models` 只做 capability discovery；再用 fake HTTP server 分别跑一轮多轮 tool-call → tool-result → final output。
3. 将当前 solver 中 `provider == 'azure'` 的 stream 特判移入 adapter capability，防止新增 provider 继续堆条件。
4. 错误分类为 auth、model_not_found、protocol_mismatch、rate_limit、quota、timeout、cancelled、provider_error。

验收：两个 fake 协议测试都真实走 HTTP wire format；故意把 Chat endpoint 配成 Responses 时得到明确 `protocol_mismatch`，而不是通用 traceback。

### M1.3：OpenCode Go Chat adapter

1. 实现 `go-chat`，URL 默认指向 `/zen/go/v1/chat/completions`，但允许安全配置覆盖。
2. 每个 `SolveRun` 生成稳定的 `x-opencode-session`；同一多轮会话复用，不同 run 不共享；发送明确 User-Agent。
3. 原样保存 usage 响应；缺失时才估算并写 `estimated=true`。
4. `ChatQuotaExceeded`/429 触发有限指数退避、该 provider 熔断与可恢复状态，不自动切到可能收费的 Zen/Azure。

验收：fake server 断言 header/session、tool loop、usage、429/配额与 cancellation；真实 Key 缺失时真实 smoke 明确 `skipped`。

### M1.4：候选 flag、trace 与 artifact 安全修复

1. `SolverResult` 明确区分 `candidate_found` 与 `confirmed`；`--no-submit` 只能产生 candidate/local-check 状态。
2. 集中 trace redactor；submit args、flag、Cookie、Authorization、API Key、URL userinfo 不写普通日志。
3. solver 停止前从 `/challenge/workspace` 归档到 run-specific 目录，失败也保留 manifest；权限与 `.gitignore` 明确。
4. 最小 SQLite schema 写入 challenge/run/evidence/candidate；为 M3 scheduler 留稳定接口，不在 M1 实现复杂调度。

验收：日志扫描测试找不到注入的 canary secret/flag；candidate 不会变成 confirmed；artifact 在容器删除后仍可读取。

### M1.5：非 Claude 默认闭环与真实 smoke

1. 默认启动不再隐式选择 Claude；无已配置 provider 时给出 doctor 指令和非零、可诊断退出。
2. 使用一个可公开再分发的历史练习题，记录来源、许可/公开状态、附件 hash 和本地预期验证器；默认 `--no-submit`。
3. 顺序跑 CPA GPT、CPA Gemini、Go 各一条：显式模型、`--coordinator none`、真实 sandbox tool call、可复核本地结果、脱敏 trace。
4. 只有三路各自成功后才宣称 M1 完成；缺哪一路就记录哪一路 `blocked/skipped`。

验收证据至少包含：run_id、provider/model ID、协议、容器架构、工具调用名与 exit code、local verifier 结果、usage/estimated 标记、耗时、artifact hash；不包含 flag 明文或凭据。

## 9. 下一可执行提交

M0 文档之后建议的第一个 M1 提交：

```text
feat(providers): add redacted provider registry and doctor diagnostics
```

限定范围：只加入配置 schema、protocol enum、脱敏诊断和 fake tests；不改 swarm 调度、不接平台、不引入前端、不发送真实 API 请求。验收为“无 Key 可运行、fake 配置可诊断、日志无 secret、现有 191 项测试继续通过”。随后才分别提交 CPA Responses/Chat 与 Go Chat adapter。

## 10. 决策日志

1. 用户确认当前开发/调试环境为 Windows x64，比赛环境大概率为 Mac；所有 Mac 结论保留为比赛前待补验，不把规划书中的候选 Mac 配置当作本次事实。
2. `azure` 被源码、测试与运行时类型确认是 Responses-only；CPA Chat 必须新增 adapter，不能复用名称。
3. Docker 基础镜像与前四个主要构建层已实测 arm64；完整构建被 x64 主机上的 QEMU `ldconfig` SIGSEGV 阻塞，故不写“Mac arm64 支持完成”，并保留原生 Apple Silicon 补验。
4. 没有可用 Key、Go 配置或完整 sandbox 镜像时跳过真实 API/sandbox 历史题，不用 mock 结果冒充端到端。
5. M0 只新增审计文档，不修 lint、不重构 coordinator/swarm、不接比赛平台。

## 11. M0.5：Windows x64 上的 Linux/amd64 沙箱基线（2026-09-20）

### 11.1 宿主、daemon 与平台预检

本轮仍在 Windows x64 开发机执行，Docker Desktop 已切到 Linux Containers。不会把本轮结果表述为目标 Mac 的原生 arm64 验收。

| 检查 | 实测结果 |
|---|---|
| Docker daemon | `os=linux arch=x86_64 cpus=32 memory=16353402880 driver=overlayfs` |
| BuildKit | v0.26.2；原生 `linux/amd64`，另有 binfmt 的 `linux/arm64` |
| Ubuntu amd64 预检 | `docker run --rm --platform linux/amd64 ubuntu:22.04 uname -m` 输出 `x86_64` |
| Ubuntu 基础镜像 | `ubuntu:22.04`，拉取 digest `sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02` |

Docker 命令在本机使用隔离配置目录 `D:\xxx\CTF\.docker-audit`；该目录只用于 Docker CLI 连接配置，不进入仓库，也不包含本审计需要输出的凭据。

### 11.2 原始 Dockerfile 的 amd64 完整构建

执行命令：

```powershell
docker --config D:\xxx\CTF\.docker-audit build --platform linux/amd64 --progress plain -f sandbox/Dockerfile.sandbox -t ctf-sandbox:amd64 .
```

结果：**成功，16/16 构建步骤及镜像导出全部完成**。没有删除工具、跳过失败层或关闭构建检查。关键证据：

- Ubuntu/Sage 大依赖层完成，`ldconfig` 正常返回；没有复现 arm64 QEMU 的 SIGSEGV。
- radare2 6.2.3 从源码构建并报告 `linux-x86_64`。
- flatter、stegseek、RsaCtfTool、CADO-NFS、uv、pwntools、angr、PyTorch CPU 等层全部完成。
- 最终镜像为 `linux/amd64`，ID `sha256:e1e1e3889dc3df04c8091fa202a23c8551e452d9cf5cd96eb68f9e28c47c6c00`，Docker 报告大小 `2342278201` bytes。

镜像 smoke 命令使用 `docker run --rm --platform linux/amd64 ctf-sandbox:amd64 bash -lc '...'`，实测：

| 项目 | 结果 |
|---|---|
| `uname -m` | `x86_64` |
| Python | 3.10.12 |
| Sage | `sage -c "print(1+1)"` 输出 `2` |
| GDB | Ubuntu 12.1 |
| radare2 | 6.2.3，`linux-x86_64` |
| `/bin/bash` | ELF 64-bit x86-64 |
| pwntools | Python import 成功 |
| flatter / stegseek / CADO-NFS | 可执行；flatter 的空 stdin 帮助探针会打印 `Problem with input stream.`，但进程链继续且安装可用 |

### 11.3 `DockerSandbox` 真实生命周期验证

源码复核确认镜像没有固定在 `sandbox.py`：`backend/sandbox.py:82` 的 `image` 是构造参数；`backend/cli.py:73` 提供 `--image`；`backend/config.py:41` 提供 `sandbox_image`；三类 solver 都把配置传给 `DockerSandbox`。因此 M0.5 **无需修改生产配置或 provider/policy/platform/frontend**。

新增 `tests/test_sandbox_docker_integration.py`，默认跳过以避免普通单元测试意外依赖 Docker；仅在 `RUN_DOCKER_INTEGRATION=1` 时启动真实容器。它实测并断言：

1. 项目 `DockerSandbox.start()` 能用 `ctf-sandbox:amd64` 启动容器；
2. `distfiles` 与 `metadata.yml` 挂载可读，`distfiles` 写入被拒绝；
3. 容器工具执行成功，workspace 文件能从宿主 bind mount 读取；
4. 长命令 `sleep 30` 的异步调用可取消；
5. `stop()` 后 workspace 被删除，带 `ctf-agent` label 的容器列表中不存在该 container ID。

首次测试在 pytest 建立用户 `%TEMP%` 目录时被 Windows ACL 拒绝，尚未进入 DockerSandbox。将 `TEMP`/`TMP` 和 `--basetemp` 指向工作区可写临时目录后，同一测试真实通过：

```powershell
$env:TEMP='D:\xxx\CTF\.tmp'
$env:TMP='D:\xxx\CTF\.tmp'
$env:RUN_DOCKER_INTEGRATION='1'
$env:CTF_SANDBOX_IMAGE='ctf-sandbox:amd64'
.\.venv\Scripts\pytest.exe -q -p no:cacheprovider --basetemp=D:\xxx\CTF\.tmp\pytest-m05-run tests\test_sandbox_docker_integration.py
# 1 passed in 1.03s
```

### 11.4 回归、lint 与平台矩阵

| 验收 | 结果 |
|---|---|
| 真实 DockerSandbox 集成测试 | `1 passed in 1.03s` |
| 全量 pytest | `191 passed, 1 skipped, 1 warning in 3.99s`；skip 即默认关闭的真实 Docker 测试 |
| `ruff check backend tests` | 通过 |
| `ruff check .` | 未通过：仍是 `pull_challenges.py` 的 15 个既有、可自动修复问题；M0.5 未越界修 lint |

| 目标平台 | 状态 | 结论 |
|---|---|---|
| Windows x64 + Docker Desktop Linux/amd64 | **通过** | 原始 Dockerfile 完整构建、工具 smoke、项目 DockerSandbox 生命周期均已实测 |
| Windows x64 + QEMU Linux/arm64 | **失败** | 先前构建在第 5/16 层 `ldconfig` 收到 SIGSEGV/exit 139；这是模拟路径失败，不能外推 amd64 主线失败 |
| Apple Silicon Mac + Linux/arm64 | **待补验** | 必须在目标 Mac 原生构建并重跑同一 integration test，不能用本轮 amd64 结果代替 |

### 11.5 已知风险与下一步

- Dockerfile 从多个上游仓库浅克隆默认分支，并从包索引获取未锁定的最新版本；本次可复现的是记录日期的构建结果，不是长期供应链可复现性保证。
- 镜像约 2.34 GB，首次构建会下载/安装大量依赖；比赛前应预构建并保留已验证 digest，避免临场网络波动。
- `DockerSandbox` 当前申请 `/dev/loop-control` 等 Linux 设备；本机 Docker Desktop 已通过，但目标 Mac Docker VM 仍需真实验证。
- 取消测试确认调用方 task 得到 `CancelledError` 且最终清理成功；本轮未额外证明容器内任意子孙进程在取消瞬间都已终止，后续可增加 PID/exec 生命周期观测。
- pytest 的用户临时目录存在本机 ACL 问题；CI/开发命令应使用可写的 `--basetemp`，这不是容器功能失败。

M0.5 验收完成。下一可执行提交仍按路线图为 `feat(providers): add redacted provider registry and doctor diagnostics`；本轮没有开始 M1，也没有读取 Key、调用付费 API、自动 fallback 或提交 flag。
