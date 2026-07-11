#!/usr/bin/env python3
"""
Fetch deep per-ticker Tushare history for PIT backtest validation.

This script is intentionally separate from scripts/fetch_tushare.py, which
serves the daily production pipeline with short lookbacks. The output here is
large, regenerable, and written under data_history/ for later bulk-store design.
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


DEFAULT_TICKERS = ["600519.SH", "000001.SZ", "002594.SZ", "300104.SZ"]
DEFAULT_START = "20050101"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data_history"
PAGE_DAYS = 365
DAILY_FIELDS = ["trade_date", "open", "high", "low", "close", "vol", "amount"]
ADJ_FIELDS = ["trade_date", "adj_factor"]
DAILY_BASIC_FIELDS = [
    "trade_date",
    "pe",
    "pb",
    "turnover_rate",
    "total_mv",
    "circ_mv",
]


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_ts():
    return date.today().strftime("%Y%m%d")


def _parse_ts_date(value):
    return datetime.strptime(value, "%Y%m%d").date()


def _format_ts_date(value):
    return value.strftime("%Y%m%d")


def _iso_date(value):
    if not value:
        return None
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


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


def _frame_to_rows(df, fields=None):
    if df is None or len(df) == 0:
        return []
    rows = []
    for row in df.to_dict(orient="records"):
        converted = {str(k): _json_safe(v) for k, v in row.items()}
        if fields:
            converted = {field: converted.get(field) for field in fields}
        rows.append(converted)
    return rows


def _dedupe_sort(rows, key):
    deduped = {}
    for row in rows:
        value = row.get(key)
        if value:
            deduped[str(value)] = row
    return [deduped[k] for k in sorted(deduped)]


def _iter_windows(start_date, end_date):
    cursor = start_date
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=PAGE_DAYS - 1), end_date)
        yield _format_ts_date(cursor), _format_ts_date(window_end)
        cursor = window_end + timedelta(days=1)


def _sleep(seconds):
    if seconds > 0:
        time.sleep(seconds)


def _fetch_paged(pro, api_name, ts_code, start_date, end_date, fields, sleep_seconds):
    rows = []
    errors = []
    calls = 0
    start = _parse_ts_date(start_date)
    end = _parse_ts_date(end_date)

    for window_start, window_end in _iter_windows(start, end):
        calls += 1
        try:
            api = getattr(pro, api_name)
            df = api(ts_code=ts_code, start_date=window_start, end_date=window_end)
            batch = _frame_to_rows(df, fields=fields)
            rows.extend(batch)
            if len(batch) >= 5900:
                errors.append(
                    {
                        "api": api_name,
                        "window": f"{window_start}-{window_end}",
                        "warning": f"{len(batch)} rows near Tushare page cap",
                    }
                )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append(
                {
                    "api": api_name,
                    "window": f"{window_start}-{window_end}",
                    "error": message,
                }
            )
            if _is_fatal_connectivity_error(message):
                break
        finally:
            _sleep(sleep_seconds)

    return _dedupe_sort(rows, "trade_date"), calls, errors


def _normalize_financial_rows(rows):
    normalized = []
    for row in rows:
        row.setdefault("ann_date", None)
        row.setdefault("f_ann_date", None)
        normalized.append(row)
    return normalized


def _fetch_financial(pro, api_name, ts_code, start_date, end_date, sleep_seconds):
    calls = 1
    try:
        api = getattr(pro, api_name)
        df = api(ts_code=ts_code, start_date=start_date, end_date=end_date)
        rows = _normalize_financial_rows(_frame_to_rows(df))
        return rows, calls, []
    except Exception as exc:
        return [], calls, [{"api": api_name, "error": f"{type(exc).__name__}: {exc}"}]
    finally:
        _sleep(sleep_seconds)


def _is_fatal_connectivity_error(message):
    markers = (
        "Failed to resolve",
        "NameResolutionError",
        "nodename nor servname provided",
        "Invalid API key",
        "token",
    )
    return any(marker in message for marker in markers)


def _ann_dates(*tables):
    dates = []
    for rows in tables:
        for row in rows:
            ann_date = row.get("ann_date")
            if ann_date:
                dates.append(str(ann_date))
    return sorted(set(dates))


def _depth_summary(daily_rows, income_rows, balancesheet_rows, cashflow_rows):
    daily_dates = sorted(str(row["trade_date"]) for row in daily_rows if row.get("trade_date"))
    ann_dates = _ann_dates(income_rows, balancesheet_rows, cashflow_rows)
    return {
        "daily_rows": len(daily_rows),
        "daily_first_date": _iso_date(daily_dates[0]) if daily_dates else None,
        "daily_last_date": _iso_date(daily_dates[-1]) if daily_dates else None,
        "fin_first_ann_date": _iso_date(ann_dates[0]) if ann_dates else None,
        "fin_last_ann_date": _iso_date(ann_dates[-1]) if ann_dates else None,
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def fetch_ticker(pro, ticker, years_requested, start_date, end_date, sleep_seconds):
    api_call_count = 0
    errors = []

    daily, calls, api_errors = _fetch_paged(
        pro, "daily", ticker, start_date, end_date, DAILY_FIELDS, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    adj_factor, calls, api_errors = _fetch_paged(
        pro, "adj_factor", ticker, start_date, end_date, ADJ_FIELDS, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    daily_basic, calls, api_errors = _fetch_paged(
        pro, "daily_basic", ticker, start_date, end_date, DAILY_BASIC_FIELDS, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    income, calls, api_errors = _fetch_financial(
        pro, "income", ticker, start_date, end_date, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    balancesheet, calls, api_errors = _fetch_financial(
        pro, "balancesheet", ticker, start_date, end_date, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    cashflow, calls, api_errors = _fetch_financial(
        pro, "cashflow", ticker, start_date, end_date, sleep_seconds
    )
    api_call_count += calls
    errors.extend(api_errors)

    payload = {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "source": "tushare",
        "years_requested": years_requested,
        "start_date": start_date,
        "end_date": end_date,
        "daily": daily,
        "adj_factor": adj_factor,
        "daily_basic": daily_basic,
        "income": income,
        "balancesheet": balancesheet,
        "cashflow": cashflow,
        "_depth": _depth_summary(daily, income, balancesheet, cashflow),
        "_api_call_count": api_call_count,
        "_errors": errors,
        "_status": "ok" if daily and not errors else ("partial" if daily else "failed"),
    }
    return payload


def _parse_tickers(value):
    if not value:
        return DEFAULT_TICKERS
    tickers = [ticker.strip() for ticker in value.split(",") if ticker.strip()]
    if not tickers:
        raise ValueError("--tickers must include at least one ts_code")
    return tickers


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch deep Tushare OHLCV, daily_basic, adj_factor, and PIT financials."
    )
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_TICKERS),
        help="Comma-separated ts_code list, e.g. 600519.SH,000001.SZ",
    )
    parser.add_argument("--years", type=int, default=20, help="Requested lookback label.")
    parser.add_argument(
        "--start",
        default=DEFAULT_START,
        help="Start date in YYYYMMDD format. Default: 20050101.",
    )
    parser.add_argument("--end", default=_today_ts(), help="End date in YYYYMMDD format.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--sleep", type=float, default=0.4, help="Seconds between API calls.")
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    pro = ts.pro_api(token)
    tickers = _parse_tickers(args.tickers)
    run_started = time.monotonic()
    total_calls = 0
    outputs = []

    for ticker in tickers:
        ticker_started = time.monotonic()
        payload = fetch_ticker(pro, ticker, args.years, args.start, args.end, args.sleep)
        total_calls += payload["_api_call_count"]
        out_path = output_dir / f"{ticker}.json"
        _write_json(out_path, payload)
        outputs.append(str(out_path))
        elapsed = time.monotonic() - ticker_started
        depth = payload["_depth"]
        print(
            f"{ticker}: status={payload['_status']} daily_rows={depth['daily_rows']} "
            f"fin_first_ann_date={depth['fin_first_ann_date']} calls={payload['_api_call_count']} "
            f"elapsed={elapsed:.1f}s"
        )

    print(
        f"completed tickers={len(tickers)} api_calls={total_calls} "
        f"wall_clock={time.monotonic() - run_started:.1f}s outputs={','.join(outputs)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
