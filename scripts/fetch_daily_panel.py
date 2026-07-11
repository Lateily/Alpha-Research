#!/usr/bin/env python3
"""
Fetch daily OHLCV + adj_factor for the FULL A-share universe from Tushare,
by-date pagination (`pro.daily(trade_date=YYYYMMDD)`), persisted to parquet.

Per docs/strategy/SWING_STRATEGY_v1.md §11.2 — by-date pagination is the
ONLY mode allowed: 1 API call per trade date returns all stocks. ~750
calls cover 3 years. By-ticker pagination is forbidden (would be ~5000
calls per date × 750 dates = blows the credit budget).

PIT discipline: each row carries the actual trade_date it represents.
No forward-fill, no fill-NaN with future data.

Outputs:
  data_history/panel/daily_prices.parquet
    columns: ts_code, trade_date, open, high, low, close, vol, amount,
             pre_close, change, pct_chg
  data_history/panel/daily_adj_factor.parquet
    columns: ts_code, trade_date, adj_factor

Usage:
  python3 scripts/fetch_daily_panel.py --start 2023-01-01 --end 2026-05-26
  python3 scripts/fetch_daily_panel.py --selftest       # fetch ONE date, no overwrite
  python3 scripts/fetch_daily_panel.py --start 2023-01-01 --end 2026-05-26 --resume
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import tushare as ts

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_DIR = REPO_ROOT / "data_history" / "panel"
DEFAULT_PRICES = PANEL_DIR / "daily_prices.parquet"
DEFAULT_ADJ = PANEL_DIR / "daily_adj_factor.parquet"

PRICE_COLUMNS = [
    "ts_code", "trade_date", "open", "high", "low", "close",
    "vol", "amount", "pre_close", "change", "pct_chg",
]
ADJ_COLUMNS = ["ts_code", "trade_date", "adj_factor"]

PRICE_FIELDS = ",".join(PRICE_COLUMNS)
ADJ_FIELDS = ",".join(ADJ_COLUMNS)

SLEEP_SECONDS = 0.18   # ~333/min — well under 500/min free-tier rate limit
PROGRESS_EVERY = 30


def load_token() -> str:
    """Read from secrets/tushare_token.txt then fall back to TUSHARE_TOKEN env."""
    secret_path = REPO_ROOT / "secrets" / "tushare_token.txt"
    if secret_path.exists():
        token = secret_path.read_text().strip()
        if token:
            return token
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN env var OR secrets/tushare_token.txt required",
              file=sys.stderr)
        sys.exit(2)
    return token


def fetch_trade_dates(pro, start: str, end: str) -> list[str]:
    """Return YYYYMMDD trade-open dates from Tushare trade_cal. [] on failure."""
    try:
        df = pro.trade_cal(exchange="SSE", is_open=1,
                           start_date=start.replace("-", ""),
                           end_date=end.replace("-", ""))
    except Exception as exc:
        print(f"  FAIL trade_cal({start}..{end}): {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return []
    # API returns cal_date (not trade_date) — see BUGFIX in fetch_universe_history.py
    if df is None or df.empty:
        return []
    out = set()
    for _, row in df.iterrows():
        if int(row.get("is_open", 0)) != 1:
            continue
        d = row.get("cal_date") or row.get("trade_date")
        if d:
            out.add(str(d))
    return sorted(out)


def _existing_dates(parquet_path: Path) -> set[str]:
    if not parquet_path.exists():
        return set()
    try:
        df = pd.read_parquet(parquet_path, columns=["trade_date"])
        return set(df["trade_date"].astype(str).unique())
    except Exception as exc:
        print(f"  warn: could not read existing parquet {parquet_path}: {exc}",
              file=sys.stderr)
        return set()


def _fetch_one_date(pro, trade_date: str, api_name: str, fields: str,
                    expected_cols: list[str]) -> Optional[pd.DataFrame]:
    """Single API call with try/catch. Returns DataFrame or None on failure."""
    try:
        fn = getattr(pro, api_name)
        df = fn(trade_date=trade_date, fields=fields)
        if df is None or df.empty:
            return pd.DataFrame(columns=expected_cols)
        for col in expected_cols:
            if col not in df.columns:
                df[col] = pd.NA
        df["trade_date"] = df["trade_date"].astype(str)
        return df[expected_cols].copy()
    except Exception as exc:
        print(f"  FAIL {api_name}({trade_date}): {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def fetch_panel(pro, trade_dates: list[str], prices_path: Path, adj_path: Path,
                resume: bool, dry_run: bool) -> dict:
    """Main loop. Returns summary stats."""
    existing_price_dates = _existing_dates(prices_path) if resume else set()
    existing_adj_dates = _existing_dates(adj_path) if resume else set()

    to_fetch = [d for d in trade_dates
                if d not in existing_price_dates or d not in existing_adj_dates]
    skipped = len(trade_dates) - len(to_fetch)
    if skipped:
        print(f"resume: skipping {skipped} dates already present, "
              f"fetching {len(to_fetch)} remaining")

    price_frames: list[pd.DataFrame] = []
    adj_frames: list[pd.DataFrame] = []
    failed_dates: list[str] = []

    t0 = time.time()
    for i, td in enumerate(to_fetch, 1):
        price_df = _fetch_one_date(pro, td, "daily", PRICE_FIELDS, PRICE_COLUMNS)
        time.sleep(SLEEP_SECONDS)
        adj_df = _fetch_one_date(pro, td, "adj_factor", ADJ_FIELDS, ADJ_COLUMNS)
        time.sleep(SLEEP_SECONDS)

        if price_df is None or adj_df is None:
            failed_dates.append(td)
            continue
        if not price_df.empty:
            price_frames.append(price_df)
        if not adj_df.empty:
            adj_frames.append(adj_df)

        if i % PROGRESS_EVERY == 0 or i == len(to_fetch):
            elapsed = time.time() - t0
            print(f"fetched {i} of {len(to_fetch)} dates, {elapsed:.1f} seconds elapsed")

    new_price = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame(columns=PRICE_COLUMNS)
    new_adj = pd.concat(adj_frames, ignore_index=True) if adj_frames else pd.DataFrame(columns=ADJ_COLUMNS)

    if dry_run:
        return {
            "fetched_dates": len(to_fetch) - len(failed_dates),
            "failed_dates": failed_dates,
            "price_rows_new": len(new_price),
            "adj_rows_new": len(new_adj),
            "skipped_resume": skipped,
            "wrote_files": False,
        }

    # Merge with existing (resume mode) and write
    prices_path.parent.mkdir(parents=True, exist_ok=True)
    for path, new_df, cols in [(prices_path, new_price, PRICE_COLUMNS),
                                (adj_path, new_adj, ADJ_COLUMNS)]:
        if new_df.empty and not resume:
            # nothing new and not appending — still write empty schema for downstream
            new_df.to_parquet(path, index=False)
            continue
        if resume and path.exists():
            old = pd.read_parquet(path)
            merged = pd.concat([old, new_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
            merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
            merged[cols].to_parquet(path, index=False)
        else:
            new_df[cols].sort_values(["trade_date", "ts_code"]).reset_index(drop=True).to_parquet(path, index=False)

    return {
        "fetched_dates": len(to_fetch) - len(failed_dates),
        "failed_dates": failed_dates,
        "price_rows_new": len(new_price),
        "adj_rows_new": len(new_adj),
        "skipped_resume": skipped,
        "wrote_files": True,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Fetch daily OHLCV panel from Tushare.")
    p.add_argument("--start", default="2023-01-01", help="Start date YYYY-MM-DD")
    p.add_argument("--end", default="2026-05-26", help="End date YYYY-MM-DD")
    p.add_argument("--out", default=str(DEFAULT_PRICES), help="Output prices parquet path")
    p.add_argument("--adj-out", default=str(DEFAULT_ADJ), help="Output adj_factor parquet path")
    p.add_argument("--resume", action="store_true",
                   help="Only fetch dates not already present in output parquet")
    p.add_argument("--selftest", action="store_true",
                   help="Fetch ONE date (2026-05-23) and validate schema, do NOT overwrite prod files")
    args = p.parse_args(argv)

    token = load_token()
    pro = ts.pro_api(token)

    if args.selftest:
        # Single-date probe — use a known-recent open trade date.
        # Default fallback if calendar lookup fails: hardcoded recent trading day.
        test_date = "20260522"
        cal_dates = fetch_trade_dates(pro, "2026-05-15", "2026-05-25")
        if cal_dates:
            test_date = cal_dates[-1]
        print(f"--selftest: fetching {test_date} (1 date, 2 API calls)")
        scratch_prices = PANEL_DIR / "_selftest_prices.parquet"
        scratch_adj = PANEL_DIR / "_selftest_adj.parquet"
        summary = fetch_panel(pro, [test_date], scratch_prices, scratch_adj,
                              resume=False, dry_run=False)
        # Validate schema if files exist
        if summary["failed_dates"]:
            print(f"\n=== --selftest FAILED ===")
            print(f"trade_date probed: {test_date}")
            print(f"failed dates: {summary['failed_dates']}")
            print("Schema validation skipped (no data fetched). Most common cause: invalid TUSHARE_TOKEN.")
            return 1
        prices = pd.read_parquet(scratch_prices)
        adj = pd.read_parquet(scratch_adj)
        print("\n=== --selftest results ===")
        print(f"trade_date probed: {test_date}")
        print(f"daily rows: {len(prices)}  columns: {list(prices.columns)}")
        print(f"adj_factor rows: {len(adj)}  columns: {list(adj.columns)}")
        print(f"daily head:\n{prices.head(3).to_string(index=False)}")
        print(f"adj head:\n{adj.head(3).to_string(index=False)}")
        assert list(prices.columns) == PRICE_COLUMNS, f"price columns mismatch: {list(prices.columns)}"
        assert list(adj.columns) == ADJ_COLUMNS, f"adj columns mismatch: {list(adj.columns)}"
        assert (prices["trade_date"].astype(str) == test_date).all(), "PIT violation: row trade_date != probed date"
        print(f"SCHEMA OK. Cleaning up scratch files.")
        scratch_prices.unlink(missing_ok=True)
        scratch_adj.unlink(missing_ok=True)
        return 0

    # Full run
    print(f"Fetching trade calendar {args.start} .. {args.end} ...")
    trade_dates = fetch_trade_dates(pro, args.start, args.end)
    print(f"Found {len(trade_dates)} trade-open dates")
    if not trade_dates:
        print("ERROR: no trade dates returned from calendar", file=sys.stderr)
        return 1

    prices_path = Path(args.out)
    adj_path = Path(args.adj_out)
    summary = fetch_panel(pro, trade_dates, prices_path, adj_path,
                          resume=args.resume, dry_run=False)

    print("\n=== summary ===")
    print(f"dates fetched OK : {summary['fetched_dates']}")
    print(f"dates failed     : {len(summary['failed_dates'])}")
    print(f"resume skipped   : {summary['skipped_resume']}")
    print(f"new price rows   : {summary['price_rows_new']}")
    print(f"new adj rows     : {summary['adj_rows_new']}")
    if summary["failed_dates"]:
        print(f"failed list (first 20): {summary['failed_dates'][:20]}")
    print(f"prices : {prices_path}")
    print(f"adj    : {adj_path}")
    return 0 if not summary["failed_dates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
