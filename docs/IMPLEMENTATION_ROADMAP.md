# HuntingBlade 实施路线图

> 2026-09-20 制定。以当前本地 M0 审计及锁定的上游 SHA
> `f4cae4d0ed897ccf3645742dc719b3755ba1ae83` 为基线；如源代码与本文件不符，
> 以仓库实际代码为准并记录差异。

## 基线与总原则

- 已完成 M0：Windows x64、`feat/cpa-go-routing`、uv 0.12.17、Python 3.14.7；测试 191 passed, 1 warning；backend tests lint 通过。`pull_challenges.py` 的 15 个原有 lint 问题不属于本阶段回归。
- Windows Docker Desktop 在 Linux 容器模式使用 Linux 虚拟化后端；Windows x64 上优先构建 `linux/amd64` 沙箱。先前主动构建 `linux/arm64` 触发的是跨架构 QEMU 路径，不能据此断言项目在 x86 Linux 中无法运行。
- 预定 macOS Apple Silicon 运行控制端：`linux/arm64` 为本地通用题型的原生候选；x86-64 Pwn/动态逆向优先路由到原生 x86-64 Linux worker（可以是 Windows x64 Docker Linux VM，或经过 CPU 架构验证的 Ubuntu x86-64 服务器）。Mac 上运行 `linux/amd64` 属于模拟/翻译回退，不能作为唯一比赛方案。
- 不要将 macOS、Windows x64、Ubuntu x86-64 混为一谈：操作系统决定宿主配置和目录处理，CPU 架构 + Linux 运行时决定容器内二进制兼容性。现有服务器若是 ARM，也不能称为原生 x86-64 worker。
- 不购买 Claude；不依赖其 SDK 成功运行。CPA 连接 Codex 和 Antigravity；OpenCode Go 独立接入且须核对其允许的接口/协议、额度和认证方式。任何模型名与价格均从实测和官方可用目录读取，不能把过往对话中的版本名当成已验证 model ID。
- 比赛平台自动抓题/自动提交是否允许，以正式规程为准；默认手工导题、`--no-submit`，仅对授权赛题环境运行。

## M0.5：Linux/amd64 Docker 沙箱基线

目标：先解除阻塞；用 Windows x64 上的 Linux/amd64 Docker 完成一份可执行沙箱，不把 arm64 QEMU 的 `ldconfig` SIGSEGV 当作构建失败的通用结论。

- 检查 `docker info` 的 OS/Architecture、Docker Desktop Linux Containers 模式、Buildx builder；记录 Windows / Linux VM / CPU 架构。
- 运行 `docker run --rm --platform linux/amd64 ubuntu:22.04 uname -m`，要求为 `x86_64`；再运行 linux/arm64 仅作为负向/兼容性记录，不阻塞 amd64 主路径。
- 在仓库根目录执行 `docker build --platform linux/amd64 -f sandbox/Dockerfile.sandbox -t ctf-sandbox:amd64 .`；保留构建日志、基础镜像摘要、必要的工具版本；不要自动修改未锁定的上游依赖。
- 最小镜像自检：`uname -m`、Python、Sage、GDB、radare2、file、pwntools 等；至少执行一个可复现的本地样例和一次 Sandbox start / exec / stop / 文件挂载测试。
- 通过真实 `DockerSandbox`（不是只有 `docker run`）检验工作目录、附件只读挂载、工具退出码及容器清理。当前代码默认 16g/容器、每容器 2 CPU、较宽松的特权和网络设定：记录整改事项。
- 在 `docs/ARCHITECTURE_AUDIT.md` 追加平台矩阵和 M0.5 证据；保留 arm64 构建失败记录，不掩盖问题。

验收：完整 amd64 镜像生成；通过 `DockerSandbox` 真正执行并回收；测试基线不退化。

失败处理：按失败层定位依赖/网络/镜像构建问题，不立即换框架、也不因 QEMU arm64 失败改动全部 Dockerfile。

候选提交：`test(sandbox): verify native amd64 Docker baseline`（优先文档/测试；必要时仅对镜像名做最小配置化）。

## M1：Provider registry 与 doctor

范围：沿用已审查的 `backend/models.py` 及现有 solver 运行时，只新增 provider 的结构化描述与纯离线检测；不重写 swarm、不引入新前端。

- 定义 `ProviderSpec` / `ModelSpec`、`Protocol = responses | chat_completions | anthropic_messages | native_cli`、`ModelRole` 和 capabilities；模型 ID 不可由展示名推导。
- 将 CPA 与 Go 的 base URL、模型、认证环境变量和协议分开；现有 `azure/*` 为 Responses 的事实保持兼容；其他协议需由实测/官方接口证明后接入。
- 新增 doctor：配置可用性、协议路由、Docker/image/platform、挂载目录、风险提示。默认完全离线、不发请求、不回显 API key、Cookie、Flag、题目附件内容。
- Fake transport tests 覆盖协议分流、Key 脱敏、未配置/不支持协议报错、无意自动切换至付费 provider。
- `uv run pytest` 和既有 lint 结果与 M0 基线对比，不为本阶段随手修改 `pull_challenges.py`。

验收：无密钥也能运行 doctor 与测试；所有新配置错误可诊断；旧 CLI 参数冒烟仍通过。

候选提交：`feat(providers): add redacted provider registry and doctor diagnostics`。

## M2：CPA 真实调用

- 从 CPA 实际接口获取可用模型 ID；先测认证/简单响应，再测工具调用/多轮上下文/取消/超时；不能把 `/models` 成功当成 solver 成功。
- 首先复用经验证的 Responses 路径接入一个 GPT 模型；随后验证 Gemini 在该路径是否真的兼容，不能假设与 Codex 相同。
- 从手动导题开始，运行一题一模型、无顶层总控、`--no-submit`；记录真实工具执行、候选 Flag、用时、报错、摘要成本。
- 禁止默认使用 Claude 列表；遇配额错误停止/标记不可用，不自动转付费备援。
- 添加 fake 接口回归与可选真实接口 smoke（CI 默认为假请求；真实测试显式 opt-in）。

验收：CPA 模型从题面到 Docker 工具，再到本地候选 Flag 的可复现闭环；不泄漏密钥或 Flag。

## M3：OpenCode Go 真实调用

- 查阅开发当日官方 Go 可用模型、允许的第三方接入方式、协议、缓存/推理计费、窗口额度和会话 header 要求；保留来源和查阅日期。
- 按模型实测协议分别适配 Chat Completions / Anthropic Messages / Responses；禁止把全部 Go 视为同一种 OpenAI API。
- 首批只接入 2 个不同模型家族的快速模型，以及 1 个强模型作为候选；不要为全量模型增加维护成本。
- 测试工具调用、脚本执行、长上下文、流式/超时/限流/余额不足、续会话；日志记录 usage 与服务端能取得的额度，不伪造额度。
- 计费设软预算/硬预算和每模型并发门槛，且输出记录供应商、模型版本、速率限制证据；若不能读到服务端余额则状态为 unknown 而不是“有额度”。

验收：至少一个 Go 模型完成与 M2 同一题的真实工具闭环；无 Claude，Go/CPA 均可独立工作；预算阻断有测试。

## M4：资源、安全与跨平台 worker

- 修正 semaphore：当前只限制启动瞬间，必须实现容器生命周期级并发令牌并在异常/取消后释放。
- 资源限制按环境配置：Windows/Ubuntu x86 worker 先从 2–3 个容器压测；Mac M1 Pro 16GB 先从 1–2 个容器开始；单容器内存由任务/环境决定，不沿用 16g 默认。
- 限制容器权限、挂载、出站目标；确需 ptrace/嵌套容器的题型按能力启用，避免所有容器默认 `SYS_ADMIN + seccomp=unconfined`。审查 `/dev/loop-control`、`host.docker.internal` 的必要性。
- 凭证只存在宿主 provider 进程中，不传入解题容器；日志中的 key/cookie/token/flag 做脱敏，原始候选 Flag 如需保留则单独权限管控。
- 采用两个镜像标签：`ctf-sandbox:amd64`（x86 Linux binary）、`ctf-sandbox:arm64`（Mac 本地一般题）；镜像架构要运行时验证，不能只看 tag。arm64 不成功则保留 amd64 worker 回退。
- 远程 worker 使用 SSH 等安全传输，补齐工作目录/附件同步：`backend/sandbox.py` 当前 Binds 为宿主机绝对路径，直接切远程 Docker daemon 会因路径不存在失败。不要裸露 Docker TCP socket。

验收：并发上限是真限制；取消/重启无悬挂容器；x86 二进制可在 amd64 worker 原生运行；ARM 原生仅在 Mac 实测成功后宣布支持。

## M5：调度与恢复

- 现有 poller/coordinator/policy/working memory 能力优先复用；新增跨题队列与执行状态，不另造整套 Agent 运行时。
- 题目状态 `pending/triaged/solving/paused/solved/confirmed/failed`；分清候选 Flag 和平台已确认提交。
- 快速模型做初步分类，给依据与不确定性；不要把模型置信度当校准后的成功概率。
- 规则优先：Fast 跑初筛 → 没有新证据再升级 Expert → 适合时 Racing；跨题并发上限、模型额度与比赛剩余时间全局控制；共享已验证证据与待证假设分开。
- 先做单题/多题批量本地导入，羊城杯接口仅在确认规则及实际兼容后开发，默认人工确认提交。
- 进度日志及运行状态持久化，支持中断恢复和取消 idempotency。

验收：在本地 5 题测试集中自动派发不重复抢同一可变工作区；模型异常不会阻塞全部任务；恢复后不重复提交/覆盖附件。

## M6：基准评测

- 以公开可复现赛题组成 Web/Crypto/Misc/Pwn/Reverse 基准；每题固定时间、工具、网络条件、初始提示，未解题不能提前喂 writeup。
- 先测快速模型，再强模型，然后双模型 Racing：分别记录有效 Flag、Time-to-Flag、工具正确率、消耗、互补解题覆盖率。
- 外部模型榜单只用于初选，不能直接等同于 CTF 专项成功率；不同时间、推理档位和服务节点不能混为同一评测。
- 以模型每个角色的有效积分/墙钟时间、边际额外解题覆盖率、额度风险决定主力与备援；动态积分/一血若未确认不要写死。

验收：模型配置与超时策略由真实报告支撑；保留一套最简稳定备援配置。

## M7：长跑、故障演练与冻结

- 检查比赛规程中 AI/自动提交/爬取/访问范围要求；未确认的能力保持禁用。
- 单题→5 题→全场模拟，做四小时长跑；注入 429、断网、Docker 退出、CPA 无额度、Agent 卡死、取消等故障。
- 限流/额度故障有熔断；管理员可暂停、强制路由、手工提交；候选 Flag 不等于平台确认；重要证据及 workspaces 持久化。
- Mac M1 Pro / Windows x64 / Ubuntu x86 worker 中，最终比赛将使用的组合必须实际完成完整 smoke 和负载测试；未测试不可宣称支持。
- 冻结依赖版本/镜像 digest/模型 ID、备份配置、检查 API 凭证期限，最迟赛前一天只修阻塞 bug。

验收：四小时模拟通过、恢复演练通过、明确 fallback：单模型 + 手动导题 + `--no-submit` + 本地已验证沙箱。

## 顺序与阶段记录

M0（已完成） → M0.5 amd64 Docker → M1 registry/doctor → M2 CPA 真调用 → M3 Go 真调用 → M4 资源安全跨平台 → M5 调度 → M6 基准评测 → M7 长跑/冻结。

可交错：M4 的隔离审查与 M1 并行；Mac 原生构建在 Mac 可用时尽早开始，不应阻塞 Windows amd64 主线；比赛平台适配最后做。

任何阶段都需更新 `docs/CHANGELOG_DEV.md`（日期/commit/测试/未解决问题），不能仅凭代码被合并就宣称完成。

## 基线命令

```bash
docker info --format '{{.OSType}}/{{.Architecture}}'
docker run --rm --platform linux/amd64 ubuntu:22.04 uname -m
docker build --platform linux/amd64 -f sandbox/Dockerfile.sandbox -t ctf-sandbox:amd64 .
docker image inspect ctf-sandbox:amd64 --format '{{.Os}}/{{.Architecture}}'
docker run --rm --platform linux/amd64 ctf-sandbox:amd64 bash -lc 'uname -m; python3 --version; sage -c "print(1+1)"; gdb --version | head -n 1; r2 -v'
uv run pytest
```

`ctf-sandbox:amd64` 是新增验证标签；如果运行时原项目读取固定镜像名，优先用配置化方式适配；在未查看代码前不要盲目认为改标签即可让 Solver 自动使用它。

## 参考资料

- [HuntingBlade 仓库](https://github.com/D1a0y1bb/HuntingBlade)
- [基线 SHA 的 Dockerfile](https://raw.githubusercontent.com/D1a0y1bb/HuntingBlade/f4cae4d0ed897ccf3645742dc719b3755ba1ae83/sandbox/Dockerfile.sandbox)
- [基线 SHA 的 sandbox.py](https://raw.githubusercontent.com/D1a0y1bb/HuntingBlade/f4cae4d0ed897ccf3645742dc719b3755ba1ae83/backend/sandbox.py)
- [Docker WSL2](https://docs.docker.com/desktop/features/wsl/)
- [Docker 多架构构建](https://docs.docker.com/build/building/multi-platform/)
- [Docker Apple Silicon 已知限制](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/known-issues/)
