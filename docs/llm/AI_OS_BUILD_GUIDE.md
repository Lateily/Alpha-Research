# AR AI OS 技术搭建指南 v0

> Owner:Reed。产品与研究验收:Junyan。架构/代码复核:Claude/Codex。展示层:Better。
> 本指南把 AI 从“临时聊天助手”变成可追踪、可复跑、可审计、可控成本的工程系统。
> 当前状态:`APPROVED / DESIGN`。任何“自动化完成”声明仍需真实运行与失败路径证明。

## 0. 最终目标

以后任何工程任务进入 AR 平台后,AI OS 自动完成以下工作:

1. 读取权威文档、Issue、PR、总账和当前代码状态。
2. 把自然语言需求编译成机器可读任务规格,指出缺失信息。
3. 检查重复任务、文件冲突、依赖、权限和陈旧上下文。
4. 选择合适的 Agent,分配预算,创建隔离工作区和 CLAIM 租约。
5. 执行任务,持续记录版本、模型、prompt、成本、文件和证据。
6. 按任务风险自动选择测试,验证申报是否与实物一致。
7. 由独立 Agent 做敌意复核,并把发现回到原任务。
8. 等 Junyan 在宪法、合同、资金、合并等关键门上批准。
9. 合并后检查部署/运行结果,不能把“代码存在”写成“生产闭环完成”。
10. 自动更新永久总账、进度板、Memory、技术债和下次行动。

一句话定义:**AI OS 是任务操作系统,Progress Board 只是它的只读显示器,模型 adapter 只是它的工人插座。**

## 1. 当前起点,不重做已有资产

| 资产 | 当前实物 | 状态 | AI OS 如何复用 |
|---|---|---|---|
| Kimi K3 adapter | `scripts/llm/adapter.py`,PR #163 已合并 | `VALIDATING` | 作为首个 provider adapter,后续抽象统一接口 |
| LLM 成本账 | `public/data/v2/ops/llm_usage.jsonl` 本地运行账 | `VALIDATING` | run manifest 引用 usage `run_id`,不复制敏感 prompt |
| 评测集 v1 | `docs/llm/EVAL_SET_v1.md`,PR #172 已合并 | `DELIVERED_UNWIRED` | 拆分纯题包/封存答案/三臂盲评后进入 capability registry |
| ai-progress.v2 | Issue #164 + event/schema/conflict checker | `VALIDATING` | 继续作为 append-only 协作事件,扩展但不另造第二套 CLAIM |
| 团队共享进度页 | PR #175 | `IN_PROGRESS` | 只读投影 AI OS snapshot,不成为 source-of-truth |
| 永久研究总账 | `docs/research/RESEARCH_ENGINEERING_BACKLOG.md` | `VALIDATING` | Reconciler 每日读取并检查孤儿、失联、过期和状态漂移 |

当前真正缺少的是中间六层:任务编译器、注册表、政策引擎、调度器、验证器、Memory 蒸馏器。

## 2. 十条设计原则

1. **人类最终负责:**Junyan 决定研究规则、合同、资金规则、删除数据和合并口令。
2. **repo 与 GitHub 是事实源:**网页、Notion、聊天和 Agent 内存均为投影或输入。
3. **先确定性后 LLM:**路径检查、schema、状态转换、依赖、测试和冲突用代码;LLM 只处理语义任务。
4. **事件追加,状态派生:**保存每次 transition,当前状态由事件重放得到;不直接覆写历史。
5. **Fail closed:**缺证据、缺 freshness、schema 错、权限不明时进入 BLOCKED/INCOMPLETE,不自动 PASS。
6. **幂等:**同一 `task_id + input_hash + prompt_version + commit_sha` 重跑不能重复创建任务或重复写数据。
7. **最小权限:**每个 Agent 只拿当前任务需要的目录、工具、网络与预算。
8. **独立复核:**执行 Agent 不能为自己的正式交付做唯一裁判。
9. **申报不等于证据:**DONE 必须引用 commit、diff、命令、exit code、测试和运行证据。
10. **Memory 不能改宪法:**蒸馏器只能提案;规则升格仍走 PR 与 Junyan 批准。

## 3. 总体架构

```
输入层
Issue / PR / 永久总账 / 运行报警 / Junyan 指令 / 周五审阅
    ↓
控制平面
Task Compiler → Registry → Policy Engine → Scheduler → Lease/Lock
    ↓                    ↓
Context Builder       Human Approval Gates
    ↓
工作平面
Claude adapter / Codex adapter / Kimi adapter / Deterministic workers
    ↓
证据平面
Run Manifest → Artifact Manifest → Verifier → Adversarial Reviewer
    ↓
完成平面
PR / Merge / Deploy Check → Reconciler → Memory Distiller → Backlog Sync
    ↓
观察平面
Progress Board / Cost / Health / Alerts / Weekly Digest
```

四个平面必须解耦。UI 不能调模型,模型不能直接改总账状态,状态不能只靠模型一句“完成”。

## 4. 任务生命周期

### 正常状态机

`DISCOVERED → TRIAGED → SPEC_READY → CLAIMED → RUNNING → VERIFYING → REVIEWING → AWAITING_APPROVAL → MERGED → DEPLOYED/VALIDATING → DONE`

### 旁路状态

| 状态 | 触发 | 退出条件 |
|---|---|---|
| `SPEC_BLOCKED` | objective、边界、验收或 owner 不完整 | 补齐 task manifest |
| `BLOCKED` | 外部依赖、权限、网络、数据或人类决定 | 写 blocker、owner、next_review_at |
| `RELEASED` | CLAIM 主动释放或租约过期 | 新 owner 重新 CLAIM |
| `FAILED` | 执行或验证失败 | 生成 failure record 和重试策略 |
| `SUPERSEDED` | 被另一 Issue/PR 覆盖 | 链接 replacement,历史保留 |
| `RETIRED` | 人类决定不做 | 记录原因、证据和替代项 |

### 状态转换铁律

每次转换必须带:

`event_id,task_id,from_state,to_state,actor,reason,evidence_refs,timestamp_utc`。

禁止的捷径:

- `RUNNING → DONE`:没有验证、复核和批准。
- `MERGED → DONE`:没有部署/运行或文档类豁免证明。
- `BLOCKED → DONE`:没有解除阻断证据。
- `DELIVERED_UNWIRED → DONE`:消费者与真实运行不存在。

## 5. 八类机器契约

### 5.1 Task Manifest `ai-task.v1`

自然语言需求编译后的唯一任务规格:

```json
{
  "schema": "ai-task.v1",
  "task_id": "issue-186",
  "source_issue": 186,
  "architecture_block": ["块1-研究框架", "块3-引擎层"],
  "objective": "一句可验收目标",
  "non_goals": ["本轮明确不做什么"],
  "human_owner": "Junyan",
  "reviewer": "Junyan",
  "executor_candidates": ["Codex", "Claude"],
  "dependencies": ["issue-181"],
  "authority_docs": ["docs/research/ALL_MARKET_RESEARCH_FUNNEL.md"],
  "file_scope": ["scripts/example", "tests/example"],
  "forbidden_scope": ["experiments/execution_tracker/model_fund"],
  "input_contracts": [],
  "output_artifacts": [],
  "acceptance_tests": [],
  "risk_level": "LOW | MEDIUM | HIGH | CONSTITUTIONAL",
  "network_policy": "OFFLINE | ALLOWLIST | LIVE_DATA",
  "budget": {"max_cny": "0", "max_minutes": 60},
  "approval_gates": ["PR_REVIEW", "JUNYAN_MERGE"],
  "created_at": "ISO-8601"
}
```

`objective/non_goals/file_scope/acceptance_tests/human_owner/reviewer/risk_level` 缺一项即 `SPEC_BLOCKED`。

### 5.2 Claim Lease `ai-claim.v1`

在现有 `ai-progress.v2 CLAIM` 上增加机器语义:

`lease_id,task_id,branch,worktree,file_scope,executor,expires_at,heartbeat_at,input_hash`。

同一任务或重叠文件存在活跃 lease 时,调度器拒绝第二个写任务。只读审计可并行。

### 5.3 Run Manifest `ai-run.v1`

每次 Agent 调用或确定性 worker 运行保存:

`run_id,task_id,agent,provider,model,prompt_version,input_hash,commit_sha,worktree,tools,network_mode,started_at,ended_at,status,usage_run_id,cost,files_touched,error_class`。

不保存隐藏推理。敏感输入只存 hash;允许保存经批准的结构化输入和最终输出。

### 5.4 Artifact Manifest `ai-artifact.v1`

描述交付物:

`artifact_id,task_id,path_or_url,artifact_type,schema_version,content_hash,source_as_of,generated_at,producer_run_id,evidence_level,data_status`。

### 5.5 Verification Manifest `ai-verify.v1`

每条验收标准对应一条结果:

`check_id,requirement,method,command,exit_code,result,evidence_ref,offline,network_calls,checked_at`。

空命令、仅 grep、仅模型自述不能单独证明功能完成。

### 5.6 Review Manifest `ai-review.v1`

独立复核统一结构:

`finding_id,severity,claim,evidence,file_line,failure_scenario,fix,disposition,reviewer_run_id`。

严重级固定:`BLOCKER/MAJOR/MINOR`。每条发现必须可复现;误杀也要记录。

### 5.7 Decision Manifest `ai-decision.v1`

保存人类批准:

`decision_id,task_id,gate,decision,decided_by,scope,reason,evidence_refs,decided_at`。

允许值:`APPROVE/REVISE/REJECT/DEFER/RETIRE`。Junyan 的合并口令必须落这里或可追到 GitHub review/comment。

### 5.8 Memory Record `ai-memory.v1`

任务完成后的结构化蒸馏:

`memory_id,task_id,symptom,root_cause,decision,implementation,regression_test,residual_risk,reusable_rule,applies_to,evidence_refs,proposed_doc_updates,created_at`。

`reusable_rule` 初始只能是 `PROPOSED`;通过规则 PR 后才可升格。

## 6. 目录蓝图

Reed 的主边界继续保持在 `scripts/llm/` 与 `docs/llm/`:

```text
scripts/llm/
  adapter.py                       # 现有 Kimi adapter,逐步变成 provider 包装
  adapters/
    base.py                        # 统一 AgentAdapter 协议
    kimi.py
    claude.py
    codex.py
    deterministic.py
  ai_os/
    cli.py                         # 单一入口:compile/claim/run/verify/reconcile
    task_compiler.py
    registry.py
    event_store.py
    policy_engine.py
    scheduler.py
    context_builder.py
    executor.py
    verifier.py
    reviewer.py
    reconciler.py
    memory_distiller.py
    projection.py
  schemas/
    task.schema.json
    claim.schema.json
    run.schema.json
    artifact.schema.json
    verify.schema.json
    review.schema.json
    decision.schema.json
    memory.schema.json

docs/llm/
  AI_OS_BUILD_GUIDE.md
  AI_OS_ENGINEERING_BACKLOG.md
  prompts/<task_type>/<version>.md
  eval/<task_type>/questions.jsonl
  eval/<task_type>/answer_key.private.example.json
  runbooks/

public/data/v2/ops/
  ai_os_snapshot.json              # 前端只读投影
  ai_os_health.json
  ai_os_cost.json
  llm_usage.jsonl                  # 本地/受控运行账,不提交真实账

tests/ai_os/
  test_task_compiler.py
  test_state_machine.py
  test_policy_engine.py
  test_scheduler_conflicts.py
  test_verifier_fail_closed.py
  test_reconciler.py
  test_memory_distiller.py
  test_no_network.py
```

运行期缓存、租约和队列放 gitignored `.ar/ai-os/`;GitHub Issue/PR/comment 和 repo 文档保持事实源。`public/data/v2/ops/` 只存脱敏投影。

## 7. 自动化事件流

| 事件 | AI OS 自动动作 | 人类门 |
|---|---|---|
| Issue 新建/加工程标签 | 编译 task manifest,查重复、依赖和缺字段 | 规格不完整由 owner 补齐 |
| 总账新增 APPROVED | 检查是否有 Issue;无则生成提案,不得静默丢失 | Junyan 确认 Issue 边界 |
| CLAIM 请求 | 查 lease/文件冲突/权限/预算,生成隔离分支与 worktree 计划 | 高风险任务需先批 |
| Agent 开跑 | 组装最小上下文,记录 run manifest,执行心跳 | 超预算或越权立即停 |
| 文件变化/推送 | 根据 diff 选择测试,检查未声明文件和敏感信息 | HIGH/CONSTITUTIONAL 必须人工 review |
| PR Ready | 生成 artifact/verify manifest,启动独立敌意 review | Junyan 裁决 findings |
| PR 合并 | 校验 merge SHA,触发部署/真实运行/文档同步检查 | 生产或规则任务保留验证期 |
| 运行告警 | 自动开 failure event,关联 owner、最近变更和 run | 阻断需人类决定时 BLOCKED |
| 任务 DONE | 回写总账,生成 Memory,检查残余风险和后续项 | 规则升格单独批准 |
| 每日 reconciliation | 扫孤儿任务、陈旧 CLAIM、无 Issue PR、合并未部署、交付未接线 | 异常进入审阅队列 |
| 每周五 digest | 汇总完成、阻断、成本、失败、Memory 提案和下周依赖 | Junyan 验收会 |

## 8. 自动发现陈旧工程

这是 AI OS 替代人工“帮我再总结一次旧工程”的核心模块:`reconciler.py`。

每日必须扫描:

1. 总账 `APPROVED/IN_PROGRESS/BLOCKED/DELIVERED_UNWIRED` 是否有活跃 Issue、owner 和更新时间。
2. open PR 是否关联 Issue、R-ID/A-ID、验收标准和 Progress CLAIM。
3. merged PR 是否仍有 open task,或文档仍写“待合并”。
4. Issue 声称 DONE 是否有 PR/commit/测试/运行证据。
5. CLAIM 是否过期、重叠或缺 heartbeat。
6. 承诺日期超过 48 小时是否仍无实物。
7. 文件/契约/路径是否在权威文档中存在。
8. 代码已交付但消费者、workflow、projection 或真实运行是否缺失。
9. 报警旗是否有人 ack,是否被下一次运行静默覆盖。
10. Memory 提出的后续项是否取得 ID,避免蒸馏后再次丢失。

输出 `ai_os_reconciliation.json`:

`orphan_tasks,stale_claims,unlinked_prs,oversold_done,delivered_unwired,stale_docs,unconsumed_alerts,missing_followups`。

任何异常只自动开 Issue/评论提案,不得自动删除数据、重写历史或合并 PR。

## 9. Context Builder

Agent 质量漂移经常来自每次读取的上下文不同。Context Builder 必须按 task type 锁定读取顺序:

1. `AGENTS.md` 与当前权威协议指针。
2. `docs/ARCHITECTURE_MAP.md`。
3. 对应永久总账与目标架构。
4. task manifest 的 `authority_docs`。
5. 依赖 Issue/PR 的真实 diff 与状态。
6. 当前分支、dirty files、最近相关 commits。
7. 相关 schema、样例、测试和最近运行健康。
8. 明确排除不相关旧文档,并记录 `context_manifest`。

上下文包必带:`paths,commit_sha,loaded_at,content_hash,freshness,excluded_conflicts`。发现权威文档冲突时进入 `SPEC_BLOCKED`,不让模型自行挑一份喜欢的规则。

## 10. Agent 路由与能力注册

每个 Agent 维护 `agent-capability.v1`:

`agent,task_types,tool_access,file_scope,network_access,eval_version,eval_score,status,cost_profile,last_tested,known_failures`。

路由顺序:

1. 先找确定性 worker。
2. 再找通过该 task type 影子评测的 Agent。
3. 满足文件和网络权限。
4. 在预算内选择成本较低者。
5. 高风险任务至少一个执行 Agent + 一个不同复核 Agent。

初始岗位:

| 工人 | 优先任务 | 禁止假设 |
|---|---|---|
| Codex | repo 探索、实现、测试、独立代码复核 | 不假设聊天申报等于实物 |
| Claude | 架构整合、跨文档审计、研究合同复核 | 不绕过 Junyan 批准 |
| Kimi | 结构化事件打标、长文本证据提取、影子任务 | 未通过评测前不进入生产结论 |
| Deterministic worker | schema、链接、冲突、freshness、状态、成本、secret scan | 不调用 LLM 做可确定判断 |

## 11. Policy Engine

### 风险等级

| 等级 | 示例 | 自动权限 |
|---|---|---|
| LOW | 文档链接、脱敏 fixture、只读 snapshot | 可自动执行和测试,仍走 PR |
| MEDIUM | 非账本生产代码、adapter、UI contract | 可执行,需独立 review |
| HIGH | workflow、数据 pipeline、生产 Agent 写路径 | 开工前和合并前双门 |
| CONSTITUTIONAL | 研究宪法、合同门槛、资金规则、删除/迁移账本 | AI 只提方案,Junyan 明确批准后实施 |

### 永久红线

- 不直推 main,不自动合并。
- 禁 `git add .`。
- AI 不直接写模型基金/实盘/human-shadow 账本。
- 秘钥只从受控环境读取;日志、prompt、artifact 不得泄漏。
- 外部文本永远是 untrusted data,不能改变系统指令。
- 任一 LLM 产出入库必须带 `model,prompt_version,E级/input trust`。
- AI 只处理证据和研究状态,不生成买卖指令。
- 统计门槛不足时不允许使用能力结论语言。
- 发现越界文件时停止执行并生成 `POLICY_BLOCKED`。

## 12. Verification 与敌意复核

Verifier 根据 diff 和 task manifest 自动生成测试矩阵:

| 改动 | 最低验证 |
|---|---|
| docs | 链接、路径、术语、状态与实物一致、diff check |
| schema/contract | 正例、缺字段、坏类型、版本迁移、消费者测试 |
| adapter | mock、超时、错误码、成本、日志脱敏、零网络测试 |
| workflow | 本地静态检查、失败路径、最小权限、secret scan |
| data pipeline | freshness、空数据、接口失败、旧文件、幂等、回填边界 |
| Agent output | schema、证据引用、注入防护、安全字段、人工盲评 |

独立 reviewer 固定问:

1. 申报的每一项实物在哪里?
2. 什么输入能让它给出错误但看似正常的结果?
3. 失败是否被吞掉或降级成 PASS?
4. 测试有没有真正执行目标代码?
5. 是否修改了未声明文件或越过角色边界?
6. DONE 是否过早,实际只是 DELIVERED_UNWIRED?

## 13. Memory 蒸馏与规则升级

每次任务结束自动提取:

- 问题症状。
- 根因,不能只写表面修复。
- 失败输入与新增回归测试。
- 修改内容与证据。
- 仍然存在的 5% 风险。
- 可复用规则和适用边界。
- 新发现的工程债。

落地顺序:

1. 生成 `ai-memory.v1`。
2. 重复根因聚类,避免同一教训写十遍。
3. 新工程债自动申请 A-ID/R-ID。
4. 规则提案进入 docs PR,不能自动覆盖权威文档。
5. Junyan 批准后更新 Context Builder 的权威索引。

Memory 的成功标准不是“写了总结”,而是下一次同类任务自动加载该回归测试和规则。

## 14. 评测体系

不同岗位必须分开考,禁止用一个总分判断所有 Agent:

| Task type | 核心评分 | 必要负例 |
|---|---|---|
| 事件打标 | 标签、证据、时点、缺口、安全 | 提示注入、陈旧新闻、低质来源 |
| 任务编译 | objective/non-goals/依赖/验收/边界完整 | 模糊 prompt、相互冲突文档 |
| 代码实现 | 功能、回归、范围、维护性 | silent fallback、旧文件冒充 |
| 审计 | 真问题、误杀率、复现性、严重级 | 大小写/嵌套字段、申报夸大 |
| Memory | 根因、复用性、证据、不过度升格 | 只复述 diff、虚构历史 |

评测纪律:

- 纯题包与 answer key 物理分离。
- 模型输出匿名化后由人类和非执行 Agent 盲评。
- 每次 prompt/model 版本变化重跑对应回归集。
- 生产资格按 task type 授予,不能从事件打标成绩外推代码能力。
- 成本、延迟、失败率与质量一起报告。

## 15. 观测与成本

AI OS 每日提供:

`tasks_by_state,stale_tasks,blocked_tasks,policy_blocks,verification_failures,review_findings,cost_by_agent,cost_by_task_type,p95_latency,retry_count,data_blocked,unconsumed_alerts`。

预算控制:

- task manifest 写最大人民币成本和最大运行时间。
- 达到 80% 预算发 WARN,达到 100% 停止新调用。
- 重试必须使用同一 `run_id` 派生 attempt,禁止悄悄重复计费。
- 无 usage 返回时标 `COST_UNKNOWN`,不能填 0。

## 16. Reed 的实施路线

### K0 已有地基

- Kimi adapter、usage JSONL、offline mock 已在 main。
- ai-progress.v2 已在 main。
- K1 题库在 main,影子盲评尚未完成。

### AIOS-K1:任务合同与只读对账器

交付:

- 八类 schema 中先做 task/event/decision 三类。
- `task_compiler.py`:Issue/总账→task manifest。
- `registry.py`:从 Issue/PR/progress events 派生状态。
- `reconciler.py`:输出第一份陈旧工程报告。

验收:

- 对当前 7 条研究 Issue 实跑。
- 能抓出无 Issue 总账项、过期 CLAIM、merged/open 状态冲突和 DELIVERED_UNWIRED。
- 只读,不自动写 GitHub。

### AIOS-K2:Policy 与 Context

交付:

- 文件/角色/网络/预算/风险政策。
- Context Builder 和 authority hash。
- SPEC_BLOCKED/POLICY_BLOCKED 失败路径。

验收:

- 注入相互冲突文档、越界路径、缺验收标准和 secret-like fixture 均被拦截。

### AIOS-K3:调度与隔离执行

交付:

- AgentAdapter 基类、capability registry、router。
- lease/heartbeat/release。
- worktree 计划和幂等 run manifest。

验收:

- 重叠文件任务不能并行写。
- 租约过期可安全释放。
- 同一输入重跑不创建重复 Issue/branch/event。
- 初期只允许 LOW 风险文档任务和影子事件打标。

### AIOS-K4:Verifier 与独立 Review

交付:

- diff-aware test planner。
- verification/artifact/review manifests。
- 自动 secret scan、scope scan、offline guard。

验收:

- 历史 `or True`、PARTIAL→COMPLETE、字段嵌套误杀等失败案例成为固定测试。
- 执行 Agent 不能签发自己的最终 review manifest。

### AIOS-K5:Memory 与自动回写

交付:

- memory distiller、root-cause clustering。
- 总账/Issue/Progress Board 的提案式同步。
- 周五 digest。

验收:

- 完成一个真实任务后自动生成 Memory、残余风险和新待办。
- 新待办取得 A-ID/R-ID,不留在聊天。
- 所有自动写 GitHub 的能力先走 GitHub App/细粒度 token 最小权限评审。

### AIOS-K6:生产化

交付:

- scheduler、队列、重试、告警消费、健康和成本投影。
- Better 对接只读 AI OS 面板。
- 月度模型重考和 prompt 回归。

验收:

- 连续运行团队约定周期,无重复任务、无越权写、无未消费高危告警。
- 自动化失败时可以退回人工 GitHub 工作流,不阻断团队。

## 17. Reed 的学习路线

| 阶段 | 学什么 | 必须做出的实物 | 达标定义 |
|---|---|---|---|
| 1 | Python 类型、JSON、CLI、pytest、HTTP | 一个 schema validator + 三个失败测试 | 能解释每行和错误路径 |
| 2 | 状态机、事件溯源、幂等、文件锁 | registry/event replay/lease | 重放结果一致,并发不重复 |
| 3 | GitHub API/App、webhook、Actions 权限 | 只读 Issue/PR reconciler | token 最小权限,无前端泄漏 |
| 4 | Agent adapter、tool calling、结构化输出 | 两个 provider 同一接口 | 可替换、可超时、可记成本 |
| 5 | Evaluation、盲评、回归集、误杀 | task-type eval harness | 问题包与答案隔离,可复跑 |
| 6 | Prompt injection、secret、sandbox | policy/red-team fixture | 外部指令不改变系统行为 |
| 7 | Observability、队列、重试、SLO | health/cost/alert projection | 失败可定位、预算可停止 |

每阶段学习报告只回答三件事:学到什么、平台哪一处使用、哪条测试证明掌握。没有代码/测试/运行证据不算完成。

## 18. Reed 每周固定产出

| 时间 | 产出 |
|---|---|
| 周一 | AI OS 状态快照:任务、阻断、成本、Agent 健康、上周失败 |
| 周二 | 当前里程碑 Draft PR + schema/fixture |
| 周三 | 离线测试、红队失败案例、评测结果 |
| 周四 | 与 Better/Junyan 联调契约和只读投影 |
| 周五 | 周度 AI OS digest:完成、未接线、陈旧工程、Memory 提案、下周依赖 |

## 19. Definition of Done

AI OS 子任务只有同时满足以下条件才可 DONE:

1. Issue 与 A-ID 存在。
2. task manifest 完整。
3. CLAIM、branch、文件范围真实。
4. 代码/文档/schema/fixture 实物存在。
5. 正例和至少一个失败回归测试通过。
6. verification manifest 可追到命令与证据。
7. 独立 review 无未解决 BLOCKER。
8. 成本、模型、prompt_version 和 E 级/可信边界齐。
9. Junyan 所需批准已记录。
10. 合并后消费者/运行验证完成,或明确标 `DELIVERED_UNWIRED/VALIDATING`。
11. Memory 和新待办已经回写。
12. Progress Board 与永久总账状态一致。

不是买卖指令;研究信号,human executes.
