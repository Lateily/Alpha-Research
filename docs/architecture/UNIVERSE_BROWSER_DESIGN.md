# Universe Browser v2 — Design Document

> **Goal:** Transform ar-platform from "5-stock watchlist tool" into a
> coherent **8000+ stock browser** that replaces 同花顺 / 东方财富 web
> functionality for Junyan's daily use.
>
> **Author:** T1 Claude
> **Created:** 2026-05-02 (during Junyan's break — review when back)
> **Status:** PROPOSAL — awaits Junyan approval before execute.

---

## 1. Junyan's actual brief (2026-05-02)

> "我认为一个合格的看股软件呢是第一界面简洁 我们可以删除很多冗余的功能
> 重复界面 我们要首先包括搜索界面 然后包括分类界面 能够根据涨跌幅 PE等
> 技术指标分类 行业分类"

Translation:
1. **First interface must be clean** — delete redundant features and duplicate interfaces
2. **Search interface** required
3. **Categorization interface** by:
   - 涨跌幅 (gain/loss %)
   - PE
   - Technical indicators
   - Industry

Plus earlier ask: K-line + all real-time market data must show for ANY stock,
not just watchlist 5.

---

## 2. Current state audit

### Existing tabs (12 — bloated)

| # | Tab id | Component | Current purpose | Verdict |
|---|---|---|---|---|
| 1 | `desk` | TradingDesk | Watchlist 5 stocks main view (composite/F6/Buf-Bur-Dam/TRI/HSGT badges) | **KEEP** — core view |
| 2 | `scanner` | Scanner | Stress test + regime + macro insight + news | **CONSOLIDATE** into desk sidebar or merge into Browse |
| 3 | `screener` | Screener | Universe browse (basic filter) | **REPLACE** with Browse v2 |
| 4 | `flow` | FlowPanel | Capital flow (北向/南向/龙虎榜/融资融券) | **MERGE** into desk as widget |
| 5 | `earnings` | EarningsCalendar | Earnings calendar | **MERGE** into desk sidebar widget |
| 6 | `paper` | PaperTrading | Paper trading P&L | **KEEP** — separate view, used weekly |
| 7 | `backtest` | BacktestPanel | VP score backtest | **KEEP** — separate view, used monthly |
| 8 | `research` | DeepResearchPanel + Research | Deep Research + per-ticker drill | **KEEP + simplify** — single drill view for ANY ticker |
| 9 | `morning` | MorningReportPage | Morning report | **MERGE** into desk top widget |
| 10 | `tracker` | Tracker | Predictions track record | **KEEP** but rename "Predictions" |
| 11 | `watchlist` | Watchlist | Watchlist component | **DELETE** — duplicates desk |
| 12 | `system` | SystemTab | System status | **KEEP** but minimize |

### Proposed v2 tab list (6 — clean)

```
┌──────────────────────────────────────────────────────────────┐
│  Browse  │  Desk  │  Research  │  Lab  │  Track  │  System   │
└──────────────────────────────────────────────────────────────┘
```

| # | New Tab | Replaces | Purpose |
|---|---|---|---|
| 1 | **Browse** | screener | Universe browser — search + filter + click any stock |
| 2 | **Desk** | desk + scanner + flow + earnings + morning | Watchlist 5 stocks + sidebar widgets (flow / earnings / morning report) |
| 3 | **Research** | research | Deep Research + per-ticker drill (ANY ticker, not just watchlist) |
| 4 | **Lab** | paper + backtest | Paper trading + backtest + future experiments |
| 5 | **Track** | tracker | Prediction track record |
| 6 | **System** | system | Platform status |

**Net:** 12 → 6 tabs. Watchlist tab DELETED. Scanner/flow/earnings/morning consolidated into Desk sidebar/widgets.

---

## 3. Browse v2 — the centerpiece

### 3.1 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browse                                                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  🔍 [Search: ticker, name, industry...]                  [Clear filters] │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─ Filters ─────────────────────────┐  ┌─ Results: 487 stocks ──────┐   │
│  │ Market: [✓ A] [✓ HK] [  US]       │  │ ☆  ticker  name  Last  Δ%  PE │
│  │                                    │  │ ⭐ 300308.SZ Innolight 195  +2.1% 85│
│  │ Industry:                          │  │ ⭐ 002594.SZ BYD     298  -0.5% 22 │
│  │ [✓] 半导体 · 光通信                 │  │ ⭐ 700.HK   Tencent  475  +1.8% 24 │
│  │ [ ] 新能源 · 整车                   │  │    300394.SZ 天孚通信 185 +3.2% 138│
│  │ [ ] 互联网 · 平台                   │  │    300033.SZ 同花顺   95  +0.8% 38 │
│  │ ...                                │  │    ...                              │
│  │                                    │  │                                     │
│  │ PE range: [0]──[●]──[200]          │  │  [< 1 2 3 ... 50 >]    Page 1/50    │
│  │ 涨跌幅: [-10%]──[●]──[+15%]        │  │  Sort: [Mkt Cap ▼]  [Show 25 ▼]    │
│  │                                    │  │                                     │
│  │ Technical:                         │  └─────────────────────────────────────┘
│  │ [ ] RSI < 30 (oversold)            │                                       │
│  │ [ ] MACD bullish cross              │                                       │
│  │ [ ] Above 20MA                     │                                       │
│  │ [ ] 52W high vicinity              │                                       │
│  │                                    │                                       │
│  │ Mkt cap: [50B]──[●]──[3000B]       │                                       │
│  └────────────────────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Filter spec

#### Search box (top, full-width, prominent)
- Type ticker (300308 / 300308.SZ / Innolight / 旭创) → instant filter
- Type industry (光通信 / semiconductor) → filter to that sector
- Auto-complete dropdown after 2 chars

#### Market filter (chip toggle)
- A-share / HK / US (US currently empty universe but stub for future)

#### Industry filter (multi-select tree)
- Top level: 一级行业 (e.g., 半导体, 新能源, 互联网, 医疗, 消费)
- Sub-level: 二级行业 (e.g., 半导体 → 光通信 / 存储 / 设计)
- Source: enriched from Tushare `stock_basic.industry` field
- Default: all selected

#### PE range slider
- 0 to 200 (cap; >200 grouped as "PE > 200")
- Two-handle range slider
- "PE = NM" filter (loss-makers) — separate checkbox

#### 涨跌幅 (today's gain/loss %) range
- -20% to +20% range
- Two-handle slider
- Default: full range

#### Technical indicator filters (checkbox)
- RSI < 30 (oversold)
- RSI > 70 (overbought)
- MACD bullish cross
- MACD bearish cross
- Price above 20-day MA
- Price within 5% of 52W high
- Price within 5% of 52W low
- Volume spike (today vol > 2x avg)

**Note:** Technical indicators currently computed only for watchlist 5 stocks (`signals_*.json`).
For universe (8000+), need either:
- (a) Lazy compute on filter activation (slow, complex)
- (b) Pre-compute essentials nightly via `swing_signals.py` extended to universe (6h pipeline cost)
- **Decision: defer to KR3.** Initial v2 ships with 4 client-side computable filters (above 20MA, 52W high vicinity, volume spike) using daily OHLCV data; rest deferred.

#### Market cap range
- 50B to 3000B RMB (or HKD/USD equivalent normalized)
- Two-handle slider

### 3.3 Result table

Columns:
- ⭐/☆ — watchlist toggle (one-click add/remove)
- ticker (clickable → drill into Research)
- name (Chinese + English alt-text on hover)
- Last price (with currency)
- Δ% (today's change, color-coded)
- Volume (formatted, e.g., "2.3M shares" or "¥1.5B turnover")
- PE (or "NM" for loss-makers)
- Mkt Cap
- Industry tag (chip, clickable → filter to industry)
- HSGT 5d flow indicator (only A-shares — small badge ↑/↓/=)

**Sortable** by any column. Default: market cap descending.

### 3.4 Pagination + performance

8000+ stocks × ~10 columns = 80k cells if rendered all. Solutions:
- Virtual scrolling (react-window) — but adds dep, defer for now
- **MVP:** Pagination, 25 / 50 / 100 / 250 per page
- Filter applied to dataset, then paginated

---

## 4. Lazy K-line / financial fetch (KR2)

### 4.1 Problem
- watchlist 5 stocks have full data (OHLC / financials / signals etc.)
- universe 8000+ stocks have only basic info (ticker / price / PE / etc.)
- Click on universe stock → "No OHLC data" — broken UX

### 4.2 Architecture

```
User clicks stock in Browse v2
    ↓
Frontend checks: is ticker in watchlist?
  Yes → load existing local files (current pattern, fast)
  No  → call /api/lazy-quote?ticker=X
    ↓
Vercel serverless endpoint:
  1. Check cache (in-memory or Vercel KV)
     - Cache hit (< 1 day old) → return cached
     - Cache miss → fall through
  2. Fetch from upstream:
     - A-share: Tushare daily + daily_basic + financial_data
     - HK / US: yfinance via Python script OR direct
  3. Cache + return
    ↓
Frontend renders (PriceChart, financial summary, etc.)
```

### 4.3 New endpoint: `/api/lazy-quote.js`

Vercel serverless function. Returns:
```json
{
  "ticker": "300033.SZ",
  "fetched_at": "ISO timestamp",
  "cache_age_min": 12,
  "ohlc": [{"date":"2026-04-30","open":...,"close":...,"volume":...}, ...],
  "fundamentals": {"pe":38, "pb":4.2, "market_cap":..., "revenue_growth":...},
  "signals": {"rsi14":52, "above_20ma":true, "macd":"bullish_cross"}
}
```

### 4.4 Cache strategy
- 1-day cache for OHLC (refresh after market close)
- 7-day cache for financials (slow-change)
- In-memory if Vercel function warm, fallback to no cache (cold start ok — slow but correct)
- Future: Vercel KV or Redis (cost; defer)

### 4.5 Rate limit / cost

- yfinance: free, no rate limit (but slow per call)
- Tushare 6000-tier: 200 req/min (200 stocks/min if 1 API call/stock)
- Worst case 8000 stocks × 1 day cache = 8000 fetch/day = ~40 min compute + 8000 API calls
- Cache HIT rate target: 80%+ (most users browse same popular stocks repeatedly)

---

## 5. Industry classification data layer (KR1, prerequisite for filter)

### 5.1 Source
Tushare `stock_basic` API returns per ticker:
```json
{"ts_code": "300308.SZ", "name": "中际旭创", "area": "山东", "industry": "光器件", ...}
```

### 5.2 Implementation
- New script: `scripts/enrich_universe_industry.py`
- Reads `public/data/universe_a.json` + `universe_hk.json`
- Calls `pro.stock_basic()` for A-share (covered by 6000 tier)
- For each stock in universe, adds `industry` field
- Writes back enriched universe JSON
- Run on demand (not in pipeline yet — manual one-time enrich, then periodic)

### 5.3 Output schema addition
```json
{
  "ticker": "300308.SZ",
  "industry": "光器件",
  "industry_l1": "电子",            // 一级行业 (computed via Tushare's classification or inferred)
  "industry_l2": "光通信"           // 二级行业 (sub)
  // ... existing fields
}
```

### 5.4 HK / US industry
- HK: yfinance `info.industry` field (already pulled in fetch_data.py per stock; needs universe-wide enrichment)
- US: yfinance same
- Defer HK/US enrichment to v2.1 (initial ships A-share industry only)

---

## 6. Implementation plan (phased)

### Phase 1 — Data layer + UX shell (after Junyan returns, ~2-3h)

KR-A: **Industry enrichment**
- Write `scripts/enrich_universe_industry.py`
- Run once, commit enriched `universe_a.json`
- ~30 min

KR-B: **Browse v2 UI shell**
- New `Browse` component replaces `Screener`
- Search box (full-width prominent)
- Industry filter (multi-select)
- PE / 涨跌幅 / market cap range sliders
- Sortable result table
- Pagination
- Click → drill into Research tab
- ~2h

KR-C: **Tab consolidation**
- Delete `watchlist` tab (redundant with desk)
- Merge `flow` / `earnings` / `morning` widgets into Desk sidebar
- Rename `screener` → `browse`
- ~30 min

### Phase 2 — Lazy fetch + drill-in (~3h, separate session)

KR-D: **Lazy quote endpoint**
- New `api/lazy-quote.js` Vercel function
- In-memory cache + Tushare/yfinance backends
- ~2h

KR-E: **PriceChart auto-fallback**
- When ticker not in local OHLC, call `/api/lazy-quote`
- Loading state + error handling
- ~1h

### Phase 3 — Real-time + technicals (~3-4h, future session)

KR-F: **Technical indicator filters**
- Pre-compute essential signals for full universe (extend `swing_signals.py`)
- OR client-side compute on top of OHLC pull
- ~2h

KR-G: **Real-time price refresh**
- Auto-refresh visible stocks every 30s
- Sina Finance API or Eastmoney scraping
- ~1-2h

### Phase 4 — Polish (~2h, future session)

KR-H: **Search auto-complete** (typeahead)
KR-I: **Watchlist add-from-browse** flow
KR-J: **Mobile responsive**

---

## 7. Decisions Junyan needs to approve

| # | Decision | T1 recommendation | Junyan |
|---|---|---|---|
| 1 | Tab consolidation 12 → 6 (per §2)? | YES | __ |
| 2 | Delete `watchlist` tab? | YES — duplicate of desk | __ |
| 3 | Browse v2 layout (per §3 wireframe)? | YES as drafted | __ |
| 4 | Phase 1 scope (data + UX shell, no lazy fetch yet)? | YES — ships clean win | __ |
| 5 | Lazy fetch in Phase 2 next session? | YES — separate batch | __ |
| 6 | Real-time refresh in Phase 3 future? | YES — non-blocking | __ |
| 7 | A-share industry first (HK/US later)? | YES | __ |
| 8 | 4 client-side technical filters (above 20MA / 52W high / volume spike) Phase 1, rest defer? | YES | __ |
| 9 | Keep Tracker / Lab / System tabs? | YES | __ |
| 10 | Use existing C.{blue/green/red/...} colors only? (no new design system) | YES — invariant | __ |

---

## 8. Out of scope (explicit)

- **WebSocket real-time** — defer to Phase 3 or later, complex
- **Multi-market simultaneous filter** (e.g., A + US together) — Phase 1 has market chip toggle, no cross-market grouping
- **Stock comparison view** (compare 2-3 stocks side-by-side) — Phase 4
- **Charting overlays** (multi-stock on same chart) — Phase 4
- **Saved filter presets** ("show me Buffett-style stocks I've configured") — Phase 4
- **Backtest from Browse** (run backtest against current filter result) — Phase 5
- **Export results to CSV** — Phase 5

---

## 9. Test gates (each KR)

| KR | Test gate |
|---|---|
| KR-A | `python3 scripts/enrich_universe_industry.py` exit 0 + `jq '.stocks[0] | has("industry")' public/data/universe_a.json` returns true |
| KR-B | `npm run build` exit 0 + JSX balance 0 + Browse tab renders + filter logic works on 5-stock subset |
| KR-C | `npm run build` exit 0 + tab count = 6 + no broken navigation |
| KR-D | Vercel function deploys + `/api/lazy-quote?ticker=300033.SZ` returns valid JSON |
| KR-E | Click universe stock → PriceChart renders with lazy-fetched OHLC |
| KR-F | Universe stock subset returns correct technical filter results |
| KR-G | Visible stocks update price every 30s without blocking UI |

---

## 10. Pre-flight before execute (Junyan return checklist)

- [ ] Read this design doc (5 min)
- [ ] Mark §7 decisions (5 min)
- [ ] Confirm Phase 1 scope OK
- [ ] Approve tab consolidation list
- [ ] Confirm "delete watchlist tab" is OK
- [ ] Then I execute Phase 1 (~2-3h)

---

## Appendix: Why this is the right path (not 同花顺 clone)

### What 同花顺 / 东方财富 do well (we copy)
- Universe browsing
- Industry classification
- Multi-criteria filtering
- Real-time price ticker
- K-line chart

### What 同花顺 does poorly (we improve)
- Buy/sell recommendations (we DON'T do — AI produces signals, human decides)
- Cluttered UI (we keep clean)
- Junk ads / sponsored content (we have none)
- One-size-fits-all view (we have watchlist drill-in for the 5 we care about)

### What we add that they don't have
- VP Score (5-dim composite)
- Triangulated valuation (TRI badge)
- Persona overlay (Buffett/Burry/Damodaran)
- Fragility scoring (F1-F6)
- Step 8 phase_timing (forthcoming once Deep Research used)
- HSGT institutional flow (just shipped)
- Multi-method valuation (3 orthogonal approaches)

**Net:** Browse like 同花顺, drill-in deeper than any competitor.

---

This document is the contract. After Junyan approves §7 decisions, execute Phase 1.
