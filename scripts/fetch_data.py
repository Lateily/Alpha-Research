#!/usr/bin/env python3
"""
AR Platform — Full Market Universe Data Fetcher
Pulls ALL A-share + HK stock data via AKShare bulk APIs + Yahoo Finance for focus stocks.

Output:
  public/data/universe_a.json   — Full A-share universe (~5000 stocks)
  public/data/universe_hk.json  — Full HK universe (~2500 stocks)
  public/data/market_data.json  — Detailed data for focus stocks (5 positions)

Run: python3 scripts/fetch_data.py
Schedule: GitHub Actions daily at 08:00 HKT
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

# ── Focus stocks (detailed Yahoo Finance data) ─────────────────────────────
FOCUS_TICKERS = {
    "300308.SZ": {"yahoo": "300308.SZ", "akshare": "300308", "exchange": "SZ", "name_en": "Innolight",       "name_zh": "中际旭创"},
    "700.HK":    {"yahoo": "0700.HK",   "akshare": None,     "exchange": "HK", "name_en": "Tencent",         "name_zh": "腾讯控股"},
    "9999.HK":   {"yahoo": "9999.HK",   "akshare": None,     "exchange": "HK", "name_en": "NetEase",         "name_zh": "网易"},
    "6160.HK":   {"yahoo": "6160.HK",   "akshare": None,     "exchange": "HK", "name_en": "BeOne Medicines", "name_zh": "百济神州"},
    "002594.SZ": {"yahoo": "002594.SZ", "akshare": "002594", "exchange": "SZ", "name_en": "BYD",             "name_zh": "比亚迪"},
}


# ══════════════════════════════════════════════════════════════════════════════
# PART 1: Full A-Share Universe via AKShare
# ══════════════════════════════════════════════════════════════════════════════
def fetch_a_share_universe() -> list:
    """Fetch ALL A-share stocks in one bulk call. Returns ~5000 stocks."""
    try:
        import akshare as ak
    except ImportError:
        print("ERROR: akshare not installed. Run: pip3 install akshare")
        return []

    print("  Calling ak.stock_zh_a_spot_em()...")
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            print("  WARNING: Empty A-share data returned")
            return []

        print(f"  Raw rows: {len(df)}, columns: {list(df.columns)}")

        stocks = []
        for _, row in df.iterrows():
            try:
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue

                # Determine exchange
                if code.startswith("6"):
                    exchange = "SH"
                    ticker = f"{code}.SH"
                elif code.startswith("0") or code.startswith("3"):
                    exchange = "SZ"
                    ticker = f"{code}.SZ"
                elif code.startswith("4") or code.startswith("8"):
                    exchange = "BJ"
                    ticker = f"{code}.BJ"
                else:
                    exchange = "SZ"
                    ticker = f"{code}.SZ"

                price = _safe_float(row.get("最新价"))
                prev_close = _safe_float(row.get("昨收"))

                stock = {
                    "ticker": ticker,
                    "code": code,
                    "name": name,
                    "exchange": exchange,
                    "price": price,
                    "change_pct": _safe_float(row.get("涨跌幅")),
                    "change_amt": _safe_float(row.get("涨跌额")),
                    "volume": _safe_float(row.get("成交量")),
                    "turnover": _safe_float(row.get("成交额")),
                    "amplitude": _safe_float(row.get("振幅")),
                    "high": _safe_float(row.get("最高")),
                    "low": _safe_float(row.get("最低")),
                    "open": _safe_float(row.get("今开")),
                    "prev_close": prev_close,
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
                }
                stocks.append(stock)
            except Exception as e:
                continue

        print(f"  Parsed {len(stocks)} A-share stocks")
        return stocks

    except Exception as e:
        print(f"  ERROR fetching A-share universe: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PART 2: Full HK Stock Universe via AKShare
# ══════════════════════════════════════════════════════════════════════════════
def fetch_hk_universe() -> list:
    """Fetch ALL HK stocks in one bulk call. Returns ~2500 stocks."""
    try:
        import akshare as ak
    except ImportError:
        return []

    print("  Calling ak.stock_hk_spot_em()...")
    try:
        df = ak.stock_hk_spot_em()
        if df is None or df.empty:
            print("  WARNING: Empty HK data returned")
            return []

        print(f"  Raw rows: {len(df)}, columns: {list(df.columns)}")

        stocks = []
        for _, row in df.iterrows():
            try:
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code or not name:
                    continue

                ticker = f"{code}.HK"
                price = _safe_float(row.get("最新价"))

                stock = {
                    "ticker": ticker,
                    "code": code,
                    "name": name,
                    "exchange": "HK",
                    "price": price,
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
                }
                stocks.append(stock)
            except Exception:
                continue

        print(f"  Parsed {len(stocks)} HK stocks")
        return stocks

    except Exception as e:
        print(f"  ERROR fetching HK universe: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# PART 3: Northbound Flow (沪深港通北向资金)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_northbound() -> dict:
    """Fetch aggregate northbound capital flow data."""
    try:
        import akshare as ak
    except ImportError:
        return {}

    print("  Fetching northbound flow...")
    try:
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
        if df is None or df.empty:
            return {}

        recent = df.tail(20)
        # Column names vary by akshare version; try common variants
        flow_col = None
        for col in ["净买入", "当日净流入", "净流入"]:
            if col in recent.columns:
                flow_col = col
                break

        if not flow_col:
            print(f"  WARNING: Cannot find flow column. Available: {list(recent.columns)}")
            return {}

        latest = float(recent.iloc[-1][flow_col])
        cum_5d = float(recent.tail(5)[flow_col].sum())
        cum_20d = float(recent[flow_col].sum())

        result = {
            "latest_net_flow": latest,
            "5d_cumulative": cum_5d,
            "20d_cumulative": cum_20d,
            "trend": "inflow" if cum_5d > 0 else "outflow",
            "updated": datetime.now().strftime("%Y-%m-%d"),
        }
        print(f"  OK: Latest = {latest:,.0f}, 5D = {cum_5d:,.0f}")
        return result

    except Exception as e:
        print(f"  ERROR fetching northbound: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# PART 4: Detailed Yahoo Finance data for focus stocks
# ══════════════════════════════════════════════════════════════════════════════
def fetch_focus_yahoo() -> dict:
    """Detailed data for 5 focus stocks via Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        print("  WARNING: yfinance not installed. Run: pip3 install yfinance")
        return {}

    results = {}
    for pid, cfg in FOCUS_TICKERS.items():
        yid = cfg["yahoo"]
        print(f"  Fetching {yid}...")
        try:
            tk = yf.Ticker(yid)
            info = tk.info or {}
            hist = tk.history(period="6mo")
            if hist.empty:
                continue

            latest = hist.iloc[-1]
            prev = hist.iloc[-2]["Close"] if len(hist) > 1 else latest["Close"]
            closes = hist["Close"]
            vols = hist["Volume"]

            # Technicals
            sma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else None
            sma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else None
            sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else None
            rsi = _calc_rsi(closes, 14)
            macd_val, sig_val, hist_val = _calc_macd(closes)

            avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else float(vols.mean())
            vol_ratio = float(latest["Volume"]) / avg_vol if avg_vol > 0 else None

            results[pid] = {
                "price": {
                    "last": round(float(latest["Close"]), 2),
                    "prev_close": round(float(prev), 2),
                    "change_pct": round((float(latest["Close"]) - float(prev)) / float(prev) * 100, 2),
                    "high": round(float(latest["High"]), 2),
                    "low": round(float(latest["Low"]), 2),
                    "volume": int(latest["Volume"]),
                    "avg_volume_20d": int(avg_vol),
                    "volume_ratio": round(vol_ratio, 2) if vol_ratio else None,
                    "high_52w": round(float(hist["High"].max()), 2),
                    "low_52w": round(float(hist["Low"].min()), 2),
                },
                "technical": {
                    "sma_20": round(sma20, 2) if sma20 else None,
                    "sma_50": round(sma50, 2) if sma50 else None,
                    "sma_200": round(sma200, 2) if sma200 else None,
                    "rsi_14": round(rsi, 1) if rsi else None,
                    "macd": round(macd_val, 4) if macd_val else None,
                    "macd_signal": round(sig_val, 4) if sig_val else None,
                    "macd_histogram": round(hist_val, 4) if hist_val else None,
                    "above_sma_20": float(latest["Close"]) > sma20 if sma20 else None,
                    "above_sma_50": float(latest["Close"]) > sma50 if sma50 else None,
                    "above_sma_200": float(latest["Close"]) > sma200 if sma200 else None,
                },
                "fundamentals": {
                    "market_cap": info.get("marketCap"),
                    "pe_trailing": info.get("trailingPE"),
                    "pe_forward": info.get("forwardPE"),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    "pb": info.get("priceToBook"),
                    "dividend_yield": info.get("dividendYield"),
                    "revenue": info.get("totalRevenue"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "gross_margin": info.get("grossMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "net_margin": info.get("profitMargins"),
                    "roe": info.get("returnOnEquity"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "free_cash_flow": info.get("freeCashflow"),
                },
                "analyst": {
                    "target_mean": info.get("targetMeanPrice"),
                    "target_high": info.get("targetHighPrice"),
                    "target_low": info.get("targetLowPrice"),
                    "recommendation": info.get("recommendationKey"),
                    "num_analysts": info.get("numberOfAnalystOpinions"),
                },
                "meta": {
                    "currency": info.get("currency", ""),
                    "exchange": cfg["exchange"],
                    "name_en": cfg["name_en"],
                    "name_zh": cfg["name_zh"],
                }
            }
            print(f"    OK: {yid} @ {latest['Close']:.2f}")
        except Exception as e:
            print(f"    ERROR: {yid} — {e}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════
def _safe_float(val):
    """Convert to float, return None if not possible."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (ValueError, TypeError):
        return None


def _calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = float(rsi.iloc[-1])
    return val if val == val else None


def _calc_macd(closes, fast=12, slow=26, signal_period=9):
    if len(closes) < slow + signal_period:
        return None, None, None
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print(f"{'='*60}")
    print(f"AR Platform — Full Market Data Fetcher")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Full A-share universe
    print("[1/4] A-Share Universe (AKShare bulk)...")
    a_stocks = fetch_a_share_universe()
    if a_stocks:
        a_output = {
            "_meta": {"fetched_at": datetime.now().isoformat(), "count": len(a_stocks), "exchange": "A-share", "source": "akshare"},
            "stocks": a_stocks,
        }
        with open(OUTPUT_DIR / "universe_a.json", "w", encoding="utf-8") as f:
            json.dump(a_output, f, ensure_ascii=False, default=str)
        print(f"  Written: universe_a.json ({len(a_stocks)} stocks, {(OUTPUT_DIR / 'universe_a.json').stat().st_size:,} bytes)\n")

    # 2. Full HK universe
    print("[2/4] HK Universe (AKShare bulk)...")
    hk_stocks = fetch_hk_universe()
    if hk_stocks:
        hk_output = {
            "_meta": {"fetched_at": datetime.now().isoformat(), "count": len(hk_stocks), "exchange": "HK", "source": "akshare"},
            "stocks": hk_stocks,
        }
        with open(OUTPUT_DIR / "universe_hk.json", "w", encoding="utf-8") as f:
            json.dump(hk_output, f, ensure_ascii=False, default=str)
        print(f"  Written: universe_hk.json ({len(hk_stocks)} stocks, {(OUTPUT_DIR / 'universe_hk.json').stat().st_size:,} bytes)\n")

    # 3. Northbound flow
    print("[3/4] Northbound Flow...")
    northbound = fetch_northbound()
    print()

    # 4. Detailed focus stocks (Yahoo Finance)
    print("[4/4] Focus Stocks (Yahoo Finance)...")
    focus = fetch_focus_yahoo()
    focus_output = {
        "_meta": {"fetched_at": datetime.now().isoformat(), "version": "2.0", "tickers": list(FOCUS_TICKERS.keys())},
        "yahoo": focus,
        "akshare": {"northbound": northbound} if northbound else {},
    }
    with open(OUTPUT_DIR / "market_data.json", "w", encoding="utf-8") as f:
        json.dump(focus_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Written: market_data.json\n")

    # Summary
    print(f"{'='*60}")
    print(f"DONE")
    print(f"  A-shares:  {len(a_stocks):,} stocks")
    print(f"  HK stocks: {len(hk_stocks):,} stocks")
    print(f"  Focus:     {len(focus)} detailed")
    print(f"  Northbound: {'OK' if northbound else 'FAILED'}")
    total_size = sum(f.stat().st_size for f in OUTPUT_DIR.glob("*.json"))
    print(f"  Total size: {total_size:,} bytes ({total_size/1024/1024:.1f} MB)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
