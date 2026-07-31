# 全市场分层研究漏斗 v0

> 目标:系统在没有人工提醒时持续知道“全市场有什么、为什么被关注、为什么被排除、下一步谁来研究”。
> 本文件定义目标架构和数据接口,不宣称当前系统已经实现全市场研究闭环。

## 1. 覆盖边界与节奏

| 市场 | 永久覆盖范围 | 作用 |
|---|---|---|
| A 股 | 全部正常上市证券;退市、停牌、ST 等保留状态并按规则降级,不从注册表消失 | 主研究和监控市场 |
| 港股 | 当前持仓、已注册研究对象、Sector OS 行业锚 | 组合与产业链补充 |
| 美股 | 宏观锚、产业链锚、全球风险资产锚 | 不进入 A 股个股漏斗 |

固定节奏:

1. 盘后:全 A 批量正式扫描,更新注册表、特征、候选和淘汰原因。
2. 盘前:更新宏观事件、海外隔夜锚和组合暴露,不重跑整套深研。
3. 盘中:只处理新事件、持仓、已注册条款和候选池;不临时扫描 5000 只后生成方向结论。
4. 周度:深研 3 到 5 个对象、更新 Sector OS、复盘漏斗遗漏和通道贡献。

## 2. 效率原则

“低成本扫描”指 API、计算、LLM token 和人工注意力的总成本。终端能在约几十秒内跑完简单价格扫描,但逐票调用红旗闸门或六维电池会把耗时和接口请求线性放大。成熟产品也应保留同一分层,扩大机器只提高吞吐,不取消漏斗。

正确的工程顺序:

1. 数据接口按日期或市场批量抓取。
2. 原始数据落本地特征仓。
3. 用向量化/本地 join 计算全市场低成本特征。
4. 只有候选池进入逐票电池。
5. 只有少量对象调用深研 Agent 和高成本模型。

## 3. 六层漏斗

| 层 | 名称 | 规模目标 | 工作 | 产物 |
|---|---|---:|---|---|
| U0 | 永久在线注册表 | 全 A | 保存证券身份、上市状态、行业、最后扫描时间、数据覆盖 | `security_registry.json/parquet` |
| U1 | 全市场批量扫描 | 全 A | 六通道计算、E1 红旗、数据完整性、宏观敏感度 | `all_market_scan` 分区数据 |
| U2 | 候选复核池 | 100-300 | 通道并集、去重、流动性门、异常复核、保留淘汰原因 | `candidate_review.json` |
| U3 | 完整研究电池 | 20-50 | 行情、资金、基本面、技术、消息、估值,加行业与宏观上下文 | `research_battery.json` |
| U4 | 深研队列 | 每周 3-5 | E1 factpack、双支柱、关系边、估值区间、wrong-if、红队 | `factpack` + `decision_sheet` |
| U5 | 法庭与组合 | 持仓/挂单/注册假设 | 两票制、风险预算、条款、判分、十日检察官 | court/portfolio/paper ledgers |

### 不消失原则

每只证券每天只能处于一种可追踪状态:

`UNSCANNED → SCANNED → CANDIDATE → BATTERY → DEEP_RESEARCH → COURT/PORTFOLIO`

降级使用 `EXCLUDED` 或 `MONITOR`,但必须保留 `reason_codes`、`decided_at`、`next_review_at`。对象不能因为没进 TOP30 就从系统记忆里消失。

## 4. U1 多通道扫描

系统不使用一个总分统治所有研究方法。六个通道独立发现对象,最后取并集:

| 通道 | 发现什么 | 最低数据 | 典型漏报补偿 |
|---|---|---|---|
| E1 事件 | 业绩预告、快报、正式公告、监管与重大事项 | issuer guidance/announcements | 资金雷达看不见的基本面变化 |
| 行情与量价 | 动量、慢牛、反转、波动收敛、缺口和流动性 | daily/adj_factor/volume | 大参林式慢牛和结构修复 |
| 资金与筹码 | 市场、行业、个股资金,龙虎榜,筹码,两融 | moneyflow/top list/chips | 价格背后的参与结构 |
| 基本面与估值 | 收入利润趋势、现金流、资产负债、估值分位 | 三表/daily_basic/factors | 旧叙事和高估值风险 |
| 行业与产业链 | 轮动连续性、龙头广度、链条 E1 锚、关系边 | sector panel/Sector OS | 单票视角遗漏的产业共振 |
| 宏观与跨资产 | 增长、通胀、利率、信用、风险偏好与行业敏感度 | Macro OS contracts | 海外就业、利率和信用变化造成的系统风险 |

初始配额只用于防止单一路径独占候选池,不是统计结论。每路至少保留若干名额,另保留随机控制样本用于估计漏斗的漏报。具体数量由运行成本和回溯结果校准,变更须留版本。

## 5. 候选晋级规则

U1 到 U2:

- 任一通道达到自身阈值即可进入并集,不要求六维同时亮灯。
- E1 红旗不会让证券消失;对象进入 `REVIEW_WITH_FLAG`,不能佩戴核心层级。
- 数据缺失产生 `DATA_BLOCKED`,不产生 PASS。
- 北交所、ST、极低流动性等采用资格标签,不在扫描层删除。

U2 到 U3:

- 至少一个发现理由可追溯到原始数据。
- 必须通过 freshness、证券身份和流动性检查。
- 同一事件簇只占一个主要名额,避免同板块复制信号挤满名单。

U3 到 U4:

- 六维状态逐项可见,缺失项清楚标注。
- 所属 Sector OS 存在或同时创建行业补课任务。
- 有明确研究问题,不能只因价格上涨进入深研。
- 深研排期同时考虑组合相关性、催化剂日期和证据更新成本。

U4 到 U5:

- 遵守 Unified Research OS 的 thesis 票与 timing 票。
- factpack、wrong-if、主期限、cluster_id、来源清单齐全。
- 宏观门只调整风险预算和优先级,不直接生成交易动作。

## 6. 目标契约

### security_registry

必需字段:`schema_version,ts_code,name,market,board,list_status,industry_key,first_seen,last_seen,last_scanned_at,data_coverage,current_stage,reason_codes,next_review_at`。

### all_market_scan row

必需字段:`trade_date,ts_code,channel,feature_version,feature_values,triggered,source_as_of,data_status,reason_codes`。

### candidate_review row

必需字段:`as_of,ts_code,source_channels,cluster_id,priority,flags,liquidity_eligibility,review_status,exclusion_reason,next_action`。

所有契约统一要求:

- `as_of` 与 `generated_at` 分开。
- `status` 只允许 `COMPLETE/PARTIAL/INCOMPLETE/DATA_BLOCKED/STALE_INPUT`。
- 下游必须消费 `status`,不能只检查进程 exit code。
- 版本升级保留迁移说明和旧消费者窗口。

## 7. Agent 项目分工

| Agent 项目 | 负责范围 | 不得越权 | 主要验收人 |
|---|---|---|---|
| Universe/Data Health Agent | 注册表、交易日、批量抓取、freshness、数据源健康 | 不做证券评价 | Junyan/Claude |
| Market Scanner Agent | 六通道全市场特征、候选并集、控制样本 | 不生成组合动作 | Junyan |
| Macro Agent | Macro OS、事件、MRG、行业敏感度、组合暴露 | 不直接选股 | Junyan |
| Sector Agent | Sector OS、行业指标、关系边、E1 锚 | 不越过 E 级证据规则 | Junyan |
| Single-name Research Agent | 电池、factpack、决策书、红队 | 不绕过注册与两票制 | Junyan/Validation Agent |
| Validation Agent | 独立簇判分、四格表、IC、反事实、漂移 | 不修改原始判断 | Junyan/Audit Agent |
| Portfolio/Risk Agent | 持仓暴露、风险预算、法庭、条款状态 | 不执行真实交易 | Junyan |
| Audit Agent | 契约、账本、越权、失败路径和申报真伪 | 不自行改宪法级规则 | Junyan |

Reed 负责这些 Agent 的 adapter、岗位说明、评测和成本;Better 负责把契约稳定展示;Junyan 决定研究规则和最终验收。

## 8. 从当前终端到成熟产品

### 当前阶段

- 日频批量抓取与本地特征仓。
- 全市场 U0/U1 使用确定性代码,不调用 LLM。
- U2/U3 少量逐票任务可并发,设置 API 速率和缓存。
- 深研 Agent 按队列工作,结果进入 repo 和判分池。

### 成熟阶段

- 调度器、对象存储和列式数据仓替代单机目录。
- 按 trade_date/market/channel 分区,只重算受影响分区。
- 多 Agent 使用队列和幂等 job id,避免重复写。
- 前端读取版本化契约和历史快照,不直接访问原始接口。
- 独立量化影子基金共用 U0/U1 数据主干,从 U2 以后各自分流并独立记账。

## 9. 验收指标

第一阶段只验收工程与研究覆盖质量:

- 全 A 注册覆盖率和每日扫描覆盖率。
- 各通道 DATA_BLOCKED、STALE_INPUT 和异常率。
- 每个候选的来源通道与淘汰原因完整率。
- 候选进入电池、深研、法庭的转换路径。
- 后验发现的重大对象是否曾被任一通道捕获,漏报发生在哪一层。
- 单日 API 次数、运行时间、LLM token 和人工复核量。

研究结果仍按独立簇判分;样本不足时只报告计数和案例,不作能力主张。

不是买卖指令;研究信号,human executes.
