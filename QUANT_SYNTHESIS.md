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

*本文档来源：平台现状分析 + A股量化社区通用策略 + 2026年4月用户提供的7篇小红书笔记（通过 Claude in Chrome + xsec_token 直接读取原文）*  
*笔记ID：69d078c8（aidesigner MCP）· 69bcd0a6（OpenClaw）· 69e4c2d4（MA交叉入门）· 69e57696（FinceptTerminal）· 69d8f9cb（TradingAgents）· 69bab577（Barra CNE5）· 69e0ff50（AS模型/CVD）*
