# AR 研究工程永久总账

> 生效日期:2026-07-31。维护人:Junyan。工程协作:Claude/Codex/Reed/Better。
> 本文件解决一个具体问题:研究工程不能只存在于聊天记录、临时承诺或某个 Agent 的记忆里。
> `docs/ARCHITECTURE_MAP.md` 负责看全局,本文件负责保存研究工程的每一笔债务与验收证据。
> AI harness、Agent 调度、评测、成本和 Memory 自动化由
> `docs/llm/AI_OS_ENGINEERING_BACKLOG.md` 单独管理;两份总账由 AI OS Reconciler 对账。

## 1. 总账规则

1. 新研究想法必须先取得 `R-xxx` 编号,再进入 Issue、PR 或排期。
2. 任务不得静默删除。停止一项任务时必须写 `RETIRED`,并填写原因、证据与替代项。
3. `DELIVERED_UNWIRED` 只表示代码或文档存在,不表示生产闭环已经成立。
4. `DONE` 必须同时满足:实物存在、消费方接线、失败路径测试、真实运行证据、文档同步。
5. 聊天中的“今晚完成”“已经修复”不改变状态;只有仓库证据和验收记录能改变状态。
6. 研究规则、组合风险规则、资金规则的状态变更由 Junyan 批准;Agent 可以实现和审计,不能自行升格。
7. 每周五逐行检查 `APPROVED`、`IN_PROGRESS`、`BLOCKED`、`DELIVERED_UNWIRED`。超过 7 天无更新必须写原因。

### 状态枚举

| 状态 | 含义 |
|---|---|
| `PROPOSED` | 已记录,尚未批准进入实施 |
| `APPROVED` | 边界已批准,等待认领或实现 |
| `IN_PROGRESS` | 有 CLAIM、负责人和在途 PR |
| `BLOCKED` | 有明确外部阻断和下一次复核日期 |
| `DELIVERED_UNWIRED` | 实物已存在,但没有进入正式消费者或日常运行 |
| `VALIDATING` | 已接入生产影子运行,正在积累失败案例和判分样本 |
| `DONE` | 五项完成条件全部有证据 |
| `RETIRED` | 正式停止,保留原因和替代项 |

## 2. 已确认的产品边界

| 决策 | 已确认口径 | 日期 |
|---|---|---|
| 永久证券池 | 全部 A 股永久在线;港股只纳入持仓、已注册研究对象和行业锚;美股只作宏观与产业链锚 | 2026-07-31 |
| 运行节奏 | 盘后跑全市场正式扫描;盘前刷新宏观和隔夜锚;盘中只处理事件与候选池 | 2026-07-31 |
| 宏观门范围 | 先判断全市场和全组合风险环境,再映射到行业与持仓 | 2026-07-31 |
| 当前产品优先级 | 内部研究系统与运作系统同等重要;完成稳定的 0 到 1 后,再提升外部产品和前端优先级 | 2026-07-31 |
| 未来基金 | 共用数据主干,独立策略、独立账本、独立判分的影子基金;当前不进入实施主线 | 2026-07-31 |

## 3. P0:先修可信度和闭环断点

### 活跃 Issue 映射

| 工程线 | Issue | 覆盖 ID |
|---|---|---|
| 夜链事实终态与质量硬闸 | [#184](https://github.com/Lateily/Alpha-Research/issues/184) | R-001,R-002,R-022 |
| 全 A 永久在线与多通道漏斗 | [#186](https://github.com/Lateily/Alpha-Research/issues/186) | R-003,R-007,R-008,R-009,R-010,R-028 |
| 判分独立性与反自欺验证 | [#183](https://github.com/Lateily/Alpha-Research/issues/183) | R-004,R-011,R-012,R-013,R-014,R-015 |
| Macro OS 与 MRG | [#185](https://github.com/Lateily/Alpha-Research/issues/185) | R-005,R-017,R-020 |
| Tushare 与新闻可信边界 | [#188](https://github.com/Lateily/Alpha-Research/issues/188) | R-006,R-018 |
| 电池、Sector OS 与法庭 | [#187](https://github.com/Lateily/Alpha-Research/issues/187) | R-010,R-016,R-019,R-026,R-027 |
| 契约、总账与 Agent 边界 | [#182](https://github.com/Lateily/Alpha-Research/issues/182) | R-021,R-023,R-024,R-025 |

| ID | 工程 | 状态 | 负责人 | 当前实物/证据 | 完成验收 |
|---|---|---|---|---|---|
| R-001 | 夜链终态必须服从子契约语义 | `APPROVED` | Claude | 2026-07-31 真实运行中 `nightly_run.json=COMPLETE`,但 `public/data/v2/meta.json=PARTIAL` 且三份契约为 `STALE_INPUT`;#180 未明确覆盖该分支 | 任一必需契约 `PARTIAL/INCOMPLETE/STALE_INPUT/DATA_BLOCKED` 时夜链非 COMPLETE、exit 非 0、报警旗生成;加入该失败案例的端到端回归测试 |
| R-002 | 自动 preflight 与晋级前质检硬闸 | `IN_PROGRESS` | Claude | PR #180:正式路径自动 preflight,晋级器消费红旗/电池/freshness,新增离线回归测试 | 独立复验 #180;坏账本时 0 引擎启动;红旗、PARTIAL、过期、缺文件四类均不能 READY;合并后真实夜跑一次 |
| R-003 | 永久在线证券注册表与全市场多通道扫描 | `APPROVED` | Junyan+Claude | 当前 `momentum_prefilter.py` 扫约 5500 只,但候选主要由动量 TOP5 注入;红旗和六维电池只覆盖约 14 只动态名单 | 全 A 每只证券每日保留状态、最后扫描时间、进入/未进入原因;六类通道使用批量数据并集;扫描失败不能沿用旧结果冒充新结果 |
| R-004 | 判分样本独立性与方向分列 | `APPROVED` | Junyan+Claude | 主 scorecard 以 signal_id 去重并混合 constructive/cautious;尚无 `cluster_id`;现有 `claim_allowed` 不能证明 30 个独立簇 | schema 增 `cluster_id` 与主期限;存量回溯;正式 scorecard 永久分方向;门槛按独立簇计算;修复前撤销合并口径的 claim_allowed |
| R-005 | Macro OS 与 MRG 完整闭环 | `APPROVED` | Junyan+Macro Agent | PR #179 有 MRG 规格;PR #181 有第一版 Tushare 宏观原料,尚无完整引擎、全局契约、组合/行业消费者和判分 | 数据抓取→事件标准化→宏观状态→MRG→行业敏感度→组合暴露→消费者→T+1/T+5/T+20 判分全链影子运行 |
| R-006 | Tushare 数据健康、语义与新闻链修复 | `IN_PROGRESS` | Claude | PR #181:29 端点健康表、issuer_guidance 改名、四个参数修复、宏观抓取、major_news 边界 | 独立复验真实端点与离线网络守卫;关键端点失败使工作流失败;四个无权限源保持 DATA_BLOCKED;旧目录完成迁移后再删除 |

## 4. P1:研究发现与证据质量

| ID | 工程 | 状态 | 负责人 | 当前缺口 | 完成验收 |
|---|---|---|---|---|---|
| R-007 | 全市场批量 E1 事件层 | `APPROVED` | Data/Universe Agent | red flag 当前逐票跑动态名单,不能覆盖全 A,线性扩展会放大 API 成本 | forecast/express/公告等先按日期批量抓取,再本地 join 到证券注册表;每个事件带 source/as_of/fetched_at/trust_boundary |
| R-008 | 本地特征仓与增量计算 | `PROPOSED` | Claude+Better | 多个引擎重复请求同一行情和基本面,全市场逐票电池预计不可接受 | 日频原始层和特征层分离;按 trade_date 增量;Parquet/SQLite 二选一做 v0;相同输入可复跑并得到相同结果 |
| R-009 | 多通道候选并集与探索配额 | `APPROVED` | Junyan+Scanner Agent | 单一动量排序会遗漏慢牛、基本面拐点、事件驱动和逆向修复 | 动量、反转、E1 事件、基本面/估值、行业轮动、宏观敏感度六路独立产候选后取并集;保留随机控制样本;记录每路贡献与淘汰原因 |
| R-010 | 六维电池语义完整化 | `APPROVED` | Research Agent | 技术维仍是部分代理;消息维以公告为主;缺宏观/行业映射;局部 DATA_BLOCKED 曾被总体 COMPLETE 掩盖 | 每维独立 `status/as_of/coverage/source`;任一必需维阻断时总体不得 COMPLETE;新增 `sector_context` 和 `macro_context`;PASS 不得解释成值得买 |
| R-011 | 前兆层四格表 | `APPROVED` | Validation Agent | 目前容易只讲亮灯后应验案例,未固定统计漏报和误报 | 每晚保存昨日灯数与后续结果;固定 TP/FP/FN/TN 和基准率;按独立事件簇报告;n 未达门槛只显示计数 |
| R-012 | 主力净额指标体检 | `APPROVED` | Validation Agent | 资金门、轮动面板、nowcast 依赖同一地基指标,但尚无定盘预测信息量与稳定性体检 | 近 60 日全市场按日和行业聚类检验 T+1/T+3;报告覆盖、缺失、极值、方向稳定性;结果决定权重,不能由既有规则反推结论 |
| R-013 | 否决信号机会成本 | `APPROVED` | Validation Agent | 被 veto/NO_TRADE 的对象只看短期防损,没有统一跟踪 T+10 反事实 | 全部否决对象回填 T+1/T+3/T+10;以可执行触发价计,无触发价标 NOT_SCORABLE;周报固定展示保护与机会成本两面 |
| R-014 | 注册 schema v2 与 tainted 检测 | `APPROVED` | Claude | trigger/invalidation 仍大量为自由文本;次日开盘后补注册可能被新信息污染;聊天方向判断可绕过注册器 | 强制结构字段、系统时间、decision_as_of、registered_at、cluster_id、source manifest;晚于窗口自动 tainted;注册失败使相关报告 INCOMPLETE |
| R-015 | 不可篡改事件账本与数据 CI | `APPROVED` | Claude+Audit Agent | JSON 可手工改写,缺文件锁、哈希链和完整账本 schema CI | append-only JSONL 或等价事件层;文件锁、前序哈希、迁移工具;任何账本 diff 触发 schema、时间和一致性校验 |
| R-016 | 十日检察官与法庭唤醒 | `APPROVED` | Court Agent | 规则已经提出,仍依赖人工记得开庭;历史上出现延迟数晚 | `court_10d` 进入夜链;到期自动入 review queue;结论带证据更新时间;逾期成为夜链非完整项 |
| R-017 | 隔夜锚生产化 | `APPROVED` | Macro Agent | 2026-07-31 运行时文件仍停在 20260722,四锚 DATA_BLOCKED | 盘前自动刷新 NVDA/SOX/TSM ADR/A50;逐源 freshness;旧文件不得冒充当日;失败进入盘前告警 |
| R-018 | 新闻与信息面可信边界 | `IN_PROGRESS` | Reed+Claude | PR #181 新增 major_news 与实体闸门;正式公告 `anns_d` 和部分实时新闻仍无权限 | 外部文本只作不可信输入;实体解析、来源健康、重复去除、注入隔离、E 级标签齐;无权限源清楚显示替代来源和覆盖缺口 |
| R-019 | 行业 OS 持续填数 | `APPROVED` | Junyan+Sector Agents | 半导体、医药已有 v0,但锚点日期、缺失 E1、关系边和指标更新节奏没有统一 SLA | 每个 Sector OS 有指标字典、E1/E2 数据源、关系边、公司覆盖、催化剂、wrong-if、更新时间;过期自动提醒 |
| R-020 | 宏观到行业和组合的暴露矩阵 | `APPROVED` | Macro Agent+Portfolio Agent | 当前宏观想法停在全局判断,没有说明对行业和现有持仓如何传导 | 因子→行业方向/时滞/证据→持仓暴露→风险预算调整建议逐层留痕;只改变 posture/gate,不直接生成交易动作 |

## 5. P2:治理、契约与可持续运行

| ID | 工程 | 状态 | 负责人 | 当前缺口 | 完成验收 |
|---|---|---|---|---|---|
| R-021 | v2 契约与 schema 覆盖 | `APPROVED` | Junyan+Better | `public/data/v2/` 产物多于 `docs/contracts/` 文档;字段、required 和 freshness 无统一 schema | 每个前端可见 JSON 有 schema、版本、required、source、as_of、report 语义和失败样例;前端只读契约 |
| R-022 | 夜链报警消费闭环 | `APPROVED` | Ops Agent | 生成报警旗不等于有人消费;日志中的失败与 Issue/queue 没有自动绑定 | 每个报警有 owner、ack 时间、处理结果;未确认报警进入次日 preflight;最近三晚健康可查询 |
| R-023 | 协议文档去冲突 | `APPROVED` | Junyan+Reed | `AGENTS.md`、`CLAUDE.md`、冻结 `STATUS.md` 与现行章程存在旧路径、旧数据源和旧权限描述 | 每条关键规则只有一个权威位置;旧文件加冻结横幅和真实替代链接;自动链接检查通过 |
| R-024 | 总账、Issue 与进度板同步 | `IN_PROGRESS` | Reed+Junyan | Issue #164/PR #175 建进度板,但研究债此前没有持久化清单;最近任务可从聊天丢失 | 本总账是研究 source-of-truth;每个活跃 ID 对应 Issue/PR;进度板只读状态;每周自动查孤儿任务和失联 PR |
| R-025 | Agent 项目制和边界 | `APPROVED` | Junyan+Reed | 多 Agent 能力增加,但项目 owner、输入、输出、评测与文件边界未覆盖每条研究线 | Universe/Macro/Sector/Single-name/Validation/Portfolio/Audit Agent 各有岗位合同;越权修改 CI 拦截或 review 阻断 |
| R-026 | 结算者唯一与数据/工程分 PR | `APPROVED` | Junyan | 约定已在实践中使用,未形成单一书面协议 | 每个交易日只有一名 settlement owner;数据 PR 与工程 PR 分离;冲突检测进入 preflight |
| R-027 | 审阅问题清账 | `APPROVED` | Junyan | 历史审阅问题和到期回复可能滞留 Notion,未进入 repo 总账 | 每周五输出 open/answered/closed;逾期原因入账;答案链接回周报或研究文档 |
| R-028 | 研究漏斗质量仪表 | `PROPOSED` | Junyan+Validation Agent | 目前只看最终名单,无法判断哪层漏掉机会或制造噪声 | 展示全市场覆盖率、通道贡献、晋级率、DATA_BLOCKED、遗漏回溯、研究耗时;不使用未经门槛支持的收益语言 |
| R-029 | 下单层红旗闸门戳校验 | `APPROVED` | Claude | 合同 v1.5 C1:红旗闸门当前只管名单层,paper 下单路径无闸;牧原 002714(0711 首亏预告 / 0713 建仓)是直接事故 | `paper_tracker.py` / `model_paper_fund.py` 注册路径强制校验当日闸门戳,无戳拒绝写入并标 `ENTRY_UNGATED` |
| R-030 | 输出层措辞检查器 | `APPROVED` | Claude | 合同 v1.5 C4:day-1 只能写"候选",当前靠人工纪律;旭创 0729 案为同周第二次越权 | 扫描含单日证据的结论,命中"确认/成立/已验证"即阻断并要求改写 |
| R-031 | MRG 接晋级前置门 | `APPROVED` | Claude+Macro Agent | 合同 v1.5 C6:宏观门只能影响优先级与风险预算;当前 MRG 未接任何下游 | `MRG=RISK_OFF_BIAS` 时冻结晋级(只冻结不卖出),契约保持 `mode: review_context_only` |

## 6. 已交付但仍需继续验证的能力

| 能力 | 状态 | 还不能宣称什么 |
|---|---|---|
| 动量全市场扫描 | `VALIDATING` | 能找到价格强势对象,不等于全市场研究已经完成 |
| 红旗闸门 | `VALIDATING` | 能排查已知负面 E1,不等于 PASS 的对象值得进入组合 |
| 六维电池 | `VALIDATING` | 动态名单可跑,不等于六维均完整或全 A 已覆盖 |
| 轮动统计 | `VALIDATING` | 初始窗口给出描述结果,不等于跨期稳定或可作概率主张 |
| 半导体/医药 Sector OS | `DELIVERED_UNWIRED` | 有行业模板和首批数据,不等于自动更新或已接全市场漏斗 |
| v2 前端契约 | `DELIVERED_UNWIRED` | 部分 JSON 能导出,不等于所有契约新鲜、完整和可展示 |

## 7. 延后但保留

| ID | 事项 | 状态 | 重新启动条件 |
|---|---|---|---|
| F-001 | Quant Shadow Fund A | `PROPOSED` | 研究主干数据契约稳定,可独立建策略、账本和判分 |
| F-002 | Quant Shadow Fund B | `PROPOSED` | F-001 的隔离架构通过验收,不得共享信号账本 |
| F-003 | 多基金母组合分配器 | `PROPOSED` | 至少两个独立影子基金积累足够独立样本后再设计 |
| F-004 | 外部产品优先阶段 | `PROPOSED` | 内部研究与运作系统完成稳定 0 到 1,契约连续运行达到团队约定周期 |

## 8. 周五检查模板

| ID | 上周状态 | 本周实物 | 测试/运行证据 | 新状态 | 未完成原因 | 下个动作/负责人/日期 |
|---|---|---|---|---|---|---|
| 示例 | APPROVED | PR/文件链接 | 命令与结果 | IN_PROGRESS | 无 | 具体动作 |

不是买卖指令;研究信号,human executes.
