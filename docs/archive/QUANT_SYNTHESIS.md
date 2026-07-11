# AR Platform — Quant Strategy Synthesis & Integration Roadmap

> 综合来源：用户提供的工具栈（Tushare / 东财 / Jupyter / Python回测）+ A股量化社区主流思路 + 平台现状分析 + 用户提供的7篇小红书笔记原文（2026-04-20，xsec_token 直接读取）
> 目的：系统性梳理接下来1周内可以集成到现有平台的高价值优化方向，节省自主探索时间  
> 作者：AR Platform v14.x | 最后更新：2026-04-20

---

## 一、现有平台能力边界（诚实评估）

| 模块 | 现状 | 主要缺口 |
|------|------|----------|
| 价格数据 | Vercel/Sina 实时价格 ✓ | 分钟级数据无 |
| 基本面数据 | yfinance 季报数据 ✓ | 结构化因子（ROE/PB/成长）弱 |
| 宇宙数据 | 东财 clist 全市场 ~5800只 ✓ | 无因子评分，无概念板块标签 |
| 技术信号 | MA5/20/60, RSI, 成交量 ✓ | 无高频数据，无分钟级均线 |
| 回测 | 月度再平衡，VP阈值 ✓ | 无因子回测，无换手率控制 |
| 选股逻辑 | 人工筛选5只Focus stocks | 无系统化多因子筛选 |
| 资金流 | 东财北/南向（受限）| 龙虎榜信号弱，游资未追踪 |

**核心结论**：平台在**深度研究层**（AI分析）很强，在**宽度筛选层**（从5800只量化出候选池）几乎为空。接下来的重点是建立这一层。

---

## 二、A股量化社区主流策略图谱

### 2A. 数据驱动选股（最适合我们平台）

**① 多因子选股**（社区最高频提及）
- 核心因子：**价值**（PE、PB、PS）+ **质量**（ROE、毛利率、净利率）+ **动量**（近3/6/12个月涨跌幅）+ **成长**（营收增速、利润增速）
- 实现路径：Tushare `daily_basic` API → 每日全市场因子快照 → 标准化 → 等权或IC加权合成
- 开源参考：`qlib`（微软开源量化框架）、`alphalens`（Quantopian因子分析库）
- **与现有平台的接口点**：universe_a.json 已有PE/PB/成交量，可直接计算初步因子分

**② 财报驱动策略**（earnings momentum）
- 逻辑：季报发布前20日买入，发布后超预期继续持有，未达预期3日内止损
- 信号源：Tushare `income` + `fina_indicator` → 对比yfinance `earnings_estimate`
- **与现有平台的接口点**：EarningsCalendar已有，缺的是beat/miss概率预测

**③ 概念板块轮动**
- 逻辑：识别近10日涨幅最强的概念板块，在板块内选择基本面最强的个股
- 信号源：东财概念板块API（`push2.eastmoney.com/api/qt/clist/get?fs=m:90+t:3`）
- 实现难度：低（已有东财API经验）

### 2B. 资金流信号（现有数据增强）

**④ 龙虎榜信号**
- 逻辑：机构席位净买入 > ¥5000万 → 视为强势信号，跟踪5日
- 现状：fetch_data.py 已有 `dragon_tiger` 字段但数据为null（AKShare被封）
- 修复路径：东财龙虎榜直接API `reportapi.eastmoney.com/report/info` 或 `www.eastmoney.com/data/dalonghubang.html`

**⑤ 北向资金行业分布**
- 逻辑：跟踪北向资金在哪个行业加仓，作为板块轮动的领先指标（通常领先2-3周）
- 信号源：东财北向行业分布数据（已存在，但 latest_net_flow=null）
- 修复路径：替换为 Tushare `moneyflow_hsgt` 或东财直接API

**⑥ 大单净流入**
- 逻辑：单日大单（>50万/笔）净流入 > 成交额10% → 主力建仓信号
- 信号源：东财 `/api/qt/stock/fflow/kline/get` → 已在 `api/capital-flow.js` 用过
- 与现有平台：直接扩展 `flow_data.json`，加入个股大单数据

### 2C. 技术策略增强

**⑦ 量价关系信号**（现有swing_signals.py扩展）
- 缩量上涨 = 主力控盘（看多）；放量下跌 = 出货（看空）
- 具体规则：近3日成交量 < 20日均量60% + 涨幅>2% → `CONTROLLED_ADVANCE`
- 实现：直接加入 `swing_signals.py`，成本极低

**⑧ 均线多头排列**
- 逻辑：MA5 > MA20 > MA60 且价格 > MA5 → 趋势确认，可降低止损位置
- 现状：已有MA5/20/60，但没有综合"多头排列"信号
- 实现：在 `compute_signals()` 中加2行

**⑨ 相对强弱（行业内RS）**
- 逻辑：个股涨幅 / 所在行业ETF涨幅 → RS > 1.2 看多
- 信号源：行业ETF价格（yfinance 已支持）

### 2D. AI辅助判断（平台核心优势）

**⑩ 财报电话会议语气分析**（v15.1预计）
- 社区流行：用LLM分析管理层措辞，量化"信心指数"
- 我们已有DeepResearch框架，接口成本低

---

## 三、Tushare集成优先级评估

Tushare Pro（tushare.pro）是社区推荐数据源首选，与我们现有体系的对比：

| Tushare API | 数据内容 | 我们现有替代 | 集成价值 |
|-------------|----------|-------------|----------|
| `daily_basic` | 全市场每日PE/PB/ROE/市值 | 东财clist（PE/PB有，ROE无）| ⭐⭐⭐ 高 |
| `income` / `balancesheet` | 季度财务报表 | yfinance（只有Focus股）| ⭐⭐⭐ 高 |
| `moneyflow_hsgt` | 北向资金历史 | AKShare（被封）| ⭐⭐ 中 |
| `top_list` | 龙虎榜机构席位 | AKShare（被封）| ⭐⭐ 中 |
| `concept_detail` | 概念板块成分股 | 无 | ⭐⭐⭐ 高 |
| `stk_limit` | 涨跌停数据 | 无 | ⭐ 低 |
| `express` | 业绩快报 | 无 | ⭐⭐⭐ 高 |

**结论**：Tushare最高价值场景是 `daily_basic`（因子数据）+ `concept_detail`（板块标签）+ `express`（业绩快报）。申请积分账户后，这些API每天可以免费调用。

---

## 四、一周内可执行的优化路线图

### Sprint A — 数据层扩展（2-3小时）

**A1. 在 fetch_data.py 中加入 Tushare 因子快照**
```python
# 每天跑一次，给universe_a.json中每只股票加上因子分
import tushare as ts
TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN', '')

def fetch_tushare_factors():
    if not TUSHARE_TOKEN: return {}
    pro = ts.pro_api(TUSHARE_TOKEN)
    today = datetime.now().strftime('%Y%m%d')
    df = pro.daily_basic(ts_code='', trade_date=today,
                         fields='ts_code,pe,pb,ps,roe,dv_ratio,total_mv,circ_mv')
    # Returns ~5800 rows in one call
    return {row['ts_code']: row.to_dict() for _, row in df.iterrows()}
```

**A2. 概念板块标签注入**
- 东财API：`https://push2.eastmoney.com/api/qt/clist/get?fs=m:90+t:3&fields=f12,f14,f3,f20`
- 返回所有概念板块及其近日涨幅
- 与universe_a.json合并，给每只股票打上所属概念标签

**A3. 龙虎榜直接API**
```python
# 替换AKShare龙虎榜
url = 'https://data.eastmoney.com/dataapi/security/newranklist'
# 参数：date, type=1（机构），返回JSON
```

### Sprint B — 多因子筛选器（3-4小时）

**B1. 在 fetch_data.py 加入因子评分计算**
```python
def score_universe(stocks, factors):
    """
    输入：universe stocks列表 + Tushare因子dict
    输出：每只股票的综合因子分 factor_score (0-100)
    """
    # 4个因子各25%权重：
    # value_score = 100 - percentile_rank(pe)   # PE越低越好
    # quality_score = percentile_rank(roe)       # ROE越高越好
    # momentum_score = percentile_rank(change_20d) # 近20日涨幅
    # growth_score = percentile_rank(revenue_growth)
    pass
```

**B2. 在 Scanner tab 中加入因子筛选条件**
- 已有 universe_a/hk 展示
- 加入 factor_score 列 + 排序
- 加入概念板块下拉筛选

### Sprint C — 信号质量提升（1-2小时）

**C1. swing_signals.py 新增信号**
- `BULLISH_ALIGNMENT`：MA5>MA20>MA60 且价格>MA5
- `CONTROLLED_ADVANCE`：量 < vol_ma20×0.6 且 涨幅>1.5%
- `VOLUME_CLIMAX`：成交量 > vol_ma20×2.5（出货警告）

**C2. VP Score与技术信号联动**
- 当 VP≥65 且 swing_zone=BULLISH → 显示"双重确认"标签
- 在Scanner的Focus stocks行里展示这一联合信号

### Sprint D — 回测增强（2小时）

**D1. 因子回测**
- 用 universe_a 历史快照（已存有每日快照）
- 每月月初按 factor_score 选TOP20，月末计算超额收益
- 对比基准：沪深300 / 中证500

**D2. 换手率控制**
- 当前回测无换手率限制
- 加入：相邻月份重叠率>60%时不交易（减少摩擦成本）

---

## 五、优先级矩阵

| 优化项 | 实现难度 | 预期价值 | 推荐优先级 |
|--------|----------|----------|-----------|
| Tushare `daily_basic` 因子集成 | 低（有token即可） | 高（解锁全市场多因子） | 🔴 第1 |
| 概念板块轮动信号 | 低（东财API已熟悉） | 高（A股板块效应显著） | 🔴 第2 |
| swing_signals 新增3个信号 | 极低（已有框架） | 中 | 🟡 第3 |
| 龙虎榜直接API修复 | 中（需找正确endpoint） | 中（辅助判断） | 🟡 第4 |
| 因子回测 | 中 | 高（验证策略有效性） | 🟡 第5 |
| 大单净流入信号（个股） | 中 | 中 | 🟢 第6 |
| 北向行业分布追踪 | 低 | 中 | 🟢 第7 |
| RS相对强弱（行业内） | 中 | 中 | 🟢 第8 |

---

## 六、工具栈整合建议

基于你提到的工具：

| 你提到的工具 | 当前平台使用方式 | 建议整合方式 |
|-------------|----------------|-------------|
| **Tushare** | 未接入 | 加入 `TUSHARE_TOKEN` GitHub Secret → `fetch_data.py` 新增因子模块 |
| **东财高级筛选** | 已用push2 API | 扩展为概念板块 + 因子组合筛选 |
| **Jupyter Notebook** | 未用 | 用于策略原型验证 → 验证后集成到 `scripts/` |
| **Python回测** | `scripts/backtest.py` 已有 | 扩展为因子回测 + 分组测试 |
| **B站/量化公众号** | 学习渠道 | 转化为具体信号加入 `swing_signals.py` |

---

## 七、下一步行动（按顺序）

1. **申请Tushare Pro积分账户**（免费，需实名认证）→ 添加 `TUSHARE_TOKEN` 到GitHub Secrets
2. **先在Jupyter原型**验证 `daily_basic` 因子分布，确认A股样本内IC（信息系数）> 0.05
3. **集成进 fetch_data.py**（Sprint A1）
4. **Scanner UI加因子列**（Sprint B2）
5. **swing_signals.py增加3个信号**（Sprint C1，最快）
6. **跑一次因子回测**，看TOP20因子组合 vs 沪深300的年化超额

---

---

## 八、社区实测洞察（用户分享的7篇小红书笔记 2026年4月）

> 来源：通过 Claude in Chrome 直接读取用户提供的7篇小红书原始笔记（含 xsec_token 鉴权），获取一手社区反馈  
> 笔记列表：69d078c8 · 69bcd0a6 · 69e4c2d4 · 69e57696 · 69d8f9cb · 69bab577 · 69e0ff50

---

### 8A. 核心战略结论 — "CC时代数据是唯一壁垒"

两篇笔记合并出了一个关键结论，对我们平台架构有直接影响：

**来源1（69e57696，FinceptTerminal，开源点子王）**：介绍6.5k Star的开源Bloomberg平替（C++20构建）。社区高赞评论：
> "CC时代技术不是问题，最贵是数据和API权限"

**来源2（69d8f9cb，TradingAgents多LLM框架，数分魔）**：展示基于多个LLM的A股分析工具（新闻+技术+情绪模块，2026年3月更新）。社区反应冷淡，高赞评论：
> "垃圾，不如直接给CC"

**综合结论**：社区正在从"多LLM协作"向"单一强模型（Claude Code）+ 高质量数据"收敛。这与我们的平台架构完全一致——技术层不是壁垒，数据接入层才是。

**对平台的直接影响**：维持"Claude驱动 + Tushare Pro + 东财API"架构，不需要引入多LLM框架；把精力放在数据质量和因子完整性上，而不是引入更多模型。

---

### 8B. 做市商砸盘机制 — AS模型与CVD信号（69e0ff50）

**来源**：0x.Jason（英国），"做市商'砸盘'的核心逻辑｜AS模型"

**核心机制**（Avellaneda-Stoikov模型）：
做市商不是随机砸盘，而是在管理自身库存风险：

- **保留价格**（Reservation Price）= 市场中间价 − (γ · σ² · q · T)
  - q = 做市商当前持仓（Inventory），γ = 风险厌恶系数
  - **当库存 q > 0（持有大量多头），保留价格低于市场价**→ 做市商倾向于通过调宽卖价、收窄买价来"卖出库存"→ 流动性撤出 → 价格下行
- **Inventory Skew（库存偏斜）> 0** = 高概率砸盘前兆

**实操信号 — CVD（累计成交量差）**：
- CVD = Σ(主动买成交量 - 主动卖成交量)
- CVD 持续走高但价格不涨 → 做市商在用报价压制价格、消化库存 → 短期做空信号
- CVD 急跌 + 价格快速下行 → 库存释放完毕 → 可能反弹机会

**与我们平台的接口点**：
- 东财 `/api/qt/stock/fflow/kline/get` 已有大单净流入数据，可计算近似CVD
- 加入 `swing_signals.py`：`CVD_BEARISH_DIVERGENCE`（价涨量差缩）、`CVD_FLOOR_FORMED`（量差急跌后趋稳）

---

### 8C. Barra因子风险模型 — 私募标配（69bab577）

**来源**：Quant量化学习站，"刚进私募，建议先吃透这套多因子风险模型"（108条评论）

**核心内容**：Barra CNE5/USE4 Python实现：
- CNE5 = 中国股票5因子模型：市场、规模、动量、波动率、价值
- USE4 = 美股4因子扩展版（加上成长因子）
- **私募标配层级**：这不是选股因子，而是**风险归因模型**——解释组合收益来源是来自因子暴露还是个股alpha

**社区热度**：108条评论，付费代码有人买。说明这是量化学习者的核心痛点。

**与我们平台的接口点**：
- 当前阶段：我们在做"选股因子"（PE/PB/ROE排名），还没到Barra层级
- v16.x 升级路径：用Barra分解来验证我们的因子组合是否有真实alpha，还是只是规模/风格暴露
- 近期可做：引入规模因子（市值）+ 波动率因子到 `score_universe()`，这是Barra CNE5子集

---

### 8D. Claude Code作为交易辅助Agent — OpenClaw实践（69bcd0a6）

**来源**：魅力谢玛丽，"open claw已全面介入我的交易决策"

**核心实践**：
- **OpenClaw（龙虾）**：基于Claude Code的自定义Agent，已全面接管美股/港股交易决策
- 数据来源：同花顺App（iFind数据通过App访问）
- 自定义Skills：入场规划（Entry Planning）+ 实时监控（Real-time Monitoring）
- 工作方式：将股票数据 → 喂给Claude → 生成结构化分析 → 辅助交易决策

**社区讨论亮点**：
- OpenClaw侧重US/HK市场，A股支持尚未完整
- 最大价值在于"结构化决策流程"，而非AI预测准确率

**与我们平台的接口点**：
- 我们已有DeepResearch框架，本质上就是"研究层OpenClaw"
- 差距：缺少实时监控hook（价格触发 → 自动重新分析）
- v15.x 可考虑：当持仓股票触发swing_signal → 自动触发DeepResearch快速更新

---

### 8E. Claude Code UI生成工具 — aidesigner MCP（69d078c8）

**来源**：前端AI探索 账号，"Claude Code终于会做UI了"（视频，04-04 福建，12条评论）

**核心内容**：
- **问题**：Claude Code做UI设计非常单一——千篇一律的Inter字体、紫色渐变、卡片宫格
- **解决方案**：aidesigner MCP，专门补全Claude Code的UI设计能力
- **社区评测**（ref_67高赞评论）：
  > "aidesigner对复杂交互状态管理（表单联动、路由守卫）还是力不从心，目前更适合做静态页面和组件级UI"

**与我们平台的接口点**：
- 我们的Dashboard.jsx也有"紫色渐变 + 卡片宫格"同质化问题
- 下次做前端重构时可以试用aidesigner MCP生成初版UI
- **现阶段不做**：我们的痛点是数据和逻辑层，UI够用即可

---

### 8F. 量化入门确认 — MA交叉策略仍是社区起点（69e4c2d4）

**来源**：momo，"量化入门｜移动平均线交叉策略🔥"（04-20，辽宁，无评论）

**核心内容**：MA(5) / MA(20) 交叉为买卖信号的标准教程。这是该笔记发布当天（2026-04-20）的新内容。

**战略意义**：
- MA交叉是A股量化入门的标准起点，我们的 `swing_signals.py` 已实现 `BULLISH_ALIGNMENT`（MA多头排列），比这个更完整
- 从社区内容层级判断，我们当前的技术信号已超过"入门教程"层级，处于中阶水平
- 标签 `#大模型 #多模态人工智能 #半导体` 被挂在量化教程下——说明A股量化圈和AI圈有高度重叠的读者群体

---

### 8G. 社区实测 vs. 原有假设 — 差异校正

| 假设 | 7篇笔记反馈 | 调整建议 |
|------|------------|---------|
| 多LLM框架有优势 | 社区明确说"不如直接给CC" | 不引入TradingAgents类多LLM框架 |
| 技术门槛是主要壁垒 | "CC时代技术不是问题，最贵是数据和API权限" | 重点投资数据质量，不是模型复杂度 |
| 做市商砸盘随机 | AS模型解释：库存偏斜驱动，CVD可预判 | 加入CVD信号到swing_signals.py |
| 我们的因子层已足够 | Barra CNE5是私募标配，我们还在基础层 | 近期加规模+波动率因子；Barra归因列入v16.x |
| UI生成需要从头设计 | aidesigner MCP可辅助 | 下次前端重构时试用 |

---

---

## 九、战略方向确认与落地路线（用户指令 2026-04-20）

> 用户对7篇笔记的落地优先级指示，作为后续开发的权威参考

---

### 9A. 🔴 最高优先级 — FinceptTerminal 融合研究

**用户指令**：把这个开源项目学习过来，融入到我们的模型中。看重它的数据和UI。

**FinceptTerminal 核心能力（已研究，来源：GitHub + 官网搜索结果）**：

| 模块 | 内容 | 对我们的价值 |
|------|------|------------|
| 数据源覆盖 | AkShare（A股）、Yahoo Finance、FRED、IMF、World Bank、DBnomics、Polygon | AkShare是关键——A股数据在其数据层 |
| 市场数据 | 19,000+标的，OHLCV实时流，50+技术指标，多时间框架 | 技术指标体系比我们完整 |
| 宏观数据 | GDP/通胀/债券收益率/100+经济指标 | 比我们的RegimePanel数据更丰富 |
| AI模块 | 37个AI Agent（Trader/Investor/Economic/Geopolitics框架），本地LLM支持 | Agent分层思路可借鉴 |
| 风险模型 | VaR, Sharpe, DCF, 组合优化，衍生品定价（embedded Python） | 与Barra方向一致 |
| UI架构 | 原生C++20/Qt6桌面端；网页版用React+TypeScript+Rust | 终端式密集信息布局 |
| 经纪商集成 | 16家broker，多账户交易，PIN认证 | 执行层（我们不做） |
| 编程API | Q3 2026 roadmap — Programmatic API 上线 | **关键节点：届时可作为数据源接入** |

**重要发现**：FinceptTerminal 本身是 C++ 桌面应用，**不能直接嵌入我们的 React 平台**。融合策略分两层：

**Layer 1 — 立即可做：学习其模块架构，移植到我们的 Dashboard**

FinceptTerminal 的模块拆分逻辑对我们 UI 重构有直接参考价值：

```
FinceptTerminal 模块结构（参考）        →  我们 Dashboard 对应 / 缺失
──────────────────────────────────────────────────────────────
Market Overview（全市场概览）           →  Scanner Tab（已有，需增强）
Technical Analysis（50+指标）           →  swing_signals（已有，需扩展）
Economic Dashboard（100+宏观指标）      →  RegimePanel（已有，数据薄）
Portfolio Analytics（VaR/Sharpe）       →  ❌ 完全缺失
Research Assistant（GenAI问答）         →  DeepResearch（已有）
Alternative Data（Reddit/X情绪）        →  ❌ 缺失
Earnings Calendar                      →  ❌ 缺失（已在规划）
```

**Layer 2 — Q3 2026：API接入**

FinceptTerminal 的 Programmatic API 上线后，直接作为数据源接入 `fetch_data.py`：
- 替代或补充 AkShare（他们已解决A股数据接入问题）
- 接入其100+宏观经济指标到我们的 RegimePanel
- 接入其情绪数据（Adanos Market Sentiment）

**近期行动**：
1. 在本地 clone FinceptTerminal 仓库，研究其 `data/` 目录的 AkShare 调用方式（解决我们被封的问题）
2. 参考其 Economic Dashboard 的指标选取，扩展我们的 `api/macro.js`
3. 参考其终端风格 UI，规划我们的 v15 UI 重构方向（替换卡片宫格为更密集的信息面板）

---

### 9B. 🔴 高优先级 — Barra风险模型 + AS模型纳入研究框架

**用户指令**：纳入我们的研究框架。

**Barra CNE5（规划路径）**：

| 阶段 | 行动 | 时间线 |
|------|------|--------|
| 近期（v14.x） | 在 `score_universe()` 加入规模因子（流通市值）+ 波动率因子（20日标准差） | Sprint B1 |
| 中期（v15.x） | 用5因子框架（市场/规模/动量/波动/价值）拆解我们的组合收益 | 下一sprint |
| 长期（v16.x） | 完整Barra CNE5归因：识别我们的alpha是真实alpha还是风格暴露 | 3个月后 |

**AS模型（近期可做）**：

CVD信号加入 `swing_signals.py`，两个新信号：
```python
# 价格涨但CVD持续下降 → 做市商压制中，警惕砸盘
'CVD_BEARISH_DIVERGENCE': price_change > 1% AND cvd_slope < 0 (5日)

# CVD急跌后趋稳 → 库存释放完毕，可能反弹
'CVD_FLOOR_FORMED': cvd_change_1d < -20% AND cvd_change_3d > -5%
```

数据来源：东财 `/api/qt/stock/fflow/kline/get`（`capital-flow.js` 已用过）

---

### 9C. 🟡 中期 — OpenClaw模式作为交易Agent参考

**用户指令**：一个月后落地，现在先做 reference。

**核心架构（学习要点）**：
- Claude Code + 自定义Skills = 结构化交易决策流程
- Skills 分层：入场规划 skill（静态分析）+ 实时监控 skill（事件触发）
- 数据喂入：将股票数据结构化后注入 Claude context

**与我们平台的接口设计（一个月后实现）**：
```
触发条件：持仓股价格变动超过VP阈值
    ↓
自动调用 DeepResearch（快速模式，不跑全流程）
    ↓
输出：更新后的入场/离场建议 → 推送到 morning-report
```

**参考资料**：OpenClaw GitHub（用户待提供链接），或从同花顺App获取数据的具体实现方式

---

### 9D. 🟡 中期 — 技术信号扩展（基于MA社区反馈）

**用户指令**：想让你有更多思路。

当前 `swing_signals.py` 已有：MA多头排列、RSI、成交量比。基于FinceptTerminal的50+指标体系，扩展建议：

| 新信号 | 逻辑 | 实现难度 |
|--------|------|---------|
| MACD金叉/死叉 | DIF上穿/下穿DEA | 低 |
| 布林带突破 | 收盘价突破上/下轨 | 低 |
| KDJ超买超卖 | K>80 超买，K<20 超卖 | 低 |
| 量能背离 | 价创新高但量萎缩 | 中 |
| CVD背离（AS模型） | 见9B | 中 |
| 相对强弱（行业内RS） | 个股涨/行业ETF涨 >1.2 | 中 |

一次性加入前3个（MACD/布林带/KDJ），成本极低，直接在Sprint C1完成。

---

### 9E. 🟢 长期 — aidesigner MCP UI重构参考

**用户指令**：功能完善后改善界面。

**等待条件**：aidesigner MCP对复杂交互状态管理的支持成熟（当前仅适合静态页面）

**届时规划**：
- 参考FinceptTerminal终端风格：多面板、信息密度高、颜色编码
- 用aidesigner MCP生成初版设计稿 → 人工调整交互逻辑 → 集成
- 从"卡片宫格"向"终端面板"的视觉语言迁移

---

*本文档来源：平台现状分析 + A股量化社区通用策略 + 2026年4月用户提供的7篇小红书笔记（通过 Claude in Chrome + xsec_token 直接读取原文）*  
*笔记ID：69d078c8（aidesigner MCP）· 69bcd0a6（OpenClaw）· 69e4c2d4（MA交叉入门）· 69e57696（FinceptTerminal）· 69d8f9cb（TradingAgents）· 69bab577（Barra CNE5）· 69e0ff50（AS模型/CVD）*

---

---

## 十、FinceptTerminal 深度实测分析（Claude in Chrome 全站探查，2026-04-20）

> 来源：通过 Claude in Chrome 直接在用户浏览器中访问 fincept.in（已登录账号 luvyears@outlook.com），实时爬取所有页面内容、性能计时API、JS代码扫描、直接调用每个发现的API端点，得到完整一手数据。  
> 分析范围：全部9个主要路由 + API端点映射 + 数据结构分析 + 技术架构逆向

---

### 10A. 架构纠正 — Web Terminal，非C++桌面

**重要修正**（9A节信息来源是XHS笔记摘要，有误）：

FinceptTerminal 有**两个独立产品**：
1. **Desktop Terminal（C++20/Qt6）** — GitHub开源版，6.5k Star，那是社区推荐的桌面版
2. **Web Terminal（Next.js/React/FastAPI）** — `fincept.in`，这是他们的云版本，**这才是我们能直接学习和对标的版本**

我们通过Chrome探查的是 **Web Terminal**，它的架构：

```
前端：Next.js (App Router) + IBM Plex Mono + #000/#EDE8C8/#FF7722
后端：FastAPI Python（在 /api/market/* 等路由后面代理）
数据库：PostgreSQL（/api/health 返回 database: true）
市场数据：yfinance（API响应明确标注 "source": "yfinance"）
新闻：Bloomberg RSS聚合（/api/rss/world-news）
AI：Claude（研究助手对话）
实时机制：requestAnimationFrame + ~4分钟批量刷新；WebSocket CONN:LIVE（状态栏每秒更新）
GitHub：github.com/Fincept-Corporation/FinceptTerminal
```

**关键启示**：fincept.in 的市场数据后端用的是 yfinance，和我们 `research.js` 里用的同一个数据源。这意味着他们在数据获取上并没有神奇之处——差别在于**API封装层的完整性**和**UI信息密度**。

---

### 10B. 完整路由结构 + 页面功能映射

通过逐一访问所有路由，确认以下完整路由表：

| 路由 | F-Key | 功能 | 对应我们的模块 |
|------|-------|------|--------------|
| `/dashboard` | F1 DASH | 主终端：Agent聊天 + 实时行情 + 新闻 + Watchlist + Most Active | Dashboard 主面板 ✓ |
| `/markets` | F2 MKT | 全市场概览：Equities/FX/Commodities/Fixed Income/Crypto 5个tab | Scanner（部分）|
| `/watchlist` | F3 WL | 自选股（CRUD + 实时价格） | ❌ 缺失 |
| `/portfolio` | F4 PORT | 持仓管理（P&L + 买价 + LIVE价格）| ❌ 缺失 |
| `/news` | F5 NEWS | 新闻聚合（Bloomberg RSS + 分类）| NewsPanel ✓ |
| `/economics` | F6 ECO | 宏观仪表盘（CB利率 + 主权债 + 经济指标）| RegimePanel（薄）|
| `/agentic-world` | F7 AGENTS | 6个自主AI Agent实时监控 | ❌ 无对标 |
| `/history` | F8 HIST | 会话历史（对话记录）| ❌ 无对标 |
| `/research` | sidebar | 单股深度研究（快照 + 财报 + 历史）| DeepResearch ✓ |
| `/dataroom` | sidebar | 私有文档上传与分析 | ❌ 无 |
| `/alerts` | sidebar | 价格提醒 | ❌ 无 |

**404路由**：`/agents`、`/fund-managers`（侧边栏写的是`/fund-manager`，暂未开放）

---

### 10C. 完整 API 端点映射（实测结果）

通过 Performance Resource Timing API + 逐一主动探测，得到完整的 API 端点图：

#### Next.js 层（内部路由，用户会话管理）

```
GET /api/health           → {timestamp, api:true, status:"healthy", database:true}
GET /api/user/profile     → 用户信息（email, plan, credits）
GET /api/user/session-pulse → 心跳（保持会话活跃）
GET /api/auth/clear-session → 登出
GET /api/chat/sessions    → {success, data:{sessions:[], total:0, limit:50}}
GET /api/portfolio        → {data:[]}  （用户持仓列表）
GET /api/watchlist        → {data:[]}  （用户自选股）
GET /api/rss/world-news   → Bloomberg RSS 聚合
GET /api/dataroom/files   → 上传文件列表
GET /api/economics        → 宏观聚合数据（见10D详解）
```

#### FastAPI Python 后端层（代理到 Python 服务）

```
# 批量实时价格（ticker bar + watchlist 用）
GET /api/market/batch/prices?symbols=AAPL,TSLA,NVDA
    → {count:3, prices:{SYMBOL:{price:{symbol,open,high,low,close,volume}, source:"yfinance"}}}

# 批量历史价格（图表用）
GET /api/market/batch/history?symbols=AAPL&period=1mo
    → {count, period, interval:"1d", history:{SYMBOL:[close_prices_array]}}

# 股票搜索
GET /api/market/search?q=AAPL
    → {query, count:10, results:[{symbol,full_symbol,name,price,change_pct,volume,market_cap,sector,type,subtype,exchange,currency,country}]}

# 单股完整快照（Research页面用）
GET /api/market/snapshot/{SYMBOL}
    → {symbol,exchange,price,info:{60+基本面字段},source:"yfinance",cached_for_minutes}

# 单股财务报表
GET /api/market/financials/{SYMBOL}
    → {symbol,frequency,income_statement,balance_sheet,cash_flow,source,exchange}

# 单股历史K线
GET /api/market/history/{SYMBOL}
    → {symbol,exchange,interval,period,start_date,end_date,count,history:{dates:[],prices:[]}}
```

---

### 10D. /api/market/snapshot 数据结构（60+字段，完整清单）

这是最重要的端点，一次调用返回一只股票的所有基本面数据：

**价格层**（6字段）：symbol, open, high, low, close, volume

**公司信息**（14字段）：short_name, long_name, display_name, quote_type, currency, financial_currency, exchange, full_exchange_name, market, industry, industry_key, sector, sector_key, long_business_summary, full_time_employees

**实时报价**（11字段）：current_price, previous_close, open, day_low, day_high, regular_market_price, regular_market_change, regular_market_change_percent, regular_market_volume, bid, ask, bid_size, ask_size

**估值倍数**（8字段）：market_cap, enterprise_value, trailing_pe, forward_pe, price_to_sales_trailing12_months, price_to_book, book_value, trailing_eps, forward_eps, eps_current_year

**成长性**（4字段）：earnings_quarterly_growth, earnings_growth, revenue_growth

**技术面**（8字段）：fifty_two_week_low/high, fifty_two_week_change_percent, fifty_day_average, two_hundred_day_average, average_volume, average_volume_10days

**股权结构**（6字段）：shares_outstanding, shares_short, float_shares, held_percent_insiders, held_percent_institutions, short_ratio, short_percent_of_float

**分红**（6字段）：dividend_rate, dividend_yield, ex_dividend_date, payout_ratio, five_year_avg_dividend_yield, trailing_annual_dividend_rate, trailing_annual_dividend_yield

**财务健康**（12字段）：beta, total_cash, total_cash_per_share, total_debt, total_revenue, revenue_per_share, debt_to_equity, quick_ratio, current_ratio, gross_profits, ebitda, ebitda_margins, operating_margins, gross_margins, profit_margins, return_on_assets, return_on_equity, free_cashflow, operating_cashflow, enterprise_to_revenue, enterprise_to_ebitda, net_income_to_common

**分析师预测**（5字段）：target_high_price, target_low_price, target_mean_price, target_median_price, recommendation_mean, recommendation_key, number_of_analyst_opinions

**结论**：这个端点完全替代了我们在 `research.js` 中手工拼接 yfinance 数据的方式。但由于是他们自己的FastAPI服务，不能直接跨域调用——我们需要**自建同样的 FastAPI 层**，或者直接用 yfinance 本地复现。

---

### 10E. /api/economics 宏观数据结构（实测数据）

```json
{
  "cards": [  // 8个美国核心宏观指标（实时更新）
    {"name":"Core CPI Change (%)", "value":2.7505, "previous":2.8851, "period":"2026-01", "category":"Inflation"},
    {"name":"Labour Productivity Growth (%)", "value":1.401, ...},
    {"name":"Money Supply M2 (USD mn)", "value":22794279, ...},
    {"name":"Nominal GDP Growth (%)", "value":5.9017, ...},
    ...
  ],
  "cbRates": [  // 11+国央行利率 + 最新变动bp
    {"country":"Australia","rate_pct":"3.85","change_bp":"25.0","period":"Feb/26"},
    {"country":"USA","rate_pct":"4.50","change_bp":"-25.0","period":"Mar/26"},
    ...
  ],
  "invertedYields": [  // 67国主权收益率曲线倒挂信号
    {"country":"Australia","details":"52.6 bp | 14.0 bp | 3.0 bp"},
    ...
  ],
  "topYields": [ ... ],  // 最高收益率国家排名
  "topCds": [ ... ],     // 主权CDS信用风险排名
  "categoryCounts": { ... }  // 经济指标分类统计
}
```

**与我们的 RegimePanel 差距**：我们的 `api/macro.js` 只返回10个指标（CPI、PMI、失业率等），没有CB利率对比、没有主权债期限结构、没有CDS数据。这个结构是我们 RegimePanel 扩展的直接参考蓝图。

---

### 10F. Agentic World — 6个实时AI Agent（实测）

访问 `/agentic-world`，确认6个持续运行的自主Agent：

| Agent | 类别 | Velocity指数 |
|-------|------|-------------|
| Global Geopolitical Monitor | 地缘政治 & 冲突 | 9 |
| Market Stress & Crisis Monitor | 市场压力 & 危机 | 8 |
| Energy & Commodities Supply Monitor | 能源 & 大宗商品 | 6 |
| Central Bank Policy Monitor | 央行 & 货币政策 | 5 |
| Global Elections Monitor | 选举 & 政治 | 5 |
| Macro Economic Data Monitor | 宏观经济数据 | 4 |

**运行状态**（截至探查时刻）：
- Total cycles: 8707（持续循环监控）
- Total findings: 8707（累计发现事件数）
- Auto-refresh: 每60秒
- 每个Agent实时产出结构化情报（含Velocity评分，代表信号强度）

**与我们平台的差距**：我们有 Morning Report（每日一次），但没有**持续运行的主题监控循环**。Agentic World 本质上是6个永不停歇的 Perplexity-like 监控循环，各自专注一个宏观主题。

---

### 10G. UI/UX 设计系统（可直接借鉴）

从代码和页面中逆向提取的设计规范：

```css
/* 字体 */
font-family: 'IBM Plex Mono', monospace;  /* 全站等宽字体 */

/* 颜色系统 */
--background: #000000;        /* 纯黑背景 */
--primary-text: #EDE8C8;      /* 米黄主文字 */
--accent: #FF7722;            /* 橙色强调（价格涨/重要数值）*/
--dim: 约 #776A50;             /* 低亮度辅助文字 */
--mid: 约 #AAA080;             /* 中间亮度（标签/描述）*/

/* 布局逻辑 */
terminalShell → terminalHeader + terminalBody + terminalFooter
terminalBody  → [sidebar 导航] + mainContent
mainContent   → contentArea（主内容区）+ 右侧栏（实时数据）

/* 信息密度原则 */
11px 字体；极小 padding；无圆角卡片；用空格对齐代替 grid；
价格 = 橙色；文字 = 米黄；背景 = 纯黑；完全的Bloomberg终端美学
```

**终端交互模式**：
- F1-F8 快捷键导航（无需鼠标）
- 顶部滚动行情 ticker（无限循环）
- 底部状态栏：用户信息 | API版本 | 延迟 | 连接状态 | 时间
- 斜杠命令：`/stocks`, `/crypto`, `/forex`, `/portfolio`, `/watchlist` 等

---

### 10H. 对我们平台的具体集成路线（修订版）

基于实测数据，对 9A 节的集成计划进行修订和细化：

**❌ 原假设纠正**：
- 原计划"Q3 2026等FinceptTerminal开放Programmatic API"——实际上 fincept.in 的 Web API **现在就可以用**（在浏览器里），但跨域限制使我们无法从自己的服务器直接调用
- 正确策略：复现他们的数据层，而不是等待他们的API开放

**✅ 修订后的三阶段计划**：

**第一阶段（v14.3，本周内）— 数据层对齐**
```python
# 在 fetch_data.py 中参考 /api/market/snapshot 的字段结构，
# 用 yfinance 本地复现同样的数据包，直接喂给 DeepResearch

def fetch_stock_snapshot(symbol: str) -> dict:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "price": {...},
        "fundamentals": {
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "target_mean_price": info.get("targetMeanPrice"),
            "recommendation_key": info.get("recommendationKey"),
            # ... 按 10D 节的60+字段全部填充
        }
    }
```

**第二阶段（v15.x，下个sprint）— 宏观层对齐**

参考 `/api/economics` 数据结构，扩展我们的 `api/macro.js`：
- 加入央行利率对比模块（FRED API 已支持）
- 加入主权债期限结构（可用 FRED 或 stooq）
- 加入67国经济指标（World Bank API，免费）
- 目标：`api/macro.js` 响应结构与 `/api/economics` 保持一致

**第三阶段（v16.x）— UI风格迁移**

从"卡片宫格"向"终端面板"的视觉语言迁移：
- 全站字体 → IBM Plex Mono
- 配色 → #000 / #EDE8C8 / #FF7722
- 布局 → terminalShell 框架（header + body + footer三栏）
- 信息密度 → 11px字体、极小padding、无圆角

---

### 10I. 能力差距总结表（更新版）

基于实测，更新 9A 节的差距分析：

| 能力模块 | FinceptTerminal实现 | 我们现状 | 差距等级 | 修复路径 |
|---------|-------------------|---------|---------|---------|
| 市场数据快照 | yfinance 60+字段统一封装 | 散落在多个API中 | 中 | fetch_stock_snapshot() 统一封装（v14.3）|
| 技术分析 | 50+指标（yfinance + ta-lib）| MA/RSI/成交量（6个）| 高 | 加MACD/布林/KDJ（Sprint C1）|
| 全球宏观仪表盘 | /api/economics（CB利率+债券+67国）| 10个美国指标 | 高 | 参考其结构扩展macro.js（v15）|
| 股票搜索 | /api/market/search（全球多交易所）| 无前端搜索 | 中 | yfinance search封装（v14.3）|
| 财务报表 | income/balance/cashflow（完整）| 仅yfinance季报摘要 | 中 | 用yfinance financials复现（v15）|
| 自选股/持仓 | /watchlist + /portfolio（DB存储）| ❌ 无 | 高 | 需要DB（v16）|
| AI Agent持续监控 | 6个主题循环（8700+cycles）| Morning Report（每日1次）| 中 | 增加主题监控循环（v15后期）|
| UI信息密度 | 终端风格（11px/等宽/纯黑）| 卡片宫格（现代web风格）| 高 | v16 UI重构参考之 |
| 新闻聚合 | Bloomberg RSS（实时）| 已有（NewsPanel）| 低 | 直接对标，已完成 |
| DeepResearch | Research Assistant（Claude）| DeepResearch（更完整）| 我们更强 | 无需改变 |

**核心发现**：FinceptTerminal 的技术壁垒比预期低——数据源是 yfinance（和我们一样），UI是纯CSS终端风格（可复制），关键差距在于**数据封装的完整性**（60+字段统一接口）和**信息密度设计**（终端美学）。我们的 DeepResearch 和 Swing Signals 在分析深度上实际超过了他们。

---

*本次新增内容来源：Claude in Chrome 直接访问 fincept.in（tabId 297150974，账号 luvyears@outlook.com），2026-04-20 17:46-17:50 UTC+1*  
*覆盖页面：/dashboard · /markets · /watchlist · /portfolio · /history · /economics · /research · /agentic-world*  
*API实测：/api/market/snapshot/AAPL · /api/market/financials/AAPL · /api/market/batch/prices · /api/market/batch/history · /api/market/search · /api/economics · /api/health · /api/chat/sessions*
