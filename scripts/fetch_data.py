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

import json, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

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
VP_SCORES = {
    "300308.SZ": {"vp": 79, "expectation_gap": 72, "fundamental_accel": 80,
                  "narrative_shift": 65, "low_coverage": 55, "catalyst_prox": 85},
    "700.HK":    {"vp": 64, "expectation_gap": 68, "fundamental_accel": 70,
                  "narrative_shift": 75, "low_coverage": 40, "catalyst_prox": 60},
    "9999.HK":   {"vp": 58, "expectation_gap": 62, "fundamental_accel": 55,
                  "narrative_shift": 50, "low_coverage": 45, "catalyst_prox": 65},
    "6160.HK":   {"vp": 65, "expectation_gap": 72, "fundamental_accel": 65,
                  "narrative_shift": 68, "low_coverage": 45, "catalyst_prox": 70},
    "002594.SZ": {"vp": 52, "expectation_gap": 55, "fundamental_accel": 60,
                  "narrative_shift": 45, "low_coverage": 35, "catalyst_prox": 50},
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

            implied_g = _bisect(obj, lo=-0.15, hi=0.95)
            if implied_g is None:
                result["error"] = "bisection_no_root"
                result["bisect_debug"] = {
                    "obj_lo": round(_dcf_equity_value(fcf0, -0.15, wacc, g_terminal, DCF_HORIZON, net_debt) - market_cap, 0),
                    "obj_hi": round(_dcf_equity_value(fcf0,  0.95, wacc, g_terminal, DCF_HORIZON, net_debt) - market_cap, 0),
                }
                return result

            delta     = our_growth - implied_g
            gap_score = _expectation_gap_score(delta)
            signal    = "UNDERPRICED" if delta > 0.05 else ("OVERPRICED" if delta < -0.05 else "FAIRLY_VALUED")

            result.update({
                "fcf0":         round(fcf0, 0),
                "implied_fcf_growth": round(implied_g, 4),
                "our_fcf_growth":     round(our_growth, 4),
                "delta":              round(delta, 4),
                "expectation_gap_score": gap_score,
                "signal":             signal,
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
def fetch_focus_stocks():
    try:
        import yfinance as yf
    except ImportError:
        print("  ERROR: yfinance not installed"); return {}, {}, {}

    results = {}
    consensus_results = {}
    hist_cache = {}   # pid → DataFrame for RDCF beta calculation

    for pid, cfg in FOCUS_TICKERS.items():
        yid = cfg["yahoo"]
        print(f"  [{pid}] {cfg['name_en']}...")
        try:
            tk = yf.Ticker(yid)
            info = tk.info or {}
            hist = tk.history(period="6mo")
            if hist.empty: continue

            latest = hist.iloc[-1]
            prev   = hist.iloc[-2]["Close"] if len(hist) > 1 else latest["Close"]
            closes = hist["Close"]
            vols   = hist["Volume"]
            sma20  = float(closes.tail(20).mean())  if len(closes) >= 20  else None
            sma50  = float(closes.tail(50).mean())  if len(closes) >= 50  else None
            sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else None
            rsi    = _calc_rsi(closes, 14)
            macd_v, sig_v, hist_v = _calc_macd(closes)
            avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else float(vols.mean())
            vr = float(latest["Volume"]) / avg_vol if avg_vol > 0 else None

            results[pid] = {
                "price": {
                    "last":          round(float(latest["Close"]), 2),
                    "prev_close":    round(float(prev), 2),
                    "change_pct":    round((float(latest["Close"]) - float(prev)) / float(prev) * 100, 2),
                    "high":          round(float(latest["High"]), 2),
                    "low":           round(float(latest["Low"]),  2),
                    "volume":        int(latest["Volume"]),
                    "avg_volume_20d":int(avg_vol),
                    "volume_ratio":  round(vr, 2) if vr else None,
                    "high_52w":      round(float(hist["High"].max()), 2),
                    "low_52w":       round(float(hist["Low"].min()),  2),
                },
                "technical": {
                    "sma_20":        round(sma20,   2) if sma20   else None,
                    "sma_50":        round(sma50,   2) if sma50   else None,
                    "sma_200":       round(sma200,  2) if sma200  else None,
                    "rsi_14":        round(rsi,     1) if rsi     else None,
                    "macd":          round(macd_v,  4) if macd_v  else None,
                    "macd_signal":   round(sig_v,   4) if sig_v   else None,
                    "macd_histogram":round(hist_v,  4) if hist_v  else None,
                    "above_sma_20":  float(latest["Close"]) > sma20  if sma20  else None,
                    "above_sma_50":  float(latest["Close"]) > sma50  if sma50  else None,
                    "above_sma_200": float(latest["Close"]) > sma200 if sma200 else None,
                },
                "fundamentals": {
                    "market_cap":        info.get("marketCap"),
                    "pe_trailing":       info.get("trailingPE"),
                    "pe_forward":        info.get("forwardPE"),
                    "ev_ebitda":         info.get("enterpriseToEbitda"),
                    "ev_revenue":        info.get("enterpriseToRevenue"),
                    "ps_ratio":          info.get("priceToSalesTrailing12Months"),
                    "pb":                info.get("priceToBook"),
                    "dividend_yield":    info.get("dividendYield"),
                    "revenue":           info.get("totalRevenue"),
                    "revenue_growth":    info.get("revenueGrowth"),
                    "gross_margin":      info.get("grossMargins"),
                    "operating_margin":  info.get("operatingMargins"),
                    "net_margin":        info.get("profitMargins"),
                    "roe":               info.get("returnOnEquity"),
                    "roa":               info.get("returnOnAssets"),
                    "debt_to_equity":    info.get("debtToEquity"),
                    "current_ratio":     info.get("currentRatio"),
                    "quick_ratio":       info.get("quickRatio"),
                    "free_cash_flow":    info.get("freeCashflow"),
                    "operating_cash_flow":info.get("operatingCashflow"),
                    "total_cash":        info.get("totalCash"),
                    "total_debt":        info.get("totalDebt"),
                    "ebitda":            info.get("ebitda"),
                    "earnings_growth":   info.get("earningsGrowth"),
                    "book_value":        info.get("bookValue"),
                    "enterprise_value":  info.get("enterpriseValue"),
                },
                "analyst": {
                    "target_mean":   info.get("targetMeanPrice"),
                    "target_high":   info.get("targetHighPrice"),
                    "target_low":    info.get("targetLowPrice"),
                    "target_median": info.get("targetMedianPrice"),
                    "recommendation":info.get("recommendationKey"),
                    "num_analysts":  info.get("numberOfAnalystOpinions"),
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
            }

            # ── Cache hist for RDCF beta calculation ──
            hist_cache[pid] = hist

            # ── OHLC history ──
            ohlc_data = []
            for idx, row in hist.iterrows():
                ohlc_data.append({
                    "date":   idx.strftime("%Y-%m-%d"),
                    "open":   round(float(row["Open"]),   2),
                    "high":   round(float(row["High"]),   2),
                    "low":    round(float(row["Low"]),    2),
                    "close":  round(float(row["Close"]),  2),
                    "volume": int(row["Volume"]),
                })
            safe_id = pid.replace(".", "_")
            with open(OUTPUT_DIR / f"ohlc_{safe_id}.json", "w") as f:
                json.dump({"ticker": pid, "data": ohlc_data,
                           "fetched_at": datetime.now().isoformat()}, f, default=str)

            # ── Financial statements ──
            fin_data = {"ticker": pid, "fetched_at": datetime.now().isoformat()}
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

            # ── Consensus estimates (HK via yfinance) ──
            if cfg["exchange"] == "HK":
                cons = fetch_consensus_hk(tk)
                if cons:
                    consensus_results[pid] = cons
                    print(f"    Consensus: OK ({len(cons)} sections)")

            print(f"    OK @ {latest['Close']:.2f}")

        except Exception as e:
            print(f"    ERROR: {yid} — {e}")

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
        with open(OUTPUT_DIR / "universe_a.json", "w", encoding="utf-8") as f:
            json.dump({"_meta": {"fetched_at": datetime.now().isoformat(),
                                 "count": len(a_stocks), "version": "4.0"},
                       "stocks": a_stocks}, f, ensure_ascii=False, default=str)
    print()

    # 2. HK universe
    print("[2/8] HK Universe...")
    hk_stocks = fetch_hk_universe()
    if hk_stocks:
        with open(OUTPUT_DIR / "universe_hk.json", "w", encoding="utf-8") as f:
            json.dump({"_meta": {"fetched_at": datetime.now().isoformat(),
                                 "count": len(hk_stocks), "version": "4.0"},
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

    # ── Write market_data.json (master for focus stocks) ──
    market_data = {
        "_meta": {
            "fetched_at": datetime.now().isoformat(),
            "version": "4.0",
            "tickers": list(FOCUS_TICKERS.keys()),
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

    # ── Write vp_snapshot.json (for Supabase sync) ──
    today = datetime.now().strftime("%Y-%m-%d")
    vp_snapshot = []
    for ticker, vp in VP_SCORES.items():
        close = focus.get(ticker, {}).get("price", {}).get("last")
        volume = focus.get(ticker, {}).get("price", {}).get("volume")
        vp_snapshot.append({
            "ticker":           ticker,
            "date":             today,
            "vp_score":         vp["vp"],
            "expectation_gap":  vp["expectation_gap"],
            "fundamental_accel":vp["fundamental_accel"],
            "narrative_shift":  vp["narrative_shift"],
            "low_coverage":     vp["low_coverage"],
            "catalyst_proximity":vp["catalyst_prox"],
            "close":            close,
            "volume":           volume,
        })
    with open(OUTPUT_DIR / "vp_snapshot.json", "w", encoding="utf-8") as f:
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
    main()
