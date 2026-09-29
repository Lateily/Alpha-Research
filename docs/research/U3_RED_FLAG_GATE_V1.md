# U3 红旗闸门 v1：与 E1 事件层共用一套判定函数

日期：2026-09-29。来源：2026-09-25 复审 P1 #2 / #3。

## 为什么改

`experiments/execution_tracker/red_flag_gate.py` 的 `check_ticker` 供三处使用：
`full_battery` 的 基本面 维度 → 漏斗 U3 → `u4_pre_decision`，以及每晚发布的
`red_flags.json` / `battery.json`。v0 另写了一套规则，和全市场 E1 事件层
（`experiments/research_funnel/e1_event_layer.py`，R036_E1_RULES_V1）不一致：

1. 快报 `yoy_net_profit` 是「上年同期净利润金额（元）」，v0 当成同比百分比读，
   产生了「最新快报净利同比-19264400%」这类文本。
2. 预告/快报从不被已披露的正式财报取代；`latest_e1_date` 不看财报。
3. 归母净利为 NaN 时比较结果为 False，静默 PASS；空值预告/快报行也算证据；
   季度推算按行位置取差，不检查季度是否相邻。

9/24 包有 39 行 U3 RED_FLAG，9/29 包有 46 行，同一晚的 E1 层对这些行全部判
NO_RED_FLAG_FOUND。

## v1 做了什么

`check_ticker` 只负责取数（forecast / express / income，窗口为 as_of 往前 800 天，
截止 as_of，字段与批量层 `*_FIELDS` 相同），判定全部交给 `e1_event_layer.classify_ticker`。
批量 E1 层用的也是同一组函数：**相同的输入行必得相同的判定**。

但两边的取数窗口不同，输入本身可能不同，所以不能说「两道闸门不会漂移」：

| | U3（本闸门） | 批量 E1 层 |
|---|---|---|
| 预告/快报 | 按公告日回看 800 天，含 as_of 之后报告期的预告（如 9/15 发布的 Q3 首亏预告） | 只取 `_recent_periods(as_of, 4)` 四个报告期，看不到 as_of 之后报告期 |
| 财报 | 回看 800 天 | 同样四个报告期；1–4 月里未报年报的公司常因缺前一季累计值而 `INSUFFICIENT_FILED_QUARTER_HISTORY` |

测试 `ProductionWindowTests` 用两边的真实窗口并排跑：规则决定结果的场景（停报、同期取代、
季度恶化）两边一致；「as_of 之后报告期的预告」这一差异被显式钉住，是有意的，不是静默漂移。

共用规则（两道闸门同时生效）：

| 规则 | 内容 |
|---|---|
| 事件选择 | 公告日晚于 as_of 的行一律忽略；每个报告期取最新公告（同日并列按整行哈希，不看到达顺序） |
| 取代 | 同期或更晚报告期的正式财报已披露 → 该期预告/快报记为 SUPERSEDED，不再判红旗 |
| 逐期判定 | 最新已披露期之后的**每一个**报告期都是 active，逐期判定，任一期负面即红旗（晚一期的预增不能掩盖更早一期未披露的首亏） |
| 新鲜度 | 最新已披露期早于「法定截止日严格早于 as_of 的最近一期」（Q1 4/30、H1 8/31、Q3 10/31、年报次年 4/30）→ `FILED_PERIOD_STALE`，DATA_BLOCKED；不拿一年前的季度判 PASS |
| 同期多份财报 | 最新公告日优先；同日时有值优先于空值，再看 `update_flag=1`，最后按整行哈希 |
| 快报同比 | 优先 `yoy_dedu_np`；否则按 `(n_income - yoy_net_profit)/abs(yoy_net_profit)` 计算 |
| 季度规则 | 锚定最新已披露期 L 与日历相邻的上一季；L 或所需前期归母为空 → `INCOME_VALUE_MISSING`；缺期 → `INSUFFICIENT_FILED_QUARTER_HISTORY`；不再退回更旧的一对季度 |
| 空值证据 | 快报三项全空 → `EXPRESS_YOY_METRIC_MISSING`；预告既无类型也无上限 → `FORECAST_GUIDANCE_UNSCORABLE` |
| 取数失败 | income 失败 → `INCOME_SOURCE_UNAVAILABLE`（无法判断是否已被取代），但仍取预告/快报，把未经确认的负面预告/快报以「未确认负面预告[类型]期末…」放在理由最前（电池只留前 60 字）；forecast/express 失败 → 除非已有核实的红旗，否则 `E1_SOURCE_PARTIAL`；已核实的红旗在来源不完整时仍成立，理由末尾追加 `E1_SOURCE_PARTIAL:…`（不带三个前缀，前缀解析器不受影响） |

以上阻断类情况一律输出 DATA_BLOCKED，不输出 PASS。

## 输出兼容

- `verdict` 仍为 `PASS | RED_FLAG | DATA_BLOCKED`；E1 的 `NO_RED_FLAG_FOUND` 映射为 `PASS`。
- `reasons` 仍是字符串列表。RED_FLAG 文本保留原前缀 `最新预告` / `最新快报净利同比` /
  `最近季度归母`（分歧队列和信任线按前缀归类），末尾加 `[code=<代码>]`。
  DATA_BLOCKED 文本以代码开头（电池只保留前 60 个字符）。
- `latest_e1_date` 现在包含最新一份已读财报的公告日。
- 新增字段：`reason_codes`（封闭代码，按字母排序）、`evidence_coverage`（与 E1 行一致）、
  `latest_filed_period`、`latest_due_period`、`active_periods`、`rule_version`；income 失败时
  另有 `unconfirmed_negative_evidence`。
- `red_flags.json` 的 `"gate"` 字段仍写 `red_flag_gate_v0`：promoter QC 等消费者按这个字面值识别戳，
  版本看同一戳里的 `gate_version` / `rule_version`。`full_battery.py` 未改动，所以电池的 基本面
  仍只带 `红旗闸门` / `红旗理由` / `最新E1日期`。

## E1 层自身的变化（同一套函数，所以一并生效）

- 归母为空的已披露期会被保留：它仍能取代旧预告，季度规则会看到这个空洞。
  以前这一期被丢掉，规则会悄悄改看更旧的季度。
- 季度对必须日历相邻。以批量层 4 个报告期的窗口，这只影响少数
  「最新期为空」或「中间缺期」的行，这些行从 RED_FLAG / NO_RED_FLAG_FOUND 变为 DATA_BLOCKED。
- 新增阻断代码 `INCOME_VALUE_MISSING`、`FORECAST_GUIDANCE_UNSCORABLE`、`FILED_PERIOD_STALE`。
  schema 的 `reason_codes` 本来就是开放字符串数组，`evidence_coverage` 的取值集合不变。
- 预告/快报从「每票一行」改为「最新已披露期之后每期各一行」逐期判定。
- `evidence_coverage.forecast = PRESENT` 表示至少读到一期 active 预告；不可评分的 active 预告
  仍记 PRESENT（该枚举没有 DATA_BLOCKED，改枚举要动 schema），可评分与否看
  `FORECAST_GUIDANCE_UNSCORABLE` 代码。`coverage.forecast_active_rows` 同理。
- `RULE_VERSION` 仍是 `R036_E1_RULES_V1`（schema 固定为常量）。为让修订前后的产物可区分，新增
  机读标记 `policy.rule_revision = "R036_E1_RULES_V1+shared_u3.2026-09-29"`（schema 的 policy
  只约束为 object），U3 的 `rule_version` 也改为 `red_flag_gate_v1/shared:R036_E1_RULES_V1+shared_u3.2026-09-29`。
  分歧队列的 staleness_rule_version、信任线的 20 晚滚动窗口应按这个修订号分段。
  升 V1.1 schema 由人决定，建议与 #386（同样改 schema 与 E1 语义）一起只升一次。

## 对 9/24、9/29 包的预期（规则层估算，不是重算）

逐票重算需要实时调用 Tushare（per-ticker forecast/express/income），本 PR 不联网，
所以只根据归档包里的 `红旗理由` 和同晚 E1 数据做规则层估算：

| 包 | U3 RED_FLAG | 预计失去红旗 | 预计保留 |
|---|---|---|---|
| 9/24 `20260924_203004_…_21f2fe2b` | 39 | 38 | 1（688512.SH，仅凭季度规则） |
| 9/29 `20260929_150751_…_8713c722` | 46 | 46 | 0 |
| 9/29 `20260929_203005_…_5271b90b` | 46 | 46 | 0 |

失去红旗的行预计为 PASS（同晚 E1 对这些票的 income 覆盖都是 COMPLETE）。
如果单票数据出现空值或断档，会变成 DATA_BLOCKED，不会变成 PASS。

补充（复审修正后，仍只用归档数据）：

- 归档包里这些 RED_FLAG 的理由没有一条引用 20260630 之后的报告期，所以「逐期判定」
  不会让它们重新亮旗。
- 按归档的 9/29 E1 层，有 5 个票在批量窗口里最新财报只到 Q1-2026（`latest_e1_date`
  为 4/28–4/30，只有 2 个可算季度），即 H1-2026 在批量数据里缺失：9/24 的 688512.SH
  （原估算里唯一保留红旗的那行），以及 9/29 的 688211.SH、688458.SH、688711.SH、688785.SH。
  它们要么确实没报 H1（v1 下为 `FILED_PERIOD_STALE`，DATA_BLOCKED；688512.SH 因而不再靠
  季度规则保留红旗），要么只是被 income_vip 9000 行截断丢了（#386 修的问题，单票取数能看到
  H1 → 按 H1 判定）。离线无法区分，所以 9/29 的 46 行里最多 4 行会是 DATA_BLOCKED 而不是
  PASS，9/24 的 688512.SH 是 RED_FLAG 或 DATA_BLOCKED，都不会是 PASS。

## 与其他在途 PR 的重叠

- #386（fix/v1-e1-tushare-paging）：`e1_event_layer.py` 语义冲突（`_classify_row` 裁决阶梯、
  `evidence_coverage`、schema）。建议合并顺序：#386 先合，本 PR 再 rebase，把
  `income_gaps`（截止日缺期）放进共用的 `_classify_evidence`，由 as_of 在两条路径上各自算出，
  并在 `ProductionWindowTests` 里加截止日缺期场景；若本 PR 先合，#386 需在
  `_classify_evidence` 内算缺期，而不是只在 `build_event_layer` 里算。本 PR 的
  `FILED_PERIOD_STALE` 与 #386 的截止日表同源（法定截止日），rebase 时统一用一张表。
- #386、#391、#392：`scripts/governance_mutation_gate.py` 末尾追加的 MUTATIONS 块文本冲突。
  后合并者两块都保留，并在合并后的树上跑 `tests/test_governance_mutation_gate.py`。
- #393（分歧队列/信任线）：按前缀解析 `红旗理由`，干净合并；v1 文本仍按 `期末YYYYMMDD`
  取预告期、按前缀归类快报/季度；新增的 `E1_SOURCE_PARTIAL:` 注记解析为 unparsed，不影响 ACTIVE 判定。
- #385：干净合并。

不是买卖指令；研究信号，human executes。
