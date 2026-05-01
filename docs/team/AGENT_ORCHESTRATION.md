# AGENT ORCHESTRATION — 多 Agent 协同工程落地方案

> AGENT_PROTOCOL.md 定义"agent 之间怎么对话"（schema + 不变量）。
> 这个文件回答"工程上怎么真的让它们一起工作"——orchestrator 设计、触发机制、
> 并发控制、成本追踪、失败兜底、v0 → v1 → v2 落地路径。
>
> Last updated: 2026-05-01 night

---

## 0. 现状评估

**已经能跑的（v0 — 单链同步）：**
- Code Review Handshake：Claude 写 `code-review-request.txt` + `READY` → 第二个终端跑 Claude/Codex CLI 读取 → 写 `code-review.txt` → 第一个 Claude 读取。
- 跑通过 12+ KR，2 天工作量。
- **缺陷**：单链；Junyan 必须手动开第二个终端；只覆盖"代码 review"一个场景。

**今天证明的并发风险：**
- 我和 cowork Claude 同时改 `docs/team/TEAM.md`，git index.lock 冲突
- 文件创建竞态：cowork 创建空 `DATA_SOURCES_CHECKLIST.md` 时我也想写
- **结论：必须有锁机制**，否则多 agent 协同 = 互相破坏

---

## 1. 决策树 — 谁是 Orchestrator？

三个选项，**最终方案是 B + C 混合**（手动 + 自动）。

### Option A — Junyan 自己路由（不推荐）
- Junyan 脑子里维护"代码 → Codex / 分析 → Claude / PDF → Gemini"的映射
- 优点：简单
- 缺点：Junyan 变成瓶颈；需要他懂每个 agent 强项

### Option B — Claude（主）做 Orchestrator（推荐用于复杂任务）
```
Junyan 给高级目标（"接入 Tushare Pro 并整合到 fetch_data.py"）
        ↓
Claude（主 session）拆解：
  • 子任务 1: 设计接入逻辑（Claude 自己做）
  • 子任务 2: 实现 fetch_tushare.py（写 research_task.json → Codex）
  • 子任务 3: 验证回测（写 research_task.json → Codex）
        ↓
Claude 等待 Codex 完成 → 读 codex_output.json → 综合产出
```

### Option C — Pipeline（cron）做 Orchestrator（推荐用于周期任务）
```
.github/workflows/fetch-data.yml （已经跑）：
  Step 2a-2n 各自调用不同脚本（不同 agent 写的）
  各 step 之间通过 public/data/*.json 通信
```

### **采用方案：B + C 混合**
- 复杂/一次性任务 → Junyan 触发 Claude → Claude orchestrates
- 周期性 / 数据更新 → cron 自动跑 + 失败兜底

---

## 2. Agent 分工矩阵（具体到任务类型）

| 任务类型 | 主 agent | 二审 / 备选 | 触发方式 |
|---|---|---|---|
| Thesis 设计、分析框架、KR 提案 | **Claude (Opus)** | 第二个 Claude session | Junyan 手动触发 |
| 生产代码（≥ 20 行 Python/JS） | **Codex** | Claude review | Claude 写 research_task.json |
| 代码 review / 边界 case 防御 | **Codex** | 第二个 Claude | Claude 写 code-review-request.txt |
| Frontend (Dashboard.jsx) | **Claude (Opus)** | Codex 静态检查 | Junyan 手动触发 |
| 长文档/PDF 处理（年报/季报） | **Gemini** | Claude 抽取关键 quote | Cron + 文件 watcher |
| 实时社交叙事（雪球/微博/X） | **Grok** | Claude 噪音过滤 | Cron 高频轮询 |
| Security audit | Claude (ar-security-auditor skill) | Codex 二审 | 手动触发 |
| Release engineering | Claude (ar-release-engineer skill) | — | 手动触发 |
| 周期数据拉取（fetch_data.py） | **Cron + 现有脚本** | continue-on-error 兜底 | GitHub Actions |
| 学长 Franky 反馈处理 | **Claude (主)** | — | Claude 每次 session 强制读 REVIEW_REQUEST.md |

---

## 3. JSON 通信协议补全（细节，AGENT_PROTOCOL.md 没覆盖的）

### 3.1 文件状态生命周期

每个 `research_task.json` 有 5 个状态：

```
[Claude 写] → pending/      （Codex 未读）
              ↓
              in_progress/  （Codex 锁定中，加 .lock 同名文件）
              ↓
              done/         （Codex 写了 codex_output.json）
                            （Claude 读取后归档到 done/<date>/）
              ↓ 可能失败
              failed/       （Codex BLOCKED 或超时）
              ↓ Claude 重试
              retry/        （重新进 pending/, retry_count++）
```

### 3.2 文件路径约定

```
ar-platform/.agent_tasks/
  ├── pending/
  │   └── <task_id>.json
  ├── in_progress/
  │   ├── <task_id>.json
  │   └── <task_id>.lock     ← 包含 holder agent + acquired_at + pid
  ├── done/
  │   └── YYYY-MM-DD/
  │       ├── <task_id>.research_task.json
  │       └── <task_id>.codex_output.json
  └── failed/
      └── <task_id>.json     （含 failure_reason）
```

`.agent_tasks/` 在 `.gitignore`（per-agent state，不进 git）。

### 3.3 Lock 文件（解决今天的冲突问题）

**场景：** Claude 和 Codex 都想读取 pending/ 的同一个 task

**解决：** Codex 拿 task 时**先**写 `.lock` 文件：
```json
{
  "task_id": "20260501-2030-tushare-fetcher",
  "holder": "codex",
  "acquired_at": "2026-05-01T20:30:15Z",
  "pid": 12345,
  "expires_at": "2026-05-01T21:00:15Z"
}
```

**规则：**
- `.lock` 存在且未过期 → 其他 agent skip 这个 task
- `.lock` 过期 → 视为孤儿任务，回 pending/
- Codex 完成时 → 删除 `.lock` + 写 codex_output.json

### 3.4 Git index.lock 防护（吃过的亏）

**场景：** 多 agent 同时跑 git 命令 → `.git/index.lock` 冲突

**解决：** 写一个 `bin/git-safe.sh` 包装：
```bash
#!/bin/bash
# 等待 git index 解锁后再执行 git 命令
LOCK="$(git rev-parse --git-dir)/index.lock"
TIMEOUT=30
ELAPSED=0
while [ -f "$LOCK" ] && [ $ELAPSED -lt $TIMEOUT ]; do
  sleep 1
  ELAPSED=$((ELAPSED + 1))
done
if [ -f "$LOCK" ]; then
  # Stale lock — check if holder pid alive
  echo "ERROR: stale git lock detected, manual cleanup needed"
  exit 1
fi
git "$@"
```

每个 agent 跑 git 时通过 `bin/git-safe.sh add ...` 而不是直接 `git add`。

---

## 4. 触发机制（v0/v1/v2 三阶段）

### v0 — 手动（已有）
- Junyan 开两个终端
- 终端 1：Claude Code（主分析）
- 终端 2：Codex CLI（review/codegen）
- Claude 写 task 文件 → Junyan 手动到终端 2 跑
- **缺点**：Junyan 变体力工

### v1 — File Watcher（推荐先做这个）

```bash
# bin/agent-watch.sh — 在 Codex 终端启动
#!/bin/bash
TASK_DIR=".agent_tasks/pending"
fswatch -0 "$TASK_DIR" | while read -d "" event; do
  task_file=$(ls -1t "$TASK_DIR"/*.json 2>/dev/null | head -1)
  [ -z "$task_file" ] && continue

  task_id=$(basename "$task_file" .json)
  # 检查 lock
  if [ -f ".agent_tasks/in_progress/$task_id.lock" ]; then
    continue
  fi

  # 拿任务
  mv "$task_file" ".agent_tasks/in_progress/"
  echo "{\"holder\":\"codex\",\"acquired_at\":\"$(date -u +%FT%TZ)\",\"pid\":$$}" \
    > ".agent_tasks/in_progress/$task_id.lock"

  # 触发 Codex 处理（命令依赖具体的 Codex CLI）
  codex --task ".agent_tasks/in_progress/$task_id.json" \
        --output ".agent_tasks/done/$(date +%F)/$task_id.codex_output.json"

  # 清理 lock
  rm ".agent_tasks/in_progress/$task_id.lock"
  mv ".agent_tasks/in_progress/$task_id.json" \
     ".agent_tasks/done/$(date +%F)/$task_id.research_task.json"
done
```

**Junyan 用法**：
- 早上开 Codex 终端，跑 `bin/agent-watch.sh`
- 之后 Claude 写 task 自动被处理
- 一直挂着直到关电脑

需要装：`brew install fswatch`（macOS）

### v2 — Orchestrator daemon（成熟版，未来）

- 一个 Python orchestrator 进程，管多个 agent
- 路由表 + 成本追踪 + 失败重试 + dashboard
- 估计 1-2 周开发，目前不急

---

## 5. 成本追踪（必须有，否则会爆预算）

### 5.1 每次 LLM 调用记录到 `.agent_tasks/cost_log.jsonl`

```json
{"timestamp":"2026-05-01T20:30:15Z","agent":"codex","task_id":"...","model":"codex-cli","tokens_in":4521,"tokens_out":1832,"cost_usd":0.0521}
{"timestamp":"...","agent":"claude","model":"claude-opus-4-7","tokens_in":12450,"tokens_out":3201,"cost_usd":0.241}
```

### 5.2 月度预算 + 警报

```
Claude Code (Opus) 默认预算：$300/月
Codex CLI 默认预算：$100/月
Gemini 默认预算：$50/月
Grok 默认预算：$50/月
```

每次 task 完成 → 累计本月成本 → 超过预算 80% 时 → STATUS.md 加红色警告 + Telegram 推送

### 5.3 实现

写 `bin/cost-track.py`：
```python
# 输入：cost_log.jsonl
# 输出：累计成本 + 月度对比 + 预算剩余
```

---

## 6. 失败兜底（必须有）

### 6.1 Agent 不可用

| Agent | 主 | 备选 1 | 备选 2 |
|---|---|---|---|
| Claude (主分析) | Claude Opus | 第二 Claude session | 暂停等 reviewer |
| Codex (代码) | Codex CLI | 2nd Claude in code-review mode | Claude 自己生成 + 标 self-review |
| Gemini (PDF) | Gemini API | Claude long-context | Skip + 标 PDF_DEFERRED |
| Grok (实时社交) | Grok API | Claude with manual feed | Skip + 用昨天数据 |

### 6.2 Task 超时

- Codex 任务超过 30 分钟 → 视为 failed
- Lock 过期 → 任务回到 pending/，retry_count++
- retry_count >= 3 → 移到 failed/，notify Junyan

### 6.3 JSON Schema 校验失败

- Codex 写的 codex_output.json 字段缺失 → Claude 不应 trust，标 SCHEMA_INVALID
- 自动写到 `.agent_tasks/failed/`

---

## 7. v0 → v1 → v2 落地路径

### v0（已有，今天能用）

✅ Code review handshake
✅ AGENT_PROTOCOL.md 协议规范

**还能加的（不用 v1 工具就能做）：**
- [ ] 创建 `.agent_tasks/{pending,in_progress,done,failed}/` 目录结构
- [ ] 写 `bin/git-safe.sh` 防 git lock 冲突
- [ ] 加 `.agent_tasks/` 到 `.gitignore`

### v1（推荐 1 周内做）

- [ ] 装 fswatch (`brew install fswatch`)
- [ ] 写 `bin/agent-watch.sh` Codex 端 watcher
- [ ] 写 `bin/cost-track.py` 成本追踪
- [ ] 测试：Claude 写 task → 自动被 Codex 处理 → Claude 读取 output

**验收标准**：Junyan 触发 Claude 一次，让它写一个简单 codegen task，整个流程自动跑完，无人工干预。

### v2（未来 1-2 个月）

- [ ] Orchestrator daemon（Python）
- [ ] Cost dashboard（Telegram bot）
- [ ] Gemini 接入（PDF 处理）
- [ ] Grok 接入（实时社交）
- [ ] 失败自动重试

---

## 8. 现在就能做的最小可行（今晚 / 明早）

按 ROI 排序：

### Step 1（5 min）— 防 git 冲突再现
```bash
cat > ~/Desktop/Stock/ar-platform/bin/git-safe.sh <<'EOF'
#!/bin/bash
LOCK="$(git rev-parse --git-dir 2>/dev/null)/index.lock"
TIMEOUT=30
ELAPSED=0
while [ -f "$LOCK" ] && [ $ELAPSED -lt $TIMEOUT ]; do
  sleep 1; ELAPSED=$((ELAPSED + 1))
done
[ -f "$LOCK" ] && { echo "ERROR: stale lock — manual cleanup"; exit 1; }
git "$@"
EOF
chmod +x ~/Desktop/Stock/ar-platform/bin/git-safe.sh
```
之后所有 agent 用 `bin/git-safe.sh add ...` 而不是 `git add ...`

### Step 2（10 min）— 任务目录结构
```bash
cd ~/Desktop/Stock/ar-platform
mkdir -p .agent_tasks/{pending,in_progress,done,failed}
echo ".agent_tasks/" >> .gitignore
```

### Step 3（30 min）— file watcher 雏形
- 装 `brew install fswatch`
- 写 `bin/agent-watch.sh`（基于 §4.v1 模板）
- 验收：跑一个简单 task 走通流程

### Step 4（之后）— 集成到 auto-work-mode skill
- skill 里 KR 实施步骤改为：Claude 写 task → 等 Codex output → 综合
- 不再让 Claude 自己直接写代码

---

## 9. 核心不变量（重申 + 补全）

继承 AGENT_PROTOCOL.md 的 4 条不变量，加 3 条工程性的：

5. **每个 agent 操作前先获取 lock**（task lock + git lock）
6. **每次 LLM 调用必须记录到 cost_log**（无例外）
7. **Failure 必须显式记录原因**（写 failed/ + 非空 failure_reason）

---

## 10. 决策点 — Junyan 拍板结果（2026-05-01 night）

| # | 决策 | 结果 | 物证 |
|---|---|---|---|
| 1 | 第一步落地从哪里开始？ | ✅ **B = v0+** | commit `ad80b07` |
| 2 | Codex CLI 用哪个? | ✅ **OpenAI Codex CLI**（Junyan 开通订阅） | 见 §11 接入步骤 |
| 3 | 成本预算月度上限? | 🟡 默认 $500 起步（Claude $300 + Codex $100 + 预留 $100） | 待 1 个月后审 |
| 4 | Gemini / Grok 现在接还是等 v2? | ✅ **等** — Phase 2/3 再说 | — |
| 5 | `.agent_tasks/` 进 git 吗? | ✅ **不进**（同 .night-shift/） | `.gitignore` 已加 |

---

## 11. Phase 1 终端配置（最终方案：双 Claude + Codex）

**Junyan 需要开三个终端：**

| # | 终端 | Agent | 角色 | 订阅 |
|---|---|---|---|---|
| 1 | Terminal 1 | Claude Code (Opus) | 主 orchestrator + thesis 设计 + KR 实施 | Claude Pro/Max（已有 ✓）|
| 2 | Terminal 2 | Claude Code (Opus) | reviewer + 二审 + 备用并行任务 | 同账户 |
| 3 | Terminal 3 | OpenAI Codex CLI | 主 codegen（≥ 20 行 Python/JS）+ 测试生成 | OpenAI API + ChatGPT Plus（Junyan 开通中）|

**v0+ 阶段（现在）：** 三终端**手动协作**——主 Claude 写 task 到 `.agent_tasks/pending/`，Junyan 切到对应终端跑命令。

**v1 阶段（一周内）：** 加 fswatch + `bin/agent-watch.sh` 让 Codex 终端自动监听 pending/，task 自动被处理。

### Codex CLI 接入命令（Junyan 明天执行）

```bash
# 1. 安装 OpenAI Codex CLI
npm install -g @openai/codex

# 2. 拿 OpenAI API key
#    浏览器 → https://platform.openai.com/api-keys → Create new secret key
#    放 ~/.zshrc：
export OPENAI_API_KEY='sk-...'
source ~/.zshrc

# 3. 第一次启动测试
cd ~/Desktop/Stock/ar-platform
codex --help

# 4. 实际开始工作时（Phase 1 v0+ 模式 — 手动）
#    主 Claude 写完 task 到 .agent_tasks/pending/<task_id>.json 后会告诉 Junyan：
#    "请到 Codex 终端跑 codex < .agent_tasks/pending/<task_id>.json"
#    Codex 处理完写到 .agent_tasks/done/YYYY-MM-DD/<task_id>.codex_output.json
#    主 Claude 监听到后继续。
```

### Phase 1 任务路由（明确分工）

| 任务类型 | 哪个终端 | 触发方式 |
|---|---|---|
| Thesis 设计、KR 提案、文档 | T1 主 Claude | Junyan 直接对话 |
| Frontend (Dashboard.jsx) 改动 | T1 主 Claude | Junyan 直接对话 |
| 写新 Python script (≥ 20 行) | T3 Codex | T1 主 Claude 写 task → Junyan 切到 T3 跑 |
| 跑代码 review | T3 Codex（主） / T2 Claude（备）| T1 写 review-request → Junyan 切 T3 |
| Adversarial 二审、辩论 | T2 Claude reviewer | T1 写 task → Junyan 切 T2 |
| Franky REVIEW_REQUEST.md 处理 | T1 主 Claude | 强制每 session 读 |

---

## 附：与 cowork 协调的失败教训（今天）

**事件**：cowork Claude 和我（这个 session）同时修改 docs/，git index.lock 冲突 + 文件创建竞态。

**根因**：
1. 没有 task lock 机制——两个 agent 都觉得"我可以写 TEAM.md"
2. 没有 git wrapper——两个 git 进程同时进来
3. 没有显式的 ownership 协议——谁负责哪部分文件不清楚

**这个文档是教训的产物**：§3.3 task lock + §3.4 git wrapper + §2 分工矩阵
都直接来自这次教训。
