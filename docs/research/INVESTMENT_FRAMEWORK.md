# INVESTMENT FRAMEWORK — 视角库 v1

> **强制读取协议** — Every research session, every Deep Research generation,
> every screening pass: read this file FIRST. The AI must walk through ALL
> applicable layers (universal + sector-specific) before producing a thesis.
>
> **Coverage philosophy:** 先加法再减法。底层分析 cover 全部相关视角；
> 输出层只展示对该股票最相关的 top 6-8 视角（带可追溯 trace）。

---

## 框架结构

```
┌──────────────────────────────────────────────┐
│  Layer A: UNIVERSAL  (适用所有股票)           │
│  → 12 个视角, 每只股票必须全部走一遍           │
├──────────────────────────────────────────────┤
│  Layer B: SECTOR-SPECIFIC  (按行业激活)        │
│  → 8 个 sector profile, 每个 +6-12 个特定视角 │
├──────────────────────────────────────────────┤
│  Layer C: GEOGRAPHIC OVERLAY  (按市场)        │
│  → A股 / HK / US 各自的特殊维度                │
├──────────────────────────────────────────────┤
│  Layer D: NARRATIVE OVERLAY  (USP 核心)       │
│  → 国内 vs 国际叙事 gap; 政策信号解码         │
└──────────────────────────────────────────────┘
```

---

## Layer A — UNIVERSAL (12 个视角，所有股票必走)

### A1. 业务模式分析 (Business Model First-Principles)
**问题：** 这家公司**物理上**怎么赚钱？产品/服务从哪里来，到谁手里，
钱从哪个环节流向公司？

- 价值链位置 (上游/中游/下游)
- 收入结构 (产品 line / geography / customer)
- 客户集中度 (前 5 大客户占比)
- 供应商集中度
- 单位经济模型 (一单赚多少)

**关注指标：** Customer concentration, Supplier concentration, Revenue mix.

### A2. 护城河 (Moat / Competitive Advantage)
**问题：** 为什么这家公司不会被竞争对手轻易复制？

- 类型: scale / network effect / switching cost / brand / regulatory /
  patent / cost advantage / technology
- 强度评级 (None / Narrow / Wide)
- 持续性 (能维持几年)
- 是否在变强还是变弱

**参考人物：** Buffett, Pat Dorsey

### A3. 盈利能力 (Profitability Quality)
**问题：** 公司赚的是真钱还是会计利润？

- ROE / ROIC / ROA 趋势
- Operating margin / Net margin / FCF margin
- Earnings quality (FCF / NI ratio)
- Working capital cycle

**关注阈值：** ROE > 15%, FCF/NI > 0.7×, 趋势是否在改善

### A4. 财务健康 (Financial Health)
**问题：** 公司能熬过下一个周期低谷吗？

- D/E ratio, Net debt / EBITDA
- Current ratio, Quick ratio
- Interest coverage
- 自由现金流稳定性 (CV)

### A5. 增长质量 (Growth Quality)
**问题：** 增长是高质量 (organic + margin-expanding) 还是低质量
(M&A-driven + margin-compressing)？

- Revenue growth (3yr / 5yr CAGR)
- Earnings growth vs revenue growth (operating leverage)
- Organic vs M&A breakdown
- Reinvestment rate vs ROIC (g = retention × ROIC)

### A6. 估值多视角 (Valuation Triangulation)
**问题：** 现在的估值在哪个分位? 多个视角是否一致？

- FCF DCF (rdcf engine)
- EV/EBITDA vs sector / history
- P/E vs sector / history / growth-adjusted (PEG)
- P/B vs ROE-justified P/B
- Residual Income / EBO
- 已有 AHF-2 multi-method triangulation 覆盖

### A7. Catalyst 识别 (Catalyst Inventory)
**问题：** 接下来 6-12 个月有什么具体事件可能引发重定价？

- Earnings revisions (consensus 上修/下修轨迹)
- Product launches
- Policy changes
- Industry inflections
- Management changes
- Capacity expansion / 产能投放节奏
- Supply chain shifts
- M&A possibility

**对应 Step 1 of THESIS_PROTOCOL**

### A8. 风险列表 (Risk Inventory — 不是泛泛的"市场风险")
**问题：** 具体什么风险会让 thesis 失效？

- 主要风险 (rank by likelihood × impact)
- 监管风险
- 客户集中风险 (单一客户流失)
- 技术替代风险
- 竞争加剧风险
- 宏观敏感性 (利率 / 汇率 / 大宗)

### A9. 管理层评估 (Management Quality)
**问题：** 管理层能力 + 利益对齐如何？

- Track record (上一个周期表现)
- 薪酬结构 (与股东利益对齐？)
- 资本配置历史 (回购 / 分红 / M&A 是否明智)
- 沟通透明度

**参考人物：** Buffett, Lynch (the "story")

### A10. ESG 维度 (Environmental, Social, Governance)
**问题：** 长期视角下，ESG 风险/机会是否影响估值？

- 环保: 碳排放 / 监管风险 / 转型机会
- 社会: 劳动关系 / 客户信任
- 治理: 董事会独立性 / 利益相关方处理

注：A 股 ESG 数据稀缺；不强求完整覆盖，但应标记缺失。

### A11. 流动性 + 持仓结构 (Liquidity / Ownership)
**问题：** 这只股票的"票面"特性？

- 日均成交额 (能否执行我们的仓位)
- 机构持仓占比
- 大股东 / 关联方 / 国资背景
- 解禁压力 / 增持/减持轨迹

### A12. Tail Risk + Fragility (Taleb 视角)
**问题：** Black swan 情景下能扛吗？

- F1 leverage / F2 liquidity / F3 tail risk / F4 vol regime / F5 max
  drawdown (已有 fragility_score.py 覆盖)
- F6 concentration (已有, 单资产 / 客户 / 业务集中)

---

## Layer B — SECTOR-SPECIFIC (按行业激活的特殊视角)

每只股票应该至少匹配 1-2 个 sector profile。多元化业务的公司可能
匹配多个。

### B1. Tech / Semiconductor / AI Infrastructure

**当前 watchlist 适用：** 300308.SZ Innolight

**特定视角：**
- B1.1 — 技术周期位置 (制程节点 / 产品代际)
- B1.2 — Hyperscaler CapEx 关联性 (NVDA / MSFT / GOOGL / META / AMZN
  CapEx 周期)
- B1.3 — 单产品 ASP 趋势 + 制程升级红利
- B1.4 — Customer concentration 容忍度低 (Tech 客户切换快)
- B1.5 — R&D / Sales 比率 (高 R&D 是护城河, 低 R&D 是衰落信号)
- B1.6 — Geopolitical exposure (中美科技博弈影响)

**关键指标：** Capacity utilization, Backlog, Order book vs revenue,
ASP/cost per unit trends.

### B2. Internet / Platform / Software

**当前 watchlist 适用：** 700.HK Tencent, 9999.HK NetEase

**特定视角：**
- B2.1 — DAU / MAU 趋势 (用户量 + 时长)
- B2.2 — ARPU 趋势 (变现能力)
- B2.3 — 内容 / 网络效应强度
- B2.4 — 监管风险 (国内特别强 — 游戏审批 / 数据安全 / 反垄断)
- B2.5 — 新产品 / 新业务线 success rate
- B2.6 — Capital allocation: 投资组合 (Tencent 投资版图) / 回购节奏
- B2.7 — AI 落地能力 (大模型自研 vs 外采)

**关键指标：** DAU / MAU / ARPU / Time spent / Top 10 game LTV / 投资
组合估值 / 回购金额。

### B3. Healthcare / Biotech / Pharma

**当前 watchlist 适用：** 6160.HK BeOne (BeiGene)

**特定视角：**
- B3.1 — Pipeline stage matrix (Phase 1/2/3 / NDA / Approved / Launch)
- B3.2 — Single-asset concentration risk (集中在某一个 catalyst 上)
- B3.3 — Clinical readout calendar (具体数据公布时间)
- B3.4 — Regulatory risk (FDA / NMPA / EMA approval probability)
- B3.5 — Competitive landscape (同适应症竞品 launch 节奏)
- B3.6 — Patent cliff timing
- B3.7 — Insurance / 医保 reimbursement (国内特别重要)
- B3.8 — Reimbursement-pricing dynamics (集采压力)
- B3.9 — Cash runway (临床期公司能撑多久)
- B3.10 — Single-asset valuation (rNPV) when applicable

**关键指标：** Pipeline NDA timing / Phase 3 readout success rate /
Cash runway / Peak sales estimate per drug × probability of approval.

### B4. Auto / Auto Parts / NEV

**当前 watchlist 适用：** 002594.SZ BYD

**特定视角：**
- B4.1 — 销量趋势 (月度交付量 + 同比)
- B4.2 — 产品 mix shift (高端化 / 海外占比)
- B4.3 — 新车型周期 (新车上市节奏)
- B4.4 — 电池技术路线竞争力 (LFP / NMC / 固态)
- B4.5 — 海外市场扩张 (出口占比 + 本地化产能)
- B4.6 — 上游成本传导 (锂 / 钴 / 镍 价格)
- B4.7 — 产能利用率 + 折旧节奏
- B4.8 — Warranty / Quality issue 暴露
- B4.9 — 政府补贴依赖度 (退坡影响)
- B4.10 — 智能驾驶 / 自研能力

**关键指标：** Monthly delivery (M/M, Y/Y), 产品结构均价, 出口占比,
ASP, 单车毛利, 海外建厂进度。

### B5. Financials / Banks / Insurance
*(暂无 watchlist 覆盖，留作扩展)*

特定视角骨架：NIM / NPL / Loan growth / 拨备覆盖率 / 资本充足率 /
数字化转型 / 财富管理收入占比 ...

### B6. Consumer / Retail / Brand
*(暂无 watchlist 覆盖)*

特定视角骨架：Same-store sales / 渠道结构 / 品牌强度 / 海外扩张 /
DTC 占比 / 库存周转 ...

### B7. Industrials / Manufacturing / Capital Goods
*(暂无 watchlist 覆盖)*

### B8. Energy / Materials / Cyclicals
*(暂无 watchlist 覆盖)*

---

## Layer C — GEOGRAPHIC OVERLAY

### C1. A 股特殊维度

**当前 watchlist 适用：** 300308.SZ, 002594.SZ

- C1.1 — 政策导向 (五年规划 / 行业政策 / "新质生产力" 主题)
- C1.2 — 国资背景 (国企 / 央企 vs 民企 — 估值 + 治理差异)
- C1.3 — 北向资金流入 / 流出 (外资定价权)
- C1.4 — 龙虎榜 / 大单流向 (机构 vs 散户)
- C1.5 — 机构调研频率 (公司透明度 + 关注度)
- C1.6 — 限售股解禁
- C1.7 — IPO/再融资压力 (大股东减持节奏)
- C1.8 — 监管环境 (证监会处罚 / 退市风险)
- C1.9 — A/H 价差 (如有 H 股) — arbitrage signal

### C2. HK 特殊维度

**当前 watchlist 适用：** 700.HK, 9999.HK, 6160.HK

- C2.1 — 沪深港通持仓变化 (南向资金)
- C2.2 — 美元资金敞口 (美联储利率敏感)
- C2.3 — 中概股回港 / 双重上市动态
- C2.4 — 离岸人民币汇率影响
- C2.5 — 港交所流动性变化 (新股发行节奏)
- C2.6 — 大股东 / 创始人股权结构

### C3. US 特殊维度
*(目前 watchlist 无, 但 leading_indicators 跟踪 NVDA/MSFT/GOOGL)*

- C3.1 — 13F filing changes (机构持仓季度变化)
- C3.2 — Options market positioning (gamma squeeze 风险 / 看涨看跌比)
- C3.3 — Short interest / Days to cover
- C3.4 — Insider buying / selling (Form 4 filings)
- C3.5 — Index inclusion / exclusion catalysts
- C3.6 — 美联储政策敏感性 / 美元强弱

---

## Layer D — NARRATIVE OVERLAY (中国 + 跨框架视角)

> **2026-05-02 重新定位 (Junyan):** 这层不再被框架为"USP 核心层" — 大投行
> 和 hedge fund 也深耕单国市场, single-country deep-dive 不是 unique edge.
> 但**这些视角仍然必走** — 它们是分析严谨度 baseline, 不是 alpha 卖点.
> 历史上的 USP framing 保留在 `docs/strategy/USP_VISION.md` 作为思考过程.

### D1. 政策信号解码 (China-Specific)

**问题：** 最近的政策文件 / 五年规划细则 / 产业政策对这家公司的具体
影响是什么？

**Sub-modules:**
- D1.1 — CSRC 发文追踪 (监管风向)
- D1.2 — 国务院 / 工信部 / 发改委 产业政策追踪
- D1.3 — 专项扶持 / 补贴政策 (如新能源 / 半导体 / AI)
- D1.4 — 集采 / 反垄断 / 数据安全 等监管压力
- D1.5 — 政策事件 → 公司影响链 (类似 Thesis Protocol Step 2 mechanism)

**数据源：** 国务院公报 / CSRC 官网 / 巨潮资讯 / 财联社政策口

**为什么这层值得做：** 99% 外资 PM 不具备这个解码能力；国内卖方有政策
敏感度但缺国际框架严谨度。我们处在中间，能两边解读。这是**分析严谨度
的 baseline**，不是 unique edge — 它让 thesis 经得起政策维度的反问，
但不是产品 USP。

### D2. 国内叙事追踪 (China-Specific)

**问题：** 国内散户 / 机构在炒什么叙事？与国际定价逻辑的 gap 是什么？

**Sub-modules:**
- D2.1 — 雪球 / 东方财富 评论区话题 trending
- D2.2 — 微博 / 知乎 财经热度
- D2.3 — 国内卖方 vs 国际卖方 共识差距
- D2.4 — 散户买入热度 (从龙虎榜推算)
- D2.5 — 题材轮动节奏 (AI / 算力 / 机器人 / 出海 / 等)

**为什么这层值得做：** Gap 本身就是 alpha 信号 (国内炒作的叙事和国际
机构定价逻辑不一致时是 leading indicator)。但它**不是产品 USP** — 任何
深耕中国市场的 fund 都会做这个，只是工作量大。

### D3. 跨框架收敛 (Multi-Persona)

**问题：** 用 6-8 个不同投资框架同时分析同一只股票，找出**所有都
同意**的部分（高确定性）和**显著分歧**的部分（值得深挖）。

**Frameworks (扩展现有 AHF-3):**
- 国际派：Buffett (quality), Burry (deep value), Damodaran (DCF
  story-numbers consistency), Soros/Druckenmiller (macro), Lynch
  (story + earnings), Buffett/Munger (quality + price), Klarman
  (value), Pabrai (Buffett-lite)
- 国内派：段永平 (慢慢变富 + 商业本质), 邓晓峰 (产业研究 + 周期),
  但斌 (品牌 + 长期), 林园 (消费 + 简单生意)

**输出：**
- "8 个框架中有 5 个 say BUY" (consensus 高)
- "2 个框架显著分歧的根因 X" (深挖点)

**为什么这层值得做：** 一站式同时跑 8-12 个框架的 cross-check 减少单框架
偏见。但**它本身不是 USP** — 任何严谨买方都会做框架交叉，只是不像我们
这样系统化进 LLM workflow。

---

## Layer E — REFLEXIVITY & TIME-AXIS (相位与时间维度) [v2 NEW]

> **2026-05-02 加入 (Junyan 从天孚通信 pair-trade 复盘提炼):** 一个 thesis
> 不是 0/1 二元判断 ("我们对 vs 市场错"), 而是**三元** ("我们对 + 市场目前
> 看似也对 + 时间会让真相浮出"). Layer E 把这个时间-相位维度系统化, 是
> Step 8 PHASE_AND_TIMING (THESIS_PROTOCOL.md) 的支撑分析层.

### E1. Soros 反身性 (Reflexivity)

**问题：** 价格不只是反映基本面，价格本身**影响**基本面吗？

**核心洞察：** 自我加强的循环 — 股价上涨 → 公司更容易融资 → 真实改善基本面 →
股价进一步上涨。或反向 — 股价下跌 → 评级下调 → 客户流失 → 业绩变差 →
股价进一步下跌。市场**不仅仅**是发现器，市场是参与者。

**应用例子：**
- 中际旭创：1.6T 量产期间股价上涨 → 拿到更多 NVIDIA 订单 (优先供应认证厂) →
  营收实际加速 → 股价继续上涨 (positive reflexivity)
- 天孚通信：如果 Q2 报毛利继续下滑 → 卖方下调评级 → 大客户重新评估供应商
  → 客户份额可能流失 → 进一步业绩压力 (negative reflexivity 启动)

**输出：** thesis 中标识 reflexivity 方向 (positive/negative/none) + 关键
节点 (什么事件激活 / 反转 reflexivity)。

### E2. 价值-价格临时分离 (Buffett 式)

**问题：** 我们的内在价值估算 vs 当前价格是 +X% 还是 -Y%? 这个 gap
**多久会收敛**? Phase 1 (gap 维持) vs Phase 2 (gap 收敛) 的过渡条件是什么?

**核心洞察：** Buffett 强调"市场短期是投票机, 长期是称重机". 这层显式问
"短期 vs 长期"什么时候切换. 给定我们认为 fair value = $X, 当前价格 = $Y,
我们必须回答**什么 catalyst** 让市场从短期投票切到长期称重.

**应用例子：**
- 天孚 short: 我们估 fair value $50 (基于 GM 压缩长期化), 当前 $200.
  Gap = -75%. Phase 1: AI capex 牛叙事维持 → 价格暂时支撑. Phase 2 catalyst:
  连续 2 个季度 GM 跌破 47% → 市场切换到 fundamentals view → 收敛.

**输出：** 内在价值估算 + 当前 gap + catalyst for convergence + 估计
convergence timing.

### E3. Pair-trade 时间错位 (Time Mismatch)

**问题：** Long-side 和 short-side 在同一个 pair-trade thesis cycle 里
**何时各自激活**? 同时进场还是错时进场?

**核心洞察：** 同一行业 cycle (如 AI capex 周期) 内, 行业受益的 long-side
通常**比** 行业受损的 short-side **先激活** — 牛叙事先涨, 然后才出现
分化. 简单地"同时 long+short"会两边吃止损.

**应用例子：**
- Innolight long / 天孚 short pair: AI 普涨期 (Phase 1), 两只都涨,
  short 端被止损. 行业分化期 (Phase 2), Innolight 继续涨, 天孚开始跌.
- **错时进场策略：** Phase 1 重仓 long Innolight + 不开仓 (或轻仓) short
  天孚. Phase 2 catalyst 触发后才把 short 端 size up.

**输出：** pair 的 long/short 各自的 phase entry triggers + sizing curve.

### E4. Shortable-but-not-yet (Junyan 2026-05-02 命名)

**问题：** 我们看到了真相, 市场还没看到, 但**会**看到. 现在该不该 short?

**核心洞察：** "We are right, market hasn't realized yet, but will" 是
最危险的 short setup — 因为"will realize" 的 timing 是 unknown 的, 早进
场会被 carry cost / forced cover 杀死. **正确做法是** Phase 1 不进场 +
等 phase_1_weakening signals + phase_2_catalyst 临近时再 size up.

**应用例子：**
- 天孚 short setup: 我们 2026-04 已经看到 GM 压缩 + 客户集中度风险.
  市场 5 月还没定价这个. 我们**不**现在 short — 等 Q2 财报 (phase_1
  weakening signal) → Q3 财报 (phase_2 catalyst confirm) → 重仓 short.

**输出：** 明确的"not yet"判断 + 等待条件 + 进场触发条件.

### E5. 国际机构资金流验证 (Institutional Flow Cross-Check)

**问题：** 北向资金 (沪深港通) / QFII / 公募外资基金的 flow 方向, 是否
验证我们的 phase 判断?

**核心洞察：** 北向资金 (Tushare moneyflow_hsgt 数据已接, 6000 tier 解锁)
代表国际机构对 A 股的看法. 如果我们的 phase 判断 "Phase 2 即将启动",
但北向资金仍在大幅流入 (即外资仍买入), 说明国际机构没看到我们看到的
真相 — 我们要么对了 (gap 是 alpha), 要么过早 (会被 carry 拖死).

**注意：** 这个视角**不是 USP** (大行 HF 也都跑这个数据), 但它是 Layer E
其他子层的 cross-check 工具.

**应用例子：**
- 天孚 short: 如果北向资金最近 5 日累计流出 (north_money 5d sum < 0),
  这是 Phase 2 catalyst 提前信号. 如果仍大幅流入, Phase 2 timing 推后.

**输出：** HSGT 5d net flow + 5w + 5m 三个时间维度的方向 vs 我们 phase
判断的对照, 一致 / 分歧 / 可疑.

### E6. 散户叙事-机构定价差距 (Retail-Institutional Gap)

**问题：** 国内散户在炒什么? 国际/国内机构在定价什么? Gap 是 alpha 还是噪音?

**核心洞察：** 雪球 / 东财股吧 上的散户讨论密度 + 情绪, 和北向资金 + 卖方
评级形成对照. 散户极度狂热 + 机构在退出 = 拐点信号. 散户冷淡 + 机构在
收购 = 底部信号.

**注意：** 这个视角**不是 USP** (国内多家 fund 跑这个), 但它是 phase 切换
的辅助验证信号 — 当散户情绪和机构 flow 出现明显分歧, 经常是 phase 切换
临近的 leading indicator.

**应用例子：**
- 天孚 short Phase 2 触发条件之一: 散户雪球热度仍极高 + 北向资金 5d 流出.
  Gap = 散户没意识到 + 机构开始撤. 这是经典 phase 切换信号.

**输出：** 散户热度 (post 数 + 多空比) + 机构 flow 方向 + Gap 评估
(aligned/diverged/extreme_diverged).

---

### Layer E 与 Step 8 的关系

```
Step 8 PHASE_AND_TIMING (THESIS_PROTOCOL.md) — 输出:
  phase_1_market_belief / phase_2_reality_recognition / position_sizing_curve

Layer E 视角 (this section) — 支撑 Step 8 输出的分析:
  E1 Reflexivity      → 帮助识别 phase 切换会自我加强还是衰减
  E2 Value-Price gap  → 帮助量化 phase 2 收敛幅度
  E3 Pair-trade timing → 帮助决定 long/short 错时进场
  E4 Shortable-not-yet → 直接 informs short_play.entry_trigger
  E5 国际机构资金流    → cross-check phase 判断 (HSGT data live 2026-05-02)
  E6 散户叙事 gap      → leading indicator for phase switch
```

跑 Layer E 是**为了产出**有质量的 Step 8 phase_timing 字段, 不是独立分析层.

---

## 应用流程

### 每只股票的 research session 必走流程

```
1. 读 STATUS.md (大局感知)
2. 读 THESIS_PROTOCOL.md (8 步骨架要求, v2)
3. 读 INVESTMENT_FRAMEWORK.md (这文件)
4. 走 Layer A (12 个 universal 视角) - 必须全部覆盖, 缺哪个标 N/A 原因
5. 激活 Layer B 中匹配的 sector profile (1-2 个)
6. 应用 Layer C 中匹配的市场 overlay (按 ticker 后缀: .SZ/.SH=A, .HK=HK, US)
7. 应用 Layer D 全部子模块 (中国 + 跨框架视角, baseline 严谨度, 必走)
8. 应用 Layer E 全部子模块 (相位与时间, 支撑 Step 8 phase_timing 输出, 必走)
9. 综合 → 用 8 步 THESIS_PROTOCOL v2 输出 (含 Step 8 phase_and_timing)
10. 输出层只展示 top 6-8 最相关视角 (但 trace 保留完整 audit)
```

### 输出层 (展示给 Junyan / Franky / 客户)

只展示对该股票 thesis **最相关** 的 6-8 个视角。例如 BYD 输出可能聚焦：
- A1 业务模式 (auto + battery)
- B4.1, B4.2, B4.5 (销量, mix, 海外)
- C1.1 (政策导向, 新能源车)
- A6 估值多视角
- A7 Catalyst (新车型 + 海外建厂)
- A12 Tail risk (F6=35 低集中)
- D1 政策解码 (新能源车补贴退坡 + 出海政策)

省略的（仍在底层 trace 中保留）：
- B4.4 电池技术路线 (与 thesis 不直接相关)
- C1.7 限售解禁 (无近期解禁压力)
- ...

---

## 待扩展（后续 KR）

- [ ] 给每个视角写"如何系统化跑数据"的具体脚本指引
- [ ] Layer B5/B6/B7/B8 sector profiles 完整化 (当前只有 watchlist
      覆盖的 4 个 profile 详细)
- [ ] Layer D 的政策解码 + 叙事追踪 数据源接入 (Bridge 5 of STATUS.md)
- [ ] 国内派系 personas (段永平, 邓晓峰...) 加入 persona_overlay.py
      (当前只有国际 3 派)
- [ ] 每个视角的 "什么是好/差/灰色区域" 阈值标准 (避免主观)
