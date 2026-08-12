# AR AIOS 团队章程 v3

**状态:** APPROVED STRATEGY / IMPLEMENTATION PROPOSED
**批准人:** Junyan
**日期:** 2026-08-12

> 本章程取代 `TEAM_CHARTER_v2.md` 中的三人体制与“每次 PR 前都由 Junyan 过程验收”的日常语义。v2 保留为历史背景；现行 AIOS 组织采用 Junyan + Simon + Reed + Jason + Better。

## 1. 组织原则

1. Junyan 负责方向、研究与资本方法论、`main`、核心文件、高风险生产和最终合并。
2. Junyan 不承担普通任务的逐步批准；成员在完整任务合同和授权模块内自主施工。
3. Simon 是项目主管，负责需求 triage、任务架构、依赖、owner/reviewer、Program Mode 和跨组推进。
4. Reed、Jason、Better、Simon 均参与 AIOS 建设并拥有真实技术制品。
5. AI 可以施工、解释、测试和 Review，但不能成为人类 owner 或自己的唯一裁判。

## 2. 责任与学习路径

| 成员 | 主路径 | 核心责任 | 首个 vertical slice |
|---|---|---|---|
| Simon | Technical AI PM / Workflow & Context Architect | Authority、Task、Workflow、Program、控制面 | Issue → task → workflow → Board projection |
| Reed | Agent Platform / Runtime / LLMOps | Bootstrap、Repo Intelligence、Skill Router、Scheduler、runtime | task → change-map → route → worker → run manifest |
| Jason | AI Quality / Safety / Reliability | P5 安全、Policy、Evals、mutation、independent review | 破坏治理门 → 测试翻红 → 修复 → current-head review |
| Better | Knowledge / Context / Prompt / AI Product | RAG、Context、P5 profiles、Board、反馈体验 | 10 份批准材料 → eval set → citation/as-of RAG → Context Pack |
| Junyan | AI Systems Product Owner / Domain Governor | A1、研究标准、优先级、main/core/final gate | 审核 Final Merge Packet 和宪法级决定 |

固定交叉 Review：

- Reed ↔ Jason：平台、运行时、安全和 Evals。
- Better ↔ Simon：需求、Context、Knowledge、Prompt 和 UX。
- 跨模块任务由 Simon 指定 integration reviewer。
- Junyan 只在 `main`、核心/宪法、高风险生产和最终决定门介入。

## 3. 共同技能底座

四位建设成员都必须掌握：GitHub 协作；Python/TypeScript/API/SQL/JSON Schema；LLM structured output/tool use；Prompt/Context/RAG；Agent 状态机/幂等/retry；sandbox/权限/注入；Evals/mutation；trace/cost/incident；AR 研究合同与非自动交易边界。

每项学习任务必须有真实制品、正常用例、失败用例、本人讲解、跨成员 Review、残余风险和复盘。只交学习笔记不算掌握。

## 4. 团队工作流

1. 正式需求进入 GitHub Issue。
2. Simon triage 并确认 task type、owner、reviewer、依赖和风险。
3. Owner CLAIM 后创建 branch/worktree，并尽早打开 Draft PR。
4. Owner 在 current head 上完成正向与失败验证。
5. 独立 Reviewer 审查；新 commit 令旧证据与 approval 变 STALE。
6. 满足 required checks 后进入 `AWAITING_APPROVAL`，生成 Final Merge Packet。
7. Junyan 作最终 `APPROVE/REVISE/REJECT/DEFER/RETIRE`。
8. 合并、部署、生产验证和 DONE 分开记录。
9. Reconciler 更新 Progress Board、handoff、Memory 和 capability evidence。

Progress Board 是自动投影，不是成员另行手填的第二套台账。群聊只发简短通知和决策摘要。

## 5. 团队风格

1. 从用户和需求端定义工作，而不是从技术偏好倒推需求。
2. 结论先行；事实、推断和建议分开。
3. 输出对口接收者，并给出明确的下一动作。
4. 先定位根因，再修改；修复后检查同类问题和系统性缺口。
5. `PARTIAL/STALE/UNKNOWN/DATA_BLOCKED` 不得写成 PASS。
6. 工作结束后沉淀 regression、Skill、workflow、合同或 Memory proposal。
7. 统一同步 `STATE/OWNER/RESULT/EVIDENCE/BLOCKER/DECISION_NEEDED/NEXT`。

## 6. 事实源

| 位置 | 职责 |
|---|---|
| Issue | 任务、范围、验收、owner、依赖、blocker、决定 |
| PR | diff、测试、Review、风险、deploy plan |
| ai-progress.v2 | CLAIM、heartbeat、状态与 evidence 追加事件 |
| Progress Board | 上述事实的只读投影 |
| 本地 `.ai-workspace/` | 缓存、session、index、checkpoint；不作为共享事实源 |
| 群聊 | 通知与摘要；不保存唯一事实 |

## 7. 相关权威

- AIOS 总蓝图：`docs/llm/AR_AIOS_MASTER_BLUEPRINT_v3.md`
- AIOS 工程指南：`docs/llm/AI_OS_BUILD_GUIDE.md`
- AIOS 实施总账：`docs/llm/AI_OS_ENGINEERING_BACKLOG.md`
- 仓库运行合同：`AGENTS.md`
