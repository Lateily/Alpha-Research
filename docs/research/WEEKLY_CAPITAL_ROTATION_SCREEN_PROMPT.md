# Weekly Capital-Rotation Screen Prompt v2 (资金去向 + 分 sector 估值)

> **Why v2 exists.** The v1 weekly screen (`WEEKLY_RESEARCH_FACTORY_PROMPT.md`) was a
> *static industrial-factor* screen: it ranked by `PE/ROE/GM/OCF-NI` only. Two structural
> flaws surfaced 2026-06-27:
> 1. It **never looked at where capital was rotating** (板块热度 / 资金去向) — it gave the
>    same answer in a risk-on melt-up or a high-low-switch sell-off.
> 2. Its `GM≥x + OCF/NI≥x` floor is an **industrial caliber that structurally EXCLUDES
>    financials** (banks/brokers have no comparable gross margin) — so when money rotated
>    INTO 券商/非银金融, the screen returned **0 candidates** and pointed nowhere.
>
> v2 fixes both: **LEAD with capital rotation + sector heat, then value each sector by its
> OWN caliber.** Run under `experiments/execution_tracker/discipline_prompt.md` as the
> system prompt. Research infrastructure, **not** investment advice — no buy/sell, candidates
> only. Every number tagged E1/E2/E3/E4 and `[validated]`/`[unvalidated]`.

## 0. Order (never skip, never revert to naive factors)
`data gates → 资金去向 → 板块热度 → 分 sector 估值 → cycle-normalize → red-flags →
intersection → 7 buckets → execution gate → court`. A candidate is never a buy.

## 1. Data gates (any fail → DATA_BLOCKED, stop)
- Universe: `stock_basic` list_status=L, **exclude ST/退 + IPO < 1yr**.
- Clean PE-TTM: `daily_basic.pe_ttm`.
- **ROE-TTM = FY ANNUAL (`fina_indicator` period=YYYY1231), NOT Q1 quarterly.** Q1 ROE
  hides peaks: 宏桥铝 Q1-ROE 13.8 looked moderate; FY-ROE **75%** revealed a cyclical peak.
- GM, OCF/NI (`ocfps/eps`, FY), real **12-1 momentum** (by-date 12mo→1mo close, NOT 1-day tape).

## 2. 资金去向门 — capital rotation (the LEAD step; v1 missed this)
- `moneyflow_ind_dc`, **5-day** net 主力 by industry → rank inflow / outflow.
- **Filter OUT index/style aggregates** (沪深300 / MSCI / 富时罗素 / 标普 / 两融 / 沪深股通 /
  大盘股) — those are membership flows, not sector signals.
- Add `moneyflow_hsgt` (北向). Output the **rotation map**: capital INTO which sectors, OUT
  of which. This frames every candidate below (e.g. 2026-06-27: 券商/非银/CXO IN, AI硬件 OUT
  = 高低切换).

## 3. 分 sector 估值口径 (the KEY fix — value each sector its OWN way)
| Sector | Valuation caliber | NOT |
|---|---|---|
| **金融**(券商/保险/银行/多元金融) | **PB + 股息 + ROE**(历史分位)| ❌ GM/OCF (no comparable GM) |
| **科技/工业/制造** | PE-TTM + ROE-TTM + GM + **OCF/NI≥0.8**(现金转化=floor)| ❌ headline EPS without cash |
| **周期**(有色/钢铁/化工/养殖/煤炭)| **NORMALIZED bridge**(units×ASP×normalized-margin)| ❌ peak EPS / 低PE当便宜 |
| **成长/创新药/CXO** | PE + pipeline/backlog/定点 + 现金 | ❌ peak EPS, 单季年化 |

## 4. Red-flag gates → Quarantine
- **OCF/NI < 0.8** = 利润不转现金(存储 −3.2/−2.3 = headline ROE 漂亮但现金为负).
- 净利率 structurally impossible = one-off(食品 65% 净利率 = 资产处置,好想你).
- **PE > 60 + no floor** = momentum bubble(长飞 388 / 鼎泰 390 / 宏和 863).
- 主力 distributing into the run(接 异动归因 + 资金门).

## 5. Intersection + 7 buckets
Candidate = **资金IN sector × real floor (sector-appropriate) × reasonable valuation ×
NOT peak-cyclical × NOT momentum-bubble.** Bucket:
1. **Registered Court** (excluded). 2. **T1A Deepen** (资金IN + floor + 合理估值).
3. **T1B Precheck** (one unresolved conflict). 4. **Expensive Quality** (high ROE/GM, priced).
5. **Cyclical-Normalization-Required** (low PE may be peak). 6. **Momentum/Theme-Only**
(避雷 — name them explicitly). 7. **Quarantine** (red-flag).

## 6. Output spec
1. **资金去向 rotation map** (inflow / outflow sectors, with the index-aggregate filter applied).
2. **Candidates by theme**, each with its **sector-appropriate** valuation
   (金融=PB/股息/ROE-分位 · 科技=PE/ROE-TTM/GM/OCF · 周期=normalized · 成长=PE+pipeline).
3. **10-20 quick + 3-5 deepen**, each: code · name · sector · 估值(口径标注) · floor ·
   catalyst · key risk · next gate.
4. Explicit: **"this is not a buy list"**; name what **NOT** to research despite momentum.
5. **⚠ One-week 资金 ≠ confirmed rotation** — need **2-3 weeks** persistence before treating
   as a style shift; do not chase a one-week flight (esp. if the week ended RISK_OFF).

## 7. Execution gate (Line B) on the top-tier
Seven gates (市场 → 板块 → 资金 → 技术 → 执行门 posture → 组合β → 自审), posture-only enums
(`NO_CHASE / HOLD_OBSERVE / WARNING / RECLAIM_REVIEW / DE_RISK_REVIEW / EXIT_REVIEW`),
`sample_eligible:false`, `no_trade_flag:true`. Market closed (weekend) → run the static
**last-settled-close** read and flag it; the true intraday gate runs on a trading day via
`realtime_quote(src='sina')`.

## 8. Discipline (every output)
No buy/sell — posture + levels + triggers only. E1/E2/E3/E4 on every material number.
DATA_CONFLICT halts (primary exchange data > media; 股吧/百度 social = CROWDING_SIGNAL, never
edge). `[validated]`/`[unvalidated]`. Bidirectional: don't oversell, don't false-kill a clean
floor. End with the literal line:

**不是买卖指令；研究信号，human executes。**
