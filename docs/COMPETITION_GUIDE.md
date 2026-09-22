# CTF 运行手册（草案）

> 本文档是跨平台操作模板，不是 M7 冻结配置。只有在目标设备上完成真实 Provider、
> Docker、历史题 Benchmark 和长跑验收后，才能把对应组合标记为比赛可用。

## 运行前安全线

- 默认使用 `--no-submit`；未确认赛事规则前不开启 `--submit`。
- 不向仓库提交 `.env`、Cookie、API Key、SSH 密码、私网地址或真实 Flag。
- 模型 ID 来自真实 `/models` 或官方说明；Fast/Expert/Racing 角色来自 Benchmark，
  不根据模型名称猜测。
- macOS/ARM64 本地容器适合控制面和通用题；x86-64 Pwn/Reverse 优先路由到
  原生 Linux/amd64 worker。模拟 amd64 不等于原生 amd64。

## 赛前检查

```bash
uv sync
uv run ctf-doctor
uv run ctf-solve --help
```

若使用本地 Docker，用实际配置的镜像名检查 OS/架构：

```bash
docker info --format '{{.OSType}}/{{.Architecture}}'
docker image inspect <sandbox-image> --format '{{.Os}}/{{.Architecture}}'
```

若使用远程 worker，在本地私有配置中使用 SSH alias 和密钥。先以 `BatchMode=yes`
检查免交互登录，不把密码或具体节点写入文档。远程 Docker 会先同步附件，
不会尝试直接挂载控制端的本地路径。

## 最小可用流程

1. 从经授权的赛事平台下载题面与附件，通过 `ctf-import` 导入本地题目目录。
2. 选择已通过真实 smoke 的模型 ID，显式设置角色，并保持 `--no-submit`。
3. 先运行单题，审查候选 Flag 和工具轨迹；再扩展到多题协调。
4. 平台确认与模型候选状态分开；手工提交后再记录确认结果。

单题离线运行示例：

```bash
uv run ctf-solve \
  --challenge challenges/example \
  --coordinator none \
  --models provider/EXACT_MODEL_ID \
  --no-submit
```

## 恢复与降级

- CLI 默认把状态写到题目根目录旁的 `.ctf-agent-state.json`；也可通过
  `COMPETITION_STATE_FILE` 显式指定。
- 进程中止后，`solving` 任务重启时会回到 `triaged`，但仍需人工检查现场与资源。
- 远程 worker 不可用时，只有在本地架构实际兼容题目时才降级到本地 Docker。
- Provider 不可用时，回退到已验证的单模型或人工流程；付费 API fallback 仍为显式开关。
- 只清理本项目带标签的容器，先列表确认，不运行针对宿主全部容器的删除命令。

## M7 正式冻结前必须完成

- 真实 CPA 与 OpenCode Go 工具调用闭环。
- 代表性历史题的可重复 Benchmark，保留原始日志和完整来源。
- 在实际 Windows/macOS/Linux 组合上的资源压测。
- 至少四小时的实时长跑，注入 429、断网、Docker 退出、额度耗尽、任务卡死和取消。
- 冻结具体模型、worker、并发和预算之前，重新运行全量测试与所有 opt-in 集成验收。
