# 财报逐条回应未结 Thesis 的问题清单 V0

状态：`QUESTION_REQUIREMENTS_ONLY / WORKFLOW_DEBUG / NO_HUMAN_VERDICT`

本清单定义下一轮财报材料应怎样逐条回应已经登记但尚未解决的 thesis。它不生成公司结论，不扩展观察名单，不运行数据采集，也**不回写原 thesis**。AI 可以形成回答草稿，但**AI 草稿不能签成人工研究结论**。

## 1. 开始前必须冻结的身份

每个问题必须绑定：

- `ticker`、公司名称、财报期和公告日期；
- `claim_id`、原始 `registered_thesis_hash`、登记时间和版本；
- 原 claim、预期方向、指标、阈值、截止时间、`wrong_if`；
- 允许使用的来源、数据截止时间、原文位置和来源 SHA256；
- 是否属于 prospective claim。历史草稿不得事后冒充前瞻预测。

无法绑定原始 claim 时，该问题直接为 `DATA_BLOCKED`，不得根据新财报反向编造旧观点。

## 2. 每条 Claim 的回答状态

| 状态 | 含义 |
| --- | --- |
| `CONFIRMED` | 财报中的同口径事实满足原先登记的可观察条件；只回答该 claim，不代表整条 thesis 正确 |
| `WEAKENED` | 方向部分成立但幅度、时间或因果机制弱于原登记 |
| `INVALIDATED` | 原 `wrong_if` 被同口径事实触发，或承重前提被直接否定 |
| `NOT_ADDRESSED` | 财报没有披露足以回答该问题的字段，不将未披露当成零 |
| `DATA_BLOCKED` | 来源、期间、口径、单位、身份或哈希不能核实 |

机器可以根据确定性条件生成候选状态，但最终研究解释和具名裁决仍由人完成。

## 3. 逐条问题模板

每个未结 claim 复制一行，不得把多条 claim 合成一个“整体符合预期”。

| 字段 | 必填内容 |
| --- | --- |
| `claim_id` | 原登记中的稳定 ID |
| `registered_thesis_hash` | 原 thesis 字节哈希 |
| 原问题 | 当时具体相信什么，不能按结果改写 |
| 原阈值与期间 | metric、operator、threshold、measurement_period、due_date |
| 财报直接回答 | 原文事实、页码/章节、单位、合并或分部口径 |
| 可重算结果 | 公式、输入值、同比/环比基期及舍入规则 |
| 回答状态 | `CONFIRMED/WEAKENED/INVALIDATED/NOT_ADDRESSED/DATA_BLOCKED` |
| 因果限制 | 财报事实能证明什么，不能证明什么，替代解释是什么 |
| 新问题 | 新证据产生的后续问题；不得静默改写旧 claim |
| 人工意见 | reviewer、reviewed_at、source_checked、comment |

## 4. 财报问题库

问题只在其与已登记 claim 有关时启用；不能为了填满模板而增加无关指标。

### 4.1 收入和需求

1. 收入变化来自销量、价格、产品结构、汇率还是并表？各因素能否从财报重算？
2. 分部或产品收入是否与 thesis 的需求对象一致，而非只看总营收？
3. 订单、合同负债、在手项目或客户库存能否支持下一期需求判断？其披露口径是否变化？

### 4.2 毛利率和盈利桥

1. 毛利率变化由产品组合、价格、良率、产能利用率、原材料或折旧中的哪一项驱动？
2. 归母净利润与经营利润的差异是否来自一次性项目、政府补助、投资收益或减值？
3. 归一化盈利桥是否完整覆盖收入、毛利、费用、税率、少数股东和股本变化？

### 4.3 现金质量与资产负债表

1. 经营现金流与利润的差异来自应收、存货、应付、预收还是非现金项目？
2. 应收和存货增速是否高于收入，账龄、减值和周转是否恶化？
3. 资本开支、在建工程和折旧是否支持或反驳原产能假设？
4. 所谓净现金是否包含受限资金、理财、短债和表外义务的正确口径？

### 4.4 分部、客户和产业链

1. 承重业务的分部披露是否与公司总口径一致？分部映射是否有来源而不是行业标签推断？
2. 客户集中度、前五大客户、关联交易或供应链依赖是否改变原风险判断？
3. 公司所处产业链节点的价格、库存和交付变化是否有 issuer 证据支持？

### 4.5 指引、催化剂与 Wrong-if

1. 管理层指引是量化承诺、方向性表述还是没有更新？可信度如何，过去兑现记录怎样？
2. 原登记催化剂是否发生、推迟、取消或口径改变？只记录事件，不因股价结果倒推催化有效。
3. 每一条 `wrong_if` 是否已触发？若字段未披露，标记 `NOT_ADDRESSED`，不能判定未触发。

## 5. 给后续工程任务的最小字段需求

这是研究需求，不是对 Jason 工程合同的直接修改：

```text
subject_id
report_period
announcement_date
claim_id
registered_thesis_hash
metric / operator / threshold / measurement_period / due_date
wrong_if_ref
source_ref / source_date / source_sha256 / excerpt_location
observed_value / unit / calculation
response_status
causal_limitations
reviewer / reviewed_at / source_checked / comment
```

负样本必须覆盖：财报期错位、累计值与单季值混用、单位变化、分部改名、未披露填零、事后修改阈值、同一来源重复计数、AI 自填 reviewer、旧 thesis hash 与当前问题不一致。

## 6. 人工交付格式

最终人工记录按 `claim_id` 排列，保留所有未回答和被证伪项。摘要可以说明总体倾向，但不能覆盖逐条状态。新 thesis 或新阈值另开版本，并明确它是在财报之后提出的，不得追改原注册时间。

不是买卖指令；研究信号，human executes.
