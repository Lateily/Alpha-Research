#!/usr/bin/env python3
"""
AR Platform — Daily Market Data Fetcher
Pulls live price, financial, and technical data for all portfolio positions.
Outputs JSON to public/data/market_data.json for frontend consumption.

Data Sources:
  - Yahoo Finance (yfinance): Price, volume, financials, analyst targets
  - AKShare (akshare): A-share specific data, northbound flow, sector indicators

Run: python scripts/fetch_data.py
Schedule: GitHub Actions daily at 08:00 HKT (00:00 UTC)
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
TICKERS = {
    "300308.SZ": {"yahoo": "300308.SZ", "akshare": "300308", "exchange": "SZ", "name_en": "Innolight", "name_zh": "中际旭创"},
    "700.HK":    {"yahoo": "0700.HK",   "akshare": None,     "exchange": "HK", "name_en": "Tencent",   "name_zh": "腾讯控股"},
    "9999.HK":   {"yahoo": "9999.HK",   "akshare": None,     "exchange": "HK", "name_en": "NetEase",   "name_zh": "网易"},
    "6160.HK":   {"yahoo": "6160.HK",   "akshare": None,     "exchange": "HK", "name_en": "BeOne Medicines", "name_zh": "百济神州"},
    "002594.SZ": {"yahoo": "002594.SZ", "akshare": "002594", "exchange": "SZ", "name_en": "BYD",       "name_zh": "比亚迪"},
}

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"
OUTPUT_FILE = OUTPUT_DIR / "market_data.json"

# ── Yahoo Finance Fetcher ───────────────────────────────────────────────────
def fetch_yahoo_data(ticker_map: dict) -> dict:
    """Fetch price, volume, financials, and analyst data from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        print("WARNING: yfinance not installed. Run: pip install yfinance")
        return {}

    results = {}
    for platform_id, config in ticker_map.items():
        yahoo_id = config["yahoo"]
        print(f"  Fetching Yahoo data for {yahoo_id}...")
        try:
            tk = yf.Ticker(yahoo_id)
            info = tk.info or {}

            # Price data
            hist = tk.history(period="6mo")
            if hist.empty:
                print(f"    WARNING: No price history for {yahoo_id}")
                continue

            latest = hist.iloc[-1]
            prev_close = hist.iloc[-2]["Close"] if len(hist) > 1 else latest["Close"]

            # 52-week range
            hist_1y = tk.history(period="1y")
            high_52w = hist_1y["High"].max() if not hist_1y.empty else None
            low_52w = hist_1y["Low"].min() if not hist_1y.empty else None

            # Volume metrics
            avg_vol_20d = hist.tail(20)["Volume"].mean() if len(hist) >= 20 else hist["Volume"].mean()

            # Technical indicators (simple)
            closes = hist["Close"]
            sma_20 = closes.tail(20).mean() if len(closes) >= 20 else None
            sma_50 = closes.tail(50).mean() if len(closes) >= 50 else None
            sma_200 = closes.tail(200).mean() if len(closes) >= 200 else None

            # RSI (14-day)
            rsi_14 = _calc_rsi(closes, 14)

            # MACD
            macd, signal, histogram = _calc_macd(closes)

            results[platform_id] = {
                "price": {
                    "last": round(latest["Close"], 2),
                    "prev_close": round(prev_close, 2),
                    "change_pct": round((latest["Close"] - prev_close) / prev_close * 100, 2),
                    "high": round(latest["High"], 2),
                    "low": round(latest["Low"], 2),
                    "volume": int(latest["Volume"]),
                    "avg_volume_20d": int(avg_vol_20d),
                    "volume_ratio": round(latest["Volume"] / avg_vol_20d, 2) if avg_vol_20d > 0 else None,
                    "high_52w": round(high_52w, 2) if high_52w else None,
                    "low_52w": round(low_52w, 2) if low_52w else None,
                },
                "technical": {
                    "sma_20": round(sma_20, 2) if sma_20 else None,
                    "sma_50": round(sma_50, 2) if sma_50 else None,
                    "sma_200": round(sma_200, 2) if sma_200 else None,
                    "rsi_14": round(rsi_14, 1) if rsi_14 else None,
                    "macd": round(macd, 4) if macd else None,
                    "macd_signal": round(signal, 4) if signal else None,
                    "macd_histogram": round(histogram, 4) if histogram else None,
                    "above_sma_20": latest["Close"] > sma_20 if sma_20 else None,
                    "above_sma_50": latest["Close"] > sma_50 if sma_50 else None,
                    "above_sma_200": latest["Close"] > sma_200 if sma_200 else None,
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
                    "exchange": config["exchange"],
                    "name_en": config["name_en"],
                    "name_zh": config["name_zh"],
                }
            }
            print(f"    OK: {yahoo_id} @ {latest['Close']:.2f}")

        except Exception as e:
            print(f"    ERROR fetching {yahoo_id}: {e}")
            results[platform_id] = {"error": str(e)}

    return results


# ── AKShare Fetcher (A-share specific) ──────────────────────────────────────
def fetch_akshare_data(ticker_map: dict) -> dict:
    """Fetch A-share specific data: northbound flow, margin trading, block trades."""
    try:
        import akshare as ak
    except ImportError:
        print("WARNING: akshare not installed. Run: pip install akshare")
        return {}

    results = {}

    # 1. Northbound (沪深港通北向资金) — portfolio-level signal
    print("  Fetching northbound flow data...")
    try:
        # Daily northbound net buy
        north_df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
        if north_df is not None and not north_df.empty:
            recent = north_df.tail(20)
            results["northbound"] = {
                "latest_net_flow": float(recent.iloc[-1].get("净买入", 0)),
                "5d_cumulative": float(recent.tail(5).get("净买入", 0).sum()) if "净买入" in recent.columns else None,
                "20d_cumulative": float(recent.get("净买入", 0).sum()) if "净买入" in recent.columns else None,
                "trend": "inflow" if float(recent.tail(5).get("净买入", 0).sum()) > 0 else "outflow",
                "updated": datetime.now().strftime("%Y-%m-%d"),
            }
            print(f"    OK: Northbound net flow = {results['northbound']['latest_net_flow']:.0f}")
    except Exception as e:
        print(f"    ERROR fetching northbound: {e}")
        results["northbound"] = {"error": str(e)}

    # 2. Per-stock A-share specific data
    for platform_id, config in ticker_map.items():
        ak_code = config.get("akshare")
        if not ak_code:
            continue

        print(f"  Fetching AKShare data for {ak_code}...")
        stock_data = {}

        # Northbound holding for specific stock
        try:
            hold_df = ak.stock_hsgt_individual_em(symbol=ak_code)
            if hold_df is not None and not hold_df.empty:
                latest_hold = hold_df.iloc[-1]
                stock_data["northbound_holding"] = {
                    "shares_held": float(latest_hold.get("持股数量", 0)),
                    "pct_of_float": float(latest_hold.get("持股占比", 0)),
                    "change_pct": float(latest_hold.get("持股变动", 0)) if "持股变动" in hold_df.columns else None,
                }
        except Exception as e:
            stock_data["northbound_holding"] = {"error": str(e)}

        # Margin trading data (融资融券)
        try:
            margin_df = ak.stock_margin_detail_sse(code=ak_code) if config["exchange"] == "SH" else None
            # Note: Different function for SZ exchange
            if margin_df is not None and not margin_df.empty:
                latest_margin = margin_df.iloc[-1]
                stock_data["margin"] = {
                    "margin_balance": float(latest_margin.get("融资余额", 0)),
                    "short_balance": float(latest_margin.get("融券余额", 0)),
                }
        except Exception as e:
            stock_data["margin"] = {"error": str(e)}

        if stock_data:
            results[platform_id] = stock_data
            print(f"    OK: {ak_code} AKShare data fetched")

    return results


# ── Technical Indicator Helpers ─────────────────────────────────────────────
def _calc_rsi(closes, period=14):
    """Calculate RSI from a pandas Series of closing prices."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else None


def _calc_macd(closes, fast=12, slow=26, signal_period=9):
    """Calculate MACD, Signal, and Histogram."""
    if len(closes) < slow + signal_period:
        return None, None, None
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


# ── Sector Indicators (from public sources) ─────────────────────────────────
def fetch_sector_indicators() -> dict:
    """Fetch macro / sector indicators that refresh daily."""
    indicators = {}

    try:
        import akshare as ak

        # China PMI
        try:
            pmi_df = ak.macro_china_pmi()
            if pmi_df is not None and not pmi_df.empty:
                latest_pmi = pmi_df.iloc[-1]
                indicators["china_pmi"] = {
                    "value": float(latest_pmi.get("制造业PMI", 0)),
                    "date": str(latest_pmi.get("日期", "")),
                }
        except Exception:
            pass

        # CNY/USD exchange rate
        try:
            fx_df = ak.fx_spot_quote()
            if fx_df is not None and not fx_df.empty:
                usd_row = fx_df[fx_df["货币对"].str.contains("USD/CNY")]
                if not usd_row.empty:
                    indicators["usd_cny"] = {
                        "value": float(usd_row.iloc[0].get("最新价", 0)),
                    }
        except Exception:
            pass

    except ImportError:
        pass

    return indicators


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"=== AR Platform Data Fetcher ===")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output = {
        "_meta": {
            "fetched_at": datetime.now().isoformat(),
            "version": "1.0",
            "tickers": list(TICKERS.keys()),
        },
        "yahoo": {},
        "akshare": {},
        "sector_indicators": {},
    }

    # Yahoo Finance
    print("[1/3] Yahoo Finance...")
    output["yahoo"] = fetch_yahoo_data(TICKERS)
    print()

    # AKShare (A-share specific)
    print("[2/3] AKShare...")
    output["akshare"] = fetch_akshare_data(TICKERS)
    print()

    # Sector indicators
    print("[3/3] Sector Indicators...")
    output["sector_indicators"] = fetch_sector_indicators()
    print()

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"Output written to {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size:,} bytes")
    print("Done.")


if __name__ == "__main__":
    main()
