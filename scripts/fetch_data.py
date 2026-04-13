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
from datetime import datetime, timedelta
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
def fetch_northbound():
    try:
        import akshare as ak
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
        if df is None or df.empty: return {}
        recent = df.tail(20)
        flow_col = next((c for c in ["净买入", "当日净流入", "净流入"] if c in recent.columns), None)
        if not flow_col: return {}
        return {
            "latest_net_flow": _safe_float(recent.iloc[-1][flow_col]),
            "5d_cumulative":   _safe_float(recent.tail(5)[flow_col].sum()),
            "20d_cumulative":  _safe_float(recent[flow_col].sum()),
            "trend": "inflow" if float(recent.tail(5)[flow_col].sum()) > 0 else "outflow",
            "updated": datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print(f"  Northbound error: {e}"); return {}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Southbound Flow (new in v4.0)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_southbound():
    try:
        import akshare as ak
        df = ak.stock_hsgt_south_net_flow_in_em(symbol="南向")
        if df is None or df.empty: return {}
        recent = df.tail(20)
        flow_col = next((c for c in ["净买入", "当日净流入", "净流入"] if c in recent.columns), None)
        if not flow_col: return {}
        return {
            "latest_net_flow": _safe_float(recent.iloc[-1][flow_col]),
            "5d_cumulative":   _safe_float(recent.tail(5)[flow_col].sum()),
            "20d_cumulative":  _safe_float(recent[flow_col].sum()),
            "trend": "inflow" if float(recent.tail(5)[flow_col].sum()) > 0 else "outflow",
            "updated": datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print(f"  Southbound error: {e}"); return {}


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
        print("  ERROR: yfinance not installed"); return {}, {}

    results = {}
    consensus_results = {}

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

    return results, consensus_results


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print(f"{'='*62}")
    print(f"AR Platform v4.0 — Full Market + Consensus + Flow + Insider")
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
    focus, consensus = fetch_focus_stocks()
    print()

    # 8. Earnings calendar (new)
    print("[8/8] Earnings Calendar...")
    earnings_cal = fetch_earnings_calendar()
    with open(OUTPUT_DIR / "earnings_calendar.json", "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now().isoformat(), "entries": earnings_cal},
                  f, ensure_ascii=False, indent=2, default=str)
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
    files = list(OUTPUT_DIR.glob("*.json"))
    total = sum(f.stat().st_size for f in files)
    print(f"  JSON files:   {len(files)} ({total/1024/1024:.1f} MB)")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
