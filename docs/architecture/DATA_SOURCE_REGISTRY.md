# DATA SOURCE REGISTRY — Single Source of Truth

> **Purpose:** Every data source the platform uses, in ONE registry.
> Defines: auth requirements, tier (free/paid), API patterns, output
> location, downstream consumers, schema invariants, graceful-degrade
> behavior.
>
> **Architecture principle (forward-compatible):**
> Code is written for the **highest tier** of each source. At runtime,
> if the current tier doesn't grant a field, the field is set to `null`
> with a sibling `_status: "tier_locked"` + `_need_tier: <tier_name>`.
> Schema is **always complete**. Consumers test for `null` and gracefully
> degrade. **Never delete a field because it's not yet available.**
>
> Last updated: 2026-05-04

---

## 1. Source Inventory

| ID | Source | Tier | Auth | Tickers | Cadence | Status |
|---|---|---|---|---|---|---|
| `tushare` | Tushare Pro | Paid (15000 pts; base fetcher 6000-compatible) | `TUSHARE_TOKEN` env | A-share | daily | ✅ ACTIVE 2026-05-02 (`scripts/fetch_tushare.py` shipped, pipeline integrated) |
| `capital_flow` | Tushare Pro concept/industry capital flow | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share market-wide boards | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_capital_flow.py`, pipeline Step 2d.6) |
| `chip_distribution` | Tushare Pro 筹码分布 / cost-basis distribution | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_chip_distribution.py`, pipeline Step 2d.7) |
| `consensus_forecast` | Tushare Pro 盈利预测 / analyst consensus forecast | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_consensus_forecast.py`, pipeline Step 2d.8) |
| `lhb` | Tushare Pro 龙虎榜 / daily top-list appearances | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_lhb.py`, pipeline Step 2d.9) |
| `quant_factors` | Tushare Pro 量化因子 / Barra-like daily factor exposures **STRATEGIC** | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_quant_factors.py`, pipeline Step 2d.10) |
| `limit_list` | Tushare Pro 涨停板单 / daily limit-up and limit-down board list | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share market-wide stocks | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_limit_list.py`, pipeline Step 2d.11) |
| `concept_membership` | Tushare Pro concept board constituent stocks | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share market-wide concept membership | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_concept_detail.py`, pipeline Step 2d.12) |
| `inst_research` | Tushare Pro 机构调研 / institutional survey records | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_inst_research.py`, pipeline Step 2d.13) |
| `top_inst` | Tushare Pro 游资数据 / 龙虎榜机构成交明细 | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_top_inst.py`, pipeline Step 2d.14) |
| `broker_recommend` | Tushare Pro 券商金股 / analyst stock recommendations | Paid (15000 pts) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_broker_recommend.py`, pipeline Step 2d.15) |
| `pledge_stat` | Tushare Pro 股权质押 / pledge ratio risk reference data | Paid (5000 pts; active under 15000 account) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_pledge_stat.py`, pipeline Step 2d.16) |
| `restricted_shares` | Tushare Pro 限售股解禁 / restricted-share unlock events | Paid (2000 pts; active under 15000 account) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-03 (`scripts/fetch_restricted_shares.py`, pipeline Step 2d.17) |
| `repurchase` | Tushare Pro 回购 / buyback program events | Paid (5000 pts; active under 15000 account) | `TUSHARE_TOKEN` env | A-share watchlist | daily | ✅ ACTIVE 2026-05-04 (`scripts/fetch_repurchase.py`, pipeline Step 2d.18) |
| `yfinance` | Yahoo Finance | Free | None | Global (HK/US/A) | daily | ✅ ACTIVE |
| `akshare` | AKShare | Free | None | A-share enhanced | daily | ⚠ GeoBlocked on GH Actions |
| `cninfo` | 巨潮资讯网 | Free | None | A-share announcements | event-driven | ✅ ACTIVE (2026-05-02) |
| `hkex` | HKEx Disclosure | Free | None | HK announcements | event-driven | ✅ ACTIVE (2026-05-02) |
| `edgar` | SEC EDGAR | Free | UA email header | US (AI infra basket) | event-driven | ✅ ACTIVE (2026-05-02) |
| `xueqiu` | 雪球 | Free | Scraping | A/HK | hourly (planned) | 🟡 STUB (fragile) |
| `eastmoney_guba` | 东财股吧 | Free | Scraping | A | hourly (planned) | 🟡 STUB (fragile) |
| `cls` | 财联社新闻 | Free + paid tier | Scraping or via Tushare news | China-wide | minute | ⏳ DEFERRED (plan: c — try Tushare news first) |
| `tushare_news` | Tushare news API | Paid (tier ≥ ?) | `TUSHARE_TOKEN` | China-wide | hourly | ⏳ TBD (verify tier) |
| `fred` | FRED Macro | Free + key | `FRED_API_KEY` | US macro | daily | ⏳ DEFERRED |

---

## 2. Per-Source Detail

### 2.1 `tushare` — Tushare Pro (current account tier: 15000)

**Auth:** `TUSHARE_TOKEN` env var (also stored in GitHub Actions secret).

**API call pattern:**
```python
import tushare as ts
ts.set_token(os.environ['TUSHARE_TOKEN'])
pro = ts.pro_api()
df = pro.daily(ts_code='300308.SZ', start_date='20260101', end_date='20260501')
```

**Tier-gated endpoints (base 6000 fetcher + newly unlocked 15000 premium APIs):**

| Endpoint | Tier | What it gives | Consumer |
|---|---|---|---|
| `stock_basic` | 0 | Stock universe | universe builders |
| `trade_cal` | 0 | Trading calendar | scheduling |
| `daily` | 120 | Daily OHLCV | rDCF + technical signals |
| `daily_basic` | 120 | PE/PB/turnover | VP `expectation_gap` |
| `adj_factor` | 120 | Back-adjusted prices | backtest alignment |
| `income` | 2000 | 利润表 | rDCF growth, fundamental_accel |
| `balancesheet` | 2000 | 资产负债表 | F6 concentration, leverage |
| `cashflow` | 2000 | 现金流量表 | M1 FCF DCF |
| `index_daily` | 120 | Index OHLC | benchmark (CSI 300) |
| `dividend` | 120 | 分红送股 | total return |
| **`moneyflow_hsgt`** ⭐⭐ | **6000** | **北向资金** | **USP layer (international institutional flow)** |
| `top10_holders` | 5000 | 前十大股东 | F6 + insider movement |
| **`pledge_stat`** ⭐ | **5000** | **股权质押率 + pledge count/history** | **Risk panel + Bridge 6 portfolio-construction risk weighting** |
| **`share_float`** ⭐ | **2000** | **限售股解禁 events + float ratio** | **Risk panel + Bridge 6 portfolio-construction supply-risk weighting** |
| **`repurchase`** ⭐ | **5000** | **回购 program events + amount/status** | **Research detail card after KR3 frontend ships + Bridge 6 portfolio buyback overlay** |
| `forecast` | 10000 | 业绩预告 | Strongest A-share catalyst signal |
| `express` | 10000 | 业绩快报 | Pre-earnings catalyst |
| `fina_indicator` | 10000? | 财务指标 (ROE/ROA) | fundamental_accel upgrade |
| **`moneyflow_cnt` / candidates** ⭐ | **15000** | Concept-board net inflow | Browse/research capital-flow heat |
| **`moneyflow_ind_dc` / candidates** ⭐ | **15000** | Industry-board net inflow | Browse/research capital-flow heat |
| **`cyq_chips` / candidates** ⭐ | **15000** | 筹码分布 by price level | Support/resistance inference (frontend KR4 queued) |
| **`profit_forecast` / `forecast_predict` candidates** ⭐ | **15000** | Analyst EPS/revenue/profit forecast candidates | Research consensus-vs-our-view delta |
| **`top_list` / candidates** ⭐ | **15000** | 龙虎榜 daily top-list appearances | Research large-fund-activity signal |
| **`top_inst` / candidates** ⭐⭐ | **15000** | 龙虎榜机构 / 营业部成交明细 | Research seat-level 游资 footprint; complements `top_list` |
| **`broker_recommend` / `report_rc` / candidates** ⭐⭐ | **15000** | 券商金股 / analyst recommendation ratings and target prices | Research analyst-signal layer; complements `consensus_forecast` |
| **`limit_list_d` / candidates** ⭐ | **15000** | 涨停/跌停/炸板 daily board list with 连板 context | Browse 封板专化 view |
| **`concept` + `concept_detail` / candidates** ⭐ | **15000** | Concept list and constituent-stock mapping | Browse concept click-through / universe filtering |
| **`stk_surv` / candidates** ⭐⭐ | **15000** | 机构调研 / per-company institutional survey records | Research 调研频次 trend; future VP confluence signal |

⭐⭐ = USP-critical
⭐ = Strong catalyst signal

**Output schema (planned):**
```
public/data/tushare/<ticker>.json
{
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-02T...",
  "current_tier": 6000,
  "data": {
    "daily":          { "rows": [...] },
    "income":         { "rows": [...] },
    "balancesheet":   { "rows": [...] },
    "moneyflow_hsgt": { "rows": [...] },
    "forecast": {
      "rows": null,
      "_status": "tier_locked",
      "_need_tier": 10000,
      "_unlock_action": "Upgrade Tushare to 10000-tier (~¥3000-5000/yr)"
    }
  },
  "completeness_pct": 60
}
```

**Implementation:** ✅ `scripts/fetch_tushare.py` (296 LOC, shipped 2026-05-02,
first three-agent production codegen task; T3 codegen + T2 review).

#### 2.1.1 `capital_flow` — Tushare 15000-tier concept + industry flow

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_capital_flow.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.6, `continue-on-error: true`.

**Output:** `public/data/capital_flow.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Endpoint fallback order:**
- Concept-level flow: `moneyflow_cnt` → `cnt_moneyflow` → `moneyflow_concept` → `concept_moneyflow`
- Industry-level flow: `moneyflow_ind_dc` → `moneyflow_ind` → `industry_moneyflow` → `ind_moneyflow`

**Schema:**
```json
{
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok | partial | endpoint_unavailable",
  "hot_concepts": [
    {"name": "光通信", "ts_code": "xxxx", "net_inflow_yuan": 123000000.0, "pct_chg": 2.1}
  ],
  "cold_concepts": [],
  "hot_industries": [],
  "cold_industries": [],
  "concept_meta": {
    "api_used": "moneyflow_cnt",
    "_attempted_endpoints": ["moneyflow_cnt"],
    "row_count": 86,
    "_status": "ok"
  },
  "industry_meta": {
    "api_used": "moneyflow_ind_dc",
    "_attempted_endpoints": ["moneyflow_ind_dc"],
    "row_count": 31,
    "_status": "ok"
  }
}
```

**Graceful degrade behavior:** Concept and industry sections succeed
independently. If all candidate endpoint names fail for one section because
the API name is wrong, permission/tier is unavailable, or Tushare returns a
not-found response, that section writes empty arrays, `_status:
"endpoint_unavailable"`, and `_attempted_endpoints` with every tried name.
Top-level `_status` is `ok` if both sections succeed, `partial` if one
succeeds, and `endpoint_unavailable` if neither succeeds. The script exits 0
for graceful endpoint unavailability and exits 1 only when auth is missing or
an unhandled process-level exception occurs.

#### 2.1.2 `chip_distribution` — Tushare 15000-tier 筹码分布

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_chip_distribution.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.7, `continue-on-error: true`.

**Output:** `public/data/chip_distribution/<ticker>.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Endpoint fallback order:**
- `cyq_chips` → `chip_distribution` → `shareholder_chips`

**Schema (A-share success):**
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok",
  "api_used": "cyq_chips",
  "chips": [
    {"price": 120.5, "percent": 1.23}
  ]
}
```

**Schema (HK/US/non-A-share placeholder):**
```json
{
  "ticker": "700.HK",
  "fetched_at": "2026-05-03T...",
  "_status": "skipped",
  "_reason": "not_a_share"
}
```

**Graceful degrade behavior:** The fetcher writes one file per watchlist ticker.
HK/US tickers are explicit skipped placeholders. A-share endpoint-name or
availability failures write `_status: "endpoint_unavailable"`,
`_attempted_endpoints`, and `chips: []`. Permission/tier failures write
`_status: "tier_locked"`, `_need_tier: 15000`, and `chips: []`. Per-ticker
failures write `_status: "fetch_failed"` with `_error` and do not stop the
remaining watchlist. The process exits 0 after per-ticker completion and exits
1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because chip concentration by
price level is a direct cost-basis distribution input for resistance/support
inference. Specific resistance/support thresholds are not defined here and
remain `[unvalidated intuition]` until KR4 surfaces and calibrates them.

#### 2.1.3 `consensus_forecast` — Tushare 15000-tier 盈利预测

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_consensus_forecast.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.8, `continue-on-error: true`.

**Output:** `public/data/consensus_forecast/<ticker>.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Endpoint fallback order:**
- `forecast` → `express` → `profit_forecast` → `forecast_predict`

**Schema (A-share success):**
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "tier": 15000,
  "_status": "ok",
  "api_used": "forecast",
  "_attempted_endpoints": ["forecast"],
  "forecasts": [
    {
      "end_date": "20261231",
      "eps": 3.2,
      "revenue": 55000000000.0,
      "net_profit": 9300000000.0,
      "op_income": 12100000000.0,
      "broker_count": 18
    }
  ]
}
```

**Schema (HK/US/non-A-share placeholder):**
```json
{
  "ticker": "700.HK",
  "fetched_at": "2026-05-03T...",
  "tier": 15000,
  "_status": "skipped",
  "_reason": "not_available_tushare_hk",
  "api_used": null,
  "_attempted_endpoints": [],
  "forecasts": []
}
```

**Graceful degrade behavior:** The fetcher writes one file per watchlist ticker.
HK/US tickers are explicit skipped placeholders because Tushare consensus
coverage is A-share-focused for this integration. A-share endpoint-name or
availability failures write `_status: "endpoint_unavailable"`,
`_attempted_endpoints`, and `forecasts: []`. Permission/tier failures write
`_status: "tier_locked"`, `_need_tier: 15000`, `_error`, and `forecasts: []`.
Per-ticker failures write `_status: "fetch_failed"` with `_error` and do not
stop the remaining watchlist. The process exits 0 after per-ticker completion
and exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because the forecast rows provide
the external consensus side of the Research pitch's "market believes X / we
believe Y" delta. Specific forecast values are source data from Tushare when
available; any future consensus-vs-our-view threshold remains `[unvalidated
intuition]` until calibrated against real thesis outcomes.

#### 2.1.4 `lhb` — Tushare 15000-tier 龙虎榜 / daily top list

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_lhb.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.9, `continue-on-error: true`.

**Output:** `public/data/lhb/<ticker>.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Endpoint fallback order:**
- `top_list` → `lhb_detail` → `top_list_daily`

**Fetch strategy:** One market-wide bulk call per run using `start_date` +
`end_date` for a `days_window` of 30 `[unvalidated intuition; task window]`;
the script filters the returned rows into per-watchlist A-share files in
Python. It does not call Tushare once per ticker.

**Schema (A-share success):**
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok",
  "api_used": "top_list",
  "_attempted_endpoints": ["top_list"],
  "days_window": 30,
  "appearances": [
    {
      "trade_date": "20260430",
      "reason": "日涨幅偏离值达到7%的前5只证券",
      "net_amount": 123000000.0,
      "net_rate": 12.3,
      "l_buy": 234000000.0,
      "l_sell": 111000000.0
    }
  ],
  "summary": {
    "total_appearances": 1,
    "total_net_amount": 123000000.0,
    "last_appearance_date": "20260430",
    "top_reason": "日涨幅偏离值达到7%的前5只证券"
  }
}
```

**Schema (A-share with no appearances in the window):**
```json
{
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok",
  "api_used": "top_list",
  "_attempted_endpoints": ["top_list"],
  "days_window": 30,
  "appearances": [],
  "summary": {
    "total_appearances": 0,
    "total_net_amount": 0,
    "last_appearance_date": null,
    "top_reason": null
  }
}
```

**Schema (HK/US/non-A-share placeholder):**
```json
{
  "ticker": "700.HK",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "skipped",
  "_reason": "not_available_tushare_hk_us",
  "api_used": null,
  "_attempted_endpoints": [],
  "days_window": 30,
  "appearances": [],
  "summary": {
    "total_appearances": 0,
    "total_net_amount": 0,
    "last_appearance_date": null,
    "top_reason": null
  }
}
```

**Graceful degrade behavior:** The fetcher writes one file per watchlist
ticker. HK/US tickers are explicit skipped placeholders because this
integration is A-share-only. If every candidate endpoint fails, A-share
tickers write `_status: "endpoint_unavailable"`, `_attempted_endpoints`, and
empty `appearances`. Permission/tier failures write `_status: "tier_locked"`,
`_need_tier: 15000`, `_error`, and empty `appearances`. Per-ticker
normalization/write failures write `_status: "fetch_failed"` with `_error`
and do not stop the remaining watchlist. The process exits 0 after per-ticker
completion and exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because 龙虎榜 is exchange-defined
unusual-trading-activity data and directly supports a large-fund-activity
evidence card. Specific top-list amounts and reasons are source data from
Tushare when available; any future signal threshold or weighting remains
`[unvalidated intuition]` until calibrated against real thesis outcomes.

---

#### 2.1.5 `quant_factors` — Tushare 15000-tier 量化因子 / Barra-like factors **STRATEGIC**

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_quant_factors.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.10, `continue-on-error: true`.

**Output:** `public/data/quant_factors/<ticker>.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** This is the data layer for the AR platform's eventual
"cleaned-up our own quant strategy" (per Junyan 2026-05-03 directive:
"量化因子是我们的主要研究框架线路之一 之后我们要清洗之后形成我们自己的一套
完整量化策略"). Display-only in v1; VP-score integration / factor weight
calibration via backtest is a future KR.

**Endpoint fallback order:**
- `stk_factor_pro` → `stk_factor` → `stock_factor`

**Fetch strategy:** One market-wide bulk call per run using `start_date` +
`end_date` for a `days_window` of 30 `[unvalidated intuition; task window]`;
the script filters the returned rows into per-watchlist A-share files in
Python. It does not call Tushare once per ticker.

**Schema (A-share success):**
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok",
  "api_used": "stk_factor_pro",
  "_attempted_endpoints": ["stk_factor_pro"],
  "days_window": 30,
  "factors": {
    "pe": 18.5,
    "pb": 4.2,
    "ps": 3.1,
    "turnover_rate": 2.5,
    "volume_ratio": 1.2,
    "momentum_5d": 0.04,
    "momentum_20d": 0.08,
    "volatility": 0.18,
    "beta": 1.1,
    "total_mv": 95000000000,
    "circ_mv": 80000000000,
    "dv_ratio": 1.5,
    "dv_ttm": 1.8
  },
  "history": [
    {"trade_date": "20260503", "pe": 18.5, "pb": 4.2, ...},
    {"trade_date": "20260502", "pe": 18.3, "pb": 4.1, ...}
  ],
  "_factor_count": 13
}
```

**Schema (HK/US/non-A-share placeholder):**
```json
{
  "ticker": "700.HK",
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "skipped",
  "_reason": "not_available_tushare_hk_us",
  "api_used": null,
  "_attempted_endpoints": [],
  "days_window": 30,
  "factors": {},
  "history": [],
  "_factor_count": 0
}
```

**Graceful degrade behavior:** Same pattern as `lhb` (§2.1.4). HK/US tickers
get `_status: "skipped"`; A-share tickers with no rows in window get
`_status: "ok"` + empty `factors` + `history`; all-endpoints-fail writes
`_status: "endpoint_unavailable"` with `_attempted_endpoints`. Permission/tier
errors map to `_status: "tier_locked"` + `_need_tier: 15000`.

**Validation status:** Causal logic is valid because Tushare's quant factors
are computed from public OHLCV / fundamentals / market data (Barra-style
exposures, not proprietary). Field set varies with Tushare endpoint; whatever
Tushare returns gets passed through. Specific factor values are sourced
data, not calibrated weights. Any signal generation built on top of these
factors (future KR) must use `[unvalidated intuition]` labeling until
backtest-validated against real thesis outcomes.

**Future integration touchpoints:**
- VP score: replace `[unvalidated intuition]` 25/25/20/15/15 weights with
  factor-regression-derived weights once backtest infrastructure can ingest
  these factors.
- Cross-stock ranking: factor-quintile bucketing for screening (Tier-2 KR).
- Pitch generation: factor-context inputs into Variant View precision.

---

#### 2.1.6 `limit_list` — Tushare 15000-tier 涨停板单 / daily limit board list

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_limit_list.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.11, `continue-on-error: true`.

**Output:** `public/data/limit_list.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** Backend data layer for the Browse tab's next "封板专化"
view. This is global market context, not per-watchlist ticker data, so the
fetcher writes one fixed-name JSON file.

**Endpoint fallback order:**
- `limit_list_d` → `limit_list` → `limit_list_ths` → `limit_step`

**Fetch strategy:** One market-wide Tushare call per successful run using
`trade_date=<today Beijing date>`. The script tries endpoint names in order
and stops on the first success. Returned rows are grouped by the Tushare
limit-state field (`U` = 涨停, `D` = 跌停, `Z` = 炸板) into `limit_up`,
`limit_down`, and `failed` arrays.

**Schema (success):**
```json
{
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "ok",
  "api_used": "limit_list_d",
  "_attempted_endpoints": ["limit_list_d"],
  "limit_up": [
    {
      "ts_code": "300308.SZ",
      "name": "中际旭创",
      "trade_date": "20260503",
      "status": "U",
      "fc_ratio": 12.3,
      "fl_ratio": 1.2,
      "turnover_ratio": 8.5,
      "theme": "光通信",
      "concept": "光通信",
      "first_time": "093501",
      "last_time": "145801",
      "lu_desc": "AI算力",
      "ld_desc": null,
      "consecutive_limit_days": 2,
      "is_first_limit": false,
      "is_continuation": true,
      "limit_sequence": "continuation"
    }
  ],
  "limit_down": [],
  "failed": [],
  "summary": {
    "lu_count": 1,
    "ld_count": 0,
    "fail_count": 0
  }
}
```

**Schema (all endpoints unavailable):**
```json
{
  "fetched_at": "2026-05-03T...",
  "trade_date": "20260503",
  "tier": 15000,
  "_status": "endpoint_unavailable",
  "api_used": null,
  "_attempted_endpoints": ["limit_list_d", "limit_list", "limit_list_ths", "limit_step"],
  "limit_up": [],
  "limit_down": [],
  "failed": [],
  "summary": {"lu_count": 0, "ld_count": 0, "fail_count": 0},
  "_error": "..."
}
```

**Graceful degrade behavior:** This fetcher has no `_status: "skipped"` path
because the source is market-wide, not ticker-scoped. Successful empty market
returns are `_status: "ok"` with empty arrays. If every candidate endpoint
fails, the file is still written with `_status: "endpoint_unavailable"` or
`_status: "tier_locked"` + `_need_tier: 15000` depending on the Tushare error
text. Unexpected process-level failures write `_status: "fetch_failed"`.
The process exits 0 after writing any graceful-degrade payload and exits 1
only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because limit-up / limit-down /
炸板 status is exchange-mechanics data that directly describes daily market
speculation pressure and board-sealing strength. Specific row values are
sourced from Tushare when available, not generated by the platform. Any
future signal weight, "封板强度" score, or Browse ranking threshold built on
top of this data remains `[unvalidated intuition]` until backtest-validated
against real thesis outcomes.

---

#### 2.1.7 `inst_research` — Tushare stk_surv (机构调研)

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_inst_research.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.13, `continue-on-error: true`.

**Output:** `public/data/inst_research/<ticker_safe>.json` where
`300308.SZ` becomes `300308SZ.json`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** 调研频次 is a leading A-share signal because unusually
frequent institutional visits often appear before material disclosure,
earnings-revision cycles, or narrative rotation. The fetcher records the raw
evidence only. A future KR will surface 调研频次 as a Research detail card and
may add it as a VP confluence signal; no VP score weighting is implemented
here.

**Endpoint fallback order:**
- `stk_surv` -> `stk_holdertrade` -> `surv_holdertrade` -> `investor_research`

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status:
"skipped_hk"`; US/non-A-share tickers write `_status: "skipped_us"`. A-share
tickers query the last 90 calendar days `[unvalidated intuition; task window]`
using `start_date` + `end_date` when accepted by the endpoint, then fall back
to ticker-only fetches with Python-side date filtering. Calls sleep `0.16s`
between Tushare API attempts, below the 15000-tier 500 req/min ceiling.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "stk_surv",
  "_attempted_endpoints": ["stk_surv"],
  "window_days": 90,
  "surveys": [
    {
      "ts_code": "300308.SZ",
      "surv_date": "20260503",
      "inst_count": 12,
      "surv_type": "现场调研",
      "description": "..."
    }
  ],
  "summary": {
    "total_30d": 3,
    "total_90d": 9,
    "unique_inst_30d": 21,
    "latest_date": "2026-05-03"
  }
}
```

**Schema (empty A-share window):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "stk_surv",
  "_attempted_endpoints": ["stk_surv", "stk_holdertrade", "surv_holdertrade", "investor_research"],
  "window_days": 90,
  "surveys": [],
  "summary": {
    "total_30d": 0,
    "total_90d": 0,
    "unique_inst_30d": null,
    "latest_date": null
  }
}
```

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, `api_error`, and `all_failed`. If every
candidate endpoint fails, the file still writes `_status: "all_failed"`,
`_attempted_endpoints`, `_error`, and `_need_tier: 15000` only when the
Tushare error text indicates a permission / tier issue. Unexpected per-ticker
normalization or write failures write `_status: "api_error"` and do not stop
the remaining watchlist. The process exits 0 after per-ticker completion and
exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because institutional survey
records are direct observations of professional investor attention and
company access events in the A-share market. Specific windows, future
frequency thresholds, and any VP confluence weights remain `[unvalidated
intuition]` until calibrated against real thesis outcomes or trade history.

---

#### 2.1.8 `top_inst` — Tushare top_inst (游资数据 / 龙虎榜机构成交明细)

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_top_inst.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.14, `continue-on-error: true`.

**Output:** `public/data/top_inst/<ticker>.json` using the raw watchlist ticker
filename, e.g. `300308.SZ.json`. The dot is intentionally preserved to match
`lhb`, `quant_factors`, `chip_distribution`, and `consensus_forecast`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** `top_inst` is the seat-level companion to `lhb` (§2.1.4).
`lhb` answers whether a stock appeared on 龙虎榜 and why; `top_inst` answers
WHO traded it by preserving 营业部 / institution rows (`exalter`, buy, sell,
net buy, reason). The most-active 营业部 across multiple watchlist stocks can
approximate a 游资 footprint, especially when the same branch repeatedly
appears around high-volatility catalysts. This fetcher writes raw evidence
only. A future KR will surface cross-stock 营业部 rankings as 游资 footprint
analysis; no reputation classification or signal weighting is implemented
here.

**Endpoint fallback order:**
- `top_inst` -> `lhb_inst` -> `lhb_top_inst` -> `top_list_inst`

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status:
"skipped_hk"`; US/non-A-share tickers write `_status: "skipped_us"`. A-share
tickers query the last 30 calendar days `[unvalidated intuition; task window]`
using `start_date` + `end_date` when accepted by the endpoint. If the endpoint
does not support range params, the fetcher falls back to ticker-only fetches
with Python-side date filtering, then daily `trade_date` calls when needed.
Calls sleep `0.16s` between Tushare API attempts, below the 15000-tier 500
req/min ceiling.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "top_inst",
  "_attempted_endpoints": ["top_inst"],
  "window_days": 30,
  "appearances": [
    {
      "trade_date": "20260503",
      "exalter": "中信证券上海溧阳路营业部",
      "buy": 123000000.0,
      "sell": 23000000.0,
      "net_buy_amount": 100000000.0,
      "side": "both",
      "reason": "日涨幅偏离值达到7%的前5只证券"
    }
  ],
  "summary": {
    "total_appearances_30d": 1,
    "unique_seats_30d": 1,
    "top_buyer_30d": {"exalter": "中信证券上海溧阳路营业部", "net_buy_amount": 100000000.0},
    "top_seller_30d": null,
    "latest_date": "2026-05-03"
  }
}
```

**Schema (empty A-share window):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "top_inst",
  "_attempted_endpoints": ["top_inst"],
  "window_days": 30,
  "appearances": [],
  "summary": {
    "total_appearances_30d": 0,
    "unique_seats_30d": 0,
    "top_buyer_30d": null,
    "top_seller_30d": null,
    "latest_date": null
  }
}
```

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, `api_error`, and `all_failed`. If every
candidate endpoint fails, the file still writes `_status: "all_failed"`,
`_attempted_endpoints`, `_error`, and `_need_tier: 15000` only when the
Tushare error text indicates a permission / tier issue. Unexpected per-ticker
normalization or write failures write `_status: "api_error"` and do not stop
the remaining watchlist. The process exits 0 after per-ticker completion and
exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because 龙虎榜机构成交明细 is
exchange-defined seat-level trading evidence: it directly identifies which
营业部 / institutions supplied unusual buy or sell flow. Specific seat amounts
are source data from Tushare when available. The 30-day window, future
cross-stock 游资 ranking thresholds, and any confluence weights remain
`[unvalidated intuition]` until calibrated against real thesis outcomes or
trade history.

---

#### 2.1.9 `broker_recommend` — Tushare 15000-tier 券商金股 / analyst recommendations

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_broker_recommend.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.15, `continue-on-error: true`.

**Output:** `public/data/broker_recommend/<ticker>.json` using the raw
watchlist ticker filename, e.g. `300308.SZ.json`. The dot is intentionally
preserved to match `top_inst`, `lhb`, `quant_factors`, `chip_distribution`,
and `consensus_forecast`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** `broker_recommend` is the rating-level analyst-signal
companion to `consensus_forecast` (§2.1.3). `consensus_forecast` preserves
numerical EPS/revenue/profit forecasts; `broker_recommend` preserves
analyst/broker opinion rows: recommendation text, target price, analyst,
broker name, report id, and report title. Both feed the Research analyst
signal layer. Future cross-check: when both are available, compare
`broker_recommend.summary.avg_target_price` against `consensus_forecast`
EPS-implied valuation as a Variant View precision input. No automatic
investment decision, VP score weight, or broker reputation weighting is
implemented here.

**Endpoint fallback order:**
- `broker_recommend` -> `report_rc` -> `analyst_rec` -> `broker_monthly`

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status:
"skipped_hk"`; US/non-A-share tickers write `_status: "skipped_us"`.
A-share tickers query the last 90 calendar days `[unvalidated intuition; task
window]` using `start_date` + `end_date` when accepted by the endpoint, then
fall back to ticker-only fetches with Python-side date filtering. Calls sleep
`0.16s` between Tushare API attempts, below the 15000-tier request ceiling.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "broker_recommend",
  "_attempted_endpoints": ["broker_recommend"],
  "window_days": 90,
  "recommendations": [
    {
      "rec_date": "20260503",
      "broker": "中信证券",
      "analyst": "张三",
      "recommendation": "买入",
      "target_price": 123.4,
      "report_id": "R123",
      "report_title": "中际旭创深度报告"
    }
  ],
  "summary": {
    "total_90d": 1,
    "unique_brokers_90d": 1,
    "latest_recommendation": "买入",
    "avg_target_price": 123.4,
    "target_price_count": 1,
    "latest_date": "2026-05-03"
  }
}
```

**Schema (empty A-share window):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "broker_recommend",
  "_attempted_endpoints": ["broker_recommend"],
  "window_days": 90,
  "recommendations": [],
  "summary": {
    "total_90d": 0,
    "unique_brokers_90d": 0,
    "latest_recommendation": null,
    "avg_target_price": null,
    "target_price_count": 0,
    "latest_date": null
  }
}
```

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, `api_error`, and `all_failed`. If every
candidate endpoint fails, the file still writes `_status: "all_failed"`,
`_attempted_endpoints`, `_error`, and `_need_tier: 15000` only when the
Tushare error text indicates a permission / tier issue. Unexpected per-ticker
normalization or write failures write `_status: "api_error"` and do not stop
the remaining watchlist. The process exits 0 after per-ticker completion and
exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because analyst ratings and
target prices are direct sell-side opinion evidence and provide an explicit
cross-check against numerical consensus forecast data. Specific
recommendation rows and target prices are source data from Tushare when
available. The 90-day window and any future target-price disagreement
thresholds remain `[unvalidated intuition]` until calibrated against real
thesis outcomes or trade history.

---

#### 2.1.10 `pledge_stat` — Tushare 5000-tier 股权质押

**Auth:** `TUSHARE_TOKEN` env var with 5000-tier access. Junyan's current
15000-tier account covers this endpoint.

**Fetcher:** `scripts/fetch_pledge_stat.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.16, `continue-on-error: true`.

**Output:** `public/data/pledge_stat/<ticker>.json` using the raw watchlist
ticker filename, e.g. `300308.SZ.json`. The dot is intentionally preserved to
match `top_inst`, `broker_recommend`, `lhb`, `quant_factors`,
`chip_distribution`, and `consensus_forecast`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** `pledge_stat` is a China-specific risk reference layer.
High shareholder pledge ratios can create forced-selling pressure and
control-risk when a stock drops sharply, especially for controlling
shareholders whose collateral can be liquidated. The fetcher writes raw
evidence and a simple ratio-band summary only. Frontend Risk panel surfacing
is a separate KR; Bridge 6 can later use this as one portfolio construction
risk-weighting input alongside correlation, concentration, and VaR.

**Endpoint:** `pledge_stat` only. No fallback chain is used because this is a
known Tushare 5000-tier endpoint.

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status:
"skipped_hk"`; US/non-A-share tickers write `_status: "skipped_us"`.
A-share tickers fetch full available history from `pledge_stat`, sort by
`end_date` descending, and emit the latest 4 quarterly records `[task-scoped
window; unvalidated intuition]`. Calls sleep `0.16s` between Tushare API
calls.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "pledge_stat",
  "window_quarters": 4,
  "records": [
    {
      "ts_code": "300308.SZ",
      "end_date": "20260331",
      "pledge_ratio": 12.34,
      "pledge_count": 2,
      "unrest_pledge": 12345.0
    }
  ],
  "summary": {
    "latest_pledge_ratio": 12.34,
    "latest_end_date": "2026-03-31",
    "trend_direction": "rising",
    "risk_level": "LOW",
    "records_count": 1
  }
}
```

**Schema (empty A-share history):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "pledge_stat",
  "window_quarters": 4,
  "records": [],
  "summary": {
    "latest_pledge_ratio": null,
    "latest_end_date": null,
    "trend_direction": null,
    "risk_level": null,
    "records_count": 0
  }
}
```

**Signal interpretation (display/reference only):**
- `pledge_ratio > 50%` → `HIGH`: forced-selling / control-risk warning if
  the stock drops 30%+.
- `20% <= pledge_ratio <= 50%` → `MED`: material collateral exposure, monitor
  alongside price drawdown and insider-control context.
- `pledge_ratio < 20%` → `LOW`: lower pledge-ratio risk, not a positive alpha
  signal by itself.
- Rising pledge ratio over the latest 4 quarterly records is a yellow flag:
  insiders pledging more can indicate financing stress.

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, and `api_error`. API failures write
`_status: "api_error"` with `_error` and do not stop the remaining watchlist.
There is no `all_failed` state because this fetcher uses a single known
endpoint and no fallback chain. The process exits 0 after per-ticker
completion and exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because pledged shares create a
direct collateral channel from share-price declines to forced liquidation and
possible controlling-shareholder instability. Specific HIGH/MED/LOW bands
(>50%, 20-50%, <20%) and the 30% drawdown reference are task-specified
unvalidated risk heuristics, not calibrated from platform trade history or
portfolio loss data. Any future Bridge 6 weighting must be calibrated before
being presented as a validated portfolio risk model.

---

#### 2.1.11 `restricted_shares` — Tushare 2000-tier 限售股解禁

**Auth:** `TUSHARE_TOKEN` env var with 2000-tier access. Junyan's current
15000-tier account covers this endpoint.

**Fetcher:** `scripts/fetch_restricted_shares.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.17, `continue-on-error: true`.

**Output:** `public/data/restricted_shares/<ticker>.json` using the raw
watchlist ticker filename, e.g. `300308.SZ.json`. The dot is intentionally
preserved to match `pledge_stat`, `top_inst`, `broker_recommend`, `lhb`,
`quant_factors`, `chip_distribution`, and `consensus_forecast`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** `restricted_shares` is a China-specific risk reference
layer for A-share liquidity / ownership analysis (INVESTMENT_FRAMEWORK C1.6).
Large restricted-share unlocks can create short-term supply pressure because
formerly locked shares become tradable. Multiple unlocks within the next 90
days are a compound-risk flag because supply can hit the market in clustered
waves. The fetcher writes raw evidence and a simple ratio-band summary only.
Frontend Risk panel surfacing is a separate KR; Bridge 6 can later use this
as one portfolio construction risk input alongside pledge ratio, correlation,
concentration, and VaR.

**Endpoint:** `share_float` only. No fallback chain is used because this is a
known Tushare 2000-tier endpoint.

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status: "skipped_hk"`;
US/non-A-share tickers write `_status: "skipped_us"`. A-share tickers query
the next 180 calendar days `[task-scoped window;
unvalidated intuition]` using `start_date` + `end_date` when accepted by the
endpoint. If the endpoint rejects range params, the fetcher falls back to
ticker-only fetches and applies the 180-day upcoming window in Python. Calls
sleep `0.16s` between Tushare API calls.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "share_float",
  "window_days": 180,
  "events": [
    {
      "ts_code": "300308.SZ",
      "ann_date": "20260503",
      "float_date": "20260615",
      "float_share": 12345678,
      "float_ratio": 4.56,
      "holder_name": "Example holder",
      "share_type": "首发原股东限售股份"
    }
  ],
  "summary": {
    "upcoming_count": 1,
    "total_float_ratio_180d": 4.56,
    "next_unlock_date": "2026-06-15",
    "next_unlock_ratio": 4.56,
    "risk_level": "MED"
  }
}
```

**Schema (empty A-share window):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-03T...",
  "api_used": "share_float",
  "window_days": 180,
  "events": [],
  "summary": {
    "upcoming_count": 0,
    "total_float_ratio_180d": 0.0,
    "next_unlock_date": null,
    "next_unlock_ratio": null,
    "risk_level": null
  }
}
```

**Signal interpretation (display/reference only):**
- `total_float_ratio_180d > 10%` -> `HIGH`: large upcoming supply event,
  treat as short-term price-pressure risk.
- `3% <= total_float_ratio_180d <= 10%` -> `MED`: material unlock pressure,
  monitor alongside liquidity, price trend, and holder identity.
- `total_float_ratio_180d < 3%` -> `LOW`: limited unlock pressure, not a
  positive alpha signal by itself.
- Multiple unlocks within 90 days are a compound-risk flag even when each
  single event is below `HIGH`; Bridge 6 should later test whether clustering
  deserves a portfolio-level risk weight.

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, and `api_error`. API failures write
`_status: "api_error"` with `_error` and do not stop the remaining watchlist.
There is no `all_failed` state because this fetcher uses a single known
endpoint and no fallback chain. The process exits 0 after per-ticker
completion and exits 1 only when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because restricted-share unlocks
directly increase tradable share supply, creating a plausible near-term
liquidity-pressure channel. Specific HIGH/MED/LOW bands (>10%, 3-10%, <3%),
the 180-day lookahead, and the 90-day clustering note are task-specified
unvalidated heuristics, not calibrated from platform trade history or
portfolio loss data. Any future Bridge 6 weighting must be calibrated before
being presented as a validated portfolio risk model.

---

#### 2.1.12 `repurchase` — Tushare 5000-tier 回购

**Auth:** `TUSHARE_TOKEN` env var with 5000-tier access. Junyan's current
15000-tier account covers this endpoint.

**Fetcher:** `scripts/fetch_repurchase.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.18, `continue-on-error: true`.

**Registry row:**

| Source | Endpoint | Tier | Output path | Consumer | Graceful degrade | Status |
|---|---|---|---|---|---|---|
| Tushare Pro | `repurchase` | 5000 | `public/data/repurchase/<ticker>.json` | Research detail card after KR3 frontend ships; future Bridge 6 portfolio buyback overlay | `skipped_hk` / `skipped_us`, `api_error` to neutral | ACTIVE — pipeline Step 2d.18 |

**Output:** `public/data/repurchase/<ticker>.json` using the raw watchlist
ticker filename, e.g. `300308.SZ.json`. The dot is intentionally preserved to
match `pledge_stat` and `restricted_shares`.

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** `repurchase` is a China-specific insider-confidence and
capital-allocation reference layer. Large committed buyback programs can
reduce selling pressure, support EPS, and signal management confidence in
intrinsic value. The fetcher writes raw evidence and a simple amount-band
summary only. Frontend surfacing is KR3; Bridge 6 can later test whether this
deserves a portfolio overlay alongside pledge ratio, unlock pressure,
correlation, concentration, and VaR.

**Endpoint:** `repurchase` only. The fetcher first tries `ts_code` +
`start_date` + `end_date`, then falls back to `ts_code` only if the endpoint
rejects range parameters.

**Fetch strategy:** Per-watchlist ticker. HK tickers write `_status:
"skipped_hk"`; US/non-A-share tickers write `_status: "skipped_us"`.
A-share tickers query the past 180 calendar days `[task-scoped window;
unvalidated intuition]` using `ann_date`, then sort events by `ann_date`
descending. Calls sleep `0.16s` between Tushare API attempts.

**Schema (A-share success):**
```json
{
  "_status": "ok",
  "ticker": "300308.SZ",
  "fetched_at": "2026-05-04T...",
  "api_used": "repurchase",
  "window_days": 180,
  "events": [
    {
      "ts_code": "300308.SZ",
      "ann_date": "20260504",
      "end_date": "20261104",
      "exp_date": "20261104",
      "proc": "进行中",
      "vol": 12345678,
      "amount": 250000000.0,
      "high_limit": 120.0,
      "low_limit": 80.0
    }
  ],
  "summary": {
    "total_count": 1,
    "total_amount_180d": 250000000.0,
    "active_program": true,
    "last_announce_date": "2026-05-04",
    "signal_level": "MED"
  }
}
```

**Schema (empty A-share window):**
```json
{
  "_status": "empty",
  "ticker": "002594.SZ",
  "fetched_at": "2026-05-04T...",
  "api_used": "repurchase",
  "window_days": 180,
  "events": [],
  "summary": {
    "total_count": 0,
    "total_amount_180d": 0.0,
    "active_program": false,
    "last_announce_date": null,
    "signal_level": "LOW"
  }
}
```

**Signal interpretation (display/reference only; thresholds are
`[unvalidated intuition]`):**
- `total_amount_180d > 5e8` -> `HIGH`: strong buyback commitment
  `[unvalidated intuition]`.
- `1e8 <= total_amount_180d <= 5e8` -> `MED`: material buyback support
  `[unvalidated intuition]`.
- `total_amount_180d < 1e8` or no events -> `LOW`: neutral / weak signal
  `[unvalidated intuition]`.
- If events exist but no amount field is parseable, `signal_level` is `null`.
- `active_program` is true when `proc` contains `进行`, `未完成`,
  `in_progress`, or `ongoing`.

**Graceful degrade behavior:** The strict ticker-level states are `ok`,
`empty`, `skipped_hk`, `skipped_us`, and `api_error`. API failures write
`_status: "api_error"` with `_error` and do not stop the remaining watchlist.
Missing or empty `TUSHARE_TOKEN` writes per-A-share `api_error` payloads while
HK/US tickers still write skipped payloads; the process exits 0.

**Validation status:** Causal logic is valid because executed or committed
buybacks can directly reduce float supply and signal management confidence,
creating plausible support for EPS and selling-pressure reduction. Specific
HIGH/MED/LOW amount bands (>5e8, 1e8-5e8, <1e8 RMB), the 180-day lookback, and
active-program text matching are task-specified unvalidated heuristics, not
calibrated from platform trade history or portfolio outcome data. Any future
Bridge 6 weighting must be calibrated before being presented as a validated
portfolio signal.

---

#### 2.1.13 `concept_membership` — Tushare 15000-tier concept constituent mapping

**Auth:** `TUSHARE_TOKEN` env var with 15000-tier access.

**Fetcher:** `scripts/fetch_concept_detail.py`

**Pipeline:** `.github/workflows/fetch-data.yml` Step 2d.12, `continue-on-error: true`.

**Output:** `public/data/concept_membership.json`

**Refresh cadence:** Daily, same schedule as the market data pipeline.

**Strategic role:** Backend lookup table for Browse concept click-through.
KR2 shift 6 surfaces "Hot Concepts"; KR6 can use this file to filter the
Browse universe to stocks that belong to the clicked concept.

**Endpoint fallback order:**
- Bulk membership: `concept_detail` -> `concept_membership` -> `ths_concept_detail`
- Fallback two-step: `concept(src="ts")` -> `concept_detail(id=<concept_code>)`

**Fetch strategy:** Strategy A tries one market-wide bulk membership call and
groups returned rows into concept buckets in Python. If all bulk candidates
fail or return zero rows, Strategy B fetches the Tushare concept list once,
then calls `concept_detail` for the first 100 concepts only to avoid
hammering the API. Per-concept calls sleep `0.2s` between requests. Members
are capped at 200 per concept; over-cap buckets keep the full `member_count`
and add `_truncated: true` while truncating the emitted `members` array.

**Schema (success):**
```json
{
  "fetched_at": "2026-05-03T...",
  "tier": 15000,
  "_status": "ok",
  "api_used": "concept_detail",
  "_attempted_endpoints": ["concept_detail"],
  "concepts": [
    {
      "name": "光通信",
      "ts_code": "TS123",
      "member_count": 2,
      "members": [
        {"ts_code": "300308.SZ", "name": "中际旭创"},
        {"ts_code": "002281.SZ", "name": "光迅科技"}
      ]
    }
  ],
  "total_concepts": 1,
  "total_memberships": 2
}
```

**Schema (all endpoints unavailable):**
```json
{
  "fetched_at": "2026-05-03T...",
  "tier": 15000,
  "_status": "endpoint_unavailable",
  "api_used": null,
  "_attempted_endpoints": [
    "concept_detail",
    "concept_membership",
    "ths_concept_detail",
    "concept",
    "concept_detail(id)"
  ],
  "concepts": [],
  "total_concepts": 0,
  "total_memberships": 0,
  "_error": "..."
}
```

**Graceful degrade behavior:** This fetcher has no `_status: "skipped"` path
because the source is market-wide, not ticker-scoped. If every candidate
endpoint fails or no usable concept-stock rows can be formed, the file is
still written with `_status: "endpoint_unavailable"` or `_status:
"tier_locked"` + `_need_tier: 15000` depending on the Tushare error text.
Unexpected process-level failures write `_status: "fetch_failed"`. The
process exits 0 after writing any graceful-degrade payload and exits 1 only
when `TUSHARE_TOKEN` is missing.

**Validation status:** Causal logic is valid because concept membership is a
source lookup table: it directly maps a Tushare concept board to its
constituent stocks and enables deterministic universe filtering. Specific
membership rows are sourced from Tushare when available, not generated by the
platform. The first-100 fallback cap, 200-member output cap, and `0.2s`
request delay are implementation caps `[unvalidated intuition]`, not
investment thresholds. Any future alpha signal built from concept membership
must be backtest-validated before being treated as calibrated.

---

### 2.2 `yfinance` — Yahoo Finance (existing)

Already integrated in `scripts/fetch_data.py`. Free, no auth.
Use for HK + US tickers (700.HK, 9999.HK, 6160.HK, NVDA, MSFT, GOOGL, META, AMZN).
**Limitation:** A-share data quality lower than Tushare. Tushare is now the primary A-share source.

---

### 2.3 `akshare` — AKShare (existing)

Already integrated in `scripts/fetch_data.py`. Free.
**Known issue:** GeoBlocked on GitHub Actions (US IPs). Mitigation: `continue-on-error: true`.
With Tushare 6000 active, akshare's role **shrinks** to backup for niche A-share endpoints.

---

### 2.4 `cninfo` — 巨潮资讯网 (NEW 2026-05-02)

**Auth:** None. Public scraping.

**API endpoint (community-discovered, stable):**
```
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
```

**Categories:**
- `category_ndbg_szsh` — 年度报告
- `category_yjdbg_szsh` — 一季报
- `category_bndbg_szsh` — 半年报
- `category_sjdbg_szsh` — 三季报
- `category_yjyg_szsh` — 业绩预告
- `category_yjkb_szsh` — 业绩快报
- `category_zjjg_szsh` — 重大事项

**Output:** `public/data/cninfo_<ticker_safe>.json`

**Schema:**
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "ISO timestamp",
  "_status": "ok",
  "announcements": [
    {
      "title": "中际旭创 2025 年年度报告",
      "category": "年度报告",
      "announce_date": "2026-04-25",
      "pdf_url": "http://static.cninfo.com.cn/...",
      "size_bytes": 12345678,
      "_pdf_downloaded": false
    }
  ]
}
```

**Implementation:** `scripts/fetch_cninfo.py` (this session)

**Rate limit:** ≥1s between requests. No documented limit; conservative.

**Downstream consumer:**
- LLM PDF reader (planned) — extract MD&A, 风险因素, 业绩说明会 Q&A
- Daily decision: surface 业绩预告 as `wrongIf_alert` candidate

---

### 2.5 `hkex` — HKEx Disclosure (NEW 2026-05-02)

**Auth:** None. Public.

**API endpoint:**
```
POST https://www1.hkexnews.hk/search/titleSearchServlet.do
```

**Output:** `public/data/hkex_<ticker_safe>.json`

**Schema:**
```json
{
  "ticker": "700.HK",
  "fetched_at": "ISO timestamp",
  "_status": "ok",
  "announcements": [
    {
      "title": "Tencent — Annual Report 2025",
      "category": "Financial Statements",
      "announce_date": "2026-03-22",
      "pdf_url_en": "https://www1.hkexnews.hk/listedco/...en.pdf",
      "pdf_url_zh": "https://www1.hkexnews.hk/listedco/...c.pdf"
    }
  ]
}
```

**Implementation:** `scripts/fetch_hkex.py` (this session)

**Rate limit:** ≥1s. No documented limit.

**Downstream consumer:**
- Same as cninfo — LLM PDF reader for MD&A

---

### 2.6 `edgar` — SEC EDGAR (NEW 2026-05-02)

**Auth:** No registration. **Required:** HTTP `User-Agent` header containing email
(SEC fair-use policy). Email used: `luvyears@outlook.com`.

**API endpoint (modern JSON):**
```
GET https://data.sec.gov/submissions/CIK<10-digit-zero-padded>.json
```

**CIK mapping (AI infra hyperscaler basket — feeds `leading_indicators.py`):**

| Ticker | CIK | Use |
|---|---|---|
| NVDA | 0001045810 | Data center revenue narrative (1.6T optical demand proxy) |
| MSFT | 0000789019 | Hyperscaler CapEx (Azure) |
| GOOGL | 0001652044 | Hyperscaler CapEx (GCP) |
| META | 0001326801 | Hyperscaler CapEx (AI) |
| AMZN | 0001018724 | Hyperscaler CapEx (AWS) |

**Output:** `public/data/edgar_<ticker>.json`

**Schema:**
```json
{
  "ticker": "NVDA",
  "cik": "0001045810",
  "fetched_at": "ISO timestamp",
  "_status": "ok",
  "filings": [
    {
      "accession_no": "0001045810-26-000035",
      "form": "8-K",
      "filed_date": "2026-04-25",
      "primary_doc": "ex991.htm",
      "url": "https://www.sec.gov/Archives/edgar/data/1045810/...",
      "category": "Material Event"
    }
  ]
}
```

**Implementation:** `scripts/fetch_edgar.py` (this session)

**Rate limit:** SEC asks ≤10 req/s. We do ≥1s between requests (very safe).

**Downstream consumer:**
- `leading_indicators.py` — supplement yfinance numerical data with 8-K narrative
- Future: LLM extracts catalyst statements from MD&A / Risk Factors

---

### 2.7 `xueqiu` — 雪球 (STUB, A 选择)

**Status:** STUB only. Skeleton in place per Junyan's "选 A" decision (multi-source social).

**Anti-scraping risk:** HIGH. Production implementation requires:
- Rotating user agents
- IP rotation / proxies
- JS rendering (Playwright?)
- Frequency throttling
- Cookie/session management

**Defer to dedicated session.** Do not deploy stub to pipeline yet.

---

### 2.8 `eastmoney_guba` — 东财股吧 (STUB, A 选择)

**Status:** STUB only. Same pattern as xueqiu.

---

### 2.9 `cls` — 财联社 (DEFERRED, c 选择)

**Decision:** Try `tushare_news` first (already paid for via 6000 tier). Fall back to
scraping `cls.cn/nodeapi/updateTelegraphList` if Tushare news inadequate.

**Verification step (TODO):** Test which Tushare news endpoint our 6000 tier unlocks.

---

## 3. Output Path Conventions

All fetchers output to `public/data/`:

| Pattern | Example | Owner |
|---|---|---|
| `<source>_<ticker>.json` | `cninfo_300308.SZ.json` | per-ticker, primary outputs |
| `<source>/<ticker>/...` | `pdfs/cninfo/300308.SZ/2025_annual.pdf` | per-ticker assets |
| `_data_completeness.json` | (single file) | audit summary, written by `data_completeness.py` |

---

## 4. Common Fetcher Conventions (all `scripts/fetch_*.py`)

Every fetcher must:

1. **Load watchlist via `_load_watchlist()`** (per CLAUDE.md INVARIANT 1: watchlist.json is the single source of truth)
2. **Filter relevant tickers** — e.g., HKEx fetcher filters to `*.HK` tickers
3. **Emit standard schema** with `_status` field at top level (`ok`, `partial`, `failed`)
4. **Mark missing data explicitly** — never silently omit
5. **Be idempotent + re-runnable** — overwriting outputs is fine
6. **Exit 0 even on per-ticker failures** — log to stderr but don't crash pipeline
7. **Respect rate limits** — `time.sleep(1.0)` minimum between requests for free public sources
8. **Be standalone-runnable** — `python3 scripts/fetch_X.py` works without other scripts
9. **Print progress** — `[X/Y] processing TICKER...` so pipeline logs are scannable

---

## 5. Graceful Degrade Examples

### Source unavailable (network error):
```json
{
  "ticker": "300308.SZ",
  "fetched_at": "...",
  "_status": "failed",
  "_error": "ConnectionError: ...",
  "announcements": null
}
```

### Tier-locked field:
```json
{
  "moneyflow_hsgt": {
    "rows": null,
    "_status": "tier_locked",
    "_need_tier": 10000,
    "_unlock_action": "Upgrade Tushare to 10000-tier"
  }
}
```

### Partial success (some tickers OK, some failed):
```json
{
  "_status": "partial",
  "succeeded": ["300308.SZ"],
  "failed": [{"ticker": "002594.SZ", "error": "Timeout"}]
}
```

---

## 6. Pipeline Integration (planned)

`.github/workflows/fetch-data.yml` will add steps for each new fetcher,
each with `continue-on-error: true` (mirrors existing pattern):

```yaml
- name: Fetch CNInfo announcements
  run: python3 scripts/fetch_cninfo.py
  continue-on-error: true

- name: Fetch HKEx announcements
  run: python3 scripts/fetch_hkex.py
  continue-on-error: true

- name: Fetch SEC EDGAR filings
  run: python3 scripts/fetch_edgar.py
  continue-on-error: true
  env:
    EDGAR_USER_AGENT_EMAIL: ${{ secrets.EDGAR_USER_AGENT_EMAIL }}
```

(`EDGAR_USER_AGENT_EMAIL` GitHub secret to be added by Junyan with value
`luvyears@outlook.com`. Until then, fetcher uses default fallback email
defined in `scripts/fetch_edgar.py`.)

---

## 7. Forward-Compatibility Test

When upgrading any source's tier (e.g., Tushare 6000 → 10000):
1. Update `current_tier` in registry above
2. Re-run pipeline
3. Schema doesn't change — `forecast.rows` populates from `null` to data
4. Frontend doesn't change — `_status` flips from `tier_locked` to `ok`
5. Downstream consumers (vp_engine, USP layer) auto-activate new logic
   (because they were written assuming the field could exist)

**No code change required.** Architecture pays for itself.

---

## 8. Anti-Patterns (do not do)

❌ Hardcode tickers in fetcher (always `_load_watchlist()`)
❌ Throw exception on per-ticker failure (continue, mark `_status: failed`)
❌ Delete missing fields from output JSON (set `null` + `_status`)
❌ Crash pipeline on source unavailable (use `continue-on-error: true`)
❌ Use bare `requests.get()` without User-Agent (SEC will ban; cninfo/hkex
   may rate-limit unidentified clients)
❌ Re-fetch unchanged data daily without caching (some sources have IP daily limits)

---

## 9. Pending Work (next /auto session)

- [ ] `scripts/fetch_tushare.py` — registry-driven Tushare fetcher (replaces ad-hoc Tushare calls in fetch_data.py)
- [ ] `scripts/data_completeness.py` — daily audit of `_status` fields across all sources
- [ ] `docs/architecture/UPGRADE_PLAYBOOK.md` — concrete actions when upgrading any source's tier
- [ ] LLM PDF reader for cninfo + hkex + edgar PDFs
- [ ] Pipeline integration in `fetch-data.yml`
- [ ] Promote xueqiu/guba stubs to production (after dedicated anti-scrape design session)
