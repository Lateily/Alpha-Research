# AR AI OS 永久工程总账

> Program Owner:Simon。模块 Owner:Better / Jason / Eric / Reed。最终验收:Junyan。
> 2026-08-16 起，Owner 分配以 `docs/team/TEAM_CHARTER_v4.md` 和下表为准；
> 本文后续历史表格中仍写 Reed 的 Owner 字段在迁移完成前视为 superseded，不得据此认领。
> 状态枚举沿用研究工程总账:`PROPOSED/APPROVED/IN_PROGRESS/BLOCKED/DELIVERED_UNWIRED/VALIDATING/DONE/RETIRED`。
> 任务不得静默删除;停止时必须写 RETIRED、原因和替代项。

## 0. 2026-08-16 Owner 覆盖表

| 系统面 | A-ID / Harness | Primary | Support / Reviewer |
|---|---|---|---|
| Constitution / Task / Workflow | A-006~A-008,A-011,A-012 / H2-H4 | Simon | Reed（用户流）、Jason（Authority）、Eric（lease/runtime） |
| Context / Repo Intelligence / Router / Skills | A-010,A-013,A-014 / H5,H6,H8 | Better | Jason（上岗/安全）、Eric（runtime 接口）、Reed（产品输出） |
| Policy / Evals / Verification / Human Gate | A-009,A-018~A-020,A-027 / H9,H11 | Jason | Simon（状态语义）、Reed（用户失败）、Junyan（最终门） |
| Runtime / Run Evidence / Health / Memory | A-015~A-017,A-021~A-025 / H1,H10,H12 | Eric | Better（Router/H6）、Jason（隔离/报警）、Simon（总账） |
| Prompt / Role / Product Bridge | A-026 / H7 + Product OS | Reed | Better（Skill 接口）、Jason（回归）、Simon（Workflow） |

边界：Better/H6 决定当前任务加载什么；Eric/H12 决定运行后哪些证据成为带
provenance/version/owner/TTL 的候选长期 Memory。H12 向 H6 提供检索候选，不能自动
修改宪法或强制进入当前上下文。

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

## 6. 实施顺序

| 里程碑 | 包含 | 前置 | 退出条件 |
|---|---|---|---|
| AIOS-K1 | A-006,A-007,A-008 | A-004 | 对现有研究总账和 Issues 产第一份只读 reconcile 报告 |
| AIOS-K2 | A-009,A-010,A-011,A-012 | K1 | 模糊规格、文档冲突、越权和重叠写均被硬阻断 |
| AIOS-K3 | A-013,A-014,A-015,A-016 | K2,A-003 | LOW 风险文档任务端到端影子执行 |
| AIOS-K4 | A-017,A-018,A-019,A-020 | K3 | 一个真实 PR 完成证据→复核→人类裁决链 |
| AIOS-K5 | A-021,A-022,A-023 | K4 | DONE 自动产 Memory、新债和周度 digest |
| AIOS-K6 | A-024,A-025,A-026,A-027 | K5 | 连续运行期内无未消费高危报警、无越权、成本可停止 |

## 7. 每周检查

| A-ID | 上周状态 | 本周实物 | 测试/运行证据 | 成本 | 新状态 | blocker | next/owner/date |
|---|---|---|---|---|---|---|---|

不是买卖指令;研究信号,human executes.
