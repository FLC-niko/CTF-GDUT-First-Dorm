# CTF 比赛实战运行与应急处置指南

> 本指南基于已验证的 M0 至 M7 体系，为正式 CTF 比赛（如羊城杯等）提供标准化操作流程。

---

## 一、赛前检查清单（5 分钟自检）

在比赛开始前 15 分钟，执行以下检查：

1. **宿主与依赖环境检查**：
   ```bash
   uv run ctf-doctor
   ```
   确认 Python 版本 >= 3.14，本地 Docker 守护进程正常。

2. **验证跨平台 Worker 连通性**：
   - 检查本地 ARM64 镜像：
     ```bash
     docker image inspect ctf-sandbox:arm64 --format "{{.Os}}/{{.Architecture}}"
     # 应输出: linux/arm64
     ```
   - 检查 VM 103（`10.21.76.27`）原生 AMD64 节点：
     ```bash
     ssh -o BatchMode=yes topview@10.21.76.27 "docker image inspect ctf-sandbox:amd64 --format '{{.Os}}/{{.Architecture}}'"
     # 应输出: linux/amd64
     ```

3. **检查模型配置与环境变量**：
   检查 `.env`，确保已填入 CPA 和 OpenCode Go 的必要参数。

---

## 二、实战运行模式

### 1. 手动导题单题模式（推荐优先尝试）
从比赛平台下载赛题附件与描述后，导入到标准题目格式：
```bash
uv run ctf-import --name "pwn_login" --category "pwn" --file ~/Downloads/pwn_login.zip
```
针对单题启动求解（默认 `--no-submit` 保护）：
```bash
uv run ctf-solve --challenge challenges/pwn_login --models "codex/gpt-5.4-mini" "codex/gpt-5.4" "go-messages/deepseek-r1"
```

### 2. 多题队列与整场比赛模式
通过协调器运行全场题目轮询与分级动态调度（Fast $\to$ Expert $\to$ Racing）：
```bash
uv run ctf-solve --coordinator none --max-challenges 3 --max-containers 4
```

---

## 三、Flag 处理与确认规范

1. **候选 Flag 隔离**：
   - 模型在工具或推理中产生的 Flag 标记为 `flag_candidate`；
   - 状态保存在 `competition_state.json` 中，默认**不会自动向平台提交**。
2. **人工审核提交**：
   - 操作员在日志或控制台中审查候选 Flag；
   - 确认无误后在竞赛答题界面手工提交，避免由于模型幻觉 Flag 导致平台罚时。
3. **平台确认状态联动**：
   - 一旦平台判定正确，系统将状态流转为 `CONFIRMED` 并自动释放对应赛题的环境容器。

---

## 四、故障应急处置策略

| 故障现象 | 应急处理动作 |
|---------|-------------|
| **模型遇到 429 速率限制** | 系统自动进入冷却期并挂起（`PAUSED`），调度器会在冷却结束后自动唤醒，无需人工干预。 |
| **VM 103 远程 Worker 临时断网** | 系统会将任务退回到待调度队列；可临时指定本地 Docker 模拟运行，或重启网络后继续。 |
| **进程意外终止 / 机器断电** | 直接重新执行启动命令；`StatePersistence` 会自动从 `competition_state.json` 恢复所有题目进度，**不会重复解题或覆盖附件**。 |
| **容器内存暴涨或僵尸进程** | 执行 `docker rm -f $(docker ps -aq --filter label=ctf-agent=true)` 即可彻底清理全部沙箱容器。 |
