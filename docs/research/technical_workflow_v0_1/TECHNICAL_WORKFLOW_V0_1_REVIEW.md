# U4 后技术策略工作流与工作台接入规格 v0.1

日期：2026-10-10（Europe/London）。

状态：`SPEC_CANDIDATE_AWAITING_HUMAN_REVIEW`。

本文冻结的是一份供审阅的规格候选，不是已批准的方法、已实现的引擎、
生产部署或 paper 登记。数字约定均为 `[unvalidated intuition]`，不是有效性结论。
首版按已收盘日线设计；15 分钟等盘中周期另设版本和验收，不混用证据。
人类审定本文件的确切 SHA256 后，才能把相应规则标记为方法规约已批准。

## 1. 目标与成功标准

目标是把 U4 获准深研对象的技术判断做成可独立运行、可重放、可人工核验的工作流，
并由现有工作台承接冻结输入、任务状态、图表、策略卡和本地核验记录。

首轮交付成功须同时满足：

1. 冻结输入能独立运行，不要求整条夜链当场重新执行成功。
2. 同一输入、规约和截止点，生成相同的确定性策略卡与引用。
3. 每个结构点、确认时间和价位推导能在原始价量中回查。
4. 缺数、形态未成立、形态已失效都产生可读结果，不凑策略。
5. 工作台能提交有界离线任务、查看产物、记录具名核验及下载回执。
6. 未取得独立授权时，U4、正式 case、paper 与生产数据均不被写入。

不在本次范围：实时采集、全市场自动轮动裁决、训练或微调模型、付费模型调用、
TradingView 作为权威行情来源、自动 paper 注册、真实交易，以及方法有效性声称。
旧规则、历史决定、旧研究包、旧 paper 结果不因本任务追溯升级。

## 2. 已核对的基线与复用边界

只读参考的本机 `origin/main` 与生产安装版本为：
`333632910357baddcfbd9137ad5f01d666b9a912`。
这是本机已有引用，不代表本次进行了远端 fetch。

工程入口当前在 `codex/news-flash-shadow`，HEAD 为
`ab7b1f948a7e59979aca87acff02f49f2a6aa2be`；doctor 提示 `BEHIND_ORIGIN_MAIN`。
本规格保存在运行说明目录，不修改这个旧分支。实现时必须建立基于届时最新 main
的隔离任务检出，不能在旧分支或 ar-live 中开发。

| 现有模块 | 真实能力 | 本次如何复用 |
| --- | --- | --- |
| `full_battery.py` | 技术面为均线和量能，并声明 SMC 未接 | 作为输入证据；不把其 COMPLETE 当作 SMC 合格 |
| `smc_annotation.py` | 固定人工标注规约与一致性比较 | 复用 pivot、sweep、reclaim 的已有约定；不改变旧标注语义 |
| `research_method.py` | 要求 `manual-smc-v1` 与人工 settled E3 身份，验证绑定与价位 | 保留原合同；机器策略卡不能冒用人工身份或 PASS |
| `research_cycle.py` / registration bridge | case、时间、批准及计划绑定 | 后续通过单独的人类材料转换步骤使用，不直接写入 |
| `model_paper_fund.py` / 五轴模块 | 模拟执行与复盘 | 后续复用现有引擎，不另写一套成交或归因逻辑 |
| `workbench_workspace.py` | 固定 job kind、幂等命令、本地事件与回执 | 增加独立离线任务类型，不新增任意 shell/API 入口 |

## 3. 运行顺序与权限

```text
冻结输入包与逐文件 hash
  -> 输入、时点、公司身份和 U4 绑定校验
  -> 日线结构计算
  -> setup 与失效状态计算
  -> 引用绑定的价位提案与背景校验
  -> 策略卡 JSON + 一页报告 + 图表标记 + 核验模板
  -> 人类核验记录（独立工件，不改原策略卡）
  -> 另行封存 case / 另行批准确切 paper 计划
```

机器产物固定携带：
`sample_purpose=WORKFLOW_DEBUG`、`claim_allowed=false`、`no_trade_flag=true`，
以及 `production_authority/u4_authority/paper_registration_authority/trade_authority=false`。

模式只有：

- `HISTORICAL_REPLAY`：已曝光材料仅用于工程与规则解释；不能升级为前瞻样本。
- `PROSPECTIVE_RESEARCH`：截止前冻结并绑定可信 U4 SELECT；仍只是待核验研究提案。

Thesis 或估值尚未封存，不阻止独立观察技术结构，但必须显示其缺件，
`registration_readiness` 保持 `NOT_AUTHORIZED`。不得把技术结构当作公司价值证明。

## 4. 冻结输入合同

操作员配置输入根；浏览器只选择已登记的 `pack_id`，不传任意路径、URL 或股票代码。
操作员的可信登记表另存 `pack_id -> request_hash/source_manifest_hash/规则版本/使用模式`，
登记值不能取自本轮请求自报，也不能由浏览器修改。重开输入时同时比对这个外部绑定，
因此攻击者改来源再重封整个包也不能改变同一个已登记输入的含义。
未登记包可作为新输入提交审阅，不能自动成为旧包的修订或获准前瞻来源。
包布局候选：

```text
technical-pack/
  request.json
  source-manifest.json
  inputs/bars.json
  inputs/trade-calendar.json
  inputs/corporate-actions.json
  inputs/settled-flow.json
  inputs/sector-context.json
  inputs/research-binding.json
  SHA256SUMS
```

`request` 字段必须包含：
`schema_version/workflow_version/rule_profile_hash/mode/pack_id/ts_code/industry_key/`
`as_of/data_cutoff/generated_at/window_id/exposure_status/source_manifest_hash`。
时刻必须带时区；市场日界按 Asia/Shanghai 解释，不使用主机时区猜测收盘。

来源清单逐文件记录：相对路径、原始来源、SHA256、公司或行业身份、证据层级、
原始发布时间、实际可用时间、捕获时间、价格及成交量单位、许可/展示范围。
捕获时间不能替代发布时间。重封 hash 不能使晚于 cutoff 的事实成为合法输入。
有 schema 外字段、重复 JSON 键、NaN/Infinity、路径越界、链接逃逸或 hash 不符时拒绝。

价量逐行至少有：`ts_code/trade_date/bar_close_at/available_at/open/high/low/close/`
`volume/amount/price_basis/currency`。数值有限，OHLC 自洽，日期严格递增且唯一。
仅接收已收盘、截止点前已可用的日线；`volume` 归一为股数，`amount` 归一为 CNY，
原单位与转换保留引用。停牌记录须明确存在，不能把无成交日补成普通 bar。

交易日历必须有版本、来源 hash 和覆盖范围。未知缺日、未核验停牌、
不明复权或公司行动断链 -> `DATA_BLOCKED`，不通过插值或旧值补齐。
本候选计算轮只接受影响计算区间的公司行动已核验且无价格基准断裂的 raw bars；
带公司行动的复权映射支持另行实现，当前不得静默混用 raw 与 adjusted。

前瞻 U4 绑定必须指向确切 packet hash、SELECT 决策行 hash、公司、行业、
`cohort_id/causal_cluster_id/method_version`；重开原证据核对，不能仅信自报。
历史回放允许无 SELECT，但状态必须为 `HISTORICAL_NO_U4_AUTHORITY`。
行业身份不得由 case 草稿自报替代 U4 队列中的身份。
`research-binding.json` 还需引用截止点适用的现有 E1/U3 红旗检查，包含日期、
verdict、理由和 source_refs；未知覆盖与旧日结果不能被当作当前“无红旗”。
本工作流不重写红旗分类器；活跃红旗保留阻断，技术形态不能将其抵消。

## 5. Reed 板块轮动固定接口

输入是具名的讨论材料，不是自动裁决器。`sector-context.json` 包含：

| 字段组 | 必需内容 |
| --- | --- |
| 身份 | `schema_version/context_id/industry_key/as_of/data_cutoff` |
| 证据 | `source_refs`：板块资金、价量、广度、事件等逐项引用及日期 |
| 人类判断 | `market_state/sector_state/rationale/counter_evidence` |
| 人类来源 | `authored_by/authored_at/review_status/reviewed_by/reviewed_at` |
| 演化 | `invalidation_conditions/supersedes/context_hash` |
| 边界 | `is_human_judgment=true/automated_decision=false/claim_allowed=false` |

`market_state`：`RISK_ON/WEAK_REPAIR/RISK_OFF/STYLE_ROTATION/UNKNOWN`。
`sector_state`：`CONFIRMED/NOT_CONFIRMED/ADVERSE/UNKNOWN`。
`review_status`：`PENDING/REVIEWED/DISPUTED`。
`REVIEWED` 只表示有人核验此材料，不能赋予 U4 或 paper 权限；具名文字本身不是认证。

适用公司必须通过来源可追的行业映射绑定，不能把“半导体看好”贴到任意公司。
不同时点、未知行业、无来源、未核验、争议或过期背景不能变成 CONFIRMED。
首个 profile 的背景确认要求市场不为 RISK_OFF/UNKNOWN、板块为 CONFIRMED，
且具名核验记录已存在并绑定同一 context hash。事后核验可以附在新回执里，
不能回填旧 cutoff 的背景已确认状态。
缺背景时可以展示已计算的技术结构，但背景为 `DATA_BLOCKED`，最终提案不得升级。
背景有新讨论时新增版本，用 `supersedes` 指向旧版；旧卡继续绑定旧判断。
不得用一个复合分数抵消 E1 红旗、缺数或不利背景。

## 6. 方法目录与首个执行 profile

SMC/ICT 名称不是统一的自然定律。本系统必须为采用的每个概念列出自己的定义、
确认时刻、参数、反例和实现状态；技术形态不能证明真实机构身份。

目录保留：市场结构 HH/HL/LH/LL、BOS/CHoCH/MSS、等高等低、liquidity sweep、
premium/discount、FVG/IFVG、order block/mitigation/breaker、OTE、inducement、
session/killzone、SMT 与流动性目标。每项显示 `PROPOSED/IMPLEMENTED/TESTED/`
`NOT_IMPLEMENTED/UNSUPPORTED_TIMEFRAME`，不得用完整目录冒充完整策略引擎。

首个 profile 候选：`DAILY_SWEEP_RECLAIM_CANDIDATE_0_1`，A 股、日线、仅多头 paper 提案。
只开启已有标注约定能明确描述的 sweep/reclaim；其余概念不参与首轮候选判断。
此处是实施排序，不是删除其余 SMC/ICT 功能范围。

| 参数 | 候选约定 | 来由与审批性质 |
| --- | --- | --- |
| 有效历史 | 至少 60 根已收盘有成交日线；完整输入区间纳入 hash | 工程候选；不代表最优 lookback |
| Pivot | 严格低于左右各 2 根；相等不算 | 复用标注规约，不据收益选优 |
| 确认时间 | pivot 后第 2 根收盘，且该 bar 已可用 | 复用无前视约定 |
| Sweep | low 至少低于参考低点 1 个 tick | tick 从品种规则取；首 profile 仅支持 0.01 CNY |
| Reclaim | sweep 当根至随后第 3 根，首个 close >= 参考低点 | 复用标注规约，共最多 4 根 |
| 事件搜索 | 冻结窗口内第一个合法事件，不为 2:1 改挑后面的事件 | 复用 first-event 纪律 |
| ATR | 14 根 true range 的 Wilder 递推；首值取首 14 个 TR 均值 | 明确算法约定，未验证有效性 |
| 止损缓冲 | 0.25 × reclaim 时已知 ATR14 | 新工程候选，必须单列人类审定 |
| 量能背景 | 最近 5 根均量 >= 最近 60 根均量 | 新工程候选；不作为 U4 选股总分 |
| 资金背景 | 最近 2 个有效交易日 settled 主力净流合计 > 0 | 新工程候选；缺任一日不视为中性 |

所有窗口依截止点计算，未来新增 bar 不得改变过去事件当时的识别结果。
展示“后来失效”必须作为后续事件，不能删除曾发生的 setup。
已有曝光的 9 个窗口仅作演示，不能用于挑选这些参数或作干净测试集。

## 7. 结构、价位与状态推导

参考低点只取 sweep 前一个收盘点已确认的最近 strict pivot。
该点确认后、sweep 之前已被穿过时，参考点失效，不回捞更旧点以寻找漂亮形态。
确认字段同时记录 `pivot_date/confirmed_at/available_at`。

到 cutoff 未 reclaim：窗口未满为 `WAIT`，窗口已满为 `NO_SETUP`。
Reclaim 后首次收盘低于 sweep.low：`INVALIDATED`，保留原确认与失效日期。

策略价位候选只在证据齐全且 reclaim 存在时计算，锚在 reclaim 时可用的证据上：

- `entry_reference`：reclaim bar 的 high 加一个 tick，向上取整到 tick。
- `structure_invalidation`：sweep.low；这是技术失效线，不是 thesis 证伪条件。
- `stop_reference`：sweep.low - 0.25 × 当时 ATR14，向下取整到 tick。
- `target_1`：reclaim 前已确认、当时尚未被穿越、且高于 entry 的 pivot high 中价位最低者。
- `target_2`：符合相同条件、严格高于 target_1 的下一档价位；不存在时为 null 加原因。
- Pivot high 为 strict 左右各 2 根的高点；目标同样不能使用尚未确认的高点。

目标或上下文不足时显示 WAIT/缺件，不能用价值带、固定百分比或后续行情补出技术目标。
`entry < target_1`、`stop < entry` 必须成立，否则 `WAIT` 并显示具体原因。
计划毛 R/R 按 `(target_1-entry)/(entry-stop)` 派生；现有 2:1 门保留。
不能为满足它而移动结构线；成本后 R/R 另列，缺费用/滑点口径时为 null 加原因。
本 profile 不改变旧 paper 成本、T+1、涨跌停、参与率和持仓政策。

必须单独计算 `entry_trigger_seen_at/target_seen_at/structure_invalidated_at`。
Reclaim 之后、截止点之前若已触及计划入场参考或目标，仍保留历史结构，
但当前前瞻提案为 `WAIT`，原因分别为 `ENTRY_ALREADY_TRIGGERED_BEFORE_PLAN`
或 `TARGET_ALREADY_REACHED_BEFORE_PLAN`。不能假装在旧时刻登记或成交。
已有观察信号日后转换为正式计划，还须在封案时重新核验有效窗口及最新合法证据。
已登记订单的判断则交原执行引擎，不由本模块改写。
同一根日线内多个价格条件的先后未知时记录 `INTRABAR_ORDER_UNKNOWN`，
本模块不编造分钟路径、成交结果或新的注册资格。

价位、形态、确认和最新状态分开记录：

| 状态 | 含义 |
| --- | --- |
| `TECHNICAL_REVIEW_CANDIDATE` | 形态、未触发窗口与背景符合规约，毛 R/R 过门，无活跃红旗；仍需人工核验，不是 PASS |
| `WAIT` | 有结构或有待确认条件，但尚不符合规约；必须有 wait 条件 |
| `NO_SETUP` | 本窗口按冻结规则没有合格 setup，或 reclaim 已超时 |
| `INVALIDATED` | 记录中的 setup 后来触发明确结构失效 |
| `DATA_BLOCKED` | 必需证据缺失、未知或不兼容 |
| `REFUSED` | 输入篡改、身份/批准越权、非法路径或合同不合法 |

结构结果和上下文结果各自显示；资金/行业未确认不能抹掉已观察到的价格事件。
计算入口须重新派生字段，既不信输入自带 verdict，也不信输入自带价位。
新策略卡与人工 SMC 合同保持不同 schema；不自动把候选转换成 manual-smc-v1/PASS。

## 8. 输出合同

每轮输出以下工件。机器核心在固定 generated_at 下须逐字节可重放：

| 工件 | 内容 |
| --- | --- |
| `strategy-card.json` | 规则、输入、绑定、事件、价位、状态和各自原因的确定性核心 |
| `technical-report.md` | 一页人话说明，原始引用、最弱依据、反证与等待条件 |
| `chart-annotations.json` | bar ID、pivot 确认时刻、区域/价位及事件，不包含窗口外行情 |
| `human-review-template.json` | PENDING 空模板，无预写 PASS、签署人或核验结论 |
| `receipt.json` | 输入与输出 hash、实际代码版本、命令、阶段状态和权限边界 |
| `SHA256SUMS` | 文件字节 hash，包含引用到的冻结来源副本 |

核心策略卡字段组：

1. `identity`：schema/workflow/profile 版本及 hash、代码 SHA、mode、ts_code、industry_key。
2. `binding`：input manifest、cutoff、window、U4 行/packet、research case 与背景 hash。
3. `quality`：逐项覆盖、缺失、矛盾、模块实现状态、曝光与使用资格。
4. `structure`：已确认 pivot 序列、确认/可用时刻、range 与 source_refs。
5. `setup`：事件 ID、类型、参考/sweep/reclaim/invalidation 日期及引用。
6. `levels`：entry/invalidation/stop/target1/target2/ATR/tick、推导明细、毛及成本后 R/R。
7. `context`：量能、settled flow、市场、板块各自结果与来源，不合成总分。
8. `verdict`：独立技术状态、背景状态、最终 review 状态、reason_codes、wait_conditions。
9. `review`：机器产物固定 PENDING；后续人类核验通过独立 receipt 关联，不改原卡。
10. `authority`：全部关闭的写入/决策权限与 `WORKFLOW_DEBUG/no_trade_flag`。

schema 实现时必须 exact-field 校验嵌套字段，拒绝不认识的字段和重复键。
缺失值用 null 和对应字段的原因表示，不用 0、“正常”或旧日期代替。
时点、公司和行业绑定须重开引用核对，hash 不是证据真实或质量合格的证明。

deterministic payload 不含绝对机器路径、墙钟运行耗时、模型自由文本或随机 ID。
复用 `research_workflows.evidence.canonical` 的稳定 JSON 编码；价位计算使用 Decimal
并由合同约定量化到 tick。语义输入 hash 与文件字节 hash 分别命名，不能混比。
task 耗时、提交身份等操作元数据进独立回执，不能改变策略核心 hash。
AI 解释若日后获准接入，要另存模型/提示词/证据版本的解释件，不进入确定性核心。

## 9. 工作台接入合同

新增 job kind 候选 `technical-trial`；第一版仅手动、有界、离线，不进入调度白名单。
复用现有命令 ID、请求 hash、job 状态、本地事件记录和原件重开验证。
请求只含 `command_id/pack_id/request_hash`；不能选择任意命令、路径或源接口。

工作台新增一个“技术策略实验室”功能区，内部用页签组织：

- 输入：冻结日期、行情基准、U4 身份、板块判断、来源与缺件。
- 运行：实际阶段、日志、停止原因；历史回放和前瞻研究醒目标识。
- 策略卡：K 线与结构标记、计算明细、提案/等待条件、原文引用。
- 核验：对同一 card hash 做通过/证据不足/退回记录，不直接写正式批准。
- 对照：同一冻结输入的不同规则版本与历史案例；不合并各版本成绩。

状态语义必须分开：
`job_finished != data_complete != technical_candidate != human_reviewed != paper_approved`。
不同 code SHA、输入 hash 或 run_id 的结果不能拼成一次“完整成功”。
读取回执须重新检查来源和产物 hash；篡改显示 INTEGRITY_ERROR，不能沿用缓存绿色状态。
同 ID 同请求重试返回原件；同 ID 换内容冲突；不同 ID 的输出在独立目录。
超时/崩溃保留部分产物与失败状态，不覆盖旧件；执行器不写正式账本、数据库或 public 指针。

团队访问必须使用已有获准的私有承载与会话边界；当前 localhost 开发令牌不能冒充
团队身份认证。没有该部署验收时只交本机测试入口，不能宣称五人已上线。
本规格不授权购买、上传数据、修改 Tailscale ACL、打开公网、启用模型或切生产。

## 10. 反例矩阵与验收

每项需从真实 CLI/job 入口测试，并为关键守卫增加能因行为断言变红的 mutation pin。
不能只测试内部 helper，也不能靠某个无关门提前拒绝来宣称目标守卫已覆盖。

| ID | 验收问题 | 预期 |
| --- | --- | --- |
| T01 | 同包、同 profile、同 cutoff，两次及跨路径运行 | 核心卡/报告/标记 hash 一致 |
| T02 | 逐根 prefix 重放，加入未来 bar | 历史事件不重绘；只有新确认/失效事件追加 |
| T03 | pivot 右侧确认未到；等低/等高 | 未确认不能成为参考点；相等不算 strict pivot |
| T04 | 改 source 值后重封全包 | 来源绑定/identity/PIT 独立守卫拒绝，不只查 hash |
| T05 | 错股票、行业、U4 行；无 SELECT 的前瞻输入 | REFUSED；历史无 SELECT 不能获得前瞻身份 |
| T06 | 未收盘、未来可用、日历缺口、未知停牌 | DATA_BLOCKED/REFUSED，不回捞旧值 |
| T07 | 公司行动断裂或 raw/adjusted 混用 | DATA_BLOCKED，不计算假 sweep 或假盈亏 |
| T08 | sweep 已失效参考点、reclaim 超时、随后失效 | 正确 WAIT/NO_SETUP/INVALIDATED，保留原事件 |
| T09 | 没有目标、负风险、R/R 不足 | WAIT；不改价位、不跳到另一个 setup 凑 2:1 |
| T10 | 资金缺一天；板块无来源/争议/错时点 | 背景明确缺失，不能变 CONFIRMED |
| T11 | 自带候选标签、PASS、价位、人工核验或生产权限 | 重算或拒绝，绝不采信或写生产 |
| T12 | 已曝光窗口与新独立样本混合发放 | 曝光样本排除干净一致性/前瞻资格 |
| T13 | 同 ID 并发、不同内容重试、逐阶段崩溃 | 原件稳定、冲突显式、无覆盖或重复提交 |
| T14 | 卡正常但 report/图引用被改；旧缓存 | 读取时拒绝，不显示完整成功 |
| T15 | 工作台显示与实际文件状态对照 | 各身份/日期/hash/失败原因一致 |
| T16 | 人类 ACCEPTED_LOCAL 被当作正式 SMC/批准 | 拒绝；第二道人类闸门仍独立 |
| T17 | 盘中 bar/session/killzone 混入日线 profile | UNSUPPORTED_TIMEFRAME，不按日线猜测 |
| T18 | 旧形态在截止前已触及入场/目标；事后追加人工核验 | 保留历史事件但当前 WAIT；不回填登记/核验时刻 |
| T19 | E1 红旗、无当前覆盖或错公司检查，叠加强技术形态 | 红旗/缺数阻断保留，不能产生可升级提案 |

Python 新测试必须同 PR 登记 `python-ci.yml`，完整离线套件通过后才开 Draft。
完整 mutation gate 与 CI 均须针对同一最终 HEAD；改代码后旧 PASS 作废。
本规格阶段未运行这些行为测试，表格不是通过回执。

## 11. 实施切片与下一道闸门

规格审定后按依赖推进，每片一个独立可审 PR：

1. 来源/时点/U4/行业/板块输入合同与失败回执，配正常、缺失、矛盾和历史样本。
2. 日线 sweep/reclaim 确定性计算、价位提案、可读报告与 prefix 防前视测试。
3. 工作台 `technical-trial` 离线 job、策略卡/图表/核验/对照页面和幂等验收。
4. 同版本完整隔离验收；通过后另行提出私有部署授权，不直接改旧生产。
5. 将具名人工核验转换为现有 manual SMC/case 材料，再单独批准确切 paper 计划。

不混入宏观修复、实时新闻、轮动自动裁决、多模型训练或旧订单迁移。
后续扩展 BOS/CHoCH/FVG/OB 等，每项先有定义和反例，再进入 challenger 版本。
盘中版本必须独立明确：合法分钟数据、可用时间、交易时段/休市、成交约束、
延迟/丢帧、重连去重、时区、同根 bar 内顺序不可知，以及与日线版本的隔离。

当前下一闸门：审阅日线范围、候选参数、Reed 背景接口和机器/人工合同边界。
审定并记录本规格完整 hash 后，再写实施计划并选择执行方式。
没有新的 human approval 时，所有新策略卡与试验都是未批准的 WORKFLOW_DEBUG 提案。

不是买卖指令；研究信号，human executes。
