# Macro OS 数据契约

> 状态:`M0-A APPROVED_SPEC / M0-B3 DELIVERED_UNWIRED`。M0-A 定义输入边界;M0-B2 已交付历史仓、官方适配器、发布日历和双源共识门;M0-B3 已交付 URL 发现、调度、延迟标注和系统时钟预期登记,但 launchd 尚未安装,不等于生产已上线。

M0-B 的实现、运行方式和边界见 [`M0B_DATA_PIPELINE.md`](./M0B_DATA_PIPELINE.md)。

## 1. 本批交付

| 实物 | 用途 | 当前状态 |
|---|---|---|
| `source_registry.v1.json` | 数据源身份、E 级、独立供应商分组、可用性和历史版本能力 | 已冻结规格 |
| `event_tiers.v1.json` | 一级事件、双时间点预测、判分窗口和共识容差状态 | 已冻结规格 |
| `source_registry.schema.json` | 数据源注册表 JSON Schema | 已完成 |
| `event_tiers.schema.json` | 事件分层 JSON Schema | 已完成 |
| `house_expectation.schema.json` | 内部宏观预判 JSON Schema | 已完成 |
| `macro_event.schema.json` | 事件事实、共识和预期差 JSON Schema | 已完成 |
| `release_calendar.schema.json` | 官方发布日历与不可变快照引用 | 已完成 |
| `consensus_gate.schema.json` | 双源共识、冲突与阻断诊断 | 已完成 |
| `release_discovery*.schema.json` | 官方索引发现规则与运行状态 | 已完成 |
| `scheduler_status.schema.json` | 发布延迟与下一检查时间 | 已完成 |
| `m0b3_run_manifest.schema.json` | 同轮产物哈希绑定 | 已完成 |
| `contracts.py` | 零网络、失败即阻断的语义校验器 | 已完成 |
| `m0b3.py` | URL 发现、自适应调度、延迟监控与原子发布 | 已交付未部署 |
| `expectation_registry.py` | 系统时钟预期登记与 append-only 事件链 | 已交付未部署 |

权威路径位于 `experiments/macro_os/`。M0-B 能生成本地运行数据,但未完成生产接线;Better 的前端不应自行发明另一套字段。

## 2. 四类事实不能混写

1. **官方实际值**:只认事件注册表指定的原始发布机关,证据等级 E1。
2. **历史版本镜像**:FRED/ALFRED 等用于保存当时可见版本,属于 E2,不能替原发布机关背书。
3. **市场共识**:至少两个不同 `provider` 且不同 `independence_group` 的来源;两个接口若属于同一供应商,仍只算一个来源。M0-A 校验的是注册表声明,M0-B 还必须用原始快照证明真实上游,不能靠改名字制造独立性。
4. **内部预判**:一级事件在 T-24h 与 T-60m 各冻结一次,必须由 Junyan 的 GitHub PR Review 批准;预测实质内容单独哈希,Review URL 与批准 commit SHA 作为外层证明,避免审批后写回元数据造成循环。

冲突共识进入 `DATA_CONFLICT`,不得取平均后继续装成正常值。容差仍为 `CALIBRATING`,因此当前不得生成 `status=OK` 的正式市场共识。
每个正式事件同时绑定 `actual_source_ids` 与 `actual_series`;机构正确但指标取错同样拒绝。

## 3. 数据源边界

- 美国 CPI/就业实际值:美国劳工统计局。
- 美国 GDP/PCE 实际值:美国经济分析局。
- 美国零售销售实际值:美国人口普查局 Economic Indicators。
- ISM PMI 实际值:ISM 官方发布。
- 中国增长、通胀、PMI:国家统计局。
- 中国货币与信贷:中国人民银行。
- VIX:Cboe 官方历史数据。
- FRED/ALFRED:利率、信用与历史版本镜像,不冒充第三方指标的原发布机关。
- 市场共识的两条候选源目前仍为 `DATA_BLOCKED`;M0-B2 已交付双源校验器,但没有采购或伪造上游。两条独立正式源真正入库前,共识与预期差继续阻断。

## 4. 时间与版本纪律

- T-24h 登记不得晚于事件前 24 小时,T-60m 不得晚于事件前 60 分钟。
- M0-A 契约仍允许读取历史自报 `registered_at`;M0-B3 新登记入口禁止调用方传入该字段,改由系统时钟写入独立 append-only 事件链。未走新入口的历史记录不得反向升级成机器级可信时间戳。
- 预测获批后修改任一实质内容都会造成 `expectation_hash` 不匹配并被拒绝。
- M0-A 只校验 Review URL、commit SHA 与哈希的格式和不可变关系;M0-B 必须读取 GitHub Review,确认被批准 commit 中确实含同一 `expectation_hash` 后才能发布。
- Tier-1 只容纳可预先确定发布时间的事件;社融、新增贷款归 Tier-2,临时政策动作归背景层,不伪造 T-60m 精度。
- 每份事实保存 `as_of`、`fetched_at` 与原始响应 `snapshot_hash`;数据库修订不能覆盖当时可见值。
- 市场共识容差按事件类型和版本管理;校准期阈值为 null。
- 一级事件发布后必须同时保留市场共识、T-24h 内部预判、T-60m 内部预判三组比较。

## 5. 失败语义

以下任一情况必须拒绝正式输出:

- 官方实际值来自错误机构或 E2 镜像;
- 共识只有一个独立供应商;
- 两个来源差异超过容差却仍标 `OK`;
- 容差尚未校准却输出正式 `OK`;
- 内部预判迟到、未审批或只有 PR 链接而没有 Review 记录;
- 输出出现买卖、目标价或仓位指令字段。

## 6. 后续批次

1. **M0-B3 部署验收**:先合并 M0-B2/M0-B3,再安全同步运行目录、安装 launchd,完成一次真实官方页面基线与一次正式调度轮。验收前保持 `DELIVERED_UNWIRED`。
2. **M1-A**:GLOBAL/US 与 CHINA 双状态机、MRG、行业和组合传导。
3. **M1-B**:内部宏观面板、夜链 U1 标注消费者和校准记录;当前不接微信提醒。

不是买卖指令;研究信号,human executes。
