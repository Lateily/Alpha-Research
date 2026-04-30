#!/usr/bin/env python3
"""
scripts/signal_quality.py — Signal Quality Feedback Loop

Reads signal attribution from trades.json, matches to P&L outcomes in positions.json,
and computes per-signal-type performance statistics. This closes the feedback loop:

  Signal fires → BUY_WATCH decision → trade entered with attribution →
  P&L accrues → signal_quality.py measures → calibration

Reads:
  public/data/trades.json      — trades with signal_attribution
  public/data/positions.json   — current positions with pnl_pct
  public/data/market_data.json — for any price lookups

Writes:
  public/data/signal_quality.json

Output schema:
  {
    "generated_at": "...",
    "date": "...",
    "portfolio_summary": { ... },
    "by_signal": [
      {
        "signal":        "GOLDEN_CROSS",
        "count":         3,          # trades where this signal contributed
        "win_count":     2,          # trades currently in profit
        "win_rate":      66.7,       # %
        "avg_pnl":       8.4,        # % average P&L on trades with this signal
        "best_pnl":      14.2,
        "worst_pnl":     -3.1,
        "avg_weight":    18.0,       # average weight in confluence score
        "tickers":       ["300308.SZ", "700.HK", "002594.SZ"]
      },
      ...
    ],
    "by_conviction": [
      { "tier": "BUY_WATCH", "count": 4, "win_rate": 75.0, "avg_pnl": 9.2 },
      { "tier": "WATCH",     "count": 1, "win_rate": 0.0,  "avg_pnl": -1.2 }
    ],
    "vp_buckets": [
      { "bucket": "VP 70+",  "count": 1, "win_rate": 100.0, "avg_pnl": 11.5 },
      { "bucket": "VP 60-70","count": 2, "win_rate": 50.0,  "avg_pnl": 5.1 },
      { "bucket": "VP 50-60","count": 2, "win_rate": 50.0,  "avg_pnl": 2.3 }
    ],
    "insights": [                    # human-readable top findings
      "GOLDEN_CROSS has best win rate (66.7%) across 3 trades",
      ...
    ]
  }
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "public" / "data"


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def get_pnl(ticker, positions):
    """Return current pnl_pct for ticker, or None if not held."""
    for p in positions:
        if p.get("ticker") == ticker:
            return p.get("pnl_pct")
    return None


def vp_bucket(vp):
    if vp is None:
        return "VP unknown"
    if vp >= 70:
        return "VP 70+"
    elif vp >= 60:
        return "VP 60-70"
    elif vp >= 50:
        return "VP 50-60"
    else:
        return "VP <50"


def main():
    print("[signal_quality] Computing signal performance analytics...")

    trades_raw   = load_json(DATA_DIR / "trades.json",    [])
    positions_d  = load_json(DATA_DIR / "positions.json", {"positions": []})

    trades     = trades_raw if isinstance(trades_raw, list) else trades_raw.get("trades", [])
    positions  = positions_d.get("positions", [])

    # Only analyse BUY trades with attribution
    buy_trades = [t for t in trades
                  if t.get("side", "").upper() == "BUY"
                  and t.get("signal_attribution")]

    print(f"  BUY trades with attribution: {len(buy_trades)}")
    print(f"  Open positions: {len(positions)}")

    if not buy_trades:
        print("  No attributed trades found. Skipping analytics.")
        output = {
            "generated_at":     datetime.now(timezone.utc).isoformat(),
            "date":             datetime.now().strftime("%Y-%m-%d"),
            "note":             "No attributed trades yet. Add trades via Trading Desk.",
            "by_signal":        [],
            "by_conviction":    [],
            "vp_buckets":       [],
            "portfolio_summary": {},
            "insights":         ["No attributed trades yet. Signal quality will populate as you trade."],
        }
        with open(DATA_DIR / "signal_quality.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        return

    # ── Build trade outcome records ───────────────────────────────────────────
    # Each trade gets enriched with its current P&L (if still open)
    trade_outcomes = []
    for t in buy_trades:
        ticker     = t["ticker"]
        pnl        = get_pnl(ticker, positions)
        attr       = t["signal_attribution"]
        signals    = attr.get("contributing_signals", [])
        conf_score = attr.get("confluence_score", 0)
        action     = attr.get("action", "UNKNOWN")
        vp         = t.get("vp_at_entry")

        # If no open position, trade was closed — we don't have final P&L
        # Mark as "CLOSED_UNKNOWN" and skip from win/loss stats
        status = "OPEN" if pnl is not None else "CLOSED_UNKNOWN"

        trade_outcomes.append({
            "ticker":     ticker,
            "date":       t["date"],
            "signals":    signals,
            "conf_score": conf_score,
            "action":     action,
            "vp":         vp,
            "pnl":        pnl,
            "status":     status,
        })
        pnl_str = f"{pnl:+.1f}%" if pnl is not None else "closed/unknown"
        print(f"  {ticker:16s} conf={conf_score:+3d}  VP={vp}  P&L={pnl_str}")

    # Only score open trades (we have live P&L)
    open_outcomes = [o for o in trade_outcomes if o["status"] == "OPEN"]

    # ── Per-signal stats ──────────────────────────────────────────────────────
    signal_stats = defaultdict(lambda: {
        "count": 0, "wins": 0, "pnls": [], "weights": [], "tickers": []
    })

    for o in open_outcomes:
        for sig in o["signals"]:
            name   = sig.get("name", "UNKNOWN")
            weight = sig.get("weight", 0)
            pnl    = o["pnl"]
            s = signal_stats[name]
            s["count"]  += 1
            s["pnls"].append(pnl)
            s["weights"].append(weight)
            if o["ticker"] not in s["tickers"]:
                s["tickers"].append(o["ticker"])
            if pnl > 0:
                s["wins"] += 1

    by_signal = []
    for name, s in sorted(signal_stats.items(), key=lambda x: -(x[1]["wins"] / max(x[1]["count"],1))):
        count    = s["count"]
        win_rate = s["wins"] / count * 100 if count > 0 else 0
        avg_pnl  = sum(s["pnls"]) / len(s["pnls"]) if s["pnls"] else 0
        by_signal.append({
            "signal":     name,
            "count":      count,
            "win_count":  s["wins"],
            "win_rate":   round(win_rate, 1),
            "avg_pnl":    round(avg_pnl, 2),
            "best_pnl":   round(max(s["pnls"]), 2) if s["pnls"] else None,
            "worst_pnl":  round(min(s["pnls"]), 2) if s["pnls"] else None,
            "avg_weight": round(sum(s["weights"]) / len(s["weights"]), 1) if s["weights"] else 0,
            "tickers":    s["tickers"],
        })

    # ── By conviction action ──────────────────────────────────────────────────
    conviction_stats = defaultdict(lambda: {"count":0,"wins":0,"pnls":[]})
    for o in open_outcomes:
        c = conviction_stats[o["action"]]
        c["count"] += 1
        c["pnls"].append(o["pnl"])
        if o["pnl"] > 0:
            c["wins"] += 1

    by_conviction = []
    for action, c in sorted(conviction_stats.items()):
        wr  = c["wins"] / c["count"] * 100 if c["count"] > 0 else 0
        avg = sum(c["pnls"]) / len(c["pnls"]) if c["pnls"] else 0
        by_conviction.append({
            "action":   action,
            "count":    c["count"],
            "win_rate": round(wr, 1),
            "avg_pnl":  round(avg, 2),
        })

    # ── By VP bucket ──────────────────────────────────────────────────────────
    vp_stats = defaultdict(lambda: {"count":0,"wins":0,"pnls":[]})
    for o in open_outcomes:
        bucket = vp_bucket(o["vp"])
        v = vp_stats[bucket]
        v["count"] += 1
        v["pnls"].append(o["pnl"])
        if o["pnl"] > 0:
            v["wins"] += 1

    vp_buckets = []
    bucket_order = ["VP 70+", "VP 60-70", "VP 50-60", "VP <50", "VP unknown"]
    for bucket in bucket_order:
        if bucket not in vp_stats:
            continue
        v = vp_stats[bucket]
        wr  = v["wins"] / v["count"] * 100 if v["count"] > 0 else 0
        avg = sum(v["pnls"]) / len(v["pnls"]) if v["pnls"] else 0
        vp_buckets.append({
            "bucket":   bucket,
            "count":    v["count"],
            "win_rate": round(wr, 1),
            "avg_pnl":  round(avg, 2),
        })

    # ── By ticker (v15.3 polish) ──────────────────────────────────────────────
    # Per-ticker P&L slice complementing by_signal/by_conviction/vp_buckets.
    # Sorted winners-first so dashboard can surface portfolio leaders.
    by_ticker = []
    for o in open_outcomes:
        sigs = o["signals"] or []
        top_signals = [s.get("name", "?") for s in sigs[:3]]
        by_ticker.append({
            "ticker":         o["ticker"],
            "pnl_pct":        round(o["pnl"], 2) if o["pnl"] is not None else None,
            "vp_at_entry":    o["vp"],
            "conf_at_entry":  o["conf_score"],
            "signal_count":   len(sigs),
            "top_signals":    top_signals,
        })
    by_ticker.sort(key=lambda x: -(x["pnl_pct"] if x["pnl_pct"] is not None else -float("inf")))

    # ── Portfolio summary ─────────────────────────────────────────────────────
    open_pnls   = [o["pnl"] for o in open_outcomes if o["pnl"] is not None]
    overall_win = sum(1 for p in open_pnls if p > 0)
    portfolio_summary = {
        "total_attributed_trades": len(buy_trades),
        "open_positions":          len(open_outcomes),
        "closed_unknown":          len([o for o in trade_outcomes if o["status"] == "CLOSED_UNKNOWN"]),
        "overall_win_rate":        round(overall_win / len(open_pnls) * 100, 1) if open_pnls else 0,
        "avg_pnl":                 round(sum(open_pnls) / len(open_pnls), 2) if open_pnls else 0,
        "best_position":           max(open_pnls) if open_pnls else None,
        "worst_position":          min(open_pnls) if open_pnls else None,
    }

    # ── Generate insights ─────────────────────────────────────────────────────
    insights = []

    if by_signal:
        best_sig  = max(by_signal, key=lambda x: x["win_rate"])
        worst_sig = min(by_signal, key=lambda x: x["win_rate"])
        if best_sig["count"] >= 2:
            insights.append(
                f"{best_sig['signal']} best win rate {best_sig['win_rate']:.0f}% "
                f"({best_sig['win_count']}/{best_sig['count']} trades, "
                f"avg P&L {best_sig['avg_pnl']:+.1f}%)"
            )
        if worst_sig["count"] >= 2 and worst_sig["win_rate"] < 50:
            insights.append(
                f"{worst_sig['signal']} underperforming: {worst_sig['win_rate']:.0f}% win rate "
                f"— consider reducing weight in signal_confluence.py"
            )

    if vp_buckets:
        best_vp = max(vp_buckets, key=lambda x: x["win_rate"])
        if best_vp["count"] >= 2:
            insights.append(
                f"{best_vp['bucket']} conviction highest quality: "
                f"{best_vp['win_rate']:.0f}% win rate, avg P&L {best_vp['avg_pnl']:+.1f}%"
            )

    if portfolio_summary["avg_pnl"] > 0:
        insights.append(
            f"Portfolio: {portfolio_summary['overall_win_rate']:.0f}% win rate · "
            f"avg P&L {portfolio_summary['avg_pnl']:+.1f}% across "
            f"{portfolio_summary['open_positions']} open positions"
        )

    if by_ticker and by_ticker[0]["pnl_pct"] is not None:
        leader = by_ticker[0]
        insights.append(
            f"{leader['ticker']} leads portfolio P&L at "
            f"{leader['pnl_pct']:+.1f}% (VP={leader['vp_at_entry']}, "
            f"conf={leader['conf_at_entry']:+d})"
        )

    if not insights:
        insights.append("Insufficient data for insights — add more trades with signal attribution.")

    # ── Output ────────────────────────────────────────────────────────────────
    output = {
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "date":              datetime.now().strftime("%Y-%m-%d"),
        "portfolio_summary": portfolio_summary,
        "by_signal":         by_signal,
        "by_conviction":     by_conviction,
        "vp_buckets":        vp_buckets,
        "by_ticker":         by_ticker,
        "insights":          insights,
    }

    out_path = DATA_DIR / "signal_quality.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[signal_quality] Done → {out_path}")
    print(f"  {len(by_signal)} signal types analysed")
    print(f"  Overall win rate: {portfolio_summary['overall_win_rate']:.0f}%")
    for ins in insights:
        print(f"  💡 {ins}")


if __name__ == "__main__":
    main()
