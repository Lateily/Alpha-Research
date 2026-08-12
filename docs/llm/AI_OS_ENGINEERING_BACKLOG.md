# AR AI OS 永久工程总账

> Program/Workflow:Simon。Agent Platform/Runtime:Reed。Quality/Safety:Jason。Knowledge/Context/Product:Better。最终验收:Junyan。本文档是 AI 系统工程的永久清单。
> Canonical strategy:`docs/llm/AR_AIOS_MASTER_BLUEPRINT_v3.md`。A-028 至 A-036 为 v3 批准战略下的 `PROPOSED` 实施项，未完成 Review/PR 前不得报告为已落地。
> 状态枚举沿用研究工程总账:`PROPOSED/APPROVED/IN_PROGRESS/BLOCKED/DELIVERED_UNWIRED/VALIDATING/DONE/RETIRED`。
> 任务不得静默删除;停止时必须写 RETIRED、原因和替代项。

## 1. 已有地基

### 活跃 Issue 映射

| 里程碑 | Issue | 覆盖 A-ID |
|---|---|---|
| K1 Task Contract/Registry/Reconciler | [#193](https://github.com/Lateily/Alpha-Research/issues/193) | A-006,A-007,A-008 |
| K2 Policy/Context/Scheduler/Lease | [#194](https://github.com/Lateily/Alpha-Research/issues/194) | A-009,A-010,A-011,A-012 |
| K3 Adapter/Router/Isolated Runner | [#195](https://github.com/Lateily/Alpha-Research/issues/195) | A-013,A-014,A-015,A-016 |
| K4 Evidence/Review/Human Gate | [#191](https://github.com/Lateily/Alpha-Research/issues/191) | A-017,A-018,A-019,A-020 |
| K5 Memory/Backlog/Digest | [#190](https://github.com/Lateily/Alpha-Research/issues/190) | A-021,A-022,A-023 |
| K6 Health/Cost/Prompt/Security | [#192](https://github.com/Lateily/Alpha-Research/issues/192) | A-024,A-025,A-026,A-027 |
| 事件打标影子评测 | [#161](https://github.com/Lateily/Alpha-Research/issues/161) | A-003,A-014 |
| Progress Board 控制事件 | [#164](https://github.com/Lateily/Alpha-Research/issues/164) | A-004,A-022,A-023 |

| ID | 工程 | 状态 | 证据 | 还缺什么 |
|---|---|---|---|---|
| A-001 | Kimi K3 provider adapter | `VALIDATING` | PR #163,`scripts/llm/adapter.py` | 抽象统一 Adapter;超时/重试/结构化输出;与 capability registry 接线 |
| A-002 | LLM usage/cost ledger | `VALIDATING` | `llm_usage.jsonl` 契约与离线测试 | provider 通用计价;无 usage=COST_UNKNOWN;预算硬停;日报投影 |
| A-003 | K1 事件打标评测集 | `DELIVERED_UNWIRED` | PR #172,Issue #161 | 纯题包/answer key 隔离;六道真题;三臂影子;匿名盲评;capability 入册 |
| A-004 | ai-progress.v2 协作事件 | `VALIDATING` | Issue #164,progress_event/schema/conflicts | 自动 heartbeat、状态派生、reconcile,不再依赖手工复制 |
| A-005 | 团队共享只读进度页 | `IN_PROGRESS` | PR #175 | 独立复验、角色边界复核、两周试用、保留/销毁裁决 |

## 2. AI OS 控制平面

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| A-006 | Task Manifest 与 schema | `APPROVED` | Reed | 自然语言/Issue 编译为 ai-task.v1;必填缺失→SPEC_BLOCKED;正反例测试 |
| A-007 | Task Registry 与事件重放 | `APPROVED` | Reed | 从 Issue/PR/progress 派生唯一状态;重放幂等;不覆写历史 |
| A-008 | 陈旧工程 Reconciler | `APPROVED` | Reed | 自动发现孤儿任务、过期 CLAIM、无 Issue PR、过早 DONE、未接线能力和未消费报警 |
| A-009 | Policy Engine | `APPROVED` | Reed+Claude | 文件/角色/网络/预算/风险四类硬闸;越权→POLICY_BLOCKED |
| A-010 | Context Builder | `APPROVED` | Reed | 按 task type 固定权威读取顺序;保存 context hash/freshness;冲突→SPEC_BLOCKED |
| A-011 | Scheduler 与依赖图 | `APPROVED` | Reed | 只调度依赖完成且规格完整任务;循环依赖和过期输入被阻断 |
| A-012 | Lease/heartbeat/file lock | `APPROVED` | Reed | 重叠文件任务不能并行写;租约到期安全释放;只读审计可并行 |

## 3. Agent 工作平面

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| A-013 | 统一 AgentAdapter | `APPROVED` | Reed | Claude/Codex/Kimi/确定性 worker 统一输入输出、超时、错误、usage 接口 |
| A-014 | Capability Registry 与路由 | `APPROVED` | Reed+Junyan | 按 task type 记录评测、权限、成本、失败;未通过影子评测不生产上岗 |
| A-015 | 隔离执行器 | `APPROVED` | Reed+Claude | branch/worktree/commit 绑定 run;最小工具和网络;中断可清理;不直推 main |
| A-016 | 幂等与重试 | `APPROVED` | Reed | 相同 task/input/prompt/commit 不重复建任务和写数据;重试成本可追踪 |

## 4. 证据与审核平面

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| A-017 | Artifact/Run/Verification manifests | `APPROVED` | Reed | 交付、模型、prompt、commit、命令、exit、成本和 evidence refs 全可追 |
| A-018 | Diff-aware Verifier | `APPROVED` | Reed+Codex | 按改动选测试;至少一个失败回归;DATA_BLOCKED/STALE 不得 PASS |
| A-019 | 敌意 Review Agent | `APPROVED` | Reed+Claude/Codex | 执行者不能单独签最终复核;findings 带严重级、证据、场景和修法 |
| A-020 | Human Decision Gate | `APPROVED` | Junyan+Reed | APPROVE/REVISE/REJECT/DEFER/RETIRE 机器可读;无口令不合并高风险任务 |

## 5. Memory、同步与观测

| ID | 工程 | 状态 | Owner | 验收 |
|---|---|---|---|---|
| A-021 | Memory Distiller | `APPROVED` | Reed | symptom/root cause/fix/test/residual risk/reusable proposal 结构化;不虚构历史 |
| A-022 | 总账与 Issue 提案式同步 | `APPROVED` | Reed | 新债取得 A-ID/R-ID;状态差异报警;不自动删除或越权升格 |
| A-023 | 周五自动 Digest | `APPROVED` | Reed | 完成、未接线、陈旧、阻断、成本、失败、Memory、下周依赖固定输出 |
| A-024 | AI OS Health/Cost/Alert contracts | `APPROVED` | Reed+Better | 前端只读;source-of-truth 仍为 GitHub/repo;无 usage 标 COST_UNKNOWN |
| A-025 | 报警消费闭环 | `APPROVED` | Reed | alert 有 owner/ack/result;未消费高危报警阻断 DONE |
| A-026 | Prompt Registry 与回归 | `APPROVED` | Reed | prompt 按 task type/version 入库;每次修改触发对应 eval;旧版可追 |
| A-027 | Agent 安全红队 | `APPROVED` | Reed+Audit Agent | prompt injection、secret、scope escape、恶意 PR、陈旧上下文、成本失控固定测试 |

## 6. v3 Harness 扩展总账

### A-028 至 A-036

| ID | 工程 | 状态 | Owner | 前置 | 验收 |
|---|---|---|---|---|---|
| A-028 | Constitution Graph、Authority Resolver 与 protected paths | `PROPOSED` | Simon+Jason | A-009 | 输出 A0-A5 `authority-pack.v1`;冲突→AUTHORITY_CONFLICT;核心路径命中 Junyan gate;普通授权域不要求逐步批准 |
| A-029 | Team Workflow Digital Twin 与 Program Mode | `PROPOSED` | Simon | A-006,A-007 | Issue→task/program→owner/reviewer→PR→deploy 状态可重放;跨模块任务有 DAG、合并顺序和 integration gate |
| A-030 | Repository Intelligence Map | `PROPOSED` | Reed | A-007,A-010 | Symbol/Data/Test/Ownership/Decision/Incident 六图;真实任务输出入口、消费者、测试、owner、active PR 和 confidence |
| A-031 | Context Broker 与 module profiles | `PROPOSED` | Better+Simon | A-010,A-030 | C0-C5 分阶段 Context Pack;source/location/reason/hash/freshness/trust 齐;main/合同变化→STALE;缺证据→CONTEXT_INCOMPLETE |
| A-032 | Skill Registry、Router 与 Chain Compiler | `PROPOSED` | Reed | A-014,A-031 | Skill 声明 trigger/schema/tools/scope/network/risk/owner/eval;原子 Skill 可独立失败;无 Eval 不进默认链 |
| A-033 | Session Checkpoint、Resume 与跨端恢复 | `PROPOSED` | Reed | A-012,A-017,A-031 | Mac/Windows 不依赖绝对路径;恢复时重验 SHA/authority/PR/CLAIM/context;过期状态不被继续执行 |
| A-034 | Cross-file Impact Analyzer 与 `ai-program.v1` | `PROPOSED` | Reed+Simon | A-029,A-030 | producer/schema/consumer/test/owner 闭环;跨模块 blast radius、子任务 DAG、集成测试和回滚明确 |
| A-035 | Harness Evals 与 Context/Prompt 回归 | `PROPOSED` | Jason | A-027,A-028,A-031,A-032 | 测 Authority 冲突、定位召回、Context precision、P5 越权、跨会话恢复、过度 DONE;高风险门含 mutation/current-head CI |
| A-036 | Team Style、P5 Prompt Composer、Decision Memory 与 Progress Projection | `PROPOSED` | Better+Jason+Simon | A-021,A-026,A-029,A-031 | team-style 机器可读;P5 按 case/phase/module/risk 生成且不扩权;Board 可从 Issue/PR/event/CI/deploy 重建;Memory 只提案 |

## 7. 依赖顺序

| 里程碑 | 包含 | 前置 | 退出条件 |
|---|---|---|---|
| AIOS-K1 | A-006,A-007,A-008 | A-004 | 对现有研究总账和 Issues 产第一份只读 reconcile 报告 |
| AIOS-K2 | A-009,A-010,A-011,A-012 | K1 | 模糊规格、文档冲突、越权和重叠写均被硬阻断 |
| AIOS-K3 | A-013,A-014,A-015,A-016 | K2,A-003 | LOW 风险文档任务端到端影子执行 |
| AIOS-K4 | A-017,A-018,A-019,A-020 | K3 | 一个真实 PR 完成证据→复核→人类裁决链 |
| AIOS-K5 | A-021,A-022,A-023 | K4 | DONE 自动产 Memory、新债和周度 digest |
| AIOS-K6 | A-024,A-025,A-026,A-027 | K5 | 连续运行期内无未消费高危报警、无越权、成本可停止 |
| AIOS-H1 | A-028,A-029,A-036(P5/style 最小切片) | K2 | Issue 可生成 Authority/Task/Workflow/P5;普通授权域与 Junyan 核心门正确分流 |
| AIOS-H2 | A-030,A-031,A-034 | H1 | 一个跨模块 Program 产 change-map、阶段 Context、DAG、集成门和回滚 |
| AIOS-H3 | A-032,A-033,A-035,A-036(完整闭环) | H2,K4 | 一个真实任务完成跨端恢复、Skill Chain、独立 Eval/Review、Board 投影与 Memory 提案 |

## 8. 每周检查

| A-ID | 上周状态 | 本周实物 | 测试/运行证据 | 成本 | 新状态 | blocker | next/owner/date |
|---|---|---|---|---|---|---|---|

不是买卖指令;研究信号,human executes.
