#!/usr/bin/env python3
"""
AR Platform — Paper Trading Engine
Reads trades.json, fetches current prices, computes positions + P&L + analytics.
Outputs positions.json, snapshots.json, analytics.json.

This script runs daily via GitHub Actions after fetch_data.py.
Frontend reads the output JSON files — zero backend infrastructure needed.

Usage:
  python3 scripts/paper_trading.py

Trade entry format (add to public/data/trades.json manually or via platform UI):
  [
    {
      "id": "t001",
      "date": "2026-04-01",
      "ticker": "300308.SZ",
      "name": "中际旭创",
      "market": "SZ",          -- SH / SZ / HK
      "side": "BUY",            -- BUY / SELL
      "quantity": 100,
      "price": 720.00,
      "currency": "CNY",
      "sector_sw": "电子",      -- Shenwan L1 sector
      "notes": "VP 79, 1.6T catalyst imminent"
    }
  ]
"""

import json, os
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path(__file__).parent.parent / "public" / "data"

# Transaction cost assumptions (round-trip)
TX_COST = {"SH": 0.0020, "SZ": 0.0020, "HK": 0.0040}

# Risk-free rate (China 1Y deposit rate)
RISK_FREE_ANNUAL = 0.020

# Benchmark tickers in OHLCV data (fetched separately by fetch_data.py)
CSI300_TICKER  = "000300.SH"
HSI_TICKER     = "HSI.HK"

# Base currency: all NAV figures normalised to CNY
BASE_CURRENCY  = "CNY"
FX_FALLBACK    = {"HKDCNY": 0.9165}   # 1 HKD ≈ 0.9165 CNY (Apr 2026 fallback)


def get_fx_rates(market_data: dict) -> dict:
    """Return FX rates dict from market_data._meta, falling back to hardcoded."""
    rates = market_data.get("_meta", {}).get("fx_rates", {})
    out = dict(FX_FALLBACK)
    out.update(rates)
    return out


def to_cny(value: float, currency: str, fx: dict) -> float:
    """Convert value in given currency to CNY using fx rates."""
    if currency in ("CNY", "RMB"):
        return value
    if currency == "HKD":
        return value * fx.get("HKDCNY", FX_FALLBACK["HKDCNY"])
    # USD fallback (not currently used)
    if currency == "USD":
        return value * fx.get("USDCNY", 7.25)
    return value   # unknown — pass through


def load_json(filename, default):
    f = DATA_DIR / filename
    if not f.exists():
        return default
    with open(f) as fh:
        return json.load(fh)


def save_json(filename, data):
    with open(DATA_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def get_current_price(ticker, market_data):
    """Get latest close from market_data.json."""
    yd = market_data.get("yahoo", {}).get(ticker, {})
    if yd:
        return yd.get("price", {}).get("last")
    # Fallback: check universe data (loaded separately)
    return None


def build_positions(trades, market_data):
    """
    Compute current positions from trade list.
    Returns dict: { ticker -> position_dict }
    """
    from collections import defaultdict
    holdings = defaultdict(lambda: {"qty": 0, "cost_basis": 0.0, "currency": "CNY",
                                     "market": "SZ", "sector_sw": "", "name": "", "trades": []})

    for t in sorted(trades, key=lambda x: x["date"]):
        tk  = t["ticker"]
        qty = t["quantity"]
        price = t["price"]
        side = t["side"].upper()
        market = t.get("market", "SZ")
        cost = price * qty * (1 + TX_COST.get(market, 0.002))

        h = holdings[tk]
        h["name"]       = t.get("name", tk)
        h["currency"]   = t.get("currency", "CNY")
        h["market"]     = market
        h["sector_sw"]  = t.get("sector_sw", "")
        h["trades"].append(t)

        if side == "BUY":
            total_cost  = h["cost_basis"] * h["qty"] + cost
            h["qty"]   += qty
            h["cost_basis"] = total_cost / h["qty"] if h["qty"] > 0 else 0
        elif side == "SELL":
            h["qty"] -= qty
            # cost basis unchanged on sell (FIFO approximation)

    # Remove closed positions
    return {tk: h for tk, h in holdings.items() if h["qty"] > 0}


def compute_positions_output(holdings, market_data):
    """Enrich positions with current price + P&L.
    All CNY-normalised values use fx rates from market_data._meta.fx_rates.
    P&L % is always in native currency (HKD for HK, CNY for A).
    NAV / weights are in CNY.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    fx    = get_fx_rates(market_data)
    positions = []
    total_value_cny = 0.0
    total_cost_cny  = 0.0

    for tk, h in holdings.items():
        current_price = get_current_price(tk, market_data)
        if current_price is None:
            current_price = h["cost_basis"]  # fallback

        qty       = h["qty"]
        avg_cost  = h["cost_basis"]
        currency  = h["currency"]
        mkt_value = current_price * qty          # native currency
        cost_value= avg_cost * qty               # native currency
        pnl_abs   = mkt_value - cost_value       # native currency
        pnl_pct   = (current_price / avg_cost - 1) * 100 if avg_cost > 0 else 0

        # CNY-normalised versions for portfolio-level NAV
        mkt_value_cny  = to_cny(mkt_value,  currency, fx)
        cost_value_cny = to_cny(cost_value, currency, fx)
        pnl_abs_cny    = mkt_value_cny - cost_value_cny

        # Holding period
        buy_dates = [t["date"] for t in h["trades"] if t["side"].upper() == "BUY"]
        first_buy = min(buy_dates) if buy_dates else today
        holding_days = (datetime.now() - datetime.strptime(first_buy, "%Y-%m-%d")).days

        # Collect signal attribution from all BUY trades (most recent first)
        buy_trades = sorted(
            [t for t in h["trades"] if t["side"].upper() == "BUY"],
            key=lambda x: x["date"], reverse=True
        )
        entry_attribution = None
        vp_at_entry       = None
        wrongif_at_entry  = None
        for bt in buy_trades:
            if bt.get("signal_attribution"):
                entry_attribution = bt["signal_attribution"]
            if bt.get("vp_at_entry") is not None:
                vp_at_entry = bt["vp_at_entry"]
            if bt.get("wrongIf_at_entry"):
                wrongif_at_entry = bt["wrongIf_at_entry"]
            if entry_attribution:
                break   # use most recent BUY with attribution

        positions.append({
            "ticker":             tk,
            "name":               h["name"],
            "market":             h["market"],
            "sector_sw":          h["sector_sw"],
            "currency":           currency,
            "quantity":           qty,
            "avg_cost":           round(avg_cost, 4),
            "current_price":      round(current_price, 4),
            # Native-currency values (for display in position currency)
            "market_value":       round(mkt_value, 2),
            "cost_value":         round(cost_value, 2),
            "pnl_abs":            round(pnl_abs, 2),
            "pnl_pct":            round(pnl_pct, 2),
            # CNY-normalised values (for portfolio aggregation)
            "market_value_cny":   round(mkt_value_cny, 2),
            "cost_value_cny":     round(cost_value_cny, 2),
            "pnl_abs_cny":        round(pnl_abs_cny, 2),
            "fx_rate_used":       fx.get("HKDCNY") if currency == "HKD" else 1.0,
            "holding_days":       holding_days,
            "as_of":              today,
            # Signal attribution — enables signal quality feedback loop
            "signal_attribution": entry_attribution,
            "vp_at_entry":        vp_at_entry,
            "wrongIf_at_entry":   wrongif_at_entry,
        })
        total_value_cny += mkt_value_cny
        total_cost_cny  += cost_value_cny

    # Compute weights based on CNY-normalised values
    for p in positions:
        p["weight_pct"] = round(p["market_value_cny"] / total_value_cny * 100, 2) if total_value_cny > 0 else 0

    return positions, total_value_cny, total_cost_cny


def compute_analytics(positions, snapshots_history):
    """
    Compute portfolio-level analytics:
    - Total P&L, P&L %
    - Daily return (today vs yesterday NAV)
    - Cumulative return since inception
    - Hit rate (% positions in profit)
    - Sector concentration
    - Jensen's alpha proxy (simplified)
    """
    if not positions:
        return {}

    # Use CNY-normalised values for all portfolio-level aggregates
    total_value = sum(p.get("market_value_cny", p["market_value"]) for p in positions)
    total_cost  = sum(p.get("cost_value_cny",   p["cost_value"])   for p in positions)
    total_pnl   = total_value - total_cost
    total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

    # Hit rate (native pnl_pct is fine — gain/loss sign is currency-invariant)
    winners = sum(1 for p in positions if p["pnl_pct"] > 0)
    hit_rate = winners / len(positions) * 100

    # Sector weights (already CNY-normalised via weight_pct)
    sector_weights = {}
    for p in positions:
        s = p.get("sector_sw", "Unknown")
        sector_weights[s] = sector_weights.get(s, 0) + p.get("weight_pct", 0)

    # Daily return (from snapshots history — all snapshots store CNY NAV)
    daily_return = None
    if len(snapshots_history) >= 2:
        prev_nav = snapshots_history[-2].get("nav")
        curr_nav = snapshots_history[-1].get("nav") if snapshots_history else None
        if prev_nav and curr_nav and prev_nav > 0:
            daily_return = round((curr_nav / prev_nav - 1) * 100, 2)

    # Inception return
    if snapshots_history:
        first_nav = snapshots_history[0].get("nav", total_cost)
        inception_return = round((total_value / first_nav - 1) * 100, 2) if first_nav > 0 else 0
    else:
        inception_return = round(total_pnl_pct, 2)

    return {
        "as_of":              datetime.now().strftime("%Y-%m-%d"),
        "total_value":        round(total_value, 2),
        "total_cost":         round(total_cost, 2),
        "total_pnl":          round(total_pnl, 2),
        "total_pnl_pct":      round(total_pnl_pct, 2),
        "daily_return_pct":   daily_return,
        "inception_return_pct": inception_return,
        "hit_rate_pct":       round(hit_rate, 1),
        "num_positions":      len(positions),
        "sector_weights":     sector_weights,
        "note": "Beta/alpha calculations require 60+ days of NAV history. "
                "Brinson attribution requires benchmark sector weights.",
    }


def append_snapshot(positions, total_value, snapshots_history):
    """Add today's NAV snapshot to history."""
    today = datetime.now().strftime("%Y-%m-%d")
    # Don't duplicate today
    existing_dates = {s["date"] for s in snapshots_history}
    if today in existing_dates:
        return snapshots_history

    snapshots_history.append({
        "date":       today,
        "nav":        round(total_value, 2),
        "positions":  len(positions),
    })
    # Keep last 3 years
    return snapshots_history[-756:]


def main():
    print(f"{'='*50}")
    print(f"AR Platform — Paper Trading Engine")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    # Load inputs
    trades_data = load_json("trades.json", [])
    if isinstance(trades_data, list):
        trades = trades_data
    else:
        trades = trades_data.get("trades", [])

    if not trades:
        print("No trades found in trades.json. Creating empty output files.")
        save_json("positions.json",  {"as_of": datetime.now().isoformat(), "positions": [], "summary": {}})
        save_json("analytics.json",  {"as_of": datetime.now().isoformat()})
        save_json("snapshots.json",  {"snapshots": []})
        return

    market_data  = load_json("market_data.json", {})
    snap_history = load_json("snapshots.json", {}).get("snapshots", [])

    print(f"  Trades loaded: {len(trades)}")

    # Compute
    holdings = build_positions(trades, market_data)
    print(f"  Open positions: {len(holdings)}")

    positions, total_value, total_cost = compute_positions_output(holdings, market_data)

    # Add today's snapshot
    snap_history = append_snapshot(positions, total_value, snap_history)

    # Analytics
    analytics = compute_analytics(positions, snap_history)

    fx = get_fx_rates(market_data)
    # Save outputs
    save_json("positions.json", {
        "as_of":          datetime.now().isoformat(),
        "base_currency":  BASE_CURRENCY,
        "fx_rates":       fx,
        "positions":      positions,
        "summary": {
            "total_value_cny": round(total_value, 2),
            "total_cost_cny":  round(total_cost, 2),
            "total_pnl_cny":   round(total_value - total_cost, 2),
            "total_pnl_pct":   round((total_value / total_cost - 1) * 100, 2) if total_cost > 0 else 0,
            # legacy aliases for backwards-compat with older dashboard reads
            "total_value":     round(total_value, 2),
            "total_cost":      round(total_cost, 2),
            "total_pnl":       round(total_value - total_cost, 2),
        },
    })
    save_json("analytics.json", analytics)
    save_json("snapshots.json", {"snapshots": snap_history})

    print(f"\n  Portfolio value: {total_value:,.2f}")
    print(f"  Total P&L:       {total_value - total_cost:+,.2f} ({(total_value/total_cost-1)*100:+.2f}%)" if total_cost > 0 else "")
    print(f"  Hit rate:        {analytics.get('hit_rate_pct', 0):.1f}%")
    print(f"\nDONE: positions.json | analytics.json | snapshots.json")


if __name__ == "__main__":
    main()
