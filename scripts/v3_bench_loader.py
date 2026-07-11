#!/usr/bin/env python3
"""v3_bench_loader.py — Load benchmark index curves from the panel parquet.

Per v3 §2.1 (Junyan ratify #13, 2026-05-28 PM2):
  Required benchmarks for BENCH gate: csi300, zz500, csi1000, ew500, cash2pct.
  SSE50 optional; HSI absent.

Source: `data_history/panel/index_prices.parquet` (fetched 2026-05-28).
Indices present:
  - 000300.SH / 399300.SZ  -> CSI300
  - 000905.SH / 399905.SZ  -> CSI500 (= ZZ500)
  - 000852.SH / 399852.SZ  -> CSI1000 (= ZZ1000)
  - 000016.SH              -> SSE50 (optional)

Usage:
  python3 scripts/v3_bench_loader.py --selftest
  python3 scripts/v3_bench_loader.py --index csi300 --start 2022-01-04 --end 2026-05-25

Public API (importable):
  load_index_series(ts_code, start, end, parquet_path=None) -> pandas.Series
  load_named_benchmark(name, start, end, capital, ...) -> list[dict{date,equity}]
  RECOMMENDED_INDEX_MAP -> {benchmark_name: preferred_ts_code}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET = REPO_ROOT / "data_history" / "panel" / "index_prices.parquet"

# Benchmark name -> (primary ts_code, fallback ts_code).
# Per Junyan ratify #13: csi300, zz500, csi1000 mandatory; SSE50 optional.
# Shanghai-listed (000xxx.SH) preferred over Shenzhen-listed (399xxx.SZ) — same
# underlying index, both kept for cross-check.
RECOMMENDED_INDEX_MAP = {
    "csi300":   ("000300.SH", "399300.SZ"),
    "zz500":    ("000905.SH", "399905.SZ"),
    "csi1000":  ("000852.SH", "399852.SZ"),
    "sse50":    ("000016.SH", None),
}


def _to_yyyymmdd(d) -> str:
    s = str(d).replace("-", "")[:8]
    return s


def load_index_series(ts_code: str,
                      start: Optional[str] = None,
                      end: Optional[str] = None,
                      parquet_path: Optional[Path] = None) -> pd.Series:
    """Load a single index series (close, indexed by trade_date string).

    Returns pandas Series with str trade_date index (YYYYMMDD form) and float
    close values. Window filtering is inclusive on both endpoints; start/end
    can be "YYYY-MM-DD" or "YYYYMMDD".
    """
    pq = Path(parquet_path) if parquet_path else DEFAULT_PARQUET
    if not pq.exists():
        raise FileNotFoundError(f"index parquet not found: {pq}")
    df = pd.read_parquet(pq)
    sub = df[df["ts_code"] == ts_code].copy()
    if sub.empty:
        raise KeyError(f"ts_code {ts_code!r} not found in {pq}")
    sub["trade_date"] = sub["trade_date"].astype(str)
    sub = sub.sort_values("trade_date")
    if start:
        s = _to_yyyymmdd(start)
        sub = sub[sub["trade_date"] >= s]
    if end:
        e = _to_yyyymmdd(end)
        sub = sub[sub["trade_date"] <= e]
    return pd.Series(sub["close"].astype(float).values,
                     index=sub["trade_date"].values,
                     name=ts_code)


def load_named_benchmark(name: str,
                         start: Optional[str],
                         end: Optional[str],
                         capital: float = 10_000_000.0,
                         parquet_path: Optional[Path] = None) -> list[dict]:
    """Load a benchmark by friendly name and return an equity curve scaled to capital.

    name in RECOMMENDED_INDEX_MAP keys: csi300 / zz500 / csi1000 / sse50.

    Returns list of {date, equity, close, ret} dicts. The equity series starts
    at `capital` and compounds daily by (close_t / close_{t-1}).
    """
    if name not in RECOMMENDED_INDEX_MAP:
        raise KeyError(
            f"unknown benchmark name {name!r}; "
            f"valid: {sorted(RECOMMENDED_INDEX_MAP.keys())}"
        )
    primary, fallback = RECOMMENDED_INDEX_MAP[name]
    try:
        series = load_index_series(primary, start=start, end=end,
                                   parquet_path=parquet_path)
    except KeyError:
        if fallback:
            series = load_index_series(fallback, start=start, end=end,
                                       parquet_path=parquet_path)
        else:
            raise
    if series.empty:
        return []
    out = []
    prev_close = float(series.iloc[0])
    eq = float(capital)
    for date, close in series.items():
        close = float(close)
        ret = (close / prev_close - 1.0) if prev_close > 0 else 0.0
        eq *= (1.0 + ret)
        out.append({
            "date": str(date),
            "equity": round(eq, 2),
            "close": round(close, 4),
            "ret": round(ret, 8),
        })
        prev_close = close
    return out


def available_benchmarks(parquet_path: Optional[Path] = None) -> dict:
    """Return a dict mapping friendly benchmark name -> {present, ts_codes_found}."""
    pq = Path(parquet_path) if parquet_path else DEFAULT_PARQUET
    if not pq.exists():
        return {name: {"present": False, "reason": f"parquet missing: {pq}"}
                for name in RECOMMENDED_INDEX_MAP}
    df = pd.read_parquet(pq)
    codes_in_panel = set(df["ts_code"].astype(str).unique())
    out = {}
    for name, (primary, fallback) in RECOMMENDED_INDEX_MAP.items():
        found = []
        if primary in codes_in_panel:
            found.append(primary)
        if fallback and fallback in codes_in_panel:
            found.append(fallback)
        out[name] = {
            "present": bool(found),
            "ts_codes_found": found,
            "primary": primary,
            "fallback": fallback,
        }
    return out


# --------- CLI ---------

def _selftest() -> int:
    errors = []
    if not DEFAULT_PARQUET.exists():
        print(f"v3_bench_loader SELFTEST SKIPPED: panel parquet not present "
              f"({DEFAULT_PARQUET}); cannot verify load path on this machine.")
        return 0

    # 1. available_benchmarks lists all required names.
    avail = available_benchmarks()
    for required_name in ("csi300", "zz500", "csi1000"):
        if not avail.get(required_name, {}).get("present"):
            errors.append(
                f"required index {required_name} not present in panel: "
                f"{avail.get(required_name)}"
            )

    # 2. load_index_series for csi300 within OOS window returns non-empty series.
    try:
        s = load_index_series("000300.SH", start="2022-01-04", end="2022-12-31")
        if len(s) < 200:
            errors.append(f"csi300 2022 series too short: {len(s)} dates")
    except Exception as e:
        errors.append(f"load_index_series('000300.SH') failed: {e}")

    # 3. load_named_benchmark returns equity curve scaled to capital.
    try:
        curve = load_named_benchmark("csi300", start="2022-01-04",
                                     end="2022-12-31", capital=10_000_000.0)
        if not curve:
            errors.append("csi300 OOS curve empty")
        elif abs(curve[0]["equity"] - 10_000_000.0) > 1_000_000.0:
            # first-day equity should be near capital (first ret = 0).
            # Within ¥1M tolerance for first-day compounding edge case.
            errors.append(
                f"csi300 first-day equity {curve[0]['equity']} not near capital "
                f"¥10M (first ret should be 0)"
            )
    except Exception as e:
        errors.append(f"load_named_benchmark('csi300') failed: {e}")

    # 4. fallback path: 399300.SZ should also load.
    try:
        s_sz = load_index_series("399300.SZ", start="2022-01-04", end="2022-12-31")
        if len(s_sz) < 200:
            errors.append(f"csi300-SZ fallback series too short: {len(s_sz)}")
    except Exception as e:
        errors.append(f"load_index_series('399300.SZ') fallback failed: {e}")

    # 5. unknown name raises KeyError.
    try:
        load_named_benchmark("nonexistent", "20220104", "20221231")
    except KeyError:
        pass
    else:
        errors.append("load_named_benchmark('nonexistent') should KeyError")

    if errors:
        print("v3_bench_loader SELFTEST FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("v3_bench_loader SELFTEST PASSED")
    print(f"  required benchmarks present: csi300={avail['csi300']['present']}, "
          f"zz500={avail['zz500']['present']}, csi1000={avail['csi1000']['present']}, "
          f"sse50={avail['sse50']['present']} (optional)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Load benchmark index curves from the panel parquet.",
    )
    parser.add_argument("--selftest", action="store_true",
                        help="Run built-in self-tests and exit.")
    parser.add_argument("--index", type=str,
                        help="Benchmark friendly name "
                             "(csi300|zz500|csi1000|sse50) or raw ts_code.")
    parser.add_argument("--start", type=str, help="Window start (YYYY-MM-DD).")
    parser.add_argument("--end", type=str, help="Window end (YYYY-MM-DD).")
    parser.add_argument("--capital", type=float, default=10_000_000.0,
                        help="Capital base for equity curve. Default ¥10M.")
    parser.add_argument("--parquet", type=str, default=str(DEFAULT_PARQUET),
                        help="Override index parquet path.")
    parser.add_argument("--list", action="store_true",
                        help="List available benchmarks and exit.")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.list:
        print(json.dumps(available_benchmarks(Path(args.parquet)), indent=2))
        return 0

    if not args.index:
        parser.error("--index required (or use --selftest or --list)")

    if args.index in RECOMMENDED_INDEX_MAP:
        curve = load_named_benchmark(
            args.index, args.start, args.end,
            capital=args.capital, parquet_path=Path(args.parquet),
        )
        print(json.dumps({
            "benchmark": args.index, "start": args.start, "end": args.end,
            "n_points": len(curve), "first": curve[0] if curve else None,
            "last": curve[-1] if curve else None,
        }, indent=2))
    else:
        s = load_index_series(args.index, args.start, args.end,
                              parquet_path=Path(args.parquet))
        print(json.dumps({
            "ts_code": args.index, "n_dates": int(len(s)),
            "first_date": str(s.index[0]) if len(s) else None,
            "last_date": str(s.index[-1]) if len(s) else None,
            "first_close": float(s.iloc[0]) if len(s) else None,
            "last_close": float(s.iloc[-1]) if len(s) else None,
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
