# 首份隔离每日简报质检记录

```yaml
schema: ar.daily-research-brief-review.v0
status: WAITING_FOR_FROZEN_BRIEF
reviewer: Reed
reviewed_at: null
brief_run_id: NOT_RECEIVED
target_trade_date: NOT_RECEIVED
brief_sha256: NOT_RECEIVED
source_manifest_sha256: NOT_RECEIVED
overall_verdict: NOT_ISSUED
sample_purpose: WORKFLOW_DEBUG
```

## 当前结论

截至 2026-09-23，仓库 `main@63ae7653`、公开 PR #365 的文件清单和本机交接材料中，**未收到首份冻结隔离简报**及其来源 manifest。因此本记录不能进行逐条事实核对，也不能产生“通过”意见。

这不是简报失败结论，只是输入尚未交付。旧网页、合成 fixture、聊天截图或历史 run 均不能替代首份冻结工件。

## 到件条件

Jason/Simon 提交的审阅包至少应包含：

1. 简报原件、`run_id`、`target_trade_date`、生成时间和数据截止时间；
2. 逐文件 manifest 与 SHA256；
3. 市场、Macro/Funnel、持仓、订单、NAV 和来源工件；
4. 最新尝试、最后成功发布和当前展示三者的独立身份；
5. `WORKFLOW_DEBUG`、无生产权限、无交易权限的边界字段。

少一项即保持 `WAITING_FOR_FROZEN_BRIEF` 或转为 `DATA_BLOCKED`，不能开始内容签署。

## 逐项质检表

允许的具名意见只有：`通过`、`证据不足`、`退回`。当前每项均为 `NOT_REVIEWED`。

| item_id | 检查项 | 当前状态 | 到件后的核验动作 | 具名意见 |
| --- | --- | --- | --- | --- |
| ID-01 | 简报身份与日期 | NOT_REVIEWED | 重算 brief hash，核对 run、交易日、截止时间 | 未出具 |
| SRC-01 | 每项陈述的来源 | NOT_REVIEWED | 打开原始工件，核对路径、来源日期和 `source_sha256` | 未出具 |
| NUM-01 | 市场与组合数字 | NOT_REVIEWED | 从持仓、订单、价格、费用和 NAV 重算 | 未出具 |
| LANG-01 | 事实/相关性/推断 | NOT_REVIEWED | 逐句检查 `FACT/ASSOCIATION/INFERENCE/DATA_BLOCKED` | 未出具 |
| IMPACT-01 | 仓位影响 | NOT_REVIEWED | 验证 `portfolio_value_delta` 及因果措辞边界 | 未出具 |
| STATE-01 | 运行和数据质量 | NOT_REVIEWED | 分开最新尝试、最后成功发布与数据质量 | 未出具 |
| AUTH-01 | 人工与 AI 权限 | NOT_REVIEWED | 检查 AI 草稿未冒充人工通过、无交易动作 | 未出具 |
| NEXT-01 | 次日核查事项 | NOT_REVIEWED | 检查 owner、截止时间、证据缺口和来源 | 未出具 |

## 裁决纪律

- `通过`：该项来源与数字均重算一致，措辞没有越过证据等级。
- `证据不足`：缺少承重证据或只能支持相关性/推断，保留缺口。
- `退回`：日期、run、hash、数字、权限或来源发生矛盾，需要重新生成。

首份包到件后，在新提交中填写 `reviewed_at` 和逐项 comment；不能覆盖这份“未到件”历史记录，也不能由 AI 代填 Reed 或 Junyan 的人工意见。

不是买卖指令；研究信号，human executes.
