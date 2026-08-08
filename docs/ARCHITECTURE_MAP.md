# AR 平台总架构图(唯一进度总览,每周五随周报刷新)

> 生效 2026-07-29。取代已冻结的 STATUS.md/ROADMAP.md 成为进度事实源。
> Track 规则:每个 PR/Issue 必挂一个块标签;新任务先答归属块,归不进=不做。
> 不是买卖指令;研究信号,human executes.

## 一张图

```
                ┌────────────────────────────────────────────┐
                │ 块7 团队与流程:GitHub流程·章程v2·进度协议·Notion·学长周消化 │
                └────────────────────────────────────────────┘
 ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌────────────────┐
 │块2 数据源 │ → │块3 引擎层 │ → │块4 契约层 │ → │块5 前端载体       │
 └─────────┘   └─────────┘   └─────────┘   └────────────────┘
                    ↑              ↑
      ┌─────────────┴─────┐  ┌─────┴─────────────┐
      │块1 研究框架(大脑)    │  │块6 AI系统(工人车间)  │
      └───────────────────┘  └───────────────────┘
                ┌───────────────────────────────┐
                │ 块8 运维:launchd·Actions·Vercel·凭证 │
                └───────────────────────────────┘
```

**前后端链接铁律:块3 写、块4 传、块5 读 — 契约层是唯一通道,其他连接方式非法。**

## 永久工程入口

| 入口 | 解决的问题 | 权威范围 |
|---|---|---|
| [研究工程永久总账](research/RESEARCH_ENGINEERING_BACKLOG.md) | 防止研究债、承诺和未接线能力随聊天或 Agent 会话丢失 | 所有研究工程的状态、owner、证据和验收条件 |
| [全市场分层研究漏斗](research/ALL_MARKET_RESEARCH_FUNNEL.md) | 从全 A 永久在线到候选、电池、深研、法庭的稳定路径 | 证券覆盖、运行节奏、通道、状态机和 Agent 分工 |
| [Macro OS](research/macro/MACRO_OS.md) | 把宏观事实、预期差、MRG、行业和组合暴露串成闭环 | 全组合宏观门与下钻接口 |
| [AI OS 技术搭建指南](llm/AI_OS_BUILD_GUIDE.md) | 让每个任务自动经历规格、认领、执行、验证、复核、批准、Memory 和总账回写 | Reed 的 Agent 控制平面、工作平面、证据平面与观测平面 |
| [AI OS 永久工程总账](llm/AI_OS_ENGINEERING_BACKLOG.md) | 防止 AI harness、评测、自动化与安全任务随会话丢失 | A-ID、状态、owner、验收和实施顺序 |
| [Product OS 技术搭建指南](product/PRODUCT_ENGINEERING_BUILD_GUIDE.md) | 把需求、契约、设计、前后端、QA、发布和反馈串成产品闭环 | Better 的 Product Engineer / Product Manager 权威手册 |
| [Product Engineering 永久总账](product/PRODUCT_ENGINEERING_BACKLOG.md) | 防止产品需求、迁移、质量与发布债散落 | PE-ID、状态、owner、验收和里程碑 |

**状态解释:**文档或脚本存在不等于闭环完成。进度必须区分 `DELIVERED_UNWIRED`、
`VALIDATING` 和 `DONE`;研究项与 AI 系统项分别以对应永久总账为准。

## 八块登记表

| 块 | 一句话 | 载体 | 负责人 | 完成度(E4) |
|---|---|---|---|---|
| 1 研究框架 | 怎么想:宪法v1.4/全市场漏斗/Macro OS/两票/双层线/E1-E4/判分 | docs/research/ + docs/team/ | Junyan | 75% |
| 2 数据源 | 原料:Tushare/东财/yfinance;健康表/宏观原料/新闻链在 #181 待验收 | scripts/fetch_*.py | Junyan+Claude | 55% |
| 3 引擎层 | 车间:夜链v2/哨兵/模型基金/判分/闸门/电池/归因;硬闸在 #180 待验收 | experiments/execution_tracker/ | Claude | 60→80%(#169/#170/#180) |
| 4 契约层 | 传送带:引擎→七契约JSON→前端只读 | public/data/v2/ + docs/contracts/ | Junyan定稿+Claude | 70%(#170 已合并 2026-07-31) |
| 5 前端载体 | 展厅(七面板+工作台)+工具间;旧Dashboard=legacy | src/(旧) → web/(新) | Better | 10% |
| 6 AI系统 | 工人:Claude(架构审核)/Codex(结对)/Kimi(考核中);评测/prompt库/成本 | scripts/llm/ + docs/llm/ + AGENTS.md | Reed | 15% |
| 7 团队流程 | 神经:main保护/PR口令/认领协议/Notion审阅/周消化 | GitHub 设置 + TEAM_CHARTER_v2 | Junyan | 60% |
| 8 运维 | 电力:launchd/Actions/Vercel(API停用)/凭证 | plist + .github/workflows/ | Claude | 55% |

## 块间接口(章程 §4 的载体化)

| 接口 | 通道 |
|---|---|
| 研究契约(1→4→5) | docs/contracts/*.md 字段规格 → export_contracts.py → v2 JSON |
| AI 岗位说明(1→6) | 指南第8章 + 评测集题目 |
| 前端插座(5→6) | AI 产出写入哪个契约、前端哪里展示 |
| 工人能力(6→1/5) | 竞技场月报 + llm_usage 成本表 |
| PR 验收(全) | 块标签 + python-ci + Claude 审 + Junyan 口令 |

## 完成度刷新记录

- 2026-07-29 初版:1:75 / 2:55 / 3:60 / 4:0(在途70) / 5:10 / 6:15 / 7:60 / 8:55。
  基准 = Codex 全面审查(2026-07-29)+ 当日在途 PR。百分比为工程成熟度 E4 估计,
  不代表收益能力。
- 2026-08-06 更新:4:70(#170 已合并 2026-07-31,夜链v2强制流水线 + public/data/v2 契约导出落地)。
  R-014 升 DELIVERED_UNWIRED(PR #217 已合并)。
