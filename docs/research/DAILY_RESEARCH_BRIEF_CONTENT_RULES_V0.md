# 每日研究简报内容规则 V0

状态：`DRAFT_NONPRODUCTION / WORKFLOW_DEBUG / INPUT_CONTRACT_UNCHANGED`

本规则约束每日研究简报中的研究语言、证据引用和人工质检。它向 Jason 提出字段需求，向 Better 提供可读版式样稿，但**不直接修改工程输入合同**。字段能否进入正式 Schema，由 Jason 的独立工程任务、测试和评审决定。

AI 可以整理草稿和指出缺口，**AI 草稿不得标成人工通过**。本规则不授予 U4 选择、研究封存、paper 注册、生产发布或真实交易权限。

## 1. 每句话先分类

| 标签 | 可以怎样写 | 最低证据 | 禁止写法 |
| --- | --- | --- | --- |
| `FACT` | “冻结工件显示沪深 300 当日收跌 1.2%。” | 同一 `run_id`、来源日期、数据截止时间、原始字段路径和 `source_sha256` | 来源缺失、日期错位或用旧 run 补今天 |
| `ASSOCIATION` | “组合回撤与半导体指数下跌同时发生。” | 两组同口径、同区间的可重算序列 | “因此指数下跌导致组合回撤” |
| `INFERENCE` | “结合持仓暴露，行业下跌可能解释部分回撤。” | 明示事实前提、推理链、替代解释和待验证点 | 把推断包装成事实，或省略反例 |
| `DATA_BLOCKED` | “缺少当日 Macro 发布，无法判断宏观状态变化。” | 缺失字段、预期来源和阻断原因 | 用 0、旧值、模型猜测或相邻日期代填 |

`UNVERIFIED` 仅用于已出现但尚未核对来源的外部说法。它不能作为事实、组合归因或策略状态变化的依据。

## 2. 什么时候可以说“影响了我们的仓位”

简报中的“仓位”仅指冻结输入绑定的模拟组合。真实资金和真实账户不在本切片范围。

### 2.1 机械影响

只有以下链条全部可重算时，才能标记 `POSITION_IMPACT_CONFIRMED`：

1. 持仓或订单在事件发生前已经存在，并绑定同一组合版本；
2. 证券数量、前后价格、现金、成本和公司行动口径明确；
3. `portfolio_value_delta` 能从冻结字段重新计算；
4. 变化区间、交易日和来源时间一致；
5. 没有把未成交订单当成持仓，也没有把计划价格当成成交价格。

这个标签只证明某项价格、成交或数量变化**机械地进入了组合金额**。它不证明“为什么价格变化”。

任一条件缺失时使用 `POSITION_IMPACT_NOT_ESTABLISHED`，并列出缺口。未持有证券的市场变化可以写进市场事实，但不能写成“影响了我们的仓位”。

### 2.2 因果解释

“某事件导致持仓涨跌”通常只能标记 `INFERENCE`。升级因果措辞至少需要：

- 事件时间早于价格或执行变化；
- 事件与公司、行业或已登记因子存在可审计暴露链；
- 有可比较的市场、行业和个股基准，排除明显共同驱动；
- 有事件前登记的 thesis、催化剂或 `wrong_if`，不是事后补理由；
- 替代解释和证据限制同时展示。

没有这些证据时，只能说“同时发生”“与……一致”或“可能解释”，不能说“导致”“证明”或“市场因为……”。

## 3. 简报逐项内容纪律

### 3.1 标题与身份

必须显示 `run_id`、`target_trade_date`、生成时间、数据截止时间、代码版本和样本用途。最新尝试、最后成功发布和页面当前展示必须分开，不能把失败后的旧成功结果冒充最新结果。

### 3.2 市场变化

每项变化包含：比较基准、数值、单位、区间、来源日期、证据标签和来源链接。行业、指数、宏观和个股不得混成一个无口径“市场上涨/下跌”。

### 3.3 模拟仓、订单与 P&L

分别列示已持仓、待成交、未成交、取消和退出。P&L 要拆分已实现、未实现、现金、费用和总 NAV 变化，并保留计算输入。收益数字不能证明 thesis 正确。

### 3.4 Macro、Funnel 与策略状态

只展示同一运行绑定的状态。`COMPLETE` 的流程状态不等于研究数据质量通过。缺失 Macro、候选电池不完整或红旗存在时，简报必须显示阻断，不能用其他通道抵消。

### 3.5 次日人工核查

只能列“需要核对的问题、证据和截止时间”，不能自动生成真实买卖动作。每个问题要绑定 owner、证据缺口和预期来源。

## 4. 给 Jason 的字段需求

以下是内容层需求，不是已经批准的 Schema。Jason 可调整字段结构，但不得削弱证据、日期和缺数语义。

| 内容对象 | 建议字段 | 用途 |
| --- | --- | --- |
| 简报封套 | `run_id`, `target_trade_date`, `generated_at`, `data_cutoff`, `code_sha`, `sample_purpose` | 防止跨日、跨 run 和生产/调试混淆 |
| 来源 | `source_id`, `source_date`, `source_path`, `source_sha256`, `artifact_sha256`, `quality_status` | 让每个数字能回到冻结原件 |
| 陈述 | `statement_id`, `statement_class`, `text`, `source_refs`, `confidence`, `limitations` | 固定 `FACT/ASSOCIATION/INFERENCE/DATA_BLOCKED` 语义 |
| 市场变化 | `metric`, `scope`, `start_value`, `end_value`, `unit`, `comparison_window` | 防止只给百分比不说明口径 |
| 持仓影响 | `portfolio_id`, `instrument_id`, `quantity`, `price_start`, `price_end`, `cost_delta`, `portfolio_value_delta`, `impact_status` | 重算机械影响，不推断价格原因 |
| 订单 | `order_id`, `order_status`, `planned_price`, `simulated_fill_price`, `filled_quantity`, `reason` | 区分计划、成交和未成交 |
| 运行状态 | `latest_attempt`, `last_successful_publication`, `displayed_run_id`, `blocked_reasons` | 失败不能被旧成功覆盖 |
| 人工质检 | `reviewer`, `reviewed_at`, `item_id`, `verdict`, `source_checked`, `comment` | 保存具名的通过、证据不足或退回意见 |

最低负样本：错交易日、错 `run_id`、来源哈希变化、缺 Macro、未成交订单冒充持仓、旧成功冒充最新尝试、AI 草稿冒充人工通过。上述情况必须拒绝或显式阻断。

## 5. 给 Better 的可读版式样稿

```text
每日研究简报 | 2026-09-XX | WORKFLOW_DEBUG
run_id: ...   数据截止: ...   代码: ...

[运行状态]
最新尝试: FAILED / BLOCKED / COMPLETE
最后成功发布: <独立时间与 run_id>
当前页面展示: <displayed_run_id>

[今天市场发生了什么]
FACT        指数/行业/个股的可重算变化          [查看来源]
ASSOCIATION 与组合变化同时发生，但未证明因果    [查看证据]
DATA_BLOCKED 缺少 Macro 某字段                 [查看缺口]

[模拟组合发生了什么]
持仓、订单、未成交、现金、费用、NAV 分栏
POSITION_IMPACT_CONFIRMED / POSITION_IMPACT_NOT_ESTABLISHED

[研究解释]
INFERENCE   前提 -> 推理 -> 替代解释 -> 待验证

[明日人工核查]
问题 | owner | 截止时间 | 所需证据 | 当前状态

[人工质检]
通过 / 证据不足 / 退回
reviewer、reviewed_at、逐项 comment
```

版式要求：事实标签靠近正文而非藏在 tooltip；阻断状态不能只靠颜色；移动端先显示状态和缺口，再显示长解释；原文和哈希通过同一条目展开。不得出现自动“买入、卖出、加仓、减仓”按钮。

## 6. 人工质检规则

- `通过`：来源、日期、哈希、数字重算和措辞等级均匹配。
- `证据不足`：表达没有被现有证据支持，但尚未发现工件矛盾；保持 `DATA_BLOCKED` 或待核验。
- `退回`：身份、日期、哈希、计算或权限边界错误，需要重新生成简报。

审阅意见必须逐项具名，不设一个总分覆盖局部缺口。首份隔离简报未到之前，不得提前写“通过”。

不是买卖指令；研究信号，human executes.
