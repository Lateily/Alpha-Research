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

## Layer D — NARRATIVE OVERLAY (USP 核心层)

> 这一层是平台的差异化所在。把它做深 = USP。

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

**为什么是 USP：** 99% 外资 PM 不具备这个解码能力；国内卖方有政策
敏感度但缺国际框架严谨度。我们处在中间，能两边解读。

### D2. 国内叙事追踪 (China-Specific)

**问题：** 国内散户 / 机构在炒什么叙事？与国际定价逻辑的 gap 是什么？

**Sub-modules:**
- D2.1 — 雪球 / 东方财富 评论区话题 trending
- D2.2 — 微博 / 知乎 财经热度
- D2.3 — 国内卖方 vs 国际卖方 共识差距
- D2.4 — 散户买入热度 (从龙虎榜推算)
- D2.5 — 题材轮动节奏 (AI / 算力 / 机器人 / 出海 / 等)

**为什么是 USP：** Gap 本身就是 alpha。国内炒作的叙事和国际机构的
定价逻辑不一致时——leading indicator。

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

**为什么是 USP：** 没人同时做了国际 + 国内派的全谱。

---

## 应用流程

### 每只股票的 research session 必走流程

```
1. 读 STATUS.md (大局感知)
2. 读 THESIS_PROTOCOL.md (7 步骨架要求)
3. 读 INVESTMENT_FRAMEWORK.md (这文件)
4. 走 Layer A (12 个 universal 视角) - 必须全部覆盖, 缺哪个标 N/A 原因
5. 激活 Layer B 中匹配的 sector profile (1-2 个)
6. 应用 Layer C 中匹配的市场 overlay (按 ticker 后缀: .SZ/.SH=A, .HK=HK, US)
7. 应用 Layer D 全部子模块 (USP 核心, 必走)
8. 综合 → 用 7 步 THESIS_PROTOCOL 输出
9. 输出层只展示 top 6-8 最相关视角 (但 trace 保留完整 audit)
```

### 输出层 (展示给 Junyan / 学长 / 客户)

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
