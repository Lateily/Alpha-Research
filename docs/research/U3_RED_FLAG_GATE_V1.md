# U3 红旗闸门 v1：与 E1 事件层共用一套规则

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
截止 as_of），判定全部交给 `e1_event_layer.classify_ticker`。批量 E1 层用的也是同一组
函数，两道闸门不会再各自漂移。

共用规则（两道闸门同时生效）：

| 规则 | 内容 |
|---|---|
| 事件选择 | 先取最新报告期，再取最新公告日；公告日晚于 as_of 的行一律忽略 |
| 取代 | 同期或更晚报告期的正式财报已披露 → 预告/快报记为 SUPERSEDED，不再判红旗 |
| 快报同比 | 优先 `yoy_dedu_np`；否则按 `(n_income - yoy_net_profit)/abs(yoy_net_profit)` 计算 |
| 季度规则 | 锚定最新已披露期 L 与日历相邻的上一季；L 或所需前期归母为空 → `INCOME_VALUE_MISSING`；缺期 → `INSUFFICIENT_FILED_QUARTER_HISTORY`；不再退回更旧的一对季度 |
| 空值证据 | 快报三项全空 → `EXPRESS_YOY_METRIC_MISSING`；预告既无类型也无上限 → `FORECAST_GUIDANCE_UNSCORABLE` |
| 取数失败 | income 失败 → `INCOME_SOURCE_UNAVAILABLE`（无法判断是否已被取代）；forecast/express 失败 → 除非已有核实的红旗，否则 `E1_SOURCE_PARTIAL` |

以上阻断类情况一律输出 DATA_BLOCKED，不输出 PASS。

## 输出兼容

- `verdict` 仍为 `PASS | RED_FLAG | DATA_BLOCKED`；E1 的 `NO_RED_FLAG_FOUND` 映射为 `PASS`。
- `reasons` 仍是字符串列表。RED_FLAG 文本保留原前缀 `最新预告` / `最新快报净利同比` /
  `最近季度归母`（分歧队列和信任线按前缀归类），末尾加 `[code=<代码>]`。
  DATA_BLOCKED 文本以代码开头（电池只保留前 60 个字符）。
- `latest_e1_date` 现在包含最新一份已读财报的公告日。
- 新增字段：`reason_codes`（封闭代码，按字母排序）、`evidence_coverage`（与 E1 行一致）、
  `latest_filed_period`、`rule_version`。`full_battery.py` 未改动，所以电池的 基本面
  仍只带 `红旗闸门` / `红旗理由` / `最新E1日期`。

## E1 层自身的变化（同一套函数，所以一并生效）

- 归母为空的已披露期会被保留：它仍能取代旧预告，季度规则会看到这个空洞。
  以前这一期被丢掉，规则会悄悄改看更旧的季度。
- 季度对必须日历相邻。以批量层 4 个报告期的窗口，这只影响少数
  「最新期为空」或「中间缺期」的行，这些行从 RED_FLAG / NO_RED_FLAG_FOUND 变为 DATA_BLOCKED。
- 新增阻断代码 `INCOME_VALUE_MISSING`、`FORECAST_GUIDANCE_UNSCORABLE`。
  schema 的 `reason_codes` 本来就是开放字符串数组，`evidence_coverage` 的取值集合不变。
- `RULE_VERSION` 仍是 `R036_E1_RULES_V1`（schema 固定为常量）。是否升版由人决定。

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

不是买卖指令；研究信号，human executes。
