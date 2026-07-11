#!/usr/bin/env python3
"""
Fetch Tushare 5000-tier 股权质押 (pledge_stat) records per watchlist ticker.

High pledge ratios are a China-specific risk signal: pledged controlling
shareholder stakes can become forced-selling and control-risk pressure when
the stock price falls sharply. This fetcher writes the raw reference-data
layer only. Risk interpretation is limited to the task-scoped HIGH/MED/LOW
ratio bands; any future portfolio risk weight remains unvalidated until Bridge
6 calibrates it against portfolio outcomes.

Output:
  public/data/pledge_stat/<raw_ticker>.json, e.g. 300308.SZ.json.

Schema states are intentionally strict:
  ok / empty / skipped_hk / skipped_us / api_error
Per-ticker isolation is deliberate: one failing ticker never stops the run.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import tushare as ts


WINDOW_QUARTERS = 4
FETCH_DELAY = 0.16
API_USED = "pledge_stat"

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "pledge_stat"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

DATE_FIELDS = ("end_date", "ann_date", "trade_date", "date")
PLEDGE_RATIO_FIELDS = ("pledge_ratio", "pledge_prop", "pledge_rate", "ratio")
PLEDGE_COUNT_FIELDS = ("pledge_count", "pledge_cnt", "holder_num", "holder_count", "count")
FLOAT_FIELDS = (
    "pledge_ratio",
    "pledge_prop",
    "pledge_rate",
    "unrest_pledge",
    "rest_pledge",
    "total_share",
    "pledge_share",
    "pledged_shares",
    "pledge_amount",
    "hold_amount",
    "total_mv",
)
INT_FIELDS = ("pledge_count", "pledge_cnt", "holder_num", "holder_count", "count")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_watchlist():
    """
    Load focus tickers from public/data/watchlist.json.

    watchlist.json is the single source of truth for every monitored ticker.
    """
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = dict(wl.get("tickers", {}))
    if not tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return tickers


def _is_a_share(ticker):
    ticker = (ticker or "").upper()
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _skip_status(ticker):
    ticker = (ticker or "").upper()
    if ticker.endswith(".HK"):
        return "skipped_hk"
    if not _is_a_share(ticker):
        return "skipped_us"
    return None


def _json_safe(value):
    if value is None:
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


def _frame_to_rows(frame):
    if frame is None:
        return []
    if isinstance(frame, dict):
        data = frame.get("data", frame)
        if isinstance(data, dict) and "fields" in data and "items" in data:
            fields = data.get("fields") or []
            return [dict(zip(fields, item)) for item in data.get("items") or []]
        if isinstance(data, list):
            return data
        return [data]
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return frame
    return []


def _first_value(row, fields):
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return row[field]
    return None


def _to_float(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _date_text(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 8:
        return digits[:8]
    return None


def _dash_date(value):
    text = _date_text(value)
    if not text:
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _call_pledge_stat(api, ts_code):
    try:
        result = api.pledge_stat(ts_code=ts_code)
    except AttributeError:
        result = api.query(API_USED, ts_code=ts_code)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def _normalize_pledge_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    row = dict(safe)
    row["end_date"] = _date_text(_first_value(safe, DATE_FIELDS))
    row["pledge_ratio"] = _to_float(_first_value(safe, PLEDGE_RATIO_FIELDS))
    row["pledge_count"] = _to_int(_first_value(safe, PLEDGE_COUNT_FIELDS))

    for field in FLOAT_FIELDS:
        if field in row and field not in ("pledge_ratio",):
            row[field] = _to_float(row[field])
    for field in INT_FIELDS:
        if field in row and field not in ("pledge_count",):
            row[field] = _to_int(row[field])
    return row


def _records_from_frame(frame):
    records = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        records.append(_normalize_pledge_row(raw))
    records.sort(key=lambda row: row.get("end_date") or "", reverse=True)
    return records[:WINDOW_QUARTERS]


def _risk_level(pledge_ratio):
    if pledge_ratio is None:
        return None
    if pledge_ratio > 50:
        return "HIGH"
    if pledge_ratio >= 20:
        return "MED"
    return "LOW"


def _trend_direction(records):
    ratios = [row.get("pledge_ratio") for row in records if isinstance(row.get("pledge_ratio"), (int, float))]
    if len(ratios) < 2:
        return None
    delta = ratios[0] - ratios[-1]
    if delta > 0:
        return "rising"
    if delta < 0:
        return "falling"
    return "flat"


def _empty_summary():
    return {
        "latest_pledge_ratio": None,
        "latest_end_date": None,
        "trend_direction": None,
        "risk_level": None,
        "records_count": 0,
    }


def _summary(records):
    if not records:
        return _empty_summary()
    latest = records[0]
    latest_ratio = latest.get("pledge_ratio")
    if isinstance(latest_ratio, (int, float)):
        latest_ratio = float(latest_ratio)
    else:
        latest_ratio = None
    return {
        "latest_pledge_ratio": latest_ratio,
        "latest_end_date": _dash_date(latest.get("end_date")),
        "trend_direction": _trend_direction(records),
        "risk_level": _risk_level(latest_ratio),
        "records_count": len(records),
    }


def _base_payload(ticker, status, records=None):
    records = records or []
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": API_USED,
        "window_quarters": WINDOW_QUARTERS,
        "records": records,
        "summary": _summary(records),
    }


def _api_error_payload(ticker, exc):
    payload = _base_payload(ticker, "api_error")
    payload["_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def fetch_one_ticker(api, ticker):
    try:
        frame = _call_pledge_stat(api, ticker)
        records = _records_from_frame(frame)
        return _base_payload(ticker, "ok" if records else "empty", records=records)
    finally:
        time.sleep(FETCH_DELAY)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare pledge_stat records.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    try:
        token = os.environ["TUSHARE_TOKEN"].strip()
    except KeyError:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_pledge_stat.py", file=sys.stderr)
        return 1
    if not token:
        print("ERROR: TUSHARE_TOKEN is empty for scripts/fetch_pledge_stat.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)
    ts.set_token(token)
    api = ts.pro_api()
    counts = {status: 0 for status in ("ok", "empty", "skipped_hk", "skipped_us", "api_error")}

    for ticker in selected:
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            skip_status = _skip_status(ticker)
            if skip_status:
                payload = _base_payload(ticker, skip_status)
            else:
                payload = fetch_one_ticker(api, ticker)
            _write_json(output_path, payload)
            counts[payload["_status"]] = counts.get(payload["_status"], 0) + 1
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(
                    f"pledge_stat[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}",
                    file=sys.stderr,
                )
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "pledge_stat: " + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
