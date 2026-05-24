#!/usr/bin/env python3
"""
Build a survivorship-safe A-share universe from Tushare stock_basic.

The output includes currently listed, delisted, and paused/suspended names so a
future backtest can construct the historical universe without survivor bias.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_history"
FIELDS = "ts_code,symbol,name,area,industry,market,list_date,delist_date,list_status"
LIST_STATUSES = ["L", "D", "P"]


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        pass
    return value


def _frame_to_rows(df):
    if df is None or len(df) == 0:
        return []
    rows = []
    for row in df.to_dict(orient="records"):
        converted = {str(k): _json_safe(v) for k, v in row.items()}
        for field in FIELDS.split(","):
            converted.setdefault(field, None)
        rows.append({field: converted.get(field) for field in FIELDS.split(",")})
    return rows


def _fetch_status(pro, list_status, sleep_seconds):
    try:
        df = pro.stock_basic(exchange="", list_status=list_status, fields=FIELDS)
        rows = _frame_to_rows(df)
        for row in rows:
            if not row.get("list_status"):
                row["list_status"] = list_status
        return rows
    finally:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def build_universe(pro, sleep_seconds):
    by_code = {}
    counts = {}
    errors = []
    api_calls = 0

    for list_status in LIST_STATUSES:
        api_calls += 1
        try:
            rows = _fetch_status(pro, list_status, sleep_seconds)
            counts[list_status] = len(rows)
            for row in rows:
                ts_code = row.get("ts_code")
                if ts_code:
                    by_code[ts_code] = row
        except Exception as exc:
            counts[list_status] = 0
            errors.append(
                {
                    "api": "stock_basic",
                    "list_status": list_status,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    stocks = [by_code[ts_code] for ts_code in sorted(by_code)]
    return {
        "fetched_at": _iso_now(),
        "source": "tushare",
        "counts": counts,
        "stocks": stocks,
        "_api_call_count": api_calls,
        "_errors": errors,
        "_status": "ok" if stocks and not errors else ("partial" if stocks else "failed"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build PIT survivorship-safe Tushare universe.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--sleep", type=float, default=0.4, help="Seconds between API calls.")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required", file=sys.stderr)
        return 1

    started = time.monotonic()
    pro = ts.pro_api(token)
    payload = build_universe(pro, args.sleep)
    out_path = Path(args.output_dir) / "universe_pit.json"
    _write_json(out_path, payload)
    print(
        f"status={payload['_status']} L={payload['counts'].get('L', 0)} "
        f"D={payload['counts'].get('D', 0)} P={payload['counts'].get('P', 0)} "
        f"stocks={len(payload['stocks'])} api_calls={payload['_api_call_count']} "
        f"wall_clock={time.monotonic() - started:.1f}s output={out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
