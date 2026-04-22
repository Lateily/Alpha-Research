#!/usr/bin/env python3
"""
AR Platform v4.0 — Full Market + Consensus + Flow + Insider Data Fetcher

Output files:
  public/data/universe_a.json       — Full A-share universe (~5839 stocks)
  public/data/universe_hk.json      — Full HK universe (~4622 stocks)
  public/data/market_data.json      — Focus stock detailed data (price, TA, fundamentals,
                                       consensus estimates, southbound, D&T board, margin)
  public/data/ohlc_{ticker}.json    — 90-day OHLC for candlestick charts
  public/data/fin_{ticker}.json     — Financial statements (IS/BS/CF)
  public/data/earnings_calendar.json — Upcoming earnings dates + beat/miss history
  public/data/flow_data.json        — Southbound + Dragon&Tiger + margin aggregate

Run: python3 scripts/fetch_data.py
"""

import json, os, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Optional API keys (set as GitHub Secrets → env vars) ───────────────────
# Twelve Data:   https://twelvedata.com      Free: 800 req/day, 8/min
# Alpha Vantage: https://alphavantage.co     Free: 25 req/day
# Tushare Pro:   https://tushare.pro         Points required (see below)
TWELVE_DATA_KEY    = os.getenv('TWELVE_DATA_KEY', '')
ALPHA_VANTAGE_KEY  = os.getenv('ALPHA_VANTAGE_KEY', '')
TUSHARE_TOKEN      = os.getenv('TUSHARE_TOKEN', '')
VERCEL_URL         = os.getenv('VERCEL_URL', 'https://equity-research-ten.vercel.app')

# ── Focus stock config ──────────────────────────────────────────────────────
FOCUS_TICKERS = {
    "300308.SZ": {"yahoo": "300308.SZ", "akshare": "300308", "exchange": "SZ",
                  "name_en": "Innolight",       "name_zh": "中际旭创"},
    "700.HK":    {"yahoo": "0700.HK",   "akshare": None,     "exchange": "HK",
                  "name_en": "Tencent",         "name_zh": "腾讯控股"},
    "9999.HK":   {"yahoo": "9999.HK",   "akshare": None,     "exchange": "HK",
                  "name_en": "NetEase",         "name_zh": "网易"},
    "6160.HK":   {"yahoo": "6160.HK",   "akshare": None,     "exchange": "HK",
                  "name_en": "BeOne Medicines", "name_zh": "百济神州"},
    "002594.SZ": {"yahoo": "002594.SZ", "akshare": "002594", "exchange": "SZ",
                  "name_en": "BYD",             "name_zh": "比亚迪"},
}

# ── VP scores for Supabase snapshot (kept in sync with Dashboard.jsx) ──────
# VP_SCORES: seed/fallback values only.
# These are overridden by DeepResearch output preserved in vp_snapshot.json.
# Update last_updated when you manually recalibrate the seed values.
VP_SCORES = {
    "300308.SZ": {"vp": 79, "expectation_gap": 72, "fundamental_accel": 80,
                  "narrative_shift": 65, "low_coverage": 55, "catalyst_prox": 85,
                  "last_updated": "2026-04-13",
                  "wrongIf_e": "1.6T qualification slips to Q4 2025 OR hyperscaler CapEx cut >20%",
                  "wrongIf_z": "1.6T认证推迟至Q4 2025，或超大规模资本支出削减>20%"},
    "700.HK":    {"vp": 64, "expectation_gap": 68, "fundamental_accel": 70,
                  "narrative_shift": 75, "low_coverage": 40, "catalyst_prox": 60,
                  "last_updated": "2026-04-13",
                  "wrongIf_e": "Regulatory cap on gaming minors extended OR macro consumption weakens sharply",
                  "wrongIf_z": "游戏监管扩大或宏观消费急剧恶化"},
    "9999.HK":   {"vp": 58, "expectation_gap": 62, "fundamental_accel": 55,
                  "narrative_shift": 50, "low_coverage": 45, "catalyst_prox": 65,
                  "last_updated": "2026-04-13",
                  "wrongIf_e": "Marvel Rivals DAU drops below 2M OR Japan MAU misses 3M by Q3 2025",
                  "wrongIf_z": "漫威对决DAU低于200万，或日本MAU未达Q3 2025的300万"},
    "6160.HK":   {"vp": 65, "expectation_gap": 72, "fundamental_accel": 65,
                  "narrative_shift": 68, "low_coverage": 45, "catalyst_prox": 70,
                  "last_updated": "2026-04-13",
                  "wrongIf_e": "CELESTIAL Phase 3 uMRD data disappoints (<50%) OR pirtobrutinib 1L CLL Phase 3 shows superior PFS",
                  "wrongIf_z": "CELESTIAL三期uMRD数据不及预期(<50%)，或多替布鲁替尼1L CLL三期PFS更优"},
    "002594.SZ": {"vp": 52, "expectation_gap": 55, "fundamental_accel": 60,
                  "narrative_shift": 45, "low_coverage": 35, "catalyst_prox": 50,
                  "last_updated": "2026-04-13",
                  "wrongIf_e": "EU tariffs on Chinese EVs exceed 35% AND Brazil imposes local content rules",
                  "wrongIf_z": "欧盟关税>35%且巴西本地化要求同时触发"},
}

# ══════════════════════════════════════════════════════════════════════════════
# EQR Auto-Rating Engine
# ══════════════════════════════════════════════════════════════════════════════
_EQR_LEVELS = ["LOW", "MED", "MED-HIGH", "HIGH"]

def _eqr_idx(level):
    return _EQR_LEVELS.index(level) if level in _EQR_LEVELS else 0

def _eqr_from_idx(i):
    return _EQR_LEVELS[max(0, min(i, 3))]

def _eqr_degrade(level, steps=1):
    return _eqr_from_idx(_eqr_idx(level) - steps)

def _auto_eqr_rating(base_level, data_age_days, cross_referenced=False, is_llm_inference=False):
    """
    Mandatory degradation waterfall:
    1. LLM inference → always LOW
    2. data_age > 180 days → force LOW
    3. data_age > 90 days  → degrade 1 level
    4. single source and rating >= MED-HIGH → degrade 1 level
    """
    if is_llm_inference:
        return "LOW"
    rating = base_level
    if data_age_days > 180:
        return "LOW"
    if data_age_days > 90:
        rating = _eqr_degrade(rating, 1)
    if not cross_referenced and _eqr_idx(rating) >= _eqr_idx("MED-HIGH"):
        rating = _eqr_degrade(rating, 1)
    return rating

def generate_eqr(ticker, market, data_dates):
    """
    Generate the full EQR JSON for one ticker.
    data_dates: { "financials": "YYYY-MM-DD", "price": ..., "consensus": ..., "news": ... }
    """
    today = datetime.now(timezone.utc).date()

    def age(date_str):
        if not date_str:
            return 999
        try:
            d = datetime.fromisoformat(str(date_str)).date()
            return (today - d).days
        except Exception:
            return 999

    fin_age  = age(data_dates.get("financials"))
    px_age   = age(data_dates.get("price"))
    con_age  = age(data_dates.get("consensus"))
    news_age = age(data_dates.get("news"))

    sections = {
        "business_model": {
            "label": "Business Model",
            "rating": _auto_eqr_rating("HIGH", fin_age, cross_referenced=True),
            "source": "Company annual report + AKShare financials",
            "data_age_days": fin_age,
        },
        "variant_thesis": {
            "label": "Variant Thesis",
            "rating": _auto_eqr_rating(
                "MED-HIGH" if con_age < 90 else "MED",
                con_age,
                cross_referenced=con_age < 90,
            ),
            "source": "Consensus estimates (yfinance/AKShare) + LLM synthesis",
            "data_age_days": con_age,
            "note": "Expectation gap component uses LLM reasoning — verify independently",
        },
        "catalysts": {
            "label": "Catalysts",
            "rating": _auto_eqr_rating("HIGH", fin_age, cross_referenced=True),
            "source": "Management guidance + regulatory calendar",
            "data_age_days": fin_age,
        },
        "risks": {
            "label": "Risks",
            "rating": _auto_eqr_rating("MED", news_age, cross_referenced=False),
            "source": "News analysis + industry reports",
            "data_age_days": news_age,
        },
        "financials": {
            "label": "Financials",
            "rating": _auto_eqr_rating("HIGH", fin_age, cross_referenced=True),
            "source": "AKShare / yfinance financial statements",
            "data_age_days": fin_age,
        },
        "technical": {
            "label": "Technical",
            "rating": _auto_eqr_rating("HIGH", px_age, cross_referenced=True),
            "source": "AKShare / yfinance daily OHLCV",
            "data_age_days": px_age,
        },
    }

    # Overall = second-lowest section rating (one weak section shouldn't tank all)
    sorted_idxs = sorted(_eqr_idx(s["rating"]) for s in sections.values())
    overall = _eqr_from_idx(sorted_idxs[1] if len(sorted_idxs) > 1 else sorted_idxs[0])

    # AI limitations — always explicit
    con_src = "yfinance" if market == "HK" else "AKShare"
    ai_limitations = [
        f"Consensus estimates via {con_src}, not Bloomberg/Capital IQ",
        "Management intent and insider dynamics are not observable from public data",
        "Variant thesis expectation gap uses LLM reasoning — treat as hypothesis, not fact",
        "Geopolitical tail risk is narrative-based; not quantified",
    ]
    if fin_age > 90:
        ai_limitations.append(
            f"⚠️ Financial data is {fin_age} days old — EQR automatically degraded"
        )
    if con_age > 90:
        ai_limitations.append(
            f"⚠️ Consensus estimates are {con_age} days old — expectation gap may be stale"
        )

    return {
        "ticker":       ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall":      overall,
        "sections":     sections,
        "ai_limitations": ai_limitations,
        "data_freshness": data_dates,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Reverse DCF Engine  (v13.3 — no scipy, pure-Python bisection)
# ══════════════════════════════════════════════════════════════════════════════

# WACC parameters by market
MARKET_PARAMS = {
    "A":  {"rf": 0.023, "erp": 0.065},   # 10Y CGB 2.3% + A-share ERP 6.5%
    "HK": {"rf": 0.038, "erp": 0.0725},  # HIBOR-linked 3.8% + US ERP 5% + China CRP 2.25%
    "SH": {"rf": 0.023, "erp": 0.065},
    "SZ": {"rf": 0.023, "erp": 0.065},
}
BENCH_TICKERS = {"A": "000300.SS", "HK": "^HSI", "SH": "000300.SS", "SZ": "000300.SS"}
SECTOR_BETA_DEFAULTS = {
    "Technology":           1.25,
    "Consumer Cyclical":    1.10,
    "Healthcare":           1.40,
    "Communication Services":0.90,
    "Industrials":          1.05,
}
DEFAULT_BETA = 1.15
DCF_HORIZON  = 5   # forecast years


def _bisect(f, lo, hi, tol=1e-7, maxiter=200):
    """Pure-Python bisection. Returns None if root not bracketed."""
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None                  # not bracketed → no solution in range
    for _ in range(maxiter):
        mid = (lo + hi) / 2.0
        if (hi - lo) < tol:
            return mid
        fmid = f(mid)
        if fmid == 0:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return (lo + hi) / 2.0


def _calc_beta_from_hist(stock_hist, bench_hist):
    """
    Compute beta from daily Close returns using last 60 trading days.
    stock_hist, bench_hist: pandas DataFrames with a 'Close' column.
    Returns float beta, or DEFAULT_BETA on failure.
    """
    try:
        s = stock_hist["Close"].pct_change().dropna()
        b = bench_hist["Close"].pct_change().dropna()
        # Align on shared dates
        common = s.index.intersection(b.index)
        if len(common) < 20:
            return DEFAULT_BETA
        s = s.loc[common].tail(60)
        b = b.loc[common].tail(60)
        cov  = float(((s - s.mean()) * (b - b.mean())).mean())
        var  = float(((b - b.mean()) ** 2).mean())
        if var == 0:
            return DEFAULT_BETA
        beta = cov / var
        # Clamp to reasonable range (0.3 – 2.5)
        return round(max(0.30, min(2.50, beta)), 4)
    except Exception:
        return DEFAULT_BETA


def _calc_wacc(beta, market):
    p   = MARKET_PARAMS.get(market, MARKET_PARAMS["HK"])
    return p["rf"] + beta * p["erp"]


def _dcf_equity_value(fcf0, g, wacc, g_terminal, n_years, net_debt):
    """
    Intrinsic equity value = PV of FCF stream + PV of terminal value − net debt.
    FCF_t = fcf0 × (1 + g)^t
    TV    = FCF_n × (1 + g_t) / (wacc − g_t)
    Guard: wacc must exceed g_terminal.
    """
    if wacc <= g_terminal:
        return float("inf")
    pv = 0.0
    fcf_t = fcf0
    for t in range(1, n_years + 1):
        fcf_t = fcf0 * ((1.0 + g) ** t)
        pv   += fcf_t / ((1.0 + wacc) ** t)
    tv  = fcf_t * (1.0 + g_terminal) / (wacc - g_terminal)
    pv += tv / ((1.0 + wacc) ** n_years)
    return pv - net_debt


def _biotech_equity_value(rev0, g, wacc, g_terminal, n_years,
                           profitability_offset, terminal_fcf_margin, tax_rate, net_debt):
    """
    Revenue-growth model for pre-profit biotech.
    Years before profitability_offset: FCF = 0 (pre-profit burn handled via net_debt).
    Years from profitability_offset onward: FCF = Rev_t × terminal_fcf_margin × (1 − tax).
    """
    if wacc <= g_terminal:
        return float("inf")
    pv = 0.0
    fcf_last = 0.0
    for t in range(1, n_years + 1):
        rev_t = rev0 * ((1.0 + g) ** t)
        if t < profitability_offset:
            fcf_t = 0.0
        else:
            fcf_t = rev_t * terminal_fcf_margin * (1.0 - tax_rate)
        fcf_last = rev_t * terminal_fcf_margin * (1.0 - tax_rate)
        pv += fcf_t / ((1.0 + wacc) ** t)
    tv  = fcf_last * (1.0 + g_terminal) / (wacc - g_terminal)
    pv += tv / ((1.0 + wacc) ** n_years)
    return pv - net_debt


def _expectation_gap_score(delta):
    """
    Map (our_growth − implied_growth) → 0..100 score.
    Positive delta = market underprices our thesis → higher score.
    Scaled so delta = +15pp → ~75, delta = +30pp → ~90.
    """
    if delta is None:
        return 50
    # Sigmoid-ish: score = 50 + 50 × tanh(delta / 0.20)
    import math
    return round(50 + 50 * math.tanh(delta / 0.20), 1)


def generate_rdcf(pid, rdcf_cfg, focus_data, stock_hist, bench_hist):
    """
    Compute Reverse DCF for one focus stock.
    Returns a dict ready to be written to rdcf_{safe_id}.json.
    """
    result = {
        "ticker":       pid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_type":   rdcf_cfg["model_type"],
        "market":       rdcf_cfg["market"],
        "error":        None,
    }

    try:
        fund  = focus_data.get("fundamentals", {})
        mkt   = rdcf_cfg["market"]

        # ── Market cap and net debt ──
        market_cap = fund.get("market_cap")
        total_debt = fund.get("total_debt") or 0.0
        total_cash = fund.get("total_cash") or 0.0
        if not market_cap or market_cap <= 0:
            result["error"] = "market_cap_unavailable"
            return result
        net_debt = total_debt - total_cash

        # ── Beta ──
        if rdcf_cfg.get("beta_override"):
            beta = rdcf_cfg["beta_override"]
            beta_source = "manual_override"
        elif stock_hist is not None and bench_hist is not None:
            beta = _calc_beta_from_hist(stock_hist, bench_hist)
            beta_source = "yfinance_60d"
        else:
            sector = focus_data.get("meta", {}).get("sector", "")
            beta = SECTOR_BETA_DEFAULTS.get(sector, DEFAULT_BETA)
            beta_source = f"sector_default({sector or 'unknown'})"

        wacc          = _calc_wacc(beta, mkt)
        g_terminal    = rdcf_cfg["terminal_growth"]
        tax_rate      = rdcf_cfg["tax_rate"]

        result["wacc_detail"] = {
            "rf":          MARKET_PARAMS.get(mkt, {}).get("rf"),
            "erp":         MARKET_PARAMS.get(mkt, {}).get("erp"),
            "beta":        round(beta, 4),
            "beta_source": beta_source,
            "wacc":        round(wacc, 4),
            "market":      mkt,
        }

        # ── Model-specific reverse DCF ──
        if rdcf_cfg["model_type"] == "standard_fcf":
            our_growth = rdcf_cfg["our_fcf_growth"]
            fcf0 = fund.get("free_cash_flow")
            # Fallback: use operating CF × 0.7 if FCF is negative or missing
            if not fcf0 or fcf0 <= 0:
                ocf = fund.get("operating_cash_flow")
                if ocf and ocf > 0:
                    fcf0 = ocf * 0.70
                    result["fcf_note"] = "FCF<=0; proxied as OCF×0.70"
                else:
                    result["error"] = "fcf_and_ocf_both_nonpositive"
                    return result

            def obj(g):
                return _dcf_equity_value(fcf0, g, wacc, g_terminal, DCF_HORIZON, net_debt) - market_cap

            # Extended hi to 2.0 to handle hyper-growth names (e.g. 300308.SZ
            # where implied growth ~118% sits outside the old 0.95 ceiling)
            implied_g = _bisect(obj, lo=-0.15, hi=2.0)
            if implied_g is None:
                result["error"] = "bisection_no_root"
                result["bisect_debug"] = {
                    "obj_lo": round(_dcf_equity_value(fcf0, -0.15, wacc, g_terminal, DCF_HORIZON, net_debt) - market_cap, 0),
                    "obj_hi": round(_dcf_equity_value(fcf0,  2.00, wacc, g_terminal, DCF_HORIZON, net_debt) - market_cap, 0),
                }
                return result

            delta     = our_growth - implied_g
            gap_score = _expectation_gap_score(delta)
            signal    = "UNDERPRICED" if delta > 0.05 else ("OVERPRICED" if delta < -0.05 else "FAIRLY_VALUED")
            # Flag hyper-growth: market pricing in >100% annual FCF growth
            hyper_growth = implied_g > 1.0

            result.update({
                "fcf0":         round(fcf0, 0),
                "implied_fcf_growth": round(implied_g, 4),
                "our_fcf_growth":     round(our_growth, 4),
                "delta":              round(delta, 4),
                "expectation_gap_score": gap_score,
                "signal":             signal,
                "hyper_growth":       hyper_growth,
                "net_debt":           round(net_debt, 0),
                "market_cap":         round(market_cap, 0),
            })

        elif rdcf_cfg["model_type"] == "biotech_revenue":
            our_growth     = rdcf_cfg["our_rev_growth"]
            prof_year_abs  = rdcf_cfg["profitability_year"]
            current_year   = datetime.now().year
            prof_offset    = max(1, prof_year_abs - current_year)
            term_fcf_marg  = rdcf_cfg["terminal_fcf_margin"]
            rev0 = fund.get("revenue")
            if not rev0 or rev0 <= 0:
                result["error"] = "revenue_unavailable"
                return result

            def obj(g):
                return _biotech_equity_value(
                    rev0, g, wacc, g_terminal, DCF_HORIZON,
                    prof_offset, term_fcf_marg, tax_rate, net_debt
                ) - market_cap

            implied_g = _bisect(obj, lo=-0.10, hi=1.20)
            if implied_g is None:
                result["error"] = "bisection_no_root"
                return result

            delta     = our_growth - implied_g
            gap_score = _expectation_gap_score(delta)
            signal    = "UNDERPRICED" if delta > 0.05 else ("OVERPRICED" if delta < -0.05 else "FAIRLY_VALUED")

            result.update({
                "rev0":          round(rev0, 0),
                "implied_rev_growth":    round(implied_g, 4),
                "our_rev_growth":        round(our_growth, 4),
                "profitability_offset":  prof_offset,
                "terminal_fcf_margin":   term_fcf_marg,
                "delta":                 round(delta, 4),
                "expectation_gap_score": gap_score,
                "signal":                signal,
                "net_debt":              round(net_debt, 0),
                "market_cap":            round(market_cap, 0),
            })

    except Exception as e:
        result["error"] = str(e)

    return result


def generate_rdcf_for_all(focus_data, hist_cache, rdcf_config):
    """
    Run Reverse DCF for all focus stocks.
    focus_data:  dict  pid → {price, technical, fundamentals, meta, ...}
    hist_cache:  dict  pid → pandas DataFrame (6mo OHLCV)
    rdcf_config: dict  pid → config from rdcf_config.json
    Returns dict pid → rdcf result.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  ERROR: yfinance not installed"); return {}

    # Fetch benchmarks once per market
    bench_cache = {}
    for mkt, bench_sym in BENCH_TICKERS.items():
        if bench_sym not in bench_cache:
            try:
                bench_cache[bench_sym] = yf.Ticker(bench_sym).history(period="6mo")
                print(f"  Benchmark {bench_sym}: {len(bench_cache[bench_sym])} rows")
            except Exception as e:
                print(f"  Benchmark {bench_sym} error: {e}")

    results = {}
    for pid, cfg in FOCUS_TICKERS.items():
        rdcf_cfg = rdcf_config.get(pid)
        if not rdcf_cfg:
            print(f"  [{pid}] No RDCF config — skipping")
            continue
        mkt       = rdcf_cfg["market"]
        bench_sym = BENCH_TICKERS.get(mkt)
        bench_h   = bench_cache.get(bench_sym)
        stock_h   = hist_cache.get(pid)
        fd        = focus_data.get(pid, {})

        rdcf = generate_rdcf(pid, rdcf_cfg, fd, stock_h, bench_h)
        results[pid] = rdcf

        if rdcf.get("error"):
            print(f"  [{pid}] RDCF error: {rdcf['error']}")
        else:
            sig = rdcf.get("signal", "?")
            delta = rdcf.get("delta", 0)
            print(f"  [{pid}] signal={sig}  delta={delta:+.1%}  gap_score={rdcf.get('expectation_gap_score')}")

        safe_id = pid.replace(".", "_")
        with open(OUTPUT_DIR / f"rdcf_{safe_id}.json", "w", encoding="utf-8") as f:
            json.dump(rdcf, f, ensure_ascii=False, indent=2)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Macro Stress Test Engine  (v13.4)
# ══════════════════════════════════════════════════════════════════════════════

def compute_stress_test(config_path=None):
    """
    Load stress_config.json, apply macro factor shocks to each stock via
    linear sensitivity model, aggregate to portfolio level.

    Sensitivity convention (all per unit of shock):
      cny_usd : stock return per 1% CNY/USD move (positive = CNY depreciation = USD↑)
      cn_10y  : stock return per 100bp CN 10Y yield increase
      us_10y  : stock return per 100bp US 10Y yield increase
      vix     : stock return per 1 VIX point increase

    shock values in config are in natural units (e.g. cny_usd=0.03 = 3% depreciation,
    cn_10y=0.20 = 20bp, us_10y=0.50 = 50bp, vix=15 = 15 VIX points).
    """
    if config_path is None:
        config_path = OUTPUT_DIR / "stress_config.json"

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"stress_config.json not found at {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    weights   = cfg["portfolio_weights"]
    sens_map  = cfg["sensitivities"]
    scenarios = cfg["scenarios"]
    tickers   = list(weights.keys())

    results = {
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "portfolio_weights": weights,
        "scenarios":         {},
    }

    for scen_key, scen in scenarios.items():
        shocks    = scen["shocks"]
        overrides = scen.get("sector_overrides", {})
        stock_impacts = {}

        for ticker in tickers:
            s = sens_map.get(ticker, {})

            # Factor-by-factor decomposition
            impact_cny = s.get("cny_usd", 0) * shocks.get("cny_usd", 0)
            impact_cn  = s.get("cn_10y",  0) * shocks.get("cn_10y",  0)
            impact_us  = s.get("us_10y",  0) * shocks.get("us_10y",  0)
            impact_vix = s.get("vix",     0) * shocks.get("vix",     0)
            override   = overrides.get(ticker, 0)
            total      = impact_cny + impact_cn + impact_us + impact_vix + override

            stock_impacts[ticker] = {
                "name":         s.get("name", ticker),
                "total_return": round(total, 4),
                "factors": {
                    "cny_usd":        round(impact_cny, 4),
                    "cn_10y":         round(impact_cn,  4),
                    "us_10y":         round(impact_us,  4),
                    "vix":            round(impact_vix, 4),
                    "sector_override":round(override, 4),
                },
            }

        # Portfolio-level impact (weighted sum)
        portfolio_return = sum(
            weights.get(t, 0) * stock_impacts[t]["total_return"]
            for t in tickers
        )
        ev_contribution = scen.get("probability", 0) * portfolio_return

        results["scenarios"][scen_key] = {
            "name":             scen["name"],
            "description":      scen["description"],
            "probability":      scen.get("probability", 0),
            "color":            scen.get("color", "info"),
            "shocks":           shocks,
            "stock_impacts":    stock_impacts,
            "portfolio_return": round(portfolio_return, 4),
            "ev_contribution":  round(ev_contribution, 4),
        }

    # Probability-weighted expected portfolio return
    results["expected_portfolio_return"] = round(
        sum(v["ev_contribution"] for v in results["scenarios"].values()), 4
    )
    # Worst-case scenario key
    results["worst_scenario"] = min(
        results["scenarios"],
        key=lambda k: results["scenarios"][k]["portfolio_return"]
    )
    return results


# ── Helpers ─────────────────────────────────────────────────────────────────
def _safe_float(val):
    if val is None: return None
    try:
        f = float(val)
        return None if f != f else round(f, 4)
    except (ValueError, TypeError): return None

def _calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = float(rsi.iloc[-1])
    return val if val == val else None

def _calc_macd(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig: return None, None, None
    ef = closes.ewm(span=fast, adjust=False).mean()
    es = closes.ewm(span=slow, adjust=False).mean()
    ml = ef - es
    sl = ml.ewm(span=sig, adjust=False).mean()
    h = ml - sl
    return float(ml.iloc[-1]), float(sl.iloc[-1]), float(h.iloc[-1])

def _df_to_dict(df):
    result = {}
    for col in df.columns:
        period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        items = {}
        for idx in df.index:
            val = df.loc[idx, col]
            if val is not None and val == val:
                items[str(idx)] = float(val)
        result[period] = items
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 0. Universe Scorer — Barra CNE5-lite cross-sectional factor model
# ══════════════════════════════════════════════════════════════════════════════
def score_universe(stocks):
    """
    Cross-sectional factor scoring for a universe of stocks.
    Adds 'alpha_score' (0-100) and 'factors' sub-scores in-place.

    Factors (Barra CNE5 lite — all cross-sectional percentile ranks 0-100):
      value_rank:   lower PE + lower PB → higher rank (cheap is better)
      quality_rank: higher ROE → higher rank
      momentum_rank: higher 1-day change_pct → higher rank
      size_rank:    mid-size preference — very large AND very small penalised
                    (log cap closest to 60th-pct gets highest rank; avoids
                    micro-cap liquidity traps AND mega-cap priced-in effect)
      low_vol_rank: lower amplitude → higher rank (quiet stocks, quality moves)

    Composite weights (sum=1.0):
      value     25%  quality   25%  momentum  20%  size  15%  low_vol  15%

    Stocks with missing data on a factor receive the median rank for that factor
    (neutral, not penalised). Stocks with price < 2 or market_cap < 5e8 (500M)
    are excluded from scoring and receive alpha_score=0 (liquidity filter).
    """
    import math

    if not stocks:
        return stocks

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _pct_rank(values):
        """Return 0-100 percentile rank array (ties: average rank)."""
        n   = len(values)
        idx = sorted(range(n), key=lambda i: values[i] if values[i] is not None else float('-inf'))
        ranks  = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and values[idx[j]] == values[idx[j + 1]]:
                j += 1
            avg_rank = (i + j) / 2.0 / (n - 1) * 100.0 if n > 1 else 50.0
            for k in range(i, j + 1):
                ranks[idx[k]] = avg_rank
            i = j + 1
        return ranks

    def _neutral_rank(ranks):
        """Median rank for missing-value fill."""
        valid = [r for r in ranks if r is not None]
        if not valid:
            return 50.0
        s = sorted(valid)
        mid = len(s) // 2
        return (s[mid - 1] + s[mid]) / 2 if len(s) % 2 == 0 else float(s[mid])

    # ── Liquidity filter ──────────────────────────────────────────────────────
    MIN_PRICE  = 2.0
    MIN_CAP    = 5e8    # 5亿 CNY / HKD

    eligible   = []
    ineligible = set()

    for i, s in enumerate(stocks):
        px  = s.get('price')
        cap = s.get('market_cap')
        if (px  is not None and px  < MIN_PRICE) or \
           (cap is not None and cap < MIN_CAP):
            ineligible.add(i)
        else:
            eligible.append(i)

    n = len(eligible)
    if n < 10:
        # Insufficient data — zero-fill and return
        for s in stocks:
            s['alpha_score'] = 0
            s['factors']     = {}
        return stocks

    # ── Extract factor raw values (eligible stocks only) ─────────────────────
    def _get(field):
        return [stocks[i].get(field) for i in eligible]

    pe_raw  = _get('pe')
    pb_raw  = _get('pb')
    roe_raw = _get('roe')
    chg_raw = _get('change_pct')
    cap_raw = _get('market_cap')
    amp_raw = _get('amplitude')

    # ── Value: winsorize PE (1–200) and PB (0.1–30) before ranking ───────────
    def _winsor(vals, lo, hi):
        return [max(lo, min(hi, v)) if v is not None and v > 0 else None
                for v in vals]

    pe_w  = _winsor(pe_raw,  1.0,  200.0)
    pb_w  = _winsor(pb_raw,  0.1,  30.0)

    # Invert: low PE/PB → high rank; replace None with median before rank
    pe_inv  = [None if v is None else -v for v in pe_w]
    pb_inv  = [None if v is None else -v for v in pb_w]

    pe_rank  = _pct_rank(pe_inv)
    pb_rank  = _pct_rank(pb_inv)
    # Value = average of PE-rank and PB-rank (use whichever available)
    value_rank = []
    for pr, pbr in zip(pe_rank, pb_rank):
        if pe_w[len(value_rank)] is None and pb_w[len(value_rank)] is None:
            value_rank.append(None)
        elif pe_w[len(value_rank)] is None:
            value_rank.append(pbr)
        elif pb_w[len(value_rank)] is None:
            value_rank.append(pr)
        else:
            value_rank.append((pr + pbr) / 2.0)

    # ── Quality: ROE (cap at -50%..+80%) ─────────────────────────────────────
    roe_w    = _winsor(roe_raw, -50.0, 80.0)
    quality_rank = _pct_rank(roe_w)

    # ── Momentum: 1-day change_pct ────────────────────────────────────────────
    momentum_rank = _pct_rank(chg_raw)

    # ── Size: mid-size preference using log(cap) ──────────────────────────────
    log_cap  = [math.log(v) if v and v > 0 else None for v in cap_raw]
    valid_lc = [v for v in log_cap if v is not None]
    if valid_lc:
        # 60th-percentile log-cap = "sweet spot" (large-mid, not mega)
        sorted_lc = sorted(valid_lc)
        p60_lc = sorted_lc[int(len(sorted_lc) * 0.60)]
        # Distance from sweet spot (inverted: zero distance = rank 100)
        dist_from_p60 = [abs(v - p60_lc) if v is not None else None for v in log_cap]
        size_inv      = [None if v is None else -v for v in dist_from_p60]
        size_rank     = _pct_rank(size_inv)
    else:
        size_rank = [50.0] * n

    # ── Low-vol: lower amplitude = higher rank ────────────────────────────────
    amp_inv  = [None if v is None else -v for v in amp_raw]
    low_vol_rank = _pct_rank(amp_inv)

    # ── Neutral-fill missing values ────────────────────────────────────────────
    vr_med  = _neutral_rank(value_rank)
    qr_med  = _neutral_rank(quality_rank)
    mr_med  = _neutral_rank(momentum_rank)
    sr_med  = _neutral_rank(size_rank)
    lv_med  = _neutral_rank(low_vol_rank)

    def _fill(rank_list, median):
        return [median if v is None else v for v in rank_list]

    vr  = _fill(value_rank,    vr_med)
    qr  = _fill(quality_rank,  qr_med)
    mr  = _fill(momentum_rank, mr_med)
    sr  = _fill(size_rank,     sr_med)
    lvr = _fill(low_vol_rank,  lv_med)

    # ── Composite weights ──────────────────────────────────────────────────────
    W_VALUE    = 0.25
    W_QUALITY  = 0.25
    W_MOMENTUM = 0.20
    W_SIZE     = 0.15
    W_LOW_VOL  = 0.15

    # ── Write scores back ──────────────────────────────────────────────────────
    for rank_idx, stock_idx in enumerate(eligible):
        composite = (
            W_VALUE    * vr[rank_idx]  +
            W_QUALITY  * qr[rank_idx]  +
            W_MOMENTUM * mr[rank_idx]  +
            W_SIZE     * sr[rank_idx]  +
            W_LOW_VOL  * lvr[rank_idx]
        )
        stocks[stock_idx]['alpha_score'] = round(composite, 1)
        stocks[stock_idx]['factors']     = {
            'value':    round(vr[rank_idx],  1),
            'quality':  round(qr[rank_idx],  1),
            'momentum': round(mr[rank_idx],  1),
            'size':     round(sr[rank_idx],  1),
            'low_vol':  round(lvr[rank_idx], 1),
        }

    for i in ineligible:
        stocks[i]['alpha_score'] = 0
        stocks[i]['factors']     = {'excluded': True}

    # Summary stats
    scored = [s['alpha_score'] for s in stocks if s['alpha_score'] > 0]
    if scored:
        top_n   = sorted(scored, reverse=True)[:10]
        avg_top = sum(top_n) / len(top_n)
        print(f"  [score_universe] {len(eligible)}/{len(stocks)} eligible, "
              f"avg top-10 alpha={avg_top:.1f}, ineligible={len(ineligible)}")

    return stocks


# ══════════════════════════════════════════════════════════════════════════════
# 1. Full A-Share Universe
# ══════════════════════════════════════════════════════════════════════════════
def fetch_a_share_universe():
    try:
        import akshare as ak
    except ImportError:
        print("  ERROR: akshare not installed"); return []
    print("  Calling ak.stock_zh_a_spot_em()...")
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty: return []
        stocks = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code or not name: continue
            ex = "SH" if code.startswith("6") else ("BJ" if code[0] in "48" else "SZ")
            stocks.append({
                "ticker": f"{code}.{ex}", "code": code, "name": name, "exchange": ex,
                "price": _safe_float(row.get("最新价")),
                "change_pct": _safe_float(row.get("涨跌幅")),
                "change_amt": _safe_float(row.get("涨跌额")),
                "volume": _safe_float(row.get("成交量")),
                "turnover": _safe_float(row.get("成交额")),
                "amplitude": _safe_float(row.get("振幅")),
                "high": _safe_float(row.get("最高")),
                "low": _safe_float(row.get("最低")),
                "open": _safe_float(row.get("今开")),
                "prev_close": _safe_float(row.get("昨收")),
                "volume_ratio": _safe_float(row.get("量比")),
                "turnover_rate": _safe_float(row.get("换手率")),
                "pe": _safe_float(row.get("市盈率-动态")),
                "pb": _safe_float(row.get("市净率")),
                "market_cap": _safe_float(row.get("总市值")),
                "float_cap": _safe_float(row.get("流通市值")),
                "high_52w": _safe_float(row.get("52周最高")),
                "low_52w": _safe_float(row.get("52周最低")),
                "roe": _safe_float(row.get("ROE")),
                "gross_margin": _safe_float(row.get("毛利率")),
                "net_margin": _safe_float(row.get("净利率")),
                "revenue_growth": _safe_float(row.get("营收同比")),
                "profit_growth": _safe_float(row.get("净利润同比")),
            })
        print(f"  OK: {len(stocks)} A-shares")
        return stocks
    except Exception as e:
        print(f"  ERROR: {e}"); return []


# ══════════════════════════════════════════════════════════════════════════════
# 2. Full HK Universe
# ══════════════════════════════════════════════════════════════════════════════
def fetch_hk_universe():
    try:
        import akshare as ak
    except ImportError: return []
    print("  Calling ak.stock_hk_spot_em()...")
    try:
        df = ak.stock_hk_spot_em()
        if df is None or df.empty: return []
        stocks = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code or not name: continue
            stocks.append({
                "ticker": f"{code}.HK", "code": code, "name": name, "exchange": "HK",
                "price": _safe_float(row.get("最新价")),
                "change_pct": _safe_float(row.get("涨跌幅")),
                "change_amt": _safe_float(row.get("涨跌额")),
                "volume": _safe_float(row.get("成交量")),
                "turnover": _safe_float(row.get("成交额")),
                "amplitude": _safe_float(row.get("振幅")),
                "high": _safe_float(row.get("最高")),
                "low": _safe_float(row.get("最低")),
                "open": _safe_float(row.get("今开")),
                "prev_close": _safe_float(row.get("昨收")),
                "volume_ratio": _safe_float(row.get("量比")),
                "turnover_rate": _safe_float(row.get("换手率")),
                "pe": _safe_float(row.get("市盈率")),
                "pb": _safe_float(row.get("市净率")),
                "market_cap": _safe_float(row.get("总市值")),
                "high_52w": _safe_float(row.get("52周最高")),
                "low_52w": _safe_float(row.get("52周最低")),
            })
        print(f"  OK: {len(stocks)} HK stocks")
        return stocks
    except Exception as e:
        print(f"  ERROR: {e}"); return []


# ══════════════════════════════════════════════════════════════════════════════
# 3. Northbound Flow
# ══════════════════════════════════════════════════════════════════════════════
def _parse_hsgt_df(df):
    """Extract flow fields from an AKShare HSGT dataframe regardless of column names."""
    if df is None or df.empty:
        return None
    flow_col = next((c for c in [
        "净买入", "当日净流入", "净流入", "净额",
        "当日净买额", "沪深港通净买入",
    ] if c in df.columns), None)
    if not flow_col:
        # Last resort: try numeric columns > 0 in last row
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if not num_cols:
            return None
        flow_col = num_cols[0]
    recent = df.tail(20)
    return {
        "latest_net_flow": _safe_float(recent.iloc[-1][flow_col]),
        "5d_cumulative":   _safe_float(recent.tail(5)[flow_col].sum()),
        "20d_cumulative":  _safe_float(recent[flow_col].sum()),
        "trend": "inflow" if float(recent.tail(5)[flow_col].sum()) > 0 else "outflow",
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }

def fetch_northbound():
    """Try multiple AKShare endpoints in sequence — AKShare API changes frequently."""
    try:
        import akshare as ak
    except ImportError:
        return {}

    attempts = [
        lambda: ak.stock_hsgt_north_net_flow_in_em(symbol="北向"),
        lambda: ak.stock_hsgt_north_net_flow_in_em(symbol="沪深港通"),
        lambda: ak.stock_hsgt_hist_em(symbol="北向资金"),
        lambda: ak.stock_hsgt_north_acc_flow_in_em(symbol="北向"),
    ]
    for i, fn in enumerate(attempts):
        try:
            df = fn()
            result = _parse_hsgt_df(df)
            if result:
                print(f"  Northbound: OK (attempt {i+1})")
                return result
        except Exception as e:
            print(f"  Northbound attempt {i+1} failed: {type(e).__name__}: {e}")
    print("  Northbound: all attempts failed — returning empty")
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Southbound Flow (new in v4.0)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_southbound():
    """Try multiple AKShare endpoints in sequence for southbound flow."""
    try:
        import akshare as ak
    except ImportError:
        return {}

    attempts = [
        lambda: ak.stock_hsgt_south_net_flow_in_em(symbol="南向"),
        lambda: ak.stock_hsgt_south_net_flow_in_em(symbol="沪深港通"),
        lambda: ak.stock_hsgt_hist_em(symbol="南向资金"),
        lambda: ak.stock_hsgt_south_acc_flow_in_em(symbol="南向"),
    ]
    for i, fn in enumerate(attempts):
        try:
            df = fn()
            result = _parse_hsgt_df(df)
            if result:
                print(f"  Southbound: OK (attempt {i+1})")
                return result
        except Exception as e:
            print(f"  Southbound attempt {i+1} failed: {type(e).__name__}: {e}")
    print("  Southbound: all attempts failed — returning empty")
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# 5. Dragon & Tiger Board (龙虎榜) — new in v4.0
# ══════════════════════════════════════════════════════════════════════════════
def fetch_dragon_tiger():
    try:
        import akshare as ak
        today = datetime.now()
        start = (today - timedelta(days=5)).strftime("%Y%m%d")
        end   = today.strftime("%Y%m%d")
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if df is None or df.empty: return []
        # Filter for focus A-shares
        focus_codes = {cfg["akshare"] for cfg in FOCUS_TICKERS.values() if cfg.get("akshare")}
        entries = []
        for _, row in df.head(50).iterrows():
            code = str(row.get("代码", "")).strip()
            entries.append({
                "code":     code,
                "name":     str(row.get("名称", "")),
                "date":     str(row.get("上榜日期", "")),
                "reason":   str(row.get("上榜原因", "")),
                "buy_amt":  _safe_float(row.get("买入金额")),
                "sell_amt": _safe_float(row.get("卖出金额")),
                "net_amt":  _safe_float(row.get("净额")),
                "focus":    code in focus_codes,
            })
        print(f"  Dragon & Tiger: {len(entries)} entries")
        return entries
    except Exception as e:
        print(f"  Dragon & Tiger error: {e}"); return []


# ══════════════════════════════════════════════════════════════════════════════
# 6. Margin Financing (融资融券) — new in v4.0
# ══════════════════════════════════════════════════════════════════════════════
def fetch_margin():
    try:
        import akshare as ak
        today_str = datetime.now().strftime("%Y%m%d")
        margin_data = {}

        # Shanghai
        try:
            df_sh = ak.stock_margin_detail_sse(date=today_str)
            if df_sh is not None and not df_sh.empty:
                focus_sh = {cfg["akshare"]: pid
                            for pid, cfg in FOCUS_TICKERS.items()
                            if cfg.get("akshare") and cfg["exchange"] == "SH"}
                for code, pid in focus_sh.items():
                    row = df_sh[df_sh.get("股票代码", df_sh.columns[0]) == code]
                    if not row.empty:
                        r = row.iloc[0]
                        margin_data[pid] = {
                            "balance_buy":  _safe_float(r.get("融资余额")),
                            "buy_today":    _safe_float(r.get("融资买入额")),
                            "balance_sell": _safe_float(r.get("融券余量")),
                            "updated": today_str,
                        }
        except Exception as e:
            print(f"  Margin SH error: {e}")

        # Shenzhen
        try:
            df_sz = ak.stock_margin_detail_szse(date=today_str)
            if df_sz is not None and not df_sz.empty:
                focus_sz = {cfg["akshare"]: pid
                            for pid, cfg in FOCUS_TICKERS.items()
                            if cfg.get("akshare") and cfg["exchange"] == "SZ"}
                for code, pid in focus_sz.items():
                    row = df_sz[df_sz.get("证券代码", df_sz.columns[0]) == code]
                    if not row.empty:
                        r = row.iloc[0]
                        margin_data[pid] = {
                            "balance_buy":  _safe_float(r.get("融资余额")),
                            "buy_today":    _safe_float(r.get("融资买入额")),
                            "balance_sell": _safe_float(r.get("融券余量")),
                            "updated": today_str,
                        }
        except Exception as e:
            print(f"  Margin SZ error: {e}")

        print(f"  Margin: {len(margin_data)} stocks")
        return margin_data
    except Exception as e:
        print(f"  Margin error: {e}"); return {}


# ══════════════════════════════════════════════════════════════════════════════
# 7. Insider / Management Holdings — new in v4.0
# ══════════════════════════════════════════════════════════════════════════════
def fetch_insider():
    try:
        import akshare as ak
        insider_data = {}
        for pid, cfg in FOCUS_TICKERS.items():
            code = cfg.get("akshare")
            if not code: continue
            try:
                df = ak.stock_hold_management_detail_em(symbol=code)
                if df is None or df.empty: continue
                recent = df.head(10)
                entries = []
                for _, row in recent.iterrows():
                    entries.append({
                        "name":       str(row.get("姓名", "")),
                        "title":      str(row.get("职务", "")),
                        "date":       str(row.get("变动日期", "")),
                        "shares":     _safe_float(row.get("变动股数")),
                        "direction":  str(row.get("变动方向", "")),
                        "price":      _safe_float(row.get("变动均价")),
                        "after":      _safe_float(row.get("变动后持股数")),
                    })
                insider_data[pid] = entries
                time.sleep(0.5)  # rate limit courtesy
            except Exception as e:
                print(f"  Insider {pid}: {e}")

        print(f"  Insider: {len(insider_data)} stocks")
        return insider_data
    except Exception as e:
        print(f"  Insider error: {e}"); return {}


# ══════════════════════════════════════════════════════════════════════════════
# 8. Earnings Calendar + Beat/Miss — new in v4.0
# ══════════════════════════════════════════════════════════════════════════════
def fetch_earnings_calendar():
    try:
        import akshare as ak
        calendar = []

        # A-share 业绩预告 (earnings pre-announcements)
        try:
            today = datetime.now()
            quarter_end = today.strftime("%Y%m%d")
            df_yg = ak.stock_yjyg_em(date=quarter_end)
            if df_yg is not None and not df_yg.empty:
                focus_codes = {cfg["akshare"] for cfg in FOCUS_TICKERS.values() if cfg.get("akshare")}
                for _, row in df_yg.iterrows():
                    code = str(row.get("股票代码", "")).strip()
                    ex = "SH" if code.startswith("6") else "SZ"
                    ticker = f"{code}.{ex}"
                    entry = {
                        "ticker":       ticker,
                        "name":         str(row.get("股票简称", "")),
                        "period":       str(row.get("预告期间", "")),
                        "type":         str(row.get("预告类型", "")),  # 预增/预减/续亏 etc.
                        "profit_low":   _safe_float(row.get("预告净利润下限")),
                        "profit_high":  _safe_float(row.get("预告净利润上限")),
                        "change_low":   _safe_float(row.get("预告净利润变动幅度下限")),
                        "change_high":  _safe_float(row.get("预告净利润变动幅度上限")),
                        "source":       "a_share_yjyg",
                        "focus":        code in focus_codes,
                    }
                    calendar.append(entry)
        except Exception as e:
            print(f"  Earnings calendar (yg) error: {e}")

        print(f"  Earnings calendar: {len(calendar)} entries")
        return calendar
    except Exception as e:
        print(f"  Earnings calendar error: {e}"); return []


# ══════════════════════════════════════════════════════════════════════════════
# 9. Consensus Estimates — A-shares via AKShare, HK via yfinance (new in v4.0)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_consensus_a_share(code):
    """Fetch broker EPS/profit forecasts for a single A-share from EastMoney."""
    try:
        import akshare as ak
        df = ak.stock_profit_forecast_em(symbol=code)
        if df is None or df.empty: return None
        # Columns vary; extract key ones safely
        forecasts = []
        for _, row in df.head(15).iterrows():
            forecasts.append({
                "broker":        str(row.get("机构名称", row.get("券商", ""))),
                "date":          str(row.get("报告日期", row.get("日期", ""))),
                "fy1_profit":    _safe_float(row.get("预测净利润FY1", row.get("FY+1净利润", None))),
                "fy2_profit":    _safe_float(row.get("预测净利润FY2", row.get("FY+2净利润", None))),
                "fy1_eps":       _safe_float(row.get("预测每股收益FY1", row.get("FY+1EPS", None))),
                "fy2_eps":       _safe_float(row.get("预测每股收益FY2", row.get("FY+2EPS", None))),
                "target_price":  _safe_float(row.get("目标价格", row.get("目标价", None))),
                "rating":        str(row.get("评级", row.get("投资评级", ""))),
            })
        # Compute median consensus
        fy1_profits = [f["fy1_profit"] for f in forecasts if f["fy1_profit"]]
        fy1_eps_vals = [f["fy1_eps"] for f in forecasts if f["fy1_eps"]]
        targets = [f["target_price"] for f in forecasts if f["target_price"]]
        import statistics as stats
        return {
            "source": "akshare_em",
            "num_analysts": len(forecasts),
            "fy1_profit_median": _safe_float(stats.median(fy1_profits)) if fy1_profits else None,
            "fy1_eps_median":    _safe_float(stats.median(fy1_eps_vals)) if fy1_eps_vals else None,
            "target_median":     _safe_float(stats.median(targets)) if targets else None,
            "target_high":       _safe_float(max(targets)) if targets else None,
            "target_low":        _safe_float(min(targets)) if targets else None,
            "forecasts":         forecasts[:5],  # keep top 5 for display
        }
    except Exception as e:
        print(f"  Consensus A-share {code} error: {e}"); return None


def fetch_consensus_hk(tk_obj):
    """Fetch consensus estimates for HK stock via yfinance."""
    consensus = {}
    try:
        # EPS estimates by quarter/year
        ee = tk_obj.earnings_estimate
        if ee is not None and not ee.empty:
            consensus["eps_estimate"] = {
                str(idx): {
                    "avg": _safe_float(ee.loc[idx, "avg"] if "avg" in ee.columns else None),
                    "low": _safe_float(ee.loc[idx, "low"] if "low" in ee.columns else None),
                    "high": _safe_float(ee.loc[idx, "high"] if "high" in ee.columns else None),
                    "num_analysts": _safe_float(ee.loc[idx, "numberOfAnalysts"] if "numberOfAnalysts" in ee.columns else None),
                }
                for idx in ee.index
            }
    except: pass

    try:
        # Revenue estimates
        re = tk_obj.revenue_estimate
        if re is not None and not re.empty:
            consensus["revenue_estimate"] = {
                str(idx): {
                    "avg": _safe_float(re.loc[idx, "avg"] if "avg" in re.columns else None),
                    "low": _safe_float(re.loc[idx, "low"] if "low" in re.columns else None),
                    "high": _safe_float(re.loc[idx, "high"] if "high" in re.columns else None),
                }
                for idx in re.index
            }
    except: pass

    try:
        # EPS revision trend (momentum signal)
        et = tk_obj.eps_trend
        if et is not None and not et.empty:
            consensus["eps_trend"] = {
                str(idx): {
                    "current":  _safe_float(et.loc[idx, "current"] if "current" in et.columns else None),
                    "7d_ago":   _safe_float(et.loc[idx, "7daysAgo"] if "7daysAgo" in et.columns else None),
                    "30d_ago":  _safe_float(et.loc[idx, "30daysAgo"] if "30daysAgo" in et.columns else None),
                    "90d_ago":  _safe_float(et.loc[idx, "90daysAgo"] if "90daysAgo" in et.columns else None),
                }
                for idx in et.index
            }
    except: pass

    try:
        # Historical beat/miss
        eh = tk_obj.earnings_history
        if eh is not None and not eh.empty:
            history = []
            for _, row in eh.head(8).iterrows():
                history.append({
                    "date":          str(row.get("reportedDate", "")),
                    "eps_estimate":  _safe_float(row.get("epsEstimate")),
                    "eps_actual":    _safe_float(row.get("epsActual")),
                    "surprise_pct":  _safe_float(row.get("surprisePercent")),
                })
            consensus["beat_miss_history"] = history
    except: pass

    try:
        # Next earnings date
        ed = tk_obj.earnings_dates
        if ed is not None and not ed.empty:
            upcoming = ed[ed.index > datetime.now()]
            if not upcoming.empty:
                consensus["next_earnings_date"] = str(upcoming.index[0].date())
    except: pass

    consensus["source"] = "yfinance"
    return consensus if len(consensus) > 1 else None


# ══════════════════════════════════════════════════════════════════════════════
# 10. Focus Stocks — Yahoo Finance detailed + OHLC + financials + consensus
# ══════════════════════════════════════════════════════════════════════════════
# ── Direct Yahoo Finance price fetch ─────────────────────────────────────────
# Uses urllib directly with a browser User-Agent — bypasses the yfinance package
# which is frequently rate-limited/blocked by Yahoo Finance from GitHub Actions IPs.
# Same approach used in morning-report.yml which reliably works from GitHub Actions.
_YF_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ══════════════════════════════════════════════════════════════════════════════
# Twelve Data — OHLCV history (primary, replaces yfinance history calls)
# https://twelvedata.com  Free: 800 req/day, 8/min  No geo-restriction.
# Stock codes: HK → "0700:HKSE"  A-share → "300308:SZSE" or "600519:SHSE"
# ══════════════════════════════════════════════════════════════════════════════
def _to_twelvedata_symbol(yf_ticker):
    """Convert Yahoo Finance ticker to Twelve Data symbol format."""
    if yf_ticker.endswith('.HK'):
        code = yf_ticker[:-3].zfill(4)          # 0700.HK → 0700:HKSE
        return f"{code}:HKSE"
    if yf_ticker.endswith('.SZ'):
        return f"{yf_ticker[:-3]}:SZSE"          # 300308.SZ → 300308:SZSE
    if yf_ticker.endswith('.SH') or (yf_ticker.endswith('.SS')):
        return f"{yf_ticker[:-3]}:SHSE"
    # Plain ticker (US-listed ADR etc.)
    return yf_ticker

def _fetch_ohlcv_twelvedata(yf_ticker, days=90):
    """
    Fetch daily OHLCV history via Twelve Data REST API.
    Returns list of {date, open, high, low, close, volume} or None on failure.
    Requires TWELVE_DATA_KEY env var.  Uses ~1 API call.
    """
    if not TWELVE_DATA_KEY:
        return None
    symbol   = _to_twelvedata_symbol(yf_ticker)
    out_size = min(days, 5000)
    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval=1day&outputsize={out_size}"
        f"&apikey={TWELVE_DATA_KEY}&format=JSON"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        if data.get('status') == 'error' or 'values' not in data:
            print(f"    Twelve Data {symbol}: {data.get('message','no values')}")
            return None

        ohlcv = []
        for bar in reversed(data['values']):   # API returns newest-first
            try:
                ohlcv.append({
                    "date":   bar['datetime'][:10],
                    "open":   round(float(bar['open']),   3),
                    "high":   round(float(bar['high']),   3),
                    "low":    round(float(bar['low']),    3),
                    "close":  round(float(bar['close']),  3),
                    "volume": int(float(bar.get('volume', 0))),
                })
            except (KeyError, ValueError):
                continue
        print(f"    Twelve Data {symbol}: {len(ohlcv)} bars OK")
        return ohlcv if ohlcv else None
    except Exception as e:
        print(f"    Twelve Data {symbol} error: {type(e).__name__}: {e}")
        return None


def _fetch_quote_twelvedata(yf_ticker):
    """
    Fetch latest quote (price, prev_close, change_pct) via Twelve Data.
    Uses ~1 API call.  Complements _fetch_ohlcv_twelvedata.
    """
    if not TWELVE_DATA_KEY:
        return None
    symbol = _to_twelvedata_symbol(yf_ticker)
    url = (
        f"https://api.twelvedata.com/quote"
        f"?symbol={symbol}&apikey={TWELVE_DATA_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read())

        if d.get('status') == 'error':
            return None

        price = float(d.get('close') or d.get('price') or 0)
        prev  = float(d.get('previous_close') or 0)
        chg   = float(d.get('percent_change') or 0)
        if not price:
            return None

        return {
            "price":      round(price, 3),
            "prev_close": round(prev,  3),
            "change_pct": round(chg,   3),
            "high":       round(float(d.get('high', price)), 3),
            "low":        round(float(d.get('low',  price)), 3),
            "open":       round(float(d.get('open', price)), 3),
            "volume":     int(float(d.get('volume', 0))),
        }
    except Exception as e:
        print(f"    Twelve Data quote {symbol} error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Alpha Vantage — Fundamentals + Earnings Surprise
# https://alphavantage.co  Free: 25 req/day  No geo-restriction.
# ══════════════════════════════════════════════════════════════════════════════
def _to_av_symbol(yf_ticker):
    """Convert Yahoo ticker to Alpha Vantage symbol.
    AV uses: HK → '0700.HKG', A-share → '300308.SHZ'/'600519.SHH'
    """
    if yf_ticker.endswith('.HK'):
        return yf_ticker[:-3].zfill(4) + '.HKG'    # 0700.HK → 0700.HKG
    if yf_ticker.endswith('.SZ'):
        return yf_ticker[:-3] + '.SHZ'              # 300308.SZ → 300308.SHZ
    if yf_ticker.endswith('.SH') or yf_ticker.endswith('.SS'):
        return yf_ticker[:-3] + '.SHH'
    return yf_ticker

def _fetch_earnings_av(yf_ticker):
    """
    Fetch quarterly earnings (actual EPS vs estimate) from Alpha Vantage.
    Returns list of {fiscal_date, reported_eps, estimated_eps, surprise_pct}
    or None on failure.  Uses 1 API call.
    """
    if not ALPHA_VANTAGE_KEY:
        return None
    symbol = _to_av_symbol(yf_ticker)
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=EARNINGS&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read())

        if 'Note' in d:                 # rate limit hit
            print(f"    AV rate limit hit for {symbol}")
            return None
        if 'Information' in d:          # invalid key
            print(f"    AV key issue: {d['Information'][:80]}")
            return None

        qtrs = d.get('quarterlyEarnings', [])
        results = []
        for q in qtrs[:8]:              # last 8 quarters
            try:
                rep = float(q.get('reportedEPS')    or 0)
                est = float(q.get('estimatedEPS')   or 0)
                spct= float(q.get('surprisePercentage') or 0)
                results.append({
                    "fiscal_date":    q.get('fiscalDateEnding', '')[:10],
                    "reported_eps":   round(rep,  3),
                    "estimated_eps":  round(est,  3),
                    "surprise_pct":   round(spct, 2),
                    "beat":           rep > est if est else None,
                })
            except (TypeError, ValueError):
                continue
        print(f"    AV earnings {symbol}: {len(results)} quarters OK")
        return results if results else None
    except Exception as e:
        print(f"    AV earnings {symbol} error: {type(e).__name__}: {e}")
        return None


def _fetch_overview_av(yf_ticker):
    """
    Fetch company overview (PE, EPS, market cap, etc.) from Alpha Vantage.
    Returns dict or None.  Uses 1 API call.
    """
    if not ALPHA_VANTAGE_KEY:
        return None
    symbol = _to_av_symbol(yf_ticker)
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read())

        if not d.get('Symbol') or 'Note' in d:
            return None

        def _f(key):
            v = d.get(key)
            if v in (None, 'None', '-', ''):
                return None
            try:
                return float(v)
            except ValueError:
                return v

        return {
            "pe_ratio":       _f('PERatio'),
            "peg_ratio":      _f('PEGRatio'),
            "eps_ttm":        _f('EPS'),
            "book_value":     _f('BookValue'),
            "dividend_yield": _f('DividendYield'),
            "profit_margin":  _f('ProfitMargin'),
            "roe":            _f('ReturnOnEquityTTM'),
            "revenue_growth": _f('RevenueGrowthYOY'),
            "earnings_growth":_f('QuarterlyEarningsGrowthYOY'),
            "market_cap":     _f('MarketCapitalization'),
            "52w_high":       _f('52WeekHigh'),
            "52w_low":        _f('52WeekLow'),
            "analyst_target": _f('AnalystTargetPrice'),
            "sector":         d.get('Sector', ''),
            "industry":       d.get('Industry', ''),
        }
    except Exception as e:
        print(f"    AV overview {symbol} error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Tushare Pro — A-share financials + northbound flow (requires token + points)
# https://tushare.pro  Free tier: 120 points  Sign up free, earn more by usage
#
# Key APIs this platform needs:
#   moneyflow_hsgt(trade_date=today)  → northbound/southbound daily net flow
#   stock_basic()                     → full A-share listing (replaces AKShare)
#   daily(ts_code, start_date, end_date) → daily OHLCV
#   income(ts_code, period)           → income statement
#   pro.stk_factor(ts_code, start_date, end_date) → technical factors
#
# Points needed:
#   120 pts: moneyflow_hsgt, stock_basic, daily, income (all accessible free)
#   2000 pts: analyst forecasts (stk_forecast)
#
# Setup: TUSHARE_TOKEN env var → GitHub Secret
# Usage: pip install tushare && ts.set_token(TUSHARE_TOKEN) && pro = ts.pro_api()
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_northbound_tushare():
    """
    Fetch today's northbound/southbound flow via Tushare Pro.
    Returns { northbound: {...}, southbound: {...} } or None on failure.
    This REPLACES the AKShare geo-blocked version.
    Requires TUSHARE_TOKEN env var.
    """
    if not TUSHARE_TOKEN:
        return None
    try:
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()

        today = datetime.now().strftime('%Y%m%d')
        # Try last 5 trading days to handle holidays
        df = pro.moneyflow_hsgt(start_date=(datetime.now() - timedelta(days=7)).strftime('%Y%m%d'),
                                end_date=today)
        if df is None or df.empty:
            return None

        df = df.sort_values('trade_date', ascending=False)
        latest = df.iloc[0]

        def _safe(v):
            try: return float(v) if v is not None else 0.0
            except: return 0.0

        # north_money = SH+SZ northbound net (亿元); south_money = southbound
        north_today = _safe(latest.get('north_money'))   * 1e8   # convert 亿 → 元
        south_today = _safe(latest.get('south_money'))   * 1e8

        # 5-day and 20-day cumulative
        north_5d  = df.head(5)['north_money'].apply(_safe).sum() * 1e8
        north_20d = df.head(20)['north_money'].apply(_safe).sum() * 1e8
        south_5d  = df.head(5)['south_money'].apply(_safe).sum() * 1e8
        south_20d = df.head(20)['south_money'].apply(_safe).sum() * 1e8

        updated = str(latest.get('trade_date', ''))
        if len(updated) == 8:
            updated = f"{updated[:4]}-{updated[4:6]}-{updated[6:]}"

        return {
            "northbound": {
                "latest_net_flow": round(north_today, 0),
                "5d_cumulative":   round(north_5d, 0),
                "20d_cumulative":  round(north_20d, 0),
                "trend": "inflow" if north_5d > 0 else "outflow",
                "updated": updated,
                "source": "tushare",
            },
            "southbound": {
                "latest_net_flow": round(south_today, 0),
                "5d_cumulative":   round(south_5d, 0),
                "20d_cumulative":  round(south_20d, 0),
                "trend": "inflow" if south_5d > 0 else "outflow",
                "updated": updated,
                "source": "tushare",
            },
        }
    except Exception as e:
        print(f"  Tushare northbound error: {type(e).__name__}: {e}")
        return None


def _sina_code(yahoo_ticker):
    """Yahoo Finance ticker → Sina Finance code.
    0700.HK → hk00700   300308.SZ → sz300308   002594.SZ → sz002594"""
    if yahoo_ticker.endswith('.HK'):
        return 'hk' + yahoo_ticker[:-3].zfill(5)
    if yahoo_ticker.endswith('.SZ'):
        return 'sz' + yahoo_ticker[:-3]
    if yahoo_ticker.endswith('.SS') or yahoo_ticker.endswith('.SH'):
        return 'sh' + yahoo_ticker[:-3]
    return yahoo_ticker


def _fetch_prices_via_vercel(yahoo_tickers):
    """
    Batch-fetch live prices via our own Vercel /api/a-quote endpoint.
    Vercel → Sina Finance — no geo-restriction, no IP ban from GitHub Actions.
    Returns {yahoo_ticker: {price, prev_close, change_pct, high, low, open, volume, ohlcv:[]}}
    """
    sina_codes = [_sina_code(t) for t in yahoo_tickers]
    code_map   = {_sina_code(t): t for t in yahoo_tickers}  # reverse lookup

    url = f"{VERCEL_URL}/api/a-quote?codes={','.join(sina_codes)}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        quotes = data.get('quotes', [])
        if not quotes:
            print(f"  [vercel/sina] Empty response — no quotes returned")
            return {}

        result = {}
        for q in quotes:
            full_code = q.get('full_code', '')   # e.g. "sz300308"
            yahoo_tk  = code_map.get(full_code)
            if not yahoo_tk or not q.get('price'):
                continue
            result[yahoo_tk] = {
                'price':      q['price'],
                'prev_close': q.get('prev_close') or q['price'],
                'change_pct': q.get('change_pct'),
                'high':       q.get('high') or q['price'],
                'low':        q.get('low')  or q['price'],
                'open':       q.get('open') or q['price'],
                'volume':     int(q.get('volume') or 0),
                'ohlcv':      [],   # history comes from ohlc_*.json, not Sina
            }
        print(f"  [vercel/sina] {len(result)}/{len(yahoo_tickers)} prices fetched "
              f"(source: {data.get('source','?')})")
        return result

    except Exception as e:
        print(f"  [vercel/sina] Failed: {type(e).__name__}: {e}")
        return {}


def _fetch_price_direct(yf_ticker, retries=3, delay=2):
    """
    Fetch live price + 5d OHLCV via direct Yahoo Finance v8 API.
    Returns dict with price, prev_close, change_pct, ohlcv list — or None on failure.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
           f"?interval=1d&range=5d")
    fallback_url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
                    f"?interval=1d&range=5d")

    for attempt, u in enumerate([url, fallback_url] * retries):
        if attempt >= retries * 2:
            break
        try:
            req = urllib.request.Request(u, headers=_YF_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            result = data['chart']['result'][0]
            meta   = result.get('meta', {})
            price  = meta.get('regularMarketPrice') or meta.get('previousClose')
            prev   = meta.get('chartPreviousClose') or meta.get('previousClose')
            if not price:
                continue

            # Extract last-day OHLCV from indicator arrays
            ts    = result.get('timestamp', [])
            quote = (result.get('indicators', {}).get('quote') or [{}])[0]
            opens  = quote.get('open',   [])
            highs  = quote.get('high',   [])
            lows   = quote.get('low',    [])
            closes = quote.get('close',  [])
            vols   = quote.get('volume', [])

            # Last non-null close (in case today's candle is partial/null)
            last_close = next((c for c in reversed(closes) if c is not None), price)
            last_open  = next((o for o in reversed(opens)  if o is not None), price)
            last_high  = next((h for h in reversed(highs)  if h is not None), price)
            last_low   = next((l for l in reversed(lows)   if l is not None), price)
            last_vol   = next((v for v in reversed(vols)   if v is not None), 0)

            ohlcv = []
            for i, t in enumerate(ts):
                c = closes[i] if i < len(closes) else None
                if c is None:
                    continue
                ohlcv.append({
                    "date":   datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"),
                    "open":   round(opens[i],  2) if i < len(opens)  and opens[i]  else c,
                    "high":   round(highs[i],  2) if i < len(highs)  and highs[i]  else c,
                    "low":    round(lows[i],   2) if i < len(lows)   and lows[i]   else c,
                    "close":  round(c, 2),
                    "volume": int(vols[i]) if i < len(vols) and vols[i] else 0,
                })

            chg_pct = round((last_close - prev) / prev * 100, 2) if prev else None
            return {
                "price":      round(last_close, 2),
                "prev_close": round(prev, 2),
                "change_pct": chg_pct,
                "high":       round(last_high, 2),
                "low":        round(last_low,  2),
                "open":       round(last_open, 2),
                "volume":     int(last_vol),
                "ohlcv":      ohlcv,   # last 5 trading days
            }
        except Exception as e:
            print(f"    Direct price fetch attempt {attempt+1} failed for {yf_ticker}: {type(e).__name__}: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    return None


def _yf_ticker_with_session(yf_ticker):
    """Return a yfinance Ticker with a browser-like session to reduce rate limit hits."""
    try:
        import yfinance as yf
        import requests
        session = requests.Session()
        session.headers.update(_YF_HEADERS)
        return yf.Ticker(yf_ticker, session=session)
    except Exception:
        import yfinance as yf
        return yf.Ticker(yf_ticker)


def _yf_history_with_retry(tk, period="6mo", retries=3, delay=3):
    """Call tk.history() with retries — yfinance sometimes returns empty on first call."""
    import pandas as pd
    for i in range(retries):
        try:
            hist = tk.history(period=period)
            if hist is not None and not hist.empty:
                return hist
            print(f"    yfinance returned empty history (attempt {i+1}/{retries})")
        except Exception as e:
            print(f"    yfinance history error (attempt {i+1}/{retries}): {e}")
        if i < retries - 1:
            time.sleep(delay)
    return pd.DataFrame()


def fetch_capital_flow(pid, cfg, days=20):
    """
    Fetch daily capital flow (大单净流入) for A-share stocks from Eastmoney.
    Returns list of {date, close, main_net, extra_large_net, large_net} dicts,
    or empty list for HK stocks (not supported by this API).

    Eastmoney fflow/kline endpoint:
      secid format: "0.300308" (SZ), "1.600519" (SH)
      klt=101 → daily; lmt=0 → max records (returns ~180 days)
    main_net (主力净流入) = extra_large_net + large_net, in 万元 (CNY 10k units)
    """
    exchange = cfg.get("exchange", "")
    if exchange not in ("SZ", "SH"):
        return []   # HK / US not supported

    mkt_prefix = "0" if exchange == "SZ" else "1"
    code       = pid.split(".")[0]
    secid      = f"{mkt_prefix}.{code}"

    url = (
        "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
        f"?lmt=0&klt=101&secid={secid}"
        "&fields1=f1,f2,f3,f4"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        "&cb=jgj0"
    )

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")

        # Strip JSONP wrapper: jgj0({...})
        if raw.startswith("jgj0("):
            raw = raw[5:]
            if raw.endswith(")"):
                raw = raw[:-1]

        obj    = json.loads(raw)
        klines = (obj.get("data") or {}).get("klines") or []

        rows = []
        for line in klines[-days:]:          # keep only most recent `days`
            parts = line.split(",")
            if len(parts) < 7:
                continue
            def _f(i):
                try:
                    v = float(parts[i])
                    return None if v == 0.0 and parts[i] in ("0", "0.00") else v
                except (ValueError, IndexError):
                    return None
            rows.append({
                "date":            parts[0],
                "close":           _f(1),
                "main_net":        _f(2),   # 主力净流入 万元 (extra_large + large)
                "main_pct":        _f(3),   # 占比 %
                "extra_large_net": _f(4),   # 超大单净流入
                "large_net":       _f(6),   # 大单净流入
            })

        print(f"    [cflow] {pid} — {len(rows)} daily rows from Eastmoney fflow")
        return rows

    except Exception as e:
        print(f"    [cflow] {pid} — fetch failed: {e}")
        return []


def fetch_focus_stocks():
    try:
        import yfinance as yf
    except ImportError:
        print("  ERROR: yfinance not installed"); return {}, {}, {}

    results = {}
    consensus_results = {}
    hist_cache = {}   # pid → DataFrame for RDCF beta calculation

    # ── Pre-fetch all prices via Vercel/Sina (bypasses GitHub Actions IP blocks) ──
    all_yf_ids     = [cfg["yahoo"] for cfg in FOCUS_TICKERS.values()]
    vercel_prices  = _fetch_prices_via_vercel(all_yf_ids)

    for pid, cfg in FOCUS_TICKERS.items():
        yid = cfg["yahoo"]
        print(f"  [{pid}] {cfg['name_en']}...")

        # ── Step A: Price — Vercel/Sina first, Yahoo direct as fallback ──────────
        direct = vercel_prices.get(yid)
        if direct:
            print(f"    Price (Vercel/Sina): {direct['price']} (chg: {direct['change_pct']}%)")
        else:
            direct = _fetch_price_direct(yid)
            if direct:
                print(f"    Price (Yahoo direct): {direct['price']} (chg: {direct['change_pct']}%)")
            else:
                print(f"    All price sources failed for {yid}")

        # ── Step B: Get fundamentals + OHLC via yfinance (with session + retries) ──
        try:
            tk   = _yf_ticker_with_session(yid)
            info = tk.info or {}
            hist = _yf_history_with_retry(tk, period="6mo")
        except Exception as e:
            print(f"    yfinance error: {e}")
            info = {}
            import pandas as pd
            hist = pd.DataFrame()

        # ── Step C: Build price block — direct API wins, yfinance as fallback ──
        if direct:
            # Use direct API for price accuracy; augment with yfinance vol if available
            avg_vol = None
            if not hist.empty:
                avg_vol = float(hist["Volume"].tail(20).mean()) if len(hist) >= 20 else float(hist["Volume"].mean())
                vr = direct["volume"] / avg_vol if avg_vol and avg_vol > 0 else None
                high_52w = round(float(hist["High"].max()), 2)
                low_52w  = round(float(hist["Low"].min()),  2)
            else:
                vr       = None
                high_52w = direct["high"]
                low_52w  = direct["low"]

            price_block = {
                "last":          direct["price"],
                "prev_close":    direct["prev_close"],
                "change_pct":    direct["change_pct"],
                "high":          direct["high"],
                "low":           direct["low"],
                "volume":        direct["volume"],
                "avg_volume_20d":int(avg_vol) if avg_vol else None,
                "volume_ratio":  round(vr, 2) if vr else None,
                "high_52w":      high_52w,
                "low_52w":       low_52w,
            }
        elif not hist.empty:
            # Fallback: construct from yfinance history
            latest  = hist.iloc[-1]
            prev_c  = float(hist.iloc[-2]["Close"]) if len(hist) > 1 else float(latest["Close"])
            avg_vol = float(hist["Volume"].tail(20).mean()) if len(hist) >= 20 else float(hist["Volume"].mean())
            vr      = float(latest["Volume"]) / avg_vol if avg_vol > 0 else None
            price_block = {
                "last":          round(float(latest["Close"]), 2),
                "prev_close":    round(prev_c, 2),
                "change_pct":    round((float(latest["Close"]) - prev_c) / prev_c * 100, 2),
                "high":          round(float(latest["High"]), 2),
                "low":           round(float(latest["Low"]),  2),
                "volume":        int(latest["Volume"]),
                "avg_volume_20d":int(avg_vol),
                "volume_ratio":  round(vr, 2) if vr else None,
                "high_52w":      round(float(hist["High"].max()), 2),
                "low_52w":       round(float(hist["Low"].min()),  2),
            }
        else:
            print(f"    [{pid}] Both direct API and yfinance failed — skipping")
            continue

        # ── Step D: Technical indicators (requires 6mo history from yfinance) ──
        tech_block = {"sma_20":None,"sma_50":None,"sma_200":None,"rsi_14":None,
                      "macd":None,"macd_signal":None,"macd_histogram":None,
                      "above_sma_20":None,"above_sma_50":None,"above_sma_200":None}
        if not hist.empty:
            try:
                closes = hist["Close"]
                sma20  = float(closes.tail(20).mean())  if len(closes) >= 20  else None
                sma50  = float(closes.tail(50).mean())  if len(closes) >= 50  else None
                sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else None
                rsi    = _calc_rsi(closes, 14)
                macd_v, sig_v, hist_v = _calc_macd(closes)
                cur_px = price_block["last"]
                tech_block = {
                    "sma_20":        round(sma20,  2) if sma20  else None,
                    "sma_50":        round(sma50,  2) if sma50  else None,
                    "sma_200":       round(sma200, 2) if sma200 else None,
                    "rsi_14":        round(rsi,    1) if rsi    else None,
                    "macd":          round(macd_v, 4) if macd_v else None,
                    "macd_signal":   round(sig_v,  4) if sig_v  else None,
                    "macd_histogram":round(hist_v, 4) if hist_v else None,
                    "above_sma_20":  cur_px > sma20  if sma20  else None,
                    "above_sma_50":  cur_px > sma50  if sma50  else None,
                    "above_sma_200": cur_px > sma200 if sma200 else None,
                }
                hist_cache[pid] = hist
            except Exception as e:
                print(f"    Technical indicators error: {e}")

        # ── Step E: Write results[pid] ──
        results[pid] = {
            "price":        price_block,
            "technical":    tech_block,
            "fundamentals": {
                "market_cap":          info.get("marketCap"),
                "pe_trailing":         info.get("trailingPE"),
                "pe_forward":          info.get("forwardPE"),
                "ev_ebitda":           info.get("enterpriseToEbitda"),
                "ev_revenue":          info.get("enterpriseToRevenue"),
                "ps_ratio":            info.get("priceToSalesTrailing12Months"),
                "pb":                  info.get("priceToBook"),
                "dividend_yield":      info.get("dividendYield"),
                "revenue":             info.get("totalRevenue"),
                "revenue_growth":      info.get("revenueGrowth"),
                "gross_margin":        info.get("grossMargins"),
                "operating_margin":    info.get("operatingMargins"),
                "net_margin":          info.get("profitMargins"),
                "roe":                 info.get("returnOnEquity"),
                "roa":                 info.get("returnOnAssets"),
                "debt_to_equity":      info.get("debtToEquity"),
                "current_ratio":       info.get("currentRatio"),
                "quick_ratio":         info.get("quickRatio"),
                "free_cash_flow":      info.get("freeCashflow"),
                "operating_cash_flow": info.get("operatingCashflow"),
                "total_cash":          info.get("totalCash"),
                "total_debt":          info.get("totalDebt"),
                "ebitda":              info.get("ebitda"),
                "earnings_growth":     info.get("earningsGrowth"),
                "book_value":          info.get("bookValue"),
                "enterprise_value":    info.get("enterpriseValue"),
            },
            "analyst": {
                "target_mean":    info.get("targetMeanPrice"),
                "target_high":    info.get("targetHighPrice"),
                "target_low":     info.get("targetLowPrice"),
                "target_median":  info.get("targetMedianPrice"),
                "recommendation": info.get("recommendationKey"),
                "num_analysts":   info.get("numberOfAnalystOpinions"),
            },
            "meta": {
                "currency":    info.get("currency", ""),
                "exchange":    cfg["exchange"],
                "name_en":     cfg["name_en"],
                "name_zh":     cfg["name_zh"],
                "sector":      info.get("sector", ""),
                "industry":    info.get("industry", ""),
                "website":     info.get("website", ""),
                "description": (info.get("longBusinessSummary") or "")[:500],
            },
            "price_source": "direct_api" if direct else "yfinance",
        }
        print(f"    OK @ {price_block['last']} ({'+' if (price_block['change_pct'] or 0)>=0 else ''}{price_block.get('change_pct','?')}%) [{results[pid]['price_source']}]")

        # ── Step F: OHLC history ──
        safe_id = pid.replace(".", "_")
        try:
            if not hist.empty:
                # Prefer full 6mo history from yfinance
                ohlc_data = []
                for idx, row in hist.iterrows():
                    ohlc_data.append({
                        "date":   idx.strftime("%Y-%m-%d"),
                        "open":   round(float(row["Open"]),  2),
                        "high":   round(float(row["High"]),  2),
                        "low":    round(float(row["Low"]),   2),
                        "close":  round(float(row["Close"]), 2),
                        "volume": int(row["Volume"]),
                    })
            elif direct and direct.get("ohlcv"):
                # Fallback: 5d OHLCV from direct API
                ohlc_data = direct["ohlcv"]
                print(f"    OHLC: using 5d direct-API data (yfinance unavailable)")
            else:
                ohlc_data = []

            if ohlc_data:
                with open(OUTPUT_DIR / f"ohlc_{safe_id}.json", "w") as f:
                    json.dump({"ticker": pid, "data": ohlc_data,
                               "fetched_at": datetime.now().isoformat()}, f, default=str)
        except Exception as e:
            print(f"    OHLC write error: {e}")

        # ── Step G: Financial statements (from yfinance, non-critical) ──
        try:
            fin_data = {"ticker": pid, "fetched_at": datetime.now().isoformat()}
            if 'tk' in dir():  # tk may not exist if yfinance import failed
                for attr, key in [("income_stmt", "income_statement"),
                                   ("balance_sheet", "balance_sheet"),
                                   ("cashflow", "cash_flow")]:
                    try:
                        df = getattr(tk, attr)
                        if df is not None and not df.empty:
                            fin_data[key] = _df_to_dict(df)
                    except: pass
            with open(OUTPUT_DIR / f"fin_{safe_id}.json", "w", encoding="utf-8") as f:
                json.dump(fin_data, f, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"    Financials write error: {e}")

        # ── Step H: Consensus estimates (HK via yfinance, non-critical) ──
        try:
            if cfg["exchange"] == "HK" and 'tk' in dir() and info:
                cons = fetch_consensus_hk(tk)
                if cons:
                    consensus_results[pid] = cons
                    print(f"    Consensus: OK ({len(cons)} sections)")
        except Exception as e:
            print(f"    Consensus error: {e}")

    # ── A-share consensus via AKShare ──
    for pid, cfg in FOCUS_TICKERS.items():
        if cfg["exchange"] in ("SH", "SZ") and cfg.get("akshare"):
            code = cfg["akshare"]
            print(f"  [{pid}] A-share consensus...")
            cons = fetch_consensus_a_share(code)
            if cons:
                consensus_results[pid] = cons
                print(f"    Consensus: {cons['num_analysts']} analysts")
            time.sleep(0.5)

    return results, consensus_results, hist_cache


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print(f"{'='*62}")
    print(f"AR Platform v4.1 — Full Market + Consensus + Flow + EQR Auto-Rating")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. A-share universe
    print("[1/8] A-Share Universe...")
    a_stocks = fetch_a_share_universe()
    if a_stocks:
        print("  Scoring A-share universe (Barra-lite)...")
        score_universe(a_stocks)
        with open(OUTPUT_DIR / "universe_a.json", "w", encoding="utf-8") as f:
            json.dump({"_meta": {"fetched_at": datetime.now().isoformat(),
                                 "count": len(a_stocks), "version": "4.1",
                                 "scored": True, "scorer": "barra_lite_v1"},
                       "stocks": a_stocks}, f, ensure_ascii=False, default=str)
    print()

    # 2. HK universe
    print("[2/8] HK Universe...")
    hk_stocks = fetch_hk_universe()
    if hk_stocks:
        print("  Scoring HK universe (Barra-lite)...")
        score_universe(hk_stocks)
        with open(OUTPUT_DIR / "universe_hk.json", "w", encoding="utf-8") as f:
            json.dump({"_meta": {"fetched_at": datetime.now().isoformat(),
                                 "count": len(hk_stocks), "version": "4.1",
                                 "scored": True, "scorer": "barra_lite_v1"},
                       "stocks": hk_stocks}, f, ensure_ascii=False, default=str)
    print()

    # 3. Northbound flow
    print("[3/8] Northbound Flow...")
    northbound = fetch_northbound()
    print()

    # 4. Southbound flow (new)
    print("[4/8] Southbound Flow...")
    southbound = fetch_southbound()
    print()

    # 5. Dragon & Tiger board (new)
    print("[5/8] Dragon & Tiger Board (龙虎榜)...")
    dragon_tiger = fetch_dragon_tiger()
    print()

    # 6. Margin financing (new)
    print("[6/8] Margin Financing (融资融券)...")
    margin = fetch_margin()
    print()

    # 7. Focus stocks + consensus
    print("[7/8] Focus Stocks (price + OHLC + financials + consensus)...")
    focus, consensus, hist_cache = fetch_focus_stocks()
    print()

    # 7b. Capital flow (CVD proxy) — A-share only
    print("[7b/8] Capital Flow (东财大单净流入 — A-share CVD proxy)...")
    for pid, cfg in FOCUS_TICKERS.items():
        flow_rows = fetch_capital_flow(pid, cfg, days=20)
        if flow_rows:
            safe_id = pid.replace(".", "_")
            with open(OUTPUT_DIR / f"cflow_{safe_id}.json", "w", encoding="utf-8") as f:
                json.dump({
                    "ticker":     pid,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "unit":       "万元 (CNY 10k)",
                    "data":       flow_rows,
                }, f, ensure_ascii=False, indent=2)
    print()

    # 8. Earnings calendar (new)
    print("[8/8] Earnings Calendar...")
    earnings_cal = fetch_earnings_calendar()
    with open(OUTPUT_DIR / "earnings_calendar.json", "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now().isoformat(), "entries": earnings_cal},
                  f, ensure_ascii=False, indent=2, default=str)
    print()

    # ── EQR auto-ratings (one file per focus stock) ──
    print("[EQR] Generating data-driven EQR ratings...")
    today_str = datetime.now(timezone.utc).date().isoformat()
    for pid, cfg in FOCUS_TICKERS.items():
        # Estimate data dates from what we just fetched
        fin_fetched = focus.get(pid, {}).get("meta", {})
        # Price data is always today; financials we estimate from last quarterly date
        # Use yfinance income_stmt most-recent column date if available, else 90d ago
        fin_date = None
        safe_id  = pid.replace(".", "_")
        fin_file = OUTPUT_DIR / f"fin_{safe_id}.json"
        if fin_file.exists():
            try:
                fin_json = json.loads(fin_file.read_text())
                is_cols  = list((fin_json.get("income_statement") or {}).keys())
                if is_cols:
                    fin_date = sorted(is_cols)[-1][:10]
            except Exception:
                pass
        con_date = None
        if pid in consensus:
            con_date = today_str   # we just fetched it

        data_dates = {
            "financials": fin_date or (datetime.now(timezone.utc).date()
                          - timedelta(days=90)).isoformat(),
            "price":      today_str,
            "consensus":  con_date,
            "news":       today_str,
        }
        eqr = generate_eqr(
            ticker=pid,
            market=cfg["exchange"],
            data_dates=data_dates,
        )
        with open(OUTPUT_DIR / f"eqr_{safe_id}.json", "w", encoding="utf-8") as f:
            json.dump(eqr, f, ensure_ascii=False, indent=2)
        print(f"  {pid} → overall: {eqr['overall']}  "
              f"(fin:{data_dates['financials']}, con:{data_dates['consensus']})")
    print()

    # ── Reverse DCF (one file per focus stock) ──
    print("[RDCF] Running Reverse DCF engine...")
    rdcf_cfg_path = OUTPUT_DIR / "rdcf_config.json"
    rdcf_config   = {}
    if rdcf_cfg_path.exists():
        try:
            rdcf_config = json.loads(rdcf_cfg_path.read_text())
        except Exception as e:
            print(f"  WARNING: could not load rdcf_config.json: {e}")
    if rdcf_config:
        generate_rdcf_for_all(focus, hist_cache, rdcf_config)
    else:
        print("  SKIPPED: rdcf_config.json not found or empty")
    print()

    # ── Macro Stress Test ──
    print("[STRESS] Running macro stress test...")
    try:
        stress_result = compute_stress_test(OUTPUT_DIR / "stress_config.json")
        with open(OUTPUT_DIR / "stress_test.json", "w", encoding="utf-8") as f:
            json.dump(stress_result, f, ensure_ascii=False, indent=2)
        worst     = stress_result["worst_scenario"]
        worst_ret = stress_result["scenarios"][worst]["portfolio_return"]
        exp_ret   = stress_result["expected_portfolio_return"]
        print(f"  Worst case: {worst} ({worst_ret:+.1%})  |  Expected: {exp_ret:+.1%}")
    except Exception as e:
        print(f"  STRESS ERROR: {e}")
    print()

    # ── Fetch FX rates (HKD/CNY for portfolio NAV normalisation) ──────────────
    fx_rates = {"HKDCNY": 0.9165}   # fallback — 1 HKD ≈ 0.9165 CNY (Apr 2026)
    try:
        hkd_cny = yf.Ticker("HKDCNY=X").history(period="2d")
        if not hkd_cny.empty:
            fx_rates["HKDCNY"] = round(float(hkd_cny["Close"].iloc[-1]), 4)
            print(f"  FX HKDCNY={fx_rates['HKDCNY']:.4f}")
    except Exception as e:
        print(f"  FX fetch failed ({e}), using fallback 0.9165")

    # ── Write market_data.json (master for focus stocks) ──
    market_data = {
        "_meta": {
            "fetched_at": datetime.now().isoformat(),
            "version": "4.1",
            "tickers": list(FOCUS_TICKERS.keys()),
            "fx_rates": fx_rates,
        },
        "yahoo":     focus,
        "consensus": consensus,
        "akshare": {
            "northbound":   northbound,
            "southbound":   southbound,
            "dragon_tiger": dragon_tiger,
            "margin":       margin,
        },
    }
    with open(OUTPUT_DIR / "market_data.json", "w", encoding="utf-8") as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2, default=str)

    # ── Write flow_data.json (separate, loaded by Flow tab) ──
    flow_data = {
        "fetched_at":  datetime.now().isoformat(),
        "northbound":  northbound,
        "southbound":  southbound,
        "dragon_tiger":dragon_tiger,
        "margin":      margin,
    }
    with open(OUTPUT_DIR / "flow_data.json", "w", encoding="utf-8") as f:
        json.dump(flow_data, f, ensure_ascii=False, indent=2, default=str)

    # ── Write vp_snapshot.json (for Supabase sync + Dashboard) ──
    # Priority: existing snapshot values (set by DeepResearch) > VP_SCORES seed dict
    # This preserves VP scores updated via manual DeepResearch runs in the browser.
    today = datetime.now().strftime("%Y-%m-%d")

    # Load existing snapshot to preserve any DeepResearch-updated scores
    existing_vp = {}
    vp_snapshot_path = OUTPUT_DIR / "vp_snapshot.json"
    if vp_snapshot_path.exists():
        try:
            with open(vp_snapshot_path) as f:
                existing_data = json.load(f)
            for snap in existing_data.get("snapshots", []):
                if snap.get("ticker"):
                    existing_vp[snap["ticker"]] = snap
        except Exception:
            pass

    vp_snapshot = []
    for ticker, seed in VP_SCORES.items():
        close  = focus.get(ticker, {}).get("price", {}).get("last")
        volume = focus.get(ticker, {}).get("price", {}).get("volume")
        prev   = existing_vp.get(ticker, {})

        # Use existing VP score only if it was set more recently than the seed
        # (i.e., if the existing file has the same or newer date — DeepResearch updated it)
        use_existing = bool(prev and prev.get("vp_score") is not None
                            and prev.get("date", "") >= seed.get("last_updated", "2000-01-01"))

        # Preserve the actual source from the existing snapshot so we don't
        # lose provenance: "deepresearch" = human-set via browser,
        # "vp_engine" = live-computed by scripts/vp_engine.py,
        # "seed" = fallback default.
        # vp_engine.py runs AFTER this step and will overwrite fundamental_accel
        # + expectation_gap + vp_score with freshly-computed values.
        prev_source = prev.get("source", "seed") if use_existing else "seed"

        vp_snapshot.append({
            "ticker":            ticker,
            "date":              today,
            "vp_score":          prev["vp_score"]          if use_existing else seed["vp"],
            "expectation_gap":   prev.get("expectation_gap",  seed["expectation_gap"]),
            "fundamental_accel": prev.get("fundamental_accel",seed["fundamental_accel"]),
            "narrative_shift":   prev.get("narrative_shift",  seed["narrative_shift"]),
            "low_coverage":      prev.get("low_coverage",     seed["low_coverage"]),
            "catalyst_proximity":prev.get("catalyst_proximity",seed["catalyst_prox"]),
            "close":             close,
            "volume":            volume,
            "source":            prev_source,   # accurate provenance (vp_engine / deepresearch / seed)
            # wrongIf preserved from DeepResearch if available, else use seed
            "wrongIf_e":         prev.get("wrongIf_e", seed.get("wrongIf_e", "")),
            "wrongIf_z":         prev.get("wrongIf_z", seed.get("wrongIf_z", "")),
        })
        if use_existing:
            print(f"  [vp_snapshot] {ticker}: preserved DeepResearch VP {prev['vp_score']} (seed={seed['vp']})")

    with open(vp_snapshot_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "snapshots": vp_snapshot}, f, ensure_ascii=False, default=str)

    # ── Summary ──
    print(f"{'='*62}")
    print("DONE — Summary:")
    print(f"  A-shares:     {len(a_stocks):,}")
    print(f"  HK stocks:    {len(hk_stocks):,}")
    print(f"  Focus stocks: {len(focus)} (OHLC + financials + consensus)")
    print(f"  Consensus:    {len(consensus)} stocks covered")
    print(f"  D&T entries:  {len(dragon_tiger)}")
    print(f"  Margin:       {len(margin)} focus stocks")
    print(f"  Earnings cal: {len(earnings_cal)} entries")
    eqr_files    = list(OUTPUT_DIR.glob("eqr_*.json"))
    rdcf_files   = list(OUTPUT_DIR.glob("rdcf_*.json"))
    stress_exists = (OUTPUT_DIR / "stress_test.json").exists()
    print(f"  EQR ratings: {len(eqr_files)} stocks")
    print(f"  RDCF files:  {len(rdcf_files)} stocks")
    print(f"  Stress test: {'OK' if stress_exists else 'MISSING'}")
    files = list(OUTPUT_DIR.glob("*.json"))
    total = sum(f.stat().st_size for f in files)
    print(f"  JSON files:   {len(files)} ({total/1024/1024:.1f} MB)")
    print(f"{'='*62}")


if __name__ == "__main__":
    import sys
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Fetch aborted by user.")
        sys.exit(130)
    except Exception as e:
        # Catch any unhandled top-level exception so GitHub Actions reports the
        # error details in the step log rather than sending a vague failure email.
        # The 'continue-on-error: true' in the workflow means subsequent steps
        # (git commit, push) still run even when we exit non-zero here.
        import traceback
        print(f"\n{'='*62}")
        print(f"FATAL ERROR — fetch_data.py crashed with unhandled exception:")
        print(f"  {type(e).__name__}: {e}")
        print(f"Traceback:")
        traceback.print_exc()
        print(f"{'='*62}")
        print("Partial data (if any) was already written to public/data/.")
        print("Check the step log above for details on which steps succeeded.")
        sys.exit(1)
