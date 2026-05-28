#!/usr/bin/env python3
"""
Fetch daily close + OHLCV for a fixed list of benchmark indices from Tushare,
per-index pagination (`pro.index_daily(ts_code='000300.SH', start_date=...,
end_date=...)`), persisted to a SEPARATE parquet from the stock panel.

Why separate parquet?  daily_prices.parquet is the stock-only 15M-row panel.
Mixing indices in would (a) pollute the stock universe in downstream filters,
(b) require special-case ts_code logic everywhere. So indices live in
data_history/panel/index_prices.parquet with the same column schema as the
stock prices parquet (minus pre_close/change — index_daily does not return them
as canonical columns; we fill with NaN if missing to keep schema stable).

Index list (multi-benchmark for v3 §2.1 hard gate):
  - 000300.SH  CSI300
  - 399300.SZ  CSI300 (Shenzhen mirror)
  - 000905.SH  ZZ500
  - 399905.SZ  ZZ500 (Shenzhen mirror)
  - 000852.SH  ZZ1000
  - 399852.SZ  ZZ1000 (Shenzhen mirror)
  - 000016.SH  SSE 50
  - HSI.HK     Hang Seng (best-effort; Tushare HK coverage may be limited)

Per Junyan 2026-05-05 memory: 3-API tier (`stk_factor_pro`/`top_list`/
`moneyflow_cnt`) is DEFERRED — NOT used here. `index_daily` is free tier.

Usage:
  python3 scripts/fetch_index_panel.py --start 2006-01-01 --end 2026-05-27
  python3 scripts/fetch_index_panel.py --selftest    # fetch 30d of CSI300 only

Outputs:
  data_history/panel/index_prices.parquet
    columns: ts_code, trade_date, open, high, low, close, vol, amount,
             pre_close, change, pct_chg
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
DEFAULT_OUT = PANEL_DIR / "index_prices.parquet"

# Match stock-panel schema for downstream compatibility.
INDEX_COLUMNS = [
    "ts_code", "trade_date", "open", "high", "low", "close",
    "vol", "amount", "pre_close", "change", "pct_chg",
]
INDEX_FIELDS = ",".join(INDEX_COLUMNS)

# Fixed benchmark universe — small + closed list, per Junyan v3b spec.
INDEX_LIST = [
    "000300.SH",   # CSI300
    "399300.SZ",   # CSI300 SZ mirror
    "000905.SH",   # ZZ500
    "399905.SZ",   # ZZ500 SZ mirror
    "000852.SH",   # ZZ1000
    "399852.SZ",   # ZZ1000 SZ mirror
    "000016.SH",   # SSE50
    "HSI.HK",      # Hang Seng (best-effort, may be empty on free tier)
]

SLEEP_SECONDS = 0.4   # per-index full-history call is expensive; under 200/min limit
MAX_RETRIES = 2


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


def _fetch_one_index(pro, ts_code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """Single index_daily call, with one retry. Returns DataFrame or None on hard fail.

    Returns empty DataFrame (with schema) when Tushare returns 0 rows — that
    means the index is unsupported on this token tier (e.g. HSI.HK can be empty
    on free tier). We treat that as success-with-zero-rows, NOT failure.
    """
    s = start.replace("-", "")
    e = end.replace("-", "")
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=s, end_date=e,
                                  fields=INDEX_FIELDS)
            if df is None:
                return pd.DataFrame(columns=INDEX_COLUMNS)
            # Normalize: ensure all expected columns exist, fill NaN for missing.
            for col in INDEX_COLUMNS:
                if col not in df.columns:
                    df[col] = pd.NA
            df["trade_date"] = df["trade_date"].astype(str)
            df["ts_code"] = df["ts_code"].astype(str)
            return df[INDEX_COLUMNS].copy()
        except Exception as exc:
            last_exc = exc
            print(f"  WARN attempt {attempt+1}/{MAX_RETRIES+1} {ts_code}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            time.sleep(2.0 * (attempt + 1))
    print(f"  FAIL {ts_code} after {MAX_RETRIES+1} attempts: {last_exc}",
          file=sys.stderr)
    return None


def fetch_indices(pro, index_list: list[str], start: str, end: str,
                   out_path: Path, dry_run: bool = False) -> dict:
    """Fetch each index full-history once. Returns summary dict."""
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    empty: list[str] = []
    t0 = time.time()

    for i, ts_code in enumerate(index_list, 1):
        print(f"[{i}/{len(index_list)}] fetching {ts_code} {start}..{end} ...",
              flush=True)
        df = _fetch_one_index(pro, ts_code, start, end)
        time.sleep(SLEEP_SECONDS)
        if df is None:
            failed.append(ts_code)
            continue
        if df.empty:
            empty.append(ts_code)
            print(f"  {ts_code}: 0 rows (likely unsupported on this token tier)")
            continue
        print(f"  {ts_code}: {len(df)} rows, "
              f"dates {df['trade_date'].min()}..{df['trade_date'].max()}")
        frames.append(df)

    all_df = (pd.concat(frames, ignore_index=True)
              if frames else pd.DataFrame(columns=INDEX_COLUMNS))
    if not all_df.empty:
        all_df = (all_df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
                  .sort_values(["ts_code", "trade_date"])
                  .reset_index(drop=True))

    summary = {
        "indices_requested": len(index_list),
        "indices_with_data": len(frames),
        "indices_empty": empty,
        "indices_failed": failed,
        "total_rows": len(all_df),
        "elapsed_sec": round(time.time() - t0, 1),
        "wrote_file": False,
    }

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        all_df[INDEX_COLUMNS].to_parquet(out_path, index=False)
        summary["wrote_file"] = True
        summary["out_path"] = str(out_path)
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Fetch index daily panel from Tushare.")
    p.add_argument("--start", default="2006-01-01", help="Start date YYYY-MM-DD")
    p.add_argument("--end", default="2026-05-27", help="End date YYYY-MM-DD")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="Output parquet path")
    p.add_argument("--indices", default=None,
                   help="Comma-separated ts_code list (default: full benchmark list)")
    p.add_argument("--selftest", action="store_true",
                   help="Fetch 30-day window of CSI300 only and validate schema")
    args = p.parse_args(argv)

    token = load_token()
    pro = ts.pro_api(token)

    if args.selftest:
        scratch = PANEL_DIR / "_selftest_index_prices.parquet"
        print("--selftest: fetching 30d of 000300.SH (CSI300) only")
        summary = fetch_indices(pro, ["000300.SH"],
                                 "2026-04-25", "2026-05-25",
                                 scratch, dry_run=False)
        print(f"\n=== --selftest summary ===\n{summary}")
        if summary["indices_failed"]:
            print("FAIL: 000300.SH errored")
            return 1
        if summary["total_rows"] == 0:
            print("FAIL: 000300.SH returned 0 rows (token issue?)")
            return 1
        df = pd.read_parquet(scratch)
        print(f"head:\n{df.head(3).to_string(index=False)}")
        assert list(df.columns) == INDEX_COLUMNS, \
            f"column order mismatch: {list(df.columns)}"
        assert (df["ts_code"] == "000300.SH").all(), \
            "ts_code mismatch in selftest fetch"
        print("SCHEMA OK. Cleaning up scratch.")
        scratch.unlink(missing_ok=True)
        return 0

    index_list = (args.indices.split(",") if args.indices else INDEX_LIST)
    print(f"Fetching {len(index_list)} indices: {index_list}")
    summary = fetch_indices(pro, index_list, args.start, args.end,
                             Path(args.out), dry_run=False)
    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    # Hard fail only if EVERY index failed (empty is OK — token-tier issue).
    if summary["indices_failed"] and summary["indices_with_data"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
