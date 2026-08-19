# Claude 验收意见 + 迁移 PR 计划(2026-07-09)

双 AI 验收:Codex 起草的 4 份规范 **全部结构合规**(posture-only、unvalidated 标注、
30 样本纪律齐全)。以下为逐份判定 + 修正案(A1-A4),以及正式化迁移的 PR 计划。
双向诚实:既查 oversell,也查 false-kill——没有发现需要否决的内容,修正案全部是
"补强",不是"推翻"。

## 逐份判定

| 文档 | 判定 | 修正案 |
|---|---|---|
| SENIOR_PM_ROLE_AND_NOTION_OS | PASS | A1 |
| WEEKLY_REPORT_TEMPLATE | PASS | A2 |
| PREDICTIVE_RESEARCH_UPGRADE_PLAN | PASS(四份中最强) | A3 |
| PAPER_TRADING_TRACKER_SPEC | PASS | A4(集成性修正,必须做) |

### A1 — Notion 从 6 库减到 3 库;补学长 onboarding

6 个数据库对一个 part-time PM 是维护负担,v0 只建 3 个:
1. **Weekly Reports**(每周一页,内容 = repo `docs/team/weekly/*.md` 的粘贴渲染)
2. **Review Requests**(学长评论 → 决定 → 后续 KR,闭环表)
3. **Paper Signals(只读镜像)**(周度从 `paper_signal_log.json` 导出摘要表)

**Repo 是唯一 source of truth,Notion 只是审阅面**——双写会烂。Industry Maps /
Model Iterations / Thesis Queue 先活在 repo 文档里,等审阅流程跑顺(≥4 周)再决定
是否搬进 Notion。

**学长 Day-1 onboarding 包(30 分钟能读完):**
- 最新一期周报(能力/实践/目标 一节先读)
- Posture ladder 速查卡(NOT_ADVANCED→…→STARTER_CANDIDATE;执行门 5 态)
- "本项目不做什么":不给买卖指令;<30 样本不谈胜率/alpha;实盘决策只属于 Junyan
- 他的三件事:挑战因果链薄弱处 · 验收"模型改动是否被验证过" · 每周最多 3 条建议

### A2 — 周报模板补两条

1. **§2/§3 数据源指针写死进模板**:NAV/持仓/成交 = `model_fund/{fund,nav_history,
   orders}.json`,信号 = `paper_signal_log.json`,判分 = `nowcast_log.json`——
   周报生成变成机械动作,杜绝手抄错数。
2. **"本周被纪律挡下的动作"升级为 Executive Summary 必填项**(现在只是 §2 注释)。
   对外部审阅者,"没做什么"往往比"做了什么"更能证明系统有纪律。

### A3 — 预测研究计划的两处校准

1. Label 列表里的 next-day(1d)标签:**预期为 null**——我们自己的 n=14 nowcast
   判分已经证明 churn 里 1 天期资金去向 ≈ 掷硬币。保留该标签是为了证伪,不是期待。
2. 价值链图谱**不从零开始**:AI 硬件链已有 15 家公司的完整 5 维研究(光模块 5 +
   PCB/CCL 5 + 连接器 5,tasks #104-106)——直接作为图谱 v0 种子,第一周产出即可
   有血肉。

### A4 — Tracker 必须扩展现有账本,不许开第三本账(阻断级)

现有 `paper_signal_log.json` 已有 **58 条正式信号** + model_fund 四件套。Codex 的
新 schema 若另起新文件,一个月后我们会有三本对不上的账。修正:
- 新 setup_type 枚举(rotation_hypothesis / value_chain_thesis / …)**并入现有
  log 的 schema**,老记录字段缺省视 legacy。
- `thought_log` 单独一个 append-only 文件,按 signal_id 外键关联,不改写原假设。
- **watchtower 盘中 nowcast 目前只写 `watchtower_log.json`(untracked),没进
  `nowcast_log` 判分池**——2026-07-09 实测确认的 gap,PR-M2 里补 wiring。

## 迁移 PR 计划(等 Junyan 批准后执行)

**PR-M1 `docs/team PM 运行系统`(纯文档,不碰任何代码/tracker):**
```
docs/team/PM_OPERATING_SYSTEM.md          ← SENIOR_PM_ROLE + A1
docs/team/WEEKLY_REPORT_TEMPLATE.md       ← 模板 + A2
docs/research/PREDICTIVE_RESEARCH_PROGRAM.md ← 升级计划 + A3 + 两份方法论合并
docs/team/weekly/2026-W28.md              ← 第一期周报(本 folder 的 DRAFT 定稿)
STATUS.md                                 ← 新增当前态一条
```
隔离 worktree off origin/main,显式 allowlist,不 merge 等口令。experiments/ 原稿
保留作 archive。

**PR-M2 `paper tracker v1`(experiments/ 范围内代码):**
schema 扩展 + thought_log + watchtower→nowcast_log wiring + 周度 rollup 脚本
(带 30 样本 gate 的汇总,永不输出胜率 claim 除非 n≥30)。

**PR-M3 生产迁移(明确推迟)**:scripts/paper_trading.py / Dashboard tab /
signal_quality.py 的对接,等 tracker 跑满一个月、第一份月度 learning memo 出来后
单独审批。

**Notion 落地(Junyan 手动 10 分钟,我无法替你创建 workspace):**
1. 新建 workspace "AR Research" → 3 个 database(属性清单见 PM_OPERATING_SYSTEM)
2. 邀请学长(可评论权限)
3. 每周五:把 `docs/team/weekly/` 最新一期粘贴为新页 + 在 Review Requests 建行
4. 自动化(Notion API token → 周报自动发布)= phase 2,先人工跑 4 周验证流程本身

## Validation footer

Causal logic is valid because:每条修正案都指向一个可命名的失败模式(双写烂账/
第三本账/1d 噪声/onboarding 缺失)。
Specific numbers:n=14 hit 0.50 [validated against ledger];"3 库""4 周""30 分钟"
均 [unvalidated intuition] 运营选择。
Conclusion posture:specs ACCEPTED with amendments;迁移 PENDING Junyan 批准。
Next gate:Junyan 批 PR-M1/M2 → 我在隔离 worktree 执行。
Self-audit:无买卖指令;无 alpha claim;学长角色不含实盘审批权。

不是买卖指令;研究信号,human executes.
