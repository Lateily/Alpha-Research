# AR 六人团队与 AIOS 建设章程 v4

> 状态：`PROPOSED / REVIEW_REQUIRED`
> 决定人：Junyan
> 项目主管：Simon
> 生效条件：本文件经 PR 独立复核并由 Junyan 合入 `main`
> 版本日期：2026-08-16

## 0. 本次调整

本版本替代三人体制的 `TEAM_CHARTER_v2.md`，并覆盖旧文档中以下分工：

- Junyan 不参与 AIOS 日常开发，保留产品、研究宪法、核心文件、`main` 与生产上线终审。
- Reed 接手 Product OS、Web 前端和产品经理职责，同时负责 AIOS 的用户层与产品对接。
- Better 转为 AI Engineer，主责 H6 Context 工程接口和 H8 Router/Agent/Skill。
- Eric 主责 H1 Runtime、H10 Observability 和 H12 Harness Memory，不是只做日志运维。
- Simon 继续担任项目主管并主责 AIOS 控制平面。
- Jason 主责 Evals、Safety、Policy 与独立质量门。

旧文档仍可作为历史与技术细节参考；角色、Owner、Reviewer 或权限发生冲突时，以本章程为准。

## 1. 权限与协作原则

1. 所有成员可以在已声明范围的 Issue、branch、worktree 和 PR 中正常开发，不需要 Junyan 逐步授权。
2. Junyan 只在研究宪法、核心文件、高风险权限、生产上线和最终合并处出现。
3. 每个重要系统面必须有一位人类主责 Owner；AI 不能成为模块 Owner。
4. 关键层不能由开发者自己证明完成，必须经过独立 cross-review。
5. `main` 是唯一共享事实源；聊天、会议纪要和本地文件不自动成为团队规则。
6. 模块数量不等于工作量。按工程复杂度、学习深度、集成责任和复核责任检查平衡。

## 2. 六人最终分工

| 成员 | 角色 | 主责系统面 | AIOS 模块 | 不负责什么 |
|---|---|---|---|---|
| Junyan | Founder / 总负责人 / Product & Research Authority | 产品方向、Research OS 宪法、核心文件、`main`、生产终审 | Human Decision Final Gate | 不参与 AIOS 日常开发，不逐步审批低风险施工 |
| Simon | 项目主管 / AI Technical PM / Control Plane Architect | 项目路线、任务状态、依赖、权威与跨模块集成 | H2 Constitution、H3 Task Lifecycle、H4 Workflow Digital Twin | 不替模块 Owner 写完所有实现，不自签团队完成状态 |
| Reed | Product Manager / Product Engineer / AIOS Product Bridge | Product OS、Web 前端、用户旅程、BFF/Contract Client、产品验收 | H7 Prompt/Role/Task UX；辅助 H4 用户工作流 | 不主责 H6 检索、H8 路由或 Agent 权限逻辑 |
| Better | AI Engineer / Context & Agent Platform | Context、Repository Intelligence、Router、Agent 与 Skill 平台 | H6 Context Broker、H8 Router/Agent/Skill；辅助 H5 Repo Intelligence | 不负责产品优先级和页面需求裁决，不自签安全上岗 |
| Jason | Evals / Safety / Governance Engineer | 评测、红队、Policy、Authority、独立 Review | H9 Evals/Quality、H11 Safety/Human Gate | 不替执行者补造证据，不允许开发者自己签最终质量门 |
| Eric | Runtime / LLMOps / Harness Memory Engineer | 隔离执行、运行生命周期、Telemetry、成本报警、长期 Memory | H1 Runtime、H10 Observability、H12 Memory/Learning | 不把原始日志直接当 Memory，不让 Memory 自动修改宪法 |

## 3. 系统协作主链

```text
Junyan 定义产品与研究边界
  ↓
Reed 把用户问题变成 Product Brief / PRD / AIOS Task UX
  ↓
Simon 编译任务状态、依赖、权威与团队工作流
  ↓
Better 组装当前上下文并路由 Agent / Skill
  ↓
Eric 在隔离 Runtime 执行、观测并沉淀长期 Memory
  ↓
Jason 进行 Evals、Safety、对抗复核与 Authority Gate
  ↓
Reed 在产品层展示结果与 Human Approval UX
  ↓
Junyan 只对核心/高风险/生产变更作最终裁决
```

## 4. 每个人的明确任务与学习路径

### 4.1 Junyan：战略、研究与最终权威

主责：

- 定义第一产品楔子、用户边界、研究宪法和停止条件。
- 审核 `main`、核心合同、生产发布和 HIGH/CONSTITUTIONAL 变更。
- 对团队提交的证据作最终接受、修改、拒绝或延后决定。

两周交付：

- 批准 Product Brief 与 canonical app 决策。
- 确认内部 Alpha → 团队 Beta → 封闭试点的进入门。
- 审核本章程与各成员首个 vertical slice。

### 4.2 Simon：控制平面与项目主管

主责：

- H2：Constitution Graph、权威顺序、核心文件与修订门。
- H3：Task Contract、Registry、状态派生、依赖和 Reconciler。
- H4：把 Research/Product/AIOS 的真实工作流投影到同一 Workflow Digital Twin。
- 维护路线图、RACI、Issue/PR/Backlog 一致性和跨模块集成顺序。

两周交付：

1. 一张可执行的 AIOS 路线图：module → owner → dependency → issue → PR → status。
2. Constitution Graph 最小切片，能指出任务应读哪些权威文件及其冲突。
3. 把本章程拆成五位建设成员的 GitHub Issue 与 Review pair。
4. 清理旧 Owner、重复 Issue 和已被替代 PR 的状态。

学习重点：任务状态机、依赖图、GitHub 项目治理、技术架构表达、系统集成与变更管理。

### 4.3 Reed：Product OS、Web 与 AIOS 产品桥

主责：

- Product Brief、PRD、信息架构、用户旅程、优先级、验收与反馈闭环。
- `web/` 新主干、Contract Client、只读 BFF/API、data-state 和部署体验。
- H7 用户层：按任务类型定义 Role、Prompt 输入、结构化输出、Human Approval UX。
- 辅助 Simon 的 H4，把用户动作映射为 AIOS Task、Run、Review、Decision 和 Memory 状态。
- 从真实用户失败与反馈中整理 eval case，交给 Jason 固化。

两周交付：

1. 对 #257 给出 merge/revise/close 决策，并完成 Product OS M0/canonical app ADR。
2. 实现一个最小 Product–AIOS Bridge：

   `用户需求 → ai-task → AIOS run 状态 → 结构化结果 → Human Review → 页面展示`。

3. 选择一条真实旅程闭环，不同时建设全部页面。
4. 为该旅程提交 COMPLETE/PARTIAL/STALE/BLOCKED/ERROR fixtures。

学习重点：产品发现、PRD、React/TypeScript、runtime schema、BFF、AI 产品交互、prompt/role 设计和用户评测。

边界：Reed 定义“用户需要什么、AI 结果如何被理解”，不决定 Context 检索算法、Router 权限或 Agent 上岗。

### 4.4 Better：Context、Router、Agent 与 Skills

主责：

- H6：Context Builder/Broker、权威读取、freshness、最小上下文、RAG 和 Memory retrieval 接口。
- H8：AgentAdapter、Capability Registry、Router、Skill Registry 和任务—能力匹配。
- 辅助 H5：Repository Intelligence、change map、producer/consumer 和影响分析。
- 向 Reed 提供稳定的 AI output contract，向 Eric 提供可执行 run request。

两周交付：

1. 接手并收口 #265 A-010 Context Builder，明确 legacy owner handoff。
2. 实现离线 vertical slice：

   `ai-task → Context Pack → Policy-ready request → Router → Skill/Agent selection`。

3. 建立最小 Skill Registry：task type、输入/输出、工具、权限、版本、eval 状态和 owner。
4. 对 stale authority、冲突文档、无资格 Agent、越界工具写负向测试。

学习重点：Python、RAG、embedding/retrieval 评测、MCP/Tools、Agent routing、structured output、repository intelligence 和 prompt injection 边界。

边界：Better 决定“当前任务加载什么、交给哪个能力”，不决定产品优先级，也不能自行批准 Agent 生产上岗。

### 4.5 Jason：Evals、Safety 与独立质量门

主责：

- H9：Harness eval、Agent/Skill 上岗评测、回归矩阵、mutation 和对抗测试。
- H11：Policy、secret/scope/network/budget 权限、安全红队和 Human Gate。
- 独立复核 Better、Eric 与 Simon 的关键 PR；审核必须绑定 exact head。

两周交付：

1. 建立 Harness Eval 最小矩阵：task type × model/skill × quality/safety/cost。
2. 独立审查 #250、#261、#265 的当前 head，并给出 merge/revise/close 结论。
3. 建立“开发者不能自签”的 verification/review/decision contract。
4. 固化 prompt injection、scope escape、stale context、恶意 PR 和成本失控回归。

学习重点：LLM evaluation、red teaming、AI safety、mutation testing、权限模型、威胁建模和审计证据。

### 4.6 Eric：Runtime、Observability 与 Harness Memory

Eric 的工作不是“写日志”。他拥有从路由结果到可恢复运行，再到长期记忆回流的完整闭环。

主责：

- H1 Runtime：Isolation Executor、run lifecycle、timeout、retry、idempotency、interrupt cleanup 和恢复。
- H10 Observability：run_id、模型/Skill 版本、cost、latency、status、failure reason、health、alert 与 ack。
- H12 Memory：从 Task/Run/PR/Review/Human Decision 中提炼长期可复用记忆，并向 H6 暴露检索接口。

两周交付分两步：

**Week 1：合同与失败模型**

- 定义 `ai-run`、`ai-health`、`ai-alert`、`ai-memory` 最小合同。
- 明确 timeout、retry、duplicate run、partial evidence、unacked alert、memory conflict 的失败语义。
- 用离线 fixture 证明 COST_UNKNOWN、PARTIAL、FAILED 和 RECOVERED 不会被伪装成成功。

**Week 2：真实 vertical slice**

```text
Router Decision
  → Isolation Executor
  → Run Manifest / Telemetry
  → Verification Evidence
  → Memory Distillation
  → Memory Registry
  → H6 Retrieval Interface
```

验收：同一 task/input/prompt/commit 重跑不产生重复副作用；失败可定位；Memory 有来源、版本、owner、适用范围、时间和过期状态。

学习重点：进程与容器/隔离、异步任务、状态机、OpenTelemetry 思维、成本与报警、事件溯源、向量/结构化 Memory、恢复与故障演练。

## 5. H6 Context 与 H12 Memory 的边界

| 问题 | Better / H6 Context | Eric / H12 Memory |
|---|---|---|
| 核心问题 | 这个任务现在需要知道什么？ | 这次运行有什么值得未来继续知道？ |
| 时间 | 任务开始前与执行中 | 任务结束、复核和人类决定之后 |
| 输入 | 权威文档、repo、当前 task、被批准的 Memory | Task、Run、Artifact、Review、Decision、失败与修复证据 |
| 输出 | 最小、最新、可追踪的 Context Pack | 带 provenance/version/owner/TTL 的 Memory Record |
| 决策权 | 选择本次加载哪些内容 | 提议哪些经验进入长期 Memory |
| 禁止 | 不把所有历史无差别塞入上下文 | 不自动修改宪法，不把原始日志直接升格为真理 |

H12 向 H6 提供“可检索候选记忆”；H6 根据当前任务、权威、freshness 和权限决定是否加载。两层必须通过合同连接，不能相互替代。

## 6. 工作量平衡检查

| 成员 | 主要复杂度 | 结论 |
|---|---|---|
| Simon | 三个控制平面模块 + 项目集成与清账 | 重；以架构/状态闭环为验收，不按代码行衡量 |
| Reed | 产品经理 + Web/Contract Client + AIOS Product Bridge | 重；不能再同时承担 H6/H8 |
| Better | Context/RAG + Router/Agent/Skill + Repo Intelligence 接口 | 重；完整 AI Engineer 主线 |
| Jason | Evals + Safety + 独立审核责任 | 重；Review 工作计入正式交付量 |
| Eric | Runtime + Observability + Harness Memory | 重；按 Week 1/Week 2 分阶段，避免同时铺开所有实现 |

五位建设成员的工作量在系统复杂度上基本均衡。若出现进度不平衡，优先缩小 vertical slice，不通过给某人追加第二套主责系统解决。

## 7. Cross-review 关系

| Owner | 必要 Reviewer | Review 重点 |
|---|---|---|
| Simon | Better + Jason | Context/依赖是否可执行；Authority 是否越权 |
| Reed | Simon + Jason | 用户流程/状态是否一致；AI 输出与权限是否误导 |
| Better | Jason + Eric | 路由与 Context 安全；runtime request 是否可执行 |
| Jason | Reed + Simon | 测试是否真正到达用户/状态语义，是否出现误杀 |
| Eric | Jason + Better | 隔离/恢复/报警是否 fail closed；Memory/H6 接口是否清楚 |

HIGH/CONSTITUTIONAL、核心文件和生产上线在独立 Review 后仍需 Junyan 最终裁决。

## 8. 每人认领模板

每位成员从本章程拆出的 Issue 必须填写：

```text
OWNER:
PRIMARY_MODULE:
USER_OR_SYSTEM_PROBLEM:
UPSTREAM_INPUT:
OUTPUT_CONTRACT:
FIRST_VERTICAL_SLICE:
NON_GOALS:
MOST_DANGEROUS_FAILURE:
FAIL_CLOSED_BEHAVIOR:
ACCEPTANCE_TESTS:
REVIEWERS:
DEPENDENCIES:
TARGET_DATE:
LEARNING_EVIDENCE:
```

## 9. 完成标准

成员完成一个学习/建设任务，必须同时满足：

1. 有 GitHub Issue、命名 branch/worktree 和 PR，不只在聊天或本地。
2. 有可运行 vertical slice，而不是只提交课程笔记或架构图。
3. 有结构化输入/输出合同和至少一个真实失败样例。
4. 有独立 Reviewer，对 exact head 给出证据。
5. 能用“问题—机制—证据—残余风险—下一步”讲清楚。
6. 状态明确区分 MERGED、DEPLOYED、VALIDATING 和 ADOPTED；不得提前宣称完成。
7. 新经验回写 Backlog/Memory；新债取得正式 ID，不能留在聊天。

不是买卖指令；AI 只生产证据和研究辅助，人类负责最终决策。
