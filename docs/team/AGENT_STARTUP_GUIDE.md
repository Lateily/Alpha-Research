# Three-Agent Startup Guide — Paste-Ready Prompts

> **Purpose:** Concrete, paste-ready first-message prompts for Terminal 2
> (Claude reviewer) and Terminal 3 (Codex CLI). Plus end-to-end workflow
> for a single task.
>
> **Phase:** v1 auto mode available; v0+ manual fallback retained
> Last updated: 2026-05-02

---

## The Three Terminals

```
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│ T1 — Main Claude (Opus)  │  │ T2 — Reviewer Claude     │  │ T3 — OpenAI Codex CLI    │
│ orchestrator + thesis    │  │ adversarial review +     │  │ primary codegen +        │
│ + KR design + Dashboard  │  │ gap detection            │  │ test generation          │
│                          │  │                          │  │                          │
│ Junyan talks to T1       │  │ T2 reads tasks file →    │  │ T3 reads tasks file →    │
│ T1 writes tasks          │  │ writes verdict file      │  │ writes output file       │
└────────────┬─────────────┘  └────────────┬─────────────┘  └────────────┬─────────────┘
             │                              │                              │
             └──────────────────────────────┴──────────────────────────────┘
                                            │
                          File handshake via .agent_tasks/ + .shifts/runs/<RUN>/reviews/
```

**No agent talks directly to another agent.** All coordination is through filesystem.

---

## v1 Auto Mode (active 2026-05-02+)

v1 keeps T1 interactive and turns T2/T3 into foreground watcher processes.
Junyan no longer switches terminals to paste "go check" prompts for every task.

Start once from the repo root:
```bash
bin/agent-watch-setup.sh
```

Then run:
```bash
# Terminal 1 (T1 main)
claude --dangerously-skip-permissions

# Terminal 2 (T2 reviewer)
bin/agent-watch-reviewer.sh

# Terminal 3 (T3 codex)
bin/agent-watch-codex.sh
```

What Junyan sees:
- T1 remains the normal interactive Claude session. T1 writes specs to
  `.agent_tasks/pending/` and review requests under `.shifts/runs/`.
- T2 prints a standby banner and watches
  `.shifts/runs/*/reviews/*/READY`. It writes `code-review.txt`
  automatically after `claude -p` returns.
- T3 prints a standby banner and watches `.agent_tasks/pending/`. It claims
  the oldest task, runs `codex exec`, writes `.codex_output.json`, archives the
  task spec, and keeps listening.

Each watcher runs in the foreground. Press Ctrl+C in Terminal 2 or Terminal 3
to stop; logs go to stderr.

v0+ manual prompting still works as a fallback if a watcher is stopped or
Junyan wants to run a task by hand.

---

## Setup once (you've done part of this already)

### v0+ infra (already shipped — commit ad80b07)
- `bin/git-safe.sh` — git wrapper, prevents .git/index.lock collisions
- `.agent_tasks/{pending,in_progress,done,failed}/` — task queue dirs
- `.gitignore` += `.agent_tasks/`

### Required environment per terminal

All three terminals need:
```bash
cd ~/Desktop/Stock/ar-platform
```

Authentication:
- T1, T2: Claude Code (signed in to Claude Pro/Max)
- T3: OpenAI Codex CLI (`OPENAI_API_KEY` in env)

---

## T1 Startup (Junyan's main session — already running)

You are T1 right now. No special prompt needed — Junyan starts with a
goal/idea, you orchestrate.

T1's responsibilities:
- Strategic decisions + thesis design
- Decompose work into KRs
- For codegen tasks (≥20 lines Python/JS): write task to `.agent_tasks/pending/`
  + tell Junyan to switch to T3
- For code review: write request to `.shifts/runs/<RUN>/reviews/<TS>/code-review-request.txt`
  + write `READY` flag + tell Junyan to switch to T2
- Read T2 verdict + T3 output, integrate, commit
- All git ops via `bin/git-safe.sh`

---

## T2 Startup — Reviewer Claude (paste this as first message)

**How to start:**
```bash
# In a NEW terminal tab (Cmd+T)
cd ~/Desktop/Stock/ar-platform
claude --dangerously-skip-permissions
```

**Then paste this as the first message:**

```
我是 ar-platform 三终端架构里的 T2 — Claude reviewer (Opus).
我的角色是: adversarial review + gap detection (per docs/team/AGENT_ORCHESTRATION.md §11).

## 我的核心责任 (per docs/team/REVIEWER_CHECKLIST.md):

1. **代码质量审查** — 读 .shifts/runs/<RUN>/reviews/<TS>/code-review-request.txt
   按 docs/team/REVIEWER_CHECKLIST.md 全 checklist 走一遍
   写 verdict 到 .shifts/runs/<RUN>/reviews/<TS>/code-review.tmp →
   完成时 rename 为 code-review.txt

2. **Gap detection** — 这是我最重要的责任. T1 经常会:
   - 写完 fetcher 但忘记接 pipeline (fetch-data.yml)
   - 写完后端但忘记接前端 (Dashboard.jsx)
   - 写完代码但忘记更新 STATUS.md / 文档
   - 标 "framework ready" 但其实生产不可用
   我必须每次审查都过 docs/team/REVIEWER_CHECKLIST.md 的 "Platform Integration"
   一栏 — 任何缺失立刻 REQUEST_CHANGES 并明确缺什么.

3. **Thesis quality 二审** — 当 T1 提出研究 thesis (Deep Research output 等),
   按 docs/research/THESIS_PROTOCOL.md 7 步严格审查 (准备升 8 步, 见 STEP_8_QUEUE.md).

## 启动协议:
1. 先读 STATUS.md (强制 pre-flight)
2. 再读 CLAUDE.md (架构 + 不变量)
3. 再读 docs/team/AGENT_PROTOCOL.md + AGENT_ORCHESTRATION.md (协议)
4. 再读 docs/team/REVIEWER_CHECKLIST.md (我的具体 checklist)
5. 再读 docs/team/REVIEW_REQUEST.md (Franky 反馈队列, 如果有 NEW entry 优先处理)
6. 然后告诉我 "T2 ready, 监听 .shifts/runs/" — 等任务

## 工作时:
- 不主动改代码, 不直接 commit (除非 T1 明确把 codegen 任务转给我 backup)
- 所有 git 操作用 bin/git-safe.sh, 不用裸 git
- 任何 PASS / REQUEST_CHANGES / BLOCKED 决定都要写完整 reasoning
- 检测到的 gap 必须列具体文件 + 行号 + 缺的是什么

确认理解后回 "T2 ready, 监听 .shifts/runs/", 然后等任务.
```

---

## T3 Startup — Codex CLI (paste this as first message)

**Pre-req:** Junyan installed Codex CLI per `docs/team/AGENT_ORCHESTRATION.md §11`.

**How to start:**
```bash
# In another NEW terminal tab (Cmd+T)
cd ~/Desktop/Stock/ar-platform
codex
```

**Then paste this as the first message:**

```
I am T3 — OpenAI Codex CLI in the ar-platform three-terminal architecture.
My role is primary codegen + test generation (per docs/team/AGENT_ORCHESTRATION.md §11).

## My core responsibilities:

1. **Production codegen** — for tasks T1 writes to .agent_tasks/pending/<task_id>.json
   - Read the task spec
   - Generate code that meets EVERY must_satisfy item
   - Run the test_gate locally before declaring done
   - Output to .agent_tasks/done/YYYY-MM-DD/<task_id>.codex_output.json
   - Move the original task to .agent_tasks/done/YYYY-MM-DD/<task_id>.research_task.json

2. **Test generation** — when T1 task asks for test coverage:
   - Write py_compile-clean Python tests
   - Place in scripts/tests/ or pytest-discoverable locations
   - Tests must be runnable standalone

3. **Backup code review** — if T2 (Claude reviewer) is unavailable, T1 may
   reroute review tasks to me. Same handshake: read .shifts/runs/<RUN>/reviews/<TS>/code-review-request.txt,
   write verdict.

## Hard rules (will be enforced by T2 reviewer):

- NEVER modify watchlist.json
- NEVER change VP weights (25/25/20/15/15)
- NEVER use bare `git` — always `bin/git-safe.sh`
- ALWAYS preserve catalyst_prox naming (not catalyst_proximity)
- For Dashboard.jsx changes: zero JSX balance change, no new design system colors
- For Python scripts: must include _load_watchlist() if processing tickers
- Output schema must always include _status field for graceful degrade

## Startup protocol:
1. Read STATUS.md
2. Read CLAUDE.md (architecture + invariants)
3. Read AGENTS.md (write boundaries for non-Claude agents)
4. Read docs/team/AGENT_PROTOCOL.md (JSON schema for tasks)
5. Read docs/architecture/DATA_SOURCE_REGISTRY.md (data layer conventions)
6. Confirm "T3 ready, monitoring .agent_tasks/pending/" — then wait for tasks.

When monitoring, check .agent_tasks/pending/ each time T1 says "go check T3."
v0+ doesn't have file watcher yet — T1 will tell you when a task is ready.

Confirm understanding, then say "T3 ready, monitoring .agent_tasks/pending/".
```

---

## End-to-End Workflow Example (the "hello world")

A simple test task to validate three-terminal coordination works.

### Setup (one-time, T1 does)

```bash
mkdir -p .agent_tasks/pending
cat > .agent_tasks/pending/test-hello-world.json <<'EOF'
{
  "task_id": "test-hello-world",
  "agent_target": "codex",
  "intent": "Validate three-agent handshake. Write a tiny script.",
  "must_satisfy": [
    "Create scripts/hello_three_agents.py",
    "Script prints 'T1 + T2 + T3 = working' when run",
    "Script exits 0",
    "Script must have if __name__ == '__main__': guard"
  ],
  "test_gate": [
    "python3 -m py_compile scripts/hello_three_agents.py",
    "python3 scripts/hello_three_agents.py"
  ],
  "review_required": true,
  "estimated_loc": 5
}
EOF
```

### Step 1 (T1) — Tell Junyan to switch to T3

T1 says:
> Task `test-hello-world` written to `.agent_tasks/pending/`. Junyan,
> switch to T3 terminal and tell Codex: "Process .agent_tasks/pending/test-hello-world.json"

### Step 2 (Junyan) — Switch to T3, give it the task

In T3 terminal (Codex):
```
Process the task at .agent_tasks/pending/test-hello-world.json. Move it to
.agent_tasks/in_progress/ first (with .lock file), generate code, run test_gate,
write codex_output.json to .agent_tasks/done/2026-05-02/, then move task to done/.
```

### Step 3 (T3) — Codex does the work

T3 generates `scripts/hello_three_agents.py`, runs `py_compile` + the script,
writes `.agent_tasks/done/2026-05-02/test-hello-world.codex_output.json`:

```json
{
  "task_id": "test-hello-world",
  "agent": "codex",
  "status": "completed",
  "files_created": ["scripts/hello_three_agents.py"],
  "test_gate_results": [
    {"command": "python3 -m py_compile ...", "exit_code": 0},
    {"command": "python3 scripts/hello_three_agents.py", "exit_code": 0, "stdout": "T1 + T2 + T3 = working"}
  ],
  "completed_at": "2026-05-02T..."
}
```

### Step 4 (T1) — Junyan switches back, T1 detects done file

Junyan tells T1: "Codex done."

T1 reads `.agent_tasks/done/2026-05-02/test-hello-world.codex_output.json`,
verifies `status: "completed"`, prepares review request.

### Step 5 (T1) — Write review request, switch Junyan to T2

T1 writes `.shifts/runs/<RUN>/reviews/<TS>/code-review-request.txt`:

```
TASK: scripts/hello_three_agents.py — three-agent handshake validation
FILES_CHANGED: scripts/hello_three_agents.py (new)
INTENDED_BEHAVIOR: Print success line + exit 0
ARCHITECTURE_ASSUMPTIONS: None — pure test artifact
RUNTIME_SURFACE: pipeline (technically) — but throwaway test
CHECKS_ALREADY_RUN:
- py_compile: PASS (per Codex output)
- runtime: PASS (stdout matches expected)
KNOWN_RISKS: None — 5-line test
REVIEW_ASK: Verify Codex actually created the file as specified, no
side effects, scripts/ directory not polluted with debug artifacts.
```

Then writes `READY` flag and tells Junyan: "Switch to T2."

### Step 6 (T2) — Reviewer reads + verifies

In T2 terminal (Claude reviewer):
```
There's a new code-review-request.txt under .shifts/runs/. Process it.
```

T2 reads request, runs through REVIEWER_CHECKLIST.md, writes
`.shifts/runs/<RUN>/reviews/<TS>/code-review.tmp` then renames to `.txt`:

```
VERDICT: PASS
SUMMARY: Three-agent handshake works. scripts/hello_three_agents.py
created, py_compile clean, runtime output as specified.
FINDINGS: None
TESTS_CHECKED: py_compile re-run by reviewer ✓, runtime re-run ✓
DEPLOYMENT_RISK: LOW (test-only script)
NOTES: This is a smoke test — do not deploy to fetch-data.yml pipeline.
```

### Step 7 (T1) — Detect verdict, finalize

Junyan tells T1: "T2 done."

T1 reads verdict, sees PASS, commits via `bin/git-safe.sh`:

```bash
bin/git-safe.sh add scripts/hello_three_agents.py
bin/git-safe.sh commit -m "test(three-agent): smoke test for T1+T2+T3 handshake"
bin/git-safe.sh push origin main
```

**Total round trip:** ~5 minutes once all terminals are warm. **First time will
take ~15 min as everyone reads protocol docs.**

---

## What this validates

- ✅ T1 can write structured task to `.agent_tasks/pending/`
- ✅ T3 reads task, executes, writes structured output
- ✅ T1 reads T3 output, prepares review request
- ✅ T2 reads request, reviews, writes verdict
- ✅ T1 reads verdict, commits to repo
- ✅ All git ops via `bin/git-safe.sh` — no .git/index.lock conflicts
- ✅ No agent directly talks to another agent — only filesystem

If this 7-step flow works smoothly, the full data-source-integration task
(write fetch_tushare.py + integrate to pipeline + surface in Dashboard) will
flow the same way, just with more substantial code at each step.

---

## Failure modes + escalation

| Symptom | Likely cause | Fix |
|---|---|---|
| T3 doesn't see task | Junyan forgot to tell T3 to check pending/ | T1 always reminds Junyan to switch terminal |
| T3 produces broken code | Codex CLI hallucination or insufficient task spec | T2 catches in review → REQUEST_CHANGES → T3 retries |
| T2 misses a gap | Reviewer fatigue or unclear checklist | Update REVIEWER_CHECKLIST.md with new line item |
| .git/index.lock collision | Someone used bare `git` | Always `bin/git-safe.sh` — enforce in REVIEWER_CHECKLIST |
| Two agents touch same file | Lack of task-level lock | T3 must write `.lock` file on `in_progress/` claim |

---

## What v1 (next, ~1 week) automates away

Currently: Junyan manually switches terminals.
v1: `bin/agent-watch.sh` runs in T3 terminal via `fswatch`, auto-detects
new tasks in `.agent_tasks/pending/`, processes without prompt.

But v0+ is enough to start working effectively. Don't rush v1 until v0+ has
been used for at least 2-3 real tasks (we'll know what to optimize after that).
