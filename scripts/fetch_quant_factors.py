#!/usr/bin/env python3
"""
Fetch Tushare 15000-tier 量化因子 (stk_factor_pro) per-watchlist daily factors.

Strategy: one bulk Tushare call covering the last 30-day window (no ts_code
filter), then group rows per ticker in Python. Each output JSON has:
  - factors: dict of latest day's numeric columns (PE/PB/PS/turnover/momentum/...)
  - history: list of last 30 days, each row {trade_date, ...numeric cols}

This is the data layer for the AR platform's eventual "cleaned-up our own
quant strategy" (future KR per Junyan 2026-05-03 directive). Display-only
for now; VP integration / factor calibration is separate work.

Forward-compat schema: 5-state _status (ok / skipped / endpoint_unavailable
/ tier_locked / fetch_failed). Per-ticker isolation via outer try/except.
HK/US tickers get _status='skipped' + _reason='not_available_tushare_hk_us'.
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tushare as ts


CURRENT_TIER = 15000
OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data" / "quant_factors"
WATCHLIST_PATH = Path(__file__).parent.parent / "public" / "data" / "watchlist.json"
WINDOW_DAYS = 30
FACTOR_ENDPOINTS = ["stk_factor_pro", "stk_factor", "stock_factor"]
LAST_FACTOR_ERRORS = []

TIER_LOCK_CUES = (
    "permission",
    "access",
    "权限",
    "积分",
    "points",
    "level",
    "tier",
    "not enough",
    "没有访问",
    "未开通",
    "请升级",
)

# Columns that are identifiers / dates, not factor values
ID_COLUMNS = {"ts_code", "trade_date", "code", "symbol", "name", "date"}


def _iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts_date(date_obj):
    return date_obj.strftime("%Y%m%d")


def _beijing_today_str():
    return _ts_date(datetime.now(timezone.utc) + timedelta(hours=8))


def _start_date_n_days_ago(n):
    return _ts_date(datetime.now(timezone.utc) + timedelta(hours=8) - timedelta(days=n))


def _is_a_share(ticker):
    return ticker.endswith(".SZ") or ticker.endswith(".SH")


def _load_watchlist():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        wl = json.load(f)
    tickers = dict(wl.get("tickers", {}))
    if not tickers:
        raise RuntimeError(f"No tickers found in {WATCHLIST_PATH}")
    return tickers


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


def _to_float(value):
    value = _json_safe(value)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value or value in ("--", "-", "None", "nan"):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_to_rows(frame):
    if frame is None:
        return []
    if isinstance(frame, dict):
        data = frame.get("data", frame)
        if isinstance(data, dict) and "fields" in data and "items" in data:
            return [dict(zip(data.get("fields") or [], item)) for item in data.get("items") or []]
        if isinstance(data, list):
            return data
        return [data]
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    return frame if isinstance(frame, list) else []


def _normalize_ts_code(value):
    value = str(_json_safe(value) or "").strip().upper()
    if value.endswith((".SZ", ".SH")):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 6:
        suffix = ".SH" if digits.startswith(("5", "6", "9")) else ".SZ"
        return f"{digits}{suffix}"
    return value or None


def _call_tushare_api(api, api_name, params):
    result = api.query(api_name, **params) if hasattr(api, "query") else getattr(api, api_name)(**params)
    if result is None:
        raise RuntimeError("Tushare returned no data object")
    if isinstance(result, dict):
        code = result.get("code")
        if code not in (None, 0, "0"):
            raise RuntimeError(f"Tushare returned code={code} msg={result.get('msg')}")
    return result


def fetch_bulk_factors(api, start_date, end_date):
    LAST_FACTOR_ERRORS.clear()
    params = {"start_date": start_date, "end_date": end_date}
    for api_name in FACTOR_ENDPOINTS:
        try:
            print(f"quant_factors: trying {api_name} start_date={start_date} end_date={end_date}", file=sys.stderr)
            rows = _frame_to_rows(_call_tushare_api(api, api_name, params))
            print(f"quant_factors: {api_name} ok rows={len(rows)}", file=sys.stderr)
            return api_name, rows
        except Exception as exc:
            LAST_FACTOR_ERRORS.append(f"{api_name}: {type(exc).__name__}: {exc}")
            print(f"quant_factors: {api_name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            time.sleep(0.2)
    return None, []


def _looks_tier_locked(error_text):
    return any(cue in (error_text or "").lower() for cue in TIER_LOCK_CUES)


def _attempted_endpoints(api_used=None):
    if not api_used:
        return list(FACTOR_ENDPOINTS)
    return list(FACTOR_ENDPOINTS[: FACTOR_ENDPOINTS.index(api_used) + 1])


def _group_by_ts_code(rows):
    grouped = defaultdict(list)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        safe = {str(key): _json_safe(value) for key, value in raw.items()}
        ts_code = _normalize_ts_code(safe.get("ts_code") or safe.get("code") or safe.get("symbol"))
        if ts_code:
            grouped[ts_code].append(safe)
    return grouped


def _extract_factors(row):
    """Pull all numeric factor columns from a row, excluding identifier columns."""
    factors = {}
    for key, value in row.items():
        if key in ID_COLUMNS:
            continue
        numeric = _to_float(value)
        if numeric is not None:
            factors[key] = numeric
    return factors


def _build_history(rows):
    """Sort rows by trade_date desc, return list of {trade_date, ...numeric cols}."""
    history = []
    for row in rows:
        trade_date = _json_safe(row.get("trade_date") or row.get("date"))
        entry = {"trade_date": trade_date}
        for key, value in row.items():
            if key in ID_COLUMNS:
                continue
            numeric = _to_float(value)
            if numeric is not None:
                entry[key] = numeric
        history.append(entry)
    return sorted(history, key=lambda r: r.get("trade_date") or "", reverse=True)


def _base_payload(ticker, trade_date, status, api_used=None):
    return {
        "ticker": ticker,
        "fetched_at": _iso_now(),
        "trade_date": trade_date,
        "tier": CURRENT_TIER,
        "_status": status,
        "api_used": api_used,
        "_attempted_endpoints": _attempted_endpoints(api_used) if api_used else [],
        "days_window": WINDOW_DAYS,
        "factors": {},
        "history": [],
        "_factor_count": 0,
    }


def _payload_for_ticker(ticker, trade_date, api_used, grouped, bulk_status, bulk_error):
    if not _is_a_share(ticker):
        payload = _base_payload(ticker, trade_date, "skipped")
        payload["_reason"] = "not_available_tushare_hk_us"
        return payload
    if bulk_status != "ok":
        payload = _base_payload(ticker, trade_date, bulk_status)
        payload["_attempted_endpoints"] = _attempted_endpoints()
        if bulk_status == "tier_locked":
            payload["_need_tier"] = CURRENT_TIER
        if bulk_error:
            payload["_error"] = bulk_error
        return payload
    rows = grouped.get(ticker, [])
    history = _build_history(rows)
    factors = _extract_factors(rows[0]) if rows else {}
    if rows:
        # Pick the row with the latest trade_date for `factors`
        latest = max(rows, key=lambda r: _json_safe(r.get("trade_date") or r.get("date")) or "")
        factors = _extract_factors(latest)
    payload = _base_payload(ticker, trade_date, "ok", api_used=api_used)
    payload["factors"] = factors
    payload["history"] = history
    payload["_factor_count"] = len(factors)
    return payload


def _failed_payload(ticker, trade_date, exc):
    payload = _base_payload(ticker, trade_date, "fetch_failed")
    payload["_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("ERROR: TUSHARE_TOKEN is required for scripts/fetch_quant_factors.py", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = _beijing_today_str()
    start_date = _start_date_n_days_ago(WINDOW_DAYS)
    watchlist = _load_watchlist()

    api_used, grouped, bulk_status, bulk_error = None, {}, "ok", None
    if any(_is_a_share(ticker) for ticker in watchlist):
        api_used, rows = fetch_bulk_factors(ts.pro_api(token), start_date, trade_date)
        if api_used:
            grouped = _group_by_ts_code(rows)
        else:
            bulk_error = " | ".join(LAST_FACTOR_ERRORS)
            bulk_status = "tier_locked" if _looks_tier_locked(bulk_error) else "endpoint_unavailable"

    counts = {"ok": 0, "skipped": 0, "failed": 0, "empty": 0}
    for idx, ticker in enumerate(watchlist, 1):
        output_path = OUTPUT_DIR / f"{ticker}.json"
        try:
            payload = _payload_for_ticker(ticker, trade_date, api_used, grouped, bulk_status, bulk_error)
            _write_json(output_path, payload)
            status = payload["_status"]
            if status == "skipped":
                counts["skipped"] += 1
            elif status == "ok":
                if payload["_factor_count"] == 0:
                    counts["empty"] += 1
                else:
                    counts["ok"] += 1
            else:
                counts["failed"] += 1
            print(f"[{idx}/{len(watchlist)}] wrote public/data/quant_factors/{ticker}.json "
                  f"status={status} factors={payload['_factor_count']}")
        except Exception as exc:
            print(f"quant_factors: {ticker} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                _write_json(output_path, _failed_payload(ticker, trade_date, exc))
            except Exception as write_exc:
                print(f"quant_factors: {ticker} write failed: {type(write_exc).__name__}: {write_exc}", file=sys.stderr)
            counts["failed"] += 1

    print(f"quant_factors: ok={counts['ok']} empty={counts['empty']} "
          f"skipped={counts['skipped']} failed={counts['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
