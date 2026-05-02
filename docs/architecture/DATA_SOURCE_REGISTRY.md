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
> Last updated: 2026-05-02

---

## 1. Source Inventory

| ID | Source | Tier | Auth | Tickers | Cadence | Status |
|---|---|---|---|---|---|---|
| `tushare` | Tushare Pro | Paid (6000 pts) | `TUSHARE_TOKEN` env | A-share | daily | ✅ ACTIVE |
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

### 2.1 `tushare` — Tushare Pro (current tier: 6000)

**Auth:** `TUSHARE_TOKEN` env var (also stored in GitHub Actions secret).

**API call pattern:**
```python
import tushare as ts
ts.set_token(os.environ['TUSHARE_TOKEN'])
pro = ts.pro_api()
df = pro.daily(ts_code='300308.SZ', start_date='20260101', end_date='20260501')
```

**Tier-gated endpoints (current 6000 active vs higher):**

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
| `pledge_stat` | 5000 | 股权质押 | China-specific risk |
| `forecast` | 10000 | 业绩预告 | Strongest A-share catalyst signal |
| `express` | 10000 | 业绩快报 | Pre-earnings catalyst |
| `fina_indicator` | 10000? | 财务指标 (ROE/ROA) | fundamental_accel upgrade |

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

**Implementation:** `scripts/fetch_tushare.py` (TODO — next /auto session per registry pattern).

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
