#!/usr/bin/env python3
"""
Fetch Tushare share_float restricted-share unlock events per watchlist ticker.

Restricted-share unlocks are a China-specific short-term price-pressure risk
signal: a large block of formerly locked shares becoming tradable can increase
near-term supply, especially when several unlocks cluster in the next quarter.
This fetcher writes raw event evidence plus task-scoped HIGH/MED/LOW bands
only. The bands are unvalidated heuristics until Bridge 6 calibrates portfolio
risk weighting against actual outcomes.

Output:
  public/data/restricted_shares/<raw_ticker>.json, e.g. 300308.SZ.json.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


WINDOW_DAYS = 180
FETCH_DELAY = 0.16
API_USED = "share_float"

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "restricted_shares"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"

ANN_DATE_FIELDS = ("ann_date", "ann_dt", "announce_date", "publish_date", "date")
FLOAT_DATE_FIELDS = ("float_date", "unlock_date", "list_date", "trade_date")
FLOAT_SHARE_FIELDS = ("float_share", "float_shares", "float_amount", "unlock_share", "share")
FLOAT_RATIO_FIELDS = ("float_ratio", "float_prop", "float_rate", "unlock_ratio", "ratio")
HOLDER_NAME_FIELDS = ("holder_name", "holder", "shareholder_name", "holder_type")
SHARE_TYPE_FIELDS = ("share_type", "float_type", "shares_type", "restricted_type")


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


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


def _normalize_text(value):
    value = _json_safe(value)
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _date_text(value):
    value = _json_safe(value)
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 8:
        return digits[:8]
    return None


def _parse_date(value):
    text = _date_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _dash_date(value):
    text = _date_text(value)
    if not text:
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _call_share_float(api, ts_code, start_date, end_date):
    errors = []
    param_variants = (
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        {"ts_code": ts_code},
    )
    for params in param_variants:
        try:
            if hasattr(api, API_USED):
                result = getattr(api, API_USED)(**params)
            else:
                result = api.query(API_USED, **params)
            if result is None:
                raise RuntimeError("Tushare returned no data object")
            if isinstance(result, dict):
                code = result.get("code")
                if code not in (None, 0, "0"):
                    raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
            return result
        except Exception as exc:
            errors.append(f"{params}: {type(exc).__name__}: {exc}")
        finally:
            time.sleep(FETCH_DELAY)
    raise RuntimeError(" | ".join(errors))


def _normalize_unlock_row(raw):
    safe = {str(key): _json_safe(value) for key, value in raw.items()}
    row = dict(safe)
    row["ann_date"] = _date_text(_first_value(safe, ANN_DATE_FIELDS))
    row["float_date"] = _date_text(_first_value(safe, FLOAT_DATE_FIELDS))
    row["float_share"] = _to_int(_first_value(safe, FLOAT_SHARE_FIELDS))
    row["float_ratio"] = _to_float(_first_value(safe, FLOAT_RATIO_FIELDS))
    row["holder_name"] = _normalize_text(_first_value(safe, HOLDER_NAME_FIELDS))
    row["share_type"] = _normalize_text(_first_value(safe, SHARE_TYPE_FIELDS))
    return row


def _records_from_frame(frame, start_dt, end_dt):
    records = []
    for raw in _frame_to_rows(frame):
        if not isinstance(raw, dict):
            continue
        float_dt = _parse_date(_first_value(raw, FLOAT_DATE_FIELDS))
        if float_dt is None or float_dt < start_dt or float_dt > end_dt:
            continue
        records.append(_normalize_unlock_row(raw))
    records.sort(key=lambda row: (row.get("float_date") or "", row.get("ann_date") or ""))
    return records


def _risk_level(total_float_ratio):
    if total_float_ratio is None:
        return None
    if total_float_ratio > 10:
        return "HIGH"
    if total_float_ratio >= 3:
        return "MED"
    return "LOW"


def _empty_summary():
    return {
        "upcoming_count": 0,
        "total_float_ratio_180d": 0.0,
        "next_unlock_date": None,
        "next_unlock_ratio": None,
        "risk_level": None,
    }


def _summary(events):
    if not events:
        return _empty_summary()

    ratios = [row.get("float_ratio") for row in events if isinstance(row.get("float_ratio"), (int, float))]
    total_ratio = float(sum(ratios)) if ratios else 0.0
    next_event = events[0]
    next_ratio = next_event.get("float_ratio")
    if isinstance(next_ratio, (int, float)):
        next_ratio = float(next_ratio)
    else:
        next_ratio = None

    return {
        "upcoming_count": len(events),
        "total_float_ratio_180d": total_ratio,
        "next_unlock_date": _dash_date(next_event.get("float_date")),
        "next_unlock_ratio": next_ratio,
        "risk_level": _risk_level(total_ratio if ratios else None),
    }


def _base_payload(ticker, status, events=None):
    events = events or []
    return {
        "_status": status,
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "api_used": API_USED,
        "window_days": WINDOW_DAYS,
        "events": events,
        "summary": _summary(events),
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


def fetch_one_ticker(api, ticker, start_dt, end_dt):
    frame = _call_share_float(api, ticker, _ts_date(start_dt), _ts_date(end_dt))
    events = _records_from_frame(frame, start_dt, end_dt)
    return _base_payload(ticker, "ok" if events else "empty", events=events)


def _selected_tickers(watchlist, ticker_arg):
    if ticker_arg:
        cfg = watchlist.get(ticker_arg)
        if cfg is None:
            return {ticker_arg: {"yahoo": ticker_arg, "exchange": None}}
        return {ticker_arg: cfg}
    return watchlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch Tushare share_float restricted-share unlock events.")
    parser.add_argument("--ticker", help="Optional single ticker, e.g. 300308.SZ")
    args = parser.parse_args(argv)

    try:
        token = os.environ["TUSHARE_TOKEN"].strip()
    except KeyError:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_restricted_shares.py", file=sys.stderr)
        return 1
    if not token:
        print("ERROR: TUSHARE_TOKEN is empty for scripts/fetch_restricted_shares.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    watchlist = _load_watchlist()
    selected = _selected_tickers(watchlist, args.ticker)
    ts.set_token(token)
    api = ts.pro_api()
    start_dt = _beijing_now().date()
    end_dt = start_dt + timedelta(days=WINDOW_DAYS)
    counts = {status: 0 for status in ("ok", "empty", "skipped_hk", "skipped_us", "api_error")}

    for idx, ticker in enumerate(selected, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            skip_status = _skip_status(ticker)
            if skip_status:
                payload = _base_payload(ticker, skip_status)
            else:
                payload = fetch_one_ticker(api, ticker, start_dt, end_dt)
            _write_json(output_path, payload)
            counts[payload["_status"]] = counts.get(payload["_status"], 0) + 1
            print(
                f"[{idx}/{len(selected)}] wrote public/data/restricted_shares/{output_path.name} "
                f"status={payload['_status']} events={len(payload['events'])}",
                file=sys.stderr,
            )
        except Exception as exc:
            payload = _api_error_payload(ticker, exc)
            try:
                _write_json(output_path, payload)
            except Exception as write_exc:
                print(
                    f"restricted_shares[{ticker}]: write failed: {type(write_exc).__name__}: {write_exc}",
                    file=sys.stderr,
                )
            counts["api_error"] = counts.get("api_error", 0) + 1

    print(
        "restricted_shares: " + " ".join(f"{status}={counts.get(status, 0)}" for status in sorted(counts)),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
