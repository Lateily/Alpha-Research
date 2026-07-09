# PM Operating System — 学长每周研究治理制度 v1

> 正式化自 `experiments/pm_research_ops_2026_07/SENIOR_PM_ROLE_AND_NOTION_OS.md`
> (Codex 起草)+ Claude 修正案 A1,Junyan 批准 2026-07-09。
> 角色区分:**Franky = 战略顾问/thesis 质量天花板**(见 SENIOR_ONBOARDING.md);
> **学长 = part-time PM + 投资逻辑审阅者**(本文档)。两条审阅线独立。

## 1. 角色定义

学长不是另一个信号源。角色 = part-time project manager + 投资逻辑挑战者:

- 保持每周"研究 + 模型改进"循环的组织性(周报驱动)。
- 挑战 thesis 里薄弱的因果链——尤其"数据支持论点"但催化剂/机制缺失的地方。
- 验收"模型改动是否被真正验证过",还是只是让故事更顺了。
- 提供产业知识、盲区、以及 Junyan 和 AI 都没覆盖的新视角。
- **不批准任何实盘动作。Junyan 是唯一的实盘执行人。**

非技术审阅者(如家人)读周报的"非技术五行",角色 = 产品/业务 sanity check:
项目是否越来越清晰、有纪律、有用,不评单个市场信号。

## 2. RACI

| 工作流 | Junyan | 学长(PM) | Claude | Codex |
|---|---|---|---|---|
| 实盘决策 | Accountable | Consulted | Informed | Informed |
| 每周优先级 | Accountable | 负责挑战 | 负责提案 | Consulted |
| 生产代码 | 批准 | Informed | Responsible | Consulted/审 |
| 实验 | 批方向 | Consulted | Consulted | experiments/ 内 Responsible |
| Thesis 逻辑 | Accountable | 负责批判 | 负责起草 | Consulted |
| Paper 账本 | Accountable | 审阅 | 维护生产路径 | 提议 schema/测试 |

## 3. 每周节奏([unvalidated intuition] 运营选择,跑 4 周后复盘)

1. **周一**:定本周问题(例:"模型能否区分板块轮动的持续与一日游?")。
   产出:1 个周 KR + 1 个 blocked 项 + 1 个 paper-signal 焦点。
2. **周中异步**:学长读 Notion 周页,只评 gap:缺催化剂、机制弱、数据出处差、
   阈值未验证、结果度量不清。
3. **周五/周末**:Junyan 复盘 portfolio + paper 结果;学长给**最多 3 条**建议;
   Claude/Codex 把被接受的建议转成 KR(不是模糊 backlog)。
4. **月度回顾**:paper 信号与模型改动合并复盘;**把流程胜利与投资胜利分开**;
   "模型靠不出信号躲过亏损"不算成功,除非那就是 pre-registered 目标。

## 4. Notion 工作区(v0 = 3 库;repo 是唯一 source of truth,Notion 只是审阅面)

1. **Weekly Reports** — 每周一页,内容 = `docs/team/weekly/*.md` 的粘贴渲染。
   属性:week / 日期范围 / market regime / NAV / 回撤 / reviewer status。
2. **Review Requests** — 学长评论 → 决定 → 后续 KR 的闭环表。
   属性:owner / 目标 artifact / 问题 / 评论 / 决定 / follow-up KR。
3. **Paper Signals(只读镜像)** — 周度从 `paper_signal_log.json` 导出摘要。
   属性:signal_id / ticker / setup_type / hypothesis / gate / outcome_status。

Industry Maps / Model Iterations / Thesis Queue 先活在 repo 文档,审阅流程跑顺
(≥4 周)再决定是否入 Notion。**禁止双写**:任何内容的编辑发生在 repo,Notion
只粘贴。

**建站步骤(Junyan 手动,~10 分钟):** 新建 workspace "AR Research" → 按上述
属性建 3 库 → 邀请学长(可评论)→ 每周五把最新周报粘为新页 + Review Requests
建行。自动化(Notion API)= phase 2。

## 5. 学长 Day-1 Onboarding 包(30 分钟)

1. 最新一期周报(`docs/team/weekly/` 最新文件;先读"能力/实践/目标"节)。
2. Posture 速查卡:研究阶梯 `NOT_ADVANCED → WATCH → WATCH_CONSTRUCTIVE →
   STARTER_CANDIDATE(需 R/R≥2:1)→ ADD/REDUCE/EXIT`;执行门
   `NO_CHASE / HOLD_OBSERVE / WARNING / RECLAIM_REVIEW / DE_RISK_REVIEW / EXIT_REVIEW`。
3. **本项目不做什么**:不给买卖指令;<30 独立样本不谈胜率/alpha;一切收益数字
   目前来自 ¥100 万虚拟账户;实盘决策只属于 Junyan。
4. 他的三件事(见 §1)+ 每周最多 3 条建议的约定。

## 6. 学长审阅 rubric(每周回答)

- 这周的核心 claim 是什么?证据 tier(E1 发行人/交易所 · E2 推断/媒体 ·
  E3 价格/资金 · E4 假设)?
- 因果链完整吗:催化剂 → 机制 → 财务影响 → 市场重定价?
- 什么会证明它错(wrong-if)?
- 模型改动是被前瞻证据验证,还是事后解释?
- 最能改进下周流程的一条建议是什么?

## 7. 非技术审阅者 rubric

系统这周学到了什么?因纪律**没做**什么?还有什么预测不了?什么证据显示在向
产品/服务靠近?下一个让系统更可信的里程碑是什么?

## 8. 禁区

- 不要求学长读所有文件;不请他批交易。
- 不把模型更新说成"更好",除非命名了评估指标。
- Notion 不许变成日记——它是决定账本。

## 9. 周验收标准

一周被"验收"当且仅当:portfolio/paper 快照 ✓ 模型改动账本 ✓ 至少一条
pre-registered 研究假设 ✓ 至少一个明确的 reviewer 问题 ✓ 下周 KR ✓。

标准本身 [unvalidated intuition];因果上有效,因为每条都建立
"想法 → 动作 → 结果"的可审计链接。

不是买卖指令;研究信号,human executes.
