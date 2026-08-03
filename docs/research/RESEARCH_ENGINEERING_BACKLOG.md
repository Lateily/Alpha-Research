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
| R-002 | 自动 preflight 与晋级前质检硬闸 | `DONE` | Claude | **PR #205 已合并**(#180 因 squash 堆叠失效后重建):正式路径自动 preflight,晋级器消费红旗/电池/freshness,离线回归测试 | **验收通过 2026-08-03**:①坏账本注入 ⇒ 0 引擎启动、报警旗落盘、report=INCOMPLETE、steps=0 ②四类拒绝全部有回归断言,且已用「短路 qc_decide」反证四条同时 ✗(13/13 恢复)③真实夜跑 nightly_v2 report=COMPLETE 15/15 步 OK |
| R-003 | 永久在线证券注册表与全市场多通道扫描 | `APPROVED` | Junyan+Claude | 当前 `momentum_prefilter.py` 扫约 5500 只,但候选主要由动量 TOP5 注入;红旗和六维电池只覆盖约 14 只动态名单 | 全 A 每只证券每日保留状态、最后扫描时间、进入/未进入原因;六类通道使用批量数据并集;扫描失败不能沿用旧结果冒充新结果 |
| R-004 | 判分样本独立性与方向分列 | `APPROVED` | Junyan+Claude | 主 scorecard 以 signal_id 去重并混合 constructive/cautious;尚无 `cluster_id`;现有 `claim_allowed` 不能证明 30 个独立簇 | schema 增 `cluster_id` 与主期限;存量回溯;正式 scorecard 永久分方向;门槛按独立簇计算;修复前撤销合并口径的 claim_allowed |
| R-005 | Macro OS 与 MRG 完整闭环 | `APPROVED` | Junyan+Macro Agent | PR #179 有 MRG 规格;PR #181 有第一版 Tushare 宏观原料,尚无完整引擎、全局契约、组合/行业消费者和判分 | 数据抓取→事件标准化→宏观状态→MRG→行业敏感度→组合暴露→消费者→T+1/T+5/T+20 判分全链影子运行 |
| R-006 | Tushare 数据健康、语义与新闻链修复 | `IN_PROGRESS` | Claude | **PR #206 已合并**(#181 因 squash 堆叠失效后重建):29 端点健康表、issuer_guidance 改名、四个参数修复、宏观抓取、major_news 边界 | **部分达成 2026-08-03(Junyan 驳回 DONE)**:已验 = `data_source_health.py` 步刻意不带 continue-on-error,五个关键源(daily/daily_basic/moneyflow_dc/moneyflow_ind_dc/moneyflow_mkt_dc)任一非 OK 即 exit 1 ⇒ 整个工作流失败 · AR_OFFLINE 离线守卫在位 · 无权限源保持 DATA_BLOCKED 不伪装为 0 · issuer_guidance 改名已覆盖 4 个消费方。**残留 = 验收第四条「旧目录完成迁移后再删除」根本未验** —— 我只验了健康表与硬失败两条就标了 DONE。需逐项确认:旧路径消费方是否已全部切到新契约 · 迁移是否完成 · 旧目录能否安全删除;在此之前不得标 DONE |

## 4. P1:研究发现与证据质量

| ID | 工程 | 状态 | 负责人 | 当前缺口 | 完成验收 |
|---|---|---|---|---|---|
| R-007 | 全市场批量 E1 事件层 | `RETIRED` | Data/Universe Agent |**由 R-036 取代**(全 A 事件层);原描述:red flag 当前逐票跑动态名单,不能覆盖全 A,线性扩展会放大 API 成本 | forecast/express/公告等先按日期批量抓取,再本地 join 到证券注册表;每个事件带 source/as_of/fetched_at/trust_boundary |
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
| R-018 | 新闻与信息面可信边界 | `IN_PROGRESS` | Reed+Claude | **PR #206 已合并**:major_news 消费器 + 实体闸门 + 不可信输入隔离;正式公告 `anns_d` 与部分实时新闻仍无权限 | **部分达成 2026-08-03**:已有 = 实体闸门(仅当实体确认才挂 ticker)· 来源健康 · 去重 · 外部正文按不可信数据只取标题/时间/来源 · major_news 消费器。**残留 = ①E 级标签未落到新闻链**(E 级只在 `api/research.js`/`research-multi.js`)②`anns_d` 无权限时未显式展示替代来源与覆盖缺口 |
| R-019 | 行业 OS 持续填数 | `APPROVED` | Junyan+Sector Agents | 半导体、医药已有 v0,但锚点日期、缺失 E1、关系边和指标更新节奏没有统一 SLA | 每个 Sector OS 有指标字典、E1/E2 数据源、关系边、公司覆盖、催化剂、wrong-if、更新时间;过期自动提醒 |
| R-020 | 宏观到行业和组合的暴露矩阵 | `APPROVED` | Macro Agent+Portfolio Agent | 当前宏观想法停在全局判断,没有说明对行业和现有持仓如何传导 | 因子→行业方向/时滞/证据→持仓暴露→风险预算调整建议逐层留痕;只改变 posture/gate,不直接生成交易动作 |

## 5. P2:治理、契约与可持续运行

| ID | 工程 | 状态 | 负责人 | 当前缺口 | 完成验收 |
|---|---|---|---|---|---|
| R-021 | v2 契约与 schema 覆盖 | `APPROVED` | Junyan+Better | `public/data/v2/` 产物多于 `docs/contracts/` 文档;字段、required 和 freshness 无统一 schema | 每个前端可见 JSON 有 schema、版本、required、source、as_of、report 语义和失败样例;前端只读契约 |
| R-022 | 夜链报警消费闭环 | `APPROVED` | Ops Agent | 生成报警旗不等于有人消费;日志中的失败与 Issue/queue 没有自动绑定 | 每个报警有 owner、ack 时间、处理结果;未确认报警进入次日 preflight;最近三晚健康可查询 |
| R-023 | 协议文档去冲突 | `APPROVED` | Junyan+Reed | `AGENTS.md`、`CLAUDE.md`、冻结 `STATUS.md` 与现行章程存在旧路径、旧数据源和旧权限描述 | 每条关键规则只有一个权威位置;旧文件加冻结横幅和真实替代链接;自动链接检查通过 |
| R-024 | 总账、Issue 与进度板同步 | `IN_PROGRESS` | Reed+Junyan | Issue #164/PR #175 建进度板,但研究债此前没有持久化清单;最近任务可从聊天丢失 | **部分达成 2026-08-03**:总账已是 source-of-truth。**残留 = ①26 个活跃项中 20 项背景列无 Issue/PR 引用**(R-003/004/007/009~017/019/020 等)②无周检孤儿任务/失联 PR 的工作流 ③本轮已修一类真实故障:R-002/R-006/R-018 曾长期引用 #180/#181,而这两个 PR 因 squash 堆叠早已 CLOSED,真正合并的是 #205/#206 |
| R-025 | Agent 项目制和边界 | `APPROVED` | Junyan+Reed | 多 Agent 能力增加,但项目 owner、输入、输出、评测与文件边界未覆盖每条研究线 | Universe/Macro/Sector/Single-name/Validation/Portfolio/Audit Agent 各有岗位合同;越权修改 CI 拦截或 review 阻断 |
| R-026 | 结算者唯一与数据/工程分 PR | `APPROVED` | Junyan | 约定已在实践中使用,未形成单一书面协议 | 每个交易日只有一名 settlement owner;数据 PR 与工程 PR 分离;冲突检测进入 preflight |
| R-027 | 审阅问题清账 | `APPROVED` | Junyan | 历史审阅问题和到期回复可能滞留 Notion,未进入 repo 总账 | 每周五输出 open/answered/closed;逾期原因入账;答案链接回周报或研究文档 |
| R-028 | 研究漏斗质量仪表 | `PROPOSED` | Junyan+Validation Agent | 目前只看最终名单,无法判断哪层漏掉机会或制造噪声 | 展示全市场覆盖率、通道贡献、晋级率、DATA_BLOCKED、遗漏回溯、研究耗时;不使用未经门槛支持的收益语言 |
| R-029 | 下单层红旗闸门戳校验 | `APPROVED` | Claude | 合同 v1.5 C1:红旗闸门当前只管名单层,paper 下单路径无闸;牧原 002714(0711 首亏预告 / 0713 建仓)是直接事故 | `paper_tracker.py` / `model_paper_fund.py` 注册路径强制校验当日闸门戳,无戳拒绝写入并标 `ENTRY_UNGATED` |
| R-030 | 输出层措辞检查器 | `APPROVED` | Claude | 合同 v1.5 C4:day-1 只能写"候选",当前靠人工纪律;旭创 0729 案为同周第二次越权 | 扫描含单日证据的结论,命中"确认/成立/已验证"即阻断并要求改写 |
| R-031 | MRG 两阶段接线 | `APPROVED` | Claude+Macro Agent | 合同 v1.5 C6 修订:未校准的门若先拿阻断权会形成循环依赖(它造成的"没开仓"被记成"避免损失",从此无法证伪) | 阶段A只标注+RISK_OFF_BIAS 降 sizing 上限至 STARTER_CAPPED 并每日入判分;阶段B 达 ≥30 独立因果簇且优于随机后由 Junyan 单独批准阻断权 |
| R-037 | 单票结论电池戳校验 | `APPROVED` | Claude | 合同 v1.5 C2:full_battery 只对动态名单强制,临时单票分析(含对话产出)无机器强制 | 单票结论产出路径校验 24h 内电池戳,无戳拒绝并标 `NO_BATTERY_STAMP` |
| R-038 | 因果簇 id 生成器与历史回填 | `BLOCKED` | Claude+Validation Agent | 合同 v1.5 C5 采用因果事件簇;claim 解锁的唯一路径。**BLOCKED 说明**:阻断源 = R-039/040/041 + 硬前置 R-014/R-015(账本无文件锁,B 不可原子计算)未建成;**下次复核日期 = 2026-09-01**。C5 §4 三态阶梯只约束 correction/migration 不约束 genesis,retrospective genesis 可在 S2 信号上执行,循环已解 | 规则版本先冻结 → 单一 genesis 批次回填 122 条 → manifest 落盘(approval_ref/manifest_hash)→ R-039 即刻对该批生效;genesis 当期 claim_allowed 强制 false |
| R-032 | U0 全市场证券注册表 | `APPROVED` | Claude+Data Agent | 漏斗 v1:红旗/电池当前只覆盖 14 只动态名单,全 A 99.7% 从未被检查 | 全部 A 股永久注册 + 资格标签(ST/北交所/低流动性标注不删除) |
| R-033 | U1 六通道批量扫描器 | `APPROVED` | Claude+Scanner Agent | 漏斗 v1 拍板一:通道独立,不得复合总分抵消 | 六通道各自阈值取并集;entry_reasons[] 逐条留痕;禁跨通道排序字段 |
| R-034 | U2 候选池与三项保留配额 | `APPROVED` | Claude+Scanner Agent | 漏斗 v1 拍板二:慢牛/逆向修复/随机控制必须保配额 | 100-300 候选,进入与淘汰理由留痕,保留配额不参与主通道竞争 |
| R-035 | 随机控制分组判分 | `APPROVED` | Validation Agent | 漏斗 v1 §10.4:漏斗自身需可证伪 | 同池分层抽样(市值分位×行业,与主通道分布对齐)+ 固定 seed + 抽样框完整留痕;U1/U2 与 U3 两层检验分开;判据预注册不可改 |
| R-036 | 全市场 E1 事件层 | `APPROVED` | Data Agent | 漏斗 v1 Phase 1;**取代 R-007** | 红旗闸门从逐票 14 只扩到全 A 批量口径,最廉价且最高价值 |
| R-039 | 簇可变性校验 | `APPROVED` | Claude | C5 §2/§3/§7:未记录未批准的拆分合并双向禁止;三分类以 object_hash 判定 | 按 C5 §2.2 以 object_hash 三分类;genesis 仅限 P1新登记/P2批准manifest/P3冻结输入补齐(仅S0)三条路径,其余 null→值 与 值→null 一律 rewrite;directional_call 为纯派生(f(fund_structure,relative_strength,setup_type))恒 no-op;§2.4 台账须含 cluster_id 与 split_born 并收录迁移新生簇;§3.1 新 cluster_id ⟺ level 4 且机制登记+approval_ref;**§0.4 批准有效性(通道/绑定/时序/失败处置)—— 不实现这条,genesis 侧只会做存在性检查,P1/P2 批准可自签**;§0.2 基准集(flock + git blob 取 B);对键含 field 的有效 R-040 记录放行 |
| R-040 | cluster_migration 事件账本 | `APPROVED` | Claude | C5 §4:S0 由世界时钟 outcome_first_bar_settled 判定(非窗口关闭、非账本是否为空);S2 由「是否出现在已登记快照中」判定 | append-only;field_changes[] 每项带 signal_id、簇字段取 object_hash;evidence as_of ≤ registered_at(同日须带可核验盘中时间戳;锚点取 min(timestamp, 首次 git 出现日),相差>0 标 backdated 不计门槛);批准须 Junyan 个人密钥签名或会话原文粘贴(GitHub 评论仅辅助留痕——agent 用 owner 凭证驱动 gh,author_identity 只证明凭证被使用);单次使用 + 未编辑 + approved_at>requested_at;操作=一条记录禁净额抵消;拆分产生簇标 split_born 在有前瞻成员前不计数;合并须留 merged_from[] 且观测取等权平均;**状态机 selftest:D 日收盘后按生产写手默认字段登记的信号,在 D 日内必须判为 S0(此即四轮 BLOCKER-A 的回归测试)** |
| R-041 | publication snapshot | `APPROVED` | Claude+Validation Agent | C5 修正规则3:已公布结论的唯一事实源,防"先公布保守结论再重新归簇解锁"的 p-hacking | 统计量与快照同代码路径,快照失败即拒绝渲染统计量;canonical 哈希+链+双向 selftest;完整性 CI(快照集合==当时 scored 集合);已发布产物补 reconstructed 快照(允许 cluster_map_status=PRE_GENESIS,须早于 R-038);补登记须追溯作废 published_at→补登记 之间影响该批 signal_ids 的 migration;更正走 supersedes |
| R-042 | 停止把 intraday 写进 horizon | `PROPOSED` | Claude | `execution_tracker.py:237` 硬编码 `["intraday","1d","3d","5d","10d"]`,而 `run_post_close_report.HORIZON_DAYS` 无 intraday、backfill 永不回填它;该装饰标签曾令 C5 四版的 S0 判据把计数锁死为 0 | **非前置**:C5 §4.1 已声明 intraday 惰性,零迁移;不得改成"先让代码停止写"——§2.3 冻结 horizon,已登记 108 行无法在不逐条走 §4 批准的情况下合法剥离 |

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
