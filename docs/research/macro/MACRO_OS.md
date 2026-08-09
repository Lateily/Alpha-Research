# Macro OS v0:全组合宏观研究操作系统

> 状态:`M1-A + M1-B DELIVERED_UNWIRED / CALIBRATING`。M0-A 至 M0-B3 提供事实与调度地基;M1-A 已实现双区域状态、MRG 候选态和事件上下文;M1-B 已实现全申万一级行业敏感度、组合宏观暴露和只读面板。两层均未接夜链或获得阻断权。
> 目标:提前识别宏观环境、预期和跨资产定价的变化,将其映射到全组合、行业和个股研究优先级。

## 1. MRG 在系统中的位置

MRG(Macro Risk-repair Gate)是 Macro OS 的战术风险修复子模块,不是完整宏观模型。

```
宏观事实与日历
  → 预期差/修正
  → 宏观状态(Growth/Inflation/Liquidity/Risk)
  → MRG(情绪/趋势/错位/信用)
  → 全组合风险预算
  → 行业敏感度
  → 持仓与候选研究优先级
  → 预注册判分
```

宏观门只允许输出 `context/posture/gate/risk_budget`。它可以降低或恢复研究与风险预算,不能直接生成买卖动作。

## 2. 五个宏观层

| 层 | 核心问题 | 主要指标 | 需要同时看什么 |
|---|---|---|---|
| 增长与就业 | 经济在加速还是减速 | GDP、PMI、工业生产、零售、失业率、非农、职位空缺、初请 | 实际值、市场预期、前值修正、3个月趋势 |
| 通胀 | 价格压力是否重新抬头 | CPI、核心 CPI、PCE、PPI、工资、通胀预期 | 环比年化、扩散、住房/服务/商品拆分 |
| 利率与流动性 | 折现率和融资条件如何变化 | 政策利率、Shibor、DR007、美债 2Y/10Y、2s10s、实际利率、美元 | 水平、斜率、变化速度、央行预期路径 |
| 信用与风险 | 长期资金是否收紧 | IG/HY OAS、信用利差、VIX、金融条件、流动性压力 | 信用是否确认股市情绪,信用拥有否决权 |
| 跨资产与外部 | 风险如何传到 A 股 | SOX/SPX、KOSPI、TSM/NVDA、A50、DXY、铜、油、黄金、人民币 | 相对强弱、支撑位、错位修复、亚洲传导 |

## 3. 预判层:不能只记公布值

每个宏观事件必须保留五组数据:

`event_time,actual,consensus,previous,previous_revised,surprise,source,as_of,fetched_at`

其中:

- `surprise` 使用方向统一后的标准化差值,例如失业率低于预期通常代表增长更强,但对风险资产的含义取决于通胀和利率状态。
- 前值修正单独计入,不能用最新数据库覆盖当时可见值后再回测。
- 新闻标题不能代替 actual/consensus;媒体只作 E2 解释层。
- 缺少 consensus 时事件仍可入库,但 surprise 标 `DATA_BLOCKED`,不允许填 0。

## 4. 宏观状态机

v0 使用四轴状态,每轴输出 `direction/confidence/data_status/reasons`:

| 轴 | 正向 | 中性 | 负向 |
|---|---|---|---|
| Growth | 增长改善 | 分歧/横盘 | 增长走弱 |
| Inflation | 通胀缓和 | 方向不清 | 通胀抬头 |
| Liquidity | 利率/流动性宽松 | 稳定 | 利率或美元收紧 |
| Risk/Credit | 信用与波动确认修复 | 未确认 | 信用恶化或波动冲击 |

组合状态采用规则树,不采用未经校准的加权平均。校准期信用红灯只产生 `CREDIT_STRESS_CANDIDATE` 与风险预算上下文,不拥有正式否决权;数据不足输出 `MACRO_PARTIAL`,不得自动继承上一日绿灯。正式阻断权必须在达到独立因果簇门槛、优于随机控制并经 Junyan 单独批准后另行接线。

以下是成熟期目标语义;M1-A 校准期只输出对应 `*_CANDIDATE`,`formal_regime` 保持 null:

| Regime | 人话含义 | 允许影响 |
|---|---|---|
| `RISK_REPAIR_CONFIRMED` | 增长/流动性/风险资产共同修复,信用没有反对 | 恢复常规研究预算,仍按个股两票制 |
| `TACTICAL_BOUNCE` | 股市和情绪修复,信用或宏观数据尚未确认 | 允许观察和小规模条款复核,禁止把反弹写成主升浪 |
| `POLICY_CONFLICT` | 增长尚可但通胀/就业使利率预期收紧 | 降低长久期和高估值方向优先级,提高事件监控 |
| `GROWTH_SCARE` | 增长和就业明显走弱 | 检查周期、可选消费和信用暴露 |
| `CREDIT_VETO` | 信用利差恶化否决风险修复 | 全组合 RISK_OFF_BIAS,禁止由股指单独升级 |
| `MACRO_PARTIAL` | 关键数据缺失、过期或冲突 | 保持人工复核,不输出确认态 |

阈值全部标 `unvalidated_v0`;只有跨事件、跨窗口判分后才能升级。

## 5. MRG 四因子子模块

| 因子 | 当前代理 | 数据源候选 | 权限 |
|---|---|---|---|
| G1 情绪 | VIX 水平与 5 日方向 | yfinance/FRED 替代 | 免费,需健康监控 |
| G2 趋势 | SOX vs MA100,KOSPI vs MA200,并附广度 | yfinance/市场数据 | 免费,需盘前 freshness |
| G3 错位 | `ln(SOX/SPX)` 120 日 z-score | yfinance | PCA 原版不可用时的代理,不得混称 PCA |
| G4 信用 | 美国 IG OAS 20 日变化 | FRED `BAMLC0A0CM` | 免费;校准期 G4 红只标候选压力,不执行否决 |

规则树初版:

1. G4 红 → `CREDIT_STRESS_CANDIDATE`,并把研究风险预算上下文标为收缩;`enforceable=false`。
2. 四绿 → `RISK_REPAIR_CANDIDATE`。
3. 三绿一黄且信用黄 → `TACTICAL_BOUNCE_CANDIDATE`。
4. 任一必需源过期或阻断 → `MACRO_PARTIAL`。

这组规则只复现当前研究思想,尚未证明前瞻能力。每次状态变化必须预注册并进入判分。

## 6. 行业敏感度与组合映射

Macro OS 不止给一个大盘标签。它必须产生两次下钻:

### 行业层

每个 Sector OS 维护:

`factor,exposure_direction,mechanism,lag,evidence_level,last_reviewed,wrong_if`

例子只作机制说明:

- 利率上行可能压制长久期估值,但业绩上修可以抵消。
- 美元与实际利率影响黄金和有色的定价环境。
- 就业和工资影响可选消费、服务与医药支付能力。
- 信用利差变化影响高杠杆、地产链和小盘融资环境。

不得把行业常识直接写成确定方向;每条关系需要证据级别和 wrong-if。

### 组合层

每个持仓和候选保存:

`growth_beta,inflation_beta,rate_duration,credit_sensitivity,usd_sensitivity,commodity_sensitivity,global_tech_beta,evidence_level,as_of`

组合汇总输出集中暴露和需要人工复核的相关性。M1-B 只读 `model_portfolio_state.v2.2`,不读取原始订单;由于当前契约没有逐仓定盘市值,权重统一标为 `CONTRACT_NOTIONAL_DIVIDED_BY_NAV_PROXY`,不得冒充实时仓位权重。未知主题直接 `DATA_BLOCKED`,不凭名称猜行业。宏观状态变化只修改风险预算、研究优先级和复核频率。

## 7. 五份正式契约

| 契约 | 内容 | 消费者 |
|---|---|---|
| `macro_events.json` | 事件日历、actual/consensus/revision/surprise、来源与可信边界 | Macro Agent/前端 |
| `macro_state.json` | 四轴状态、regime、reason codes、freshness | 夜链/盘前帧/组合门 |
| `macro_risk_gate.json` | G1-G4 原始值、阈值版本、规则树结果 | 晋级器/盘前帧 |
| `industry_macro_sensitivity.json` | 宏观因子到行业的机制、方向、时滞和证据 | Sector Agent/轮动面板 |
| `portfolio_macro_exposure.json` | 持仓和组合暴露、集中度、状态变化影响 | Portfolio Agent/前端 |
| `macro_panel.json` | 双区域状态、MRG、事件缺口、行业和组合上下文的只读总览 | 内部面板/审阅者 |
| `macro_scorecard.json` | 每次预注册状态的 T+1/T+5/T+20 后验 | Validation Agent/周报 |

统一 required:`schema_version,report,as_of,generated_at,source_health,data,disclaimer`。

## 8. 运行顺序

盘前:

1. 更新隔夜资产、已公布宏观事件和当日事件日历。
2. 检查每个源的 freshness 与交易时区。
3. 生成 MRG 和盘前 `macro_state` 增量。
4. 映射到组合与行业,只输出风险上下文。

盘后:

1. 固化当日可见数据快照。
2. 更新全量四轴状态、MRG、行业敏感度和组合暴露。
3. 对到期宏观假设做 T+1/T+5/T+20 判分。
4. 把变化送入次日全市场漏斗和候选复核池。

## 9. Agent 工程拆分

| 子项目 | Owner | 第一阶段交付 |
|---|---|---|
| Macro 治理 | Junyan | 公式、事件层级、阈值与最终批准 |
| Macro 项目管理 | Simon | 路线图、依赖、验收节拍和跨角色协调 |
| Macro Data Agent | Reed/Jason + Codex/Claude | 数据源 adapter、事件 schema、vintage/revision、防注入 |
| Macro State Agent | Junyan + Codex/Claude | 双区域状态机、MRG 规则树、DATA_BLOCKED 语义 |
| Macro-Sector Agent | Junyan+Sector Agents | 首批半导体、医药、有色敏感度表 |
| Macro-Portfolio Agent | Junyan+Portfolio Agent | 持仓因子暴露与组合聚合 |
| Macro Validation Agent | Reed+Validation Agent | 事件簇、T+1/T+5/T+20、基准和负控制 |
| Macro UI / Product | Better | 独立内部面板;成熟后并入产品前端,全程只读契约 |

## 10. 已冻结架构

- GLOBAL/US 与 CHINA 两套状态机独立运行,冲突不互相抵消;分别生成 A/H 传导。
- 战术层观察 0-5 个交易日,慢周期层观察 1-3 个月。
- 正式状态由确定性规则树产生;AI 只负责解释、质疑和提出 challenger。
- 展示同时给出相对平稳市场的环境等级和组合压力等级。
- 组合压力 = 行业基线 + 公司 factpack 调整,再按组合权重聚合。
- 全行业使用申万一级粗粒度映射;半导体、医药、有色先建深模型。
- Champion 使用可解释规则树,Challenger 使用统计模型;替换公式必须经 Junyan PR Review。
- 校准期只做标注、研究优先级和风险预算,不获得直接阻断权。
- `api/macro.js` 只能生成解释文字,不得拥有或改写正式 `macro_state`。
- 团队云端只展示宏观状态与 paper portfolio;真实组合仅从本地手工覆盖层读取。

## 11. 实施里程碑

M0-A 契约地基(本批):

- 四份 JSON Schema + 两份带内容哈希的注册表。
- 官方事实、历史镜像、市场共识和内部预判分层。
- Tier-1 事件 T-24h/T-60m 双快照与 GitHub Review 审批。
- 市场/利率 10 年覆盖 95%、事件 5 年 90%、共识 3 年 80% 的校准退出门槛。

M0-B 数据可信:

- PR #181 宏观原料独立复验。
- 接入 official/free sources、SQLite 历史仓、双源 consensus/vintage 和源健康。
- 数据公布延迟先以 5 分钟为目标,后续按源强度自适应优化。
- 盘前隔夜锚恢复当日新鲜度。

M1 状态闭环:

- 生成 `macro_events/macro_state/macro_risk_gate` 三契约。
- GLOBAL/US 与 CHINA 各自使用 Growth/Inflation/Liquidity/Risk 四轴,不得求平均抵消。
- 所有阈值为 `UNVALIDATED_V0`;正式状态保持 null,只输出 `*_CANDIDATE`。
- 夜链与盘前帧消费 report/freshness(尚未接线)。
- 关键源阻断时进入 MACRO_PARTIAL。

M2 研究下钻:

- 全部 31 个申万一级行业粗粒度敏感度种子;电子/通信、医药、有色先建深模型。
- 当前组合暴露聚合,只使用契约中的 theme/notional/NAV,不猜原始订单或实时市值。
- 全市场扫描增加宏观敏感度通道。

M3 判分:

- 宏观状态变化先注册后验证。
- 按事件簇去重,报告 T+1/T+5/T+20 与基准。
- 样本不足只显示计数、四格表和失败案例。

不是买卖指令;研究信号,human executes.
