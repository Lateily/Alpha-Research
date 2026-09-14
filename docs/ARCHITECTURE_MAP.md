# AR 平台总架构图(唯一进度总览,每周五随周报刷新)

> 生效 2026-07-29,最近同步 2026-09-14。取代已冻结的 STATUS.md/ROADMAP.md 成为进度事实源。
> 刷新纪律自查:上一次同步是 2026-08-16,中间停更四周;本次由 Claude 按实物重测后补写。
> 块完成度是工程成熟度 E4 估计,不代表收益能力,也不代表该块在跑。
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
| 1 研究框架 | 怎么想:宪法v1.5/全市场漏斗/Macro OS/两票/双层线/E1-E4/判分 | docs/research/ + docs/team/ | Junyan | 75% |
| 2 数据源 | 原料:Tushare/东财/yfinance/FRED/BLS/BEA;WO-X1 十二源扩展已合并并完成历史采集,特征库新增 16 张半导体表;官方发布日历物化器仍缺;宏观库五源中 BEA/BLS/Census 至今 0 行 | scripts/fetch_*.py + experiments/macro_os/ + experiments/research_funnel/ | Junyan+Macro Agent | 65% |
| 3 引擎层 | 车间:夜链v4 共 24 步/哨兵/模型基金/判分/闸门/电池/归因;代码成熟但**自动调度自 2026-09-09 起连续三次失败**,班次已于 2026-09-14 由 16:35 改 20:30,待首次验收 | experiments/execution_tracker/ + experiments/macro_os/ + experiments/research_funnel/ | Claude+Macro Agent | 80%(运行中断,见本周实况) |
| 4 契约层 | 传送带:引擎→v2 JSON→前端只读;2026-09-08 那轮 48 件工件哈希复验一致,2026-09-14 补跑后当前发布面为 20260911、35 件工件、状态 COMMITTED。**缺口:契约没有新鲜度字段**,停更期间仍报 COMPLETE | public/data/v2/ + docs/contracts/ + experiments/*/schemas/ | Junyan定稿+Claude | 75%(缺过期标记) |
| 5 前端载体 | 展厅(七面板+工作台)+工具间;旧 Dashboard 仍是唯一对外站点,`web/` 至今只有一个 AGENTS.md;本机只读工作台是实际在用的查看入口 | src/(旧) → web/(新) | Better | 10% |
| 6 AI系统 | 工人:Claude(建设与独立复审)/Codex(工单实现)/Kimi(考核中);只读工作台已发布并常驻,AIOS 人工闸门 #290 仍 Draft | scripts/llm/ + docs/llm/ + AGENTS.md | Reed | 20% |
| 7 团队流程 | 神经:main保护/PR口令/认领协议/Notion审阅/周消化;**周报自 2026-W31(08-03)停更**,PM 验收节奏事实上中断 | GitHub 设置 + TEAM_CHARTER_v2 | Junyan | 50%(下调,周节奏停摆) |
| 8 运维 | 电力:launchd 五个服务(夜链20:30/EOD14:26/哨兵09:14/工作台常驻+观测)/Actions/Vercel(API停用)/凭证 | plist + .github/workflows/ | Claude | 55% |

## 本周实况(2026-09-14,由实物重测)

| 事项 | 状态 |
|---|---|
| 夜链 | 9/09、9/10、9/11 三次 16:35 班次全部 INCOMPLETE,目标交易日为空。根因是 `run_official_sample.py` 的全源结算日一致性检查:东财资金流对部分个股晚于日线结算,而重试只有 3 次 × 30 秒。2026-09-14 已把 `com.ar.nightly` 改为 20:30,取自唯一成功样本 9/08 20:26;同日 01:02 的补跑以 20260911 为目标跑通 24 步并发布,证明阻塞只在第一步。重试窗口本身由 PR #359 收口为 6 次 × 60 秒且受 420 秒墙钟预算约束;仓库内 plist 模板仍写 16:35,另由一个 PR 对齐。首次调度验收看当晚 `nightly_run.json` 是否 COMPLETE |
| 发布面 | 2026-09-14 01:05 的补跑已把发布面推进到目标交易日 20260911,35 件工件 COMMITTED;此前停在 9/08 20:26 那一轮(48 件,哈希复验一致)。`meta.json` 仍无过期字段,停更期间照报 COMPLETE,记为契约层新债 |
| 两道闸门 | 第一道已于 2026-09-09 15:17 触发:packet `78306352ac44`,002119.SZ / 600667.SH / 688035.SH 仅进深研,600667 警示保留。第二道未开:研究包 `research_pack_20260911` v2.1 的三条 paper 计划处于 PROPOSED,等 8 项执行口径裁定 |
| 模拟盘 | 100 万元虚拟盘,历史 5 笔订单全部了结,当前 0 持仓,NAV 自 7/06 起 +2.54%,最后一笔平仓 9/04 |
| 引擎缺口 | 两日成交有效期、T+10 退出尝试、三票共用一个集群额度均未实现;PR #357 仍 Draft。批准计划后这三项要人工执行 |
| Macro | `macro_gate.json` 停在 2026-08-06;M1-C 契约维持 CALIBRATING / DATA_BLOCKED,无正式阻断权 |
| 代码同步 | `~/ar-live` 仍停在 2b1eb5ad,比远端 main 少一个提交(9/09 合并的 #356);#358 与 #359 合并后需要一次同步 |
| 文档 | 本次同时修正 `CLAUDE.md`:它仍把已冻结的 STATUS.md 列为必读,并保留 2026-06-07 的推荐制 PIVOT 说明,与现行"只给姿态、不给买卖"章程冲突 |

### Macro 线状态快照(2026-08-15)

| 里程碑 | main 实物 | 当前状态 | 尚未完成 |
|---|---|---|---|
| M0-A | 契约、schema 与来源注册表,#240 | `VALIDATING / CALIBRATING` | 已由 M1-C 消费;待自动轮与连续运行证据 |
| M0-B | SQLite 历史仓、官方采集器与来源身份绑定,#245 | `VALIDATING / CALIBRATING` | 已完成手动生产 canary;待持续采集证据 |
| M0-B2 | 发布日历与双源共识门,#247 | `DELIVERED_UNWIRED / CALIBRATING` | 校验器已交付;官方日历物化器尚不存在,不得用手填/空日历冒充生产日历 |
| M0-B3 | URL 发现、自适应调度、延迟监控与 launchd 模板,#249 | `VALIDATING / CALIBRATING` | M1-C 已调用同一调度锁;独立 5 分钟模板仍未安装,待官方日历后真实 due/reuse 轮 |
| M1-A | 双区域四轴状态、MRG 候选态与事件上下文,#251 | `VALIDATING / CALIBRATING` | 手动生产产物已验证;待 T+1/T+5/T+20 影子判分 |
| M1-B | 31 个申万一级行业敏感度、组合暴露与只读面板,#252 | `VALIDATING / CALIBRATING` | 手动生产产物已原子发布;待前端消费与真实逐仓权重 |
| M1-C | `m1c.py`、同轮 manifest、夜链步骤与 staged publish,#256 | `VALIDATING / CALIBRATING` | 已合并部署且手动 canary 通过;待 2026-08-17 launchd 自动轮。日历缺失继续 `RELEASE_CALENDAR_NOT_PUBLISHED` |

这里的“手动生产 canary 通过”不等于自动调度验收。自动上线还要求 launchd 的运行计数
推进、退出码为 0、精确 run 日志段、同轮持久产物和无 incomplete 告警同时成立。
当前 Macro 只输出标签、研究优先级与风险预算语境;`formal_regime` 保持空值,没有交易动作或正式阻断权。#253 已把代表性 Macro
治理门接入 mutation-gate CI;AIOS K1 扩展由独立 PR 负责,此处不预先计为完成。

### 全市场研究漏斗状态快照(2026-08-15)

| 层 | main/生产实物 | 当前状态 | 下一门 |
|---|---|---|---|
| U0 | #226/#234 永久在线证券注册表,#269 同轮消费 | `VALIDATING` | 2026-08-17 launchd 自动验收 |
| U1 | #267 六通道独立扫描,#269 不可变观察 bundle;手动 canary 33,258 行 | `VALIDATING / PARTIAL` | 补 DATA_BLOCKED 通道,不得用复合总分 |
| U2 | #267 候选并集/配额/控制抽样;手动 canary 105 个 U3-ready | `VALIDATING / PARTIAL` | 修慢牛 0/15 与目标短缺 95;接 R-035 判分 |
| U3 | 既有动态名单六维电池可用 | `IN_PROGRESS` | 把 U2-ready 批量送入同日电池复审 |
| U4 | 契约与人工权威门已交付;2026-09-09 首次正式登记 148 条决策(3 SELECT / 40 REJECT / 3 DATA_BLOCKED / 21 NO_TRADE / 81 DEFER),账本累计 263 事件 | `HUMAN_GATE` | 第二道闸门待批 paper 规则;夜链停摆期间 deep queue 仍为 0 |
| U5 | 注册、判分、法庭与组合链可继续运行 | `VALIDATING` | R-039/040/041 完成前不得解锁因果簇 claim |

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
- 2026-08-09 Macro 状态同步:M0-A 至 M1-B 代码已进 `main`,统一按
  `DELIVERED_UNWIRED / CALIBRATING` 记账;M1-C 仍待接线,未上调生产完成度。
- 2026-08-09 M1-C 开工:同轮采集、M0-B3、M1-A、M1-B 和夜链 staged publish
  已在代码层串起,状态升为 `VALIDATING / CALIBRATING`;合并部署与真实夜跑前仍不算上线。
- 2026-08-09 依赖复核:M0-B2 具备日历证据绑定/校验,M0-B3 具备按日历调度,但仓库尚无
  从官方日历页生成 `release_calendar.json` 的生产物化器。M1-C 对该缺口 fail-closed,
  不生成空日历,并将其保留为 R-005 上线前硬前置。
- 2026-08-15 生产地基更新:#256/#258/#259/#267/#269 已合并并同步 `~/ar-live`;
  R-043 迁移在 0806 现场完成 WAL/双 manifest/双 pointer 实战验收;#269 手动 canary
  22/22 步通过。自动状态仍保持 PENDING,等 2026-08-17 launchd 首轮 receipt。
- 2026-09-14 复测更新:2:55→65(WO-X1 十二源与历史采集已合并),4:70→75(48 件工件实盘发布并复验),
  6:15→20(只读工作台常驻),7:60→50(周报停更六周,如实下调);3 与 8 维持,但夜链自动调度
  自 09-09 起中断,班次改为 20:30 待验收。基准 = Claude 对 `~/ar-live` 运行时、launchd、
  发布面与账本的只读重测,以及三个只读测绘代理的交叉核对。
- 2026-09-14 01:10 补记:同日 01:02 的补跑以 20260911 为目标跑通并发布(35 件工件),
  特征库补入 09-09 至 09-11,样本与信号补回 9/11;09-09、09-10 两天的样本与 NAV 行不补,
  因为一次运行只锁定一个目标交易日,回填历史交易日没有合法入口。夜链重试窗口见 PR #359。
