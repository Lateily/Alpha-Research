# 周报模板 v1(Notion 页 / repo 文档通用)

> 正式化自 `experiments/pm_research_ops_2026_07/WEEKLY_REPORT_TEMPLATE.md`
> (Codex 起草)+ Claude 修正案 A2,Junyan 批准 2026-07-09。
> 读者:Junyan、学长(PM)、非技术审阅者。实例存 `docs/team/weekly/YYYY-Www.md`。

## 数据源指针(周报生成是机械动作,不许手抄)

| 节 | 数据来源(repo 内) |
|---|---|
| NAV / 现金 / 持仓 | `experiments/execution_tracker/model_fund/{fund,nav_history,orders}.json` |
| 成交/撤单/决定 | `experiments/execution_tracker/model_fund/decision_log.json` |
| 正式信号 | `experiments/execution_tracker/paper_signal_log.json` |
| nowcast 判分 | `experiments/execution_tracker/nowcast_log.json`(evaluator --report) |
| 定盘样本 | `experiments/execution_tracker/samples/YYYYMMDD.json` |
| 模型改动 | 本周 merged/open PR 列表(`gh pr list`) |

## Header

Week / 日期范围 / Prepared by / Reviewers / Market regime / 一句话 verdict

## 1. Executive Summary(≤5 行)

市场变了什么 · portfolio/paper 变了什么 · 模型变了什么 · 学到什么可证伪的 ·
下周单一 KR。

**"本周被纪律挡下的动作"为必填项**——对审阅者,"没做什么"往往比"做了什么"
更能证明系统有纪律。空着不交等于 REPORT_INCOMPLETE。

### 非技术审阅者五行

建了什么 / 改进了什么 / 学到什么 / 还不可靠什么 / 下周测什么。

## 2. Portfolio Snapshot(敞口与风险 posture,非实盘指令)

| 项 | 值 | 证据 |
|---|---:|---|
| NAV / 周收益 / 现金权重 / 最大敞口 / 风险 flag | | ledger 文件名 |

要求:持仓与 pending 分开列;非动作若是关键结果要明说;每个实质数字标
`[validated against ledger]` / `E3 market data` / `[unvalidated estimate]`。

## 3. 交易与信号账本

每个真实/paper 决定一行审计记录,**含被 gate 挡下的非交易**:

| ID | Ticker | Real/Paper | Setup | Reasoning | Gate | Outcome | Review |
|---|---|---|---|---|---|---|---|

Reasoning 必含:market state / sector state / flow fact / forecast claim(如有)
/ invalidation / horizon。禁止写"模型看好"——写具体因果链。

## 4. Model Iterations(想法 → 落地 → 效果)

| 改动 | 起点(痛点/想法) | 落地(file/PR) | 验证(命令/样本/测试) | 结果 | 决定 |
|---|---|---|---|---|---|

框架:解决什么痛?可度量地改进了什么?**没**证明什么?还缺什么数据?
决定 ∈ {ship, paper_only, revise, kill, defer}。

## 5. 能力 / 实践 / 目标(给外部审阅者看进度的最清晰方式)

- **能力**:模型今天能做什么。
- **实践**:模型本周实际做了什么(含因纪律没做的)。
- **目标**:下一步要能做什么。

## 6. Research Frontier

- 轮动实验室:加了什么数据、测了什么假设、什么失败了。
- 产业链图谱:建了哪条链、识别了哪些瓶颈节点、哪些公司要进 deep thesis。

## 7. 给审阅者的问题(少而聚焦,最多 3 条)

好:"半导体链图谱是否漏了上游瓶颈?" 坏:"有什么建议吗?"

## 8. 决定与下周 KR

| 决定 | Owner | Artifact | Due | 状态 |
|---|---|---|---|---|

状态 ∈ {accepted, rejected, deferred, needs_data, needs_review}。

## 9. Validation Footer(必填)

Causal logic is [valid/questionable/unestablished] because …
数字标注 [validated against data / unvalidated intuition / calibrated from X] …
DATA_BLOCKED / DATA_CONFLICT flags …
Conclusion posture … / Next gate …
Self-audit:给了买卖指令吗?把未验证策略叫 alpha 了吗?把资金事实混同
去向预测了吗?忽略板块/指数确认了吗?事后解释冒充 pre-registered claim 了吗?

不是买卖指令;研究信号,human executes.
