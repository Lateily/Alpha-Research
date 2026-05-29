#!/usr/bin/env python3
"""fetch_hk_prices.py — minimal HK price + benchmark backfill via yfinance.

Per Junyan 2026-05-29: unblock CORE validation for the HK names. Primary source
is **yfinance** (already the repo's active HK/US price source; no new API, no
Tushare permission). History/benchmark prices ONLY — does not touch disclosure
(fetch_hkex.py is a disclosure source and is intentionally NOT used here).

Discovers every .HK ticker referenced by the CORE ledger inputs (thesis eval +
paper positions), maps to Yahoo format (zfill(4)+'.HK'), fetches daily OHLCV,
and writes a panel parquet the ledger can read with the SAME schema as the
A-share panel (ts_code / trade_date=YYYYMMDD / close ...).

Benchmarks: HSI=^HSI; HSTECH=^HSTECH with ETF-proxy fallback (3033.HK). If a
benchmark can't be fetched it is recorded as benchmark_status=proxy_or_missing —
never silently skipped.

Output:
  data_history/panel/hk_prices.parquet   — stocks + benchmarks (ts_code repo form)
  data_history/panel/hk_prices_meta.json  — fetch status, row counts, proxy flags

Usage:
    python3 scripts/fetch_hk_prices.py
    python3 scripts/fetch_hk_prices.py --start 2023-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
THESIS_EVAL = REPO / "public" / "data" / "iter9_thesis_eval.json"
POSITIONS = REPO / "public" / "data" / "positions.json"
OUT_PARQUET = REPO / "data_history" / "panel" / "hk_prices.parquet"
OUT_META = REPO / "data_history" / "panel" / "hk_prices_meta.json"

# Benchmarks: (repo_key, [yahoo symbols to try in order], is_proxy_after_index)
HK_BENCHES = {
    "HSI": ["^HSI"],
    "HSTECH": ["^HSTECH", "3033.HK"],   # index first; iShares Hang Seng TECH ETF as proxy
}
PROXY_SYMS = {"3033.HK"}


def to_yahoo(repo_tic: str) -> str:
    """700.HK → 0700.HK (Yahoo zero-pads HK codes to 4 digits)."""
    if repo_tic.endswith(".HK"):
        return repo_tic[:-3].zfill(4) + ".HK"
    return repo_tic


def discover_hk_tickers() -> set[str]:
    tics: set[str] = set()
    if THESIS_EVAL.exists():
        for r in json.loads(THESIS_EVAL.read_text()).get("records", []):
            t = r.get("ts_code", "")
            if isinstance(t, str) and t.endswith(".HK"):
                tics.add(t)
    if POSITIONS.exists():
        for p in json.loads(POSITIONS.read_text()).get("positions", []):
            t = p.get("ticker", "")
            if isinstance(t, str) and t.endswith(".HK"):
                tics.add(t)
    return tics


def fetch_one(yahoo_sym: str, start: str):
    import yfinance as yf
    df = yf.Ticker(yahoo_sym).history(start=start, auto_adjust=True)
    if df is None or df.empty:
        return None
    df = df.reset_index()
    # Normalize the date column name (yfinance returns 'Date' or 'Datetime').
    date_col = "Date" if "Date" in df.columns else ("Datetime" if "Datetime" in df.columns else df.columns[0])
    out = pd.DataFrame({
        "trade_date": pd.to_datetime(df[date_col]).dt.strftime("%Y%m%d"),
        "open": df["Open"].astype(float),
        "high": df["High"].astype(float),
        "low": df["Low"].astype(float),
        "close": df["Close"].astype(float),
        "volume": df.get("Volume", pd.Series([None] * len(df))),
    })
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2023-01-01")
    args = p.parse_args(argv)

    tics = discover_hk_tickers()
    print(f"[hk-fetch] discovered .HK tickers: {sorted(tics)}")
    if not tics:
        print("[hk-fetch] WARNING: no .HK tickers discovered", file=sys.stderr)

    frames = []
    meta = {"source": "yfinance", "auto_adjust": True, "start": args.start,
            "stocks": {}, "benchmarks": {}, "note": "prices split/dividend-adjusted (yfinance auto_adjust)"}

    # ── stocks ──
    for repo_tic in sorted(tics):
        ysym = to_yahoo(repo_tic)
        df = fetch_one(ysym, args.start)
        if df is None:
            meta["stocks"][repo_tic] = {"yahoo": ysym, "rows": 0, "status": "EMPTY"}
            print(f"  {repo_tic:<10} ({ysym}) → EMPTY")
            continue
        df["ts_code"] = repo_tic
        frames.append(df)
        meta["stocks"][repo_tic] = {"yahoo": ysym, "rows": len(df),
                                    "first": df["trade_date"].iloc[0], "last": df["trade_date"].iloc[-1],
                                    "last_close": round(float(df["close"].iloc[-1]), 3), "status": "OK"}
        print(f"  {repo_tic:<10} ({ysym}) → {len(df)} rows, last={df['close'].iloc[-1]:.2f} ({df['trade_date'].iloc[-1]})")

    # ── benchmarks ──
    for bkey, syms in HK_BENCHES.items():
        got = None
        used = None
        for sym in syms:
            df = fetch_one(sym, args.start)
            if df is not None and not df.empty:
                got, used = df, sym
                break
        if got is None:
            meta["benchmarks"][bkey] = {"status": "proxy_or_missing", "tried": syms, "rows": 0}
            print(f"  bench {bkey:<8} → MISSING (tried {syms}) — benchmark_status=proxy_or_missing")
            continue
        is_proxy = used in PROXY_SYMS or not used.startswith("^")
        got["ts_code"] = bkey
        frames.append(got)
        status = "proxy_or_missing" if is_proxy else "index_ok"
        meta["benchmarks"][bkey] = {"status": status, "used_symbol": used, "is_proxy": is_proxy,
                                    "rows": len(got), "first": got["trade_date"].iloc[0],
                                    "last": got["trade_date"].iloc[-1],
                                    "last_close": round(float(got["close"].iloc[-1]), 3)}
        tag = f" (PROXY {used}, benchmark_status=proxy_or_missing)" if is_proxy else f" ({used})"
        print(f"  bench {bkey:<8} → {len(got)} rows{tag}, last={got['close'].iloc[-1]:.2f}")

    if not frames:
        print("[hk-fetch] ERROR: nothing fetched; not writing parquet", file=sys.stderr)
        OUT_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        return 1

    panel = pd.concat(frames, ignore_index=True)[
        ["ts_code", "trade_date", "open", "high", "low", "close", "volume"]
    ].sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUT_PARQUET, index=False)
    OUT_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # ── acceptance check ──
    need_stocks = {"700.HK", "9999.HK", "6160.HK", "175.HK"}
    have = {t for t in panel["ts_code"].unique()}
    print("\n[hk-fetch] acceptance:")
    for t in sorted(need_stocks):
        ok = t in have and (panel[panel.ts_code == t]["close"].notna().any())
        print(f"  {t:<10} daily close: {'OK' if ok else 'MISSING'}")
    print(f"  HSI daily close: {'OK' if ('HSI' in have) else 'MISSING'}")
    hstech = meta['benchmarks'].get('HSTECH', {})
    print(f"  HSTECH: {hstech.get('status')} (used={hstech.get('used_symbol')})")
    print(f"\n[hk-fetch] wrote {OUT_PARQUET}  ({len(panel)} rows, {panel['ts_code'].nunique()} series)")
    print(f"[hk-fetch] wrote {OUT_META}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
