# Weekly Screen Prompt v3 — 技术先行 · 快慢因子分层 (Junyan-ratified flow, 2026-07-06)

> **v2 vs v3 — when to use which.** v2 (`WEEKLY_CAPITAL_ROTATION_SCREEN_PROMPT.md`)
> LEADS with capital rotation — best in DEFENSIVE/rotation regimes ("where is money
> hiding"). v3 leads with TECHNICAL structure at the industry level — best in
> OFFENSIVE regimes ("which battlefield has a working trend"). Both end in the same
> Research Decision Pack contract. Weights/thresholds all **[unvalidated intuition]**;
> the Model Paper Fund ledger is the validation engine for the flow itself.
>
> Born from the 2026-07-06 live run where technicals-first correctly filtered two
> traps the flow-first screen had admitted: 公用事业 (资金IN but industry technical
> BOTTOM, −10.3% mom20 = value-trap signature) and 科沃斯 (clean fundamentals, 破MA20
> = entry not ready).

## 0. Regime gate FIRST (the master switch, not a filter)
`RISK_ON / WEAK_REPAIR / RISK_OFF / STYLE_ROTATION` from index + 全市场主力.
It sets (a) whether breakout entries are even valid, (b) the position-size
multiplier, (c) v2-vs-v3 choice. RISK_OFF ⇒ breakout-style entries only
(fill-on-strength), reduced risk budget.

## 1. 行业初筛 — FAST factors only (选战场)
Fast factors move daily; fundamentals do NOT belong at this layer.
- **技术结构** (per 申万L1 index): trend state (px>MA20>MA60 = 2 / >MA20 = 1 / else 0)
  · 20d & 5d momentum · distance to 20d high (breakout proximity).
  **Stale-momentum guard:** high mom20 + negative mom5 + far from high = BROKEN
  structure, not strength (the 电子 false-positive) — human veto required.
- **量化情绪** (no vibes): market level = 涨停家数 / 连板高度 / 成交量分位;
  industry level = 龙虎榜/游资 activity · 乖离度 (crowding penalty — we were burned
  3x by crowded names).
- **资金流向** (industry 5-day 主力, index-aggregates filtered) + crash-day
  跌中承接 read.
- **相对强度 RS** vs 上证/万得全A — separates true leaders from beta.
→ Output: 3-5 battlefields where technicals ∩ sentiment ∩ flows CONVERGE
  (a dimension missing = flag, not average away).

## 2. 消息面 gate (对每个入选行业逐个核)
Hard catalyst (policy/E1 filing/industry data) confirms; hard NEGATIVE catalyst
(e.g. 2027 燃油车补贴退坡 vs 汽车) demotes even a technically-strong industry.
Media narratives = E2, verified against primary before use; 股吧 = crowding signal.

## 3. 个股深研 — SLOW factors (选士兵, within winning industries only)
- **基本面 per sector caliber**: 金融=PB/股息/ROE · 科技=PE/ROE-TTM/GM/OCF≥0.8 ·
  周期=normalized bridge · 成长=PE+pipeline. FY-annual ROE, never Q1-as-TTM.
- **公司资金** (settle moneyflow_dc, 3-5d structure) — price-up/flow-out divergence
  (东方财富 0706) = excluded.
- **事件日历门**: 业绩预告窗口 / 解禁 / 减持 within the holding horizon — mines
  flagged BEFORE entry, not after.
- **个股技术位**: MA20/60 posture · ATR · 20d high/low — "估值好技术没就位" = WATCH,
  not a paper order (不凭感觉编位; levels must exist before registration).

## 4. Output = Research Decision Pack (契约不变)
All 8 sections (Variant View / Clean Valuation / Catalyst Map / Risk+Mitigation /
Execution Gate / Portfolio Impact / Paper Plan / Self-Audit), else REPORT_INCOMPLETE.
Suggested trading strategy = PAPER plans (entry/stop/target/invalidation,
no_trade_flag) + fund slot/theme-cap arithmetic + explicit 避雷 list.
This is not a buy list. 不是买卖指令；研究信号，human executes。
