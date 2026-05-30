#!/usr/bin/env python3
"""theme_peer_residual.py — CORE Alpha Factory v0 #3: theme/peer residual attribution.

Separates thesis skill from broad-market AND theme/sector beta. A broad-index
(CSI300/HSI) residual conflates the two. Per the v0 run: of Innolight's +92% CSI300
residual, only ~20pp is CPO/optical theme beta — +71.7% remains ABOVE its optical
peers (so it is NOT "mostly theme beta"). This computes the residual vs the THEME
PEER BASKET (per CORE_ALPHA_FACTORY_v0_SPEC §6) and reports the broad-index residual
alongside so the decomposition is explicit.

READ-ONLY: reads price panels + positions.json; writes ONLY its output JSON. Never
writes positions/analytics/snapshots.json. No trades, no positions.

Method (per ticker, over its holding window):
  - peers = its basket members EXCLUDING itself (no self-inclusion bias).
  - usable peers = those with price coverage over the window.
  - if usable peers < 4 -> benchmark_status="proxy_or_missing", residual is computed
    vs the BROAD INDEX (CSI300 for A, HSI for HK) and the status is stated. No silent
    fallback to a broad index without the flag.
  - else -> equal-weight daily basket return; beta = cov(stock, basket)/var(basket);
    theme_residual = total_return - beta * basket_total_return.
  - the broad-index residual (CSI300/HSI) is ALWAYS reported for comparison.

The peer baskets are `[unvalidated peer definition]` and are ATTRIBUTION-ONLY,
never selection rules.

Output: public/data/theme_peer_residual.json
Usage:  python3 scripts/theme_peer_residual.py
        python3 scripts/theme_peer_residual.py --selftest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
A_PANEL = REPO / "data_history" / "panel" / "daily_prices.parquet"
HK_PANEL = REPO / "data_history" / "panel" / "hk_prices.parquet"
INDEX = REPO / "data_history" / "panel" / "index_prices.parquet"
POSITIONS = REPO / "public" / "data" / "positions.json"
OUT = REPO / "public" / "data" / "theme_peer_residual.json"

MIN_PEERS = 4  # spec §6: < 4 usable peers -> proxy_or_missing

# Canonical theme baskets — CORE_ALPHA_FACTORY_v0_SPEC §6.1. [unvalidated peer definition].
# Attribution-only; never a selection rule. Single source of truth (fetch_hk_prices
# imports HK members from here).
BASKETS = {
    "cpo_optical_v0": {"theme": "CPO_OPTICAL",
        "tickers": ["300308.SZ", "300394.SZ", "300502.SZ", "002281.SZ", "000988.SZ",
                    "300548.SZ", "300570.SZ", "301205.SZ", "688205.SH", "688498.SH"]},
    "hk_internet_gaming_v0": {"theme": "HK_INTERNET_GAMING",
        "tickers": ["700.HK", "9999.HK", "9988.HK", "3690.HK", "1024.HK",
                    "9618.HK", "9626.HK", "0777.HK", "2400.HK"]},
    "auto_ev_v0": {"theme": "AUTO_EV",
        "tickers": ["002594.SZ", "175.HK", "1211.HK", "2015.HK", "9866.HK",
                    "9868.HK", "000625.SZ", "601633.SH", "600104.SH", "601127.SH"]},
    "pharmacy_retail_v0": {"theme": "PHARMACY_RETAIL",
        "tickers": ["603233.SH", "603939.SH", "603883.SH", "002727.SZ", "605266.SH", "000705.SZ"]},
    "hk_biotech_v0": {"theme": "HK_BIOTECH",
        "tickers": ["6160.HK", "1177.HK", "2269.HK", "2359.HK", "1877.HK", "9969.HK", "2696.HK"]},
}

# Which basket each live/thesis ticker is attributed against.
TICKER_BASKET = {
    "300308.SZ": "cpo_optical_v0",
    "700.HK": "hk_internet_gaming_v0", "9999.HK": "hk_internet_gaming_v0",
    "002594.SZ": "auto_ev_v0", "175.HK": "auto_ev_v0",
    "603233.SH": "pharmacy_retail_v0",
    "6160.HK": "hk_biotech_v0",
}

A_BENCH = "000300.SH"   # CSI300
HK_BENCH = "HSI"


def is_hk(t: str) -> bool:
    return isinstance(t, str) and t.endswith(".HK")


def all_hk_basket_tickers() -> list[str]:
    return sorted({t for b in BASKETS.values() for t in b["tickers"] if is_hk(t)})


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str), format="%Y%m%d", errors="coerce")


def load_series(parquet: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    if not parquet.exists():
        return {}
    df = pd.read_parquet(parquet, columns=["ts_code", "trade_date", "close"])
    df = df[df["ts_code"].isin(tickers)].copy()
    df["date"] = _to_dt(df["trade_date"])
    out = {}
    for tic, g in df.groupby("ts_code"):
        g = g.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        out[tic] = g[["date", "close"]]
    return out


def _window(df: pd.DataFrame, entry: str) -> pd.DataFrame:
    return df[df["date"] >= pd.Timestamp(entry)].reset_index(drop=True)


def _daily_ret(df: pd.DataFrame) -> pd.Series:
    return df.set_index("date")["close"].pct_change().dropna()


def beta_residual(stock_ret: pd.Series, factor_ret: pd.Series,
                  stock_total: float, factor_total: float) -> dict | None:
    m = pd.concat([stock_ret.rename("s"), factor_ret.rename("f")], axis=1).dropna()
    if len(m) < 8 or float(np.var(m["f"])) == 0:
        return None
    beta = float(np.cov(m["s"], m["f"])[0, 1] / np.var(m["f"]))
    return {"beta": round(beta, 3), "factor_total_return": round(factor_total, 4),
            "beta_contribution": round(beta * factor_total, 4),
            "residual": round(stock_total - beta * factor_total, 4), "n_days": int(len(m))}


def attribute(ticker: str, entry: str, px: dict, bpx: dict) -> dict:
    basket_id = TICKER_BASKET.get(ticker)
    rec = {"ticker": ticker, "basket_id": basket_id,
           "theme_bucket": BASKETS.get(basket_id, {}).get("theme"),
           "entry_date_used": entry}
    if ticker not in px:
        rec["status"] = "no_price_for_ticker"
        return rec
    sdf = _window(px[ticker], entry)
    if len(sdf) < 10:
        rec["status"] = "insufficient_ticker_window"
        return rec
    s_ret = _daily_ret(sdf)
    s_total = float(sdf["close"].iloc[-1] / sdf["close"].iloc[0] - 1.0)
    rec["total_return"] = round(s_total, 4)

    # broad-index residual (always reported for comparison)
    bcode = HK_BENCH if is_hk(ticker) else A_BENCH
    rec["broad_index"] = bcode
    if bcode in bpx:
        bdf = _window(bpx[bcode], entry)
        br = beta_residual(s_ret, _daily_ret(bdf), s_total,
                           float(bdf["close"].iloc[-1] / bdf["close"].iloc[0] - 1.0)) if len(bdf) >= 10 else None
        rec["broad_index_residual"] = (br["residual"] if br else None)
        rec["broad_index_beta"] = (br["beta"] if br else None)

    # No theme basket mapped for this ticker — e.g. the book adds/holds a name
    # before a basket exists. Degrade EXPLICITLY (never crash); broad-index
    # residual above is still reported.
    if basket_id is None or basket_id not in BASKETS:
        rec["status"] = "no_theme_basket"
        rec["benchmark_status"] = "proxy_or_missing"
        rec["theme_residual"] = None
        rec["note"] = "no theme basket mapping; broad_index_residual only"
        return rec

    # theme/peer basket residual
    peers = [t for t in BASKETS[basket_id]["tickers"] if t != ticker]
    usable = []
    peer_rets, peer_totals = [], []
    for p in peers:
        if p in px:
            pdf = _window(px[p], entry)
            if len(pdf) >= 10:
                usable.append(p)
                peer_rets.append(_daily_ret(pdf))
                peer_totals.append(float(pdf["close"].iloc[-1] / pdf["close"].iloc[0] - 1.0))
    rec["n_peers_total"] = len(peers)
    rec["n_peers_usable"] = len(usable)
    rec["peers_used"] = usable

    if len(usable) < MIN_PEERS:
        rec["benchmark_status"] = "proxy_or_missing"
        rec["theme_residual"] = None
        rec["note"] = (f"only {len(usable)}/{len(peers)} peers have prices (< {MIN_PEERS}); "
                       f"theme residual not computed — use broad_index_residual ({bcode}) with this flag")
        return rec

    rec["benchmark_status"] = "ok"
    basket_daily = pd.concat(peer_rets, axis=1).mean(axis=1).dropna()  # equal-weight daily basket return
    basket_total = float(np.prod([1 + r for r in basket_daily]) - 1.0)
    tr = beta_residual(s_ret, basket_daily, s_total, basket_total)
    if tr is None:
        rec["benchmark_status"] = "proxy_or_missing"
        rec["theme_residual"] = None
        rec["note"] = "insufficient overlap for theme beta regression"
        return rec
    rec["beta_vs_basket"] = tr["beta"]
    rec["basket_total_return"] = round(basket_total, 4)
    rec["theme_beta_contribution"] = tr["beta_contribution"]
    rec["theme_residual"] = tr["residual"]
    rec["n_days"] = tr["n_days"]
    return rec


def _load_positions() -> list[dict]:
    if not POSITIONS.exists():
        return []
    pos = json.loads(POSITIONS.read_text())
    out = []
    as_of = (pos.get("as_of") or "")[:10]
    for p in pos.get("positions", []):
        tic = p.get("ticker"); hd = p.get("holding_days")
        a = (p.get("as_of") or as_of)[:10]
        entry = None
        if hd is not None and a:
            entry = str((pd.Timestamp(a) - pd.Timedelta(days=int(hd))).date())
        out.append({"ticker": tic, "name": p.get("name"), "entry_date": entry,
                    "pnl_pct": p.get("pnl_pct")})
    return out


def main() -> int:
    positions = _load_positions()
    need_a = {p["ticker"] for p in positions if not is_hk(p["ticker"])}
    need_hk = {p["ticker"] for p in positions if is_hk(p["ticker"])}
    # also load every basket member so peers resolve
    for b in BASKETS.values():
        for t in b["tickers"]:
            (need_hk if is_hk(t) else need_a).add(t)

    px = load_series(A_PANEL, need_a)
    hk = load_series(HK_PANEL, need_hk)
    px.update(hk)
    bpx = load_series(INDEX, {A_BENCH})
    bpx.update({k: v for k, v in load_series(HK_PANEL, {HK_BENCH}).items()})

    hk_present = sorted(t for t in need_hk if t in px)
    hk_missing = sorted(t for t in need_hk if t not in px)
    print(f"[theme-resid] A tickers loaded: {len(need_a & set(px))}/{len(need_a)}  "
          f"HK loaded: {len(hk_present)}/{len(need_hk)}")
    if hk_missing:
        print(f"[theme-resid] HK not in panel (run fetch_hk_prices.py to add): {hk_missing}")

    rows = [attribute(p["ticker"], p["entry_date"], px, bpx) for p in positions if p["entry_date"]]
    # attach name/pnl
    by_t = {p["ticker"]: p for p in positions}
    for r in rows:
        r["name"] = by_t.get(r["ticker"], {}).get("name")
        r["pnl_pct"] = by_t.get(r["ticker"], {}).get("pnl_pct")

    out = {
        "_meta": {"read_only": True, "no_trades": True,
                  "method": "theme/peer-basket beta residual vs equal-weight basket (target excluded); "
                            "broad-index residual reported alongside; <4 usable peers -> proxy_or_missing",
                  "baskets_are": "[unvalidated peer definition] — attribution-only, never selection",
                  "min_peers": MIN_PEERS, "spec": "CORE_ALPHA_FACTORY_v0_SPEC §6"},
        "baskets": {k: v["tickers"] for k, v in BASKETS.items()},
        "positions": rows,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    print("\n=== Theme/peer residual vs broad-index residual (holding window) ===")
    hdr = f"{'name':<10}{'ticker':<11}{'theme':<20}{'total':>9}{'broad_resid':>13}{'theme_resid':>13}{'n_peers':>9}{'status':>16}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        if r.get("status"):
            print(f"{str(r.get('name') or '?'):<10}{r['ticker']:<11}{str(r.get('theme_bucket') or '?'):<20}{'':>9}{'':>13}{'':>13}{'':>9}{r['status']:>16}")
            continue
        tr = r.get("theme_residual"); brr = r.get("broad_index_residual")
        print(f"{str(r.get('name') or '?'):<10}{r['ticker']:<11}{str(r.get('theme_bucket')):<20}"
              f"{(r.get('total_return') or 0)*100:>+8.1f}%"
              f"{(brr*100 if brr is not None else 0):>+12.1f}%"
              f"{(tr*100 if tr is not None else 0):>+12.1f}%"
              f"{r.get('n_peers_usable',0):>9}{r.get('benchmark_status',''):>16}")
    print(f"\n[theme-resid] wrote {OUT}")
    return 0


def _selftest() -> int:
    """Synthetic: a stock that IS the basket beta should have ~0 theme residual."""
    errs = []
    dates = pd.date_range("2025-01-01", periods=60, freq="B")
    rng = [(-1) ** i * 0.01 + 0.002 for i in range(59)]  # deterministic basket daily returns
    base = pd.Series([100.0], dtype=float)
    closes = [100.0]
    for r in rng:
        closes.append(closes[-1] * (1 + r))
    basket_df = pd.DataFrame({"date": dates, "close": closes})
    # stock = 1.5x basket beta + small idio
    s_closes = [100.0]
    for i, r in enumerate(rng):
        s_closes.append(s_closes[-1] * (1 + 1.5 * r + (0.0005 if i % 7 == 0 else 0)))
    stock_df = pd.DataFrame({"date": dates, "close": s_closes})
    s_total = s_closes[-1] / s_closes[0] - 1
    b_total = closes[-1] / closes[0] - 1
    res = beta_residual(_daily_ret(stock_df), _daily_ret(basket_df), s_total, b_total)
    if res is None:
        errs.append("beta_residual returned None on valid input")
    else:
        if abs(res["beta"] - 1.5) > 0.1:
            errs.append(f"beta {res['beta']} != ~1.5")
        if abs(res["residual"]) > 0.05:
            errs.append(f"residual {res['residual']} should be ~0 (stock is pure basket beta)")
    # <4 peers path: TICKER_BASKET sanity
    for t, b in TICKER_BASKET.items():
        if b not in BASKETS:
            errs.append(f"{t} -> unknown basket {b}")
        if t not in BASKETS[b]["tickers"]:
            errs.append(f"{t} not a member of its own basket {b}")
    # robustness: an UNMAPPED ticker with valid prices must degrade, not crash.
    udf = pd.DataFrame({"date": dates, "close": s_closes})
    try:
        ur = attribute("ZZZZ.XX", "2025-01-01", {"ZZZZ.XX": udf}, {})
        if ur.get("status") != "no_theme_basket":
            errs.append(f"unmapped ticker -> status {ur.get('status')!r}, expected 'no_theme_basket'")
        if ur.get("theme_residual") is not None:
            errs.append("unmapped ticker should have theme_residual=None")
    except Exception as e:
        errs.append(f"unmapped ticker raised {type(e).__name__}: {e}")
    if errs:
        print("theme_peer_residual selftest FAILED:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"theme_peer_residual selftest PASSED (beta={res['beta']} residual={res['residual']}; basket membership OK)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(main())
